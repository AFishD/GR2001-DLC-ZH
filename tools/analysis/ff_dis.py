# -*- coding: utf-8 -*-
"""ff_dis.py —— 小 MIPS R5900 反汇编（够用版），用于查兵种名控件文本预处理。"""
import struct
import sys

sys.path.insert(0, r'tools\dlc')
import dlclib as L  # noqa: E402

ISO = sys.argv[1] if len(sys.argv) > 1 else r'work\builds\v25r.iso'
GPR = ['zero', 'at', 'v0', 'v1', 'a0', 'a1', 'a2', 'a3', 't0', 't1', 't2', 't3', 't4', 't5', 't6',
       't7', 's0', 's1', 's2', 's3', 's4', 's5', 's6', 's7', 't8', 't9', 'k0', 'k1', 'gp', 'sp',
       'fp', 'ra']
FPR = ['f%d' % i for i in range(32)]


def sext16(x):
    return x - 0x10000 if x >= 0x8000 else x


def decode(w, va):
    op = w >> 26
    rs = (w >> 21) & 0x1F
    rt = (w >> 16) & 0x1F
    rd = (w >> 11) & 0x1F
    sa = (w >> 6) & 0x1F
    fn = w & 0x3F
    imm = w & 0xFFFF
    if op == 0:
        if fn == 0:
            return 'nop'
        if fn == 0x21:
            return 'addu %s,%s,%s' % (GPR[rd], GPR[rs], GPR[rt])
        if fn == 0x23:
            return 'subu %s,%s,%s' % (GPR[rd], GPR[rs], GPR[rt])
        if fn == 0x25:
            return 'or %s,%s,%s' % (GPR[rd], GPR[rs], GPR[rt])
        if fn == 0x24:
            return 'and %s,%s,%s' % (GPR[rd], GPR[rs], GPR[rt])
        if fn == 0x27:
            return 'nor %s,%s,%s' % (GPR[rd], GPR[rs], GPR[rt])
        if fn == 0x2A:
            return 'slt %s,%s,%s' % (GPR[rd], GPR[rs], GPR[rt])
        if fn == 0x2B:
            return 'sltu %s,%s,%s' % (GPR[rd], GPR[rs], GPR[rt])
        if fn == 0x00:
            return 'sll %s,%s,%d' % (GPR[rd], GPR[rt], sa)
        if fn == 0x02:
            return 'srl %s,%s,%d' % (GPR[rd], GPR[rt], sa)
        if fn == 0x03:
            return 'sra %s,%s,%d' % (GPR[rd], GPR[rt], sa)
        if fn == 0x04:
            return 'sllv %s,%s,%s' % (GPR[rd], GPR[rt], GPR[rs])
        if fn == 0x08:
            return 'jr %s' % GPR[rs]
        if fn == 0x09:
            return 'jalr %s' % GPR[rs]
        if fn == 0x10:
            return 'mfhi %s' % GPR[rd]
        if fn == 0x12:
            return 'mflo %s' % GPR[rd]
        if fn == 0x18:
            return 'mult %s,%s' % (GPR[rs], GPR[rt])
        if fn == 0x1A:
            return 'div %s,%s' % (GPR[rs], GPR[rt])
        if fn == 0x2D:
            return 'daddu %s,%s,%s' % (GPR[rd], GPR[rs], GPR[rt])
        return 'special%02X' % fn
    if op == 0x02:
        return 'j 0x%X' % ((w & 0x3FFFFFF) << 2)
    if op == 0x03:
        return 'jal 0x%X' % ((w & 0x3FFFFFF) << 2)
    if op == 0x04:
        return 'beq %s,%s,0x%X' % (GPR[rs], GPR[rt], va + 4 + sext16(imm) * 4)
    if op == 0x05:
        return 'bne %s,%s,0x%X' % (GPR[rs], GPR[rt], va + 4 + sext16(imm) * 4)
    if op == 0x06:
        return 'blez %s,0x%X' % (GPR[rs], va + 4 + sext16(imm) * 4)
    if op == 0x07:
        return 'bgtz %s,0x%X' % (GPR[rs], va + 4 + sext16(imm) * 4)
    if op == 0x08:
        return 'addi %s,%s,%d' % (GPR[rt], GPR[rs], sext16(imm))
    if op == 0x09:
        return 'addiu %s,%s,%d' % (GPR[rt], GPR[rs], sext16(imm))
    if op == 0x0A:
        return 'slti %s,%s,%d' % (GPR[rt], GPR[rs], sext16(imm))
    if op == 0x0B:
        return 'sltiu %s,%s,%d' % (GPR[rt], GPR[rs], sext16(imm))
    if op == 0x0C:
        return 'andi %s,%s,0x%X' % (GPR[rt], GPR[rs], imm)
    if op == 0x0D:
        return 'ori %s,%s,0x%X' % (GPR[rt], GPR[rs], imm)
    if op == 0x0F:
        return 'lui %s,0x%04X' % (GPR[rt], imm)
    if op in (0x20, 0x21, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E,
              0x2F):
        n = {0x20: 'lb', 0x21: 'lh', 0x23: 'lw', 0x24: 'lbu', 0x25: 'lhu', 0x26: 'lwr', 0x27: 'lwu',
             0x28: 'sb', 0x29: 'sh', 0x2B: 'sw', 0x2C: 'sdl', 0x2D: 'sdr', 0x2E: 'swr',
             0x2A: 'swl'}[op]
        return '%s %s,%d(%s)' % (n, GPR[rt], sext16(imm), GPR[rs])
    if op == 0x11:
        if rs == 0x10:
            fd = (w >> 6) & 0x1F
            fs = (w >> 11) & 0x1F
            ft = (w >> 16) & 0x1F
            m = {0: 'add.s', 1: 'sub.s', 2: 'mul.s', 3: 'div.s', 0x28: 'add.s?', 0x29: 'sub.s?'}
            if fn in (0x00, 0x01, 0x02, 0x03):
                return '%s %s,%s,%s' % (m[fn], FPR[fd], FPR[fs], FPR[ft])
            if fn in (0x24, 0x25):
                return 'cvt.w.s %s,%s' % (FPR[fd], FPR[fs])
            if fn == 0x20:
                return 'cvt.s.w %s,%s' % (FPR[fd], FPR[fs])
            if fn in (0x2C, 0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37,
                      0x38, 0x39, 0x3A, 0x3B, 0x3C, 0x3D, 0x3E, 0x3F):
                return 'c.%02X.s %s,%s' % (fn, FPR[fs], FPR[ft])
            return 'cop1.%02X' % fn
        if rs == 0x00:
            return 'mfc1 %s,%s' % (GPR[rt], FPR[fs])
        if rs == 0x04:
            return 'mtc1 %s,%s' % (GPR[rt], FPR[fs])
        if rs == 0x08:
            return 'bc1%s 0x%X' % ('t' if ((w >> 16) & 1) else 'f',
                                   va + 4 + sext16(imm) * 4)
        return 'cop1 rs=%02X' % rs
    return 'op%02X %08X' % (op, w)


def main():
    args = sys.argv[2:]
    if len(args) >= 2:
        start = int(args[0], 16)
        end = int(args[1], 16)
    else:
        start, end = 0x40A4E0, 0x40A4E0 + 0x120
    if start >= 0x100000:
        file_off = start - 0xFFF00
    else:
        file_off = start
    iso = L.Iso(ISO)
    elf = iso.elf()
    iso.close()
    data = elf[file_off:file_off + (end - start)]
    print('# %s  VA 0x%X..0x%X  file 0x%X' % (ISO, start, end, file_off))
    for i in range(0, len(data) - 3, 4):
        va = start + i if start >= 0x100000 else start + i
        w = struct.unpack_from('<I', data, i)[0]
        print('%08X: %08X  %s' % (va, w, decode(w, va)))


if __name__ == '__main__':
    main()
