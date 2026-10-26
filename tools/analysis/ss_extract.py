# -*- coding: utf-8 -*-
"""ss_extract.py —— 用 PCSX2 自带 zstd.dll 解压 p2s 里的 zstd(方法93) 条目并搜索文本。"""
import ctypes
import io
import os
import struct
import sys
import zipfile

P2S = sys.argv[1] if len(sys.argv) > 1 else r'work\emu_runtime_ss\sstates\SLUS-20820 (0406EA00).01.p2s'
DLL = r'work\emu_runtime_ss\zstd.dll'
OUT = r'work\analysis\emu\savestate_probe'
sys.path.insert(0, r'tools\dlc')
import textlib as T  # noqa: E402

os.makedirs(OUT, exist_ok=True)
cs = T.charset()
z = zipfile.ZipFile(P2S)
raw = open(P2S, 'rb').read()

lib = ctypes.CDLL(os.path.abspath(DLL))
lib.ZSTD_decompress.restype = ctypes.c_size_t
lib.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
lib.ZSTD_isError.restype = ctypes.c_uint
lib.ZSTD_isError.argtypes = [ctypes.c_size_t]


def extract(name):
    info = z.getinfo(name)
    off = info.header_offset
    (sig, ver, flags, method, tm, dt, crc, csize, usize, nlen, elen) = struct.unpack_from(
        '<IHHHHHIIIHH', raw, off)
    dstart = off + 30 + nlen + elen
    comp = raw[dstart:dstart + csize]
    if method == 0:
        return comp
    dst = ctypes.create_string_buffer(usize)
    src = ctypes.create_string_buffer(comp, len(comp))
    r = lib.ZSTD_decompress(dst, usize, src, len(comp))
    if lib.ZSTD_isError(r):
        raise RuntimeError('zstd error %d for %s' % (r, name))
    return dst.raw[:usize]


ee = extract('eeMemory.bin')
open(os.path.join(OUT, 'ee_mem.bin'), 'wb').write(ee)
print('EE mem extracted', len(ee))

pats = {
    '突击队员': 'a2b6b9fdc1e9',
    '支援队员': 'a4b0a4afc1e9',
    '爆破手': 'eba3c8f0',
    '狙击手': 'a2ecb9fdf0',
    '突击向(坏)': 'a2b6b9fde1',
    '爆罗手(坏)': 'eba3e8f0',
    '走组亦练(坏)': 'a4d0c4afa2b1a3',
    '狙击手缺(坏)': 'b9fdf0',
}
for k, hx in pats.items():
    n = bytes.fromhex(hx)
    hits = []
    st = 0
    while True:
        i = ee.find(n, st)
        if i < 0:
            break
        hits.append(i)
        st = i + 1
        if len(hits) >= 8:
            break
    print('%-12s %s hits=%s' % (k, hx, [hex(x) for x in hits]))

# 输出一些命中处的上下文，便于判断 RAM 中该串的真身
for hx in ('a2b6b9fdc1e9', 'a4b0a4afc1e9', 'eba3c8f0', 'a2ecb9fdf0'):
    n = bytes.fromhex(hx)
    i = ee.find(n)
    if i >= 0:
        ctx = ee[max(0, i - 32):i + 48]
        print('\nCTX', hx, 'at', hex(i), ctx.hex())
        try:
            print('   decoded-ish:', repr(cs.decode(ctx)))
        except Exception:
            pass
