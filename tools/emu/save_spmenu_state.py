# -*- coding: utf-8 -*-
"""save_spmenu_state.py —— 进入单人菜单，停在指定行（0 或 2），按 F1 存即时存档。"""
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
    return int(np.argmax(counts))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--iso', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--runtime', required=True)
    ap.add_argument('--row', type=int, default=0)
    a = ap.parse_args()
    r = NS.Runner(Args(a.iso, a.out, a.runtime))
    r.start()
    try:
        r.boot_to_mainmenu()
        r.press('space')
        time.sleep(3.0)
        for _ in range(8):
            img = r.grab()
            cur = hrow(img)
            r.log('row=%d target=%d' % (cur, a.row))
            if cur == a.row:
                break
            r.press('g' if a.row > cur else 't', hold=0.03)
            time.sleep(1.3)
        r.save(r.grab(), 'state_row%d' % a.row)
        r.press('f1')
        time.sleep(4.0)
        r.log('F1 pressed for row %d' % a.row)
    finally:
        time.sleep(0.8)
        r.stop()
        for p in sorted((Path(a.runtime) / 'sstates').glob('*.p2s')):
            print('SAVESTATE', p)


if __name__ == '__main__':
    main()
