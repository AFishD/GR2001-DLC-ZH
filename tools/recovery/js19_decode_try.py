# -*- coding: utf-8 -*-
r"""js19_decode_try.py — 用「本体字符集 pair→char」假设解码 JS19 LANG，看是否通顺。

编码规则（已由 elf-analyst 反汇编确认，VA 0x1808C8 decoder）：
  · byte < 0xA1              → 单字节码（走 FONT.RES FT 记录，index=code-base）
  · 0xA1 <= byte < 0xAE      → 若下一字节 ∈ [0xA1,0xFF) 则双字节 pair，否则单字节
  · byte >= 0xAE             → 单字节码
  · pair slot = (lead-0xA1)*94 + (trail-0xA1)；UV: row=slot//62, col=slot%62,
    x=2+8*col, y=2+16*(row+3*[row>=12]), cell 8x16
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'font'))
import dlclib as L            # noqa: E402
import fontlib as F           # noqa: E402

JS = os.path.join(REPO, 'work', 'analysis', 'js19')
P_LANG = os.path.join(JS, 'payloads', '00576_EN_STRINGS.RES.bin')
CHARSET = os.path.join(REPO, 'assets', 'charset', 'charset_compiled_zh16.json')


def lang_entries():
    raw = open(P_LANG, 'rb').read()
    blob = b''.join(s[0] for s in L.lzo_subs(raw))
    ents, used = L.parse_lang(blob)
    return ents


def split_codes(data):
    """按 cave 规则切码：返回 [(kind, code_bytes)]，kind in {'pair','single'}。"""
    out = []
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        if 0xA1 <= b < 0xAE and i + 1 < n and 0xA1 <= data[i + 1] < 0xFF:
            out.append(('pair', (b, data[i + 1])))
            i += 2
        else:
            out.append(('single', b))
            i += 1
    return out


def load_charset():
    js = json.load(open(CHARSET, encoding='utf-8'))
    pair2ch = {}
    for ch, pr in js['pair_of'].items():
        pair2ch[(pr[0], pr[1])] = ch
    single2ch = {int(v): ch for ch, v in js['codes'].items()}
    return pair2ch, single2ch, js


def main():
    ents = lang_entries()
    pair2ch, single2ch, js = load_charset()
    print('charset pairs=%d singles=%d' % (len(pair2ch), len(single2ch)))
    n_pair = n_single = 0
    pair_hit = 0
    sing_hi = collections.Counter()
    sing_lo = collections.Counter()
    texts = []
    for e in ents:
        if not any(b >= 0x80 for b in e.data):
            texts.append((e, '', 'ascii'))
            continue
        codes = split_codes(e.data)
        s = []
        for kind, c in codes:
            if kind == 'pair':
                n_pair += 1
                ch = pair2ch.get(c)
                if ch:
                    pair_hit += 1
                    s.append(ch)
                else:
                    s.append('\u25a1')
            else:
                n_single += 1
                if c >= 0xAE:
                    sing_hi[c] += 1
                else:
                    sing_lo[c] += 1
                ch = single2ch.get(c)
                s.append(ch if ch else '?')
        texts.append((e, ''.join(s), 'zh'))
    print('pair=%d (charset命中 %d = %.1f%%)  single=%d' % (n_pair, pair_hit, 100.0 * pair_hit / max(1, n_pair), n_single))
    print('单字节高码(>=0xAE) 分布:', sing_hi.most_common(30))
    print('单字节低码(<0xA1) 分布:', sing_lo.most_common(15))
    print('\n=== 样例 ===')
    for e, s, kind in texts[:6]:
        print('%d.%d %r' % (e.g, e.i, s))
    zh = [(e, s) for e, s, k in texts if k == 'zh']
    print('\n=== 中文条目里连续可读的 12 条 ===')
    shown = 0
    for e, s in zh:
        if len(s) >= 8 and shown < 12:
            print('%d.%d %r' % (e.g, e.i, s))
            shown += 1


if __name__ == '__main__':
    main()
