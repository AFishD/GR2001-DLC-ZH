# -*- coding: utf-8 -*-
"""scan_pattern.py —— 按“指针 + 索引 + 0”的结构找菜单光标字段。

用法: scan_pattern.py <row0_ee.bin> <row2_ee.bin>
"""
import struct
import sys

a = open(sys.argv[1], 'rb').read()
b = open(sys.argv[2], 'rb').read()
n = len(a)
hits = []
for off in range(16, n - 16, 4):
    va = struct.unpack_from('<I', a, off)[0]
    vb = struct.unpack_from('<I', b, off)[0]
    if vb - va != 2:
        continue
    if va not in (1, 2, 3):
        continue
    prev = struct.unpack_from('<I', a, off - 4)[0]
    if not (0x00400000 <= prev < 0x00A00000):
        continue
    nxt = struct.unpack_from('<I', a, off + 4)[0]
    if nxt != 0:
        continue
    z1 = struct.unpack_from('<I', a, off - 8)[0]
    z2 = struct.unpack_from('<I', a, off - 12)[0]
    if z1 != 0 and z2 != 0:
        continue
    hits.append((off, va, vb, prev))
print('hits:', len(hits))
for off, va, vb, prev in hits[:60]:
    print('0x%08X  %d -> %d  ptr 0x%08X  ctx=%s' % (off, va, vb, prev, a[off - 12:off + 8].hex()))
