# -*- coding: utf-8 -*-
"""capture_missionlist.py —— 战役→战役画廊→任务列表(C01..C08) 截图，并下滚到 C05-C08。"""
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


def highlight_row(img):
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
    a = ap.parse_args()
    r = NS.Runner(Args(a.iso, a.out, a.runtime))
    r.start()
    try:
        r.boot_to_mainmenu()
        r.press('space')
        time.sleep(3.0)
        for _ in range(8):
            img = r.grab()
            if highlight_row(img) == 2:
                break
            r.press('g', hold=0.03)
            time.sleep(1.4)
        r.press('space')   # 进入战役画廊
        time.sleep(2.5)
        r.settle()
        r.save(r.grab(), 'ml_gallery')
        r.press('space')   # 进入任务列表（可能先过场视频，连拍找界面帧）
        for i in range(14):
            time.sleep(0.7)
            img = r.grab()
            if img is not None:
                r.save(img, 'ml_seq_%02d' % i)
    finally:
        time.sleep(0.5)
        r.stop()


if __name__ == '__main__':
    main()
