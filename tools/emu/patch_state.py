# -*- coding: utf-8 -*-
"""patch_state.py —— 解 p2s 的 eeMemory.bin，改写 4 字节并重打包（全部用 ZIP_STORED）。

用法: python patch_state.py --in A.p2s --out B.p2s --offset 0x116CB1C --value 2
"""
import argparse
import ctypes
import zipfile

DLL = r'work\emu_runtime_sp0\zstd.dll'


def extract(z, raw, name):
    info = z.getinfo(name)
    off = info.header_offset
    import struct
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
    ap.add_argument('--offset', required=True)
    ap.add_argument('--value', type=int, required=True)
    a = ap.parse_args()
    off = int(a.offset, 0)
    z = zipfile.ZipFile(a.src)
    ee = bytearray(extract(z, open(a.src, 'rb').read(), 'eeMemory.bin'))
    old = ee[off:off + 4]
    ee[off:off + 4] = int(a.value).to_bytes(4, 'little')
    print('patch eeMemory[0x%X]: %s -> %s' % (off, old.hex(), ee[off:off + 4].hex()))
    with zipfile.ZipFile(a.dst, 'w', zipfile.ZIP_STORED) as out:
        for name in z.namelist():
            if name == 'eeMemory.bin':
                out.writestr(name, bytes(ee))
            else:
                out.writestr(name, extract(z, open(a.src, 'rb').read(), name))
    print('written', a.dst)


if __name__ == '__main__':
    main()
