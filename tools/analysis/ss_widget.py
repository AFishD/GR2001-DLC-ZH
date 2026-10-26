# -*- coding: utf-8 -*-
"""ss_widget.py —— 在 EE RAM 里找「爆罗手」字符串的引用者，定位控件对象/vtable/SetText。"""
import struct
import sys

EE = r'work\analysis\emu\savestate_probe\ee_mem.bin'
ee = open(EE, 'rb').read()

STR = 0x601b03  # "爆罗手" bytes EBA3E8F0
needle = ee[STR:STR + 4]
print('needle at 0x%X:' % STR, needle.hex())

# 1) 找指向该字符串的指针（节点内可能还有 header，先试几个偏移）
cands = []
for off in (STR, STR - 1, STR - 2, STR - 4, STR - 8, STR - 12, STR - 16):
    ptr = struct.pack('<I', off & 0xFFFFFFFF)
    hits = []
    st = 0
    while True:
        i = ee.find(ptr, st)
        if i < 0:
            break
        hits.append(i)
        st = i + 1
        if len(hits) > 20:
            break
    print('ptr -> 0x%X: %d hits %s' % (off, len(hits), [hex(x) for x in hits[:8]]))

# 2) 在那些引用位置附近寻找 vtable 指针（0x5Axxxx/0x5Bxxxx/0x56-0x5F 区域）
VLO, VHI = 0x500000, 0x610000
for off in (STR, STR - 1, STR - 2, STR - 4, STR - 8, STR - 12, STR - 16):
    ptr = struct.pack('<I', off & 0xFFFFFFFF)
    st = 0
    while True:
        i = ee.find(ptr, st)
        if i < 0:
            break
        st = i + 1
        # 引用者很可能在对象/结构里；打印附近 64 字节和可能的 vtable 值
        win = ee[max(0, i - 0x100):i + 0x40]
        base = max(0, i - 0x100)
        vt = []
        for j in range(0, len(win) - 3, 4):
            v = struct.unpack_from('<I', win, j)[0]
            if VLO <= v < VHI:
                vt.append((base + j, v))
        print('\nref at 0x%X (node=0x%X):' % (i, off))
        print('  near bytes:', ee[i - 16:i + 16].hex())
        print('  candidate pointers:', [(hex(a), hex(v)) for a, v in vt[:8]])
