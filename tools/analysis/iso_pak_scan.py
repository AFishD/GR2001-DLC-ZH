# -*- coding: utf-8 -*-
r"""iso_pak_scan.py —— 40 个 *.PAK 纹理图集包的记录级结构分析（《幽灵行动：丛林风暴》PS2）。

全只读。输出：
  · 每个 PAK 的记录清单：序号/记录头偏移/类型/名字/psm/w/h/两段(CLUT、像素)盘上长度
  · 记录类型判读：ty=0 原样 GS 纹理段；ty=2 压缩纹理段（每段 {u32 未压缩长度}+压缩流）；
    ty=3 内嵌 JPEG（{u32 jpeg_size}+JPEG 字节流）；0x63 = 记录区终结符
  · 逐 PAK 自检：记录刚好铺满到终结符、无越界、无重叠；异常单列
  · 与本体（GR.IMG / MENU.IMG）同名 PAK 的记录级对比：继承记录 / 新增记录 / 几何变化
  · 与本体中文成品盘的 COMMON.PAK（字库图集）对比（供字库工程参考）

用法：
  python tools/analysis/iso_pak_scan.py                 # 全量 + 写 work/analysis/iso/pak_records.json
  python tools/analysis/iso_pak_scan.py --summary       # 只打印每 PAK 记录数/类型统计
  python tools/analysis/iso_pak_scan.py --no-base       # 跳过与本体对比
  python tools/analysis/iso_pak_scan.py --help

注意：ty=2 段的压缩算法**未识别**（已排除 LZO1X / zlib/deflate / LZ4 / LZF / LZSS-8bit-flag
      / PackBits 等候选，见 docs/ANALYSIS_ISO.md §PAK）；汉化不需要重压这些段
      （字库图集所在 COMMON.PAK 是 ty=0 原样段）。
"""
import argparse
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
import dlclib  # noqa: E402

BASE_ISO = dlclib.DEFAULT_BASE_ISO
BASE_ZH_ISO = dlclib.DEFAULT_BASE_ZH_ISO
TERM = 0x63


def P(*a):
    print(' '.join(str(x) for x in a), flush=True)


def parse_pak(blob):
    """解析 PAK。返回 (records, term_off, anomalies)。宽容：出错处停止并记录。"""
    recs, anoms = [], []
    pos, n = 0, len(blob)
    guard = 0
    while pos + 8 <= n and guard < 4096:
        guard += 1
        ty, nl = struct.unpack_from('<II', blob, pos)
        if ty == TERM:
            return recs, pos, anoms
        if nl < 2 or nl > 128 or pos + 8 + nl > n:
            anoms.append(dict(pos=pos, reason='bad name len nl=%d' % nl))
            return recs, pos, anoms
        name = blob[pos + 8:pos + 8 + nl].rstrip(b'\x00').decode('latin-1', 'replace')
        q = pos + 8 + nl
        if ty == 3:
            # JPEG 记录：{u32 jpeg_size}{jpeg}
            if q + 4 > n:
                anoms.append(dict(pos=pos, reason='jpeg size OOB'))
                return recs, pos, anoms
            jsz = struct.unpack_from('<I', blob, q)[0]
            jend = q + 4 + jsz
            if jend > n or blob[q + 4:q + 7] != b'\xff\xd8\xff':
                anoms.append(dict(pos=pos, name=name, reason='jpeg 头/长度不符 jsz=%d' % jsz))
                return recs, pos, anoms
            recs.append(dict(i=len(recs), pos=pos, ty=ty, name=name, kind='jpeg',
                             psm=None, w=None, h=None, clut_len=None, px_len=None,
                             jpeg_len=jsz, total=jend - pos))
            pos = jend
            continue
        if ty not in (0, 1, 2):
            anoms.append(dict(pos=pos, ty=ty, name=name, reason='未知记录类型'))
            return recs, pos, anoms
        if q + 16 > n:
            anoms.append(dict(pos=pos, name=name, reason='纹理头越界'))
            return recs, pos, anoms
        psm, w, h, s1 = struct.unpack_from('<4I', blob, q)
        s1_off = q + 16
        if psm == 0:
            total = 8 + nl + 16 + s1
            if s1_off + s1 > n:
                anoms.append(dict(pos=pos, name=name, reason='段1越界'))
                return recs, pos, anoms
            recs.append(dict(i=len(recs), pos=pos, ty=ty, name=name, kind='tex',
                             psm=psm, w=w, h=h, clut_len=s1, px_len=None,
                             clut_off=s1_off, px_off=None, total=total))
            pos += total
            continue
        if s1_off + s1 + 4 > n:
            anoms.append(dict(pos=pos, name=name, reason='段1/段2头越界'))
            return recs, pos, anoms
        s2 = struct.unpack_from('<I', blob, s1_off + s1)[0]
        px_off = s1_off + s1 + 4
        total = 8 + nl + 16 + s1 + 4 + s2
        if px_off + s2 > n:
            anoms.append(dict(pos=pos, name=name, reason='段2越界'))
            return recs, pos, anoms
        recs.append(dict(i=len(recs), pos=pos, ty=ty, name=name, kind='tex',
                         psm=psm, w=w, h=h, clut_len=s1, px_len=s2,
                         clut_off=s1_off, px_off=px_off, total=total))
        pos += total
    if pos + 8 <= n:
        anoms.append(dict(pos=pos, reason='未找到 0x63 终结符'))
    return recs, pos, anoms


def section_usize(blob, off, size):
    if off is None or not size:
        return None
    return struct.unpack_from('<I', blob, off)[0]


def describe_pak(name, recs, term, blob_len, anoms):
    kinds = {}
    for r in recs:
        k = r['kind'] + ('/ty%d' % r['ty'])
        kinds[k] = kinds.get(k, 0) + 1
    d = dict(name=name, real=blob_len, records=len(recs), kinds=kinds,
             term_off=term, covered=term + 4 if term + 4 <= blob_len else None,
             tail_bytes=blob_len - (term + 4) if term + 4 <= blob_len else None,
             anomalies=anoms, recs=recs)
    return d


def find_pak_in(iso, lba, names):
    """在指定 IMG 容器里按名字找 PAK 条目。"""
    try:
        ents = dlclib.img_entries(iso, lba)
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for e in ents:
        if e['name'].upper() in names:
            out[e['name'].upper()] = e
    return out


def base_pak_summary(iso_path, lba_list):
    if not os.path.isfile(iso_path):
        return None
    iso = dlclib.Iso(iso_path)
    out = {}
    for lba, tag in lba_list:
        try:
            ents = dlclib.img_entries(iso, lba)
        except Exception:  # noqa: BLE001
            continue
        for e in ents:
            if not e['name'].upper().endswith('.PAK'):
                continue
            try:
                blob = dlclib.entry_payload(iso, e)['blob']
                recs, term, anoms = parse_pak(blob)
                d = describe_pak(e['name'], recs, term, len(blob), anoms)
                d['container'] = tag
                d['stored'] = e['stored']
                d['real'] = e['real']
                out.setdefault(e['name'].upper(), []).append(d)
            except Exception as ex:  # noqa: BLE001
                out.setdefault(e['name'].upper(), []).append(dict(error=str(ex)))
    iso.close()
    return out


def main():
    ap = argparse.ArgumentParser(description='40 个 *.PAK 的记录级结构分析（只读）')
    ap.add_argument('--iso', default=dlclib.DEFAULT_ISO)
    ap.add_argument('--base-iso', default=BASE_ISO, help='本体英文盘（对比用；不存在则跳过）')
    ap.add_argument('--base-zh-iso', default=BASE_ZH_ISO, help='本体中文成品盘（COMMON.PAK 对比）')
    ap.add_argument('--json', default=os.path.join(REPO, 'work', 'analysis', 'iso', 'pak_records.json'))
    ap.add_argument('--summary', action='store_true', help='只打印汇总表')
    ap.add_argument('--no-base', action='store_true', help='跳过与本体对比')
    args = ap.parse_args()

    iso = dlclib.Iso(args.iso)
    ents = dlclib.img_entries(iso)
    paks = [e for e in ents if e['name'].upper().endswith('.PAK')]
    P('[dlc] %d 个 PAK 条目' % len(paks))
    out = dict(schema='pak_records/1', generated_by='tools/analysis/iso_pak_scan.py',
               source=os.path.basename(iso.path), paks=[], compare={},
               notes=dict(
                   ty0='原样 GS 纹理段（CLUT 段 = 16B GIF tag + 调色板；像素段 = 16B GIF tag + 像素）',
                   ty2='压缩纹理段：每段 = {u32 未压缩长度}+压缩流（压缩算法未识别）',
                   ty3='内嵌 JPEG：{u32 jpeg_size}+JPEG(SOI…EOI)，后缀含 EXIF 缩略图',
                   term='0x63（u32）= 记录区终结符，其后无数据'))
    P('\n%-28s %6s %5s %6s %8s %8s  %s' %
      ('PAK', 'ty0', 'ty2', 'jpeg', 'stored', 'covered', 'rec 名字'))
    for e in paks:
        blob = dlclib.entry_payload(iso, e)['blob']
        recs, term, anoms = parse_pak(blob)
        d = describe_pak(e['name'], recs, term, len(blob), anoms)
        d['stored'] = e['stored']
        d['real'] = e['real']
        out['paks'].append(d)
        ty0 = sum(1 for r in recs if r['ty'] == 0)
        ty2 = sum(1 for r in recs if r['ty'] == 2)
        jp = sum(1 for r in recs if r['ty'] == 3)
        names = ','.join(r['name'] for r in recs[:6]) + ('…' if len(recs) > 6 else '')
        P('%-28s %6d %5d %6d %8d %8d  %s%s'
          % (e['name'], ty0, ty2, jp, e['stored'], term,
             names, '  !!' if anoms else ''))
        if anoms and not args.summary:
            for a in anoms[:3]:
                P('    anomaly:', a)
    # 自检
    bad = [x for x in out['paks'] if x['anomalies']]
    P('\n自检：%d/%d 个 PAK 记录区无异常（记录铺满到 0x63 终结符）'
      % (len(out['paks']) - len(bad), len(out['paks'])))

    # 关键记录
    P('\n=== 关键记录（字库/菜单/简报）===')
    want = {'COMMON.PAK': ['new_font_revised'], 'MENU.PAK': None, 'ACTION.PAK': None,
            'LOADING.PAK': None}
    for x in out['paks']:
        up = x['name'].upper()
        if up not in want:
            continue
        if not args.summary:
            P('  %s (%d 条)' % (x['name'], x['records']))
            for r in x['recs']:
                P('    %-28s ty=%d %s %sx%s clut=%-6s px=%-8s %s'
                  % (r['name'], r['ty'],
                     'psm=%-2s' % r['psm'] if r['psm'] is not None else 'jpeg',
                     r['w'], r['h'], r['clut_len'], r['px_len'],
                     'jpeg=%d' % r['jpeg_len'] if r['kind'] == 'jpeg' else ''))

    # 与本体对比
    if not args.no_base:
        P('\n=== 与本体（GR.IMG / MENU.IMG）同名 PAK 对比 ===')
        base = base_pak_summary(args.base_iso, [(19175, 'BASE_GR'), (776286, 'BASE_MENU')])
        if base is None:
            P('  本体盘不存在，跳过')
        else:
            out['compare']['base'] = {}
            for x in out['paks']:
                up = x['name'].upper()
                if up not in base:
                    out['compare']['base'][up] = dict(present=False)
                    continue
                lst = base[up]
                entry = dict(present=True, copies=[])
                for bd in lst:
                    dnames = set(r['name'] for r in x['recs'])
                    bnames = set(r['name'] for r in bd.get('recs', []))
                    entry['copies'].append(dict(
                        container=bd.get('container'), real=bd.get('real'),
                        records=bd.get('records'), kinds=bd.get('kinds'),
                        inherited=sorted(dnames & bnames),
                        new_in_dlc=sorted(dnames - bnames),
                        only_in_base=sorted(bnames - dnames)))
                out['compare']['base'][up] = entry
                b0 = entry['copies'][0]
                P('  %-24s 本体 %d 份; 记录 %s→%s; 继承 %d, 新增 %d, 本体独有 %d'
                  % (x['name'], len(entry['copies']),
                     [c['records'] for c in entry['copies']], x['records'],
                     len(b0['inherited']), len(b0['new_in_dlc']), len(b0['only_in_base'])))
                if b0['new_in_dlc'] or b0['only_in_base']:
                    P('     新增: %s' % b0['new_in_dlc'][:12])
                    P('     本体独有: %s' % b0['only_in_base'][:12])
        # 本体中文成品盘 COMMON.PAK（字库图集参照）
        if os.path.isfile(args.base_zh_iso):
            zh = base_pak_summary(args.base_zh_iso, [(19175, 'ZH_GR'), (776286, 'ZH_MENU')])
            if zh and 'COMMON.PAK' in zh:
                out['compare']['base_zh_common'] = zh['COMMON.PAK']
                P('\n  本体中文成品盘 COMMON.PAK:')
                for bd in zh['COMMON.PAK']:
                    P('    %s records=%s kinds=%s' % (bd.get('container'), bd.get('records'), bd.get('kinds')))
                    for r in bd.get('recs', []):
                        if r['name'] in ('new_font_revised', 'pda_counterparts'):
                            P('      %-24s psm=%-2s %sx%s clut=%s px=%s'
                              % (r['name'], r['psm'], r['w'], r['h'], r['clut_len'], r['px_len']))
            # 本体英文 COMMON.PAK
            if base and 'COMMON.PAK' in base:
                P('\n  本体英文盘 COMMON.PAK:')
                for bd in base['COMMON.PAK']:
                    P('    %s records=%s' % (bd.get('container'), bd.get('records')))
                    for r in bd.get('recs', []):
                        if r['name'] == 'new_font_revised':
                            P('      %-24s psm=%-2s %sx%s clut=%s px=%s'
                              % (r['name'], r['psm'], r['w'], r['h'], r['clut_len'], r['px_len']))

    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    P('\n[out] %s (%.1f KB)' % (args.json, os.path.getsize(args.json) / 1024))
    iso.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
