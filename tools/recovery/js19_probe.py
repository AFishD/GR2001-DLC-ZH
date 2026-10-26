# -*- coding: utf-8 -*-
r"""js19_probe.py — JS_ZH19 上一版中文构筑还原：探针脚本（框架搭好后固化为正式分析脚本）。

用法:
  python tools/recovery/js19_probe.py langstats     # LANG 字节统计 + 编码假设检验
  python tools/recovery/js19_probe.py atlasprofile   # 图集行/列 ink 剖面
"""
import collections
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'font'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))

import dlclib as L            # noqa: E402
import fontlib as F           # noqa: E402

JS = os.path.join(REPO, 'work', 'analysis', 'js19')
P_PAK = os.path.join(JS, 'payloads', '00009_COMMON.PAK.bin')
P_FONT = os.path.join(JS, 'payloads', '00580_FONT.RES.bin')
P_LANG = os.path.join(JS, 'payloads', '00576_EN_STRINGS.RES.bin')


def load_lang_blob():
    raw = open(P_LANG, 'rb').read()
    subs = L.lzo_subs(raw)
    blob = b''.join(s[0] for s in subs)
    return blob, raw, subs


def lang_entries():
    blob, raw, subs = load_lang_blob()
    ents, used = L.parse_lang(blob)
    return ents, blob, used


def cmd_langstats():
    ents, blob, used = lang_entries()
    print('blob=%d used_end=%d ngroups_entries=%d' % (len(blob), used, len(ents)))
    print('groups:', len(set(e.g for e in ents)))
    cjk = 0
    hi = collections.Counter()
    pairs = collections.Counter()
    single_hi = collections.Counter()
    for e in ents:
        d = e.data
        if any(b >= 0x80 for b in d):
            cjk += 1
        for b in d:
            if b >= 0x80:
                hi[b] += 1
    print('entries with high bytes: %d / %d' % (cjk, len(ents)))
    print('high byte histogram (top 40):', hi.most_common(40))
    print('lead range:', min(hi), max(hi))
    # naive pairing: scan bytes left->right; <0x80 = ascii single; >=0x80 = take next byte
    for e in ents[:8]:
        print('E%02d.%03d len=%3d %r' % (e.g, e.i, e.length, e.data[:60]))
    # show a long one
    longs = sorted(ents, key=lambda x: -len(x.data))
    for e in longs[:5]:
        print('LONG %d.%d len=%d %r' % (e.g, e.i, e.length, e.data[:100]))


def cmd_atlasprofile():
    pak = open(P_PAK, 'rb').read()
    recs = L.parse_pak_records(pak)
    r = [x for x in recs if x['name'] == 'new_font_revised'][0]
    cont = pak[r['px_off']:r['px_off'] + r['px']]
    tex, empty, pk, segs = F.atlas_engine_image(cont, 512, 512, 19)
    ink = tex == 0
    print('empty=%d ink=%d' % (empty, int(ink.sum())))
    rows = ink.sum(1)
    cols = ink.sum(0)
    print('row ink profile (y: count) nonzero ranges:')
    nz = np.nonzero(rows)[0]
    runs = []
    if len(nz):
        s = p = nz[0]
        for y in nz[1:]:
            if y == p + 1:
                p = y
            else:
                runs.append((s, p))
                s = p = y
        runs.append((s, p))
    print('row runs:', runs)
    print('col runs:', end=' ')
    nzc = np.nonzero(cols)[0]
    cruns = []
    if len(nzc):
        s = p = nzc[0]
        for x in nzc[1:]:
            if x == p + 1:
                p = x
            else:
                cruns.append((s, p))
                s = p = x
        cruns.append((s, p))
    print(cruns)
    # per candidate cell grid: 62 cols x 8 wide, Y0=2, 16 high, skip rows>=12 add 3
    print('--- geometry check (NCOL=62, CW=8, CH=16, Y0=2, SKIP_ROW=12, +3) ---')
    for row in range(0, 22):
        y = 2 + 16 * (row + (3 if row >= 12 else 0))
        inkc = []
        for col in range(62):
            x = 8 * col + 2
            n = int(ink[y:y + 16, x:x + 8].sum())
            inkc.append(n)
        print('row %2d y=%3d  ink=%4d  nonempty=%2d  maxcell=%3d' % (row, y, sum(inkc), sum(1 for v in inkc if v), max(inkc)))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'langstats'
    globals()['cmd_' + cmd]()


if __name__ == '__main__':
    main()
