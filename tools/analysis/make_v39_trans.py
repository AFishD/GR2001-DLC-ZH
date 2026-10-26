# -*- coding: utf-8 -*-
"""make_v39_trans.py —— HUD 提示/消息文本“29 字对齐”：在每 29 个全宽字（ASCII 0.5）之后插入一个
半角空格，让引擎按自身 ~30 字宽度折行时在空格处断开，从而每行恰好 29 个汉字（行尾空格不可见）。

仅处理游戏内提示/消息类 LANG 文本（非 G058、且不含 {br}，已有简报手工折行的不动）。
"""
import csv
import io
import os
import re
import sys

REPO = os.path.abspath('.')
SRC = os.path.join(REPO, 'work', 'translation', 'merged', 'translations_v35.csv')
DST = os.path.join(REPO, 'work', 'translation', 'merged', 'translations_v39.csv')
LIMIT = 29.0
BTN_RE = re.compile(r'\{\{BTN:[0-9A-Fa-f]{4}\}\}')
ASCII_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9.,%+/\'\-]*')


def tokens(par):
    out = []
    i = 0
    while i < len(par):
        m = BTN_RE.match(par, i)
        if m:
            out.append((m.group(0), 1.0, 'btn'))
            i = m.end()
            continue
        ch = par[i]
        if ASCII_RE.match(ch):
            m = ASCII_RE.match(par, i)
            s = m.group(0)
            out.append((s, 0.5 * len(s), 'ascii'))
            i = m.end()
            continue
        if ch == ' ':
            out.append((' ', 0.5, 'space'))
            i += 1
            continue
        out.append((ch, 1.0, 'cjk'))
        i += 1
    return out


def pad29(par):
    toks = tokens(par)
    out = []
    used = 0.0
    for tok, w, kind in toks:
        if used + w > LIMIT and used > 0:
            out.append(' ')
            used = 0.0
            if kind == 'space':
                continue
        out.append(tok)
        used += w
    return ''.join(out)


groups_ok = None


def main():
    rows = list(csv.reader(io.open(SRC, encoding='utf-8-sig')))
    h = rows[0]
    ir, ii, iz = h.index('resource'), h.index('id'), h.index('text_zh')
    n = 0
    for r in rows[1:]:
        if len(r) <= iz or r[ir] != 'LANG':
            continue
        g = r[ii].split('.')[0]
        if g == 'G058':          # UI 面板，宽度各异，不动
            continue
        if '{br}' in r[iz]:      # 已有手工折行（简报面板），不动
            continue
        parts = [pad29(p) for p in r[iz].split('{p}')]
        new = '{p}'.join(parts)
        if new != r[iz]:
            r[iz] = new
            n += 1
    with io.open(DST, 'w', encoding='utf-8-sig', newline='') as f:
        csv.writer(f, lineterminator='\r\n').writerows(rows)
    print('v39 29-char-padded entries:', n, '->', DST)


if __name__ == '__main__':
    main()
