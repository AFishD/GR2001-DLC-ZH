# -*- coding: utf-8 -*-
"""nav_post.py —— 不打扰外部程序的导航：只用 PostMessage 发键 + PrintWindow 抓帧。

与 nav_state.py 的区别：
  * **不使用 SendInput**（那会把按键发给前台窗口/影响模拟器之外的程序）；
    改用 PostMessage(hwnd, WM_KEYDOWN/WM_KEYUP)，只投递给模拟器窗口。
  * **不抢焦点**：截图用 PrintWindow 抓模拟器的渲染子窗口（游戏画面），
    不触发 F8、不切前台。
  * 片头动画阶段连点 Start 跳过，见到标题画面后进入状态机导航。

用法：
    python tools\\emu\\nav_post.py --iso <abs iso> --memcard-src Mcd001.ps2 \\
        --out work\\analysis\\emu\\nav_post1 --seconds 300
"""
import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import wincap  # noqa: E402
import run_smoke as RS  # noqa: E402

user32 = ctypes.WinDLL('user32', use_last_error=True)
EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

REFS = {
    'title':    'work/analysis/emu/bootprobe/bp_native_200s.png',
    'browser':  'work/analysis/emu/startprobe2/s2_native_220s.png',
    'loading':  'work/analysis/emu/loadprobe3/l3_native_225s.png',
    'submenu':  'work/analysis/emu/campnav3/c3_native_240s.png',
    'mainmenu': 'work/analysis/emu/campnav3/c3_native_254s.png',
    'ingame':   'work/analysis/emu/loadprobe3/l3_native_278s.png',
    'movie':    'work/analysis/emu/campnav3/c3_native_270s.png',
}
THUMB = (64, 48)


def children(hwnd):
    out = []

    def cb(h, _lp):
        out.append(h)
        return True

    user32.EnumChildWindows(hwnd, EnumChildProc(cb), 0)
    return out


def biggest_child(hwnd):
    best = None
    best_area = 0
    for h in children(hwnd):
        r = wintypes.RECT()
        if not user32.GetClientRect(h, ctypes.byref(r)):
            continue
        a = (r.right - r.left) * (r.bottom - r.top)
        if a > best_area:
            best_area, best = a, h
    return best, best_area


def crop43(img):
    w, h = img.size
    target = 4.0 / 3.0
    if w / float(h) > target:
        nw = int(round(h * target))
        x = (w - nw) // 2
        return img.crop((x, 0, x + nw, h))
    nh = int(round(w / target))
    y = (h - nh) // 2
    return img.crop((0, y, w, y + nh))


def thumb(img):
    im = crop43(img).convert('L').resize(THUMB)
    return list(im.getdata())


def dist(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / float(len(a))


class Classifier:
    def __init__(self):
        from PIL import Image
        self.refs = {}
        for name, rel in REFS.items():
            p = REPO / rel
            if p.exists():
                self.refs[name] = thumb(Image.open(str(p)))

    def classify(self, img):
        t = thumb(img)
        best, bestd = 'unknown', 1e9
        for name, ref in self.refs.items():
            d = dist(t, ref)
            if d < bestd:
                best, bestd = name, d
        mean = sum(t) / float(len(t))
        if bestd > 14.0:
            return ('dark' if mean < 42 else 'unknown'), bestd
        return best, bestd


def yellow_rows(img):
    """在 4:3 画面里找菜单高亮行（返回 native(1475x1106) 坐标系下的 y 顶）。"""
    im = crop43(img).resize((1475, 1106)).convert('RGB')
    px = im.load()
    runs = []
    cur = None
    for y in range(140, 800, 4):
        hit = 0
        for x in (520, 640, 760, 880):
            r, g, b = px[x, y]
            if r > 150 and g > 110 and b < 110 and r - b > 60:
                hit += 1
        if hit >= 2:
            if cur is None:
                cur = [y, y]
            else:
                cur[1] = y
        else:
            if cur is not None:
                runs.append(tuple(cur))
                cur = None
    if cur:
        runs.append(tuple(cur))
    # 只保留有厚度的高亮条（单像素行是抗锯齿/边框噪声）
    return [r for r in runs if (r[1] - r[0]) >= 8]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--iso', required=True)
    ap.add_argument('--memcard-src', dest='memcard_src', default='')
    ap.add_argument('--out', default=str(REPO / 'work' / 'analysis' / 'emu' / 'nav_post'))
    ap.add_argument('--runtime', default=str(REPO / 'work' / 'analysis' / 'emu' / 'runtime_post'))
    ap.add_argument('--source-pcsx2', default=str(RS.DEFAULT_SOURCE_PCSX2))
    ap.add_argument('--bios', default=str(RS.DEFAULT_BIOS_DIR / RS.DEFAULT_BIOS))
    ap.add_argument('--seconds', type=float, default=300.0)
    ap.add_argument('--renderer', default='dx12')
    ap.add_argument('--statefile', default='')
    ap.add_argument('--submenu-row', type=int, default=2,
                    help='单人子菜单目标行：0=训练 1=战术演习 2=战役 3=快速任务')
    ap.add_argument('--save-state-at', type=float, default=0.0,
                    help='到达该秒数后按一次 F1（PostMessage）保存即时存档')
    args = ap.parse_args(argv)

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    iso = Path(args.iso).resolve()

    prov = RS.provision_runtime(Path(args.runtime), Path(args.source_pcsx2),
                                Path(args.bios), force=False)
    memcard = ''
    if args.memcard_src and Path(args.memcard_src).exists():
        dst = Path(args.runtime) / 'memcards' / 'Mcd001.ps2'
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.memcard_src, dst)
        memcard = 'Mcd001.ps2'
    ini = RS.write_clean_ini(Path(args.runtime), renderer=args.renderer,
                             bios_name=Path(prov['bios']).name,
                             framelimit=True, memcard=memcard, texfilter=-1)

    log_path = out / 'emulog.txt'
    if log_path.exists():
        log_path.unlink()
    exe = Path(args.runtime) / 'pcsx2-qt.exe'
    cmd = [str(exe), '-batch', '-fastboot', '-logfile', str(log_path)]
    if args.statefile:
        cmd += ['-statefile', str(Path(args.statefile).resolve())]
    cmd += ['--', str(iso)]
    console_f = open(out / 'console.txt', 'wb')
    start = time.time()
    proc = subprocess.Popen(cmd, cwd=str(args.runtime), stdout=console_f,
                            stderr=subprocess.STDOUT, env=dict(os.environ))
    import atexit
    atexit.register(lambda: proc.terminate() if proc.poll() is None else None)
    print('[navp] pid=%d iso=%s' % (proc.pid, iso.name), flush=True)

    clf = Classifier()
    main_win = None
    render_win = None

    def windows():
        nonlocal main_win, render_win
        if main_win is None:
            for _ in range(40):
                w = wincap.pick_main_window(wincap.list_windows(proc.pid))
                if w:
                    main_win = w
                    break
                time.sleep(0.5)
        if main_win is not None and render_win is None:
            ch, area = biggest_child(main_win.hwnd)
            if ch and area > 100 * 100:
                render_win = ch
        return main_win, render_win

    def grab(tag=None):
        mw, rw = windows()
        if mw is None:
            return None
        target = rw or mw.hwnd
        img = wincap.capture_window(target, mode=2)
        if img is None:
            return None
        if tag:
            img.save(str(out / ('%s.png' % tag)))
        return img

    def post(key):
        mw, _ = windows()
        if mw is None:
            return
        wincap.post_key(mw.hwnd, RS.KEY_VK[key], keyup=False)
        time.sleep(0.05)
        wincap.post_key(mw.hwnd, RS.KEY_VK[key], keyup=True)

    state_log = []
    armed = False
    last_act = 0.0
    deadline = start + float(args.seconds)
    ended = 'timeout'
    saved = False
    seq = 0
    last_sig = None
    while time.time() < deadline:
        if proc.poll() is not None:
            ended = 'emulator_exited'
            break
        img = grab()
        if img is None:
            time.sleep(0.5)
            continue
        seq += 1
        if seq % 6 == 1:
            try:
                img.save(str(out / ('seq_%04d.png' % seq)))
            except OSError:
                pass
        sig = thumb(img)[:200]
        if last_sig is not None and sig == last_sig:
            pass
        last_sig = sig
        state, d = clf.classify(img)
        rows = yellow_rows(img)
        t = round(time.time() - start, 1)
        state_log.append(dict(t=t, state=state, dist=round(d, 1), rows=rows))
        print('[navp] t=%.1f state=%s d=%.1f rows=%s' % (t, state, d, rows), flush=True)
        if args.save_state_at and not saved and t >= args.save_state_at:
            post('f1')
            saved = True
            print('[navp]   → F1 存档', flush=True)
        # 崩溃感知：emulog 出现 TLB Miss 后立刻 F1 存档（便于事后取 RAM 现场）
        if not saved:
            try:
                txt = log_path.read_text(encoding='utf-8', errors='replace')
                if 'TLB Miss' in txt:
                    post('f1')
                    saved = True
                    print('[navp]   → 检测到 TLB Miss，F1 存档现场', flush=True)
            except OSError:
                pass
        if not armed:
            if state == 'title':
                armed = True
                print('[navp]   标题画面：开始导航', flush=True)
            elif state == 'dark':
                post('return')
                time.sleep(1.8)
            else:
                time.sleep(1.2)
            continue
        if state == 'movie':
            time.sleep(5.0)
            continue
        if state == 'submenu':
            idx = None
            if rows:
                top = max(rows, key=lambda r: r[1] - r[0])[0]
                idx = int(round((top - 244.0) / 69.0))
            target = int(getattr(args, 'submenu_row', 2))
            if idx is not None and idx == target:
                post('space')
                time.sleep(2.0)
            elif idx is not None and idx < target:
                post('g')
                time.sleep(1.0)
            elif idx is not None and idx > target:
                post('t')
                time.sleep(1.0)
            else:
                post('space')
                time.sleep(1.2)
            continue
        if time.time() - last_act < 1.2:
            time.sleep(0.6)
            continue
        key = {'title': 'return', 'browser': 'space', 'loading': 'space',
               'mainmenu': 'space', 'unknown': 'space'}.get(state, 'space')
        print('[navp]   → %s' % key, flush=True)
        post(key)
        last_act = time.time()
        time.sleep(1.4)

    import json
    (out / 'nav_log.json').write_text(json.dumps(state_log, ensure_ascii=False, indent=1),
                                      encoding='utf-8')
    try:
        proc.terminate()
        proc.wait(timeout=20)
    except Exception:
        proc.kill()
    print('[navp] 结束：%s（%d 条状态）' % (ended, len(state_log)), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
