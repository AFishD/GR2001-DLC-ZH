# -*- coding: utf-8 -*-
r"""fontlib.py — 《幽灵行动：丛林风暴》PS2 汉化「字库/图集」公共库（只读分析 + 字节构造）。

本模块是 task-3（字库/图集工程师）的落地实现，职责：
  · 只读打开 ISO（mmap），解析 ISO9660 / GR.IMG 条目表 / PAK 记录链 / FONT.RES / 字库图集容器；
  · 图集容器 = **GIF 封包流**：按包（PT + A+D TRXPOS + IMAGE tag）还原「引擎看到的图」，
    读写一律按**数据区**偏移，绝不把 48B 包头当像素；
  · 构造新 PAK / 新 FONT.RES / 新 ISO（方案 B：1024×644 PSMT4，2350 槽）；
  · 全部「写」操作都是**新文件**，输入盘只读。

口径来源（本体成品 FINAL ISO 实测，见 docs/ANALYSIS_FONT.md）：
  图集  : psm=0x14(PSMT4), 1024×644, clut=1040(ZH 形状)/80(DLC 原生 16 色形状), px=329,744；
          容器 = 11 段 GIF 流（每段 48B 头 + 32,768B 数据，末段 1,520B）+ 末尾 16B 空 tag = 329,744B；
          11 段 SSAY = 0,64,...,640 ⇒ 引擎图 = 连续行，无行相位。
  网格  : slot=(lead-0xA1)*94+(trail-0xA1)；lead∈[0xA1,0xBA), trail∈[0xA1,0xFE]；容量 2350；
          NCOL=64, CW=CH=16, Y0=3, SKIP_ROW=12, SKIP_ROWS=2；
          row=slot//64, col=slot%64；x=16*col；y=3+16*(row + 2*[row>=12])。
  FONT.RES : {u32 nameLen}{name}{u32 nfaces} 每面 {u32 nameLen}{name}{14×u32}{nrec×10B}，nrec=fld[4]*fld[5]；
          末尾尾部样式表 {u32 count}{count×entry}。本体英文 7,222B(8 条样式)，DLC 7,466B(15 条样式)。
  GR.IMG : 条目表 +0x830，每项 12×u32 = 48B；[6]=stored [7]=real [8]=条目内偏移；
          头部 +0x0 = GR.IMG 声明总大小 == ISO9660 根目录里 GR.IMG 的 size（= max(off+stored) + 0x10000）。
"""
import hashlib
import json
import mmap
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))

from lz77_decode import lzo1x_decompress            # noqa: E402
from lzo1x_c import compress as lzo_compress        # noqa: E402

SEC = 2048
GR_LBA = 61000                 # DLC GR.IMG
MENU_LBA_BASE = 776286         # 本体 MENU.IMG
GR_LBA_BASE = 19175            # 本体 GR.IMG
TAB_OFF = 0x830
TAB_STEP = 48
IMG_PAD = 0x10000              # GR.IMG 声明大小 = max(off+stored) + 0x10000（本体/资料片两盘同构，实测）

DLC_ISO = os.path.join(REPO, 'third_party', 'orig', 'ps2',
                       "[PS2] Tom Clancy's Ghost Recon - Jungle Storm (U).iso")
BASE_ZH_ISO = os.path.join(
    r'C:\Users\84363\Desktop\Ghost_Recon_2001_Locolization', 'work', 'builds', 'FINAL',
    "Tom Clancy's Ghost Recon (ZH_CN).iso")
BASE_EN_ISO = os.path.join(
    r'C:\Users\84363\Desktop\Ghost_Recon_2001_Locolization', 'third_party', 'orig', 'ps2',
    "Tom Clancy's Ghost Recon (USA).iso")
SEED_DIR = os.path.join(REPO, 'third_party', 'ref', 'zh_font_seed')
CHARSET = os.path.join(REPO, 'assets', 'charset', 'charset_compiled_zh16.json')
TTF = os.path.join(REPO, 'third_party', 'fonts', '方正像素16.ttf')

# ── 网格几何（K2 / 本体成品实测；elf-analyst 已从 ELF 立即数逐字复核） ──
NCOL, CW, CH = 64, 16, 16
GRID_Y0, GRID_SKIP_ROW, GRID_SKIP_ROWS = 3, 12, 2
LEAD_LO, LEAD_HI = 0xA1, 0xBA
TRAIL_LO, TRAIL_HI = 0xA1, 0xFE
PAIR_CAP = (LEAD_HI - LEAD_LO) * (TRAIL_HI - TRAIL_LO + 1)          # 2350
ATLAS_W, ATLAS_H, ATLAS_PSM = 1024, 644, 0x14
ATLAS_PX = ATLAS_W * ATLAS_H // 2 + 16                              # 329,744
ATLAS_SEG_ROWS = 64
ATLAS_PREFIX = 48                                                   # PT16 + A+D16 + IMAGE tag16
ATLAS_TAIL_TAG = 16
FONT_NAME = b'new_font_revised'
FT_NREC_BASE = 224


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


def align_up(v, a):
    return (v + a - 1) // a * a


# ═══════════════════════════ ISO（只读 mmap） ═══════════════════════════
class Iso(object):
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.f = open(self.path, 'rb')
        self.size = os.path.getsize(self.path)
        self.mm = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ)

    def read(self, off, n):
        return bytes(self.mm[off:off + n])

    def sector(self, lba, n=1):
        return self.read(lba * SEC, n * SEC)

    def close(self):
        self.mm.close()
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- ISO9660 ----
    def pvd(self):
        p = self.sector(16)
        assert p[0] == 1 and p[1:6] == b'CD001', '不是 ISO9660 PVD: %r' % p[:8]
        return dict(
            volume_id=p[40:72].rstrip(b' ').decode('latin-1'),
            volume_space_le=struct.unpack_from('<I', p, 80)[0],
            volume_space_be=struct.unpack_from('>I', p, 84)[0],
            root_record_off=16 * SEC + 156,
            root_lba=struct.unpack_from('<I', p, 158)[0],
            root_size=struct.unpack_from('<I', p, 166)[0],
            pvd_off=16 * SEC)

    def root_entries(self):
        """解析根目录，返回 [dict(name,lba,size,rec_off,is_dir)]（rec_off = ISO 绝对偏移）。"""
        pvd = self.pvd()
        nsec = (pvd['root_size'] + SEC - 1) // SEC
        base = pvd['root_lba'] * SEC
        data = self.read(base, nsec * SEC)
        out, off = [], 0
        while off + 33 <= pvd['root_size']:
            ln = data[off]
            if ln == 0:
                off = (off // SEC + 1) * SEC
                continue
            rec = data[off:off + ln]
            ext = struct.unpack_from('<I', rec, 2)[0]
            size = struct.unpack_from('<I', rec, 10)[0]
            flags = rec[25]
            nl = rec[32]
            name = rec[33:33 + nl].decode('latin-1')
            if name not in ('\x00', '\x01'):
                out.append(dict(name=name, lba=ext, size=size, is_dir=bool(flags & 2),
                                rec_off=base + off, rec_len=ln))
            off += ln
        return out

    def find_root(self, name):
        for e in self.root_entries():
            if e['name'].split(';')[0] == name:
                return e
        return None


# ═══════════════════════════ GR.IMG 条目表 ═══════════════════════════
def img_header(iso, lba=GR_LBA):
    base = lba * SEC
    h = struct.unpack_from('<12I', iso.mm, base)
    return dict(total=h[0], names_end=h[1], block=h[2], tab_end=h[3],
                names_off=h[4], first_off=h[5], version=h[6], aux_off=h[8],
                base=base)


def img_entries(iso, lba=GR_LBA):
    base = lba * SEC
    h = img_header(iso, lba)
    noff, nend = h['names_off'], h['names_end']
    names = [x.decode('latin-1') for x in
             bytes(iso.mm[base + noff:base + nend]).split(b'\x00') if x]
    out = []
    for i, nm in enumerate(names):
        r = struct.unpack_from('<12I', iso.mm, base + TAB_OFF + TAB_STEP * i)
        out.append(dict(idx=i, name=nm, raw=list(r), stored=r[6], real=r[7],
                        off=r[8], iso_off=base + r[8], tab_off=base + TAB_OFF + TAB_STEP * i))
    return out


def img_last_end(entries):
    return max(e['off'] + e['stored'] for e in entries)


def img_consistent(iso, entries, lba=GR_LBA):
    """自检：header[0] == 根目录里 GR.IMG 的 size == max(off+stored)+0x10000。"""
    h = img_header(iso, lba)
    root = iso.find_root('GR.IMG')
    last = img_last_end(entries)
    return dict(header_total=h['total'], root_size=root['size'] if root else None,
                last_end=last, pad=h['total'] - last,
                ok=(root is not None and h['total'] == root['size'] == last + IMG_PAD))


# ═══════════════════════════ LZO 帧（FONT.RES 等） ═══════════════════════════
def frame_decode(raw):
    """顺序解 {u32 clen}{u32 rlen}{comp} 帧链；返回 (blob, frames, consumed)。

    ★ 本体成品的 FONT.RES 存的是「1 帧 + 尾部 0 填充」：只解第一帧就够，剩余零字节是槽内填充。
    """
    p, out, frames = 0, bytearray(), []
    while p + 8 <= len(raw):
        L, S = struct.unpack_from('<II', raw, p)
        if L == 0 or L > len(raw) - p - 8:
            break
        try:
            d, err, _ = lzo1x_decompress(raw[p + 8:p + 8 + L], out_size=S)
        except Exception:                                   # noqa: BLE001
            break
        if err is not None or len(d) != S:
            break
        frames.append(dict(clen=L, rlen=S, off=p))
        out += d
        p += 8 + L
    return bytes(out), frames, p


def frame_pack(blobs):
    """[(blob, rlen)] → 帧字节（自带回环自证）。"""
    out = bytearray()
    for c, S in blobs:
        cc = lzo_compress(c, level=7, use_m1=True, use_m4=True)
        back, err, _ = lzo1x_decompress(cc, out_size=S)
        assert err is None and back == c, 'LZO 子流回环失败 (rlen=%d)' % S
        out += struct.pack('<II', len(cc), S) + cc
    return bytes(out)


# ═══════════════════════════ PAK 记录链 ═══════════════════════════
def pak_parse(pak):
    """解析 PAK 记录链。返回 list[dict(name,psm,w,h,clut,px,px_off,hdr_off,rec_end,
    clut_off,clut_bytes,px_size_field)]；停在哨兵 type=0x63。"""
    out, p = [], 0
    while p + 8 <= len(pak):
        ty, nl = struct.unpack_from('<II', pak, p)
        if ty == 0x63 or nl > 64:
            break
        nm = pak[p + 8:p + 8 + nl].decode('latin-1')
        q = p + 8 + nl
        psm, w, h, clut = struct.unpack_from('<4I', pak, q)
        clut_off = q + 16                                  # 真 CLUT 块起点（16B 之后）
        px_size_field = struct.unpack_from('<I', pak, clut_off + clut)[0]
        px_off = clut_off + clut + 4
        out.append(dict(ty=ty, name=nm, psm=psm, w=w, h=h, clut=clut,
                        px=px_size_field, px_off=px_off, hdr_off=p,
                        rec_end=px_off + px_size_field,
                        clut_off=clut_off,
                        clut_bytes=bytes(pak[clut_off:clut_off + clut])))
        p = px_off + px_size_field
    return out


def pak_find(recs, name):
    for i, r in enumerate(recs):
        if r['name'] == name:
            return i, r
    raise KeyError('PAK 里找不到 %s' % name)


def pak_sentinel_off(pak):
    """最后一个记录之后（哨兵 type=0x63）的偏移。"""
    recs = pak_parse(pak)
    return recs[-1]['rec_end'] if recs else 0


# ═══════════════════════════ FONT.RES ═══════════════════════════
def ft_parse(blob):
    """解析展开态 FONT.RES。

    返回 dict(magic, nfaces, faces=[dict(name,fld,recs,nrec,at)], parsed_end, tail)。
    rec = (b0, b1=advance, u0, v0, u1, v1)
    """
    nl = struct.unpack_from('<I', blob, 0)[0]
    magic = blob[4:4 + nl].decode('latin-1')
    p = 4 + nl
    nf = struct.unpack_from('<I', blob, p)[0]
    p += 4
    faces = []
    for _f in range(nf):
        fl = struct.unpack_from('<I', blob, p)[0]
        p += 4
        fn = blob[p:p + fl].decode('latin-1')
        p += fl
        fld = list(struct.unpack_from('<14I', blob, p))
        p += 56
        nrec = fld[4] * fld[5]
        recs = [list(struct.unpack_from('<BB4H', blob, p + 10 * r)) for r in range(nrec)]
        p += nrec * 10
        faces.append(dict(name=fn, fld=fld, nrec=nrec, recs=recs, at=p - nrec * 10))
    return dict(magic=magic, nfaces=nf, faces=faces, parsed_end=p,
                tail=bytes(blob[p:]), tail_len=len(blob) - p)


def ft_build(magic, faces, tail):
    """按 ft_parse 的口径重建 FONT.RES 展开态字节。faces 元素需含 name/fld/recs。"""
    m = magic.encode('latin-1')
    out = bytearray(struct.pack('<I', len(m)) + m + struct.pack('<I', len(faces)))
    for f in faces:
        nm = f['name'].encode('latin-1')
        out += struct.pack('<I', len(nm)) + nm + struct.pack('<14I', *f['fld'])
        for r in f['recs']:
            out += struct.pack('<BB4H', *r)
    out += tail
    return bytes(out)


def ft_merge_for_dlc(zh_blob, dlc_blob):
    """把**本体中文** FONT.RES 合成为资料片可用的展开态 FONT.RES。

    规则（见 docs/ANALYSIS_FONT.md §FONT.RES）：
      · large/default 两面原样用中文版（各 224 条：ASCII 8×16 带 + 单字节带）；
      · huge 面中文版只有 96 条（code 0x20..0x7F 的 ASCII），**扩展回 224 条**：
        96..223 填退化记录 (0,0,0,0)，并令 fld[5]=14 ⇒ nrec=fld[4]*fld[5]=16*14=224
        （保持资料片原 FONT.RES 的 224 条/face 声明，不改变 loader 的 count/base 假设）；
      · 尾部（样式表）用**资料片原盘的 522B（15 条）**：资料片引擎可能引用 index≥8 的样式，
        不能用中文版的 278B（8 条）；本体英文盘也只有 8 条 ⇒ 这就是 7,466 vs 7,222 的 244B 差额。
    合成后长度 == 资料片原 blob 长度（7,466B）。
    """
    z = ft_parse(zh_blob)
    d = ft_parse(dlc_blob)
    faces = []
    for f in z['faces']:
        fld = list(f['fld'])
        recs = [list(r) for r in f['recs']]
        if f['name'] == 'huge':
            fld[5] = 14                                  # 16*14 = 224
            recs = recs + [[0, 0, 0, 0, 0, 0]] * (224 - len(recs))
        faces.append(dict(name=f['name'], fld=fld, recs=recs))
    out = ft_build(z['magic'], faces, d['tail'])
    assert len(out) == len(dlc_blob), (len(out), len(dlc_blob))
    out = restore_face_metrics(out, dlc_blob)
    chk = ft_parse(out)
    assert [f['nrec'] for f in chk['faces']] == [224, 224, 224], [f['nrec'] for f in chk['faces']]
    assert chk['tail'] == d['tail'][:0] + out[chk['parsed_end']:]   # 尾部内容允许被 A‴ 规整
    return out


def restore_face_metrics(blob, dlc_blob):
    """A‴ 度量恢复（v8，见 docs/ANALYSIS_FONT.md §14 / MOD_GUIDE §2.3）。

    背景：A′/A″ 把 fld[1] 统一成 16、style f5/f6 全归 1.0，虽然让字形 quad=16px 不再
    拉伸，但**引擎的 19 处竖向排版调用者（CharHeight getter 0x21A440）也一起读到 16**
    ⇒ 按钮/标题/帮助条等 UI 的行盒高度与 EN 原盘不一致，整屏文字上下错位。

    本函数把「排版口径」还原成资料片原版（EN）：
      · 三个 face 的 fld[1] 恢复 EN 值（large 26 / default 26 / huge 42）；
      · 15 条 style 的 f5/f6 **保持 1.0**（横向布局与 v7 完全一致、不引入宽度回归；
        CharHeight = fld[1]×1.0 ⇒ 布局行盒 = EN 的 26/26/42）。
    字形仍为 16px —— 由 ELF 侧 DrawString quad 高度钉 16 + 居中锚点 cave（VA 0x575D04）负责：
    y1 = y + (CH−16)/2、y2 = y1+16 ⇒ 居中对齐族净位移 0、底对齐族 −5px、常量/顶对齐族 +5px。
    幂等；长度与 EN 原 blob 相同（7,466B）。
    """
    buf = bytearray(blob)
    info = ft_parse(bytes(buf))
    d = ft_parse(dlc_blob)
    for f, fd in zip(info['faces'], d['faces']):
        hdr = f['at'] - 56                              # 14×u32 face 头起点
        struct.pack_into('<I', buf, hdr + 4, fd['fld'][1])   # fld[1] = EN 原值
    # 尾部 style：f5/f6 一律 1.0（横向口径与 v7 一致，高度口径由 fld[1] 决定）
    tail = info['parsed_end']
    ns = struct.unpack_from('<I', buf, tail)[0]
    q = tail + 4
    for _ in range(ns):
        nl = struct.unpack_from('<I', buf, q)[0]
        p = q + 4 + nl
        struct.pack_into('<2f', buf, p + 17, 1.0, 1.0)
        q = p + 17 + 8
    return bytes(buf)


def normalize_face_metrics(blob):
    """A′ 度量规整（v3 渲染修复，见 docs/ANALYSIS_ELF.md §12 / MOD_GUIDE §2.3）。

    根因：本工程把各 face 的 FT 记录全部重写成 16px 高（ASCII 8x16、中文 16x16），
    但本体中文 FONT.RES 的 face 头 fld[1]（= 引擎 CharHeight 基数，def+0x0C）仍是
    large/default = 26，配合 style 的高度缩放 f6（#5=1.64 / #7=1.63 / #12=1.2）
    会让 quad 高 26*1.64≈42.6 去映射 16px 字形 ⇒ 标题纵向拉伸 2.6x 并越界裁剪。
    修复（纯数据、8+24 字节）：
      · 三个 face 的 fld[1] 统一 = 16（CharHeight 基数 == 图集格高）；
      · 所有 f5/f6 > 1 的 style 归 1.0（pair CharWidth 恒 16 不乘 f5，归 1 才与 ASCII 一致）。
    不动 fld[2]/[3]（中英 UI 布局字段，绘制路径不读）。幂等。
    """
    buf = bytearray(blob)
    info = ft_parse(bytes(buf))
    n = 0
    for f in info['faces']:
        hdr = f['at'] - 56                         # 14×u32 face 头起点
        struct.pack_into('<I', buf, hdr + 4, 16)   # fld[1] = 16
        n += 1
    tail_off = info['parsed_end']
    ns = struct.unpack_from('<I', buf, tail_off)[0]
    q = tail_off + 4
    fixed = 0
    for i in range(ns):
        nl = struct.unpack_from('<I', buf, q)[0]
        nm = bytes(buf[q + 4:q + 4 + nl])
        p = q + 4 + nl
        q = p + 4 * 4 + 1
        f5, f6 = struct.unpack_from('<2f', buf, q)
        # 全部 style 归 1.0（不止 >1）：ASCII 的 quad 尺寸走 FT 记录（恒 16px），
        # 而 pair 的 quad 尺寸 = CharHeight = fld[1]×f6、宽度 = 16 恒不乘 f5；
        # f5/f6 ≠ 1 时 ASCII 与中文的"大小/垂直位置"不一致 ⇒ 混排行明显上下偏移。
        struct.pack_into('<2f', buf, q, 1.0, 1.0)
        fixed += 1
        q += 8
    assert q <= len(buf), 'style 表越界'
    return bytes(buf)


# ═══════════════════════════ 图集容器（GIF 封包流） ═══════════════════════════
def atlas_packets(cont, stride):
    """把像素容器按 GIF 封包语法切开（只读、不猜）。

    返回 list[dict(kind='ad'|'image'|'noop'|'unknown', ...)]：
      ad    : PT(nloop=1,nreg=1) 之后的 A+D qword（含 TRXPOS: ssax/ssay）
      image : IMAGE tag（nloop qwords）+ 数据区 [doff, doff+nloop*16)
    """
    packets, o, trx = [], 0, 0
    while o + 16 <= len(cont):
        w0, w1 = struct.unpack_from('<II', cont, o)
        nloop, eop, flg = w0 & 0x7FFF, (w0 >> 15) & 1, (w1 >> 26) & 3
        nreg = (((w1 >> 28) - 1) & 0xF) + 1
        pk = dict(off=o, w0=w0, w1=w1, nloop=nloop, eop=eop, flg=flg, nreg=nreg)
        if flg in (0, 1):                                   # PACKED（A+D）
            if nloop == 0:
                pk['kind'] = 'noop'
                packets.append(pk)
                break
            if nloop == 1 and nreg == 1:
                words = struct.unpack_from('<4I', cont, o + 16)
                pk.update(kind='ad', ad=list(words), ssax=words[0], ssay=words[1])
                packets.append(pk)
                trx = words[1]
                o += 16 + nloop * 16 * nreg
                continue
            pk['kind'] = 'unknown'
            packets.append(pk)
            break
        pk.update(kind='image', bytes=nloop * 16, first_row=trx, doff=o + 16)
        packets.append(pk)
        o += 16 + nloop * 16
        if eop and nloop == 0:
            break
    return packets


def atlas_segments(cont, stride):
    """容器 → [(first_row, data_off, nbytes)]（只取 IMAGE 数据区；0 长度包剔除）。"""
    return [(p['first_row'], p['doff'], p['bytes'])
            for p in atlas_packets(cont, stride) if p['kind'] == 'image' and p['bytes']]


def atlas_decode(cont, w, h, psm, segs=None):
    """容器 → **引擎看到的图**（PSMT 索引矩阵 uint8[h,w]）。

    PSMT4: 每字节 2 texel，偶 x = 低 nibble、奇 x = 高 nibble。
    PSMT8: 每字节 1 texel。
    """
    stride = w // 2 if psm == 0x14 else w
    if segs is None:
        segs = atlas_segments(cont, stride)
    tex = np.zeros((h, w), dtype=np.uint8)
    for (r0, doff, nb) in segs:
        nrow = nb // stride
        rem = nb % stride
        if nrow:
            a = np.frombuffer(bytes(cont[doff:doff + nrow * stride]), np.uint8).reshape(nrow, stride)
            if r0 + nrow > h:
                a = a[:h - r0]
                nrow = len(a)
            if psm == 0x14:
                tex[r0:r0 + nrow, 0::2] = a & 0x0F
                tex[r0:r0 + nrow, 1::2] = (a >> 4) & 0x0F
            else:
                tex[r0:r0 + nrow, :] = a
        if rem and r0 + nrow < h:
            row = np.frombuffer(bytes(cont[doff + nrow * stride:doff + nrow * stride + rem]), np.uint8)
            if psm == 0x14:
                tex[r0 + nrow, 0:rem * 2:2] = row & 0x0F
                tex[r0 + nrow, 1:rem * 2:2] = row >> 4
            else:
                tex[r0 + nrow, :rem] = row
    return tex


def atlas_engine_image(cont, w, h, psm):
    """容器 → (引擎图 uint8[h,w], 空白索引, 封包表, 段表)。空白索引 = 出现最多的非 0 值。"""
    stride = w // 2 if psm == 0x14 else w
    pk = atlas_packets(cont, stride)
    segs = [(p['first_row'], p['doff'], p['bytes'])
            for p in pk if p['kind'] == 'image' and p['bytes']]
    tex = atlas_decode(cont, w, h, psm, segs)
    cnt = np.bincount(tex.ravel(), minlength=16 if psm == 0x14 else 256)
    nz = [(int(cnt[i]), i) for i in range(1, len(cnt))]
    nz.sort(reverse=True)
    empty = nz[0][1] if nz else 0
    return tex, empty, pk, segs


def atlas_write_pixels(cont, w, psm, segs, ys, xs, vals):
    """把引擎图像素批量写回容器（**4bpp 半字节安全**：只改目标 nibble，另一 nibble 原样）。

    ys/xs/vals = 等长数组；vals = 目标 texel 索引（0=墨/1=空…）。
    返回写入像素数；任何像素不落在某段数据区即 raise（封包换算错了）。
    """
    cont = bytearray(cont)
    stride = w // 2 if psm == 0x14 else w
    ys = np.asarray(ys, dtype=np.int64)
    xs = np.asarray(xs, dtype=np.int64)
    vals = np.asarray(vals, dtype=np.uint8)
    n = 0
    for (r0, doff, nb) in segs:
        rows = nb // stride
        sel = (ys >= r0) & (ys < r0 + rows)
        if not sel.any():
            continue
        yy, xx = ys[sel], xs[sel]
        vv = vals[sel]
        rel = (yy - r0) * stride + xx // 2
        if rel.min() < 0 or rel.max() >= nb:
            raise ValueError('像素越出该段数据区: rows=%d max_rel=%d nb=%d' % (rows, rel.max(), nb))
        offs = doff + rel
        hi = (xx & 1) == 1
        if psm == 0x14:
            if hi.any():
                o = offs[hi]
                cont_arr = np.frombuffer(bytes(cont), np.uint8).copy()
                cont_arr[o] = (cont_arr[o] & 0x0F) | ((vv[hi] & 0x0F) << 4)
                cont = bytearray(cont_arr.tobytes())
            lo = ~hi
            if lo.any():
                o = offs[lo]
                cont_arr = np.frombuffer(bytes(cont), np.uint8).copy()
                cont_arr[o] = (cont_arr[o] & 0xF0) | (vv[lo] & 0x0F)
                cont = bytearray(cont_arr.tobytes())
        else:
            cont_arr = np.frombuffer(bytes(cont), np.uint8).copy()
            cont_arr[offs] = vv
            cont = bytearray(cont_arr.tobytes())
        n += int(sel.sum())
    if n != len(ys):
        raise ValueError('有 %d 个像素不属于任何段的数据区' % (len(ys) - n))
    return bytes(cont)


def atlas_build_single_packet(tex, psm):
    """引擎图 → **单包** GIF 容器 [GIFTAG 16B][像素数据]（方案 A 原型用；256KB 级）。

    nloop = 像素字节数/16；eop=1；flg=2(IMAGE)。数据按行优先打包（PSMT4: 偶 x 低 nibble）。
    """
    h, w = tex.shape
    if psm == 0x14:
        lo = (tex[:, 0::2] & 0x0F).astype(np.uint8)
        hi = ((tex[:, 1::2] & 0x0F) << 4).astype(np.uint8)
        data = (lo | hi).tobytes()
    else:
        data = tex.tobytes()
    assert len(data) % 16 == 0, len(data)
    nloop = len(data) // 16
    # GIF 128-bit tag: [w0=NLOOP|EOP<<15, w1=FLG<<26, w2=REGS 低, w3=REGS 高] —— 恒 16 字节
    tag = struct.pack('<4I', nloop | (1 << 15), 2 << 26, 0, 0)
    return tag + data


# ═══════════════════════════ 网格公式 / slot 账本 ═══════════════════════════
def yrow(row):
    """网格行 → 图集 y（引擎采样左上角）。"""
    return GRID_Y0 + CH * (row + (GRID_SKIP_ROWS if row >= GRID_SKIP_ROW else 0))


def slot_cell(slot):
    """slot → (row, col, x, y)。"""
    row, col = slot // NCOL, slot % NCOL
    return row, col, CW * col, yrow(row)


def slot_of(b1, b2):
    return (b1 - LEAD_LO) * 94 + (b2 - TRAIL_LO)


def pair_of_slot(slot):
    return LEAD_LO + slot // 94, TRAIL_LO + slot % 94


def charset_load(path=CHARSET):
    js = json.load(open(path, encoding='utf-8'))
    return dict(enc_single={ch: int(v) for ch, v in js['codes'].items()},
                enc_pair={ch: tuple(v) for ch, v in js['pair_of'].items()},
                meta=js)


def slot_ledger(tex, cs):
    """按本体口径给 2350 个 slot 做账：used/real/pua/ink/free/col63。

    tex = 引擎图 uint8（值为索引；0=墨、1=空 —— 以 atlas_engine_image 的 empty 为准）。
    """
    ink = tex == 0
    slot2ch = {slot_of(*p): ch for ch, p in cs['enc_pair'].items()}
    rows = {}
    stat = dict(cap=PAIR_CAP, used=0, real_chars=0, pua=0, ink_slots=0, free_slots=0,
                col63_pua=0, usable_free=0)
    for slot in range(PAIR_CAP):
        row, col, x, y = slot_cell(slot)
        n = int(ink[y:y + CH, x:x + CW].sum())
        ch = slot2ch.get(slot)
        d = rows.setdefault(row, dict(row=row, y=y, slots=0, used=0, real=0, pua=0,
                                     ink=0, blank=0, col63=0))
        d['slots'] += 1
        if col == NCOL - 1:
            d['col63'] += 1
        if ch:
            stat['used'] += 1
            d['used'] += 1
            if 0xE000 <= ord(ch) <= 0xF8FF:
                stat['pua'] += 1
                d['pua'] += 1
                if col == NCOL - 1:
                    stat['col63_pua'] += 1
                else:
                    stat['usable_free'] += 1          # 占位键可改给新字
            else:
                stat['real_chars'] += 1
                d['real'] += 1
        else:
            stat['free_slots'] += 1
            stat['usable_free'] += 1                  # 完全未映射的空槽
        if n:
            stat['ink_slots'] += 1
            d['ink'] += 1
        else:
            d['blank'] += 1
    return dict(stat=stat, rows=[rows[r] for r in sorted(rows)])


# ═══════════════════════════ 方案 B：新 PAK / 新 FONT.RES / 写 ISO ═══════════════════════════
def build_new_pak(old_pak, old_recs, seed, clut_mode='native', container=None, px_size=None):
    """构造新 COMMON.PAK：替换 new_font_revised 记录（图集换成中文 1024×644 PSMT4）。

    · container 缺省 = seed['container']（本体成品 329,744B，逐字节拷贝）
    · clut_mode='native' → DLC 原生 psm20 形状 80B 块（12B 头 + 16 色 + u32 px_size）；
      'zh' → 本体中文记录原样 1040B 块（12B 头 + 256 色 + u32 px_size）
    返回 (new_pak, info)。
    """
    fi, rec = pak_find(old_recs, 'new_font_revised')
    container = seed['container'] if container is None else container
    px_size = len(container) if px_size is None else px_size
    zh_clut = seed['clut']
    if clut_mode == 'native':
        # 资料片自己的 psm20 原生 CLUT 形状（pda-lcd-02 实测）：
        #   [16B GIF IMAGE tag nloop=4/eop=1/flg=2][16 色 ×4B]  = 80B
        #   色表沿用中文图集的 palette[0..15]（index0=墨、其余透明）
        pal16 = zh_clut[16:16 + 16 * 4]
        assert len(pal16) == 64
        clut = struct.pack('<4I', 4 | (1 << 15), 2 << 26, 0, 0) + pal16
    elif clut_mode == 'zh':
        clut = zh_clut
    else:
        raise ValueError('clut_mode 只支持 native/zh')
    name = rec['name'].encode('latin-1')
    q = struct.pack('<II', rec.get('ty', 0), len(name)) + name
    q += struct.pack('<4I', ATLAS_PSM, ATLAS_W, ATLAS_H, len(clut))
    q += clut + struct.pack('<I', px_size) + container
    new_pak = bytes(old_pak[:rec['hdr_off']]) + q + bytes(old_pak[rec['rec_end']:])
    info = dict(pak_old_len=len(old_pak), pak_new_len=len(new_pak),
                delta=len(new_pak) - len(old_pak),
                font_record_index=fi, font_record_len=len(q),
                clut_mode=clut_mode, clut_len=len(clut), px_size=px_size,
                container_sha256=sha256(container), clut_sha256=sha256(clut))
    # 回读自证：新 PAK 能解析、十记录名字/其他记录字节不变、图集记录几何正确
    recs2 = pak_parse(new_pak)
    assert len(recs2) == len(old_recs), (len(recs2), len(old_recs))
    assert [x['name'] for x in recs2] == [x['name'] for x in old_recs]
    for i, (a, b) in enumerate(zip(old_recs, recs2)):
        if i == fi:
            continue
        assert bytes(old_pak[a['hdr_off']:a['rec_end']]) == bytes(new_pak[b['hdr_off']:b['rec_end']]), \
            '非目标记录 #%d (%s) 字节变了' % (i, a['name'])
    fr = recs2[fi]
    assert (fr['psm'], fr['w'], fr['h'], fr['px']) == (ATLAS_PSM, ATLAS_W, ATLAS_H, px_size)
    assert bytes(new_pak[fr['px_off']:fr['px_off'] + fr['px']]) == bytes(container)
    return new_pak, info


def build_new_ft_frame(dlc_font_raw, dlc_font_entry, zh_font_blob):
    """构造新 FONT.RES 帧（展开态 = ft_merge_for_dlc 的结果）。

    返回 (frame_bytes, merged_blob, frames, info)。
    约束：压缩帧必须 ≤ 原槽 stored（原地覆盖，尺寸/偏移都不变）。
    """
    dlc_blob, dframes, _used = frame_decode(dlc_font_raw)
    assert dlc_blob, 'DLC FONT.RES 解帧失败'
    merged = ft_merge_for_dlc(zh_font_blob, dlc_blob)
    cc = lzo_compress(merged, level=7, use_m1=True, use_m4=True)
    back, err, _ = lzo1x_decompress(cc, out_size=len(merged))
    assert err is None and back == merged, 'FONT.RES 回环失败'
    frame = struct.pack('<II', len(cc), len(merged)) + cc
    if len(frame) > dlc_font_entry['stored']:
        raise ValueError('新 FONT.RES 帧 %d B 超过原槽 %d B' % (len(frame), dlc_font_entry['stored']))
    info = dict(font_stored_slot=dlc_font_entry['stored'], font_real_slot=dlc_font_entry['real'],
                merged_len=len(merged), clen=len(cc), frame_len=len(frame),
                slack=dlc_font_entry['stored'] - len(frame),
                merged_sha256=sha256(merged), frame_sha256=sha256(frame),
                 faces=[dict(name=f['name'], nrec=f['nrec'], fld=f['fld'])
                        for f in ft_parse(merged)['faces']],
                tail_len=len(ft_parse(merged)['tail']))
    return frame, merged, info


def plan_b_layout(iso, entries, pak_new_len):
    """算出方案 B 的放置位置与 ISO9660 修改点。"""
    hdr = img_header(iso, entries[0]['off'] and GR_LBA)
    root = iso.find_root('GR.IMG')
    last_end = img_last_end(entries)
    new_off = align_up(last_end, 16)
    new_last_end = new_off + pak_new_len
    root_size_new = new_last_end + IMG_PAD
    abs_end = root['lba'] * SEC + root_size_new
    iso_new_size = align_up(max(iso.size, abs_end), SEC)
    vol_new = iso_new_size // SEC
    return dict(gr_lba=root['lba'], gr_base=root['lba'] * SEC,
                header_total=hdr['total'], last_end=last_end,
                new_off=new_off, new_last_end=new_last_end,
                root_size_new=root_size_new, root_size_old=root['size'],
                abs_end=abs_end, iso_old_size=iso.size, iso_new_size=iso_new_size,
                iso_grow=iso_new_size - iso.size,
                vol_old=struct.unpack_from('<I', iso.mm, 16 * SEC + 80)[0],
                vol_new=vol_new,
                root_rec_off=root['rec_off'],
                pvd_off=16 * SEC)


def write_plan_b_iso(src_iso, out_iso, layout, entries, new_pak, font_frame,
                     font_entry, verbose=True):
    """方案 B 落盘：换 PAK（放到 GR.IMG 末尾）+ 原地覆盖 FONT.RES 帧 + 改 ISO9660。

    修改点（全部实测，见 docs/ANALYSIS_FONT.md）：
      ① ISO 尾部扩展到 layout['iso_new_size']（新增扇区 = 新 PAK 超出原盘尾的字节）；
      ② PVD volume_space LE@+80 / BE@+84；
      ③ 根目录 GR.IMG 记录 size LE@+10 / BE@+14；
      ④ GR.IMG 头 +0x0 = 新声明大小（= 新 max(off+stored) + 0x10000，与旧盘同构）；
      ⑤ 条目 #9：off/stored/real 三字段；其余字段与其余 3110 条一个字节都不动；
      ⑥ 新 COMMON.PAK 写进 GR.IMG 末尾（旧 PAK 位置成为死区，不再被引用）。
    """
    if os.path.exists(out_iso):
        raise SystemExit('输出已存在，拒绝覆盖: %s' % out_iso)
    import shutil
    t = dict()
    shutil.copyfile(src_iso, out_iso)
    with open(out_iso, 'r+b') as f:
        # ① 扩到新尺寸
        f.truncate(layout['iso_new_size'])
        # ② PVD volume space（LE/BE 各一份）
        f.seek(16 * SEC + 80)
        f.write(struct.pack('<I', layout['vol_new']))
        f.write(struct.pack('>I', layout['vol_new']))
        # ③ 根目录 GR.IMG 记录 size（LE@+10 / BE@+14）
        f.seek(layout['root_rec_off'] + 10)
        f.write(struct.pack('<I', layout['root_size_new']))
        f.write(struct.pack('>I', layout['root_size_new']))
        # ④ GR.IMG 头声明大小
        f.seek(layout['gr_base'] + 0)
        f.write(struct.pack('<I', layout['root_size_new']))
        # ⑤ 条目 #9 三字段
        fi = entries[9]['idx']
        f.seek(entries[9]['tab_off'] + 6 * 4)
        f.write(struct.pack('<3I', len(new_pak), len(new_pak), layout['new_off']))
        # ⑥ 新 PAK
        f.seek(layout['gr_base'] + layout['new_off'])
        f.write(new_pak)
        # FONT.RES 帧原地覆盖（槽尺寸不变，尾部填 0）
        assert len(font_frame) <= font_entry['stored']
        f.seek(font_entry['iso_off'])
        f.write(font_frame)
        f.write(b'\x00' * (font_entry['stored'] - len(font_frame)))
    if verbose:
        P('[write] %s' % out_iso)
        P('        新 PAK @GR.IMG+0x%X (%d B) ; ISO %d → %d B (Δ%+d, %d 扇区)'
          % (layout['new_off'], len(new_pak), layout['iso_old_size'],
             layout['iso_new_size'], layout['iso_grow'], layout['vol_new'] - layout['vol_old']))
    return t


def verify_plan_b(src_iso, out_iso, seed, expectations, layout_new=None):
    """方案 B 回读自证（逐项断言，全过返回 dict(ok=True,...)）。"""
    res = dict(checks=[])
    ok = True
    if layout_new is None:
        layout_new = dict(new_off=0, new_last_end=0, last_end=0)

    def chk(cond, msg):
        nonlocal ok
        ok = ok and bool(cond)
        res['checks'].append(('ok   ' if cond else 'FAIL ') + msg)

    src = Iso(src_iso)
    out = Iso(out_iso)
    try:
        # ① ISO 级：root 条目结构、GR.IMG 大小/头、PVD volume space
        sr = {e['name']: e for e in src.root_entries()}
        orr = {e['name']: e for e in out.root_entries()}
        chk(set(sr) == set(orr), 'root 目录条目集合一致 (%d 项)' % len(orr))
        for nm in sr:
            if nm != 'GR.IMG;1':
                chk(sr[nm]['lba'] == orr[nm]['lba'] and sr[nm]['size'] == orr[nm]['size'],
                    'root 条目 %s 未变' % nm)
        pvd = out.pvd()
        chk(pvd['volume_space_le'] == pvd['volume_space_be'] == out.size // SEC,
            'PVD volume_space LE==BE==%d 扇区 (ISO %d B)' % (out.size // SEC, out.size))
        chk(out.size == expectations['iso_new_size'], 'ISO 尺寸 == 预期 %d B' % expectations['iso_new_size'])
        gr = out.find_root('GR.IMG')
        chk(gr['size'] == expectations['root_size_new'],
            '根目录 GR.IMG size == %d (LE/BE 双写)' % expectations['root_size_new'])
        h = img_header(out)
        chk(h['total'] == gr['size'], 'GR.IMG 头 +0x0 == 根目录 size')
        ents = img_entries(out)
        chk(len(ents) == len(img_entries(src)), 'IMG 条目数一致 (%d)' % len(ents))
        chk(img_consistent(out, ents)['ok'], 'GR.IMG 头/根 size/max(off+stored)+0x10000 三者自洽')
        # ② 条目表：只有 #9 的 [6][7][8] 变
        se = img_entries(src)
        bad = []
        for a, b in zip(se, ents):
            ra, rb = list(a['raw']), list(b['raw'])
            if a['idx'] == 9:
                ra[6:9] = rb[6:9]
            if ra != rb:
                bad.append((a['idx'], a['name'], ra, rb))
        chk(not bad, '3111 条条目表除 #9 的 [6][7][8] 外逐字段不变 (违例 %d)' % len(bad))
        # ③ 载荷：只有 #9（新 PAK）与 #580（新 FONT.RES）允许变，其余 3109 条逐字节不变
        changed = []
        for a, b in zip(se, ents):
            n = a['stored']
            x = src.read(a['iso_off'], n)
            y = out.read(b['iso_off'], n)
            if x != y:
                changed.append((a['idx'], a['name']))
        chk(changed == [(9, 'COMMON.PAK'), (580, 'FONT.RES')],
            '只有 #9 COMMON.PAK 与 #580 FONT.RES 载荷变化，其余 3109 条逐字节不变 (实际变化 %s)'
            % ([i for i, _n in changed],))
        # ③b #580 的条目表字段不变（stored/real/off 全保持），只换槽内字节
        chk(se[580]['raw'] == ents[580]['raw'], '#580 FONT.RES 条目表 12 字段不变（原地覆盖）')
        # ③c iso-analyst 实证的字段策略硬断言（[0][1][9][10][11] 只依赖名字，必须原样保留）
        r9o, r9n = se[9]['raw'], ents[9]['raw']
        e9len = expectations.get('pak_len')
        chk(r9n[6] == r9n[7] == e9len,
            '#9 [6]==[7]==新载荷长度 %s（raw 条目恒相等）' % e9len)
        chk(r9n[4] == 0, '#9 [4]=0（raw 载荷标志，与英文原盘一致）')
        chk(r9n[0] == r9o[0] and r9n[1] == r9o[1] and r9n[9] == r9o[9]
            and r9n[10] == r9o[10] and r9n[11] == r9o[11],
            '#9 [0][1][9][10][11]（name_off/名字升序链/名字键/哈希桶/冲突链）与英文原盘完全相同')
        chk(layout_new['new_off'] % 16 == 0, '#9 新 off=0x%X 保持 16 字节对齐' % layout_new['new_off'])
        chk(layout_new['new_last_end'] >= layout_new['last_end'],
            '新 data_end(%.0f) 只增不减（旧 %.0f）' % (layout_new['new_last_end'], layout_new['last_end']))
        # ④ 新 COMMON.PAK / FONT.RES
        e9 = ents[9]
        pak = out.read(e9['iso_off'], e9['stored'])
        recs = pak_parse(pak)
        chk(len(recs) == 10, '新 COMMON.PAK 解析出 10 条记录')
        chk([r['name'] for r in recs] == [r['name'] for r in pak_parse(src.read(se[9]['iso_off'], se[9]['stored']))],
            '10 条记录名字/顺序不变')
        fi, fr = pak_find(recs, 'new_font_revised')
        chk((fr['psm'], fr['w'], fr['h'], fr['px']) == (0x14, 1024, 644, ATLAS_PX),
            'new_font_revised = psm20 1024x644 px=%d' % ATLAS_PX)
        cont = pak[fr['px_off']:fr['px_off'] + fr['px']]
        chk(cont == seed['container'], '图集容器逐字节 == seed (sha=%s…)' % sha256(cont)[:16])
        tex, empty, pk, segs = atlas_engine_image(cont, 1024, 644, 0x14)
        chk(len(segs) == 11, '引擎图 = %d 段 GIF 封包（每段 48B 头；无相位）' % len(segs))
        seed_tex, seed_empty, _, seed_segs = atlas_engine_image(seed['container'], 1024, 644, 0x14)
        xor = int((tex != seed_tex).sum())
        chk(xor == 0, '回读引擎图 vs seed 图集逐 texel xor==0 (差异 %d)' % xor)
        # 逐格（2350 slot + ASCII 带）比对
        cs = expectations['charset']
        slot_bad = 0
        for slot in range(PAIR_CAP):
            row, col, x, y = slot_cell(slot)
            if not np.array_equal(tex[y:y + CH, x:x + CW], seed_tex[y:y + CH, x:x + CW]):
                slot_bad += 1
        chk(slot_bad == 0, '2350 个网格 slot 逐格 xor==0 (差异 %d)' % slot_bad)
        ft_e = ents[580]
        fraw = out.read(ft_e['iso_off'], ft_e['stored'])
        fblob, fframes, _ = frame_decode(fraw)
        chk(len(fblob) == ft_e['real'], 'FONT.RES 展开 %d == real %d' % (len(fblob), ft_e['real']))
        ft = ft_parse(fblob)
        chk([f['nrec'] for f in ft['faces']] == [224, 224, 224],
            'FONT.RES 三 face 记录数 = 224/224/224（不改 loader 假设）')
        chk(len(ft['tail']) == 522, 'FONT.RES 尾部样式表 = 资料片原盘 522B(15 条)')
        chk(sha256(fblob) == expectations['merged_sha256'], 'FONT.RES 展开 blob sha == 预期')
        res.update(iso_size=out.size, pak_len=len(pak), pak_sha256=sha256(pak),
                   font_blob_sha256=sha256(fblob), frames=fframes, empty_index=empty,
                   ink_texels=int((tex == 0).sum()))
    finally:
        src.close()
        out.close()
    res['ok'] = ok
    res['failed'] = [c for c in res['checks'] if c.startswith('FAIL')]
    return res


# ═══════════════════════════ 方案 A 原型（1024×512 原地等大小，评估用） ═══════════════════════════
def plan_a_prototype(seed, zh_faces, n_real_chars):
    """1024×512 PSMT4 单包容器原型：只保留引擎图前 512 行 ⇒ 结构合法但内容装不下。

    返回 dict(container, xor, ...)。用于在 docs 里给出**实测数字**：
      · 容器 = 16B GIFTAG + 262,144B = 262,160B == DLC 原图集记录 px（可原地等大小替换）；
      · 但 512 行网格（Y0=0/SKIP=0 时 32 行 × 64 列 = 2048 格）装不下：
        真汉字 N + ASCII/单字节 FT 带所需整格 ≈ ceil(FT带面积/256) ⇒ 合计 > 2048。
    """
    seed_tex, _e, _pk, _segs = atlas_engine_image(seed['container'], ATLAS_W, ATLAS_H, ATLAS_PSM)
    tex = seed_tex[:512, :].copy()
    cont = atlas_build_single_packet(tex, 0x14)
    back = atlas_decode(cont, 1024, 512, 0x14)
    xor = int((back != tex).sum())
    lost = sum(1 for slot in range(PAIR_CAP) if slot_cell(slot)[3] + CH > 512)
    # FT 带面积：**唯一矩形并集**（三个 face 大面积共享同一批带；按 face 累加会虚高 3 倍）
    ft_mask = np.zeros((ATLAS_H, ATLAS_W), dtype=bool)
    for f in zh_faces:
        for r in f['recs']:
            _b0, _b1, u0, v0, u1, v1 = r
            if u1 > u0 and v1 > v0:
                ft_mask[max(0, v0):min(ATLAS_H, v1), max(0, u0):min(ATLAS_W, u1)] = True
    ft_px = int(ft_mask.sum())
    ft_cells = int(np.ceil(ft_px / float(CW * CH)))
    return dict(container=cont, container_len=len(cont), xor=xor,
                slots_lost_beyond_512=lost,
                ft_band_px=ft_px, ft_band_cells=ft_cells,
                cells_needed=n_real_chars + ft_cells,
                cells_1024x512=1024 // CW * (512 // CH),
                fits=(n_real_chars + ft_cells) <= (1024 // CW * (512 // CH)))


def draw_glyphs(container, w, h, psm, assignments, ttf_path=TTF, empty=1):
    """在引擎图坐标系里**补画**新字形（4bpp 半字节安全），返回 (new_container, report)。

    assignments = {char: slot}：只允许写**空格**（当前零墨、非 col-63，且不与 FT 矩形交叠由调用方保证）。
    渲染配方与本体一致：PIL truetype 16px → 32×32 白底 → text((8,8)) → [8:24,8:24] → <128 = 墨。
    写后立即回读：每格与模板逐 texel xor 必须为 0。
    """
    from PIL import Image, ImageDraw, ImageFont
    tex, _empty, _pk, segs = atlas_engine_image(container, w, h, psm)
    stride = w // 2 if psm == 0x14 else w
    fnt = ImageFont.truetype(ttf_path, 16)
    ys, xs, vals, report = [], [], [], []
    for ch, slot in assignments.items():
        row, col, x, y = slot_cell(slot)
        assert col != NCOL - 1, 'slot=%d 落在 col-63（右缘采样不到）' % slot
        img = Image.new('L', (32, 32), 255)
        ImageDraw.Draw(img).text((8, 8), ch, font=fnt, fill=0)
        tpl = np.asarray(img)[8:24, 8:24] < 128
        assert tpl.any(), 'TTF 里没有 %r 的字形' % ch
        assert not (tex[y:y + CH, x:x + CW] == 0).any(), 'slot=%d 目标格已有墨，拒绝覆盖' % slot
        cell_vals = np.where(tpl, 0, empty).astype(np.uint8)
        ys.extend((y + np.repeat(np.arange(CH), CW)).tolist())
        xs.extend((x + np.tile(np.arange(CW), CH)).tolist())
        vals.extend(cell_vals.reshape(-1).tolist())
        report.append(dict(char=ch, slot=slot, cell=[x, y], ink=int(tpl.sum()),
                           tpl=tpl))
    new = atlas_write_pixels(container, w, psm, segs, ys, xs, vals)
    tex2 = atlas_decode(new, w, h, psm, segs)
    for item in report:
        x, y = item['cell']
        got = tex2[y:y + CH, x:x + CW] == 0
        item['xor'] = int((got != item.pop('tpl')).sum())
        item['readback_ok'] = (item['xor'] == 0)
    return new, report


# ═══════════════════════════ 小工具：图集 PNG ═══════════════════════════
def save_atlas_png(tex, path, empty=1, scale=1):
    from PIL import Image
    ink = (tex == 0)
    if scale > 1:
        ink = np.repeat(np.repeat(ink, scale, axis=0), scale, axis=1)
    img = Image.frombytes('L', (ink.shape[1], ink.shape[0]),
                          np.where(ink, 0, 255).astype(np.uint8).tobytes())
    img.save(path, optimize=True)
    return os.path.getsize(path)


if __name__ == '__main__':
    P('fontlib selfcheck: 常量 PAIR_CAP=%d ATLAS_PX=%d yrow(0)=%d yrow(12)=%d yrow(36)=%d'
      % (PAIR_CAP, ATLAS_PX, yrow(0), yrow(12), yrow(36)))
