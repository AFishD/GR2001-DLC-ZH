# -*- coding: utf-8 -*-
"""dis_region.py —— 用 capstone 反汇编 base ELF 的指定 VA 区间。"""
import sys

from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN

ELF = r'work\analysis\elf\DLC_SLUS_208.20.elf'
data = open(ELF, 'rb').read()


def dis(va, size=0x400):
    off = va - 0xFFF00
    md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 + CS_MODE_LITTLE_ENDIAN)
    out = []
    for ins in md.disasm(data[off:off + size], va):
        out.append('%08X  %-8s %s' % (ins.address, ins.mnemonic, ins.op_str))
    return out


if __name__ == '__main__':
    va = int(sys.argv[1], 0)
    size = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x300
    for line in dis(va, size):
        print(line)
