# -*- coding: utf-8 -*-
"""make_trace_probe5.py —— 在真正名册兵种名路径插桩：
0x1F16B0 的 `jal 0x402AE0` 换成 `jal cave`；cave dump {key,s0,RSString buf ptr,buf 16B}
到 0x1FFF000，再调用原 0x402AE0 并返回 0x1F16B8。
"""
import shutil

SRC = r'work\builds\v25r.iso'
DST = r'work\builds\probe_trace5.iso'
ELF_ABS = 296 * 2048
CAVE_VA = 0x58C77C
SCRATCH = 0x01FFF000

hi = (SCRATCH >> 16) & 0xFFFF
lo = SCRATCH & 0xFFFF
LUI = (0x0F << 26) | (9 << 16) | hi
ORI = (0x0D << 26) | (9 << 21) | (9 << 16) | lo
cave = [
    LUI,
    ORI,           # t1 = 0x01FFF000
    0xAD3F0020,    # sw ra, 0x20(t1)
    0xAD310000,    # sw s1, 0(t1)  key
    0xAD300004,    # sw s0, 4(t1)  slot object
    0x27A20038,    # addiu t2, sp, 56
    0x8C480004,    # lw t0, 4(t2)  buffer
    0xAD280008,    # sw t0, 8(t1)
    0x8D0C0000,    # lw t4, 0(t0)
    0xAD2C000C,    # sw t4, 12(t1)
    0x8D0C0004,    # lw t4, 4(t0)
    0xAD2C0010,    # sw t4, 16(t1)
    0x8D0C0008,    # lw t4, 8(t0)
    0xAD2C0014,    # sw t4, 20(t1)
    0x8D0C000C,    # lw t4, 12(t0)
    0xAD2C0018,    # sw t4, 24(t1)
    0x0C100AB8,    # jal 0x402AE0
    0x00000000,    # nop
    LUI,
    ORI,
    0x8D3F0020,    # lw ra, 0x20(t1)
    0x03E00008,    # jr ra
    0x00000000,    # nop
]
jal_cave = 0x0C000000 | ((CAVE_VA >> 2) & 0x03FFFFFF)

shutil.copy2(SRC, DST)
with open(DST, 'r+b') as f:
    f.seek(ELF_ABS + (CAVE_VA - 0xFFF00))
    for w in cave:
        f.write(w.to_bytes(4, 'little'))
    f.seek(ELF_ABS + (0x1F16B0 - 0xFFF00))
    f.write(jal_cave.to_bytes(4, 'little'))
print('trace probe5 built:', DST)
