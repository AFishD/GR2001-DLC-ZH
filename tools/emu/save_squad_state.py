# -*- coding: utf-8 -*-
"""save_squad_state.py —— 跑到小队名册界面后按 F1 存一个 PCSX2 即时存档，用于 RAM 取证。"""
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
    args = Args(a.iso, a.out, a.runtime)
    r = NS.Runner(args)
    r.start()
    try:
        brief = r.boot_to_brief()
        r.save(brief, 'ss_brief')
        # 简介页自动推进 / 主动 Cross
        before = r.grab()
        changed, _ = r.wait_change(before, timeout=10)
        if not changed:
            r.advance('space', 'ss_cross_brief', 8)
        img = r.wait_for_band(0.15, 0.21, 15)
        r.settle()
        r.save(img, 'ss_squad_setup')
        # Cross → 自动分配
        r.advance('space', 'ss_cross_auto', 8)
        r.settle()
        img = r.grab()
        r.save(img, 'ss_squad_auto')
        # 选中队员（右下显示姓名+兵种名）
        r.press('t')
        time.sleep(1.5)
        img = r.grab()
        r.save(img, 'ss_member_selected')
        # F1 存即时存档（默认槽 1）
        r.press('f1')
        time.sleep(4.0)
        r.log('F1 pressed, expect savestate in runtime/sstates')
        r.press('f1')
        time.sleep(3.0)
    finally:
        time.sleep(1.0)
        r.stop()
        for p in sorted((Path(a.runtime) / 'sstates').glob('*.p2s')):
            print('SAVESTATE', p)


if __name__ == '__main__':
    main()
