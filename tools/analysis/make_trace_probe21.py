# -*- coding: utf-8 -*-
"""make_trace_probe21.py —— Hook interner 调用点 0x3FF808（s0 = 待设置字符串）：
只记录「首字节=0x20(空格) 且第二字节>=0x80」的字符串（兵种名形如 " 爆罗手"），
{ptr, 前4B} 到 0x1FFF000 环形缓冲；ra 存自身栈帧，避免用 k0。
"""
import shutil

SRC = r'work\builds\v25r.iso'
DST = r'work\builds\probe_trace21.iso'
ELF_ABS = 296 * 2048
CAVE_VA = 0x180D00
RING = 0x01FFF000


def op_i(op, rs, rt, imm):
    return (op << 26) | ((rs & 0x1F) << 21) | ((rt & 0x1F) << 16) | (imm & 0xFFFF)


def br(op, rs, rt, at, target):
    return op_i(op, rs, rt, (target - (at + 1)) & 0xFFFF)


hi, lo = (RING >> 16) & 0xFFFF, RING & 0xFFFF
SKIP = 25
cave = [
    op_i(0x09, 29, 29, -16),          # 0 addiu sp,sp,-16
    op_i(0x2B, 29, 31, 8),            # 1 sw ra,8(sp)
    op_i(0x0F, 0, 9, hi),             # 2 lui t1
    op_i(0x0D, 9, 9, lo),             # 3 ori t1
    op_i(0x0B, 16, 3, 0x1000),        # 4 sltiu t3,s0,0x1000
    br(0x05, 11, 0, 5, SKIP),         # 5 bne t3,zero,skip
    0,                                # 6
    0x820B0000,                       # 7 lb t3,0(s0)
    op_i(0x09, 0, 12, 0x20),          # 8 addiu t4,zero,0x20
    br(0x05, 11, 12, 9, SKIP),        # 9 bne t3,t4,skip
    0,                                # 10
    0x820C0001,                       # 11 lb t4,1(s0)
    op_i(0x0B, 12, 12, 0x80),         # 12 sltiu t4,t4,0x80
    br(0x05, 12, 0, 13, SKIP),        # 13 bne t4,zero,skip
    0,                                # 14
    0x8D2A0000,                       # 15 lw t2,0(t1)
    0x214B0001,                       # 16 addiu t3,t2,1
    0xAD2B0000,                       # 17 sw t3,0(t1)
    0x314A003F,                       # 18 andi t2,t2,0x3F
    0x000A5140,                       # 19 sll t2,t2,5
    0x01495021,                       # 20 addu t2,t2,t1
    0x214A0100,                       # 21 addiu t2,t2,0x100
    0xAD500000,                       # 22 sw s0,0(t2)
    0x8E0B0000,                       # 23 lw t3,0(s0)
    0xAD4B0004,                       # 24 sw t3,4(t2)
    0x0240282D,                       # 25 daddu a1,s0,zero
    0x0C103204,                       # 26 jal 0x40C810
    0x00000000,                       # 27
    0x8FBF0008,                       # 28 lw ra,8(sp)
    0x27BD0010,                       # 29 addiu sp,sp,16
    0x03E00008,                       # 30 jr ra
    0x00000000,                       # 31
]
jal_cave = 0x0C000000 | ((CAVE_VA >> 2) & 0x03FFFFFF)

shutil.copy2(SRC, DST)
with open(DST, 'r+b') as f:
    f.seek(ELF_ABS + (CAVE_VA - 0xFFF00))
    for w in cave:
        f.write(w.to_bytes(4, 'little'))
    f.seek(ELF_ABS + (0x3FF808 - 0xFFF00))
    f.write(jal_cave.to_bytes(4, 'little'))
print('probe21 built: words', len(cave), 'bytes', len(cave) * 4)
print('b5', hex(cave[5]), 'b9', hex(cave[9]), 'b13', hex(cave[13]))
