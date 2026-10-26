# -*- coding: utf-8 -*-
"""measure_weapon_panel.py —— 量「武器属性」右面板金框与文字右边界，算可用全宽字宽。"""
import glob
import sys

import numpy as np
from PIL import Image

GAME_W = 640.0
CAP_X0, CAP_X1 = 312, 1786   # 游戏画面区


def game_x(px):
    return (px - CAP_X0) * GAME_W / (CAP_X1 - CAP_X0)


def gold_mask(a):
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    return (r > 150) & (g > 110) & (b < 90)


def text_mask(a):
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    return (r > 120) & (g > 120) & (b > 120)


for p in sorted(glob.glob(r'work\analysis\emu\weapon_capture\wc_weapon_attr_*.png')):
    a = np.asarray(Image.open(p).convert('RGB'), dtype=np.int16)
    h, w = a.shape[:2]
    gm = gold_mask(a)
    tm = text_mask(a)
    # 右面板：画面右侧 x>0.5w
    x0 = int(0.50 * w)
    sub_g = gm[:, x0:]
    ys, xs = np.nonzero(sub_g)
    if len(xs) == 0:
        print(p, 'no gold')
        continue
    gx0, gx1 = xs.min() + x0, xs.max() + x0
    gy0, gy1 = ys.min(), ys.max()
    # 文字：面板内部（去掉边框 6px）
    inner = tm[gy0 + 8:gy1 - 8, gx0 + 8:gx1 - 8]
    tys, txs = np.nonzero(inner)
    tx1 = (txs.max() + gx0 + 8) if len(txs) else gx0
    print('%-70s 金框 x %d..%d (game %.0f..%.0f, 宽 %.1f 字) 文字最右 %d (game %.0f) 余量 %.0f game px (%.1f 字)'
          % (p.split('\\')[-1], gx0, gx1, game_x(gx0), game_x(gx1), (game_x(gx1) - game_x(gx0)) / 16.0,
             tx1, game_x(tx1), game_x(gx1) - game_x(tx1), (game_x(gx1) - game_x(tx1)) / 16.0))
