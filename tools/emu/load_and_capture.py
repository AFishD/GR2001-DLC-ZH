# -*- coding: utf-8 -*-
"""load_and_capture.py —— 启动游戏→F3 载入指定即时存档→截几张图（用于验证改内存后的效果）。"""
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
    ap.add_argument('--n', type=int, default=4)
    a = ap.parse_args()
    r = NS.Runner(Args(a.iso, a.out, a.runtime))
    r.start()
    try:
        r.boot_to_mainmenu()
        r.press('f3')
        time.sleep(4.0)
        for i in range(a.n):
            r.save(r.grab(), 'loaded_%02d' % i)
            time.sleep(1.0)
    finally:
        time.sleep(0.5)
        r.stop()


if __name__ == '__main__':
    main()
