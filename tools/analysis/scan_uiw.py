# -*- coding: utf-8 -*-
"""scan_uiw.py —— 从 v58 提示条存档里找“消息框布局”候选（宽 490-545 的 float/int，附近有 x/y/h）。"""
import ctypes
import glob
import struct
import zipfile

P = glob.glob(r'work\emu_runtime_msv58\sstates\*.p2s')[0]
DLL = r'work\emu_runtime_msv58\zstd.dll'
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
open(r'work\analysis\emu\ee_msv58.bin', 'wb').write(ee)


def f(o):
    return struct.unpack_from('<f', ee, o)[0]


def u(o):
    return struct.unpack_from('<I', ee, o)[0]


cands = []
for o in range(0, len(ee) - 4, 4):
    v = f(o)
    if not (490.0 <= v <= 545.0):
        continue
    near_x = near_h = False
    for d in range(-0x60, 0x61, 4):
        q = o + d
        if q < 0 or q + 4 > len(ee):
            continue
        w = f(q)
        if 40.0 <= w <= 90.0:
            near_x = True
        if 70.0 <= w <= 130.0:
            near_h = True
    if near_x and near_h:
        cands.append((o, v))
print('float width candidates:', len(cands))
for o, v in cands[:60]:
    print('0x%06X width %.1f ctx %s' % (o, v, [round(f(o + k), 1) for k in range(-0x20, 0x21, 4)]))

# 整数候选（窗口/尺寸常以 int 存）
icands = []
for o in range(0, len(ee) - 4, 4):
    v = u(o)
    if not (490 <= v <= 545):
        continue
    near = 0
    for d in range(-0x60, 0x61, 4):
        q = o + d
        if q < 0 or q + 4 > len(ee):
            continue
        w = u(q)
        if 40 <= w <= 90 or 70 <= w <= 130:
            near += 1
    if near >= 2:
        icands.append((o, v))
print('int candidates:', len(icands))
for o, v in icands[:40]:
    print('0x%06X int %d ctx %s' % (o, v, [u(o + k) for k in range(-0x10, 0x11, 4)]))
