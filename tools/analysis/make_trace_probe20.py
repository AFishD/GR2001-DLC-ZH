# -*- coding: utf-8 -*-
"""make_trace_probe20.py —— Hook 文本 interner 调用点 0x3FF808（此时 s0 = 待设置的字符串）：
只记录 CJK（首字节>=0x80）或空格开头（0x20）的字符串的前 8 字节 + ptr 到环形缓冲。
用 k0 保存 ra（cave 128B）。
目的：看 setter 收到的兵种名字节是否已经是坏的（爆罗手）。
"""
import shutil

SRC = r'work\builds\v25r.iso'
DST = r'work\builds\probe_trace20.iso'
ELF_ABS = 296 * 2048
CAVE_VA = 0x180D00
RING = 0x01FFF000


def op_i(op, rs, rt, imm):
    return (op << 26) | ((rs & 0x1F) << 21) | ((rt & 0x1F) << 16) | (imm & 0xFFFF)


def br(op, rs, rt, at, target):
    return op_i(op, rs, rt, (target - (at + 1)) & 0xFFFF)


hi, lo = (RING >> 16) & 0xFFFF, RING & 0xFFFF
LUI = op_i(0x0F, 0, 9, hi)
ORI = op_i(0x0D, 9, 9, lo)
REC, SKIP = 14, 27
cave = [
    LUI,                              # 0
    ORI,                              # 1
    op_i(0x0B, 16, 3, 0x1000),        # 2  sltiu t3, s0, 0x1000
    br(0x05, 11, 0, 3, SKIP),         # 3
    0,                                # 4
    0x820B0000,                       # 5  lb t3, 0(s0)
    op_i(0x0B, 11, 12, 0x80),         # 6  sltiu t4, t3, 0x80
    br(0x04, 12, 0, 7, REC),          # 7  beq t4,zero,record
    0,                                # 8
    op_i(0x09, 0, 12, 0x20),          # 9  addiu t4,zero,0x20
    br(0x04, 11, 12, 10, REC),        # 10 beq t3,t4,record
    0,                                # 11
    br(0x04, 0, 0, 12, SKIP),         # 12 beq zero,zero,skip
    0,                                # 13
    0x03E0D02D,                       # 14 daddu k0, ra, zero
    0x8D2A0000,                       # 15 lw t2,0(t1)
    0x214B0001,                       # 16 addiu t3,t2,1
    0xAD2B0000,                       # 17 sw t3,0(t1)
    0x314A003F,                       # 18 andi t2,t2,0x3F
    0x000A5140,                       # 19 sll t2,t2,5
    0x01495021,                       # 20 addu t2,t2,t1
    0x214A0100,                       # 21 addiu t2,t2,0x100
    0xAD500000,                       # 22 sw s0,0(t2)
    0x8E0B0000, 0xAD4B0004,           # 23/24 lw t3,0(s0); sw t3,4(t2)
    0x8E0B0004, 0xAD4B0008,           # 25/26
    0x0240282D,                       # 27 daddu a1, s0, zero
    0x0C103204,                       # 28 jal 0x40C810
    0x00000000,                       # 29
    0x03400008,                       # 30 jr k0
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
print('probe20 built: words', len(cave), 'bytes', len(cave) * 4)
print('branch3', hex(cave[3]), 'branch7', hex(cave[7]), 'branch10', hex(cave[10]), 'branch12', hex(cave[12]))
