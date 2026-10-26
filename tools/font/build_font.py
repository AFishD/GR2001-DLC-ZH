# -*- coding: utf-8 -*-
r"""build_font.py — 方案 B 原型：把本体中文字库（seed）移植到资料片，产出**可验证的新 ISO**。

输入：
    · 资料片英文原盘（只读）           third_party/orig/ps2/[PS2] Tom Clancy's Ghost Recon - Jungle Storm (U).iso
    · 字库 seed（本地自备，只读）      third_party/ref/zh_font_seed/（tools/font/extract_seed.py 提取）
    · 本项目字符集                     assets/charset/charset_compiled_zh16.json
输出（默认写 work/analysis/font/，gitignored）：
    · <out-iso>            新 ISO（方案 B：1024×644 PSMT4 图集 / 2350 槽）
    · build_report.json    全部字节级数字与自证结果
    · PNG 预览             <前缀>_atlas_engine.png / <前缀>_sample30.png / <前缀>_ascii_band.png
    · docs/img/ 小图（可选 --docs-img，≤200KB）

构建算法（字节级，见 docs/ANALYSIS_FONT.md）：
  ① 新 FONT.RES 展开态 = 中文 large/default(224/224) + 中文 huge 96 条 ASCII + 128 条退化记录
     + **资料片原盘 522B 尾部样式表** ⇒ 恰好 7,466B；LZO(level7,m1,m4) → 帧 ~1.6KB ≤ 原槽 4,460B，
     原地覆盖 GR#580（stored/real/偏移全不变，尾部补 0）。
  ② 新 COMMON.PAK = 资料片 PAK，把 new_font_revised 记录换成 psm20/1024×644/px329,744；
     **像素容器 = seed 里本体成品那份 329,744B 逐字节拷贝**（11 段 GIF 流 + 末尾空 tag），
     CLUT 按资料片自己的 psm20 原生形状 80B 重建（12B 头 + 16 色 + u32 px_size）。
  ③ 新 PAK 不原地挤（会牵动 #10..#3110 的偏移字段），而是**放到 GR.IMG 末尾**：
     gr_off = align16(max(off+stored))；只改 GR#9 的 [6][7][8] 三字段、GR.IMG 头 +0x0、
     根目录 GR.IMG size（LE/BE）、PVD volume_space（LE/BE），ISO 尾部扩到新末扇区。
     其余 3110 条条目**一个字节都不动**。
  ④ 回读自证：解回去逐 texel 比对 seed 图集 xor==0（整平面 + 2350 槽逐格 + 544 条 FT 矩形），
     全部条目载荷逐字节不变，ISO9660 结构自洽。

用法：
    python tools/font/build_font.py                       # 只算 payload + 方案 A 数字，不写大 ISO
    python tools/font/build_font.py --out-iso work/analysis/font/GR_JS_ZH_FONT.iso   # 真出盘并自证
    python tools/font/build_font.py --plan-a              # 额外跑 1024×512 方案 A 原型
    python tools/font/build_font.py --demo-new-chars      # 演示「补画新字」+ 半字节安全回读 xor==0
"""
import argparse
import io
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fontlib as F                                                   # noqa: E402

TOOL = 'tools/font/build_font.py'
TOOL_VERSION = 'r1.0'
OUTDIR = os.path.join(F.REPO, 'work', 'analysis', 'font')


def P(*a):
    F.P(*a)


# ═══════════════════════════ 装载 ═══════════════════════════
def load_seed(seed_dir=None, charset_path=None):
    seed_dir = os.path.abspath(seed_dir or F.SEED_DIR)
    meta_p = os.path.join(seed_dir, 'meta.json')
    if not os.path.isfile(meta_p):
        raise SystemExit('!! seed 目录不完整（缺 meta.json）: %s\n'
                         '   先跑: python tools/font/extract_seed.py' % seed_dir)
    meta = json.load(io.open(meta_p, encoding='utf-8'))

    def rd(name):
        p = os.path.join(seed_dir, name)
        b = io.open(p, 'rb').read()
        want = meta['files'][name]['sha256']
        if F.sha256(b) != want:
            raise SystemExit('!! seed 文件 sha256 不符: %s' % name)
        return b

    ft_blob = rd('FONT_RES.MENU4.zh.bin')
    ft_blob_gr = rd('FONT_RES.GR906.zh.bin')
    pak = rd('COMMON_PAK.MENU3.zh.bin')
    cs_bytes = rd('charset_compiled_zh16.json')
    recs = F.pak_parse(pak)
    _fi, fr = F.pak_find(recs, 'new_font_revised')
    cont = pak[fr['px_off']:fr['px_off'] + fr['px']]
    clut = fr['clut_bytes']
    tex, empty, packets, segs = F.atlas_engine_image(cont, fr['w'], fr['h'], fr['psm'])
    ft = F.ft_parse(ft_blob)
    cs = F.charset_load(os.path.abspath(charset_path or F.CHARSET))
    assert F.sha256(cs_bytes) == meta['charset']['sha256'], 'charset 副本与 assets 里的不一致'
    return dict(meta=meta, ft_blob=ft_blob, ft_blob_gr=ft_blob_gr, ft=ft,
                pak=pak, recs=recs, font_rec=fr, container=cont, clut=clut,
                tex=tex, empty=empty, packets=packets, segs=segs, cs=cs,
                dir=seed_dir)


def load_dlc(iso_path=None):
    iso = F.Iso(iso_path or F.DLC_ISO)
    root = {e['name'].split(';')[0]: e for e in iso.root_entries()}
    lba = root['GR.IMG']['lba']
    ents = F.img_entries(iso, lba)
    cons = F.img_consistent(iso, ents, lba)
    ft_e = next(e for e in ents if e['name'] == 'FONT.RES')
    pak_e = next(e for e in ents if e['name'] == 'COMMON.PAK')
    font_raw = iso.read(ft_e['iso_off'], ft_e['stored'])
    font_blob, frames, _ = F.frame_decode(font_raw)
    pak = iso.read(pak_e['iso_off'], pak_e['stored'])
    return dict(iso=iso, path=iso.path, root=root, lba=lba, ents=ents,
                consist=cons, ft_e=ft_e, pak_e=pak_e,
                font_raw=font_raw, font_blob=font_blob, font_frames=frames,
                pak=pak, recs=F.pak_parse(pak))


# ═══════════════════════════ 主流程 ═══════════════════════════
def main(argv=None):
    ap = argparse.ArgumentParser(description='方案 B 字库移植原型（出可验证的新 ISO）')
    ap.add_argument('--dlc-iso', default=F.DLC_ISO)
    ap.add_argument('--seed', default=F.SEED_DIR)
    ap.add_argument('--out-iso', default=None, help='新 ISO 路径（不给=只算 payload/自检，不写大文件）')
    ap.add_argument('--outdir', default=OUTDIR)
    ap.add_argument('--clut-mode', choices=['native', 'zh'], default='native')
    ap.add_argument('--plan-a', action='store_true', help='额外做 1024×512 方案 A 原型（只读评估）')
    ap.add_argument('--demo-new-chars', action='store_true', help='演示补画新字（写进 seed 容器副本，仅自证）')
    ap.add_argument('--docs-img', action='store_true', help='把 1~2 张小图复制到 docs/img/（≤200KB）')
    ap.add_argument('--no-png', action='store_true')
    ap.add_argument('--verify-only', default=None,
                    help='只对已存在的新 ISO 跑回读自证（不重新出盘；用于模拟器占用输出文件时）')
    a = ap.parse_args(argv)
    t0 = time.time()
    os.makedirs(os.path.abspath(a.outdir), exist_ok=True)
    outdir = os.path.abspath(a.outdir)
    rep = dict(tool=TOOL, tool_version=TOOL_VERSION,
               generated=time.strftime('%Y-%m-%d %H:%M:%S'), mode='planB')

    # ---------- 装载 ----------
    P('=' * 78)
    P('[1] seed:', os.path.abspath(a.seed))
    seed = load_seed(a.seed)
    S = seed
    P('    中文字面: %d faces %s ; FONT.RES 展开 %d B sha=%s'
      % (len(S['ft']['faces']), [(f['name'], f['nrec']) for f in S['ft']['faces']],
         len(S['ft_blob']), F.sha256(S['ft_blob'])[:16]))
    P('    图集: %dx%d psm=0x%02X 容器 %d B sha=%s'
      % (S['font_rec']['w'], S['font_rec']['h'], S['font_rec']['psm'],
         len(S['container']), F.sha256(S['container'])[:16]))
    P('    slot 账本:', F.slot_ledger(S['tex'], S['cs'])['stat'])
    P('[2] DLC:', F.DLC_ISO)
    D = load_dlc(a.dlc_iso)
    P('    GR.IMG @LBA %d 条目 %d ; FONT.RES #%d stored=%d real=%d ; COMMON.PAK #%d stored=%d 记录=%d'
      % (D['lba'], len(D['ents']), D['ft_e']['idx'], D['ft_e']['stored'], D['ft_e']['real'],
         D['pak_e']['idx'], D['pak_e']['stored'], len(D['recs'])))
    P('    GR.IMG 自洽:', D['consist'])
    rep['input'] = dict(
        seed_dir=S['dir'], seed_font_sha256=F.sha256(S['ft_blob']),
        seed_container_sha256=F.sha256(S['container']),
        dlc_iso=os.path.abspath(D['path']), dlc_iso_sha256=None,   # 大文件按需算（下面 --out-iso 时算）
        dlc_font_entry=dict(idx=D['ft_e']['idx'], stored=D['ft_e']['stored'],
                            real=D['ft_e']['real'], off=D['ft_e']['off']),
        dlc_pak_entry=dict(idx=D['pak_e']['idx'], stored=D['pak_e']['stored'],
                           off=D['pak_e']['off']),
        dlc_img_consistent=D['consist'])

    # ---------- ① 新 FONT.RES ----------
    P('=' * 78)
    P('[3] 构造新 FONT.RES（中文面 + 资料片 522B 尾部样式表）')
    font_frame, merged, font_info = F.build_new_ft_frame(
        D['font_raw'], D['ft_e'], S['ft_blob'])
    P('    展开 %d B（= 资料片原 real %d）; LZO 帧 %d B ≤ 原槽 %d B (余 %d B)'
      % (font_info['merged_len'], D['ft_e']['real'], font_info['frame_len'],
         D['ft_e']['stored'], font_info['slack']))
    P('    faces:', [(f['name'], f['nrec']) for f in font_info['faces']],
      '; tail', font_info['tail_len'], 'B')
    rep['font_res'] = font_info
    # 逐 face 记录自证
    zf = {f['name']: f for f in S['ft']['faces']}
    nf = {f['name']: f for f in F.ft_parse(merged)['faces']}
    keep = {}
    for nm in ('large', 'default'):
        keep[nm] = sum(1 for x, y in zip(zf[nm]['recs'], nf[nm]['recs']) if x == y)
    keep['huge_0_95'] = sum(1 for x, y in zip(zf['huge']['recs'], nf['huge']['recs']) if x == y)
    deg = sum(1 for r in nf['huge']['recs'][96:] if r == [0, 0, 0, 0, 0, 0])
    rep['font_res']['records_check'] = dict(
        large_same=keep['large'], default_same=keep['default'],
        huge_0_95_same=keep['huge_0_95'], huge_96_223_degenerate=deg,
        tail_is_dlc=(F.ft_parse(merged)['tail'] == F.ft_parse(D['font_blob'])['tail']))

    # ---------- ② 新 COMMON.PAK ----------
    P('=' * 78)
    P('[4] 构造新 COMMON.PAK（图集记录换 1024×644 PSMT4；容器=seed 逐字节拷贝；CLUT=%s）'
      % a.clut_mode)
    new_pak, pak_info = F.build_new_pak(D['pak'], D['recs'], S,
                                        clut_mode=a.clut_mode)
    P('    PAK %d → %d B (Δ%+d) ; 命中记录 #%d 长 %d B ; CLUT %d B ; px %d'
      % (pak_info['pak_old_len'], pak_info['pak_new_len'], pak_info['delta'],
         pak_info['font_record_index'], pak_info['font_record_len'],
         pak_info['clut_len'], pak_info['px_size']))
    rep['common_pak'] = pak_info
    # 新 PAK 回读：记录名/其它记录字节/图集记录几何/像素容器
    nr = F.pak_parse(new_pak)
    assert [x['name'] for x in nr] == [x['name'] for x in D['recs']]
    _fi2, nf2 = F.pak_find(nr, 'new_font_revised')
    cont2 = new_pak[nf2['px_off']:nf2['px_off'] + nf2['px']]
    assert cont2 == S['container']
    rep['common_pak']['readback'] = dict(records=len(nr),
                                         names_ok=True, container_equal=True,
                                         psm=nf2['psm'], w=nf2['w'], h=nf2['h'],
                                         clut=nf2['clut'], px=nf2['px'])

    # ---------- ③ 方案 A 原型（可选） ----------
    if a.plan_a:
        P('=' * 78)
        P('[5] 方案 A 原型：1024×512 PSMT4 单包（原地等大小 262,160B，2048 格）')
        led = F.slot_ledger(S['tex'], S['cs'])['stat']
        pa = F.plan_a_prototype(S, S['ft']['faces'], led['real_chars'])
        P('    容器 %d B（== 资料片原 px 262,160? %s）; 单包回读 xor=%d'
          % (pa['container_len'], pa['container_len'] == 262160, pa['xor']))
        P('    512 行以外丢失 slot: %d ; FT 带面积 %d px ≈ %d 格；'
          '真汉字 %d + FT 带 %d = %d 格 > 2048 格 ⇒ fits=%s'
          % (pa['slots_lost_beyond_512'], pa['ft_band_px'], pa['ft_band_cells'],
             led['real_chars'], pa['ft_band_cells'], pa['cells_needed'], pa['fits']))
        rep['plan_a'] = dict(container_len=pa['container_len'], unit_xor=pa['xor'],
                             slots_lost_beyond_512=pa['slots_lost_beyond_512'],
                             ft_band_px=pa['ft_band_px'], ft_band_cells=pa['ft_band_cells'],
                             real_chars=led['real_chars'], cells_needed=pa['cells_needed'],
                             cells_1024x512=pa['cells_1024x512'], fits=pa['fits'],
                             verdict='不可行：内容装不下（2038+ 格 vs 2048 格，且无新字余量）')

    # ---------- ④ 补画新字演示（可选） ----------
    if a.demo_new_chars:
        P('=' * 78)
        P('[6] 「补画新字」演示（写进 seed 容器副本，不参与出盘；验证 4bpp 半字节安全 + 回读 xor==0）')
        led = F.slot_ledger(S['tex'], S['cs'])
        real_slots = {F.slot_of(*p) for ch, p in S['cs']['enc_pair'].items()
                      if not (0xE000 <= ord(ch) <= 0xF8FF)}
        free = []
        for slot in range(F.PAIR_CAP):
            row, col, x, y = F.slot_cell(slot)
            if col == F.NCOL - 1 or slot in real_slots:
                continue
            if (S['tex'][y:y + F.CH, x:x + F.CW] == 0).any():   # 0 = 墨；格内有墨不能用
                continue
            free.append(slot)
        P('    可用空格：%d 个（其中 PUA 占位槽 %d / 完全未映射空槽 %d）'
          % (len(free), sum(1 for s in free if s in {F.slot_of(*p) for p in S["cs"]["enc_pair"].values()}),
             sum(1 for s in free if s not in {F.slot_of(*p) for p in S["cs"]["enc_pair"].values()})))
        assert len(free) >= 20, len(free)
        from PIL import ImageFont
        fnt = ImageFont.truetype(F.TTF, 16)
        cand = '鹏巍鑫犇淼焱垚犟骥骧龘靐齉爩鱻麤'
        chars = []
        for ch in cand:
            img = __import__('PIL.Image', fromlist=['Image']).new('L', (32, 32), 255)
            from PIL import ImageDraw
            ImageDraw.Draw(img).text((8, 8), ch, font=fnt, fill=0)
            if (np.asarray(img)[8:24, 8:24] < 128).any():
                chars.append(ch)
            if len(chars) >= 3:
                break
        assign = {ch: free[i] for i, ch in enumerate(chars)}
        new_cont, draw_rep = F.draw_glyphs(S['container'], F.ATLAS_W, F.ATLAS_H,
                                           0x14, assign, os.path.join(F.REPO, 'third_party', 'fonts', '方正像素16.ttf'))
        new_tex, _e, _pk, _sg = F.atlas_engine_image(new_cont, F.ATLAS_W, F.ATLAS_H, 0x14)
        changed_cells = 0
        for slot in range(F.PAIR_CAP):
            row, col, x, y = F.slot_cell(slot)
            if not np.array_equal(new_tex[y:y + F.CH, x:x + F.CW], S['tex'][y:y + F.CH, x:x + F.CW]):
                changed_cells += 1
        rep['demo_new_chars'] = dict(assign={ch: assign[ch] for ch in assign},
                                     draws=draw_rep, changed_slots=changed_cells)
        P('    补画 %s → slot %s ; 逐格回读 xor: %s ; 全图变化格数=%d（应=补画数 %d）'
          % (''.join(assign), list(assign.values()),
             [d['readback_ok'] for d in draw_rep], changed_cells, len(assign)))

    # ---------- ⑤ 出盘 + 回读自证（可选） ----------
    if a.verify_only:
        P('=' * 78)
        P('[7v] 只回读自证:', os.path.abspath(a.verify_only))
        iso_o = D['iso']
        o = F.Iso(a.verify_only)
        try:
            oe = F.img_entries(o)
            oh = F.img_header(o)
            layout_new = dict(new_off=oe[9]['off'], new_last_end=F.img_last_end(oe),
                              last_end=F.img_last_end(D['ents']),
                              root_size_new=oh['total'], iso_new_size=o.size,
                              root_size_old=iso_o.find_root('GR.IMG')['size'],
                              gr_base=o.find_root('GR.IMG')['lba'] * F.SEC,
                              vol_new=o.pvd()['volume_space_le'],
                              vol_old=F.img_header(iso_o)['total'] and
                                      iso_o.pvd()['volume_space_le'])
        finally:
            o.close()
        new_pak, _pi = F.build_new_pak(D['pak'], D['recs'], S, clut_mode=a.clut_mode)
        exp = dict(iso_new_size=layout_new['iso_new_size'],
                   root_size_new=layout_new['root_size_new'],
                   merged_sha256=F.sha256(merged), charset=S['cs'],
                   pak_len=len(new_pak))
        ver = F.verify_plan_b(iso_o.path, os.path.abspath(a.verify_only), S, exp,
                              layout_new=layout_new)
        rep['verify'] = ver
        rep['output_iso'] = os.path.abspath(a.verify_only)
        rep['output_iso_sha256'] = F.sha256_file(os.path.abspath(a.verify_only))
        for c in ver['checks']:
            P('    ', c)
        P('    结论:', 'PASS' if ver['ok'] else 'FAIL')
        # 若已有 build_report.json，把新的 verify 段合并进去
        rp0 = os.path.join(outdir, 'build_report.json')
        if os.path.isfile(rp0):
            old = json.load(io.open(rp0, encoding='utf-8'))
            old['verify'] = ver
            old['output_iso'] = rep['output_iso']
            old['output_iso_sha256'] = rep['output_iso_sha256']
            old['verify_only'] = True
            rep = old
    # ---------- ⑤ 出盘 + 回读自证（可选） ----------
    if a.out_iso and not a.verify_only:
        P('=' * 78)
        P('[7] 方案 B 落盘（只改 GR#9 三字段 / GR.IMG 头 / 根目录 size / PVD volume / 新 PAK 追加）')
        iso = D['iso']
        layout = F.plan_b_layout(iso, D['ents'], len(new_pak))
        P('    GR.IMG+0x%X 放新 PAK %d B ; 声明大小 %d → %d ; ISO %d → %d B (Δ%+d, +%d 扇区)'
          % (layout['new_off'], len(new_pak), layout['root_size_old'],
             layout['root_size_new'], layout['iso_old_size'], layout['iso_new_size'],
             layout['iso_grow'], layout['vol_new'] - layout['vol_old']))
        rep['layout'] = {k: v for k, v in layout.items() if k != 'iso'}
        # 先算出盘前 packed 容器（像素级）
        F.write_plan_b_iso(D['iso'].path, os.path.abspath(a.out_iso), layout,
                           D['ents'], new_pak, font_frame, D['ft_e'])
        rep['output_iso'] = os.path.abspath(a.out_iso)
        rep['output_iso_sha256'] = F.sha256_file(os.path.abspath(a.out_iso))
        P('[8] 回读自证……')
        exp = dict(iso_new_size=layout['iso_new_size'], root_size_new=layout['root_size_new'],
                   merged_sha256=F.sha256(merged), charset=S['cs'],
                   pak_len=len(new_pak))
        ver = F.verify_plan_b(D['iso'].path, os.path.abspath(a.out_iso), S, exp,
                              layout_new=layout)
        rep['verify'] = ver
        for c in ver['checks']:
            P('    ', c)
        P('    结论:', 'PASS' if ver['ok'] else 'FAIL')

    # ---------- ⑥ PNG 预览 ----------
    if not a.no_png:
        P('=' * 78)
        P('[9] PNG 预览 →', outdir)
        try:
            from PIL import Image, ImageDraw
            tex = S['tex']
            p_atlas = os.path.join(outdir, 'planB_atlas_engine_1024x644.png')
            F.save_atlas_png(tex, p_atlas, S['empty'])
            # 30 个汉字放大（按 slot 升序抽 30 个真汉字）
            chars = [(F.slot_of(*p), ch) for ch, p in S['cs']['enc_pair'].items()
                     if not (0xE000 <= ord(ch) <= 0xF8FF)]
            chars.sort()
            step = max(1, len(chars) // 30)
            pick = chars[::step][:30]
            SC = 3
            sheet = Image.new('RGB', (10 * (F.CW * SC + 2) + 2, 3 * (F.CH * SC + 2) + 2),
                              (255, 255, 255))
            for i, (slot, ch) in enumerate(pick):
                row, col, x, y = F.slot_cell(slot)
                blk = Image.frombytes('L', (F.CW, F.CH),
                                      np.where(tex[y:y + F.CH, x:x + F.CW] == 0, 0, 255)
                                      .astype(np.uint8).tobytes()).convert('RGB')
                blk = blk.resize((F.CW * SC, F.CH * SC), Image.NEAREST)
                sheet.paste(blk, (2 + (i % 10) * (F.CW * SC + 2),
                                  2 + (i // 10) * (F.CH * SC + 2)))
            p_sample = os.path.join(outdir, 'planB_sample30_cjk.png')
            sheet.save(p_sample, optimize=True)
            # ASCII/单字节带放大（y=592..644 两行带）
            band = Image.frombytes('L', (1024, 52),
                                   np.where(tex[592:644, :] == 0, 0, 255)
                                   .astype(np.uint8).tobytes()).convert('RGB')
            band = band.resize((2048, 104), Image.NEAREST)
            p_band = os.path.join(outdir, 'planB_ascii_band.png')
            band.save(p_band, optimize=True)
            rep['png'] = {k: dict(path=v, bytes=os.path.getsize(v))
                          for k, v in (('atlas', p_atlas), ('sample30', p_sample),
                                       ('ascii_band', p_band))}
            P('    ', {k: (v['bytes']) for k, v in rep['png'].items()})
            # docs/img 小图（≤200KB）
            if a.docs_img:
                ddir = os.path.join(F.REPO, 'docs', 'img')
                os.makedirs(ddir, exist_ok=True)
                copied = {}
                for key, dst in (('atlas', 'font_atlas_1024x644.png'),
                                 ('sample30', 'font_sample30_cjk.png')):
                    src = rep['png'][key]['path']
                    if os.path.getsize(src) <= 200 * 1024:
                        dd = os.path.join(ddir, dst)
                        io.open(dd, 'wb').write(io.open(src, 'rb').read())
                        copied[dst] = os.path.getsize(dd)
                rep['docs_img'] = copied
                P('    docs/img:', copied)
        except Exception as ex:                                    # noqa: BLE001
            P('    PNG 生成失败:', ex)
            rep['png_error'] = '%s: %s' % (type(ex).__name__, ex)

    # ---------- ⑦ 报告 ----------
    rep['one_line'] = (
        '方案 B 原型：新 COMMON.PAK %d B（图集 psm20 1024×644 px=%d）+ 合并 FONT.RES %d B'
        '（帧 %d B，face 224/224/224，尾部=资料片 522B）；2350 槽全保留（1966 真汉字原样），'
        '其中 %d 格可改给资料片新字（实测 %d 格当前零墨、可直接补画）。'
        % (pak_info['pak_new_len'], pak_info['px_size'], font_info['merged_len'],
           font_info['frame_len'], S['meta']['slot_ledger']['usable_free'],
           S['meta']['slot_ledger']['usable_free'] - 2))
    rep['seconds'] = round(time.time() - t0, 1)
    rp = os.path.join(outdir, 'build_report.json')
    io.open(rp, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(rep, ensure_ascii=False, indent=1) + '\n')
    P('=' * 78)
    P('报告:', rp)
    P('一句话:', rep['one_line'])
    P('DONE %.1fs' % (time.time() - t0))
    return 0 if (('verify' not in rep) or rep['verify']['ok']) else 1


if __name__ == '__main__':
    sys.exit(main())
