# -*- coding: utf-8 -*-
r"""js19_chart_rel.py — JS19 图集字表 ↔ 本体 charset 的对应关系（他们怎么排的槽）。

对每个被 OCR 的 pair 格：delta = 本体 slot(该字) - JS19 slot。
若 delta 呈「0 段 + 常数偏移段」⇒ JS19 字表就是本体字表删/插了少量字后的顺序。
"""
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
JS = os.path.join(REPO, 'work', 'analysis', 'js19')
CHARSET = os.path.join(REPO, 'assets', 'charset', 'charset_compiled_zh16.json')


def main():
    ocr = json.load(open(os.path.join(JS, 'js19_atlas_ocr.json'), encoding='utf-8'))
    cs = json.load(open(CHARSET, encoding='utf-8'))
    base_slot = {}
    for ch, pr in cs['pair_of'].items():
        base_slot[ch] = (pr[0] - 0xA1) * 94 + (pr[1] - 0xA1)
    rows = []
    for c in ocr['cells']:
        s = c['slot']
        if s >= 1222 or not c.get('char'):
            continue
        ch = c['char']
        bs = base_slot.get(ch)
        rows.append((s, ch, bs, None if bs is None else bs - s, c['confidence']))
    delta = Counter(d for _s, _c, _b, d, _conf in rows if d is not None)
    print('pair 区有字格 %d；其中字在本体 pair 表里 %d；离本体表(单字节/新增) %d'
          % (len(rows), sum(1 for r in rows if r[2] is not None),
             sum(1 for r in rows if r[2] is None)))
    print('delta=本体slot-JS19slot 分布 top15:', delta.most_common(15))
    # 分段展示：delta 随 slot 变化
    print('\nslot / 字 / 本体slot / delta（抽样每 40 格，及 delta 变化点）:')
    last = object()
    for i, (s, ch, bs, d, conf) in enumerate(rows):
        if i % 40 == 0 or d != last:
            print('  slot %4d %r 本体 %s delta %s (%s)' % (s, ch, bs, d, conf))
            last = d
    # 本体表里没有的字（JS19 新增或本体用单字节码表示）
    miss = sorted(set(ch for _s, ch, bs, _d, _c in rows if bs is None))
    print('\n不在本体 pair 表的字 %d 个: %s' % (len(miss), ''.join(miss)))


if __name__ == '__main__':
    main()
