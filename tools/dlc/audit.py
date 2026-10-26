# -*- coding: utf-8 -*-
r"""audit.py —— 汉化完整性审计（从成品 ISO 回读，不是看资产表）。

输出 work/analysis/final_audit.json + 控制台摘要：
  A LANG：2971 条中已中文/仍英文/空/纯数字符号 的分类与残留英文样例
  B SFXML：98 个 <text> + 174 个标题的翻译覆盖
  C MIS：45+ 个任务文件的玩家可见字段翻译覆盖
  D ATR / EN_STRINGS.TXT
  E 字库：所有译文用字可编码；字形覆盖
  F ELF：CRC / sha
"""
import argparse
import collections
import hashlib
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))

import dlclib as L                                             # noqa: E402
import tcslib as T                                             # noqa: E402

CHARSET = os.path.join(REPO, 'assets', 'charset', 'charset_compiled_zh16.json')
OUT = os.path.join(REPO, 'work', 'analysis', 'final_audit.json')
CJK = re.compile(r'[\u4e00-\u9fff]')
EN_WORD = re.compile(r'[A-Za-z]{3,}')


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def xor_crc32(data):
    c = 0
    for (w,) in __import__('struct').iter_unpack('<I', data[:len(data) // 4 * 4]):
        c ^= w
    return c & 0xFFFFFFFF


def text_class(s):
    if not s.strip():
        return 'empty'
    if CJK.search(s):
        return 'zh'
    if EN_WORD.search(s):
        return 'en'
    return 'symbol'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--iso', default=os.path.join(REPO, 'work', 'builds', 'JS_ZH_v2.iso'))
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                          # noqa: BLE001
        pass
    iso = L.Iso(a.iso)
    ents = L.img_entries(iso)
    cs = T.Charset(CHARSET)
    rep = dict(iso=dict(path=os.path.relpath(iso.path, REPO),
                        bytes=iso.size, sha256=L.sha256_file(iso.path)))
    # ELF
    elf = iso.elf()
    rep['elf'] = dict(bytes=len(elf), sha256=sha256(elf), crc='%08X' % xor_crc32(elf))

    # ── A. LANG ──
    e_lang = L.img_find(ents, 'EN_STRINGS.RES')
    lang = L.entry_payload(iso, e_lang)
    ents_l, used = L.parse_lang(lang['blob'])
    cls = collections.Counter()
    by_group = collections.defaultdict(lambda: collections.Counter())
    en_samples = collections.defaultdict(list)
    zh_chars = collections.Counter()
    for e in ents_l:
        try:
            txt, _ = cs.decode(e.data)
        except Exception:                                      # noqa: BLE001
            txt = ''
        c = text_class(txt)
        cls[c] += 1
        by_group[e.g + 1][c] += 1
        for ch in txt:
            if CJK.match(ch):
                zh_chars[ch] += 1
        if c == 'en' and len(en_samples[e.g + 1]) < 6:
            en_samples[e.g + 1].append(dict(i=e.i, en=txt[:90]))
    rep['lang'] = dict(entries=len(ents_l), groups=67, classes=dict(cls),
                       zh_chars=len(zh_chars), zh_char_total=sum(zh_chars.values()),
                       groups_en=[g for g, c in by_group.items() if c['en']],
                       en_samples=dict(en_samples),
                       per_group={g: dict(c) for g, c in sorted(by_group.items())})

    # ── B. SFXML ──
    e_sf = L.img_find(ents, 'EN_SPECIAL_FEATURE.XML')
    sf = L.entry_payload(iso, e_sf)['blob']
    texts = T.parse_sfxml(sf)
    tcls = collections.Counter()
    ten = []
    for (k, off, ln, body) in texts:
        try:
            txt, _ = cs.decode(body)
        except Exception:                                  # noqa: BLE001
            txt = body.decode('latin-1')
        c = text_class(txt)
        tcls[c] += 1
        if c == 'en' and len(ten) < 10:
            ten.append(txt[:90])
    # 标题：<item name="..."> 等属性
    titles = re.findall(rb'(?:studio|group|item) name="([^"]*)"', sf)
    def _dec(b):
        try:
            return cs.decode(b)[0]
        except Exception:                                  # noqa: BLE001
            return b.decode('latin-1')
    ttl = collections.Counter(text_class(_dec(x)) for x in titles)
    rep['sfxml'] = dict(texts=len(texts), classes=dict(tcls), en_samples=ten,
                        titles=len(titles), title_classes=dict(ttl))

    # ── C. MIS ──
    mis = [e for e in ents if e['name'].upper().endswith('.MIS')]
    fld_cls = collections.Counter()
    mis_en = []
    for e in mis:
        try:
            blob = L.entry_payload(iso, e)['blob']
        except Exception:                                      # noqa: BLE001
            continue
        for tag in (b'Name', b'MapName', b'LocationText', b'DateText',
                    b'BriefingText', b'RecommendedGameTypes'):
            m = re.search(b'<' + tag + b'>([^<]*)</' + tag + b'>', blob)
            if not m:
                continue
            try:
                txt, _ = cs.decode(m.group(1))
            except Exception:                              # noqa: BLE001
                txt = m.group(1).decode('latin-1')
            c = text_class(txt)
            fld_cls[c] += 1
            if c == 'en' and len(mis_en) < 12:
                mis_en.append('%s/%s: %s' % (e['name'], tag.decode(), txt[:80]))
    rep['mis'] = dict(files=len(mis), field_classes=dict(fld_cls), en_samples=mis_en)

    # ── D. ATR / TXT ──
    atr = [e for e in ents if e['name'].upper().endswith('.ATR')]
    atr_en = atr_zh = 0
    for e in atr:
        try:
            blob = L.entry_payload(iso, e)['blob']
        except Exception:                                      # noqa: BLE001
            continue
        m = re.search(b'<ActorName>([^<]*)</ActorName>', blob)
        if m:
            try:
                t, _ = cs.decode(m.group(1))
            except Exception:                              # noqa: BLE001
                t = m.group(1).decode('latin-1')
            if CJK.search(t):
                atr_zh += 1
            else:
                atr_en += 1
    txt = [e for e in ents if e['name'].upper() == 'EN_STRINGS.TXT']
    rep['atr'] = dict(files=len(atr), zh=atr_zh, en=atr_en,
                      note='人名按规范保留英文')
    # TXT
    if txt:
        b = L.entry_payload(iso, txt[0])['blob']
        rep['strings_txt'] = dict(bytes=len(b), sha256=sha256(b))

    # ── E. 字库覆盖 ──
    missing = collections.Counter()
    for e in ents_l:
        try:
            t, _ = cs.decode(e.data)
        except Exception:                                      # noqa: BLE001
            continue
        for ch in t:
            if ord(ch) > 0x7F and ch not in cs.enc_single and ch not in cs.enc_pair:
                missing[ch] += 1
    rep['font'] = dict(charset_pairs=len(cs.enc_pair), charset_singles=len(cs.enc_single),
                       missing_chars=len(missing), missing=list(missing))
    iso.close()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(rep, io.open(OUT, 'w', encoding='utf-8', newline='\n'),
              ensure_ascii=False, indent=1)
    # 控制台摘要
    print('ISO %s  %d B  CRC %s' % (os.path.basename(a.iso), rep['iso']['bytes'],
                                    rep['elf']['crc']))
    print('LANG  %d 条: %s ; 仍英文组 %s ; 汉字 %d 种 / %d 次'
          % (rep['lang']['entries'], rep['lang']['classes'],
             rep['lang']['groups_en'], rep['lang']['zh_chars'],
             rep['lang']['zh_char_total']))
    print('SFXML %d texts: %s ; titles %d: %s'
          % (rep['sfxml']['texts'], rep['sfxml']['classes'], rep['sfxml']['titles'],
             rep['sfxml']['title_classes']))
    print('MIS   %d 文件字段分类: %s' % (rep['mis']['files'], rep['mis']['field_classes']))
    print('ATR   %d 文件: 中文名 %d / 英文名 %d' % (rep['atr']['files'],
                                                  rep['atr']['zh'], rep['atr']['en']))
    print('字库  %d 对偶 + %d 单字节 ; 缺字 %d %s'
          % (rep['font']['charset_pairs'], rep['font']['charset_singles'],
             rep['font']['missing_chars'], rep['font']['missing'][:10]))
    print('输出:', os.path.relpath(OUT, REPO))
    return 0


if __name__ == '__main__':
    sys.exit(main())
