# -*- coding: utf-8 -*-
r"""char_coverage.py —— 统计「当前全部译文」需要的字符集覆盖 & 缺字清单。

输入：work/translation/merged/translations_all.csv（merge_translations.py 产出）
      assets/charset/charset_compiled_zh16.json（当前字符集）
输出：work/translation/merged/char_coverage.json
      work/translation/merged/missing_chars.json  ← 交给字库补画流程

同时校验：每条译文可被字符集编码（缺字逐字列出）、无 0xFF、无控制字符。
"""
import collections
import csv
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))
import tcslib as T                                             # noqa: E402

MERGED = os.path.join(REPO, 'work', 'translation', 'merged', 'translations_all.csv')
CHARSET = os.path.join(REPO, 'assets', 'charset', 'charset_compiled_zh16.json')
OUT = os.path.join(REPO, 'work', 'translation', 'merged')


def main():
    cs = T.Charset(CHARSET)
    rows = list(csv.DictReader(io.open(MERGED, encoding='utf-8-sig')))
    hist = collections.Counter()
    missing = collections.Counter()
    missing_examples = collections.defaultdict(list)
    bad = []
    ctrl = []
    total_bytes = 0
    for r in rows:
        zh = r['text_zh']
        for ch in zh:
            if ch in ('\r', '\n', '\t'):
                continue
            if ch == '\uffff':
                ctrl.append((r['resource'], r['id'], '0xFFFF'))
                continue
            o = ord(ch)
            if o < 0x20:
                ctrl.append((r['resource'], r['id'], 'U+%04X' % o))
                continue
            if o < 0x80:
                continue
            hist[ch] += 1
            if ch not in cs.enc_single and ch not in cs.enc_pair:
                missing[ch] += 1
                if len(missing_examples[ch]) < 6:
                    missing_examples[ch].append('%s:%s' % (r['resource'], r['id']))
        try:
            b = cs.encode_strict(zh)
            total_bytes += len(b)
        except Exception as ex:                                # noqa: BLE001
            if 'charset 无此字' not in str(ex):
                bad.append(dict(resource=r['resource'], id=r['id'], error=str(ex)[:160]))
    # 已用字符集统计
    used_pairs = sum(1 for ch in hist if ch in cs.enc_pair)
    used_single = sum(1 for ch in hist if ch in cs.enc_single)
    ink_slots = 0
    for ch in hist:
        if ch in cs.enc_pair:
            b1, b2 = cs.enc_pair[ch]
            slot = (b1 - 0xA1) * 94 + (b2 - 0xA1)
            if slot < 2350:
                ink_slots += 1
    cap = 2350
    free = cap - len(cs.enc_pair)
    rep = dict(
        entries=len(rows),
        unique_cjk=len(hist),
        used_pairs=used_pairs,
        used_single=used_single,
        charset_pairs=len(cs.enc_pair),
        charset_singles=len(cs.enc_single),
        used_slots=ink_slots,
        capacity=cap,
        free_slots=cap - len(cs.enc_pair),
        missing_chars=len(missing),
        missing_total_occurrences=sum(missing.values()),
        missing=sorted(([ch, n] + missing_examples[ch])
                       for ch, n in missing.items()),
        encode_errors=bad[:50],
        control_chars=ctrl[:20],
        total_bytes=total_bytes,
    )
    os.makedirs(OUT, exist_ok=True)
    json.dump(rep, io.open(os.path.join(OUT, 'char_coverage.json'), 'w',
                           encoding='utf-8', newline='\n'),
              ensure_ascii=False, indent=1)
    json.dump(dict(chars=[ch for ch, _ in missing.most_common()],
                   detail=rep['missing']),
              io.open(os.path.join(OUT, 'missing_chars.json'), 'w',
                      encoding='utf-8', newline='\n'),
              ensure_ascii=False, indent=1)
    print('译文条目 %d / 唯一非 ASCII 字符 %d（对偶 %d + 单字节 %d）'
          % (len(rows), len(hist), used_pairs, used_single))
    print('字符集：%d 对偶 + %d 单字节；已用槽 %d / 2350；空槽 %d'
          % (len(cs.enc_pair), len(cs.enc_single), ink_slots, free))
    print('缺字 %d 个 / 出现 %d 次：%s'
          % (len(missing), sum(missing.values()),
             ''.join(ch for ch, _ in missing.most_common(60))))
    print('控制字符 %d 条；编码异常 %d 条' % (len(ctrl), len(bad)))
    return 0 if not ctrl and not bad else 1


if __name__ == '__main__':
    sys.exit(main())
