# -*- coding: utf-8 -*-
"""read_scratch3.py —— 读 v56 诊断值（0x57D300..0x57D380）。"""
import ctypes
import glob
import struct
import zipfile

P = glob.glob(r'work\emu_runtime_ms56\sstates\*.p2s')[0]
DLL = r'work\emu_runtime_ms56\zstd.dll'
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
open(r'work\analysis\emu\msg_ee56.bin', 'wb').write(ee)
names = {0x57D300: 'M2 s7', 0x57D304: 'M2 s4', 0x57D368: 'M2 count',
         0x57D320: 'H2 s7', 0x57D36C: 'H2 count'}
for o, n in names.items():
    v = struct.unpack_from('<I', ee, o)[0]
    print('0x%06X %-9s = 0x%08X int %-10d float %.3f' % (
        o, n, v, v, struct.unpack('<f', ee[o:o + 4])[0]))
