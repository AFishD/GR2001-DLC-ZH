# -*- coding: utf-8 -*-
"""cmp_obj.py <img1> <img2> ... —— 量化简报任务目标行在图像中的垂直位置。"""
import sys

import numpy as np
from PIL import Image


def ink(p, y0, y1, x0=420, x1=1300, dark=True, thr=110):
    a = np.asarray(Image.open(p).convert('RGB')).astype(int)
    sub = a[y0:y1, x0:x1]
    br = sub.mean(axis=2)
    m = br < thr if dark else br > 170
    w = m.sum(axis=1)
    tot = w.sum()
    if tot == 0:
        return None
    return y0 + (w * np.arange(len(w))).sum() / tot


def prof(p):
    a = np.asarray(Image.open(p).convert('RGB')).astype(int)
    sub = a[630:960, 420:1300]
    br = sub.mean(axis=2)
    bg = np.median(br, axis=1, keepdims=True)
    return np.abs(br - bg).sum(axis=1)


for p in sys.argv[1:]:
    lab = p.split('\\')[-2]
    print(lab, 'item1', round(ink(p, 650, 712), 1),
          'item2', round(ink(p, 690, 745, dark=False), 1),
          'item3', round(ink(p, 735, 790, dark=False), 1),
          'item4', round(ink(p, 780, 835, dark=False), 1))
