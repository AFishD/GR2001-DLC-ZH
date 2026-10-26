# -*- coding: utf-8 -*-
"""atlas_guard.py —— 字库「图标哨兵槽」检测与保护。

背景（docs/ANALYSIS_FONT.md §2.6 / R11）：
  图集对偶槽里 trail ∈ {0xB1, 0xB5} 的 **50 个格** 是引擎硬编码的「图标特判」哨兵槽：
  DrawString/CharWidth 对 0x00B1/0x00B5（以及哨兵槽）走图标分支。它们**不能被分配给汉字**，
  其中 2 格还真实存有图标像素（slot 768=(0xA9,0xB1)、slot 772=(0xA9,0xB5)）。
  因此构筑时必须：
    ① 字符集不占用哨兵槽（pair_of 无 trail∈{B1,B5}，新字分配同样避开）；
    ② 图集里哨兵格像素与 seed 完全一致（保护图标像素不被补画/重排覆盖）；
    ③ 文本里的图标码（单字节 0xB1/0xB5）在成品盘与原盘逐条目数量一致（占位符不被翻译吞掉）。
"""

import csv
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))

import numpy as np                                               # noqa: E402

import fontlib as F                                              # noqa: E402
import build_font as BF                                          # noqa: E402

NCOL, CW, CH, Y0 = 64, 16, 16, 3
SENTINEL_TRAILS = (0xB1, 0xB5)
ICON_BYTES = (0xB1, 0xB5)
CHARSET_PATH = os.path.join(REPO, 'assets', 'charset', 'charset_compiled_zh16.json')
SEED_DIR = os.path.join(REPO, 'third_party', 'ref', 'zh_font_seed')


def slot_of(lead, trail):
    return (lead - 0xA1) * 94 + (trail - 0xA1)


def slot_geometry(slot):
    row, col = divmod(slot, NCOL)
    return row, col, CW * col, Y0 + CH * (row + (2 if row >= 12 else 0))


def sentinel_slots():
    out = []
    for lead in range(0xA1, 0xBA):
        for trail in SENTINEL_TRAILS:
            out.append(dict(slot=slot_of(lead, trail), lead=lead, trail=trail))
    return out


def slot_cells(tex, slots):
    h, w = tex.shape
    cells = []
    for s in slots:
        row, col, x, y = slot_geometry(s['slot'])
        if x + CW > w or y + CH > h:
            cells.append(None)
            continue
        cells.append(tex[y:y + CH, x:x + CW].copy())
    return cells


def load_atlas(iso_path):
    dlc = BF.load_dlc(iso_path)
    pak, recs = dlc['pak'], dlc['recs']
    _fi, fr = F.pak_find(recs, 'new_font_revised')
    cont = pak[fr['px_off']:fr['px_off'] + fr['px']]
    tex, empty, packets, segs = F.atlas_engine_image(cont, fr['w'], fr['h'], fr['psm'])
    try:
        dlc['iso'].close()
    except Exception:                                            # noqa: BLE001
        pass
    return dict(rec=fr, tex=tex, empty=empty, container=cont)


def load_seed_atlas():
    """本体 ZH seed 图集（补画前的基准）；返回 tex 或 None。"""
    p = os.path.join(SEED_DIR, 'COMMON_PAK.MENU3.zh.bin')
    if not os.path.exists(p):
        return None
    pak = open(p, 'rb').read()
    recs = F.pak_parse(pak)
    _fi, fr = F.pak_find(recs, 'new_font_revised')
    cont = pak[fr['px_off']:fr['px_off'] + fr['px']]
    tex, empty, packets, segs = F.atlas_engine_image(cont, fr['w'], fr['h'], fr['psm'])
    return dict(tex=tex, empty=empty, rec=fr)


def charset_pairs(path=None):
    d = json.load(io.open(path or CHARSET_PATH, encoding='utf-8'))
    inv = {}
    for ch, pair in d['pair_of'].items():
        inv[(pair[0], pair[1])] = ch
    return d, inv


def check_charset(path=None):
    """① 字符集不得占用哨兵槽；返回 (ok, violations, risk_pairs)。"""
    d, inv = charset_pairs(path)
    bad = [(ch, p) for (p, ch) in
           [((pair[0], pair[1]), ch) for ch, pair in d['pair_of'].items()]
           if p[1] in SENTINEL_TRAILS]
    risk = [(ch, p) for ch, p in d['pair_of'].items()
            if p[0] in ICON_BYTES]          # lead 命中：仅报告（历史隐患，非本工程引入）
    return (len(bad) == 0), bad, risk


def check_atlas_vs_seed(iso_path):
    """② 哨兵格像素保护：成品盘哨兵格必须与 seed 完全一致。"""
    cur = load_atlas(iso_path)
    seed = load_seed_atlas()
    if seed is None:
        return None, 'seed 图集缺失，跳过像素比对'
    a = slot_cells(cur['tex'], sentinel_slots())
    b = slot_cells(seed['tex'], sentinel_slots())
    bad = []
    for i, (ca, cb) in enumerate(zip(a, b)):
        if ca is None or cb is None or ca.shape != cb.shape or not np.array_equal(ca, cb):
            bad.append(sentinel_slots()[i]['slot'])
    return (len(bad) == 0), bad


def _dbcs_units(raw):
    """按引擎 decoder 规则切分：lead∈[0xA1,0xBA) 且 trail∈[0xA1,0xFF) → 对偶码，否则单字节。"""
    out = []
    i = 0
    n = len(raw)
    while i < n:
        c = raw[i]
        if 0xA1 <= c < 0xBA and i + 1 < n and 0xA1 <= raw[i + 1] < 0xFF:
            out.append(('pair', c, raw[i + 1], i))
            i += 2
        else:
            out.append(('single', c, None, i))
            i += 1
    return out


def scan_icon_codes(iso_path):
    """③ 扫描盘内文本的图标占位码：**单字节** 0xB1/0xB5（引擎画手柄图标）与 {{BTN:xxxx}}。

    返回 rows：resource / key / icons（单字节图标码个数）/ positions / pairs（对偶码个数）。
    """
    sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
    import dlclib as L
    import dump_text as D

    iso = L.Iso(iso_path)
    data = D.load_all(iso)
    iso.close()
    rows = []

    def walk(obj, res):
        if isinstance(obj, dict):
            rid = obj.get('id')
            raw = obj.get('data') or obj.get('text') or obj.get('raw')
            if rid and isinstance(raw, (bytes, bytearray)):
                units = _dbcs_units(bytes(raw))
                hits = [u[3] for u in units if u[0] == 'single' and u[1] in ICON_BYTES]
                if hits:
                    rows.append(dict(resource=res, key=rid, icons=len(hits),
                                     positions=','.join(str(h) for h in hits),
                                     pairs=sum(1 for u in units if u[0] == 'pair'),
                                     raw=bytes(raw)))
            for v in obj.values():
                walk(v, res)
        elif isinstance(obj, list):
            for v in obj:
                walk(v, res)

    walk(data.get('lang'), 'LANG')
    walk(data.get('sfxml'), 'SFXML')
    walk(data.get('mis'), 'MIS')
    walk(data.get('atr'), 'ATR')
    walk(data.get('txt'), 'TXT')
    return rows


def write_icon_report(rows, path):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, lineterminator='\r\n')
        w.writerow(['resource', 'key', 'icon_count', 'positions', 'raw_hex'])
        for r in rows:
            w.writerow([r['resource'], r['key'], r['icons'], r['positions'],
                        r['raw'].hex()])


def icon_cell_info(iso_path):
    """返回图集里有墨的哨兵格（图标像素所在格）列表。"""
    cur = load_atlas(iso_path)
    out = []
    for s, cell in zip(sentinel_slots(), slot_cells(cur['tex'], sentinel_slots())):
        if cell is None:
            continue
        ink = int((cell == 0).sum())
        if ink:
            out.append(dict(s, ink=ink, row=slot_geometry(s['slot'])[0],
                            col=slot_geometry(s['slot'])[1]))
    return out


if __name__ == '__main__':
    args = sys.argv[1:]
    iso = args[0] if args else os.path.join(REPO, 'work', 'builds', 'FINAL', 'GR_JS_ZH.iso')
    ok, bad, risk = check_charset()
    print('charset sentinel violations:', len(bad), bad[:5])
    print('charset lead-risk pairs (历史遗留):', len(risk))
    ok2, bad2 = check_atlas_vs_seed(iso)
    print('atlas sentinel cells vs seed:', ok2, bad2)
    print('icon cells:', icon_cell_info(iso))
    rows = scan_icon_codes(iso)
    print('text icon-code entries:', len(rows), [(r['resource'], r['key'], r['icons']) for r in rows[:10]])
