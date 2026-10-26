# -*- coding: utf-8 -*-
r"""patch_zh139_chars.py — 把**有证据的缺字**写进 PUA 占位槽 (只动图集 + charset, ELF 0 字节)。

做法 (与 `patch_zh138_glyphs61.py` 同一套配方/断言, 只多两件事):
  · 目标槽来自 **plan json** (a3_plan.py 产出): 每行 {char, slot, pair};
  · 同时改写 charset JSON: 把该槽上的 **PUA 占位键**换成真字 (**码位/槽位不变**)。

★ 不动的东西 (工具逐项断言):
  · 图集几何 w/h/psm/px_size/段数/payload/48B 包头;
  · 其它 2,337 个已登记格 + 全部非字符像素;
  · **全部文本字节** (LANG/SFXML 容器逐字节不变) / FT 记录 / ELF (逐字节相同 ⇒ Game CRC 不变);
  · 目标格原本**零墨** (只加墨, 不擦任何已有像素)。

用法:
    python patch_zh139_chars.py --base <GR_ZH138.iso> --out <GR_ZH139.iso> \
        --plan out/a3_plan.json --charset <charset.json> --report out/patch.json [--dry-run]
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
    """向上找仓库根 (同时含 docs/ 与 tools/text_csv/tcslib.py 的那一层)。

    本脚本有两份**逐字节相同**的副本: `work/builds/GR_EXPAND/tools/` 与 `tools/final_fix/`,
    两者层级不同 ⇒ 不能写死 '..' 的个数 (上一轮 patch_zh138 曾因此 ModuleNotFoundError)。
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
except Exception:                                                       # noqa: BLE001
    pass

import numpy as np                                                      # noqa: E402
from PIL import Image, ImageDraw, ImageFont                             # noqa: E402

import tcslib                                                           # noqa: E402
import dump_font                                                        # noqa: E402
import repack_font as RF                                                # noqa: E402
import dump_text_csv as D                                               # noqa: E402

TOOL = 'work/builds/GR_EXPAND/tools/patch_zh139_chars.py'
TOOL_VERSION = 'r1.0'
FZ16 = os.path.join(REPO, 'third_party', 'fonts', '方正像素16.ttf')
PUA_LO, PUA_HI = 0xE000, 0xF8FF


def render16(ch, font):
    """★ 全项目共用的渲染配方 (gen_font16.render16 / patch_zh138_glyphs61.render16 同款)。"""
    img = Image.new('L', (32, 32), 255)
    ImageDraw.Draw(img).text((8, 8), ch, font=font, fill=0)
    a = np.asarray(img)
    win = a[8:24, 8:24] < 128
    full = a < 128
    if not full.any():
        return win, 'ttf_missing'
    ys, xs = np.where(full)
    if not win.any():
        return win, 'zombie'
    if ys.min() < 8 or xs.min() < 8 or ys.max() >= 24 or xs.max() >= 24:
        return win, 'overflow'
    return win, 'ok'


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 24), b''):
            h.update(b)
    return h.hexdigest()


def diff_spans(p1, p2, chunk=1 << 23, gap=4096):
    """两个文件的字节差异区间 [[lo,hi), ...] (分块比对; gap 内的差异合并)。"""
    spans = []
    pos = 0
    with open(p1, 'rb') as f1, open(p2, 'rb') as f2:
        while True:
            b1 = f1.read(chunk)
            b2 = f2.read(chunk)
            if not b1 and not b2:
                break
            if b1 != b2:
                n = min(len(b1), len(b2))
                a1 = np.frombuffer(b1[:n], dtype=np.uint8)
                a2 = np.frombuffer(b2[:n], dtype=np.uint8)
                idx = np.nonzero(a1 != a2)[0]
                if idx.size:
                    lo = int(idx[0])
                    prev = int(idx[0])
                    for k in idx[1:]:
                        k = int(k)
                        if k - prev > gap:
                            spans.append([pos + lo, pos + prev + 1])
                            lo = k
                        prev = k
                    spans.append([pos + lo, pos + prev + 1])
            pos += len(b1)
    # 跨块合并
    merged = []
    for s in spans:
        if merged and s[0] - merged[-1][1] <= gap:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return [tuple(s) for s in merged]


def walk_pairs(blob, cs):
    out = []
    i, n = 0, len(blob)
    enc = cs.pair_of
    while i < n:
        v = blob[i]
        if v < 0x80:
            out.append(('ascii', v, 0))
            i += 1
        elif tcslib.LEAD_LO <= v < tcslib.LEAD_HI and i + 1 < n and (v, blob[i + 1]) in enc:
            out.append(('pair', v, blob[i + 1]))
            i += 2
        elif v in cs.codes:
            out.append(('single', v, 0))
            i += 1
        else:
            out.append(('pua', v, 0))
            i += 1
    return out


def text_refs(iso_path, cs):
    """盘上全部文本条目 → 每个对偶码被引用次数 + 未映射字节单元。"""
    iso = tcslib.Iso(iso_path)
    try:
        res = D.load_resources(iso, ['LANG', 'SFXML'])
        blobs = {name: r['copies'][0]['blob'] for name, r in res.items()}
    finally:
        iso.close()
    refs = {}
    pua = []
    n_units = 0
    for name, blob in blobs.items():
        if name == 'LANG':
            ents, _used = tcslib.parse_lang(blob)
            spans = [(e.data_off, e.data_off + e.length, 'LANG:G%03d.I%03d' % (e.g, e.i))
                     for e in ents]
        else:
            spans = [(off, off + ln, 'SFXML:T%04d' % k)
                     for (k, off, ln, _b) in tcslib.parse_sfxml(blob)]
        for (lo, hi, tag) in spans:
            for (kind, b1, b2) in walk_pairs(blob[lo:hi], cs):
                n_units += 1
                if kind == 'pair':
                    refs[(b1, b2)] = refs.get((b1, b2), 0) + 1
                elif kind == 'pua':
                    pua.append(dict(byte=b1, entry=tag))
    return dict(refs=refs, pua_units=pua, n_units=n_units,
                blob_sha256=dict((k, hashlib.sha256(v).hexdigest()) for k, v in blobs.items()))


def load_plan(path):
    """读 a3_plan.json 的 selected (char/slot/pair) 或简化 list。"""
    js = json.load(io.open(path, encoding='utf-8'))
    sel = js.get('selected') or js.get('chars') or js
    out = []
    for d in sel:
        out.append(dict(char=d['char'], slot=int(d['slot']),
                        pair=d.get('pair') or '%02X%02X' % (d['lead'], d['trail']),
                        tier=d.get('tier', ''), evidence=d.get('doc') or '',
                        pua_char=d.get('pua_char'), ink=int(d.get('ink') or 0)))
    out.sort(key=lambda d: d['slot'])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True)
    ap.add_argument('--out', default=None)
    ap.add_argument('--plan', required=True)
    ap.add_argument('--charset', default=os.path.join(REPO, 'tools', 'final_fix', 'assets', 'charset',
                                        'charset_compiled_zh16.json'))
    ap.add_argument('--report', default=os.path.join(REPO, 'work', 'builds', 'GR_EXPAND', 'out',
                                                     'patch_zh139.json'))
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    dry = a.dry_run or not a.out
    rep = dict(tool=TOOL, tool_version=TOOL_VERSION, base=os.path.relpath(a.base, REPO),
               plan=os.path.relpath(a.plan, REPO), dry_run=dry,
               font=dict(path=os.path.relpath(FZ16, REPO), sha256=sha256_file(FZ16)),
               base_sha256=sha256_file(a.base))

    # ── 0. 几何 (盘上 ELF 立即数) + 三闸门 ──
    geom = RF.sync_geometry_from_iso(a.base, verbose=True)
    font = dump_font.load_font(a.base)
    at = font['atlas']
    W, H, PSM, PXS = at['w'], at['h'], at['psm'], at['px_size']
    blob = dump_font.container_blob(at)
    segs = [s for s in tcslib.atlas_container_segments(blob, W // 2) if s[2]]
    reps = dict(geom=geom, atlas=dict(w=W, h=H, psm=PSM, px_size=PXS, n_data_segments=len(segs),
                                      payload=sum(s[2] for s in segs),
                                      px_plane_sha256=hashlib.sha256(blob[:W * H // 2]).hexdigest(),
                                      header_sha256=[hashlib.sha256(bytes(blob[doff - 48:doff])).hexdigest()
                                                     for (_fr, doff, _nb) in segs]))
    gates = dict(w_lt_1025=(W < 1025), px_size=(PXS == W * H // 2 + 16),
                 stride_2048=((W * H // 2) % 2048 == 0),
                 geom_k2=((W, H, PSM) == (1024, 644, 0x14)),
                 nseg=(len(segs) == 11), payload=(sum(s[2] for s in segs) == 329200))
    rep['gates'] = gates
    if not all(gates.values()):
        raise SystemExit('!! 几何/闸门不符 (期望 K2 1024x644 PSMT4 / 11 段 / payload 329200): %r' % gates)

    A = RF.Atlas(at['pak'], at['px_off'], PXS, W, H, PSM)
    protect, rects = RF.protect_mask(font['faces'], W, H)
    cells = {c['slot']: c for c in RF.enumerate_cells(W, H)}
    cls = RF.classify(cells.values(), protect, W, H)
    cs = tcslib.Charset(a.charset)
    js = json.load(io.open(a.charset, encoding='utf-8'))
    enc_pair = {ch: tuple(v) for ch, v in js['pair_of'].items()}
    slot_of = {tcslib.pair_slot(int(v[0]), int(v[1])): ch for ch, v in enc_pair.items()}

    # ── 1. 盘上文本引用 (零引用的正面证据) ──
    tr = text_refs(a.base, cs)
    rep['text'] = dict(n_units=tr['n_units'], pua_units=tr['pua_units'],
                       container_blob_sha256=tr['blob_sha256'])

    # ── 2. plan 校验 ──
    plan = load_plan(a.plan)
    rep['plan'] = plan
    todo = []
    for d in plan:
        ch, slot = d['char'], d['slot']
        b1, b2 = tcslib.pair_from_slot(slot)
        if d['pair'] != '%02X%02X' % (b1, b2):
            raise SystemExit('!! %r 的 plan pair %s 与槽 %d 的对偶码 %02X%02X 不符'
                             % (ch, d['pair'], slot, b1, b2))
        c = cells[slot]
        x, y, ink0 = c['x'], c['y'], int(A.eng[c['y']:c['y'] + 16, c['x']:c['x'] + 16].sum())
        cur = slot_of.get(slot)
        st = dict(char=ch, slot=slot, pair=d['pair'], row=c['row'], col=c['col'], x=x, y=y,
                  ink_before=ink0, cls=cls[slot][0],
                  prot=int(protect[y:y + 16, x:x + 16].sum()),
                  refs=tr['refs'].get((b1, b2), 0), charset_key=cur,
                  already=(ch in enc_pair and enc_pair[ch] == (b1, b2)),
                  tier=d.get('tier'), evidence=d.get('evidence'))
        if st['already']:
            img = Image.new('L', (32, 32), 255)
            ImageDraw.Draw(img).text((8, 8), ch,
                                     font=ImageFont.truetype(FZ16, 16), fill=0)
            tpl = np.asarray(img)[8:24, 8:24] < 128
            st['xor_existing'] = int(np.logical_xor(A.eng[y:y + 16, x:x + 16], tpl).sum())
            st['ink'] = int(tpl.sum())
            st['verdict'] = 'already'
            todo.append(st)
            continue
        if ch in enc_pair:
            raise SystemExit('!! %r 已在 charset 里 (pair %02X%02X), 槽 %d 要换的字不是它'
                             % (ch, enc_pair[ch][0], enc_pair[ch][1], slot))
        if cur is None:
            raise SystemExit('!! 槽 %d 在 charset 里**没有登记** (不能抢占未登记槽)' % slot)
        if not (PUA_LO <= ord(cur) <= PUA_HI):
            raise SystemExit('!! 槽 %d 当前登记的是真字 %r (不是 PUA 占位) —— 占用冲突, 拒绝'
                             % (slot, cur))
        if ink0 != 0:
            raise SystemExit('!! 槽 %d (%r→%r) 格内有 %d 墨点 (不是空槽)' % (slot, cur, ch, ink0))
        if cls[slot][0] != 'usable':
            raise SystemExit('!! 槽 %d 分类 %s' % (slot, cls[slot][0]))
        if st['prot'] != 0:
            raise SystemExit('!! 槽 %d 与 FT 记录矩形交叠 %d px' % (slot, st['prot']))
        if c['col'] == 63 or x + 16 > W or y + 16 > H:
            raise SystemExit('!! 槽 %d 在 col-63 / 越界 (x=%d y=%d)' % (slot, x, y))
        if st['refs'] != 0:
            raise SystemExit('!! 对偶码 %s 在盘上文本里被引用 %d 次 —— 换掉会改现役文本的字!'
                             % (d['pair'], st['refs']))
        todo.append(st)
    n_new = sum(1 for t in todo if not t['already'])
    rep['n_targets'] = len(todo)
    rep['n_new'] = n_new
    rep['n_already'] = len(todo) - n_new
    print('[plan] %d 个目标 (%d 待画 / %d 已在盘上)' % (len(todo), n_new, len(todo) - n_new))

    # ── 3. 渲染 + 静态断言 ──
    fnt = ImageFont.truetype(FZ16, 16)
    old = A.eng
    new = old.copy()
    tpl_cache = {}
    rows = []
    for t in todo:
        ch, x, y = t['char'], t['x'], t['y']
        tpl, verdict = render16(ch, fnt)
        tpl_cache[ch] = tpl
        ink = int(tpl.sum())
        t['verdict'] = verdict
        t['ink'] = ink
        if verdict != 'ok':
            raise SystemExit('!! %r 渲染判定 %s (拒绝写入)' % (ch, verdict))
        if t['already']:
            continue
        new[y:y + 16, x:x + 16] = tpl
        rows.append(dict(char=ch, slot=t['slot'], pair=t['pair'], row=t['row'], col=t['col'],
                         x=x, y=y, ink=ink, tier=t['tier'], evidence=t['evidence']))
    rep['glyphs'] = rows
    diff = new != old
    rep['texels_changed'] = int(diff.sum())
    rep['ink'] = dict(before=int(old.sum()), after=int(new.sum()),
                      sum_of_glyph_ink=sum(r['ink'] for r in rows))
    tgt = {(t['y'], t['x']) for t in todo}
    outside = diff.copy()
    for (y, x) in tgt:
        outside[y:y + 16, x:x + 16] = False
    rep['texels_changed_outside_targets'] = int(outside.sum())
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
                                all_in_target=all(d['slot'] in {t['slot'] for t in todo}
                                                  for d in per_cell))
    rep['protected_px_changed'] = int((new[protect] != old[protect]).sum())
    ok = (rep['texels_changed'] == rep['ink']['sum_of_glyph_ink'] * 1
          and rep['texels_changed_outside_targets'] == 0
          and rep['protected_px_changed'] == 0
          and len(per_cell) == n_new)
    rep['static_checks_ok'] = ok
    if not ok:
        raise SystemExit('!! 静态自检失败: texels %d vs 模板墨 %d ; outside %d ; protected %d ; cells %d/%d'
                         % (rep['texels_changed'], rep['ink']['sum_of_glyph_ink'],
                            rep['texels_changed_outside_targets'], rep['protected_px_changed'],
                            len(per_cell), n_new))

    # ── 4. charset 新内容 (先算好, 写盘成功后才落盘) ──
    new_js = json.loads(json.dumps(js))                # 深拷贝 (保持键顺序)
    po_new = {}
    replaced = {}
    for k, v in new_js['pair_of'].items():
        hit = next((t for t in todo if not t['already'] and t['charset_key'] == k), None)
        if hit:
            po_new[hit['char']] = v
            replaced[k] = hit['char']
        else:
            po_new[k] = v
    new_js['pair_of'] = po_new
    main_meta = dict(
        note='★ round-expand2300: 把有证据的缺字写进**零引用 PUA 占位槽** (码位/槽位不变, 只换键名); '
             '渲染配方与现役 1,941 个字形逐字同款 (方正像素16 16px → 32×32 → [8:24,8:24] → <128)。'
             '本轮**不动任何文本字节** ⇒ 现役画面零变化。',
        tool=TOOL, tool_version=TOOL_VERSION,
        base=os.path.relpath(a.base, REPO), base_sha256=rep['base_sha256'],
        atlas=dict(w=W, h=H, psm=PSM, px_size=PXS, nseg=len(segs),
                   px_plane_sha256_before=reps['atlas']['px_plane_sha256']),
        rules=dict(
            pua_pool=dict(total=359, col63=36, replaceable=323,
                          why='col-63 (x=1008..1023) 右缘贴 1024 ⇒ 引擎采样矩形取不到 (REPORT_GLYPH_FIX)'),
            conditions=['pair_of 键是 U+E000..U+F8FF 的 PUA 占位',
                        '不在 col-63', '格内零墨', 'classify==usable 且与 FT 矩形 0 px 交叠',
                        '盘上文本零引用 (引擎口径逐单元对齐)', 'trail 不在 0xB1/0xB5 哨兵'],
            selection='档A=docs 明写"字库无X" / 档B=译者丰富版草稿原文片段 / 档C=官方 PC 中文对照表; '
                      '按档位+频次降序取, 同分按码位升序; 只用**有证据**的字, 其余槽保持 PUA'),
        slots=[t['slot'] for t in todo],
        chars=''.join(t['char'] for t in todo),
        pairs={t['char']: t['pair'] for t in todo},
        replaced_pua=replaced,
        evidence={t['char']: dict(tier=t['tier'], evidence=t['evidence'], slot=t['slot'],
                                  pair=t['pair']) for t in todo},
        ink=dict(before=rep['ink']['before'], after=rep['ink']['after'],
                 delta=rep['ink']['after'] - rep['ink']['before'],
                 sum_of_glyph_ink=rep['ink']['sum_of_glyph_ink']),
        text_untouched=True,
    )
    new_js['_expand_2300'] = main_meta
    if '_font_compact' in new_js:
        fc = new_js['_font_compact']
        fc['used'] = int(js['_font_compact'].get('used', 1941)) + n_new
        fc['iso_version'] = 'GR_ZH139'
        fc['note_stamp_20261020_expand'] = (
            'round-expand2300: used 1,941 → %d (= 有字形的登记槽); 新增字全部落在原 PUA 占位槽, '
            'pair_of 条数仍 2,300; free_slots=50 不变' % fc['used'])

    # ── 5. 写盘 ──
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
        # 先拷盘, 再只覆盖像素容器
        if os.path.abspath(a.base) != os.path.abspath(a.out):
            shutil.copyfile(a.base, a.out)
        with open(a.out, 'r+b') as f:
            f.seek(font['pak_e']['iso_off'] + at['px_off'])
            f.write(bytes(A.cont))
        rep['out'] = dict(path=os.path.relpath(a.out, REPO), bytes=os.path.getsize(a.out),
                          sha256=sha256_file(a.out))

        # ---- 回读: 逐格 / 容器 / ELF / 文本 ----
        F2 = dump_font.load_font(a.out)
        A2 = RF.Atlas(F2['atlas']['pak'], F2['atlas']['px_off'], F2['atlas']['px_size'],
                      F2['atlas']['w'], F2['atlas']['h'], F2['atlas']['psm'])
        bad = 0
        rb = []
        for t in todo:
            w2 = A2.eng[t['y']:t['y'] + 16, t['x']:t['x'] + 16]
            xo = int(np.logical_xor(w2, tpl_cache[t['char']]).sum())
            rb.append(dict(char=t['char'], slot=t['slot'], xor=xo, ink=int(w2.sum())))
            bad += (xo != 0)
        other = 0
        for s in range(tcslib.pair_capacity()):
            c = cells[s]
            if s in {t['slot'] for t in todo} or c['x'] + 16 > W or c['y'] + 16 > H:
                continue
            if (A2.eng[c['y']:c['y'] + 16, c['x']:c['x'] + 16]
                    != old[c['y']:c['y'] + 16, c['x']:c['x'] + 16]).any():
                other += 1
        tr2 = text_refs(a.out, cs)
        # 全盘逐字节 diff (分块) —— 只允许落在图集像素容器内
        px_lo = font['pak_e']['iso_off'] + at['px_off']
        px_hi = px_lo + PXS
        spans = diff_spans(a.base, a.out)
        outside_px = sum((hi - lo) for (lo, hi) in spans if lo < px_lo or hi > px_hi)
        rep['readback'] = dict(
            xor0=sum(1 for r in rb if r['xor'] == 0), n=len(rb), xor_nonzero=bad, detail=rb,
            other_cells_changed=other,
            protected_px_changed=int((A2.eng[protect] != old[protect]).sum()),
            headers_identical=all(bytes(A2.cont[doff - tcslib.ATLAS_PREFIX_BYTES:doff]) == hb
                                  for (doff, hb) in hdr_before),
            pak_outside_px_identical=(
                bytes(F2['atlas']['pak'][:at['px_off']]) == bytes(at['pak'][:at['px_off']])
                and bytes(F2['atlas']['pak'][at['px_off'] + PXS:])
                == bytes(at['pak'][at['px_off'] + PXS:])),
            geom_same=(F2['atlas']['w'], F2['atlas']['h'], F2['atlas']['psm'],
                       F2['atlas']['px_size']) == (W, H, PSM, PXS),
            font_res_identical=(hashlib.sha256(bytes(F2['ft_blob'])).hexdigest()
                                == hashlib.sha256(bytes(font['ft_blob'])).hexdigest()),
            text_blobs_identical=(tr2['blob_sha256'] == tr['blob_sha256']),
            file_diff=dict(n_spans=len(spans), spans=[[lo, hi] for (lo, hi) in spans][:50],
                           px_window=[px_lo, px_hi],
                           bytes_outside_px_window=outside_px),
        )
        r = rep['readback']
        rb_ok = (bad == 0 and other == 0 and r['protected_px_changed'] == 0
                 and r['headers_identical'] and r['pak_outside_px_identical'] and r['geom_same']
                 and r['font_res_identical'] and r['text_blobs_identical'] and outside_px == 0)
        rep['readback_ok'] = rb_ok
        if not rb_ok:
            raise SystemExit('!! 回读校验失败: %r' % {k: v for k, v in r.items() if k != 'detail'})

        # ---- charset 落盘 (在盘成功之后) ----
        rep['charset'] = dict(path=os.path.relpath(a.charset, REPO),
                              sha256_before=hashlib.sha256(
                                  io.open(a.charset, 'rb').read()).hexdigest())
        if n_new == 0:
            # ★ 幂等: 没有任何新字要写 ⇒ **一个字都不动 charset** (连戳都不改)
            rep['charset']['sha256_after'] = rep['charset']['sha256_before']
            rep['charset']['n_pair'] = len(new_js['pair_of'])
            rep['charset']['n_codes'] = len(new_js['codes'])
            rep['charset']['skipped_noop'] = True
        else:
            io.open(a.charset, 'w', encoding='utf-8', newline='\n').write(
                json.dumps(new_js, ensure_ascii=False, indent=1))
            rep['charset']['sha256_after'] = sha256_file(a.charset)
            rep['charset']['n_pair'] = len(new_js['pair_of'])
            rep['charset']['n_codes'] = len(new_js['codes'])

    rep['ok'] = True
    os.makedirs(os.path.dirname(a.report), exist_ok=True)
    io.open(a.report, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(rep, ensure_ascii=False, indent=1))
    print('')
    print('=' * 96)
    print('[zh139] 目标 %d (新画 %d) ; 墨量 %d → %d (+%d, 模板墨 %d) ; 改动 texel %d'
          % (len(todo), n_new, rep['ink']['before'], rep['ink']['after'],
             rep['ink']['after'] - rep['ink']['before'], rep['ink']['sum_of_glyph_ink'],
             rep['texels_changed']))
    print('[zh139] 变化格 %d 个全在目标内=%s ; 格外 %d ; 保护窗 %d'
          % (len(per_cell), rep['cells_changed']['all_in_target'],
             rep['texels_changed_outside_targets'], rep['protected_px_changed']))
    if not dry:
        print('[zh139] 回读 xor==0 %d/%d ; 其它格 %d ; FONT.RES 同 %s ; 文本容器同 %s ; '
              '差异区间 %d 个 / 窗口外 %d B'
              % (rep['readback']['xor0'], rep['readback']['n'],
                 rep['readback']['other_cells_changed'], rep['readback']['font_res_identical'],
                 rep['readback']['text_blobs_identical'],
                 rep['readback']['file_diff']['n_spans'],
                 rep['readback']['file_diff']['bytes_outside_px_window']))
        print('[zh139] 产物 %s  %d B  sha256 %s'
              % (rep['out']['path'], rep['out']['bytes'], rep['out']['sha256']))
        print('[zh139] charset sha256 %s → %s'
              % (rep['charset']['sha256_before'], rep['charset']['sha256_after']))
    print('[out] %s' % a.report)
    return 0


if __name__ == '__main__':
    sys.exit(main())
