# -*- coding: utf-8 -*-
"""weapon_probe.py —— 从小队名册出发，系统扫按键/组合键，找出进入「选择队员武器/武器说明」的入口。
只使用 PostMessage（GRJS_EMU_NO_SENDINPUT=1），不抢 Windows 焦点。
"""
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
        r.save(brief, 'wp_brief')
        before = r.grab()
        changed, _ = r.wait_change(before, timeout=10)
        if not changed:
            r.advance('space', 'wp_cross1', 8)
        r.wait_for_band(0.15, 0.21, 15)
        r.settle()
        r.save(r.grab(), 'wp_squadscreen')
        r.advance('space', 'wp_cross2', 8)
        r.settle()
        base = r.grab()
        r.save(base, 'wp_roster_base')

        keys = ['e', 'q', 'a', '1', '2', 'h', 'f', 't', 'g', 's', 'w', 'tab', 'return']
        prev = base
        for k in keys:
            r.press(k, hold=0.15)
            time.sleep(0.8)
            img = r.grab()
            if img is None:
                continue
            d = NS.bigdiff(prev, img)
            r.save(img, 'wp_key_%s_d%04d' % (k.replace(' ', '_'), int(d * 10)))
            r.log('KEY %-5s diff=%5.2f' % (k, d))
            prev = img

        # 组合：先选中队员，再按 R1（短/长按）、L1、Square 后 R1
        r.press('t')
        time.sleep(1.0)
        sel = r.grab()
        r.save(sel, 'wp_selected')
        for k, hold, tag in (('e', 0.15, 'r1_short'), ('e', 0.40, 'r1_long'),
                             ('q', 0.15, 'l1'), ('a', 0.15, 'square'),
                             ('h', 0.15, 'right')):
            r.press(k, hold=hold)
            time.sleep(1.0)
            img = r.grab()
            if img is None:
                continue
            d = NS.bigdiff(sel, img)
            r.save(img, 'wp_seq_%s_d%04d' % (tag, int(d * 10)))
            r.log('SEQ %-10s key=%s diff=%5.2f' % (tag, k, d))
        # 再试：Square 后 R1、Right 后 R1
        r.press('a')
        time.sleep(0.8)
        r.press('e')
        time.sleep(1.0)
        img = r.grab()
        if img is not None:
            r.save(img, 'wp_seq_square_then_r1')
        r.press('w')
        time.sleep(0.8)
        r.press('h')
        time.sleep(0.8)
        r.press('e')
        time.sleep(1.0)
        img = r.grab()
        if img is not None:
            r.save(img, 'wp_seq_right_then_r1')
    finally:
        time.sleep(0.5)
        r.stop()


if __name__ == '__main__':
    main()
