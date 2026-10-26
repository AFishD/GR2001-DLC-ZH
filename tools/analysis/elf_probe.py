# -*- coding: utf-8 -*-
r"""elf_probe.py —— PS2 ELF 只读分析工具（《幽灵行动：丛林风暴》汉化工程 · ELF/引擎能力分析）

子命令：
    info        ELF 头 / program headers / section headers / PT_LOAD 布局 / sha256 / md5 / 尺寸
    crc         PCSX2 Game CRC（= 全 ELF 按 u32 LE 异或，参考本体工程 tools/final_fix/elf_crc.py）
    strings     内嵌可打印 ASCII 串（--grep 过滤；--font 只看字体/UI 相关）
    gate-scan   扫 DBCS 相关模式：sltiu/slti/addiu/andi 立即数（默认 0xA0..0xC0,0xFF 邻域）、
                lb/lbu/andi 0xFF、srl/sll 8、mult/div 常数 94/10/20 …；每条带上下文指令
    disasm      定点反汇编：--at VA[,VA...] / --range VA:VA / --sym 名字（本体 ELF 符号表）
    insn-search 反汇编文本正则搜索（例：'jal 0x2195f0'、'sltiu .*0x00b1'）
    callers     找 jal/j 目标等于给定 VA 的调用点
    cave        找全零填充岛（cave 候选），可选 --check 做「无跳转目标 / 无地址引用」校验
    symbols     本体英文 ELF 的符号表：--near VA / --grep 子串 / --dump
    sim         两个 ELF 里同构函数的「归一化指令序列」相似度（判断可移植性）
    diff        两个 ELF 的逐字节差异（自动换算 VA，可选 --syms 注释）
    dump        导出一段字节到文件（大中间产物放 work/analysis/elf/）

约定：
    · 只读：ISO / ELF 全部 mmap 只读，不写任何原盘。
    · ELF 载入：默认取 work/analysis/elf/ 缓存，其次从 ISO 根目录按名读取（ISO9660，支持多 ISO）。
    · VA ↔ 文件偏移：按 PT_LOAD 段反查（本 DLC ELF: file = VA - 0xFFF00；本体 ELF: file = VA - 0xFFF80）。
      不写死公式，一律走段表。
    · 反汇编：优先 capstone（MIPS64+LE，skipdata）+ EE(R5900) 专有指令补丁（lq/sq/pcpyld/...）；
      无 capstone 时退化为内置轻量解码器（足以支撑 gate-scan 上下文）。

用法示例：
    python tools/analysis/elf_probe.py info
    python tools/analysis/elf_probe.py crc
    python tools/analysis/elf_probe.py gate-scan --imm 0xA1,0xAE,0xB1,0xB5,0xBA --ctx 8
    python tools/analysis/elf_probe.py disasm --at 0x2195F0 --n 40
    python tools/analysis/elf_probe.py disasm --range 0x416E00:0x417800 --out work/analysis/elf/zh_cave.txt
    python tools/analysis/elf_probe.py insn-search --pattern "jal 0x173678"
    python tools/analysis/elf_probe.py cave --min 64 --check
    python tools/analysis/elf_probe.py symbols --near 0x219A70
    python tools/analysis/elf_probe.py sim --base-va 0x21AD10 --other DLC --other-va 0x21A360 --n 60
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys

SEC = 2048
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
WORK = os.path.join(REPO, 'work', 'analysis', 'elf')

DLC_ISO = os.path.join(REPO, 'third_party', 'orig', 'ps2',
                       "[PS2] Tom Clancy's Ghost Recon - Jungle Storm (U).iso")
DLC_NAME = 'SLUS_208.20'
BASE_ROOT = r'C:\Users\84363\Desktop\Ghost_Recon_2001_Locolization'
BASE_ISO = os.path.join(BASE_ROOT, 'third_party', 'orig', 'ps2',
                        "Tom Clancy's Ghost Recon (USA).iso")
BASE_NAME = 'SLUS_206.13'
BASE_ZH_ISO = os.path.join(BASE_ROOT, 'work', 'builds', 'FINAL',
                           "Tom Clancy's Ghost Recon (ZH_CN).iso")

# work/analysis/elf 下的 ELF 缓存（由 elf_port.py extract 生成）
CACHE = {
    'dlc': os.path.join(WORK, 'DLC_SLUS_208.20.elf'),
    'base': os.path.join(WORK, 'BASE_EN_SLUS_206.13.elf'),
    'zh': os.path.join(WORK, 'BASE_ZH_SLUS_206.13.elf'),
}


def P(*a):
    print(' '.join(str(x) for x in a), flush=True)


# ─────────────────────────── ISO9660（只读） ───────────────────────────
class Iso(object):
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.f = open(self.path, 'rb')
        self.size = os.path.getsize(self.path)

    def read(self, off, n):
        self.f.seek(off)
        return self.f.read(n)

    def sector(self, lba, n=1):
        return self.read(lba * SEC, n * SEC)

    def pvd(self):
        pvd = self.sector(16)
        if pvd[1:6] != b'CD001':
            raise SystemExit('不是 ISO9660 映像: %s' % self.path)
        root = pvd[156:190]
        return dict(volume_id=pvd[40:72].rstrip(b' ').decode('latin-1'),
                    root_lba=struct.unpack_from('<I', root, 2)[0],
                    root_size=struct.unpack_from('<I', root, 10)[0],
                    volume_space=struct.unpack_from('<I', pvd, 80)[0])

    def find_root(self, name):
        p = self.pvd()
        data = self.sector(p['root_lba'], (p['root_size'] + SEC - 1) // SEC)
        off = 0
        while off + 33 <= p['root_size']:
            ln = data[off]
            if ln == 0:
                off = (off // SEC + 1) * SEC
                continue
            rec = data[off:off + ln]
            ext = struct.unpack_from('<I', rec, 2)[0]
            size = struct.unpack_from('<I', rec, 10)[0]
            flags = rec[25]
            nlen = rec[32]
            nm = rec[33:33 + nlen].decode('latin-1')
            if nm not in ('\x00', '\x01') and nm.split(';')[0].upper() == name.upper():
                return dict(name=nm, lba=ext, size=size, is_dir=bool(flags & 2))
            off += ln
        return None

    def read_file(self, name):
        e = self.find_root(name)
        if not e:
            raise SystemExit('ISO 里找不到 %s' % name)
        return self.read(e['lba'] * SEC, e['size'])

    def close(self):
        self.f.close()


# ─────────────────────── EE(R5900) 反汇编（capstone + 补丁） ───────────────────────
# 注意：capstone 无 R5900 后端，MIPS64 模式对 EE 专有指令会报 .byte。
# 这里对「字面编码 → 助记符」做定点补丁（只补我们分析需要的，且都是实测编码）。
GPR = ['zero', 'at', 'v0', 'v1', 'a0', 'a1', 'a2', 'a3',
       't0', 't1', 't2', 't3', 't4', 't5', 't6', 't7',
       's0', 's1', 's2', 's3', 's4', 's5', 's6', 's7',
       't8', 't9', 'k0', 'k1', 'gp', 'sp', 'fp', 'ra']

MMI_FUNCT = {0x00: 'madd', 0x01: 'maddu', 0x02: 'plzcw', 0x04: 'msub', 0x05: 'msubu',
             0x08: 'mfhi1', 0x09: 'mthi1', 0x0A: 'mflo1', 0x0B: 'mtlo1',
             0x10: 'mfhi', 0x11: 'mthi', 0x12: 'mflo', 0x13: 'mtlo',
             0x18: 'mult1', 0x19: 'multu1', 0x1A: 'div1', 0x1B: 'divu1',
             0x1C: 'madd1', 0x1D: 'maddu1'}
# MMI 并行/位操作组：编码 (funct, sa) 由实测反推
MMI_PAR = {(0x28, 0x18): 'pcpyld', (0x29, 0x18): 'pcpyud'}


def _s16(x):
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


def ee_override(word):
    """返回 EE 专有指令的 (mnemonic, op_str)，不认识返回 None。

    重要：R5900 的 MULT/MULTU 是**三操作数**形式 `mult rd, rs, rt`（低 64 位积写 rd），
    ee-gcc 大量使用（本体英文 ELF 里 rd!=0 的有 1198 处，rd==0 的 264 处）。
    标准 MIPS32/64 解码器会把 rd!=0 的 mult 解成 .byte 或 `mult $acN,…`，这里补正。
    """
    op = word >> 26
    if op == 0:
        funct = word & 0x3F
        rd = (word >> 11) & 0x1F
        rs = (word >> 21) & 0x1F
        rt = (word >> 16) & 0x1F
        if funct in (0x18, 0x19) and rd != 0:
            return ('mult' if funct == 0x18 else 'multu',
                    '%s, %s, %s' % (GPR[rd], GPR[rs], GPR[rt]))
    if op == 0x1E:                       # LQ
        rt, rs, off = (word >> 16) & 0x1F, (word >> 21) & 0x1F, _s16(word)
        return 'lq', '%s, %d(%s)' % (GPR[rt], off, GPR[rs])
    if op == 0x1F:                       # SQ
        rt, rs, off = (word >> 16) & 0x1F, (word >> 21) & 0x1F, _s16(word)
        return 'sq', '%s, %d(%s)' % (GPR[rt], off, GPR[rs])
    if op == 0x1C:                       # MMI
        funct = word & 0x3F
        sa = (word >> 6) & 0x1F
        if (funct, sa) in MMI_PAR:
            rd, rs, rt = (word >> 11) & 0x1F, (word >> 21) & 0x1F, (word >> 16) & 0x1F
            return MMI_PAR[(funct, sa)], '%s, %s, %s' % (GPR[rd], GPR[rs], GPR[rt])
        if funct in MMI_FUNCT and funct not in (0x10, 0x11, 0x12, 0x13):
            rd, rs, rt = (word >> 11) & 0x1F, (word >> 21) & 0x1F, (word >> 16) & 0x1F
            if funct in (0x08, 0x0A):
                return MMI_FUNCT[funct], GPR[rd]
            if funct in (0x09, 0x0B, 0x11, 0x13):
                return MMI_FUNCT[funct], GPR[rs]
            return MMI_FUNCT[funct], '%s, %s, %s' % (GPR[rd], GPR[rs], GPR[rt])
    return None


class Dis(object):
    """带 EE 补丁的反汇编器；capstone 缺失时自动降级。"""

    def __init__(self):
        self.cap = None
        try:
            from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS64, CS_MODE_LITTLE_ENDIAN
            self.cap = Cs(CS_ARCH_MIPS, CS_MODE_MIPS64 | CS_MODE_LITTLE_ENDIAN)
            self.cap.skipdata = True
        except Exception:                                       # noqa: BLE001
            self.cap = None

    def iter(self, data, va):
        """yield (va, word, bytes, mnemonic, op_str)"""
        n = len(data) // 4
        words = struct.unpack_from('<%dI' % n, data, 0)
        if self.cap is not None:
            i = 0
            for ins in self.cap.disasm(data[:n * 4], va):
                idx = (ins.address - va) // 4
                w = words[idx] if 0 <= idx < n else 0
                mn, ops = ins.mnemonic, ins.op_str
                ov = ee_override(w)
                if ov:
                    mn, ops = ov
                yield (ins.address, w, ins.bytes, mn, ops)
                i = idx
            return
        for k, w in enumerate(words):
            ov = ee_override(w)
            if ov:
                mn, ops = ov
            else:
                mn, ops = light_decode(w, va + k * 4)
            yield (va + k * 4, w, struct.pack('<I', w), mn, ops)

    def one(self, word, va):
        for _, _, _, mn, ops in self.iter(struct.pack('<I', word), va):
            return mn, ops
        return '?', ''


def light_decode(w, pc):
    """内置轻量解码器：只覆盖常见指令（capstone 缺失时用）。"""
    op = w >> 26
    rs, rt = (w >> 21) & 0x1F, (w >> 16) & 0x1F
    imm, sa, rd = _s16(w), (w >> 6) & 0x1F, (w >> 11) & 0x1F
    funct = w & 0x3F
    if w == 0:
        return 'nop', ''
    if op == 0:
        R = {0x00: 'sll', 0x02: 'srl', 0x03: 'sra', 0x04: 'sllv', 0x06: 'srlv',
             0x08: 'jr', 0x09: 'jalr', 0x0C: 'syscall', 0x0D: 'break', 0x10: 'mfhi',
             0x11: 'mthi', 0x12: 'mflo', 0x13: 'mtlo', 0x18: 'mult', 0x19: 'multu',
             0x1A: 'div', 0x1B: 'divu', 0x20: 'add', 0x21: 'addu', 0x22: 'sub',
             0x23: 'subu', 0x24: 'and', 0x25: 'or', 0x26: 'xor', 0x27: 'nor',
             0x2A: 'slt', 0x2B: 'sltu', 0x2D: 'daddu', 0x2E: 'dsub', 0x2F: 'dsubu'}
        mn = R.get(funct)
        if not mn:
            return '.word', ''
        if funct in (0x2A, 0x2B, 0x21, 0x23, 0x25, 0x24, 0x26, 0x2D, 0x2F, 0x22):
            return mn, '%s, %s, %s' % (GPR[rd], GPR[rs], GPR[rt])
        if funct in (0x00, 0x02, 0x03):
            return mn, '%s, %s, %d' % (GPR[rd], GPR[rt], sa)
        if funct in (0x10, 0x12):
            return mn, GPR[rd]
        if funct in (0x18, 0x19, 0x1A, 0x1B):
            return mn, '%s, %s' % (GPR[rs], GPR[rt])
        if funct == 0x08:
            return mn, GPR[rs]
        if funct == 0x09:
            return mn, '%s, %s' % (GPR[rd], GPR[rs])
        return mn, ''
    I = {0x04: 'beq', 0x05: 'bne', 0x06: 'blez', 0x07: 'bgtz', 0x08: 'addi',
         0x09: 'addiu', 0x0A: 'slti', 0x0B: 'sltiu', 0x0C: 'andi', 0x0D: 'ori',
         0x0E: 'xori', 0x0F: 'lui', 0x20: 'lb', 0x21: 'lh', 0x23: 'lw', 0x24: 'lbu',
         0x25: 'lhu', 0x28: 'sb', 0x29: 'sh', 0x2B: 'sw', 0x31: 'lwc1', 0x39: 'swc1'}
    mn = I.get(op)
    if not mn:
        if op == 0x02:
            return 'j', '0x%08X' % (((w & 0x3FFFFFF) << 2) | (pc & 0xF0000000))
        if op == 0x03:
            return 'jal', '0x%08X' % (((w & 0x3FFFFFF) << 2) | (pc & 0xF0000000))
        return '.word', ''
    if op == 0x0F:
        return 'lui', '%s, 0x%X' % (GPR[rt], w & 0xFFFF)
    if op in (0x04, 0x05):
        return mn, '%s, %s, 0x%X' % (GPR[rs], GPR[rt], (pc + 4 + (imm << 2)) & 0xFFFFFFFF)
    if op in (0x06, 0x07):
        return mn, '%s, 0x%X' % (GPR[rs], (pc + 4 + (imm << 2)) & 0xFFFFFFFF)
    if op in (0x20, 0x21, 0x23, 0x24, 0x25, 0x28, 0x29, 0x2B, 0x31, 0x39):
        return mn, '%s, %d(%s)' % (GPR[rt], imm, GPR[rs])
    return mn, '%s, %s, %d' % (GPR[rt], GPR[rs], imm)


# ─────────────────────────────── ELF 映像 ───────────────────────────────
class Elf(object):
    def __init__(self, data, tag='elf', iso_path=None, lba=None):
        self.data = data
        self.tag = tag
        self.path = iso_path
        self.lba = lba
        self.name = None
        self._parse()

    # ---- 构造 ----
    @staticmethod
    def from_file(path, tag=None):
        with open(path, 'rb') as f:
            return Elf(f.read(), tag or os.path.basename(path), iso_path=path)

    @staticmethod
    def from_iso(iso_path, name):
        iso = Iso(iso_path)
        try:
            e = iso.find_root(name)
            if not e:
                raise SystemExit('ISO 里找不到 %s' % name)
            data = iso.read_file(name)
        finally:
            iso.close()
        return Elf(data, tag='%s@%s' % (name, os.path.basename(iso_path)),
                   iso_path=iso_path, lba=e['lba'])

    @staticmethod
    def pick(kind=None, path=None):
        """kind: dlc/base/zh；或直接 path（ELF 文件）。返回 (Elf, source)。"""
        if path:
            if not os.path.exists(path):
                raise SystemExit('找不到 ELF: %s' % path)
            return Elf.from_file(path), path
        kind = kind or 'dlc'
        if kind == 'dlc':
            if os.path.exists(CACHE['dlc']):
                return Elf.from_file(CACHE['dlc'], 'DLC SLUS_208.20'), CACHE['dlc']
            e = Elf.from_iso(DLC_ISO, DLC_NAME)
            return e, DLC_ISO
        if kind == 'base':
            if os.path.exists(CACHE['base']):
                return Elf.from_file(CACHE['base'], 'BASE-EN SLUS_206.13'), CACHE['base']
            return Elf.from_iso(BASE_ISO, BASE_NAME), BASE_ISO
        if kind == 'zh':
            if os.path.exists(CACHE['zh']):
                return Elf.from_file(CACHE['zh'], 'BASE-ZH SLUS_206.13'), CACHE['zh']
            return Elf.from_iso(BASE_ZH_ISO, BASE_NAME), BASE_ZH_ISO
        raise SystemExit('未知 ELF 类型: %s' % kind)

    # ---- 解析 ----
    def _parse(self):
        d = self.data
        if d[:4] != b'\x7fELF':
            raise SystemExit('不是 ELF')
        (self.e_type, self.e_machine, self.e_version, self.e_entry, self.e_phoff,
         self.e_shoff, self.e_flags, self.e_ehsize, self.e_phentsize, self.e_phnum,
         self.e_shentsize, self.e_shnum, self.e_shstrndx) = \
            struct.unpack_from('<HHIIIIIHHHHHH', d, 16)
        self.size = len(d)
        self.phdrs = []
        for i in range(self.e_phnum):
            p = struct.unpack_from('<IIIIIIII', d, self.e_phoff + i * self.e_phentsize)
            self.phdrs.append(dict(type=p[0], off=p[1], vaddr=p[2], paddr=p[3],
                                   filesz=p[4], memsz=p[5], flags=p[6], align=p[7]))
        self.sections = []
        if self.e_shoff and self.e_shnum:
            raw = [struct.unpack_from('<IIIIIIIIII', d, self.e_shoff + i * self.e_shentsize)
                   for i in range(self.e_shnum)]
            strtab = raw[self.e_shstrndx]
            for sh in raw:
                nm = ''
                if sh[0]:
                    base = strtab[4] + sh[0]
                    end = d.find(b'\0', base)
                    nm = d[base:end].decode('latin-1')
                self.sections.append(dict(name=nm, type=sh[1], flags=sh[2], addr=sh[3],
                                          off=sh[4], size=sh[5], link=sh[6]))
        # 文本段：第一个 filesz>0 的可执行 PT_LOAD
        self.text = None
        for p in self.phdrs:
            if p['type'] == 1 and p['filesz'] > 0:
                self.text = p
                break
        self._syms = None

    # ---- VA ↔ 文件偏移 ----
    def off(self, va):
        for p in self.phdrs:
            if p['type'] == 1 and p['vaddr'] <= va < p['vaddr'] + max(p['filesz'], p['memsz']):
                if va < p['vaddr'] + p['filesz']:
                    return p['off'] + (va - p['vaddr'])
                raise SystemExit('VA 0x%08X 在 BSS 段内（无文件字节）' % va)
        raise SystemExit('VA 0x%08X 不在任何 PT_LOAD 内' % va)

    def va(self, off):
        for p in self.phdrs:
            if p['type'] == 1 and p['off'] <= off < p['off'] + p['filesz']:
                return p['vaddr'] + (off - p['off'])
        raise SystemExit('文件偏移 0x%X 不在任何 PT_LOAD 内' % off)

    def read(self, va, n):
        o = self.off(va)
        return self.data[o:o + n]

    def word(self, va):
        return struct.unpack('<I', self.read(va, 4))[0]

    def words(self, va, n):
        return struct.unpack_from('<%dI' % n, self.read(va, n * 4), 0)

    # ---- 身份 ----
    def sha256(self):
        return hashlib.sha256(self.data).hexdigest()

    def md5(self):
        return hashlib.md5(self.data).hexdigest()

    def crc(self):
        """PCSX2 Game CRC：全 ELF 按 u32 LE 异或。"""
        c = 0
        for (w,) in struct.iter_unpack('<I', self.data[:len(self.data) // 4 * 4]):
            c ^= w
        return c & 0xFFFFFFFF

    # ---- 符号表（本体英文 ELF 有；DLC stripped） ----
    def syms(self):
        if self._syms is not None:
            return self._syms
        out = []
        st = sa = None
        for s in self.sections:
            if s['type'] == 2 and s['size']:
                st = s
            if s['type'] == 3 and s['size'] and sa is None:
                sa = s
        if not st or not sa:
            self._syms = out
            return out
        self._syms = out
        n = st['size'] // 16
        for i in range(n):
            nm, val, sz, info, other, shndx = struct.unpack_from(
                '<IIIBBH', self.data, st['off'] + i * 16)
            if nm == 0:
                continue
            base = sa['off'] + nm
            end = self.data.find(b'\0', base)
            self._syms.append((val, sz, info, self.data[base:end].decode('latin-1')))
        self._syms.sort()
        return out

    def sym_for(self, va):
        """返回覆盖 va 的最大符号；没有返回 None。"""
        best = None
        for val, sz, info, nm in self.syms():
            if val <= va < val + max(sz, 1) and sz > 0:
                if best is None or sz > best[1]:
                    best = (val, sz, nm)
        return best

    def syms_near(self, va, k=4):
        ss = self.syms()
        import bisect
        vals = [s[0] for s in ss]
        i = bisect.bisect_right(vals, va) - 1
        lo = max(0, i - k)
        return ss[lo:min(len(ss), i + k + 1)]


DIS = Dis()


# ───────────────────────────── 输出辅助 ───────────────────────────────
def line(elf, va, word, mn, ops):
    return '0x%06X f0x%06X %08X  %-8s %s' % (
        va, elf.off(va) if _in_file(elf, va) else 0, word, mn, ops)


def _in_file(elf, va):
    try:
        elf.off(va)
        return True
    except SystemExit:
        return False


def dump_dis(elf, va, n, ctx=None, out=None, mark=None):
    """反汇编 va 起 n 条；返回文本行列表。"""
    n = max(1, n)
    data = elf.read(va, n * 4)
    rows = []
    for addr, w, b, mn, ops in DIS.iter(data, va):
        s = '%s %08X  %-8s %s' % (('0x%06X' % addr), w, mn, ops)
        if mark and addr in mark:
            s += '   ; ★ ' + mark[addr]
        rows.append(s)
    txt = '\n'.join(rows)
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, 'w', encoding='utf-8') as f:
            f.write(txt + '\n')
        P('[dump] %s  (%d 条指令)' % (out, len(rows)))
    else:
        P(txt)
    return rows


def ctx_block(elf, va, before, after):
    """VA 前后各若干指令的上下文块。"""
    rows = []
    for k in range(-before, after + 1):
        try:
            a = va + k * 4
            w = elf.word(a)
        except SystemExit:
            continue
        mn, ops = DIS.one(w, a)
        mark = ' <== ' if k == 0 else ''
        rows.append('0x%06X %08X  %-8s %-34s%s' % (a, w, mn, ops, mark))
    return rows


# ─────────────────────────────── 子命令 ───────────────────────────────
def cmd_info(a):
    elf = Elf.pick(a.kind, a.path)[0]
    P('== ELF info: %s' % elf.tag)
    P('size      %d B (0x%X)' % (elf.size, elf.size))
    P('sha256    %s' % elf.sha256())
    P('md5       %s' % elf.md5())
    P('e_type    %d   e_machine %d   e_flags 0x%X   e_entry 0x%08X' % (
        elf.e_type, elf.e_machine, elf.e_flags, elf.e_entry))
    P('phoff 0x%X (entsize %d, num %d)   shoff 0x%X (entsize %d, num %d)  shstrndx %d' % (
        elf.e_phoff, elf.e_phentsize, elf.e_phnum, elf.e_shoff, elf.e_shentsize,
        elf.e_shnum, elf.e_shstrndx))
    P('symbols   %d %s' % (len(elf.syms()), '(stripped)' if not elf.syms() else ''))
    P('-- program headers --')
    for i, p in enumerate(elf.phdrs):
        P('  PH[%d] type=0x%X off=0x%08X vaddr=0x%08X paddr=0x%08X filesz=0x%X memsz=0x%X '
          'flags=0x%X align=0x%X' % (i, p['type'], p['off'], p['vaddr'], p['paddr'],
                                     p['filesz'], p['memsz'], p['flags'], p['align']))
    if elf.sections:
        P('-- section headers --')
        for s in elf.sections:
            P('  %-16s type=%-4d flags=0x%-8X addr=0x%08X off=0x%08X size=0x%X' % (
                s['name'] or '(null)', s['type'], s['flags'], s['addr'], s['off'], s['size']))
    # 文本段事实
    t = elf.text
    P('-- .text (first executable PT_LOAD) --')
    P('  vaddr=0x%08X .. 0x%08X  filesz=0x%X  file=0x%X..0x%X  va_to_file = VA - 0x%X' % (
        t['vaddr'], t['vaddr'] + t['filesz'], t['filesz'], t['off'], t['off'] + t['filesz'],
        t['vaddr'] - t['off']))
    P('  sha256(.text) %s' % hashlib.sha256(elf.data[t['off']:t['off'] + t['filesz']]).hexdigest())
    P('-- 内嵌字符串统计 --')
    ss = extract_strings(elf, 4)
    P('  可打印 ASCII 串(>=4): %d 条 / %d 字节' % (len(ss), sum(len(x[2]) for x in ss)))
    js = dict(size=elf.size, sha256=elf.sha256(), md5=elf.md5(), entry=elf.e_entry,
              phdrs=elf.phdrs, sections=elf.sections, crc=elf.crc(),
              strings=len(ss), strings_bytes=sum(len(x[2]) for x in ss))
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump(js, f, ensure_ascii=False, indent=1)
        P('[json] %s' % a.json)


def cmd_crc(a):
    elf = Elf.pick(a.kind, a.path)[0]
    patches = parse_patch_args(a.set)
    if patches:
        data = bytearray(elf.data)
        for va, word in patches:
            o = elf.off(va)
            data[o:o + 4] = struct.pack('<I', word)
        e2 = Elf(bytes(data), tag=elf.tag + '+patch')
        P('原 CRC = %08X   patched CRC = %08X   (改了 %d 个 u32)' % (
            elf.crc(), e2.crc(), len(patches)))
        P('  ⇒ 即时存档名 SLUS-%s (%08X).01.p2s' % (_crc_elf_id(elf.tag), e2.crc()))
        return
    P('ELF %s  %d B  sha256 %s' % (elf.tag, elf.size, elf.sha256()))
    P('Game CRC = %08X  (PCSX2 口径: 全 ELF 按 u32 LE 异或)' % elf.crc())
    P('  ⇒ 即时存档名 SLUS-%s (%08X).01.p2s' % (_crc_elf_id(elf.tag), elf.crc()))


def _crc_elf_id(tag):
    m = re.search(r'SLUS[_-]?(\d{3})[._]?(\d{2})', tag)
    return (m.group(1) + m.group(2)) if m else '?????'


def parse_patch_args(sets):
    out = []
    for item in (sets or []):
        for part in item.split(','):
            part = part.strip()
            if not part:
                continue
            va, w = part.split('=')
            out.append((int(va, 16), int(w, 16)))
    return out


def extract_strings(elf, minlen=4):
    """返回 [(file_off, va, str)]"""
    out = []
    pat = re.compile(rb'[\x20-\x7e]{%d,}' % max(1, minlen))
    d = elf.data
    for m in pat.finditer(d):
        try:
            va = elf.va(m.start())
        except SystemExit:
            va = 0
        out.append((m.start(), va, m.group().decode('latin-1')))
    return out


def cmd_strings(a):
    elf = Elf.pick(a.kind, a.path)[0]
    ss = extract_strings(elf, a.min)
    if a.grep:
        rx = re.compile(a.grep, re.I)
        ss = [x for x in ss if rx.search(x[2])]
    if a.font:
        rx = re.compile(r'font|glyph|letter|char|text|string|menu|hud|ui|button|icon|'
                        r'atlas|tex|res|\.xml|save|crc|load|press|start', re.I)
        ss = [x for x in ss if rx.search(x[2])]
    P('# %d 条字符串（min=%d%s%s）' % (len(ss), a.min,
                                      (' grep=%r' % a.grep) if a.grep else '',
                                      ' font-filter' if a.font else ''))
    for off, va, s in ss[:a.limit]:
        P('  0x%06X  va=0x%06X  %r' % (off, va, s))
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump([dict(file_off=o, va=v, s=s) for o, v, s in ss], f,
                      ensure_ascii=False, indent=1)
        P('[json] %s' % a.json)


# ---- gate-scan ----
def cmd_gate_scan(a):
    elf = Elf.pick(a.kind, a.path)[0]
    imms = set(int(x, 16) for x in a.imm.split(',')) if a.imm else \
        set(list(range(0xA0, 0xC1)) + [0xFF, 0xFE, 0x5E, 0x0A, 0x14, 0x28])
    t = elf.text
    data = elf.data[t['off']:t['off'] + t['filesz']]
    n = len(data) // 4
    W = struct.unpack_from('<%dI' % n, data, 0)
    sel = a.ops.split(',') if a.ops else ['sltiu', 'slti', 'addiu', 'andi', 'ori']
    hits = []
    for i, w in enumerate(W):
        op = w >> 26
        imm = w & 0xFFFF
        names = {0x0B: 'sltiu', 0x0A: 'slti', 0x09: 'addiu', 0x0C: 'andi',
                 0x0D: 'ori', 0x0E: 'xori', 0x08: 'addi'}[op] if op in (
            0x0B, 0x0A, 0x09, 0x0C, 0x0D, 0x0E, 0x08) else None
        if not names or names not in sel:
            continue
        uimm, simm = imm, _s16(imm)
        ok = (uimm in imms) or (-simm in imms) or (simm in imms)
        if not ok:
            continue
        va = t['vaddr'] + i * 4
        rt, rs = (w >> 16) & 0x1F, (w >> 21) & 0x1F
        hits.append(dict(va=va, file_off=elf.off(va), word=w, mnem=names,
                         reg='%s, %s' % (GPR[rt], GPR[rs]), imm=imm))
    P('# gate-scan: %d 命中（%s 立即数 ∈ %s）' % (
        len(hits), '/'.join(sel), ','.join('0x%02X' % x for x in sorted(imms))))
    for h in hits[:a.limit]:
        P('')
        P('== VA 0x%06X file 0x%06X  %08X  %s %s, 0x%X' % (
            h['va'], h['file_off'], h['word'], h['mnem'], h['reg'], h['imm']))
        for row in ctx_block(elf, h['va'], a.ctx, a.ctx):
            P('   ' + row)
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump(hits, f, ensure_ascii=False, indent=1)
        P('[json] %s' % a.json)


# ---- disasm ----
def cmd_disasm(a):
    elf = Elf.pick(a.kind, a.path)[0]
    mark = {}
    if a.mark:
        for item in a.mark:
            for part in item.split(','):
                va, txt = part.split('=')
                mark[int(va, 16)] = txt
    if a.range:
        lo, hi = a.range.split(':')
        lo, hi = int(lo, 16), int(hi, 16)
        rows = dump_dis(elf, lo, (hi - lo) // 4, out=a.out, mark=mark)
        return
    if a.sym:
        ss = [s for s in elf.syms() if a.sym.lower() in s[3].lower()]
        if not ss:
            P('符号未找到: %s' % a.sym)
            return
        for val, sz, info, nm in ss[:a.limit]:
            P('### sym %s  va=0x%06X size=%d' % (nm, val, sz))
            dump_dis(elf, val, (sz // 4) or a.n, out=a.out)
        return
    for item in (a.at or []):
        for part in item.split(','):
            va = int(part, 16)
            dump_dis(elf, va, a.n, out=a.out, mark=mark)


def cmd_insn_search(a):
    elf = Elf.pick(a.kind, a.path)[0]
    rx = re.compile(a.pattern, re.I)
    t = elf.text
    lo, hi = t['vaddr'], t['vaddr'] + t['filesz']
    if a.range:
        lo, hi = [int(x, 16) for x in a.range.split(':')]
    hits = 0
    data = elf.read(lo, hi - lo)
    for addr, w, b, mn, ops in DIS.iter(data, lo):
        txt = '%s %s' % (mn, ops)
        if rx.search(txt):
            hits += 1
            P('== 0x%06X file 0x%06X  %08X  %s' % (addr, elf.off(addr), w, txt))
            for row in ctx_block(elf, addr, a.ctx, a.ctx):
                P('   ' + row)
            if hits >= a.limit:
                break
    P('# %d 命中（limit %d）' % (hits, a.limit))


def cmd_callers(a):
    elf = Elf.pick(a.kind, a.path)[0]
    targets = set()
    for item in a.targets:
        for p in item.split(','):
            targets.add(int(p, 16))
    t = elf.text
    data = elf.data[t['off']:t['off'] + t['filesz']]
    n = len(data) // 4
    W = struct.unpack_from('<%dI' % n, data, 0)
    P('# callers of %s' % ', '.join('0x%06X' % x for x in sorted(targets)))
    cnt = 0
    for i, w in enumerate(W):
        op = w >> 26
        if op not in (2, 3):
            continue
        pc = t['vaddr'] + i * 4
        tgt = ((w & 0x3FFFFFF) << 2) | (pc & 0xF0000000)
        if tgt in targets:
            cnt += 1
            P('  0x%06X (file 0x%06X) %s 0x%06X   [sym %s]' % (
                pc, elf.off(pc), 'jal' if op == 3 else 'j', tgt,
                (elf.sym_for(pc) or (0, 0, '?'))[2]))
    P('# total %d' % cnt)


# ---- cave 扫描 ----
def cmd_cave(a):
    elf = Elf.pick(a.kind, a.path)[0]
    t = elf.text
    data = elf.data[t['off']:t['off'] + t['filesz']]
    P('# cave 扫描: .text 0x%08X..0x%08X  min_len=%d' % (
        t['vaddr'], t['vaddr'] + t['filesz'], a.min))
    runs = []
    for m in re.finditer(b'\x00{%d,}' % a.min, data):
        va = t['vaddr'] + m.start()
        runs.append((va, m.end() - m.start()))
    P('# 全零岛 %d 段，共 %d B' % (len(runs), sum(r[1] for r in runs)))
    # 全 ELF 的跳转目标集合（用于校验）
    alltgt = set()
    if a.check:
        n = len(data) // 4
        W = struct.unpack_from('<%dI' % n, data, 0)
        for i, w in enumerate(W):
            op = w >> 26
            pc = t['vaddr'] + i * 4
            if op in (2, 3):
                alltgt.add(((w & 0x3FFFFFF) << 2) | (pc & 0xF0000000))
            elif op in (0x04, 0x05, 0x06, 0x07):
                alltgt.add(pc + 4 + (_s16(w) << 2))
            elif op == 0x01:      # regimm
                alltgt.add(pc + 4 + (_s16(w) << 2))
        # 全 ELF 中的地址引用（lui+addiu 对 / 裸字）
        ptrs = set()
        for m in re.finditer(re.escape(b''), b''):
            pass
        ref_rx = None
        all_words = struct.unpack_from('<%dI' % (len(elf.data) // 4), elf.data, 0)
        for w in all_words:
            op = w >> 26
            if op == 0x0F:                       # lui
                ptrs.add((w & 0xFFFF) << 16)
            elif op in (0x09, 0x0D):             # addiu / ori：记录低 16 位组合在检查时用
                pass
    for va, ln in runs:
        if ln < a.min:
            continue
        note = ''
        if a.check:
            bad = [x for x in range(va, va + ln, 4) if x in alltgt]
            note = '  jump_targets=%d' % len(bad)
            if bad:
                note += ' %s' % ['0x%06X' % x for x in bad[:6]]
        P('  VA 0x%06X .. 0x%06X  len %6d  file 0x%06X%s' % (
            va, va + ln, ln, t['off'] + (va - t['vaddr']), note))
        if a.limit and len(runs) > a.limit:
            pass


# ---- symbols ----
def cmd_symbols(a):
    elf = Elf.pick(a.kind or 'base', a.path)[0]
    ss = elf.syms()
    if not ss:
        P('# 无符号表（stripped）')
        return
    if a.grep:
        rx = re.compile(a.grep)
        hit = [s for s in ss if rx.search(s[3])]
        P('# %d 个符号匹配 %r' % (len(hit), a.grep))
        for val, sz, info, nm in hit[:a.limit]:
            P('  0x%08X size=%-6d %s' % (val, sz, nm))
        return
    for item in (a.near or []):
        va = int(item, 16)
        P('# near VA 0x%06X' % va)
        for val, sz, info, nm in elf.syms_near(va, a.k):
            P('  0x%08X size=%-6d %s' % (val, sz, nm))
    if a.dump:
        with open(a.dump, 'w', encoding='utf-8') as f:
            for val, sz, info, nm in ss:
                f.write('0x%08X\t%d\t%s\n' % (val, sz, nm))
        P('[dump] %s (%d symbols)' % (a.dump, len(ss)))


# ---- sim ----
def norm_keys(elf, va, n):
    """归一化指令键：R 型 = funct（0x100+），其他 = opcode；用于跨编译比较。"""
    ws = elf.words(va, n)
    return [0x100 + (w & 0x3F) if (w >> 26) == 0 else (w >> 26) for w in ws]


def best_window(keys_pat, keys_hay):
    """在 hay 上滑窗，返回 (best_off, score)。朴素实现，n 小。"""
    n = len(keys_pat)
    best = (-1, -1)
    for i in range(0, len(keys_hay) - n + 1):
        s = sum(1 for j in range(n) if keys_hay[i + j] == keys_pat[j])
        if s > best[1]:
            best = (i, s)
    return best


def cmd_sim(a):
    e1 = Elf.pick(a.kind, a.path)[0]
    e2 = Elf.pick(a.other, a.other_path)[0]
    k1 = norm_keys(e1, int(a.base_va, 16), a.n)
    region_va = int(a.other_va, 16) if a.other_va else e2.text['vaddr']
    hay_n = a.hay or 200000
    k2 = norm_keys(e2, region_va, min(hay_n, (e2.text['filesz']) // 4))
    off, score = best_window(k1, k2)
    P('sim %s:0x%s [%d insns]  vs  %s:0x%X.. [%d insns]' % (
        e1.tag, a.base_va, a.n, e2.tag, region_va, len(k2)))
    P('  best offset +0x%X  ==> VA 0x%06X  score %d/%d (%.0f%%)' % (
        off * 4, region_va + off * 4, score, a.n, 100.0 * score / a.n))
    P('  -- 并排（左 %s / 右 %s）--' % (e1.tag, e2.tag))
    for j in range(a.n):
        if j % a.group == 0:
            P('  -- insn %d --' % j)
        wa = e1.word(int(a.base_va, 16) + j * 4)
        va2 = region_va + (off + j) * 4
        try:
            wb = e2.word(va2)
        except SystemExit:
            wb = 0
        ma = DIS.one(wa, int(a.base_va, 16) + j * 4)
        mb = DIS.one(wb, va2)
        same = '=' if k1[j] == (0x100 + (wb & 0x3F) if (wb >> 26) == 0 else (wb >> 26)) else '!'
        P('  %s 0x%06X %08X %-8s %-30s | 0x%06X %08X %-8s %s' % (
            same, int(a.base_va, 16) + j * 4, wa, ma[0], ma[1], va2, wb, mb[0], mb[1]))


# ---- diff ----
def cmd_diff(a):
    e1 = Elf.pick(a.kind, a.path)[0]
    e2 = Elf.pick(a.other, a.other_path)[0]
    n = min(e1.size, e2.size)
    runs = []
    i = 0
    while i < n:
        if e1.data[i] != e2.data[i]:
            j = i
            while j < n and e1.data[j] != e2.data[j]:
                j += 1
            runs.append((i, j - i))
            i = j
        else:
            i += 1
    P('# diff %s (size %d) vs %s (size %d): %d runs / %d bytes' % (
        e1.tag, e1.size, e2.tag, e2.size, len(runs), sum(l for _, l in runs)))
    for off, ln in runs[:a.limit]:
        try:
            va = e1.va(off)
        except SystemExit:
            va = 0
        sym = ''
        if a.syms and va:
            s = e1.sym_for(va)
            if s:
                sym = ' [%s+0x%X]' % (s[2], va - s[0])
        P('  file 0x%08X VA 0x%08X len %d  %s -> %s%s' % (
            off, va, ln, e1.data[off:off + ln].hex(), e2.data[off:off + ln].hex(), sym))
    if len(runs) > a.limit:
        P('  ... %d more' % (len(runs) - a.limit))


# ---- dump ----
def cmd_dump(a):
    elf = Elf.pick(a.kind, a.path)[0]
    va = int(a.at, 16)
    data = elf.read(va, a.n)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, 'wb') as f:
        f.write(data)
    P('[dump] VA 0x%06X  %d B -> %s' % (va, len(data), a.out))


# ─────────────────────────────── main ───────────────────────────────
def main():
    ap = argparse.ArgumentParser(description='PS2 ELF 只读分析（GR DLC 汉化工程）')
    ap.add_argument('--elf', default='dlc', choices=['dlc', 'base', 'zh'],
                    help='目标 ELF：dlc=SLUS_208.20 / base=本体英文 / zh=本体汉化')
    ap.add_argument('--elf-path', default=None, help='直接指定 ELF 文件')
    sub = ap.add_subparsers(dest='cmd')

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_)
        p.set_defaults(fn=fn)
        p.add_argument('--json', default=None)
        return p

    p = add('info', cmd_info, 'ELF 头部/段/符号/字符串统计')
    p = add('crc', cmd_crc, 'PCSX2 Game CRC')
    p.add_argument('--set', action='append', default=[],
                   help='模拟补丁：VA=word[,VA=word] 计算打补丁后的 CRC')
    p = add('strings', cmd_strings, '内嵌字符串')
    p.add_argument('--min', type=int, default=4)
    p.add_argument('--grep', default=None)
    p.add_argument('--font', action='store_true')
    p.add_argument('--limit', type=int, default=200)
    p = add('gate-scan', cmd_gate_scan, 'DBCS 闸门/立即数扫描')
    p.add_argument('--imm', default=None, help='十六进制逗号分隔，默认 0xA0..0xC0,0xFF,0xFE,0x5E,0x0A,0x14,0x28')
    p.add_argument('--ops', default=None, help='默认 sltiu,slti,addiu,andi,ori')
    p.add_argument('--ctx', type=int, default=4)
    p.add_argument('--limit', type=int, default=80)
    p = add('disasm', cmd_disasm, '定点反汇编')
    p.add_argument('--at', action='append', default=[])
    p.add_argument('--range', default=None, help='VA:VA')
    p.add_argument('--sym', default=None, help='符号名子串（本体 ELF）')
    p.add_argument('--n', type=int, default=32)
    p.add_argument('--out', default=None)
    p.add_argument('--mark', action='append', default=[], help='VA=注释')
    p.add_argument('--limit', type=int, default=10)
    p = add('insn-search', cmd_insn_search, '反汇编文本正则搜索')
    p.add_argument('--pattern', required=True)
    p.add_argument('--range', default=None)
    p.add_argument('--ctx', type=int, default=3)
    p.add_argument('--limit', type=int, default=20)
    p = add('callers', cmd_callers, '找调用点')
    p.add_argument('--targets', action='append', required=True)
    p = add('cave', cmd_cave, '全零 cave 候选')
    p.add_argument('--min', type=int, default=64)
    p.add_argument('--check', action='store_true', help='校验跳转目标（较慢）')
    p.add_argument('--limit', type=int, default=200)
    p = add('symbols', cmd_symbols, '符号表')
    p.add_argument('--grep', default=None)
    p.add_argument('--near', action='append', default=[])
    p.add_argument('--k', type=int, default=4)
    p.add_argument('--dump', default=None)
    p.add_argument('--limit', type=int, default=200)
    p = add('sim', cmd_sim, '跨 ELF 指令级相似度')
    p.add_argument('--base-va', required=True)
    p.add_argument('--other', default='base', choices=['dlc', 'base', 'zh'])
    p.add_argument('--other-path', default=None)
    p.add_argument('--other-va', default=None)
    p.add_argument('--n', type=int, default=40)
    p.add_argument('--hay', type=int, default=0)
    p.add_argument('--group', type=int, default=1)
    p = add('diff', cmd_diff, '逐字节差异')
    p.add_argument('--other', default='zh', choices=['dlc', 'base', 'zh'])
    p.add_argument('--other-path', default=None)
    p.add_argument('--syms', action='store_true')
    p.add_argument('--limit', type=int, default=400)
    p = add('dump', cmd_dump, '导出字节')
    p.add_argument('--at', required=True)
    p.add_argument('--n', type=int, required=True)
    p.add_argument('--out', required=True)

    a = ap.parse_args()
    if not getattr(a, 'cmd', None):
        ap.print_help()
        return
    a.kind = a.elf
    a.path = a.elf_path
    a.fn(a)


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                            # noqa: BLE001
        pass
    main()
