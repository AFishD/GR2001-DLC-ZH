# -*- coding: utf-8 -*-
"""make_trace_probe19.py —— Hook 文本 setter 0x3FF7E0 入口（只用 t 寄存器，132B cave）：
只记录「首字节>=0x80」或「首字节=空格且第二字节>=0x80」的字符串
{ptr, ra, 前 16B} 到 0x1FFF000 的 64 项环形缓冲。
"""
import shutil

SRC = r'work\builds\v25r.iso'
DST = r'work\builds\probe_trace19.iso'
ELF_ABS = 296 * 2048
CAVE_VA = 0x180D00
RING = 0x01FFF000

hi = (RING >> 16) & 0xFFFF
lo = RING & 0xFFFF


def op_i(op, rs, rt, imm):
    return (op << 26) | ((rs & 0x1F) << 21) | ((rt & 0x1F) << 16) | (imm & 0xFFFF)


def br(op, rs, rt, at, target):
    return op_i(op, rs, rt, (target - (at + 1)) & 0xFFFF)


LUI = op_i(0x0F, 0, 9, hi)
ORI = op_i(0x0D, 9, 9, lo)
cave = [
    LUI,                                  # 0
    ORI,                                  # 1
    op_i(0x0B, 5, 3, 0x1000),             # 2  sltiu t3, a1, 0x1000
    br(0x05, 11, 0, 3, 32),               # 3  bne t3,zero, skip
    0,                                    # 4
    0x80AB0000,                           # 5  lb t3, 0(a1)
    op_i(0x0C, 11, 12, 0x80),             # 6  andi t4, t3, 0x80
    br(0x05, 12, 0, 7, 16),               # 7  bne t4,zero, record
    0,                                    # 8
    op_i(0x09, 0, 12, 0x20),              # 9  addiu t4, zero, 0x20
    br(0x05, 11, 12, 10, 32),             # 10 bne t3,t4, skip
    0,                                    # 11
    0x80AC0001,                           # 12 lb t4, 1(a1)
    op_i(0x0C, 12, 12, 0x80),             # 13 andi t4, t4, 0x80
    br(0x04, 12, 0, 14, 32),              # 14 beq t4,zero, skip
    0,                                    # 15
    0xAD3F0C00,                           # 16 sw ra, 0xC00(t1)
    0x8D2A0000,                           # 17 lw t2, 0(t1)
    0x214B0001,                           # 18 addiu t3, t2, 1
    0xAD2B0000,                           # 19 sw t3, 0(t1)
    0x314A003F,                           # 20 andi t2, t2, 0x3F
    0x000A5140,                           # 21 sll t2, t2, 5
    0x01495021,                           # 22 addu t2, t2, t1
    0x214A0100,                           # 23 addiu t2, t2, 0x100
    0xAD450000,                           # 24 sw a1, 0(t2)
    0xAD5F0004,                           # 25 sw ra, 4(t2)
    0x8CAC0000, 0xAD4C0008,               # 26/27
    0x8CAC0004, 0xAD4C000C,               # 28/29
    0x8CAC0008, 0xAD4C0010,               # 30/31
    0x27BDFFD0,                           # 32 addiu sp, sp, -48
    0x080FFDF9,                           # 33 j 0x3FF7E4
    0x00000000,                           # 34
]
jal_cave = 0x0C000000 | ((CAVE_VA >> 2) & 0x03FFFFFF)

shutil.copy2(SRC, DST)
with open(DST, 'r+b') as f:
    f.seek(ELF_ABS + (CAVE_VA - 0xFFF00))
    for w in cave:
        f.write(w.to_bytes(4, 'little'))
    f.seek(ELF_ABS + (0x3FF7E0 - 0xFFF00))
    f.write(jal_cave.to_bytes(4, 'little'))
print('probe19 rebuilt: words', len(cave), 'bytes', len(cave) * 4,
      'branch3', hex(cave[3]), 'branch7', hex(cave[7]), 'branch10', hex(cave[10]), 'branch14', hex(cave[14]))
