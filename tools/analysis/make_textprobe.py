# -*- coding: utf-8 -*-
"""make_textprobe.py —— 生成一张「兵种名测试盘」：把 I902-I905 设成受控字节串，
用来判定：前导空格是否触发字符变换、变换是“整体”还是逐字节。
  I902 = " 队队"   (空格 + 两个单字节码 C1)
  I903 = "队队"     (无空格)
  I904 = " 破破"   (空格 + 两个对偶码 A3C8)
  I905 = "破破"
"""
import csv
import io
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, 'work', 'translation', 'merged', 'translations_v25.csv')
DST = os.path.join(REPO, 'work', 'translation', 'merged', 'translations_probe_space.csv')

MAP = {
    'G058.I902': ' 队队',
    'G058.I903': '队队',
    'G058.I904': ' 破破',
    'G058.I905': '破破',
}


def main():
    rows = list(csv.reader(io.open(SRC, encoding='utf-8-sig', newline='')))
    h = rows[0]
    i_res, i_id, i_zh = h.index('resource'), h.index('id'), h.index('text_zh')
    n = 0
    for r in rows[1:]:
        if len(r) <= i_zh:
            continue
        if r[i_res] == 'LANG' and r[i_id] in MAP:
            r[i_zh] = MAP[r[i_id]]
            n += 1
    with io.open(DST, 'w', encoding='utf-8-sig', newline='') as f:
        csv.writer(f, lineterminator='\r\n').writerows(rows)
    print('textprobe rows', n, '->', DST)


if __name__ == '__main__':
    main()
