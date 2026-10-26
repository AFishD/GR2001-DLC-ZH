# -*- coding: utf-8 -*-
r"""textlib.py —— 《幽灵行动：丛林风暴》PS2 (SLUS-20820) 资料片文本工程公共库。

职责（只读原盘；不写 ISO）：
  · 编码：英文正文按 Windows-1252 解 / 编；中文按本体 2403 字字符集解 / 编；
    CSV 单元格一律「\r \n \t 字面转义」，禁止真换行。
  · 容器：LANG（EN_STRINGS.RES，67 组 / 2,971 条）、SFXML（EN_SPECIAL_FEATURE.XML）、
    MIS（45 个，5 段 LZO 子流，XML 在解压流里）、ATR（766 个，raw XML）、
    EN_STRINGS.TXT（token→显示名）、其它 XML 审计。
  · 翻译记忆：本体英文盘 LANG/SFXML + 本体译文资产 CSV + 本体成品盘 MIS/TXT 中文
    → 精确 / 归一化 / difflib≥0.85 候选。
  · 用字清单：TM 复用字的真实频次 + 未覆盖条目的保守估算 + 术语候选新字。
  · 注入约束：按原条目分块 16384 B 重压，预测 stored 与 slack（不写盘）。

关键事实（本库脚本文档均以本次实测为准）：
  LANG      GR.IMG#576  stored=69,355  real=177,441（11 子流：10×16384 + 13,601）
  SFXML     GR.IMG#3101 stored=55,639  real=133,359（98 条 <text>，123 个 <item>）
  MIS       45 个，stored!=real，每条目 LZO 子流；**rlen==clen 的子流是原文直存**（实测 107 条资源）
  ATR       766 个，raw XML，<ActorName> 是显示名候选
  TXT       GR.IMG#577 stored=2,822 real=7,092（228 对 token→显示名）
  slack     条目与下一条 off 的间隙极小：LANG=5 B / SFXML=9 B / MIS=3..10 B → 注入后不能变大
"""
import collections
import csv
import difflib
import io
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)

import dlclib                                                    # noqa: E402

P = dlclib.P

# ── 路径 ──
DEFAULT_ISO = dlclib.DEFAULT_ISO
DEFAULT_BASE_ISO = dlclib.DEFAULT_BASE_ISO
DEFAULT_BASE_ZH_ISO = dlclib.DEFAULT_BASE_ZH_ISO
ASSETS_TEXT = os.path.join(REPO, 'assets', 'text')
SOURCE_DIR = os.path.join(ASSETS_TEXT, 'source')
CHARSET_PATH = os.path.join(REPO, 'assets', 'charset', 'charset_compiled_zh16.json')
WORK_TEXT = os.path.join(REPO, 'work', 'analysis', 'text')

# ── 资源号（GR.IMG）──
IDX = dlclib.IDX
LANG_IDX = 576
SFXML_IDX = 3101
TXT_IDX = 577
MIS_EXT = '.MIS'
ATR_EXT = '.ATR'
SPECIAL_FEATURE_LANGS = {
    'EN': 3101, 'DE': 3100, 'ES': 3102, 'FR': 3104, 'IT': 3107,
}
OTHER_XML = ['CAMPAIGN.XML', 'CMBTMODL.XML', 'BEST_TIMES.XML', 'OPTIONS.XML',
             'UNLOCKED_HEROES.XML', 'UNLOCKED_MISSIONS.XML']

# ── 注入约束常量 ──
CHUNK = 16384                    # 载荷分块大小（LANG/SFXML/MIS 实测都是 16 KiB 边界的子流）
ICON_BYTES = (0xB1, 0xB5)        # 引擎文本图标码：0xB1=△ 0xB5=✕（本体英文盘实测出现）

# MILESTONES: LANG 分组语义（本库文档表格用；数据驱动，不参与解析）
LANG_GROUP_ROLES = {
    range(1, 12): '多人模式 胜负/目标提示（G001..G011）',
    range(12, 19): '训练关卡帮助正文（G012..G018，7 份近似重复）',
    range(19, 27): 'Jungle Storm 战役 C01..C08（G019..G026）',
    range(27, 34): '战役 J01..J08（G027..G033）',
    range(34, 39): '多人地图 MP01..MP05（G034..G038）',
    range(39, 40): 'U05 战役目标（G039）',
    range(40, 45): 'CP01..CP05 地图（G040..G044）',
    range(45, 48): '多人模式规则（G045..G047）',
    range(48, 53): 'TAC01..TAC05 战术关卡（G048..G052）',
    range(53, 58): 'DP01..DP05 训练/联机地图（G053..G057）',
    range(58, 59): '通用 UI 大组（G058，1,324 条）',
    range(59, 60): '菜单/系统提示（G059）',
    range(61, 62): '按键动作名（G061）',
    range(62, 63): '制作人员名单（G062，393 条）',
    range(63, 68): '文件名/音频名占位（G063..G067）',
}


# ═════════════════════════ 编码 / CSV 单元格 ═════════════════════════
_CP1252 = {}
for _b in range(0x80, 0x100):
    try:
        _CP1252[_b] = bytes([_b]).decode('cp1252')
    except UnicodeDecodeError:
        pass
_CP1252_INV = {v: k for k, v in _CP1252.items()}
for _ch, _b in (('’', 0x92), ('…', 0x85), ('®', 0xAE), ('¾', 0xBE),
                ('ç', 0xE7), ('é', 0xE9), ('ñ', 0xF1)):
    _CP1252_INV.setdefault(_ch, _b)

_ESCAPE_MAP = {'\\': '\\\\', '\r': '\\r', '\n': '\\n', '\t': '\\t'}


def esc_cell(s):
    """text（可含真 CR/LF/TAB）→ 单行 CSV 单元格（字面转义 \\r \\n \\t）。"""
    if not isinstance(s, str):
        raise TypeError('esc_cell 需要 str')
    out = []
    for ch in s:
        e = _ESCAPE_MAP.get(ch)
        if e is not None:
            out.append(e)
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append('\\x%02x' % ord(ch))
        else:
            out.append(ch)
    return ''.join(out)


def unesc_cell(s):
    """CSV 单元格 → text（\\r \\n \\t \\xNN 反转义）。"""
    if '\\' not in s:
        return s
    out, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch != '\\':
            out.append(ch)
            i += 1
            continue
        nxt = s[i + 1] if i + 1 < n else ''
        if nxt == '\\':
            out.append('\\'); i += 2
        elif nxt == 'r':
            out.append('\r'); i += 2
        elif nxt == 'n':
            out.append('\n'); i += 2
        elif nxt == 't':
            out.append('\t'); i += 2
        elif nxt == 'x' and i + 3 < n:
            out.append(chr(int(s[i + 2:i + 4], 16))); i += 4
        else:
            raise ValueError('非法转义序列 \\%s @%d: %r' % (nxt, i, s[max(0, i - 8):i + 8]))
    return ''.join(out)


def cell_roundtrip_ok(s):
    try:
        return unesc_cell(esc_cell(s)) == s
    except ValueError:
        return False


def decode_en(data, where='?', icons=ICON_BYTES):
    """英文正文 bytes → text（Windows-1252；< 0x20 保留为 \\r\\n\\t；图标码 → {{BTN:XXXX}}）。"""
    out = []
    for pos, b in enumerate(data):
        if b == 0x0A:
            out.append('\n')
        elif b == 0x0D:
            out.append('\r')
        elif b == 0x09:
            out.append('\t')
        elif b < 0x20 or b == 0x7F:
            raise ValueError('%s 第 %d 字节是 ASCII 控制字符 0x%02X（未约定语义）'
                             % (where, pos + 1, b))
        elif b < 0x80:
            out.append(chr(b))
        elif b in icons:
            out.append('{{BTN:%04X}}' % (0xE000 + b))
        elif b in _CP1252:
            out.append(_CP1252[b])
        else:
            raise ValueError('%s 第 %d 字节 0x%02X 不是可打印 cp1252 字符（上下文 %r）'
                             % (where, pos + 1, b, bytes(data[max(0, pos - 16):pos + 16])))
    return ''.join(out)


def encode_en(text, where='?'):
    """text → 英文盘 bytes（decode_en 的逆；中文等非 cp1252 字符报错）。"""
    out = bytearray()
    i = 0
    while i < len(text):
        if text.startswith('{{BTN:', i):
            m = re.match(r'\{\{BTN:([0-9A-Fa-f]{4})\}\}', text[i:])
            if not m:
                raise ValueError('%s 按键标记写法错误 @%d' % (where, i))
            out.append(int(m.group(1), 16) - 0xE000)
            i += m.end()
            continue
        ch = text[i]
        if ch == '\n':
            out.append(0x0A)
        elif ch == '\r':
            out.append(0x0D)
        elif ch == '\t':
            out.append(0x09)
        elif ord(ch) < 0x80:
            out.append(ord(ch))
        elif ch in _CP1252_INV:
            out.append(_CP1252_INV[ch])
        else:
            raise ValueError('%s 字符 %r (U+%04X) 不在 cp1252 里' % (where, ch, ord(ch)))
        i += 1
    return bytes(out)


def normalize_for_match(s):
    """归一化（大小写/空白/引号/破折号），供 TM 精确归一与 difflib 用。"""
    if not s:
        return ''
    s = s.casefold()
    s = s.replace('\u2019', "'").replace('\u2018', "'")
    s = s.replace('\u201c', '"').replace('\u201d', '"')
    s = s.replace('\u2013', '-').replace('\u2014', '-').replace('\u2212', '-')
    s = s.replace('\u00a0', ' ')
    s = re.sub(r'\{p\}|\{br\}', ' ', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def looks_like_english(s):
    return bool(re.search(r'[A-Za-z]{2,}', s))


def has_cjk(s):
    return bool(re.search(r'[\u3400-\u9fff]', s))


# ═════════════════════════ 本体中文字符集 ═════════════════════════
class Charset(object):
    """本库自带的字符集（assets/charset/charset_compiled_zh16.json）只读封装。

    · codes   : 103 条单字节 char -> byte（含 ç/ñ 与 128..159 区符号）
    · pair_of : 2300 条对偶 char -> (lead, trail)
    · 供「用字是否在字符集里」「模拟编码后长度」用；注入实现可复用。
    """

    PUA_LO, PUA_HI = 0xE000, 0xF8FF

    def __init__(self, path=CHARSET_PATH):
        j = json.load(open(path, encoding='utf-8'))
        self.path = path
        self.single = {ch: int(v) for ch, v in j['codes'].items()}
        self.pair = {ch: tuple(v) for ch, v in j['pair_of'].items()}
        self.dec_single = {v: ch for ch, v in self.single.items()}
        self.dec_pair = {v: ch for ch, v in self.pair.items()}
        self.chars = set(self.single) | set(self.pair)
        self.pua_free = sorted(ch for ch in self.chars
                               if self.PUA_LO <= ord(ch) <= self.PUA_HI)
        self.pair_leads = sorted(set(b1 for b1, _ in self.pair.values()))
        self.pair_stride = len(set(b2 for _, b2 in self.pair.values()))

    # ---- 解码（本体成品盘的字节 → text）----
    def decode(self, data, where='?'):
        out, i, n = [], 0, len(data)
        bad = 0
        while i < n:
            b = data[i]
            if b in ICON_BYTE_TOKENS:
                out.append(ICON_BYTE_TOKENS[b]); i += 1
            elif b < 0x80:
                out.append(chr(b)); i += 1
            elif (b, data[i + 1] if i + 1 < n else -1) in self.dec_pair:
                out.append(self.dec_pair[(b, data[i + 1])]); i += 2
            elif b in self.dec_single:
                out.append(self.dec_single[b]); i += 1
            else:
                out.append('\ufffd'); bad += 1; i += 1
        if bad:
            raise ValueError('%s 有 %d 个字节不在本体字符集里（decode 失败）' % (where, bad))
        return ''.join(out)

    # ---- 编码（text → 引擎字节；模拟注入长度用）----
    def encode(self, text, where='?', strict=True):
        out = bytearray()
        issues = []
        i = 0
        while i < len(text):
            if text.startswith('{{BTN:', i):
                m = re.match(r'\{\{BTN:([0-9A-Fa-f]{4})\}\}', text[i:])
                if not m:
                    issues.append((i, '按键标记写法错误'))
                    i += 1
                    continue
                val = int(m.group(1), 16)
                out.append(ICON_TOKEN_BYTES.get(val, val - 0xE000))
                i += m.end()
                continue
            ch = text[i]
            o = ord(ch)
            if ch == '\n':
                out.append(0x0A)
            elif ch == '\r':
                out.append(0x0D)
            elif ch == '\t':
                out.append(0x09)
            elif o < 0x80:
                out.append(o)
            elif ch in self.single:
                out.append(self.single[ch])
            elif ch in self.pair:
                b1, b2 = self.pair[ch]
                out += bytes((b1, b2))
            else:
                issues.append((i, '字符集无此字 %r U+%04X' % (ch, o)))
            i += 1
        if issues and strict:
            raise ValueError('%s 编码失败: %s' % (where, issues[:6]))
        return bytes(out), issues


# 引擎手柄图标码换区（v18）：{{BTN:E0B1}}→0x90（△）、{{BTN:E0B5}}→0x84（✕）
ICON_TOKEN_BYTES = {0xE0B1: 0x90, 0xE0B5: 0x84}
ICON_BYTE_TOKENS = {v: '{{BTN:%04X}}' % k for k, v in ICON_TOKEN_BYTES.items()}


CHARSET = None


def charset():
    global CHARSET
    if CHARSET is None:
        CHARSET = Charset()
    return CHARSET


# ═════════════════════════ 容器：条目 / LZO 子流 ═════════════════════════
def parse_chunks(iso, entry):
    """解析一个 IMG 条目的载荷分块（`{u32 clen}{u32 rlen}{data}` 顺序拼接）。

    ★ 实测（2026-10-21，全 3,111 条扫描）：**clen == rlen 的子流是原文直存**，
      不是 LZO 流（107 条资源出现；例：CP03_PRISON.MIS 的尾段 969 B、全部 .WAV）。
    返回 dict(packed, chunks=[dict(kind,clen,rlen,hdr_off,data)], blob, frame_end)。
    """
    packed = iso.read(entry['iso_off'], entry['stored'])
    if entry['stored'] == entry['real']:
        return dict(packed=packed, chunks=[], blob=packed, frame_end=len(packed), whole_raw=True)
    p, chunks = 0, []
    while p + 8 <= len(packed):
        clen, rlen = struct.unpack_from('<II', packed, p)
        if clen == 0 or p + 8 + clen > len(packed):
            break
        data = packed[p + 8:p + 8 + clen]
        if clen == rlen:
            chunks.append(dict(kind='raw', clen=clen, rlen=rlen, hdr_off=p, data=data))
        else:
            dec, err, _ = dlclib.lzo1x_decompress(data, out_size=rlen)
            if err is not None:
                raise ValueError('%s 子流 @%d LZO 解压失败: %s' % (entry['name'], p, err))
            chunks.append(dict(kind='lzo', clen=clen, rlen=rlen, hdr_off=p, data=bytes(dec)))
        p += 8 + clen
    blob = b''.join(c['data'] for c in chunks)
    if len(blob) != entry['real']:
        raise ValueError('%s 子流展开 %d != real %d' % (entry['name'], len(blob), entry['real']))
    return dict(packed=packed, chunks=chunks, blob=blob, frame_end=p, whole_raw=False)


def load_entry_blob(iso, entry):
    return parse_chunks(iso, entry)['blob']


def pack_frames(blobs, allow_raw=True):
    """[块 bytes] → (帧字节, [dict(kind,clen,rlen)])，逐块自证。

    clen == rlen 时按实测约定写成原文直存（与 107 条原盘资源同构）。
    """
    out = bytearray()
    info = []
    for seg in blobs:
        comp = dlclib.lzo_compress(seg, level=7, use_m1=True, use_m4=True)
        if allow_raw and len(comp) >= len(seg):
            out += struct.pack('<II', len(seg), len(seg)) + seg
            info.append(dict(kind='raw', clen=len(seg), rlen=len(seg)))
            continue
        back, err, _ = dlclib.lzo1x_decompress(comp, out_size=len(seg))
        if err is not None or bytes(back) != bytes(seg):
            raise ValueError('LZO 压缩回环失败 (len=%d)' % len(seg))
        out += struct.pack('<II', len(comp), len(seg)) + comp
        info.append(dict(kind='lzo', clen=len(comp), rlen=len(seg)))
    return bytes(out), info


def roughly_pack(blob, chunk_size=CHUNK):
    """把新 blob 按 chunk_size 分块重压，返回 (frames, info, stored)。"""
    segs = [blob[i:i + chunk_size] for i in range(0, len(blob), chunk_size)]
    frames, info = pack_frames(segs)
    return frames, info, len(frames)


def entry_slack(entries, idx):
    """条目 idx 的 slack = 下一条 off - (本条目 off + stored)；末条返回 None。"""
    e = entries[idx]
    if idx + 1 >= len(entries):
        return None
    return entries[idx + 1]['off'] - (e['off'] + e['stored'])


# ═════════════════════════ LANG（EN_STRINGS.RES）═════════════════════════
def load_lang(iso, entries=None):
    """解析 LANG 表 → dict(entry, chunks, blob, rows, used_end, tail_hex, ngroups)。

    rows[i] = dict(id, g, i, data, length, data_off, attr_off, attr, span_start, span_end)
      · id = 'G%03d.I%03d' % (g+1, i)（1-based 组号，与本体工程 CSV 口径一致）
      · span_start = data_off-4（u32 长度字段起点）；span_end = attr_off+2
    """
    entries = entries or dlclib.img_entries(iso)
    e = entries[LANG_IDX]
    ch = parse_chunks(iso, e)
    blob = ch['blob']
    ents, used = dlclib.parse_lang(blob)
    rows = []
    for x in ents:
        rows.append(dict(
            id='G%03d.I%03d' % (x.g + 1, x.i), g=x.g + 1, gi=x.i,
            data=x.data, length=x.length,
            data_off=x.data_off, attr_off=x.attr_off,
            attr=blob[x.attr_off:x.attr_off + 2],
            span_start=x.data_off - 4, span_end=x.attr_off + 2))
    ngroups = struct.unpack_from('<I', blob, 0)[0]
    return dict(entry=e, chunks=ch['chunks'], blob=blob, rows=rows,
                used_end=used, ngroups=ngroups,
                tail=blob[used:], packed_len=len(ch['packed']))


def build_lang_blob(rows):
    """按 rows 的 (g, i) 顺序重建 LANG blob（保留每条 attr 2 字节）。

    rows 需含 g(1-based), gi(i), data(bytes), attr(bytes2 或 int)。
    返回 (blob, 结构信息 dict)。
    """
    by_group = collections.defaultdict(list)
    for r in rows:
        by_group[r['g'] - 1].append(r)
    for g in by_group:
        by_group[g].sort(key=lambda r: r['gi'])
    out = bytearray()
    out += struct.pack('<I', len(by_group))
    for g in range(len(by_group)):
        if g:
            out += struct.pack('<I', 0)
        grp = by_group[g]
        out += struct.pack('<I', len(grp))
        for r in grp:
            data = r['data']
            attr = r.get('attr', b'\x00\x00')
            if isinstance(attr, int):
                attr = struct.pack('<H', attr)
            out += struct.pack('<I', len(data)) + data + attr
    return bytes(out), dict(ngroups=len(by_group), entries=sum(len(v) for v in by_group.values()))


# ═════════════════════════ SFXML（EN_SPECIAL_FEATURE.XML）═════════════════════════
_TAG_SEARCH = re.compile(rb'<([A-Za-z][A-Za-z0-9_]*)([^>]*)>')
_ATTR_NAME = re.compile(rb'name\s*=\s*"([^"]*)"')


def _attr_name(attrs):
    m = _ATTR_NAME.search(attrs)
    if not m:
        return None, None
    return m.group(1).decode('latin-1'), m.start(1)


def load_sfxml(iso, entries=None, idx=SFXML_IDX):
    """解析特别收录 XML → dict(entry, chunks, blob, titles, texts, tail)。

    titles: [dict(id='A%04d', tag=studio|group|item, name, span(start,end),
                  studio, group, order)]
    texts : [dict(id='T%04d', text(bytes), span(start,end), studio, group, item)]
    """
    entries = entries or dlclib.img_entries(iso)
    e = entries[idx]
    ch = parse_chunks(iso, e)
    blob = ch['blob']
    titles, texts = [], []
    cur_studio = cur_group = cur_item = None
    n_selfclose_text = 0
    pos = 0
    while True:
        m = _TAG_SEARCH.search(blob, pos)
        if not m:
            break
        tag = m.group(1).decode('latin-1')
        attrs = m.group(2) or b''
        if attrs.rstrip().endswith(b'/'):
            # 自闭合标签（本盘实测：<text/> ×25、<soundname/>、<moviename/>、<3dname/> 等）
            if tag == 'text':
                n_selfclose_text += 1
            pos = m.end()
            continue
        if tag in ('studio', 'group', 'item'):
            name, rel = _attr_name(attrs)
            if name is None:
                pos = m.end()
                continue
            start = m.start(2) + rel
            span = (start, start + len(name.encode('latin-1')))
            rec = dict(id='A%04d' % (len(titles) + 1), tag=tag, name=name, span=list(span),
                       order=len(titles), studio=cur_studio, group=cur_group)
            titles.append(rec)
            if tag == 'studio':
                cur_studio, cur_group, cur_item = name, None, None
            elif tag == 'group':
                cur_group, cur_item = name, None
            else:
                cur_item = name
            pos = m.end()
        elif tag == 'text':
            end = blob.find(b'</text>', m.end())
            if end < 0:
                pos = m.end()
                continue
            body = blob[m.end():end]
            texts.append(dict(id='T%04d' % (len(texts) + 1), text=body,
                              span=[m.end(), end], studio=cur_studio,
                              group=cur_group, item=cur_item))
            pos = end + len(b'</text>')
        else:
            pos = m.end()
    return dict(entry=e, chunks=ch['chunks'], blob=blob, titles=titles, texts=texts,
                selfclose_texts=n_selfclose_text, packed_len=len(ch['packed']))


# ═════════════════════════ MIS（*.MIS，LZO 分块里的 XML）═════════════════════════
MIS_FIELDS = ('Name', 'MapName', 'LocationText', 'DateText', 'TimeText',
              'BriefingText', 'RecommendedGameTypes')


def load_mis(iso, entries=None):
    """解析全部 *.MIS。返回 [dict(name, entry, chunks, blob, fields=[...])]。

    fields: [dict(field, value(bytes), span(start,end))]
    """
    entries = entries or dlclib.img_entries(iso)
    out = []
    for e in entries:
        if not e['name'].upper().endswith(MIS_EXT):
            continue
        ch = parse_chunks(iso, e)
        blob = ch['blob']
        fields = []
        for f in MIS_FIELDS:
            pat = re.compile(b'<' + f.encode('ascii') + b'>([^<]*)</' + f.encode('ascii') + b'>')
            for m in pat.finditer(blob):
                fields.append(dict(field=f, value=bytes(m.group(1)),
                                   span=[m.start(1), m.end(1)]))
        out.append(dict(name=e['name'], entry=e, chunks=ch['chunks'], blob=blob,
                        packed=ch['packed'], fields=fields,
                        packed_len=len(ch['packed'])))
    return out


# ═════════════════════════ ATR（*.ATR，raw XML）═════════════════════════
def load_atr(iso, entries=None):
    entries = entries or dlclib.img_entries(iso)
    out = []
    for e in entries:
        if not e['name'].upper().endswith(ATR_EXT):
            continue
        ch = parse_chunks(iso, e)
        blob = ch['blob']
        rec = dict(name=e['name'], entry=e, chunks=ch['chunks'], blob=blob,
                   packed=ch['packed'], packed_len=len(ch['packed']), fields={})
        for f in ('ActorName', 'ClassName', 'FolderName'):
            m = re.search(b'<' + f.encode() + b'>([^<]*)</' + f.encode() + b'>', blob)
            if m:
                rec['fields'][f] = dict(value=bytes(m.group(1)),
                                        span=[m.start(1), m.end(1)])
        out.append(rec)
    return out


# ═════════════════════════ EN_STRINGS.TXT ═════════════════════════
def load_txt(iso, entries=None):
    """解析 EN_STRINGS.TXT 的 token→显示名表。返回 dict(entry, chunks, blob, pairs, sections)。

    pairs[i] = dict(id='TXT:<token>', token, value(bytes), value_span(start,end),
                    token_span, section, line)
    """
    entries = entries or dlclib.img_entries(iso)
    e = entries[TXT_IDX]
    ch = parse_chunks(iso, e)
    blob = ch['blob']
    pairs, sections = [], []
    line_no = 0
    for m_sec in re.finditer(rb'//[^\r\n]*', blob):
        sections.append(dict(span=[m_sec.start(), m_sec.end()],
                             text=m_sec.group(0).decode('latin-1').strip()))
    sec_idx = -1
    for m in re.finditer(rb'"([^"]*)"[ \t]+"([^"]*)"', blob):
        line = blob.count(b'\n', 0, m.start())
        while sec_idx + 1 < len(sections) and sections[sec_idx + 1]['span'][0] < m.start():
            sec_idx += 1
        section = sections[sec_idx]['text'] if sec_idx >= 0 else ''
        pairs.append(dict(id='TXT:%s' % m.group(1).decode('latin-1'),
                          token=m.group(1).decode('latin-1'),
                          value=bytes(m.group(2)),
                          value_span=[m.start(2), m.end(2)],
                          token_span=[m.start(1), m.end(1)],
                          section=section, line=line))
    return dict(entry=e, chunks=ch['chunks'], blob=blob, pairs=pairs, sections=sections,
                packed_len=len(ch['packed']))


# ═════════════════════════ 其它 XML 审计 ═════════════════════════
def audit_other_xml(iso, entries=None):
    """逐个检查非 SFXML 的 XML：返回 [dict(name, idx, stored, real, tags, player_text, verdict)]。"""
    entries = entries or dlclib.img_entries(iso)
    by_name = {e['name']: e for e in entries}
    rows = []
    for nm in OTHER_XML:
        e = by_name.get(nm)
        if e is None:
            rows.append(dict(name=nm, idx=None, stored=None, real=None, tags={},
                             player_text=[], verdict='缺失'))
            continue
        ch = parse_chunks(iso, e)
        blob = ch['blob']
        tags = collections.Counter(m.group(1).decode('latin-1')
                                   for m in re.finditer(rb'<([A-Za-z][A-Za-z0-9_]*)>', blob))
        pt = []
        # 只把「有文字内容且不是数字/文件名/内部 id」的 leaf 记成候选
        for m in re.finditer(rb'<([A-Za-z][A-Za-z0-9_]*)>([^<]{1,2000})</\1>', blob):
            v = m.group(2).strip()
            if not v:
                continue
            txt = decode_en(v, 'XML/%s/%s' % (nm, m.group(1).decode('latin-1')))
            if re.fullmatch(r'[-+]?\d+(\.\d+)?', txt) or re.fullmatch(r'[A-Za-z0-9_./\\-]+\.(rsb|atr|mis|xml|wav|keys|env|gun|kit|pob|qob|ico|bmz|sb|ss|sh|qoz|cha|gun|pss)', txt, re.I):
                continue
            if not looks_like_english(txt):
                continue
            pt.append(dict(tag=m.group(1).decode('latin-1'), text=txt,
                           span=[m.start(2), m.end(2)]))
        if nm == 'OPTIONS.XML':
            # ChatMsg 的 text = "" 全是空串；配置项本身不是「玩家可见静态文本」
            verdict = '无玩家可见文本（配置项/数值；ChatMsg 默认全为空串）'
        elif nm in ('CAMPAIGN.XML', 'UNLOCKED_HEROES.XML', 'UNLOCKED_MISSIONS.XML'):
            verdict = '无玩家可见文本（内容全是内部文件名 .mis/.atr）'
        elif nm in ('CMBTMODL.XML', 'BEST_TIMES.XML'):
            verdict = '无玩家可见文本（数值/空文件）'
        else:
            verdict = '需人工复核'
        rows.append(dict(name=nm, idx=e['idx'], stored=e['stored'], real=e['real'],
                         tags=dict(tags), player_text=pt, verdict=verdict))
    return rows


# ═════════════════════════ 本体盘读取 ═════════════════════════
BASE_MENU_LBA = 776286
BASE_GR_LBA = 19175
BASE_LANG_IDX = 25          # MENU.IMG#25 EN_STRINGS.RES
BASE_SFXML_IDX = 283        # MENU.IMG#283 EN_SPECIAL_FEATURE.XML
BASE_TXT_IDX = 30           # MENU.IMG#30 EN_STRINGS.TXT


def _base_menu_entries(iso):
    return dlclib.img_entries(iso, BASE_MENU_LBA)


def load_base_lang_en(iso_path=DEFAULT_BASE_ISO):
    """本体英文盘 LANG → dict(id -> dict(data, en_text, g, gi))。"""
    with dlclib.Iso(iso_path) as iso:
        menu = _base_menu_entries(iso)
        e = menu[BASE_LANG_IDX]
        ch = parse_chunks(iso, e)
        ents, used = dlclib.parse_lang(ch['blob'])
        out = {}
        for x in ents:
            rid = 'LANG:G%03d.I%03d' % (x.g + 1, x.i)
            out[rid] = dict(id=rid, g=x.g + 1, gi=x.i, data=x.data,
                            en_text=decode_en(x.data, 'BASE/' + rid))
        return out


def load_base_sfxml_en(iso_path=DEFAULT_BASE_ISO):
    """本体英文盘 SFXML → [dict(id='SFXML:T%04d', body, en_text)]（按 <text> 顺序，1-based）。"""
    with dlclib.Iso(iso_path) as iso:
        menu = _base_menu_entries(iso)
        e = menu[BASE_SFXML_IDX]
        ch = parse_chunks(iso, e)
        out = []
        for k, m in enumerate(dlclib.TEXT_RE.finditer(ch['blob']), start=1):
            body = bytes(m.group(1))
            out.append(dict(id='SFXML:T%04d' % k, body=body,
                            en_text=decode_en(body, 'BASE/SFXML:T%04d' % k)))
        return out


def _load_base_menu_mis(iso):
    """本体 MENU.IMG 里全部 *.MIS → {name: {field: bytes}}（不依赖 GR.IMG 副本）。"""
    out = {}
    for e in _base_menu_entries(iso):
        if not e['name'].upper().endswith(MIS_EXT):
            continue
        try:
            ch = parse_chunks(iso, e)
        except Exception:                                        # noqa: BLE001
            continue
        rec = {}
        for f in MIS_FIELDS:
            m = re.search(b'<' + f.encode() + b'>([^<]*)</' + f.encode() + b'>', ch['blob'])
            if m:
                rec[f] = bytes(m.group(1))
        out[e['name'].upper()] = rec
    return out


def load_base_mis_zh(iso_path=DEFAULT_BASE_ZH_ISO):
    """本体成品中文盘 MENU.IMG 的 MIS 字段（原文按本体字符集解码）。"""
    if not os.path.isfile(iso_path):
        return {}
    cs = charset()
    with dlclib.Iso(iso_path) as iso:
        raw = _load_base_menu_mis(iso)
    out = {}
    for nm, rec in raw.items():
        dec = {}
        for f, v in rec.items():
            try:
                dec[f] = cs.decode(v, 'BASE_ZH/%s/%s' % (nm, f))
            except ValueError:
                dec[f] = None
        out[nm] = dec
    return out


def load_base_txt_en_zh(iso_en_path=DEFAULT_BASE_ISO, iso_zh_path=DEFAULT_BASE_ZH_ISO):
    """本体英文/成品中文 EN_STRINGS.TXT：token → (en_value, zh_value|None)。"""
    def read(path):
        with dlclib.Iso(path) as iso:
            e = _base_menu_entries(iso)[BASE_TXT_IDX]
            ch = parse_chunks(iso, e)
            out = {}
            for m in re.finditer(rb'"([^"]*)"[ \t]+"([^"]*)"', ch['blob']):
                out[m.group(1).decode('latin-1')] = bytes(m.group(2))
            return out
    en = read(iso_en_path)
    zh = read(iso_zh_path) if os.path.isfile(iso_zh_path) else {}
    cs = charset()
    out = {}
    for tok, ev in en.items():
        zv = zh.get(tok)
        zt = None
        if zv is not None and zv != ev:
            try:
                zt = cs.decode(zv, 'BASE_ZH/TXT/' + tok)
            except ValueError:
                zt = None
        out[tok] = dict(en=decode_en(ev, 'BASE/TXT/' + tok), zh=zt)
    return out


# ═════════════════════════ 本体译文资产 CSV ═════════════════════════
BASE_ASSET_CSVS = [
    os.path.join(ASSETS_TEXT, 'merge', 'GR_ZH141_text_short.csv'),
    os.path.join(ASSETS_TEXT, 'merge', 'GR_ZH141_text_long.csv'),
    os.path.join(ASSETS_TEXT, 'merge', 'GR_ZH141_text_long_nowrap.csv'),
    os.path.join(ASSETS_TEXT, 'enrich', 'GR_ZH140_text_long.csv'),
]
BASE_TITLES_CSV = os.path.join(ASSETS_TEXT, 'merge', 'GR_ZH141_text_sf_titles.csv')


def cell_to_engine(s):
    """本体 CSV 单元格 → 引擎文本形态：真换行按「1 个={br} / 空行={p}」还原标记。

    本体 CSV 的换行口径：单元格里 1 个换行 = 盘上 {br}；1 个空行（连续 2 换行）= {p}。
    连续 ≥3 换行按 1 个 {p} 处理（引擎没有更多空行写法）。
    """
    if not s:
        return s
    if '\n' not in s:
        return s
    lines = s.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    out = []
    i = 0
    while i < len(lines):
        if i == 0:
            out.append(lines[0])
            i = 1
            continue
        # 数连续空行
        empties = 0
        while i < len(lines) and lines[i] == '':
            empties += 1
            i += 1
        tag = '{p}' if empties >= 1 else '{br}'
        if i < len(lines):
            out.append(tag)
            out.append(lines[i])
            i += 1
        else:
            out.append(tag)
    return ''.join(out)


def newlines_to_tags(s):
    """翻译文里如果写了真换行（CSV 里是 \\r\\n 字面转义）→ 转成引擎口径的 {br}/{p} 标记。

    本盘 LANG/SFXML/MIS 全部用 {p}/{br} 标记（实测：LANG {p}×136 {br}×5、SFXML {p}×33
    {br}×28、MIS {p}×21；没有一个真 CR/LF 字节）。译文若直接写换行，必须转标记，
    否则引擎会把换行当普通字节（或 XML 解析层直接吃/折叠）。
    """
    if not s or ('\n' not in s and '\r' not in s):
        return s
    norm = s.replace('\r\n', '\n').replace('\r', '\n')
    lines = norm.split('\n')
    out = [lines[0]]
    i = 1
    while i < len(lines):
        empties = 0
        while i < len(lines) and lines[i] == '':
            empties += 1
            i += 1
        tag = '{p}' if empties >= 1 else '{br}'
        if i < len(lines):
            out.append(tag)
            out.append(lines[i])
            i += 1
        else:
            out.append(tag)
    return ''.join(out)


def load_base_assets():
    """读本体译文资产 → dict(lang_zh, sfxml_zh, titles, stats)。"""
    lang_zh, sfxml_zh = {}, {}
    rows_count = 0
    for fn in BASE_ASSET_CSVS:
        if not os.path.isfile(fn):
            continue
        with open(fn, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                rows_count += 1
                rid = r.get('id') or ''
                zh = r.get('text_zh') or ''
                if not zh:
                    continue
                if rid.startswith('LANG:'):
                    lang_zh.setdefault(rid, zh)
                elif rid.startswith('SFXML:'):
                    sfxml_zh.setdefault(rid, zh)
    titles = []
    if os.path.isfile(BASE_TITLES_CSV):
        with open(BASE_TITLES_CSV, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                en = r.get('text_en') or ''
                zh = r.get('text_zh') or ''
                if not en:
                    continue
                note = r.get('note') or ''
                m = re.search(r'XML 属性 <([a-z]+)', note)
                titles.append(dict(id=r.get('id') or '', tag=m.group(1) if m else '?',
                                   en=en, zh=zh or ''))
    return dict(lang_zh=lang_zh, sfxml_zh=sfxml_zh, titles=titles,
                rows=rows_count)


# ═════════════════════════ 翻译记忆语料 / 匹配器 ═════════════════════════
def build_tm_corpus(base_en_lang, base_en_sfxml, base_assets,
                    base_txt=None, base_mis_zh=None):
    """构造 TM 语料：[dict(base_id, resource, en, zh, note)]，en/zh 均为引擎文本形态。"""
    corpus = []
    # ① 本体 LANG（英文盘） + 译文资产（CSV）
    #    ★ 保留「译文仍是 ASCII/符号」的条目（如 Ok→确认 是中文、'-'→'-' 是原样）：
    #      它们同样可复用，且能准确反映「不用再译」的工作量。
    for rid in sorted(base_en_lang):
        rec = base_en_lang[rid]
        zcell = base_assets['lang_zh'].get(rid)
        if not zcell:
            continue
        zh = cell_to_engine(zcell)
        corpus.append(dict(base_id=rid, resource='LANG', en=rec['en_text'], zh=zh,
                           note='本体 LANG / ZH141 资产'))
    # ② 本体 SFXML 正文
    for rec in base_en_sfxml:
        zcell = base_assets['sfxml_zh'].get(rec['id'])
        if not zcell:
            continue
        zh = cell_to_engine(zcell)
        corpus.append(dict(base_id=rec['id'], resource='SFXML', en=rec['en_text'],
                           zh=zh, note='本体 SFXML / ZH141 资产'))
    # ③ SFXML 标题（studio/group/item name，资产里直接有 en+zh）
    for rec in base_assets['titles']:
        if rec['zh']:
            corpus.append(dict(base_id=rec['id'], resource='SFXML_TITLE',
                               en=rec['en'], zh=rec['zh'],
                               note='本体特别收录标题 / A 资产'))
    # ④ 本体成品盘 EN_STRINGS.TXT 里被翻译过的 token（额外 TM，10 条）
    if base_txt:
        for tok, rec in sorted(base_txt.items()):
            if rec.get('zh'):
                corpus.append(dict(base_id='TXT:' + tok, resource='STRINGS_TXT',
                                   en=rec['en'], zh=rec['zh'],
                                   note='本体成品盘 TXT 已译值'))
    # ⑤ 本体成品盘 MIS 的 Name/MapName 中文（额外 TM）
    if base_mis_zh:
        for nm, rec in sorted(base_mis_zh.items()):
            for f in ('Name', 'MapName', 'LocationText', 'DateText', 'TimeText',
                      'BriefingText'):
                zh = rec.get(f)
                if zh:
                    corpus.append(dict(base_id='MIS:%s:%s' % (nm, f),
                                       resource='MIS', en=None, zh=zh,
                                       note='本体成品盘 MIS 中文（英文原文由 base_en_mis 配）'))
    return corpus


class TMMatcher(object):
    """精确 / 归一化 / difflib≥0.85 三级匹配；bigram 倒排做候选剪枝。"""

    FUZZY_MIN = 0.85
    FUZZY_HIGH = 0.92

    def __init__(self, corpus):
        self.corpus = corpus
        self.by_exact = collections.defaultdict(list)
        self.by_norm = collections.defaultdict(list)
        self.bigrams = collections.defaultdict(list)
        for i, c in enumerate(corpus):
            if not c.get('en'):
                continue
            self.by_exact[c['en']].append(i)
            nk = normalize_for_match(c['en'])
            self.by_norm[nk].append(i)
            for bg in set(self._bigrams(nk)):
                self.bigrams[bg].append(i)

    @staticmethod
    def _bigrams(s):
        s = ' ' + s + ' '
        return [s[i:i + 2] for i in range(len(s) - 1)]

    def match(self, text, prefer_resource=None):
        """返回 None 或 dict(match_type, ratio, base_id, base_resource, base_en, base_zh, alternatives)。"""
        if not text:
            return None
        hits = self.by_exact.get(text)
        if hits:
            i = self._pick(hits, prefer_resource)
            c = self.corpus[i]
            return dict(match_type='exact', ratio=1.0, base_id=c['base_id'],
                        base_resource=c['resource'], base_en=c.get('en'),
                        base_zh=c['zh'], alternatives=len(hits))
        nk = normalize_for_match(text)
        hits = self.by_norm.get(nk)
        if hits:
            i = self._pick(hits, prefer_resource)
            c = self.corpus[i]
            return dict(match_type='norm', ratio=1.0, base_id=c['base_id'],
                        base_resource=c['resource'], base_en=c.get('en'),
                        base_zh=c['zh'], alternatives=len(hits))
        if len(nk) < 8 or not self.bigrams:
            return None
        scores = collections.Counter()
        for bg in set(self._bigrams(nk)):
            for i in self.bigrams.get(bg, ()):                       # noqa: B905
                scores[i] += 1
        if not scores:
            return None
        top = [i for i, _ in scores.most_common(16)]
        best = None
        for i in top:
            c = self.corpus[i]
            ce = c.get('en') or ''
            if abs(len(ce) - len(text)) > max(12, int(0.45 * len(text))):
                continue
            ratio = difflib.SequenceMatcher(None, nk, normalize_for_match(ce)).ratio()
            if ratio < self.FUZZY_MIN:
                continue
            if best is None or ratio > best[0]:
                best = (ratio, i)
        if best is None:
            return None
        ratio, i = best
        c = self.corpus[i]
        return dict(match_type='fuzzy_high' if ratio >= self.FUZZY_HIGH else 'fuzzy_low',
                    ratio=ratio, base_id=c['base_id'], base_resource=c['resource'],
                    base_en=c.get('en'), base_zh=c['zh'], alternatives=len(top))

    def _pick(self, hits, prefer_resource):
        if prefer_resource:
            for i in hits:
                if self.corpus[i]['resource'] == prefer_resource:
                    return i
        return hits[0]


# 常用音译汉字池（专名音译备用字；用于估算 proper-noun 音译可能需要的字库缺口）
TRANSLITERATION_POOL = (
    '阿埃奥巴拜班邦保贝本比彼得迪蒂杜多厄恩法菲费弗福戈格根古哈海赫亨胡霍基吉加贾杰捷卡凯'
    '坎康考科克肯库奎拉莱赖兰朗劳勒雷里利连列林隆卢鲁路伦罗洛马迈曼梅门蒙米缅明摩莫姆穆纳'
    '奈南内尼涅宁纽努诺欧帕潘培佩皮平珀普奇齐乔切钦丘萨塞森沙尚绍舍申什施史舒斯松苏索塔泰'
    '坦汤唐特提汀通图托瓦万王威韦维温文沃乌西希锡夏谢辛休雅亚扬耶伊因英尤于约泽扎詹兹佐祖'
    '茨芭芭比利亚加尔德斯图尔特雷纳姆托莱多哈瓦那关塔那摩圣地亚哥巴亚莫曼萨尼约马坦萨斯西恩'
    '富戈斯卡马圭奥尔金比那尔德里奥圣克拉拉谢戈德阿维拉格拉玛拉斯图纳斯玛雅贝壳圣萨尔瓦多佩'
    '滕查拉特南戈蒂涅姆芭芭拉詹妮弗华盛顿林肯杰斐逊罗斯福丘吉尔拿破仑希特勒墨索里尼斯大林列'
    '宁马克思恩格斯达尔文牛顿爱因斯坦弗洛伊德荣格尼采康德黑格尔柏拉图亚里士多德苏格拉底荷马'
    '但丁莎士比亚歌德巴尔扎克雨果托尔斯泰陀思妥耶夫斯基契诃夫高尔基普希金莱蒙托夫果戈理'
)


# ═════════════════════════ 用字统计 ═════════════════════════
_NON_TEXT_RE = re.compile(r'\{\{BTN:[0-9A-Fa-f]{4}\}\}|\{p\}|\{br\}|[\x00-\x1f]')


def cjk_chars(text):
    """取文本里的中文/全角等「需要中文字库」的字符（去标记、去 ASCII）。"""
    t = _NON_TEXT_RE.sub('', text or '')
    return [ch for ch in t if ord(ch) >= 0x80]


def count_chars(text):
    return collections.Counter(cjk_chars(text))


def en_visible_len(text):
    """英文可见字符数（去标记/空白）。"""
    t = _NON_TEXT_RE.sub('', text or '')
    t = re.sub(r'\s+', '', t)
    return len(t)


# 术语候选（只用本资料片真实出现的关键词 → 中文术语；用于估算字库缺口）
TERM_GLOSSARY = [
    # (英文关键词（不区分大小写）, 中文术语, 说明)
    ('jungle', '丛林', '资料片标题 Jungle Storm / 丛林地图'),
    ('storm', '风暴', '资料片标题'),
    ('ghost recon', '幽灵行动', '系列名'),
    ('cuba', '古巴', '战役地点'),
    ('colombia', '哥伦比亚', '战役地点'),
    ('haiti', '海地', '战役地点'),
    ('venezuela', '委内瑞拉', '战役地点'),
    ('russia', '俄罗斯', '地图地点'),
    ('lithuania', '立陶宛', '地图地点'),
    ('latvia', '拉脱维亚', '地图地点'),
    ('chechnya', '车臣', '地图地点'),
    ('georgia', '格鲁吉亚', '地图地点'),
    ('ossetia', '奥塞梯', '地图地点'),
    ('abkhazia', '阿布哈兹', '地图地点'),
    ('french guiana', '法属圭亚那', '地图地点'),
    ('caribbean', '加勒比海', '地图地点'),
    ('plantation', '种植园', '地图/任务名'),
    ('airfield', '机场', '地图名'),
    ('stronghold', '据点', '地图名'),
    ('ravine', '峡谷', '地图名'),
    ('creekbed', '河床', '地图名'),
    ('wilderness', '荒野', '地图名'),
    ('hunting lodge', '狩猎小屋', '地图名'),
    ('prison', '监狱', '地图名'),
    ('market', '集市', '地图名'),
    ('village', '村庄', '地图名'),
    ('bridge', '桥梁', '任务名'),
    ('mountain', '山脉', '地图名'),
    ('swamp', '沼泽', '地图名'),
    ('volcano', '火山', '地图名'),
    ('refinery', '炼油厂', '地图名'),
    ('train depot', '列车调度场', '地图名'),
    ('mine', '地雷', '武器/目标'),
    ('claymore', '定向雷', '武器'),
    ('grenade', '手榴弹', '武器'),
    ('rocket', '火箭弹', '武器'),
    ('sniper', '狙击手', '兵种'),
    ('rifleman', '步枪手', '兵种'),
    ('demolitions', '爆破兵', '兵种'),
    ('support', '支援', '兵种'),
    ('hostage', '人质', '任务目标'),
    ('rescue', '营救', '任务目标'),
    ('extraction', '撤离', '任务目标'),
    ('ambush', '伏击', '任务目标'),
    ('recon', '侦察', '任务目标'),
    ('infiltrate', '渗透', '任务目标'),
    ('escort', '护送', '任务目标'),
    ('defend', '防御', '任务目标'),
    ('assault', '突击', '任务目标'),
    ('patrol', '巡逻', '行为'),
    ('night vision', '夜视', '装备'),
    ('binoculars', '望远镜', '装备'),
    ('medical', '医疗', '装备'),
    ('ammunition', '弹药', '装备'),
    ('sensor', '传感器', '装备'),
    ('helicopter', '直升机', '载具'),
    ('armored', '装甲', '载具'),
    ('tank', '坦克', '载具'),
    ('convoy', '车队', '目标'),
    ('radio', '电台', '目标'),
    ('satellite', '卫星', '目标'),
    ('intelligence', '情报', '目标'),
    ('documents', '文件', '目标'),
    ('guerrilla', '游击队', '敌方'),
    ('rebel', '叛军', '敌方'),
    ('cartel', '卡特尔', '敌方'),
    ('civilian', '平民', '第三方'),
    ('marine', '海军陆战队', '友军'),
    ('specialist', '专家', '角色'),
    ('campaign', '战役', '菜单'),
    ('multiplayer', '多人模式', '菜单'),
    ('options', '选项', '菜单'),
    ('credits', '制作人员', '菜单'),
    ('profile', '档案', '菜单'),
    ('briefing', '简报', '界面'),
    ('objective', '目标', '界面'),
    ('waypoint', '航点', '界面'),
    ('reticule', '准星', '界面'),
    ('character', '角色', '界面'),
    ('weapon', '武器', '界面'),
    ('soldier', '士兵', '界面'),
    ('command', '指挥', '界面'),
    ('team', '小队', '界面'),
    # ── 资料片真实地名（LocationText 29 个唯一值）→ 建议译名（译审定稿为准）──
    ('alta magdalena', '上马格达莱纳', '地点'),
    ('buenaventura', '布埃纳文图拉', '地点'),
    ('valle de cauca', '考卡谷', '地点'),
    ('cabo pepe', '佩佩角', '地点'),
    ('isla de la juventud', '青年岛', '地点'),
    ('camaguey', '卡马圭', '地点'),
    ('caqueta', '卡克塔', '地点'),
    ('cayo lucas', '卢卡斯礁', '地点'),
    ('cayos de los inglesitos', '因格莱西托斯礁', '地点'),
    ('choco', '乔科', '地点'),
    ('cienaga grande', '大沼泽', '地点'),
    ('cienfuegos', '西恩富戈斯', '地点'),
    ('ft. bragg', '布拉格堡', '地点'),
    ('ft. drum', '德拉姆堡', '地点'),
    ('holguin', '奥尔金', '地点'),
    ('hot springs', '温泉城', '地点'),
    ('huila', '乌伊拉', '地点'),
    ('isles du salut', '救赎群岛', '地点'),
    ('french guiana', '法属圭亚那', '地点'),
    ('lubana river', '卢巴纳河', '地点'),
    ('latvia', '拉脱维亚', '地点'),
    ('venta', '文塔', '地点'),
    ('lithuania', '立陶宛', '地点'),
    ('meta department', '梅塔省', '地点'),
    ('near tacoma', '塔科马附近', '地点'),
    ('near dimas', '迪马斯附近', '地点'),
    ('northwest cuba', '古巴西北', '地点'),
    ('pinar del rio', '比那尔德里奥', '地点'),
    ('punta tabacal', '蓬塔塔巴卡尔', '地点'),
    ('severodvinsk', '北德文斯克', '地点'),
    ('sierra de los organos', '奥尔加诺斯山脉', '地点'),
    ('south ossetian', '南奥塞梯', '地点'),
    ('tatacoa desert', '塔塔科阿沙漠', '地点'),
    # ── 任务代号（C/J/U 战役）→ 建议译名（意译；译审定稿为准）──
    ('watchful yeoman', '警觉自耕农', '任务代号'),
    ('angel rage', '天使之怒', '任务代号'),
    ('jaguar maze', '美洲豹迷宫', '任务代号'),
    ('hidden spectre', '隐藏幽灵', '任务代号'),
    ('rapid python', '迅捷巨蟒', '任务代号'),
    ('liberty storm', '自由风暴', '任务代号'),
    ('ocean forge', '海洋熔炉', '任务代号'),
    ('righteous archer', '正义弓手', '任务代号'),
    ('jungle prison', '丛林监狱', '任务代号'),
    ('hunting lodge', '狩猎小屋', '地图名'),
    ('totem ground', '图腾之地', '任务代号'),
    ('vapor knife', '蒸汽之刃', '任务代号'),
    ('ocelot desert', '豹猫沙漠', '任务代号'),
    ('ocean hammer', '海洋之锤', '任务代号'),
    ('titan bolt', '泰坦之箭', '任务代号'),
    ('silver spider', '银蛛', '任务代号'),
    ('whisper shadow', '影语', '任务代号'),
    ('eagle clarion', '鹰之号角', '任务代号'),
    ('radio tower', '无线电塔', '地图名'),
    ('abandoned harbor', '废弃港口', '地图名'),
    ('village outskirts', '村庄外围', '地图名'),
    ('railroad junction', '铁路枢纽', '地图名'),
    ('railroad depot', '铁路场站', '地图名'),
    ('winding river', '蜿蜒河流', '地图名'),
    ('obstacle course', '障碍训练场', '训练关名'),
    ('small arms', '轻武器', '训练关名'),
    ('heavy weapons', '重武器', '训练关名'),
    ('machine guns', '机枪', '训练关名'),
    ('anti vehicle', '反装甲', '训练关名'),
    ('polling center', '投票中心', '地图名'),
    ('beach resort', '海滩度假村', '地图名'),
    ('military camp', '军营', '地图名'),
    ('swamp airfield', '沼泽机场', '地图名'),
    ('high sierra', '高山', '地图名'),
    ('island village', '岛屿村庄', '地图名'),
    ('farm day', '农场日', '地图名'),
    ('train wreck', '列车残骸', '地图名'),
]


# ═════════════════════════ 文件输出 ═════════════════════════
def ensure_dirs():
    for d in (SOURCE_DIR, WORK_TEXT):
        os.makedirs(d, exist_ok=True)


def write_csv(path, header, rows):
    """写 utf-8-sig CSV（CRLF 行尾），并硬断言单元格里无真 CR/LF。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, lineterminator='\r\n')
        w.writerow(header)
        for r in rows:
            vals = []
            for k in header:
                v = r.get(k, '')
                if v is None:
                    v = ''
                v = str(v)
                if '\n' in v or '\r' in v:
                    raise ValueError('CSV 单元格含真换行 (%s): %r' % (path, v[:80]))
                vals.append(v)
            w.writerow(vals)


def write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write('\n')


def sha256_file(path, buf=1 << 22):
    import hashlib
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(buf), b''):
            h.update(chunk)
    return h.hexdigest()
