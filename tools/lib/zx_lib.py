# -*- coding: utf-8 -*-
r"""zx_lib.py — 「零缺字成品盘」共享库 (round82)

提供:
  · ISO / IMG 条目读写 (字段语义见 LEAD_ENTRY_FIELDS_VERIFIED.md: u32[0]=名字偏移,
    u32[6]=stored, u32[7]=real, u32[8]=off; 名字区/哈希表一律不动)
  · 图集容器 (GIF 封包流) 的**引擎口径**解/编码 (任意段数, 每段 64 行)
  · 槽位 ↔ 引擎格坐标
  · 硬断言助手

所有函数都是纯计算, 不改盘; 写盘只在 zx_patch_font.py 里做。
"""
import os
import struct
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))
import tcslib                                                        # noqa: E402
import numpy as np                                                   # noqa: E402

SEC = 2048
MENU_LBA = tcslib.MENU_LBA
GR_LBA = tcslib.GR_LBA
TAB_OFF, TAB_STEP = 0x830, 48
W = 1024
SEG_ROWS = 64
SEG_DATA = W // 2 * SEG_ROWS                 # 0x8000 每段像素字节
NCOL, CW, CH = tcslib.NCOL, tcslib.CW, tcslib.CH
OUT = os.path.join(REPO, 'work', 'builds', 'GR_ZH98', 'temp', 'r82')

# 两条活带 (FONT.RES 里被引用的 v 带)
BAND_EN_OLD = (452, 468)
BAND_KB_OLD = (482, 498)
BAND_EN_NEW = (594, 610)                     # Δv = +142
BAND_KB_NEW = (610, 626)                     # Δv = +128
GLYPH_DU, GLYPH_DV = tcslib.GLYPH_DU, tcslib.GLYPH_DV   # 记录矩形 → 采样窗 (+4, +2)


# ═══════════════════════════ 条目表 ═══════════════════════════

def entries(iso, lba):
    """读 IMG 全部条目 (按名字表定条目数; 遇空洞不停)。返回 [dict]"""
    base = lba * SEC
    noff = struct.unpack_from('<I', iso.mm, base + 0x10)[0]
    nend = struct.unpack_from('<I', iso.mm, base + 4)[0]
    names = [x.decode('latin-1') for x in bytes(iso.mm[base + noff:base + nend]).split(b'\x00')
             if x]
    out = []
    for i, nm in enumerate(names):
        r = struct.unpack_from('<12I', iso.mm, base + TAB_OFF + TAB_STEP * i)
        out.append(dict(idx=i, name=nm, raw=list(r), stored=r[6], real=r[7], off=r[8],
                        iso_off=base + r[8]))
    return out


def header(iso, lba):
    base = lba * SEC
    h = struct.unpack_from('<12I', iso.mm, base)
    return dict(size=h[0], names_end=h[1], sector=h[2], tbl_end=h[3], names_start=h[4],
                data_start=h[5], hash_off=h[8], raw=list(h))


def names_region(iso, lba):
    base = lba * SEC
    h = header(iso, lba)
    return bytes(iso.mm[base + h['names_start']:base + h['names_end']])


def hash_region(iso, lba):
    base = lba * SEC
    h = header(iso, lba)
    return bytes(iso.mm[base + h['hash_off']:base + h['hash_off'] + 16384])


# ═══════════════════════════ 图集容器 ═══════════════════════════

def seg_table(container, w=W):
    """→ [(首行, 数据偏移, 字节数)]; 用项目自己的解析器 (尾部 no-op 段会被过滤)。"""
    segs = tcslib.atlas_container_segments(bytes(container), w // 2) or []
    return [s for s in segs if s[2] > 0]


def seg_prefixes(container, w=W):
    """返回每段的 48 B 前缀 (含 PT/A+D/IMAGE 三个 tag) + SSAY 字段偏移。"""
    out = []
    for (row, doff, nb) in seg_table(container, w):
        out.append((row, doff - 48, bytes(container[doff - 48:doff])))
    # 找 SSAY 字段偏移: 各段前缀里唯一按 64 递增的 u32
    p0 = out[0][1]
    cand = []
    for k in range(0, 48 - 4 + 1, 4):
        vals = [struct.unpack_from('<I', c, k)[0] for (_, _, c) in out]
        if vals == [64 * i for i in range(len(vals))]:
            cand.append(k)
    assert len(cand) == 1, 'SSAY 字段定位失败: %s' % cand
    return out, cand[0]


def decode_engine(container, w=W, h=512):
    """→ (img: bool 数组 True=墨, cov: bool 覆盖)。按封包把每段数据放到 TRXPOS 指定行。"""
    img = np.zeros((h, w), dtype=bool)
    cov = np.zeros((h, w), dtype=bool)
    nib = bytes(container)
    for (first_row, doff, nbytes) in seg_table(container, w):
        nrow = min(nbytes // (w // 2), h - first_row)
        if nrow <= 0:
            continue
        a = np.frombuffer(nib[doff:doff + nrow * (w // 2)],
                          dtype=np.uint8).reshape(nrow, w // 2)
        img[first_row:first_row + nrow, 0::2] = (a & 0x0F) == 0
        img[first_row:first_row + nrow, 1::2] = (a >> 4) == 0
        cov[first_row:first_row + nrow, :] = True
    return img, cov


class AtlasWriter:
    """按"每段 64 行自闭合 GIF 包"写一个新容器 (段数 = ceil(h/64))。"""

    def __init__(self, w=W, h=640, prefix_tpl=None, ssa_off=None, trailer=None):
        self.w, self.h = w, h
        self.nseg = (h + SEG_ROWS - 1) // SEG_ROWS
        assert prefix_tpl is not None and ssa_off is not None and trailer is not None
        self.tpl, self.ssa_off, self.trailer = bytearray(prefix_tpl), ssa_off, bytes(trailer)
        # 数据区: 每段 64 行 × (w/2) 字节; 初值 = 0x11 (调色板索引 1 = 透明)
        self.data = bytearray(b'\x11' * (self.nseg * SEG_DATA))
        self.heads = []
        for k in range(self.nseg):
            p = bytearray(self.tpl)
            struct.pack_into('<I', p, self.ssa_off, SEG_ROWS * k)
            self.heads.append(bytes(p))

    def set_segment(self, k, blob):
        """把旧容器第 k 段的数据**逐字节**放进新段的开头 (同段同首行 ⇒ 像素口径不变)。"""
        assert 0 <= k < self.nseg
        assert len(blob) <= SEG_DATA, (k, len(blob))
        self.data[k * SEG_DATA:k * SEG_DATA + len(blob)] = blob

    # ---- 像素视图 ----
    def raw_off(self, x, y):
        k = y // SEG_ROWS
        assert 0 <= k < self.nseg, (x, y)
        return k * SEG_DATA + (y - SEG_ROWS * k) * (self.w // 2) + x // 2

    def set_px(self, x, y, ink, empty=1):
        off = self.raw_off(x, y)
        cur = self.data[off]
        v = 0 if ink else empty
        self.data[off] = ((cur & 0x0F) | (v << 4)) if (x & 1) else ((cur & 0xF0) | v)

    def get_px(self, x, y):
        cur = self.data[self.raw_off(x, y)]
        return ((cur >> 4) if (x & 1) else (cur & 0x0F)) == 0

    def bytes(self):
        out = bytearray()
        for k in range(self.nseg):
            out += self.heads[k]
            out += self.data[k * SEG_DATA:(k + 1) * SEG_DATA]
        out += self.trailer
        return bytes(out)


def container_size(nseg):
    return nseg * 48 + nseg * SEG_DATA + 16


def slot_cell(slot):
    """slot → (x, y) 引擎格左上角 (无相位)。"""
    return tcslib.atlas_cell_xy_engine_view(slot)


def ft_records(blob, body_off=28):
    """→ [(face_name, fld, [(rec_off, (b0,b1,u0,v0,u1,v1))])]  带**展开态偏移**。"""
    p = body_off
    n = struct.unpack_from('<I', blob, 24)[0]
    out = []
    for _ in range(n):
        l = struct.unpack_from('<I', blob, p)[0]
        p += 4
        nm = blob[p:p + l].decode('latin-1')
        p += l
        fld = list(struct.unpack_from('<14I', blob, p))
        p += 56
        nrec = fld[4] * fld[5]
        rows = [(p + 10 * r, struct.unpack_from('<BB4H', blob, p + 10 * r)) for r in range(nrec)]
        p += nrec * 10
        out.append((nm, fld, rows))
    return out, p


def band_windows(recs, band):
    """某 v 带的**采样窗并集** (引擎坐标, 半开区间)。

    接受两种输入: `[(rec_off, rec6)]` 或 `[rec6]`。
    """
    xs, ys = [], []
    for item in recs:
        r = item[1] if (isinstance(item, tuple) and len(item) == 2
                        and isinstance(item[1], tuple)) else item
        b0, b1, u0, v0, u1, v1 = r
        if (v0, v1) != band or u1 <= u0:
            continue
        xs.append((u0 + GLYPH_DU, u1 + GLYPH_DU))
        ys.append((v0 + GLYPH_DV, v1 + GLYPH_DV))
    if not xs:
        return None
    return (min(a for a, _ in xs), max(b for _, b in xs),
            min(a for a, _ in ys), max(b for _, b in ys))


def pad(a, n=78):
    return a + ' ' * max(0, n - len(a))
