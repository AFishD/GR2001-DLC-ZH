# -*- coding: utf-8 -*-
"""capture_at_row2.py —— 用「黄色高亮行检测 + 反馈」稳定进入单人菜单第 N 行（0=训练,1=战术演习,2=战役,3=快速任务）。"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'tools' / 'emu'))
import nav_squad as NS  # noqa: E402

XS, XE = 312, 1786
SX = (XE - XS) / 640.0
SY = 1106 / 448.0
# 四行的高亮条 game y 范围（实测：训练/战术/战役/快速）
ROW_Y = [(96, 111), (124, 139), (152, 167), (180, 195)]


class Args(object):
    def __init__(self, iso, out, runtime):
        self.iso = iso
        self.out = out
        self.runtime = runtime
        self.input = 'post'
        self.sweep = False
        self.diag = True
        self.mode = 'run'


def highlight_row(img):
    a = np.asarray(img.convert('RGB')).astype(int)
    counts = []
    for (gy0, gy1) in ROW_Y:
        x0, x1 = int(XS + 180 * SX), int(XS + 470 * SX)
        y0, y1 = int(gy0 * SY), int(gy1 * SY)
        sub = a[y0:y1, x0:x1]
        r, g, b = sub[:, :, 0], sub[:, :, 1], sub[:, :, 2]
        yellow = (r > 120) & (g > 85) & (b < 80)
        counts.append(int(yellow.sum()))
    best = int(np.argmax(counts))
    return best, counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--iso', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--runtime', required=True)
    ap.add_argument('--row', type=int, required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--extra-cross', type=int, default=0, help='进入后再按几次 Cross（如战役→任务列表）')
    a = ap.parse_args()
    r = NS.Runner(Args(a.iso, a.out, a.runtime))
    r.start()
    try:
        r.boot_to_mainmenu()
        r.press('space')
        time.sleep(3.0)
        for step in range(12):
            img = r.grab()
            cur, counts = highlight_row(img)
            r.log('row=%d counts=%s target=%d' % (cur, counts, a.row))
            if cur == a.row:
                r.save(img, '%s_menu' % a.tag)
                break
            # 一次按键实测约移动 2 行：按方向 + 反馈修正
            key = 'g' if a.row > cur else 't'
            r.press(key, hold=0.03)
            time.sleep(1.4)
        r.press('space')
        time.sleep(2.5)
        r.settle()
        for k in range(a.extra_cross):
            r.press('space')
            time.sleep(2.0)
            r.settle()
        r.save(r.grab(), '%s_00' % a.tag)
        for k in range(6):
            r.press('g', hold=0.02)
            time.sleep(0.7)
        r.settle()
        r.save(r.grab(), '%s_p2' % a.tag)
    finally:
        time.sleep(0.5)
        r.stop()


if __name__ == '__main__':
    main()
