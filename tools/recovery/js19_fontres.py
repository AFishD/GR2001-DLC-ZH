# -*- coding: utf-8 -*-
r"""js19_fontres.py — 解析 JS19 FONT.RES（7488B 展开态），导出 3 面 × 224 条 FT 记录的
rect 并统计「单字节码 idx → 矩形」与「rect 唯一性/落点」。

输出 work/analysis/js19/js19_ft_records.json
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'font'))
import dlclib as L            # noqa: E402
import fontlib as F           # noqa: E402

JS = os.path.join(REPO, 'work', 'analysis', 'js19')
P_FONT = os.path.join(JS, 'payloads', '00580_FONT.RES.bin')


def load_blob():
    raw = open(P_FONT, 'rb').read()
    blob, frames, used = F.frame_decode(raw)
    return blob, raw, frames, used


def main():
    blob, raw, frames, used = load_blob()
    print('raw=%d blob=%d frames=%s used=%d' % (len(raw), len(blob), frames, used))
    ft = F.ft_parse(blob)
    print('magic=%r nfaces=%d parsed_end=%d tail=%d' % (ft['magic'], ft['nfaces'], ft['parsed_end'], ft['tail_len']))
    for f in ft['faces']:
        print('face %-8r fld=%s nrec=%d at=%d' % (f['name'], f['fld'], f['nrec'], f['at']))
        recs = f['recs']
        nz = [r for r in recs if any(r[2:])]
        print('  非零 rect 记录 %d ; 前 6 条: %s' % (len(nz), recs[:6]))
        # rect 分布
        rects = [(r[2], r[3], r[4], r[5]) for r in recs]
        from collections import Counter
        c = Counter(rects)
        print('  唯一 rect %d; 最常见: %s' % (len(c), c.most_common(6)))
        # v 分布（按 v0 聚类）
        vs = Counter(r[3] for r in recs)
        print('  v0 分布:', sorted(vs.items())[:20])
    json.dump(dict(magic=ft['magic'], nfaces=ft['nfaces'],
                   faces=[dict(name=f['name'], fld=f['fld'], nrec=f['nrec'], recs=f['recs']) for f in ft['faces']],
                   tail_len=ft['tail_len'], tail=ft['tail'].hex()),
              open(os.path.join(JS, 'js19_ft_records.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print('[out] js19_ft_records.json')
    # 单字节高码用到的 idx
    jsl = open(os.path.join(JS, 'lang_alignment.csv'), encoding='utf-8-sig').read().splitlines()[1:]
    import collections
    hi = collections.Counter()
    for line in jsl:
        parts = line.split(',')
        if len(parts) < 6:
            continue
        try:
            b = bytes.fromhex(parts[5])
        except ValueError:
            continue
        i = 0
        while i < len(b):
            v = b[i]
            if 0xA1 <= v < 0xAE and i + 1 < len(b) and 0xA1 <= b[i + 1] < 0xFF:
                i += 2
                continue
            if v >= 0xAE or (0x80 <= v < 0xA1):
                hi[v] += 1
            i += 1
    print('单字节高位/特殊码统计:', hi.most_common(40))
    print('单字节码 idx(=code-0x20) 范围:', min(hi) - 0x20, max(hi) - 0x20, 'distinct', len(hi))


if __name__ == '__main__':
    main()
