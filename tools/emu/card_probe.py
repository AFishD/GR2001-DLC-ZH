# -*- coding: utf-8 -*-
"""card_probe.py —— 启动到标题后按 START，连拍 profile/记忆卡界面。

用法：python tools/emu/card_probe.py --iso <iso> --out <dir> --runtime <dir>
"""
import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
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
    ap.add_argument('--boot-wait', type=float, default=140.0)
    ap.add_argument('--after', type=float, default=45.0)
    a = ap.parse_args()
    r = NS.Runner(Args(a.iso, a.out, a.runtime))
    r.start()
    try:
        t0 = time.time()
        while time.time() - t0 < a.boot_wait:
            time.sleep(2)
        img = r.grab()
        if img is not None:
            r.save(img, 'card_press_start')
        r.press('start')
        t1 = time.time()
        i = 0
        while time.time() - t1 < a.after:
            img = r.grab()
            if img is not None:
                r.save(img, 'card_%03d' % i)
            i += 1
            time.sleep(2)
    finally:
        r.stop()


if __name__ == '__main__':
    main()
