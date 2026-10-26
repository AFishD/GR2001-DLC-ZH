# -*- coding: utf-8 -*-
"""patch_state_multi.py —— 对 p2s 的 eeMemory.bin 多点打补丁（float/int），重打包 ZIP_STORED。

用法: patch_state_multi.py --in A.p2s --out B.p2s --patches "0xOFF=float:493,0xOFF2=int:493"
"""
import argparse
import ctypes
import struct
import zipfile

DLL = r'work\emu_runtime_msv58\zstd.dll'


def extract(z, raw, name):
    info = z.getinfo(name)
    off = info.header_offset
    (_s, _v, _f, m, _t, _d, _c, cs, us, nl, el) = struct.unpack_from('<IHHHHHIIIHH', raw, off)
    comp = raw[off + 30 + nl + el:off + 30 + nl + el + cs]
    if m == 0:
        return comp
    lib = ctypes.CDLL(DLL)
    lib.ZSTD_decompress.restype = ctypes.c_size_t
    lib.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
    lib.ZSTD_isError.restype = ctypes.c_uint
    lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
    dst = ctypes.create_string_buffer(us)
    src = ctypes.create_string_buffer(comp, len(comp))
    r = lib.ZSTD_decompress(dst, us, src, len(comp))
    if lib.ZSTD_isError(r):
        raise RuntimeError(r)
    return dst.raw[:us]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='src', required=True)
    ap.add_argument('--out', dest='dst', required=True)
    ap.add_argument('--patches', required=True)
    a = ap.parse_args()
    raw = open(a.src, 'rb').read()
    z = zipfile.ZipFile(a.src)
    ee = bytearray(extract(z, raw, 'eeMemory.bin'))
    for item in a.patches.split(','):
        off_s, spec = item.split('=')
        off = int(off_s, 0)
        kind, val = spec.split(':')
        if kind == 'float':
            data = struct.pack('<f', float(val))
        else:
            data = struct.pack('<I', int(val, 0))
        old = ee[off:off + 4]
        ee[off:off + 4] = data
        print('patch 0x%X: %s -> %s' % (off, old.hex(), data.hex()))
    with zipfile.ZipFile(a.dst, 'w', zipfile.ZIP_STORED) as out:
        for name in z.namelist():
            if name == 'eeMemory.bin':
                out.writestr(name, bytes(ee))
            else:
                out.writestr(name, extract(z, raw, name))
    print('written', a.dst)


if __name__ == '__main__':
    main()
