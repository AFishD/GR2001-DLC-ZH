# -*- coding: utf-8 -*-
r"""js19_single_probe.py — 目视校验：把单字节码的 FT 矩形裁剪打印成位图，对照 TTF 渲染。"""
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


def show(a, label=''):
    print(label)
    for row in a:
        print('   ' + ''.join('#' if v else '.' for v in row))


def main():
    ink = atlas_ink()
    recs = json.load(open(os.path.join(JS, 'js19_ft_records.json'), encoding='utf-8'))
    large = [f for f in recs['faces'] if f['name'] == 'large'][0]['recs']
    # 抽样：上下文猜测
    guesses = {0xBA: '战', 0xEA: '人', 0xDB: '后', 0xFB: '有', 0xB8: '时',
               0xBC: '在', 0xC5: '一', 0xF6: '老', 0xE6: '鼠', 0xD5: '到', 0xAF: '的',
               0xC2: '？', 0xAE: '®'}
    for code, g in guesses.items():
        idx = code - 0x20
        b0, adv, u0, v0, u1, v1 = large[idx]
        crop = ink[v0:v1, u0:u1]
        print('=== code %02X idx %3d rect=(%d,%d,%d,%d) %dx%d adv=%d b0=%d ==='
              % (code, idx, u0, v0, u1, v1, u1 - u0, v1 - v0, adv, b0))
        show(crop, ' atlas:')
        if crop.shape == (16, 8):
            t = render16(g)
            show(t, ' TTF %r:' % g)
            print(' xor=%d' % int((t != crop).sum()))


if __name__ == '__main__':
    main()
