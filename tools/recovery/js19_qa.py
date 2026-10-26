# -*- coding: utf-8 -*-
r"""js19_qa.py — 最终交付物自检（CSV 可回读、字段完整、转义可逆、json 结构、统计一致性）。"""
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
JS = os.path.join(REPO, 'work', 'analysis', 'js19')
CHARSET = os.path.join(REPO, 'assets', 'charset', 'charset_compiled_zh16.json')


def unesc(s):
    out, i = [], 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            c = s[i + 1]
            out.append({'r': '\r', 'n': '\n', 't': '\t', '\\': '\\'}.get(c, c))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return ''.join(out)


def main():
    ok = True
    chk = []

    def c(cond, msg):
        nonlocal ok
        ok = ok and bool(cond)
        chk.append(('ok   ' if cond else 'FAIL ') + msg)

    # ---- CSV ----
    p = os.path.join(JS, 'js19_lang_decoded.csv')
    rows = list(csv.DictReader(open(p, encoding='utf-8-sig')))
    c(len(rows) == 2971, 'js19_lang_decoded.csv 2971 行 (实际 %d)' % len(rows))
    c(all(r['confidence'] in ('verified', 'high') for r in rows), 'confidence 只有 verified/high')
    c(sum(1 for r in rows if r['changed'] == '1') == 2278, 'changed=2278')
    c(sum(1 for r in rows if r['changed'] == '0') == 693, 'unchanged=693')
    c(all(r['text_en'] == r['text_en'].replace('\n', '\\n') for r in rows),
      'text_en 无裸换行（字面转义）')
    # 抽 100 条：text_zh 非空、可逆转义
    cjk = re.compile(r'[\u3400-\u9fff\uf900-\ufaff]')
    n_zh = 0
    for r in rows:
        z = unesc(r['text_zh_js19'])
        if cjk.search(z):
            n_zh += 1
    c(n_zh == 2313, '含汉字条目 2313 = 2275 已译 + 38 条未译的重音字节重画 (实际 %d)' % n_zh)
    # 未译条目里 38 条「显示层重音字节被改画」的标记
    acc = [r for r in rows if '重音字节' in r['note']]
    c(len(acc) == 38, '38 条重音重画标记存在 (实际 %d)' % len(acc))
    c(all(r['changed'] == '0' for r in acc), '重音重画标记只出现在未译条目')
    # 与 en_lang.json 对账
    en = json.load(open(os.path.join(JS, 'en_lang.json'), encoding='utf-8'))
    c(len(en) == 2971, 'en_lang.json 2971 条')
    ek = {(x['g'], x['i']): x for x in en}
    bad = 0
    for r in rows[:300]:
        x = ek.get((int(r['g']), int(r['i'])))
        if x is None or unesc(r['text_en']) != x['text']:
            bad += 1
    c(bad == 0, 'text_en 前 300 行与 en_lang.json 一致 (坏 %d)' % bad)

    # ---- charset json ----
    cs = json.load(open(os.path.join(JS, 'js19_charset.json'), encoding='utf-8'))
    c(len(cs['pair']) == 813, 'pair 映射 813 (实际 %d)' % len(cs['pair']))
    c(len(cs['single']) == 168, 'single 映射 168 (实际 %d)' % len(cs['single']))
    c(all(v.get('char') for v in cs['pair'].values()), 'pair 全部有 char')
    c(all(v.get('char') for v in cs['single'].values()), 'single 全部有 char')
    g = cs['geometry']
    c((g['ncol'], g['cell_w'], g['cell_h'], g['x0'], g['y0']) == (62, 8, 16, 2, 2), '几何常量正确')
    c(g['pair_cap'] == 1222, 'pair 容量 1222')
    # pair key 与 slot 自洽
    badk = [k for k, v in cs['pair'].items()
            if (int(k[:2], 16) - 0xA1) * 94 + (int(k[2:], 16) - 0xA1) != v['slot']]
    c(not badk, 'pair key 与 slot 自洽 (坏 %d)' % len(badk))

    # ---- 用字覆盖 ----
    base = json.load(open(CHARSET, encoding='utf-8'))
    bset = set(base['pair_of']) | set(base['codes'])
    need = json.load(open(os.path.join(JS, 'js19_chars_needed.json'), encoding='utf-8'))
    miss = [x for x in need['chars'] if not x['in_base_pair'] and not x['in_base_single']]
    c(len(need['chars']) == 881, '用字 881 (实际 %d)' % len(need['chars']))
    c(not miss, '881 用字全部在本工程 charset 内 (缺 %d)' % len(miss))

    # ---- TM ----
    tm = list(csv.DictReader(open(os.path.join(JS, 'js19_tm_unique.csv'), encoding='utf-8-sig')))
    c(len(tm) == 1792, 'TM 去重 1792 (实际 %d)' % len(tm))

    # ---- 报告 ----
    for line in chk:
        print(line)
    print('\n答案: %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
