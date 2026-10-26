# -*- coding: utf-8 -*-
r"""js19_shift_test.py — 求单字节码字形的「相对 pair 模板」的平移变换。"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'font'))
import dlclib as L            # noqa: E402
import fontlib as F           # noqa: E402

JS = os.path.join(REPO, 'work', 'analysis', 'js19')
P_PAK = os.path.join(JS, 'payloads', '00009_COMMON.PAK.bin')
TTF = os.path.join(REPO, 'third_party', 'fonts', '方正像素16.ttf')


def atlas_ink():
    pak = open(P_PAK, 'rb').read()
    recs = L.parse_pak_records(pak)
    r = [x for x in recs if x['name'] == 'new_font_revised'][0]
    cont = pak[r['px_off']:r['px_off'] + r['px']]
    tex, _e, _pk, _segs = F.atlas_engine_image(cont, 512, 512, 19)
    return tex == 0


def render16(ch):
    fnt = ImageFont.truetype(TTF, 16)
    img = Image.new('L', (32, 32), 255)
    ImageDraw.Draw(img).text((8, 8), ch, font=fnt, fill=0)
    a = np.asarray(img)[8:24, 8:24] < 128
    return a[:, 0::2] | a[:, 1::2]


def shift_xor(t, crop, dx, dy):
    H, W = crop.shape
    # 把 t 平移 (dx,dy) 后与 crop 的公共区域比较，非公共区算不匹配
    out = t
    tt = np.zeros_like(crop)
    src0y, src0x = max(0, -dy), max(0, -dx)
    dst0y, dst0x = max(0, dy), max(0, dx)
    h = min(H - dst0y, H - src0y)
    w = min(W - dst0x, W - src0x)
    if h > 0 and w > 0:
        tt[dst0y:dst0y + h, dst0x:dst0x + w] = t[src0y:src0y + h, src0x:src0x + w]
    return int((tt != crop).sum())


def main():
    ink = atlas_ink()
    recs = json.load(open(os.path.join(JS, 'js19_ft_records.json'), encoding='utf-8'))
    large = [f for f in recs['faces'] if f['name'] == 'large'][0]['recs']
    guesses = {0xBA: '战', 0xEA: '人', 0xDB: '后', 0xFB: '有', 0xB8: '时',
               0xBC: '在', 0xC5: '一', 0xF6: '老', 0xE6: '鼠', 0xD5: '到', 0xAF: '的',
               0xC2: '？', 0xB0: '不', 0xB2: '有', 0xC3: '了'}
    for code, g in guesses.items():
        idx = code - 0x20
        b0, adv, u0, v0, u1, v1 = large[idx]
        crop = ink[v0:v1, u0:u1]
        t = render16(g)
        best = None
        for dy in range(-3, 4):
            for dx in range(-4, 5):
                x = shift_xor(t, crop, dx, dy)
                if best is None or x < best[0]:
                    best = (x, dx, dy)
        print('code %02X 猜测 %r  最佳 shift dx=%d dy=%d xor=%d' % (code, g, best[1], best[2], best[0]))


if __name__ == '__main__':
    main()
