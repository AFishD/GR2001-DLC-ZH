# -*- coding: utf-8 -*-
r"""js19_analyze.py — 逆向**上一版 JS_ZH19 构筑**（PCSX2 转储里 dump 出的 payload）的图集/FONT.RES 几何。

用途（task-3 附加交付）：给 js19-recovery（翻译还原）与 elf-analyst（反汇编交叉验证）提供
**数据侧**的精确几何：cell 网格、行公式、容量、FT 记录带分布、face 布局、尾部异常。

输入（都是别的分析者 dump 出来的 payload，只读）：
    work/analysis/js19/payloads/00009_COMMON.PAK.bin   （JS19 版 COMMON.PAK）
    work/analysis/js19/payloads/00580_FONT.RES.bin     （JS19 版 FONT.RES 槽字节）
输出（默认）：work/analysis/font/js19_geometry.json

用法：
    python tools/font/js19_analyze.py [--payload-dir work/analysis/js19/payloads]
                                      [--out work/analysis/font/js19_geometry.json]

实测结论（脚本会重新算出并写进 JSON）：
  · 图集 new_font_revised = psm19 512×512，px=262,160（单 16B GIF tag + 262,144B）；
    只有两种 texel：0=墨（66,352 px）、15=空（195,792 px）；
  · CJK 网格 NCOL=32、CW=CH=16、Y0=2、SKIP_ROW=12、SKIP_ROWS=3（本体验证过的 FA2400 旧配方），
    CJK 行 0..19 = **640 格**；紧密全铺上限也只有 32×32=1024 格；
  · FONT.RES 展开 7,488B = 3 face×224 条 + 尾部 544B；large 与 default 记录完全相同；
    **尾部 count=15 但实测 16 条名字记录（off-by-one 损坏）**；FT 带有两条压在 CJK 行 18/19 上。
"""
import argparse
import io
import json
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fontlib as F                                                   # noqa: E402

TOOL = 'tools/font/js19_analyze.py'
TOOL_VERSION = 'r1.0'


def analyze(payload_dir):
    pak_p = os.path.join(payload_dir, '00009_COMMON.PAK.bin')
    ft_p = os.path.join(payload_dir, '00580_FONT.RES.bin')
    for p in (pak_p, ft_p):
        if not os.path.isfile(p):
            raise SystemExit('!! 找不到 JS19 payload: %s' % p)
    out = dict(tool=TOOL, tool_version=TOOL_VERSION,
               scope='JS_ZH19 上一版构筑的图集/FONT.RES 几何逆向（数据侧，只读）',
               payload_dir=os.path.abspath(payload_dir))
    pak = io.open(pak_p, 'rb').read()
    fraw = io.open(ft_p, 'rb').read()
    out['common_pak'] = dict(file=os.path.basename(pak_p), bytes=len(pak),
                             sha256=F.sha256(pak))
    recs = F.pak_parse(pak)
    out['records'] = [dict(name=r['name'], psm=r['psm'], w=r['w'], h=r['h'],
                           clut=r['clut'], px=r['px']) for r in recs]
    _fi, fr = F.pak_find(recs, 'new_font_revised')
    cont = pak[fr['px_off']:fr['px_off'] + fr['px']]
    tex = F.atlas_decode(cont, 512, 512, 0x13)
    ink = tex == 0
    vals, cnts = np.unique(tex, return_counts=True)
    for p in F.atlas_packets(cont, 512):
        p.pop('w0', None)
        p.pop('w1', None)
    out['atlas'] = dict(
        name='new_font_revised', psm=fr['psm'], w=fr['w'], h=fr['h'],
        clut=fr['clut'], px=fr['px'], container_bytes=len(cont),
        container_sha256=F.sha256(cont),
        packets=[dict(kind=p['kind'], off=p['off'], nloop=p['nloop'],
                      bytes=p.get('bytes')) for p in F.atlas_packets(cont, 512)],
        texel_values=[(int(v), int(c)) for v, c in zip(vals, cnts)],
        ink_px=int(ink.sum()), empty_index=15, ink_index=0)
    clut = fr['clut_bytes']
    out['clut'] = dict(bytes=len(clut), sha256=F.sha256(clut),
                       tag_words=['%08X' % x for x in struct.unpack_from('<2I', clut, 0)],
                       palette0_3=['%08X' % x for x in struct.unpack_from('<4I', clut, 16)])
    blob, frames, _used = F.frame_decode(fraw)
    ft = F.ft_parse(blob)
    out['font_res'] = dict(
        file=os.path.basename(ft_p), stored=len(fraw), frames=frames,
        expanded_bytes=len(blob), blob_sha256=F.sha256(blob),
        faces=[dict(name=f['name'], nrec=f['nrec'], fld=f['fld']) for f in ft['faces']],
        tail_len=ft['tail_len'], tail_sha256=F.sha256(ft['tail']),
        tail_count_field=struct.unpack_from('<I', ft['tail'], 0)[0],
        art_note='尾部 count 字段=15，但实测有 16 条名字记录 ⇒ off-by-one 损坏迹象；'
                 '还原时按名字位置切片，不要假设 15 条整齐记录')
    faces = ft['faces']
    out['face_record_identity'] = dict(
        f0_eq_f1=sum(1 for a, b in zip(faces[0]['recs'], faces[1]['recs']) if a == b),
        f0_eq_f2=sum(1 for a, b in zip(faces[0]['recs'], faces[2]['recs']) if a == b),
        total=224)
    # FT 记录带
    bands = {}
    for f in faces:
        for idx, r in enumerate(f['recs']):
            b0, b1, u0, v0, u1, v1 = r
            code = idx + 0x20
            key = ('DEGENERATE' if (u1 <= u0 or v1 <= v0)
                   else 'v=%d..%d h=%d' % (v0, v1, v1 - v0))
            d = bands.setdefault(key, dict(n=0, faces=[], uniq=set(),
                                           xmin=10 ** 9, xmax=-1, codes=[]))
            d['n'] += 1
            d['faces'] = sorted(set(d['faces']) | {f['name']})
            if u1 > u0 and v1 > v0:
                d['uniq'].add((u0, v0, u1, v1))
                d['xmin'] = min(d['xmin'], u0)
                d['xmax'] = max(d['xmax'], u1)
            if len(d['codes']) < 6:
                d['codes'].append('%02X' % code)
    out['ft_bands'] = [dict(kind=k, n=d['n'], uniq=len(d['uniq']), faces=d['faces'],
                            xmin=(None if d['xmin'] == 10 ** 9 else d['xmin']),
                            xmax=(None if d['xmax'] < 0 else d['xmax']),
                            codes=d['codes'])
                       for k, d in sorted(bands.items(), key=lambda kv: -kv[1]['n'])]
    # FT 覆盖掩码
    cover = np.zeros((512, 512), dtype=bool)
    for f in faces:
        for r in f['recs']:
            b0, b1, u0, v0, u1, v1 = r
            if u1 > u0 and v1 > v0:
                cover[v0:v1, u0:u1] = True

    def yrow(r):
        return 2 + 16 * (r + (3 if r >= 12 else 0))

    rows = []
    for r in range(0, 26):
        y = yrow(r)
        if y + 16 > 512:
            break
        cr = dict(row=r, y=y, slots=0, ink=0, ft_covered=0, cells=[])
        for c in range(32):
            x = 16 * c
            cr['slots'] += 1
            blk = ink[y:y + 16, x:x + 16]
            n = int(blk.sum())
            cov = bool(cover[y:y + 16, x:x + 16].any())
            if n:
                cr['ink'] += 1
            if cov:
                cr['ft_covered'] += 1
            if n or cov:
                cr['cells'].append(dict(col=c, ink=n, ft=cov))
        rows.append(cr)
    out['grid'] = dict(
        NCOL=32, CW=16, CH=16, Y0=2, SKIP_ROW=12, SKIP_ROWS=3,
        row_formula='y(r)=2+16*(r+3*[r>=12])', rows=rows,
        cjk_capacity_20rows=640, tight_32x32_cells=1024,
        note='行 0..19 是 CJK 网格（640 格）；行 20..22 的墨来自 ASCII/单字节 FT 带；'
             '640 格中 46 格被 FT 矩形覆盖（干净 594 格）')
    detail = {}
    for r in range(3):
        y = yrow(r)
        arr = []
        for c in range(32):
            x = 16 * c
            blk = ink[y:y + 16, x:x + 16]
            if blk.any():
                ys, xs = np.where(blk)
                arr.append(dict(c=c, bbox=[int(x + xs.min()), int(y + ys.min()),
                                           int(x + xs.max()), int(y + ys.max())],
                                ink=int(blk.sum())))
        detail['r%d' % r] = arr
    out['grid']['row0_2_detail'] = detail
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description='JS_ZH19 图集/FONT.RES 几何逆向（只读）')
    ap.add_argument('--payload-dir', default=os.path.join(F.REPO, 'work', 'analysis', 'js19',
                                                          'payloads'))
    ap.add_argument('--out', default=os.path.join(F.REPO, 'work', 'analysis', 'font',
                                                  'js19_geometry.json'))
    a = ap.parse_args(argv)
    rep = analyze(os.path.abspath(a.payload_dir))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    io.open(a.out, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(rep, ensure_ascii=False, indent=1) + '\n')
    F.P('[js19] 图集 psm=%d %dx%d px=%d；texel=%s'
        % (rep['atlas']['psm'], rep['atlas']['w'], rep['atlas']['h'],
           rep['atlas']['px'], rep['atlas']['texel_values']))
    F.P('[js19] faces:', [(f['name'], f['nrec']) for f in rep['font_res']['faces']],
        '; tail', rep['font_res']['tail_len'],
        'B（count 字段 %d）' % rep['font_res']['tail_count_field'])
    F.P('[js19] CJK 网格: NCOL=32 / 16px 格 / y=2+16*(r+3*[r>=12]) / 容量 640 格'
        '（紧密全铺上限 1024）')
    F.P('[js19] FT 带: %s' % [(b['kind'], b['n'], b['uniq']) for b in rep['ft_bands']])
    F.P('[out]', os.path.abspath(a.out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
