# -*- coding: utf-8 -*-
r"""patch_zh138_glyphs61.py — 把 **61 个"已登记、盘上无像素"的真汉字** 画进它们自己的槽位。

## 背景 (docs/REPORT_FONT_STATE.md §A.3, 2026-10-20 fix/font 轮)
`charset_compiled_zh16.json` 的 `_expand_cap2400.real_chars` 登记了槽 1872..1935 的 64 个
真汉字 {槽位: [字, 频次]}, 但其中 **61 个槽位在图集里一个墨点都没有** (鼠 弧 撒 兽 埋 匍 匐 签
趴 钮 …)。`方正像素16.ttf` 能渲染它们 (不是字体缺字) ⇒ 这是"漏画", 不是"无源"。

## 本工具做什么 (只有这一件事)
用**与现有 1,874 个槽位完全相同**的配方渲染这 61 个字, 画进各自**已登记**的槽位:

    ImageFont.truetype('方正像素16.ttf', 16) → 32×32 白底 → text((8,8)) → 取 [8:24, 8:24]
    → `< 128` 为墨 (2 值, 无灰度) —— 与 gen_font16.render16 / glyph_audit.render16 /
    work/builds/GR_FONTSTATE/tools/verify_font_state.py 逐字同款。

★ **不动的东西** (工具会逐项断言):
  · 图集几何: w/h/psm/px_size/段数/payload/48B 包头 —— 全部不变;
  · 其它 2,239 个已登记格 + 全部非字符像素 (icon 带 / EN 带) —— 逐格 xor 必须为 0;
  · 码位 / charset / FT 记录 / ELF —— 一个字不动 ⇒ **ELF CRC 不变, 旧存档可用**;
  · 61 个目标格里原本就是**全空** (零墨), 因此本工具只会"加墨", 不会擦掉任何已有像素。

## 用法

    # 只算不写 (给数字, 不产盘)
    python patch_zh138_glyphs61.py --iso <src.iso> --dry-run --report out.json

    # 真写: 拷一份到 --out, 只把像素容器的相关 nibble 改掉
    python patch_zh138_glyphs61.py --iso <src.iso> --out <dst.iso> --report out.json

退出码: 0 = 全部断言通过; 非 0 = 有断言失败 (不写盘)。
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _find_repo(start):
    """向上找仓库根 (含 docs/ 与 tools/text_csv/tcslib.py 的那一层)。

    本脚本有两份**逐字节相同**的副本: `work/builds/GR_FONTFIX/tools/` 与 `tools/final_fix/`,
    两者层级不同 ⇒ 不能写死 '..' 的个数 (曾因此 ModuleNotFoundError: tcslib)。
    """
    p = start
    for _ in range(8):
        p = os.path.dirname(p)
        if (os.path.isdir(os.path.join(p, 'docs'))
                and os.path.isfile(os.path.join(p, 'tools', 'text_csv', 'tcslib.py'))):
            return p
    raise SystemExit('!! 找不到仓库根 (从 %s 向上找 docs/ + tools/text_csv/tcslib.py)' % start)


REPO = _find_repo(HERE)
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
except Exception:                                                     # noqa: BLE001
    pass

import numpy as np                                                    # noqa: E402
from PIL import Image, ImageDraw, ImageFont                            # noqa: E402

import tcslib                                                         # noqa: E402
import dump_font                                                      # noqa: E402
import repack_font as RF                                              # noqa: E402

TOOL = 'work/builds/GR_FONTFIX/tools/patch_zh138_glyphs61.py'
TOOL_VERSION = 'r1.0'
FZ16 = os.path.join(REPO, 'third_party', 'fonts', '方正像素16.ttf')
CHARSET = os.path.join(REPO, 'tools', 'final_fix', 'assets', 'charset', 'charset_compiled_zh16.json')
BLOCK = '_expand_cap2400'


def render16(ch, font):
    """★ 全项目共用的渲染配方 (与 gen_font16.render16 / verify_font_state.r16 逐字同款)。"""
    img = Image.new('L', (32, 32), 255)
    ImageDraw.Draw(img).text((8, 8), ch, font=font, fill=0)
    return np.asarray(img)[8:24, 8:24] < 128


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 24), b''):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--iso', required=True)
    ap.add_argument('--out', default=None, help='输出 ISO (不给 ⇒ 等价 --dry-run)')
    ap.add_argument('--charset', default=CHARSET)
    ap.add_argument('--report', default=None)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    dry = a.dry_run or not a.out
    rep = dict(tool=TOOL, tool_version=TOOL_VERSION, iso=os.path.relpath(a.iso, REPO),
               charset=os.path.relpath(a.charset, REPO), dry_run=dry,
               font_sha256=sha256_file(FZ16), font_size=os.path.getsize(FZ16))

    # ── 0. 几何: 一律以盘上 ELF 立即数为准 ──
    geom = RF.sync_geometry_from_iso(a.iso, verbose=True)
    rep['geom_from_elf'] = geom

    font = dump_font.load_font(a.iso)
    at = font['atlas']
    W, H, PSM, PXS = at['w'], at['h'], at['psm'], at['px_size']
    blob = dump_font.container_blob(at)
    segs = [s for (s) in tcslib.atlas_container_segments(blob, W // 2) if s[2]]
    payload = sum(s[2] for s in segs)
    rep['atlas_before'] = dict(w=W, h=H, psm=PSM, px_size=PXS, n_data_segments=len(segs),
                               payload=payload,
                               px_plane_sha256=hashlib.sha256(blob[:W * H // 2]).hexdigest())
    n_bad_geom = 0
    if not (W, H, PSM) == (1024, 644, 0x14):
        n_bad_geom += 1
    if PXS != W * H // 2 + 16:
        n_bad_geom += 1
    if len(segs) != 11 or payload != 329200:
        n_bad_geom += 1
    rep['atlas_gates_ok'] = (n_bad_geom == 0)
    if n_bad_geom:
        raise SystemExit('!! 图集几何不是 K2 (1024x644 PSMT4 / 11 段 / payload 329200): 拒绝动手')

    A = RF.Atlas(at['pak'], at['px_off'], PXS, W, H, PSM)
    protect, rects = RF.protect_mask(font['faces'], W, H)
    cells = {c['slot']: c for c in RF.enumerate_cells(W, H)}
    cls = RF.classify(cells.values(), protect, W, H)
    cs = tcslib.Charset(a.charset)
    js = json.load(io.open(a.charset, encoding='utf-8'))
    reg = RF.registered_missing_slots(js, cs)          # {slot: char} (已登记/真汉字, 与 pair_of 交叉核对)
    rep['registered_missing_meta'] = dict(n=len(reg),
                                          sample=dict(list(reg.items())[:5]))

    # ── 1. 目标 = 已登记 ∩ 盘上空格 (只认 1872..1935 这段) ──
    old = A.eng
    targets = []
    for slot, ch in sorted(reg.items()):
        c = cells[slot]
        ink = int(old[c['y']:c['y'] + 16, c['x']:c['x'] + 16].sum())
        targets.append(dict(slot=slot, char=ch, row=c['row'], col=c['col'],
                            x=c['x'], y=c['y'], ink_before=ink, cls=cls[slot][0]))
    todo = [t for t in targets if t['ink_before'] == 0]
    rep['targets'] = targets
    rep['n_targets'] = len(todo)
    rep['n_already_drawn'] = len(targets) - len(todo)
    if len(todo) != 61:
        raise SystemExit('!! 目标数不是 61 (实测 %d) —— 这张盘的缺字集合与报告不符, 拒绝动手'
                         % len(todo))

    # ── 2. 逐字渲染 + 静态检查 (不写盘) ──
    fnt = ImageFont.truetype(FZ16, 16)
    tpl_cache = {}
    new = old.copy()
    changed = np.zeros_like(old)
    rows = []
    for t in todo:
        ch, x, y = t['char'], t['x'], t['y']
        if t['cls'] != 'usable':
            raise SystemExit('!! %r 的格 (slot %d) 分类是 %s —— 不是可用格, 拒绝写'
                             % (ch, t['slot'], t['cls']))
        box_prot = protect[y:y + 16, x:x + 16]
        if box_prot.any():
            raise SystemExit('!! %r 的格与 FT 记录矩形/图标窗交叠 (%d px), 拒绝写'
                             % (ch, int(box_prot.sum())))
        tpl = render16(ch, fnt)
        tpl_cache[ch] = tpl
        ink = int(tpl.sum())
        if ink == 0:
            raise SystemExit('!! %r 在 方正像素16 里渲染为空 —— 不是"漏画", 不能补' % ch)
        new[y:y + 16, x:x + 16] = tpl
        changed[y:y + 16, x:x + 16] = True
        rows.append(dict(char=ch, slot=t['slot'], row=t['row'], col=t['col'], x=x, y=y,
                         ink=ink, dots=''.join('#' if v else '.' for v in tpl.reshape(-1))[:64] + '…'))
    rep['glyphs'] = rows
    ink_before = int(old.sum())
    ink_after = int(new.sum())
    rep['ink'] = dict(before=ink_before, after=ink_after, delta=ink_after - ink_before,
                      sum_of_glyph_ink=sum(r['ink'] for r in rows))

    # ── 3. 断言: 只有这 61 格变了 ──
    diff = new != old
    rep['texels_changed'] = int(diff.sum())
    # 逐格普查: 2350 个 slot 的格 xor (应为 61 个非 0)
    per_cell = []
    for s in range(tcslib.pair_capacity()):
        c = cells[s]
        if c['x'] + 16 > W or c['y'] + 16 > H:
            continue
        xo = int((new[c['y']:c['y'] + 16, c['x']:c['x'] + 16]
                  != old[c['y']:c['y'] + 16, c['x']:c['x'] + 16]).sum())
        if xo:
            per_cell.append(dict(slot=s, row=c['row'], col=c['col'], xo=xo))
    rep['cells_changed'] = dict(n=len(per_cell), slots=[d['slot'] for d in per_cell],
                                all_in_target=all(d['slot'] in set(t['slot'] for t in todo)
                                                  for d in per_cell))
    # 目标格之外**任何** texel 都不许变
    outside = diff.copy()
    for t in todo:
        outside[t['y']:t['y'] + 16, t['x']:t['x'] + 16] = False
    rep['texels_changed_outside_targets'] = int(outside.sum())
    # 保护窗 (FT 记录矩形) 必须 0 变化
    rep['protected_px_changed'] = int((new[protect] != old[protect]).sum())
    ok = (rep['texels_changed'] == rep['ink']['sum_of_glyph_ink']
          and rep['texels_changed_outside_targets'] == 0
          and rep['protected_px_changed'] == 0
          and len(per_cell) == 61 and rep['cells_changed']['all_in_target'])
    rep['static_checks_ok'] = ok
    if not ok:
        raise SystemExit('!! 静态自检失败: changed=%d 期望=%d, outside=%d, protected=%d, cells=%d'
                         % (rep['texels_changed'], rep['ink']['sum_of_glyph_ink'],
                            rep['texels_changed_outside_targets'], rep['protected_px_changed'],
                            len(per_cell)))

    # ── 4. 写盘 (只在 --out 时) ──
    if not dry:
        ys, xs = np.where(diff)
        ink = new[ys, xs]
        empty, _hist = A.empty_index()
        rep['empty_index'] = empty
        hdr_before = A.headers()
        A.write_pixels(ys, xs, ink, empty)
        for (doff, hb) in hdr_before:
            if bytes(A.cont[doff - tcslib.ATLAS_PREFIX_BYTES:doff]) != hb:
                raise SystemExit('!! 有 48B 包头被改了 (doff=0x%X)' % doff)
        if os.path.abspath(a.iso) != os.path.abspath(a.out):
            shutil.copyfile(a.iso, a.out)
        with open(a.out, 'r+b') as f:
            f.seek(font['pak_e']['iso_off'] + at['px_off'])
            f.write(bytes(A.cont))
        rep['out'] = dict(path=os.path.relpath(a.out, REPO), bytes=os.path.getsize(a.out),
                          sha256=sha256_file(a.out))
        # ---- 回读: 重新从产物解一遍, 逐格比对 ----
        F2 = dump_font.load_font(a.out)
        A2 = RF.Atlas(F2['atlas']['pak'], F2['atlas']['px_off'], F2['atlas']['px_size'],
                      F2['atlas']['w'], F2['atlas']['h'], F2['atlas']['psm'])
        readback = []
        bad = 0
        for t in todo:
            w2 = A2.eng[t['y']:t['y'] + 16, t['x']:t['x'] + 16]
            xo = int(np.logical_xor(w2, tpl_cache[t['char']]).sum())
            readback.append(dict(char=t['char'], slot=t['slot'], x=t['x'], y=t['y'], xor=xo,
                                 ink=int(w2.sum())))
            bad += (xo != 0)
        rep['readback'] = dict(n=len(readback), xor0=sum(1 for r in readback if r['xor'] == 0),
                               xor_nonzero=bad, detail=readback)
        # 其它格: 与源盘逐格比 (应为 0)
        other = 0
        for s in range(tcslib.pair_capacity()):
            c = cells[s]
            if s in set(t['slot'] for t in todo) or c['x'] + 16 > W or c['y'] + 16 > H:
                continue
            if (A2.eng[c['y']:c['y'] + 16, c['x']:c['x'] + 16]
                    != old[c['y']:c['y'] + 16, c['x']:c['x'] + 16]).any():
                other += 1
        # 保护窗 / 容器头 / 容器外字节
        rep['readback']['other_cells_changed'] = other
        rep['readback']['protected_px_changed'] = int(
            (A2.eng[protect] != old[protect]).sum())
        rep['readback']['headers_identical'] = all(
            bytes(A2.cont[doff - tcslib.ATLAS_PREFIX_BYTES:doff]) == hb
            for (doff, hb) in hdr_before)
        pak_before = font['atlas']['pak']
        pak_after = F2['atlas']['pak']
        rep['readback']['pak_outside_px_identical'] = (
            bytes(pak_after[:at['px_off']]) == bytes(pak_before[:at['px_off']])
            and bytes(pak_after[at['px_off'] + PXS:]) == bytes(pak_before[at['px_off'] + PXS:]))
        rep['readback']['geom_same'] = (F2['atlas']['w'], F2['atlas']['h'], F2['atlas']['psm'],
                                        F2['atlas']['px_size']) == (W, H, PSM, PXS)
        rb_ok = (bad == 0 and other == 0
                 and rep['readback']['protected_px_changed'] == 0
                 and rep['readback']['headers_identical']
                 and rep['readback']['pak_outside_px_identical']
                 and rep['readback']['geom_same'])
        rep['readback_ok'] = rb_ok
        if not rb_ok:
            raise SystemExit('!! 回读校验失败: 见报告 %r' % (a.report,))

    rep['ok'] = True
    p = a.report or os.path.join(REPO, 'work', 'builds', 'GR_FONTFIX', 'out',
                                 'patch_zh138_glyphs61.json')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    print('')
    print('=' * 92)
    print('[glyphs61] 目标 %d 字 / 已画过 %d ; 墨量 %d → %d (+%d) ; 改动 texel %d'
          % (rep['n_targets'], rep['n_already_drawn'], ink_before, ink_after,
             rep['ink']['delta'], rep['texels_changed']))
    print('[glyphs61] 只有这 %d 格变了: %s ; 格外 %d ; 保护窗 %d'
          % (len(per_cell), rep['cells_changed']['all_in_target'],
             rep['texels_changed_outside_targets'], rep['protected_px_changed']))
    if not dry:
        print('[glyphs61] 回读: xor==0 %d/%d ; 其它格变化 %d ; 包头完整 %s ; 容器外字节不变 %s'
              % (rep['readback']['xor0'], rep['readback']['n'],
                 rep['readback']['other_cells_changed'],
                 rep['readback']['headers_identical'],
                 rep['readback']['pak_outside_px_identical']))
        print('[glyphs61] 产物 %s  sha256 %s' % (rep['out']['path'], rep['out']['sha256']))
    print('[out] %s' % p)
    return 0


if __name__ == '__main__':
    sys.exit(main())
