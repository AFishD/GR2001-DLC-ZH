# -*- coding: utf-8 -*-
"""trace_read18.py —— 读 DrawString 字符串环形缓冲。"""
import ctypes
import struct
import sys
import zipfile

P2S, DLL, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, r'tools\dlc')
import textlib as T  # noqa: E402

z = zipfile.ZipFile(P2S)
raw = open(P2S, 'rb').read()
lib = ctypes.CDLL(DLL)
lib.ZSTD_decompress.restype = ctypes.c_size_t
lib.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
lib.ZSTD_isError.restype = ctypes.c_uint
lib.ZSTD_isError.argtypes = [ctypes.c_size_t]


def ex(n):
    info = z.getinfo(n)
    off = info.header_offset
    (_s, _v, _f, m, _t, _d, _c, cs, us, nl, el) = struct.unpack_from('<IHHHHHIIIHH', raw, off)
    comp = raw[off + 30 + nl + el:off + 30 + nl + el + cs]
    if m == 0:
        return comp
    dst = ctypes.create_string_buffer(us)
    src = ctypes.create_string_buffer(comp, len(comp))
    r = lib.ZSTD_decompress(dst, us, src, len(comp))
    if lib.ZSTD_isError(r):
        raise RuntimeError(r)
    return dst.raw[:us]


ee = ex('eeMemory.bin')
open(OUT, 'wb').write(ee)
cs = T.charset()
targets = {
    '突击队员': 'a2b6b9fdc1e9',
    '支援队员': 'a4b0a4afc1e9',
    '爆破手': 'eba3c8f0',
    '狙击手': 'a2ecb9fdf0',
    '突击向(坏)': 'a2b6b9fde1',
    '爆罗手(坏)': 'eba3e8f0',
    '支援向员(坏)': 'a4b0a4afe1e9',
}
cnt = struct.unpack_from('<I', ee, 0x1FFF000)[0]
print('counter', cnt)
for i in range(64):
    base = 0x1FFF100 + i * 32
    ptr = struct.unpack_from('<I', ee, base)[0]
    blob = ee[base + 4:base + 4 + 20].split(b'\x00')[0]
    if not ptr:
        continue
    try:
        dec = cs.decode(blob)
    except Exception:
        dec = '?'
    hits = [k for k, v in targets.items() if bytes.fromhex(v) == blob[:len(bytes.fromhex(v))]]
    mark = ('  <<< ' + ','.join(hits)) if hits else ''
    print('%2d ptr=0x%08X %-42s %r%s' % (i, ptr, blob.hex(), dec, mark))
