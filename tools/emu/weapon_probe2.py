# -*- coding: utf-8 -*-
"""weapon_probe2.py —— 两个状态分别扫键：
A) 小队设置（自动分配之前，右侧装备面板可见）
B) 角色说明页（Circle 打开后）
只 PostMessage，不抢焦点。
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


def scan(r, tag, base, keys):
    prev = base
    for k in keys:
        r.press(k, hold=0.12)
        time.sleep(0.7)
        img = r.grab()
        if img is None:
            continue
        d = NS.bigdiff(prev, img)
        r.save(img, '%s_key_%s_d%04d' % (tag, k, int(d * 10)))
        r.log('%s KEY %-3s diff=%5.2f' % (tag, k, d))
        prev = img


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
        r.save(brief, 'w2_brief')
        before = r.grab()
        changed, _ = r.wait_change(before, timeout=10)
        if not changed:
            r.advance('space', 'w2_cross1', 8)
        r.wait_for_band(0.15, 0.21, 15)
        r.settle()
        shot = r.grab()
        r.save(shot, 'w2_squad_setup')
        # A) 小队设置状态扫键
        scan(r, 'w2A', shot, ['e', 'q', 'a', 'h', 'f', 'g', 't'])
        # B) 自动分配 → 选中 → Circle 打开角色说明
        r.advance('space', 'w2_cross2', 8)
        r.settle()
        r.save(r.grab(), 'w2_auto')
        r.press('t')
        time.sleep(1.0)
        r.press('s')
        time.sleep(1.5)
        info = r.grab()
        if info is not None:
            r.save(info, 'w2_member_info')
            scan(r, 'w2B', info, ['e', 'q', 'h', 'f', 'g', 't'])
            # 在说明页试 R1 长按
            r.press('e', hold=0.4)
            time.sleep(1.0)
            img = r.grab()
            if img is not None:
                r.save(img, 'w2_info_r1long')
    finally:
        time.sleep(0.5)
        r.stop()


if __name__ == '__main__':
    main()
