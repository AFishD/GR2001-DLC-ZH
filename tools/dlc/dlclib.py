# -*- coding: utf-8 -*-
r"""dlclib.py —— 《幽灵行动：丛林风暴》PS2 (SLUS-20820) 资料片汉化工程核心库。

只依赖标准库。所有「读盘」操作都是只读（mmap）。

盘面事实（2026-10-21 侦察，见 docs/ANALYSIS_ISO.md）：
    ISO        1,229,225,984 B / 600,208 扇区 / 卷标 SLUS_20820
    ELF        SLUS_208.20 @ LBA 296 / 5,319,720 B
    GR.IMG     LBA 61000 / 1,104,291,830 B / 3,111 条目
    条目表     +0x830 起，每项 12×u32 = 48 B；[6]=stored [7]=real [8]=条目内偏移
              名字表 +0x10 起（名字起点 u32 @+0x10，结尾 u32 @+0x4），'\0' 分隔
    载荷       若 stored == real：原样（PAK/RSB 等自带压缩）
               若 stored != real：若干 LZO1X 子流 {u32 clen}{u32 rlen}{payload}
关键资源：
    GR#576  EN_STRINGS.RES      LANG 语言表（67 组 / 2,971 条）
    GR#580  FONT.RES            字库定义（3 face）
    GR#9    COMMON.PAK          内含 new_font_revised 字形图集
    GR#3101 EN_SPECIAL_FEATURE.XML
    GR#349  CAMPAIGN.XML 等 11 个 XML；45 个 *.MIS；766 个 *.ATR
"""
import hashlib
import io
import json
import mmap
import os
import re
import struct
import sys

SEC = 2048

# ───────────────────────────── 盘面常量 ─────────────────────────────
GR_LBA = 61000
TAB_OFF = 0x830
TAB_STEP = 48
ENTRY_COUNT = 3111
ISO_BYTES = 1229225984
ISO_SHA256 = '292f5a6a050e82e05efb5bf9fd5ce3bc12706a8ae57c78b729348a5c80fd0767'
ELF_LBA = 296
ELF_BYTES = 5319720

# 关键资源索引（名字 → 条目号，见 work/analysis/dlc_gr_img_names.txt）
IDX = {
    'ACTION.PAK': 0,
    'COMMON.PAK': 9,
    'MENU.PAK': 25,
    'EN_STRINGS.RES': 576,
    'EN_STRINGS.TXT': 577,
    'DE_STRINGS.RES': 574,
    'ES_STRINGS.RES': 578,
    'FR_STRINGS.RES': 581,
    'IT_STRINGS.RES': 584,
    'FONT.RES': 580,
    'IKE.RES': 583,
    'NTSC_IKE.RES': 586,
    'CAMPAIGN.XML': 349,
    'OPTIONS.XML': 3108,
    'UNLOCKED_HEROES.XML': 3109,
    'UNLOCKED_MISSIONS.XML': 3110,
    'BEST_TIMES.XML': 3097,
    'EN_SPECIAL_FEATURE.XML': 3101,
}

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
DEFAULT_ISO = os.path.join(
    REPO, 'third_party', 'orig', 'ps2',
    "[PS2] Tom Clancy's Ghost Recon - Jungle Storm (U).iso")
DEFAULT_BASE_ISO = os.path.join(
    r'C:\Users\84363\Desktop\Ghost_Recon_2001_Locolization', 'third_party', 'orig', 'ps2',
    "Tom Clancy's Ghost Recon (USA).iso")
DEFAULT_BASE_ZH_ISO = os.path.join(
    r'C:\Users\84363\Desktop\Ghost_Recon_2001_Locolization', 'work', 'builds', 'FINAL',
    "Tom Clancy's Ghost Recon (ZH_CN).iso")


def P(*a):
    print(' '.join(str(x) for x in a), flush=True)


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path, buf=1 << 22):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(buf), b''):
            h.update(chunk)
    return h.hexdigest()


# ───────────────────────────── ISO ─────────────────────────────
class Iso(object):
    """只读 ISO（mmap）。"""

    def __init__(self, path=None):
        self.path = os.path.abspath(path or DEFAULT_ISO)
        self.f = open(self.path, 'rb')
        self.size = os.path.getsize(self.path)
        self.mm = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ)

    def read(self, off, n):
        return bytes(self.mm[off:off + n])

    def sector(self, lba, n=1):
        return self.read(lba * SEC, n * SEC)

    def is_dir_lba(self, lba):
        self.mm.seek(lba * SEC)
        return False

    def close(self):
        self.mm.close()
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- ISO9660 ----
    def pvd(self):
        pvd = self.sector(16)
        assert pvd[0] == 1 and pvd[1:6] == b'CD001', '不是 ISO9660 PVD'
        volid = pvd[40:72].rstrip(b' ').decode('latin-1')
        root = pvd[156:190]
        root_lba = struct.unpack_from('<I', root, 2)[0]
        root_size = struct.unpack_from('<I', root, 10)[0]
        return dict(volume_id=volid, root_lba=root_lba, root_size=root_size,
                    volume_space=struct.unpack_from('<I', pvd, 80)[0])

    def root_entries(self):
        pvd = self.pvd()
        out = []
        off = 0
        data = self.sector(pvd['root_lba'], (pvd['root_size'] + SEC - 1) // SEC)
        while off + 33 <= pvd['root_size']:
            ln = data[off]
            if ln == 0:
                off = (off // SEC + 1) * SEC
                continue
            rec = data[off:off + ln]
            ext = struct.unpack_from('<I', rec, 2)[0]
            size = struct.unpack_from('<I', rec, 10)[0]
            flags = rec[25]
            namelen = rec[32]
            name = rec[33:33 + namelen].decode('latin-1')
            if name not in ('\x00', '\x01'):
                out.append(dict(name=name, lba=ext, size=size, is_dir=bool(flags & 2)))
            off += ln
        return out

    def find_root(self, name):
        for e in self.root_entries():
            if e['name'].split(';')[0] == name:
                return e
        return None

    # ---- 读盘变量 ----
    def elf(self):
        return self.read(ELF_LBA * SEC, ELF_BYTES)

    def system_cnf(self):
        e = self.find_root('SYSTEM.CNF')
        return self.read(e['lba'] * SEC, e['size'])


# ───────────────────────────── IMG 容器 ─────────────────────────────
def img_entries(iso, lba=GR_LBA):
    """解析 IMG 条目表。返回 [dict(idx,name,raw,stored,real,off,iso_off,file_off)]"""
    base = lba * SEC
    noff, nend = struct.unpack_from('<II', iso.mm, base + 0x10)[0], \
        struct.unpack_from('<I', iso.mm, base + 4)[0]
    names = [x.decode('latin-1') for x in
             bytes(iso.mm[base + noff:base + nend]).split(b'\x00') if x]
    out = []
    for i, nm in enumerate(names):
        r = struct.unpack_from('<12I', iso.mm, base + TAB_OFF + TAB_STEP * i)
        out.append(dict(idx=i, name=nm, raw=list(r), stored=r[6], real=r[7],
                        off=r[8], iso_off=base + r[8]))
    return out


def img_find(entries, name, nth=0):
    hits = [e for e in entries if e['name'].upper() == name.upper()]
    if not hits:
        raise KeyError('IMG 里找不到 %s' % name)
    return hits[nth]


def img_filesize(iso, lba=GR_LBA):
    """GR.IMG 在 ISO 上的真实文件长度（ISO9660 根目录里登记值）。"""
    e = iso.find_root('GR.IMG')
    return e['size']


def img_last_end(entries):
    return max(e['off'] + e['stored'] for e in entries)


# ───────────────────────────── LZO 子流 ─────────────────────────────
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))
from lz77_decode import lzo1x_decompress            # noqa: E402
from lzo1x_c import compress as lzo_compress        # noqa: E402


def lzo_subs(raw):
    """顺序解析 {u32 clen}{u32 rlen}{comp} 子流表。返回 [(dec, clen, rlen, hdr_off)]

    ★ 引擎的两种子流形态（实证：CP03_PRISON.MIS 的第二个子流 clen==rlen==969，
      payload 是 ASCII 数据而不是 LZO 流）：
        · clen != rlen → LZO1X 压缩流，解压到 rlen 字节
        · clen == rlen → **原样存储**（引擎直接拷 rlen 字节，不解压）
    """
    subs, p = [], 0
    while p + 8 <= len(raw):
        L, S = struct.unpack_from('<II', raw, p)
        if L == 0 or p + 8 + L > len(raw):
            break
        if L == S:
            subs.append((bytes(raw[p + 8:p + 8 + L]), L, S, p))
            p += 8 + L
            continue
        try:
            dd, err, _ = lzo1x_decompress(raw[p + 8:p + 8 + L], out_size=S)
        except Exception:                                      # noqa: BLE001
            break
        if err is not None or len(dd) != S:
            break
        subs.append((bytes(dd), L, S, p))
        p += 8 + L
    return subs


def lzo_pack(chunks):
    """[(payload, rlen)] → 帧字节，每块回环自证。

    ★ clen == rlen 表示「原样存储」（引擎口径，见 lzo_subs）；压缩后不小于原文时
      直接存原文，保证回读逐字节一致。
    """
    out = bytearray()
    for c, S in chunks:
        assert len(c) == S
        cc = lzo_compress(c, level=7, use_m1=True, use_m4=True)
        if len(cc) >= S:
            out += struct.pack('<II', S, S) + c
            continue
        back, err, _ = lzo1x_decompress(cc, out_size=S)
        assert err is None and back == c, 'LZO 子流回环失败 (rlen=%d)' % S
        out += struct.pack('<II', len(cc), S) + cc
    return bytes(out)


def entry_payload(iso, e, entries=None):
    """读一个条目的 payload。

    返回 dict(kind='raw'|'lzo', packed=盘上字节, blob=展开后字节, subs=[...])
    · stored == real  → raw（PAK/RSB 等，自带内部压缩）
    · stored != real  → LZO 子流展开
    """
    packed = iso.read(e['iso_off'], e['stored'])
    if e['stored'] == e['real']:
        return dict(kind='raw', packed=packed, blob=packed, subs=[])
    subs = lzo_subs(packed)
    blob = b''.join(s[0] for s in subs)
    if len(blob) != e['real']:
        raise ValueError('%s: LZO 展开 %d != real %d' % (e['name'], len(blob), e['real']))
    return dict(kind='lzo', packed=packed, blob=blob, subs=subs)


def load_resource(iso, entries, name_or_idx):
    e = (entries[name_or_idx] if isinstance(name_or_idx, int)
         else img_find(entries, name_or_idx))
    return e, entry_payload(iso, e)


# ───────────────────────────── LANG 语言表 ─────────────────────────────
class LangEntry(object):
    __slots__ = ('g', 'i', 'data_off', 'length', 'attr_off', 'attr', 'data')

    def __init__(self, g, i, data_off, length, attr_off, data, attr=0):
        self.g, self.i = g, i
        self.data_off, self.length, self.attr_off, self.data = \
            data_off, length, attr_off, data
        self.attr = attr

    def __repr__(self):
        return 'LangEntry(g=%d,i=%d,len=%d,%r)' % (self.g, self.i, self.length,
                                                   self.data[:24])


def parse_lang(blob):
    """解析语言表。返回 (entries, used_end)。

    布局：{u32 ngroups}
          组 1: {u32 count} + count × ({u32 len}{data}{u16 attr})
          组 k≥2: {u32 0} + {u32 count} + count × ({u32 len}{data}{u16 attr})
    """
    ng = struct.unpack_from('<I', blob, 0)[0]
    p = 4
    ents = []
    for g in range(ng):
        if g:
            p += 4
        cnt = struct.unpack_from('<I', blob, p)[0]
        p += 4
        for i in range(cnt):
            ln = struct.unpack_from('<I', blob, p)[0]
            p += 4
            data = bytes(blob[p:p + ln])
            p += ln
            attr_off = p
            attr = struct.unpack_from('<H', blob, p)[0]
            p += 2
            ents.append(LangEntry(g, i, p - ln - 2, ln, attr_off, data, attr))
    return ents, p


def lang_entry_span(blob, e):
    return e.data_off - 4, e.attr_off + 2


def build_lang(entries):
    """按 (g,i) 顺序重建 LANG blob（保留每条 attr 两字节）。"""
    groups = {}
    for e in entries:
        groups.setdefault(e.g, []).append(e)
    out = bytearray()
    out += struct.pack('<I', len(groups))
    for g in range(len(groups)):
        ge = groups[g]
        if g:
            out += struct.pack('<I', 0)
        out += struct.pack('<I', len(ge))
        for e in ge:
            out += struct.pack('<I', len(e.data))
            out += e.data
            out += struct.pack('<H', e.attr & 0xFFFF)
    return bytes(out)


def lang_replace(blob, repl):
    """repl = {(g,i): new_bytes}；返回新 LANG blob（未列的条目原样保留）。"""
    ents, used = parse_lang(blob)
    for e in ents:
        k = (e.g, e.i)
        if k in repl:
            e.data = bytes(repl[k])
            e.length = len(e.data)
    return build_lang(ents)


# ───────────────────────────── LZO 资源帧 ─────────────────────────────
CHUNK = 16384


def lzo_frame(blob):
    """把资源 blob 打成引擎的 LZO 子流帧：按 16,384 B 切块（末块可短）。

    实证：原盘全部 1,197 个 LZO 资源的子流 rlen 都严格是 [16384]*k + [rest]。
    """
    blob = bytes(blob)
    chunks = []
    for off in range(0, len(blob), CHUNK):
        part = blob[off:off + CHUNK]
        chunks.append((part, len(part)))
    return lzo_pack(chunks)


def lzo_join(subs):
    return b''.join(s[0] for s in subs)


# ───────────────────────────── SFXML ─────────────────────────────
TEXT_RE = re.compile(rb'<text>([^<]*)</text>')


def parse_sfxml(xml):
    """返回 [(idx(1-based), body_off, body_len, body)]"""
    out = []
    for k, m in enumerate(TEXT_RE.finditer(xml), start=1):
        out.append((k, m.start(1), m.end(1) - m.start(1), bytes(m.group(1))))
    return out


def splice(blob, edits):
    """edits = [(start, end, newbytes)]，区间不重叠；返回新 bytes。"""
    if not edits:
        return blob
    edits = sorted(edits, key=lambda x: x[0])
    out, pos = bytearray(), 0
    for a, b, nb in edits:
        assert a >= pos, '编辑区间重叠: %d < %d' % (a, pos)
        out += blob[pos:a] + nb
        pos = b
    out += blob[pos:]
    return bytes(out)


# ───────────────────────────── MIS / XML（看着二进制，其实是 XML） ─────────────────────────────
def xml_payload(blob):
    """MIS/ATR/XML 条目 payload 常是 XML（截到最后一个 '>'）。"""
    return blob


def xml_tag_text(blob, tag):
    """取第一个 <tag>...</tag> 的正文（bytes）。"""
    m = re.search(b'<' + tag.encode('ascii') + b'>([^<]*)</' + tag.encode('ascii') + b'>', blob)
    return m.group(1) if m else None


# ───────────────────────────── 英文原文解码 / 字符集 ─────────────────────────────
_TCS = None


def tcslib():
    """惰性加载继承自本体工程的 tcslib（英文 cp1252 解码 / Charset 编码器）。"""
    global _TCS
    if _TCS is None:
        import tcslib as _T                                    # noqa: PLC0415
        _TCS = _T
    return _TCS


def decode_en(data, where='?'):
    """英文基线盘正文 → 可读文本（Windows-1252 + {{BTN:XXXX}} 图标标记）。"""
    return tcslib().decode_en(data, where)


def charset(path=None):
    return tcslib().Charset(path or os.path.join(REPO, 'assets', 'charset',
                                                 'charset_compiled_zh16.json'))


# ───────────────────────────── PAK 记录 ─────────────────────────────
def parse_pak_records(pak):
    """解析 PAK 记录链。返回 [(name, psm, w, h, clut_size, px_size, px_off)]"""
    out, p = [], 0
    while p + 8 <= len(pak):
        ty, nl = struct.unpack_from('<II', pak, p)
        if ty == 0x63 or nl > 64:
            break
        nm = pak[p + 8:p + 8 + nl].decode('latin-1')
        q = p + 8 + nl
        psm, w, h, clut = struct.unpack_from('<4I', pak, q)
        px = struct.unpack_from('<I', pak, q + 16 + clut)[0]
        out.append(dict(name=nm, psm=psm, w=w, h=h, clut=clut, px=px,
                        px_off=q + 20 + clut, hdr_off=p, rec_end=q + 20 + clut + px))
        p = q + 20 + clut + px
    return out


# ───────────────────────────── 自查 ─────────────────────────────
def selfcheck(iso_path=None, verbose=True):
    """快速自检：尺寸 / sha256 / 卷标 / ELF / 条目数。"""
    iso = Iso(iso_path)
    ok = True

    def chk(cond, msg):
        nonlocal ok
        if verbose:
            P(('  ok   ' if cond else '  FAIL ') + msg)
        ok = ok and bool(cond)

    chk(iso.size == ISO_BYTES, 'ISO 尺寸 %d' % iso.size)
    if iso_path is None or os.path.abspath(iso_path) == DEFAULT_ISO:
        h = sha256_file(iso.path)
        chk(h == ISO_SHA256, 'ISO sha256 %s' % h)
    pvd = iso.pvd()
    chk(pvd['volume_id'] == 'SLUS_20820', '卷标 %s' % pvd['volume_id'])
    chk(pvd['volume_space'] * SEC == iso.size, 'volume_space %d' % pvd['volume_space'])
    ents = img_entries(iso)
    chk(len(ents) == ENTRY_COUNT, 'GR.IMG 条目数 %d' % len(ents))
    chk(ents[0]['name'] == 'ACTION.PAK', 'GR#0 = %s' % ents[0]['name'])
    chk(ents[576]['name'] == 'EN_STRINGS.RES', 'GR#576 = %s' % ents[576]['name'])
    chk(ents[580]['name'] == 'FONT.RES', 'GR#580 = %s' % ents[580]['name'])
    chk(ents[3101]['name'] == 'EN_SPECIAL_FEATURE.XML', 'GR#3101 = %s' % ents[3101]['name'])
    chk(iso.find_root('SLUS_208.20')['size'] == ELF_BYTES, 'ELF 尺寸')
    iso.close()
    return ok


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='dlclib 自检')
    ap.add_argument('--iso')
    a = ap.parse_args()
    ok = selfcheck(a.iso)
    P('SELFCHECK', 'OK' if ok else 'FAIL')
    sys.exit(0 if ok else 1)
