# -*- coding: utf-8 -*-
r"""elf_crc.py —— 算一张 PS2 ISO 里主 ELF 的 PCSX2 Game CRC (u32 异或)。

    python tools/final_fix/elf_crc.py --iso work/builds/GR_RELEASE/GR_ZH133.iso [--expect 653FBF69]

CRC 变了 ⇒ PCSX2 的即时存档名变了 (SLUS-20613 (<CRC>).01.p2s) ⇒ **旧存档对新盘无效, 必须新开**。
"""
import argparse
import hashlib
import os
import struct
import sys

ELF_NAME = 'SLUS_206.13'
SEC = 2048


def read_elf(path, name=ELF_NAME):
    with open(path, 'rb') as f:
        f.seek(16 * SEC)
        pvd = f.read(SEC)
        if pvd[1:6] != b'CD001':
            raise SystemExit('不是 ISO9660 映像: %s' % path)
        rlba = struct.unpack_from('<I', pvd, 158)[0]
        rsz = struct.unpack_from('<I', pvd, 166)[0]
        f.seek(rlba * SEC)
        d = f.read(rsz)
    off = 0
    while off < len(d) and d[off]:
        nm = d[off + 33:off + 33 + d[off + 32]].decode('latin-1').split(';')[0]
        if nm.upper() == name.upper():
            lba = struct.unpack_from('<I', d, off + 2)[0]
            sz = struct.unpack_from('<I', d, off + 10)[0]
            with open(path, 'rb') as f:
                f.seek(lba * SEC)
                elf = f.read(sz)
            if elf[:4] != b'\x7fELF':
                raise SystemExit('取到的不是 ELF')
            return elf, lba, sz
        off += d[off]
    raise SystemExit('ISO 里找不到 %s' % name)


def xor_crc32(data):
    c = 0
    for (w,) in struct.iter_unpack('<I', data[:len(data) // 4 * 4]):
        c ^= w
    return c & 0xFFFFFFFF


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--iso', required=True)
    ap.add_argument('--expect', default=None)
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                                 # noqa: BLE001
        pass
    elf, lba, sz = read_elf(a.iso)
    crc = xor_crc32(elf)
    print('  [ELF] %s  LBA %d  %d B  sha256 %s'
          % (os.path.basename(a.iso), lba, sz, hashlib.sha256(elf).hexdigest()))
    print('  [CRC] Game CRC = %08X   ⇒ 即时存档名 SLUS-20613 (%08X).01.p2s' % (crc, crc))
    if a.expect:
        ok = ('%08X' % crc) == a.expect.upper()
        print('  [%s] 与声明值 %s %s' % ('OK ' if ok else 'FAIL', a.expect.upper(),
                                        '一致' if ok else '不一致'))
        return 0 if ok else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
