# -*- coding: utf-8 -*-
"""capture_msg_state.py —— 进入训练关，等提示消息出现后按 F1 存即时存档（用于逆向提示框控件）。"""
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
    ap.add_argument('--downs', type=int, default=0)
    ap.add_argument('--wait', type=float, default=12.0)
    a = ap.parse_args()
    r = NS.Runner(Args(a.iso, a.out, a.runtime))
    r.start()
    try:
        r.boot_to_mainmenu()
        r.press('space')
        time.sleep(3.0)
        r.press('space')
        time.sleep(2.5)
        for _ in range(a.downs):
            r.press('g', hold=0.02)
            time.sleep(0.8)
        r.press('space')
        time.sleep(a.wait)
        r.save(r.grab(), 'msg_before_save')
        r.press('f1')
        time.sleep(4.0)
        r.log('F1 saved at message')
    finally:
        time.sleep(0.8)
        r.stop()
        for p in sorted((Path(a.runtime) / 'sstates').glob('*.p2s')):
            print('SAVESTATE', p)


if __name__ == '__main__':
    main()
