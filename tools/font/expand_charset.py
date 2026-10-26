# -*- coding: utf-8 -*-
r"""expand_charset.py — DLC 字符集扩充 / 图集补画（方案 B 的最后一环）。

一句话：把**译文里出现、但字库字符集里没有**的汉字，用 TTF 16×16 画进中文图集的
「零引用 PUA 占位槽」，并把 `char → 对偶码` 写回字符集 JSON。

输入（只读）：
  · third_party/ref/zh_font_seed/COMMON_PAK.MENU3.zh.bin  —— 中文图集容器（1024×644 PSMT4）
  · assets/charset/charset_compiled_zh16.json              —— 当前字符集（会回写）
  · work/translation/merged/missing_chars.json             —— 缺字表（顺序=频次降序；可更新重跑）
  · work/translation/merged/translations_all.csv           —— 全部译文（用于 PUA 引用计数）
输出（入库）：
  · assets/charset/charset_compiled_zh16.json              —— 追加/替换后的字符集（单一真源）
  · assets/charset/charset_expand_dlc.json                 —— `char → slot/pair/来源/槽类型`（单一真源）
输出（work/，gitignored）：
  · work/analysis/font/container_expanded_1024x644.bin     —— 补画后的图集容器（可回滚）
  · work/analysis/font/expand_report.json                  —— 自证报告
  · work/analysis/font/charset_before_dlc_expand.json       —— 回写前快照

★ 槽位分配（确定性、可复现；顺序固定 = 频次降序的缺字表 × slot 升序）
  1. **禁止**用 trail ∈ {0xB1,0xB5} 的槽（`_trail_fix_hashr` 实证：引擎 DrawString/CharWidth 对
     0xB1/0xB5 有硬编码图标特判，命中会逐字符写坏内存）。★ 全部 50 个「未映射槽」都恰好是这类
     哨兵槽，**一个都不能用**（它们不是可用空槽）。
  2. 其次用**零引用 PUA 占位槽**：非 col-63、非哨兵、槽内零墨、且该 PUA 字符在全部译文里
     引用次数 = 0（正文没引用过的占位键可回收）。按 slot 升序分配。
  3. 跳过 col-63（x=1008 右缘贴 1024，引擎采不到）。
  4. **永不覆盖**已登记真汉字槽（无论译文是否引用）。
  ⇒ 当前安全容量 = 298 槽（334 PUA − 36 col63）；26 个缺字用掉 26 ⇒ 剩 272 槽。

★ 回写语义：PUA 回收 = 删掉一个 PUA 占位键、用同一对偶码登记真字 ⇒ **pair_of 总数不变（2300）**，
  但真字 1966→1992、PUA 334→308。对偶码本身不新增（安全容量里没有未占用的安全码位）。

构建期接口（只读，不写任何文件）：
    import expand_charset as EC
    container, report = EC.expand_container(seed_container)
    new_pak, info = fontlib.build_new_pak(..., container=container)

开发期命令（写 charset/expand json + work 报告）：
    python tools/font/expand_charset.py                # 规划+补画+回写+自证
    python tools/font/expand_charset.py --dry-run      # 只算不写
    python tools/font/expand_charset.py --verify-only  # 只校验当前 charset/expand json 与容器一致
"""
import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import sys
import time
from collections import Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
import fontlib as F                                                   # noqa: E402

# ── 路径常量（构建期与开发期共用） ──
CHARSET = F.CHARSET                                                   # assets/charset/charset_compiled_zh16.json
EXPAND_JSON = os.path.join(REPO, 'assets', 'charset', 'charset_expand_dlc.json')
MISSING_JSON = os.path.join(REPO, 'work', 'translation', 'merged', 'missing_chars.json')
CORPUS_CSV = os.path.join(REPO, 'work', 'translation', 'merged', 'translations_all.csv')
OUTDIR = os.path.join(REPO, 'work', 'analysis', 'font')
CONTAINER_OUT = os.path.join(OUTDIR, 'container_expanded_1024x644.bin')
REPORT_OUT = os.path.join(OUTDIR, 'expand_report.json')
CHARSET_BACKUP = os.path.join(OUTDIR, 'charset_before_dlc_expand.json')

SCHEMA = 'grjs-font-expand/1'
TOOL = 'tools/font/expand_charset.py'
TOOL_VERSION = 'r1.0'
# 引擎硬编码图标字节（对偶码 trail 不得落在其上；见 charset._trail_fix_hashr）
FORBIDDEN_TRAILS = (0xB1, 0xB5)
PUA_LO, PUA_HI = 0xE000, 0xF8FF


def P(*a):
    print(' '.join(str(x) for x in a), flush=True)


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def read_json(path):
    with io.open(path, encoding='utf-8') as f:
        return json.load(f)


def write_json_atomic(path, obj):
    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write('\n')
    os.replace(tmp, path)


# ═════════════════════════ 装载 ═════════════════════════
def load_seed_container(seed_dir=None):
    """从 seed 读中文图集容器（只读）。"""
    seed_dir = os.path.abspath(seed_dir or F.SEED_DIR)
    pak_p = os.path.join(seed_dir, 'COMMON_PAK.MENU3.zh.bin')
    meta_p = os.path.join(seed_dir, 'meta.json')
    if not (os.path.isfile(pak_p) and os.path.isfile(meta_p)):
        raise SystemExit('!! seed 不完整（缺 COMMON_PAK.MENU3.zh.bin / meta.json）: %s\n'
                         '   先跑 python tools/font/extract_seed.py' % seed_dir)
    meta = read_json(meta_p)
    pak = io.open(pak_p, 'rb').read()
    if sha256(pak) != meta['files']['COMMON_PAK.MENU3.zh.bin']['sha256']:
        raise SystemExit('!! seed COMMON_PAK sha256 与 meta 不符')
    recs = F.pak_parse(pak)
    _i, fr = F.pak_find(recs, 'new_font_revised')
    cont = pak[fr['px_off']:fr['px_off'] + fr['px']]
    if sha256(cont) != meta['atlas']['container_sha256']:
        raise SystemExit('!! seed 图集容器 sha256 与 meta 不符')
    return cont, meta


def load_corpus_text(path=None):
    path = os.path.abspath(path or CORPUS_CSV)
    if not os.path.isfile(path):
        raise SystemExit('!! 找不到合并译文: %s' % path)
    with io.open(path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    return ''.join(r['text_zh'] for r in rows), rows, path


# ═════════════════════════ 槽位表 ═════════════════════════
def build_slot_table(container, charset, usage):
    """给 2350 个 slot 建账：字符/对偶码/墨/是否 col63/是否 trail 哨兵/引用数。"""
    tex, _empty, _pk, _segs = F.atlas_engine_image(
        container, F.ATLAS_W, F.ATLAS_H, F.ATLAS_PSM)
    ink = tex == 0
    pair = {ch: tuple(v) for ch, v in charset['pair_of'].items()}
    slot2ch = {F.slot_of(*p): ch for ch, p in pair.items()}
    sentinel = set(charset.get('_trail_fix_hashr', {}).get('sentinel_slots') or [])
    rows, stat = [], Counter()
    for slot in range(F.PAIR_CAP):
        row, col, x, y = F.slot_cell(slot)
        b1, b2 = F.pair_of_slot(slot)
        inked = bool(ink[y:y + F.CH, x:x + F.CW].any())
        ch = slot2ch.get(slot)
        is_col63 = (col == F.NCOL - 1)
        is_sentinel = (b2 in FORBIDDEN_TRAILS) or (slot in sentinel)
        if is_col63:
            cat = 'col63'
        elif is_sentinel:
            cat = 'sentinel_forbidden'
        elif ch is None:
            cat = 'unmapped'
        elif PUA_LO <= ord(ch) <= PUA_HI:
            ref = usage.get(ch, 0)
            cat = 'pua_referenced' if ref else 'pua_recyclable'
        else:
            cat = 'real_used' if usage.get(ch, 0) else 'real_unused'
        stat[cat] += 1
        rows.append(dict(slot=slot, row=row, col=col, x=x, y=y, b1=b1, b2=b2,
                         char=ch, inked=inked, col63=is_col63, sentinel=is_sentinel,
                         ref=usage.get(ch, 0) if ch else 0, cat=cat))
    return rows, stat


def existing_assignments(expand_obj):
    """expand json → {char: entry}（按文件顺序）。"""
    out = {}
    for e in (expand_obj or {}).get('assignments', []):
        out[e['char']] = e
    return out


def plan(rows, charset, missing_chars, existing):
    """确定性规划。返回 (assignments, stats, warnings)。"""
    by_slot = {r['slot']: r for r in rows}
    pair = {ch: tuple(v) for ch, v in charset['pair_of'].items()}
    used_slots = set()
    assignments, warnings = [], []
    # ① 既有登记：必须保留（字符仍在字符集里、pair/slot 自洽）
    for ch, e in existing.items():
        slot = int(e['slot'])
        if slot not in by_slot:
            raise SystemExit('!! expand json 的 slot 越界: %s -> %d' % (ch, slot))
        r = by_slot[slot]
        b1, b2 = int(e['b1']), int(e['b2'])
        if ch not in pair:
            raise SystemExit('!! expand json 里的 %s 不在 charset pair_of（字符集被改过？）' % ch)
        if tuple(pair[ch]) != (b1, b2):
            raise SystemExit('!! expand json 与 charset 对偶码不一致: %s %s vs %s'
                             % (ch, (b1, b2), pair[ch]))
        if F.slot_of(b1, b2) != slot:
            raise SystemExit('!! expand json 的 slot 与对偶码公式不符: %s' % ch)
        if b2 in FORBIDDEN_TRAILS:
            raise SystemExit('!! expand json 的 %s 用了 trail 哨兵 0x%02X' % (ch, b2))
        assignments.append(dict(char=ch, slot=slot, b1=b1, b2=b2,
                                slot_type=e.get('slot_type', 'pua_recycled'),
                                old_pua=e.get('old_pua'), source='expand_json'))
        used_slots.add(slot)
    # ② 新缺字：按 missing 顺序，逐个拿「安全 PUA 可回收槽」（slot 升序）
    avail = [r['slot'] for r in rows
             if r['cat'] == 'pua_recyclable' and r['slot'] not in used_slots and not r['inked']]
    avail.sort()
    if avail:
        avail_iter = iter(avail)
    else:
        avail_iter = iter(())
    new_count = 0
    for ch in missing_chars:
        if ch in existing:
            continue
        if ch in pair:                                  # 字符集里已登记（别的途径）
            b1, b2 = pair[ch]
            slot = F.slot_of(b1, b2)
            if by_slot[slot]['cat'] == 'sentinel_forbidden' or b2 in FORBIDDEN_TRAILS:
                raise SystemExit('!! 已登记字符 %s 用了 trail 哨兵（历史遗留冲突）' % ch)
            assignments.append(dict(char=ch, slot=slot, b1=b1, b2=b2,
                                    slot_type='pre_existing', old_pua=None,
                                    source='charset'))
            used_slots.add(slot)
            continue
        try:
            slot = next(avail_iter)
        except StopIteration:
            raise SystemExit('!! 安全槽位耗尽：还有缺字 %r 无法分配（请扩充图集或回收更多 PUA 槽）'
                             % [c for c in missing_chars if c not in pair and c not in existing])
        r = by_slot[slot]
        assignments.append(dict(char=ch, slot=slot, b1=r['b1'], b2=r['b2'],
                                slot_type='pua_recycled', old_pua=r['char'],
                                source='missing_chars'))
        used_slots.add(slot)
        new_count += 1
    # ③ 容量账
    pua_safe = [r for r in rows if r['cat'] == 'pua_recyclable' and not r['inked']]
    free_after = [r['slot'] for r in pua_safe if r['slot'] not in used_slots]
    st = dict(
        capacity_safe=len(pua_safe),
        assigned_total=len(assignments),
        assigned_new=new_count,
        remaining_safe=len(free_after),
        first_remaining=free_after[:8],
        sentinel_forbidden=sum(1 for r in rows if r['cat'] == 'sentinel_forbidden'),
        col63=sum(1 for r in rows if r['cat'] == 'col63'),
        unmapped=sum(1 for r in rows if r['cat'] == 'unmapped'),
        pua_recyclable_total=len(pua_safe),
        real_used=sum(1 for r in rows if r['cat'] == 'real_used'),
        real_unused=sum(1 for r in rows if r['cat'] == 'real_unused'),
        pua_referenced=sum(1 for r in rows if r['cat'] == 'pua_referenced'),
    )
    if st['unmapped']:
        warnings.append('存在 %d 个未映射槽（%s），但全部是 trail 0xB1/0xB5 哨兵 ⇒ 视为不可用'
                        % (st['unmapped'], '见 _trail_fix_hashr'))
    return assignments, st, warnings


# ═════════════════════════ 补画（构建期接口） ═════════════════════════
def apply(container, assignments, ttf_path=None):
    """把 assignments（char+slot）画进容器副本（4bpp 半字节安全），返回 (new_container, rows)。

    自证：目标格 xor==0（与 TTF 模板）；非目标像素零改动；目标格「无墨→有墨」；
          GIF 段头字节零改动。
    """
    ttf_path = os.path.abspath(ttf_path or F.TTF)
    tex0, _empty, packets, segs = F.atlas_engine_image(
        container, F.ATLAS_W, F.ATLAS_H, F.ATLAS_PSM)
    ink0 = tex0 == 0
    # 目标格若有残墨，先清格（当前 PUA 槽全零墨；保留逻辑以备将来）
    clear_slots = []
    for e in assignments:
        s = e['slot']
        r = F.slot_cell(s)
        if ink0[r[3]:r[3] + F.CH, r[2]:r[2] + F.CW].any():
            clear_slots.append(s)
    cont = container
    if clear_slots:
        ys, xs, vals = [], [], []
        for s in clear_slots:
            _row, _col, x, y = F.slot_cell(s)
            yy, xx = np.meshgrid(np.arange(F.CH), np.arange(F.CW), indexing='ij')
            ys.extend((y + yy).reshape(-1).tolist())
            xs.extend((x + xx).reshape(-1).tolist())
            vals.extend([1] * (F.CH * F.CW))            # 1 = 空白索引
        cont = F.atlas_write_pixels(cont, F.ATLAS_W, F.ATLAS_PSM, segs, ys, xs, vals)
    # 用 fontlib 的补画器（内部会断言目标格为空并逐字回读 xor）
    char_map = {e['char']: int(e['slot']) for e in assignments}
    new_cont, draw_rows = F.draw_glyphs(cont, F.ATLAS_W, F.ATLAS_H, F.ATLAS_PSM,
                                        char_map, ttf_path=ttf_path)
    # 回读校验
    tex1, _e1, _pk1, _sg1 = F.atlas_engine_image(new_cont, F.ATLAS_W, F.ATLAS_H, F.ATLAS_PSM)
    ink1 = tex1 == 0
    target = {int(e['slot']): e for e in assignments}
    changed = set()
    for s in range(F.PAIR_CAP):
        _row, _col, x, y = F.slot_cell(s)
        if not np.array_equal(ink0[y:y + F.CH, x:x + F.CW], ink1[y:y + F.CH, x:x + F.CW]):
            changed.add(s)
    if changed != set(target):
        raise SystemExit('!! 补画越界：改动槽 %s ≠ 目标槽 %s'
                         % (sorted(changed - set(target)), sorted(set(target) - changed)))
    non_target_changed = len(changed - set(target))
    # 目标格：空→有墨；回读 xor
    rows = []
    draw_by_char = {d['char']: d for d in draw_rows}
    for e in assignments:
        s = int(e['slot'])
        _row, _col, x, y = F.slot_cell(s)
        old_ink = int(ink0[y:y + F.CH, x:x + F.CW].sum())
        new_ink = int(ink1[y:y + F.CH, x:x + F.CW].sum())
        d = draw_by_char[e['char']]
        if not d.get('readback_ok', False):
            raise SystemExit('!! %s (slot %d) 回读 xor != 0' % (e['char'], s))
        if not (old_ink == 0 and new_ink > 0) and s not in clear_slots:
            raise SystemExit('!! %s (slot %d) 不是「无墨→有墨」(old=%d new=%d)'
                             % (e['char'], s, old_ink, new_ink))
        rows.append(dict(char=e['char'], slot=s, b1=e['b1'], b2=e['b2'],
                         slot_type=e['slot_type'], old_pua=e.get('old_pua'),
                         cell=[x, y], xor=d['xor'], ink=new_ink,
                         cell_changed=(s in changed),
                         non_target_changed=non_target_changed,
                         cleared=(s in clear_slots)))
    # 段头零改动
    def headers(cont):
        out = []
        for p in packets:
            if p['kind'] == 'ad':
                out.append(cont[p['off']:p['off'] + 32])
            elif p['kind'] == 'image':
                out.append(cont[p['off']:p['off'] + 16])
        out.append(cont[len(cont) - 16:])
        return out
    if headers(container) != headers(new_cont):
        raise SystemExit('!! 补画改动了 GIF 段头字节（不允许）')
    if len(new_cont) != len(container):
        raise SystemExit('!! 容器长度变了: %d -> %d' % (len(container), len(new_cont)))
    return new_cont, rows


# ═════════════════════════ 字符集回写 ═════════════════════════
def update_charset(charset, assignments):
    """返回 (new_charset, diff)。PUA 回收 = 删 PUA 键 + 以同一对偶码登记真字。"""
    new = json.loads(json.dumps(charset))              # 深拷贝
    pair = new['pair_of']
    added, replaced = [], []
    for e in assignments:
        ch = e['char']
        if e['slot_type'] == 'pua_recycled':
            old = e.get('old_pua')
            if old in pair:
                if tuple(pair[old]) != (e['b1'], e['b2']):
                    raise SystemExit('!! 回收槽对偶码不符: %s/%s' % (old, ch))
                del pair[old]
                replaced.append(dict(char=ch, old_pua=old))
            pair[ch] = [e['b1'], e['b2']]
            added.append(ch)
        elif e['slot_type'] == 'pre_existing':
            pass
        else:
            pair[ch] = [e['b1'], e['b2']]
            added.append(ch)
    # meta：单一真源记录（charset 里保留一份摘要，便于审计）
    n_real = sum(1 for c in pair if not (PUA_LO <= ord(c) <= PUA_HI))
    n_pua = len(pair) - n_real
    new['_expand_dlc'] = dict(
        note='DLC 字符集扩充：把译文缺字画进零引用 PUA 占位槽（同一对偶码回收）；'
             '禁止使用 trail 0xB1/0xB5 哨兵槽；col63 不可用。构建期由 '
             'tools/font/expand_charset.py::expand_container() 补画。',
        tool=TOOL, tool_version=TOOL_VERSION,
        pairs_total=len(pair), real_chars=n_real, pua_keys=n_pua,
        added=[dict(char=e['char'], slot=e['slot'],
                    pair='%02X%02X' % (e['b1'], e['b2']),
                    old_pua=e.get('old_pua')) for e in assignments],
    )
    return new, dict(added=added, replaced=replaced,
                     pairs_total=len(pair), real_chars=n_real, pua_keys=n_pua)


# ═════════════════════════ 自证 ═════════════════════════
def verify_new_charset(new_charset, new_container, assignments, corpus_text, tmp_dir=None):
    """回读自证：字符集可编码/解码、全部译文 encode_strict 通过、图集逐字 xor==0。"""
    import tcslib
    tmp_dir = os.path.abspath(tmp_dir or OUTDIR)
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_cs = os.path.join(tmp_dir, '_charset_verify_tmp.json')
    write_json_atomic(tmp_cs, new_charset)
    cs = tcslib.Charset(tmp_cs)
    rows = []
    # ① 逐新字：encode_strict == 对偶字节；decode 回环
    for e in assignments:
        ch, b1, b2 = e['char'], e['b1'], e['b2']
        try:
            b = cs.encode_strict(ch)
        except Exception as ex:                             # noqa: BLE001
            raise SystemExit('!! 新字 %s encode_strict 失败: %s' % (ch, ex))
        if b != bytes([b1, b2]):
            raise SystemExit('!! 新字 %s encode_strict=%s != 期望 %02X%02X'
                             % (ch, b.hex(), b1, b2))
        back, _ = cs.decode(b)
        if back != ch:
            raise SystemExit('!! 新字 %s decode 回环不符: %r' % (ch, back))
        rows.append(dict(char=ch, bytes=b.hex(), ok=True))
    # ② 全量译文 encode_strict
    n_rows, n_bytes, bad = -1, 0, []
    try:
        enc = cs.encode_strict(corpus_text)
        n_bytes = len(enc)
        n_rows = -1
    except Exception as ex:                                 # noqa: BLE001
        bad.append(str(ex))
    # ③ 图集逐字 xor==0（用 TTF 模板）
    tex, _e, _pk, _segs = F.atlas_engine_image(new_container, F.ATLAS_W, F.ATLAS_H, F.ATLAS_PSM)
    from PIL import Image, ImageDraw, ImageFont
    fnt = ImageFont.truetype(F.TTF, 16)
    for e in assignments:
        _row, _col, x, y = F.slot_cell(e['slot'])
        img = Image.new('L', (32, 32), 255)
        ImageDraw.Draw(img).text((8, 8), e['char'], font=fnt, fill=0)
        tpl = np.asarray(img)[8:24, 8:24] < 128
        xor = int((tpl ^ (tex[y:y + F.CH, x:x + F.CW] == 0)).sum())
        if xor != 0:
            raise SystemExit('!! %s 图集格 xor=%d != 0' % (e['char'], xor))
    return dict(new_chars_ok=len(rows), new_char_bytes_ok=True,
                corpus_encode_bytes=n_bytes, corpus_encode_error=(bad or None),
                atlas_xor_all_zero=True, tmp_charset=tmp_cs)


# ═════════════════════════ 构建期接口（只读） ═════════════════════════
def expand_container(container, verify_only=False):
    """build.py 调用：读 charset+expand json，把已登记的扩充字画进容器并校验。

    返回 (new_container, report)。不写任何文件。
    """
    if not os.path.isfile(EXPAND_JSON):
        return container, dict(assignments=0, note='无 charset_expand_dlc.json，跳过')
    obj = read_json(EXPAND_JSON)
    charset = read_json(CHARSET)
    pair = {ch: tuple(v) for ch, v in charset['pair_of'].items()}
    assignments = []
    for e in obj.get('assignments', []):
        ch, slot = e['char'], int(e['slot'])
        b1, b2 = int(e['b1']), int(e['b2'])
        if ch not in pair:
            raise SystemExit('!! expand json 的 %s 不在 charset（请重跑 expand_charset.py）' % ch)
        if tuple(pair[ch]) != (b1, b2):
            raise SystemExit('!! %s 在 expand json 与 charset 中对偶码不一致' % ch)
        if F.slot_of(b1, b2) != slot:
            raise SystemExit('!! %s slot/对偶码公式不符' % ch)
        if b2 in FORBIDDEN_TRAILS:
            raise SystemExit('!! %s 占用 trail 哨兵 0x%02X' % (ch, b2))
        assignments.append(dict(char=ch, slot=slot, b1=b1, b2=b2,
                                slot_type=e.get('slot_type', 'pua_recycled'),
                                old_pua=e.get('old_pua')))
    if not assignments:
        return container, dict(assignments=0)
    new_cont, rows = apply(container, assignments)
    return new_cont, dict(assignments=len(rows), rows=rows,
                          container_sha256=sha256(new_cont))


# ═════════════════════════ 开发期主流程（写文件） ═════════════════════════
def main(argv=None):
    ap = argparse.ArgumentParser(description='DLC 字符集扩充 / 图集补画')
    ap.add_argument('--dry-run', action='store_true', help='只规划+补画+自证，不写 charset/expand json')
    ap.add_argument('--verify-only', action='store_true', help='只校验现有 charset/expand json/容器')
    ap.add_argument('--missing', default=MISSING_JSON)
    ap.add_argument('--corpus', default=CORPUS_CSV)
    ap.add_argument('--charset', default=CHARSET)
    ap.add_argument('--outdir', default=OUTDIR)
    a = ap.parse_args(argv)
    t0 = time.time()
    os.makedirs(a.outdir, exist_ok=True)
    P('=' * 78)
    P('[1] 装载 seed 图集容器 / 字符集 / 全部译文')
    container, seed_meta = load_seed_container()
    charset = read_json(a.charset)
    corpus, corpus_rows, corpus_path = load_corpus_text(a.corpus)
    usage = Counter(corpus)
    missing_obj = read_json(a.missing)
    missing = list(missing_obj.get('chars') or [])
    P('    图集容器 %d B sha=%s ; 字符集 pair=%d ; 译文 %d 行 / %d 字 / 唯一 %d'
      % (len(container), sha256(container)[:16], len(charset['pair_of']),
         len(corpus_rows), len(corpus), len(usage)))
    P('    缺字表 %d 个: %s' % (len(missing), ''.join(missing)))
    # 槽位账
    rows, stat = build_slot_table(container, charset, usage)
    P('[2] 槽位账:', dict(stat))
    P('    安全容量 = pua_recyclable %d（col63=%d 不可用；sentinel=%d 禁止；未映射=%d 全为哨兵）'
      % (stat['pua_recyclable'], stat['col63'], stat['sentinel_forbidden'], stat['unmapped']))
    # 既有 expand json
    existing = {}
    if os.path.isfile(EXPAND_JSON):
        existing = existing_assignments(read_json(EXPAND_JSON))
        P('    既有 expand 登记 %d 条' % len(existing))
    assignments, st, warnings = plan(rows, charset, missing, existing)
    for w in warnings:
        P('    [warn]', w)
    P('[3] 规划: 总登记 %d（本轮新增 %d）；剩余安全槽 %d %s'
      % (st['assigned_total'], st['assigned_new'], st['remaining_safe'], st['first_remaining']))
    for e in assignments:
        P('    %s -> slot %-4d %02X%02X  类型=%-13s 旧占位=%r'
          % (e['char'], e['slot'], e['b1'], e['b2'], e['slot_type'],
             e.get('old_pua')))
    if a.verify_only:
        if not assignments:
            P('    （无登记，跳过）')
            return 0
        _new_cont, _rows = apply(container, assignments)
        rep = verify_new_charset(charset, _new_cont, assignments, corpus, a.outdir)
        P('[4] verify-only:', rep)
        return 0
    # 补画
    P('[4] 补画（4bpp 半字节安全；目标格 xor==0 / 非目标零改动 / 空→有墨）')
    new_cont, draw_rows = apply(container, assignments)
    for r in draw_rows:
        P('    %s slot=%-4d cell=%-9s xor=%d ink=%d%s'
          % (r['char'], r['slot'], r['cell'], r['xor'], r['ink'],
             ' (清残墨)' if r['cleared'] else ''))
    # 更新字符集
    new_charset, diff = update_charset(charset, assignments)
    P('[5] 字符集: pair %d -> %d（真字 %d -> %d ; PUA %d -> %d）'
      % (len(charset['pair_of']), diff['pairs_total'],
         sum(1 for c in charset['pair_of'] if not (PUA_LO <= ord(c) <= PUA_HI)),
         diff['real_chars'],
         sum(1 for c in charset['pair_of'] if PUA_LO <= ord(c) <= PUA_HI), diff['pua_keys']))
    # 自证
    P('[6] 自证')
    vrep = verify_new_charset(new_charset, new_cont, assignments, corpus, a.outdir)
    P('    新字 encode/decode 回环: %d/%d OK' % (vrep['new_chars_ok'], len(assignments)))
    P('    全部译文 encode_strict: %d B %s'
      % (vrep['corpus_encode_bytes'],
         'OK' if not vrep['corpus_encode_error'] else 'FAIL %s' % vrep['corpus_encode_error']))
    P('    图集逐字 xor==0: %s' % vrep['atlas_xor_all_zero'])
    # 含新字的示例译文（真实语料行，encode_strict 成功即证明可注入）
    examples = []
    seen_chars = set()
    for r in corpus_rows:
        zh = r['text_zh']
        for ch in zh:
            if ch in {e['char'] for e in assignments} and ch not in seen_chars:
                try:
                    enc = cs2.encode_strict(zh) if False else None
                except Exception:                              # noqa: BLE001
                    enc = None
                examples.append(dict(char=ch, resource=r['resource'], id=r['id'],
                                     text=zh if len(zh) <= 80 else zh[:80] + '…',
                                     ok=True))
                seen_chars.add(ch)
        if len(seen_chars) >= len({e['char'] for e in assignments}):
            break
    # 每条示例再单独用「新字符集」严格编码一次（独立 Charset 实例）
    import tcslib as _T
    _cs = _T.Charset(os.path.join(a.outdir, '_charset_verify_tmp.json'))
    bad_ex = []
    for ex in examples:
        try:
            ex['bytes_hex'] = _cs.encode_strict(
                next(r['text_zh'] for r in corpus_rows
                     if r['resource'] == ex['resource'] and r['id'] == ex['id'])).hex()
            ex['encode_strict'] = 'OK'
        except Exception as e:                                 # noqa: BLE001
            ex['encode_strict'] = 'FAIL: %s' % e
            bad_ex.append(ex['char'])
    report = dict(tool=TOOL, tool_version=TOOL_VERSION, schema=SCHEMA,
                  generated=time.strftime('%Y-%m-%d %H:%M:%S'),
                  seed_container_sha256=sha256(container),
                  charset_before_sha256=sha256(io.open(a.charset, 'rb').read()),
                  corpus=dict(path=corpus_path, rows=len(corpus_rows),
                              chars=len(corpus), unique=len(usage)),
                  missing=dict(path=os.path.abspath(a.missing), count=len(missing),
                               chars=missing),
                  slot_stats=dict(stat), plan_stats=dict(st),
                  examples=examples, example_failures=bad_ex,
                  atlas_non_target_changed=0,
                  interface=dict(
                      build_call='import expand_charset as EC; '
                                 'container, report = EC.expand_container(seed_container)',
                      one_shot='EC.apply(container, assignments, ttf_path=None) -> (new_container, rows)',
                      inputs=[os.path.relpath(a.charset, REPO).replace('\\', '/'),
                              os.path.relpath(EXPAND_JSON, REPO).replace('\\', '/')]),
                  assignments=draw_rows, charset_diff=diff,
                  verify=vrep, new_container_sha256=sha256(new_cont),
                  new_container=os.path.abspath(CONTAINER_OUT))
    P('    示例译文 %d 条（含新字）：' % len(examples))
    for ex in examples[:5]:
        P('      %s [%s/%s] %s … encode_strict=%s'
          % (ex['char'], ex['resource'], ex['id'], ex['text'][:34], ex['encode_strict']))
    if bad_ex:
        raise SystemExit('!! 示例译文 encode_strict 失败: %r' % bad_ex)
    if a.dry_run:
        P('[dry-run] 不写 charset / expand json / 容器')
    else:
        # 快照 + 原子写
        io.open(CHARSET_BACKUP, 'wb').write(io.open(a.charset, 'rb').read())
        write_json_atomic(a.charset, new_charset)
        # expand json（单一真源）
        exp_obj = dict(schema=SCHEMA, tool=TOOL, tool_version=TOOL_VERSION,
                       generated=report['generated'],
                       sources=dict(seed_container_sha256=sha256(container),
                                    charset=os.path.relpath(a.charset, REPO).replace('\\', '/'),
                                    charset_sha256=sha256(
                                        io.open(a.charset, 'rb').read()),
                                    missing=os.path.relpath(os.path.abspath(a.missing), REPO).replace('\\', '/'),
                                    corpus=os.path.relpath(corpus_path, REPO).replace('\\', '/')),
                       capacity=dict(
                                     safe=(len([r for r in rows if r['cat'] == 'pua_recyclable'])
                                           + len([x for x in assignments
                                                  if x['slot_type'] == 'pua_recycled'])),
                                     used=len(assignments),
                                     remaining=st['remaining_safe'],
                                     sentinel_forbidden=stat['sentinel_forbidden'],
                                     col63=stat['col63'],
                                     note='安全容量 = 零引用 PUA 槽（trail 0xB1/0xB5 哨兵槽禁止使用）'),
                       totals=dict(pairs_before=len(charset['pair_of']),
                                   pairs_after=diff['pairs_total'],
                                   real_chars_after=diff['real_chars'],
                                   pua_keys_after=diff['pua_keys']),
                       assignments=[dict(char=r['char'], slot=r['slot'],
                                         b1=r['b1'], b2=r['b2'],
                                         hex='%02X%02X' % (r['b1'], r['b2']),
                                         slot_type=r['slot_type'],
                                         old_pua=r['old_pua'],
                                         cell=r['cell'], xor=r['xor'], ink=r['ink'])
                                    for r in draw_rows])
        write_json_atomic(EXPAND_JSON, exp_obj)
        io.open(CONTAINER_OUT, 'wb').write(new_cont)
        write_json_atomic(REPORT_OUT, report)
        P('[7] 写出: charset / expand json / 容器 / 报告')
        P('    %s' % a.charset)
        P('    %s' % EXPAND_JSON)
        P('    %s' % CONTAINER_OUT)
        P('    %s' % REPORT_OUT)
        # 幂等自检：重读 → 再规划应 0 新增
        charset2 = read_json(a.charset)
        rows2, stat2 = build_slot_table(new_cont, charset2, usage)
        exp2 = existing_assignments(read_json(EXPAND_JSON))
        _a2, st2, _w2 = plan(rows2, charset2, missing, exp2)
        P('[8] 幂等: 重跑新增 %d（应=0）；剩余安全槽 %d' % (st2['assigned_new'],
                                                      st2['remaining_safe']))
        if st2['assigned_new'] != 0:
            raise SystemExit('!! 幂等自检失败：重跑仍产生新分配')
    P('=' * 78)
    P('DONE %.1fs — 新字 %d，pair %d，安全余量 %d'
      % (time.time() - t0, len(assignments), diff['pairs_total'], st['remaining_safe']))
    return 0


def pua_safe_capacity(stat):
    return stat.get('pua_recyclable', 0)


if __name__ == '__main__':
    sys.exit(main())
