# -*- coding: utf-8 -*-
r"""js19_final_map.py — 组装 JS19 完整字符映射（pair→char、single→char）并做自检。

映射来源（全部有据）：
  pair   : (lead-0xA1)*94+(trail-0xA1)=slot → 图集网格格 row=slot//62,col=slot%62 →
           x=2+8*col, y=2+16*(row+3*[row>=12]) → OCR（js19_atlas_ocr.json）
  single : code c>=0xAE（或 0x80<=c<0xA1）→ FONT.RES FT 记录 idx=c-0x20 →
           rect (u0,v0,u1,v1)；u0/8=格列（该带 u0 漏了 +2），v0 为格 y →
           同图集格 OCR 字符（AF..B9 等新码用此法）
           例外 0xAE/0xE7/0xF1 = ASCII 带 Latin 字形（cp1252 ®/ç/ñ），单独核对
  自检   : 未改动条目（693 条）用此映射解码必须与英文原文逐字节等价（ASCII/控制码）。
输出 work/analysis/js19/js19_charset.json
"""
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'font'))
import dlclib as L            # noqa: E402

JS = os.path.join(REPO, 'work', 'analysis', 'js19')
P_LANG = os.path.join(JS, 'payloads', '00576_EN_STRINGS.RES.bin')
P_OCR = os.path.join(JS, 'js19_atlas_ocr.json')
P_FT = os.path.join(JS, 'js19_ft_records.json')
P_EN = os.path.join(JS, 'en_lang.json')
P_SINGLE = os.path.join(JS, 'js19_single_map.json')

NCOL = 62
PAIR_CAP = (0xAE - 0xA1) * 94          # 1222
X0, Y0, CW, CH = 2, 2, 8, 16
SKIP_ROW, SKIP_ROWS = 12, 3
LATIN_SPECIAL = {0xAE: '®', 0xE7: 'ç', 0xF1: 'ñ'}   # 待上下文核对
# OCR 低置信/歧义、经上下文人工判定的 slot 覆写（见 docs/ANALYSIS_JS19.md §3.3）
SLOT_OVERRIDE = {161: ('®', '上下文判定：27 条均为 PlayStation®2，OCR 最佳候选 "*" 不可用')}


def lang_entries():
    raw = open(P_LANG, 'rb').read()
    blob = b''.join(s[0] for s in L.lzo_subs(raw))
    ents, used = L.parse_lang(blob)
    return ents


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


def slot_of(lead, trail):
    return (lead - 0xA1) * 94 + (trail - 0xA1)


def cell_of_slot(slot):
    row, col = slot // NCOL, slot % NCOL
    y = Y0 + CH * (row + (SKIP_ROWS if row >= SKIP_ROW else 0))
    x = X0 + CW * col
    return row, col, x, y


def main():
    ocr = json.load(open(P_OCR, encoding='utf-8'))
    slotinfo = {c['slot']: c for c in ocr['cells']}
    ft = json.load(open(P_FT, encoding='utf-8'))
    large = [f for f in ft['faces'] if f['name'] == 'large'][0]['recs']
    single_ocr = json.load(open(P_SINGLE, encoding='utf-8'))
    ents = lang_entries()
    en = json.load(open(P_EN, encoding='utf-8'))
    enkey = {(x['g'], x['i']): x for x in en}

    # ---- pair 映射（只导出实际用到的 slot）----
    used_slots = Counter()
    used_singles = Counter()
    for e in ents:
        for kind, c in split_codes(e.data):
            if kind == 'pair':
                used_slots[slot_of(*c)] += 1
            else:
                used_singles[c] += 1
    pair_map = {}
    conf_stat = Counter()
    bad_used = []
    for slot in sorted(used_slots):
        c = slotinfo.get(slot)
        if not c or not c.get('char'):
            bad_used.append((slot, 'blank'))
            continue
        key = '%02X%02X' % (0xA1 + slot // 94, 0xA1 + slot % 94)
        if slot in SLOT_OVERRIDE:
            ch, why = SLOT_OVERRIDE[slot]
            pair_map[key] = dict(char=ch, slot=slot, dist=c.get('dist'),
                                 conf='override', note=why,
                                 count=used_slots[slot],
                                 row=c['row'], col=c['col'], x=c['x'], y=c['y'])
            conf_stat['override'] += 1
            continue
        pair_map[key] = dict(char=c['char'], slot=slot, dist=c.get('dist'),
                             conf=c.get('confidence'), count=used_slots[slot],
                             row=c['row'], col=c['col'], x=c['x'], y=c['y'])
        conf_stat[c.get('confidence')] += 1
    # ---- single 映射 ----
    single_map = {}
    for code in sorted(used_singles):
        if code < 0xA1:
            single_map['%02X' % code] = dict(char=chr(code), slot=None, rect=None,
                                             conf='ascii', count=used_singles[code],
                                             source='ascii-literal')
            continue
        if code < 0xAE:
            # 0xA1..0xAD 作为单字节出现 = 英文未译文本里的 Latin-1（实测仅 0xA9='©' 一次）
            try:
                ch = bytes([code]).decode('cp1252')
            except UnicodeDecodeError:
                ch = None
            single_map['%02X' % code] = dict(char=ch, slot=None, rect=None,
                                             conf='latin1-passthrough', count=used_singles[code],
                                             source='english-passthrough')
            continue
        if True:
            idx = code - 0x20
            b0, adv, u0, v0, u1, v1 = large[idx]
            w, h = u1 - u0, v1 - v0
            if (w, h) == (8, 16):
                # cell = u0/8 (band u0 漏 +2) ; row by v0
                col = u0 // 8
                # 反推 row：v0 = 2 + 16*(row + 3*[row>=12])
                row = None
                for r in range(0, 40):
                    yy = Y0 + CH * (r + (SKIP_ROWS if r >= SKIP_ROW else 0))
                    if yy == v0:
                        row = r
                        break
                slot = row * NCOL + col if row is not None else None
                c2 = slotinfo.get(slot) if slot is not None else None
                if c2 and c2.get('char'):
                    single_map['%02X' % code] = dict(char=c2['char'], slot=slot,
                                                     rect=[u0, v0, u1, v1], dist=c2.get('dist'),
                                                     conf=c2.get('confidence'),
                                                     count=used_singles[code],
                                                     adv=adv, source='grid-cell')
                else:
                    single_map['%02X' % code] = dict(char=None, slot=slot,
                                                     rect=[u0, v0, u1, v1],
                                                     conf='unresolved', count=used_singles[code])
            else:
                single_map['%02X' % code] = dict(char=LATIN_SPECIAL.get(code), slot=None,
                                                 rect=[u0, v0, u1, v1], conf='latin-special',
                                                 count=used_singles[code], adv=adv,
                                                 source='ascii-band',
                                                 ocr=single_ocr.get(str(code), {}).get('char'))
        else:
            # 0x80..0xA0：ASCII 带（本体口径 code-0x20）；JS19 文本实测未使用
            single_map['%02X' % code] = dict(char=None, conf='unexpected', count=used_singles[code])

    charset = dict(
        geometry=dict(atlas='512x512 PSMT8 (psm=19)', ink_val=0, empty_val=15,
                      ncol=NCOL, cell_w=CW, cell_h=CH, x0=X0, y0=Y0,
                      skip_row=SKIP_ROW, skip_rows=SKIP_ROWS, pair_cap=PAIR_CAP,
                      slot_formula='(lead-0xA1)*94+(trail-0xA1)',
                      row='slot//62', col='slot%62',
                      x='2+8*col', y='2+16*(row+3*[row>=12])'),
        pair_gate=dict(lead_range=[0xA1, 0xAE], trail_range=[0xA1, 0xFF]),
        decoder='byte<0xA1 single; 0xA1<=byte<0xAE & next in [0xA1,0xFF) pair(2B); else single',
        single_rule='idx = code-0x20 → FONT.RES FT 记录(large) → rect → 图集格',
        pair=pair_map,
        single=single_map,
        stats=dict(used_pairs=len(used_slots), used_singles=len(used_singles),
                   pair_ocr_conf=dict(conf_stat), pair_unresolved=len(bad_used)),
    )
    # ---- 自检：未改动条目解码必须 == 英文 ----
    def decode(data):
        out = []
        for kind, c in split_codes(data):
            if kind == 'pair':
                k = '%02X%02X' % c
                v = pair_map.get(k)
                out.append(v['char'] if v else '\u25a1')
            else:
                if c < 0xA1:
                    out.append(chr(c))
                else:
                    v = single_map.get('%02X' % c)
                    out.append(v['char'] if (v and v.get('char')) else ('{%02X}' % c))
        return ''.join(out)
    ok = bad = 0
    problems = []
    for e in ents:
        ref = enkey[(e.g, e.i)]
        if ref['raw'] != e.data.hex():
            continue
        # 未改动 = 英文原样；按 cp1252 解英文，比较
        s = decode(e.data)
        en_s = ''.join(chr(b) if b < 0x80 else bytes([b]).decode('cp1252', 'replace') for b in bytes.fromhex(ref['raw']))
        if s == en_s:
            ok += 1
        else:
            bad += 1
            if len(problems) < 10:
                problems.append((e.g, e.i, en_s[:60], s[:60]))
    print('自检(未改动条目 %d): 完全一致 %d, 不一致 %d' % (ok + bad, ok, bad))
    for p in problems:
        print('  %d.%d\n    EN:%r\n    JS:%r' % p)
    print('pair 置信度:', dict(conf_stat))
    print('pair 未解析:', bad_used[:10])
    print('single 解析:', {k: (v['char'] if isinstance(v, dict) else v) for k, v in single_map.items()})
    json.dump(charset, open(os.path.join(JS, 'js19_charset.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('[out] js19_charset.json')


if __name__ == '__main__':
    main()
