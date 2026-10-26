#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""inject_text.py —— 把译文表变成「条目 payload blob」清单（不写 ISO）。

角色（见 Lead 2026-10-21 接口约定）：
    本模块只负责「原盘 + 译文表 → {条目号: 新 payload blob} + 校验报告」；
    真正的 ISO 重排/写盘由 tools/dlc/rebuild.py 做（它接受 blob_repl 并自己按
    16,384 B 分块打 LZO 帧、重算条目表/偏移）。

对外主接口：
    build_replacements(iso_path, translation_path, *, allow_marker_drift=False,
                       keep_tail=True) -> (blob_repl, report)

命令行：
    python tools\dlc\inject_text.py --translations work\translation\translated `
        --out-dir work\build\payloads --report work\analysis\text\inject_report.json
    python tools\dlc\inject_text.py --translations <csv/dir> --check-only

输入译文表格式（列名大小写不敏感，自动识别）：
    · resource,id,text_zh            ← Lead 约定 / translation_worklist.csv
    · resource,id,text_en,text_zh    ← 7 个批次 CSV
    · key,text_en,text_zh            ← assets/text/source/*.csv（id 列名为 key）
    id 允许带前缀（LANG: / SFXML: / MIS: / ATR: / TXT:）或裸 id。
    text_zh 里的真换行可写成字面转义 \r\n（本工程约定），也可直接是换行；
    写盘前统一转成引擎口径的 {p}/{br} 标记。

校验（全部写进 report，任何 error 都拒绝产出 payload）：
    ① 基盘一致性：被抽条目的 blob sha256 必须与 assets/text/source/text_source.json 一致；
    ② LANG 结构：组数/条目数/(g,i) 序列/每组 count 与原文完全一致；
    ③ 逐条编码：译文必须能被本体字符集编码（缺字逐字列出）；
    ④ 往返：encode→decode 必须等于译文（{{BTN:XXXX}} 归一化比较）；
    ⑤ 控制字符：编码后的正文不许出现 C0 控制字节（\\x00 \\x0b …）；
    ⑥ 0xFF 禁忌：SFXML/MIS/ATR/TXT 是 XML 词法器读的文本，禁止 0xFF（「著」）；
    ⑦ 富文本标记：{p}/{br}/{{BTN:…}} 计数必须与原条一致（--allow-marker-drift 降级为警告）；
    ⑧ 未知 id / 重复 id / 空译文：逐条报告。
"""
import argparse
import collections
import csv
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)

import dlclib                                                       # noqa: E402
import textlib as T                                                 # noqa: E402

P = T.P
SOURCE = T.SOURCE_DIR
WORK = T.WORK_TEXT
SCHEMA = 'grjs-text-inject/1'
CHUNK = 16384

BTN_RE = re.compile(r'\{\{BTN:([0-9A-Fa-f]{4})\}\}')
CTRL_BYTES = set(list(range(0x00, 0x09)) + [0x0B, 0x0C] + list(range(0x0E, 0x20)) + [0x7F])


# ═════════════════════════ 小工具 ═════════════════════════
def _norm_res(s):
    s = (s or '').strip().upper()
    alias = {'LANG': 'LANG', 'SFXML': 'SFXML', 'SFXML_TEXT': 'SFXML',
             'SFXML_TITLE': 'SFXML_TITLE', 'TITLE': 'SFXML_TITLE',
             'MIS': 'MIS', 'ATR': 'ATR', 'TXT': 'STRINGS_TXT',
             'STRINGS_TXT': 'STRINGS_TXT', 'EN_STRINGS_TXT': 'STRINGS_TXT'}
    return alias.get(s, s)


def canonicalize(resource, key):
    """(resource, key) → ((resource, canonical_id) 或 None, 原因)。"""
    res = _norm_res(resource)
    k = (key or '').strip()
    if not k:
        return None, '空 id'
    low = k
    if low.upper().startswith('LANG:'):
        res, k = 'LANG', low[5:]
    elif low.upper().startswith('SFXML:'):
        k = low[6:]
        res = 'SFXML_TITLE' if re.fullmatch(r'A\d{4}', k) else 'SFXML'
    elif low.upper().startswith('MIS:'):
        res, k = 'MIS', low[4:]
    elif low.upper().startswith('ATR:'):
        res, k = 'ATR', low[4:]
    elif low.upper().startswith('TXT:'):
        res, k = 'STRINGS_TXT', low[4:]
    elif low.upper().startswith('EN_STRINGS.TXT#'):
        res, k = 'STRINGS_TXT', low.split('#', 1)[1]
    if not res:
        if re.fullmatch(r'G\d+\.I\d+', k, re.I):
            res = 'LANG'
        elif re.fullmatch(r'T\d{4}', k):
            res = 'SFXML'
        elif re.fullmatch(r'A\d{4}', k):
            res = 'SFXML_TITLE'
        elif re.match(r'.+\.MIS#', k, re.I):
            res = 'MIS'
        elif re.match(r'.+\.ATR#', k, re.I):
            res = 'ATR'
        else:
            return None, '无法从 key 推断资源（请给 resource 列）'
    # 规范化
    if res == 'LANG':
        m = re.fullmatch(r'G(\d+)\.I(\d+)', k)
        if not m:
            return None, 'LANG id 应形如 G019.I002'
        return ('LANG', 'G%03d.I%03d' % (int(m.group(1)), int(m.group(2)))), None
    if res == 'SFXML':
        m = re.fullmatch(r'T(\d{4})', k)
        if not m:
            return None, 'SFXML id 应形如 T0010'
        return ('SFXML', 'T%04d' % int(m.group(1))), None
    if res == 'SFXML_TITLE':
        m = re.fullmatch(r'A(\d{4})', k)
        if not m:
            return None, 'SFXML_TITLE id 应形如 A0001'
        return ('SFXML_TITLE', 'A%04d' % int(m.group(1))), None
    if res == 'MIS':
        if '#' in k:
            fn, field = k.split('#', 1)
        elif ':' in k:
            fn, field = k.rsplit(':', 1)          # 兼容 worklist 的 MIS:FILE:Field
        else:
            return None, 'MIS id 应形如 C01_PLANTATION.MIS#Name'
        return ('MIS', '%s#%s' % (fn.strip().upper(), field.strip())), None
    if res == 'ATR':
        if '#' in k:
            fn = k.split('#', 1)[0]
        elif ':' in k:
            fn = k.rsplit(':', 1)[0]
        else:
            return None, 'ATR id 应形如 DEMOLITIONS-01.ATR#ActorName'
        return ('ATR', '%s#ActorName' % fn.strip().upper()), None
    if res == 'STRINGS_TXT':
        return ('STRINGS_TXT', 'TXT:%s' % k), None
    return None, '未知资源 %r' % resource


def marker_counts(s):
    return dict(p=s.count('{p}'), br=s.count('{br}'),
                btn=len(BTN_RE.findall(s)))


def bad_btn_marks(s):
    """找出写法不完整的 {{BTN… 标记。"""
    bad = []
    for m in re.finditer(r'\{\{BTN', s, re.I):
        if not BTN_RE.match(s, m.start()):
            bad.append(s[m.start():m.start() + 24])
    for m in re.finditer(r'(?<!\{)\{[^{}]*BTN', s, re.I):
        bad.append(m.group(0))
    return bad


def normalize_btn_markers_for_cmp(s):
    return BTN_RE.sub(lambda m: chr(0xE000 + int(m.group(1), 16)), s)


def has_bad_ctrl_text(s):
    return [hex(ord(ch)) for ch in s if ord(ch) < 0x20 and ch not in '\r\n\t']


# ═════════════════════════ 译文表读取 ═════════════════════════
def _collect_files(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for f in sorted(files):
                    if f.lower().endswith('.csv'):
                        out.append(os.path.join(root, f))
        elif os.path.isfile(p):
            out.append(p)
        else:
            raise SystemExit('找不到译文表: %s' % p)
    return out


def load_translations(paths, errors):
    """→ (trans, origin, stat)。

    trans  : {(resource, canon_id): dict(text, is_tm, file)}
    origin : {(resource, canon_id): 'tm' | 'new'}  ← 供 marker_drift 分级
    is_tm 判定：行里有 status=tm_* / tm_source 非空 / source=tm，或文件名含 worklist/tm。
    """
    files = _collect_files(paths)
    trans, first_src = {}, {}
    stat = dict(files=[os.path.basename(f) for f in files], rows=0, used=0,
                empty=0, unknown=[], duplicates=[], resources=collections.Counter(),
                tm_rows=0, new_rows=0)
    for fn in files:
        base = os.path.basename(fn).lower()
        file_is_tm = ('worklist' in base) or bool(re.search(r'(^|[_\-.])tm([_\-.]|$)', base))
        with open(fn, encoding='utf-8-sig', newline='') as f:
            rd = csv.DictReader(f)
            for row in rd:
                stat['rows'] += 1
                # 列名大小写不敏感
                low = {(k or '').strip().lower(): v for k, v in row.items()}
                text = low.get('text_zh')
                if text is None:
                    text = low.get('text') or low.get('zh') or low.get('translation')
                if text is None or not str(text).strip():
                    stat['empty'] += 1
                    continue
                text = str(text)
                try:
                    text = T.unesc_cell(text)
                except ValueError:
                    pass                       # 译文中出现反斜杠时按原样
                res = low.get('resource') or low.get('kind') or ''
                key = low.get('id') or low.get('key') or ''
                canon, why = canonicalize(res, key)
                if canon is None:
                    stat['unknown'].append(dict(file=os.path.basename(fn), id=key,
                                                resource=res, reason=why))
                    continue
                status = str(low.get('status') or '').strip().lower()
                tm_source = str(low.get('tm_source') or '').strip()
                srcflag = str(low.get('source') or '').strip().lower()
                is_tm = (status.startswith('tm') or bool(tm_source)
                         or srcflag in ('tm', 'translation_memory') or file_is_tm)
                if canon in trans and trans[canon]['text'] != text:
                    stat['duplicates'].append(dict(
                        key='%s:%s' % (canon[0], canon[1]),
                        first=first_src.get(canon),
                        second=os.path.basename(fn),
                        first_text=trans[canon]['text'][:60], second_text=text[:60]))
                    continue
                trans[canon] = dict(text=text, is_tm=is_tm, file=os.path.basename(fn))
                first_src.setdefault(canon, os.path.basename(fn))
                stat['used'] += 1
                stat['resources'][canon[0]] += 1
                if is_tm:
                    stat['tm_rows'] += 1
                else:
                    stat['new_rows'] += 1
    stat['resources'] = dict(stat['resources'])
    origin = {k: ('tm' if v['is_tm'] else 'new') for k, v in trans.items()}
    return trans, origin, stat


# ═════════════════════════ 校验 + 编码 ═════════════════════════
class Validator(object):
    """译文分级校验。

    allow_marker_drift: False=严格；True=全部降级为警告；'tm'=只对 TM 来源行降级。
    allow_missing_chars: True 时缺字降级为警告，用 '?' 占位（**仅供中间测试盘**；
        最终 --strict 会失败，等字库补齐 / 字体工程加字后再严格构建）。
    """

    def __init__(self, allow_marker_drift=False, allow_missing_chars=False):
        self.errors = []
        self.warnings = []
        self.allow_marker_drift = allow_marker_drift
        self.allow_missing_chars = allow_missing_chars
        self.missing_chars = collections.Counter()
        self.substitutions = []
        self.checked = 0

    def err(self, kind, key, msg):
        self.errors.append(dict(kind=kind, key=key, msg=msg))

    def warn(self, kind, key, msg):
        self.warnings.append(dict(kind=kind, key=key, msg=msg))

    def _missing_chars(self, text):
        cs = T.charset()
        out = []
        i = 0
        while i < len(text):
            if text.startswith('{{BTN:', i):
                m = BTN_RE.match(text, i)
                if m:
                    i = m.end()
                    continue
            ch = text[i]
            if ch == '\r' or ch == '\n' or ch == '\t':
                i += 1
                continue
            if ord(ch) < 0x80 or ch in cs.single or ch in cs.pair:
                i += 1
                continue
            out.append((i, ch))
            i += 1
        return out

    def encode(self, text, res, key, src_text, is_tm=False):
        """译文 → bytes；各类问题落到 self.errors / self.warnings。"""
        self.checked += 1
        # 1) 真换行 → {p}/{br}
        text = T.newlines_to_tags(text)
        # 2) 标记写法 / 计数
        bad = bad_btn_marks(text)
        if bad:
            self.err('btn_mark', key, '按键标记写法错误: %r' % bad[:3])
        sc, tc = marker_counts(src_text), marker_counts(text)
        if sc != tc:
            msg = '富文本标记计数不一致: 原 %s / 译 %s' % (sc, tc)
            allow = (self.allow_marker_drift is True
                     or (self.allow_marker_drift == 'tm' and is_tm))
            if allow:
                self.warn('marker_drift', key,
                          msg + ('（TM 行，允许）' if is_tm else '（允许）'))
            else:
                self.err('marker_drift', key, msg)
        # 3) 控制字符
        ctl = has_bad_ctrl_text(text)
        if ctl:
            self.err('ctrl_text', key, '译文含控制字符 %s' % ctl[:5])
        # 4) 缺字 → 编码（allow_missing_chars 时用 '?' 占位并降级为警告）
        missing = self._missing_chars(text)
        if missing:
            chars = ''.join(sorted({ch for _p, ch in missing}))
            if not self.allow_missing_chars:
                for pos, ch in missing:
                    self.err('charset', key, '字符集无此字 %r（第 %d 字符）' % (ch, pos + 1))
                    self.missing_chars[ch] += 1
                return None
            for _pos, ch in missing:
                self.missing_chars[ch] += 1
            self.warn('missing_chars', key,
                      '缺字 %d 个 %r —— 已用 "?" 占位（中间盘；--strict 会失败）'
                      % (len(missing), chars))
            for pos, ch in missing:
                self.substitutions.append(dict(key=key, res=res, pos=pos, char=ch))
            fixed = []
            for i, ch in enumerate(text):
                fixed.append('?' if (i, ch) in set(missing) else ch)
            text = ''.join(fixed)
        enc, issues = T.charset().encode(text, '%s/%s' % (res, key), strict=False)
        if issues:
            for pos, why in issues:
                self.err('charset', key, '%s（第 %d 字符 %r）' % (why, pos + 1, text[pos]))
            return None
        # 5) 字节层控制字符
        badb = sorted({b for b in enc if b in CTRL_BYTES})
        if badb:
            self.err('ctrl_bytes', key, '编码后含控制字节 %s' % [hex(b) for b in badb])
        # 6) 0xFF 禁忌（XML 词法器）
        if res in ('SFXML', 'SFXML_TITLE', 'MIS', 'ATR', 'STRINGS_TXT') and 0xFF in enc:
            self.err('ff_byte', key, '译文编码出 0xFF（XML 词法器会当 EOF；换词或改对偶码）')
        elif res == 'LANG' and 0xFF in enc:
            self.warn('ff_byte', key, 'LANG 译文编码出 0xFF（「著」→建议换词）')
        # 7) 往返（缺字占位后与替换后的文本比较）
        try:
            back = T.charset().decode(enc, '%s/%s' % (res, key))
        except ValueError as e:
            self.err('roundtrip', key, 'decode 失败: %s' % e)
            return enc
        cmp_src = normalize_btn_markers_for_cmp(text)
        cmp_back = normalize_btn_markers_for_cmp(back)
        if cmp_back != cmp_src:
            k = next((i for i in range(min(len(cmp_back), len(cmp_src)))
                      if cmp_back[i] != cmp_src[i]), 0)
            self.err('roundtrip', key, 'encode→decode 不一致 @%d: %r → %r'
                     % (k, cmp_src[max(0, k - 6):k + 6], cmp_back[max(0, k - 6):k + 6]))
        return enc

    def text_only_checks(self, text, res, key):
        """没有原条可对照时的轻量检查（一般用不到）。"""
        self.checked += 1
        if has_bad_ctrl_text(text):
            self.err('ctrl_text', key, '译文含控制字符')
        bad = bad_btn_marks(text)
        if bad:
            self.err('btn_mark', key, '按键标记写法错误: %r' % bad[:3])


# ═════════════════════════ 原盘 / manifest 读取 ═════════════════════════
def load_iso_resources(iso_path):
    iso = dlclib.Iso(iso_path)
    try:
        entries = dlclib.img_entries(iso)
        data = dict(entries=entries,
                    lang=T.load_lang(iso, entries),
                    sfxml=T.load_sfxml(iso, entries),
                    mis=T.load_mis(iso, entries),
                    atr=T.load_atr(iso, entries),
                    txt=T.load_txt(iso, entries))
    finally:
        iso.close()
    return data


def load_manifests():
    def _j(name):
        p = os.path.join(SOURCE, name)
        if os.path.isfile(p):
            try:
                return json.load(open(p, encoding='utf-8'))
            except Exception:                                    # noqa: BLE001
                return None
        return None
    return dict(lang=_j('manifest_lang.json'), sfxml=_j('manifest_sfxml.json'),
                mis=_j('manifest_mis.json'), atr=_j('manifest_atr.json'),
                txt=_j('manifest_strings_txt.json'), source=_j('text_source.json'))


def check_base_fingerprint(data, manifests, report_errors):
    """被抽条目的 blob sha256 与 text_source.json 比对（注入前核对基盘）。"""
    src = manifests.get('source')
    if not src or not src.get('entries'):
        return dict(checked=0, note='text_source.json 缺失，跳过条目指纹核对')
    blobs = {}
    blobs[T.LANG_IDX] = data['lang']['blob']
    blobs[T.SFXML_IDX] = data['sfxml']['blob']
    blobs[T.TXT_IDX] = data['txt']['blob']
    for m in data['mis']:
        blobs[m['entry']['idx']] = m['blob']
    for a in data['atr']:
        blobs[a['entry']['idx']] = a['blob']
    bad = []
    for rec in src['entries']:
        idx = rec.get('entry_idx')
        want = rec.get('blob_sha256')
        if idx is None or idx not in blobs:
            continue
        got = hashlib.sha256(blobs[idx]).hexdigest()
        if want and got != want:
            bad.append(dict(entry_idx=idx, name=rec.get('name'), want=want, got=got))
    if bad:
        report_errors.append(dict(kind='base_mismatch',
                                  msg='%d 个条目的 blob sha256 与 text_source.json 不符（基盘不是同一张？）'
                                      % len(bad), items=bad[:10]))
    return dict(checked=len(src['entries']) - len(bad), mismatched=len(bad),
                iso_sha256=src.get('iso_sha256'))


# ═════════════════════════ 各资源 payload 构建 ═════════════════════════
def build_lang(data, trans, v):
    lang = data['lang']
    rows = []
    translated = 0
    for r in lang['rows']:
        key = ('LANG', r['id'])
        src_text = T.decode_en(r['data'], 'LANG/' + r['id']) if r['length'] else ''
        data_b = r['data']
        rec = trans.get(key)
        if rec is not None:
            if not r['length']:
                v.err('translate_empty', r['id'], '原文为空，译文非空（空条目不应有译文）')
            enc = v.encode(rec['text'], 'LANG', r['id'], src_text, is_tm=rec['is_tm'])
            if enc is None:
                return None, dict(translated=translated, error='LANG 编码失败')
            data_b = enc
            translated += 1
            trans.pop(key, None)
        rows.append(dict(g=r['g'], gi=r['gi'], data=data_b, attr=r['attr']))
    blob, info = T.build_lang_blob(rows)
    blob = blob + (lang['tail'] if lang['tail'] else b'')
    # 结构复检
    try:
        ents2, used2 = dlclib.parse_lang(blob)
    except Exception as e:                                        # noqa: BLE001
        v.err('lang_structure', 'LANG', '重建后的 LANG blob 无法解析: %s' % e)
        return None, dict(translated=translated)
    seq1 = [(r['g'], r['gi']) for r in lang['rows']]
    seq2 = [(x.g + 1, x.i) for x in ents2]
    if seq1 != seq2:
        v.err('lang_structure', 'LANG', '重建后 (g,i) 序列与原文不一致（%d vs %d 条）'
              % (len(seq1), len(seq2)))
    counts1 = collections.Counter(r['g'] for r in lang['rows'])
    counts2 = collections.Counter(x.g + 1 for x in ents2)
    if counts1 != counts2:
        v.err('lang_structure', 'LANG', '重建后每组条数变化: %s → %s'
              % (dict(counts1), dict(counts2)))
    if any(blob[x.attr_off:x.attr_off + 2] !=
           lang['blob'][lang['rows'][i]['attr_off']:lang['rows'][i]['attr_off'] + 2]
           for i, x in enumerate(ents2) if i < len(lang['rows'])
           and lang['rows'][i]['length']):
        v.warn('lang_attr', 'LANG', '有条目的 attr 两字节与原文不同（正常应全 0）')
    return blob, dict(translated=translated,
                      entries=len(ents2), groups=int.from_bytes(blob[:4], 'little'),
                      blob_len=len(blob), used_end=used2)


def build_sfxml(data, trans, v):
    sf = data['sfxml']
    edits, translated = [], 0
    for t in sf['texts']:
        key = ('SFXML', t['id'])
        rec = trans.get(key)
        if rec is None:
            continue
        src_text = T.decode_en(t['text'], 'SFXML/' + t['id'])
        enc = v.encode(rec['text'], 'SFXML', t['id'], src_text, is_tm=rec['is_tm'])
        if enc is None:
            return None, dict(translated=translated, error='SFXML 编码失败')
        edits.append((t['span'][0], t['span'][1], enc))
        translated += 1
        trans.pop(key, None)
    for t in sf['titles']:
        key = ('SFXML_TITLE', t['id'])
        rec = trans.get(key)
        if rec is None:
            continue
        enc = v.encode(rec['text'], 'SFXML_TITLE', t['id'], t['name'], is_tm=rec['is_tm'])
        if enc is None:
            return None, dict(translated=translated, error='SFXML 标题编码失败')
        edits.append((t['span'][0], t['span'][1], enc))
        translated += 1
        trans.pop(key, None)
    edits.sort()
    blob = dlclib.splice(sf['blob'], edits)
    return blob, dict(translated=translated, texts=len(sf['texts']),
                      titles=len(sf['titles']), blob_len=len(blob))


def build_mis(data, trans, v, manifests):
    man = manifests.get('mis')
    man_map = {}
    if man and man.get('files'):
        for f in man['files']:
            man_map[f['name'].upper()] = f
    repl, files, translated = {}, [], 0
    for m in data['mis']:
        mm = man_map.get(m['name'].upper())
        if mm:
            # 交叉核对 manifest 偏移 == 重新解析的偏移（防 manifest 过期）
            mf = {f['field']: (f['span_start'], f['span_end']) for f in mm['fields']}
            for f in m['fields']:
                got = (f['span'][0], f['span'][1])
                if f['field'] in mf and mf[f['field']] != got:
                    v.err('manifest_mis', m['name'],
                          'manifest 偏移 %r != 实测 %r（manifest 过期，请重跑 dump_text.py）'
                          % (mf[f['field']], got))
        edits = []
        for f in m['fields']:
            key = ('MIS', '%s#%s' % (m['name'].upper(), f['field']))
            rec = trans.get(key)
            if rec is None:
                continue
            src_text = T.decode_en(f['value'], 'MIS/%s/%s' % (m['name'], f['field']))
            enc = v.encode(rec['text'], 'MIS', '%s#%s' % (m['name'], f['field']),
                           src_text, is_tm=rec['is_tm'])
            if enc is None:
                return None, dict(files=files, translated=translated,
                                  error='MIS 编码失败: %s' % m['name'])
            edits.append((f['span'][0], f['span'][1], enc))
            translated += 1
            trans.pop(key, None)
        if edits:
            edits.sort()
            repl[m['entry']['idx']] = dlclib.splice(m['blob'], edits)
            files.append(m['name'])
    return repl, dict(files=files, translated=translated)


def build_atr(data, trans, v):
    repl, files, translated = {}, [], 0
    for a in data['atr']:
        f = a['fields'].get('ActorName')
        if not f:
            continue
        key = ('ATR', '%s#ActorName' % a['name'].upper())
        rec = trans.get(key)
        if rec is None:
            continue
        src_text = T.decode_en(f['value'], 'ATR/' + a['name'])
        enc = v.encode(rec['text'], 'ATR', '%s#ActorName' % a['name'], src_text,
                       is_tm=rec['is_tm'])
        if enc is None:
            return None, dict(files=files, translated=translated, error='ATR 编码失败')
        repl[a['entry']['idx']] = dlclib.splice(
            a['blob'], [(f['span'][0], f['span'][1], enc)])
        files.append(a['name'])
        translated += 1
        trans.pop(key, None)
    return repl, dict(files=files, translated=translated)


def build_txt(data, trans, v):
    txt = data['txt']
    edits, translated = [], 0
    for p in txt['pairs']:
        key = ('STRINGS_TXT', 'TXT:%s' % p['token'])
        rec = trans.get(key)
        if rec is None:
            continue
        src_text = T.decode_en(p['value'], 'TXT/' + p['token'])
        enc = v.encode(rec['text'], 'STRINGS_TXT', 'TXT:' + p['token'], src_text,
                       is_tm=rec['is_tm'])
        if enc is None:
            return None, dict(translated=translated, error='STRINGS_TXT 编码失败')
        edits.append((p['value_span'][0], p['value_span'][1], enc))
        translated += 1
        trans.pop(key, None)
    if not edits:
        return None, dict(translated=0)
    edits.sort()
    return dlclib.splice(txt['blob'], edits), dict(translated=translated,
                                                   blob_len=len(txt['blob']))


# ═════════════════════════ 布局预测 / 输出 ═════════════════════════
def predict_layout(data, repl):
    """按 rebuild.py 口径（16,384 B 分块 + dlclib.lzo_pack）预测 stored/real。"""
    items = []
    for idx in sorted(repl):
        e = data['entries'][idx]
        blob = bytes(repl[idx])
        old_kind = 'lzo' if e['stored'] != e['real'] else 'raw'
        if old_kind == 'raw':
            new_stored = len(blob)
            new_real = len(blob)
        else:
            chunks = [(blob[i:i + CHUNK], min(CHUNK, len(blob) - i))
                      for i in range(0, len(blob), CHUNK)]
            packed = dlclib.lzo_pack(chunks)
            new_stored = len(packed)
            new_real = len(blob)
        items.append(dict(entry_idx=idx, name=e['name'], kind=old_kind,
                          old_real=e['real'], old_stored=e['stored'],
                          new_real=new_real, new_stored=new_stored,
                          delta_real=new_real - e['real'],
                          delta_stored=new_stored - e['stored']))
    total_delta_stored = sum(x['delta_stored'] for x in items)
    return dict(items=items, total_delta_stored=total_delta_stored,
                requires_img_relayout=bool(total_delta_stored),
                note='Lead 的 rebuild.py 会重排 GR.IMG 条目偏移并更新条目表/根目录大小，'
                     '因此 stored 增大不是阻塞；本字段供确认新 IMG 增量。')


def write_payloads(out_dir, data, repl, report):
    os.makedirs(out_dir, exist_ok=True)
    index = []
    for idx in sorted(repl):
        e = data['entries'][idx]
        safe = re.sub(r'[^A-Za-z0-9_.-]+', '_', e['name'])
        fn = '%04d_%s.blob' % (idx, safe)
        with open(os.path.join(out_dir, fn), 'wb') as f:
            f.write(bytes(repl[idx]))
        index.append(dict(entry_idx=idx, name=e['name'], payload_file=fn,
                          blob_len=len(repl[idx])))
    doc = dict(schema=SCHEMA, generated_by='tools/dlc/inject_text.py',
               iso_sha256=dlclib.ISO_SHA256, payloads=index)
    T.write_json(os.path.join(out_dir, 'replacements.json'), doc)
    report['payload_index'] = index
    return index


# ═════════════════════════ 译文合并器（批次 + TM 预填 → 总表）═════════════════════════
def merge_translation_sources(translation_paths, worklist_path=None, out_csv=None):
    """把「7 个翻译批次 CSV」+「worklist 里的 TM 预填行」合并成最终总表。

    · 目标全集 = `translation_worklist.csv` 的全部可译行（3,372 条）；
    · 新译批次优先（source=new），其次 worklist 的 tm_* 预填行（source=tm）；
    · 输出列：resource,id,text_en,text_zh,source（id 用 worklist 原 id，注入侧可直接消费）。
    返回 (stats, rows)。不覆盖任何已有文件，除非显式给 out_csv。
    """
    worklist_path = worklist_path or os.path.join(WORK, 'translation_worklist.csv')
    targets = []
    with open(worklist_path, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            targets.append(dict(resource=r.get('resource') or '',
                                id=r.get('id') or '',
                                text_en=r.get('text_en') or '',
                                tm_zh=r.get('text_zh') or '',
                                status=r.get('status') or ''))
    trans, _origin, _stat = load_translations(_as_paths(translation_paths), None)
    rows, missing = [], []
    n_new = n_tm = 0
    for t in targets:
        canon, _why = canonicalize(t['resource'], t['id'])
        zh, source = '', ''
        if canon in trans and trans[canon]['text'].strip():
            zh = trans[canon]['text']
            source = 'tm' if trans[canon]['is_tm'] else 'new'
        elif t['tm_zh'].strip():
            try:
                zh = T.unesc_cell(t['tm_zh'])
            except ValueError:
                zh = t['tm_zh']
            source = 'tm'
        if zh:
            if source == 'new':
                n_new += 1
            else:
                n_tm += 1
        else:
            missing.append(t['id'])
        rows.append(dict(resource=t['resource'], id=t['id'], text_en=t['text_en'],
                         text_zh=T.esc_cell(zh) if zh else '', source=source))
    stats = dict(targets=len(targets), filled=n_new + n_tm, missing=len(missing),
                 new_rows=n_new, tm_rows=n_tm,
                 coverage_pct=round(100.0 * (n_new + n_tm) / max(1, len(targets)), 2),
                 missing_ids=missing[:50], out_csv=out_csv)
    if out_csv:
        T.write_csv(out_csv, ['resource', 'id', 'text_en', 'text_zh', 'source'], rows)
        P('  合并完成: %d/%d（new %d / tm %d / 缺 %d）→ %s'
          % (stats['filled'], stats['targets'], n_new, n_tm, len(missing), out_csv))
    return stats, rows


# ═════════════════════════ 主接口 ═════════════════════════
def _as_paths(translation_path):
    if isinstance(translation_path, (list, tuple)):
        return list(translation_path)
    return [translation_path]


def _build(iso_path, translation_path, *, allow_marker_drift=False,
           allow_missing_chars=True, strict=False, keep_tail=True,
           manifests=None):
    """内部实现：返回 (blob_repl, report, data, origin, trans)。"""
    if strict:
        allow_marker_drift = False
        allow_missing_chars = False
    trans, origin, tstat = load_translations(_as_paths(translation_path), None)
    v = Validator(allow_marker_drift=allow_marker_drift,
                  allow_missing_chars=allow_missing_chars)
    manifests = manifests or load_manifests()
    data = load_iso_resources(iso_path)
    errors = []
    fingerprint = check_base_fingerprint(data, manifests, errors)
    repl, res_report = {}, {}
    # a) LANG
    blob, st = build_lang(data, trans, v)
    if blob is not None:
        repl[T.LANG_IDX] = blob
    res_report['LANG'] = st
    # b) SFXML
    blob, st = build_sfxml(data, trans, v)
    if blob is not None:
        repl[T.SFXML_IDX] = blob
    res_report['SFXML'] = st
    # c) MIS（45 个全量，按条目号输出）
    mis_repl, st = build_mis(data, trans, v, manifests)
    if mis_repl is None:
        mis_repl = {}
    repl.update(mis_repl)
    res_report['MIS'] = st
    # d) ATR / TXT
    atr_repl, st = build_atr(data, trans, v)
    if atr_repl is None:
        atr_repl = {}
    repl.update(atr_repl)
    res_report['ATR'] = st
    txt_blob, st = build_txt(data, trans, v)
    if txt_blob is not None:
        repl[T.TXT_IDX] = txt_blob
    res_report['STRINGS_TXT'] = st
    # e) 剩余译文 = 未知 id
    unknown = sorted('%s:%s' % (k[0], k[1]) for k in trans)
    layout = predict_layout(data, repl)
    payload_index = [dict(entry_idx=idx, name=data['entries'][idx]['name'],
                          blob_len=len(repl[idx])) for idx in sorted(repl)]
    report = dict(
        schema=SCHEMA, ok=False,
        iso=dict(path=os.path.basename(iso_path), sha256=dlclib.ISO_SHA256),
        flags=dict(allow_marker_drift=allow_marker_drift,
                   allow_missing_chars=allow_missing_chars, strict=strict),
        translations=tstat,
        unknown_ids_count=len(unknown),
        unknown_ids=unknown[:20],
        fingerprint=fingerprint,
        resources=res_report,
        checks=dict(validated_translations=v.checked,
                    errors=len(v.errors) + len(errors),
                    warnings=len(v.warnings),
                    missing_chars=dict(v.missing_chars),
                    missing_char_total=sum(v.missing_chars.values()),
                    substitutions=len(v.substitutions),
                    tm_rows=tstat.get('tm_rows', 0),
                    new_rows=tstat.get('new_rows', 0)),
        missing_char_substitutions=v.substitutions[:200],
        errors=errors + v.errors,
        warnings=v.warnings,
        layout=layout,
        payload_index=payload_index)
    report['ok'] = (not report['errors'])
    return repl, report, data, origin, trans


def build_replacements(iso_path, translation_paths, *, allow_marker_drift=True,
                       allow_missing_chars=True, strict=False, keep_tail=True,
                       manifests=None):
    """原盘 + 译文表 → (blob_repl, report)。

    参数（与 Lead/build.py 约定一致）：
      iso_path            : 英文原盘 ISO
      translation_paths   : **路径列表**（文件或目录均可；也兼容单个字符串）
      allow_marker_drift  : True=富文本标记计数不一致只告警（build 中间盘用）；
                            False=严格；也可传 'tm' 只放过 TM 来源行。
      allow_missing_chars : True=缺字用 '?' 占位并告警（中间盘用；最终 --strict 必须失败）
      strict              : True=全部按最严格处理（覆盖上面两个开关）

    返回 blob_repl = {条目号(int): 新 payload blob(bytes)}，直接喂
    rebuild.py 的 build_img(..., blob_repl=...)。
    """
    repl, report, _data, _origin, _trans = _build(
        iso_path, translation_paths, allow_marker_drift=allow_marker_drift,
        allow_missing_chars=allow_missing_chars, strict=strict,
        keep_tail=keep_tail, manifests=manifests)
    return repl, report


# ═════════════════════════ CLI ═════════════════════════
def _print_report(report, repl):
    P('\n===== inject_text 报告 =====')
    P('  译文表: %d 个文件 / %d 行；命中 %d 条；空值 %d；未知 %d；重复冲突 %d'
      % (len(report['translations']['files']), report['translations']['rows'],
         report['translations']['used'], report['translations']['empty'],
         len(report['translations']['unknown']),
         len(report['translations']['duplicates'])))
    P('  按资源: %s' % report['translations']['resources'])
    P('  基盘指纹: %s' % report['fingerprint'])
    for k in ('LANG', 'SFXML', 'MIS', 'ATR', 'STRINGS_TXT'):
        st = report['resources'].get(k, {})
        if not st:
            continue
        P('  %-10s %s' % (k, {kk: vv for kk, vv in st.items()
                              if kk in ('translated', 'files', 'entries', 'groups',
                                        'blob_len', 'texts', 'titles')}))
    lay = report['layout']
    P('  新 payload 条目 %d 个；stored 合计 Δ=%+d B（rebuild.py 负责重排）'
      % (len(lay['items']), lay['total_delta_stored']))
    for x in lay['items']:
        if abs(x['delta_stored']) > 200 or x['entry_idx'] == T.LANG_IDX:
            P('    #%04d %-26s %+6d B  (real %d→%d)'
              % (x['entry_idx'], x['name'], x['delta_stored'],
                 x['old_real'], x['new_real']))
    if report['checks']['missing_chars']:
        P('  [!!] 缺字: %s' % report['checks']['missing_chars'])
    for e in report['errors'][:12]:
        P('  [error] %s %s: %s' % (e.get('kind'), e.get('key'), e.get('msg')))
    if len(report['errors']) > 12:
        P('  ... 共 %d 条 error' % len(report['errors']))
    for w in report['warnings'][:6]:
        P('  [warn] %s %s: %s' % (w.get('kind'), w.get('key'), w.get('msg')))
    if report['unknown_ids']:
        P('  [warn] 未被消费的译文 id %d 个，前 5: %s'
          % (report['unknown_ids_count'], report['unknown_ids'][:5]))
    P('  结论: %s' % ('OK（可交给 rebuild.py）' if report['ok']
                      else '拒绝产出（%d 条 error）' % len(report['errors'])))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='把译文表变成条目 payload blob 清单（不写 ISO）')
    ap.add_argument('--iso', default=T.DEFAULT_ISO)
    ap.add_argument('--translations', nargs='+', required=True,
                    help='译文 CSV 文件或目录（可多个；路径列表）')
    ap.add_argument('--out-dir', help='写出 <idx>_<name>.blob + replacements.json')
    ap.add_argument('--report', default=os.path.join(WORK, 'inject_report.json'))
    ap.add_argument('--allow-marker-drift', nargs='?', const='all', default='none',
                    choices=['none', 'all', 'tm'],
                    help='富文本标记计数不一致的处理：none=严格 / all=只告警 / tm=只放过 TM 行')
    ap.add_argument('--strict', action='store_true',
                    help='最终构建：缺字与标记漂移都必须失败（覆盖上面两个开关）')
    ap.add_argument('--check-only', action='store_true', help='只校验，不写 blob 文件')
    ap.add_argument('--merge-out',
                    help='先把 --translations（批次）与 --merge-worklist 的 TM 预填合并成'
                         '总表（resource,id,text_en,text_zh,source），再用它做注入输入')
    ap.add_argument('--merge-worklist',
                    default=os.path.join(WORK, 'translation_worklist.csv'),
                    help='合并器的目标全集（默认 work/analysis/text/translation_worklist.csv）')
    args = ap.parse_args(argv)
    adm = args.allow_marker_drift
    adm_val = {'none': False, 'all': True, 'tm': 'tm'}[adm]
    paths = args.translations
    if args.merge_out:
        merge_translation_sources(paths, args.merge_worklist, args.merge_out)
        paths = [args.merge_out]
    repl, report, data, _origin, _trans = _build(
        args.iso, paths, allow_marker_drift=adm_val,
        allow_missing_chars=not args.strict, strict=args.strict)
    if args.out_dir and not args.check_only and report['ok']:
        write_payloads(args.out_dir, data, repl, report)
    if args.report:
        T.write_json(args.report, report)
    _print_report(report, repl)
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
