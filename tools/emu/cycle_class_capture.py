# -*- coding: utf-8 -*-
"""cycle_class_capture.py —— 跑到小队名册后，反复按 Up/Down 切换选中队员，
每次截一张「右下姓名+兵种」区域，用于观察受控测试串的渲染结果。
"""
import argparse
import sys
import time
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'tools' / 'emu'))
import nav_squad as NS  # noqa: E402


class Args(object):
    def __init__(self, iso, out, runtime):
        self.iso = iso
        self.out = out
        self.runtime = runtime
        self.input = 'post'
        self.sweep = False
        self.diag = True
        self.mode = 'run'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--iso', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--runtime', required=True)
    ap.add_argument('--n', type=int, default=6)
    a = ap.parse_args()
    r = NS.Runner(Args(a.iso, a.out, a.runtime))
    r.start()
    try:
        brief = r.boot_to_brief()
        before = r.grab()
        changed, _ = r.wait_change(before, timeout=10)
        if not changed:
            r.advance('space', 'cc_cross1', 8)
        r.wait_for_band(0.15, 0.21, 15)
        r.settle()
        r.advance('space', 'cc_cross2', 8)
        r.settle()
        img = r.grab()
        r.save(img, 'cc_roster')
        for i in range(a.n):
            r.press('g')
            time.sleep(1.0)
            img = r.grab()
            if img is None:
                continue
            r.save(img, 'cc_sel_%02d' % i)
            w, h = img.size
            crop = img.crop((int(0.60 * w), int(0.70 * h), int(0.90 * w), int(0.86 * h)))
            crop = crop.resize((crop.size[0] * 2, crop.size[1] * 2), Image.LANCZOS)
            crop.save(str(r.out / ('cc_class_%02d.png' % i)))
            r.log('CC capture %d' % i)
    finally:
        time.sleep(0.5)
        r.stop()


if __name__ == '__main__':
    main()
