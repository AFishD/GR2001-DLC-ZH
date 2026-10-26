#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""dump_text.py —— 《幽灵行动：丛林风暴》PS2 (SLUS-20820) 资料片文本抽取 / 翻译记忆 / 注入约束分析。

本文件是**库**：正式构筑链通过 python tools\dlc\build.py --stage dump-text 调用它
（产物 → work/analysis/text/tables/，含原文表与原文/译文对照表）。
也可单独跑（PowerShell，先设 $env:PYTHONIOENCODING="utf-8"）：
    python tools\dlc\dump_text.py dump          # 只读原盘 → assets/text/source/*.csv + manifest_*.json
    python tools\dlc\dump_text.py tm            # 翻译记忆 → work/analysis/text/tm_matches.csv + tm_stats.json
    python tools\dlc\dump_text.py chars         # 用字清单 → work/analysis/text/needed_chars.json
    python tools\dlc\dump_text.py plan          # 注入约束预测 → work/analysis/text/inject_bounds.json
    python tools\dlc\dump_text.py all           # dump + tm + chars + plan
    python tools\dlc\dump_text.py audit         # 打印资源/条目统计摘要

约定：
  · 所有 CSV = UTF-8 with BOM / CRLF；正文列内 CR LF TAB 一律字面转义（\\r \\n \\t），绝不出现真换行。
  · LANG id 口径 = 'G%03d.I%03d'（1-based 组号；与本体工程 assets/text/*.csv 一致）。
  · 不写 ISO、不跑 git；原盘只读。
"""
import argparse
import collections
import hashlib
import io
import json
import os
import re
import struct
import sys
import math
import random

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)

import dlclib                                                     # noqa: E402
import textlib as T                                               # noqa: E402

P = T.P
SOURCE = T.SOURCE_DIR
WORK = T.WORK_TEXT

# ═════════════════════════ 资源审计 / 统计 ═════════════════════════
FILE_EXT_RE = re.compile(
    r'\.(rsb|atr|mis|xml|wav|keys|env|gun|kit|pob|qob|ico|bmz|sb|ss|sh|qoz|cha|pss|gtf|dir|bik|txt)\s*$',
    re.I)
FORMAT_RE = re.compile(r'%[-+ #0]*[\d.]*[sdxXofeEgG]')
PURE_NUM_RE = re.compile(r'^[-+]?\d+(\.\d+)?$')
KEEP_SHORT = {'-', "'", '"', '', 'mainmenu', 'mainMenu', 'MAINMENU'}

# 本体成品盘 EN_STRINGS.TXT 里实际被译成中文的 10 个 token（2026-10-21 实测，见 probe8）
BASE_TRANSLATED_TXT_TOKENS = {
    'WPN_EXTRAAMMO', 'ITM_BINOCULARS', 'ITM_SENSOR', 'ITM_CLAYMORE', 'ITM_BOMB',
    'No Restrictions', 'Pistols Only', 'Primary Weapons Only',
    'Standard Kits', 'Originals Only',
}


def group_role(g):
    for rng, role in T.LANG_GROUP_ROLES.items():
        if g in rng:
            return role
    return '其它'


def classify_lang_keep(rec):
    """LANG 条目是否「不该翻译 / 不显示」（内部文件名、格式串、内部 key）。"""
    text = rec['text']
    if not text:
        return True, 'empty'
    if FILE_EXT_RE.search(text):
        return True, 'filename/internal'
    if FORMAT_RE.search(text) and '{' not in text:
        return True, 'format'
    if PURE_NUM_RE.match(text):
        return True, 'number'
    return False, ''


def load_all(iso):
    entries = dlclib.img_entries(iso)
    P('[load] LANG ...')
    lang = T.load_lang(iso, entries)
    P('[load] SFXML ...')
    sfxml = T.load_sfxml(iso, entries)
    P('[load] MIS ...')
    mis = T.load_mis(iso, entries)
    P('[load] ATR ...')
    atr = T.load_atr(iso, entries)
    P('[load] EN_STRINGS.TXT ...')
    txt = T.load_txt(iso, entries)
    P('[load] 其它 XML 审计 ...')
    xml_audit = T.audit_other_xml(iso, entries)
    return dict(entries=entries, lang=lang, sfxml=sfxml, mis=mis, atr=atr,
                txt=txt, xml_audit=xml_audit)


# ═════════════════════════ 统一文本单元 ═════════════════════════
ATR_TRANSLATABLE_ROLES = {
    'Rifleman', 'Demolitions', 'Support', 'Sniper',
    'Cuban Rifleman', 'Cuban Demolition', 'Cuban Support', 'Cuban Sniper',
}


def build_units(data, base_assets=None):
    """把全部资源摊平成统一 unit 列表（供 CSV/统计/TM/用字/注入预测共用）。

    unit = dict(resource, id, text, bytes, meta, keep, keep_reason, lang_ref)
    """
    units = []
    # ── LANG ──
    lang_by_text = collections.defaultdict(list)
    for r in data['lang']['rows']:
        if r['length']:
            lang_by_text[r['data']].append(r['id'])
    for r in data['lang']['rows']:
        text = T.decode_en(r['data'], 'LANG/%s' % r['id']) if r['length'] else ''
        keep, reason = classify_lang_keep(dict(text=text))
        dup = lang_by_text.get(r['data'], [])
        units.append(dict(resource='LANG', id=r['id'], text=text, raw=r['data'],
                          meta=dict(g=r['g'], gi=r['gi'], length=r['length'],
                                    attr=r['attr'].hex(),
                                    dup=[x for x in dup if x != r['id']][:2],
                                    dup_n=len(dup)),
                          keep=keep, keep_reason=reason, lang_ref=None))
    # ── SFXML 正文 ──
    for t in data['sfxml']['texts']:
        text = T.decode_en(t['text'], 'SFXML/%s' % t['id'])
        units.append(dict(resource='SFXML', id=t['id'], text=text, raw=t['text'],
                          meta=dict(studio=t['studio'], group=t['group'], item=t['item']),
                          keep=False, keep_reason='', lang_ref=None))
    # ── SFXML 标题 ──
    for t in data['sfxml']['titles']:
        keep = (t['name'] == '')
        units.append(dict(resource='SFXML_TITLE', id=t['id'], text=t['name'],
                          raw=t['name'].encode('latin-1'),
                          meta=dict(tag=t['tag'], studio=t['studio'], group=t['group'],
                                    order=t['order']),
                          keep=keep, keep_reason='empty' if keep else '', lang_ref=None))
    # ── MIS 字段 ──
    for m in data['mis']:
        for f in m['fields']:
            text = T.decode_en(f['value'], 'MIS/%s/%s' % (m['name'], f['field']))
            ref = lang_by_text.get(f['value'], [None])[0]
            units.append(dict(resource='MIS', id='MIS:%s:%s' % (m['name'], f['field']),
                              text=text, raw=f['value'],
                              meta=dict(file=m['name'], field=f['field'],
                                        span=f['span'], lang_ref=ref),
                              keep=False, keep_reason='', lang_ref=ref))
    # ── ATR ActorName ──
    for a in data['atr']:
        f = a['fields'].get('ActorName')
        if not f:
            continue
        text = T.decode_en(f['value'], 'ATR/%s' % a['name'])
        cls = a['fields'].get('ClassName', {}).get('value', b'').decode('latin-1')
        translatable = text in ATR_TRANSLATABLE_ROLES
        units.append(dict(resource='ATR', id='ATR:%s:ActorName' % a['name'],
                          text=text, raw=f['value'],
                          meta=dict(file=a['name'], field='ActorName', class_name=cls,
                                    span=f['span']),
                          keep=not translatable,
                          keep_reason='' if translatable else '人名（本体成品盘未译，建议保留英文）',
                          lang_ref=None))
    # ── EN_STRINGS.TXT ──
    # 本体成品盘只译了 10 个 token 的 value（物品名/套件限制名）；武器名/按键名保留英文。
    txt_translatable = set(BASE_TRANSLATED_TXT_TOKENS)
    if base_assets:
        for tok in (base_assets.get('txt_zh_tokens') or {}):
            txt_translatable.add(tok)
    for p in data['txt']['pairs']:
        text = T.decode_en(p['value'], 'TXT/%s' % p['token'])
        sec = p['section']
        keep = True
        reason = '本体成品盘未译（武器名/按键名按本体惯例保留英文）'
        if p['token'] in txt_translatable:
            keep, reason = False, ''
        elif sec.startswith('// Kit restriction') or sec.startswith('// weapons'):
            # 武器名、kit 名：本体惯例保留英文
            keep, reason = True, '武器/套件名（本体惯例保留英文）'
        units.append(dict(resource='STRINGS_TXT', id=p['id'], text=text, raw=p['value'],
                          meta=dict(token=p['token'], section=sec, line=p['line']),
                          keep=keep, keep_reason=reason, lang_ref=None))
    return units


# ═════════════════════════ 统计 ═════════════════════════
def tag_hist(blob):
    return dict(collections.Counter(m.group(0).decode('latin-1')
                                    for m in re.finditer(rb'\{[a-zA-Z0-9_]+\}', blob)))


def nonascii_hist(blob):
    return {'%02X' % b: n for b, n in sorted(collections.Counter(
        x for x in blob if x >= 0x80).items())}


def source_stats(data, units):
    lang = data['lang']
    lang_rows = lang['rows']
    nonempty = [r for r in lang_rows if r['length']]
    dups = collections.Counter(r['data'] for r in nonempty)
    sf = data['sfxml']
    sf_empty = sum(1 for t in sf['texts'] if not len(t['text']))
    mis_files = data['mis']
    atr = data['atr']
    txt = data['txt']
    translatable = [u for u in units if not u['keep'] and u['text']]
    st = dict(
        iso=dict(path=os.path.basename(dlclib.DEFAULT_ISO), size=dlclib.ISO_BYTES,
                 sha256=dlclib.ISO_SHA256),
        generated_by='tools/dlc/dump_text.py',
        lang=dict(
            container='GR.IMG#%d EN_STRINGS.RES' % T.LANG_IDX,
            entry=dict(stored=lang['entry']['stored'], real=lang['entry']['real'],
                       off=lang['entry']['off'], iso_off=lang['entry']['iso_off']),
            groups=lang['ngroups'], entries=len(lang_rows), nonempty=len(nonempty),
            empty=len(lang_rows) - len(nonempty),
            blob_bytes=len(lang['blob']), used_bytes=lang['used_end'],
            tail_hex=lang['tail'].hex(),
            text_bytes=sum(r['length'] for r in lang_rows),
            chunk_rlens=[c['rlen'] for c in lang['chunks']],
            chunk_clens=[c['clen'] for c in lang['chunks']],
            chunk_kinds=[c['kind'] for c in lang['chunks']],
            stored_bytes=lang['entry']['stored'],
            slack=T.entry_slack(data['entries'], T.LANG_IDX),
            tags=tag_hist(b''.join(r['data'] for r in lang_rows)),
            nonascii=nonascii_hist(b''.join(r['data'] for r in lang_rows)),
            cp1252_chars={('0x%02X' % int(k, 16)): T._CP1252.get(int(k, 16), '?')
                          for k in nonascii_hist(b''.join(r['data'] for r in lang_rows))},
            nonascii_bytes=sum(1 for r in lang_rows for b in r['data'] if b >= 0x80),
            attrs_nonzero=sum(1 for r in lang_rows if r['attr'] != b'\x00\x00'),
            dup_string_groups=sum(1 for n in dups.values() if n > 1),
            dup_string_extra=sum(n - 1 for n in dups.values() if n > 1),
            per_group={str(g): n for g, n in sorted(collections.Counter(
                r['g'] for r in lang_rows).items())},
            max_entry_bytes=max(r['length'] for r in lang_rows),
            avg_entry_bytes=round(sum(r['length'] for r in lang_rows) / len(lang_rows), 2),
        ),
        sfxml=dict(
            container='GR.IMG#%d EN_SPECIAL_FEATURE.XML' % T.SFXML_IDX,
            entry=dict(stored=sf['entry']['stored'], real=sf['entry']['real'],
                       off=sf['entry']['off']),
            blob_bytes=len(sf['blob']),
            texts=len(sf['texts']), texts_empty=sf_empty,
            texts_selfclose=sf.get('selfclose_texts', 0),
            text_bytes=sum(len(t['text']) for t in sf['texts']),
            titles=len(sf['titles']),
            titles_by_tag=dict(collections.Counter(t['tag'] for t in sf['titles'])),
            chunk_rlens=[c['rlen'] for c in sf['chunks']],
            chunk_clens=[c['clen'] for c in sf['chunks']],
            chunk_kinds=[c['kind'] for c in sf['chunks']],
            stored_bytes=sf['entry']['stored'],
            slack=T.entry_slack(data['entries'], T.SFXML_IDX),
            tags=tag_hist(sf['blob']),
            nonascii=nonascii_hist(sf['blob']),
            tail_hex=sf['blob'][max(0, sf['blob'].rfind(b'</SpecialFeatures>')):][:160].hex(),
        ),
        mis=dict(
            files=len(mis_files),
            fields={f: sum(1 for m in mis_files for x in m['fields'] if x['field'] == f)
                    for f in T.MIS_FIELDS},
            display_bytes=sum(len(f['value']) for m in mis_files for f in m['fields']),
            chunk_rlen_sets=[len(m['chunks']) for m in mis_files],
            raw_chunk_files=[m['name'] for m in mis_files
                             if any(c['kind'] == 'raw' for c in m['chunks'])],
            stored_total=sum(m['entry']['stored'] for m in mis_files),
            real_total=sum(m['entry']['real'] for m in mis_files),
        ),
        atr=dict(
            files=len(atr),
            actor_names=sum(1 for a in atr if 'ActorName' in a['fields']),
            distinct_actor_names=len({a['fields']['ActorName']['value'] for a in atr
                                      if 'ActorName' in a['fields']}),
        ),
        strings_txt=dict(
            container='GR.IMG#%d EN_STRINGS.TXT' % T.TXT_IDX,
            entry=dict(stored=txt['entry']['stored'], real=txt['entry']['real']),
            pairs=len(txt['pairs']),
            sections=[s['text'] for s in txt['sections']],
            value_bytes=sum(len(p['value']) for p in txt['pairs']),
            slack=T.entry_slack(data['entries'], T.TXT_IDX),
        ),
        other_xml=[dict(name=r['name'], idx=r['idx'], verdict=r['verdict'],
                        player_text=len(r['player_text'])) for r in data['xml_audit']],
        units=dict(total=len(units), translatable=len(translatable),
                   by_resource=dict(collections.Counter(u['resource'] for u in units)),
                   translatable_by_resource=dict(collections.Counter(
                       u['resource'] for u in translatable)),
                   keep=sum(1 for u in units if u['keep'])),
        totals=dict(
            player_visible_bytes=sum(len(u['raw']) for u in units
                                     if not u['keep'] and u['raw']),
            player_visible_en_chars=sum(T.en_visible_len(u['text']) for u in translatable),
        ),
    )
    return st


# ═════════════════════════ 产物：dump ═════════════════════════
def dump_lang(iso, data):
    rows = data['lang']['rows']
    by_text = collections.defaultdict(list)
    for r in rows:
        if r['length']:
            by_text[r['data']].append(r['id'])
    out = []
    for r in rows:
        text = T.decode_en(r['data'], 'LANG/%s' % r['id']) if r['length'] else ''
        keep, reason = classify_lang_keep(dict(text=text))
        flags = []
        if not r['length']:
            flags.append('empty')
        if keep:
            flags.append('keep:' + (reason or 'internal'))
        if '{p}' in text:
            flags.append('p')
        if '{br}' in text:
            flags.append('br')
        na = [b for b in r['data'] if b >= 0x80]
        if na:
            flags.append('nonascii')
        dup = by_text.get(r['data'], []) if r['length'] else []
        if len(dup) > 1:
            flags.append('dup%d' % len(dup))
        note = group_role(r['g'])
        if len(dup) > 1:
            others = [x for x in dup if x != r['id']][:2]
            note += ' ; 同文 id: %s' % ', '.join(others)
        out.append(dict(
            key=r['id'], group=r['g'], text_en=T.esc_cell(text), text_zh='',
            flags=';'.join(flags), byte_len_en=str(r['length']),
            non_ascii=';'.join('%02X' % b for b in na), notes=note))
    T.write_csv(os.path.join(SOURCE, 'lang_source.csv'),
                ['key', 'group', 'text_en', 'text_zh', 'flags', 'byte_len_en',
                 'non_ascii', 'notes'], out)
    # manifest
    man = dict(resource='LANG', csv='lang_source.csv',
               container='GR.IMG#%d EN_STRINGS.RES' % T.LANG_IDX,
               entry=dict(idx=T.LANG_IDX, name=data['lang']['entry']['name'],
                          stored=data['lang']['entry']['stored'],
                          real=data['lang']['entry']['real'],
                          off=data['lang']['entry']['off'],
                          iso_off=data['lang']['entry']['iso_off']),
               blob_bytes=len(data['lang']['blob']),
               used_end=data['lang']['used_end'], ngroups=data['lang']['ngroups'],
               tail_hex=data['lang']['tail'].hex(),
               chunks=[dict(kind=c['kind'], clen=c['clen'], rlen=c['rlen'],
                            hdr_off=c['hdr_off']) for c in data['lang']['chunks']],
               entries=[dict(id=r['id'], g=r['g'], i=r['gi'], data_off=r['data_off'],
                             length=r['length'], attr_off=r['attr_off'],
                             attr_hex=r['attr'].hex(), span_start=r['span_start'],
                             span_end=r['span_end']) for r in rows])
    T.write_json(os.path.join(SOURCE, 'manifest_lang.json'), man)
    return len(out)


def dump_sfxml(iso, data):
    sf = data['sfxml']
    out = []
    for t in sf['texts']:
        text = T.decode_en(t['text'], 'SFXML/%s' % t['id'])
        na = [b for b in t['text'] if b >= 0x80]
        flags = []
        if not t['text']:
            flags.append('empty')
        if '{p}' in text:
            flags.append('p')
        if '{br}' in text:
            flags.append('br')
        if '{{BTN:' in text:
            flags.append('btn')
        if na:
            flags.append('nonascii')
        out.append(dict(key=t['id'], studio=t['studio'] or '', group=t['group'] or '',
                        item=t['item'] or '', text_en=T.esc_cell(text), text_zh='',
                        flags=';'.join(flags), byte_len_en=str(len(t['text'])),
                        non_ascii=';'.join('%02X' % b for b in na),
                        notes='特别收录正文（XML <text>）'))
    T.write_csv(os.path.join(SOURCE, 'sfxml_text_source.csv'),
                ['key', 'studio', 'group', 'item', 'text_en', 'text_zh', 'flags',
                 'byte_len_en', 'non_ascii', 'notes'], out)
    tout = []
    for t in sf['titles']:
        tout.append(dict(key=t['id'], kind=t['tag'], parent=t['studio'] or '',
                         order=str(t['order']), text_en=T.esc_cell(t['name']),
                         text_zh='', flags='' if t['name'] else 'empty',
                         byte_len_en=str(len(t['name'].encode('latin-1'))),
                         notes='特别收录条目标题（XML 属性 <%s name="…">）' % t['tag']))
    T.write_csv(os.path.join(SOURCE, 'sfxml_titles_source.csv'),
                ['key', 'kind', 'parent', 'order', 'text_en', 'text_zh', 'flags',
                 'byte_len_en', 'notes'], tout)
    man = dict(resource='SFXML', csv=['sfxml_text_source.csv', 'sfxml_titles_source.csv'],
               container='GR.IMG#%d EN_SPECIAL_FEATURE.XML' % T.SFXML_IDX,
               entry=dict(idx=T.SFXML_IDX, name=sf['entry']['name'],
                          stored=sf['entry']['stored'], real=sf['entry']['real'],
                          off=sf['entry']['off'], iso_off=sf['entry']['iso_off']),
               blob_bytes=len(sf['blob']),
               chunks=[dict(kind=c['kind'], clen=c['clen'], rlen=c['rlen'],
                            hdr_off=c['hdr_off']) for c in sf['chunks']],
               texts=[dict(id=t['id'], span_start=t['span'][0], span_end=t['span'][1],
                           length=len(t['text']), studio=t['studio'],
                           group=t['group'], item=t['item']) for t in sf['texts']],
               titles=[dict(id=t['id'], tag=t['tag'], span_start=t['span'][0],
                            span_end=t['span'][1], studio=t['studio'],
                            group=t['group']) for t in sf['titles']])
    T.write_json(os.path.join(SOURCE, 'manifest_sfxml.json'), man)
    return len(out), len(tout)


def dump_mis(iso, data):
    out, man_files = [], []
    # 同文映射：MIS 字段字节 == DLC LANG 某条字节 → 记 lang_ref（译 LANG 即自动覆盖）
    lang_ref_by_text = {}
    for r in data['lang']['rows']:
        if r['length'] and r['data'] not in lang_ref_by_text:
            lang_ref_by_text[r['data']] = r['id']
    for m in data['mis']:
        man_fields = []
        for f in m['fields']:
            text = T.decode_en(f['value'], 'MIS/%s/%s' % (m['name'], f['field']))
            na = [b for b in f['value'] if b >= 0x80]
            flags = []
            if not f['value']:
                flags.append('empty')
            if '{p}' in text:
                flags.append('p')
            if '{br}' in text:
                flags.append('br')
            if na:
                flags.append('nonascii')
            ref = lang_ref_by_text.get(f['value'], '')
            if ref:
                flags.append('same_as_lang')
            notes = 'MIS 玩家可见字段'
            if ref:
                notes += '; 同文 LANG=%s（译好 LANG 即自动覆盖，建议 MIS 不单独译）' % ref
            out.append(dict(key='%s#%s' % (m['name'], f['field']), file=m['name'],
                            field=f['field'], lang_ref=ref, text_en=T.esc_cell(text),
                            text_zh='', flags=';'.join(flags),
                            byte_len_en=str(len(f['value'])),
                            non_ascii=';'.join('%02X' % b for b in na),
                            notes=notes))
            man_fields.append(dict(field=f['field'], span_start=f['span'][0],
                                   span_end=f['span'][1], length=len(f['value']),
                                   lang_ref=ref))
        man_files.append(dict(idx=m['entry']['idx'], name=m['name'],
                              stored=m['entry']['stored'], real=m['entry']['real'],
                              off=m['entry']['off'], iso_off=m['entry']['iso_off'],
                              chunks=[dict(kind=c['kind'], clen=c['clen'],
                                           rlen=c['rlen'], hdr_off=c['hdr_off'])
                                      for c in m['chunks']],
                              fields=man_fields))
    T.write_csv(os.path.join(SOURCE, 'mis_source.csv'),
                ['key', 'file', 'field', 'lang_ref', 'text_en', 'text_zh', 'flags',
                 'byte_len_en', 'non_ascii', 'notes'], out)
    T.write_json(os.path.join(SOURCE, 'manifest_mis.json'),
                 dict(resource='MIS', csv='mis_source.csv',
                      container='GR.IMG *.MIS（45 个，LZO 分块里的 XML）',
                      files=man_files))
    return len(out)


def dump_atr(iso, data):
    out = []
    for a in data['atr']:
        f = a['fields'].get('ActorName')
        if not f:
            continue
        text = T.decode_en(f['value'], 'ATR/%s' % a['name'])
        cls = a['fields'].get('ClassName', {}).get('value', b'').decode('latin-1')
        folder = a['fields'].get('FolderName', {}).get('value', b'').decode('latin-1')
        translatable = text in ATR_TRANSLATABLE_ROLES
        out.append(dict(key='ATR:%s:ActorName' % a['name'], file=a['name'],
                        class_name=cls, text_en=T.esc_cell(text), text_zh='',
                        flags='' if translatable else 'keep_english',
                        byte_len_en=str(len(f['value'])),
                        notes=('兵种显示名，可译' if translatable else
                               '人名（本体成品盘未译，建议保留英文）; folder=%s' % folder)))
    T.write_csv(os.path.join(SOURCE, 'atr_source.csv'),
                ['key', 'file', 'class_name', 'text_en', 'text_zh', 'flags',
                 'byte_len_en', 'notes'], out)
    T.write_json(os.path.join(SOURCE, 'manifest_atr.json'),
                 dict(resource='ATR', csv='atr_source.csv',
                      container='GR.IMG *.ATR（766 个，raw XML）',
                      files=[dict(idx=a['entry']['idx'], name=a['name'],
                                  stored=a['entry']['stored'], real=a['entry']['real'],
                                  off=a['entry']['off'],
                                  actor_name_span=(a['fields']['ActorName']['span']
                                                   if 'ActorName' in a['fields'] else None))
                             for a in data['atr']]))
    return len(out)


def dump_txt(iso, data):
    out = []
    for p in data['txt']['pairs']:
        text = T.decode_en(p['value'], 'TXT/%s' % p['token'])
        out.append(dict(key=p['id'], section=p['section'], token=p['token'],
                        text_en=T.esc_cell(text), text_zh='',
                        flags='keep_english' if p['token'] not in BASE_TRANSLATED_TXT_TOKENS
                        else '',
                        byte_len_en=str(len(p['value'])),
                        notes='token→显示名；本体成品盘只译了 10 条物品/套件名，'
                              '武器名与按键名保留英文'))
    T.write_csv(os.path.join(SOURCE, 'strings_txt_source.csv'),
                ['key', 'section', 'token', 'text_en', 'text_zh', 'flags',
                 'byte_len_en', 'notes'], out)
    T.write_json(os.path.join(SOURCE, 'manifest_strings_txt.json'),
                 dict(resource='STRINGS_TXT', csv='strings_txt_source.csv',
                      container='GR.IMG#%d EN_STRINGS.TXT' % T.TXT_IDX,
                      entry=dict(idx=T.TXT_IDX, stored=data['txt']['entry']['stored'],
                                 real=data['txt']['entry']['real'],
                                 off=data['txt']['entry']['off']),
                      chunks=[dict(kind=c['kind'], clen=c['clen'], rlen=c['rlen'],
                                   hdr_off=c['hdr_off']) for c in data['txt']['chunks']],
                      pairs=[dict(id=p['id'], token=p['token'],
                                  token_span=list(p['token_span']),
                                  value_span=list(p['value_span']),
                                  length=len(p['value']), section=p['section'])
                             for p in data['txt']['pairs']]))
    return len(out)


def dump_other_xml(iso, data):
    rows = []
    for r in data['xml_audit']:
        pt = r['player_text']
        rows.append(dict(resource=r['name'], entry_idx=str(r['idx'] or ''),
                         stored=str(r['stored'] or ''), real=str(r['real'] or ''),
                         verdict=r['verdict'],
                         tags=','.join('%s×%d' % (k, v) for k, v in
                                       sorted(r['tags'].items())[:12]),
                         player_text_count=str(len(pt)),
                         sample=' | '.join('%s=%s' % (x['tag'], T.esc_cell(x['text'])[:40])
                                           for x in pt[:3])))
    T.write_csv(os.path.join(SOURCE, 'other_xml_audit.csv'),
                ['resource', 'entry_idx', 'stored', 'real', 'verdict', 'tags',
                 'player_text_count', 'sample'], rows)
    return len(rows)


# ═════════════════════════ 机器可读 manifest（注入的唯一真源）═════════════════════════
SCHEMA = 'grjs-text-src/1'


def dump_manifest(data, units):
    """产出 assets/text/source/text_source.json —— schema grjs-text-src/1。

    items 里：
      · kind=lang        → g / i / bytes(hex)；注入按 LANG 结构重建，不用偏移
      · kind=sfxml / sfxml_title / mis / atr / txt
                         → entry(条目号) + blob_off/blob_len（相对条目 LZO 展开后的 blob）
    entries[] 给出每个被抽条目的 (entry_idx, name, blob_len, blob_sha256)，注入前核对基盘。
    """
    items = []
    # ── LANG ──
    for r in data['lang']['rows']:
        text = T.decode_en(r['data'], 'LANG/%s' % r['id']) if r['length'] else ''
        keep, _reason = classify_lang_keep(dict(text=text))
        items.append(dict(kind='lang', key=r['id'], g=r['g'], i=r['gi'],
                          text_en=T.esc_cell(text), bytes=r['data'].hex(),
                          keep=keep, csv='lang_source.csv'))
    # ── SFXML 正文 ──
    for t in data['sfxml']['texts']:
        text = T.decode_en(t['text'], 'SFXML/%s' % t['id'])
        items.append(dict(kind='sfxml', key=t['id'], entry=T.SFXML_IDX,
                          blob_off=t['span'][0], blob_len=t['span'][1] - t['span'][0],
                          field='text', text_en=T.esc_cell(text), keep=False,
                          studio=t['studio'], group=t['group'], item=t['item'],
                          csv='sfxml_text_source.csv'))
    # ── SFXML 标题 ──
    for t in data['sfxml']['titles']:
        items.append(dict(kind='sfxml_title', key=t['id'], entry=T.SFXML_IDX,
                          blob_off=t['span'][0], blob_len=t['span'][1] - t['span'][0],
                          field='title', tag=t['tag'], text_en=T.esc_cell(t['name']),
                          keep=(t['name'] == ''), csv='sfxml_titles_source.csv'))
    # ── MIS ──
    for m in data['mis']:
        for f in m['fields']:
            text = T.decode_en(f['value'], 'MIS/%s/%s' % (m['name'], f['field']))
            items.append(dict(kind='mis', key='%s#%s' % (m['name'], f['field']),
                              entry=m['entry']['idx'],
                              blob_off=f['span'][0],
                              blob_len=f['span'][1] - f['span'][0],
                              field=f['field'], text_en=T.esc_cell(text), keep=False,
                              csv='mis_source.csv'))
    # ── ATR ──
    for a in data['atr']:
        f = a['fields'].get('ActorName')
        if not f:
            continue
        text = T.decode_en(f['value'], 'ATR/%s' % a['name'])
        items.append(dict(kind='atr', key='%s#ActorName' % a['name'],
                          entry=a['entry']['idx'], blob_off=f['span'][0],
                          blob_len=f['span'][1] - f['span'][0], field='ActorName',
                          text_en=T.esc_cell(text), keep=(text not in ATR_TRANSLATABLE_ROLES),
                          csv='atr_source.csv'))
    # ── EN_STRINGS.TXT ──
    for p in data['txt']['pairs']:
        text = T.decode_en(p['value'], 'TXT/%s' % p['token'])
        items.append(dict(kind='txt', key='EN_STRINGS.TXT#%s' % p['token'],
                          entry=T.TXT_IDX, blob_off=p['value_span'][0],
                          blob_len=p['value_span'][1] - p['value_span'][0],
                          field='value', token=p['token'], section=p['section'],
                          text_en=T.esc_cell(text),
                          keep=(p['token'] not in BASE_TRANSLATED_TXT_TOKENS),
                          csv='strings_txt_source.csv'))
    # ── 条目 sha256 清单（注入前核对）──
    entries = []

    def add_entry(idx, blob, kind, store=None):
        entries.append(dict(entry_idx=idx,
                            name=(store or data['entries'][idx])['name'],
                            blob_len=len(blob),
                            blob_sha256=hashlib.sha256(blob).hexdigest(),
                            real=(store or data['entries'][idx])['real'],
                            stored=(store or data['entries'][idx])['stored'],
                            kind=kind))

    add_entry(T.LANG_IDX, data['lang']['blob'], 'lang', data['lang']['entry'])
    add_entry(T.SFXML_IDX, data['sfxml']['blob'], 'sfxml', data['sfxml']['entry'])
    add_entry(T.TXT_IDX, data['txt']['blob'], 'txt', data['txt']['entry'])
    for m in data['mis']:
        add_entry(m['entry']['idx'], m['blob'], 'mis', m['entry'])
    for a in data['atr']:
        add_entry(a['entry']['idx'], a['blob'], 'atr', a['entry'])
    entries.sort(key=lambda e: e['entry_idx'])
    manifest = dict(
        schema=SCHEMA,
        generated_by='tools/dlc/dump_text.py',
        generated_at='2026-10-21',
        iso=dict(file=os.path.basename(dlclib.DEFAULT_ISO), size=dlclib.ISO_BYTES),
        iso_sha256=dlclib.ISO_SHA256,
        encoding=dict(
            text_en='Windows-1252（>=0x80 字节按 cp1252 解码；0xB1/0xB5 → {{BTN:E0B1}}/{{BTN:E0B5}}）',
            text_zh='待译；写盘时按 assets/charset/charset_compiled_zh16.json 编码（ASCII 直通）',
            csv_escape='正文列 CR LF TAB 一律字面转义为 \\\\r \\\\n \\\\t；text_en 即该转义形态',
            control_chars='LANG/SFXML 正文实测无 C0 控制字符；MIS BriefingText 可能有 \\r\\n（已转义）',
        ),
        container_rules=dict(
            chunk='LZO 资源按 16384 B 解压块切分，帧格式 {u32 clen}{u32 rlen}{data}',
            raw_chunk='clen == rlen 表示该块原样直存（实测 107 条目；如 CP03_PRISON.MIS 尾块 969 B）',
            lang_rebuild='LANG 注入按 {u32 ngroups} + 每组 {u32 count}+count×({u32 len}{data}{u16 attr}) 重建',
            span_rule='同一 blob 内多个区间互不重叠；注入时按 blob_off 降序 splice',
            slack='每条目 stored 不可超过下一条目 off 的间隙（LANG slack=5 / SFXML=9 / MIS=3..10）',
        ),
        csv_files=dict(lang='lang_source.csv', sfxml='sfxml_text_source.csv',
                       sfxml_title='sfxml_titles_source.csv', mis='mis_source.csv',
                       atr='atr_source.csv', txt='strings_txt_source.csv',
                       xml='（无玩家可见文本，见 other_xml_audit.csv）'),
        counts=dict(collections.Counter(i['kind'] for i in items)),
        keep_count=sum(1 for i in items if i.get('keep')),
        items=items,
        entries=entries,
        other_xml_audit=[dict(name=r['name'], entry_idx=r['idx'],
                              verdict=r['verdict'],
                              player_text_count=len(r['player_text']))
                         for r in data['xml_audit']],
    )
    T.write_json(os.path.join(SOURCE, 'text_source.json'), manifest)
    # 单独一份「条目指纹清单」，便于注入器快速核对
    T.write_json(os.path.join(SOURCE, 'entries_sha256.json'),
                 dict(schema=SCHEMA, iso_sha256=dlclib.ISO_SHA256, entries=entries))
    # 翻译人员用总表（key,text_en,text_zh,notes）
    master = []
    for u in units:
        notes = u['resource']
        if u['keep']:
            notes += ' ; 不译: ' + (u['keep_reason'] or 'internal')
        if u.get('keep_reason') and u['resource'] == 'ATR':
            notes += ' ; ' + u['keep_reason']
        if u['resource'] == 'MIS' and u['lang_ref']:
            notes += ' ; 同文 LANG=%s' % u['lang_ref']
        if u.get('meta', {}).get('dup_n', 1) > 1:
            notes += ' ; 同文 %d 条' % u['meta']['dup_n']
        master.append(dict(key=u['id'], text_en=T.esc_cell(u['text']),
                           text_zh='', notes=notes))
    T.write_csv(os.path.join(SOURCE, 'translation_master.csv'),
                ['key', 'text_en', 'text_zh', 'notes'], master)
    P('  manifest   → text_source.json（schema=%s, items=%d, entries=%d）'
      % (SCHEMA, len(items), len(entries)))
    P('  翻译总表   → translation_master.csv（%d 行，key/text_en/text_zh/notes）'
      % len(master))
    return manifest


def cmd_dump(args):
    T.ensure_dirs()
    iso = dlclib.Iso(args.iso)
    try:
        data = load_all(iso)
    finally:
        iso.close()
    n_lang = dump_lang(None, data)
    n_sf, n_title = dump_sfxml(None, data)
    n_mis = dump_mis(None, data)
    n_atr = dump_atr(None, data)
    n_txt = dump_txt(None, data)
    n_xml = dump_other_xml(None, data)
    units = build_units(data)
    st = source_stats(data, units)
    T.write_json(os.path.join(SOURCE, 'source_stats.json'), st)
    T.write_json(os.path.join(WORK, 'source_stats.json'), st)
    man = dump_manifest(data, units)
    # README（用 $xxx$ 占位替换，避免 str.format 把 {p}/{br} 当格式字段）
    readme = SOURCE_README
    for k, v in dict(items=len(man['items']), entries=len(man['entries']),
                     n_lang=n_lang, n_sf=n_sf, n_title=n_title, n_mis=n_mis,
                     n_atr=n_atr, n_txt=n_txt, n_xml=n_xml,
                     units=st['units']['total'],
                     trans=st['units']['translatable']).items():
        readme = readme.replace('$%s$' % k, str(v))
    with open(os.path.join(SOURCE, 'README.md'), 'w', encoding='utf-8') as f:
        f.write(readme)
    P('\n== dump 完成 ==')
    P('  LANG       %d 条 → lang_source.csv' % n_lang)
    P('  SFXML      %d 条正文 + %d 个标题' % (n_sf, n_title))
    P('  MIS        %d 个字段' % n_mis)
    P('  ATR        %d 个 ActorName' % n_atr)
    P('  TXT        %d 对 token' % n_txt)
    P('  其它 XML   %d 条审计（无玩家可见文本）' % n_xml)
    P('  统一单元   %d（其中需翻译 %d）' % (st['units']['total'],
                                            st['units']['translatable']))
    P('  产物目录   %s' % SOURCE)


SOURCE_README = """# assets/text/source —— 资料片原文表（只读；由 tools/dlc/dump_text.py 生成）

本目录是**英文原盘抽取的原文资产**，供翻译与回注使用。`text_zh` 列留空待填。

| 文件 | 内容 | 条数 |
|---|---|---|
| `text_source.json` | ★ **机器可读唯一真源**（schema `grjs-text-src/1`）：items（原文/原字节/blob 偏移）+ entries（条目 sha256 指纹） | items $items$ / entries $entries$ |
| `entries_sha256.json` | 条目指纹清单（注入前核对基盘） | — |
| `lang_source.csv` | EN_STRINGS.RES 语言表（GR#576，67 组 / 2,971 条） | $n_lang$ |
| `sfxml_text_source.csv` | EN_SPECIAL_FEATURE.XML 的 `<text>` 正文 | $n_sf$ |
| `sfxml_titles_source.csv` | 特别收录的 studio/group/item 标题（XML 属性） | $n_title$ |
| `mis_source.csv` | 45 个 *.MIS 的玩家可见字段（Name/MapName/Location/Date/Time/Briefing…） | $n_mis$ |
| `atr_source.csv` | 766 个 *.ATR 的 `<ActorName>`（人名默认保留英文） | $n_atr$ |
| `strings_txt_source.csv` | EN_STRINGS.TXT 的 token→显示名 | $n_txt$ |
| `other_xml_audit.csv` | 其它 XML 审计（结论：无玩家可见文本） | $n_xml$ |
| `translation_master.csv` | 给译者的一份扁平总表（key / text_en / text_zh / notes） | — |
| `manifest_*.json` | 分资源详细定位（LANG 条目偏移/attr、LZO 分块等），供调试 | — |
| `source_stats.json` | 结构/文本量统计 | — |

## CSV 格式（UTF-8 with BOM / CRLF）

* 正文列里 **CR LF TAB 一律字面转义**为 `\\r` `\\n` `\\t`（单行单元格，禁止真换行）。
* `{p}` / `{br}` 是引擎富文本标记（段落/换行），**原样保留**，不要改写成换行。
* `{{BTN:E0B1}}` / `{{BTN:E0B5}}` 是手柄按键图标标记（△/✕），原样保留。
* `flags` 列：`empty` / `p` / `br` / `btn` / `nonascii` / `dupN` / `keep:…`；
  `keep:` 表示按本体惯例**不翻译/不显示**（内部文件名、格式串、人名等）。
* `text_zh` 是翻译列；`key` / 偏移 / 长度列不要改。
* LANG key 口径 `G%03d.I%03d`（1 起组号），与本体工程 `assets/text/merge/*.csv` 相同。

## 重要提示

* `lang_source.csv` 的 67 组语义见 `docs/ANALYSIS_TEXT.md`；MIS 字段里 95% 以上与 LANG 同文，
  译好 LANG 后 MIS 可自动回填（见 `mis_source.csv` 的 `lang_ref` 列）。
* 人名（ATR ActorName）按本体成品盘惯例保留英文；只有 8 个兵种显示名可译。
* 日期/时间建议按 `2010年3月20日` / `06:30` 格式本地化。
* 需要翻译的单元 $trans$ / $units$；详见 `work/analysis/text/tm_stats.json`。
"""


# ═════════════════════════ TM / 用字 / 注入预测 ═════════════════════════
def load_tm_context(args):
    P('[tm] 读本体英文盘 LANG/SFXML ...')
    base_lang = T.load_base_lang_en(args.base_iso)
    base_sfx = T.load_base_sfxml_en(args.base_iso)
    P('[tm] 读本体译文资产 CSV ...')
    base_assets = T.load_base_assets()
    base_assets['txt_zh_tokens'] = {}
    txt_zh = {}
    try:
        P('[tm] 读本体成品盘 EN_STRINGS.TXT / MIS ...')
        base_txt = T.load_base_txt_en_zh(args.base_iso, args.base_zh_iso)
        for tok, rec in base_txt.items():
            if rec.get('zh') and T.has_cjk(rec['zh']):
                txt_zh[tok] = rec
        base_assets['txt_zh_tokens'] = txt_zh
        base_mis_zh = T.load_base_mis_zh(args.base_zh_iso)
    except Exception as e:                                       # noqa: BLE001
        P('[warn] 本体成品盘读取失败（%s），TM 只用 assets CSV' % e)
        base_txt, base_mis_zh = {}, {}
    P('[tm] 构造语料 ...')
    corpus = T.build_tm_corpus(base_lang, base_sfx, base_assets,
                               base_txt=base_txt, base_mis_zh=base_mis_zh)
    # MIS 语料补英文（本体成品盘 MIS 中文对应的本体英文）
    try:
        with dlclib.Iso(args.base_iso) as b:
            base_mis_en = T._load_base_menu_mis(b)               # noqa: SLF001
    except Exception:                                            # noqa: BLE001
        base_mis_en = {}
    for c in corpus:
        if c['resource'] == 'MIS' and not c.get('en'):
            m = re.match(r'MIS:([^:]+):(.+)$', c['base_id'])
            if m:
                rec = base_mis_en.get(m.group(1), {})
                raw = rec.get(m.group(2))
                if raw:
                    try:
                        c['en'] = T.decode_en(raw, 'BASE_MIS/' + c['base_id'])
                    except ValueError:
                        c['en'] = None
    corpus = [c for c in corpus if c.get('en')]
    P('[tm] 语料 %d 条（其中 LANG %d / SFXML %d / 标题 %d / TXT %d / MIS %d）' % (
        len(corpus), sum(1 for c in corpus if c['resource'] == 'LANG'),
        sum(1 for c in corpus if c['resource'] == 'SFXML'),
        sum(1 for c in corpus if c['resource'] == 'SFXML_TITLE'),
        sum(1 for c in corpus if c['resource'] == 'STRINGS_TXT'),
        sum(1 for c in corpus if c['resource'] == 'MIS')))
    return dict(base_lang=base_lang, base_sfx=base_sfx, base_assets=base_assets,
                base_txt=base_txt, base_mis_zh=base_mis_zh, corpus=corpus)


def run_tm(args, data, ctx):
    matcher = T.TMMatcher(ctx['corpus'])
    units = build_units(data, ctx['base_assets'])
    P('[tm] 逐条匹配 %d 个单元 ...' % len(units))
    prefer = {'LANG': 'LANG', 'MIS': 'LANG', 'SFXML': 'SFXML',
              'SFXML_TITLE': 'SFXML_TITLE', 'STRINGS_TXT': 'STRINGS_TXT',
              'ATR': 'LANG'}
    results = []
    for i, u in enumerate(units):
        if not u['text']:
            results.append(dict(unit=u, match=None))
            continue
        m = matcher.match(u['text'], prefer_resource=prefer.get(u['resource']))
        results.append(dict(unit=u, match=m))
        if (i + 1) % 500 == 0:
            P('    %d/%d' % (i + 1, len(units)))
    # 统计
    def cls_of(x):
        if not x['unit']['text']:
            return 'empty'
        if x['unit']['keep']:
            return 'keep'
        return x['match']['match_type'] if x['match'] else 'none'

    stat = dict(total=len(results), by_class=dict(collections.Counter(
        cls_of(x) for x in results)))
    # 需翻译口径
    trans = [x for x in results if x['unit']['text'] and not x['unit']['keep']]
    stat['translatable'] = len(trans)
    stat['translatable_by_class'] = dict(collections.Counter(
        (x['match']['match_type'] if x['match'] else 'none') for x in trans))
    en_chars = sum(T.en_visible_len(x['unit']['text']) for x in trans)
    stat['en_visible_chars'] = en_chars
    stat['en_bytes'] = sum(len(x['unit']['raw']) for x in trans)
    for k in ('exact', 'norm', 'fuzzy_high', 'fuzzy_low', 'none'):
        n = stat['translatable_by_class'].get(k, 0)
        stat[k] = n
        stat[k + '_pct'] = round(100.0 * n / max(1, len(trans)), 2)
    stat['reuse_strict'] = stat.get('exact', 0) + stat.get('norm', 0)
    stat['reuse_strict_pct'] = round(100.0 * stat['reuse_strict'] / max(1, len(trans)), 2)
    stat['reuse_with_high_fuzzy'] = stat['reuse_strict'] + stat.get('fuzzy_high', 0)
    stat['reuse_with_high_fuzzy_pct'] = round(
        100.0 * stat['reuse_with_high_fuzzy'] / max(1, len(trans)), 2)
    # 按资源
    stat['by_resource'] = {}
    for res in sorted({u['resource'] for u in units}):
        rs = [x for x in results if x['unit']['resource'] == res]
        rt = [x for x in rs if x['unit']['text'] and not x['unit']['keep']]
        c = collections.Counter((x['match']['match_type'] if x['match'] else 'none')
                                for x in rt)
        stat['by_resource'][res] = dict(
            units=len(rs), translatable=len(rt),
            exact=c.get('exact', 0), norm=c.get('norm', 0),
            fuzzy_high=c.get('fuzzy_high', 0), fuzzy_low=c.get('fuzzy_low', 0),
            none=c.get('none', 0),
            keep=sum(1 for x in rs if x['unit']['keep']),
            empty=sum(1 for x in rs if not x['unit']['text']))
    # 复用中文字符量（只取 >=0x80 的中文/全角字符；ASCII 一律不计）
    zh_chars = sum(len(T.cjk_chars(m['base_zh'])) for x in trans
                   for m in [x['match']] if m and m['match_type'] in
                   ('exact', 'norm', 'fuzzy_high'))
    matched_en_chars = sum(T.en_visible_len(x['unit']['text']) for x in trans
                           if x['match'] and x['match']['match_type'] in
                           ('exact', 'norm', 'fuzzy_high'))
    stat['reusable_zh_chars'] = zh_chars
    stat['matched_en_chars'] = matched_en_chars
    if matched_en_chars:
        stat['ratio_zh_per_en_on_matched'] = round(zh_chars / matched_en_chars, 4)
    # 全局参考比（含未覆盖，仅信息）
    if en_chars and zh_chars:
        stat['zh_per_en_char_all'] = round(zh_chars / en_chars, 4)
    stat['corpus_size'] = len(ctx['corpus'])
    stat['written'] = dict()
    # ── tm_matches.csv ──
    rows = []
    for x in results:
        u, m = x['unit'], x['match']
        rows.append(dict(
            resource=u['resource'], dlc_id=u['id'],
            text_en=T.esc_cell(u['text']),
            match_type=(m['match_type'] if m else ('skip_keep' if u['keep'] else
                                                  ('skip_empty' if not u['text'] else 'none'))),
            ratio=('%.4f' % m['ratio']) if m else '',
            base_id=m['base_id'] if m else '',
            base_resource=m['base_resource'] if m else '',
            base_text_en=T.esc_cell(m['base_en'] or '') if m else '',
            reusable_zh=T.esc_cell(m['base_zh']) if m else '',
            note=('' if m else (u['keep_reason'] or '')),))
    T.write_csv(os.path.join(WORK, 'tm_matches.csv'),
                ['resource', 'dlc_id', 'text_en', 'match_type', 'ratio', 'base_id',
                 'base_resource', 'base_text_en', 'reusable_zh', 'note'], rows)
    T.write_json(os.path.join(WORK, 'tm_stats.json'), stat)
    P('\n== 翻译记忆 ==')
    P('  可翻译单元 %d；exact=%d norm=%d fuzzy_high=%d fuzzy_low=%d none=%d'
      % (len(trans), stat['exact'], stat['norm'], stat['fuzzy_high'],
         stat['fuzzy_low'], stat['none']))
    P('  严格复用率 %.2f%%（exact+norm）；含高置信 fuzzy %.2f%%'
      % (stat['reuse_strict_pct'], stat['reuse_with_high_fuzzy_pct']))
    P('  复用中文 %d 字 / 已匹配英文 %d 字符；zh/en=%.3f'
      % (zh_chars, matched_en_chars, stat.get('ratio_zh_per_en_on_matched', 0)))
    return results, stat


def tags_to_newlines_for_xml(s):
    """把 LANG 口径的 {p}/{br} 标记转成 XML 文本里的真实换行（MIS/SFXML 用）。"""
    if not s:
        return s
    s = s.replace('{p}', '\r\n\r\n').replace('{br}', '\r\n')
    return s


# ═════════════════════════ 用字清单 ═════════════════════════
def run_chars(args, data, ctx, results, stat):
    cs = T.charset()
    known = collections.Counter()
    known_sources = collections.defaultdict(set)
    est_total = 0
    ratio = stat.get('ratio_zh_per_en_on_matched') or 0.5
    unmatched = []
    for x in results:
        u, m = x['unit'], x['match']
        if not u['text'] or u['keep']:
            continue
        reusable = m and m['match_type'] in ('exact', 'norm', 'fuzzy_high')
        if reusable and m.get('base_zh'):
            zh = m['base_zh']
            if u['resource'] in ('MIS', 'SFXML', 'SFXML_TITLE'):
                zh = tags_to_newlines_for_xml(zh)
            for ch in T.cjk_chars(zh):
                known[ch] += 1
                known_sources[ch].add(u['resource'])
        else:
            est_total += int(round(T.en_visible_len(u['text']) * ratio))
            unmatched.append(u)
    # 未匹配工作量：按本体语料字频分布摊到字上（得到「预期字频需求」）
    corpus_freq = collections.Counter()
    for c in ctx['corpus']:
        for ch in T.cjk_chars(c['zh']):
            corpus_freq[ch] += 1
    corpus_total = sum(corpus_freq.values()) or 1
    estimated = collections.Counter()
    for ch, f in corpus_freq.items():
        n = int(round(est_total * f / corpus_total))
        if n > 0:
            estimated[ch] = n
    # 术语候选新字（真实关键词 → 建议中文术语）
    corpus_text = '\n'.join(u['text'] for x in results for u in [x['unit']])
    lower = corpus_text.lower()
    cand = {}
    for eng, zh, why in T.TERM_GLOSSARY:
        hits = lower.count(eng.lower())
        if not hits:
            continue
        for ch in zh:
            if ord(ch) < 0x80:
                continue
            if ch in cs.chars:
                continue
            rec = cand.setdefault(ch, dict(char=ch, in_charset=False,
                                           estimated_count=0, terms=[]))
            rec['estimated_count'] += hits
            rec['terms'].append('%s→%s(%s)' % (eng, zh, why))
    # 统计外推：本体语料随机抽样到 70% 篇幅时的去重字数 → 边际新字率 → 乘新增篇幅
    #   （按序切半会被「语料分组顺序」污染；随机抽样的边际率更稳）
    base_zh_units = [T.cjk_chars(c['zh']) for c in ctx['corpus'] if c.get('zh')]
    seq_chars = [ch for s in base_zh_units for ch in s]
    n_full, s_full = len(seq_chars), len(set(seq_chars))
    target = int(n_full * 0.70)
    rng = random.Random(20261021)
    order = list(range(len(base_zh_units)))
    samples = []
    for _ in range(12):
        rng.shuffle(order)
        acc, seen = 0, set()
        for i in order:
            if acc >= target:
                break
            seen.update(base_zh_units[i])
            acc += len(base_zh_units[i])
        samples.append(len(seen))
    s70 = sum(samples) / max(1, len(samples))
    rate_per_1000 = ((s_full - s70) * 1000.0 / (n_full - target)) if n_full > target else 0.0
    vocab_new = int(round(rate_per_1000 * est_total / 1000.0))
    # 专名音译风险字（字体工程师口径的第二梯队：常用音译汉字池中不在本体字符集的字）
    base_vocab = set()
    for c in ctx['corpus']:
        if c.get('en'):
            base_vocab.update(re.findall(r"[a-z]{2,}", c['en'].lower()))
    proper = collections.Counter()
    for u in unmatched:
        for w in re.findall(r'\b[A-Z][A-Za-z]{2,}\b', u['text']):
            if w.lower() not in base_vocab:
                proper[w] += 1
    proper_top = [w for w, _n in proper.most_common(20)]
    tier2 = [ch for ch in sorted(set(T.TRANSLITERATION_POOL))
             if '\u4e00' <= ch <= '\u9fff' and ch not in cs.chars and ch not in cand]
    # 统计
    known_in = sum(1 for ch in known if ch in cs.chars)
    all_needed = set(known) | set(estimated) | set(cand)
    missing = sorted(ch for ch in all_needed if ch not in cs.chars)
    base_distinct_set = set(seq_chars)
    unused_existing = [ch for ch in cs.chars
                       if not (T.Charset.PUA_LO <= ord(ch) <= T.Charset.PUA_HI)
                       and ch not in base_distinct_set]
    recommended = max(len(cand), vocab_new)
    budget = int(math.ceil(recommended * 1.3))
    out = dict(
        meta=dict(
            generated_by='tools/dlc/dump_text.py chars',
            iso_sha256=dlclib.ISO_SHA256,
            charset=os.path.relpath(T.CHARSET_PATH, T.REPO),
            charset_chars=len(cs.chars),
            charset_single=len(cs.single),
            charset_pair=len(cs.pair),
            charset_free_pua_slots=len(cs.pua_free),
            ratio_zh_per_en_char=ratio,
            base_corpus_zh_chars=n_full,
            base_corpus_distinct_chars=s_full,
            note='known=TM 复用文本的真实用字；estimated=未覆盖条目的保守频次估算'
                 '（按本体语料字频分布摊分，仅作字库规划参考）；new_chars_candidates='
                 '本资料片真实关键词的建议译名中不在本体字符集的字，需译审确认；'
                 'vocab_extrapolation=本体语料随机抽样边际新字率 × 新增篇幅。'),
        known={ch: dict(count=n, in_charset=True,
                        resources=sorted(known_sources[ch])) for ch, n in
               known.most_common()},
        estimated={ch: dict(count=n, in_charset=True) for ch, n in
                   estimated.most_common()},
        new_chars_candidates=sorted(cand.values(), key=lambda r: -r['estimated_count']),
        summary=dict(
            known_distinct=len(known), known_total=sum(known.values()),
            known_all_in_charset=(known_in == len(known)),
            estimated_distinct=len(estimated), estimated_total=sum(estimated.values()),
            estimated_workload_chars=est_total,
            unmatched_units=len(unmatched),
            new_char_candidates=len(cand),
            missing_from_charset=missing,
            free_pua_slots=len(cs.pua_free),
            vocab_extrapolation=dict(
                method='本体语料随机抽样到 70% 篇幅的去重字数差 → 每千字边际新字率 → 乘新增篇幅',
                base_chars=n_full, base_distinct=s_full,
                sample70_distinct=round(s70, 1),
                marginal_new_per_1000=round(rate_per_1000, 2),
                estimated_new_chars=vocab_new),
            recommended_new_chars=recommended,
            budget_with_margin=budget,
            spare_capacity=len(cs.pua_free),
            unused_existing_chars=len(unused_existing),
            effective_spare_capacity=len(cs.pua_free) + len(unused_existing),
            spare_enough=(recommended <= len(cs.pua_free) + len(unused_existing)),
            note='新增字需求=术语候选缺字与统计外推的较大者；空 PUA 槽 + 字符集里已画但'
                 '本体正文未用到的字 = 可复用余量。翻译时优先用字符集已有字可减少补画。',
            font_budget=dict(
                capacity_new_glyphs=346,
                capacity_source='font-engineer 实测（1024×644 方案 B：298 PUA + 50 空槽 − 2 残墨）',
                named_conservative_chars=len(cand) + len(tier2),
                statistical_estimate=recommended,
                status=('可容纳' if recommended <= 346 else '可能超容量，需尽早决策扩容量'),
                note='named_conservative_chars=已点名的保守缺字（tier1 术语+地点+任务代号，'
                     'tier2 专名音译备用字）；statistical_estimate=按本体语料字频外推的'
                     '新增字需求量（尚无具体字形）。'),
            verdict=('TM 复用文本用字全部在本体字符集内' if known_in == len(known)
                     else 'TM 复用文本中有 %d 个字不在本体字符集（需核）'
                          % (len(known) - known_in)),
        ))
    T.write_json(os.path.join(WORK, 'needed_chars.json'), out)
    # ── 给字体工程师的「新字保守全集」（font-engineer 2026-10-21 约定格式）──
    named = []
    for rec in sorted(cand.values(), key=lambda r: -r['estimated_count']):
        named.append(dict(char=rec['char'], count=rec['estimated_count'], tier=1,
                          priority=1, evidence='; '.join(rec['terms'][:4])))
    for ch in tier2:
        named.append(dict(char=ch, count=0, tier=2, priority=2,
                          evidence='专名音译备用字（DLC 未译专名样例: %s）'
                                   % ', '.join(proper_top[:8])))
    font_json = dict(
        total=len(named),
        chars=named,
        capacity_new_glyphs=346,
        capacity_source='font-engineer 实测（1024×644 方案 B：298 PUA 占位 + 50 未映射空槽 − 2 残墨）',
        statistical_estimate=recommended,
        statistical_estimate_note='按本体语料字频外推出的新增字需求量（尚无具体字形，'
                                  '译者实际用字可能落在本体已有 1,966 真汉字内而低于此数）',
        tier1_note='tier1=由本资料片真实英文关键词/地名/任务代号建议译名中**已确认不在本体字符集**的字',
        tier2_note='tier2=常用音译汉字池中不在本体字符集的字（专名音译可能需要，未确认必然用）',
        overflow_note=('named_conservative=%d ≤ 容量 346，暂不需要扩容量；统计估计 %d 也在容量内，'
                       '但若翻译大量使用生僻专名，需按 tier1→tier2 顺序保留并复核'
                       % (len(named), recommended)),
        generated_by='tools/dlc/dump_text.py chars',
        iso_sha256=dlclib.ISO_SHA256,
    )
    T.write_json(os.path.join(WORK, 'needed_chars_font.json'), font_json)
    T.write_json(os.path.join(SOURCE, 'needed_chars_font.json'), font_json)
    # 预填翻译表（TM 复用部分）供后续人工翻译
    md = dict(row=None)
    trans_rows = []
    for x in results:
        u, m = x['unit'], x['match']
        if not u['text'] or u['keep']:
            continue
        reusable = m and m['match_type'] in ('exact', 'norm', 'fuzzy_high')
        zh = ''
        if reusable and m.get('base_zh'):
            zh = m['base_zh']
            if u['resource'] in ('MIS', 'SFXML', 'SFXML_TITLE'):
                zh = tags_to_newlines_for_xml(zh)
        trans_rows.append(dict(resource=u['resource'], id=u['id'],
                               text_en=T.esc_cell(u['text']),
                               text_zh=T.esc_cell(zh) if zh else '',
                               status=('tm_' + m['match_type']) if reusable else 'todo',
                               tm_source=m['base_id'] if reusable else '',
                               note=u['keep_reason']))
    T.write_csv(os.path.join(WORK, 'translation_worklist.csv'),
                ['resource', 'id', 'text_en', 'text_zh', 'status', 'tm_source', 'note'],
                trans_rows)
    P('\n== 用字清单 ==')
    P('  TM 复用用字 %d 个 / %d 次；全部在本体字符集内: %s'
      % (len(known), sum(known.values()), out['summary']['known_all_in_charset']))
    P('  未覆盖条目保守估算新增中文 %d 字（%d 条）'
      % (est_total, len(unmatched)))
    P('  术语候选新字 %d 个（缺字 %d）: %s'
      % (len(cand), len(missing), ''.join(missing[:60])))
    P('  本体字符集空 PUA 槽: %d' % len(cs.pua_free))
    return out


# ═════════════════════════ 注入约束预测 ═════════════════════════
def enc_zh(text, where):
    """翻译文本 → 引擎字节（中文用本体字符集；ASCII 直通）。"""
    data, issues = T.charset().encode(text, where, strict=False)
    if issues:
        raise ValueError('%s 编码问题: %s' % (where, issues[:4]))
    return data


def plan_lang(data, tx):
    lang = data['lang']
    rows = [dict(r) for r in lang['rows']]
    changed = 0
    for r in rows:
        zh = tx.get(r['id'])
        if zh:
            r['data'] = enc_zh(zh, 'LANG/%s' % r['id'])
            changed += 1
    blob, info = T.build_lang_blob(rows)
    frames, finfo, stored = T.roughly_pack(blob)
    slack = T.entry_slack(data['entries'], T.LANG_IDX)
    return dict(old=dict(real=lang['entry']['real'], stored=lang['entry']['stored'],
                         blob=len(lang['blob'])),
                new=dict(real=len(blob), stored=stored, blob=len(blob),
                         chunks=len(finfo)),
                delta=stored - lang['entry']['stored'], slack=slack,
                changed_entries=changed,
                verdict=('可原地注入（stored 不增）' if stored <= lang['entry']['stored'] + slack
                         else '需 GR.IMG 重排/扩盘'))


def plan_sfxml(data, tx):
    sf = data['sfxml']
    edits = []
    changed = 0
    for t in sf['texts']:
        zh = tx.get(t['id'])
        if zh:
            edits.append((t['span'][0], t['span'][1],
                          enc_zh(tags_to_newlines_for_xml(zh), 'SFXML/' + t['id'])))
            changed += 1
    for t in sf['titles']:
        zh = tx.get(t['id'])
        if zh:
            edits.append((t['span'][0], t['span'][1],
                          enc_zh(zh, 'SFXML_TITLE/' + t['id'])))
            changed += 1
    edits.sort()
    new_blob = T.dlclib.splice(sf['blob'], edits)
    frames, finfo, stored = T.roughly_pack(new_blob)
    slack = T.entry_slack(data['entries'], T.SFXML_IDX)
    return dict(old=dict(real=sf['entry']['real'], stored=sf['entry']['stored'],
                         blob=len(sf['blob'])),
                new=dict(real=len(new_blob), stored=stored, chunks=len(finfo)),
                delta=stored - sf['entry']['stored'], slack=slack,
                changed_entries=changed,
                verdict=('可原地注入（stored 不增）' if stored <= sf['entry']['stored'] + slack
                         else '需 GR.IMG 重排/扩盘'))


def _stored_for_chunk(blob, chunk):
    segs = [blob[i:i + chunk] for i in range(0, len(blob), chunk)]
    frames, info = T.pack_frames(segs)
    return len(frames), len(info)


def plan_mis(data, tx):
    """MIS 注入预测：显示字段都在 sub0（首个 16,384 B 块）内，故对比三种重压方案：
      A) sub0-only  : 只重压第一块（帧仍 16,384）——引擎兼容性最稳；
      B) chunk64k   : 整条按 65,536 B 块重压（大块压缩率更好，可抵消我们 LZO 编码器
                      相对原盘约 2% 的劣势；但 rlen>16,384 的帧需要引擎侧确认）；
      C) single     : 整条压成 1 帧（同上，需确认）。
    预填模拟里未覆盖字段仍是英文（比中文长）⇒ 尺寸是上界，真实全译只会更小。
    """
    out = []
    for m in data['mis']:
        edits, changed = [], 0
        first_rlen = m['chunks'][0]['rlen'] if m['chunks'] else 0
        for f in m['fields']:
            u = 'MIS:%s:%s' % (m['name'], f['field'])
            zh = tx.get(u)
            if zh:
                edits.append((f['span'][0], f['span'][1],
                              enc_zh(tags_to_newlines_for_xml(zh), u)))
                changed += 1
        if not edits:
            continue
        edits.sort()
        new_blob = dlclib.splice(m['blob'], edits)
        if first_rlen and any(b > first_rlen for _a, b, _nb in edits):
            st_sub0 = None
        else:
            new_sub0 = dlclib.splice(m['blob'][:first_rlen], edits)
            c0 = m['chunks'][0]
            frame0, _info0 = T.pack_frames([new_sub0])
            tail = m['packed'][c0['hdr_off'] + 8 + c0['clen']:]
            st_sub0 = len(frame0) + len(tail)
        st64, n64 = _stored_for_chunk(new_blob, 65536)
        st1, n1 = _stored_for_chunk(new_blob, len(new_blob))
        slack = T.entry_slack(data['entries'], m['entry']['idx'])
        budget = m['entry']['stored'] + (slack or 0)
        base = dict(file=m['name'], idx=m['entry']['idx'], changed=changed,
                    old_real=m['entry']['real'], old_stored=m['entry']['stored'],
                    slack=slack, new_real=len(new_blob),
                    delta_sub0=(None if st_sub0 is None else st_sub0 - m['entry']['stored']),
                    delta_chunk64=st64 - m['entry']['stored'],
                    delta_single=st1 - m['entry']['stored'],
                    fits_sub0=(st_sub0 is not None and st_sub0 <= budget),
                    fits_chunk64=(st64 <= budget),
                    fits_single=(st1 <= budget))
        out.append(base)
    return out


def plan_atr_txt(data, tx):
    out = []
    for a in data['atr']:
        f = a['fields'].get('ActorName')
        if not f:
            continue
        u = 'ATR:%s:ActorName' % a['name']
        zh = tx.get(u)
        if not zh:
            continue
        new = T.dlclib.splice(a['blob'], [(f['span'][0], f['span'][1],
                                           enc_zh(zh, u))])
        slack = T.entry_slack(data['entries'], a['entry']['idx'])
        out.append(dict(file=a['name'], idx=a['entry']['idx'],
                        old_real=a['entry']['real'], new_real=len(new),
                        delta=len(new) - a['entry']['real'],
                        verdict=('可原地注入（raw 等长或变短）'
                                 if len(new) <= a['entry']['real'] + (slack or 0)
                                 else '需重排')))
    # TXT
    txt = data['txt']
    edits, changed = [], 0
    for p in txt['pairs']:
        zh = tx.get('TXT:%s' % p['token'])
        if zh:
            edits.append((p['value_span'][0], p['value_span'][1],
                          enc_zh(zh, 'TXT/' + p['token'])))
            changed += 1
    if edits:
        edits.sort()
        new_blob = T.dlclib.splice(txt['blob'], edits)
        frames, finfo, stored = T.roughly_pack(new_blob)
        out.append(dict(file='EN_STRINGS.TXT', idx=T.TXT_IDX, changed=changed,
                        old_real=txt['entry']['real'], old_stored=txt['entry']['stored'],
                        new_real=len(new_blob), new_stored=stored,
                        delta=stored - txt['entry']['stored'],
                        slack=T.entry_slack(data['entries'], T.TXT_IDX),
                        verdict=('可原地注入' if stored <= txt['entry']['stored'] +
                                 (T.entry_slack(data['entries'], T.TXT_IDX) or 0)
                                 else '需重排')))
    return out


def run_plan(args, data, results):
    # 预填：TM 可复用中文（exact/norm/fuzzy_high），其余保留英文
    tx = {}
    for x in results:
        u, m = x['unit'], x['match']
        if not u['text'] or u['keep'] or not m or not m.get('base_zh'):
            continue
        if m['match_type'] not in ('exact', 'norm', 'fuzzy_high'):
            continue
        zh = m['base_zh']
        # 外文专名/日期等含 ASCII 的翻译同样保留
        tx[u['id']] = zh
    P('[plan] 预填 %d 条 TM 中文（其余保留英文，作为长度上界）' % len(tx))
    # 本库 LZO 编码器 vs 原盘压缩器的差距（同数据重压对比）
    gap = []
    ch = data['lang']['chunks']
    frames, _i = T.pack_frames([data['lang']['blob'][i:i + T.CHUNK]
                                for i in range(0, len(data['lang']['blob']), T.CHUNK)])
    gap.append(dict(resource='LANG', original_stored=data['lang']['entry']['stored'],
                    our_stored=len(frames),
                    delta=len(frames) - data['lang']['entry']['stored']))
    sf = data['sfxml']
    frames, _i = T.pack_frames([sf['blob'][i:i + T.CHUNK]
                                for i in range(0, len(sf['blob']), T.CHUNK)])
    gap.append(dict(resource='SFXML', original_stored=sf['entry']['stored'],
                    our_stored=len(frames),
                    delta=len(frames) - sf['entry']['stored']))
    mis_gap = []
    for m in data['mis']:
        c0 = m['chunks'][0]
        comp = dlclib.lzo_compress(m['blob'][:c0['rlen']], level=7, use_m1=True, use_m4=True)
        mis_gap.append(len(comp) - c0['clen'])
    gap.append(dict(resource='MIS-sub0', files=len(mis_gap),
                    original_total=sum(m['chunks'][0]['clen'] for m in data['mis']),
                    our_extra_total=sum(mis_gap),
                    max_extra=max(mis_gap) if mis_gap else 0,
                    min_extra=min(mis_gap) if mis_gap else 0))
    report = dict(
        meta=dict(mode='TM 预填模拟（exact/norm/fuzzy_high 用中文，其余英文原样）',
                  note='中文按本体字符集编码；LANG/SFXML 按 16384 B 分块重压；'
                       'MIS 对比三种方案（sub0-only / 64K 块 / 单帧）；'
                       'slack = 下一条 off - (本条 off+stored)。只预测，不写盘。'),
        compressor_gap=gap,
        lang=plan_lang(data, tx),
        sfxml=plan_sfxml(data, tx),
        mis=plan_mis(data, tx),
        atr_txt=plan_atr_txt(data, tx))
    # MIS 汇总（三种方案分别统计超预算）
    mis_rows = report['mis']

    def over(key):
        return [r['file'] for r in mis_rows if not r[key]]

    report['mis_summary'] = dict(
        files=len(mis_rows),
        min_slack=min([r['slack'] for r in mis_rows if r['slack'] is not None] + [0]),
        max_delta_sub0=max([r['delta_sub0'] for r in mis_rows
                            if r['delta_sub0'] is not None] + [0]),
        max_delta_chunk64=max([r['delta_chunk64'] for r in mis_rows] + [0]),
        max_delta_single=max([r['delta_single'] for r in mis_rows] + [0]),
        over_budget_sub0=over('fits_sub0'),
        over_budget_chunk64=over('fits_chunk64'),
        over_budget_single=over('fits_single'),
        sum_delta_sub0=sum(r['delta_sub0'] for r in mis_rows
                           if r['delta_sub0'] is not None),
        sum_delta_chunk64=sum(r['delta_chunk64'] for r in mis_rows),
        sum_delta_single=sum(r['delta_single'] for r in mis_rows))
    # 判定
    verdicts = {k: (report[k].get('verdict') if isinstance(report[k], dict) else None)
                for k in ('lang', 'sfxml')}
    report['verdicts'] = verdicts
    T.write_json(os.path.join(WORK, 'inject_bounds.json'), report)
    P('\n== 注入约束预测（TM 预填模拟）==')
    P('  LANG : old stored=%d new=%d delta=%+d slack=%d → %s'
      % (report['lang']['old']['stored'], report['lang']['new']['stored'],
         report['lang']['delta'], report['lang']['slack'], report['lang']['verdict']))
    P('  SFXML: old stored=%d new=%d delta=%+d slack=%d → %s'
      % (report['sfxml']['old']['stored'], report['sfxml']['new']['stored'],
         report['sfxml']['delta'], report['sfxml']['slack'],
         report['sfxml']['verdict']))
    P('  LZO 编码器差距: LANG %+d / SFXML %+d / MIS-sub0 合计 %+d B（我们比原盘弱）'
      % (gap[0]['delta'], gap[1]['delta'], gap[2]['our_extra_total']))
    P('  MIS  : %d 个有改动；16K 帧超预算 %d 个（sum Δ=%+d）；64K 块超预算 %d 个（sum Δ=%+d）；'
      '单帧超预算 %d 个（sum Δ=%+d）'
      % (report['mis_summary']['files'], len(report['mis_summary']['over_budget_sub0']),
         report['mis_summary']['sum_delta_sub0'],
         len(report['mis_summary']['over_budget_chunk64']),
         report['mis_summary']['sum_delta_chunk64'],
         len(report['mis_summary']['over_budget_single']),
         report['mis_summary']['sum_delta_single']))
    atr = report['atr_txt']
    P('  ATR/TXT 改动 %d 个条目' % len(atr))
    return report


# ═════════════════════════ 主流程 ═════════════════════════
def cmd_tm(args):
    iso = dlclib.Iso(args.iso)
    try:
        data = load_all(iso)
    finally:
        iso.close()
    ctx = load_tm_context(args)
    results, stat = run_tm(args, data, ctx)
    T.write_json(os.path.join(WORK, 'tm_context.json'),
                 dict(corpus=[dict(base_id=c['base_id'], resource=c['resource'],
                                   en=T.esc_cell(c['en']), zh=T.esc_cell(c['zh']))
                              for c in ctx['corpus']]))
    return data, ctx, results, stat


def cmd_all(args):
    T.ensure_dirs()
    P('════ 1/4 dump ════')
    cmd_dump(args)
    P('\n════ 2/4 TM ════')
    data, ctx, results, stat = cmd_tm(args)
    P('\n════ 3/4 用字清单 ════')
    run_chars(args, data, ctx, results, stat)
    P('\n════ 4/4 注入约束预测 ════')
    run_plan(args, data, results)
    P('\n[all] 完成。产物：assets/text/source/ + work/analysis/text/')


def cmd_audit(args):
    iso = dlclib.Iso(args.iso)
    try:
        data = load_all(iso)
    finally:
        iso.close()
    units = build_units(data)
    st = source_stats(data, units)
    print(json.dumps(st, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser(description='丛林风暴资料片文本抽取/翻译记忆/注入约束分析')
    ap.add_argument('cmd', nargs='?', default='all',
                    choices=['dump', 'tm', 'chars', 'plan', 'all', 'audit'])
    ap.add_argument('--iso', default=T.DEFAULT_ISO)
    ap.add_argument('--base-iso', default=T.DEFAULT_BASE_ISO)
    ap.add_argument('--base-zh-iso', default=T.DEFAULT_BASE_ZH_ISO)
    args = ap.parse_args()
    if args.cmd == 'dump':
        cmd_dump(args)
    elif args.cmd == 'tm':
        cmd_tm(args)
    elif args.cmd == 'audit':
        cmd_audit(args)
    elif args.cmd == 'chars':
        data, ctx, results, stat = cmd_tm(args)
        run_chars(args, data, ctx, results, stat)
    elif args.cmd == 'plan':
        data, ctx, results, stat = cmd_tm(args)
        run_plan(args, data, results)
    else:
        cmd_all(args)


if __name__ == '__main__':
    main()
