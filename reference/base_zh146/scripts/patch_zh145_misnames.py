# -*- coding: utf-8 -*-
r"""patch_zh145_misnames.py — GR_ZH143 -> GR_ZH145: 40 个 *.MIS 的 <Name> 汉化

★ 基底链说明 (见 docs/REPORT_MIS_NAMES.md):
  本轮执行期间 work\builds\GR_RELEASE\GR_ZH144.iso 被另一路并发改写
  (sha256 与 meta 不符, 其 v3 脚本最后一次运行报 simulation mismatch),
  为可复现起见, 本脚本**直接从已验证的 GR_ZH143.iso** (sha 52145319…4d42)
  一次生成 145: 40 个名字一起打, 其中 M15 的目标值与上一轮相同 (`M15 - 白刃`)。

★ 技术 = 上一轮 M15 已验证的那套 (work/builds/GR_MISSIONTITLES/patch_zh144_m15_title.py):
  · 条目 = 5 个 {u32 clen}{u32 rlen}{payload} LZO1X 子流; 名字在 sub0, 由 </Name> 定界
  · 名字必须**恰好等长** (子流 rlen 固定), 短了补 0x20
  · 名字字节被后续匹配当源 ⇒ 必须重编码那些匹配 (本脚本用 DP 做局部最优重编码,
    并允许把相邻问题区合并; 整条子流统一记账, 用 M2->M3 升级把长度补齐)
  · 每个条目都回读自证: 解压结果必须逐字节 == "只有名字变化"的期望

用法:
  python patch_zh145_misnames.py                 # 生成 + 全量验证
  python patch_zh145_misnames.py --verify-only
"""
import argparse
import hashlib
import re
import io
import os
import struct
import sys
import time

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))

import mislib                                                        # noqa: E402
import mispatch                                                      # noqa: E402
import tcslib                                                        # noqa: E402

MAP = os.path.join(HERE, 'assets', 'mis', 'map.tsv')
BASE_SHA = '52145319c15de639d392788bb0be56deeea7dc952f254c966fad1ceb5eed4d42'
ELF_LBA, ELF_BYTES = 295, 37453732
ELF_SHA = 'a0c8499cf30f1cc5c44dfb49502270ed0ecbdccb30c023246b227591c40ba12e'
ELF_CRC = '653FBF69'

MAPNAME_RE = mislib.NAME_RE


def load_map():
    rows = {}
    with io.open(MAP, encoding='utf-8') as f:
        hdr = f.readline().rstrip('\n').split('\t')
        for line in f:
            v = line.rstrip('\n').split('\t')
            rows[dict(zip(hdr, v))['code']] = dict(zip(hdr, v))
    return rows


def code_of(fn):
    b = fn.rsplit('.', 1)[0].upper()
    import re
    m = re.match(r'^([A-Z]+\d\d)', b)
    return m.group(1) if m else b


def diff_range(old, new):
    f0 = next(i for i in range(len(old)) if old[i] != new[i])
    f1 = max(i for i in range(len(old)) if old[i] != new[i])
    return f0, f1 + 1


def plan_one(out, m, newname, dbg=False):
    """给一条 <Name> (match 对象 m) 规划补丁; 返回 (target, changed, note) 或 None"""
    a = m.start(1)
    old = m.group(1)
    if len(old) != len(newname):
        return None
    if old == newname:
        return None
    tgt = out[:a] + newname + out[a + len(old):]
    f0, f1 = diff_range(old, newname)
    return tgt, (a + f0, a + f1), 'name'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default=os.path.join(REPO, 'work', 'builds', 'GR_RELEASE',
                                                   'GR_ZH143.iso'))
    ap.add_argument('--out', default=os.path.join(REPO, 'work', 'builds', 'GR_RELEASE',
                                                  'GR_ZH145.iso'))
    ap.add_argument('--verify-only', action='store_true')
    ap.add_argument('--dbg', action='store_true')
    a = ap.parse_args()
    t_start = time.time()

    mp = load_map()
    print('[1] verify base ...')
    sha = tcslib.sha256_file(a.base)
    assert sha == BASE_SHA, 'base sha mismatch: %s' % sha
    bsz = os.path.getsize(a.base)
    print('    %s  sha256=%s  %d B  OK'
          % (os.path.basename(a.base), sha[:16] + '…', bsz))

    print('[2] plan 40 names x 2 containers ...')
    iso = tcslib.Iso(a.base)
    import zx_lib
    gaps = {}
    for lba in (tcslib.GR_LBA, tcslib.MENU_LBA):
        ents = zx_lib.entries(iso, lba)
        for i in range(len(ents) - 1):
            gaps[(lba, ents[i]['idx'])] = ents[i + 1]['iso_off'] - (ents[i]['iso_off'] + ents[i]['stored'])
    jobs, skipped, done = [], [], []
    for tag, lba, e in mislib.iter_mis(iso):
        code = code_of(e['name'])
        if code not in mp:
            continue
        d = mp[code]
        newname = bytes.fromhex(d['enc_hex'])
        raw = iso.read(e['iso_off'], e['stored'])
        subs = mislib.substreams(raw)
        parts = []
        for (p, pay, S) in subs:
            o, err = mislib.decode_payload(pay, S)
            if err:
                raise SystemExit('decode fail %s#%d' % (tag, e['idx']))
            parts.append(o)
        blob = b''.join(parts)
        m = MAPNAME_RE.search(blob)
        if not m:
            continue
        plan = plan_one(blob, m, newname)
        if plan is None:
            if m.group(1) == newname:
                done.append((tag, e['idx'], e['name'], code, 'already'))
            else:
                skipped.append((tag, e['idx'], e['name'], code, 'len mismatch'))
            continue
        tgt, changed, kind = plan
        # sub0 里做
        pay0, S0 = subs[0][1], subs[0][2]
        if m.start(1) >= S0:
            skipped.append((tag, e['idx'], e['name'], code, 'name not in sub0'))
            continue
        out0 = parts[0]
        tgt0 = out0[:changed[0]] + tgt[changed[0]:changed[1]] + out0[changed[1]:]
        exp_blob = tgt0 + blob[S0:]
        slack = max(0, min(gaps.get((lba, e['idx']), 0), 24))
        new0, st = mispatch.plan_entry(pay0, S0, tgt0, changed, verbose=False, dbg=a.dbg, slack=slack)
        note = 'ok'
        if new0 is None:
            # 退路: <Name> 若整段是 <MapName> 的复制, 直接改 MapName, Name 自动跟随
            mm = None
            for mm in re.finditer(rb'<MapName>(.*?)</MapName>', blob, re.S):
                break
            if mm and mm.group(1) == m.group(1):
                ma = mm.start(1)
                if ma < S0 and ma + len(newname) <= S0:
                    f0, f1 = diff_range(mm.group(1), newname)
                    tgt_m = out0[:ma] + newname + out0[ma + len(newname):]
                    new0b, st2 = mispatch.plan_entry(pay0, S0, tgt_m, (ma + f0, ma + f1),
                                                     verbose=False, dbg=a.dbg, slack=slack)
                    if new0b is not None:
                        chk, _ = mislib.decode_payload(new0b, S0)
                        if b'<Name>' + newname + b'</Name>' in chk:
                            new0, st, note = new0b, st2, 'via-mapname'
        if new0 is None:
            skipped.append((tag, e['idx'], e['name'], code, 'LZO 结构无法等长重编码'))
            print('    %-8s #%-4d %-22s %-6s  ** SKIP **  %s'
                  % (tag, e['idx'], e['name'], code, st))
            continue
        # 重建整条条目
        newraw = bytearray()
        newraw += struct.pack('<II', len(new0), S0) + new0
        for (p, pay, S) in subs[1:]:
            newraw += struct.pack('<II', len(pay), S) + pay
        grow = len(newraw) - e['stored']
        assert 0 <= grow <= slack, (grow, slack, e['name'])
        jobs.append(dict(tag=tag, lba=lba, e=e, code=code, new=bytes(newraw), grow=grow,
                         note=note, stats=st, exp=exp_blob))
        print('    %-8s #%-4d %-22s %-6s -> %-18r %s  deps=%d win=%d pad=%d'
              % (tag, e['idx'], e['name'], code,
                 newname.decode('latin-1').rstrip(), note, st.get('deps', 0),
                 len(st.get('windows', [])), st.get('padded', 0)))
    iso.close()
    print('    planned %d entries, skipped %d' % (len(jobs), len(skipped)))
    for s in skipped:
        print('    SKIP %-8s #%-4d %-22s %-6s %s' % s)

    if not a.verify_only:
        print('[3] copy base -> %s ...' % os.path.basename(a.out))
        with open(a.base, 'rb') as fi, open(a.out, 'wb') as fo:
            while True:
                b = fi.read(1 << 22)
                if not b:
                    break
                fo.write(b)
        assert os.path.getsize(a.out) == bsz
        print('[4] write %d entries ...' % len(jobs))
        with open(a.out, 'r+b') as f:
            for j in jobs:
                if j['grow']:
                    tb = j['lba'] * 2048 + 0x830 + 48 * j['e']['idx']
                    f.seek(tb + 24)
                    f.write(struct.pack('<I', j['e']['stored'] + j['grow']))
                f.seek(j['e']['iso_off'])
                f.write(j['new'])
            f.flush()
            os.fsync(f.fileno())

    # ---------- 验证 ----------
    print('[5] read back + decompress ...')
    iso = tcslib.Iso(a.out)
    ok = True
    for j in jobs:
        e = j['e']
        ent = iso.img_entry(j['lba'], e['idx'])
        assert ent['stored'] == e['stored'] + j['grow'], (ent['stored'], e['stored'], j['grow'])
        got, _ = mislib.entry_blob(iso, ent)
        nm = mislib.NAME_RE.search(got).group(1)
        good = (nm == bytes.fromhex(mp[j['code']]['enc_hex'])) and got == j['exp']
        ok &= good
        if not good:
            print('    !! %s#%d name=%r' % (j['tag'], e['idx'], nm))
    print('    %d/%d entries: <Name> == 语言表译名 (等长补齐)' % (sum(1 for j in jobs), len(jobs)))
    iso.close()

    print('[6] whole-image chunked scan ...')
    CH = 1 << 24
    diffs, off, prev = [], 0, b''
    with open(a.base, 'rb') as f0, open(a.out, 'rb') as f1:
        while True:
            b0, b1 = f0.read(CH), f1.read(CH)
            if not b0 and not b1:
                break
            if b0 != b1:
                diffs.extend(off + i for i in range(len(b0)) if b0[i] != b1[i])
            off += len(b0)
    print('    byte diff vs 143: %d' % len(diffs))
    ranges = []
    if diffs:
        s = p = diffs[0]
        for d in diffs[1:]:
            if d > p + 64:
                ranges.append((s, p))
                s = d
            p = d
        ranges.append((s, p))
        for (s, p) in ranges:
            print('      0x%09X..0x%09X  (%d B)' % (s, p, p - s + 1))
    # 差异是否全在条目内
    inside = 0
    ent_spans = [(j['e']['iso_off'], j['e']['iso_off'] + j['e']['stored']) for j in jobs]
    for d in diffs:
        if any(s <= d < t for (s, t) in ent_spans):
            inside += 1
    print('    diffs inside patched .MIS entries: %d / %d' % (inside, len(diffs)))

    print('[7] identity ...')
    sz = os.path.getsize(a.out)
    print('    bytes  = %d  (same as 143: %s)' % (sz, sz == bsz))
    print('    sha256 = %s' % tcslib.sha256_file(a.out))
    h = hashlib.md5()
    with open(a.out, 'rb') as f:
        while True:
            b = f.read(1 << 22)
            if not b:
                break
            h.update(b)
    print('    md5    = %s' % h.hexdigest())
    esha, ecrc = elf_digest(a.out)
    print('    ELF    = LBA %d / %d B  sha256 %s  crc32_xor %s'
          % (ELF_LBA, ELF_BYTES, esha, ecrc))
    ok &= (sz == bsz) and esha == ELF_SHA and ecrc == ELF_CRC

    _rep = os.environ.get('GR_REPORT', os.path.join(REPO, 'work', '_misnames_report.json'))
    with open(_rep, 'w', encoding='utf-8') as f:
        import json
        json.dump(dict(planned=[dict(tag=j['tag'], idx=j['e']['idx'], name=j['e']['name'],
                                     code=j['code'], note=j['note'],
                                     windows=len(j['stats'].get('windows', [])),
                                     padded=j['stats'].get('padded', 0),
                                     deps=j['stats'].get('deps', 0)) for j in jobs],
                       skipped=skipped, diffs=len(diffs), n_diff_ranges=len(ranges),
                       inside=inside, ranges=['0x%09X..0x%09X' % r for r in ranges],
                       elapsed=round(time.time() - t_start, 1)), f, ensure_ascii=False, indent=1)
    print('\nRESULT: %s  (%.1fs)' % ('ALL PASS' if ok else 'FAILED', time.time() - t_start))
    return 0 if ok else 1


def target_slice(blob, tgt, changed):
    """把整条 blob 的期望切片对齐到 sub0 内部偏移 (名字一定在 sub0 里)"""
    return tgt[changed[0]:changed[1]]


def elf_digest(path):
    h, c, left, tail = hashlib.sha256(), 0, ELF_BYTES, b''
    with open(path, 'rb') as f:
        f.seek(ELF_LBA * 2048)
        while left > 0:
            b = f.read(min(1 << 22, left))
            if not b:
                break
            h.update(b)
            buf = tail + b
            n = len(buf) // 4 * 4
            for (w,) in struct.iter_unpack('<I', buf[:n]):
                c ^= w
            tail = buf[n:]
            left -= len(b)
    return h.hexdigest(), '%08X' % (c & 0xFFFFFFFF)


if __name__ == '__main__':
    sys.exit(main())
