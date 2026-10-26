# -*- coding: utf-8 -*-
r"""misvar.py — 可变长度任务名改写内核 (GR_MISNAMES2 轮)

与上一轮 (GR_MISNAMES/mispatch.py, 等长+空格填充) 的区别:
  · **目标解压流可以变短** (中文名比英文名短 2..12 B), 子流 rlen / 条目 real 同步减;
  · **载荷长度必须精确回到原值** ⇒ 事后用「反优化(匹配→等值字面量)」补长、
    「M2↔M3 同 back 同长度互转」做 ±1 微调; 这样 sub1..N 的文件偏移、条目 stored 全不动。

四个部件:
  1) trace(pay, S)               — 严格按 tools/hanliu/tools/lz77_decode.py 口径解出一串"项目"
  2) solve_min(target, A, W, …)  — 把 target[A:A+W] 重新编码成**最小字节数**的合法 LZO1X 项目序列
                                   (DAG 最短路; 状态 0/1/2 = 可长字面量 / 刚过长字面量 / 刚过 post>0 匹配)
  3) 修复循环                    — 逐个匹配校验 `target[mo-back:…] == target[mo:…]`,
                                   成立就只改 back (重指, 2~3 B); 找不到等值源就附近做 ②
  4) rebalance                   — 把载荷长度精确补齐/削减到原值 (只动令牌, 输出逐字节不变)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))

from lzokit import enc_lit_run, enc_m2, enc_m4l, lit_cost            # noqa: E402
from lz77_decode import lzo1x_decompress                           # noqa: E402


def enc_m4(back, post, data):
    """M4: state!=0 时的紧凑 len=2 匹配, back 1..1024"""
    assert 1 <= back <= 1024 and 0 <= post <= 3
    v = back - 1
    return bytes([((v & 3) << 2) | post, (v >> 2) & 0xFF]) + data


def enc_m3(back, mlen, post, data):
    """M3: len 3..1200 (扩展长度), back 1..16384"""
    assert 3 <= mlen <= 1200 and 1 <= back <= 16384 and 0 <= post <= 3
    c = mlen - 2
    out = bytearray()
    if c <= 31:
        out.append(0x20 | c)
    else:
        k = (c - 32) // 255
        out.append(0x20)
        out += b'\x00' * k
        out.append(c - 31 - 255 * k)
    v = back - 1
    out.append(((v & 0x3F) << 2) | post)
    out.append((v >> 6) & 0xFF)
    return bytes(out) + data


# ═════════════════════════════ 1. 项目级解码 ═════════════════════════════
def trace(pay, S):
    """→ (out_bytes, items)。items 按载荷升序、首尾相接覆盖整条 payload。

    item = dict(kind='L'|'M'|'T', out, out_len, pay, pay_len, form, back, mlen, post)
      · 'L' 长字面量段; · 'M' 匹配+后置字面量 (out_len = mlen + post); · 'T' 流尾
    """
    ip, n = 0, len(pay)
    out = bytearray()
    items = []
    state = 0

    def gb():
        nonlocal ip
        if ip >= n:
            raise IndexError('payload depleted at %d' % ip)
        b = pay[ip]
        ip += 1
        return b

    def add_lit(tok, cnt):
        nonlocal ip
        o = len(out)
        out.extend(pay[ip:ip + cnt])
        ip += cnt
        items.append(dict(kind='L', out=o, out_len=cnt, pay=tok, pay_len=ip - tok,
                          form=None, back=None, mlen=0, post=0))

    def add_match(tok, mlen, back, post, form):
        nonlocal ip
        o = len(out)
        if back > o:
            raise ValueError('INVALID BACK %d at out=%d' % (back, o))
        for i in range(mlen):
            out.append(out[o - back + i])
        d0 = ip
        out.extend(pay[ip:ip + post])
        ip += post
        items.append(dict(kind='M', out=o, out_len=mlen + post, pay=tok,
                          pay_len=(d0 - tok) + post, form=form, back=back,
                          mlen=mlen, post=post))

    x = gb()
    if x > 17:                                   # 首令牌: 字面量段
        add_lit(0, x - 17)
        x = gb()

    while len(out) < S:
        if x > 15:
            tok = ip - 1
            if x > 63:                            # M2
                cnt = (x >> 5) - 1
                back = (gb() << 3) + ((x >> 2) & 7) + 1
                post, form = x & 3, 'M2'
                add_match(tok, cnt + 2, back, post, form)
            elif x > 31:                          # M3
                cnt = x & 31
                if cnt == 0:
                    while True:
                        b = gb()
                        if b:
                            cnt += 31 + b
                            break
                        cnt += 255
                b1 = gb()
                back = (gb() << 6) + (b1 >> 2) + 1
                post, form = b1 & 3, 'M3'
                add_match(tok, cnt + 2, back, post, form)
            else:                                 # M1 (长 back) / EOS
                cnt = x & 7
                if cnt == 0:
                    while True:
                        b = gb()
                        if b:
                            cnt += 7 + b
                            break
                        cnt += 255
                b1 = gb()
                back = (1 << 14) + ((x & 8) << 11) + (gb() << 6) + (b1 >> 2)
                if back == (1 << 14):             # 流结束标记
                    items.append(dict(kind='T', out=len(out), out_len=0, pay=tok,
                                      pay_len=ip - tok, form='EOS', back=0,
                                      mlen=0, post=0))
                    return bytes(out), items
                post, form = b1 & 3, 'M1'
                add_match(tok, cnt + 2, back, post, form)
            state = post
            if len(out) >= S or ip >= n:
                break
            x = gb()
        elif state == 0:                          # 长字面量段
            tok = ip - 1
            cnt = x & 15
            if cnt == 0:
                while True:
                    b = gb()
                    if b:
                        cnt += 15 + b
                        break
                    cnt += 255
            add_lit(tok, cnt + 3)
            if len(out) >= S or ip >= n:
                break
            x = gb()
            if x > 15:
                continue
            tok2 = ip - 1                          # M4L: 长字面量段之后的 len=3 匹配
            back = (1 << 11) + (gb() << 2) + (x >> 2) + 1
            post = x & 3
            add_match(tok2, 3, back, post, 'M4L')
            state = post
            if len(out) >= S or ip >= n:
                break
            x = gb()
        else:                                     # M4: state!=0 时的紧凑 len=2 匹配
            tok = ip - 1
            back = (gb() << 2) + (x >> 2) + 1
            post = x & 3
            add_match(tok, 2, back, post, 'M4')
            state = post
            if len(out) >= S or ip >= n:
                break
            x = gb()

    if ip < len(pay):
        items.append(dict(kind='T', out=len(out), out_len=0, pay=ip,
                          pay_len=len(pay) - ip, form='EOS', back=0, mlen=0, post=0))
    return bytes(out), items


def enc_item(form, back, mlen, post, data):
    if form == 'M2':
        return enc_m2(back, mlen, post, data)
    if form == 'M3':
        return enc_m3(back, mlen, post, data)
    if form == 'M4':
        return enc_m4(back, post, data)
    if form == 'M4L':
        return enc_m4l(back, post, data)
    if form == 'M1':
        return enc_m1(back, mlen, post, data)
    raise ValueError('form %s' % form)


def enc_m1(back, mlen, post, data):
    """M1: 16<=x<32, back 16384..49151, len 2..9"""
    assert 16384 <= back <= 49151 and 2 <= mlen <= 9 and 0 <= post <= 3
    u = back - 16384
    assert u != 0
    x = 16 | ((u >> 11) & 8) | ((mlen - 2) & 7)
    b1 = ((u & 0x3F) << 2) | post
    b2 = (u >> 6) & 0xFF
    return bytes([x, b1, b2]) + data


def state_after(it):
    if it['kind'] == 'L':
        return 1
    return 0 if it['post'] == 0 else 2


def forms_for(mlen, back, st):
    """在给定状态下能表达 (mlen, back) 的形式, 按字节数升序"""
    out = []
    if mlen == 2:
        if st == 2 and back <= 1024:
            out.append('M4')
    elif mlen == 3 and st == 1 and 2049 <= back <= 3072:
        out.append('M4L')
    if 3 <= mlen <= 8:
        if back <= 2048:
            out.append('M2')
        if back <= 16384:
            out.append('M3')
    elif 9 <= mlen <= 33:
        if back <= 16384:
            out.append('M3')
    if 2 <= mlen <= 9 and back >= 16384:
        out.append('M1')
    return out


# ═════════════════════════════ 2. 最小代价窗口重编码 ═════════════════════════════
def solve_min(target, A, W, st0, en, maxL=33):
    """把 target[A:A+W] 编码成合法项目序列, 字节数最小。
    st0: 编码开始时的状态; en: 结束时必须处于的状态。
    返回 (bytes, cost) 或 (None, None)。"""
    best = [dict() for _ in range(W + 1)]
    best[0][st0] = (0, None)
    src = [dict() for _ in range(W)]
    for p in range(W):
        ap = A + p
        row = {}
        for L in range(2, min(maxL, W - p) + 1):
            s = target.rfind(target[ap:ap + L], 0, ap)
            if s >= 0:
                row[L] = s
        src[p] = row

    def relax(p, st, cost, prev):
        cur = best[p].get(st)
        if cur is None or cost < cur[0]:
            best[p][st] = (cost, prev)

    for p in range(W + 1):
        if not best[p]:
            continue
        for st in list(best[p].keys()):
            cost = best[p][st][0]
            if p == W:
                continue
            if st == 0:
                for L in range(4, min(W - p, 290) + 1):
                    relax(p + L, 1, cost + lit_cost(L) + L, (p, st, ('L', L)))
            row = src[p]
            for L in range(2, min(maxL, W - p) + 1):
                s = row.get(L)
                if s is None:
                    continue
                b = A + p - s
                for form in forms_for(L, b, st):
                    mc = len(enc_item(form, b, L, 0, b''))
                    for post in range(4):
                        if p + L + post > W:
                            break
                        relax(p + L + post, 0 if post == 0 else 2,
                              cost + mc + post, (p, st, ('M', form, L, b, post)))

    if en is None:
        cands = [(best[W][st][0], st) for st in best[W]]
        if not cands:
            return None, None
        cost, en = min(cands)
    else:
        if en not in best[W]:
            return None, None
        cost = best[W][en][0]
    chunks = []
    key = (W, en)
    while True:
        prev = best[key[0]][key[1]][1]
        if prev is None:
            break
        pp, ps, dec = prev
        if dec[0] == 'L':
            L = dec[1]
            chunks.append(enc_lit_run(L, target[A + pp:A + pp + L]))
        else:
            _, form, L, b, post = dec
            data = target[A + pp + L:A + pp + L + post]
            chunks.append(enc_item(form, b, L, post, data))
        key = (pp, ps)
    out = b''.join(reversed(chunks))
    assert len(out) == cost, (len(out), cost)
    return out, cost


# ═════════════════════════════ 3. 位置映射 ═════════════════════════════
def build_target(out0, regions):
    """regions: [(start, end, newbytes)] (原始输出坐标, 互不重叠) → target"""
    target = bytearray()
    pos = 0
    for (a, b, nb) in sorted(regions):
        assert a >= pos
        target += out0[pos:a]
        target += nb
        pos = b
    target += out0[pos:]
    return bytes(target)


def ends_of(regions):
    ends, cum = [], 0
    for (a, b, nb) in sorted(regions):
        cum += len(nb) - (b - a)
        ends.append((b, cum))
    return ends


def map_pos(ends, p):
    d = 0
    for (end, cum) in ends:
        if end <= p:
            d = cum
    return p + d


# ═════════════════════════════ 4. 主规划 ═════════════════════════════
class PlanError(Exception):
    def __init__(self, msg, stats=None):
        Exception.__init__(self, msg)
        self.stats = stats or {}


def en_for_next(nxt):
    """窗口之后那个项目要求窗口以什么状态收尾 (None = 任意)"""
    if nxt is None:
        return None
    if nxt['kind'] == 'L':
        return 0                       # 长字面量段要 decoder state == 0
    if nxt['kind'] == 'M' and nxt['form'] == 'M4L':
        return 1                       # 必须刚读完长字面量段
    if nxt['kind'] == 'M' and nxt['form'] == 'M4':
        return 2                       # 紧凑 len=2 匹配要 state != 0
    return None                        # M2/M3/M1/T: 只看 x>15


def choose_window(items, idx0, idx1, target, ends, max_left=6, max_right=8,
                  maxW=400, dbg=False):
    """在 idx0..idx1 外围找窗口, 用 DP 最小代价重编码; 选 (cost-old) 最小的。"""
    best = None
    for left in range(0, max_left + 1):
        j0 = idx0 - left
        if j0 < 0:
            break
        for right in range(0, max_right + 1):
            j1 = idx1 + right
            if j1 >= len(items):
                break
            A = items[j0]['out']
            B = items[j1]['out'] + items[j1]['out_len']
            st0 = state_after(items[j0 - 1]) if j0 > 0 else 0
            nxt = items[j1 + 1] if j1 + 1 < len(items) else None
            en = en_for_next(nxt)
            A2 = map_pos(ends, A)
            B2 = map_pos(ends, B)
            W = B2 - A2
            if W <= 0 or W > maxW:
                continue
            enc, cost = solve_min(target, A2, W, st0, en)
            if enc is None:
                if dbg:
                    print('      win %d..%d W=%d st=%s en=%s -> None'
                          % (j0, j1, W, st0, en))
                continue
            old = sum(items[t]['pay_len'] for t in range(j0, j1 + 1))
            key = (cost - old, j1 - j0, cost)
            if best is None or key < best[0]:
                best = (key, cost, old, j0, j1, enc, A, B)
            if items[j1]['kind'] == 'T':
                break
    return best


def plan_entry(pay0, S0, out0, regions, dbg=False, max_round=600,
               max_left=6, max_right=8):
    """返回 dict(newpay, target, notes, stats)；失败抛 PlanError。"""
    regions = [(a, b, bytes(nb)) for (a, b, nb) in sorted(regions)]
    target = build_target(out0, regions)
    ends = ends_of(regions)
    notes = []
    out, items = trace(pay0, S0)
    if out != out0:
        raise PlanError('base trace mismatch')

    # ---- 4.1 覆盖改动区的项目 → 窗口 ----
    hit = [i for i, it in enumerate(items)
           if any(it['out'] < b and it['out'] + it['out_len'] > a for (a, b, _) in regions)]
    if not hit:
        raise PlanError('no item covers regions')
    i0, i1 = hit[0], hit[-1]
    best = choose_window(items, i0, i1, target, ends, max_left, max_right, dbg=dbg)
    if best is None:
        raise PlanError('window DP failed')
    key, cost, old, j0, j1, enc, A, B = best
    A2w = map_pos(ends, A)
    B2w = map_pos(ends, B)
    notes.append('窗口 items[%d..%d] 输出 0x%X..0x%X (%d B) 载荷 %d -> %d B (%+d)'
                 % (j0, j1, A, B, B - A, old, cost, cost - old))

    pieces = [pay0[it['pay']:it['pay'] + it['pay_len']] for it in items[:j0]]
    pieces.append(enc)
    pieces += [pay0[it['pay']:it['pay'] + it['pay_len']] for it in items[j1 + 1:]]
    newpay = b''.join(pieces)

    # ---- 4.1b 先把"源在改动区之前、目标在改动区之后"的匹配 back 平移 ----
    R0 = min(a for (a, b, _) in regions)
    dtot = len(target) - len(out0)
    sh = cost - old
    pre = 0
    if dtot:
        buf = bytearray(newpay)
        for it in items[j1 + 1:]:
            if it['kind'] != 'M':
                continue
            src0 = it['out'] - it['back']
            src1 = src0 + it['mlen']
            if src1 > R0:
                continue
            nb = it['back'] + dtot
            if nb < 1:
                continue
            o2 = map_pos(ends, it['out'])
            data = target[o2 + it['mlen']:o2 + it['out_len']]
            try:
                enc2 = enc_item(it['form'], nb, it['mlen'], it['post'], data)
            except AssertionError:
                continue
            if len(enc2) != it['pay_len']:
                continue
            buf[it['pay'] + sh:it['pay'] + sh + it['pay_len']] = enc2
            pre += 1
        newpay = bytes(buf)
    if pre:
        notes.append('预先平移 %d 处跨区匹配的 back (%+d)' % (pre, dtot))

    # ---- 4.2 修复循环: 逐个匹配校验 ----
    fixed = 0
    fix_notes = []
    stats = dict(window=(j0, j1, old, cost), fixed=0)
    for _round in range(max_round):
        out1, its = trace(newpay, len(target))
        bad = None
        for idx, it in enumerate(its):
            if it['kind'] != 'M':
                continue
            mo = it['out']
            if mo - it['back'] < 0 or \
                    target[mo - it['back']:mo - it['back'] + it['mlen']] != target[mo:mo + it['mlen']]:
                bad = (idx, it)
                break
        if bad is None:
            if out1 != target:
                k = next(i for i in range(min(len(out1), len(target))) if out1[i] != target[i])
                raise PlanError('output differs at 0x%X (no bad match)' % k, stats)
            break
        idx, it = bad
        want = target[it['out']:it['out'] + it['mlen']]
        st = state_after(its[idx - 1]) if idx > 0 else 0
        data = target[it['out'] + it['mlen']:it['out'] + it['out_len']]
        cand = None
        for s in range(it['out'] - it['mlen'], -1, -1):
            if target[s:s + it['mlen']] == want:
                b = it['out'] - s
                fs = forms_for(it['mlen'], b, st)
                if fs:
                    cand = (s, b, fs[0])
                    break
        if cand is not None:
            s, b, form = cand
            nb = enc_item(form, b, it['mlen'], it['post'], data)
            newpay = newpay[:it['pay']] + nb + newpay[it['pay'] + it['pay_len']:]
            fixed += 1
            fix_notes.append('重指 %r out=0x%X back %d->%d (%s)'
                             % (want[:12], it['out'], it['back'], b, form))
            continue
        got = None
        for left in range(0, 13):
            w0 = idx - left
            if w0 < 0:
                break
            for right in range(0, 6):
                w1 = idx + right
                if w1 >= len(its):
                    break
                A2 = its[w0]['out']
                B2 = its[w1]['out'] + its[w1]['out_len']
                st2 = state_after(its[w0 - 1]) if w0 > 0 else 0
                nxt2 = its[w1 + 1] if w1 + 1 < len(its) else None
                en2 = en_for_next(nxt2)
                enc2, cost2 = solve_min(target, A2, B2 - A2, st2, en2)
                if enc2 is None:
                    continue
                got = (w0, w1, enc2)
                break
            if got:
                break
        if got is None:
            raise PlanError('cannot fix match at out 0x%X %r (st=%d mlen=%d post=%d)'
                            % (it['out'], want[:12], st, it['mlen'], it['post']), stats)
        w0, w1, enc2 = got
        newpay = newpay[:its[w0]['pay']] + enc2 + \
            newpay[its[w1]['pay'] + its[w1]['pay_len']:]
        fixed += 1
        fix_notes.append('局部重编码 items[%d..%d] out 0x%X..0x%X (%d B)'
                         % (w0, w1, its[w0]['out'], its[w1]['out'] + its[w1]['out_len'],
                            its[w1]['out'] + its[w1]['out_len'] - its[w0]['out']))

    if fixed:
        notes.append('修复 %d 处 (重指/局部重编码)' % fixed)
        notes.extend(fix_notes)
    stats['fixed'] = fixed
    stats['fix_notes'] = fix_notes

    # ---- 4.3 载荷长度精确回原 ----
    need = len(pay0) - len(newpay)
    stats['natural_need'] = need
    if need != 0:
        newpay, ops = fit_length(newpay, target, len(pay0), delta_total=dtot,
                                 near=B2w, dbg=dbg)
        stats['ops'] = ops
        notes.append('载荷长度调节 %+d B: %s' % (need, ' ; '.join(ops)))

    # ---- 4.4 终验 ----
    if len(newpay) != len(pay0):
        raise PlanError('payload length %d != %d' % (len(newpay), len(pay0)), stats)
    got, err, _ = lzo1x_decompress(newpay, out_size=len(target))
    if err is not None or got != target:
        tr2, its2 = trace(newpay, len(target))
        print('      [diag] trace==target: %s  real decode len=%d err=%r'
              % (tr2 == target, len(got), err))
        k = next((i for i in range(min(len(tr2), len(target))) if tr2[i] != target[i]), None)
        print('      [diag] trace first diff at %r' % (k,))
        if k is not None:
            it = next((x for x in its2 if x['out'] <= k < x['out'] + max(1, x['out_len'])), None)
            print('      [diag] item at diff: %r' % (it,))
            j = its2.index(it) if it in its2 else 0
            for x in its2[max(0, j - 3):j + 4]:
                print('        ', x['kind'], x['form'], 'out', hex(x['out']),
                      x['out_len'], 'pay', x['pay'], x['pay_len'], 'back', x['back'],
                      'mlen', x['mlen'], 'post', x['post'])
        open(os.path.join(HERE, 'out', '_fail_newpay.bin'), 'wb').write(newpay)
        open(os.path.join(HERE, 'out', '_fail_target.bin'), 'wb').write(target)
        raise PlanError('final decode mismatch: %r len=%d/%d'
                        % (err, len(got), len(target)), stats)
    stats['clen'] = len(newpay)
    return dict(newpay=newpay, target=target, notes=notes, stats=stats)


def tail_trim(pay, target, k):
    """从最后一个输出项目里裁掉 k 字节 (仅当它是长字面量段且裁后仍 >=4 B)。
    这些字节解码器永远读不到 (rlen 已变短), 故输出不变。返回 (newpay, done)。"""
    out, its = trace(pay, len(target))
    assert out == target
    last = None
    for it in reversed(its):
        if it['kind'] in ('L', 'M'):
            last = it
            break
    if last is None or last['kind'] != 'L':
        return pay, 0
    L = last['out_len']
    if L - k < 4:
        return pay, 0
    nb = enc_lit_run(L - k, target[last['out']:last['out'] + L - k])
    newpay = pay[:last['pay']] + nb + pay[last['pay'] + last['pay_len']:]
    return newpay, k


def rebalance(pay, target, need, delta_total=0, near=None):
    """把载荷长度改 need 字节 (need>0 变长, need<0 变短), 输出逐字节不变。
    near: 改动窗口的输出偏移 (目标口径); 补偿 op 尽量靠近它 ⇒ 位移区间最短。"""
    ops = []

    def dist(it):
        return abs(it['out'] - near) if near is not None else 0

    for _round in range(400):
        if need == 0:
            break
        out, its = trace(pay, len(target))
        assert out == target
        if need > 0:
            cands = []
            for idx, it in enumerate(its):
                prev = its[idx - 1] if idx > 0 else None
                nxt = its[idx + 1] if idx + 1 < len(its) else None
                d = deopt_delta(it, prev, nxt)
                if 0 < d <= need:
                    cands.append((d, idx, dist(it)))
            pick = None
            exact = [c for c in cands if c[0] == need]
            if exact:
                pick = [min(exact, key=lambda c: c[2])[1]]
            if pick is None:
                near_c = sorted(cands, key=lambda c: c[2])[:80]
                best = None
                for i in range(len(near_c)):
                    for j in range(i + 1, len(near_c)):
                        if near_c[i][0] + near_c[j][0] != need:
                            continue
                        sc = max(near_c[i][2], near_c[j][2])
                        if best is None or sc < best[0]:
                            best = (sc, [near_c[i][1], near_c[j][1]])
                if best:
                    pick = best[1]
            if pick is None:
                small = [c for c in cands if c[0] <= need]
                if small:
                    pick = [min(small, key=lambda c: c[2])[1]]
            if pick:
                for idx in sorted(pick, reverse=True):
                    it = its[idx]
                    L = it['mlen'] + it['post']
                    data = target[it['out']:it['out'] + L]
                    nb = enc_lit_run(L, data)
                    pay = pay[:it['pay']] + nb + pay[it['pay'] + it['pay_len']:]
                    need -= len(nb) - it['pay_len']
                    ops.append('反优化 out=0x%X %dB匹配->%dB字面量 (%+d, 距窗口 0x%X)'
                               % (it['out'], it['pay_len'], len(nb),
                                  len(nb) - it['pay_len'], it['out'] - (near or 0)))
                continue
            done = False
            m2 = [it for it in its if it['kind'] == 'M' and it['form'] == 'M2']
            if m2:
                it = min(m2, key=dist)
                data = target[it['out'] + it['mlen']:it['out'] + it['out_len']]
                nb = enc_m3(it['back'], it['mlen'], it['post'], data)
                assert len(nb) == it['pay_len'] + 1
                pay = pay[:it['pay']] + nb + pay[it['pay'] + it['pay_len']:]
                need -= 1
                ops.append('M2->M3 out=0x%X (+1, 距窗口 0x%X)'
                           % (it['out'], it['out'] - (near or 0)))
                done = True
            if not done:
                raise PlanError('cannot grow payload by %d' % need)
        else:
            if delta_total < 0 and -need <= -delta_total:
                pay2, k = tail_trim(pay, target, -need)
                if k:
                    pay = pay2
                    need += k
                    ops.append('尾字面量裁剪 %d B (解码器读不到的部分)' % k)
                    continue
            m3 = [it for it in its if it['kind'] == 'M' and it['form'] == 'M3'
                  and it['mlen'] <= 8 and it['back'] <= 2048]
            if m3:
                it = min(m3, key=dist)
                data = target[it['out'] + it['mlen']:it['out'] + it['out_len']]
                nb = enc_m2(it['back'], it['mlen'], it['post'], data)
                assert len(nb) == it['pay_len'] - 1
                pay = pay[:it['pay']] + nb + pay[it['pay'] + it['pay_len']:]
                need += 1
                ops.append('M3->M2 out=0x%X (-1)' % it['out'])
                continue
            raise PlanError('cannot shrink payload by %d' % -need)
    if need != 0:
        raise PlanError('rebalance left %d' % need)
    return pay, ops


def shrink_scan(pay, target, want, width=9, step=5, max_windows=8, dbg=False,
                maxW=400, near=None):
    """在载荷里找窗口, DP 重编码后比原编码更省; 累积省 >= want。
    返回 (newpay|None, saved, ops)。所有窗口输出逐字节不变。"""
    out, its = trace(pay, len(target))
    if out != target:
        return None, 0, []
    n = len(its)
    cands = []
    for w0 in range(1, max(2, n - width - 1), step):
        w1 = w0 + width
        if w1 >= n:
            break
        if its[w0]['kind'] == 'T' or its[w1]['kind'] == 'T':
            break
        A = its[w0]['out']
        B = its[w1]['out'] + its[w1]['out_len']
        W = B - A
        if W <= 0 or W > maxW:
            continue
        st = state_after(its[w0 - 1])
        en = en_for_next(its[w1 + 1] if w1 + 1 < n else None)
        enc, cost = solve_min(target, A, W, st, en)
        if enc is None:
            continue
        old = sum(its[t]['pay_len'] for t in range(w0, w1 + 1))
        d = cost - old
        if d < 0:
            cands.append((d, w0, w1, enc, old))
    if near is not None:
        cands.sort(key=lambda c: (abs(its[(c[1] + c[2]) // 2]['out'] - near), c[0]))
    else:
        cands.sort(key=lambda c: (c[0], c[1]))
    picked, covered, total = [], [], 0
    for (d, w0, w1, enc, old) in cands:
        if total >= want:
            break
        if any(not (w1 < a or w0 > b) for (a, b) in covered):
            continue
        picked.append((w0, w1, enc, d, old))
        covered.append((w0, w1))
        total += -d
    if dbg:
        print('      shrink_scan: cands=%d picked=%d saved=%d want=%d'
              % (len(cands), len(picked), total, want))
    if total < want:
        return None, 0, []
    pay2 = pay
    for (w0, w1, enc, d, old) in sorted(picked, key=lambda x: -x[0]):
        pay2 = pay2[:its[w0]['pay']] + enc + pay2[its[w1]['pay'] + its[w1]['pay_len']:]
    ops = ['窗口找省 items[%d..%d] 载荷 %d->%d (%+d)'
           % (w0, w1, old, old + d, d) for (w0, w1, _e, d, old) in picked]
    return pay2, total, ops


def fit_length(pay, target, orig_len, delta_total=0, near=None, dbg=False):
    """把载荷长度精确调回 orig_len; 输出逐字节不变。返回 (pay, ops)。"""
    ops = []
    chk, _ = trace(pay, len(target))[0], None
    if chk != target:
        raise PlanError('fit_length: decode mismatch')
    need = orig_len - len(pay)
    if need == 0:
        return pay, ops
    if need > 0:
        pay, o2 = rebalance(pay, target, need, delta_total, near)
        return pay, ops + o2
    want = -need
    if delta_total < 0:
        pay2, k = tail_trim(pay, target, min(want, -delta_total))
        if k:
            pay = pay2
            need += k
            want -= k
            ops.append('尾字面量裁剪 %d B' % k)
    if want:
        pay2, saved, o3 = shrink_scan(pay, target, want, dbg=dbg, near=near)
        if pay2 is None:
            raise PlanError('cannot shrink payload by %d (no savings window)' % want)
        pay = pay2
        need += saved
        ops += o3
        if dbg:
            print('      after scan: need=%+d' % need)
    if need > 0:
        pay, o4 = rebalance(pay, target, need, delta_total, near)
        ops += o4
    return pay, ops


def deopt_delta(it, prev, nxt=None):
    """把该项目改成"等值长字面量"能增加的字节数 (0 = 不可行)。
    条件: 前一项是 post==0 的匹配 (decoder state 0), 后一项不是长字面量段。"""
    if it['kind'] != 'M' or it['form'] == 'M1':
        return 0
    if prev is None or prev['kind'] != 'M' or prev['post'] != 0:
        return 0
    if nxt is not None and (nxt['kind'] == 'L' or nxt['form'] == 'M4'):
        return 0
    L = it['mlen'] + it['post']
    if not (4 <= L <= 290):
        return 0
    ntok = it['pay_len'] - it['post']
    return lit_cost(L) + L - (ntok + it['post'])


def local_pad(pay, target, need, start_out, K=60):
    """在 start_out 之后的 K 个项目内凑出恰好 need 字节的补长。
    返回 (pay|None, labels)。"""
    out, its = trace(pay, len(target))
    if out != target:
        return None, []
    idx0 = 0
    for i, it in enumerate(its):
        if it['out'] >= start_out:
            idx0 = i
            break
    groups = []
    for idx in range(idx0, min(len(its), idx0 + K)):
        it = its[idx]
        prev = its[idx - 1] if idx > 0 else None
        nxt = its[idx + 1] if idx + 1 < len(its) else None
        g = []
        d = deopt_delta(it, prev, nxt)
        if 0 < d <= need:
            g.append((d, 'deopt'))
        if it['kind'] == 'M' and it['form'] == 'M2':
            g.append((1, 'm2m3'))
        if g:
            groups.append((idx, g))
    if not groups:
        return None, []
    best = {0: (idx0 - 1, [])}
    for (idx, g) in groups:
        new = dict(best)
        for s, (mi, ops) in best.items():
            for (d, kind) in g:
                ns = s + d
                if ns > need:
                    continue
                score = max(mi, idx)
                if ns not in new or score < new[ns][0]:
                    new[ns] = (score, ops + [(idx, kind)])
        best = new
    if need not in best:
        return None, []
    mi, ops = best[need]
    ops = sorted(ops, reverse=True)
    labels = []
    for (idx, kind) in ops:
        it = its[idx]
        if kind == 'deopt':
            d = deopt_delta(it, its[idx - 1] if idx > 0 else None,
                            its[idx + 1] if idx + 1 < len(its) else None)
            labels.append('反优化 out=0x%X (%+d, 紧邻窗口)' % (it['out'], d))
            L = it['mlen'] + it['post']
            nb = enc_lit_run(L, target[it['out']:it['out'] + L])
        else:
            labels.append('M2->M3 out=0x%X (+1, 紧邻窗口)' % it['out'])
            data = target[it['out'] + it['mlen']:it['out'] + it['out_len']]
            nb = enc_m3(it['back'], it['mlen'], it['post'], data)
            assert len(nb) == it['pay_len'] + 1
        pay = pay[:it['pay']] + nb + pay[it['pay'] + it['pay_len']:]
        try:
            chk, _its = trace(pay, len(target))
            if chk != target:
                k = next((i for i in range(min(len(chk), len(target))) if chk[i] != target[i]), None)
                print('      [local_pad] op %s idx=%d -> trace outputs differ at %r' % (kind, idx, k))
        except Exception as ex:
            print('      [local_pad] op %s idx=%d (out=0x%X) BROKE stream: %s'
                  % (kind, idx, its[idx]['out'], ex))
            print('        item: %r' % (its[idx],))
            prev = its[idx - 1] if idx > 0 else None
            nxt = its[idx + 1] if idx + 1 < len(its) else None
            print('        prev: %r' % (prev,))
            print('        next: %r' % (nxt,))
            open(os.path.join(HERE, 'out', '_fail_local.bin'), 'wb').write(pay)
            raise
    return pay, labels


def fit_local(pay, target, orig_len, anchor_out, delta_total=0, K=80, dbg=False):
    """优先在 anchor_out 附近把载荷长度调回 orig_len; 返回 (pay, ops, ok)。"""
    need = orig_len - len(pay)
    if need == 0:
        return pay, [], True
    if need > 0:
        pay2, ops = local_pad(pay, target, need, anchor_out, K)
        if pay2 is not None:
            if dbg:
                print('      fit_local: +%d 在锚点后 %d 项内解决' % (need, K))
            return pay2, ops, True
        return pay, [], False
    out, its = trace(pay, len(target))
    idx0 = 0
    for i, it in enumerate(its):
        if it['out'] >= anchor_out:
            idx0 = i
            break
    cands = []
    tot = 0
    for w0 in range(max(1, idx0), min(len(its) - 12, idx0 + 150), 3):
        w1 = w0 + 9
        A = its[w0]['out']
        B = its[w1]['out'] + its[w1]['out_len']
        if B - A > 400:
            continue
        st = state_after(its[w0 - 1])
        en = en_for_next(its[w1 + 1] if w1 + 1 < len(its) else None)
        enc, cost = solve_min(target, A, B - A, st, en)
        if enc is None:
            continue
        old = sum(its[t]['pay_len'] for t in range(w0, w1 + 1))
        if cost < old:
            cands.append((cost - old, w0, w1, enc, old))
            tot += old - cost
            if tot >= -need:
                break
    if cands and tot >= -need:
        picked, t2 = [], 0
        for c in cands:
            if t2 >= -need:
                break
            picked.append(c)
            t2 += -c[0]
        pay2 = pay
        for (d, w0, w1, enc, old) in sorted(picked, key=lambda x: -x[1]):
            pay2 = pay2[:its[w0]['pay']] + enc + pay2[its[w1]['pay'] + its[w1]['pay_len']:]
        ops = ['窗口找省 items[%d..%d] (%+d, 紧邻窗口)' % (w0, w1, d)
               for (d, w0, w1, _e, _o) in picked]
        return pay2, ops, True
    return pay, [], False
