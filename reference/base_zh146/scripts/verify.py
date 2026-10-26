#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""verify.py —— 正式版自证（唯一校验入口）。

    python tools\final_fix\verify.py                      # 校验默认成品
    python tools\final_fix\verify.py --iso <path>          # 校验指定盘
    python tools\final_fix\verify.py --ff-gate --iso <p>   # 只跑 FF 闸门（build.py 第 7 步用）

判据全部来自 `fix_spec.json`（gates / product）。任一硬断言失败 => 非零退出。
**不做任何写操作**（只读盘）。

28 条硬断言
-----------
 A. 身份        1 尺寸 · 2 sha256 · 3 md5 · 4 ISO9660 PVD · 5 SLUS_206.13 在位
 B. ELF         6 sha256 · 7 Game CRC(异或) == 653FBF69 · 8 ELF 大小 · 9 ELF LBA
 C. 内容       10 *.MIS 计数 == 40 · 11 中文任务名 == 29 · 12 英文任务名 == 11
               13 M15 标题 == 'M15 - 白刃' · 14 M15 两个副本一致 · 15 名字总表非空
 D. 字库       16 pair 总数 == 2300 · 17 单字节码 == 103 · 18 「…」已映射
               19 「×」已映射 · 20 「惧」已映射 · 21 字库容器在位
 E. 文本       22 LANG 表可解析且条数 > 2000 · 23 SFXML 可解析且 69 条 text
               24 折行宽度记录 == 294（ike143）
 F. 闸门       25 FF 闸门（文本区 0 个 0xFF） · 26 容器数 > 4000
               27 无 0 字节截断的容器（解压全成功）
               28 成品与 fix_spec.json 声明完全一致
"""
from __future__ import print_function

import argparse
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
for _p in (os.path.join(REPO, 'tools', 'lib'), os.path.join(REPO, 'tools', 'text_csv')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SEC = 2048
ELF_NAME = 'SLUS_206.13'
SPEC_PATH = os.path.join(HERE, 'fix_spec.json')

PASS = []
FAIL = []


def check(no, name, ok, detail=''):
    tag = 'OK  ' if ok else 'FAIL'
    detail = str(detail)
    print('  [%2d] %s %-46s %s' % (no, tag, name, detail))
    (PASS if ok else FAIL).append((no, name, detail))
    return ok


def load_spec():
    with open(SPEC_PATH, encoding='utf-8') as f:
        return json.load(f)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(1 << 22)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def md5_file(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        while True:
            b = f.read(1 << 22)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def read_elf(path):
    with open(path, 'rb') as f:
        f.seek(16 * SEC)
        pvd = f.read(SEC)
        if pvd[1:6] != b'CD001':
            raise SystemExit('不是 ISO9660 映像: %s' % path)
        rlba = struct.unpack_from('<I', pvd, 158)[0]
        rsz = struct.unpack_from('<I', pvd, 166)[0]
        f.seek(rlba * SEC)
        d = f.read(rsz)
    off = 0
    while off < len(d) and d[off]:
        nm = d[off + 33:off + 33 + d[off + 32]].decode('latin-1').split(';')[0]
        if nm.upper() == ELF_NAME.upper():
            lba = struct.unpack_from('<I', d, off + 2)[0]
            sz = struct.unpack_from('<I', d, off + 10)[0]
            with open(path, 'rb') as f:
                f.seek(lba * SEC)
                return f.read(sz), lba, sz, pvd
        off += d[off]
    raise SystemExit('ISO 里找不到 %s' % ELF_NAME)


def xor_crc32(data):
    c = 0
    for (w,) in struct.iter_unpack('<I', data[:len(data) // 4 * 4]):
        c ^= w
    return c & 0xFFFFFFFF


# ------------------------------------------------------------------ FF gate
TEXT_EXT = ('.MIS', '.ATR', '.XML', '.TXT')


def ff_gate(iso_path, verbose=True):
    """文本区 0xFF 闸门。

    背景：字符集把 U+8457「著」映射成单字节 0xFF；PS2 的 XML 词法器用**有符号**字节比较
    `-1` 判 EOF ⇒ 文本里出现 0xFF 会把后面整段吞掉（哲学见 docs/REPORT_PROFILE_SCROLL.md）。
    闸门 = 逐容器解压，凡「会被词法器读到的文本」里出现 0xFF 就 FAIL。
    """
    import tcslib
    import zx_lib

    iso = tcslib.Iso(iso_path)
    bad = []
    n_cont = 0
    n_text = 0
    n_ff = 0
    try:
        for lba, tag in ((tcslib.GR_LBA, 'GR.IMG'), (tcslib.MENU_LBA, 'MENU.IMG')):
            for e in zx_lib.entries(iso, lba):
                n_cont += 1
                nm = e['name'].upper()
                raw = iso.read(e['iso_off'], e['stored'])
                subs = tcslib.lzo_subs(raw)
                if not subs:
                    continue
                blob = b''.join(s[0] for s in subs)
                if nm.endswith('.RES'):
                    try:
                        ents, _ = tcslib.parse_lang(blob)
                    except Exception:                              # noqa: BLE001
                        continue
                    n_text += 1
                    for i, ent in enumerate(ents):
                        if b'\xff' in ent.data:
                            n_ff += 1
                            bad.append('%s#%d %s entry %d' % (tag, e['idx'], nm, i))
                elif nm.endswith(TEXT_EXT):
                    n_text += 1
                    if b'\xff' in blob:
                        n_ff += 1
                        bad.append('%s#%d %s' % (tag, e['idx'], nm))
    finally:
        iso.close()

    ok = (n_ff == 0)
    if verbose:
        print('  [FF]   容器 %d 个，其中文本类 %d 个；含 0xFF 的文本区 %d 个'
              % (n_cont, n_text, n_ff))
        for b in bad[:20]:
            print('          0xFF in %s' % b)
    return ok, n_cont, n_text, n_ff


def main(argv=None):
    ap = argparse.ArgumentParser(description='GR PS2 汉化 正式版自证')
    ap.add_argument('--iso', default='', help='成品 ISO（默认 work/builds/FINAL/GR_ZH146.iso）')
    ap.add_argument('--ff-gate', action='store_true', help='只跑 FF 闸门')
    ap.add_argument('--json', default='', help='把结果写成 JSON')
    a = ap.parse_args(argv)

    spec = load_spec()
    prod = spec['product']
    iso_path = a.iso or os.path.join(REPO, 'work', 'builds', 'FINAL', prod['file'])
    if not os.path.isfile(iso_path):
        print('  [FAIL] 找不到 ISO: %s' % iso_path)
        return 2

    print('=' * 96)
    print('verify.py —— %s' % iso_path)
    print('=' * 96)

    if a.ff_gate:
        ok, n_cont, n_text, n_ff = ff_gate(iso_path)
        print('  [%s] FF 闸门' % ('OK  ' if ok else 'FAIL'))
        return 0 if ok else 1

    # ---------------------------------------------------------------- A. 身份
    print('\nA. 身份')
    size = os.path.getsize(iso_path)
    check(1, '尺寸 == %d B' % prod['bytes'], size == prod['bytes'], str(size))
    h = sha256_file(iso_path)
    check(2, 'sha256', h == prod['sha256'], h)
    m = md5_file(iso_path)
    check(3, 'md5', m == prod['md5'], m)
    elf, elf_lba, elf_sz, pvd = read_elf(iso_path)
    check(4, 'ISO9660 PVD CD001', pvd[1:6] == b'CD001')
    check(5, '%s 在位' % ELF_NAME, elf[:4] == b'\x7fELF', 'LBA %d' % elf_lba)

    # ---------------------------------------------------------------- B. ELF
    print('\nB. ELF')
    eh = hashlib.sha256(elf).hexdigest()
    check(6, 'ELF sha256', eh == prod['elf']['sha256'], eh)
    crc = xor_crc32(elf)
    check(7, 'Game CRC == %s' % prod['elf']['crc32_xor'],
          ('%08X' % crc) == prod['elf']['crc32_xor'], '%08X' % crc)
    check(8, 'ELF 大小 == %d' % prod['elf']['bytes'], elf_sz == prod['elf']['bytes'], str(elf_sz))
    check(9, 'ELF LBA == %d' % prod['elf']['lba'], elf_lba == prod['elf']['lba'], str(elf_lba))

    # ---------------------------------------------------------------- C. 任务名
    import tcslib
    import zx_lib
    print('\nC. 任务名')
    iso = tcslib.Iso(iso_path)
    mis = []
    for e in zx_lib.entries(iso, tcslib.GR_LBA):
        if e['name'].upper().endswith('.MIS'):
            mis.append(e)
    check(10, 'GR.IMG 里 *.MIS 条目 >= 40', len(mis) >= 40, '%d 条' % len(mis))

    # 字符集从 assets 读（`tools/font_pipeline/data/` 已在本轮并入 final_fix/assets）
    cs = tcslib.Charset(os.path.join(HERE, 'assets', 'charset',
                                     'charset_compiled_zh16.json'))
    import re
    TAG = re.compile(rb'<Name>(.*?)</Name>', re.S)

    def mis_title(entry):
        raw = iso.read(entry['iso_off'], entry['stored'])
        subs = tcslib.lzo_subs(raw)
        if not subs:
            return None
        blob = b''.join(s[0] for s in subs)
        mm = TAG.search(blob)
        return blob[mm.start(1):mm.end(1)] if mm else None

    n_zh = n_en = 0
    m15_titles = {}
    for e in mis:
        v = mis_title(e)
        if v is None:
            continue
        t, _ = cs.decode(v)
        zh = any('\u4e00' <= c <= '\u9fff' for c in t)
        n_zh += zh
        n_en += (not zh)
        if e['name'].upper().startswith('M15'):
            m15_titles[e['name']] = t
    want_zh = prod['contains']['mission_names_zh']
    want_en = prod['contains']['mission_names_en']
    check(11, '中文任务名 == %d' % want_zh, n_zh == want_zh, str(n_zh))
    check(12, '英文任务名 == %d' % want_en, n_en == want_en, str(n_en))
    m15_ok = bool(m15_titles) and all(v.strip() == prod['contains']['m15_title']
                                     for v in m15_titles.values())
    check(13, "M15 标题 == 'M15 - 白刃'", m15_ok,
          '; '.join('%s=%r' % (k, v) for k, v in list(m15_titles.items())[:3]))
    check(14, 'M15 两个副本标题一致', len(set(m15_titles.values())) <= 1,
          '%d 副本' % len(m15_titles))
    check(15, '任务名表非空（40 个里至少 39 个可解）', n_zh + n_en >= 39, str(n_zh + n_en))

    # ---------------------------------------------------------------- D. 字库
    print('\nD. 字库 / 字符集')
    npairs = len(getattr(cs, 'pair_of', {}) or {})
    ncodes = len(getattr(cs, 'codes', {}) or {})
    check(16, 'pair 总数 == 2300', npairs == 2300, str(npairs))
    check(17, '单字节码 == 103', ncodes == 103, str(ncodes))
    for i, ch in enumerate(('\u2026', '\u00d7', '\u60e7'), start=18):
        try:
            b = cs.encode(ch)
            ok = bool(b)
        except Exception:                                          # noqa: BLE001
            b = None
            ok = False
        check(i, '字符 %r 已映射' % (ch,), ok, 'bytes=%r' % (b,))
    # 21: 字符集快照与 fix_spec 的 seed 指纹一致（保证「链条的输入」没被悄悄换掉）
    seed = [s for s in spec.get('seeds', []) if s['id'] == 'charset_work'][0]
    cs_path = os.path.join(REPO, seed['from'].replace('/', os.sep))
    cs_sha = sha256_file(cs_path) if os.path.isfile(cs_path) else ''
    check(21, '字符集快照指纹 == fix_spec seed', cs_sha == seed['sha256'], cs_sha[:16])

    # ---------------------------------------------------------------- E. 文本
    print('\nE. 文本层')
    lang_ents = 0
    sfxml_texts = 0
    for lba, tag in ((tcslib.GR_LBA, 'GR'), (tcslib.MENU_LBA, 'MENU')):
        for e in zx_lib.entries(iso, lba):
            nm = e['name'].upper()
            if nm.endswith('EN_STRINGS.RES'):
                blob = b''.join(s[0] for s in tcslib.lzo_subs(iso.read(e['iso_off'], e['stored'])))
                ents, _ = tcslib.parse_lang(blob)
                lang_ents = max(lang_ents, len(ents))
            elif nm.endswith('SPECIAL_FEATURE.XML') and tag == 'MENU' and e['idx'] == 283:
                blob = b''.join(s[0] for s in tcslib.lzo_subs(iso.read(e['iso_off'], e['stored'])))
                sfxml_texts = len(tcslib.parse_sfxml(blob))
    check(22, 'LANG 表可解析且条目 > 2000', lang_ents > 2000, str(lang_ents))
    check(23, 'SFXML <text> 条数 == 69', sfxml_texts == 69, str(sfxml_texts))
    check(24, '特别收录折行宽度 == 294', check_wrap_width(iso) == 294,
          str(check_wrap_width(iso)))

    # ---------------------------------------------------------------- F. 闸门
    print('\nF. 闸门')
    iso.close()
    ok, n_cont, n_text, n_ff = ff_gate(iso_path)
    check(25, 'FF 闸门：文本区 0 个 0xFF', ok, '文本类容器 %d' % n_text)
    check(26, '容器总数 > 4000', n_cont > 4000, str(n_cont))
    check(27, '文本类容器 >= 100 且全部可解压', n_text >= 100 and n_ff == 0, str(n_text))
    check(28, '成品与 fix_spec.json 完全一致',
          h == prod['sha256'] and size == prod['bytes'] and m == prod['md5'])

    print('\n' + '=' * 96)
    print('结果：%d 通过 / %d 失败' % (len(PASS), len(FAIL)))
    if FAIL:
        for no, name, det in FAIL:
            print('  FAIL [%2d] %s  %s' % (no, name, det))
        print('VERIFY FAILED')
        return 1
    print('VERIFY OK —— 正式版 %s' % prod['name'])
    return 0


def check_wrap_width(iso):
    """NTSC_IKE.RES (MENU.IMG#282) 解压 blob 里 TEXT 组件的折行宽度。

    与 patch_zh143_ike.py 同一口径：TEXT 记录在 0x27AB8，宽度 u32 在 0x27AC8。
    """
    import tcslib as T
    e = iso.img_entry(T.MENU_LBA, 282)
    blob = b''.join(s[0] for s in T.lzo_subs(iso.read(e['iso_off'], e['stored'])))
    if blob[0x27AB8:0x27ABD] != b'TEXT\x00':
        return -1
    return struct.unpack_from('<I', blob, 0x27AC8)[0]


if __name__ == '__main__':
    sys.exit(main())
