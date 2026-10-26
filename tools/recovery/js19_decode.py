# -*- coding: utf-8 -*-
r"""js19_decode.py — 用「OCR 图集 slot→char」+「cave pair→slot」解码 JS19 LANG 全部条目。

输出 work/analysis/js19/js19_lang_decoded.csv（g,i,text_en,text_zh_js19,confidence,...）
"""
import csv
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'font'))
import dlclib as L            # noqa: E402
import fontlib as F           # noqa: E402

JS = os.path.join(REPO, 'work', 'analysis', 'js19')
P_LANG = os.path.join(JS, 'payloads', '00576_EN_STRINGS.RES.bin')
P_OCR = os.path.join(JS, 'js19_atlas_ocr.json')
P_FT = os.path.join(JS, 'js19_ft_records.json')
P_EN = os.path.join(JS, 'en_lang.json')

NCOL = 62
PAIR_CAP = (0xAE - 0xA1) * 94          # 1222


def lang_entries():
    raw = open(P_LANG, 'rb').read()
    blob = b''.join(s[0] for s in L.lzo_subs(raw))
    ents, used = L.parse_lang(blob)
    return ents


def slot_of(lead, trail):
    return (lead - 0xA1) * 94 + (trail - 0xA1)


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


def load_slot2ch():
    ocr = json.load(open(P_OCR, encoding='utf-8'))
    slot2ch, slot2conf = {}, {}
    for c in ocr['cells']:
        s = c['slot']
        if c.get('char'):
            slot2ch[s] = c['char']
            slot2conf[s] = c['confidence']
    # 单字节码：占位（后续 FT rect OCR 填补）
    return slot2ch, slot2conf, ocr


CJK_RE = re.compile(r'[\u3400-\u9fff\uf900-\ufaff]')


def score(text):
    if not text:
        return dict(n=0, cjk=0, cjk_ratio=0.0, unknown=0, ascii_ratio=0.0)
    n = len(text)
    cjk = len(CJK_RE.findall(text))
    unknown = text.count('\u25a1') + text.count('?')
    return dict(n=n, cjk=cjk, cjk_ratio=cjk / n, unknown=unknown,
                ascii_ratio=sum(1 for c in text if c.isascii()) / n)


def main():
    ents = lang_entries()
    slot2ch, slot2conf, ocr = load_slot2ch()
    en = json.load(open(P_EN, encoding='utf-8'))
    enkey = {(x['g'], x['i']): x for x in en}
    # 单字节码暂用占位：≥0xAE → '\ue000' 类标记，先看 pair 覆盖率
    stats = dict(pair=0, pair_hit=0, pair_blank=0, single_hi=0, single_lo=0)
    out = []
    for e in ents:
        codes = split_codes(e.data)
        parts, confs = [], []
        for kind, c in codes:
            if kind == 'pair':
                stats['pair'] += 1
                s = slot_of(*c)
                ch = slot2ch.get(s)
                if ch:
                    parts.append(ch)
                    confs.append(slot2conf.get(s, 'none'))
                    stats['pair_hit'] += 1
                else:
                    parts.append('\u25a1')
                    confs.append('blank')
            else:
                if c >= 0xAE:
                    stats['single_hi'] += 1
                    parts.append('<%02X>' % c)
                    confs.append('ft')
                else:
                    stats['single_lo'] += 1
                    parts.append(chr(c))
                    confs.append('ascii')
        zh = ''.join(parts)
        ref = enkey.get((e.g, e.i), {})
        out.append(dict(g=e.g, i=e.i, en=ref.get('text', ''), zh=zh,
                        raw=e.data.hex(), conf='|'.join(sorted(set(confs))),
                        changed=(ref.get('raw') != e.data.hex())))
    print('pair=%d hit=%d (%.2f%%) single_hi=%d single_lo=%d'
          % (stats['pair'], stats['pair_hit'], 100.0 * stats['pair_hit'] / max(1, stats['pair']),
             stats['single_hi'], stats['single_lo']))
    changed = [x for x in out if x['changed']]
    print('翻译条目 %d' % len(changed))
    print('\n=== 抽 15 条 changed 样本 ===')
    for x in changed[:15]:
        print('%d.%d\n  EN: %s\n  ZH: %s' % (x['g'], x['i'], x['en'][:90], x['zh'][:90]))
    # 统计 pair 未命中的 slot
    miss = {}
    for e in ents:
        for kind, c in split_codes(e.data):
            if kind == 'pair':
                s = slot_of(*c)
                if s not in slot2ch:
                    miss[s] = miss.get(s, 0) + 1
    print('\n未命中 slot %d 个, top 20: %s' % (len(miss), sorted(miss.items(), key=lambda kv: -kv[1])[:20]))
    json.dump(out, open(os.path.join(JS, '_decoded_tmp.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print('[tmp] _decoded_tmp.json')


if __name__ == '__main__':
    main()
