# -*- coding: utf-8 -*-
r"""rebuild.py —— 从英文原盘「加改动」重建一张新 ISO（构筑链的核心引擎）。

设计原则（对应 docs/PLAN.md 纪律 2）：
  · 输入**只有**英文原盘 + 本工程的替换资源（payload 级），不依赖任何历史成品盘；
  · 未替换的条目逐字节从原盘搬运；替换条目只换 payload，条目表/名字表由本模块重算；
  · 全部改动可校验：重建后逐条目回读 == 期望 payload（见 verify_identity）。

IMG 布局（实证，见 docs/ANALYSIS_ISO.md）：
  [0x000 .. 0x830)            文件头（+0x4 名字区结束, +0x10 名字区起点, +0x14 载荷起点, ...）
  [0x830 .. 0x830+N*48)       条目表，每项 12×u32：[6]=stored [7]=real [8]=条目内偏移
  [names_off .. names_end)    名字表（'\0' 分隔，顺序 == 条目顺序）
  [payload_off .. EOF)        载荷区：条目按表顺序、16 字节对齐顺序排布

条目载荷两种形态：
  raw : stored == real           —— 原样字节（PAK/RSB 等，自带内部压缩）
  lzo : stored != real           —— 若干 LZO1X 子流 {u32 clen}{u32 rlen}{payload}
                                  子流按 16,384 B 解压块切分（ceil(real/16384) 段）

用法：
    python tools\dlc\rebuild.py --identity                  # 无改动重建 → 必须逐字节等于原盘
    python tools\dlc\rebuild.py --replace GR#576=payload.bin --out new.iso
    python tools\dlc\rebuild.py --replace EN_STRINGS.RES=new.bin --out new.iso
"""
import argparse
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dlclib as L                                            # noqa: E402

SEC = 2048
CHUNK = 16384                      # LZO 子流解压块 (实证: ceil(real/16384) == 子流数)
ALIGN = 16                         # 条目载荷起点对齐 (实证: 原盘全部 16 对齐)
GR_LBA = L.GR_LBA
TAB_OFF = L.TAB_OFF
TAB_STEP = L.TAB_STEP


def align_up(x, a=ALIGN):
    return (x + a - 1) // a * a


def P(*a):
    print(' '.join(str(x) for x in a), flush=True)


def frame_for_blob(blob):
    """把一个资源 blob 重新打包成 LZO 子流帧（16,384 B 一块）。"""
    chunks = []
    for off in range(0, len(blob), CHUNK):
        part = blob[off:off + CHUNK]
        chunks.append((part, len(part)))
    return L.lzo_pack(chunks)


def prepare_storage(orig_entry, packed_orig, new_blob=None, new_raw=None):
    """算一个条目在新盘上的 (stored, real, data_bytes)。

    · new_blob 给定：按原条目的形态（lzo/raw）重新封装（lzo → 16KB 子流帧）
    · new_raw  给定：直接用这份盘上字节（必须是完整帧/raw），real 由参数或推断
    · 都不给：原样搬运
    """
    kind = 'lzo' if orig_entry['stored'] != orig_entry['real'] else 'raw'
    if new_blob is not None:
        if kind == 'raw':
            data = bytes(new_blob)
        else:
            data = frame_for_blob(bytes(new_blob))
        return dict(kind=kind, stored=len(data), real=len(new_blob), data=data)
    if new_raw is not None:
        data = bytes(new_raw)
        real = orig_entry['real']
        return dict(kind=kind, stored=len(data), real=real, data=data)
    return dict(kind=kind, stored=orig_entry['stored'], real=orig_entry['real'],
                data=bytes(packed_orig))


def entry_alignment(entries):
    """从原盘布局推导每个条目的起始对齐要求（16 或 2048）。

    实证（docs/ANALYSIS_ISO.md）：绝大多数条目 16 对齐；.PSS 视频流等 42 条要求
    2048 对齐（原盘上一段内容结束处到该条目的 gap 恰好补到 2048 边界）。
    规则：若 off % 2048 == 0 且 align_up(prev_end, 2048) == off ⇒ 2048；否则 16。
    """
    out = []
    prev_end = None
    for e in entries:
        if prev_end is None:
            out.append(16)
        elif e['off'] % 2048 == 0 and align_up(prev_end, 2048) == e['off']:
            out.append(2048)
        else:
            out.append(16)
        prev_end = e['off'] + e['stored']
    return out


def build_img(iso, entries, blob_repl=None):
    """构造新 GR.IMG 的规划（不写盘）。

    blob_repl: {条目名 或 条目号: 新 blob bytes}   ← payload 层替换
    返回 dict(entries=[...], total_bytes=..., header=bytes, table=bytes)
    """
    blob_repl = dict(blob_repl or {})
    header = bytes(iso.mm[GR_LBA * SEC:GR_LBA * SEC + TAB_OFF])
    names_off = struct.unpack_from('<I', header, 0x10)[0]
    names_end = struct.unpack_from('<I', header, 0x4)[0]
    payload_off = struct.unpack_from('<I', header, 0x14)[0]
    assert payload_off >= names_end, '载荷起点必须 >= 名字区结束'
    aligns = entry_alignment(entries)
    gr_size = iso.find_root('GR.IMG')['size']
    trailing = gr_size - (entries[-1]['off'] + entries[-1]['stored'])
    assert trailing >= 0

    plan = []
    cur = payload_off
    for k, e in enumerate(entries):
        repl = None
        if e['idx'] in blob_repl:
            repl = blob_repl[e['idx']]
        elif e['name'] in blob_repl:
            repl = blob_repl[e['name']]
        packed_orig = bytes(iso.mm[e['iso_off']:e['iso_off'] + e['stored']])
        if repl is not None:
            st = prepare_storage(e, packed_orig, new_blob=repl)
        else:
            st = prepare_storage(e, packed_orig)
        off = align_up(cur, aligns[k])
        cur = off + st['stored']
        plan.append(dict(idx=e['idx'], name=e['name'], off=off,
                         stored=st['stored'], real=st['real'],
                         data=st['data'], kind=st['kind'], replaced=repl is not None,
                         align=aligns[k]))
    total = cur + trailing

    # IMG 头部区（0 .. payload_off）原样拷贝，只改条目表里每项的 [6]stored [7]real [8]off。
    # 头部区里还包含：0x830 的条目表、表后 2400 B 辅助区、names 起点前 16 KB 的数据块
    # （+0x20 指向它）—— 这些都必须逐字节保留，不能自己重建（identity 教训）。
    hdr = bytearray(iso.mm[GR_LBA * SEC:GR_LBA * SEC + payload_off])
    struct.pack_into('<I', hdr, 0x0, total)          # IMG 声明大小（= 根目录里的文件长度）
    for p in plan:
        o = TAB_OFF + p['idx'] * TAB_STEP
        struct.pack_into('<III', hdr, o + 24, p['stored'], p['real'], p['off'])
    return dict(plan=plan, total_bytes=total, header=bytes(hdr),
                payload_off=payload_off, trailing=trailing)


def rebuild_iso(src_iso, out_iso, blob_repl=None, elf_bytes=None, verbose=True):
    """从原盘重建一张新 ISO。blob_repl 见 build_img；elf_bytes 给定时替换 ELF。"""
    t0 = time.time()
    src = L.Iso(src_iso)
    entries = L.img_entries(src)
    img = build_img(src, entries, blob_repl)

    src_elf_entry = src.find_root('SLUS_208.20')
    gr_entry = src.find_root('GR.IMG')
    assert gr_entry is not None and src_elf_entry is not None

    # 新 ISO 尺寸 = 前段(到 GR.IMG 起点) + 新 GR.IMG 长度，再补到扇区。
    # 不缩盘：若新 IMG 不比原盘大，保留原 ISO 尺寸（尾部本来是 0 填充）。
    img_start = GR_LBA * SEC
    new_img_bytes = img['total_bytes']
    new_iso_size = max(src.size, align_up(img_start + new_img_bytes, SEC))
    # ELF 变长会推动其后的文件位置 —— 本工程约定 ELF 等长或更短（回填 0）。
    elf_entry = src_elf_entry
    if elf_bytes is not None:
        assert len(elf_bytes) <= elf_entry['size'], 'ELF 不允许变长（会推动后续文件）'
        elf_slot = bytes(src.mm[elf_entry['lba'] * SEC:
                                elf_entry['lba'] * SEC + elf_entry['size']])

    tmp = out_iso + '.part'
    if os.path.exists(out_iso):
        raise SystemExit('输出已存在，拒绝覆盖: %s' % out_iso)
    os.makedirs(os.path.dirname(os.path.abspath(out_iso)) or '.', exist_ok=True)

    # ── 写盘：前缀 + GR.IMG 头/表/名字 + 载荷区 ──
    with open(src.path, 'rb') as fi, open(tmp, 'w+b') as fo:
        fo.truncate(new_iso_size)
        # [1] GR.IMG 之前的全部字节
        fi.seek(0)
        left = img_start
        while left > 0:
            n = min(left, 1 << 24)
            fo.write(fi.read(n))
            left -= n
        # [2] GR.IMG 头部区（0 .. payload_off）逐字节拷贝，条目表已按新布局改好
        fo.write(img['header'])
        # [3] 载荷区：按规划逐条 seek 写入（洞/对齐填充 = 0，由 truncate 保证）
        for p in img['plan']:
            fo.seek(img_start + p['off'])
            fo.write(p['data'])
        # [4] 收尾：改 PVD volume_space + root dir 里 GR.IMG 长度；写 ELF
        fo.seek(16 * SEC)
        pvd = bytearray(fo.read(SEC))
        struct.pack_into('<I', pvd, 80, new_iso_size // SEC)     # LE
        struct.pack_into('>I', pvd, 84, new_iso_size // SEC)     # BE
        fo.seek(16 * SEC)
        fo.write(pvd)
        # 根目录记录：重新解析并在原位置改 GR.IMG 大小（LE@+10, BE@+14）
        pvd = src.pvd()
        leaf = pvd['root_lba'] * SEC
        root_len = (pvd['root_size'] + SEC - 1) // SEC * SEC
        fo.seek(leaf)
        rootdir = bytearray(fo.read(root_len))
        off = 0
        done = False
        while off + 33 < root_len:
            ln = rootdir[off]
            if ln == 0:
                off = (off // SEC + 1) * SEC
                continue
            namelen = rootdir[off + 32]
            nm = bytes(rootdir[off + 33:off + 33 + namelen]).decode('latin-1')
            if nm.split(';')[0] == 'GR.IMG':
                struct.pack_into('<I', rootdir, off + 10, new_img_bytes)
                struct.pack_into('>I', rootdir, off + 14, new_img_bytes)
                done = True
                break
            off += ln
        assert done, '根目录里找不到 GR.IMG'
        fo.seek(leaf)
        fo.write(rootdir)
        # ELF（等长替换 / 回填 0）
        if elf_bytes is not None:
            slot = bytearray(elf_slot)
            slot[:len(elf_bytes)] = elf_bytes
            fo.seek(elf_entry['lba'] * SEC)
            fo.write(bytes(slot))
        # 原盘 GR.IMG 之后、ISO 末尾之间还有一小段数据（原盘尾部 14 个非零字节，
        # 见 identity 测试）；按「距文件尾相同距离」原样搬过去。
        orig_tail_len = src.size - (img_start + gr_entry['size'])
        if orig_tail_len > 0:
            tail = bytes(src.mm[img_start + gr_entry['size']:src.size])
            fo.seek(new_iso_size - orig_tail_len)
            fo.write(tail)
        fo.flush()
    os.replace(tmp, out_iso)
    if verbose:
        P('[rebuild] %s -> %s' % (os.path.basename(src_iso), os.path.basename(out_iso)))
        P('          新 ISO %d B (%d 扇区, Δ%+d) ; 新 GR.IMG %d B (Δ%+d) ; 用时 %.1fs'
          % (new_iso_size, new_iso_size // SEC, new_iso_size - src.size,
             new_img_bytes, new_img_bytes - gr_entry['size'], time.time() - t0))
    src.close()
    return dict(out=out_iso, bytes=new_iso_size, img_bytes=new_img_bytes,
                plan=img['plan'])


def verify_identity(orig_iso, new_iso, verbose=True):
    """校验「无改动重建」是否逐字节等于原盘（最强布局自证）。"""
    a = L.sha256_file(orig_iso)
    b = L.sha256_file(new_iso)
    if verbose:
        P('[identity] orig %s' % a)
        P('[identity] new  %s' % b)
        P('[identity]', 'OK 逐字节相同' if a == b else 'FAIL 不同')
    return a == b


def main(argv):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                          # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description='从英文原盘重建汉化 ISO（payload 级替换）')
    ap.add_argument('--iso', default=L.DEFAULT_ISO, help='英文原盘（只读基底）')
    ap.add_argument('--out', help='输出 ISO（必须不存在）')
    ap.add_argument('--replace', action='append', default=[],
                    help='替换：<条目名或条目号>=<blob 文件>，可多次')
    ap.add_argument('--elf', help='新 ELF 文件（必须 <= 原 ELF 长度，等长或回填 0）')
    ap.add_argument('--identity', action='store_true',
                    help='无改动重建，并校验与原盘逐字节相同')
    ap.add_argument('--dry', action='store_true', help='只打印规划，不写盘')
    a = ap.parse_args(argv)

    repl = {}
    for spec in a.replace:
        key, _, path = spec.partition('=')
        blob = open(path, 'rb').read()
        if key.startswith('GR#'):
            repl[int(key[3:])] = blob
        else:
            repl[key] = blob
        P('[input] 替换 %s <- %s (%d B)' % (key, path, len(blob)))
    elf = open(a.elf, 'rb').read() if a.elf else None

    if a.dry or (a.identity and not a.out):
        src = L.Iso(a.iso)
        entries = L.img_entries(src)
        img = build_img(src, entries, repl)
        P('[dry] 新 GR.IMG %d B ; 替换 %d 条' % (img['total_bytes'], len(repl)))
        for p in img['plan']:
            if p['replaced']:
                P('        #%d %-28s off=%-10d stored=%-8d real=%-8d' %
                  (p['idx'], p['name'], p['off'], p['stored'], p['real']))
        src.close()
        return 0

    assert a.out, '--out 必填（--identity 也要给 --out）'
    rebuild_iso(a.iso, a.out, repl, elf_bytes=elf)
    if a.identity:
        ok = verify_identity(a.iso, a.out)
        assert ok, 'identity 失败：无改动重建与原盘不一致'
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
