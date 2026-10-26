# -*- coding: utf-8 -*-
r"""js19_decode_final.py — 输出 JS19 中文翻译还原：LANG 全量解码 CSV + 质量统计 + 抽样。

输入 work/analysis/js19/js19_charset.json（pair/single 映射，已 OCR 自证）
输出 work/analysis/js19/js19_lang_decoded.csv
     work/analysis/js19/js19_decode_stats.json
     work/analysis/js19/js19_quality_sample.csv
"""
import csv
import json
import os
import re
import sys
import unicodedata
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
import dlclib as L            # noqa: E402

JS = os.path.join(REPO, 'work', 'analysis', 'js19')
P_LANG = os.path.join(JS, 'payloads', '00576_EN_STRINGS.RES.bin')
P_EN = os.path.join(JS, 'en_lang.json')
P_CS = os.path.join(JS, 'js19_charset.json')

CJK = re.compile(r'[\u3400-\u9fff\uf900-\ufaff]')
PUNCT_ZH = set('，。！？：；、（）《》“”‘’…—·【】％＋－×÷／　')
CTRL = re.compile(r'[\x00-\x1f]')


def split_codes(data):
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


def load():
    raw = open(P_LANG, 'rb').read()
    blob = b''.join(s[0] for s in L.lzo_subs(raw))
    ents, used = L.parse_lang(blob)
    en = json.load(open(P_EN, encoding='utf-8'))
    cs = json.load(open(P_CS, encoding='utf-8'))
    return ents, {(x['g'], x['i']): x for x in en}, cs


def decode(data, cs):
    """返回 (text, unknowns, low_conf_count)。"""
    pm, sm = cs['pair'], cs['single']
    out, unk, low = [], 0, 0
    for kind, c in split_codes(data):
        if kind == 'pair':
            k = '%02X%02X' % c
            v = pm.get(k)
            if not v:
                out.append('\u25a1')
                unk += 1
                low += 1
            else:
                out.append(v['char'])
                if v.get('conf') not in ('high', 'override'):
                    low += 1
        else:
            k = '%02X' % c
            v = sm.get(k)
            if not v or not v.get('char'):
                out.append('{%02X}' % c)
                unk += 1
                low += 1
            else:
                out.append(v['char'])
    return ''.join(out), unk, low


def esc(s):
    """CSV 里字面转义 \\r \\n \\t。"""
    return s.replace('\\', '\\\\').replace('\r', '\\r').replace('\n', '\\n').replace('\t', '\\t')


def quality(text):
    n = len(text)
    cjk = len(CJK.findall(text))
    zh_punct = sum(1 for c in text if c in PUNCT_ZH)
    ascii_alpha = sum(1 for c in text if c.isascii() and c.isalpha())
    unk = text.count('\u25a1') + len(re.findall(r'\{[0-9A-F]{2}\}', text))
    return dict(n=n, cjk=cjk, cjk_ratio=(cjk / n if n else 0.0),
                zh_punct=zh_punct, ascii_alpha=ascii_alpha, unknown=unk,
                fully_zh=(cjk > 0 and ascii_alpha == 0))


def en_letters(s):
    return sum(1 for c in s if c.isascii() and c.isalpha())


def main():
    ents, en, cs = load()
    rows = []
    stat = dict(total=len(ents), changed=0, unchanged=0, changed_zh=0, changed_nonzh=0,
                unknown_chars=0, low_conf=0, cjk_chars=0, zh_entries_with_ascii=0)
    conf_of = {}
    for e in ents:
        ref = en[(e.g, e.i)]
        changed = ref['raw'] != e.data.hex()
        text, unk, low = decode(e.data, cs)
        q = quality(text)
        stat['unknown_chars'] += unk
        stat['low_conf'] += low
        stat['cjk_chars'] += q['cjk']
        if changed:
            stat['changed'] += 1
            if q['cjk'] > 0:
                stat['changed_zh'] += 1
            else:
                stat['changed_nonzh'] += 1
            if q['ascii_alpha'] > 0:
                stat['zh_entries_with_ascii'] += 1
        else:
            stat['unchanged'] += 1
        conf = 'verified' if not changed else (
            'high' if (unk == 0 and low == 0) else
            'medium' if unk == 0 else 'low')
        rows.append(dict(g=e.g, i=e.i, en=ref['text'], zh=text, changed=int(changed),
                         conf=conf, unk=unk, low=low, n_en=len(ref['text']), n_zh=q['n'],
                         cjk=q['cjk'], cjk_ratio=q['cjk_ratio'],
                         ascii_alpha=q['ascii_alpha'], zh_punct=q['zh_punct'],
                         accent_remap=(not changed and q['cjk'] > 0)))

    # ── CSV 主产物 ──
    path = os.path.join(JS, 'js19_lang_decoded.csv')
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['g', 'i', 'text_en', 'text_zh_js19', 'confidence', 'note',
                    'changed', 'len_en', 'len_zh', 'cjk_ratio'])
        for r in rows:
            note = ''
            if not r['changed']:
                note = ('未翻译(英文原样)；★显示层重音字节被 JS19 改画为汉字，勿复用于注入'
                        if r['accent_remap'] else '未翻译(英文原样)')
            elif r['unk']:
                note = '含 %d 个未解析码' % r['unk']
            elif r['low']:
                note = '含 %d 个低置信码' % r['low']
            elif r['ascii_alpha'] > 0:
                note = '中英混排'
            w.writerow([r['g'], r['i'], esc(r['en']), esc(r['zh']), r['conf'], note,
                        r['changed'], r['n_en'], r['n_zh'],
                        '%.3f' % r['cjk_ratio']])
    print('[out] %s' % path)

    # ── 统计 ──
    changed = [r for r in rows if r['changed']]
    zh = [r for r in changed if r['cjk'] > 0]
    mix = [r for r in changed if r['cjk'] > 0 and r['ascii_alpha'] > 0]
    stat.update(
        changed_cjk_ratio_avg=sum(r['cjk_ratio'] for r in changed) / max(1, len(changed)),
        len_ratio_avg=(sum(r['n_zh'] for r in changed) / max(1, sum(r['n_en'] for r in changed))),
        mixed_zh_en=len(mix),
        unknown_entries=sum(1 for r in changed if r['unk']),
    )
    print(json.dumps(stat, ensure_ascii=False, indent=1))
    json.dump(stat, open(os.path.join(JS, 'js19_decode_stats.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    # ── 抽样：长度分层 50 条（short/medium/long）──
    import random
    random.seed(200119)
    pool = [r for r in changed if r['n_zh'] > 0]
    buckets = [('short', [r for r in pool if r['n_zh'] <= 30]),
               ('medium', [r for r in pool if 30 < r['n_zh'] <= 120]),
               ('long', [r for r in pool if r['n_zh'] > 120])]
    sample = []
    for name, b in buckets:
        random.shuffle(b)
        sample.extend(b[:20])
    sp = os.path.join(JS, 'js19_quality_sample.csv')
    with open(sp, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['bucket', 'g', 'i', 'len_en', 'len_zh', 'text_en', 'text_zh_js19',
                    'verdict', 'comment'])
        for r in sample:
            b = 'short' if r['n_zh'] <= 30 else ('medium' if r['n_zh'] <= 120 else 'long')
            w.writerow([b, r['g'], r['i'], r['n_en'], r['n_zh'], esc(r['en']), esc(r['zh']), '', ''])
    print('[out] %s (%d 条)' % (sp, len(sample)))

    # ── 高频字 / 未翻译条目检查 ──
    chars = Counter()
    for r in zh:
        chars.update(CJK.findall(r['zh']))
    print('译文用字 %d 种, top30: %s' % (len(chars), ''.join(c for c, _n in chars.most_common(30))))
    # changed 但仍全英文的条目
    nontrans = [r for r in changed if r['cjk'] == 0]
    print('\n"changed 但无汉字" 条目 %d 条 (修改了标点/空格等):' % len(nontrans))
    for r in nontrans[:10]:
        print('  %d.%d EN=%r ZH=%r' % (r['g'], r['i'], r['en'][:50], r['zh'][:50]))
    # 未翻译但含高字节的条目
    print('\n未翻译条目数:', stat['unchanged'])
    # 译文里最长 10 条
    print('\n最长 10 条译文:')
    for r in sorted(zh, key=lambda x: -x['n_zh'])[:10]:
        print('  %d.%d (%d字) %s' % (r['g'], r['i'], r['n_zh'], r['zh'][:60]))


if __name__ == '__main__':
    main()
