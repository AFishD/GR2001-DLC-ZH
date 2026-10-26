# -*- coding: utf-8 -*-
r"""font_probe.py — 字库/图集探测器（只读）：对任意一张盘回答「字库长什么样、装在哪儿」。

用法：
    python tools/font/font_probe.py --iso <盘.iso> [--img gr|menu] [--out <目录>]
                                    [--png] [--json <文件>]

探查顺序（全部自动，只读 mmap）：
  ① ISO9660：PVD / root / GR.IMG、MENU.IMG 的 LBA 与声明大小；
  ② IMG：条目表头部（声明大小 / 名字表 / 条目表边界 / 24 条未知字段抽样）；
  ③ FONT.RES：LZO 帧链、三 face 的 fld/nrec、FT 矩形按 (v0,v1) 分带（带 x 范围/去重数/face）；
  ④ COMMON.PAK：全部记录（名字/psm/w/h/clut/px）；
  ⑤ 图集：封包序列（PT/A+D/IMAGE）、SSAY、数据区、引擎图、空白索引、墨 texel；
  ⑥ 网格账本（若图集几何与本体 K2 口径一致）：每行 slot 数 / 在用 / 真字 / PUA / 墨 / 空；
  ⑦ 可选 PNG：引擎图、样本 30 汉字、ASCII/单字节带放大。

退出码：0 = 成功；2 = 找不到 FONT.RES / COMMON.PAK。
"""
import argparse
import io
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fontlib as F                                                   # noqa: E402

TOOL = 'tools/font/font_probe.py'
TOOL_VERSION = 'r1.0'


def find_img(iso, which):
    """按 --img 选 IMG：gr = GR.IMG；menu = MENU.IMG（不存在则回落 GR.IMG）。"""
    root = {e['name'].split(';')[0]: e for e in iso.root_entries()}
    order = [('menu', 'MENU.IMG'), ('gr', 'GR.IMG')] if which == 'menu' else \
            [('gr', 'GR.IMG'), ('menu', 'MENU.IMG')]
    for tag, nm in order:
        if nm in root:
            return tag, root[nm]['lba'], root[nm]
    raise SystemExit('!! 根目录里既没有 GR.IMG 也没有 MENU.IMG')


def find_font_pak(iso, lba):
    """在该 IMG 里找 FONT.RES 与 COMMON.PAK（取第一个同名条目）。"""
    ents = F.img_entries(iso, lba)
    ft = next((e for e in ents if e['name'] == 'FONT.RES'), None)
    pak = next((e for e in ents if e['name'] == 'COMMON.PAK'), None)
    return ents, ft, pak


def ft_bands(faces):
    """FT 矩形按 (v0,v1) 分带：记录数 / 去重矩形 / x 范围 / 涉及 face。"""
    out = {}
    for fi, f in enumerate(faces):
        for idx, r in enumerate(f['recs']):
            b0, b1, u0, v0, u1, v1 = r
            code = idx + 0x20
            if u1 <= u0 or v1 <= v0:
                d = out.setdefault('DEGENERATE', dict(key='DEGENERATE', records=0, faces=[],
                                                     uniq=set(), codes=[]))
                d['records'] += 1
                d['faces'] = sorted(set(d['faces']) | {f['name']})
                continue
            key = 'v=%d..%d h=%d' % (v0, v1, v1 - v0)
            d = out.setdefault(key, dict(key=key, records=0, faces=[], uniq=set(), codes=[],
                                         xmin=10 ** 9, xmax=-1))
            d['records'] += 1
            d['faces'] = sorted(set(d['faces']) | {f['name']})
            d['uniq'].add((u0, v0, u1, v1))
            d['xmin'] = min(d['xmin'], u0)
            d['xmax'] = max(d['xmax'], u1)
            if len(d['codes']) < 6:
                d['codes'].append((f['name'], '%02X' % code))
    res = []
    for k, d in out.items():
        d = dict(d)
        d['uniq'] = len(d.pop('uniq'))
        res.append(d)
    res.sort(key=lambda x: -x['records'])
    return res


def probe(iso_path, which='gr', charset_path=None, png=False, out_dir=None, verbose=True):
    rep = dict(tool=TOOL, tool_version=TOOL_VERSION, iso=os.path.abspath(iso_path))
    iso = F.Iso(iso_path)
    try:
        rep['iso_size'] = iso.size
        pvd = iso.pvd()
        rep['pvd'] = dict(volume_id=pvd['volume_id'],
                          volume_space_le=pvd['volume_space_le'],
                          volume_space_be=pvd['volume_space_be'],
                          root_lba=pvd['root_lba'], root_size=pvd['root_size'])
        rep['root'] = [dict(name=e['name'], lba=e['lba'], size=e['size'], is_dir=e['is_dir'])
                       for e in iso.root_entries()]
        tag, lba, img_root = find_img(iso, which)
        rep['img'] = dict(tag=tag, lba=lba, root=img_root)
        hdr = F.img_header(iso, lba)
        ents = F.img_entries(iso, lba)
        cons = F.img_consistent(iso, ents, lba)
        rep['img'].update(header=dict(declared=hdr['total'], names_off=hdr['names_off'],
                                      names_end=hdr['names_end'], tab_end=hdr['tab_end'],
                                      first_off=hdr['first_off'], aux_off=hdr['aux_off']),
                          entries=len(ents), consistent=cons)
        _ents, ft_e, pak_e = find_font_pak(iso, lba)
        if ft_e is None or pak_e is None:
            raise SystemExit('!! 该 IMG 里找不到 FONT.RES(%s) / COMMON.PAK(%s)'
                             % (ft_e and ft_e['name'], pak_e and pak_e['name']))
        # ---- FONT.RES ----
        fraw = iso.read(ft_e['iso_off'], ft_e['stored'])
        fblob, frames, used = F.frame_decode(fraw)
        ft = F.ft_parse(fblob) if fblob else dict(faces=[], tail=b'', parsed_end=0, magic='?')
        rep['font'] = dict(name=ft_e['name'], idx=ft_e['idx'], stored=ft_e['stored'],
                           real=ft_e['real'], off=ft_e['off'], frames=frames,
                           blob_len=len(fblob), blob_sha256=F.sha256(fblob) if fblob else None,
                           magic=ft.get('magic'), nfaces=len(ft['faces']),
                           parsed_end=ft.get('parsed_end'), tail_len=len(ft.get('tail', b'')),
                           tail_sha256=F.sha256(ft['tail']) if ft.get('tail') else None,
                           faces=[dict(name=f['name'], nrec=f['nrec'], fld=f['fld'])
                                  for f in ft['faces']])
        if ft['faces']:
            rep['font']['bands'] = ft_bands(ft['faces'])
        # ---- PAK ----
        pak = iso.read(pak_e['iso_off'], pak_e['stored'])
        recs = F.pak_parse(pak)
        rep['pak'] = dict(name=pak_e['name'], idx=pak_e['idx'], stored=pak_e['stored'],
                          real=pak_e['real'], off=pak_e['off'],
                          sha256=F.sha256(pak), records=len(recs),
                          list=[dict(name=r['name'], psm=r['psm'], w=r['w'], h=r['h'],
                                     clut=r['clut'], px=r['px']) for r in recs])
        fr = next((r for r in recs if r['name'] == 'new_font_revised'), None)
        if fr is None:
            raise SystemExit('!! PAK 里没有 new_font_revised')
        cont = pak[fr['px_off']:fr['px_off'] + fr['px']]
        tex, empty, packets, segs = F.atlas_engine_image(cont, fr['w'], fr['h'], fr['psm'])
        stride = fr['w'] // 2 if fr['psm'] == 0x14 else fr['w']
        rep['atlas'] = dict(
            psm=fr['psm'], w=fr['w'], h=fr['h'], clut=fr['clut'], px=fr['px'],
            container_len=len(cont), container_sha256=F.sha256(cont),
            clut_sha256=F.sha256(fr['clut_bytes']),
            packets=[dict(kind=p['kind'], off=p['off'], nloop=p['nloop'], flg=p['flg'],
                          nreg=p['nreg'], eop=p['eop'], bytes=p.get('bytes'),
                          first_row=p.get('first_row'), ssay=p.get('ssay'))
                     for p in packets],
            segments=[[s[0], s[1], s[2]] for s in segs],
            seg_first_rows=[s[0] for s in segs],
            payload_bytes=sum(s[2] for s in segs),
            header_bytes=len(cont) - sum(s[2] for s in segs),
            rows_payload=sum(s[2] for s in segs) / float(stride),
            empty_index=int(empty),
            ink_texels=int((tex == 0).sum()),
            texel_hist=[int(x) for x in np.bincount(tex.ravel(), minlength=16)])
        # ---- 网格账本（几何匹配时） ----
        geom_ok = (fr['psm'] == F.ATLAS_PSM and fr['w'] == F.ATLAS_W and fr['h'] == F.ATLAS_H)
        rep['geometry_matches_k2'] = bool(geom_ok)
        if geom_ok and charset_path:
            cs = F.charset_load(charset_path)
            led = F.slot_ledger(tex, cs)
            rep['slot_ledger'] = led['stat']
            rep['slot_rows'] = led['rows']
            # 抽样 30 个真汉字 vs 方正像素16 TTF 模板（逐像素 xor；证明 slot→格位公式与字形都在）
            ttf = os.path.join(F.REPO, 'third_party', 'fonts', '方正像素16.ttf')
            if os.path.isfile(ttf):
                try:
                    from PIL import Image, ImageDraw, ImageFont
                    fnt = ImageFont.truetype(ttf, 16)
                    chars = sorted(((F.slot_of(*p), ch) for ch, p in cs['enc_pair'].items()
                                    if not (0xE000 <= ord(ch) <= 0xF8FF)))
                    step = max(1, len(chars) // 30)
                    pick = chars[::step][:30]
                    items, ok = [], 0
                    ink = tex == 0
                    for (slot, ch) in pick:
                        row, col, x, y = F.slot_cell(slot)
                        img = Image.new('L', (32, 32), 255)
                        ImageDraw.Draw(img).text((8, 8), ch, font=fnt, fill=0)
                        tpl = np.asarray(img)[8:24, 8:24] < 128
                        xor = int((tpl ^ ink[y:y + F.CH, x:x + F.CW]).sum())
                        items.append(dict(char=ch, slot=slot, cell=[x, y], xor=xor))
                        ok += (xor == 0)
                    rep['ttf_sample30'] = dict(n=len(items), xor0=ok, bad=len(items) - ok,
                                               items=items[:30])
                except Exception as ex:                            # noqa: BLE001
                    rep['ttf_sample30'] = dict(error='%s: %s' % (type(ex).__name__, ex))
        # ---- PNG ----
        if png:
            out_dir = os.path.abspath(out_dir or os.path.join(
                F.REPO, 'work', 'analysis', 'font', 'probe'))
            os.makedirs(out_dir, exist_ok=True)
            rep['png'] = {}
            rep['png']['atlas'] = dict(
                path=os.path.join(out_dir, 'atlas_engine.png'),
                bytes=F.save_atlas_png(tex, os.path.join(out_dir, 'atlas_engine.png'), int(empty)))
            try:
                from PIL import Image
                im = Image.open(rep['png']['atlas']['path'])
                rep['png']['atlas']['size'] = list(im.size)
            except Exception:                                    # noqa: BLE001
                pass
        if verbose:
            _print_report(rep)
    finally:
        iso.close()
    return rep


def _print_report(rep):
    F.P('=' * 78)
    F.P('盘:', rep['iso'], '(%d B)' % rep['iso_size'])
    F.P('PVD:', rep['pvd'])
    F.P('root:', [(e['name'], e['lba'], e['size']) for e in rep['root']])
    F.P('IMG:', rep['img']['tag'], '@LBA', rep['img']['lba'],
        '条目 %d' % rep['img']['entries'], '自洽', rep['img']['consistent'])
    F.P('FONT.RES:', rep['font']['name'], '#%d' % rep['font']['idx'],
        'stored=%d real=%d 帧=%s 展开=%d sha=%s'
        % (rep['font']['stored'], rep['font']['real'], rep['font']['frames'],
           rep['font']['blob_len'], (rep['font']['blob_sha256'] or '')[:16]))
    for f in rep['font']['faces']:
        F.P('  face %-8r nrec=%-3d fld=%s' % (f['name'], f['nrec'], f['fld']))
    F.P('  tail %d B sha=%s' % (rep['font']['tail_len'],
                                (rep['font']['tail_sha256'] or '')[:16]))
    for b in rep['font'].get('bands') or []:
        F.P('  FT 带 %-22s rec=%-4d uniq=%-4s x=[%s..%s] faces=%s'
            % (b['key'], b['records'], b.get('uniq'), b.get('xmin'), b.get('xmax'), b['faces']))
    F.P('PAK:', rep['pak']['name'], '#%d' % rep['pak']['idx'],
        'stored=%d 记录=%d sha=%s' % (rep['pak']['stored'], rep['pak']['records'],
                                      rep['pak']['sha256'][:16]))
    for r in rep['pak']['list']:
        F.P('  %-24s psm=%2d %4dx%-4d clut=%-5d px=%-7d'
            % (r['name'], r['psm'], r['w'], r['h'], r['clut'], r['px']))
    a = rep['atlas']
    F.P('图集: %dx%d psm=0x%02X clut=%d px=%d 容器 sha=%s'
        % (a['w'], a['h'], a['psm'], a['clut'], a['px'], a['container_sha256'][:16]))
    F.P('  封包 %d 个 / 数据段 %d 个 / payload=%d B (%.3f 行) / 头=%d B / 空白索引=%d / 墨=%d'
        % (len(a['packets']), len(a['segments']), a['payload_bytes'],
           a['rows_payload'], a['header_bytes'], a['empty_index'], a['ink_texels']))
    F.P('  SSAY:', a['seg_first_rows'])
    F.P('  texel 直方图:', a['texel_hist'])
    if 'ttf_sample30' in rep:
        t = rep['ttf_sample30']
        F.P('TTF 抽样 30 汉字: xor==0 %s / %s（%s）'
            % (t.get('xor0'), t.get('n'), t.get('error', '与方正像素16 模板逐像素比对')))
    if 'slot_ledger' in rep:
        F.P('slot 账本:', rep['slot_ledger'])
        for r in rep['slot_rows']:
            F.P('  r=%-2d y=%-4d slots=%-2d used=%-2d real=%-2d pua=%-2d ink=%-2d blank=%-2d col63=%-2d'
                % (r['row'], r['y'], r['slots'], r['used'], r['real'], r['pua'],
                   r['ink'], r['blank'], r['col63']))
    if 'png' in rep:
        F.P('PNG:', {k: v['path'] for k, v in rep['png'].items()})


def main(argv=None):
    ap = argparse.ArgumentParser(description='字库/图集探测器（只读）')
    ap.add_argument('--iso', default=F.DLC_ISO)
    ap.add_argument('--img', choices=['gr', 'menu'], default='gr')
    ap.add_argument('--charset', default=F.CHARSET)
    ap.add_argument('--out', default=None, help='PNG 输出目录')
    ap.add_argument('--json', default=None, help='把报告写成 JSON')
    ap.add_argument('--png', action='store_true')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv)
    rep = probe(a.iso, a.img, a.charset, png=a.png, out_dir=a.out, verbose=not a.quiet)
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        io.open(a.json, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(rep, ensure_ascii=False, indent=1) + '\n')
        F.P('[out]', a.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
