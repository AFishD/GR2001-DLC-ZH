# -*- coding: utf-8 -*-
"""bootshots.py —— 启动 ISO，按固定间隔连拍，记录开场/读盘/Loading 画面。"""
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
    ap.add_argument('--secs', type=float, default=150.0)
    ap.add_argument('--step', type=float, default=3.0)
    a = ap.parse_args()
    r = NS.Runner(Args(a.iso, a.out, a.runtime))
    r.start()
    try:
        t0 = time.time()
        i = 0
        while time.time() - t0 < a.secs:
            img = r.grab()
            if img is not None:
                r.save(img, 'boot_%03d' % i)
            i += 1
            time.sleep(a.step)
    finally:
        r.stop()


if __name__ == '__main__':
    main()
