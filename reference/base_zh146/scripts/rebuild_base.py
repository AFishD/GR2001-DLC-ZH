# -*- coding: utf-8 -*-
r"""rebuild_base.py —— 从**英文原版 ISO** 重建 2400 产品线基底（收尾归档版）。

产出 = `GR_REBUILD2400.iso` (1,648,164,864 B,
sha256 d7f83d7ec4a8fe1ec8d60de4b17b94513bd1540dc929d3b667086f4910443ca0)。

★ 强制规则（2026-10-18 收尾确立）
    今后一切构筑**必须从英文原版 ISO 出发**：
        third_party\orig\ps2\Tom Clancy's Ghost Recon (USA).iso
        sha256 2b42ea7ce9bd0a85972a07ca59b1b9d79422ed318b85737db3cfd17daa788531
    **禁止**拿上一版汉化 ISO 当基底（那样复现链会退化成"依赖历史产物"）。
    本文件 = 这条规则的执行体；`repro_from_eng.ps1` 是它的总装入口。

链路（每一步都有硬断言，失败即中止、不落盘）：
    [1]  基底 = 英文原盘 ⊕ GR_FA2400_K2 块转储的全部扇区
    [1c] MENU.IMG 尾部位移 +0x10800 的重建（K2 转储未覆盖处取 原盘[x-0x10800]）
    [A1] ELF 区逐字节 == K2 真件（**从转储里现取**，sha256 5cb59175…；不再依赖
         任何 work\builds\** 下的中间文件 —— 这正是 2026-10-18 断链的根因）
    [2]  GR#902 EN_STRINGS.RES ← 由 MENU#25 的「EN → 中文」逐条对应重建 + 重压
    [3]  GR#906 FONT.RES ← MENU#4（英文盘上两份逐字节相同 ⇒ 同步写）
    [4]  GR#3451 COMMON.PAK ← GR_ZH113b 系转储的 MENU#3 槽（旁证候选；引擎从不读 GR 侧那份）
    [5]  重新压回 [1] 的 K2 真扇区（覆盖 [4] 写过的区域）
    [6]  自查（条目数 / 容器指纹 / MENU#25 与 GR#902 逐条 payload 相同）
    [7]  与声明值对指纹（基底 sha256、ELF sha256），写 build_info + 日志

与旧配方的关系
--------------
本文件是 `work\builds\GR_REBUILD\tools\rb_build.py`（2026-10-17）的**等价重写**，
数学/字节操作逐行照搬，只有两处不同：
    ① [A1] 的参照 ELF 改为**从 K2 转储现场取出**（旧配方读
       `work\builds\GR_CSFIX\temp\K2_SLUS_206.13.elf`，该文件已被历史清理删除 ⇒ 断链）；
    ② 全部输入改成命令行参数，并强制落在**仓库外/只读**的输入上。
⇒ 旧配方里"必须从 GR_REBUILD2400.iso 起"的表述随之作废（见 README.md 顶部规则）。

只读输入（绝不写）：英文原盘、两个 cdvd 转储。只写 `--out`。

用法
----
    python tools\final_fix\rebuild_base.py --out D:\tmp\GR_REBUILD2400.iso
    python tools\final_fix\rebuild_base.py --dry          # 只打印输入指纹
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
import tcslib as T                                                    # noqa: E402

SEC = 2048
DUMPDIR = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'PCSX2', 'cdvd-dump')
ORIG = os.path.join(REPO, 'third_party', 'orig', 'ps2',
                    "Tom Clancy's Ghost Recon (USA).iso")
K2DUMP = os.path.join(DUMPDIR, 'GR_FA2400_K2 (2026-10-17 15-08-20).dump')
CANDDUMP = os.path.join(DUMPDIR, 'GR_ZH113b (2026-10-15 19-39-44).dump')
MENU_LBA, GR_LBA = T.MENU_LBA, T.GR_LBA               # 776286 / 19175
TAB_OFF, TAB_STEP = T.TAB_OFF, T.TAB_STEP             # 0x830 / 48

ELF_LBA = 295
ELF_BYTES = 37453732
EXP_ORIG_SHA = '2b42ea7ce9bd0a85972a07ca59b1b9d79422ed318b85737db3cfd17daa788531'
EXP_ORIG_ELF_SHA = '5fec662f2a138f9f62f6bc07d24be484c7b0f65a38e965b6cba9fc928cb94105'
EXP_BASE_SHA = 'd7f83d7ec4a8fe1ec8d60de4b17b94513bd1540dc929d3b667086f4910443ca0'
EXP_K2_ELF_SHA = '5cb59175d28bfea3f37a9eb485399ea3925a2ca6f73d32d65e226d274abf47d8'

LOG = []


def P(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(p, buf=1 << 22):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(buf), b''):
            h.update(b)
    return h.hexdigest()


# ─────────────────────── BDV2 块转储（只读） ───────────────────────
def load_idx(path):
    """BDV2: off0 'BDV2' ; off4 block=2048 ; off8 total_lba ; off12 0 ;
    之后 N × [u32 LBA][2048 B]。自检 16 + N*2052 == filesize。"""
    n = os.path.getsize(path)
    with open(path, 'rb') as f:
        magic, bsz, total, zero = struct.unpack('<4sIII', f.read(16))
        assert magic == b'BDV2', '%s: 不是 BDV2' % path
        assert bsz == SEC, '%s: block_size=%d' % (path, bsz)
        cnt, rem = divmod(n - 16, 4 + SEC)
        assert rem == 0, '%s: 长度自检失败 (余 %d)' % (path, rem)
        idx = {}
        for i in range(cnt):
            f.seek(16 + i * (4 + SEC))
            idx[struct.unpack('<I', f.read(4))[0]] = 16 + i * (4 + SEC) + 4
    return idx, total


def read_at(path, idx, off, size):
    """从转储里按 ISO 绝对偏移读 size 字节；任一扇区缺失返回 None。"""
    l0, l1 = off // SEC, (off + size - 1) // SEC
    buf = bytearray()
    with open(path, 'rb') as f:
        for l in range(l0, l1 + 1):
            if l not in idx:
                return None
            f.seek(idx[l])
            buf += f.read(SEC)
    return bytes(buf[off - l0 * SEC:off - l0 * SEC + size])


def dump_elf(path, idx):
    """从转储取出 LBA 295 起的 ELF 真字节（18,288 扇区 截到 37,453,732 B）。"""
    need = (ELF_BYTES + SEC - 1) // SEC
    miss = [l for l in range(ELF_LBA, ELF_LBA + need) if l not in idx]
    assert not miss, '%s: 缺 ELF 扇区 %d 个（例 %s）' % (path, len(miss), miss[:8])
    buf = bytearray()
    with open(path, 'rb') as f:
        for l in range(ELF_LBA, ELF_LBA + need):
            f.seek(idx[l])
            buf += f.read(SEC)
    return bytes(buf[:ELF_BYTES])


# ─────────────────────── IMG 条目表（= zx_lib.entries 口径） ───────────────────────
def entries(iso, lba):
    base = lba * SEC
    noff = struct.unpack_from('<I', iso.mm, base + 0x10)[0]
    nend = struct.unpack_from('<I', iso.mm, base + 4)[0]
    names = [x.decode('latin-1') for x in
             bytes(iso.mm[base + noff:base + nend]).split(b'\x00') if x]
    out = []
    for i, nm in enumerate(names):
        r = struct.unpack_from('<12I', iso.mm, base + TAB_OFF + TAB_STEP * i)
        out.append(dict(idx=i, name=nm, raw=list(r), stored=r[6], real=r[7], off=r[8],
                        iso_off=base + r[8]))
    return out


def find(ent, name, nth=0):
    return [x for x in ent if x['name'] == name][nth]


def main(argv):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                                # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description='从英文原盘重建 2400 产品线基底')
    ap.add_argument('--orig', default=ORIG, help='英文原版 ISO（只读）')
    ap.add_argument('--k2-dump', default=K2DUMP, help='K2 盘 cdvd 块转储（只读）')
    ap.add_argument('--cand-dump', default=CANDDUMP, help='GR_ZH113b 系转储（只读）')
    ap.add_argument('--out', help='输出基底 ISO（必须不存在）')
    ap.add_argument('--dry', action='store_true', help='只打印输入指纹，不写盘')
    ap.add_argument('--expect-base-sha256', default=EXP_BASE_SHA)
    a = ap.parse_args(argv)
    t0 = time.time()

    P('=' * 100)
    P('rebuild_base.py  ——  从英文原盘重建 GR_REBUILD2400')
    P('=' * 100)
    P('[输入] 英文原盘 = %s' % a.orig)
    assert os.path.exists(a.orig), a.orig
    orig_size = os.path.getsize(a.orig)
    orig_sha = sha_file(a.orig)
    P('       sha256 = %s (%d B)' % (orig_sha, orig_size))
    assert orig_sha == EXP_ORIG_SHA, '英文原盘指纹不符: %s' % orig_sha
    P('       ✓ == 声明值 %s' % EXP_ORIG_SHA)

    for tag, p in (('K2', a.k2_dump), ('候选', a.cand_dump)):
        assert os.path.exists(p), p
        P('[输入] %s 转储 = %s' % (tag, p))
        P('       %d B ; sha256 = %s' % (os.path.getsize(p), sha_file(p)))

    kidx, ktot = load_idx(a.k2_dump)
    cidx, _ctot = load_idx(a.cand_dump)
    P('       K2 覆盖扇区 %d / %d (%.2f%%) ; 候选覆盖 %d'
      % (len(kidx), ktot, 100.0 * len(kidx) / ktot, len(cidx)))

    # ── [A1 前置] 从转储现取 K2 的真 ELF（旧配方读的中间文件已被删除）──
    k2elf = dump_elf(a.k2_dump, kidx)
    k2elf_sha = sha(k2elf)
    P('[A1] 从 K2 转储取回的 ELF: %d B ; sha256 = %s' % (len(k2elf), k2elf_sha))
    assert k2elf_sha == EXP_K2_ELF_SHA, 'K2 转储里的 ELF 指纹不符: %s' % k2elf_sha
    P('     ✓ == 声明值 %s' % EXP_K2_ELF_SHA)

    if a.dry:
        P('[dry] 到此为止（不写盘）')
        return 0

    assert a.out, '--out 必填'
    out = os.path.abspath(a.out)
    if os.path.exists(out):
        raise SystemExit('输出已存在，拒绝覆盖: %s' % out)
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    tmp = out + '.part'

    # ═══════════ [1] 基底 = 原盘 ⊕ K2 转储 ═══════════
    P('')
    P('[1] 基底 = 英文原盘 ⊕ K2 块转储')
    nsec = orig_size // SEC
    assert orig_size % SEC == 0
    shutil.copyfile(a.orig, tmp)
    P('    [1a] 拷原盘 → %s' % os.path.basename(tmp))
    n_over = 0
    with open(tmp, 'r+b') as fo, open(a.k2_dump, 'rb') as fd:
        for lba, off in sorted(kidx.items()):
            if lba >= nsec:
                continue
            fd.seek(off)
            fo.seek(lba * SEC)
            fo.write(fd.read(SEC))
            n_over += 1
    P('    [1b] 覆盖 K2 扇区 %d 个 (%.2f MB)' % (n_over, n_over * SEC / 1048576.0))

    # ── [1c] MENU.IMG 尾部整体位移 +0x10800 的重建 ──
    MENU_SHIFT = 0x10800
    MENU_FT_NEW = 0xC9920                 # K2: FONT.RES 新 off（= 0xB9120 + 0x10800）
    menu_base = MENU_LBA * SEC
    menu_lim = (MENU_LBA + ktot - MENU_LBA) * SEC    # 一直到盘尾
    P('')
    P('[1c] MENU.IMG 尾部位移重建: base=0x%X ; 阈值 x>=0x%X 取 原盘[x-0x%X]'
      % (menu_base, MENU_FT_NEW, MENU_SHIFT))
    src = open(a.orig, 'rb')
    try:
        with open(tmp, 'r+b') as fo:
            lo = menu_base + MENU_FT_NEW
            hi = min(menu_base + menu_lim, orig_size)
            l0, l1 = lo // SEC, (hi - 1) // SEC
            n_fill = n_skip = 0
            for lba in range(l0, l1 + 1):
                if lba in kidx:
                    n_skip += 1                    # K2 真字节，保留
                    continue
                fo.seek(lba * SEC)
                cur = bytearray(fo.read(SEC))
                src.seek(lba * SEC - MENU_SHIFT)
                old = src.read(SEC)
                if len(old) < SEC:
                    old = old + b'\x00' * (SEC - len(old))
                cut = max(0, lo - lba * SEC)
                cur[cut:] = old[cut:]
                fo.seek(lba * SEC)
                fo.write(bytes(cur))
                n_fill += 1
        P('     填充 %d 扇区 / 跳过（K2 真字节）%d 扇区' % (n_fill, n_skip))
    finally:
        src.close()

    # ── [A1] ELF 逐字节 == K2 真件 ──
    with open(tmp, 'rb') as f:
        f.seek(ELF_LBA * SEC)
        elf_in = f.read(ELF_BYTES)
    P('    [A1] ELF(ISO %d..+%d) == K2 转储真件 : %s ; sha=%s'
      % (ELF_LBA * SEC, ELF_BYTES, elf_in == k2elf, sha(elf_in)[:16]))
    assert elf_in == k2elf, 'ELF 与 K2 真件不符'
    assert sha(elf_in) == EXP_K2_ELF_SHA

    iso = T.Iso(tmp)
    men = entries(iso, MENU_LBA)
    gr = entries(iso, GR_LBA)

    e_m_pak = find(men, 'COMMON.PAK')
    e_m_ft = find(men, 'FONT.RES')
    e_m_lang = find(men, 'EN_STRINGS.RES')
    e_g_lang = find(gr, 'EN_STRINGS.RES')
    e_g_ft = find(gr, 'FONT.RES')
    e_g_pak = find(gr, 'COMMON.PAK')

    # ── [A2] MENU#3 图集 1024x644 / 329744 ──
    pak = bytes(iso.read(e_m_pak['iso_off'], e_m_pak['stored']))
    rec = [r for r in T.parse_pak_records(pak) if r[0] == 'new_font_revised'][0]
    P('    [A2] MENU#%d COMMON.PAK stored=%d ; new_font_revised psm=%d w=%d h=%d px=%d'
      % (e_m_pak['idx'], e_m_pak['stored'], rec[1], rec[2], rec[3], rec[5]))
    assert (rec[1], rec[2], rec[3], rec[5]) == (20, 1024, 644, 329744), rec
    assert rec[5] == 1024 * 644 // 2 + 16
    assert (1024 * 644 // 2) % 2048 == 0
    assert rec[2] < 1025
    # ── [A3] MENU#25 已是中文 ──
    slotm = bytes(iso.read(e_m_lang['iso_off'], e_m_lang['stored']))
    blobm = b''.join(s[0] for s in T.lzo_subs(slotm))
    ents_m, used_m = T.parse_lang(blobm)
    P('    [A3] MENU#%d EN_STRINGS.RES 条目=%d used_end=0x%X 首条 payload=%s'
      % (e_m_lang['idx'], len(ents_m), used_m, ents_m[0].data[:12]))
    assert ents_m[0].data != b'Victory!', 'MENU 语言表不是中文（K2 扇区没取回？）'

    # ═══════════ [2] GR#902 ← MENU#25 的 EN→中文对应 ═══════════
    P('')
    P('[2] GR#%d EN_STRINGS.RES ← 由 MENU#%d 的 EN→中文 逐条对应重建'
      % (e_g_lang['idx'], e_m_lang['idx']))
    s_gr_en = bytes(iso.read(e_g_lang['iso_off'], e_g_lang['stored']))
    subs_g = T.lzo_subs(s_gr_en)
    blob_g_en = b''.join(s[0] for s in subs_g)
    ents_g, used_g = T.parse_lang(blob_g_en)
    P('    GR#902 条目=%d used_end=0x%X blob=%d ; 与 MENU 条目数一致=%s'
      % (len(ents_g), used_g, len(blob_g_en), len(ents_g) == len(ents_m)))
    assert len(ents_g) == len(ents_m)
    assert [(x.g, x.i) for x in ents_g] == [(x.g, x.i) for x in ents_m]

    o = T.Iso(a.orig)
    e_o = find(entries(o, MENU_LBA), 'EN_STRINGS.RES')
    o.close()
    with open(a.orig, 'rb') as f:
        f.seek(e_o['iso_off'])
        slot_o = f.read(e_o['stored'])
    blob_m_en = b''.join(s[0] for s in T.lzo_subs(slot_o))
    ents_men, used_men = T.parse_lang(blob_m_en)
    assert len(ents_men) == len(ents_g)
    assert [(x.g, x.i) for x in ents_men] == [(x.g, x.i) for x in ents_g]
    same_en = sum(1 for x, y in zip(ents_men, ents_g) if x.data == y.data)
    P('    [A4] 英文盘上 MENU#25 与 GR#902 逐条 payload 相同 %d/%d (%.1f%%)'
      % (same_en, len(ents_men), 100.0 * same_en / len(ents_men)))
    assert same_en >= 0.99 * len(ents_men)
    n_zh = sum(1 for x, y in zip(ents_men, ents_m) if x.data != y.data)
    P('    [A5] MENU#25 EN→K2 中文：payload 变化 %d/%d 条' % (n_zh, len(ents_men)))

    edits = []
    for i in range(len(ents_g)):
        sp = T.lang_entry_span(blob_g_en, ents_g[i])
        attr = blob_g_en[ents_g[i].attr_off:ents_g[i].attr_off + 2]
        edits.append((sp[0], sp[1], struct.pack('<I', len(ents_m[i].data))
                      + ents_m[i].data + attr))
    spliced = T.splice(blob_g_en, edits)
    growth = len(spliced) - len(blob_g_en)
    shift, undo = 0, []
    for (s0, s1, nb) in sorted(edits, key=lambda x: x[0]):
        undo.append((s0 + shift, s0 + shift + len(nb), blob_g_en[s0:s1]))
        shift += len(nb) - (s1 - s0)
    assert T.splice(spliced, undo) == blob_g_en, '[S2] 反向重建失败'
    P('    [S2] 反向重建 == 源 GR_EN blob ✓ ; 新 blob %d B (Δ%+d)' % (len(spliced), growth))
    if growth > 0:
        assert growth <= len(blob_g_en) - used_g, 'GR 容器装不下'
        new_blob_g = spliced[:len(blob_g_en)]
    else:
        new_blob_g = spliced + b'\x00' * (-growth)
    nG, uG = T.parse_lang(new_blob_g)
    assert len(nG) == len(ents_g)
    assert [(x.g, x.i) for x in nG] == [(x.g, x.i) for x in ents_g]
    bad = [i for i in range(len(nG)) if nG[i].data != ents_m[i].data]
    P('    [S5] 逐条 payload == MENU 侧中文 : 不同 %d 条' % len(bad))
    assert not bad, bad[:5]
    assert uG == used_m, 'used_end 不一致: 0x%X vs 0x%X' % (uG, used_m)
    P('    [S4] 新 blob used_end=0x%X == MENU 侧 0x%X ✓' % (uG, used_m))

    frame = bytearray()
    q = 0
    n_rep = 0
    for k, s in enumerate(subs_g):
        part = new_blob_g[q:q + s[2]]
        q += s[2]
        if part == s[0]:
            frame += s_gr_en[s[3]:s[3] + 8 + s[1]]
            continue
        cc = T.lzo_compress(part, level=7, use_m1=True, use_m4=True)
        back, err, _ = T.lzo1x_decompress(cc, out_size=s[2])
        assert err is None and back == part, '子流 %d 回环失败' % k
        frame += struct.pack('<II', len(cc), s[2]) + cc
        n_rep += 1
    frame = bytes(frame)
    assert q == len(new_blob_g)
    assert len(frame) <= e_g_lang['stored'], (len(frame), e_g_lang['stored'])
    P('    [S7] 重压 %d 子流 ; 帧 %d B ; 槽 %d B ⇒ 余 %d B'
      % (n_rep, len(frame), e_g_lang['stored'], e_g_lang['stored'] - len(frame)))
    iso.close()

    with open(tmp, 'r+b') as f:
        f.seek(e_g_lang['iso_off'])
        f.write(frame)
        f.write(b'\x00' * (e_g_lang['stored'] - len(frame)))
    P('    写出 GR#%d @0x%08X' % (e_g_lang['idx'], e_g_lang['iso_off']))

    # ═══════════ [3] GR#906 FONT.RES ← MENU#4 ═══════════
    P('')
    P('[3] GR#%d FONT.RES ← MENU#%d（英文盘上两份逐字节相同 → 同步）'
      % (e_g_ft['idx'], e_m_ft['idx']))
    iso3 = T.Iso(tmp)
    men3 = entries(iso3, MENU_LBA)
    gr3 = entries(iso3, GR_LBA)
    e_m_ft3 = find(men3, 'FONT.RES')
    e_g_ft3 = find(gr3, 'FONT.RES')
    slot_ft = bytes(iso3.read(e_m_ft3['iso_off'], e_m_ft3['stored']))
    blob_ft = b''.join(s[0] for s in T.lzo_subs(slot_ft))
    P('    MENU#4 FONT.RES stored=%d 展开=%d sha=%s'
      % (e_m_ft3['stored'], len(blob_ft), sha(slot_ft)[:16]))
    assert e_m_ft3['stored'] == e_g_ft3['stored'], '两槽长度不同'
    iso3.close()
    with open(tmp, 'r+b') as f:
        f.seek(e_g_ft3['iso_off'])
        f.write(slot_ft)
    with open(tmp, 'rb') as f:
        f.seek(e_g_ft3['iso_off'])
        back = f.read(e_g_ft3['stored'])
    assert back == slot_ft
    P('    [R3] 写后回读 == MENU 侧 slot ✓')

    # ═══════════ [4] GR#3451 COMMON.PAK ← 旁证候选 ═══════════
    P('')
    P('[4] GR#%d COMMON.PAK ← 旁证候选（%s 的 MENU#3 槽）'
      % (e_g_pak['idx'], os.path.basename(a.cand_dump)))
    o2 = T.Iso(a.orig)
    e_o_m_pak = find(entries(o2, MENU_LBA), 'COMMON.PAK')
    o2.close()
    cand = read_at(a.cand_dump, cidx, e_o_m_pak['iso_off'], e_o_m_pak['stored'])
    assert cand is not None and len(cand) == e_g_pak['stored']
    r2 = [r for r in T.parse_pak_records(cand) if r[0] == 'new_font_revised'][0]
    P('    候选 new_font_revised psm=%d w=%d h=%d stored=%d ; sha=%s'
      % (r2[1], r2[2], r2[3], r2[5], sha(cand)[:16]))
    assert (r2[1], r2[2], r2[3], r2[5]) == (20, 1024, 512, 262160), r2
    with open(tmp, 'r+b') as f:
        f.seek(e_g_pak['iso_off'])
        f.write(cand)
    P('    写出 GR#%d @0x%08X (%d B)' % (e_g_pak['idx'], e_g_pak['iso_off'], len(cand)))

    # ═══════════ [5] 重新压回 K2 真扇区 ═══════════
    P('')
    P('[5] 重新压回 [1] 的 K2 真扇区（覆盖写过的区域）')
    l0 = e_g_pak['iso_off'] // SEC
    l1 = (e_g_pak['iso_off'] + e_g_pak['stored'] - 1) // SEC
    n_back = 0
    with open(tmp, 'r+b') as fo, open(a.k2_dump, 'rb') as fd:
        for lba in range(l0, l1 + 1):
            if lba in kidx and lba < nsec:
                fd.seek(kidx[lba])
                fo.seek(lba * SEC)
                fo.write(fd.read(SEC))
                n_back += 1
    P('    GR#3451 区间 LBA %d..%d 中 K2 真扇区 %d 个已回压' % (l0, l1, n_back))

    # ═══════════ [6] 自查 ═══════════
    P('')
    P('[6] 总装自查')
    v = T.Iso(tmp)
    menv = entries(v, MENU_LBA)
    grv = entries(v, GR_LBA)
    P('    [C1] MENU 条目 %d / GR 条目 %d（与原盘一致 %s / %s）'
      % (len(menv), len(grv), len(menv) == 686, len(grv) == 4070))
    for nm, ent, tag in (('COMMON.PAK', menv, 'MENU'), ('FONT.RES', menv, 'MENU'),
                         ('EN_STRINGS.RES', menv, 'MENU'),
                         ('EN_SPECIAL_FEATURE.XML', menv, 'MENU'),
                         ('EN_STRINGS.RES', grv, 'GR'), ('FONT.RES', grv, 'GR'),
                         ('COMMON.PAK', grv, 'GR')):
        e = find(ent, nm)
        s = bytes(v.read(e['iso_off'], e['stored']))
        subs = T.lzo_subs(s)
        blob = b''.join(x[0] for x in subs) if subs else b''
        P('    %s#%-5d %-24s stored=%-8d 子流=%-3d 展开=%-8d sha=%s'
          % (tag, e['idx'], nm, e['stored'], len(subs) if subs else 0, len(blob),
             sha(blob)[:16] if blob else sha(s)[:16]))
    s2 = bytes(v.read(find(grv, 'EN_STRINGS.RES')['iso_off'],
                      find(grv, 'EN_STRINGS.RES')['stored']))
    b2 = b''.join(x[0] for x in T.lzo_subs(s2))
    e2, u2 = T.parse_lang(b2)
    s1 = bytes(v.read(find(menv, 'EN_STRINGS.RES')['iso_off'],
                      find(menv, 'EN_STRINGS.RES')['stored']))
    b1 = b''.join(x[0] for x in T.lzo_subs(s1))
    e1, u1 = T.parse_lang(b1)
    P('    [C2] MENU#25 与 GR#902 逐条 payload 相同 = %s (used_end 0x%X / 0x%X)'
      % (all(x.data == y.data for x, y in zip(e1, e2)), u1, u2))
    assert all(x.data == y.data for x, y in zip(e1, e2))
    v.close()

    os.replace(tmp, out)
    h = sha_file(out)
    P('')
    P('★ 产物 = %s' % out)
    P('  尺寸 = %d B ; sha256 = %s' % (os.path.getsize(out), h))
    P('  用时 %.1f s' % (time.time() - t0))
    ok = (h == a.expect_base_sha256)
    P('[7] 基底指纹 %s 声明值 %s ⇒ %s'
      % (h, a.expect_base_sha256, '一致 ✓' if ok else '不一致 ✗'))
    assert ok, '基底 sha256 与声明值不符: %s' % h

    info = dict(version='GR_REBUILD2400', out=out, bytes=os.path.getsize(out), sha256=h,
                built=time.strftime('%Y-%m-%d %H:%M'),
                builder='tools/final_fix/rebuild_base.py (from ENG original ISO; mandatory rule)',
                base=os.path.relpath(a.orig, REPO) if a.orig.startswith(REPO) else a.orig,
                base_sha256=orig_sha,
                k2_dump=a.k2_dump, k2_dump_sha256=sha_file(a.k2_dump),
                k2_dump_bytes=os.path.getsize(a.k2_dump), k2_sectors=len(kidx),
                k2_elf_from_dump_sha256=k2elf_sha,
                cand_dump=a.cand_dump, cand_dump_sha256=sha_file(a.cand_dump),
                cand_sectors=len(cidx),
                steps=['[1] orig + K2 block dump (%d sectors)' % n_over,
                       '[1c] MENU.IMG tail shift +0x%X rebuilt (%d fill / %d skip)'
                       % (MENU_SHIFT, n_fill, n_skip),
                       '[A1] ELF == K2 true bytes from dump (%s)' % k2elf_sha[:12],
                       '[2] GR#902 EN_STRINGS.RES rebuilt from MENU#25, frame %d B' % len(frame),
                       '[3] GR#906 FONT.RES <- MENU#4 slot (%d B)' % len(slot_ft),
                       '[4] GR#3451 COMMON.PAK <- ZH113b-family candidate (%d B)' % len(cand),
                       '[5] re-asserted %d K2-true sectors' % n_back])
    with io.open(os.path.join(os.path.dirname(out), 'build_info_rebuild.json'), 'w',
                 encoding='utf-8', newline='\n') as fh:
        json.dump(info, fh, ensure_ascii=False, indent=1)
    with io.open(os.path.join(os.path.dirname(out), 'rebuild_base.log'), 'w',
                 encoding='utf-8', newline='\n') as fh:
        fh.write('\n'.join(LOG) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
