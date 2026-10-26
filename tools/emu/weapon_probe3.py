# -*- coding: utf-8 -*-
"""weapon_probe3.py —— 名册状态下试「方向键移动焦点 + Circle/R1」组合，找武器信息界面。"""
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

    def seq(tag, keys, waits=0.9):
        for k in keys:
            r.press(k, hold=0.12)
            time.sleep(waits)
        img = r.grab()
        if img is not None:
            r.save(img, 'w3_%s' % tag)
            r.log('W3 %s keys=%s' % (tag, keys))

    try:
        brief = r.boot_to_brief()
        r.save(brief, 'w3_brief')
        before = r.grab()
        changed, _ = r.wait_change(before, timeout=10)
        if not changed:
            r.advance('space', 'w3_cross1', 8)
        r.wait_for_band(0.15, 0.21, 15)
        r.settle()
        r.save(r.grab(), 'w3_setup')
        r.advance('space', 'w3_cross2', 8)
        r.settle()
        base = r.grab()
        r.save(base, 'w3_roster')

        seq('h', ['h'])
        seq('h_then_s', ['s'])
        seq('back_w_h_s', ['w', 'h', 's'])
        seq('f_s', ['f', 's'])
        seq('down2_h_s', ['g', 'h', 's'])
        seq('up_h_s', ['w', 't', 'h', 's'])
        seq('h_e', ['e'])
        seq('h_sq', ['a'])
    finally:
        time.sleep(0.5)
        r.stop()


if __name__ == '__main__':
    main()
