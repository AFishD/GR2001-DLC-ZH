# -*- coding: utf-8 -*-
r"""apply_fix.py —— 《幽灵行动》PS2 (SLUS-206.13) 汉化 2400 产品线
「游戏内卡死」修复**四件套**（F4 + OOMFIX + F7 + F7b）的**唯一权威**打补丁 / 校验器。

本文件是本工程 2400 线的收尾归档产物：把此前分散在
    work\builds\GR_COMBFIX\tools\combfix_apply.py
    work\builds\GR_SPINFIX\tools\spinfix_apply.py   (F4 / cave 0x41A35C)
    work\builds\GR_OOMFIX\tools\oomfix_apply.py     (OOMFIX / cave 0x550048)
里的前三条合并为一份、并**删掉只用于当轮 A/B 实验的分支代码**
（F1 / F1b / flavor A / flavor B / 全部探测与系数扫描）。
2026-10-18 的 F7B 轮在此之上加了第 4 条 **F7b**（分配器 unsorted 桶快路径
0x102208 / cave 0x570BB0）—— 用户实机在「发射火箭弹 / 按 L1」时踩到的就是这条回边。

补丁表是数据，不是代码：全部站点、cave 字、闸门、窗口、成品身份都在同目录的
`fix_spec.json` 里（单一真源），本脚本只负责按表施工 + 自查。

★ 强制规则（2026-10-18）：今后一切构筑**必须从英文原版 ISO 出发**
    third_party\orig\ps2\Tom Clancy's Ghost Recon (USA).iso
    sha256 2b42ea7ce9bd0a85972a07ca59b1b9d79422ed318b85737db3cfd17daa788531
**禁止以上一版汉化 ISO 为基底**。本脚本只接受 `--base` = 声明的那一张基底
（sha256 d7f83d7e…443ca0，即「英文原盘 ⊕ K2 cdvd 转储」的产物，由
`tools\final_fix\rebuild_base.py` 现场重建）；指纹不符即拒绝施工。
端到端（含基底重建）一键复跑 = `tools\final_fix\repro_from_eng.ps1`。

用法
----
    # ① 出盘：基底（GR_REBUILD2400.iso）-> 成品
    python tools\final_fix\apply_fix.py --base work\builds\GR_REBUILD\GR_REBUILD2400.iso ^
                                       --out  D:\out\GR_ZH127.iso

    # ② 只校验一张已存在的盘（不写盘；加上 --base 还能核「相对基底的 108 B / 34 run」）
    python tools\final_fix\apply_fix.py --verify-only --iso work\builds\GR_RELEASE\GR_ZH127.iso ^
                                       --base work\builds\GR_REBUILD\GR_REBUILD2400.iso

退出码：0 = 全部断言通过（且出盘 sha256 == 成品身份）；非 0 = 有断言失败（会逐条打印）。
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, 'fix_spec.json')
SEC = 2048


# ───────────────────────────── 基础工具 ─────────────────────────────
def sha256_file(path, blk=1 << 22):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(blk), b''):
            h.update(b)
    return h.hexdigest()


def md5_file(path, blk=1 << 22):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(blk), b''):
            h.update(b)
    return h.hexdigest()


def xor_crc32(data):
    """PCSX2 的 Game CRC = ELF 全体 u32 异或。"""
    c = 0
    for (w,) in struct.iter_unpack('<I', data[:len(data) // 4 * 4]):
        c ^= w
    return c & 0xFFFFFFFF


def iso_root_entries(path):
    with open(path, 'rb') as f:
        f.seek(16 * SEC)
        pvd = f.read(SEC)
        assert pvd[1:6] == b'CD001', '不是 ISO9660 映像'
        rlba = struct.unpack_from('<I', pvd, 158)[0]
        rsz = struct.unpack_from('<I', pvd, 166)[0]
        f.seek(rlba * SEC)
        d = f.read(rsz)
    ents, off = [], 0
    while off < len(d) and d[off]:
        rl = d[off]
        nm = d[off + 33:off + 33 + d[off + 32]].decode('latin-1').split(';')[0]
        ents.append((nm.upper(), struct.unpack_from('<I', d, off + 2)[0],
                     struct.unpack_from('<I', d, off + 10)[0]))
        off += rl
    return ents


def read_elf_from_iso(path, elf_name):
    for (nm, lba, sz) in iso_root_entries(path):
        if nm == elf_name.upper():
            with open(path, 'rb') as f:
                f.seek(lba * SEC)
                d = f.read(sz)
            assert d[:4] == b'\x7fELF', '取到的不是 ELF'
            return d, lba, sz
    raise SystemExit('ISO 里找不到 %s' % elf_name)


def diff_runs(a, b, blk=1 << 22):
    """逐字节比较两个同尺寸文件，返回 [(off, old_bytes, new_bytes), ...]。"""
    runs, cur, off = [], None, 0
    with open(a, 'rb') as fa, open(b, 'rb') as fb:
        while True:
            ba, bb = fa.read(blk), fb.read(blk)
            if not ba and not bb:
                break
            if len(ba) != len(bb):
                raise SystemExit('两个文件尺寸不同')
            if ba != bb:
                for i in range(len(ba)):
                    if ba[i] != bb[i]:
                        if cur is None:
                            cur = [off + i, bytearray(), bytearray()]
                        cur[1].append(ba[i])
                        cur[2].append(bb[i])
                    elif cur is not None:
                        runs.append((cur[0], bytes(cur[1]), bytes(cur[2])))
                        cur = None
            elif cur is not None:
                runs.append((cur[0], bytes(cur[1]), bytes(cur[2])))
                cur = None
            off += len(ba)
    if cur is not None:
        runs.append((cur[0], bytes(cur[1]), bytes(cur[2])))
    return runs


class Report(object):
    """收集断言结果；任何一条 FAIL 都会让脚本以非 0 退出。"""

    def __init__(self, title):
        self.title = title
        self.rows = []
        self.failed = 0

    def check(self, name, ok, detail=''):
        ok = bool(ok)
        if not ok:
            self.failed += 1
        self.rows.append((name, ok, detail))
        print('  [%s] %-46s %s' % ('OK ' if ok else 'FAIL', name, detail))
        return ok

    def head(self, text):
        print('\n' + '=' * 96)
        print(text)
        print('=' * 96)


# ───────────────────────────── 规格装载 ─────────────────────────────
def load_spec(path=SPEC_PATH):
    with open(path, 'r', encoding='utf-8') as f:
        spec = json.load(f)
    spec['_iso_of_va'] = int(spec['iso_layout']['iso_of_va'], 16)
    spec['_lba'] = int(spec['iso_layout']['elf_lba'])
    spec['_elf_name'] = spec['iso_layout']['elf_name']
    for p in spec['patches']:
        p['_va'] = int(p['va'], 16)
        p['_old'] = int(p['old_word'], 16)
        p['_new'] = int(p['new_word'], 16)
        c = p['cave']
        c['_va'] = int(c['va'], 16)
        c['_words'] = [int(w, 16) for w in c['words']]
    return spec


def elf_off(spec, va):
    return va - spec['_iso_of_va'] - spec['_lba'] * SEC


def word_at(spec, elf, va):
    return struct.unpack_from('<I', elf, elf_off(spec, va))[0]


def declared_windows(spec):
    """声明窗口，单位 = ISO 绝对偏移（= VA - 0x6C780）。"""
    win = []
    for p in spec['patches']:
        win.append((p['_va'] - spec['_iso_of_va'], p['_va'] - spec['_iso_of_va'] + 4))
        win.append((p['cave']['_va'] - spec['_iso_of_va'],
                    p['cave']['_va'] - spec['_iso_of_va'] + p['cave']['bytes']))
    return win


def region_pairs(spec):
    """参照区 -> [(ELF 内偏移 lo, hi), ...]（用于与基底逐字节比对）。"""
    out = []
    for r in spec['must_stay_identical_regions']:
        out.append((r['why'], elf_off(spec, int(r['va_lo'], 16)), elf_off(spec, int(r['va_hi'], 16))))
    return out


def region_same(spec, a_elf, b_elf, lo, hi):
    """参照区比对：允许落在声明窗口内的字节不同（例如 OOMFIX 站点就在解压器本体里）。"""
    if a_elf[lo:hi] == b_elf[lo:hi]:
        return True, '逐字节相同'
    win = []
    for p in spec['patches']:
        win.append((elf_off(spec, p['_va']), elf_off(spec, p['_va']) + 4))
        win.append((elf_off(spec, p['cave']['_va']), elf_off(spec, p['cave']['_va']) + p['cave']['bytes']))
    bad = [lo + i for i in range(hi - lo)
           if a_elf[lo + i] != b_elf[lo + i] and not any(w0 <= lo + i < w1 for (w0, w1) in win)]
    if bad:
        return False, '窗口外仍被改 %d 字节（首个 ELF 0x%X）' % (len(bad), bad[0])
    return True, '本区含声明窗口，除声明字外逐字节相同'


# ───────────────────────────── 施工 ─────────────────────────────
def do_apply(spec, base, out, meta_path, force=False):
    rep = Report('出盘：%s  ->  %s' % (base, out))
    rep.head('① 基底指纹（必须是声明的那一张基底，否则拒绝施工）')
    base_sha = sha256_file(base)
    rep.check('基底 sha256 == 声明值', base_sha == spec['base_chain'][1]['sha256'], base_sha)
    rep.check('基底尺寸 == 声明值', os.path.getsize(base) == spec['base_chain'][1]['bytes'],
              '%d B' % os.path.getsize(base))
    base_elf, lba, elf_size = read_elf_from_iso(base, spec['_elf_name'])
    base_elf_sha = hashlib.sha256(base_elf).hexdigest()
    rep.check('基底 ELF sha256 == 声明值', base_elf_sha == spec['base_chain'][1]['elf_sha256'], base_elf_sha)
    rep.check('ELF LBA/尺寸 == 声明值', (lba, elf_size) == (spec['_lba'], spec['product_identity']['elf']['bytes']),
              'LBA %d / %d B' % (lba, elf_size))
    if rep.failed:
        print('\n[拒绝] 基底指纹不符，未写任何文件。')
        return 1

    rep.head('② 施工前逐站点 / 逐 cave 断言（原字相符；cave 必须是全零区）')
    for p in spec['patches']:
        got = word_at(spec, base_elf, p['_va'])
        rep.check('%s 站点原字 %s (%s)' % (p['name'], p['old_word'], p['old_dis']), got == p['_old'],
                  '实测 %08X' % got)
        eo = elf_off(spec, p['cave']['_va'])
        blob = base_elf[eo:eo + p['cave']['bytes']]
        nz = sum(1 for b in blob if b)
        rep.check('%s cave %s 全零（%d B）' % (p['name'], p['cave']['va'], p['cave']['bytes']),
                  nz == 0, '非零字节 %d' % nz)
    if rep.failed:
        print('\n[拒绝] 基底与补丁表不匹配（可能基底已被打过补丁），未写任何文件。')
        return 1

    if os.path.exists(out) and not force:
        print('\n[拒绝] 输出已存在：%s（要覆盖请加 --force）' % out)
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(out)) or '.', exist_ok=True)
    shutil.copyfile(base, out)
    with open(out, 'r+b') as f:
        for p in spec['patches']:
            f.seek(p['_va'] - spec['_iso_of_va'])
            f.write(struct.pack('<I', p['_new']))
            f.seek(p['cave']['_va'] - spec['_iso_of_va'])
            for w in p['cave']['_words']:
                f.write(struct.pack('<I', w))
        f.flush()
        os.fsync(f.fileno())

    rep.head('③ 写后回读 + 差异窗口 + 参照区（不信任任何中间量，全部重新读盘）')
    out_elf, lba2, size2 = read_elf_from_iso(out, spec['_elf_name'])
    for p in spec['patches']:
        rep.check('%s 站点回读 == %s' % (p['name'], p['new_dis']),
                  word_at(spec, out_elf, p['_va']) == p['_new'])
        ok = all(word_at(spec, out_elf, p['cave']['_va'] + 4 * i) == w
                 for i, w in enumerate(p['cave']['_words']))
        rep.check('%s cave 回读 == 表中 %d 字' % (p['name'], len(p['cave']['_words'])), ok)
    rep.check('ELF LBA / 尺寸未变', (lba2, size2) == (lba, elf_size), 'LBA %d / %d B' % (lba2, size2))
    rep.check('ELF 头 0x1000 B 未动', base_elf[:0x1000] == out_elf[:0x1000])
    for g in spec['gates_readback']:
        va, want = int(g['va'], 16), int(g['word'], 16)
        rep.check('闸门 %s == %s' % (g['va'], g['word']), word_at(spec, out_elf, va) == want,
                  '实测 %08X' % word_at(spec, out_elf, va))
    for r in spec['must_stay_identical_regions']:
        lo, hi = int(r['va_lo'], 16), int(r['va_hi'], 16)
        a, b = elf_off(spec, lo), elf_off(spec, hi)
        ok, why = region_same(spec, base_elf, out_elf, a, b)
        rep.check('参照区未被动：%s' % r['why'], ok, why)
    runs = diff_runs(base, out)
    nb = sum(len(ob) for (_o, ob, _n) in runs)
    win = declared_windows(spec)
    inwin = all(any(lo <= o and o + len(ob) <= hi for (lo, hi) in win) for (o, ob, _n) in runs)
    touched = sum(1 for (lo, hi) in win if any(lo <= o < hi for (o, _ob, _n) in runs))
    rep.check('差异只落在声明窗口内', inwin)
    rep.check('每个声明窗口都被写到', touched == len(win), '%d / %d' % (touched, len(win)))
    rep.check('尺寸未变', os.path.getsize(out) == spec['product_identity']['bytes'])
    rep.check('差异字节数 == %d / run == %d'
              % (spec['product_identity']['diff_vs_base']['bytes'],
                 spec['product_identity']['diff_vs_base']['runs']),
              (nb, len(runs)) == (spec['product_identity']['diff_vs_base']['bytes'],
                                  spec['product_identity']['diff_vs_base']['runs']),
              '%d B / %d run' % (nb, len(runs)))

    rep.head('④ 成品身份（与交付成品逐项比对）')
    out_sha, out_md5 = sha256_file(out), md5_file(out)
    crc = xor_crc32(out_elf)
    pid = spec['product_identity']
    rep.check('sha256 == 成品', out_sha == pid['sha256'], out_sha)
    rep.check('md5 == 成品', out_md5 == pid['md5'], out_md5)
    rep.check('ELF sha256 == 成品', hashlib.sha256(out_elf).hexdigest() == pid['elf']['sha256'])
    rep.check('ELF CRC32(xor) == %s' % pid['elf']['crc32_xor'], '%08X' % crc == pid['elf']['crc32_xor'],
              '%08X  ⇒ 存档名 SLUS-20613 (%08X).01.p2s' % (crc, crc))

    if meta_path:
        m = dict(tag=os.path.splitext(os.path.basename(out))[0],
                 tool='tools/final_fix/apply_fix.py',
                 spec='tools/final_fix/fix_spec.json',
                 base_file=os.path.relpath(base), base_sha256=base_sha, base_bytes=os.path.getsize(base),
                 base_elf_sha256=base_elf_sha,
                 patches=[dict(name=p['name'], va=p['va'], iso_off=p['iso_off'], elf_off=p['elf_off'],
                               old_word=p['old_word'], new_word=p['new_word'],
                               cave_va=p['cave']['va'], cave_bytes=p['cave']['bytes'])
                          for p in spec['patches']],
                 out=os.path.abspath(out), bytes=os.path.getsize(out), sha256=out_sha, md5=out_md5,
                 elf_sha256=hashlib.sha256(out_elf).hexdigest(), elf_crc32_xor='%08X' % crc,
                 savestate_name='SLUS-20613 (%08X).01.p2s' % crc,
                 diff_runs=[dict(iso_off='0x%08X' % o, len=len(ob), old=ob.hex(), new=nb2.hex())
                            for (o, ob, nb2) in runs],
                 diff_run_count=len(runs), diff_bytes=nb, selfcheck_failed=rep.failed)
        with open(meta_path, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(m, f, ensure_ascii=False, indent=1)
        print('\n[meta] %s' % meta_path)

    print('\n[结论] %s（失败 %d 条）' % ('全部断言通过' if rep.failed == 0 else '有断言失败', rep.failed))
    if rep.failed == 0:
        print('[结论] 出盘 sha256 == 交付成品 %s  ⇒ 复现成功' % pid['sha256'])
    return 0 if rep.failed == 0 else 1


# ───────────────────────────── 校验 ─────────────────────────────
def do_verify(spec, iso, base):
    rep = Report('校验：%s' % iso)
    pid = spec['product_identity']
    rep.head('① 文件身份')
    size = os.path.getsize(iso)
    rep.check('尺寸 == 1,648,164,864 B', size == pid['bytes'], '%d B' % size)
    sha = sha256_file(iso)
    rep.check('sha256 == 成品', sha == pid['sha256'], sha)
    md5 = md5_file(iso)
    rep.check('md5 == 成品', md5 == pid['md5'], md5)
    elf, lba, elf_size = read_elf_from_iso(iso, spec['_elf_name'])
    rep.check('ELF LBA / 尺寸', (lba, elf_size) == (spec['_lba'], pid['elf']['bytes']),
              'LBA %d / %d B' % (lba, elf_size))
    rep.check('ELF sha256 == 成品', hashlib.sha256(elf).hexdigest() == pid['elf']['sha256'])
    crc = xor_crc32(elf)
    rep.check('ELF CRC32(xor) == %s' % pid['elf']['crc32_xor'], '%08X' % crc == pid['elf']['crc32_xor'],
              '%08X' % crc)

    rep.head('② 四件套是否在位（站点 + cave 逐字）')
    for p in spec['patches']:
        rep.check('%s 站点 %s == %s' % (p['name'], p['va'], p['new_dis']),
                  word_at(spec, elf, p['_va']) == p['_new'],
                  '实测 %08X' % word_at(spec, elf, p['_va']))
        ok = all(word_at(spec, elf, p['cave']['_va'] + 4 * i) == w
                 for i, w in enumerate(p['cave']['_words']))
        rep.check('%s cave %s == 表中 %d 字' % (p['name'], p['cave']['va'], len(p['cave']['_words'])), ok)
    for g in spec['gates_readback']:
        rep.check('闸门 %s == %s' % (g['va'], g['word']),
                  word_at(spec, elf, int(g['va'], 16)) == int(g['word'], 16))

    if base:
        rep.head('③ 相对基底的差异（应为 %d B / %d run，全部在声明窗口内）+ 参照区逐字节相同' % (pid['diff_vs_base']['bytes'], pid['diff_vs_base']['runs']))
        if sha256_file(base) != spec['base_chain'][1]['sha256']:
            rep.check('基底指纹 == 声明值', False, '给的 --base 不是 GR_REBUILD2400.iso')
        else:
            base_elf = read_elf_from_iso(base, spec['_elf_name'])[0]
            for why, lo, hi in region_pairs(spec):
                ok, detail = region_same(spec, base_elf, elf, lo, hi)
                rep.check('参照区未被动：%s' % why, ok, detail)
            runs = diff_runs(base, iso)
            nb = sum(len(ob) for (_o, ob, _n) in runs)
            win = declared_windows(spec)
            inwin = all(any(lo <= o and o + len(ob) <= hi for (lo, hi) in win) for (o, ob, _n) in runs)
            rep.check('差异字节数 == %d' % pid['diff_vs_base']['bytes'], nb == pid['diff_vs_base']['bytes'], '%d B' % nb)
            rep.check('差异 run 数 == %d' % pid['diff_vs_base']['runs'], len(runs) == pid['diff_vs_base']['runs'], '%d run' % len(runs))
            rep.check('差异全部在声明窗口内（窗口外 0 B）', inwin)
    else:
        rep.head('③ 相对基底差异 / 参照区（未给 --base，跳过；这些断言需要基底才能判）')

    print('\n[结论] %s（失败 %d 条）' % ('该盘就是交付成品' if rep.failed == 0 else '有断言失败', rep.failed))
    if rep.failed == 0:
        print('[结论] 全量验收结论索引见 fix_spec.json · acceptance_index / docs/REPORT_RELEASE_VERIFY.md')
    return 0 if rep.failed == 0 else 1


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='幽灵行动 PS2 汉化 2400 线 · 卡死修复四件套唯一权威工具')
    ap.add_argument('--spec', default=SPEC_PATH, help='补丁表（默认同目录 fix_spec.json）')
    ap.add_argument('--base', help='基底 ISO（GR_REBUILD2400.iso）')
    ap.add_argument('--out', help='出盘路径（apply 模式必填）')
    ap.add_argument('--meta', help='出盘 meta json 路径（默认 <out>.meta.json）')
    ap.add_argument('--force', action='store_true', help='允许覆盖已存在的 --out')
    ap.add_argument('--verify-only', action='store_true', help='只校验 --iso，不写任何文件')
    ap.add_argument('--iso', help='--verify-only 时要校验的盘')
    a = ap.parse_args()

    spec = load_spec(a.spec)

    if a.verify_only:
        if not a.iso:
            ap.error('--verify-only 需要 --iso')
        return do_verify(spec, a.iso, a.base)
    if not (a.base and a.out):
        ap.error('apply 模式需要 --base 与 --out（或改用 --verify-only --iso）')
    meta = a.meta or os.path.splitext(a.out)[0] + '.meta.json'
    return do_apply(spec, a.base, a.out, meta, force=a.force)


if __name__ == '__main__':
    sys.exit(main())
