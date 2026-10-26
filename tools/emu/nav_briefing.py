# -*- coding: utf-8 -*-
"""nav_briefing.py —— 导航到战役 C01「简介」页并截图（实测可用路径）。

实测路径（在 v21/v22/英文原盘/3 个锚点探针盘上各跑通）：
    开机 → 主菜单 → 单人游戏主菜单 → 战役画廊（ISLAND THUNDER）→ 任务过场 FMV → 简介页
开机时间差异用「主菜单画面判定」吸收；主菜单/简介页用画面特征判定，中间菜单层级按经验等待推进。
详见 docs/NAV_CLOSED_LOOP.md。

用法：python tools\\emu\\nav_briefing.py --iso <iso> --out work\\analysis\\emu\\navauto
"""
import argparse
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / 'tools' / 'emu'))
import wincap  # noqa
import run_smoke as RS  # noqa

user32 = ctypes.WinDLL('user32', use_last_error=True)
EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def children(hwnd):
    out = []

    def cb(h, _lp):
        out.append(h)
        return True

    user32.EnumChildWindows(hwnd, EnumChildProc(cb), 0)
    return out


def biggest_child(hwnd):
    best, best_area = None, 0
    for h in children(hwnd):
        r = wintypes.RECT()
        if not user32.GetClientRect(h, ctypes.byref(r)):
            continue
        a = (r.right - r.left) * (r.bottom - r.top)
        if a > best_area:
            best, best_area = h, a
    return best, best_area


def sig(img, size=(64, 48)):
    return np.asarray(img.convert('L').resize(size), dtype=np.float32) / 255.0


def dist(a, b):
    return float(np.abs(a - b).mean())


def ymask(img):
    a = np.asarray(img.convert('RGB'), dtype=np.int16)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    return (r > 170) & (g > 140) & (b < 110)


def yellow_count(img):
    return int(ymask(img).sum())


def bar_y_norm(img):
    m = ymask(img)
    h, w = m.shape
    sub = m[int(h * 0.15):int(h * 0.95), int(w * 0.18):int(w * 0.62)]
    ys, xs = np.nonzero(sub)
    if len(ys) < 300:
        return None
    return float(ys.mean()) / (h * 0.8)


def main(argv=None):
    ap = argparse.ArgumentParser(description='导航到战役 C01 简介页并截图（实测路径：主菜单→单人菜单→战役画廊→FMV→简介）')
    ap.add_argument('--iso', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--runtime', default=str(Path(__file__).resolve().parent.parent.parent / 'work' / 'emu_runtime'))
    a = ap.parse_args(argv)
    iso = Path(a.iso).resolve()
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    refdir = REPO / 'work' / 'analysis' / 'emu' / 'refs'
    ref = sig(Image.open(refdir / 'mainmenu.png'))

    prov = RS.provision_runtime(Path(a.runtime), Path(RS.DEFAULT_SOURCE_PCSX2),
                                Path(RS.DEFAULT_BIOS_DIR / RS.DEFAULT_BIOS), force=False)
    memcard = ''
    mc = REPO / 'reference' / 'Mcd001.ps2'
    if mc.exists():
        dst = REPO / 'work' / 'emu_runtime' / 'memcards' / 'Mcd001.ps2'
        dst.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(mc, dst)
        memcard = 'Mcd001.ps2'
    RS.write_clean_ini(Path(a.runtime), renderer='dx12',
                       bios_name=Path(prov['bios']).name, framelimit=True,
                       memcard=memcard, texfilter=-1)
    exe = Path(a.runtime) / 'pcsx2-qt.exe'
    proc = subprocess.Popen([str(exe), '-batch', '-fastboot', '-logfile', str(out / 'emulog.txt'),
                             '--', str(iso)], cwd=str(REPO / 'work' / 'emu_runtime'),
                            stdout=open(out / 'console.txt', 'wb'), stderr=subprocess.STDOUT)
    print('pid', proc.pid, flush=True)
    mw = None
    rw = None
    t0 = time.time()
    n = 0

    def windows():
        nonlocal mw, rw
        if mw is None:
            for _ in range(60):
                w = wincap.pick_main_window(wincap.list_windows(proc.pid))
                if w:
                    mw = w
                    break
                time.sleep(0.5)
        if mw is not None and rw is None:
            ch, a = biggest_child(mw.hwnd)
            if ch and a > 10000:
                rw = ch
        return mw, rw

    def grab():
        windows()
        if mw is None:
            return None
        return wincap.capture_window(rw or mw.hwnd, mode=2)

    def post(key):
        windows()
        if mw is None:
            return
        wincap.post_key(mw.hwnd, RS.KEY_VK[key], keyup=False)
        time.sleep(0.05)
        wincap.post_key(mw.hwnd, RS.KEY_VK[key], keyup=True)

    def save(img, tag):
        nonlocal n
        n += 1
        img.save(str(out / ('%03d_%s.png' % (n, tag))))

    # ① 开机 → 主菜单
    last_key = 0.0
    while time.time() - t0 < 400:
        img = grab()
        if img is None:
            time.sleep(0.8); continue
        t = time.time() - t0
        if dist(sig(img), ref) < 0.10 and yellow_count(img) > 8000:
            save(img, 'mainmenu')
            print('[t=%.1f] mainmenu' % t, flush=True)
            break
        if t - last_key >= 1.2:
            post('space' if int(t / 1.2) % 2 == 0 else 'return')
            last_key = t
        time.sleep(0.6)
    # ② 进单人菜单
    post('space'); time.sleep(3.2)
    img = grab(); save(img, 'sp_menu')
    print('sp bar', bar_y_norm(img), flush=True)
    # ③ 闭环到战役（row2，bar≈0.278）
    for i in range(5):
        cur = bar_y_norm(grab())
        if cur is not None and cur >= 0.25:
            break
        post('t'); time.sleep(1.3)
        print('down ->', bar_y_norm(grab()), flush=True)
    img = grab(); save(img, 'row_campaign')
    print('final bar', bar_y_norm(img), flush=True)
    # ④ 进战役画廊
    post('space'); time.sleep(3.5)
    img = grab(); save(img, 'campaign_gallery')
    print('gallery yellow', yellow_count(img), flush=True)
    # ⑤ 默认 ISLAND THUNDER，直接 Cross 进任务列表
    post('space'); time.sleep(4.0)
    img = grab(); save(img, 'mission_list')
    print('list yellow', yellow_count(img), flush=True)
    # ⑥ 第一项 C01 → Cross 打开简介页
    post('space')
    tt = time.time(); k = 0
    while time.time() - tt < 50:
        img = grab()
        if img is not None:
            k += 1
            save(img, 'brief_%02d' % k)
            print('brief', k, 'yellow', yellow_count(img), flush=True)
        time.sleep(1.0)
    proc.terminate()
    print('done frames', n, flush=True)


if __name__ == '__main__':
    main()
