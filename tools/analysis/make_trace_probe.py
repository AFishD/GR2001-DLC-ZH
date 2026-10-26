# -*- coding: utf-8 -*-
"""make_trace_probe.py —— 在小队名册「设置兵种名」的 SetText 调用点插桩：
在 4 个分支的 jalr t9 处改为 jal cave；cave 把 (SetText 地址, RSString*, 返回地址,
RSString 缓冲区指针, 缓冲区前 8 字节) 写入 EE RAM 0x84000，然后调用原 SetText。
跑完存即时存档，即可从 RAM 读到 SetText 的真实地址和"变换前"的字符串。
"""
import shutil

SRC = r'work\builds\v25r.iso'
DST = r'work\builds\probe_trace.iso'
ELF_ABS = 296 * 2048
CAVE_VA = 0x57DABC
SCRATCH = 0x00084000

# cave 机器码
cave = [
    0x3C090008,  # lui t1, 0x0008
    0x35294000,  # ori t1, t1, 0x4000      -> 0x00084000
    0xAD390000,  # sw  t9, 0(t1)          SetText
    0xAD250004,  # sw  a1, 4(t1)          RSString*
    0xAD3F0008,  # sw  ra, 8(t1)          返回地址
    0x8CA20004,  # lw  t2, 4(a1)          buffer ptr
    0xAD2A000C,  # sw  t2, 12(t1)
    0x8D4B0000,  # lw  t3, 0(t2)
    0xAD2B0010,  # sw  t3, 16(t1)
    0x8D4B0004,  # lw  t3, 4(t2)
    0xAD2B0014,  # sw  t3, 20(t1)
    0x0320F809,  # jalr t9
    0x00000000,  # nop
    0x8D3F0008,  # lw  ra, 8(t1)
    0x03E00008,  # jr  ra
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
        put(site, [jal_cave])  # 把 jalr t9 换成 jal cave（延迟槽保持原样：设置 a1）
print('trace probe built:', DST)
