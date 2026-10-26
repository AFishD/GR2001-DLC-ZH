# -*- coding: utf-8 -*-
"""compare_brief.py —— 生成“原版 vs 汉化版”同页对比图。

用法：
    python tools\\emu\\compare_brief.py --en <英文原版简报帧.png> --cn <汉化版简报帧.png> \
        --out work/analysis/emu/compare_<tag>.png [--tag v23]

输出：
    <out>            整页并排（上：EN，下：CN；左上角标注）
    <out 的 _crop>   简报文字区 + 任务目标区放大并排（便于看换行/对齐）
"""
import argparse
import os

from PIL import Image, ImageDraw, ImageFont


def font(size=22):
    for p in (r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\msyhbd.ttc'):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def label_panel(img, text, fnt, pad=26):
    w, h = img.size
    out = Image.new('RGB', (w, h + pad), (12, 16, 22))
    out.paste(img, (0, pad))
    d = ImageDraw.Draw(out)
    d.text((6, 2), text, fill=(255, 220, 120), font=fnt)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--en', required=True)
    ap.add_argument('--cn', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--tag', default='')
    a = ap.parse_args()
    fnt = font(24)
    en = Image.open(a.en).convert('RGB')
    cn = Image.open(a.cn).convert('RGB')
    # 整页并排（各缩放到宽 1000）
    def sc(im, w=1000):
        return im.resize((w, int(im.size[1] * w / im.size[0])))
    en_s, cn_s = sc(en), sc(cn)
    W = 1000
    H = en_s.size[1] + cn_s.size[1] + 60
    out = Image.new('RGB', (W, H), (12, 16, 22))
    out.paste(label_panel(en_s, 'EN original' + (' ' + a.tag if a.tag else ''), fnt), (0, 0))
    out.paste(label_panel(cn_s, 'CN v' + a.tag if a.tag else 'CN', fnt), (0, en_s.size[1] + 30))

    # 裁剪：顶部（简介/GR-C01）+ 简报正文首行 + 任务目标面板
    def crops(im):
        w, h = im.size
        return [
            im.crop((int(0.12 * w), int(0.02 * h), int(0.95 * w), int(0.12 * h))),
            im.crop((int(0.14 * w), int(0.12 * h), int(0.47 * w), int(0.45 * h))),
            im.crop((int(0.14 * w), int(0.50 * h), int(0.80 * w), int(0.88 * h))),
        ]
    en_c, cn_c = crops(en), crops(cn)
    tile_w = 1000
    rows = []
    for i in range(3):
        a1, b1 = en_c[i], cn_c[i]
        a1 = a1.resize((tile_w, int(a1.size[1] * tile_w / a1.size[0])))
        b1 = b1.resize((tile_w, int(b1.size[1] * tile_w / b1.size[0])))
        row = Image.new('RGB', (tile_w, a1.size[1] + b1.size[1] + 56), (12, 16, 22))
        d = ImageDraw.Draw(row)
        d.text((6, 2), ['header', 'briefing text', 'objectives'][i], fill=(255, 220, 120), font=fnt)
        row.paste(a1, (0, 26))
        d.text((6, a1.size[1] + 30), 'CN', fill=(255, 220, 120), font=fnt)
        row.paste(b1, (0, a1.size[1] + 54))
        rows.append(row)
    W2 = tile_w
    H2 = sum(r.size[1] + 20 for r in rows)
    crop_out = Image.new('RGB', (W2, H2), (12, 16, 22))
    y = 0
    for r in rows:
        crop_out.paste(r, (0, y))
        y += r.size[1] + 20

    out_dir = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(out_dir, exist_ok=True)
    out.save(a.out)
    crop_path = a.out.replace('.png', '_crop.png')
    crop_out.save(crop_path)
    print('saved', a.out)
    print('saved', crop_path)


if __name__ == '__main__':
    main()
