# -*- coding: utf-8 -*-
r"""js19_tm_overlap.py — JS19 译文 vs 本工程既有译文资产（assets/text/）的重叠/一致性。

说明：assets/text/ 下是**本体（Ghost Recon 2001）汉化工程**的译文资产（只读参考）。
JS19 是**资料片 Jungle Storm** 的上一版构筑，串内容不同，但训练/多人/UI 用语有大量同源，
所以做一次对照：能精确命中的，比对其中文是否一致（衡量 JS19 译文风格是否与本工程一致）。
"""
import csv
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
JS = os.path.join(REPO, 'work', 'analysis', 'js19')


def load_js19():
    out = {}
    with open(os.path.join(JS, 'js19_tm_unique.csv'), encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            out[row['text_en']] = row['text_zh_js19']
    return out


def load_base():
    """扫 assets/text 下所有含 text_en / text_zh 列的 CSV。"""
    tm = {}
    nfiles = 0
    for root, _dirs, files in os.walk(os.path.join(REPO, 'assets', 'text')):
        for fn in files:
            if not fn.endswith('.csv'):
                continue
            p = os.path.join(root, fn)
            try:
                with open(p, encoding='utf-8-sig', newline='') as f:
                    rd = csv.DictReader(f)
                    cols = rd.fieldnames or []
                    if 'text_en' not in cols or 'text_zh' not in cols:
                        continue
                    nfiles += 1
                    for row in rd:
                        en = (row.get('text_en') or '').strip()
                        zh = (row.get('text_zh') or '').strip()
                        if en and zh:
                            tm.setdefault(en, zh)
            except Exception as exc:            # noqa: BLE001
                print('  skip %s: %s' % (fn, exc))
    return tm, nfiles


def norm(s):
    return ' '.join(s.split()).strip().lower()


def main():
    js = load_js19()
    base, nfiles = load_base()
    print('JS19 唯一串 %d ; 本体译文资产 %d 条 (来自 %d 个 CSV)' % (len(js), len(base), nfiles))
    base_norm = {norm(en): zh for en, zh in base.items()}
    exact = same = diff = 0
    diffs = []
    for en, zh in js.items():
        bz = base.get(en)
        hit = 'exact'
        if bz is None:
            bz = base_norm.get(norm(en))
            hit = 'ci'
        if bz is None:
            continue
        if hit == 'exact':
            exact += 1
        if bz.replace(' ', '') == zh.replace(' ', ''):
            same += 1
        else:
            diff += 1
            if len(diffs) < 40:
                diffs.append((en[:70], zh, bz))
    print('命中本体资产: 精确 %d 条 (+忽略大小写/空白归一 %d 条)' % (exact, exact and 0))
    print('命中里中文一致 %d ; 不一致 %d' % (same, diff))
    print('\n不一致样例（JS19 用词 vs 本工程用词）:')
    for en, a, b in diffs[:25]:
        print('  EN: %s\n    JS19: %s\n    本体: %s' % (en, a[:70], b[:70]))
    json.dump(dict(js19_unique=len(js), base_entries=len(base), base_files=nfiles,
                   exact_hits=exact, same_zh=same, diff_zh=diff),
              open(os.path.join(JS, 'js19_tm_overlap.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('[out] js19_tm_overlap.json')


if __name__ == '__main__':
    main()
