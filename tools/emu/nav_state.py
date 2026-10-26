# -*- coding: utf-8 -*-
"""nav_state.py —— 用「画面状态机」驱动 PCSX2 走到战役（不靠固定时间点穷举按键）。

思路：
  1. 启动带 DebugServer/Pine 的 PCSX2（源目录可用 --source-pcsx2 指向 PCSX2-MCP 预编译包）；
  2. 每轮用 F8 原生截图（干净的模拟器帧缓冲）→ 与参考模板做灰度缩略图 L1 距离分类；
  3. 依据当前画面状态决定按哪个键（START/Cross/Down/...），按键后重新分类；
  4. 菜单里用「黄色高亮行」检测确认选中项，逐步逼近 战役；
  5. 全程记录状态迁移；到达 MOVIE/INGAME 后继续观察是否出现 TLB Miss（崩溃）。

用法：
    python tools\\emu\\nav_state.py --iso work\\builds\\JS_ZH_v13guard.iso \\
        --memcard Mcd001.ps2 --out work\\analysis\\emu\\nav_sm --seconds 420
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import wincap  # noqa: E402
import run_smoke as RS  # noqa: E402

# 参考画面（native 1475x1106，来自既有运行证据目录）
REFS = {
    'title':    'work/analysis/emu/bootprobe/bp_native_200s.png',
    'browser':  'work/analysis/emu/startprobe2/s2_native_220s.png',
    'loading':  'work/analysis/emu/loadprobe3/l3_native_225s.png',
    'submenu':  'work/analysis/emu/campnav3/c3_native_240s.png',
    'mainmenu': 'work/analysis/emu/campnav3/c3_native_254s.png',
    'ingame':   'work/analysis/emu/loadprobe3/l3_native_278s.png',
    'movie':    'work/analysis/emu/campnav3/c3_native_270s.png',
}

VK = RS.KEY_VK
THUMB = (64, 48)


def thumb(path_or_img):
    from PIL import Image
    im = path_or_img
    if isinstance(im, (str, Path)):
        im = Image.open(str(im))
    im = im.convert('L').crop((0, 0, 1475, 1106)).resize(THUMB)
    return list(im.getdata())


def dist(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / float(len(a))


class Classifier:
    def __init__(self):
        self.refs = {}
        for name, rel in REFS.items():
            p = REPO / rel
            if p.exists():
                self.refs[name] = thumb(p)

    def classify(self, img):
        t = thumb(img)
        best, bestd = 'unknown', 1e9
        for name, ref in self.refs.items():
            d = dist(t, ref)
            if d < bestd:
                best, bestd = name, d
        # 亮度低 + 匹配差 ⇒ 片头/加载黑屏
        mean = sum(t) / float(len(t))
        if bestd > 14.0:
            return ('dark' if mean < 42 else 'unknown'), bestd
        return best, bestd


def find_yellow_row(img, win_scale):
    """在原生截图里找菜单黄色高亮行（返回行号 0..N 或 None）。"""
    px = img.convert('RGB').load()
    W, H = img.size
    xs = [int(x * win_scale) for x in (232, 300, 380)]
    ys = [int(y * win_scale) for y in range(70, 330, 4)]
    rows = []
    for y in ys:
        hit = 0
        for x in xs:
            if x >= W or y >= H:
                continue
            r, g, b = px[x, y]
            if r > 150 and g > 110 and b < 110 and r - b > 60:
                hit += 1
        rows.append((y, hit))
    runs = []
    cur = None
    for y, hit in rows:
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
    return runs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--iso', required=True)
    ap.add_argument('--memcard', default='')
    ap.add_argument('--statefile', default='')
    ap.add_argument('--out', default=str(REPO / 'work' / 'analysis' / 'emu' / 'nav_sm'))
    ap.add_argument('--runtime', default=str(REPO / 'work' / 'analysis' / 'emu' / 'runtime_mcp'))
    ap.add_argument('--source-pcsx2', default=str(RS.DEFAULT_SOURCE_PCSX2))
    ap.add_argument('--bios', default=str(RS.DEFAULT_BIOS_DIR / RS.DEFAULT_BIOS))
    ap.add_argument('--seconds', type=float, default=420.0)
    ap.add_argument('--renderer', default='dx12')
    ap.add_argument('--memcard-src', dest='memcard_src', default='')
    args = ap.parse_args(argv)

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    iso = Path(args.iso).resolve()

    source = Path(args.source_pcsx2)
    if not source.exists():
        print('ERROR: --source-pcsx2 不存在：%s' % source)
        return 2
    runtime = Path(args.runtime)
    prov = RS.provision_runtime(runtime, source, Path(args.bios), force=False)

    memcard = ''
    if args.memcard_src or args.memcard:
        src_card = Path(args.memcard_src or args.memcard)
        if src_card.exists():
            dst = runtime / 'memcards' / 'Mcd001.ps2'
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_card, dst)
            memcard = 'Mcd001.ps2'

    ini = RS.write_clean_ini(runtime, renderer=args.renderer,
                             bios_name=Path(prov['bios']).name,
                             framelimit=True, memcard=memcard, texfilter=-1)
    # 打开 Pine IPC（DebugServer 已编译进 MCP 版 pcsx2-qt.exe）
    txt = Path(ini).read_text(encoding='utf-8', errors='replace')
    if 'EnablePINE' not in txt:
        txt = txt.replace('[EmuCore]', '[EmuCore]\nEnablePINE = true\nPINESlot = 28011', 1)
        Path(ini).write_text(txt, encoding='utf-8')

    log_path = out / 'emulog.txt'
    if log_path.exists():
        log_path.unlink()
    exe = runtime / 'pcsx2-qt.exe'
    cmd = [str(exe), '-batch', '-fastboot', '-logfile', str(log_path)]
    if args.statefile:
        cmd += ['-statefile', str(Path(args.statefile).resolve())]
    cmd += ['--', str(iso)]
    console_f = open(out / 'console.txt', 'wb')
    start = time.time()
    proc = subprocess.Popen(cmd, cwd=str(runtime), stdout=console_f,
                            stderr=subprocess.STDOUT, env=dict(os.environ))
    import atexit
    atexit.register(lambda: proc.terminate() if proc.poll() is None else None)
    print('[nav] pid=%d runtime=%s' % (proc.pid, runtime))

    snap_dir = runtime / 'snaps'
    snap_dir.mkdir(parents=True, exist_ok=True)
    for old in snap_dir.glob('*.png'):
        try:
            old.unlink()
        except OSError:
            pass

    clf = Classifier()
    print('[nav] 参考模板 %d 个：%s' % (len(clf.refs), ','.join(clf.refs)))

    main_win = None
    def window():
        nonlocal main_win
        if main_win is None:
            for _ in range(20):
                w = wincap.pick_main_window(wincap.list_windows(proc.pid))
                if w:
                    main_win = w
                    return w
                time.sleep(0.5)
        return main_win

    def native(tag):
        w = window()
        if w is None:
            return None, None
        before = {p.name for p in snap_dir.glob('*.png')}
        wincap.force_focus(w.hwnd)
        time.sleep(0.35)
        wincap.click_window(w.hwnd)
        time.sleep(0.15)
        wincap.tap_key(w.hwnd, 0x77, 45)
        deadline = time.time() + 5.0
        while time.time() < deadline:
            time.sleep(0.12)
            cand = sorted(p for p in snap_dir.glob('*.png') if p.name not in before)
            if cand:
                f = cand[-1]
                dest = out / ('%s.png' % tag)
                # 等 PCSX2 写完（文件大小稳定）再搬/开，避免占用锁
                last_size = -1
                for _ in range(40):
                    try:
                        size = f.stat().st_size
                    except OSError:
                        size = -1
                    if size > 0 and size == last_size:
                        break
                    last_size = size
                    time.sleep(0.1)
                try:
                    shutil.move(str(f), str(dest))
                except OSError:
                    dest = f
                from PIL import Image
                for _ in range(20):
                    try:
                        return Image.open(str(dest)).convert('RGB'), dest
                    except (PermissionError, OSError):
                        time.sleep(0.15)
                return None, dest
        return None, None

    def tap(key):
        w = window()
        if w is None:
            return
        wincap.tap_key(w.hwnd, VK[key], hold_ms=40)

    actions = {
        'title':    ('return', '标题画面 → START'),
        'browser':  ('space', '存档浏览 → Cross(载入)'),
        'loading':  ('space', '读取对话框 → Cross'),
        'mainmenu': ('space', '主菜单 → Cross(单人游戏)'),
        'submenu':  ('g', '单人游戏子菜单 → Down(G)'),
        'dark':     ('return', '片头/黑屏 → START 跳过'),
        'unknown':  ('space', '未知画面 → Cross 试探'),
    }
    # 单人游戏子菜单行位（native y 顶）→ 行号：训练0 / 战术演习1 / 战役2 / 快速任务3
    SUBMENU_TOP = 244.0
    SUBMENU_PITCH = 69.0
    state_log = []
    last_state = None
    last_act = 0.0
    armed = False   # 未见到标题画面前不按键（片头期间按键会触发引擎崩溃）
    deadline = start + float(args.seconds)
    ended_reason = 'timeout'
    while time.time() < deadline:
        if proc.poll() is not None:
            ended_reason = 'emulator_exited'
            break
        img, path = native('nav_%05.1f' % (time.time() - start))
        if img is None:
            time.sleep(0.5)
            continue
        state, d = clf.classify(img)
        rows = find_yellow_row(img, 1475 / 640.0)
        state_log.append(dict(t=round(time.time() - start, 1), state=state, dist=round(d, 1),
                              rows=rows, file=str(path)))
        print('[nav] t=%.1f state=%s d=%.1f rows=%s' % (time.time() - start, state, d, rows),
              flush=True)
        if not armed:
            if state == 'title':
                armed = True
                print('[nav]   已到标题画面，开始导航', flush=True)
            elif state == 'dark':
                # 片头动画：连点 Start 跳过（省时间）；只在确实黑屏/片头时按
                print('[nav]   片头 → START 跳过', flush=True)
                tap('return')
                time.sleep(2.0)
            else:
                time.sleep(1.5)
            continue
        if state == 'ingame' and last_state in ('movie', 'loading', 'unknown'):
            ended_reason = 'reached_game'
            break
        if state == 'submenu':
            # 子菜单：训练(0)/战术演习(1)/战役(2)/快速任务(3)，按高亮行号决定下一步
            idx = None
            if rows:
                top = min(r[0] for r in rows)
                idx = int(round((top - SUBMENU_TOP) / SUBMENU_PITCH))
            if idx is not None and idx >= 2:
                tap('space')
                time.sleep(2.5)
            else:
                tap('g')
                time.sleep(1.2)
            last_state = state
            continue
        if state == 'movie':
            # 片头播放中：等待（崩溃观察期）
            last_state = state
            time.sleep(6.0)
            continue
        if time.time() - last_act < 1.5:
            time.sleep(0.8)
            continue
        key, why = actions.get(state, actions['unknown'])
        print('[nav]   → %s (%s)' % (key, why))
        tap(key)
        last_act = time.time()
        last_state = state
        time.sleep(1.6)

    import json
    (out / 'nav_log.json').write_text(json.dumps(state_log, ensure_ascii=False, indent=1),
                                      encoding='utf-8')
    try:
        proc.terminate()
        proc.wait(timeout=20)
    except Exception:
        proc.kill()
    print('[nav] 结束：%s，状态迁移 %d 条，日志 %s' % (ended_reason, len(state_log), out / 'nav_log.json'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
