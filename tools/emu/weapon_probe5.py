# -*- coding: utf-8 -*-
"""weapon_probe5.py —— 干净路径：简报→小队设置→自动分配→选人→R1/L1 反复，逐帧保存。"""
import argparse
import sys
import time
from pathlib import Path

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
    a = ap.parse_args()
    r = NS.Runner(Args(a.iso, a.out, a.runtime))
    r.start()
    try:
        brief = r.boot_to_brief()
        r.save(brief, 'w5_brief')
        before = r.grab()
        changed, _ = r.wait_change(before, timeout=10)
        if not changed:
            r.advance('space', 'w5_cross1', 8)
        r.wait_for_band(0.15, 0.21, 15)
        r.settle()
        r.advance('space', 'w5_cross2', 8)
        r.settle()
        r.save(r.grab(), 'w5_auto')
        r.press('t')
        time.sleep(1.2)
        base = r.grab()
        r.save(base, 'w5_selected')
        prev = base
        for i, k in enumerate(['e', 'e', 'q', 'q', 'e']):
            r.press(k, hold=0.15)
            time.sleep(1.2)
            img = r.grab()
            if img is None:
                continue
            d = NS.bigdiff(prev, img)
            r.save(img, 'w5_step%d_%s_d%04d' % (i, k, int(d * 10)))
            r.log('W5 step%d key=%s diff=%5.2f' % (i, k, d))
            prev = img
        # R1 之后按 Circle 看是否打开武器信息
        r.press('s')
        time.sleep(1.5)
        img = r.grab()
        if img is not None:
            r.save(img, 'w5_after_r1_circle')
    finally:
        time.sleep(0.5)
        r.stop()


if __name__ == '__main__':
    main()
