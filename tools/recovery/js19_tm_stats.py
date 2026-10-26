# -*- coding: utf-8 -*-
r"""js19_tm_stats.py — JS19 译文作为 TM 的可用性分析。

产出：
  work/analysis/js19/js19_tm_stats.json      统计（唯一串/重复/用字/覆盖率/可疑条目）
  work/analysis/js19/js19_tm_unique.csv      去重后的 EN→ZH 记忆条目
  work/analysis/js19/js19_chars_needed.json  译文用字清单 + 是否在本体 charset 内
  work/analysis/js19/js19_tm_issues.csv      可疑条目（中英混排/长度异常/同英不同译）
"""
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
import dlclib as L            # noqa: E402

JS = os.path.join(REPO, 'work', 'analysis', 'js19')
P_DEC = os.path.join(JS, 'js19_lang_decoded.csv')
CHARSET = os.path.join(REPO, 'assets', 'charset', 'charset_compiled_zh16.json')
CJK = re.compile(r'[\u3400-\u9fff\uf900-\ufaff]')
RT = re.compile(r'\{[a-z0-9/]+\}')       # {p}/{br} 等富文本标记


def esc(s):
    return s.replace('\\', '\\\\').replace('\r', '\\r').replace('\n', '\\n')


def main():
    rows = list(csv.DictReader(open(P_DEC, encoding='utf-8-sig')))
    cs = json.load(open(CHARSET, encoding='utf-8'))
    base_pairs = set(cs['pair_of'].keys())
    base_singles = set(cs['codes'].keys())
    changed = [r for r in rows if r['changed'] == '1']
    zh = [r for r in changed if CJK.search(r['text_zh_js19'])]
    print('changed=%d zh=%d' % (len(changed), len(zh)))

    # ---- 去重：英文原文 → 中文 ----
    by_en = defaultdict(list)
    for r in zh:
        by_en[r['text_en']].append(r)
    uniq = {}
    conflicts = []
    for en, lst in by_en.items():
        zhs = set(x['text_zh_js19'] for x in lst)
        if len(zhs) == 1:
            uniq[en] = zhs.pop()
        else:
            # 同英文多译法：取出现最多的，其余记冲突
            c = Counter(x['text_zh_js19'] for x in lst)
            best, n = c.most_common(1)[0]
            uniq[en] = best
            conflicts.append(dict(en=en, variants=dict(c), n_ids=len(lst)))
    print('唯一英文串 %d (原文 %d 条), 同英不同译 %d 组'
          % (len(uniq), len(zh), len(conflicts)))
    # 重复次数
    rep = Counter(len(v) for v in by_en.values())
    print('重复次数分布(top):', sorted(rep.items())[:10])

    # ---- 用字 ----
    chars = Counter()
    for r in zh:
        chars.update(CJK.findall(r['text_zh_js19']))
    missing = [c for c in chars if c not in base_pairs and c not in base_singles]
    print('用字 %d 种; 不在本体 charset 的 %d 种: %s'
          % (len(chars), len(missing), ''.join(missing)))
    json.dump(dict(distinct_chars=len(chars),
                   chars=[dict(ch=c, count=n,
                               in_base_pair=c in base_pairs,
                               in_base_single=c in base_singles)
                          for c, n in chars.most_common()],
                   missing=[dict(ch=c, count=chars[c]) for c in missing]),
              open(os.path.join(JS, 'js19_chars_needed.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    # ---- 可疑条目 ----
    issues = []
    for r in zh:
        en, z = r['text_en'], r['text_zh_js19']
        en_core = RT.sub('', en)
        z_core = RT.sub('', z)
        ascii_alpha = sum(1 for c in z_core if c.isascii() and c.isalpha())
        zh_n = len(CJK.findall(z_core))
        reasons = []
        if zh_n and ascii_alpha > 0 and ascii_alpha / max(1, zh_n) > 1.0:
            reasons.append('英文残留较多')
        if len(z_core.strip()) == 0:
            reasons.append('译文为空')
        if len(en_core) > 60 and zh_n < 3:
            reasons.append('长原文极短译文')
        if zh_n and en_core and len(z_core) / len(en_core) > 1.6:
            reasons.append('译文字数异常膨胀')
        if reasons:
            issues.append(dict(g=r['g'], i=r['i'], en=en, zh=z, reasons=';'.join(reasons),
                               ascii_alpha=ascii_alpha, zh_n=zh_n, en_n=len(en_core)))
    print('可疑条目 %d 条' % len(issues))
    for x in issues[:25]:
        print('  %s.%s [%s] EN=%r ZH=%r' % (x['g'], x['i'], x['reasons'], x['en'][:60], x['zh'][:60]))

    # ---- 产出 ----
    with open(os.path.join(JS, 'js19_tm_unique.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['text_en', 'text_zh_js19', 'source_ids', 'confidence'])
        for en, z in sorted(uniq.items()):
            ids = by_en[en]
            ids_s = ' '.join('%s.%s' % (x['g'], x['i']) for x in ids[:6])
            w.writerow([esc(en), esc(z), ids_s, 'verified-decoded'])
    with open(os.path.join(JS, 'js19_tm_issues.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['g', 'i', 'reasons', 'text_en', 'text_zh_js19'])
        for x in issues:
            w.writerow([x['g'], x['i'], x['reasons'], esc(x['en']), esc(x['zh'])])
    with open(os.path.join(JS, 'js19_tm_conflicts.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['text_en', 'n_ids', 'variant', 'count'])
        for c in conflicts:
            for v, n in sorted(c['variants'].items(), key=lambda kv: -kv[1]):
                w.writerow([esc(c['en']), c['n_ids'], esc(v), n])

    # ---- 与本体成品 TM 资产对照（可复用性）----
    base_tm = {}
    for fn in ('GR_ZH141_text_long.csv', 'GR_ZH141_text_short.csv',
               'GR_ZH140_text_long.csv'):
        p = os.path.join(REPO, 'assets', 'text', fn)
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding='utf-8-sig', newline='') as f:
                for row in csv.DictReader(f):
                    e = (row.get('text_en') or '').strip()
                    z = (row.get('text_zh') or '').strip()
                    if e and z:
                        base_tm.setdefault(e.lower(), z)
        except Exception as exc:              # noqa: BLE001
            print('  (跳过 %s: %s)' % (fn, exc))
    exact = sum(1 for en in uniq if en in base_tm)
    lowex = sum(1 for en in uniq if en.lower().strip() in base_tm)
    print('本体 TM 资产: %d 条; JS19 唯一串命中(精确) %d / (忽略大小写) %d'
          % (len(base_tm), exact, lowex))

    stats = dict(
        decoded_entries=len(rows), changed=len(changed), zh_entries=len(zh),
        unchanged=len(rows) - len(changed),
        cjk_chars_total=sum(len(CJK.findall(r['text_zh_js19'])) for r in zh),
        distinct_en=len(uniq), duplicate_ids=len(zh) - len(uniq),
        same_en_diff_zh=len(conflicts),
        distinct_chars=len(chars), chars_missing_from_base=len(missing),
        issues=len(issues),
        base_tm_size=len(base_tm), base_tm_exact_hits=exact, base_tm_ci_hits=lowex,
        top_repeated=[dict(en=en, n=len(v)) for en, v in
                      sorted(by_en.items(), key=lambda kv: -len(kv[1]))[:20]],
    )
    json.dump(stats, open(os.path.join(JS, 'js19_tm_stats.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(json.dumps(stats, ensure_ascii=False, indent=1)[:2500])
    print('[out] js19_tm_stats.json / js19_tm_unique.csv / js19_chars_needed.json / js19_tm_issues.csv / js19_tm_conflicts.csv')


if __name__ == '__main__':
    main()
