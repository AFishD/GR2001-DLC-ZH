# -*- coding: utf-8 -*-
"""step_spmenu.py —— 从主菜单进入单人菜单后，连续短按 Down 6 次，每次截图，用于确认实际移动行数。"""
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
    ap.add_argument('--key', default='g')
    a = ap.parse_args()
    r = NS.Runner(Args(a.iso, a.out, a.runtime))
    r.start()
    try:
        r.boot_to_mainmenu()
        r.press('space')
        time.sleep(3.0)
        r.save(r.grab(), 'sp_00')
        for i in range(1, 7):
            r.press(a.key, hold=0.005)
            time.sleep(1.0)
            r.save(r.grab(), 'sp_%02d' % i)
    finally:
        time.sleep(0.5)
        r.stop()


if __name__ == '__main__':
    main()
