# -*- coding: utf-8 -*-
r"""patch_profile2_text.py -- GR_ZH136: make the 0xFF byte (character 著) disappear
from `MENU.IMG#283 EN_SPECIAL_FEATURE.XML`, so the engine's XML lexer stops mistaking
it for EOF and the SpecialistProfile <text> nodes stop being cut in half.

WHY (see docs/REPORT_PROFILE_SCROLL.md):
  * the translated charset maps U+8457 著 to the **single byte 0xFF**;
  * `RSXMLLexan::GetCharData @0x00544450` stores the char and then tests it with a
    **signed** byte load:  0x00544588  lb   $v1,0($a0)
                           0x0054458C  addiu $v0,$zero,-1
                           0x00544590  bne  $v1,$v0,<normal char>
    A stored 0xFF is -1 ⇒ treated as EOF ⇒ the char-data token is dropped and the
    text node ends; the rest of the node is re-parsed as a second "text" node and
    `SFStudio::ParseItem` **assigns** (not appends) ⇒ the item text loses everything
    before the 0xFF.
  * every one of the 13 SpecialistProfile texts has its first 0xFF exactly 2 bytes
    into "显著特征", so the panel starts at "特征：无" instead of the name line.

FIX: replace that one byte by a normal two-byte code and compensate the blob length
in the CRLF padding tail (the container slot is a fixed 116486-byte slot):
    显著 -> 明显   (显 a3dc  stays,  著 FF -> 明 a4cb)
    卓著 -> 卓越   (卓 adee stays,  著 FF -> 越 a1d2)

READ-ONLY on --iso; writes only --out (+ optional JSON report).

Usage:
  python patch_profile2_text.py --iso <GR_ZH134.iso> --out <GR_ZH136.iso> [--report r.json]
"""
import argparse
import hashlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))

import tcslib                                                          # noqa: E402
import font_compact as FC                                              # noqa: E402

TOOL = 'work/builds/GR_PROFILE2/tools/patch_profile2_text.py'
SLOT_BLOB = 116486
XML_IDX = tcslib.XML_IDX
MENU_LBA = tcslib.MENU_LBA
FF = b'\xff'
# 显著 -> 明显 : 显 a3dc | 著 FF  =>  明 a4cb | 显 a3dc     (2-byte span, +1 B)
SPAN_XIAN = bytes.fromhex('a3dcff')
REPL_XIAN = bytes.fromhex('a4cba3dc')
# 卓著 -> 卓越 : 卓 adee | 著 FF  =>  卓 adee | 越 a1d2     (1-byte span, +1 B)
SPAN_ZHUO = bytes.fromhex('adeeff')
REPL_ZHUO = bytes.fromhex('adeea1d2')


class FixError(Exception):
    pass


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''):
            h.update(b)
    return h.hexdigest()


def read_sfxml_blob(iso):
    e = iso.img_entry(MENU_LBA, XML_IDX)
    raw = iso.read(e['iso_off'], e['stored'])
    subs = tcslib.lzo_subs(raw)
    if not subs:
        raise FixError('SFXML container is not an LZO sub-stream frame')
    return e, b''.join(s[0] for s in subs), subs


def close_tail(blob, target_len, log):
    t = tcslib.xml_tail_start(blob)
    body, tail = blob[:t], blob[t:]
    if set(tail) - set(b'\r\n'):
        raise FixError('XML tail is not pure CRLF padding')
    need = target_len - len(body)
    if need < 0:
        raise FixError('body already longer than the slot (%d > %d)' % (len(body), target_len))
    new_tail = tail[:need] if need <= len(tail) else tail + (b'\r\n' * ((need - len(tail)) // 2 + 2))[:need - len(tail)]
    log('  [tail ] %d -> %d (%+d); blob stays %d'
        % (len(tail), len(new_tail), len(new_tail) - len(tail), len(body) + len(new_tail)))
    return body + new_tail


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--iso', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--report', default=None)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    LOG = []

    def log(s=''):
        print(s, flush=True)
        LOG.append(s)

    src, dst = os.path.abspath(a.iso), os.path.abspath(a.out)
    if src == dst:
        raise FixError('--out must differ from --iso')
    log('=' * 96)
    log('%s' % TOOL)
    log('  src    %s  sha256 %s' % (src, sha256_file(src)))

    iso = tcslib.Iso(src)
    try:
        e, blob, subs = read_sfxml_blob(iso)
    finally:
        iso.close()
    log('  SFXML  %s#%d  stored=%d  blob=%d  subs=%s'
        % (e['name'], XML_IDX, e['stored'], len(blob), [s[2] for s in subs]))
    if len(blob) != SLOT_BLOB:
        raise FixError('blob %d != %d' % (len(blob), SLOT_BLOB))

    ents0 = tcslib.parse_sfxml(blob)
    log('  entries (before) = %d' % len(ents0))

    # ---- plan: every 0xFF must be 显著 or 卓著 ----
    edits, applied = [], []
    i = -1
    while True:
        i = blob.find(FF, i + 1)
        if i < 0:
            break
        if blob[i - 2:i + 1] == SPAN_XIAN:
            lo_e, rep, why = i - 2, REPL_XIAN, '显著 -> 明显'
        elif blob[i - 2:i + 1] == SPAN_ZHUO:
            lo_e, rep, why = i - 2, REPL_ZHUO, '卓著 -> 卓越'
        else:
            raise FixError('unexpected 0xFF context at %d: %s' % (i, blob[i - 6:i + 6].hex()))
        # must be inside a <text> body
        inside = [k for (k, off, ln, _b) in ents0 if off <= lo_e and i < off + ln]
        if not inside:
            raise FixError('0xFF at %d is outside every <text> body' % i)
        edits.append((lo_e, i + 1, rep))
        applied.append(dict(abs_off=lo_e, tag='T%04d' % inside[0],
                            old=blob[lo_e:i + 1].hex().upper(), new=rep.hex().upper(),
                            delta=len(rep) - (i + 1 - lo_e), note=why))
        log('  [edit ] @%-6d %-6s %s -> %s  %+d B  %s'
            % (lo_e, 'T%04d' % inside[0], blob[lo_e:i + 1].hex().upper(), rep.hex().upper(),
               len(rep) - (i + 1 - lo_e), why))
    if not edits:
        raise FixError('no 0xFF found: already patched?')
    log('  total: %d edits, net %+d B (absorbed by the CRLF tail)'
        % (len(edits), sum(x['delta'] for x in applied)))

    new_blob = tcslib.splice(blob, edits)
    new_blob = close_tail(new_blob, SLOT_BLOB, log)

    # ---- structural assertions ----
    if len(new_blob) != len(blob):
        raise FixError('blob length changed')
    if FF in new_blob:
        raise FixError('0xFF still present in the patched blob')
    ents1 = tcslib.parse_sfxml(new_blob)
    if [k for (k, _o, _l, _b) in ents0] != [k for (k, _o, _l, _b) in ents1]:
        raise FixError('SFXML key order/count changed')
    cs = tcslib.Charset()
    for (k, o0, l0, b0), (k1, o1, l1, b1) in zip(ents0, ents1):
        if b0.count(b'{br}') != b1.count(b'{br}') or b0.count(b'{p}') != b1.count(b'{p}'):
            raise FixError('T%04d: {br}/{p} count changed' % k)
        t0 = cs.decode(b0)[0]
        t1 = cs.decode(b1)[0]
        if t0.replace('显著', '明显').replace('卓著', '卓越') != t1:
            raise FixError('T%04d: unexpected textual change\n  old=%r\n  new=%r' % (k, t0[:80], t1[:80]))
    log('  [check] 0xFF gone; %d entries; key order, {br}/{p} counts and wording all as planned' % len(ents1))
    k0 = ents1[0][0]
    log('  [check] T%04d now starts: %r' % (k0, cs.decode(ents1[0][3])[0][:34]))

    if a.dry_run:
        log('[dry-run] not writing')
        return 0

    # ---- write: copy + repack the slot ----
    import shutil
    if os.path.exists(dst):
        os.remove(dst)
    shutil.copyfile(src, dst)
    iso_s = tcslib.Iso(src)
    try:
        slot = FC.Slot(iso_s, 'MENU.IMG#%d' % XML_IDX, MENU_LBA, XML_IDX)
        fr, n_rep, flen, method = slot.repack(new_blob, 'MENU.IMG#%d' % XML_IDX)
        log('  [pack ] frame %d B / slot %d B (method %s, recompressed sub-streams %d)'
            % (flen, slot.slot, method, n_rep))
        if flen > slot.slot:
            raise FixError('compressed frame exceeds the slot')
    finally:
        iso_s.close()
    with open(dst, 'r+b') as f:
        FC.Slot.write(f, e['iso_off'], e['stored'], fr)
    if os.path.getsize(dst) != os.path.getsize(src):
        raise FixError('ISO size changed')
    sha_out = sha256_file(dst)
    log('  [write] %s  sha256 %s  (%d B)' % (dst, sha_out, os.path.getsize(dst)))

    # ---- diff census: only inside the SFXML entry ----
    lo = e['iso_off']
    hi = e['iso_off'] + e['stored']
    diffs, pos = [], 0
    with open(src, 'rb') as f1, open(dst, 'rb') as f2:
        while True:
            b1 = f1.read(1 << 22)
            if not b1:
                break
            b2 = f2.read(1 << 22)
            if b1 != b2:
                for j, (x, y) in enumerate(zip(b1, b2)):
                    if x != y:
                        diffs.append(pos + j)
            pos += len(b1)
    outside = [d for d in diffs if not (lo <= d < hi)]
    log('  [diff ] %d differing bytes, all inside the SFXML entry [0x%X,0x%X)? %s'
        % (len(diffs), lo, hi, 'YES' if not outside else 'NO (%d outside)' % len(outside)))
    if outside:
        raise FixError('diff escaped the SFXML entry')

    if a.report:
        rep = dict(tool=TOOL, src=os.path.basename(src), src_sha256=sha256_file(src),
                   out=os.path.basename(dst), out_sha256=sha_out, iso_size=os.path.getsize(dst),
                   entry=dict(img='MENU.IMG', idx=XML_IDX, iso_off=lo, stored=e['stored'], real=e['real']),
                   blob_len=len(new_blob), edits=applied, net_delta=sum(x['delta'] for x in applied),
                   diff_bytes=len(diffs),
                   diff_range=['0x%X' % min(diffs), '0x%X' % max(diffs)] if diffs else [])
        with io.open(a.report, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=1)
        log('  [rep  ] %s' % a.report)
    log('OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
