# -*- coding: utf-8 -*-
"""把指定文本按「全宽字单元」硬折行（用于任务简报等窄栏文本）。

用法：
    python tools\\dlc\\wrap_text.py --in <输入译文表.csv> --out <输出.csv> --units 15
        [--only-briefing]     # 只处理“简报组”（同组里有 1./2./X - 目标项的 LANG 长文本）

规则：
· 全宽字（CJK/全角标点/图标标记 {{BTN:...}}）计 1 单元；ASCII 计 0.5 单元；
· 优先在空格/标点后断行；不拆英文单词；已有 {br} 保留；{p} 分段保留（段内重排）。
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
OBJ_RE = re.compile(r'^(\d+\.|X\s*-)\s')
GOOD_BREAK = set('，。；：！？、）】》”’ ')


def units(text):
    """估算文本宽度（全宽字=1）。"""
    n = 0.0
    i = 0
    while i < len(text):
        m = BTN_RE.match(text, i)
        if m:
            n += 1.0
            i = m.end()
            continue
        ch = text[i]
        n += 1.0 if ord(ch) > 0xFF else 0.5
        i += 1
    return n


def wrap_para(text, limit):
    """一段（无 {p}）文本 → 按 limit 单元硬折行（插入 {br}）。

    · 贪心装满；装不下时优先把收尾标点留在本行（避免「。」「，」出现在行首）；
    · 不拆英文单词：切点落单词中间时回退到最近空格；
    """
    CLOSERS = '。，、；：！？）》”’'
    out = []
    line = ''
    used = 0.0
    i = 0
    n = len(text)
    while i < n:
        m = BTN_RE.match(text, i)
        if m is not None:
            line += m.group(0)
            used += 1.0
            i = m.end()
            continue
        ch = text[i]
        w = 1.0 if ord(ch) > 0xFF else 0.5
        if used + w <= limit or not line:
            line += ch
            used += w
            i += 1
            continue

        # 装不下：先把后续的收尾标点并进本行（最多 2 个）
        j = i
        extra = 0
        while j < n and extra < 2:
            mm = BTN_RE.match(text, j)
            if mm is not None:
                break
            if text[j] in CLOSERS:
                line += text[j]
                j += 1
                extra += 1
            else:
                break
        if extra:
            i = j
            out.append(line.rstrip())
            line = ''
            used = 0.0
            continue

        # 英文单词不拆：切点落在字母/数字时，回退到最近空格
        cut = len(line)
        if ch.isascii() and ch.isalnum():
            k = len(line) - 1
            back = 0
            while k >= 0 and back < 12:
                if line[k] == ' ':
                    cut = k + 1
                    break
                if line[k].isascii() and line[k].isalnum():
                    k -= 1
                    back += 1
                    continue
                break
            if cut == len(line):
                cut = len(line)
        head, tail = line[:cut].rstrip(), line[cut:].lstrip()
        out.append(head)
        line = tail + ch
        used = units(line)
        i += 1
    if line.strip():
        out.append(line.rstrip())
    return '{br}'.join(x for x in out if x)


def wrap_full(text, limit):
    """{p} 分段处理。"""
    paras = text.split('{p}')
    return '{p}'.join(wrap_para(p, limit) for p in paras)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='src', required=True)
    ap.add_argument('--out', dest='dst', required=True)
    ap.add_argument('--units', type=float, default=15.0)
    ap.add_argument('--only-briefing', action='store_true',
                    help='只处理简报组（同组含 1./2./X- 目标项的 LANG 长文本）')
    ap.add_argument('--min-len', type=int, default=120)
    a = ap.parse_args(argv)

    rows = list(csv.reader(io.open(a.src, encoding='utf-8-sig', newline='')))
    header = rows[0]
    try:
        i_res = header.index('resource')
        i_id = header.index('id')
        i_text = header.index('text_zh')
    except ValueError:
        print('输入表需要列：resource,id,text_zh')
        return 1

    # 找「简报组」：同组里出现 目标项（1./2./X -）的组
    briefing_groups = set()
    for r in rows[1:]:
        if len(r) <= max(i_res, i_id) or r[i_res] != 'LANG':
            continue
        key = r[i_id]
        if OBJ_RE.match((r[i_text] or '').strip()):
            m = re.match(r'(G\d+)\.', key)
            if m:
                briefing_groups.add(m.group(1))
    print('briefing groups:', sorted(briefing_groups))

    n_wrapped = 0
    for r in rows[1:]:
        if len(r) <= max(i_res, i_id, i_text):
            continue
        if r[i_res] != 'LANG':
            continue
        text = r[i_text] or ''
        if not text.strip():
            continue
        m = re.match(r'(G\d+)\.', r[i_id])
        grp = m.group(1) if m else ''
        if a.only_briefing and grp not in briefing_groups:
            continue
        if len(text) < a.min_len:
            continue
        if units(text.replace('{br}', '').replace('{p}', '')) <= a.units:
            continue
        new = wrap_full(text, a.units)
        if new != text:
            r[i_text] = new
            n_wrapped += 1
    with io.open(a.dst, 'w', encoding='utf-8-sig', newline='') as f:
        csv.writer(f, lineterminator='\r\n').writerows(rows)
    print('wrapped %d entries -> %s' % (n_wrapped, a.dst))
    return 0


if __name__ == '__main__':
    sys.exit(main())
