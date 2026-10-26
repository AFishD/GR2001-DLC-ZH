# -*- coding: utf-8 -*-
r"""js19_atlas_png.py — 生成 JS19 图集带格线/标注预览 + OCR 对照样张。

产出：
  work/analysis/js19/js19_font_atlas_cells.png  主图（2x 图集 + 格线 + 区域标注 + 统计 + 抽样对照）
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
P_OCR = os.path.join(JS, 'js19_atlas_ocr.json')
P_CS = os.path.join(JS, 'js19_charset.json')

NCOL, CW, CH = 62, 8, 16
X0, Y0, SKIP_ROW, SKIP_ROWS = 2, 2, 12, 3
PAIR_CAP = (0xAE - 0xA1) * 94


def atlas_ink():
    pak = open(P_PAK, 'rb').read()
    recs = L.parse_pak_records(pak)
    r = [x for x in recs if x['name'] == 'new_font_revised'][0]
    cont = pak[r['px_off']:r['px_off'] + r['px']]
    tex, _e, _pk, _segs = F.atlas_engine_image(cont, 512, 512, 19)
    return tex == 0


def yrow(row):
    return Y0 + CH * (row + (SKIP_ROWS if row >= SKIP_ROW else 0))


def main():
    ink = atlas_ink()
    ocr = json.load(open(P_OCR, encoding='utf-8'))
    cs = json.load(open(P_CS, encoding='utf-8'))
    S = 2
    W = 512 * S
    PAD_L, PAD_T = 70, 66
    H_FOOT = 250
    img = Image.new('RGB', (PAD_L + W + 320, PAD_T + W + H_FOOT), (255, 255, 255))
    d = ImageDraw.Draw(img)
    f12 = ImageFont.truetype(TTF, 12)
    f14 = ImageFont.truetype(TTF, 14)
    f16 = ImageFont.truetype(TTF, 16)

    # ── 图集 RGB + 单元格着色（只染白底，保留黑墨）：
    #    pair 且文本用到=白底；pair 画出但文本未用=淡黄；单字节码格=淡绿；空槽=白 ──
    rgb = np.full((512, 512, 3), 255, np.uint8)
    single_slots = set(v['slot'] for v in cs['single'].values() if v.get('slot') is not None)
    pair_slots = set(v['slot'] for v in cs['pair'].values())

    def tint(y, x, color):
        cell = rgb[y:y + CH, x:x + CW]
        white = cell.min(axis=2) == 255
        for k in range(3):
            ch = cell[:, :, k]
            ch[white] = color[k]

    for slot in range(PAIR_CAP):
        row, col = slot // NCOL, slot % NCOL
        y = yrow(row)
        if y + CH > 512:
            break
        x = X0 + CW * col
        if slot in single_slots:
            tint(y, x, (200, 245, 200))
        elif slot not in pair_slots:
            tint(y, x, (255, 250, 205))
    rgb[ink] = (0, 0, 0)

    ox, oy = PAD_L, PAD_T
    img.paste(Image.fromarray(rgb).resize((W, W), Image.NEAREST), (ox, oy))

    # ── 格线 + 行号 ──
    for row in range(0, 30):
        y = yrow(row)
        if y + CH > 512:
            break
        d.line([ox, oy + y * S, ox + W, oy + y * S], fill=(120, 160, 255), width=1)
        d.line([ox, oy + (y + CH) * S, ox + W, oy + (y + CH) * S], fill=(120, 160, 255), width=1)
        d.text((4, oy + y * S + 2), 'r%d' % row, font=f12, fill=(0, 0, 160))
        d.text((30, oy + y * S + 2), '%d' % (row * NCOL), font=f12, fill=(120, 120, 120))
    for col in range(0, NCOL + 1):
        x = X0 + CW * col
        if x > 512:
            break
        d.line([ox + x * S, oy, ox + x * S, oy + W], fill=(205, 215, 255), width=1)
        if col % 5 == 0:
            d.text((ox + x * S - 5, oy - 15), '%d' % col, font=f12, fill=(0, 0, 160))

    # ── 区域标注 ──
    gap_y0 = yrow(11) + CH
    d.rectangle([ox, oy + gap_y0 * S, ox + W, oy + (gap_y0 + 3 * CH) * S],
                outline=(255, 140, 0), width=2)
    d.text((ox + 8, oy + (gap_y0 + 18) * S), 'SKIP_ROWS=3 空档 y=%d..%d' % (gap_y0, gap_y0 + 48),
           font=f14, fill=(200, 90, 0))
    d.rectangle([ox, oy + 370 * S, ox + W, oy + 450 * S], outline=(200, 0, 140), width=2)
    d.text((ox + 8, oy + 452 * S), 'ASCII / 单字节 FT 带 y=370..450', font=f14, fill=(180, 0, 130))

    # ── 标题 ──
    d.text((10, 6), 'JS_ZH19 图集（COMMON.PAK new_font_revised, 512x512 PSMT8）— 62 列 x 8x16 网格',
           font=f16, fill=(0, 0, 0))
    d.text((10, 26), '墨=黑(texel 0)，底=白(texel 15)；蓝线=cell 边界；白底=pair 格(文本用到)；淡黄=pair 格(画出未用)；淡绿=单字节高码引用格；橙=跳行空档；紫=ASCII 带',
           font=f12, fill=(70, 70, 70))
    d.text((10, 44), 'slot=(lead-0xA1)*94+(trail-0xA1) → row=slot//62, col=slot%62 → x=2+8*col, y=2+16*(row+3*[row>=12])；cell=8x16',
           font=f12, fill=(70, 70, 70))

    # ── 右侧统计 ──
    px = PAD_L + W + 16
    stat = cs['stats']
    lines = [
        ('解析规模', ''),
        ('图集', '512x512 PSMT8'),
        ('格几何', '62 列 x 8x16'),
        ('pair 容量', '%d (lead A1..AD)' % PAIR_CAP),
        ('有墨格', '1283 / 1446'),
        ('OCR xor=0 唯一', '1209'),
        ('文本用 pair 槽', '%d' % stat['used_pairs']),
        ('文本用单字节码', '%d' % stat['used_singles']),
        ('', ''),
        ('译文还原', ''),
        ('LANG 条目', '2971'),
        ('已翻译', '2278'),
        ('  其中含汉字', '2275'),
        ('未翻译(英文)', '693'),
        ('汉字总数', '22,594'),
        ('不同字', '881 (全在本体字集)'),
        ('唯一英文串', '1792'),
        ('未解析码', '0'),
        ('', ''),
        ('字形配方', 'TTF16px→OR半采样'),
    ]
    for i, (k, v) in enumerate(lines):
        yy = PAD_T + i * 20
        d.text((px, yy), k, font=f12, fill=(0, 0, 0))
        d.text((px + 118, yy), v, font=f12, fill=(0, 100, 0))

    # ── 底部：24 格 OCR 对照 ──
    fy = PAD_T + W + 10
    d.text((10, fy), '抽样 24 格校验：左=图集实际位图(8x16 放大4x)，右=按配方用 TTF 渲染的同一格；x0=完美一致（共 1209 格）',
           font=f14, fill=(0, 0, 0))
    cells = [c for c in ocr['cells'] if c.get('char') and c['ink'] > 0]
    step = max(1, len(cells) // 24)
    pick = cells[::step][:24]
    fnt = ImageFont.truetype(TTF, 16)
    bx, by = 14, fy + 22
    for n, c in enumerate(pick):
        col = n % 8
        row = n // 8
        cx = bx + col * 168
        cy = by + row * 66
        x, y = c['x'], c['y']
        crop = ink[y:y + CH, x:x + CW]
        im = Image.frombytes('L', (CW, CH), np.where(crop, 30, 235).astype(np.uint8).tobytes())
        im = im.resize((CW * 4, CH * 4), Image.NEAREST).convert('RGB')
        img.paste(im, (cx, cy))
        d.rectangle([cx, cy, cx + CW * 4 - 1, cy + CH * 4 - 1], outline=(160, 160, 160))
        t = Image.new('L', (32, 32), 255)
        ImageDraw.Draw(t).text((8, 8), c['char'], font=fnt, fill=0)
        t = t.crop((8, 8, 24, 24)).resize((CW * 2, CH * 2), Image.NEAREST).convert('RGB')
        img.paste(t, (cx + CW * 4 + 6, cy))
        d.rectangle([cx + CW * 4 + 6, cy, cx + CW * 4 + 6 + CW * 2 - 1, cy + CH * 2 - 1],
                    outline=(160, 160, 160))
        d.text((cx + CW * 4 + 26, cy + 2), c['char'], font=f14, fill=(0, 0, 0))
        d.text((cx + CW * 4 + 26, cy + 20), 'slot %d' % c['slot'], font=f12, fill=(90, 90, 90))
        d.text((cx + CW * 4 + 26, cy + 36), 'xor %d' % c['dist'], font=f12,
               fill=(0, 130, 0) if c['dist'] == 0 else (200, 0, 0))

    out = os.path.join(JS, 'js19_font_atlas_cells.png')
    img.save(out, optimize=True)
    print('[out] %s  %dx%d  %d B' % (out, img.width, img.height, os.path.getsize(out)))


if __name__ == '__main__':
    main()
