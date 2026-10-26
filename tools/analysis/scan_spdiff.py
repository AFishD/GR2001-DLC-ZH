# -*- coding: utf-8 -*-
"""scan_spdiff.py —— 在已解出的两个 EE RAM (sp0_ee.bin/sp2_ee.bin) 里找菜单光标候选。"""
import sys

a = open(sys.argv[1], 'rb').read()
b = open(sys.argv[2], 'rb').read()
n = len(a)
pairs = {(0, 2), (2, 0), (1, 3), (3, 1), (2, 4), (4, 2), (0, 4), (4, 0), (1, 5), (5, 1)}
cands = []
for off in range(0, n):
    va, vb = a[off], b[off]
    if va == vb:
        continue
    if (va, vb) not in pairs:
        continue
    s = max(0, off - 12)
    e = min(n, off + 12)
    if a[s:off] == b[s:off] and a[off + 1:e] == b[off + 1:e]:
        cands.append((off, va, vb))
print('candidates:', len(cands))
for off, va, vb in cands[:60]:
    print('0x%08X  %d -> %d   ctx a=%s b=%s' % (off, va, vb, a[off - 6:off + 6].hex(), b[off - 6:off + 6].hex()))
