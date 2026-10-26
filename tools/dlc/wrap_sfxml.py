# -*- coding: utf-8 -*-
"""wrap_sfxml.py —— 把 SFXML 窄面板文本按“全宽字单元”硬折行（用于小队/武器信息栏）。

用法：
    python tools\\dlc\\wrap_sfxml.py --in <合并译文表.csv> --out <输出.csv> \
        --ids "T0016-T0060,T0088-T0091" --units 13 [--keep-p]

规则：
· 只处理 resource=SFXML 且 id 落在 --ids 范围内的条目；
· 去掉原有 {br}（保留 {p} 分段），按 units 重新硬折行写入 {br}；
· {{BTN:…}} 图标标记按 1 个全宽单元计，不拆行。
"""
import argparse
import csv
import io
import os
import re
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))

BTN_RE = re.compile(r'\{\{BTN:[0-9A-Fa-f]{4}\}\}')
CLOSERS = '。，、；：！？）》”’'


def units(text):
    n = 0.0
    i = 0
    while i < len(text):
        m = BTN_RE.match(text, i)
        if m:
            n += 1.0
            i = m.end()
            continue
        n += 1.0 if ord(text[i]) > 0xFF else 0.5
        i += 1
    return n


TOKEN_ASCII = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,%+/\\-\'')


def _tokens(text):
    """切成 token：{{BTN}}、ASCII 词/数字（含 . , % + - / '）、单个中日韩字符。"""
    out, i, n = [], 0, len(text)
    while i < n:
        m = BTN_RE.match(text, i)
        if m:
            out.append((m.group(0), 1.0))
            i = m.end()
            continue
        ch = text[i]
        if ch.isascii() and ch in TOKEN_ASCII:
            j = i
            while j < n and text[j].isascii() and text[j] in TOKEN_ASCII:
                j += 1
            tok = text[i:j]
            out.append((tok, 0.5 * len(tok)))
            i = j
            continue
        out.append((ch, 1.0 if ord(ch) > 0xFF else 0.5))
        i += 1
    return out


def wrap_para(text, limit):
    toks = _tokens(text)
    out, line, used = [], [], 0.0
    for tok, w in toks:
        if not line and tok.strip() == '':
            continue
        if used + w > limit and line:
            # 收尾标点不落行首：把上一 token 一起挪到下一行（保证每行 <= limit）
            if len(tok) == 1 and tok in CLOSERS and len(line) >= 2:
                last = line.pop()
                used -= units(last)
                out.append(''.join(line).rstrip())
                line, used = [last, tok], units(last) + w
                continue
            out.append(''.join(line).rstrip())
            line, used = [], 0.0
            if tok.strip() == '':
                continue
        line.append(tok)
        used += w
    if line:
        out.append(''.join(line).rstrip())
    return '{br}'.join(x for x in out if x)


def rewrap(text, limit):
    paras = text.split('{p}')
    out = []
    for para in paras:
        para = para.replace('{br}', '')
        out.append(wrap_para(para, limit))
    return '{p}'.join(out)


def parse_ids(spec):
    ids = set()
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r'([A-Za-z])(\d{4})-([A-Za-z])(\d{4})', part)
        if m and m.group(1) == m.group(3):
            pre = m.group(1)
            for n in range(int(m.group(2)), int(m.group(4)) + 1):
                ids.add('%s%04d' % (pre, n))
        else:
            ids.add(part)
    return ids


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='src', required=True)
    ap.add_argument('--out', dest='dst', required=True)
    ap.add_argument('--ids', required=True, help='如 T0016-T0060,T0088-T0091')
    ap.add_argument('--units', type=float, default=13.0)
    a = ap.parse_args(argv)
    ids = parse_ids(a.ids)
    rows = list(csv.reader(io.open(a.src, encoding='utf-8-sig', newline='')))
    header = rows[0]
    i_res = header.index('resource')
    i_id = header.index('id')
    i_zh = header.index('text_zh')
    n = 0
    for r in rows[1:]:
        if len(r) <= max(i_res, i_id, i_zh):
            continue
        if r[i_res] != 'SFXML' or r[i_id] not in ids:
            continue
        old = r[i_zh]
        new = rewrap(old, a.units)
        if new != old:
            r[i_zh] = new
            n += 1
    os.makedirs(os.path.dirname(os.path.abspath(a.dst)), exist_ok=True)
    with io.open(a.dst, 'w', encoding='utf-8-sig', newline='') as f:
        csv.writer(f, lineterminator='\r\n').writerows(rows)
    print('rewrapped %d entries (units=%.1f) -> %s' % (n, a.units, a.dst))


if __name__ == '__main__':
    main()
