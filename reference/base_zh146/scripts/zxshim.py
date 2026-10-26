# -*- coding: utf-8 -*-
r"""zx_lib.py (本地垫片) — 只实现本轮需要的 ISO/IMG 条目枚举。

背景: 2026-10-21 14:27 另一路并发把 tools\re\toolbelt\ 整目录移走/删除了
(仓库里已无 zx_lib.py), 而 GR_MISNAMES/mislib.py 仍然 `import zxshim as zx_lib`。
为不依赖那棵被并发改动的树, 这里按原实现的字段口径重写 entries():
  u32[0..11] 表项, +24=stored, +28=real, +32=off; 表在 lba*2048+0x830, 步长 48;
  条目名区 offset 在 +0x10, 结束在 +0x04。
"""
import struct

from tcslib import Iso                                             # noqa: F401
import tcslib                                                      # noqa: F401

SEC = 2048
MENU_LBA = tcslib.MENU_LBA
GR_LBA = tcslib.GR_LBA
TAB_OFF, TAB_STEP = 0x830, 48


def entries(iso, lba):
    base = lba * SEC
    noff = struct.unpack_from('<I', iso.mm, base + 0x10)[0]
    nend = struct.unpack_from('<I', iso.mm, base + 4)[0]
    names = [x.decode('latin-1') for x in bytes(iso.mm[base + noff:base + nend]).split(b'\x00')
             if x]
    out = []
    for i, nm in enumerate(names):
        r = struct.unpack_from('<12I', iso.mm, base + TAB_OFF + TAB_STEP * i)
        out.append(dict(idx=i, name=nm, raw=list(r), stored=r[6], real=r[7], off=r[8],
                        iso_off=base + r[8]))
    return out


def header(iso, lba):
    base = lba * SEC
    h = struct.unpack_from('<12I', iso.mm, base)
    return dict(size=h[0], names_end=h[1], sector=h[2], tbl_end=h[3], names_start=h[4],
                data_start=h[5], hash_off=h[8], raw=list(h))
