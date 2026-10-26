# -*- coding: utf-8 -*-
r"""mispatch.py — 任务名等长替换 + LZO1X 令牌级修正 (M15 技术的通用化)

为什么需要"令牌级修正":
  名字那 L 个字节是 LZO 解压流里的**字面量**; 一旦改成中文, 后面那些
  back 指向名字区的**匹配**就会抄到错的数据 ⇒ 必须把它们重新编码。

做法 (与 M15 同一思路, 但**整条子流统一记账**):
  ① 把子流解析成"项目"序列 (literal / match) —— trace_items
  ② 标出"问题项目": 输出压在改动区上的, 以及**源**压在改动区上的匹配
  ③ 相邻问题项目合成窗口; 窗口放不下就把后面的窗口并进来一起编码
  ④ 窗口用 DP 重新编码 (输出逐字节 = 期望, 长度可变, 取最小)
  ⑤ 整条子流重建; 若比原来**短**, 把若干 M2 升成 M3 (同 back 同长度, +1 B) 补齐
     ⇒ 总载荷长度与原文件一模一样 ⇒ 子流帧 / 条目 stored / ISO 布局全不动
  ⑥ 用项目解码器回读, 必须逐字节等于"只有名字变化"的期望输出

DP 语法 = 本工程 lz77_decode.py 的 LZO1X 口径:
  项目 = (匹配令牌 + 后置字面量 0..3) 或 (长字面量段 >=4)
  长字面量段只能出现在"上一匹配后置字面量=0"之后, 其后必须是匹配令牌。
  状态: 0=自由  1=长字面量段之后 (只许 x>15 的匹配或 M4L)  2=匹配后置字面量>0 之后
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import mislib                                                        # noqa: E402


class Item(object):
    __slots__ = ('kind', 'pay', 'pay_len', 'out', 'out_len', 'back', 'post', 'form', 'mlen')

    def __init__(self, kind, pay, pay_len, out, out_len, back, post, form, mlen=0):
        self.kind, self.pay, self.pay_len = kind, pay, pay_len
        self.out, self.out_len = out, out_len
        self.back, self.post, self.form, self.mlen = back, post, form, mlen

    def __repr__(self):
        return 'Item(%s pay=0x%X/%d out=0x%X/%d back=%s post=%s %s)' % (
            self.kind, self.pay, self.pay_len, self.out, self.out_len,
            self.back, self.post, self.form)


def trace_items(pay, S):
    """→ (out, items): 项目按载荷升序, 首尾相接 (末尾可能有 3 字节 EOS 的 'T' 项目)"""
    tr = mislib.Trace(pay, S)
    out, err = tr.run()
    assert err is None, err
    assert len(out) == S, (len(out), S)
    items, p, skip = [], 0, None
    for (o, kind, ia, ib, ln, back, tok) in tr.ev:
        if kind == 'lit':
            if skip is not None and ia == skip[0] and ln == skip[1]:
                skip = None          # 上一条匹配的"后置字面量", 已算进匹配项目
                continue
            items.append(Item('L', p, ib - p, o, ln, None, None, None))
            p = ib
        else:
            # 令牌起点用"上一项目结束位置": Trace 的 tok 在扩展长度的 M3/M1 上会少算
            f = mislib.form_of(pay, p)
            post = pay[ib - 2] & 3   # M2/M4 取 x; M3/M1 取 b1 —— 都是令牌倒数第 2 字节
            items.append(Item('M', p, (ib - p) + post, o, ln + post, back, post, f, ln))
            p = ib + post
            skip = (ib, post) if post else None
    items.sort(key=lambda it: it.pay)
    q = 0
    for it in items:
        assert it.pay == q, (it, q)
        q += it.pay_len
    if q < len(pay):
        items.append(Item('T', q, len(pay) - q, S, 0, None, None, None))
        q = len(pay)
    assert q == len(pay), (q, len(pay))
    return out, items


# ───────────────────────── 编码原语 ─────────────────────────
def lit_cost(L):
    c = L - 3
    if c <= 15:
        return 1
    if c <= 270:
        return 2
    return 2 + (c - 270 + 254) // 255


def enc_lit_run(L, data):
    assert L >= 4 and len(data) == L
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


def enc_m4l(b, post, data):                    # 长字面量段之后的 2 字节匹配: len=3, back 2049..3072
    v = b - 1 - 2048
    assert 0 <= v <= 1023
    return bytes([((v & 3) << 2) | post, (v >> 2) & 0xFF]) + data


def enc_m2(b, L, post, data):                  # len 3..8, back <= 2048
    assert 3 <= L <= 8 and 1 <= b <= 2048
    v = b - 1
    return bytes([((L - 1) << 5) | ((v & 7) << 2) | post, (v >> 3) & 0xFF]) + data


def enc_m4(b, post, data):                     # len 2, back <= 1024 (仅 state 2)
    assert 2 <= b <= 1024
    v = b - 1
    return bytes([((v & 3) << 2) | post, (v >> 2) & 0xFF]) + data


def enc_m3(b, L, post, data):
    assert 3 <= L <= 33 and 1 <= b <= 16384, (L, b)
    v = b - 1
    return bytes([0x20 | (L - 2), ((v & 0x3F) << 2) | post, (v >> 6) & 0xFF]) + data


# ───────────────────────── 局部重编码 DP ─────────────────────────
def solve_window(target, A, W, budget, start_state, end_state, maxL=33, dbg=False):
    """把 target[A:A+W] 重新编码成 <= budget 字节的 LZO1X 载荷 (取最小长度)。
    返回 (bytes, cost) 或 (None, None)"""
    if W <= 0:
        return (b'', 0) if budget >= 0 else (None, None)
    lim = min(maxL, W)
    nb = []
    for p in range(W):
        row = [-1] * (lim + 1)
        ap = A + p
        for L in range(2, lim + 1):
            if p + L > W:
                break
            row[L] = target.rfind(target[ap:ap + L], 0, ap)
        nb.append(row)

    dp = {(0, 0, start_state): None}
    for p in range(W + 1):
        cur = sorted([(c, s) for (pp, c, s) in dp if pp == p])
        for (cost, st) in cur:
            if p == W:
                continue
            if st == 0:                       # 长字面量段
                for L in range(4, min(W - p, 290) + 1):
                    nc = cost + lit_cost(L) + L
                    if nc > budget:
                        break
                    k = (p + L, nc, 1)
                    if k not in dp:
                        dp[k] = (p, cost, st, ('L', L))
            for L in range(2, lim + 1):       # 匹配
                if p + L > W:
                    break
                s = nb[p][L]
                if s < 0:
                    continue
                b = (A + p) - s
                opts = []
                if L == 2:
                    if st == 2 and b <= 1024:
                        opts.append((2, 'm4'))
                elif L <= 8:
                    if b <= 2048:
                        opts.append((2, 'm2'))
                    if b <= 16384:
                        opts.append((3, 'm3'))
                elif L <= 33:
                    if b <= 16384:
                        opts.append((3, 'm3'))
                if L == 3 and st == 1 and 2048 <= b <= 3071:
                    opts.append((2, 'm4l'))
                for (mc, form) in opts:
                    for post in (0, 1, 2, 3):
                        if p + L + post > W:
                            break
                        nc = cost + mc + post
                        if nc > budget:
                            continue
                        k = (p + L + post, nc, 0 if post == 0 else 2)
                        if k not in dp:
                            dp[k] = (p, cost, st, ('M', form, L, b, post))
    goals = [(c, s) for (p, c, s) in dp if p == W and s == end_state]
    if not goals:
        if dbg:
            mx = max(p for (p, c, s) in dp)
            print('     DP no goal: states=%d maxp=%d/%d' % (len(dp), mx, W))
        return None, None
    cost = min(goals)[0]
    key = min(k for k in dp if k[0] == W and k[1] == cost and k[2] == end_state)
    chunks, path = [], []
    while key is not None:
        prev = dp[key]
        if prev is None:
            break
        pp, pc, ps, dec = prev
        path.append((key, dec))
        if dec[0] == 'L':
            L = dec[1]
            chunks.append(enc_lit_run(L, target[A + pp:A + pp + L]))
        else:
            _, form, L, b, post = dec
            data = target[A + pp + L:A + pp + L + post]
            if form == 'm2':
                chunks.append(enc_m2(b, L, post, data))
            elif form == 'm3':
                chunks.append(enc_m3(b, L, post, data))
            elif form == 'm4':
                chunks.append(enc_m4(b, post, data))
            elif form == 'm4l':
                chunks.append(enc_m4l(b, post, data))
            else:
                raise SystemExit('form?')
        key = (pp, pc, ps)
    if dbg:
        for (kk, dd) in reversed(path):
            print('     p=%d cost=%d st=%d %s' % (kk[0], kk[1], kk[2], dd))
    out = b''.join(reversed(chunks))
    assert len(out) <= budget, (len(out), budget)
    return out, cost


# ───────────────────────── 条目级规划 ─────────────────────────
def _ov(a, ln, rng):
    return rng is not None and a < rng[1] and a + ln > rng[0]


def _state_after(it):
    if it.kind == 'L':
        return 1
    return 0 if it.post == 0 else 2


def plan_entry(pay0, S, target, changed, verbose=False, dbg=False, slack=0):
    """返回 (new_pay, stats) ; 失败 (None, stats)。new_pay 与 pay0 等长。"""
    out, items = trace_items(pay0, S)
    assert len(out) == S and len(target) == S
    n = len(items)
    stats = dict(problems=0, windows=[], deps=0, delta=0)

    prob = [False] * n
    for i, it in enumerate(items):
        if it.kind == 'L':
            if _ov(it.out, it.out_len, changed):
                prob[i] = True
        elif it.kind == 'M':
            if _ov(it.out, it.mlen, changed):
                prob[i] = True
            if _ov(it.out - it.back, it.mlen, changed):
                prob[i] = True
                stats['deps'] += 1
    stats['problems'] = sum(prob)
    if not any(prob):
        pay = bytearray(pay0)
        a, b = changed
        for it in items:
            if it.kind != 'L' or not _ov(it.out, it.out_len, (a, b)):
                continue
            base = it.pay + it.pay_len - it.out_len
            s0, s1 = max(a, it.out), min(b, it.out + it.out_len)
            pay[base + (s0 - it.out):base + (s1 - it.out)] = target[s0:s1]
        return bytes(pay), stats

    # 相邻问题项目合成组
    groups, i = [], 0
    while i < n:
        if prob[i] and items[i].kind != 'T':
            j = i
            while j + 1 < n and prob[j + 1] and items[j + 1].kind != 'T':
                j += 1
            groups.append([i, j])
            i = j + 1
        else:
            i += 1
    if not groups:
        return None, stats

    # 每组: 终点延到"其后第一个 post=0 的匹配"
    plan = []
    for (i0, i1) in groups:
        while i1 + 1 < n and items[i1].kind != 'T' and \
                not (items[i1].kind == 'M' and items[i1].post == 0):
            i1 += 1
        if i1 >= n:
            i1 = n - 1
        if items[i1].kind == 'T':
            i1 -= 1
        plan.append([i0, i1])

    # 编码: 可分次把后面的组并进来; 全局记账 (前面省下的字节可以给后面用)
    enc = {}
    credit = 0
    k = 0
    while k < len(plan):
        i0, i1 = plan[k][0], plan[k][1]
        left_lim = (plan[k - 1][1] + 1) if k > 0 else 1
        merged = 0
        ok = False
        while not ok:
            right_lim = (plan[k + 1 + merged][0] - 1) if (k + 1 + merged) < len(plan) else (n - 1)
            ends, j = [], i1
            while j < n and j <= right_lim and len(ends) < 8:
                it = items[j]
                nxt_m = (j + 1 < n and items[j + 1].kind == 'M')
                if it.kind == 'M' and (it.post == 0 or nxt_m):
                    ends.append(j)
                j += 1
            if not ends:
                ends = [min(i1, right_lim)]
            cands = []
            for left in range(0, 9):
                i0x = i0 - left
                if i0x < left_lim:
                    break
                for j1 in ends:
                    if j1 < i0x:
                        continue
                    cands.append((items[j1].out + items[j1].out_len - items[i0x].out, i0x, j1))
            cands.sort()
            tried = 0
            for (W, i0x, j1) in cands:
                if W > 500 or tried > 60:
                    break
                tried += 1
                budget = sum(items[t].pay_len for t in range(i0x, j1 + 1))
                if budget > 500:
                    continue
                A = items[i0x].out
                st = _state_after(items[i0x - 1]) if i0x > 0 else 0
                en = _state_after(items[j1])
                got, cost = solve_window(target, A, W, budget + max(credit, 0) + slack, st, en)
                if got is None:
                    if dbg:
                        print('     try items %d..%d out 0x%X W=%d budget=%d st=%d en=%d -> no'
                              % (i0x, j1, A, W, budget, st, en))
                    continue
                enc[k] = (got, i0x, j1)
                plan[k] = [i0x, j1]
                credit += budget - cost
                if verbose:
                    print('     win items %d..%d out 0x%X..0x%X W=%d budget=%d -> %d (credit=%+d)'
                          % (i0x, j1, A, A + W, W, budget, cost, credit))
                ok = True
                break
            if ok:
                break
            merged += 1
            if k + merged >= len(plan):
                return None, stats
        # 被并进来的组: 跳过
        k += 1 + merged
    stats['credit'] = credit

    # 重建
    inwin = {}
    for kk, (i0, i1) in enumerate(plan):
        if kk in enc:
            for t in range(i0, i1 + 1):
                inwin[t] = kk
    pieces = []
    i = 0
    while i < n:
        if i in inwin:
            kk = inwin[i]
            pieces.append((i, enc[kk][0]))
            i = plan[kk][1] + 1
        else:
            it = items[i]
            pieces.append((i, pay0[it.pay:it.pay + it.pay_len]))
            i += 1
    total = sum(len(x[1]) for x in pieces)
    orig = len(pay0)
    stats['delta'] = total - orig
    if total > orig:
        if total - orig <= slack:
            stats['grow'] = total - orig
            newpay = b''.join(x[1] for x in pieces)
            got, err, _ = mislib.lzo1x_decompress(newpay, out_size=S)
            if err is not None or got != target:
                stats['verify_fail'] = (err, got == target)
                return None, stats
            stats['windows'] = [(p[0], p[1], len(enc[kk][0])) for kk, p in enumerate(plan) if kk in enc]
            return newpay, stats
        return None, stats

    # 补齐: M2 -> M3 (同 back 同长度, 令牌 +1 B), 只动窗口之外的匹配
    pad_need = orig - total
    stats['pad_need'] = pad_need
    if pad_need:
        used = 0
        for idx in range(len(pieces)):
            if pad_need <= 0:
                break
            t, chunk = pieces[idx]
            it = items[t]
            if t in inwin or it.kind != 'M' or it.form != 'M2':
                continue
            data = pay0[it.pay + 2:it.pay + it.pay_len]
            newchunk = enc_m3(it.back, it.mlen, it.post, data)
            assert len(newchunk) == len(chunk) + 1
            pieces[idx] = (t, newchunk)
            pad_need -= 1
            used += 1
        stats['padded'] = used
        if pad_need > 0:
            return None, stats

    newpay = b''.join(x[1] for x in pieces)
    assert len(newpay) == orig, (len(newpay), orig)
    got, err, _ = mislib.lzo1x_decompress(newpay, out_size=S)
    if err is not None or got != target:
        stats['verify_fail'] = (err, got == target)
        return None, stats
    stats['windows'] = [(p[0], p[1], len(enc[kk][0])) for kk, p in enumerate(plan)
                        if kk in enc]
    return newpay, stats
