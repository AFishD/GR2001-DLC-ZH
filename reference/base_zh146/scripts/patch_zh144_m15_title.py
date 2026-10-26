# -*- coding: utf-8 -*-
r"""patch_zh144_m15_title.py — GR_ZH143 -> GR_ZH144: 只把 M15 的任务名改成中文

★ 格式结论 (详见 docs/REPORT_MISSION_NAME.md):
  `M15_RED_SQUARE.MIS` 在 GR.IMG(#675) 与 MENU.IMG(#184) 各一份;
  每个条目 = 5 个 LZO1X 子流, 帧 = {u32 clen}{u32 rlen}{payload}。
  解压后是**纯文本 XML**; 任务名在 `<Name>M15 - White Razor</Name>` 里,
  **没有 NUL、没有长度前缀** —— 以 `</Name>` 结束, 长度可变
  (同盘 40 个任务的 <Name> 长度 11..21 字节不等)。

★ v3 的关键修正:
  v1/v2 把名字写死成 11 字节, 是因为只做**原地字面量替换**; 但 11 字节只是这段
  LZO 流里那一段的长度, 不是格式要求。正确做法是让解压内容**变短 7 字节**
  (White Razor 11 -> 白刃 4), 并同步 sub0 的 rlen / 条目的 real+stored:
    · sub0 输出 16384 -> 16377
    · 字面量段 "- White Razor</" (15 B) -> "- 白刃</" (8 B), 载荷 -7 B
    · 条目 real / stored 各 -7 (IMG 里条目后有 8 / 5 字节空隙, 变短不影响别人)
  标题宽度于是与同盘其它任务名 (M01 - 铁龙 / M14 - 柳弓) 一致, 居中恢复正常。

★ 为什么不能"只改这 11 字节"(v1 的教训):
  这 11 字节中的 't','e',' ','R' 被**后续 LZO 匹配**当作源引用
  ("te " at out CF, " R" at out 274; 其余 ~25 处级联)。缩段后这些匹配的 back
  距离是相对的、偏移自动跟随, 但**源内容**变了 ⇒ 用"逐匹配校验"把它们修好。

★ 自证: 重新解压两个条目, 必须**逐字节等于**"原解压流只替换成 白刃"的期望。

用法:
  python patch_zh144_m15_title.py
  python patch_zh144_m15_title.py --verify-only
"""
import argparse
import hashlib
import os
import struct
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))

import tcslib                                                        # noqa: E402
import zx_lib                                                       # noqa: E402
from lz77_decode import lzo1x_decompress                            # noqa: E402

HITS = [0xE613A7E, 0x6198DD0A]
NEEDLE = b'White Razor'
NEW = b'\xa7\xe6\xa9\xea'                   # 白刃 = 4 B (与语言表 M15 - 白刃 一致)
DELTA = len(NEW) - len(NEEDLE)              # -7
BASE_SHA = '52145319c15de639d392788bb0be56deeea7dc952f254c966fad1ceb5eed4d42'
ELF_LBA, ELF_BYTES = 295, 37453732
ELF_SHA = 'a0c8499cf30f1cc5c44dfb49502270ed0ecbdccb30c023246b227591c40ba12e'
ELF_CRC_XOR = '653FBF69'


# ============================== 插桩 LZO1X 解码器 ==============================
class Trace(object):
    """标准 LZO1X 解码 + 记录 (输出偏移, 类型, 长度, back, 令牌偏移)"""

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


# ============================== 只读工具 ==============================
def substreams(raw):
    out, p = [], 0
    while p + 8 <= len(raw):
        L, S = struct.unpack_from('<II', raw, p)
        if L == 0 or p + 8 + L > len(raw):
            break
        out.append((p, raw[p + 8:p + 8 + L], S))
        p += 8 + L
    return out


def decode_entry(raw):
    parts, errs = [], []
    for (p, pay, S) in substreams(raw):
        if len(pay) == S:
            out, err = pay, None
        else:
            out, err, _ = lzo1x_decompress(pay, out_size=S)
        if len(out) != S:
            err = err or 'out %d != %d' % (len(out), S)
        parts.append(out)
        errs.append(err)
    return b''.join(parts), errs


def find_entry(iso, h):
    for lba, tag in ((tcslib.GR_LBA, 'GR.IMG'), (tcslib.MENU_LBA, 'MENU.IMG')):
        for e in zx_lib.entries(iso, lba):
            if e['iso_off'] <= h < e['iso_off'] + e['stored']:
                return e, tag
    raise KeyError('no entry contains 0x%X' % h)


def hash_file(path, algo, buf=1 << 22):
    h = hashlib.new(algo)
    with open(path, 'rb') as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def elf_digest(path):
    h, c, left, tail = hashlib.sha256(), 0, ELF_BYTES, b''
    with open(path, 'rb') as f:
        f.seek(ELF_LBA * 2048)
        while left > 0:
            b = f.read(min(1 << 22, left))
            if not b:
                break
            h.update(b)
            buf = tail + b
            n = len(buf) // 4 * 4
            for (w,) in struct.iter_unpack('<I', buf[:n]):
                c ^= w
            tail = buf[n:]
            left -= len(b)
    return h.hexdigest(), '%08X' % (c & 0xFFFFFFFF)


# ============================== 令牌改写 ==============================
def form_of(pay, tok):
    x = pay[tok]
    return 'M2' if x > 63 else 'M3' if x > 31 else 'M1' if x > 15 else 'M4'


def encode_back(pay, tok, nb):
    """返回 (写入位置, 新字节)；只改 back 距离, 令牌长度与后置字面量数不变"""
    f, x = form_of(pay, tok), pay[tok]
    if f == 'M2':
        assert nb <= 2048, nb
        return tok, bytes([(x & 0xE3) | (((nb - 1) & 7) << 2), (nb - 1) >> 3])
    if f == 'M4':
        assert nb <= 1024, nb
        return tok, bytes([(((nb - 1) & 3) << 2) | (x & 3), (nb - 1) >> 2])
    if f == 'M3':
        assert nb <= 16384, nb
        b1 = pay[tok + 1]
        return tok + 1, bytes([((nb - 1) & 0x3F) << 2 | (b1 & 3), (nb - 1) >> 6])
    raise SystemExit('M1 unsupported')


def set_post(pay, tok, post):
    f, x = form_of(pay, tok), pay[tok]
    if f in ('M2', 'M4'):
        return (tok, bytes([(x & ~3) | post]))
    if f == 'M3':
        return (tok + 1, bytes([(pay[tok + 1] & ~3) | post]))
    raise SystemExit('M1 unsupported')


# ============================== 规划 ==============================
def plan_entry(pay0, rlen0):
    """把 sub0 里 "- White Razor</" 换成 "- 白刃</", 并把被波及的匹配修好"""
    tr0 = Trace(pay0, rlen0)
    out, err = tr0.run()
    assert err is None and len(out) == rlen0, err
    no = out.find(NEEDLE)
    assert no >= 0
    expected = out[:no] + NEW + out[no + len(NEEDLE):]
    rlen1 = len(expected)
    assert rlen1 == rlen0 + DELTA

    # 1) 覆盖名字的那一段字面量
    ev = [e for e in tr0.ev if e[1] == 'lit' and e[0] <= no < e[0] + e[4]]
    assert len(ev) == 1, ev
    o, _k, ia, _ib, cnt, _b, _t = ev[0]
    assert no + len(NEEDLE) <= o + cnt
    tok_run = ia - 1
    assert (pay0[tok_run] & 15) == cnt - 3, (pay0[tok_run], cnt)
    content = out[o:no] + NEW + out[no + len(NEEDLE):o + cnt]
    assert len(content) == cnt + DELTA and 4 <= len(content) <= 18, len(content)
    pay = bytearray(pay0[:tok_run] + bytes([len(content) - 3]) + content
                    + pay0[tok_run + 1 + cnt:])
    assert len(pay) == len(pay0) + DELTA

    notes = ['字面量段 %r (%d B) -> %r (%d B)；载荷 %d -> %d B'
             % (out[o:o + cnt], cnt, content, len(content), len(pay0), len(pay))]

    # 2) 逐匹配校验 + 修 (损坏的匹配 = 源字节与期望输出不符)
    for _round in range(600):
        tr = Trace(bytes(pay), rlen1)
        out1, err1 = tr.run()
        assert err1 is None and len(out1) == rlen1, (err1, len(out1))
        bad = None
        for e in tr.ev:
            if e[1] != 'match':
                continue
            mo, _kk, _ia2, _ib2, ln, back, tok = e
            if mo - back < 0 or expected[mo - back:mo - back + ln] != expected[mo:mo + ln]:
                bad = e
                break
        if bad is None:
            break
        mo, _kk, _ia2, _ib2, ln, back, tok = bad
        want = expected[mo:mo + ln]
        f = form_of(pay, tok)
        best = None
        for s in range(0, mo - ln + 1):
            if expected[s:s + ln] != want:
                continue
            nb = mo - s
            if (f == 'M4' and nb > 1024) or (f == 'M2' and nb > 2048):
                continue
            if f == 'M3' and nb > 16384:
                continue
            best = (nb, s)
        if best:
            nb, s = best
            pos, b = encode_back(pay, tok, nb)
            pay[pos:pos + len(b)] = b
            notes.append('重指 %-4r out 0x%X back %d->%d (src 0x%X->0x%X, %s)'
                         % (want, mo, back, nb, mo - back, s, f))
            continue
        prev = [e for e in tr.ev if e[1] == 'match' and e[0] + e[4] == mo]
        assert ln == 3 and len(prev) == 1, (want, ln, len(prev))
        po, _p, _pia, pib, _pln, _pb, ptok = prev[0]
        assert pib == tok
        done = False
        for (p, q) in ((2, 2), (3, 1), (1, 3)):
            mid = expected[mo + p:mo + p + 3]
            cand = [mo + p - s2 for s2 in range(0, mo + p - 2)
                    if expected[s2:s2 + 3] == mid and 0 < mo + p - s2 <= 2048]
            if not cand:
                continue
            nb = min(cand)
            pos, nb_bytes = set_post(pay, ptok, p)
            pay[pos:pos + len(nb_bytes)] = nb_bytes
            new6 = bytes(expected[mo:mo + p]) + \
                bytes([(2 << 5) | (((nb - 1) & 7) << 2) | q, (nb - 1) >> 3]) + \
                bytes(expected[mo + p + 3:mo + p + 3 + q])
            assert len(new6) == 6
            pay[tok:tok + 6] = new6
            notes.append('拆分 %r: prev(out 0x%X) post=%d + M2(%r, back=%d) + %d 字面量'
                         % (want, po, p, mid, nb, q))
            done = True
            break
        assert done, 'no fix for %r' % want
    out1, err1 = Trace(bytes(pay), rlen1).run()
    assert err1 is None and out1 == expected, 'simulation mismatch'

    # 3) 载荷缩短了 7 字节 ⇒ 在**靠后**的位置把某个匹配"反优化"成等值字面量,
    #    把载荷长度补回原值: sub1..4 的文件偏移、条目 stored 都不动。
    need = -DELTA
    if need:
        tr = Trace(bytes(pay), rlen1)
        out2, _ = tr.run()
        assert out2 == expected
        cands = []
        for e in tr.ev:
            if e[1] != 'match':
                continue
            mo, _kk, _ia, ib, ln, _bk, tok = e
            f = form_of(pay, tok)
            if f == 'M2':
                ntok, post = 2, pay[tok] & 3
            elif f == 'M3':
                ntok, post = 3, pay[tok + 1] & 3
            else:
                continue
            if post != 0 or ln < 4 or ln > 18 or ib >= len(pay) or pay[ib] <= 15:
                continue
            if mo < no + 0x40:            # 必须在名字之后: 保证名字仍在原 ISO 偏移上
                continue
            delta = (1 + ln) - ntok
            if 0 < delta <= need:
                cands.append((mo, tok, ntok, ln, delta))
        cands.sort(key=lambda c: abs(c[0] - no))   # 离名字越近越好: 位移区间最小

        def try_deopt(sel):
            t = bytearray(pay)
            for (mo, tok, ntok, ln, delta) in sorted(sel, key=lambda c: -c[1]):
                t[tok:tok + ntok] = bytes([ln - 3]) + expected[mo:mo + ln]
            if len(t) != len(pay0):
                return None
            oo, ee = Trace(bytes(t), rlen1).run()
            return bytes(t) if (ee is None and oo == expected) else None

        picked = None
        for c in cands:
            if c[4] == need:
                t = try_deopt([c])
                if t is not None:
                    picked, pay = [c], bytearray(t)
                    break
        if picked is None:
            for i in range(len(cands)):
                for j in range(i + 1, len(cands)):
                    if cands[i][4] + cands[j][4] != need:
                        continue
                    t = try_deopt([cands[i], cands[j]])
                    if t is not None:
                        picked, pay = [cands[i], cands[j]], bytearray(t)
                        break
                if picked is not None:
                    break
        assert picked is not None, 'cannot pad payload back by %d' % need
        for c in picked:
            notes.append('反优化 out 0x%X: %d B 匹配 -> %d B 字面量 (载荷 +%d, 输出不变)'
                         % (c[0], c[2], 1 + c[3], c[4]))
        assert len(pay) == len(pay0), (len(pay), len(pay0))
        out3, err3 = Trace(bytes(pay), rlen1).run()
        assert err3 is None and out3 == expected, 'de-opt broke the stream'
    return bytes(pay), expected, notes


# ============================== 主流程 ==============================
def build(base, out_path):
    print('[1] verify base image ...')
    bsha = hash_file(base, 'sha256')
    assert bsha == BASE_SHA, 'base sha256 mismatch: %s' % bsha
    bsz = os.path.getsize(base)
    print('    GR_ZH143.iso  sha256 = %s  OK' % bsha)

    print('[2] plan both entries ...')
    iso = tcslib.Iso(base)
    jobs = []
    for h in HITS:
        ent, tag = find_entry(iso, h)
        subs = substreams(iso.read(ent['iso_off'], ent['stored']))
        off0, pay0, rlen0 = subs[0]
        pay1, expected, notes = plan_entry(pay0, rlen0)
        new = struct.pack('<II', len(pay1), rlen0 + DELTA) + pay1
        for (p, pay, S) in subs[1:]:
            new += struct.pack('<II', len(pay), S) + pay
        assert len(new) == ent['stored'], 'entry size must stay identical'
        print('    %-9s idx=%-4d off=0x%09X  stored %d (不变)  real %d->%d  sub0 rlen %d->%d'
              % (tag, ent['idx'], ent['iso_off'], ent['stored'],
                 ent['real'], ent['real'] + DELTA, rlen0, rlen0 + DELTA))
        for n in notes:
            print('      * %s' % n)
        jobs.append(dict(tag=tag, ent=ent, new=new, expected=expected,
                         real=ent['real'] + DELTA))
    iso.close()
    del iso

    print('[3] copy base -> %s ...' % os.path.basename(out_path))
    with open(base, 'rb') as fi, open(out_path, 'wb') as fo:
        while True:
            b = fi.read(1 << 22)
            if not b:
                break
            fo.write(b)
    assert os.path.getsize(out_path) == bsz

    print('[4] write entries + IMG table (stored/real) ...')
    with open(out_path, 'r+b') as f:
        for j in jobs:
            e = j['ent']
            f.seek(e['iso_off'])
            f.write(j['new'])
            base_lba = tcslib.GR_LBA if j['tag'] == 'GR.IMG' else tcslib.MENU_LBA
            t = base_lba * 2048 + 0x830 + 48 * e['idx']
            f.seek(t + 4 * 7)
            f.write(struct.pack('<I', j['real']))
        f.flush()
        os.fsync(f.fileno())
    return bsz


def verify(base, out_path, bsz):
    print('[5] read back + decompress ...')
    iso = tcslib.Iso(out_path)
    iso143 = tcslib.Iso(base)
    ok = True
    for h in HITS:
        ent, tag = find_entry(iso, h)
        raw = iso.read(ent['iso_off'], ent['stored'])
        got, errs = decode_entry(raw)
        lba = tcslib.GR_LBA if tag == 'GR.IMG' else tcslib.MENU_LBA
        e143 = iso143.img_entry(lba, ent['idx'])
        want, _ = decode_entry(iso143.read(e143['iso_off'], e143['stored']))
        no = want.find(NEEDLE)
        want = want[:no] + NEW + want[no + len(NEEDLE):]
        same = (got == want) and all(e is None for e in errs)
        ok &= same
        i = got.find(b'<Name>')
        print('    %-9s idx=%-4d stored=%-6d real=%-6d decoded %d B / %d sub; '
              'matches expected: %s'
              % (tag, ent['idx'], ent['stored'], ent['real'], len(got), len(errs),
                 'YES' if same else 'NO'))
        print('      context: %r' % got[i:i + 40])
    iso.close()
    iso143.close()
    del iso, iso143

    print('[6] whole-image chunked scan (residue / diff) ...')
    CH = 1 << 24
    residue, diffs, off, prev = 0, [], 0, b''
    with open(base, 'rb') as f14, open(out_path, 'rb') as f15:
        while True:
            b14, b15 = f14.read(CH), f15.read(CH)
            if not b14 and not b15:
                break
            assert len(b14) == len(b15)
            buf = prev + b15
            base_i = len(prev)
            residue += sum(1 for i in range(len(buf))
                           if buf.startswith(NEEDLE, i) and i + len(NEEDLE) > base_i)
            prev = b15[-len(NEEDLE) + 1:]
            if b14 != b15:
                diffs.extend(off + i for i in range(len(b14)) if b14[i] != b15[i])
            off += len(b14)
    print('    "White Razor" residue: %d' % residue)
    print('    byte diff vs 143: %d' % len(diffs))
    if diffs:
        ranges, s, p = [], diffs[0], diffs[0]
        for d in diffs[1:]:
            if d > p + 64:
                ranges.append((s, p))
                s = d
            p = d
        ranges.append((s, p))
        for (s, p) in ranges:
            print('      0x%09X..0x%09X  (%d B)' % (s, p, p - s + 1))

    print('[7] identity ...')
    sz = os.path.getsize(out_path)
    esha, ecrc = elf_digest(out_path)
    print('    bytes  = %d   (same as 143: %s)' % (sz, sz == bsz))
    print('    sha256 = %s' % hash_file(out_path, 'sha256'))
    print('    md5    = %s' % hash_file(out_path, 'md5'))
    print('    ELF    = LBA %d / %d B   sha256 %s   crc32_xor %s'
          % (ELF_LBA, ELF_BYTES, esha, ecrc))
    ok &= (sz == bsz) and (esha == ELF_SHA) and (ecrc == ELF_CRC_XOR) and residue == 0
    print('\nRESULT: %s' % ('ALL PASS' if ok else 'FAILED'))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default=os.path.join(REPO, 'work', 'builds', 'GR_RELEASE',
                                                   'GR_ZH143.iso'))
    ap.add_argument('--out', default=os.path.join(REPO, 'work', 'builds', 'GR_RELEASE',
                                                  'GR_ZH144.iso'))
    ap.add_argument('--verify-only', action='store_true')
    a = ap.parse_args()
    bsz = os.path.getsize(a.base)
    if not a.verify_only:
        bsz = build(a.base, a.out)
    ok = verify(a.base, a.out, bsz)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
