# -*- coding: utf-8 -*-
r"""mislib.py — 任务名(LZO1X 内嵌 XML 文本) 读写/依赖分析 公共库 (GR_MISNAMES 轮)

复用上一轮 M15 已验证的口径 (work/builds/GR_MISSIONTITLES/patch_zh144_m15_title.py):
  · 条目 = 若干 {u32 clen}{u32 rlen}{payload} 子流
  · payload = 标准 LZO1X (本工程 tools/hanliu/tools/lz77_decode.py 口径)
  · 名字 = 解压流里的 `<Name>...</Name>`, 由 `</Name>` 定界, 无 NUL/无长度前缀
  · 替换必须**恰好等长** (子流 rlen 固定), 短了用 0x20 空格填充
  · 名字字节可能被**后续匹配当源** ⇒ 必须同时改写那些匹配令牌

本库只做只读分析 + 令牌级改写; 写盘在 patch 脚本里。
"""
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))

import tcslib                                                        # noqa: E402
import zx_lib                                                        # noqa: E402
from lz77_decode import lzo1x_decompress                             # noqa: E402

NAME_RE = re.compile(rb'<Name>(.*?)</Name>', re.S)


# ============================== LZO1X 插桩解码器 (M15 轮已验证) ==============================
class Trace(object):
    """标准 LZO1X 解码 + 记录 (输出偏移, 类型, 长度, back, 令牌偏移, 字节来源)

    src[i] = ('L', payload_off) 或 ('M', back, i)
    ev     = [(out_off, 'lit'|'match', ip_start, ip_end, out_len, back|None, tok_off)]
    """

    def __init__(self, payload, out_size):
        self.d, self.ip, self.n = payload, 0, len(payload)
        self.out, self.src, self.ev = bytearray(), [], []
        self.out_size = out_size

    def g(self):
        b = self.d[self.ip]
        self.ip += 1
        return b

    def lit(self, cnt):
        o, i0 = len(self.out), self.ip
        self.out += self.d[self.ip:self.ip + cnt]
        for k in range(cnt):
            self.src.append(('L', i0 + k))
        self.ip += cnt
        if cnt:
            self.ev.append((o, 'lit', i0, self.ip, cnt, None, i0))

    def match(self, cnt, back, ntok):
        o, i0 = len(self.out), self.ip
        for i in range(cnt + 2):
            self.out.append(self.out[o - back + i])
            self.src.append(('M', back, i))
        self.ev.append((o, 'match', i0, self.ip, cnt + 2, back, i0 - ntok))

    def run(self):
        state, err = 0, None
        try:
            x = self.g()
            if x > 17:
                self.lit(x - 17)
                x = self.g()
            while err is None:
                if self.out_size is not None and len(self.out) >= self.out_size:
                    break
                ntok = 2
                if x > 15:
                    if x > 63:
                        cnt = (x >> 5) - 1
                        back = (self.g() << 3) + ((x >> 2) & 7) + 1
                    elif x > 31:
                        ntok = 3
                        cnt = x & 31
                        if cnt == 0:
                            while True:
                                x = self.g()
                                if x:
                                    cnt += 31 + x
                                    break
                                cnt += 255
                        x = self.g()
                        back = (self.g() << 6) + (x >> 2) + 1
                    else:
                        ntok = 3
                        cnt = x & 7
                        if cnt == 0:
                            while True:
                                x = self.g()
                                if x:
                                    cnt += 7 + x
                                    break
                                cnt += 255
                        back = (1 << 14) + ((x & 8) << 11)
                        x = self.g()
                        back += (self.g() << 6) + (x >> 2)
                        if back == (1 << 14):
                            break
                elif not state:
                    cnt = x & 15
                    if cnt == 0:
                        while True:
                            x = self.g()
                            if x:
                                cnt += 15 + x
                                break
                            cnt += 255
                    self.lit(cnt + 3)
                    x = self.g()
                    if x > 15:
                        continue
                    self.match(1, (1 << 11) + (self.g() << 2) + (x >> 2) + 1, 2)
                    state = cnt = x & 3
                    self.lit(cnt)
                    if self.out_size is not None and len(self.out) >= self.out_size:
                        break
                    if self.ip >= self.n:
                        break
                    x = self.g()
                    continue
                else:
                    cnt = 0
                    back = (self.g() << 2) + (x >> 2) + 1
                self.match(cnt, back, ntok)
                state = cnt = x & 3
                self.lit(cnt)
                if self.out_size is not None and len(self.out) >= self.out_size:
                    break
                if self.ip >= self.n:
                    break
                x = self.g()
        except IndexError as e:
            err = str(e)
        return bytes(self.out), err


# ============================== 子流 / 条目 ==============================
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
    """条目全部子流解压后拼起来; 返回 (blob, [每个子流的 out])"""
    raw = iso.read(e['iso_off'], e['stored'])
    parts, subs = [], substreams(raw)
    for (p, pay, S) in subs:
        out, err = decode_payload(pay, S)
        if err:
            raise RuntimeError('sub@%d: %s' % (p, err))
        parts.append(out)
    return b''.join(parts), parts


def iter_mis(iso):
    """枚举两个容器里带 <Name> 的 *.MIS 条目, 返回 [(tag, lba, entry)]"""
    out = []
    for lba, tag in ((tcslib.GR_LBA, 'GR.IMG'), (tcslib.MENU_LBA, 'MENU.IMG')):
        for e in zx_lib.entries(iso, lba):
            nm = e['name'].upper()
            if not nm.endswith('.MIS'):
                continue
            out.append((tag, lba, e))
    return out


# ============================== 令牌改写原语 ==============================
def form_of(pay, tok):
    x = pay[tok]
    return 'M2' if x > 63 else 'M3' if x > 31 else 'M1' if x > 15 else 'M4'


def back_max(pay, tok):
    f = form_of(pay, tok)
    return {'M2': 2048, 'M3': 16384, 'M1': 49152, 'M4': 1024}[f]


def tok_b1_off(pay, tok):
    """M3/M1 的 b1 偏移 (扩展长度时 b1 在扩展字节之后)"""
    x = pay[tok]
    f = form_of(pay, tok)
    if (f == 'M3' and (x & 31) == 0) or (f == 'M1' and (x & 7) == 0):
        i = tok + 1
        while pay[i] == 0:
            i += 1
        return i + 1
    return tok + 1


def encode_back(pay, tok, nb):
    """只改 back 距离, 令牌长度不变。"""
    f, x = form_of(pay, tok), pay[tok]
    if f == 'M2':
        assert nb <= 2048, nb
        return (tok, tok + 2, bytes([(x & 0xE3) | (((nb - 1) & 7) << 2), (nb - 1) >> 3]))
    if f == 'M4':
        assert nb <= 1024, nb
        return (tok, tok + 2, bytes([(((nb - 1) & 3) << 2) | (x & 3), (nb - 1) >> 2]))
    if f == 'M3':
        assert nb <= 16384, nb
        b1o = tok_b1_off(pay, tok)
        b1 = pay[b1o]
        return (b1o, b1o + 2, bytes([(((nb - 1) & 0x3F) << 2) | (b1 & 3), (nb - 1) >> 6]))
    raise SystemExit('M1 unsupported')


def cur_back(pay, tok):
    """从令牌字节反算当前 back (M2/M4 2 字节; M3 3 字节)"""
    f, x = form_of(pay, tok), pay[tok]
    if f == 'M2':
        return (pay[tok + 1] << 3) + ((x >> 2) & 7) + 1
    if f == 'M4':
        return (pay[tok + 1] << 2) + (x >> 2) + 1
    if f == 'M3':
        b1o = tok_b1_off(pay, tok)
        b1, b2 = pay[b1o], pay[b1o + 1]
        return (b2 << 6) + (b1 >> 2) + 1
    raise SystemExit('M1 unsupported')


def tok_len(pay, tok):
    """令牌字节数 (M2/M4=2, M3=3)"""
    return 3 if form_of(pay, tok) == 'M3' else 2


def apply_ops(pay, ops):
    b = bytearray(pay)
    for (s, e, nb) in sorted(ops, key=lambda x: -x[0]):
        b[s:e] = nb
    return bytes(b)
