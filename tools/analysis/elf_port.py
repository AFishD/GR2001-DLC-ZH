# -*- coding: utf-8 -*-
r"""elf_port.py —— 本体(英文→汉化) ELF 补丁差异提取 + DLC 移植可行性分析。

这是 elf_probe.py 的「移植蓝本」专用工具：把本体工程 SLUS_206.13
「英文原版 ELF」与「汉化最终 ELF(GR_ZH138 血统)」的差异全部挖出来，
按「字体/文本栈 / 图标常量 / 崩溃修复 / 排版常量 / 其它」分类，
并把字体文本栈各函数在三个 ELF 里做指令级相似度比较，输出移植判断。

三份 ELF：
    base-EN  third_party/orig/ps2/slus_out/SLUS_206.13          (37,453,732 B, sha256 5fec662f…)
    base-ZH  work/builds/FINAL/Tom Clancy's Ghost Recon (ZH_CN).iso @LBA295
             (37,453,732 B, sha256 a0c8499c…，= 本体汉化最终 ELF)
    DLC      third_party/orig/ps2/[PS2] … Jungle Storm (U).iso @LBA296
             (5,319,720 B, sha256 cf29cabe…)

默认把三份都导出到 work/analysis/elf/ 缓存（extract 子命令），其它子命令优先用缓存。

子命令：
    extract       从三个 ISO 里抽出 ELF 到 work/analysis/elf/（只读 ISO）
    diff          英文→汉化逐字节差异，带符号名注释 + 分类；--json
    redirects     diff 中的「跳转重定向」站点（j/jal 目标被改）→ cave 入口清单
    caves         反汇编 cave 区（默认 0x416E00:0x417800 / 0x565600:0x565B00）
    func          反汇编指定函数（--elf base|zh|dlc --va 0x…；--side 并排）
    textmap       字体/文本栈函数三份 ELF 的映射与相似度 → 移植判断
    all           一次跑完 diff/redirects/caves/textmap，全写 work/analysis/elf/

用法：
    python tools/analysis/elf_port.py extract
    python tools/analysis/elf_port.py diff --json work/analysis/elf/zh_diff.json
    python tools/analysis/elf_port.py redirects
    python tools/analysis/elf_port.py caves --out work/analysis/elf/zh_caves.txt
    python tools/analysis/elf_port.py func --elf zh --va 0x219A70 --n 140
    python tools/analysis/elf_port.py textmap
    python tools/analysis/elf_port.py all
"""
import argparse
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import elf_probe as EP                                       # noqa: E402

P = EP.P
WORK = EP.WORK
CACHE = EP.CACHE

# 本体汉化 ELF 里被写成「DBCS cave」的两个大区（全零/废弃的 sce* 函数区）
ZH_CAVE_REGIONS = [
    (0x00416E00, 0x00417800, 'DBCS cave A（原 sceRemove/sceMkdir/sceFormat 等无用 libc 区）'),
    (0x00565600, 0x00565B00, 'DBCS cave B（测量/拦截器/槽位辅助）'),
]

# 字体/文本栈函数（本体英文 ELF 地址 = 汉化 ELF 地址）
TEXT_FUNCS = [
    ('wctomb', 0x0040BFC8, 0),
    ('RSFontMgr::DrawString', 0x00219A70, 0),
    ('RSFontMgr::DrawString(2)', 0x00219E00, 0),
    ('RSFontMgr::DrawString(3)', 0x00219EB0, 0),
    ('RSFontMgr::AddOneWord', 0x00219F50, 0),
    ('RSFontMgr::Flush', 0x0021A190, 0),
    ('RSFontMgr::Draw', 0x0021A290, 0),
    ('RSFont::StringWidth', 0x0021AC00, 0),
    ('RSFont::CharHeight', 0x0021ACD0, 0),
    ('RSFont::CharWidth', 0x0021AD10, 0),
    ('RSFont::ComputeCharTextureCoords', 0x0021ADE0, 0),
]

# DLC 对应函数（由 elf-probe 指纹匹配得到；file_off = VA - 0xFFF00）
DLC_MAP = {
    'wctomb': 0x00173678,
    'RSFontMgr::DrawString': 0x002195F0,
    'RSFontMgr::AddOneWord': 0x002193B0,
    'RSFont::StringWidth': 0x0021A4C0,
    'RSFont::CharHeight': 0x002199A0,
    'RSFont::CharWidth': 0x0021A360,
    'RSFont::ComputeCharTextureCoords': 0x0021A210,
}

# 汉化 cave 的新增入口（由 redirects 子命令从 diff 自动发现 + 人工确认）
ZH_CAVE_ENTRIES = [
    (0x00416ED0, 'DBCS 解码 cave：输入 a0=输出格, a1=当前字节；写 2B 解码值 + 1B 步长'),
    (0x00416F40, 'CharWidth cave：替换 RSFont::CharWidth 函数体'),
    (0x00417050, '槽位→UV cave：替换 ComputeCharTextureCoords 函数头'),
    (0x00417150, '测量循环 cave：替换 StringWidth 逐字循环'),
    (0x00417200, 'DrawString 前置/状态 cave（0x219ADC 跳转目标）'),
    (0x00417600, '容量钳位 cave（[obj+0xF8] = min(v,16)）'),
    (0x00565670, 'StringWidth 尾部 cave：字形数/字距口径'),
    (0x00565930, 'DrawString 拦截器 cave：行高修正 + 补回 sd ra,160(sp)'),
    (0x00565A00, '解码辅助/槽位公式 cave（B 区）'),
]


def load(kind):
    elf, src = EP.Elf.pick(kind)
    return elf


def cmd_extract(a):
    os.makedirs(WORK, exist_ok=True)
    todo = [('dlc', EP.DLC_ISO, EP.DLC_NAME),
            ('base', EP.BASE_ISO, EP.BASE_NAME),
            ('zh', EP.BASE_ZH_ISO, EP.BASE_NAME)]
    for kind, iso, name in todo:
        dst = CACHE[kind]
        if os.path.exists(dst) and not a.force:
            elf = EP.Elf.from_file(dst)
            P('[skip] %s 已存在  %d B  sha256 %s' % (dst, elf.size, elf.sha256()[:16]))
            continue
        if not os.path.exists(iso):
            P('[MISS] %s 不存在（跳过 %s）' % (iso, kind))
            continue
        elf = EP.Elf.from_iso(iso, name)
        with open(dst, 'wb') as f:
            f.write(elf.data)
        P('[ok] %-4s %s  LBA %d  %d B  sha256 %s' % (
            kind, os.path.basename(dst), elf.lba, elf.size, elf.sha256()))


# ─────────────────────── diff & 分类 ───────────────────────
def classify(va, sym, zword, oword, off):
    """给一个差异站点分类。返回 (类别, 说明)"""
    for lo, hi, why in ZH_CAVE_REGIONS:
        if lo <= va < hi:
            return 'cave', why
    if va < 0x0006C780:
        return 'alloc/crash', '低地址（dlmalloc/memcpy：四件套区）'
    if 0x00219A00 <= va < 0x0021AF30:
        return 'text-stack', 'RSFont/RSFontMgr 字体文本栈'
    if 0x0021B000 <= va < 0x0021D000:
        return 'text-stack-2', 'RSFont 相关（菜单/UI 文本辅助）'
    if va in (0x00216578,):
        return 'layout', 'DrawLetters 行距 +3→+5'
    if 0x002BEE00 <= va < 0x002BEF00:
        return 'layout', 'UI 浮点常量微调'
    if 0x002DE000 <= va < 0x002DF000:
        return 'layout', 'UI 宽度硬编码'
    if 0x001FF000 <= va < 0x00208000:
        return 'layout', '换行宽度硬编码 21/16'
    if 0x00407000 <= va < 0x0040A000:
        return 'guard', '键码表 sltiu 越界守卫'
    if va in (0x00416578,):
        return 'layout', 'DrawLetters 行距'
    if sym:
        return 'other', 'sym=%s' % sym
    return 'other', ''


def cmd_diff(a):
    eo = load('base')
    ez = load('zh')
    n = min(eo.size, ez.size)
    runs = []
    i = 0
    while i < n:
        if eo.data[i] != ez.data[i]:
            j = i
            while j < n and eo.data[j] != ez.data[j]:
                j += 1
            runs.append((i, j - i))
            i = j
        else:
            i += 1
    P('# base-EN  %d B sha %s' % (eo.size, eo.sha256()))
    P('# base-ZH  %d B sha %s' % (ez.size, ez.sha256()))
    P('# diff runs %d / bytes %d' % (len(runs), sum(l for _, l in runs)))
    rows = []
    stat = {}
    for off, ln in runs:
        try:
            va = eo.va(off)
        except SystemExit:
            va = 0
        sym = eo.sym_for(va)
        symname = sym[2] if sym else ''
        ow = struct.unpack('<I', eo.data[off:off + 4].ljust(4, b'\0'))[0] if ln >= 1 else 0
        zw = struct.unpack('<I', ez.data[off:off + 4].ljust(4, b'\0'))[0] if ln >= 1 else 0
        cat, why = classify(va, symname, zw, ow, off)
        stat[cat] = stat.get(cat, 0) + 1
        row = dict(file_off=off, va=va, len=ln,
                   orig=eo.data[off:off + ln].hex(), zh=ez.data[off:off + ln].hex(),
                   orig_word=ow, zh_word=zw, sym=symname,
                   sym_off=(va - sym[0]) if sym else None,
                   cat=cat, why=why,
                   orig_dis='%s %s' % EP.DIS.one(ow, va),
                   zh_dis='%s %s' % EP.DIS.one(zw, va))
        rows.append(row)
    P('# 分类统计: %s' % stat)
    with open(os.path.join(WORK, 'zh_diff.json'), 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    P('[json] work/analysis/elf/zh_diff.json  (%d 行)' % len(rows))
    out = os.path.join(WORK, 'zh_diff.txt')
    with open(out, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write('file 0x%08X VA 0x%08X len %-3d [%-12s] %-38s %s -> %s\n' % (
                r['file_off'], r['va'], r['len'], r['cat'],
                (r['sym'] + ('+0x%X' % r['sym_off'] if r['sym_off'] else ''))[:38],
                r['orig'], r['zh']))
            f.write('      orig: %-24s  zh: %s\n' % (r['orig_dis'], r['zh_dis']))
    P('[txt ] %s' % out)
    # 附加：逐类别列出
    for cat in sorted(stat):
        P('')
        P('## %s  (%d 站)' % (cat, stat[cat]))
        for r in rows:
            if r['cat'] != cat:
                continue
            P('  0x%08X VA 0x%06X len %-2d %-34s %s -> %s  %s' % (
                r['file_off'], r['va'], r['len'],
                (r['sym'] + ('+0x%X' % r['sym_off'] if r['sym_off'] else ''))[:34],
                r['orig'], r['zh'], r['why']))
    return rows


# ─────────────────────── redirects（跳转重定向） ───────────────────────
def cmd_redirects(a):
    rows = json.load(open(os.path.join(WORK, 'zh_diff.json'), encoding='utf-8'))
    reds = []
    for r in rows:
        va = r['va']
        ow, zw = r['orig_word'], r['zh_word']
        oop, zop = ow >> 26, zw >> 26
        if oop in (2, 3) or zop in (2, 3):
            ot = ((ow & 0x3FFFFFF) << 2) | (va & 0xF0000000) if oop in (2, 3) else None
            zt = ((zw & 0x3FFFFFF) << 2) | (va & 0xF0000000) if zop in (2, 3) else None
            reds.append(dict(va=va, file_off=r['file_off'], oop=oop, zop=zop,
                             orig_tgt=ot, zh_tgt=zt, sym=r['sym'],
                             orig=ow, zh=zw))
    P('# 跳转/调用重定向 %d 处' % len(reds))
    out = os.path.join(WORK, 'zh_redirects.txt')
    with open(out, 'w', encoding='utf-8') as f:
        for r in reds:
            s = 'VA 0x%08X file 0x%08X  %08X(j->0x%08X) => %08X(j->0x%08X)  [%s]' % (
                r['va'], r['file_off'], r['orig'],
                r['orig_tgt'] or 0, r['zh'], r['zh_tgt'] or 0, r['sym'])
            P('  ' + s)
            f.write(s + '\n')
    P('[txt ] %s' % out)
    return reds


# ─────────────────────── cave 反汇编 ───────────────────────
def cmd_caves(a):
    ez = load('zh')
    out = a.out or os.path.join(WORK, 'zh_caves.txt')
    lines = []
    lines.append('# 本体汉化 ELF (base-ZH, sha256 %s) DBCS cave 全区反汇编' % ez.sha256())
    lines.append('# file_off = VA - 0xFFF80（PT_LOAD off=0x80 va=0x100000）')
    for lo, hi, why in ZH_CAVE_REGIONS:
        lines.append('')
        lines.append('#' * 78)
        lines.append('## 0x%08X .. 0x%08X  %s' % (lo, hi, why))
        lines.append('#' * 78)
        data = ez.read(lo, hi - lo)
        for addr, w, b, mn, ops in EP.DIS.iter(data, lo):
            lines.append('0x%06X f0x%06X %08X  %-8s %s' % (
                addr, ez.off(addr), w, mn, ops))
    with open(out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    P('[txt ] %s  (%d 行)' % (out, len(lines)))
    # 入口函数单独 dump
    for va, why in ZH_CAVE_ENTRIES:
        P('')
        P('=== cave 入口 0x%08X  %s' % (va, why))
        EP.dump_dis(ez, va, a.n)


# ─────────────────────── func ───────────────────────
def cmd_func(a):
    e = load(a.elf)
    for item in a.va:
        va = int(item, 16)
        P('=' * 78)
        P('## %s  VA 0x%08X  file 0x%08X' % (e.tag, va, e.off(va)))
        EP.dump_dis(e, va, a.n, out=a.out)
        if a.side:
            e2 = load(a.side)
            # 用 DLC_MAP 反查
            dva = None
            for nm, v in TEXT_FUNCS:
                if v == va:
                    dva = DLC_MAP.get(nm)
            if dva is None:
                P('(side: 无已知映射)')
                continue
            P('## side %s VA 0x%08X  file 0x%08X' % (e2.tag, dva, e2.off(dva)))
            EP.dump_dis(e2, dva, a.n, out=None)


# ─────────────────────── textmap（三份 ELF 相似度） ───────────────────────
def cmd_textmap(a):
    eo = load('base')
    ez = load('zh')
    ed = load('dlc')
    rows = []
    P('%-36s %-10s %-10s %-8s %-10s %-10s %s' % (
        'function', 'base-EN', 'base-ZH', 'diff', 'DLC', 'DLC-sim', 'verdict'))
    for nm, va, sz in TEXT_FUNCS:
        if sz == 0:
            sym = eo.sym_for(va)
            sz = sym[1] if sym and sym[0] == va else 0
        ln = (sz // 4) if sz else 0
        dva = DLC_MAP.get(nm)
        # 英文→汉化 相似度（同地址，等价性：相同字数）
        same = 0
        if ln:
            ow = eo.words(va, ln)
            zw = ez.words(va, ln)
            same = sum(1 for x, y in zip(ow, zw) if x == y)
        # 英文→DLC 归一化序列相似度（在 DLC 全文中找最佳窗口）
        sim = None
        if dva and ln:
            k1 = EP.norm_keys(eo, va, ln)
            k2 = EP.norm_keys(ed, max(ed.text['vaddr'], dva - 0x2000), min(
                (ed.text['filesz']) // 4, 0x4000))
            off, score = EP.best_window(k1, k2)
            sim = score / ln if ln else 0
            sim_va = max(ed.text['vaddr'], dva - 0x2000) + off * 4
        rows.append(dict(name=nm, base_va=va, size=sz, insns=ln,
                         same_en_zh=same, dlc_va=dva,
                         dlc_sim=(sim if sim is not None else None),
                         dlc_sim_va=(sim_va if dva and ln else None)))
        P('%-36s 0x%06X  0x%06X  %4d/%-4d 0x%08X  %5s  %s' % (
            nm, va, va, same, ln, dva or 0,
            ('%.1f%%' % (100 * sim)) if sim is not None else '-',
            '需重新汇编（结构相同/寄存器不同）' if (sim or 0) > 0.3 else '需确认'))
    with open(os.path.join(WORK, 'textmap.json'), 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    P('[json] work/analysis/elf/textmap.json')


def cmd_all(a):
    cmd_extract(a)
    P('')
    cmd_diff(a)
    P('')
    cmd_redirects(a)
    P('')
    cmd_textmap(a)
    P('')
    cmd_caves(a)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd')

    def add(name, fn):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        return p

    p = add('extract', cmd_extract)
    p.add_argument('--force', action='store_true')
    p = add('diff', cmd_diff)
    p.add_argument('--json', default=None)
    p = add('redirects', cmd_redirects)
    p = add('caves', cmd_caves)
    p.add_argument('--out', default=None)
    p.add_argument('--n', type=int, default=40)
    p = add('func', cmd_func)
    p.add_argument('--elf', default='zh', choices=['dlc', 'base', 'zh'])
    p.add_argument('--va', action='append', required=True)
    p.add_argument('--n', type=int, default=60)
    p.add_argument('--side', default=None, choices=['dlc', 'base', 'zh'])
    p.add_argument('--out', default=None)
    p = add('textmap', cmd_textmap)
    p = add('all', cmd_all)
    p.add_argument('--force', action='store_true')

    a = ap.parse_args()
    if not getattr(a, 'cmd', None):
        ap.print_help()
        return
    a.fn(a)


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                            # noqa: BLE001
        pass
    main()
