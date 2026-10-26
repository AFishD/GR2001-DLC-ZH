# -*- coding: utf-8 -*-
r"""js19_en_ref.py — 从 DLC 原盘提取英文 LANG 参考（只读），并与 JS19 中文构筑逐条对齐。

输出:
  work/analysis/js19/en_lang.json     [{g,i,text_en(bytes->cp1252),raw_hex}]
  work/analysis/js19/lang_alignment.csv  g,i,len_en,en_bytes,zh_bytes...
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'font'))
import dlclib as L            # noqa: E402

JS = os.path.join(REPO, 'work', 'analysis', 'js19')
DLC_ISO = os.path.join(REPO, 'third_party', 'orig', 'ps2',
                       "[PS2] Tom Clancy's Ghost Recon - Jungle Storm (U).iso")
P_LANG_JS = os.path.join(JS, 'payloads', '00576_EN_STRINGS.RES.bin')

ENTRY_ID = 576


def decode_cp1252(b):
    s = []
    for v in b:
        try:
            s.append(bytes([v]).decode('cp1252'))
        except UnicodeDecodeError:
            s.append(chr(v))
    return ''.join(s)


def load_en():
    with L.Iso(DLC_ISO) as iso:
        ents = L.img_entries(iso)
        e = ents[ENTRY_ID]
        payload = L.entry_payload(iso, e)
        blob = payload['blob']
        lent, used = L.parse_lang(blob)
        print('EN LANG: %d entries, real=%d' % (len(lent), e['real']))
        out = [dict(g=x.g, i=x.i, raw=x.data.hex(), text=decode_cp1252(x.data),
                    attr=x.attr) for x in lent]
        json.dump(out, open(os.path.join(JS, 'en_lang.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        return out


def load_js():
    raw = open(P_LANG_JS, 'rb').read()
    blob = b''.join(s[0] for s in L.lzo_subs(raw))
    ents, used = L.parse_lang(blob)
    return ents


def main():
    en = load_en()
    js = load_js()
    print('JS LANG: %d entries' % len(js))
    if len(en) != len(js):
        print('!! 条目数不同 en=%d js=%d' % (len(en), len(js)))
    # 对齐：按 (g,i)
    key = {(x['g'], x['i']): x for x in en}
    changed = unchanged = 0
    csv = open(os.path.join(JS, 'lang_alignment.csv'), 'w', encoding='utf-8-sig', newline='')
    import csv as csvmod
    w = csvmod.writer(csv)
    w.writerow(['g', 'i', 'len_en', 'len_js', 'en_bytes', 'js_bytes', 'en', 'changed'])
    for e in js:
        ref = key.get((e.g, e.i))
        if ref is None:
            continue
        same = (ref['raw'] == e.data.hex())
        if same:
            unchanged += 1
        else:
            changed += 1
        w.writerow([e.g, e.i, len(ref['raw']) // 2, e.length, ref['raw'], e.data.hex(),
                    ref['text'], 0 if same else 1])
    csv.close()
    print('对齐: changed=%d unchanged=%d' % (changed, unchanged))
    # 统计英文里 high-byte 与中文条目里 high-byte
    import collections
    en_hi = collections.Counter()
    for x in en:
        for b in bytes.fromhex(x['raw']):
            if b >= 0xA1:
                en_hi[b] += 1
    print('英文 LANG 里 >=0xA1 字节统计: 总 %d' % sum(en_hi.values()))
    print(' top:', en_hi.most_common(20))


if __name__ == '__main__':
    main()
