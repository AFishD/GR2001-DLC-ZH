# -*- coding: utf-8 -*-
"""capture_training_msg.py —— 进入训练关并抓取「屏幕顶部提示消息框」的帧。

流程：主菜单 → 单人游戏 → 训练 → 选关（默认训练1；可选先按 Down N 次）→ Cross 开始
→ 连拍等待关卡加载与提示消息出现。
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
    ap.add_argument('--downs', type=int, default=0, help='在训练列表中按 Down 次数（每次 2 行）')
    ap.add_argument('--tag', default='tr1')
    a = ap.parse_args()
    r = NS.Runner(Args(a.iso, a.out, a.runtime))
    r.start()
    try:
        r.boot_to_mainmenu()
        r.press('space')      # 单人游戏子菜单（默认高亮 训练）
        time.sleep(3.0)
        r.press('space')      # 进入训练列表
        time.sleep(2.5)
        r.settle()
        r.save(r.grab(), '%s_list' % a.tag)
        for k in range(a.downs):
            r.press('g', hold=0.02)
            time.sleep(0.8)
        r.settle()
        r.save(r.grab(), '%s_list2' % a.tag)
        r.press('space')      # 开始
        t0 = time.time()
        for i in range(50):
            time.sleep(1.2)
            img = r.grab()
            if img is not None:
                r.save(img, '%s_%02d' % (a.tag, i))
    finally:
        time.sleep(0.5)
        r.stop()


if __name__ == '__main__':
    main()
