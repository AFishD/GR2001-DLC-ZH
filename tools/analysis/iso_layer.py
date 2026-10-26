# -*- coding: utf-8 -*-
r"""iso_layer.py —— ISO9660 层分析（《幽灵行动：丛林风暴》PS2 / SLUS-20820）。

全只读。输出：
  · PVD 全字段（LE/BE 双写校验）、卷空间、路径表；
  · 根目录 / MODULES / LICENSE 三个目录的全部记录（名字/LBA/大小/flag）；
  · SYSTEM.CNF、SLUS_208.20（ELF 头）、DNAS.BIN / OFFLINE.BIN / ONLINE.BIN 的性质判定；
  · 空间账本：每个文件的 LBA extent、相邻分配间隙、未分配扇区、卷尾余量；
  · 「对汉化的结论」所需的扩盘余量数字（GR.IMG 前后空隙 / 可搬迁窗口）。

用法：
  python tools/analysis/iso_layer.py                       # 打印 + 写 work/analysis/iso/iso_layer.json
  python tools/analysis/iso_layer.py --iso <path>          # 指定 ISO（默认英文原盘）
  python tools/analysis/iso_layer.py --json <path>         # 指定 JSON 输出
  python tools/analysis/iso_layer.py --no-sha256           # 跳过全盘 sha256（快）
  python tools/analysis/iso_layer.py --help
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
import dlclib  # noqa: E402

SEC = 2048


def P(*a):
    print(' '.join(str(x) for x in a), flush=True)


def sha256_file(path, buf=1 << 22):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(buf), b''):
            h.update(chunk)
    return h.hexdigest()


def iso_date(b):
    """ISO9660 17 字节日期 → dict（'0000000000000000' 表示未设置）。

    第 17 字节 = 带符号 GMT 偏移，单位 15 分钟（0x24 = +9h）。
    """
    s = b.decode('latin-1')
    if not s.strip('0'):
        return None
    tz_raw = ord(s[16]) if len(s) > 16 else 0
    tz_q = tz_raw - 256 if tz_raw > 127 else tz_raw
    return dict(str=s,
                year=int(s[0:4]), month=int(s[4:6]), day=int(s[6:8]),
                hour=int(s[8:10]), minute=int(s[10:12]), second=int(s[12:14]),
                tz_quarters=tz_q, tz_hours=tz_q / 4.0)


def iso_date7(b):
    """ISO9660 目录记录 7 字节日期（年自 1900，末字节=GMT 偏移/15min）。"""
    if len(b) < 7:
        return None
    tz_raw = b[6]
    tz_q = tz_raw - 256 if tz_raw > 127 else tz_raw
    return dict(year=b[0] + 1900, month=b[1], day=b[2], hour=b[3], minute=b[4],
                second=b[5], tz_quarters=tz_q, tz_hours=tz_q / 4.0)


def read_dir(iso, lba, size):
    """解析一个目录 extent 的记录表。"""
    data = iso.read(lba * SEC, size)
    out = []
    off = 0
    while off + 33 <= len(data):
        ln = data[off]
        if ln == 0:
            off = (off // SEC + 1) * SEC
            if off >= len(data):
                break
            continue
        if off + ln > len(data):
            break
        rec = data[off:off + ln]
        ext = struct.unpack_from('<I', rec, 2)[0]
        ext_be = struct.unpack_from('>I', rec, 6)[0]
        sz = struct.unpack_from('<I', rec, 10)[0]
        sz_be = struct.unpack_from('>I', rec, 14)[0]
        flags = rec[25]
        nl = rec[32]
        nm = rec[33:33 + nl].decode('latin-1')
        out.append(dict(name=nm, lba=ext, lba_be=ext_be, size=sz, size_be=sz_be,
                        flags=flags, is_dir=bool(flags & 2), rec_len=ln,
                        rec_off=off, date=iso_date7(rec[18:25])))
        off += ln
    return out


def walk(iso, lba, size, prefix, out):
    for r in read_dir(iso, lba, size):
        if r['name'] in ('\x00', '\x01'):
            continue
        path = prefix + '/' + r['name'] if prefix else r['name']
        ent = dict(path=path, name=r['name'], lba=r['lba'], size=r['size'],
                   flags=r['flags'], is_dir=r['is_dir'], date=r['date'])
        out.append(ent)
        if r['is_dir']:
            walk(iso, r['lba'], r['size'], path, out)


def ident_binary(blob):
    """粗判二进制文件的类型（ELF / MWo3 私有头 / IRX / 文本 / 未知）。"""
    if blob[:4] == b'\x7fELF':
        return dict(type='ELF', note='标准 ELF（PS2 主程序/模块）')
    if blob[:4] == b'MWo3':
        idx = struct.unpack_from('<I', blob, 4)[0] if len(blob) >= 8 else None
        return dict(type='MWo3', note='私有 "MWo3" 头 + u32 序号 %s（推测：加密/封装 MIPS 模块载荷，'
                                      '与汉化无关）' % idx)
    if blob[:4] == b'PS-X':
        return dict(type='PS-X EXE', note='PS1/PS2 可执行')
    printable = sum(1 for c in blob[:4096] if 32 <= c < 127 or c in (9, 10, 13))
    if printable / max(1, min(len(blob), 4096)) > 0.9:
        return dict(type='text', note='纯文本（可打印占比 %.0f%%）' % (100.0 * printable / min(len(blob), 4096)))
    return dict(type='binary', note='未知二进制')


def main():
    ap = argparse.ArgumentParser(description='ISO9660 层 + 关键文件性质分析（只读）')
    ap.add_argument('--iso', default=dlclib.DEFAULT_ISO)
    ap.add_argument('--json', default=os.path.join(REPO, 'work', 'analysis', 'iso', 'iso_layer.json'))
    ap.add_argument('--no-sha256', action='store_true', help='跳过全盘/ELF sha256')
    args = ap.parse_args()

    iso = dlclib.Iso(args.iso)
    out = dict(schema='iso_layer/1', iso=os.path.basename(iso.path), iso_bytes=iso.size,
               sector_size=SEC, sectors=iso.size // SEC,
               iso_bytes_aligned=(iso.size % SEC == 0))
    if not args.no_sha256:
        out['iso_sha256'] = sha256_file(iso.path)
    P('[iso] %s  %d B  %d 扇区' % (iso.path, iso.size, iso.size // SEC))
    if 'iso_sha256' in out:
        P('      sha256 %s %s' % (out['iso_sha256'],
                                  '(== 基线)' if out['iso_sha256'] == dlclib.ISO_SHA256 else '(!! 与基线不同)'))

    # ── PVD ──
    P('\n=== 1) ISO9660 PVD（扇区 16）===')
    pvd_raw = iso.sector(16)
    assert pvd_raw[1:6] == b'CD001' and pvd_raw[0] == 1
    def field(b, off, n, enc='latin-1'):
        return b[off:off + n].rstrip(b'\x00 ').decode(enc, 'replace')
    pvd = dict(
        type=pvd_raw[0], id=pvd_raw[1:6].decode(),
        version=pvd_raw[6],
        system_id=field(pvd_raw, 8, 32),
        volume_id=field(pvd_raw, 40, 32),
        volume_space_size_le=struct.unpack_from('<I', pvd_raw, 80)[0],
        volume_space_size_be=struct.unpack_from('>I', pvd_raw, 84)[0],
        volume_set_size=struct.unpack_from('<H', pvd_raw, 120)[0],
        volume_seq_no=struct.unpack_from('<H', pvd_raw, 124)[0],
        logical_block_size=struct.unpack_from('<H', pvd_raw, 128)[0],
        path_table_size=struct.unpack_from('<I', pvd_raw, 132)[0],
        path_table_l_lba=struct.unpack_from('<I', pvd_raw, 140)[0],
        path_table_l_opt_lba=struct.unpack_from('<I', pvd_raw, 144)[0],
        path_table_m_lba=struct.unpack_from('>I', pvd_raw, 148)[0],
        path_table_m_opt_lba=struct.unpack_from('>I', pvd_raw, 152)[0],
        root_dir=dict(lba=struct.unpack_from('<I', pvd_raw, 158)[0],
                      size=struct.unpack_from('<I', pvd_raw, 166)[0]),
        volume_set_id=field(pvd_raw, 190, 128),
        publisher=field(pvd_raw, 318, 128),
        data_preparer=field(pvd_raw, 446, 128),
        application=field(pvd_raw, 574, 128),
        copyright_file=field(pvd_raw, 702, 38),
        abstract_file=field(pvd_raw, 740, 38),
        bibliographic_file=field(pvd_raw, 778, 38),
        created=iso_date(pvd_raw[813:830]),
        modified=iso_date(pvd_raw[830:847]),
        expires=iso_date(pvd_raw[847:864]),
        effective=iso_date(pvd_raw[864:881]),
        file_structure_version=pvd_raw[881],
        app_use_1=pvd_raw[883:883 + 141].rstrip(b'\x00').decode('latin-1'),
        app_use_2=pvd_raw[1395:1395 + 91].rstrip(b'\x00').decode('latin-1'),
    )
    # 第 17 扇区 = SVD（卷终结符 / 补充卷描述符）
    svd = iso.sector(17)
    pvd['sector17'] = dict(type=svd[0], id=svd[1:6].decode('latin-1'),
                           note='SVD(2)或终结符(255)')
    out['pvd'] = pvd
    P('  卷标 %s | 系统标识 %r | 卷空间 %d 扇区(%d B)'
      % (pvd['volume_id'], pvd['system_id'], pvd['volume_space_size_le'],
         pvd['volume_space_size_le'] * SEC))
    P('  逻辑块 %d | 路径表 size=%d L@%d (opt %d) M@%d (opt %d) | 根目录 @%d size=%d | 第17扇区 type=%d'
      % (pvd['logical_block_size'], pvd['path_table_size'], pvd['path_table_l_lba'],
         pvd['path_table_l_opt_lba'], pvd['path_table_m_lba'], pvd['path_table_m_opt_lba'],
         pvd['root_dir']['lba'], pvd['root_dir']['size'], svd[0]))
    P('  创建 %s | 修改 %s | 生效 %s'
      % (pvd['created'], pvd['modified'], pvd['effective']))
    assert pvd['volume_space_size_le'] == pvd['volume_space_size_be'], '卷空间 LE/BE 不一致'
    assert pvd['volume_space_size_le'] * SEC == iso.size, '卷空间与实际大小不一致'

    # ── 路径表 ──
    pt = iso.read(pvd['path_table_l_lba'] * SEC, pvd['path_table_size'])
    paths = []
    p = 0
    while p + 8 <= len(pt):
        nl = pt[p]
        if nl == 0:
            break
        ext = struct.unpack_from('<I', pt, p + 2)[0]
        parent = struct.unpack_from('<H', pt, p + 6)[0]
        nm = pt[p + 8:p + 8 + nl]
        if nm and nm[:1] != b'\x00':
            paths.append(dict(name=nm.decode('latin-1'), lba=ext, parent=parent))
        p += 8 + nl + (nl & 1)
    out['path_table'] = dict(size=pvd['path_table_size'], lba=pvd['path_table_l_lba'],
                             entries=paths)
    P('  路径表条目 %d: %s' % (len(paths), [(x['name'], x['lba']) for x in paths]))

    # ── 目录树 ──
    P('\n=== 2) 目录树与文件布局 ===')
    tree = []
    walk(iso, pvd['root_dir']['lba'], pvd['root_dir']['size'], '', tree)
    files = [x for x in tree if not x['is_dir']]
    dirs = [x for x in tree if x['is_dir']]
    P('  目录 %d 个 / 文件 %d 个' % (len(dirs), len(files)))
    for x in tree:
        P('    %-30s %-8s LBA=%-7d size=%-11d sectors=%-6d flags=0x%02x'
          % (x['path'], 'DIR' if x['is_dir'] else 'FILE', x['lba'], x['size'],
             (x['size'] + SEC - 1) // SEC, x['flags']))

    # ── 关键文件 ──
    P('\n=== 3) 关键文件性质 ===')
    key = {}
    for x in [y for y in files if y['path'] in
              ('SYSTEM.CNF;1', 'SLUS_208.20;1', 'DNAS.BIN;1', 'OFFLINE.BIN;1',
               'ONLINE.BIN;1', 'GR.IMG;1')] + \
             [y for y in files if 'MODULES' in y['path'] or 'LICENSE' in y['path']]:
        head = iso.read(x['lba'] * SEC, min(x['size'], 256))
        info = ident_binary(head)
        info.update(name=x['name'], lba=x['lba'], size=x['size'],
                    sectors=(x['size'] + SEC - 1) // SEC)
        if not args.no_sha256 and x['size'] <= 20 << 20:
            info['sha256'] = sha256_file_iso(iso, x)
        key[x['path']] = info
        P('  %-30s LBA=%-6d size=%-11d %-8s %s'
          % (x['path'], x['lba'], x['size'], info['type'], info['note']))
    out['key_files'] = key

    # SYSTEM.CNF 正文
    cnf = iso.find_root('SYSTEM.CNF')
    out['system_cnf'] = iso.read(cnf['lba'] * SEC, cnf['size']).decode('latin-1')
    P('  SYSTEM.CNF = %r' % out['system_cnf'])

    # ELF 头
    elf = iso.find_root('SLUS_208.20')
    eb = iso.read(elf['lba'] * SEC, 52)
    ehdr = dict(magic=eb[:4].hex(), klass=eb[4], endian=eb[5], version=eb[6],
                osabi=eb[7], type=struct.unpack_from('<H', eb, 16)[0],
                machine=struct.unpack_from('<H', eb, 18)[0],
                entry=struct.unpack_from('<I', eb, 24)[0],
                phoff=struct.unpack_from('<I', eb, 28)[0],
                shoff=struct.unpack_from('<I', eb, 32)[0],
                flags=struct.unpack_from('<I', eb, 36)[0],
                ehsize=struct.unpack_from('<H', eb, 40)[0],
                phentsize=struct.unpack_from('<H', eb, 42)[0],
                phnum=struct.unpack_from('<H', eb, 44)[0],
                shentsize=struct.unpack_from('<H', eb, 46)[0],
                shnum=struct.unpack_from('<H', eb, 48)[0],
                shstrndx=struct.unpack_from('<H', eb, 50)[0])
    out['elf_header'] = ehdr
    P('  ELF: type=%d machine=%d(8=MIPS) entry=0x%X phnum=%d phoff=0x%X'
      % (ehdr['type'], ehdr['machine'], ehdr['entry'], ehdr['phnum'], ehdr['phoff']))
    # 程序头（LOAD 段）
    phs = []
    for i in range(ehdr['phnum']):
        off = ehdr['phoff'] + i * ehdr['phentsize']
        ph = iso.read(elf['lba'] * SEC + off, 32)
        typ, poff, vaddr, paddr, filesz, memsz, pflags, align = struct.unpack('<8I', ph)
        phs.append(dict(type=typ, offset=poff, vaddr=vaddr, paddr=paddr,
                        filesz=filesz, memsz=memsz, flags=pflags, align=align))
    out['elf_program_headers'] = phs
    for ph in phs:
        if ph['type'] == 1:
            P('    LOAD off=0x%-8X vaddr=0x%08X filesz=%-9d memsz=%-9d flags=%d'
              % (ph['offset'], ph['vaddr'], ph['filesz'], ph['memsz'], ph['flags']))

    # ── 空间账本 ──
    P('\n=== 4) 空间账本（扩盘余量）===')
    alloc = []
    for x in dirs + files:
        s = (x['size'] + SEC - 1) // SEC
        alloc.append((x['lba'], s, x['lba'] + s, 'DIR ' if x['is_dir'] else 'FILE', x['path']))
    alloc.sort()
    total_sectors = iso.size // SEC
    used = 0
    gaps = []
    prev_end = 0
    for lba, ns, end, kind, path in alloc:
        if lba > prev_end:
            gaps.append(dict(start=prev_end, end=lba, sectors=lba - prev_end,
                             bytes=(lba - prev_end) * SEC,
                             after=alloc[alloc.index((lba, ns, end, kind, path)) - 1][4]
                             if prev_end else '(卷首)'))
        used += ns
        prev_end = max(prev_end, end)
    if prev_end < total_sectors:
        gaps.append(dict(start=prev_end, end=total_sectors, sectors=total_sectors - prev_end,
                         bytes=(total_sectors - prev_end) * SEC, after='(末尾)'))
    # 未分配 = 卷内不属于任何文件/目录 extent 的扇区
    ledger = dict(total_sectors=total_sectors, used_sectors=used,
                  free_sectors=total_sectors - used,
                  free_bytes=(total_sectors - used) * SEC,
                  gaps=[g for g in gaps if g['sectors'] > 0])
    out['space_ledger'] = ledger
    P('  卷 %d 扇区 / 已分配 %d / 未分配 %d (%.1f MB)'
      % (total_sectors, used, total_sectors - used,
         (total_sectors - used) * SEC / 1048576.0))
    for g in ledger['gaps']:
        if g['sectors'] >= 64:
            P('    空隙 %6d..%6d (%6d 扇区 = %8.1f KB) 位于 %s 之后'
              % (g['start'], g['end'], g['sectors'], g['bytes'] / 1024.0, g['after']))
    # 关键数字：GR.IMG 之前可搬迁/扩展的连续空间；GR.IMG 之后卷尾余量
    gr = iso.find_root('GR.IMG')
    gr_end_sector = gr['lba'] + (gr['size'] + SEC - 1) // SEC
    gaps_before = [g for g in ledger['gaps'] if g['end'] <= gr['lba']]
    largest_before = max(gaps_before, key=lambda g: g['sectors']) if gaps_before else None
    out['gr_img'] = dict(lba=gr['lba'], size=gr['size'],
                         sectors=(gr['size'] + SEC - 1) // SEC,
                         end_byte=gr['lba'] * SEC + gr['size'],
                         end_sector=gr_end_sector,
                         volume_end_byte=iso.size,
                         tail_bytes=iso.size - (gr['lba'] * SEC + gr['size']),
                         tail_sectors=(iso.size - (gr['lba'] * SEC + gr['size'])) // SEC,
                         largest_free_gap_before=largest_before,
                         note='GR.IMG 紧贴卷尾；卷内可用扩展空间见 space_ledger / '
                              'largest_free_gap_before（可把 GR.IMG 下移到该空隙处从而扩容）')
    P('  GR.IMG: LBA %d, %d B (%d 扇区), 结束于字节 %d；卷尾余 %d B (%d 扇区)'
      % (gr['lba'], gr['size'], (gr['size'] + SEC - 1) // SEC,
         gr['lba'] * SEC + gr['size'], iso.size - (gr['lba'] * SEC + gr['size']),
         (iso.size - (gr['lba'] * SEC + gr['size'])) // SEC))
    if largest_before:
        P('  GR.IMG 之前最大连续空闲: LBA %d..%d (%d 扇区 = %.2f MB) —— 可把 GR.IMG 整体前移并扩容'
          % (largest_before['start'], largest_before['end'], largest_before['sectors'],
             largest_before['bytes'] / 1048576.0))
    P('  ⇒ 扩盘方案：GR.IMG 可整体搬到此空隙（或把 GR.IMG 复制到卷尾新 LBA 并延长），'
      'ISO 总量上限 4.7GB(DVD5)，现用 %.1f%%' % (100.0 * iso.size / (4.7e9)))

    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    P('\n[out] %s (%.1f KB)' % (args.json, os.path.getsize(args.json) / 1024))
    iso.close()
    return 0


def sha256_file_iso(iso, ent):
    h = hashlib.sha256()
    left = ent['size']
    off = ent['lba'] * SEC
    while left > 0:
        n = min(left, 1 << 20)
        h.update(iso.read(off, n))
        off += n
        left -= n
    return h.hexdigest()


if __name__ == '__main__':
    sys.exit(main())
