# -*- coding: utf-8 -*-
"""capture_hint_frames.py —— 跑到小队名册后连拍 N 帧，保存底部提示条裁图，用于判定交替/滚动。"""
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
    ap.add_argument('--n', type=int, default=24)
    ap.add_argument('--gap', type=float, default=0.25)
    a = ap.parse_args()
    r = NS.Runner(Args(a.iso, a.out, a.runtime))
    r.start()
    try:
        brief = r.boot_to_brief()
        r.save(brief, 'hf_brief')
        before = r.grab()
        changed, _ = r.wait_change(before, timeout=10)
        if not changed:
            r.advance('space', 'hf_cross1', 8)
        r.wait_for_band(0.15, 0.21, 15)
        r.settle()
        r.advance('space', 'hf_cross2', 8)
        r.settle()
        r.save(r.grab(), 'hf_roster')
        r.press('t')   # 选中队员（Circle 提示变为 队员信息）
        time.sleep(1.5)
        w = h = None
        for i in range(a.n):
            img = r.grab()
            if img is None:
                continue
            if w is None:
                w, h = img.size
            r.save(img, 'hf_full_%02d' % i)
            band = img.crop((int(0.10 * w), int(0.86 * h), int(0.95 * w), int(0.97 * h)))
            band.save(str(r.out / ('hf_hint_%02d.png' % i)))
            time.sleep(a.gap)
        r.log('hint burst done')
    finally:
        time.sleep(0.5)
        r.stop()


if __name__ == '__main__':
    main()
