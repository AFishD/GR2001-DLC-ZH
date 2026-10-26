# -*- coding: utf-8 -*-
r"""js19_glyph_calib.py — 校准 JS19 图集 8x16 格与「方正像素16.ttf 16px 渲染」的压缩关系。

JS19 图集格 = 8x16；本体工程字形配方 = PIL truetype(16) 画在 32x32 的 (8,8)，取 [8:24,8:24] <128。
猜测上一版把 16x16 横向压成 8x16。这里用已知字符（atlas slot 0..7 = 区移挥备机记入图，
来自本体 charset pair_of 顺序）对多种压缩模式逐一比对，找出 xor==0 的模式。
"""
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
CHARSET = os.path.join(REPO, 'assets', 'charset', 'charset_compiled_zh16.json')

NCOL, CW, CH = 62, 8, 16
X0, Y0 = 2, 2
SKIP_ROW, SKIP_ROWS = 12, 3


def atlas_ink():
    pak = open(P_PAK, 'rb').read()
    recs = L.parse_pak_records(pak)
    r = [x for x in recs if x['name'] == 'new_font_revised'][0]
    cont = pak[r['px_off']:r['px_off'] + r['px']]
    tex, _e, _pk, _segs = F.atlas_engine_image(cont, 512, 512, 19)
    return tex == 0


def cell(ink, slot):
    row, col = slot // NCOL, slot % NCOL
    y = Y0 + CH * (row + (SKIP_ROWS if row >= SKIP_ROW else 0))
    x = X0 + CW * col
    return ink[y:y + CH, x:x + CW]


_font_cache = {}


def render16(ch, ttf=TTF, size=16):
    key = (ch, size)
    if key in _font_cache:
        return _font_cache[key]
    fnt = ImageFont.truetype(ttf, size)
    img = Image.new('L', (32, 32), 255)
    ImageDraw.Draw(img).text((8, 8), ch, font=fnt, fill=0)
    a = np.asarray(img)[8:24, 8:24] < 128
    _font_cache[key] = a
    return a


MODES = {
    'even': lambda a: a[:, 0::2],
    'odd': lambda a: a[:, 1::2],
    'or': lambda a: a[:, 0::2] | a[:, 1::2],
    'and': lambda a: a[:, 0::2] & a[:, 1::2],
}


def compress_mode(a, mode):
    """16x16 → 8x16。mode: even/odd/or/and 或 'thrN'（取 2 列均值 < N/2 为墨）。"""
    if mode in MODES:
        return MODES[mode](a)
    if mode.startswith('thr'):
        n = int(mode[3:])
        g = a.astype(np.uint16)
        pairs = g[:, 0::2] + g[:, 1::2]      # 0..2 (bool 相加)
        return pairs >= n
    raise ValueError(mode)


def main():
    js = json.load(open(CHARSET, encoding='utf-8'))
    pair_of = js['pair_of']
    ink = atlas_ink()
    # 反查 slot→char（本体 charset 口径）
    slot2ch = {}
    for ch, pr in pair_of.items():
        slot2ch[(pr[0] - 0xA1) * 94 + (pr[1] - 0xA1)] = ch
    modes = ['even', 'odd', 'or', 'and', 'thr1', 'thr2']
    # 前 64 个 slot 统计各 mode 的 xor
    res = {m: [] for m in modes}
    for slot in range(64):
        ch = slot2ch.get(slot)
        if not ch:
            continue
        got = cell(ink, slot)
        tpl16 = render16(ch)
        for m in modes:
            t = compress_mode(tpl16, m)
            res[m].append(int((t != got).sum()))
    print('前 64 slot 各压缩模式 xor 统计（越小越好，0=全等）:')
    for m in modes:
        v = res[m]
        print('  %-5s n=%d  mean=%.2f  zero=%d  max=%d' % (m, len(v), np.mean(v), sum(1 for x in v if x == 0), max(v)))


if __name__ == '__main__':
    main()
