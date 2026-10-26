# -*- coding: utf-8 -*-
r"""iso_base_compare.py —— 资料片 vs 本体（Ghost Recon 2001）资源对比。

全只读。输出：
  · 两份盘 ISO 层结构对比（root 文件清单 / 容器 LBA / 大小 / 条目数）
  · 资源名集合对比：DLC 继承自本体（GR.IMG/MENU.IMG） / 资料片新增 / 本体独有
  · 同名资源的 stored/real/载荷 sha256 对比：内容未变 vs 已改（文字/字库/新增内容）
  · 文本资源量对比：EN_STRINGS.RES(LANG) 组/条/字节、EN_SPECIAL_FEATURE.XML <text>、
    *.MIS / *.ATR / *.GTF / *.XML 数量
  · 产出 work/analysis/iso/base_compare.json 与三份名单 txt

用法：
  python tools/analysis/iso_base_compare.py
  python tools/analysis/iso_base_compare.py --dlc-iso <path> --base-iso <path>
  python tools/analysis/iso_base_compare.py --no-payload-sha   # 跳过逐条载荷 sha256（快）
  python tools/analysis/iso_base_compare.py --help
"""
import argparse
import hashlib
import json
import os
import struct
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
import dlclib  # noqa: E402

BASE_GR_LBA = 19175
BASE_MENU_LBA = 776286


def P(*a):
    print(' '.join(str(x) for x in a), flush=True)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def expand_frames(packed):
    """与 iso_img_scan 相同的宽容帧展开（clen==rlen 视为原样块）。"""
    blob = bytearray()
    p, n = 0, len(packed)
    while p + 8 <= n:
        L, S = struct.unpack_from('<II', packed, p)
        if L == S and 0 < L and p + 8 + L <= n:
            data = packed[p + 8:p + 8 + L]
        elif 0 < L < S and p + 8 + L <= n:
            try:
                data, err, _ = dlclib.lzo1x_decompress(packed[p + 8:p + 8 + L], out_size=S)
            except Exception:  # noqa: BLE001
                break
            if err is not None or len(data) != S:
                break
        else:
            break
        blob += data
        p += 8 + L
    return bytes(blob)


def payload(iso, e):
    packed = iso.read(e['iso_off'], e['stored'])
    if e['stored'] == e['real']:
        return packed
    return expand_frames(packed)


def norm_payload(iso, e, with_sha=True):
    packed = iso.read(e['iso_off'], e['stored'])
    h = sha(packed) if with_sha else None
    return packed, h


def ext_of(name):
    return name.rsplit('.', 1)[-1].upper() if '.' in name else '(NONE)'


def iso_root(iso):
    return {e['name'].split(';')[0].upper(): e for e in iso.root_entries()}


def main():
    ap = argparse.ArgumentParser(description='资料片 vs 本体资源对比（只读）')
    ap.add_argument('--dlc-iso', default=dlclib.DEFAULT_ISO)
    ap.add_argument('--base-iso', default=dlclib.BASE_ISO if hasattr(dlclib, 'BASE_ISO')
                    else dlclib.DEFAULT_BASE_ISO)
    ap.add_argument('--out-dir', default=os.path.join(REPO, 'work', 'analysis', 'iso'))
    ap.add_argument('--json', default=os.path.join(REPO, 'work', 'analysis', 'iso', 'base_compare.json'))
    ap.add_argument('--no-payload-sha', action='store_true')
    args = ap.parse_args()
    with_sha = not args.no_payload_sha

    # ---------- 资料片 ----------
    dlc = dlclib.Iso(args.dlc_iso)
    dlc_root = iso_root(dlc)
    dlc_ents = dlclib.img_entries(dlc)
    dlc_by_name = {}
    for e in dlc_ents:
        dlc_by_name.setdefault(e['name'].upper(), []).append(e)

    # ---------- 本体 ----------
    base = dlclib.Iso(args.base_iso)
    base_root = iso_root(base)
    base_ents = {}
    for tag, lba in (('GR', BASE_GR_LBA), ('MENU', BASE_MENU_LBA)):
        base_ents[tag] = dlclib.img_entries(base, lba)
    base_by_name = {}
    for tag in ('GR', 'MENU'):
        for e in base_ents[tag]:
            base_by_name.setdefault(e['name'].upper(), []).append((tag, e))

    out = dict(schema='base_compare/1', generated_by='tools/analysis/iso_base_compare.py',
               dlc=dict(iso=os.path.basename(dlc.path), bytes=dlc.size,
                        root={k: dict(lba=v['lba'], size=v['size'], is_dir=v['is_dir'])
                              for k, v in dlc_root.items()},
                        img=dict(lba=dlclib.GR_LBA, entries=len(dlc_ents),
                                 bytes=dlc_root['GR.IMG']['size'])),
               base=dict(iso=os.path.basename(base.path), bytes=base.size,
                         root={k: dict(lba=v['lba'], size=v['size'], is_dir=v['is_dir'])
                               for k, v in base_root.items()},
                         img=dict(gr_lba=BASE_GR_LBA, gr_entries=len(base_ents['GR']),
                                  menu_lba=BASE_MENU_LBA, menu_entries=len(base_ents['MENU']))),
               compare={})

    P('[dlc ] %s  %d B  GR.IMG %d 条' % (os.path.basename(dlc.path), dlc.size, len(dlc_ents)))
    P('[base] %s  %d B  GR.IMG %d 条 / MENU.IMG %d 条'
      % (os.path.basename(base.path), base.size, len(base_ents['GR']), len(base_ents['MENU'])))
    P('\n本体 root 文件: %s' % sorted(base_root.keys()))
    P('资料片 root 文件: %s' % sorted(dlc_root.keys()))

    # ---------- 名字集合 ----------
    base_names = set(base_by_name)
    dlc_names = set(dlc_by_name)
    inherited = sorted(dlc_names & base_names)
    new_dlc = sorted(dlc_names - base_names)
    base_only = sorted(base_names - dlc_names)
    out['compare']['sets'] = dict(base_names=len(base_names), dlc_names=len(dlc_names),
                                  inherited=len(inherited), new_in_dlc=len(new_dlc),
                                  base_only=len(base_only))
    P('\n=== 1) 资源名集合 ===')
    P('  本体(GR+MENU 去重) %d 名；资料片 %d 名；继承 %d；资料片新增 %d；本体独有 %d'
      % (len(base_names), len(dlc_names), len(inherited), len(new_dlc), len(base_only)))

    # 按容器细分的继承
    inh_gr = sorted(n for n in dlc_names if any(t == 'GR' for t, _ in base_by_name.get(n, [])))
    inh_menu = sorted(n for n in dlc_names if any(t == 'MENU' for t, _ in base_by_name.get(n, [])))
    out['compare']['inherited_by_container'] = dict(inherited_gr=len(inh_gr),
                                                    inherited_menu=len(inh_menu))

    def ext_hist(names):
        return dict(sorted(Counter(ext_of(n) for n in names).items(), key=lambda kv: -kv[1]))

    out['compare']['ext_hist'] = dict(inherited=ext_hist(inherited),
                                      new_in_dlc=ext_hist(new_dlc),
                                      base_only=ext_hist(base_only))
    P('\n  继承资源/扩展名:'); P('   ', out['compare']['ext_hist']['inherited'])
    P('  新增资源/扩展名:'); P('   ', ext_hist(new_dlc))
    P('  本体独有/扩展名:'); P('   ', ext_hist(base_only))

    # ---------- 同名资源内容对比 ----------
    P('\n=== 2) 同名资源内容对比（载荷 sha256）===')
    changed, same, only_base_single = [], [], []
    sha_cache = {}
    for n in inherited:
        d = dlc_by_name[n][0]
        packed_d, pace = (None, None)
        if with_sha:
            packed_d = dlc.read(d['iso_off'], d['stored'])
            sha_cache[n] = sha(packed_d)
        # 本体可能有两份（GR/MENU），任一份相同即算「未变」
        status = 'only_base_diff'
        for tag, b in base_by_name[n]:
            if with_sha:
                pb = base.read(b['iso_off'], b['stored'])
                if sha(pb) == sha_cache[n]:
                    status = 'same'
                    break
            else:
                if b['stored'] == d['stored'] and b['real'] == d['real']:
                    status = 'same'
                    break
        if status == 'same':
            same.append(n)
        else:
            changed.append(n)
    out['compare']['payload'] = dict(same=len(same), changed=len(changed),
                                     changed_names=changed)
    P('  同名 %d 条：载荷逐字节相同 %d，已改 %d' % (len(inherited), len(same), len(changed)))
    ext_changed = ext_hist(changed)
    out['compare']['ext_hist']['changed'] = ext_changed
    P('  已改资源/扩展名:', ext_changed)
    if changed:
        P('  已改资源前 40 个:', changed[:40])

    # f09/f10 名字键一致性（跨盘同名的强证据）
    f9_same = f9_diff = f10_same = f10_diff = 0
    for n in inherited:
        d = dlc_by_name[n][0]
        b = base_by_name[n][0][1]
        if b['raw'][9] == d['raw'][9]:
            f9_same += 1
        else:
            f9_diff += 1
        if b['raw'][10] == d['raw'][10]:
            f10_same += 1
        else:
            f10_diff += 1
    out['compare']['name_key'] = dict(f09_same=f9_same, f09_diff=f9_diff,
                                      f10_same=f10_same, f10_diff=f10_diff,
                                      note='u32[9]/u32[10] 为「同名资源恒定」的名字键；'
                                           '同名跨盘应 100% 相同（含内容已改的条目）')
    P('  名字键 u32[9] 相同 %d/%d，u32[10] 相同 %d/%d（同名集合内）'
      % (f9_same, len(inherited), f10_same, len(inherited)))

    # ---------- 文本资源量对比 ----------
    P('\n=== 3) 文本资源量对比 ===')
    tstat = dict(lang={}, sfxml={})

    def lang_stats(iso, ents, name, tag, bucket):
        cands = [e for e in ents if e['name'].upper() == name]
        if not cands:
            bucket[tag] = dict(found=False)
            return
        e = cands[0]
        blob = payload(iso, e)
        try:
            lang, used = dlclib.parse_lang(blob)
            groups = sorted(set(x.g for x in lang))
            bucket[tag] = dict(found=True, stored=e['stored'], real=e['real'],
                               blob=len(blob), groups=len(groups), entries=len(lang),
                               text_bytes=sum(len(x.data) for x in lang),
                               tail=len(blob) - used)
        except Exception as ex:  # noqa: BLE001
            bucket[tag] = dict(found=True, error=str(ex))

    def sfxml_stats(iso, ents, name, tag, bucket):
        cands = [e for e in ents if e['name'].upper() == name]
        if not cands:
            bucket[tag] = dict(found=False)
            return
        e = cands[0]
        blob = payload(iso, e)
        texts = dlclib.parse_sfxml(blob)
        ne = [t for t in texts if t[3]]
        bucket[tag] = dict(found=True, stored=e['stored'], real=e['real'],
                           text_tags=len(texts), nonempty=len(ne),
                           text_bytes=sum(t[2] for t in ne))
        return texts

    for label, iso, ents in (('dlc', dlc, dlc_ents),
                             ('base_gr', base, base_ents['GR']),
                             ('base_menu', base, base_ents['MENU'])):
        lang_stats(iso, ents, 'EN_STRINGS.RES', label, tstat['lang'])
        sfxml_stats(iso, ents, 'EN_SPECIAL_FEATURE.XML', label, tstat['sfxml'])
    P('  LANG（EN_STRINGS.RES）:')
    for k in ('dlc', 'base_gr', 'base_menu'):
        P('    %-10s %s' % (k, tstat['lang'].get(k)))
    P('\n  SFXML（EN_SPECIAL_FEATURE.XML）:')
    for k in ('dlc', 'base_gr', 'base_menu'):
        P('    %-10s %s' % (k, tstat['sfxml'].get(k)))
    out['compare']['text_resources'] = tstat

    # 各类文本资源数量对比
    def count_ext(ents, exts):
        c = Counter()
        for e in ents:
            ext = ext_of(e['name'])
            if ext in exts:
                c[ext] += 1
        return dict(c)
    TEXT_EXTS = ('MIS', 'ATR', 'GTF', 'XML', 'KIT', 'GUN', 'TOE', 'PRJ', 'VCL', 'ITM',
                 'ENV', 'CSF', 'PSF', 'KIL', 'RES', 'TXT', 'DIR', 'LST')
    cnt = dict(dlc=count_ext(dlc_ents, TEXT_EXTS),
               base_gr=count_ext(base_ents['GR'], TEXT_EXTS),
               base_menu=count_ext(base_ents['MENU'], TEXT_EXTS))
    out['compare']['text_resource_counts'] = cnt
    P('\n  文本/定义类资源数量:')
    keys = sorted(set().union(*[set(v) for v in cnt.values()]))
    P('    %-6s %8s %8s %8s' % ('ext', 'dlc', 'base_gr', 'base_menu'))
    for k in keys:
        P('    %-6s %8d %8d %8d' % (k, cnt['dlc'].get(k, 0),
                                    cnt['base_gr'].get(k, 0), cnt['base_menu'].get(k, 0)))

    # ---------- 名单落盘 ----------
    os.makedirs(args.out_dir, exist_ok=True)
    def dump_list(fn, names):
        p = os.path.join(args.out_dir, fn)
        with open(p, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(names) + '\n')
        return p
    p_new = dump_list('base_new_in_dlc.txt', new_dlc)
    p_inh = dump_list('base_inherited.txt', inherited)
    p_only = dump_list('base_only_in_base.txt', base_only)
    p_chg = dump_list('base_changed_payload.txt', changed)
    P('\n[out] 名单: %s / %s / %s / %s' % (p_new, p_inh, p_only, p_chg))
    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    P('[out] %s (%.1f KB)' % (args.json, os.path.getsize(args.json) / 1024))

    # 新增资源中的「汉化相关」
    P('\n=== 4) 资料片新增资源里与汉化相关的（文本/字库/图集）===')
    interesting = [n for n in new_dlc if ext_of(n) in
                   ('MIS', 'ATR', 'GTF', 'XML', 'RES', 'TXT', 'PAK', 'DIR')]
    P('  新增文本/图集类 %d 个，前 80:' % len(interesting))
    for n in interesting[:80]:
        P('    %-40s %s' % (n, ext_of(n)))
    out['compare']['new_text_related'] = interesting
    with open(args.json, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    base.close()
    dlc.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
