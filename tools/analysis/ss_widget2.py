# -*- coding: utf-8 -*-
"""ss_widget2.py —— 找引用 RSString 对象(0xE5B0A0) 的控件，读其 vtable+0x104。"""
import struct
import sys

sys.path.insert(0, r'tools\dlc')
import dlclib as L  # noqa: E402

ee = open(r'work\analysis\emu\savestate_probe\ee_mem.bin', 'rb').read()
iso = L.Iso(r'work\builds\v25r.iso')
elf = iso.elf()
iso.close()


def read_va(va):
    off = va - 0xFFF00
    if 0 <= off < len(elf) - 4:
        return struct.unpack_from('<I', elf, off)[0]
    return None


def scan_refs(target, lo=0x80000, hi=0x1800000, maxhits=30):
    ptr = struct.pack('<I', target)
    hits = []
    st = lo
    while True:
        i = ee.find(ptr, st, hi)
        if i < 0:
            break
        hits.append(i)
        st = i + 1
        if len(hits) >= maxhits:
            break
    return hits


# 1) 找引用 RSString 对象的字段
for tgt_name, tgt in (('RSString 0xE5B0A0', 0xE5B0A0), ('RSString 0xE5B0B8', 0xE5B0B8),
                      ('node 0x601B02', 0x601B02)):
    hits = scan_refs(tgt)
    print('%s refs: %s' % (tgt_name, [hex(x) for x in hits[:10]]))
    for h in hits[:4]:
        win = ee[max(0, h - 0x40):h + 0x40]
        base = max(0, h - 0x40)
        cands = []
        for j in range(0, len(win) - 3, 4):
            v = struct.unpack_from('<I', win, j)[0]
            if 0x560000 <= v <= 0x610000:
                fn = read_va(v + 0x104)
                cands.append((base + j, v, fn))
        print('  ref@0x%X nearby vtable-ish: %s' % (h, [(hex(a), hex(v), hex(fn) if fn else None)
                                                        for a, v, fn in cands[:6]]))
