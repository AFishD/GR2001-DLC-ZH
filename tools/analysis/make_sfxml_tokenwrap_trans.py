# -*- coding: utf-8 -*-
"""make_v33_trans.py —— 在 v31 基础上：
1) 武器属性右面板再缩一个全宽字：SFXML 武器说明 T0016-T0060 与 LANG G058.I047 由 15 → 14 字/行；
2) 名册底部 Circle 提示 G058.I229 = 「队员信息」（4 字，验证是否可静止平铺）。
"""
import csv
import io
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
import wrap_sfxml  # noqa: E402

SRC = os.path.join(REPO, 'work', 'translation', 'merged', 'translations_v31.csv')
DST = os.path.join(REPO, 'work', 'translation', 'merged', 'translations_v33.csv')
UNITS = 14.0
WEAPON_IDS = wrap_sfxml.parse_ids('T0016-T0060')


def rewrap_para(text):
    parts = []
    for para in text.split('{p}'):
        if '{br}' in para:
            head, rest = para.split('{br}', 1)
            if wrap_sfxml.units(head) <= 8:
                parts.append(head + '{br}' + wrap_sfxml.rewrap(rest, UNITS))
                continue
        parts.append(wrap_sfxml.rewrap(para, UNITS))
    return '{p}'.join(parts)


def main():
    rows = list(csv.reader(io.open(SRC, encoding='utf-8-sig', newline='')))
    h = rows[0]
    i_res, i_id, i_zh = h.index('resource'), h.index('id'), h.index('text_zh')
    n = 0
    for r in rows[1:]:
        if len(r) <= i_zh:
            continue
        if r[i_res] == 'SFXML' and r[i_id] in WEAPON_IDS:
            new = wrap_sfxml.rewrap(r[i_zh], UNITS)
        elif r[i_res] == 'LANG' and r[i_id] == 'G058.I047':
            new = rewrap_para(r[i_zh])
        elif r[i_res] == 'LANG' and r[i_id] == 'G058.I229':
            new = '队员信息'
        else:
            continue
        if new != r[i_zh]:
            r[i_zh] = new
            n += 1
    with io.open(DST, 'w', encoding='utf-8-sig', newline='') as f:
        csv.writer(f, lineterminator='\r\n').writerows(rows)
    print('v33 changes:', n, '->', DST)


if __name__ == '__main__':
    main()
