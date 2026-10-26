# -*- coding: utf-8 -*-
"""make_trace_probe8.py —— 在 DBCS cave 之后的死函数区(0x180D00)放 marker cave，
验证该区域可安全执行 + 0x3FF7E0 setter 路径是否可达。"""
import shutil

SRC = r'work\builds\v25r.iso'
DST = r'work\builds\probe_trace8.iso'
ELF_ABS = 296 * 2048
CAVE_VA = 0x180D00
SCRATCH = 0x01FFF000

hi = (SCRATCH >> 16) & 0xFFFF
lo = SCRATCH & 0xFFFF
cave = [
    (0x0F << 26) | (9 << 16) | hi,
    (0x0D << 26) | (9 << 21) | (9 << 16) | lo,
    (0x0F << 26) | (10 << 16) | 0xDEAD,
    (0x0D << 26) | (10 << 21) | (10 << 16) | 0xBEEF,
    0xAD2A0000,   # sw t2, 0(t1)   marker
    0xAD3F0004,   # sw ra, 4(t1)
    0x0200282D,   # daddu a1, s0, zero
    0x0C103204,   # jal 0x40C810
    0x00000000,
    (0x0F << 26) | (9 << 16) | hi,
    (0x0D << 26) | (9 << 21) | (9 << 16) | lo,
    0x8D3F0004,   # lw ra, 4(t1)
    0x03E00008,
    0x00000000,
]
jal_cave = 0x0C000000 | ((CAVE_VA >> 2) & 0x03FFFFFF)

shutil.copy2(SRC, DST)
with open(DST, 'r+b') as f:
    f.seek(ELF_ABS + (CAVE_VA - 0xFFF00))
    for w in cave:
        f.write(w.to_bytes(4, 'little'))
    f.seek(ELF_ABS + (0x3FF808 - 0xFFF00))
    f.write(jal_cave.to_bytes(4, 'little'))
print('trace probe8 built:', DST)
