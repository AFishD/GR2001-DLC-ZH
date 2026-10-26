# -*- coding: utf-8 -*-
"""row_align_measure.py —— 量每行文字中心相对行条带中心的偏移（EN vs v46）。"""
import numpy as np
from PIL import Image

XS, XE = 312, 1786
SX = (XE - XS) / 640.0
SY = 1106 / 448.0
# 行条带 game 坐标（A1..A3 绿色, B1..B3 蓝色）
ROWS = {
    'A1': (137, 168), 'A2': (167, 198), 'A3': (197, 228),
    'B1': (252, 283), 'B2': (282, 313), 'B3': (312, 343),
}


def measure(path, label):
    a = np.asarray(Image.open(path).convert('RGB')).astype(int)
    print('==', label)
    for name, (gy0, gy1) in ROWS.items():
        x0, x1 = int(XS + 62 * SX), int(XS + 235 * SX)
        y0, y1 = int(gy0 * SY), int(gy1 * SY)
        sub = a[y0:y1, x0:x1]
        r, g, b = sub[:, :, 0], sub[:, :, 1], sub[:, :, 2]
        green = (g > r + 15) & (g > 70)
        blue = (b > r + 25) & (b > 70)
        band = green if name.startswith('A') else blue
        band_rows = [i for i, v in enumerate(band.sum(axis=1)) if v > (x1 - x0) * 0.55]
        bright = (r > 165) & (g > 165) & (b > 165)
        text_rows = [i for i, v in enumerate(bright.sum(axis=1)) if v > 12]
        if not band_rows or not text_rows:
            print('  %-2s band=%s text=%s' % (name, len(band_rows), len(text_rows)))
            continue
        bc = (band_rows[0] + band_rows[-1]) / 2.0
        # 只取落在条带内部的文字行
        tr = [i for i in text_rows if band_rows[0] + 2 <= i <= band_rows[-1] - 2]
        if not tr:
            tr = text_rows
        tc = (tr[0] + tr[-1]) / 2.0
        print('  %-2s band %.1f..%.1f c=%.1f | text %.1f..%.1f c=%.1f | Δ=%+.1f game px'
              % (name, gy0 + band_rows[0] / SY, gy0 + band_rows[-1] / SY, gy0 + bc / SY,
                 gy0 + tr[0] / SY, gy0 + tr[-1] / SY, gy0 + tc / SY, (tc - bc) / SY))


measure(r'work\analysis\emu\squad_en\member_selected.png', 'EN roster')
measure(r'work\analysis\emu\hint46\hf_roster.png', 'v46 roster')
