# -*- coding: utf-8 -*-
"""ss_vtable.py —— 从 RAM 里找到的 vtable(0x5B7788) 读 +0x104 的 SetText，并反汇编。"""
import struct
import sys

sys.path.insert(0, r'tools\dlc')
import dlclib as L  # noqa: E402

EE = r'work\analysis\emu\savestate_probe\ee_mem.bin'
ee = open(EE, 'rb').read()

# RAM 里对象字段：0xE5B0A0 起 vtable=0x5B7788；0xE5B0B8 也有一个 vtable
for obj in (0xE5B0A0, 0xE5B0B8):
    vt = struct.unpack_from('<I', ee, obj)[0]
    print('object 0x%X vtable=0x%X' % (obj, vt))

VT = struct.unpack_from('<I', ee, 0xE5B0A0)[0]
iso = L.Iso(r'work\builds\v25r.iso')
elf = iso.elf()
iso.close()
off = VT - 0xFFF00
print('vtable VA 0x%X file 0x%X head:' % (VT, off), elf[off:off + 32].hex())
# 打印 vtable 前 0x140 个函数指针
ptrs = []
for k in range(0, 0x140 // 4):
    v = struct.unpack_from('<I', elf, off + k * 4)[0]
    ptrs.append(v)
    if v:
        print('  +0x%03X: 0x%X' % (k * 4, v))
print('SetText@+0x104 =', hex(ptrs[0x104 // 4]))
