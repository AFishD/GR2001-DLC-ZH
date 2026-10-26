# -*- coding: utf-8 -*-
"""make_trace_probe2.py —— 同 make_trace_probe，但插桩 scratch 放在 ELF 的零岛（VA 0x58C77C，1KB 内）
以减少被游戏清掉的风险：cave@0x58C77C，scratch@0x58C87C。
"""
import shutil

SRC = r'work\builds\v25r.iso'
DST = r'work\builds\probe_trace4.iso'
ELF_ABS = 296 * 2048
CAVE_VA = 0x58C77C
SCRATCH = 0x01FFF000

hi = (SCRATCH >> 16) & 0xFFFF
lo = SCRATCH & 0xFFFF
cave = [
    (0x0F << 26) | (9 << 16) | hi,      # lui t1, hi
    (0x0D << 26) | (9 << 21) | (9 << 16) | lo,  # ori t1,t1,lo
    0xAD390000,  # sw t9, 0(t1)
    0xAD250004,  # sw a1, 4(t1)
    0xAD3F0008,  # sw ra, 8(t1)
    0x8CA20004,  # lw t2, 4(a1)
    0xAD2A000C,  # sw t2, 12(t1)
    0x8D4B0000,  # lw t3, 0(t2)
    0xAD2B0010,  # sw t3, 16(t1)
    0x8D4B0004,  # lw t3, 4(t2)
    0xAD2B0014,  # sw t3, 20(t1)
    0x0320F809,  # jalr t9
    0x00000000,  # nop
    0x8D3F0008,  # lw ra, 8(t1)
    0x03E00008,  # jr ra
    0x00000000,  # nop
]
jal_cave = 0x0C000000 | ((CAVE_VA >> 2) & 0x03FFFFFF)

shutil.copy2(SRC, DST)
with open(DST, 'r+b') as f:
    def put(va, words):
        f.seek(ELF_ABS + (va - 0xFFF00))
        for w in words:
            f.write(w.to_bytes(4, 'little'))

    put(CAVE_VA, cave)
    for site in (0x329A54, 0x329A98, 0x329ADC, 0x329B20):
        put(site, [jal_cave])
print('trace probe4 built:', DST, 'cave', hex(CAVE_VA), 'scratch', hex(SCRATCH))

# scratch = EE scratchpad 0x70000000
