# -*- coding: utf-8 -*-
r"""extract_seed.py — 一次性从**本体汉化成品 ISO** 提取中文字库 seed（本地自备，不进 git）。

产出目录（默认 third_party/ref/zh_font_seed/，gitignored）：
    FONT_RES.MENU4.zh.bin    本体 MENU.IMG#4 FONT.RES 展开态（5,942B，引擎真正读的那份）
    FONT_RES.GR906.zh.bin    本体 GR.IMG#906 FONT.RES 展开态（同 5,942B；与 MENU#4 差 24B，留档）
    COMMON_PAK.MENU3.zh.bin  本体 MENU.IMG#3 COMMON.PAK（468,243B，含 1024×644 图集记录）
    charset_compiled_zh16.json  字符集副本（与 assets/charset/ 同源，记 sha256 交叉核对）
    meta.json                全部来源/偏移/大小/sha256/几何/统计

用法：
    python tools/font/extract_seed.py [--base-iso ...] [--out third_party/ref/zh_font_seed]
                                      [--no-register]     # 不写 third_party/readme.md
"""
import argparse
import io
import json
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fontlib as F                                                   # noqa: E402

TOOL = 'tools/font/extract_seed.py'
TOOL_VERSION = 'r1.0'


def main(argv=None):
    ap = argparse.ArgumentParser(description='提取本体中文字库 seed')
    ap.add_argument('--base-iso', default=F.BASE_ZH_ISO)
    ap.add_argument('--out', default=F.SEED_DIR)
    ap.add_argument('--charset', default=F.CHARSET)
    ap.add_argument('--no-register', action='store_true')
    a = ap.parse_args(argv)
    t0 = time.time()
    iso_path = os.path.abspath(a.base_iso)
    F.P('=' * 78)
    F.P('[1] 本体成品 ISO:', iso_path)
    iso = F.Iso(iso_path)
    try:
        size, sha = iso.size, F.sha256_file(iso_path)
        F.P('    尺寸 %d B ; sha256 %s' % (size, sha))
        roots = {e['name'].split(';')[0]: e for e in iso.root_entries()}
        F.P('    root:', [(e['name'], e['lba'], e['size']) for e in iso.root_entries()])
        gr_lba = roots['GR.IMG']['lba']
        menu_lba = roots['MENU.IMG']['lba']
        gr = F.img_entries(iso, gr_lba)
        menu = F.img_entries(iso, menu_lba)
        F.P('[2] GR.IMG @LBA %d (%d 条) ; MENU.IMG @LBA %d (%d 条)'
            % (gr_lba, len(gr), menu_lba, len(menu)))
        assert F.img_consistent(iso, gr, gr_lba)['ok'], 'GR.IMG 头部/根目录 size 不自洽'
        mcons = F.img_consistent(iso, menu, menu_lba)
        if not mcons['ok']:
            F.P('    [note] MENU.IMG 头部与根目录 size 不自洽（本体工程移位重建的遗留，仅记录）:',
                mcons)

        # ── FONT.RES：MENU#4（引擎真正读的）+ GR#906（副本）──
        m4 = menu[4]
        assert m4['name'] == 'FONT.RES', m4
        fraw = iso.read(m4['iso_off'], m4['stored'])
        fblob, frames, used = F.frame_decode(fraw)
        assert fblob, 'MENU#4 FONT.RES 解帧失败'
        ft = F.ft_parse(fblob)
        g906 = next(e for e in gr if e['name'] == 'FONT.RES')
        graw = iso.read(g906['iso_off'], g906['stored'])
        gblob, gframes, _ = F.frame_decode(graw)
        F.P('[3] FONT.RES MENU#4: stored=%d 帧=%s 展开=%d sha=%s'
            % (m4['stored'], frames, len(fblob), F.sha256(fblob)[:16]))
        F.P('    GR#%d: stored=%d 展开=%d sha=%s ; 与 MENU#4 差异字节=%d'
            % (g906['idx'], g906['stored'], len(gblob), F.sha256(gblob)[:16],
               sum(1 for x, y in zip(fblob, gblob) if x != y) if len(fblob) == len(gblob) else -1))
        for f in ft['faces']:
            F.P('    face %-8r nrec=%-3d fld=%s' % (f['name'], f['nrec'], f['fld']))

        # ── COMMON.PAK：MENU#3（中文图集）──
        m3 = menu[3]
        assert m3['name'] == 'COMMON.PAK', m3
        pak = iso.read(m3['iso_off'], m3['stored'])
        recs = F.pak_parse(pak)
        F.P('[4] COMMON.PAK MENU#3: stored=%d 记录=%d sha=%s'
            % (m3['stored'], len(recs), F.sha256(pak)[:16]))
        for r in recs:
            F.P('    %-24s psm=%2d %4dx%-4d clut=%-5d px=%-7d'
                % (r['name'], r['psm'], r['w'], r['h'], r['clut'], r['px']))
        fi, fr = F.pak_find(recs, 'new_font_revised')
        assert (fr['psm'], fr['w'], fr['h']) == (F.ATLAS_PSM, F.ATLAS_W, F.ATLAS_H), fr
        cont = pak[fr['px_off']:fr['px_off'] + fr['px']]
        clut = fr['clut_bytes']
        tex, empty, packets, segs = F.atlas_engine_image(cont, F.ATLAS_W, F.ATLAS_H, fr['psm'])
        stat = F.slot_ledger(tex, F.charset_load(a.charset))
        F.P('[5] 图集: %dx%d psm=0x%02X 容器=%d 空白索引=%d 墨 texel=%d 封包=%d 段=%d'
            % (fr['w'], fr['h'], fr['psm'], len(cont), empty, int((tex == 0).sum()),
               len(packets), len(segs)))
        F.P('    slot 账本: %s' % stat['stat'])
        # 图集容器逐字节核对（这是 build 唯一的像素来源）
        assert len(cont) == fr['w'] * fr['h'] // 2 + 16, (len(cont), fr['w'] * fr['h'] // 2 + 16)
        assert len(segs) == 11 and len(packets) == 23, (len(segs), len(packets))

        # ── charset ──
        cs_path = os.path.abspath(a.charset)
        cs_raw = io.open(cs_path, 'rb').read()
        cs = F.charset_load(cs_path)
        pua = [ch for ch in cs['enc_pair'] if 0xE000 <= ord(ch) <= 0xF8FF]
        slots = [F.slot_of(*p) for p in cs['enc_pair'].values()]
        F.P('[6] charset: %s (%d B sha=%s) single=%d pair=%d PUA=%d slot=[%d..%d]'
            % (os.path.basename(cs_path), len(cs_raw), F.sha256(cs_raw)[:16],
               len(cs['enc_single']), len(cs['enc_pair']), len(pua), min(slots), max(slots)))

        # ── 落盘 ──
        out = os.path.abspath(a.out)
        os.makedirs(out, exist_ok=True)
        files = {}

        def put(name, data):
            p = os.path.join(out, name)
            with open(p, 'wb') as fh:
                fh.write(data)
            files[name] = dict(bytes=len(data), sha256=F.sha256(data))
            F.P('    %-28s %9d B  sha256 %s' % (name, len(data), F.sha256(data)))

        F.P('[7] 写出 seed →', out)
        put('FONT_RES.MENU4.zh.bin', fblob)
        put('FONT_RES.GR906.zh.bin', gblob)
        put('COMMON_PAK.MENU3.zh.bin', pak)
        put('charset_compiled_zh16.json', cs_raw)
        meta = dict(
            tool=TOOL, tool_version=TOOL_VERSION,
            generated=time.strftime('%Y-%m-%d %H:%M:%S'),
            why='本体汉化成品的中文字库/图集 seed；build 时只读本目录 + 资料片英文原盘 + 本项目 assets',
            source_iso=dict(path=iso_path, bytes=size, sha256=sha),
            root=dict(gr_img_lba=gr_lba, menu_img_lba=menu_lba,
                      gr_entries=len(gr), menu_entries=len(menu)),
            font_res=dict(
                menu_index=4, menu_name=m4['name'], menu_stored=m4['stored'],
                menu_real=m4['real'], menu_off=m4['off'], frames=frames, blob_len=len(fblob),
                blob_sha256=F.sha256(fblob),
                gr_index=g906['idx'], gr_stored=g906['stored'], gr_real=g906['real'],
                blob_sha256_gr=F.sha256(gblob),
                copies_diff_bytes=sum(1 for x, y in zip(fblob, gblob) if x != y)
                if len(fblob) == len(gblob) else None,
                faces=[dict(name=f['name'], nrec=f['nrec'], fld=f['fld']) for f in ft['faces']],
                parsed_end=ft['parsed_end'], tail_len=ft['tail_len'],
                ascii_note='ASCII/单字节 FT 记录是 8×16 带（y=611..627 / 627..643 / 195..227），'
                           '汉字 pair 不占 FT 记录'),
            common_pak=dict(
                menu_index=3, menu_name=m3['name'], menu_stored=m3['stored'],
                menu_off=m3['off'], blob_sha256=F.sha256(pak), records=len(recs),
                record_names=[r['name'] for r in recs],
                font_record_index=fi),
            atlas=dict(psm=fr['psm'], w=fr['w'], h=fr['h'], clut_len=fr['clut'],
                       px=fr['px'], container_len=len(cont), container_sha256=F.sha256(cont),
                       clut_sha256=F.sha256(clut), packets=len(packets), segments=len(segs),
                       empty_index=empty, ink_texels=int((tex == 0).sum()),
                       seg_first_rows=[s[0] for s in segs],
                       seg_nbytes=[s[2] for s in segs],
                       packet_kinds=[p['kind'] for p in packets],
                       header_bytes=len(cont) - sum(s[2] for s in segs),
                       payload_bytes=sum(s[2] for s in segs)),
            grid=dict(NCOL=F.NCOL, CW=F.CW, CH=F.CH, Y0=F.GRID_Y0,
                      SKIP_ROW=F.GRID_SKIP_ROW, SKIP_ROWS=F.GRID_SKIP_ROWS,
                      lead=[hex(F.LEAD_LO), hex(F.LEAD_HI)],
                      trail=[hex(F.TRAIL_LO), hex(F.TRAIL_HI)],
                      capacity=F.PAIR_CAP,
                      formula='slot=(lead-0xA1)*94+(trail-0xA1); row=slot//64; col=slot%64; '
                              'x=16*col; y=3+16*(row+2*[row>=12])'),
            slot_ledger=stat['stat'],
            slot_rows=stat['rows'],
            charset=dict(path=cs_path, bytes=len(cs_raw), sha256=F.sha256(cs_raw),
                         single=len(cs['enc_single']), pair=len(cs['enc_pair']),
                         pua=len(pua), slot_min=min(slots), slot_max=max(slots)),
            files=files,
            register_note='见 third_party/readme.md：「zh_font_seed」小节登记（本地自备，绝不入 git）',
        )
        mp = os.path.join(out, 'meta.json')
        with io.open(mp, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=1)
            fh.write('\n')
        F.P('    %-28s %9d B  sha256 %s' % ('meta.json', os.path.getsize(mp),
                                            F.sha256_file(mp)[:16]))
    finally:
        iso.close()

    # ── 登记 third_party/readme.md（幂等） ──
    if not a.no_register:
        rp = os.path.join(F.REPO, 'third_party', 'readme.md')
        txt = io.open(rp, encoding='utf-8').read() if os.path.isfile(rp) else ''
        marker = '## zh_font_seed'
        if marker not in txt:
            lines = [
                '',
                '## zh_font_seed —— 本体汉化中文字库 seed（本地自备，不进 git）',
                '',
                '- 路径：`third_party/ref/zh_font_seed/`',
                '- 来源：本体汉化成品 ISO `work/builds/FINAL/Tom Clancy\'s Ghost Recon (ZH_CN).iso`'
                '（工程外只读盘），由 `tools/font/extract_seed.py` 一键提取。',
                '- 内容：FONT.RES 展开态（MENU#4 / GR#906 两份）、MENU#3 COMMON.PAK（含 1024×644'
                ' PSMT4 中文图集）、charset 副本、meta.json（全部 sha256/几何/账本）。',
                '- 用途：《幽灵行动：丛林风暴》资料片字库移植（task-3）build 的唯一中文字形来源；'
                'build = 资料片英文原盘 + 本 seed + 本项目 assets。',
                '- 提取脚本：`python tools/font/extract_seed.py`；核对：`meta.json` 里的 sha256。',
                '- **绝不入 git**（版权资产 + 体积；`.gitignore` 已忽略 `third_party/**`）。',
            ]
            txt = txt.rstrip('\n') + '\n' + '\n'.join(lines) + '\n'
            io.open(rp, 'w', encoding='utf-8', newline='\n').write(txt)
            F.P('[8] 已登记 third_party/readme.md')
        else:
            F.P('[8] third_party/readme.md 已有 zh_font_seed 小节（跳过）')
    F.P('=' * 78)
    F.P('DONE %.1fs' % (time.time() - t0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
