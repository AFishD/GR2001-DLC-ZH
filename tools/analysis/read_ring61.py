# -*- coding: utf-8 -*-
"""read_ring61.py —— 读 v61 DrawString 环形记录（0x569400）。"""
import ctypes
import glob
import struct
import zipfile

P = glob.glob(r'work\emu_runtime_ms61\sstates\*.p2s')[0]
DLL = r'work\emu_runtime_ms61\zstd.dll'
raw = open(P, 'rb').read()
z = zipfile.ZipFile(P)
off = z.getinfo('eeMemory.bin').header_offset
(_s, _v, _f, m, _t, _d, _c, cs, us, nl, el) = struct.unpack_from('<IHHHHHIIIHH', raw, off)
comp = raw[off + 30 + nl + el:off + 30 + nl + el + cs]
lib = ctypes.CDLL(DLL)
lib.ZSTD_decompress.restype = ctypes.c_size_t
lib.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
dst = ctypes.create_string_buffer(us)
src = ctypes.create_string_buffer(comp, len(comp))
r = lib.ZSTD_decompress(dst, us, src, len(comp))
assert r == us
ee = dst.raw
open(r'work\analysis\emu\msg_ee61.bin', 'wb').write(ee)
base = 0x569400
cnt = struct.unpack_from('<I', ee, base)[0]
print('count', cnt)
n = min(cnt, 64)
for k in range(n):
    off2 = base + 16 + (k * 24)
    a0, a1, a2, a3, t2, ra = struct.unpack_from('<6I', ee, off2)
    print('%2d a0=%08X a1=%08X a2=%08X a3=%08X t2=%08X ra=%08X' % (k, a0, a1, a2, a3, t2, ra))
