# -*- coding: utf-8 -*-
"""weapon_capture.py —— 到达「武器属性」界面并逐条目截图。
路径：简报 → Cross → 小队设置 → Cross 自动分配 → Up 选人 → R1 聚焦装备栏 → Circle 打开武器属性
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
    ap.add_argument('--cycles', type=int, default=4)
    a = ap.parse_args()
    r = NS.Runner(Args(a.iso, a.out, a.runtime))
    r.start()
    try:
        brief = r.boot_to_brief()
        r.save(brief, 'wc_brief')
        before = r.grab()
        changed, _ = r.wait_change(before, timeout=10)
        if not changed:
            r.advance('space', 'wc_cross1', 8)
        r.wait_for_band(0.15, 0.21, 15)
        r.settle()
        r.advance('space', 'wc_cross2', 8)
        r.settle()
        r.save(r.grab(), 'wc_roster')
        # 选人
        r.press('t')
        time.sleep(1.0)
        r.save(r.grab(), 'wc_selected')
        # R1 聚焦装备栏
        r.press('e')
        time.sleep(1.0)
        r.save(r.grab(), 'wc_kit_focus')
        # Circle 打开武器属性
        r.press('s')
        time.sleep(1.5)
        shot = r.grab()
        r.save(shot, 'wc_weapon_attr_0')
        r.settle()
        for i in range(a.cycles):
            r.press('h')  # 右键换下一件装备
            time.sleep(1.2)
            img = r.grab()
            if img is not None:
                r.save(img, 'wc_weapon_attr_%d' % (i + 1))
        # 换回并截图武器说明（Circle 已是说明页；左右切换后仍有说明）
    finally:
        time.sleep(0.5)
        r.stop()


if __name__ == '__main__':
    main()
