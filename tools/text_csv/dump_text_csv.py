# -*- coding: utf-8 -*-
r"""dump_text_csv.py — 把 PS2《幽灵行动》盘内的长段文本 dump 成「按 kind 分类的多张 CSV」

round29 / 工具链: dump(本脚本) → 人工在 Excel 里改换行 → inject_text_csv.py

★ round37（用户要求「改成按照 kind 进行分类 输出多个表格」）:
  输出**不再是一张合并的大表**, 而是**按 kind 拆开的多张表**, 都在同一个基准名下::

      <out 去掉 .csv>_long.csv          kind=long          ★ 可写 {WRAP} 控制断点的长段
      <out 去掉 .csv>_long_nowrap.csv   kind=long_nowrap   语言表长段 (简报等; 宽度未标定)
      <out 去掉 .csv>_short.csv         kind=short         按钮 / 条目名 / 短提示
      <out 去掉 .csv>_locked.csv        kind=locked        不可编辑 (通常 0 条 ⇒ 不产出)
      <out 去掉 .csv>.meta.json         每张表的条数 / kind 列表 / 总条数 / sha256
      <out 去掉 .csv>.txt               **合并的一份**轻量快照 (id<TAB>正文; 便于 git diff)

  例: --out work/builds/GR_ZH92/text/GR_ZH92_text.csv
      ⇒ work/builds/GR_ZH92/text/GR_ZH92_text_long.csv / _long_nowrap.csv / _short.csv …
  ★ **每张表的表头与列完全不变** (16 列) —— 只是行按 kind 分开了。
  ★ 主表 (long / long_nowrap / short) 即使 **0 条也照样产出只有表头的空表**, 免得你以为漏了。
  ★ `--only-kind long,short` 只产出这几张表 (调试/小批编辑用)。
  ★ `--carry-edited` 可给多次、也可以给目录 (把旧表里人工改过的 text_edited 原样搬到新表)。

设计要点 (详见 tools/text_csv/FORMAT.md):
  · 输出 UTF-8 with BOM + CRLF, 正文列用引号包住 → Excel 双击直接可开可存
  · 一条文本 = CSV 一行 (换行符出现在被引号包住的单元格内, 不会拆行)
  · ★ round36 换行/断点口径 (与注入严格互逆, 见 FORMAT.md §3):
        盘上 {br} → CSV 里恰好 1 个换行;  盘上 {p} → CSV 里恰好 1 个空行;
        **人工断点**: 人在 text_edited 里写 `{WRAP}` / `{Warp}` (大小写不限)
                      ⇒ 注入时变成**一个真换行** (盘上 {br});
        **引擎自动折行点**: dump **绝不**写进正文列 —— 只写进只读列
                      `wrap_hint` (字符位置) 与 `wrap_preview` (带 `|` 的预览)。
    round35 及更早把"引擎会自动折行"也写成 `{WRAP}` 塞进正文列 ⇒ 与人工断点分不开:
    注入端只能整段丢弃 (用户写的断点永远不生效), 改当真换行又会把 1548 个自动提示固化。
    round36 的解法是"源头分开": dump 一个 `{WRAP}` 都不写 ⇒ CSV 里的 `{WRAP}`
    只可能是人写的, 一律当真断点。
  · ★ 写 CSV 前做**往返自检**: 每一行的 text_zh 必须能逐字节还原盘上原字节
    (`cell_to_bytes_text(text_zh) == 盘上字节`) —— 这是"人工怎么改都不会累积变坏"的机器判据。
  · 短文本(条目名/按钮标签)不插入换行
  · text_zh = 现值(只读参考); text_edited = 人工编辑栏 (dump 时预填为同内容)
    ⇒ 「不编辑任何东西」时 inject 逐字节不改动原盘
  · ★ round34: 新增只读参考列 text_en = **英文原文**, 紧挨在 text_zh 右边, 供人工对照校对。
    数据来自英文基线盘 (USA SLUS-206.13), 按 id 左连接; 注入器**完全忽略**这一列。
  · ★ round36: 新增只读列 wrap_hint / wrap_preview (引擎自动折行点); 注入器同样**完全忽略**。
  · ★ round36: `--carry-edited <旧 CSV>` 可把旧表里**人工改过的 text_edited** 搬进新表
    (重新 dump 不会丢掉用户的改动); round37 起可给多次/给目录。

用法:
  python tools/text_csv/dump_text_csv.py --iso work/builds/GR_ZH92/GR_ZH92.iso \
         --out work/builds/GR_ZH92/text/GR_ZH92_text.csv      # ⇒ 产出多张表
  python tools/text_csv/dump_text_csv.py --iso ... --out ... --carry-edited <旧大表或旧表目录>
  python tools/text_csv/dump_text_csv.py --iso ... --out ... --only-kind long,short
  python tools/text_csv/dump_text_csv.py --iso ... --out ... --resources LANG
  python tools/text_csv/dump_text_csv.py --iso ... --out ... --wrapw LANG=270   # 强制开启折行提示
  python tools/text_csv/dump_text_csv.py --iso ... --stats                      # 只统计
  python tools/text_csv/dump_text_csv.py --iso ... --out ... --en-iso <别的英文盘>
  python tools/text_csv/dump_text_csv.py --iso ... --out ... --no-en            # 不要 text_en
"""
import argparse
import csv
import datetime
import hashlib
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import tcslib as T                                                # noqa: E402

FMT_VERSION = T.FMT_TABLES         # ★ round37: text-csv/4 = 多表布局 (每张表仍 16 列)
FMT_LEGACY_MERGED = 'text-csv/3'   # round36 的合并大表 (还能注入, 但会提示改用多表)
LONG_MIN = 40                      # 长段文本判据: 编码字节 >= 40 (约 20 汉字)
# ★ round34: text_en (英文原文, 只读参考) 紧挨在 text_zh 右边 —— 用户要「旁边有一列英文原文」。
# ★ round36: wrap_hint / wrap_preview (引擎自动折行点, 只读提示) 紧跟 lines 之后。
#   列序: ... kind, wrap_w, lines, wrap_hint, wrap_preview, text_zh, text_en, text_edited, note
COLS = ['id', 'resource', 'container', 'entry_index', 'offset', 'len_bytes',
        'max_bytes', 'kind', 'wrap_w', 'lines', 'wrap_hint', 'wrap_preview',
        'text_zh', 'text_en', 'text_edited', 'note']
ALWAYS_QUOTE = {'text_zh', 'text_en', 'text_edited', 'note', 'wrap_preview'}
# 会被「Excel 显示不出来」硬门槛扫描的列 (round34 起含 text_en; round36 起含折行提示两列)
CELL_COLS = ('text_zh', 'text_en', 'text_edited', 'note', 'wrap_hint', 'wrap_preview')

# ★ round33 硬保证: 写出的 CSV 里**不许**出现 Excel 显示不出来的字符。
#   PUA (U+E000..U+F8FF) 在 Excel 里就是方框/空白 (用户报障的根因);
#   裸控制字符 (C0 除 \n、DEL、C1)、零宽/双向控制字符在 Excel 里同样不可见或错位。
#   这类字符现在一律换成 {{BTN:XXXX}} 标记; 万一将来字符集变动又漏出新的,
#   这里会**直接拒绝写出 CSV**并指名道姓, 而不是悄悄给用户一份没法编辑的文件。
#   round34: 扫描范围含 text_en —— 英文原文列同样不许出现 PUA / 不可见字符。
FORBIDDEN_RE = re.compile(
    '[\u0000-\u0009\u000b-\u001f\u007f-\u009f'      # C0(除 LF 0x0A) + DEL + C1
    '\ue000-\uf8ff'                                  # PUA 私有区
    '\u200b-\u200f\u2028\u2029\u202a-\u202e'         # 零宽 / 行分隔 / 双向控制
    '\u2060-\u2069\ufeff\u00ad]')                    # 词连接符 / 隔离符 / BOM / 软连字符


def assert_cells_clean(rows, cols=CELL_COLS):
    """★ 拒绝写出「Excel 里看不见」的 CSV。返回 (检查字符数, 若无问题则 None)。"""
    bad = []
    n = 0
    for r in rows:
        for c in cols:
            v = r.get(c) or ''
            n += len(v)
            m = FORBIDDEN_RE.search(v)
            if m:
                bad.append('%s 的 %s 列 @第 %d 个字符: U+%04X (%s)'
                           % (r.get('id'), c, m.start() + 1, ord(m.group(0)),
                              '私有区占位' if 0xE000 <= ord(m.group(0)) <= 0xF8FF
                              else '不可见控制字符'))
    if bad:
        raise SystemExit(
            '!! 拒绝写出 CSV: 还有 %d 处「Excel 显示不出来」的字符没被标记替换掉:\n   %s\n'
            '   怎么办: 这是工具链缺陷 —— 说明有占位字符没被识别成 {{BTN:XXXX}}。\n'
            '           若出在 text_en 列, 说明英文基线盘里有本工具没见过的高位字节;\n'
            '           请把上面这几处报给工程侧 (tcslib.EN_CP1252 / EN_ICON_BYTES)。'
            % (len(bad), '\n   '.join(bad[:12])))
    return n, None


# ─────────────────── ★ round35: 往返自检 (dump 的硬保证) ───────────────────
#   「人工怎么改都不会累积变坏」的机器判据只有一句话:
#        CSV 单元格 text_zh 用注入器的解析口径 (cell_to_bytes_text) 必须**逐字节**
#        还原盘上原字节。
#   只要这条对所有行成立 ⇒ ① dump 无损 (不含任何无法还原的信息);
#                              ② 人工在 CSV 里敲 1 个回车 = 盘上恰好多 1 个 {br},
#                                 敲 1 个空行 = 盘上恰好 1 个 {p}, 不会串味;
#                              ③ {WRAP} 建议断点**不占字节** (去掉后与原文逐字符相同)。
#   任何一条不成立 ⇒ 拒绝写 CSV (宁可报错, 也不给一份"看着没问题、注入就出事"的表)。
#   唯一例外: kind=locked (字节回环本身不稳定, 工具链本来就不改它)。

def _spans_consistent(text, wrap_w):
    """建议断点区间自检: wrap_seg_spans 必须与折行模型 wrap_seg 逐行一致且区间连续。

    ★ 比较用**折行模型的"看词"口径** (连续空白折叠成一个空格, 见 tcslib.norm_ws):
      模型按单空格切词, 而单元格保留原文的每一个空格 —— 二者只在这一处不同,
      写盘字节仍由往返自检 (lossless_reason 的第 2 步) 逐字节保证。
    """
    for (_a, _b, seg) in T.segments(text):
        spans, lines = T.wrap_seg_spans(seg, wrap_w), T.wrap_seg(seg, wrap_w)
        if len(spans) != len(lines):
            return '段 %r: 区间 %d 个 != 模型行 %d 行' % (seg[:24], len(spans), len(lines))
        if not all(spans[i][1] == spans[i + 1][0] for i in range(len(spans) - 1)) or \
                (spans and (spans[0][0] != 0 or spans[-1][1] != len(seg))):
            return '段 %r: 折行区间不连续' % seg[:24]
        for (x, y), ln in zip(spans, lines):
            if T.norm_ws(seg[x:y]) != T.norm_ws(ln):
                return '段 %r: 区间内容与模型行不同 (%r vs %r)' % (seg[:24], seg[x:y], ln)
    return None


def lossless_reason(rid, text, cell, raw, cs, wrap_w):
    """返回 None (= 无损) 或人话原因字符串。"""
    if wrap_w > 0:
        r = _spans_consistent(text, wrap_w)
        if r:
            return r
    try:
        back = T.cell_to_bytes_text(cell, cs)
    except T.CharsetError as ex:
        return '按注入口径编码失败: %s' % ex
    if back != raw:
        k = next((i for i in range(min(len(back), len(raw))) if back[i] != raw[i]),
                 min(len(back), len(raw)))
        return ('按注入口径回写, 字节与盘上不一致 (回 %d B / 盘上 %d B, 首处不同 @%d)\n'
                '         回: %s\n         盘: %s'
                % (len(back), len(raw), k,
                   cs.decode(back[:k + 12])[0][-14:].encode('unicode_escape').decode(),
                   cs.decode(raw[:k + 12])[0][-14:].encode('unicode_escape').decode()))
    return None


# ───────────────────────────── CSV 输出 ─────────────────────────────

def csv_field(name, value):
    s = '' if value is None else str(value)
    if name in ALWAYS_QUOTE or any(c in s for c in ',"\r\n'):
        return '"' + s.replace('"', '""') + '"'
    return s


def write_csv(path, rows, cols=COLS):
    with open(path, 'wb') as f:
        f.write(b'\xef\xbb\xbf')                               # UTF-8 BOM
        for r in [dict(zip(cols, cols))] + rows:
            line = ','.join(csv_field(c, r.get(c, '')) for c in cols)
            f.write(line.replace('\n', '\n').encode('utf-8') + b'\r\n')


# ─────────────────────── 资源装载 (通用) ───────────────────────

def load_resources(iso, names):
    """返回 {res: dict(kind, copies=[dict(tag, lba, idx, entry, blob, subs, ...)])}"""
    out = {}
    for name in names:
        spec = T.RES[name]
        copies = []
        for (img, lba, idx, tag) in spec['copies']:
            e = iso.img_entry(lba, idx)
            raw = iso.read(e['iso_off'], e['stored'])
            subs = T.lzo_subs(raw)
            blob = b''.join(s[0] for s in subs)
            copies.append(dict(img=img, lba=lba, idx=idx, tag=tag, entry=e,
                               raw=raw, subs=subs, blob=blob,
                               frame_len=sum(s[1] + 8 for s in subs)))
        out[name] = dict(kind=spec['kind'], copies=copies)
    return out


def free_capacity(res, blob, used_end, charset):
    """容器还能吃下多少「未压缩字节」—— 取 尾部可吸收 / 压缩槽余量折算 的较小值。"""
    cap_tail = len(blob) - used_end                      # 尾部陈旧数据可被顶掉
    caps = [cap_tail]
    for c in res['copies']:
        slot_free = c['entry']['stored'] - c['frame_len']
        ratio = len(c['blob']) / max(1, c['frame_len'])
        caps.append(int(slot_free * ratio * 0.9))
    return max(0, min(caps))


# ─────────────────── 只读参考列 text_en: 英文原文 (round34) ───────────────────

def hexkey(d):
    """{0x92: 14} → {'0x92': 14} (meta.json 里好读; JSON 的 key 只能是字符串)"""
    return dict(('0x%02X' % int(k), v) for k, v in d.items())


def _en_byte_note(hist):
    """人话描述某条 text_en 里出现过的英文盘原始非 ASCII 字节。"""
    parts = []
    for b, n in sorted(hist.items()):
        if b in T.EN_ICON_BYTES:
            parts.append('0x%02X→{{BTN:%04X}}×%d' % (b, 0xE000 + b, n))
        else:
            parts.append('0x%02X→%s×%d' % (b, T.EN_CP1252.get(b, '?'), n))
    return ('; ★text_en 里有英文盘原始非 ASCII 字节 %s (按 Windows-1252 转成可见字符; '
            '原字节不属于本盘, 仅校对参考)' % ' '.join(parts))


def attach_text_en(rows, en_lang, en_xml, en_info, enabled, reason):
    """给每行补上**只读**参考列 text_en (左连接: 中文有、英文没有 ⇒ 留空 + note 说明)。

    对齐键 = `id` (LANG: G###.I###; SFXML: 条目序 T####), 与 CSV 的 id 列完全一致。
    返回统计 dict。
    """
    known = set(en_lang) | set(en_xml)                       # 英文盘里**有正文**的条目
    blank = set(en_info['lang']['empty_ids']) | set(en_info['sfxml']['empty_ids']) \
        if en_info else set()                                # 英文盘里存在但 len=0 的条目
    st = dict(nonempty=0, blank=0, unaligned=[], byte_rows=0, by_res={})
    for r in rows:
        rid, res = r['id'], r['resource']
        d = st['by_res'].setdefault(res, dict(nonempty=0, blank=0, unaligned=0))
        if not enabled:
            r['text_en'] = ''
            r['note'] += '; ★text_en 留空 (英文原文列): %s' % reason
            continue
        v = (en_lang if res == 'LANG' else en_xml).get(rid, '')
        if v:
            r['text_en'] = v
            st['nonempty'] += 1
            d['nonempty'] += 1
            h = en_info['entry_bytes'].get(rid)
            if h:
                r['note'] += _en_byte_note(h)
                st['byte_rows'] += 1
        elif rid in known or rid in blank:
            r['text_en'] = ''
            r['note'] += ('; ★英文原文本身为空 (英文基线盘里这条存在但正文 len=0, '
                          '不是没对齐)')
            st['blank'] += 1
            d['blank'] += 1
        else:
            r['text_en'] = ''
            r['note'] += ('; ★英文基线盘里没有这一条 (按 id / 条目序对不上) ⇒ text_en 留空')
            st['unaligned'].append(rid)
            d['unaligned'] += 1
    st['total'] = len(rows)
    return st


# ─────────── ★ round36/37: 把旧表里的人工改动搬进新表 (--carry-edited) ───────────
#   重新 dump 会按**盘上字节**重建 text_zh/text_edited ⇒ 用户上次在 CSV 里改的东西会丢。
#   `--carry-edited <旧表>` 把旧表里 `text_edited != text_zh` 的行**原样**搬过来
#   (只搬这一列; 其它列一律以新 dump 为准)。搬运不改语义: 旧表 text_edited 里的
#   `{WRAP}`/`{Warp}` 在新表里同样是"人工断点" ⇒ 断点位置原样保留、注入时变成真换行。
#   ★ 只有**改过**的行才搬 —— 没改过的行在新表里本来就应该等于新 dump 的现值
#     (否则「一个字都不改直接注入 = 逐字节相同」这条硬指标就废了)。
#   ★ round37: 参数可给**多次**, 也可以给**目录** (自动读该目录下所有 *_text_*.csv;
#     老格式的合并大表也照旧能当搬运来源)。

def read_carried_edits(path):
    """读旧 CSV ⇒ ``(dict(id -> text_edited), dict(id -> text_zh), 旧表格式串)``。"""
    carried, old_zh = {}, {}
    meta_format = None
    with io.open(path, 'r', encoding='utf-8-sig', newline='') as f:
        rd = csv.DictReader(f)
        cols = rd.fieldnames or []
        for need in ('id', 'text_edited', 'text_zh'):
            if need not in cols:
                raise SystemExit('!! --carry-edited 的表缺 %s 列: %s\n   列 = %s'
                                 % (need, path, cols))
        for r in rd:
            rid = (r.get('id') or '').strip()
            if not rid:
                continue
            te, tz = r.get('text_edited'), r.get('text_zh') or ''
            if te is None or te == '' or te == tz:
                continue                       # 空 / 与旧表现值相同 ⇒ 没改过
            carried[rid] = te
            old_zh[rid] = tz
    mp = os.path.splitext(path)[0] + '.meta.json'
    if not os.path.isfile(mp):                 # 多表: meta 在表集基准名下 (…_text.meta.json)
        for cand in T.table_meta_paths(path):
            if os.path.isfile(cand):
                mp = cand
                break
    if os.path.isfile(mp):
        try:
            meta_format = json.load(open(mp, encoding='utf-8')).get('format')
        except Exception:                                          # noqa: BLE001
            meta_format = None
    return carried, old_zh, meta_format


def carry_source_paths(specs):
    """``--carry-edited`` 的参数 → 有序的旧表路径 (支持多份 / 目录 / 老的大表)。"""
    paths, notes = T.expand_csv_inputs(specs)
    bad = [n for n in notes if n['level'] == 'error']
    if bad:
        raise SystemExit('!! --carry-edited 找不到可读的旧表:\n   %s\n'
                         '   (可以给一份旧 CSV; 也可以给装着多表的 text/ 目录 —— '
                         '目录里的 *_text_*.csv 会全部读入)' % '\n   '.join(n['msg'] for n in bad))
    if not paths:
        raise SystemExit('!! --carry-edited 没有解析出任何旧表')
    return paths, notes


def apply_carry_edited(all_rows, specs):
    """把旧表的人工改动搬进 all_rows (就地改 text_edited + note)。返回统计 dict。"""
    paths, notes = carry_source_paths(specs)
    by_id = dict((r['id'], r) for r in all_rows)
    print('\n# --- ★ 搬运人工改动 (--carry-edited) ---')
    carried, old_zh, per_file, conflicts = {}, {}, [], []
    for path in paths:
        c, z, fmt = read_carried_edits(path)
        _base, kind = T.split_table_name(path)
        rel = os.path.relpath(path, T.REPO).replace('\\', '/')
        per_file.append(dict(csv=os.path.abspath(path), kind=kind or '',
                             csv_format=fmt, edited_rows=len(c)))
        print('# 旧表  : %-52s (%s; 格式 %s; 改过 %d 行)'
              % (rel if not rel.startswith('..') else path, kind or '合并大表',
                 fmt or '未知/无 meta', len(c)))
        for rid, te in c.items():
            if rid in carried and carried[rid] != te:
                conflicts.append(dict(id=rid, old_a=carried[rid], old_b=te,
                                      path_a=os.path.abspath(path)))
                continue                       # 两份旧表互相矛盾 ⇒ 保留第一份 + 告警
            carried[rid] = te
            old_zh.setdefault(rid, z.get(rid, ''))
    for n in notes:
        if n['code'] in ('merged-table', 'dir-extra'):
            print('# [提示] %s' % n['msg'])
    if conflicts:
        print('# [!!] 两份旧表里同一个 id 的 text_edited **不一致** %d 处 '
              '(已按"先给的那份"为准, 请人工确认): %s'
              % (len(conflicts), ' '.join(c['id'] for c in conflicts[:8])))
    if not carried:
        print('# 旧表里**没有**「改过」的行 (text_edited == text_zh 或为空) —— 没有可搬运的改动')
        return dict(meta=dict(csvs=[f['csv'] for f in per_file], sources=per_file,
                              csv_format=(per_file[0]['csv_format'] if per_file else None),
                              edited_rows=0, carried=[], missing=[], conflicts=[]),
                    carried=[])
    used, missing, n_marks = [], [], 0
    for rid in sorted(carried):
        r = by_id.get(rid)
        te = carried[rid]
        if r is None:
            missing.append(rid)
            continue
        n = T.count_wrap_marks(te)
        n_marks += n
        r['text_edited'] = te
        pos = T.wrap_break_positions(te)          # 每个断点**前面**的字符数 (第 p 个字符之后)
        r['note'] += ('; ★text_edited 是从旧表**搬运**过来的人工改动 (%d 个断点标记 %s%s '
                      '⇒ 注入时变成 %d 个真换行 {br})'
                      % (n, T.WRAP_MARK, ('; 断点位置: 第 %s 个字符之后'
                                          % ','.join(str(p) for p in pos[:12])) if n else '',
                         n)) if n else '; ★text_edited 是从旧表**搬运**过来的人工改动'
        used.append(dict(id=rid, resource=r['resource'], kind=r['kind'],
                         mark=n, cell_chars=len(te),
                         old_cell_chars=len(old_zh.get(rid, '')),
                         break_positions=pos,
                         disk_len_now=int(r['len_bytes'])))
        print('#   %-16s %-6s %-12s 断点标记 %s ×%d%s (编辑格 %d 字符, 盘上现值 %s B)'
              % (rid, r['resource'], r['kind'], T.WRAP_MARK, n,
                 ('; 断点位置: 第 %s 个字符之后' % ','.join(str(p) for p in pos[:12]))
                 if n else '',
                 len(te), r['len_bytes']))
    print('# 已搬运 %d 条 (断点标记合计 %d 个); 旧表里有、新 dump 里没有的 id %d 条%s'
          % (len(used), n_marks, len(missing),
             (' (%s)' % ' '.join(missing[:8])) if missing else ''))
    print('# ★ 搬运只改 text_edited 一列; 其它列全部以本次 dump 为准')
    return dict(meta=dict(csvs=[f['csv'] for f in per_file], sources=per_file,
                          csv_format=(per_file[0]['csv_format'] if per_file else None),
                          edited_rows=len(carried), carried=used, missing=missing,
                          conflicts=[dict(id=c['id']) for c in conflicts],
                          wrap_marks_carried=n_marks,
                          policy=('旧表里 text_edited != text_zh 的行原样搬到新表; '
                                  '新表里这些行会被注入器视为"人工改过"')),
                carried=used)


def warn_about_existing_edits(paths):
    """目标表已存在且里面有**人工改过**的行, 但这次没给 --carry-edited ⇒ 显著提醒。"""
    hits = []
    for p in paths:
        if not os.path.isfile(p):
            continue
        try:
            carried, _old, fmt = read_carried_edits(p)
        except Exception:                                              # noqa: BLE001
            continue
        if carried:
            hits.append((p, carried, fmt))
    if not hits:
        return
    n_all = sum(len(h[1]) for h in hits)
    print('\n[!! 注意] 目标表**已经存在**, 而且里面有 %d 行「人工改过的 text_edited」:' % n_all)
    for (p, carried, fmt) in hits:
        print('    %s (格式 %s, 改过 %d 行)'
              % (os.path.relpath(p, T.REPO).replace('\\', '/'), fmt or '未知', len(carried)))
        for rid in sorted(carried)[:6]:
            print('       %s (断点标记 %d 个)' % (rid, T.count_wrap_marks(carried[rid])))
        if len(carried) > 6:
            print('       …(还有 %d 行)' % (len(carried) - 6))
    print('   你这次**没有**给 --carry-edited ⇒ 这些改动不会被搬进新表 (新表按盘上字节重建)。')
    print('   想把它们留住: 重新跑一次并加 --carry-edited <那份旧表所在目录或文件>')
    print('   (旧表格式 = %s; 若它是 round35 及更早的 text-csv/1 或 /2, 里面的 %s 是'
          % (hits[0][2] or '未知', T.WRAP_MARK))
    print('    "引擎自动折行"的旧提示而不是人工断点 —— 别拿它直接注入, 见 FORMAT.md §3.6)')


# ─────────────────────── 资源: LANG 语言表 ───────────────────────

def dump_lang(iso, res, cs, wrap, long_min, rt_bad=None):
    rows, stats = [], dict(entries=0, long=0, short=0, locked=0, bytes=0,
                           cp_mismatch=0, ctrl=0, ctrl_marks=0, hints=0)
    c0 = res['copies'][0]
    ents, used = T.parse_lang(c0['blob'])
    free = free_capacity(res, c0['blob'], used, cs)
    # 两份拷贝一致性
    if len(res['copies']) > 1:
        for c in res['copies'][1:]:
            e2, u2 = T.parse_lang(c['blob'])
            if len(e2) != len(ents) or any(a.data != b.data for a, b in zip(ents, e2)):
                stats['cp_mismatch'] = 1
    wrap_w = wrap['LANG']['wrap_w']
    src = wrap['LANG']
    for e in ents:
        if e.length == 0:
            continue
        stats['entries'] += 1
        stats['bytes'] += e.length
        text, mp = cs.decode(e.data)
        try:
            rt_ok = cs.encode_strict(text) == e.data
        except T.CharsetError:
            rt_ok = False
        # 按键图标占位: 数「解出来正文里的私有区字符」, 并把它们列成标记写进 note
        marks = sorted({T.BTN_FMT % ord(c) for c in text if 0xE000 <= ord(c) <= 0xE0FF})
        n_ctrl = sum(1 for c in text if 0xE000 <= ord(c) <= 0xE0FF)
        if n_ctrl:
            stats['ctrl'] += 1
            stats['ctrl_marks'] += n_ctrl
        long_txt = e.length >= long_min
        hint = preview = nlines = ''
        n_hint = 0
        if not rt_ok:
            kind, w = 'locked', 0
            note = '字节回环不稳定: 本工具不改动 (原因见 dump 控制台)'
            stats['locked'] += 1
            # ★ locked 条目不做 {br}/{p} 转换, 但**必须**转标记: 否则 PUA 会漏进 CSV
            cell = edited = T.pua_to_marks(text)
            n_hard = len(T.TAG_RE.findall(text))
        elif long_txt:
            stats['long'] += 1
            n_hard = len(T.TAG_RE.findall(text))
            cell = edited = T.text_to_cell(text)          # ★ round36: 正文列**不含**任何标记
            if wrap_w:
                kind, w = 'long', wrap_w
                # ★ round39: 同样改名, 免得覆盖上面的按键标记清单 marks (见 dump_sfxml 里的说明)
                _c, _wrap_marks, preview = T.wrap_hint_cell(text, wrap_w)
                hint = ','.join(str(p) for p in _wrap_marks)
                n_hint = len(_wrap_marks)
                nlines = T.wrap_line_count(text, wrap_w)
                note = ('长段; 引擎自动折行点 %d 处 (只读提示, 见 wrap_hint / wrap_preview 列; '
                        '**不会**写进盘) + 显式换行 ×%d; ★ 想**固定**断行: 在 text_edited 里'
                        '想断的地方写 %s (也接受 {Warp}, 大小写不限) —— 注入时变成真换行 '
                        '{br}' % (n_hint, n_hard, T.WRAP_MARK))
            else:
                kind, w = 'long_nowrap', 0
                note = ('长段; 未标定折行宽度 ⇒ 不显示引擎自动折行点 (wrap_hint 留空); '
                        '显式换行 ×%d; ★ 想**固定**断行: 在 text_edited 里写 %s'
                        % (n_hard, T.WRAP_MARK))
            stats['hints'] += n_hint
        else:
            stats['short'] += 1
            cell = edited = T.text_to_cell(text)
            kind, w = 'short', 0
            note = '短文本; 不插换行' + ('; 含显式标记' if T.TAG_RE.search(text) else '')
        rid = 'LANG:G%03d.I%03d' % (e.g + 1, e.i)
        if rt_ok and rt_bad is not None:                 # ★ 往返自检 (locked 除外)
            why = lossless_reason(rid, text, cell, e.data, cs, w)
            if why:
                rt_bad.append((rid, kind, why))
        if n_ctrl:
            note += ('; ★含手柄按键图标 ×%d: 请原样保留 %s 不要删改 '
                     '(这些标记 = 游戏里直接画出来的按键图标/特殊符号, 不吃字库; '
                     '删掉或写错都会被注入器拒绝, 详见 FORMAT.md §4)'
                     % (n_ctrl, ' '.join(marks)))
        rows.append(dict(
            id=rid,
            resource='LANG', container=c0['tag'] + ('+GR.IMG#%d' % T.LANG_GR_IDX
                                                    if len(res['copies']) > 1 else ''),
            entry_index='G%03d.I%03d' % (e.g + 1, e.i),
            offset=e.data_off, len_bytes=e.length, max_bytes=e.length + free,
            kind=kind, wrap_w=w, lines=nlines,
            wrap_hint=hint, wrap_preview=preview,
            text_zh=cell, text_edited=edited, note=note))
    stats['free'] = free
    stats['used_end'] = used
    stats['blob_len'] = len(c0['blob'])
    return rows, stats


# ─────────────────────── 资源: SFXML ───────────────────────

def dump_sfxml(iso, res, cs, wrap, long_min, rt_bad=None):
    rows, stats = [], dict(entries=0, long=0, short=0, locked=0, bytes=0,
                           ctrl=0, ctrl_marks=0, hints=0)
    c0 = res['copies'][0]
    xml = c0['blob']
    tail_start = T.xml_tail_start(xml)
    free = free_capacity(res, xml, tail_start, cs)
    wrap_w = wrap['SFXML']['wrap_w']
    src = wrap['SFXML']
    for (k, off, ln, body) in T.parse_sfxml(xml):
        stats['entries'] += 1
        stats['bytes'] += ln
        text, mp = cs.decode(body)
        try:
            rt_ok = cs.encode_strict(text) == body
        except T.CharsetError:
            rt_ok = False
        long_txt = ln >= long_min or bool(T.CJK_RE.search(text))
        marks = sorted({T.BTN_FMT % ord(c) for c in text if 0xE000 <= ord(c) <= 0xE0FF})
        n_ctrl = sum(1 for c in text if 0xE000 <= ord(c) <= 0xE0FF)
        if n_ctrl:
            stats['ctrl'] += 1
            stats['ctrl_marks'] += n_ctrl
        hint = preview = nlines = ''
        n_hint = 0
        if not rt_ok:
            kind, w = 'locked', 0
            note = '字节回环不稳定: 本工具不改动'
            stats['locked'] += 1
            cell = edited = T.pua_to_marks(text)            # 同上: 不许漏 PUA
            n_hard = len(T.TAG_RE.findall(text))
        elif long_txt and wrap_w:
            stats['long'] += 1
            n_hard = len(T.TAG_RE.findall(text))
            cell = edited = T.text_to_cell(text)            # ★ round36: 正文列**不含**任何标记
            kind, w = 'long', wrap_w
            # ★ round39 修 bug: 这里原来写的是 `_c, marks, preview = T.wrap_hint_cell(...)`,
            #   把上面算好的**按键标记清单 marks 覆盖成"折行点位置(int)列表"** ⇒
            #   当这一条既含手柄按键图标、又是长段 (wrap_w>0) 时, 下面 `' '.join(marks)`
            #   会抛 TypeError: sequence item 0: expected str instance, int found
            #   (实测触发条目: SFXML:T0023 MP5SD 等)。
            #   改名成 _wrap_marks, 两个变量互不干扰。
            _c, _wrap_marks, preview = T.wrap_hint_cell(text, wrap_w)
            hint = ','.join(str(p) for p in _wrap_marks)
            n_hint = len(_wrap_marks)
            nlines = T.wrap_line_count(text, wrap_w)
            note = ('长段; 引擎自动折行点 %d 处 (只读提示, 见 wrap_hint / wrap_preview 列, '
                    'wrapW=%d %s; **不会**写进盘) + 显式换行 ×%d; '
                    '★ 想**固定**断行: 在 text_edited 里想断的地方写 %s (也接受 {Warp}, '
                    '大小写不限) —— 注入时变成真换行 {br}'
                    % (n_hint, wrap_w, src['source'], n_hard, T.WRAP_MARK))
            stats['hints'] += n_hint
        elif long_txt:
            stats['long'] += 1
            n_hard = len(T.TAG_RE.findall(text))
            cell = edited = T.text_to_cell(text)
            kind, w = 'long_nowrap', 0
            note = ('长段; 未标定折行宽度 ⇒ 不显示引擎自动折行点 (wrap_hint 留空); '
                    '显式换行 ×%d; ★ 想**固定**断行: 在 text_edited 里写 %s'
                    % (n_hard, T.WRAP_MARK))
        else:
            stats['short'] += 1
            cell = edited = T.text_to_cell(text)
            kind, w = 'short', 0
            note = '短文本; 不插换行' + ('; 含显式标记' if T.TAG_RE.search(text) else '')
        rid = 'SFXML:T%04d' % k
        if rt_ok and rt_bad is not None:                    # ★ 往返自检 (locked 除外)
            why = lossless_reason(rid, text, cell, body, cs, w)
            if why:
                rt_bad.append((rid, kind, why))
        if n_ctrl:
            note += ('; ★含手柄按键图标 ×%d: 请原样保留 %s 不要删改 '
                     '(这些标记 = 游戏里直接画出来的按键图标/特殊符号, 不吃字库; '
                     '删掉或写错都会被注入器拒绝, 详见 FORMAT.md §4)'
                     % (n_ctrl, ' '.join(marks)))
        rows.append(dict(
            id=rid,
            resource='SFXML', container=c0['tag'], entry_index='T%04d' % k,
            offset=off, len_bytes=ln, max_bytes=ln + free,
            kind=kind, wrap_w=w, lines=nlines,
            wrap_hint=hint, wrap_preview=preview,
            text_zh=cell, text_edited=edited, note=note))
    stats['free'] = free
    stats['used_end'] = tail_start
    stats['blob_len'] = len(xml)
    return rows, stats


DUMPERS = dict(LANG=dump_lang, SFXML=dump_sfxml)


# ───────────────────────────── main ─────────────────────────────

def main():
    ap = argparse.ArgumentParser(description='dump 盘内文本到**按 kind 分类的多张 CSV**')
    ap.add_argument('--iso', required=True)
    ap.add_argument('--out', default=None, metavar='基准路径',
                    help='输出**基准路径**: 实际写出 <基准>_<kind>.csv 多张表 + <基准>.txt '
                         '(合并快照) + <基准>.meta.json。例: '
                         '--out work/builds/GR_ZH92/text/GR_ZH92_text.csv ⇒ '
                         'GR_ZH92_text_long.csv / _long_nowrap.csv / _short.csv … '
                         '(缺省 = 与 --iso 同目录同名 .text.csv)')
    ap.add_argument('--only-kind', default='', metavar='KINDS',
                    help='★ 只产出这几张表 (逗号分隔, 如 long,short); 缺省 = 全部 kind。'
                         '被点名但 0 条的 kind 也会产出只有表头的空表')
    ap.add_argument('--resources', default='LANG,SFXML',
                    help='要 dump 的资源, 逗号分隔 (LANG / SFXML)')
    ap.add_argument('--wrapw', default='', help='覆盖折行宽度, 形如 LANG=270,SFXML=270')
    ap.add_argument('--long-min', type=int, default=LONG_MIN, help='长段字节阈值 (默认 40)')
    ap.add_argument('--stats', action='store_true', help='只打印统计, 不写 CSV')
    ap.add_argument('--en-iso', default=None,
                    help='英文基线盘 ISO (只读) —— 用于生成只读参考列 text_en; '
                         '缺省 = 自动用 work/builds/GR_EN_ORIG/GR_EN_ORIG.iso (存在时)')
    ap.add_argument('--no-en', action='store_true',
                    help='不读英文盘; text_en 整列留空并在 note 里说明')
    ap.add_argument('--allow-roundtrip-diff', action='store_true',
                    help='★ 工程侧专用: 往返自检不通过时也写出 CSV (这些行不可安全编辑)')
    ap.add_argument('--carry-edited', action='append', default=[], metavar='旧表/旧目录',
                    help='★ 把旧表里**人工改过的 text_edited** 原样搬到新表 (只搬 '
                         'text_edited != text_zh 的行; 重新 dump 不会丢用户的改动)。'
                         '可给多次; 也可以给**目录** (自动读该目录下所有 *_text_*.csv)')
    a = ap.parse_args()

    names = [x.strip().upper() for x in a.resources.split(',') if x.strip()]
    for n in names:
        assert n in T.RES, '未知资源 %s (可用: %s)' % (n, '/'.join(T.RES))
    wrap = T.load_wrap_profiles()
    for kv in a.wrapw.split(','):
        if not kv.strip():
            continue
        k, v = kv.split('=')
        wrap[k.strip().upper()] = dict(wrap.get(k.strip().upper(), {}),
                                       wrap_w=int(v), source='forced(--wrapw)')

    iso_sha = T.sha256_file(a.iso)
    iso = T.Iso(a.iso)
    cs = T.Charset()
    res = load_resources(iso, names)

    print('# dump_text_csv.py — %s' % FMT_VERSION)
    print('# ISO     : %s' % iso.path)
    print('# sha256  : %s' % iso_sha)
    print('# charset : %s (%d 单字节码 + %d 双字节码)'
          % (os.path.relpath(T.CHARSET, T.REPO), len(cs.enc_single), len(cs.enc_pair)))

    # ── 解码口径自检 (单字节码优先; 见 tcslib.selfcheck_*) ──
    print('# --- 解码口径自检 (单字节码优先: 0xAF=的, 0xB0=你) ---')
    ok1, det1 = T.selfcheck_charset(cs)
    for ln in det1:
        print('# %s' % ln)
    ok2, det2 = T.selfcheck_anchors(
        cs,
        blob_lang=res['LANG']['copies'][0]['blob'] if 'LANG' in res else None,
        blob_xml=res['SFXML']['copies'][0]['blob'] if 'SFXML' in res else None)
    # 会随翻译更新的「文案锚点」: 期望值过时属正常 (例: G058.I195 命令→顺序, round29 已改),
    # 只降级为告警; 字节级锚点 (0xAF=的 / 0xB0=你 / AF A1 BD→的方) 仍然致命。
    MUTABLE_TEXT_ANCHORS = ('G058.I195',)
    fatal2 = [ln for ln in det2
              if ln.startswith('[!!]') and not any(a in ln for a in MUTABLE_TEXT_ANCHORS)]
    if not ok2 and not fatal2:
        ok2 = True
        det2 = det2 + ['[ok] 上述文案锚点差异属「翻译已更新」(见 MUTABLE_TEXT_ANCHORS), 已降级为告警; '
                       '字节级锚点全部通过']
    for ln in det2:
        print('# %s' % ln)
    assert ok1 and ok2, '解码口径自检失败 —— 拒绝 dump (见上面 [!!] 行)'

    # ── ★ round36: 换行/人工断点 进-出互逆自检 ──
    print('# --- 换行/断点口径自检 ({br} ↔ 1 换行, {p} ↔ 空行, %s/{Warp} 人工断点 ↔ 真换行) ---'
          % T.WRAP_MARK)
    ok3, det3 = T.selfcheck_newlines(cs)
    for ln in det3:
        print('# %s' % ln)
    assert ok3, '换行/断点口径自检失败 —— 拒绝 dump (见上面 [!!] 行)'

    # ── ★ 只读参考列 text_en 的数据源: 英文基线盘 (round34) ──
    en_enabled, en_reason, en_path = False, '', None
    if a.no_en:
        en_reason = '命令行给了 --no-en'
    elif a.en_iso:
        en_path = os.path.abspath(a.en_iso)
        if os.path.isfile(en_path):
            en_enabled = True
        else:
            en_reason = '--en-iso 指定的文件不存在 (%s)' % a.en_iso
    elif os.path.isfile(T.EN_ISO_DEFAULT):
        en_path = T.EN_ISO_DEFAULT
        en_enabled = True
    else:
        en_reason = ('英文基线盘不存在 (%s), 也没给 --en-iso'
                     % os.path.relpath(T.EN_ISO_DEFAULT, T.REPO).replace('\\', '/'))

    en_lang, en_xml, en_info, en_sha = {}, {}, None, None
    print('\n# --- text_en (只读参考列: 英文原文) ---')
    if en_enabled:
        en_sha = T.sha256_file(en_path)
        en_iso = T.Iso(en_path)
        en_lang, en_xml, en_info = T.en_read_tables(en_iso)
        en_iso.close()
        en_info['iso_sha256'] = en_sha
        print('# 英文盘  : %s' % os.path.relpath(en_path, T.REPO).replace('\\', '/'))
        print('# sha256  : %s' % en_sha)
        print('# 来源拷贝: %s + %s   ← 与中文盘 dump 的**主拷贝**一致'
              % (T.RES['LANG']['copies'][0][3], T.RES['SFXML']['copies'][0][3]))
        print('# 对齐键  : LANG = id (G###.I###);  SFXML = 条目序 (T####) —— 左连接, '
              '对不上就留空并在 note 说明')
        print('# 英文盘 LANG : 共 %d 条, 有正文 %d 条; SFXML: 共 %d 条, 有正文 %d 条 '
              '(存在但正文为空 %d 条)'
              % (en_info['lang']['entries'], en_info['lang']['nonempty'],
                 en_info['sfxml']['entries'], en_info['sfxml']['nonempty'],
                 len(en_info['sfxml']['empty_ids'])))
        print('# 英文盘原始非 ASCII 字节:')
        print('#   LANG : %s' % (T.fmt_en_hist(en_info['lang']['bytes_hist'],
                                               en_info['lang']['mapped']) or '(无)'))
        print('#   SFXML: %s' % (T.fmt_en_hist(en_info['sfxml']['bytes_hist'],
                                               en_info['sfxml']['mapped']) or '(无)'))
        print('#   0xB1/0xB5 = 手柄按键图标占位 (英文原文自己写着 "press the [...] button") ⇒ '
              '写成 {{BTN:E0B1}}/{{BTN:E0B5}}, 与 text_zh 同一套写法')
        if en_info['copies_differ']:
            print('# 注: 英文盘两份 LANG 拷贝有 %d 条正文不同 (%s%s); text_en 取**第一份** '
                  '—— 实测中文译文就是从第一份翻的 (证据见 docs/REPORT_en_column.md)'
                  % (len(en_info['copies_differ']), ' '.join(en_info['copies_differ'][:6]),
                     ' …' if len(en_info['copies_differ']) > 6 else ''))
        print('# ★ text_en 只读: 注入器**完全忽略**这一列, 里面写什么都不会进游戏')
    else:
        print('# [跳过] text_en 整列留空 —— %s' % en_reason)
        print('#   怎么办: 放一份英文基线盘到 work/builds/GR_EN_ORIG/GR_EN_ORIG.iso, '
              '或用 --en-iso <路径> 指定')

    all_rows, meta = [], dict(
        format=FMT_VERSION, iso=iso.path, iso_sha256=iso_sha,
        charset=os.path.relpath(T.CHARSET, T.REPO),
        long_min=a.long_min,
        generated=datetime.datetime.now().isoformat(timespec='seconds'),
        wrap_profiles={k: wrap[k] for k in names},
        en=None,
        resources={})
    rt_bad = []                       # ★ round35 往返自检的不通过清单 [(id, kind, 原因)]

    for n in names:
        rows, stats = DUMPERS[n](iso, res[n], cs, wrap, a.long_min, rt_bad)
        all_rows += rows
        meta['resources'][n] = dict(
            stats, container=T.RES[n]['copies'][0][3] + (
                '+%s#%d' % (T.RES[n]['copies'][1][0], T.RES[n]['copies'][1][2])
                if len(T.RES[n]['copies']) > 1 else ''))
        c0 = res[n]['copies'][0]
        print('\n== %s (%s) ==' % (n, meta['resources'][n]['container']))
        print('  子流解压 %d B, 已用 %d B, 尾部可吸收 %d B, 压缩帧 %d / 槽 %d (余 %d)'
              % (len(c0['blob']), stats['used_end'], len(c0['blob']) - stats['used_end'],
                 c0['frame_len'], c0['entry']['stored'],
                 c0['entry']['stored'] - c0['frame_len']))
        print('  条目 %d (长段 %d / 短 %d / 锁定 %d), 正文合计 %d B'
              % (stats['entries'], stats['long'], stats['short'], stats['locked'],
                 stats['bytes']))
        print('  单条扩容预算 max_bytes = len + %d B (仅当其它条不变时)'
              % stats['free'])
        if stats.get('cp_mismatch'):
            print('  !! 两份拷贝 payload 不一致 —— 请人工确认')
        if stats['ctrl']:
            print('  %d 条含手柄按键图标 (共 %d 个占位; CSV 里写成 %s 这类 ASCII 标记, '
                  'Excel 可直接显示/编辑)'
                  % (stats['ctrl'], stats['ctrl_marks'],
                     '{{BTN:E0B1}}' if not a.stats else '{{BTN:XXXX}}'))
        if stats.get('hints'):
            print('  %d 个「引擎自动折行点」提示 (wrapW>0 的长段; 只写进**只读列** '
                  'wrap_hint / wrap_preview, **不写进盘**)'
                  % stats['hints'])
        locked = [r for r in rows if r['kind'] == 'locked']
        for r in locked[:10]:
            print('  [locked] %s len=%d' % (r['id'], r['len_bytes']))
            t = r['text_zh']
            try:
                cs.encode_strict(t)
            except T.CharsetError as ex:
                print('           %s' % ex)
        if a.stats:
            continue

    if a.stats:
        iso.close()
        return

    # ── ★ 给每行补上只读参考列 text_en (左连接; 绝不参与注入) ──
    en_stats = attach_text_en(all_rows, en_lang, en_xml, en_info, en_enabled, en_reason)
    print('\n# --- text_en 对齐结果 (只读参考列) ---')
    for res_name in sorted(en_stats['by_res']):
        d = en_stats['by_res'][res_name]
        tot = sum(1 for r in all_rows if r['resource'] == res_name)
        print('# %-6s %d 行: 有英文原文 %d; 英文本身为空 %d; 对不上 %d'
              % (res_name, tot, d['nonempty'], d['blank'], d['unaligned']))
    print('# 合计  %d 行: text_en 非空 %d (%.2f%%); 英文本身为空 %d; 对不上 %d'
          % (en_stats['total'], en_stats['nonempty'],
             100.0 * en_stats['nonempty'] / max(1, en_stats['total']),
             en_stats['blank'], len(en_stats['unaligned'])))
    if en_stats['unaligned']:
        print('# 对不上的条目 (前 20): %s' % ' '.join(en_stats['unaligned'][:20]))
    if en_stats['byte_rows']:
        print('# 其中 %d 行的 text_en 里含英文盘原始非 ASCII 字节 '
              '(已转成可见字符, 并在该行 note 里注明) ✓' % en_stats['byte_rows'])
    if en_enabled:
        meta['en'] = dict(
            iso=os.path.relpath(en_path, T.REPO).replace('\\', '/'),
            iso_sha256=en_sha,
            source=dict(lang=T.RES['LANG']['copies'][0][3],
                        sfxml=T.RES['SFXML']['copies'][0][3],
                        note='只读第一份拷贝 (与中文盘 dump 的主拷贝一致)'),
            align_key=dict(LANG='id (G###.I###)', SFXML='条目序 (T####)'),
            policy='text_en 只读参考: 注入器完全忽略这一列, 改了不会进游戏',
            lang=dict(entries=en_info['lang']['entries'],
                      nonempty=en_info['lang']['nonempty'],
                      empty=len(en_info['lang']['empty_ids']),
                      bytes=en_info['lang']['bytes'],
                      bytes_hist=hexkey(en_info['lang']['bytes_hist'])),
            sfxml=dict(entries=en_info['sfxml']['entries'],
                       nonempty=en_info['sfxml']['nonempty'],
                       empty=len(en_info['sfxml']['empty_ids']),
                       empty_ids=en_info['sfxml']['empty_ids'],
                       bytes=en_info['sfxml']['bytes'],
                       bytes_hist=hexkey(en_info['sfxml']['bytes_hist'])),
            byte_map=dict(('0x%02X' % b, (T.BTN_FMT % (0xE000 + b))
                           if b in T.EN_ICON_BYTES else T.EN_CP1252[b])
                          for b in sorted(set(list(T.EN_CP1252) + list(T.EN_ICON_BYTES)))),
            byte_map_note='0xB1/0xB5 = 手柄按键图标占位(引擎直接画图标); 其余 = Windows-1252 可见字符',
            copies_differ=en_info['copies_differ'],
            aligned=dict(nonempty=en_stats['nonempty'], blank=en_stats['blank'],
                         unaligned=len(en_stats['unaligned']),
                         unaligned_ids=en_stats['unaligned'][:50],
                         rows_with_raw_bytes=en_stats['byte_rows']))
    else:
        meta['en'] = dict(skipped=True, reason=en_reason)

    out = a.out or os.path.splitext(a.iso)[0] + '.text.csv'
    base = T.csv_stem(out)                      # …/GR_ZH92_text
    out = base + '.csv'                         # 老的大表口径 (只用于"残留检测")
    os.makedirs(os.path.dirname(os.path.abspath(base)) or '.', exist_ok=True)
    want_kinds = [x.strip() for x in a.only_kind.split(',') if x.strip()]

    # ── ★ round37: 算出这次要产出哪几张表 (每个 kind 一张) ──
    kinds_present = T.kind_order(set(r['kind'] for r in all_rows))
    if want_kinds:
        kinds = T.kind_order(want_kinds)
        unknown = [k for k in want_kinds if k not in kinds_present]
    else:
        kinds = T.kind_order(set(kinds_present) | set(T.ALWAYS_KINDS))
        unknown = []
    table_paths = [T.table_path_for(base, k) for k in kinds]
    meta_path = base + '.meta.json'
    txt_path = base + '.txt'

    # ── ★ round36/37: 搬运旧表里的人工改动, 并在"目标表已存在且有人工改动"时显著提醒 ──
    carry = apply_carry_edited(all_rows, a.carry_edited) if a.carry_edited else None
    if carry is None:
        warn_about_existing_edits(table_paths + ([out] if os.path.isfile(out) else []))
    if carry:
        meta['carry'] = carry['meta']

    # ── ★ round37: 老格式的合并大表若还留在同一目录里 ⇒ 明确提示 (不再更新它) ──
    stale = out if os.path.isfile(out) else None
    if stale:
        print('\n[!! 提示] 这个目录里还留着一张**老格式的合并大表**:')
        print('   %s' % os.path.relpath(stale, T.REPO).replace('\\', '/'))
        print('   本轮起 dump **不再更新它**, 而是产出按 kind 拆开的多张表:')
        for k, p in zip(kinds, table_paths):
            print('     %-14s %s' % (k, os.path.relpath(p, T.REPO).replace('\\', '/')))
        print('   ★ 那张老的大表已经是**过期快照** ⇒ 请删掉它 (或在 Excel 里关掉后删除),')
        print('     以免看着像"最新的表"。注入时请直接把**目录**给 --csv (会自动读全部多表)。')

    # ── ★ round36 往返自检: text_zh 必须能逐字节还原盘上原字节 ──
    n_rt = sum(1 for r in all_rows if r['kind'] != 'locked')
    n_hint = sum(len([x for x in (r['wrap_hint'] or '').split(',') if x]) for r in all_rows)
    n_mark_zh = sum(T.count_wrap_marks(r['text_zh']) for r in all_rows)
    n_carried = sum(T.count_wrap_marks(r['text_edited']) for r in all_rows)
    print('\n[check] 往返自检 (CSV 单元格 → 盘上字节, 用**注入器的解析口径**):')
    print('        检查 %d 行 (kind=locked 除外); 正文列里的断点标记 %d 个 (dump **不写**标记); '
          '引擎折行提示(只读列) %d 个; 搬运来的人工断点 %d 个'
          % (n_rt, n_mark_zh, n_hint, n_carried))
    if rt_bad:
        print('  [!!] %d 行**无法逐字节还原** —— 这些行一旦被编辑注入, 盘上结构就会变:'
              % len(rt_bad))
        for (rid, kind, why) in rt_bad[:10]:
            print('    ── %s (%s)\n       %s' % (rid, kind, why))
        if len(rt_bad) > 10:
            print('    …(还有 %d 行)' % (len(rt_bad) - 10))
        print('  ★ 为什么必须拦住: 单元格能显示、但回写不出原字节 ⇒ 这份 CSV 的"视图"'
              '与盘上存储**不是一一对应**, 人工改一个字就可能顺带改掉结构\n'
              '    (典型: 盘上出现连续标记 {br}{br}/{p}{p}, 而 "1 换行={br} / 空行={p}" '
              '无法表达它)。\n'
              '    怎么办: 报给工程侧 (需要给这种条目一个无损写法); 确要强行导出加 '
              '--allow-roundtrip-diff。')
        if not a.allow_roundtrip_diff:
            raise SystemExit('!! 往返自检不通过 (%d 行) —— 拒绝写出文本表' % len(rt_bad))
        print('  [!! 警告] --allow-roundtrip-diff 已指定: 仍然写出文本表 (这些行**不可安全编辑**)')
    else:
        print('  [ok] 全部 %d 行逐字节往返一致 ✓ —— 「人工在 CSV 里敲 1 个回车 ⇒ 盘上'
              '恰好 1 个 {br}」「敲 1 个空行 ⇒ 恰好 1 个 {p}」「写一个 %s ⇒ 恰好 1 个 {br}」'
              '对每一行都成立' % (n_rt, T.WRAP_MARK))
    meta['roundtrip'] = dict(checked=n_rt, failed=len(rt_bad),
                             wrap_mark=T.WRAP_MARK,
                             wrap_marks_in_text_columns=n_mark_zh,
                             wrap_hints_total=n_hint,
                             wrap_marks_carried=n_carried,
                             failures=[dict(id=a1, kind=b1, reason=c1)
                                       for (a1, b1, c1) in rt_bad[:50]],
                             policy=('text_zh 用注入器口径 (cell_to_bytes_text) 必须逐字节'
                                     '还原盘上原字节; kind=locked 除外。'
                                     'dump 端**绝不**自动插 %s (引擎折行点只进只读列 '
                                     'wrap_hint/wrap_preview)' % T.WRAP_MARK))
    # ★ 写盘前硬门槛: 所有文本列里不许有任何 Excel 显示不出来的字符
    n_scanned, _ = assert_cells_clean(all_rows)
    print('\n[check] 已扫描 %d 行 × %d 个文本列的 %d 个字符: '
          'PUA 私有区 0 个 / 不可见控制字符 0 个 ✓'
          % (len(all_rows), len(CELL_COLS), n_scanned))

    # ── ★ round37: 按 kind 写出多张表 (每张表头/列完全不变; 0 条的 kind 也写空表) ──
    sub = dict((k, [r for r in all_rows if r['kind'] == k]) for k in kinds)
    tables = []
    print('\n[out] 按 kind 分类写出 %d 张表 (列/表头与原大表完全相同, 只是行分开了):' % len(kinds))
    for k in kinds:
        p = T.table_path_for(base, k)
        write_csv(p, sub[k])
        tables.append((p, sub[k]))
        print('   %-14s %5d 行  %8.1f KB  %s'
              % (k, len(sub[k]), os.path.getsize(p) / 1024,
                 os.path.relpath(p, T.REPO).replace('\\', '/')))
    n_written = sum(len(sub[k]) for k in kinds)
    dropped = len(all_rows) - n_written

    # ── ★ round37: TXT 快照仍然**合并成一份** (便于 git diff) ──
    #   ★ 行序 = **dump 的自然顺序** (LANG 全部 → SFXML 全部), 与"一张大表"时代完全一致
    #     ⇒ 从大表切到多表后, TXT 快照**逐字节不变** (git diff 里只看到 CSV 被拆开)。
    kinds_set = set(kinds)
    txt_rows = [r for r in all_rows if r['kind'] in kinds_set]
    n_txt, n_chars, n_cjk = T.write_txt_snapshot(
        txt_path, [(r['id'], T.row_for_txt(r)) for r in txt_rows])
    print('[out] 合并 TXT 快照 (一份, 便于 diff): %s (%d 行, %d 字符, 中文 %d)'
          % (os.path.relpath(txt_path, T.REPO).replace('\\', '/'), n_txt, n_chars, n_cjk))

    summary = T.table_set_summary(tables)
    used_kinds = T.kind_order(set(r['kind'] for r in all_rows))
    empty_tables = [f['name'] for f in summary['files'] if f['rows'] == 0]
    meta['tables'] = dict(
        base=os.path.relpath(base, T.REPO).replace('\\', '/'),
        glob=T.TABLE_GLOB,
        kinds=summary['kinds'], kinds_present=used_kinds, kinds_requested=want_kinds,
        unknown_kinds=unknown,
        tables=summary['tables'], rows_total=summary['rows_total'],
        rows_dumped=len(all_rows), rows_not_written=dropped,
        files=summary['files'],
        empty_tables=empty_tables,
        naming='<基准>_<kind>.csv —— 每张表 16 列, 表头与原大表完全相同',
        no_merged_csv=('不再产出合并的大 CSV (避免"改了一张、另一张没改"的歧义); '
                       'TXT 快照仍然合并成一份: %s' % os.path.basename(txt_path)),
        stale_merged_csv=(os.path.relpath(stale, T.REPO).replace('\\', '/') if stale else None),
        policy=('注入: --csv 可给多次, 也可给本目录 (自动读全部 *_text_*.csv); '
                '多表按 id 合并, 同一个 id 的 text_edited 不一致会报错'))
    meta['txt'] = dict(path=os.path.relpath(txt_path, T.REPO).replace('\\', '/'),
                       rows=n_txt, bytes=os.path.getsize(txt_path),
                       sha256=T.sha256_file(txt_path),
                       chars=n_chars, cjk_chars=n_cjk,
                       scope='本次写出的多张表合并而成 (一份, 便于 git diff)',
                       format='每行 id<TAB>正文(单行); 换行=\\n 制表=\\t 反斜杠=\\\\')
    json.dump(meta, open(meta_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('[out] %s (每张表的条数/kind/总条数/sha256 都在这里)'
          % os.path.relpath(meta_path, T.REPO).replace('\\', '/'))

    if empty_tables:
        print('\n[注意] 下面这些表**本次 0 条** (照样产出了只有表头的空表, 不是漏了):')
        print('   %s' % ', '.join(empty_tables))
    if unknown:
        print('\n[注意] --only-kind 点名的 %s 在这次 dump 里**一条都没有** ⇒ 产出空表'
              % ','.join(unknown))
    if dropped:
        print('[注意] --only-kind 只写出 %d 行, 另外 %d 行 (其它 kind) **没有写进任何表**'
              % (n_written, dropped))
        print('       ⇒ 拿这份表注入只会改动这 %d 行, 其余条目一个字都不动' % n_written)

    print('\n下一步: 用 Excel 打开对应的表 —— 一张表只管一类文本:')
    print('        ★ %-34s 可写 %s 控制断点的**长段** (特别收录介绍等)'
          % (os.path.basename(T.table_path_for(base, 'long')), T.WRAP_MARK))
    print('          %-34s 语言表长段 (简报/说明; 折行宽度未标定, 没有 wrap_hint)'
          % os.path.basename(T.table_path_for(base, 'long_nowrap')))
    print('          %-34s 按钮 / 条目名 / 短提示 (别加换行)'
          % os.path.basename(T.table_path_for(base, 'short')))
    print('        只改 text_edited 一列; text_zh 右边那列 text_en 是英文原文(只读参考)。')
    print('        ★ 想**主动控制断点**: 在 text_edited 里想断行的地方写 %s (或 {Warp},'
          % T.WRAP_MARK)
    print('          大小写不限) ⇒ 注入时就在那里断行 (盘上多 1 个 {br})。')
    print('          标记**不能**写在文本最开头/最末尾, 也不能紧挨着另一个标记或换行')
    print('          (那些位置会写出连续换行); 想空一行请在 CSV 里敲**一个空行**。')
    print('        ★ 只读列 wrap_hint / wrap_preview 显示的是「引擎现在会自动折在哪」,')
    print('          只是提示, **不会**写进盘, 也不影响注入。')
    print('        ★ 注入时**把目录给它**最省事 (自动读全部多表, 不会漏):')
    print('          python tools/text_csv/inject_text_csv.py --csv %s \\'
          % os.path.relpath(os.path.dirname(base), T.REPO).replace('\\', '/'))
    print('                 --src %s --dst <新盘>'
          % os.path.relpath(a.iso, T.REPO).replace('\\', '/'))
    print('        (也可以 --csv 单个表文件, 给几次都行; 老的大表照样能用, 但会提示改用多表)')
    iso.close()


if __name__ == '__main__':
    main()
