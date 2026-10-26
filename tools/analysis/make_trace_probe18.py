# -*- coding: utf-8 -*-
"""make_trace_probe18.py —— 在 DrawString 内部 strlen 调用点 0x21964C 插桩
（此时 s2 = 文本指针，t 寄存器已死，可安全引用），环形记录每次绘制字符串的前 20 字节。
"""
import shutil

SRC = r'work\builds\v25r.iso'
DST = r'work\builds\probe_trace18.iso'
ELF_ABS = 296 * 2048
CAVE_VA = 0x180D00
RING = 0x01FFF000

hi = (RING >> 16) & 0xFFFF
lo = RING & 0xFFFF
LUI = (0x0F << 26) | (9 << 16) | hi
ORI = (0x0D << 26) | (9 << 21) | (9 << 16) | lo
cave = [
    LUI, ORI,
    0xAD3F0C00,               # sw ra,0xC00(t1)
    0x8D2A0000,               # lw t2,0(t1)
    0x214B0001,               # addiu t3,t2,1
    0xAD2B0000,               # sw t3,0(t1)
    0x314A003F,               # andi t2,t2,0x3F
    0x000A5140,               # sll t2,t2,5
    0x01495021,               # addu t2,t2,t1
    0x214A0100,               # addiu t2,t2,0x100
    0xAD520000,               # sw s2,0(t2)
    0x10A00008,               # beq s2? -- 用 beq s2,zero
]
# 上面 beq 占位，下面按正确顺序重建
cave = [
    LUI, ORI,
    0xAD3F0C00,
    0x8D2A0000,
    0x214B0001,
    0xAD2B0000,
    0x314A003F,
    0x000A5140,
    0x01495021,
    0x214A0100,
    0xAD520000,               # sw s2,0(t2)
    0x1240000D,               # beq s2,zero, skip
    0x00000000,
    0x8E4B0000, 0xAD4B0004,   # lw t3,0(s2) ; sw t3,4(t2)
    0x8E4B0004, 0xAD4B0008,
    0x8E4B0008, 0xAD4B000C,
    0x8E4B000C, 0xAD4B0010,
    0x8E4B0010, 0xAD4B0014,
    0x8E4B0014, 0xAD4B0018,
    0x0240202D,               # daddu a0,s2,zero
    0x0C08667C,               # jal 0x2199F0
    0x00000000,
    LUI, ORI,
    0x8D3F0C00,
    0x03E00008,
    0x00000000,
]
jal_cave = 0x0C000000 | ((CAVE_VA >> 2) & 0x03FFFFFF)

shutil.copy2(SRC, DST)
with open(DST, 'r+b') as f:
    f.seek(ELF_ABS + (CAVE_VA - 0xFFF00))
    for w in cave:
        f.write(w.to_bytes(4, 'little'))
    f.seek(ELF_ABS + (0x21964C - 0xFFF00))
    f.write(jal_cave.to_bytes(4, 'little'))
print('trace probe18 built:', DST, 'words', len(cave))
