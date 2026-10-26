# -*- coding: utf-8 -*-
"""dump_atlas_table.py —— 字库纹理「表格图」导出（含原版对照）。

用法：
    python tools\\font\\dump_atlas_table.py --iso work\\builds\\FINAL\\GR_JS_ZH.iso --tag zh
    python tools\\font\\dump_atlas_table.py --iso <英文原盘> --tag en

产物（默认 work/analysis/font/）：
    atlas_engine_<tag>.png        引擎图 1:1
    atlas_table_<tag>.png         表格图（2× 放大 + 网格 + 列/行号 + 槽号 + 高亮）
    atlas_slots_<tag>.csv         槽位表（slot/row/col/lead/trail/char/kind）
    atlas_compare.png             EN 原版 vs 成品 对照（--compare 时生成）
"""
import argparse
import csv
import io
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'analysis'))

import fontlib as F                                              # noqa: E402
import build_font as BF                                          # noqa: E402

OUT = os.path.join(REPO, 'work', 'analysis', 'font')
NCOL = 64
CW = CH = 16
Y0 = 3


def slot_geometry(slot):
    row, col = divmod(slot, NCOL)
    x = CW * col
    y = Y0 + CH * (row + (2 if row >= 12 else 0))
    return row, col, x, y


def slot_of(lead, trail):
    return (lead - 0xA1) * 94 + (trail - 0xA1)


def load_atlas(iso_path):
    dlc = BF.load_dlc(iso_path)
    pak = dlc['pak']
    recs = dlc['recs']
    _fi, fr = F.pak_find(recs, 'new_font_revised')
    cont = pak[fr['px_off']:fr['px_off'] + fr['px']]
    tex, empty, packets, segs = F.atlas_engine_image(cont, fr['w'], fr['h'], fr['psm'])
    dlc['iso'].close()
    return dict(rec=fr, tex=tex, empty=empty, cont=cont)


def charset_map():
    p = os.path.join(REPO, 'assets', 'charset', 'charset_compiled_zh16.json')
    cs = json.load(io.open(p, encoding='utf-8'))
    inv = {}
    for ch, pair in cs['pair_of'].items():
        inv[(pair[0], pair[1])] = ch
    return cs, inv


def slot_table(tex, inv):
    rows = []
    h, w = tex.shape
    for lead in range(0xA1, 0xBA):
        for trail in range(0xA1, 0xFF):
            slot = slot_of(lead, trail)
            row, col, x, y = slot_geometry(slot)
            char = inv.get((lead, trail), '')
            kind = 'pair'
            if trail in (0xB1, 0xB5):
                kind = 'sentinel'
            elif not char:
                kind = 'empty'
            ink = 0
            if x + CW <= w and y + CH <= h:
                ink = int((tex[y:y + CH, x:x + CW] == 0).sum())
            if kind == 'pair' and char and 0xE000 <= ord(char) <= 0xF8FF:
                kind = 'pua'
            if kind == 'pair' and not char:
                kind = 'empty'
            rows.append(dict(slot=slot, row=row, col=col, lead=lead, trail=trail,
                             char=char, kind=kind, ink=ink))
    return rows


def render_table(tex, empty, rows, title, scale=2, highlight=True):
    h, w = tex.shape
    ink = (tex == 0)
    if scale > 1:
        ink = np.repeat(np.repeat(ink, scale, axis=0), scale, axis=1)
    base = Image.frombytes('L', (ink.shape[1], ink.shape[0]),
                           np.where(ink, 0, 255).astype(np.uint8).tobytes()).convert('RGB')
    if not highlight:
        base.save(title)
        return base

    MARGIN_L, MARGIN_T = 66, 34
    MARGIN_R, MARGIN_B = 18, 42
    out = Image.new('RGB', (MARGIN_L + base.width + MARGIN_R,
                            MARGIN_T + base.height + MARGIN_B), (24, 26, 30))
    out.paste(base, (MARGIN_L, MARGIN_T))
    d = ImageDraw.Draw(out, 'RGBA')
    try:
        f_small = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 9)
        f_lbl = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 11)
        f_title = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 15)
    except OSError:
        f_small = f_lbl = f_title = ImageFont.load_default()

    green = (60, 220, 120, 255)
    red = (255, 70, 70, 255)
    gray = (140, 140, 150, 200)

    # 网格
    if w >= 1024:                                              # 中文图集（对偶槽网格）
        for r in range(37):
            row, col, x, y = slot_geometry(r * NCOL)
            yy = MARGIN_T + y * scale
            d.line([(MARGIN_L, yy), (MARGIN_L + base.width, yy)],
                   fill=(90, 96, 104, 120), width=1)
            if r < 36:
                d.text((4, yy + 2), 'r%d' % r, fill=(200, 205, 215), font=f_small)
        for c in range(NCOL + 1):
            xx = MARGIN_L + c * CW * scale
            d.line([(xx, MARGIN_T), (xx, MARGIN_T + base.height)],
                   fill=(70, 76, 84, 90), width=1)
        for c in range(0, NCOL, 4):
            xx = MARGIN_L + c * CW * scale
            d.text((xx + 1, 6), 'c%d' % c, fill=(200, 205, 215), font=f_small)
        # 高亮
        for r in rows:
            row, col, x, y = slot_geometry(r['slot'])
            x0, y0 = MARGIN_L + x * scale, MARGIN_T + y * scale
            x1, y1 = x0 + CW * scale, y0 + CH * scale
            if r['kind'] == 'sentinel':
                d.rectangle([x0, y0, x1 - 1, y1 - 1], outline=red, width=2)
            elif r['kind'] in ('pua',):
                d.rectangle([x0, y0, x1 - 1, y1 - 1], outline=green, width=2)
        # 图例
        lx, ly = MARGIN_L, MARGIN_T + base.height + 6
        d.rectangle([lx, ly + 2, lx + 10, ly + 12], outline=red, width=2)
        d.text((lx + 14, ly), '红框 = 50 个图标哨兵槽（trail 0xB1/0xB5，引擎特判，禁止占用）',
               fill=(255, 200, 200), font=f_lbl)
        d.rectangle([lx + 640, ly + 2, lx + 650, ly + 12], outline=green, width=2)
        d.text((lx + 654, ly), '绿框 = PUA 回收槽（可补画新字）',
               fill=(200, 255, 200), font=f_lbl)
        d.text((lx, ly + 18), title, fill=(255, 220, 120), font=f_title)
    else:
        for gx in range(0, w + 1, 32):
            d.line([(MARGIN_L + gx * scale, MARGIN_T),
                    (MARGIN_L + gx * scale, MARGIN_T + base.height)],
                   fill=(70, 76, 84, 90), width=1)
        for gy in range(0, h + 1, 32):
            d.line([(MARGIN_L, MARGIN_T + gy * scale),
                    (MARGIN_L + base.width, MARGIN_T + gy * scale)],
                   fill=(70, 76, 84, 90), width=1)
        d.text((MARGIN_L, MARGIN_T + base.height + 6),
               title + '（原版英文图集；单字节字形按 FT 记录矩形取，不走 64 列网格）',
               fill=(255, 220, 120), font=f_title)
    return out


def save_slots_csv(rows, path):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, lineterminator='\r\n')
        w.writerow(['slot', 'row', 'col', 'lead', 'trail', 'char', 'kind', 'ink_px'])
        for r in rows:
            w.writerow([r['slot'], r['row'], r['col'], '0x%02X' % r['lead'],
                        '0x%02X' % r['trail'], r['char'], r['kind'], r['ink']])


def render_icon_zoom(tex, rows, path, scale=8):
    """哨兵/图标格放大图：50 个哨兵槽 + 有墨的图标格（8×）。"""
    from PIL import ImageDraw, ImageFont
    sent = [r for r in rows if r['kind'] == 'sentinel']
    inked = [r for r in sent if r['ink'] > 0]
    show = sent
    cell_px = CW * scale
    cols = 10
    rows_n = (len(show) + cols - 1) // cols
    pad, label_h = 8, 18
    W = pad + cols * (cell_px + pad)
    H = 46 + rows_n * (cell_px + label_h + pad) + 24
    out = Image.new('RGB', (W, H), (22, 24, 28))
    d = ImageDraw.Draw(out)
    try:
        f = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 11)
        ft = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 14)
    except OSError:
        f = ft = ImageFont.load_default()
    d.text((pad, 8), '图标哨兵槽放大图（%d 格；红=有墨的图标像素格，引擎画手柄按键用）'
                     % len(show), fill=(255, 220, 120), font=ft)
    for i, r in enumerate(show):
        row, col, x, y = slot_geometry(r['slot'])
        cx = pad + (i % cols) * (cell_px + pad)
        cy = 46 + (i // cols) * (cell_px + label_h + pad)
        cell = tex[y:y + CH, x:x + CW]
        ink = (cell == 0)
        img = Image.frombytes('L', (CW, CH), np.where(ink, 0, 255).astype(np.uint8).tobytes())
        img = img.resize((cell_px, cell_px), Image.NEAREST).convert('RGB')
        out.paste(img, (cx, cy))
        color = (255, 70, 70) if r['ink'] > 0 else (110, 116, 124)
        d.rectangle([cx - 1, cy - 1, cx + cell_px, cy + cell_px], outline=color, width=2)
        d.text((cx, cy + cell_px + 2), 'slot %d' % r['slot'], fill=(210, 215, 225), font=f)
        d.text((cx, cy + cell_px + 12), '%s/%s' % (r['lead'], r['trail']),
               fill=(170, 176, 186), font=f)
    out.save(path, optimize=True)
    return path


def render_compare(en_png, zh_png, path):
    """EN 原版图集 vs 成品图集 对照图。"""
    en = Image.open(en_png).convert('RGB')
    zh = Image.open(zh_png).convert('RGB')
    target_w = 1000
    en2 = en.resize((target_w, int(en.height * target_w / en.width)), Image.LANCZOS)
    zh2 = zh.resize((target_w, int(zh.height * target_w / zh.width)), Image.LANCZOS)
    gap, header = 24, 44
    W = target_w * 2 + gap
    H = header + max(en2.height, zh2.height) + 12
    out = Image.new('RGB', (W, H), (18, 20, 24))
    from PIL import ImageDraw, ImageFont
    d = ImageDraw.Draw(out)
    try:
        f = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 15)
    except OSError:
        f = ImageFont.load_default()
    d.text((8, 10), '原版英文图集 512×512 PSMT8（ASCII/拉丁字形）', fill=(255, 220, 120), font=f)
    d.text((target_w + gap + 8, 10), '汉化成品图集 1024×644 PSMT4（2350 对偶槽 + ASCII 带）',
           fill=(255, 220, 120), font=f)
    out.paste(en2, (0, header))
    out.paste(zh2, (target_w + gap, header))
    out.save(path, optimize=True)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--iso', required=True)
    ap.add_argument('--tag', default='zh')
    ap.add_argument('--out', default=OUT)
    ap.add_argument('--scale', type=int, default=2)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)

    at = load_atlas(a.iso)
    tex, empty = at['tex'], at['empty']
    print('atlas', tex.shape, 'empty_index', empty, 'psm', hex(at['rec']['psm']))
    F.save_atlas_png(tex, os.path.join(a.out, 'atlas_engine_%s.png' % a.tag), int(empty),
                     scale=1)
    cs, inv = charset_map()
    rows = slot_table(tex, inv)
    img = render_table(tex, empty, rows, '字库纹理表格 %s（%d×%d PSMT%s）'
                       % (a.tag.upper(), tex.shape[1], tex.shape[0],
                          '4' if at['rec']['psm'] == 0x14 else '8'),
                       scale=a.scale)
    img.save(os.path.join(a.out, 'atlas_table_%s.png' % a.tag), optimize=True)
    save_slots_csv(rows, os.path.join(a.out, 'atlas_slots_%s.csv' % a.tag))
    if tex.shape[1] >= 1024:
        render_icon_zoom(tex, rows, os.path.join(a.out, 'atlas_icon_cells_zoom.png'))
    print('saved ->', a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
