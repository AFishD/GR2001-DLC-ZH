# -*- coding: utf-8 -*-
r"""lzokit.py — 本轮自带的 LZO1X 子流工具 (不依赖 work/builds/GR_MISNAMES/*)

背景: 2026-10-21 14:34 起另一路并发在清理 work\builds 旧轮目录 (GR_MISNAMES /
GR_MISSIONTITLES 的 mislib.py / mispatch.py 先后被删), tools\re\toolbelt 也被移走。
为保证本轮可复现, 把用到的 4 个编码原语 + 4 个条目工具**原样搬进本目录**:
  · enc_lit_run / lit_cost / enc_m2 / enc_m4l   ← 原 GR_MISNAMES/mispatch.py (逐字)
  · substreams / decode_payload / entry_blob / iter_mis ← 原 GR_MISNAMES/mislib.py (逐字)
"""
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))

import tcslib                                                      # noqa: E402
import zxshim as zx_lib                                                      # noqa: E402  (本目录垫片)
from lz77_decode import lzo1x_decompress                           # noqa: E402

NAME_RE = re.compile(rb'<Name>(.*?)</Name>', re.S)
MAPNAME_RE = re.compile(rb'<MapName>(.*?)</MapName>', re.S)


# ───────────────────────── 编码原语 (原 mispatch.py) ─────────────────────────
def lit_cost(L):
    c = L - 3
    if c <= 15:
        return 1
    if c <= 270:
        return 2
    return 2 + (c - 270 + 254) // 255


def enc_lit_run(L, data):
    assert L >= 4 and len(data) == L, (L, len(data))
    c = L - 3
    out = bytearray()
    if c <= 15:
        out.append(c)
    else:
        k = (c - 270 + 254) // 255 if c > 270 else 0
        out.append(0)
        for _ in range(k):
            out.append(0)
        v = c - 255 * k - 15
        assert 1 <= v <= 255, (L, c, k, v)
        out.append(v)
    assert len(out) == lit_cost(L)
    out += data
    return bytes(out)


def enc_m2(b, L, post, data):
    assert 3 <= L <= 8 and 1 <= b <= 2048, (L, b)
    v = b - 1
    return bytes([((L - 1) << 5) | ((v & 7) << 2) | post, (v >> 3) & 0xFF]) + data


def enc_m4l(b, post, data):
    v = b - 1 - 2048
    assert 0 <= v <= 1023, (b,)
    return bytes([((v & 3) << 2) | post, (v >> 2) & 0xFF]) + data


# ───────────────────────── 条目工具 (原 mislib.py) ─────────────────────────
def substreams(raw):
    """→ [(hdr_off, payload, rlen)]"""
    out, p = [], 0
    while p + 8 <= len(raw):
        L, S = struct.unpack_from('<II', raw, p)
        if L == 0 or p + 8 + L > len(raw):
            break
        out.append((p, raw[p + 8:p + 8 + L], S))
        p += 8 + L
    return out


def decode_payload(pay, S):
    if len(pay) == S:
        return pay, None
    out, err, _ = lzo1x_decompress(pay, out_size=S)
    if len(out) != S:
        err = err or ('out %d != %d' % (len(out), S))
    return out, err


def entry_blob(iso, e):
    raw = iso.read(e['iso_off'], e['stored'])
    parts, subs = [], substreams(raw)
    for (p, pay, S) in subs:
        out, err = decode_payload(pay, S)
        if err:
            raise RuntimeError('sub@%d: %s' % (p, err))
        parts.append(out)
    return b''.join(parts), parts


def iter_mis(iso):
    out = []
    for lba, tag in ((tcslib.GR_LBA, 'GR.IMG'), (tcslib.MENU_LBA, 'MENU.IMG')):
        for e in zx_lib.entries(iso, lba):
            if not e['name'].upper().endswith('.MIS'):
                continue
            out.append((tag, lba, e))
    return out
