# -*- coding: utf-8 -*-
"""read_hook59.py —— 读 v59 DrawString hook 记录（0x5A0800..）。"""
import ctypes
import glob
import struct
import zipfile

P = glob.glob(r'work\emu_runtime_ms59\sstates\*.p2s')[0]
DLL = r'work\emu_runtime_ms59\zstd.dll'
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
open(r'work\analysis\emu\msg_ee59.bin', 'wb').write(ee)
for o in (0x5A0800, 0x5A0804, 0x5A0808, 0x5A080C):
    v = struct.unpack_from('<I', ee, o)[0]
    print('0x%06X = 0x%08X' % (o, v))
