# -*- coding: utf-8 -*-
r"""merge_zh146.py — 合并两条线：GR_ZH145 的 29 个任务名 + GR_ZH144 的 M15 `白刃`

背景：
  · GR_ZH145（另一条任务）：从 GR_ZH143 出发汉化了 29/40 个 *.MIS 的 <Name>；
    它的 M15 用的是"白刃 + 7 空格"凑长度的做法 ⇒ 标题会被顶偏。
  · GR_ZH144（本轮 v3）：只改 M15，名字 `白刃`（10 B，零填充），居中正确。

合并方式（最小侵入）：
  两个盘里 M15 的那两个 .MIS 条目 **idx / 文件偏移 / stored 完全相同**
  （GR.IMG#675 0x00E6139D0/18696、MENU.IMG#184 0x06198DC70/18539），
  所以直接把 GR_ZH144 里这两个条目的**整段字节**搬到 GR_ZH145 上，
  再把 IMG 表里这两条的 `real` 从 144 抄过来（16384 → 16377 的子流长度差）。
  其余 29 个任务名的改动一个字节都不碰。

用法: python merge_zh146.py [--a 144] [--b 145] [--out 146]
"""
import argparse
import hashlib
import os
import re
import struct
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))
sys.path.insert(0, HERE)

import tcslib                                                        # noqa: E402
import zx_lib                                                       # noqa: E402
import patch_zh144_m15_title as P                                    # noqa: E402

A_SHA = 'd50b4e720c401b529155bae343c86ae8dcb8cb60fcab7e3cc8b254113788747b'   # 144
B_SHA = 'bf269e18c5dc4d4831b174ed7e153fc1242a6aa914adb9c5915c5b9dcd58142c'   # 145
TITLE = 'M15 - 白刃'
TAG = re.compile(rb'<Name>(.*?)</Name>', re.S)


def sha(path):
    return P.hash_file(path, 'sha256')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--a', default=os.path.join(REPO, 'work', 'builds', 'GR_RELEASE',
                                                'GR_ZH144.iso'))
    ap.add_argument('--b', default=os.path.join(REPO, 'work', 'builds', 'GR_RELEASE',
                                                'GR_ZH145.iso'))
    ap.add_argument('--out', default=os.path.join(REPO, 'work', 'builds', 'GR_RELEASE',
                                                  'GR_ZH146.iso'))
    a = ap.parse_args()

    print('[1] 校验两个输入盘 …')
    sa, sb = sha(a.a), sha(a.b)
    assert sa == A_SHA, 'GR_ZH144 sha256 不符: %s' % sa
    assert sb == B_SHA, 'GR_ZH145 sha256 不符: %s' % sb
    assert os.path.getsize(a.a) == os.path.getsize(a.b)
    print('    144 = %s' % sa)
    print('    145 = %s' % sb)

    print('[2] 定位 M15 的两个条目 …')
    iso_a = tcslib.Iso(a.a)
    iso_b = tcslib.Iso(a.b)
    jobs = []
    for h in P.HITS:
        ea, ta = P.find_entry(iso_a, h)
        eb, tb = P.find_entry(iso_b, h)
        assert ta == tb and ea['idx'] == eb['idx'], (ta, tb, ea['idx'], eb['idx'])
        assert ea['iso_off'] == eb['iso_off'] and ea['stored'] == eb['stored']
        blob = iso_a.read(ea['iso_off'], ea['stored'])
        blob_b = iso_b.read(eb['iso_off'], eb['stored'])
        # 校验 144 那边解出来确实是 白刃
        dec, errs = P.decode_entry(blob)
        got = _title_from(dec)
        print('    %-9s idx=%-4d off=0x%09X stored=%d  144标题=%r  145标题=%r'
              % (ta, ea['idx'], ea['iso_off'], ea['stored'], got, _title(iso_b, eb)))
        jobs.append(dict(tag=ta, ent=ea, blob=blob,
                         diff=sum(1 for i in range(len(blob)) if blob[i] != blob_b[i])))
    iso_a.close()
    iso_b.close()
    del iso_a, iso_b

    print('[3] 复制 145 -> 146 …')
    with open(a.b, 'rb') as fi, open(a.out, 'wb') as fo:
        while True:
            chunk = fi.read(1 << 22)
            if not chunk:
                break
            fo.write(chunk)
    assert os.path.getsize(a.out) == os.path.getsize(a.b)

    print('[4] 用 144 的条目字节覆盖 146 的 M15 条目 + 抄 real …')
    with open(a.out, 'r+b') as f:
        for j in jobs:
            e = j['ent']
            f.seek(e['iso_off'])
            f.write(j['blob'])
            base_lba = tcslib.GR_LBA if j['tag'] == 'GR.IMG' else tcslib.MENU_LBA
            t = base_lba * 2048 + 0x830 + 48 * e['idx']
            f.seek(t + 4 * 7)
            f.write(struct.pack('<I', e['real']))
        f.flush()
        os.fsync(f.fileno())
    print('    M15 条目分别换了 %s 字节' % ', '.join(str(j['diff']) for j in jobs))

    print('[5] 验证 …')
    iso = tcslib.Iso(a.out)
    ok = True
    n_zh = n_en = 0
    for e in zx_lib.entries(iso, tcslib.GR_LBA):
        if not e['name'].upper().endswith('.MIS'):
            continue
        dec, errs = P.decode_entry(iso.read(e['iso_off'], e['stored']))
        m = TAG.search(dec)
        if not m:
            continue
        v = dec[m.start(1):m.end(1)]
        t, _ = tcslib.Charset().decode(v)
        zh = any('\u4e00' <= c <= '\u9fff' for c in t)
        n_zh += zh
        n_en += (not zh)
        if e['name'].startswith(('M15', 'M01_', 'M04_', 'M05_')):
            print('    %-22s %2d B  %r' % (e['name'], len(v), t))
    for h in P.HITS:
        ent, tag = P.find_entry(iso, h)
        dec, errs = P.decode_entry(iso.read(ent['iso_off'], ent['stored']))
        m = TAG.search(dec)
        good = dec[m.start(1):m.end(1)] == (b'M15 - ' + P.NEW) and all(x is None for x in errs)
        ok &= good
        print('    %-9s idx=%-4d stored=%-6d real=%-6d 解压 %d B  标题正确: %s'
              % (tag, ent['idx'], ent['stored'], ent['real'], len(dec),
                 'YES' if good else 'NO'))
    print('    GR.IMG 的 40 个 *.MIS: ZH=%d EN=%d' % (n_zh, n_en))
    iso.close()
    del iso

    print('[6] 身份 …')
    esha, ecrc = P.elf_digest(a.out)
    sz = os.path.getsize(a.out)
    print('    bytes  = %d' % sz)
    print('    sha256 = %s' % sha(a.out))
    print('    md5    = %s' % P.hash_file(a.out, 'md5'))
    print('    ELF    = %s / crc32_xor %s' % (esha, ecrc))
    ok &= (sz == os.path.getsize(a.b)) and ecrc == P.ELF_CRC_XOR and esha == P.ELF_SHA
    print('\nRESULT: %s' % ('ALL PASS' if ok else 'FAILED'))
    return 0 if ok else 1


def _title_from(dec):
    m = TAG.search(dec)
    return dec[m.start(1):m.end(1)] if m else None


def _title(iso, ent):
    dec, _ = P.decode_entry(iso.read(ent['iso_off'], ent['stored']))
    return _title_from(dec)


if __name__ == '__main__':
    sys.exit(main())
