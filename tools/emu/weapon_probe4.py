# -*- coding: utf-8 -*-
"""weapon_probe4.py —— 小队设置（空槽）状态下按 Circle/Cross/方向，找「选择队员武器/装备」界面。"""
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

    def seq(tag, keys):
        for k in keys:
            r.press(k, hold=0.12)
            time.sleep(0.9)
        img = r.grab()
        if img is not None:
            r.save(img, 'w4_%s' % tag)
            r.log('W4 %s keys=%s' % (tag, keys))

    try:
        brief = r.boot_to_brief()
        r.save(brief, 'w4_brief')
        before = r.grab()
        changed, _ = r.wait_change(before, timeout=10)
        if not changed:
            r.advance('space', 'w4_cross1', 8)
        r.wait_for_band(0.15, 0.21, 15)
        r.settle()
        r.save(r.grab(), 'w4_setup')
        seq('circle_slot', ['s'])
        seq('cross_slot', ['space'])
        seq('back_w', ['w'])
        seq('down1', ['g'])
        seq('down1_circle', ['s'])
        seq('back_w', ['w'])
        seq('down2', ['g', 'g'])
        seq('down2_circle', ['s'])
        seq('back_w', ['w'])
        seq('down2_h', ['g', 'g', 'h'])
        seq('down2_h_circle', ['s'])
        seq('back_w', ['w'])
        seq('down2_e', ['g', 'g', 'e'])
        seq('down2_e_circle', ['s'])
    finally:
        time.sleep(0.5)
        r.stop()


if __name__ == '__main__':
    main()
