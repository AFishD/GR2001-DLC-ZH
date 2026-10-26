# -*- coding: utf-8 -*-
"""make_trace_probe15.py —— Hook RSFont::DrawString(0x2195F0) 入口，环形记录
每次绘制的 (font*, string*, 前 12 字节) 到 EE RAM 0x640000（512 项）。
用于判断：绘制兵种名时拿到的字节是干净的还是已被改坏。
"""
import shutil

SRC = r'work\builds\v25r.iso'
DST = r'work\builds\probe_trace17.iso'
ELF_ABS = 296 * 2048
CAVE_VA = 0x180D00
RING = 0x01FFF000

hi = (RING >> 16) & 0xFFFF
lo = RING & 0xFFFF
cave = [
    (0x0F << 26) | (9 << 16) | hi,          # lui t1, 0x0064
    (0x0D << 26) | (9 << 21) | (9 << 16) | lo,  # ori t1,t1,0
    0x8D2A0000,   # lw t2,0(t1)
    0x214B0001,   # addiu t3,t2,1
    0xAD2B0000,   # sw t3,0(t1)
    0x314A003F,   # andi t2,t2,0x3F
    0x000A5140,   # sll t2,t2,5
    0x01495021,   # addu t2,t2,t1
    0x214A0010,   # addiu t2,t2,0x10
    0xAD440000,   # sw a0,0(t2)
    0xAD450004,   # sw a1,4(t2)
    0x10A0000A,   # beq a1,zero, skip
    0x00000000,
    0x2CA31000,   # sltiu t3,a1,0x10000
    0x14600007,   # bne t3,zero, skip
    0x00000000,
    0x8CAB0000, 0xAD4B0008,
    0x8CAB0004, 0xAD4B000C,
    0x8CAB0008, 0xAD4B0010,
    0x27BDFF20,   # addiu sp,sp,-224 (原首指令)
    0x0808657D,   # j 0x2195F4
    0x00000000,
]
jal_cave = 0x0C000000 | ((CAVE_VA >> 2) & 0x03FFFFFF)

shutil.copy2(SRC, DST)
with open(DST, 'r+b') as f:
    f.seek(ELF_ABS + (CAVE_VA - 0xFFF00))
    for w in cave:
        f.write(w.to_bytes(4, 'little'))
    f.seek(ELF_ABS + (0x2195F0 - 0xFFF00))
    f.write(jal_cave.to_bytes(4, 'little'))
print('trace probe15 built:', DST)
