#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# [hanliu 收编] 原件: gr_tools/lzo1x_c.py (逐字复制 (minilzo 兼容压缩器, RES 8 子流写回用))。原件保留于原处未动。
# 工具链总览见 hanliu/README.md 与 hanliu/tools/__init__.py。
"""lzo1x_c.py - minilzo 兼容 LZO1X 压缩器 (Ghost Recon PS2 汉化工程) 2026-09-11

== 背景 ==
EN_STRINGS.RES 必须在原 47,570B 槽位内原地覆写 (条目表 off/stored/real 三字段
绝对不动), 即 {u32 plen}{u32 osz=128545}{payload} 帧整体 ≤ 47,570B
→ payload ≤ 47,562B。原盘 minilzo (lzo1x_1 贪心, 16K 窗口 × 8 子流) 比率 37.0%;
旧贪心压缩器 (res_encode.py, 仅 M3 + 单槽 dict) 46% 不达标。

== 本压缩器增强 (相对 lzo1x_1) ==
  - 3 字节哈希 + head/prev 哈希链 (可调链长), 找到更长匹配
  - zlib 式惰性匹配 (一步前瞻, 前瞻失败则该字节并入字面量)
  - 全部令牌形式:
      M2: len 3..8,  back ≤ 2048,   2 字节 (x ≥ 0x40)
      M4: len 2,     back ≤ 1024,   2 字节 (x ≤ 0x0F, 仅 state≠0)
      M3: len 2..33 (扩展至 288+),  back ≤ 16384,  3 字节 (0x20..0x3F)
      M1: len 2..9,  back 16385..49151, 3 字节 (0x10..0x1F; 可选, 原盘数据未实证)
      字面量: 首令牌 1..238B + x≤15 段 4..273B (0 扩展可无限长)
      RLE: back < len 重叠拷贝 (尾 279 个 0x00 → 一条 M3 back=1)
      EOF: 0x11 0x00 0x00 (M1 back==0x4000 && len==3, 原盘 8 子流实证)
默认只使用原盘子流数据实证过的语法 (M2/M3/M4/段/EOF), --m1 才启用 M1。

== state 机规则 (由 lz77_decode.lzo1x_decompress 反推, 已 42 子流验证) ==
  - x ≤ 15 且 state==0  → 字面量段 (len≥4);  x ≤ 15 且 state≠0 → M4
  - 连续两个字面量段非法; 段后首令牌若 ≤15 是带 0x800 偏置的 M4 (本器不产出)
  - 匹配后置字面量 k: M2/M4 用令牌低 2 位, M3/M1 用参数字节 b1 低 2 位
  - 长段/长匹配前必须 k=0 结尾的匹配 (或处于流首)

== 用法 ==
  python lzo1x_c.py selftest
  python lzo1x_c.py compress <in> <out> [--frame] [--m1] [--chain N] [--level N]
  python lzo1x_c.py bench <expanded.bin> [orig_stored.bin]
"""
import os
import struct
import sys
import time
from array import array

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lz77_decode import lzo1x_decompress

try:
    import numpy as np
except ImportError:
    np = None


# ---------------------------------------------------------------- 哈希表

def _hash3_list(data, bits):
    """对每个位置 i (0..n-3) 计算 3 字节窗口哈希, 返回 Python list。"""
    n = len(data)
    bits_mask = (1 << bits) - 1
    if np is not None and n >= 3:
        arr = np.frombuffer(data, dtype=np.uint8)
        v = ((arr[:-2].astype(np.uint64) << np.uint64(16)) |
             (arr[1:-1].astype(np.uint64) << np.uint64(8)) |
             arr[2:].astype(np.uint64))
        h = ((v * np.uint64(2654435761)) >> np.uint64(17)) & np.uint64(bits_mask)
        return h.astype(np.int64).tolist()
    h = [0] * max(0, n - 2)
    for i in range(n - 2):
        h[i] = ((data[i] << 16 | data[i + 1] << 8 | data[i + 2]) * 2654435761
                >> 17) & bits_mask
    return h


# ---------------------------------------------------------------- 匹配长度

def _mlen(data, n, j, i, limit):
    """data[j..] 与 data[i..] 的公共前缀长, 上限 limit。切片比较 (C 速度)。"""
    l = 0
    while l < limit:
        step = limit - l
        if step > 32:
            step = 32
        if data[j + l:j + l + step] == data[i + l:i + l + step]:
            l += step
            if step < 32:
                break
            continue
        end = j + l + step
        jj = j + l
        ii = i + l
        while jj < end and data[jj] == data[ii]:
            jj += 1
            ii += 1
        l += jj - (j + l)
        break
    return l


# ---------------------------------------------------------------- 压缩主体

LEVELS = {
    # level: (max_chain, lazy, good_len, nice_len, max_lazy)
    1: (8, False, 24, 96, 8),
    2: (16, True, 24, 128, 16),
    3: (32, True, 32, 192, 24),
    4: (64, True, 48, 256, 32),
    5: (128, True, 64, 288, 40),
    6: (512, True, 96, 288, 64),
    7: (2048, True, 160, 288, 96),
}


def compress(data, level=5, max_back=16384, use_m1=False, use_m4=False,
             max_chain=None, lazy=None, good_len=None, nice_len=None,
             max_lazy=None, hash_bits=17, verbose=False):
    """LZO1X 压缩, 返回 payload (不含 {plen}{osz} 帧, 不含 3 字节 EOF 前的帧头)。
    payload 末尾含 3 字节 EOF 标记 0x11 00 00 (M1 len=3 back=0x4000, 原盘实证)。内置 lz77_decode 自检。"""
    n = len(data)
    if n == 0:
        raise ValueError('空输入')
    if n < 8:
        # 极短输入退化为纯字面量 (初始令牌即可)
        out = bytearray()
        out.append(n + 17)
        out += data
        out += b'\x11\x00\x00'
        return bytes(out)

    if max_chain is None or lazy is None or good_len is None or \
            nice_len is None or max_lazy is None:
        lc, ll, lg, ln, lm = LEVELS[level]
        max_chain = max_chain or lc
        lazy = lazy if lazy is not None else ll
        good_len = good_len or lg
        nice_len = nice_len or ln
        max_lazy = max_lazy or lm
    window = 49151 if use_m1 else max_back

    h = _hash3_list(data, hash_bits)
    HSIZE = 1 << hash_bits
    head = array('i', [-1]) * HSIZE
    prev = array('i', [0]) * n
    n3 = n - 2                                  # 哈希表有效位置数

    matches = []                                # (pos, len, back)

    def search(p):
        """在 p 找最佳匹配, 返回 (len, back); 无则 (0, 0)。"""
        if p >= n3:
            return 0, 0
        j = head[h[p]]
        if j < 0:
            return 0, 0
        imax = n - p
        lim = p - window
        blen = 0
        bback = 0
        chain = max_chain
        while j >= lim and j >= 0:
            if blen:
                qi = p + blen
                if qi >= n:
                    break                        # 已达最大可能长度
                if data[j + blen] != data[qi]:
                    j = prev[j]
                    chain -= 1
                    if chain <= 0:
                        break
                    continue
            if data[j:j + 3] == data[p:p + 3]:   # 哈希碰撞过滤
                l = _mlen(data, n, j, p, imax if imax < nice_len else nice_len)
                if l > blen:
                    back = p - j
                    if back > 16384 and l > 9:
                        l = 9                    # M1 最长 9
                    if l > blen:
                        blen = l
                        bback = back
                        if blen >= imax or blen >= nice_len:
                            break
            j = prev[j]
            chain -= 1
            if chain <= 0:
                break
        return blen, bback

    def insert(p):
        if p < n3:
            hv = h[p]
            prev[p] = head[hv]
            head[hv] = p

    i = 0
    t0 = time.time()
    while i < n3:
        l, b = search(i)
        if l >= 3 or (use_m4 and l == 2):
            if l < good_len and lazy and i + 1 < n3:
                l2, b2 = search(i + 1)
                if l2 > l:
                    insert(i)
                    i += 1
                    continue
            matches.append((i, l, b))
            end = i + l
            q = i
            stop = end if end < n3 else n3
            while q < stop:
                insert(q)
                q += 1
            i = end
        else:
            insert(i)
            i += 1
    if verbose:
        print('  parse: %d matches, %.1fs' % (len(matches), time.time() - t0))

    return serialize(data, n, matches, use_m1)


# ---------------------------------------------------------------- 序列化

def serialize(data, n, matches, use_m1=True):
    """把匹配决策列表按 state 机规则序列化为 LZO1X payload (含 EOF 尾标)。"""
    out = bytearray()

    # --- 流首: 初始字面量令牌 (1..238B), 覆盖 [0, first_gap_end) ---
    g0 = matches[0][0] if matches else n        # 首匹配前的字面量长度
    a = g0 if g0 < 238 else 238
    r = g0 - a
    out.append(a + 17)
    out += data[:a]
    if r:
        if r >= 4:
            _emit_run(out, r)
            out += data[a:g0]
        else:
            # 残 1..3 字节无法成段 → 缩初始段腾出 4 字节给标准段
            a2 = g0 - 4                          # ≥ 235 (g0 > 238 时才会到这里)
            del out[1:]                          # 回退重发
            out.append(a2 + 17)
            out += data[:a2]
            _emit_run(out, 4)
            out += data[a2:g0]

    # --- 逐匹配: 令牌 + 后置字面量 + (段) ---
    for idx in range(len(matches)):
        p, l, b = matches[idx]
        pend = matches[idx + 1][0] if idx + 1 < len(matches) else n
        gap = pend - (p + l)
        k = gap if gap < 3 else (3 if gap == 3 else 0)
        _emit_match(out, l, b, k, use_m1)
        if k:
            out += data[p + l:p + l + k]
        if gap >= 4:
            rl = gap - k
            _emit_run(out, rl)
            out += data[p + l + k:pend]

    out += b'\x11\x00\x00'                       # EOF: M1 back==0x4000, len=3 (实证)
    return bytes(out)


def _emit_run(out, rlen):
    """字面量段令牌 (rlen ≥ 4, 调用者随后追加 rlen 字节原文)。"""
    if rlen <= 18:
        out.append(rlen - 3)                     # x ∈ [1,15]
    else:
        out.append(0)                            # x=0 → 扩展
        rem = rlen - 3
        while rem > 270:                         # cnt = 15 + 255*j + b
            out.append(0)
            rem -= 255
        out.append(rem - 15)                     # b ∈ [1,255]


def _emit_match(out, l, b, k, use_m1):
    if l == 2:
        # M4: back ≤ 1024
        if b > 1024:
            raise ValueError('len2 匹配 back %d > 1024' % b)
        out.append((((b - 1) & 3) << 2) | k)
        out.append((b - 1) >> 2)
        return
    if b <= 2048 and l <= 8:
        # M2: len 3..8
        out.append(((l - 1) << 5) | (((b - 1) & 7) << 2) | k)
        out.append((b - 1) >> 3)
        return
    if use_m1 and b > 16384:
        # M1: back 16385..49151, len 2..9
        if not 16385 <= b <= 49151:
            raise ValueError('M1 back %d 越界' % b)
        if not 3 <= l <= 9:
            raise ValueError('M1 len %d 越界 (cnt==0 会触发扩展循环, 禁用)' % l)
        d = b - 16384
        bit = 1 if d >= 16384 else 0
        if bit:
            d -= 16384
        out.append(0x10 | (bit << 3) | (l - 2))
        out.append(((d & 63) << 2) | k)
        out.append(d >> 6)
        return
    # M3: back ≤ 16384, len 2..288+
    if b > 16384:
        raise ValueError('M3 back %d > 16384 (需 --m1)' % b)
    if l <= 33:
        out.append(0x20 | (l - 2))
    else:
        out.append(0x20)
        rem = l - 2
        while rem > 286:
            out.append(0)
            rem -= 255
        out.append(rem - 31)
    out.append((((b - 1) & 63) << 2) | k)
    out.append((b - 1) >> 6)


# ---------------------------------------------------------------- 帧与校验

def frame(data, level=5, **kw):
    """{u32 plen}{u32 osz}{payload} 单子流框架, 内含解码自检。"""
    payload = compress(data, level=level, **kw)
    fr = struct.pack('<II', len(payload), len(data)) + payload
    back, err, _ = lzo1x_decompress(payload, out_size=len(data))
    if err is not None or back != data:
        raise RuntimeError('LZO1X 自检失败: %s' % err)
    return fr


def _selftest():
    import random
    cases = {
        'empty-ish 1B': b'A',
        '3B': b'abc',
        '4B': b'abcd',
        'RLE 1000x00': b'\x00' * 1000,
        'all-same 70000': b'Q' * 70000,
        'random 64K': bytes(random.getrandbits(8) for _ in range(65536)),
        'text-ish': (b'the quick brown fox jumps over the lazy dog. ' * 800),
        'mixed': b''.join(
            (b'HELLO_WORLD_%d;' % k) * (1 + k % 7) for k in range(400)),
        'binary+zeros': bytes(random.getrandbits(8) for _ in range(30000)) +
                        b'\x00' * 5000 + b'PATTERNxyz' * 900,
    }
    ok = True
    for name, data in cases.items():
        for kwargs in ({'level': 1}, {'level': 5}, {'level': 7},
                       {'level': 5, 'use_m1': True}, {'level': 6, 'use_m4': True}):
            payload = compress(data, **kwargs)
            back, err, _ = lzo1x_decompress(payload, out_size=len(data))
            good = err is None and back == data
            # 也测无 out_size 模式 (解码到 EOF)
            back2, err2, _ = lzo1x_decompress(payload)
            good2 = err2 is None and back2 == data
            if not (good and good2):
                print('FAIL %-16s %s payload=%d err=%s/%s'
                      % (name, kwargs, len(payload), err, err2))
                ok = False
            else:
                print('PASS %-16s %-38s %6d -> %6d (%.1f%%)'
                      % (name, kwargs, len(data), len(payload),
                         100.0 * len(payload) / len(data)))
    print('SELFTEST %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 2


def _bench(expanded_path, orig_path=None):
    data = open(expanded_path, 'rb').read()
    print('输入: %s (%d 字节)' % (expanded_path, len(data)))
    orig = None
    if orig_path and os.path.exists(orig_path):
        orig = open(orig_path, 'rb').read()
        print('原盘基准: %d 字节 (%.2f%%)' % (len(orig),
                                              100.0 * len(orig) / len(data)))
    for lvl in (3, 4, 5, 6, 7):
        t0 = time.time()
        payload = compress(data, level=lvl, verbose=True)
        back, err, _ = lzo1x_decompress(payload, out_size=len(data))
        assert err is None and back == data, 'level %d 自检失败' % lvl
        print('level %d: payload %d B (%.2f%%) %s  [%.1fs]'
              % (lvl, len(payload), 100.0 * len(payload) / len(data),
                 ('vs 原盘 %+d B' % (len(payload) - len(orig))) if orig else '',
                 time.time() - t0))
    t0 = time.time()
    payload = compress(data, level=7, use_m1=True, verbose=True)
    back, err, _ = lzo1x_decompress(payload, out_size=len(data))
    assert err is None and back == data
    print('level 7 + M1(49K窗): payload %d B (%.2f%%)  [%.1fs]'
          % (len(payload), 100.0 * len(payload) / len(data), time.time() - t0))
    return 0


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    if argv[0] == 'selftest':
        return _selftest()
    if argv[0] == 'bench':
        return _bench(argv[1], argv[2] if len(argv) > 2 else None)
    if argv[0] == 'compress':
        src, dst = argv[1], argv[2]
        frame_out = '--frame' in argv
        use_m1 = '--m1' in argv
        level = 5
        if '--level' in argv:
            level = int(argv[argv.index('--level') + 1])
        chain = None
        if '--chain' in argv:
            chain = int(argv[argv.index('--chain') + 1])
        data = open(src, 'rb').read()
        t0 = time.time()
        payload = compress(data, level=level, use_m1=use_m1,
                           max_chain=chain, verbose=True)
        back, err, _ = lzo1x_decompress(payload, out_size=len(data))
        if err is not None or back != data:
            print('自检失败: %s' % err)
            return 2
        if frame_out:
            blob = struct.pack('<II', len(payload), len(data)) + payload
        else:
            blob = payload
        open(dst, 'wb').write(blob)
        print('%s -> %s: %d -> %d B (%.2f%%) level=%d m1=%s [%.1fs]'
              % (src, dst, len(data), len(blob),
                 100.0 * len(blob) / len(data), level, use_m1, time.time() - t0))
        return 0
    print(__doc__)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
