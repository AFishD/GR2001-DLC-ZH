# -*- coding: utf-8 -*-
"""make_trace_probe13.py —— 在 0x3FF500（jal 0x3FF830，此时 a1 已是 char* 文本缓冲）插桩，
环形记录最近 32 次「控件文本」的字符串（ptr+20B），写到 0x1FFF000。
"""
import shutil

SRC = r'work\builds\v25r.iso'
DST = r'work\builds\probe_trace13.iso'
ELF_ABS = 296 * 2048
CAVE_VA = 0x180D00
RING = 0x01FFF000

hi = (RING >> 16) & 0xFFFF
lo = RING & 0xFFFF
LUI = (0x0F << 26) | (9 << 16) | hi
ORI = (0x0D << 26) | (9 << 21) | (9 << 16) | lo
cave = [
    LUI, ORI,
    0xAD3F0C00,               # sw ra, 0xC00(t1)
    0x8D2A0000,               # lw t2,0(t1)
    0x214B0001,               # addiu t3,t2,1
    0xAD2B0000,               # sw t3,0(t1)
    0x314A001F,               # andi t2,t2,0x1F
    0x000A5140,               # sll t2,t2,5
    0x01495021,               # addu t2,t2,t1
    0x214A0100,               # addiu t2,t2,0x100
    0xAD450000,               # sw a1,0(t2)
    0x10A00008,               # beq a1,zero, skip
    0x00000000,
    0x8CAB0000, 0xAD4B0004,
    0x8CAB0004, 0xAD4B0008,
    0x8CAB0008, 0xAD4B000C,
    0x8CAB000C, 0xAD4B0010,
    0x8CAB0010, 0xAD4B0014,
    0x8CAB0014, 0xAD4B0018,
    0x0C0FFE0C,               # jal 0x3FF830
    0x00000000,
    LUI, ORI,
    0x8D3F0C00,               # lw ra,0xC00(t1)
    0x03E00008,
    0x00000000,
]
# skip 目标：beq 在索引 11，目标为索引 24（jal 前），offset = 24-12 = 12
cave[11] = 0x10A0000C
jal_cave = 0x0C000000 | ((CAVE_VA >> 2) & 0x03FFFFFF)

shutil.copy2(SRC, DST)
with open(DST, 'r+b') as f:
    f.seek(ELF_ABS + (CAVE_VA - 0xFFF00))
    for w in cave:
        f.write(w.to_bytes(4, 'little'))
    f.seek(ELF_ABS + (0x3FF500 - 0xFFF00))
    f.write(jal_cave.to_bytes(4, 'little'))
print('trace probe13 built:', DST, 'cave words', len(cave))
