# -*- coding: utf-8 -*-
r"""patch_zh146.py — GR_ZH143 -> GR_ZH146: 40 个任务名 **可变长度、零填充** 汉化

两容器各一份 (GR.IMG / MENU.IMG), 共 80 个条目。

做法 (docs/REPORT_MISNAMES_FINAL.md §B):
  · sub0 解压 → 把 `<Name>` (DP01-05 还有同值的 `<MapName>`) 换成语言表里的中文名,
    **不加空格, 长度可变** (变短);
  · 名字所在窗口用 DP 以最小字节数重新编码 (状态机与 lz77_decode 口径一致);
  · "源在改动区前、目标在改动区后"的匹配 back 整体平移 (+delta), 其余逐个校验/重指,
    找不到等值源就在附近用 DP 局部重编码;
  · 载荷长度**精确补回原值**: 反优化 (匹配→等值字面量) 加长、局部窗口找省 / 尾裁剪缩短;
  · 因此 sub1..N 的文件偏移、条目 `stored` 全不变, 只改 sub0 的 rlen 与条目 real。

用法:
  python patch_zh146.py --all                 # 规划 + 出盘 + 分段落盘 + 全量验证
  python patch_zh146.py --plan-only           # 只规划, 打印逐任务表
  python patch_zh146.py --verify-only         # 对已存在的 146 做全量验证
"""
import argparse
import hashlib
import io
import json
import os
import re
import struct
import sys
import time

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))

import lzokit as mislib                                            # noqa: E402
import misvar                                                      # noqa: E402
import tcslib                                                      # noqa: E402
import zxshim as zx_lib                                                      # noqa: E402
from lz77_decode import lzo1x_decompress                           # noqa: E402

REL = os.path.join(REPO, 'work', 'builds', 'GR_RELEASE')
BASE = os.environ.get('GR_BASE', os.path.join(REL, 'GR_ZH143.iso'))
OUT = os.environ.get('GR_OUT', os.path.join(REL, 'GR_ZH146.iso'))
MAP = os.path.join(HERE, 'assets', 'mis', 'map.tsv')
OUTDIR = os.environ.get('GR_REPORT_DIR', os.path.join(HERE, 'out'))

BASE_SHA = '52145319c15de639d392788bb0be56deeea7dc952f254c966fad1ceb5eed4d42'
ELF_LBA, ELF_BYTES = 295, 37453732
ELF_SHA = 'a0c8499cf30f1cc5c44dfb49502270ed0ecbdccb30c023246b227591c40ba12e'
ELF_CRC = '653FBF69'
TAB_OFF, TAB_STEP = 0x830, 48
NAME_RE = re.compile(rb'<Name>(.*?)</Name>', re.S)
MAPNAME_RE = re.compile(rb'<MapName>(.*?)</MapName>', re.S)
# 上一轮因"等长装不下"跳过的 11 个
SKIPPED_BEFORE = ['D02', 'DP02', 'M01', 'M02', 'M06', 'T02', 'T03', 'T07',
                  'TAC03', 'TAC04', 'TAC05']


def load_map():
    mp, order = {}, []
    with io.open(MAP, encoding='utf-8') as f:
        hdr = f.readline().rstrip('\n').split('\t')
        for line in f:
            d = dict(zip(hdr, line.rstrip('\n').split('\t')))
            full = bytes.fromhex(d['enc_hex'])
            pad = int(d['pad'])
            d['zh'] = full[:len(full) - pad]
            d['pad'] = pad
            mp[d['code']] = d
            order.append(d['code'])
    return mp, order


def code_of(fn):
    b = fn.rsplit('.', 1)[0].upper()
    m = re.match(r'^([A-Z]+\d\d)', b)
    return m.group(1) if m else b


def build_expected(blob, regions):
    out = bytearray()
    pos = 0
    for (a, b, nb) in regions:
        out += blob[pos:a]
        out += nb
        pos = b
    out += blob[pos:]
    return bytes(out)


def base_entries(iso, mp):
    """→ {code: [(tag, lba, e, old_name)]}"""
    info = {}
    for tag, lba, e in mislib.iter_mis(iso):
        code = code_of(e['name'])
        if code not in mp:
            continue
        blob, _ = mislib.entry_blob(iso, e)
        m = NAME_RE.search(blob)
        info.setdefault(code, []).append((tag, lba, e, m.group(1) if m else None))
    return info


def plan_job(iso, tag, lba, e, mp):
    """规划一个条目; 返回 job dict (含 newraw / expected / 统计)"""
    code = code_of(e['name'])
    zh = mp[code]['zh']
    raw = iso.read(e['iso_off'], e['stored'])
    subs = mislib.substreams(raw)
    parts = []
    for (p, pay, S) in subs:
        o, err = mislib.decode_payload(pay, S)
        if err:
            raise misvar.PlanError('decode %s#%d: %s' % (tag, e['idx'], err))
        parts.append(o)
    blob = b''.join(parts)
    pay0, S0 = subs[0][1], subs[0][2]
    m = NAME_RE.search(parts[0])
    if not m:
        raise misvar.PlanError('no <Name> in sub0')
    if m.group(1) == zh:
        return None                       # 已是目标值 (幂等)
    regions = []
    mm = MAPNAME_RE.search(parts[0])
    if mm and mm.group(1) == m.group(1):
        regions.append((mm.start(1), mm.end(1), zh))
    regions.append((m.start(1), m.end(1), zh))
    regions.sort()
    old_name = m.group(1)
    t0 = time.time()
    plan = misvar.plan_entry(pay0, S0, parts[0], regions)
    target = plan['target']
    newpay = plan['newpay']
    assert len(newpay) == len(pay0)
    newraw = struct.pack('<II', len(newpay), len(target)) + newpay
    for (p, pay, S) in subs[1:]:
        newraw += struct.pack('<II', len(pay), S) + pay
    assert len(newraw) == e['stored'], (len(newraw), e['stored'])
    exp = build_expected(blob, regions)
    assert exp[:len(target)] == target
    real_new = e['real'] - (S0 - len(target))
    return dict(tag=tag, lba=lba, idx=e['idx'], file=e['name'], code=code,
                iso_off=e['iso_off'], stored=e['stored'], real=e['real'],
                real_new=real_new, S0=S0, rlen_new=len(target),
                clen=len(newpay), new=newraw, expected=exp, zh=zh,
                old_name=old_name, regions=regions, n_occ=len(regions),
                stats=plan['stats'], notes=plan['notes'],
                secs=round(time.time() - t0, 2))


def apply_job(f, job):
    f.seek(job['iso_off'])
    f.write(job['new'])
    tb = job['lba'] * 2048 + TAB_OFF + TAB_STEP * job['idx']
    f.seek(tb + 28)
    f.write(struct.pack('<I', job['real_new']))


def verify_job(iso, job):
    """从盘上回读该条目: 解压 == expected; 旧名 0 处; stored/real 正确"""
    ent = iso.img_entry(job['lba'], job['idx'])
    if ent['stored'] != job['stored']:
        return 'stored %d != %d' % (ent['stored'], job['stored'])
    if ent['real'] != job['real_new']:
        return 'real %d != %d' % (ent['real'], job['real_new'])
    raw = iso.read(ent['iso_off'], ent['stored'])
    if raw != job['new']:
        return 'raw bytes differ'
    blob, _ = mislib.entry_blob(iso, ent)
    if blob != job['expected']:
        return 'decoded blob differs (len %d vs %d)' % (len(blob), len(job['expected']))
    nm = NAME_RE.search(blob).group(1)
    if nm != job['zh']:
        return 'name %r != %r' % (nm, job['zh'])
    if job['old_name'] in blob:
        return 'old name residue in entry'
    return None


def hash_file(path, algo, buf=1 << 22):
    h = hashlib.new(algo)
    with open(path, 'rb') as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


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


def diff_scan(base, out, patched_spans, table_spans):
    CH = 1 << 24
    diffs, off = [], 0
    with open(base, 'rb') as f0, open(out, 'rb') as f1:
        while True:
            b0, b1 = f0.read(CH), f1.read(CH)
            if not b0 and not b1:
                break
            if b0 != b1:
                diffs.extend(off + i for i in range(len(b0)) if b0[i] != b1[i])
            off += len(b0)
    ranges = []
    if diffs:
        s = p = diffs[0]
        for d in diffs[1:]:
            if d > p + 64:
                ranges.append((s, p))
                s = d
            p = d
        ranges.append((s, p))

    def in_spans(d, spans):
        for (a, b) in spans:
            if a <= d < b:
                return True
        return False

    in_ent = sum(1 for d in diffs if in_spans(d, patched_spans))
    in_tab = sum(1 for d in diffs if in_spans(d, table_spans))
    return diffs, ranges, in_ent, in_tab, len(diffs) - in_ent - in_tab


def residue_scan(path, needles):
    CH = 1 << 20
    counts = {n: 0 for n in needles}
    maxlen = max(len(n) for n in needles)
    prev = b''
    with open(path, 'rb') as f:
        while True:
            b = f.read(CH)
            if not b:
                break
            buf = prev + b
            base_i = len(prev)
            for n in needles:
                start = 0
                while True:
                    k = buf.find(n, start)
                    if k < 0:
                        break
                    if k + len(n) > base_i:
                        counts[n] += 1
                    start = k + 1
            prev = buf[-(maxlen - 1):]
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--plan-only', action='store_true')
    ap.add_argument('--verify-only', action='store_true')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--batch', type=int, default=5, help='每批任务数 (落盘粒度)')
    ap.add_argument('--base', default=None, help='基盘 (默认 GR_ZH143.iso)')
    ap.add_argument('--out', default=None, help='出盘 (默认 GR_ZH146.iso)')
    ap.add_argument('--report-dir', default=None, help='报告目录')
    a = ap.parse_args()
    global BASE, OUT, OUTDIR
    if a.base:
        BASE = a.base
    if a.out:
        OUT = a.out
    if a.report_dir:
        OUTDIR = a.report_dir
    os.makedirs(OUTDIR, exist_ok=True)
    t_start = time.time()

    mp, order = load_map()
    print('[1] 基盘校验')
    sha = hash_file(BASE, 'sha256')
    print('    %s  sha256=%s  %d B  %s'
          % (os.path.basename(BASE), sha, os.path.getsize(BASE),
             'OK' if sha == BASE_SHA else '** MISMATCH **'))
    assert sha == BASE_SHA

    if a.verify_only:
        return verify_all(mp, order, t_start)

    print('[2] 规划 40 任务 × 2 容器 (共 80 条目)')
    iso = tcslib.Iso(BASE)
    info = base_entries(iso, mp)
    missing = [c for c in order if c not in info]
    print('    找到 %d 个 code; 缺: %r' % (len(info), missing))
    jobs, failures = [], []
    for code in order:
        for (tag, lba, e, _old) in info.get(code, []):
            try:
                j = plan_job(iso, tag, lba, e, mp)
            except Exception as ex:                                # noqa: BLE001
                failures.append(dict(code=code, tag=tag, idx=e['idx'], file=e['name'],
                                     err='%s: %s' % (type(ex).__name__, ex)))
                print('    %-6s %-9s #%-4d ** FAIL ** %s: %s'
                      % (code, tag, e['idx'], type(ex).__name__, ex))
                continue
            if j is not None:
                jobs.append(j)
    iso.close()
    print('    规划成功 %d 条目 (%d 个任务失败)'
          % (len(jobs), len(set(f['code'] for f in failures))))

    dump_report(jobs, failures, mp, order)
    if a.plan_only:
        print_table(jobs, failures)
        return 0 if not failures else 1

    # ---- 出盘 ----
    print('[3] 复制基盘 -> %s' % os.path.basename(OUT))
    if os.path.exists(OUT) and not a.force:
        raise SystemExit('%s 已存在; 用 --force 重新生成' % os.path.basename(OUT))
    with open(BASE, 'rb') as fi, open(OUT, 'wb') as fo:
        while True:
            b = fi.read(1 << 22)
            if not b:
                break
            fo.write(b)
    assert os.path.getsize(OUT) == os.path.getsize(BASE)

    # ---- 分段落盘 (每 batch 个任务一批) ----
    done = []
    with open(OUT, 'r+b') as f:
        for n, code in enumerate(order):
            batch = [j for j in jobs if j['code'] == code]
            for j in batch:
                apply_job(f, j)
            f.flush()
            os.fsync(f.fileno())
            done.extend(batch)
            if (n + 1) % a.batch == 0 or n == len(order) - 1:
                iso2 = tcslib.Iso(OUT)
                bad = []
                for j in done:
                    err = verify_job(iso2, j)
                    if err:
                        bad.append((j['code'], j['tag'], j['idx'], err))
                iso2.close()
                codes_done = sorted(set(j['code'] for j in done))
                print('    [落盘自检] 已写 %2d 条目 / %2d 任务 (%s..%s) 回读错误: %d'
                      % (len(done), len(codes_done), codes_done[0], codes_done[-1],
                         len(bad)))
                for b in bad:
                    print('      !! %s %s #%d: %s' % b)
                if bad:
                    return 2

    print_table(jobs, failures)
    return verify_all(mp, order, t_start)


def dump_report(jobs, failures, mp, order):
    """把逐条目结果写 out/report_zh146.json + out/map_final.tsv"""
    rows = []
    for j in sorted(jobs, key=lambda x: (x['tag'], x['idx'])):
        st = j['stats']
        rows.append(dict(code=j['code'], container=j['tag'], idx=j['idx'],
                         file=j['file'], old_name=j['old_name'].decode('latin-1'),
                         old_len=len(j['old_name']), new_hex=j['zh'].hex(),
                         new_len=len(j['zh']), pad=0,
                         stored=j['stored'], real=j['real'], real_new=j['real_new'],
                         rlen_sub0_old=j['S0'], rlen_sub0_new=j['rlen_new'],
                         clen=j['clen'], window=st.get('window'),
                         fixed=st.get('fixed'), natural_need=st.get('natural_need'),
                         ops=st.get('ops', []), secs=j['secs']))
    data = dict(base='GR_ZH143.iso', base_sha256=BASE_SHA,
                out='GR_ZH146.iso', entries=len(rows), missions=len(order),
                skipped_before=SKIPPED_BEFORE, rows=rows, failures=failures)
    with io.open(os.path.join(OUTDIR, 'report_zh146.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    with io.open(os.path.join(OUTDIR, 'map_final.tsv'), 'w', encoding='utf-8',
                 newline='\n') as f:
        f.write('code\tcontainer\tidx\tfile\told\told_len\tnew_hex\tnew_len\tpad\t'
                'stored\treal\treal_new\trlen_old\trlen_new\tclen\twindow\tfixed\tneed\n')
        for r in rows:
            f.write('%s\t%s\t%d\t%s\t%s\t%d\t%s\t%d\t0\t%d\t%d\t%d\t%d\t%d\t%d\t%s\t%s\t%s\n'
                    % (r['code'], r['container'], r['idx'], r['file'], r['old_name'],
                       r['old_len'], r['new_hex'], r['new_len'], r['stored'], r['real'],
                       r['real_new'], r['rlen_sub0_old'], r['rlen_sub0_new'], r['clen'],
                       r['window'], r['fixed'], r['natural_need']))
    print('    [报告] out/report_zh146.json + out/map_final.tsv (%d 行)' % len(rows))


def print_table(jobs, failures):
    print('\n[逐任务表]')
    print('%-6s %-9s %-6s %-22s %-28s %-28s %-5s %-5s %s'
          % ('code', 'tag', 'idx', 'file', 'old', 'new', 'oldB', 'newB', 'stored/real'))
    for j in sorted(jobs, key=lambda x: x['iso_off']):
        print('%-6s %-9s #%-5d %-22s %-28r %-28r %-5d %-5d %d/%d->%d'
              % (j['code'], j['tag'], j['idx'], j['file'],
                 j['old_name'], j['zh'], len(j['old_name']), len(j['zh']),
                 j['stored'], j['real'], j['real_new']))
    if failures:
        print('\n[失败]')
        for f in failures:
            print('  %-6s %-9s #%-4d %-22s %s'
                  % (f['code'], f['tag'], f['idx'], f['file'], f['err']))


def verify_all(mp, order, t_start):
    print('\n[4] 全量验证 %s' % os.path.basename(OUT))
    ok = True
    iso = tcslib.Iso(OUT)
    iso_b = tcslib.Iso(BASE)
    info = base_entries(iso_b, mp)
    good_names = 0
    total = 0
    for code in order:
        zh = mp[code]['zh']
        got = []
        for tag, lba, e, _old in info.get(code, []):
            ent = iso.img_entry(lba, e['idx'])
            blob, _ = mislib.entry_blob(iso, ent)
            m = NAME_RE.search(blob)
            good = (m is not None and m.group(1) == zh)
            got.append(good)
            good_names += 1 if good else 0
            total += 1
        print('    %-6s %-28r 两拷贝 <Name> == 语言表: %s'
              % (code, zh, all(got) if got else 'NO ENTRY'))
    print('    合计: %d/%d 条目名 == 语言表' % (good_names, total))
    ok &= (good_names == total and total == 80)

    print('\n[5] 旧英文名全盘残留 (1 MiB 分块 + 重叠)')
    needles = sorted(set(old for code in order for (_t, _l, _e, old) in info[code]
                         if old))
    print('    待搜旧名 %d 个 (含 DP01-05 的 MapName 同值)' % len(needles))
    cnt = residue_scan(OUT, needles)
    total_res = sum(cnt.values())
    for n in needles:
        if cnt[n]:
            print('      !! %r -> %d 处' % (n, cnt[n]))
    print('    全盘旧名残留合计: %d 处' % total_res)
    ok &= (total_res == 0)

    print('\n[6] 尺寸 / ELF / 差异 / 幂等')
    sz, szb = os.path.getsize(OUT), os.path.getsize(BASE)
    esha, ecrc = elf_digest(OUT)
    print('    bytes  = %d (与基盘相同: %s)' % (sz, sz == szb))
    print('    ELF    = LBA %d / %d B  sha256 %s  crc32_xor %s  (未变: %s)'
          % (ELF_LBA, ELF_BYTES, esha, ecrc,
             esha == ELF_SHA and ecrc == ELF_CRC))
    ok &= (sz == szb) and esha == ELF_SHA and ecrc == ELF_CRC

    patched_spans, table_spans = [], []
    for code in order:
        for (tag, lba, e, _old) in info[code]:
            patched_spans.append((e['iso_off'], e['iso_off'] + e['stored']))
            tb = lba * 2048 + TAB_OFF + TAB_STEP * e['idx']
            table_spans.append((tb, tb + 48))
    diffs, ranges, in_ent, in_tab, outside = diff_scan(BASE, OUT, patched_spans,
                                                       table_spans)
    print('    全盘差异: %d B / %d 段' % (len(diffs), len(ranges)))
    print('      其中 .MIS 条目内 %d B, IMG 表内 %d B, 其它 %d B'
          % (in_ent, in_tab, outside))
    for (s, p) in ranges:
        print('      0x%09X..0x%09X  (%d B)' % (s, p, p - s + 1))
    ok &= (outside == 0)

    iso2 = tcslib.Iso(OUT)
    changed = 0
    for tag, lba, e in mislib.iter_mis(iso2):
        code = code_of(e['name'])
        if code not in mp:
            continue
        raw = iso2.read(e['iso_off'], e['stored'])
        subs = mislib.substreams(raw)
        parts = []
        for (p, pay, S) in subs:
            o, err = mislib.decode_payload(pay, S)
            parts.append(o)
        m = NAME_RE.search(parts[0])
        if m is None or m.group(1) != mp[code]['zh']:
            changed += 1
    iso2.close()
    print('    幂等重检: 目标未达成的条目 %d / 80' % changed)
    ok &= (changed == 0)

    sha256 = hash_file(OUT, 'sha256')
    md5 = hash_file(OUT, 'md5')
    print('\n    成品 sha256 = %s' % sha256)
    print('    成品 md5    = %s' % md5)
    print('\nRESULT: %s (%.1fs)' % ('ALL PASS' if ok else 'FAILED', time.time() - t_start))
    iso.close()
    iso_b.close()
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
