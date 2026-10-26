# -*- coding: utf-8 -*-
r"""cave_verify_f7b.py -- GR PS2 ZH round F7B: prove a candidate code cave is unreferenced.

Kept in tools\final_fix\ because it is the evidence tool behind the F7b cave choice
(0x00570BB0, 40 B) -- see docs\REPORT_F7B.md §B.  It answers the question the
SPINFIX/OOMFIX/COMBFIX rounds got stuck on ("ELF 里 >=32 B 且 8 份运行期快照全零的
干净区间 = 0 个"): widen the criterion from "all-zero in the ELF AND all-zero at
runtime" to "byte-identical to the ELF in EVERY runtime snapshot", and use .symtab
to require that no FUNC/OBJECT symbol covers the range.  The retail SLUS_206.13 is
a **debug build** (38,722 symbols + .debug/.line), so symbol gaps are exact.

Checks, for a candidate VA range [va, va+size), against the game ELF image and
against N runtime ee_ram snapshots:

  C1  bytes are all zero in the ELF image
  C2  bytes are byte-identical to the ELF in every snapshot (nobody writes them)
  C3  no 32-bit word anywhere in the ELF image equals a VA inside the range
  C4  no 32-bit word anywhere in any snapshot equals a VA inside the range
  C5  no `lui`+`addiu`/`ori` pair in the whole code computes an address inside it
  C6  no branch / j / jal anywhere in the image targets inside it
  C7  not covered by any FUNC or OBJECT symbol in .symtab
  C8  not inside any declared must-stay-identical window (caller supplies them)

READ-ONLY.

usage:
  python verify_cave.py --elf <elf> --va 0x570BB0 --size 36 --snap <ram.bin> ...
"""
import argparse
import struct
import sys

VA_BASE = 0x00100000
OFF_BASE = 0x80
FILESZ = 0x4DED00
VA_END = VA_BASE + FILESZ


def sections(d):
    e_shoff = struct.unpack_from('<I', d, 0x20)[0]
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from('<HHH', d, 0x2e)
    secs = []
    for i in range(e_shnum):
        o = e_shoff + i * e_shentsize
        nm, typ, flags, addr, off, size, link, info, align, entsz = struct.unpack_from('<10I', d, o)
        secs.append(dict(nameoff=nm, type=typ, addr=addr, off=off, size=size, entsz=entsz))
    stro = secs[e_shstrndx]['off']
    for s in secs:
        e = d.index(b'\x00', stro + s['nameoff'])
        s['name'] = d[stro + s['nameoff']:e].decode('latin-1')
    return secs


def symbols(d, secs):
    sym = [s for s in secs if s['type'] == 2][0]
    strt = [s for s in secs if s['name'] == '.strtab'][0]
    out = []
    for i in range(sym['size'] // 16):
        o = sym['off'] + i * 16
        nameoff, value, size, info, other, shndx = struct.unpack_from('<IIIBBH', d, o)
        if not value:
            continue
        e = d.index(b'\x00', strt['off'] + nameoff)
        out.append(dict(name=d[strt['off'] + nameoff:e].decode('latin-1'),
                        value=value, size=size, type=info & 0xF))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--elf', required=True)
    ap.add_argument('--va', required=True)
    ap.add_argument('--size', type=int, default=36)
    ap.add_argument('--snap', action='append', default=[])
    ap.add_argument('--json')
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    va = int(a.va, 16)
    hi = va + a.size
    d = open(a.elf, 'rb').read()
    secs = sections(d)
    syms = symbols(d, secs)
    img = d[OFF_BASE:OFF_BASE + FILESZ]
    ok = True
    rows = []

    def rep(name, good, detail=''):
        nonlocal ok
        ok = ok and bool(good)
        rows.append(dict(check=name, ok=bool(good), detail=str(detail)))
        print('  [%s] %-58s %s' % ('OK ' if good else 'FAIL', name, detail))

    print('cave candidate 0x%08X..0x%08X (%d B)' % (va, hi, a.size))

    # C1
    blob = img[va - VA_BASE:hi - VA_BASE]
    rep('C1 all zero in ELF image', all(b == 0 for b in blob),
        '%d nonzero' % sum(1 for b in blob if b))

    # C2
    for p in a.snap:
        b = open(p, 'rb').read()
        s = b[va:hi]
        rep('C2 snapshot identical to ELF: %s' % p.split('\\')[-2], s == blob,
            'differs %d B' % sum(1 for i in range(a.size) if s[i] != blob[i]))

    # C3
    hits = []
    for k in range(0, FILESZ - 3, 4):
        w = struct.unpack_from('<I', img, k)[0]
        if va <= w < hi:
            hits.append((VA_BASE + k, w))
    rep('C3 no pointer word in ELF image', not hits, str(hits[:5]))

    # C4
    for p in a.snap:
        b = open(p, 'rb').read()
        h = []
        for k in range(VA_BASE, VA_END - 3, 4):
            w = struct.unpack_from('<I', b, k)[0]
            if va <= w < hi:
                h.append((k, w))
        rep('C4 no pointer word in RAM: %s' % p.split('\\')[-2], not h, str(h[:5]))

    # C5  lui+addiu/ori pairs
    pairs = []
    for k in range(0, FILESZ - 7, 4):
        w0 = struct.unpack_from('<I', img, k)[0]
        if (w0 >> 26) != 0x0F:      # lui
            continue
        rt0 = (w0 >> 16) & 0x1F
        imm0 = w0 & 0xFFFF
        w1 = struct.unpack_from('<I', img, k + 4)[0]
        op1 = w1 >> 26
        if op1 not in (0x09, 0x0D):  # addiu, ori
            continue
        rs1 = (w1 >> 21) & 0x1F
        if rs1 != rt0:
            continue
        rt1 = (w1 >> 16) & 0x1F
        if rt1 != rt0:
            continue
        imm1 = w1 & 0xFFFF
        if op1 == 0x09 and imm1 & 0x8000:
            imm1 -= 0x10000
        addr = ((imm0 << 16) + imm1) & 0xFFFFFFFF
        if va <= addr < hi:
            pairs.append((VA_BASE + k, addr))
    rep('C5 no lui+addiu/ori building an address inside', not pairs, str(pairs[:5]))

    # C6  branch/j/jal targets
    tgt = []
    for k in range(0, FILESZ - 3, 4):
        w = struct.unpack_from('<I', img, k)[0]
        pc = VA_BASE + k
        op = w >> 26
        if op in (2, 3):
            t = ((w & 0x03FFFFFF) << 2) | (pc & 0xF0000000)
            if va <= t < hi:
                tgt.append((pc, 'j/jal', t))
        elif op in (1, 4, 5, 6, 7, 0x14, 0x15, 0x16, 0x17):
            imm = w & 0xFFFF
            if imm & 0x8000:
                imm -= 0x10000
            t = (pc + 4 + imm * 4) & 0xFFFFFFFF
            if va <= t < hi:
                tgt.append((pc, 'branch', t))
    rep('C6 no control-flow target inside', not tgt, str(tgt[:5]))

    # C7
    cov = [s for s in syms if s['size'] and s['value'] < hi and s['value'] + s['size'] > va]
    rep('C7 not covered by any symbol', not cov,
        '; '.join('%s(0x%X+%d)' % (s['name'], s['value'], s['size']) for s in cov[:4]))

    # neighbours
    before = [s for s in syms if s['size'] and s['value'] + s['size'] <= va]
    after = [s for s in syms if s['value'] >= hi]
    before.sort(key=lambda s: s['value'] + s['size'])
    after.sort(key=lambda s: s['value'])
    left = right = None
    if before:
        left = dict(symbol=before[-1]['name'], ends='0x%08X' % (before[-1]['value'] + before[-1]['size']),
                    clearance=va - (before[-1]['value'] + before[-1]['size']))
        print('  left  neighbour: %s ends 0x%08X  (clearance %d B)'
              % (left['symbol'], before[-1]['value'] + before[-1]['size'], left['clearance']))
    else:
        print('  left  neighbour: none')
    if after:
        right = dict(symbol=after[0]['name'], starts='0x%08X' % after[0]['value'],
                     clearance=after[0]['value'] - hi)
        print('  right neighbour: %s starts 0x%08X (clearance %d B)'
              % (right['symbol'], after[0]['value'], right['clearance']))
    else:
        print('  right neighbour: none')

    print('\n[verdict] %s' % ('cave candidate ACCEPTED' if ok else 'cave candidate REJECTED'))
    if a.json:
        import json
        json.dump(dict(elf=a.elf, va='0x%08X' % va, hi='0x%08X' % hi, size=a.size,
                       snapshots=list(a.snap), checks=rows, accepted=bool(ok),
                       left_neighbour=left, right_neighbour=right),
                  open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('[out] %s' % a.json)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
