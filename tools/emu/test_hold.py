# -*- coding: utf-8 -*-
"""test_hold.py —— 测试不同 hold 时长下单人菜单一次按键移动几行。"""
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


def hrow(img):
    a = np.asarray(img.convert('RGB')).astype(int)
    counts = []
    for (gy0, gy1) in ROW_Y:
        x0, x1 = int(XS + 180 * SX), int(XS + 470 * SX)
        y0, y1 = int(gy0 * SY), int(gy1 * SY)
        sub = a[y0:y1, x0:x1]
        r, g, b = sub[:, :, 0], sub[:, :, 1], sub[:, :, 2]
        counts.append(int(((r > 120) & (g > 85) & (b < 80)).sum()))
    return int(np.argmax(counts)), counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--iso', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--runtime', required=True)
    a = ap.parse_args()
    r = NS.Runner(Args(a.iso, a.out, a.runtime))
    r.start()
    try:
        r.boot_to_mainmenu()
        r.press('space')
        time.sleep(3.0)
        for hold in (0.004, 0.008, 0.012, 0.016, 0.020, 0.030):
            img = r.grab()
            cur, _ = hrow(img)
            r.press('g', hold=hold)
            time.sleep(1.2)
            img2 = r.grab()
            nxt, _ = hrow(img2)
            r.log('hold=%.3f  %d -> %d' % (hold, cur, nxt))
            r.save(img2, 'hold_%03d' % int(hold * 1000))
    finally:
        time.sleep(0.5)
        r.stop()


if __name__ == '__main__':
    main()
