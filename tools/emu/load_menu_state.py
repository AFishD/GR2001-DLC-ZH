# -*- coding: utf-8 -*-
"""load_menu_state.py —— 启动游戏 → F3 载入指定即时存档（已改行索引）→ 截图并检测高亮行；
若到达目标行则按 Cross 进入并截图。"""
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
    ap.add_argument('--expect-row', type=int, required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--enter', action='store_true')
    a = ap.parse_args()
    r = NS.Runner(Args(a.iso, a.out, a.runtime))
    r.start()
    try:
        r.boot_to_mainmenu()
        r.press('f3')
        time.sleep(4.0)
        img = r.grab()
        row, counts = hrow(img)
        r.log('expect row=%d got row=%d counts=%s' % (a.expect_row, row, counts))
        r.save(img, '%s_loaded' % a.tag)
        if row == a.expect_row and a.enter:
            r.press('space')
            time.sleep(2.5)
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
