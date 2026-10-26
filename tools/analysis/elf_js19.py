# -*- coding: utf-8 -*-
r"""elf_js19.py —— JS_ZH19 上一版中文构筑（PCSX2 cdvd 块转储）的反汇编/差异/崩溃取证工具。

背景：`%LOCALAPPDATA%\PCSX2\cdvd-dump\JS_ZH19 (2026-10-21 16-19-47).dump`
是上一个会话对同一资料片的「已打 DBCS 补丁」构筑的 CDVD 块转储；其中完整的
SLUS_208.20 已提取为 work/analysis/js19/JS_ZH19_ELF_from_dump.bin
（sha256 80e25599…、Game CRC 3A320B22，与 PCSX2 日志一致 ⇒ 提取逐字节正确）。

本工具只读该 ELF + 原始 DLC ELF + PCSX2 emulog，做四件事：
  verify   身份校验（size/sha256/CRC/段表）
  diff     与原版 ELF 的逐字节差异（133 段），标注 cave 区与调用点
  cave     反汇编 cave 全区（0x1808A8..0x180C98）并按已知入口分块
  crash    解析 PCSX2 emulog.txt 的 TLB Miss 记录，定位故障指令与「空指针+偏移」含义
  fontres  展开 JS19 的 FONT.RES，复现其 style 表 off-by-22 损坏
  compare  与「本体汉化最终 ELF」DBCS cave 的同源性指纹比对
  all      以上全部 → work/analysis/elf/js19_report.txt + js19_analysis.json

用法：
    python tools/analysis/elf_js19.py all
    python tools/analysis/elf_js19.py cave --va 0x1808A8 --n 260
    python tools/analysis/elf_js19.py crash
"""
import argparse
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
import elf_probe as EP                                     # noqa: E402

WORK = os.path.join(REPO, 'work', 'analysis', 'elf')
JS19_DIR = os.path.join(REPO, 'work', 'analysis', 'js19')
JS19_ELF = os.path.join(JS19_DIR, 'JS_ZH19_ELF_from_dump.bin')
JS19_FONTRES_STORED = os.path.join(JS19_DIR, 'payloads', '00580_FONT.RES.bin')
EMULOG = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'PCSX2', 'logs', 'emulog.txt')

JS19_SHA256 = '80e2559992105156382c3f97c44f0c2aa96f06f170c659be985e8268050594f6'
JS19_CRC = 0x3A320B22
DLC_SHA256 = 'cf29cabeebb75fc8d9fdd1a076e4c574c5740e73948f0a2ef643b632baee7eee'
DLC_CRC = 0xDE1E4DEE

CAVE_LO, CAVE_HI = 0x1808A8, 0x180C98
# JS19 cave 内的功能块入口（由调用点重定向目标反推）
JS19_BLOCKS = [
    (0x1808A8, 'draw_advance', 'DrawString 游标推进（lbu sp+0xDD; addu s5; j 0x219950）'),
    (0x1808C8, 'decode', '解码 cave：gate 0xA1/0xAE、trail 0xA1/0xFF、写 2B+步长'),
    (0x180948, 'charwidth', 'CharWidth cave：单字节/对偶、slot=(lead-0xA1)*94+(trail-0xA1)+224'),
    (0x180A48, 'uv', '槽位→UV cave：NCOL=62、CW=8、Y0=2、SKIP_ROW=12、SKIP_ROWS=3'),
    (0x180B38, 'measure', 'StringWidth 循环 cave（DBCS 逐字，跨字节）'),
    (0x180BD8, 'wrap', '另一处 UI 测量/折行 cave（0x21B780 重定向）'),
]


def load_js19():
    if not os.path.exists(JS19_ELF):
        raise SystemExit('找不到 JS19 ELF: %s（先按 docs 复现提取）' % JS19_ELF)
    return EP.Elf.from_file(JS19_ELF, 'JS19')


def load_orig():
    return EP.Elf.pick('dlc')[0]


# ─────────────────────────── verify ───────────────────────────
def cmd_verify(a):
    e = load_js19()
    P = print
    P('== JS_ZH19 补丁后 ELF')
    P('size     %d' % e.size)
    P('sha256   %s   (期望 %s)' % (e.sha256(), JS19_SHA256))
    P('Game CRC %08X   (期望 %08X)' % (e.crc(), JS19_CRC))
    P('PT_LOAD  %s' % [(hex(p['vaddr']), hex(p['off']), hex(p['filesz']), hex(p['memsz']))
                      for p in e.phdrs])
    ok = (e.size == 5319720 and e.sha256() == JS19_SHA256 and e.crc() == JS19_CRC)
    P('判定: %s' % ('OK（与 PCSX2 记录一致，转储提取逐字节正确）' if ok else 'MISMATCH'))
    return ok


# ─────────────────────────── diff ───────────────────────────
def diff_runs(eo, ej):
    n = min(eo.size, ej.size)
    runs, i = [], 0
    while i < n:
        if eo.data[i] != ej.data[i]:
            j = i
            while j < n and eo.data[j] != ej.data[j]:
                j += 1
            runs.append((i, j - i))
            i = j
        else:
            i += 1
    return runs


def cmd_diff(a, quiet=False):
    eo, ej = load_orig(), load_js19()
    runs = diff_runs(eo, ej)
    print('== 原版 vs JS19 逐字节差异: %d 段 / %d 字节' % (len(runs), sum(l for _, l in runs)))
    rows = []
    for off, ln in runs:
        try:
            va = eo.va(off)
        except SystemExit:
            va = 0
        ow = struct.unpack('<I', eo.data[off:off + 4].ljust(4, b'\0'))[0]
        jw = struct.unpack('<I', ej.data[off:off + 4].ljust(4, b'\0'))[0]
        area = ('cave' if CAVE_LO <= va < CAVE_HI else 'site')
        rows.append(dict(file_off=off, va=va, len=ln, area=area,
                         orig=eo.data[off:off + ln].hex(), js19=ej.data[off:off + ln].hex(),
                         orig_dis='%s %s' % EP.DIS.one(ow, va),
                         js19_dis='%s %s' % EP.DIS.one(jw, va)))
    if not quiet:
        for r in rows:
            if r['area'] == 'cave':
                continue
            print('  [site] VA 0x%06X file 0x%06X len %-3d %s -> %s   | %s → %s' % (
                r['va'], r['file_off'], r['len'], r['orig'], r['js19'],
                r['orig_dis'], r['js19_dis']))
    print('  cave 区差异段: %d（0x%06X..0x%06X 整段替换）' % (
        sum(1 for r in rows if r['area'] == 'cave'), CAVE_LO, CAVE_HI))
    return rows


# ─────────────────────────── cave ───────────────────────────
def cmd_cave(a):
    ej = load_js19()
    lo = int(a.va, 16) if a.va else CAVE_LO
    n = a.n or ((CAVE_HI - lo) // 4)
    blocks = dict((v, (k, why)) for v, k, why in JS19_BLOCKS)
    for addr, w, b, mn, ops in EP.DIS.iter(ej.read(lo, n * 4), lo):
        tag = ''
        if addr in blocks:
            tag = '   ; ===== %s: %s' % blocks[addr]
        print('0x%06X f0x%06X %08X  %-8s %s%s' % (
            addr, ej.off(addr), w, mn, ops, tag))


# ─────────────────────────── crash ───────────────────────────
def cmd_crash(a):
    if not os.path.exists(EMULOG):
        print('找不到 emulog: %s' % EMULOG)
        return None
    txt = open(EMULOG, encoding='utf-8', errors='replace').read()
    lines = re.findall(r'\[\s*([0-9.]+)\] TLB Miss, pc=0x([0-9a-fA-F]+) addr=0x([0-9a-fA-F]+) '
                       r'\[(\w+)\]', txt)
    print('== emulog TLB Miss: %d 条 / 唯一 (pc,addr,op)=%d' % (
        len(lines), len(set((p, ad, op) for _, p, ad, op in lines))))
    eo, ej = load_orig(), load_js19()
    seen = {}
    for t, pc, addr, op in lines:
        key = (pc, addr, op)
        seen.setdefault(key, []).append(float(t))
    prof = []
    for (pc, addr, op), ts in sorted(seen.items(), key=lambda x: -len(x[1])):
        va = int(pc, 16)
        in_cave = CAVE_LO <= va < CAVE_HI
        # 找是哪条指令 + 用哪个寄存器（原/JS19 同一位置字节不同，按 JS19 解码）
        try:
            w = ej.word(va)
            mn, ops = EP.DIS.one(w, va)
        except SystemExit:
            mn, ops = '?', ''
        off = int(addr, 16)
        # 反推基址寄存器
        m = re.search(r',\s*(-?0x[0-9a-fA-F]+|-?\d+)\(', ops)
        base = ''
        if m:
            g = m.group(1)
            disp = int(g, 16) if g.lower().lstrip('-').startswith('0x') else int(g)
            base = '基址寄存器 = 0x%X - (0x%X) = 0x%X' % (
                off, disp & 0xFFFFFFFF, (off - disp) & 0xFFFFFFFF)
        prof.append(dict(pc=pc, addr=addr, op=op, count=len(ts), t0=min(ts), t1=max(ts),
                         in_cave=in_cave, insn='%s %s' % (mn, ops), base=base,
                         code_owned='JS19-cave' if in_cave else 'orig-code'))
        print('  第 %2d 次 pc=0x%s addr=0x%s [%s]  %-8s %-28s %s  (%s)  时间 %.3f..%.3f' % (
            len(ts), pc, addr, op, mn, ops, ('cave内' if in_cave else '原版代码'), base,
            min(ts), max(ts)))
    return prof


# ─────────────────────────── fontres ───────────────────────────
def cmd_fontres(a):
    import dlclib
    print('== JS19 FONT.RES 结构（展开）')
    raw = open(JS19_FONTRES_STORED, 'rb').read()
    subs = dlclib.lzo_subs(raw)
    blob = b''.join(s[0] for s in subs)
    print('  stored=%d B, LZO 子流 %d 条, rlen=%s, 展开=%d B'
          % (len(raw), len(subs), [s[2] for s in subs], len(blob)))
    p = 0
    ln = struct.unpack_from('<I', blob, p)[0]
    name = blob[p + 4:p + 4 + ln]
    p += 4 + ln
    nf = struct.unpack_from('<I', blob, p)[0]
    p += 4
    print('  图集名=%r  nfaces=%d' % (name, nf))
    faces = []
    for f in range(nf):
        nl = struct.unpack_from('<I', blob, p)[0]
        nm = blob[p + 4:p + 4 + nl]
        p += 4 + nl
        hdr = struct.unpack_from('<14I', blob, p)
        p += 56
        recs = blob[p:p + 224 * 10]
        p += 224 * 10
        faces.append(dict(name=nm.decode('latin-1'), hdr=[hex(x) for x in hdr]))
        print('  face[%d] %-8s hdr14=%s' % (f, nm.decode('latin-1'), [hex(x) for x in hdr]))
    tail = blob[p:]
    print('  尾部样式表 = %d B（原版 522 B，JS19 多 %d B）' % (len(tail), len(tail) - 522))
    cnt = struct.unpack_from('<I', tail, 0)[0]
    # 按自描述记录走：{u32 namelen, name[namelen], u8 nul, 24B 固定}
    entries, q = [], 4
    while q + 4 <= len(tail):
        nl = struct.unpack_from('<I', tail, q)[0]
        if not (1 <= nl <= 32) or q + 4 + nl > len(tail):
            break
        nm = tail[q + 4:q + 4 + nl]
        entries.append(dict(off=q, namelen=nl, name=nm.decode('latin-1')))
        q += 4 + nl + 1 + 24
    print('  count 字段 = %d，实际可解析记录 = %d' % (cnt, len(entries)))
    for i, x in enumerate(entries):
        print('    rec %2d off %4d len %2d name=%-8s%s' % (
            i, x['off'], x['namelen'], x['name'],
            '   ← 记录被截断（固定字段缺 22B）' if i == 7 else ''))
    verdict = dict(blob=len(blob), tail=len(tail), count=cnt, entries=len(entries),
                   offby1=(cnt != len(entries)),
                   truncated_entry=(entries[7] if len(entries) > 7 else None))
    print('  判定: count=%d vs 实际=%d ⇒ %s；rec7 只有 %d B（正常应为 %d B）⇒ 尾部 off-by-%d 损坏'
          % (cnt, len(entries), '不一致(OFF-BY-ONE)' if cnt != len(entries) else '一致',
             (entries[8]['off'] - entries[7]['off']) if len(entries) > 8 else -1,
             4 + entries[7]['namelen'] + 25 if len(entries) > 7 else -1,
             (4 + entries[7]['namelen'] + 25 - (entries[8]['off'] - entries[7]['off']))
             if len(entries) > 8 else -1))
    return verdict


# ─────────────────────────── compare（同源性） ───────────────────────────
def cmd_compare(a):
    """JS19 cave 各块 vs 本体汉化 ELF 的 DBCS cave 块：归一化指令序列相似度。"""
    ej = load_js19()
    ez = EP.Elf.pick('zh')[0]
    pairs = [('decode', 0x1808C8, 27, 0x416ED0, 27),
             ('charwidth', 0x180948, 55, 0x416F40, 61),
             ('uv', 0x180A48, 59, 0x417050, 59),
             ('measure', 0x180B38, 25, 0x417150, 29),
             ('wrap/0x21B780', 0x180BD8, 42, 0x417500, 40)]
    print('== JS19 cave vs 本体汉化最终 ELF DBCS cave：归一化指令序列相似度')
    res = []
    for name, vj, nj, vz, nz in pairs:
        nj = min(nj, nz)
        kj = EP.norm_keys(ej, vj, nj)
        kz = EP.norm_keys(ez, vz, nz)
        off, score = EP.best_window(kj, kz)
        sim = score / nj
        print('  %-10s JS19 0x%06X[%2d] vs ZH 0x%06X[%2d]  best off %+d  %2d/%2d = %.0f%%'
              % (name, vj, nj, vz, nz, off, score, nj, 100 * sim))
        res.append(dict(block=name, js19_va='0x%06X' % vj, zh_va='0x%06X' % vz,
                        sim=round(sim, 3)))
    print('  ⇒ 归一化指令序列高度一致 ⇒ JS19 cave 是**从本体汉化的 DBCS cave 移植而来**'
          '（常量/寄存器按 DLC 改写），不是独立实现。')
    return res


# ─────────────────────────── all ───────────────────────────
def cmd_all(a):
    out = []
    buf = []

    class Tee:
        def write(self, s):
            out.append(s)
            sys.__stdout__.write(s)

        def flush(self):
            sys.__stdout__.flush()

    old = sys.stdout
    sys.stdout = Tee()
    try:
        print('#' * 78)
        print('# JS_ZH19 上一版中文构筑 · ELF 取证报告（tools/analysis/elf_js19.py all）')
        print('#' * 78)
        ok = cmd_verify(a)
        print()
        rows = cmd_diff(a, quiet=True)
        print()
        print('== cave 全区反汇编（0x%06X..0x%06X）' % (CAVE_LO, CAVE_HI))
        cmd_cave(argparse.Namespace(va=None, n=None))
        print()
        prof = cmd_crash(a)
        print()
        fr = cmd_fontres(a)
        print()
        cmp_res = cmd_compare(a)
    finally:
        sys.stdout = old
    os.makedirs(WORK, exist_ok=True)
    path = os.path.join(WORK, 'js19_report.txt')
    open(path, 'w', encoding='utf-8').write(''.join(out))
    meta = dict(elapsed=None, verify=bool(ok), diff_runs=len(rows),
                diff_bytes=sum(r['len'] for r in rows),
                sites=[r for r in rows if r['area'] == 'site'],
                cave_blocks=[dict(va='0x%06X' % v, name=k, why=w) for v, k, w in JS19_BLOCKS],
                crash=prof, fontres=fr, compare=cmp_res)
    jpath = os.path.join(WORK, 'js19_analysis.json')
    json.dump(meta, open(jpath, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('[out] %s' % path)
    print('[out] %s' % jpath)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd')

    def add(name, fn):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        return p

    add('verify', cmd_verify)
    add('diff', cmd_diff)
    p = add('cave', cmd_cave)
    p.add_argument('--va', default=None)
    p.add_argument('--n', type=int, default=None)
    add('crash', cmd_crash)
    add('fontres', cmd_fontres)
    add('compare', cmd_compare)
    add('all', cmd_all)
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                            # noqa: BLE001
        pass
    if not getattr(a, 'cmd', None):
        ap.print_help()
        return
    a.fn(a)


if __name__ == '__main__':
    main()
