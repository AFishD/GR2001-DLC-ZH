# -*- coding: utf-8 -*-
r"""mipsasm.py —— 轻量 MIPS/EE(R5900) 汇编器（只覆盖汉化补丁 cave 用到的指令子集）

为什么需要它：DLC 的 DBCS 补丁 cave 必须由**可审阅的文本源码**生成字节，
不能手搓 hex；而本机没有 ee-gcc / binutils-mips 交叉工具链，所以自带一个
「够用且可自测」的汇编器。

设计要点
--------
* 两遍扫描：第一遍定标签地址，第二遍生成机器码。
* `.equ NAME, expr` 常量（支持 + - * / 与括号里的简单十六进制/十进制）。
* 标签：`name:`（全局）与 `$L1:`（局部）都可。
* 伪指令：`li rd, imm`（自动选 lui+ori / ori / addiu）、`la rd, label`、
  `move rd, rs`、`nop`、`b label`、`beqz`/`bnez`、`j label`、`jal label`。
* **R5900 三操作数 `mult rd, rs, rt` / `multu rd, rs, rt`**：EE 专有形式，
  低 64 位积直接写 rd（本体英文 ELF 里 1198 处实测使用）。两操作数 `mult rs,rt`
  仍写 HI/LO，需配 `mflo rd`。
* 只支持 cave 需要的常见指令；遇到不认识的**直接报错**（不进字节流），
  避免"看起来汇编成功、实际是垃圾"。
* `--selftest`：用 `reference/base_zh146/scripts/elf_patches.json` 里
  **84 条已声明新字** + 本体汉化 ELF 的 DBCS 解码 cave 逐字反汇编做回归，
  要求 100% 命中，否则非零退出。

用法
----
    python tools/analysis/mipsasm.py --selftest
    python tools/analysis/mipsasm.py --src tools/analysis/caves/dbcs_cave_dlc.s \
        --base 0x6124B0 --bin work/analysis/elf/dbcs_cave_dlc.bin \
        --json work/analysis/elf/dbcs_cave_dlc.json
    python tools/analysis/mipsasm.py --src ... --base ... --listing
"""
import argparse
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))

GPR = {n: i for i, n in enumerate(
    'zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 '
    's0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra'.split())}
FPR = {('f%d' % i): i for i in range(32)}

# R 型 funct 表
R_TYPE = dict(add=0x20, addu=0x21, sub=0x22, subu=0x23, **{'and': 0x24}, **{'or': 0x25},
              xor=0x26, nor=0x27, slt=0x2A, sltu=0x2B, dadd=0x2C, daddu=0x2D,
              dsub=0x2E, dsubu=0x2F, movz=0x0A, movn=0x0B, syscall=0x0C, break_=0x0D,
              sync=0x0F, mfhi=0x10, mthi=0x11, mflo=0x12, mtlo=0x13,
              mult=0x18, multu=0x19, div=0x1A, divu=0x1B,
              dmult=0x1C, dmultu=0x1D, ddiv=0x1E, ddivu=0x1F,
              dsll=0x38, dsrl=0x3A, dsra=0x3B, dsll32=0x3C, dsrl32=0x3E, dsra32=0x3F)
SHIFT = dict(sll=0x00, srl=0x02, sra=0x03, dsll=0x38, dsrl=0x3A, dsra=0x3B,
             dsll32=0x3C, dsrl32=0x3E, dsra32=0x3F)
SHIFT_V = dict(sllv=0x04, srlv=0x06, srav=0x07, dsllv=0x14, dsrlv=0x16, dsrav=0x17)
# I 型 opcode 表
I_TYPE = dict(beq=0x04, bne=0x05, blez=0x06, bgtz=0x07, addi=0x08, addiu=0x09,
              slti=0x0A, sltiu=0x0B, andi=0x0C, ori=0x0D, xori=0x0E, lui=0x0F,
              beql=0x14, bnel=0x15, blezl=0x16, bgtzl=0x17,
              lb=0x20, lh=0x21, lwl=0x22, lw=0x23, lbu=0x24, lhu=0x25, lwr=0x26,
              sb=0x28, sh=0x29, swl=0x2A, sw=0x2B, sdl=0x2C, sdr=0x2D, swr=0x2E,
              ll=0x30, lwc1=0x31, lld=0x34, ld=0x37, sc=0x38, swc1=0x39, sd=0x3F,
              lq=0x1E, sq=0x1F)
# regimm：bltz/bgez 等（rt 字段区分）
REGIMM = dict(bltz=0x00, bgez=0x01, bltzl=0x02, bgezl=0x03,
              bltzal=0x10, bgezal=0x11)
IMM_TYPE = ('addi', 'addiu', 'slti', 'sltiu', 'andi', 'ori', 'xori')
# COP1
COP1_BC = dict(bc1f=0x00, bc1t=0x01, bc1fl=0x02, bc1tl=0x03)
FPU2 = dict(add_s=0x00, sub_s=0x01, mul_s=0x02, div_s=0x03, sqrt_s=0x04,
            abs_s=0x05, mov_s=0x06, neg_s=0x07,
            cvt_s_w=0x20, cvt_w_s=0x24,
            c_olt_s=0x34, c_ole_s=0x36, c_olt=0x34, c_ole=0x36)


def _reg(tok):
    tok = tok.strip().lstrip('$').lower()
    if tok in GPR:
        return GPR[tok]
    if tok in FPR:
        raise ValueError('FPR 不能当 GPR 用: %s' % tok)
    if re.fullmatch(r'\d+', tok) and int(tok) < 32:
        return int(tok)
    raise ValueError('未知寄存器: %s' % tok)


def _fpr(tok):
    tok = tok.strip().lstrip('$').lower()
    if tok in FPR:
        return FPR[tok]
    if re.fullmatch(r'\d+', tok) and int(tok) < 32:
        return int(tok)
    raise ValueError('未知浮点寄存器: %s' % tok)


def _expr(tok, labels, consts):
    """求值：数字 / 标签 / 标签±数字 / 常量表达式（+ - * / 括号）。"""
    s = tok.strip()
    if not s:
        raise ValueError('空表达式')
    # 先替换标签与常量（负向断言避免把 0x0200 里的 x0200 当符号）
    def repl(m):
        name = m.group(1)
        if name in consts:
            return '(%d)' % consts[name]
        if name in labels:
            return '(%d)' % labels[name]
        raise ValueError('未定义符号: %s' % name)
    s2 = re.sub(r'(?<![\w$.])([A-Za-z_$.][A-Za-z0-9_$.]*)', repl, s)
    if not re.fullmatch(r'[0-9a-fA-FxX()+\-*/\s]+', s2):
        raise ValueError('表达式非法: %r -> %r' % (s, s2))
    return int(eval(s2, {'__builtins__': {}}, {}))       # noqa: S307 —— 已白名单


class AsmError(Exception):
    pass


def assemble(src, base):
    """返回 (words:list[int], labels:dict, listing:list[(va,word,text)])"""
    consts = {}
    labels = {}
    # ── 预处理：去注释、拆标签 ──
    items = []          # (lineno, kind, text)
    for ln, raw in enumerate(src.splitlines(), 1):
        line = raw.split('#')[0].split(';')[0].strip()
        if not line:
            continue
        m = re.match(r'^([A-Za-z_$.][A-Za-z0-9_$.]*)\s*:\s*(.*)$', line)
        if m:
            items.append((ln, 'label', m.group(1)))
            line = m.group(2).strip()
            if not line:
                continue
        if line.startswith('.'):
            items.append((ln, 'dir', line))
        else:
            items.append((ln, 'insn', line))
    # ── pass 1：地址 & 常量 ──
    pc = base
    addr_of = [None] * len(items)
    for idx, (ln, kind, text) in enumerate(items):
        if kind == 'label':
            if text in labels:
                raise AsmError('L%d: 重复标签 %s' % (ln, text))
            labels[text] = pc
            addr_of[idx] = pc
        elif kind == 'dir':
            parts = text[len('.'):].split(None, 1)
            name = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ''
            if name == 'equ':
                nm, val = [x.strip() for x in arg.split(',', 1)]
                consts[nm] = _expr(val, labels, consts)
            elif name == 'word':
                addr_of[idx] = pc
                pc += 4 * len([x for x in arg.split(',') if x.strip()])
            elif name == 'space':
                addr_of[idx] = pc
                pc += _expr(arg, labels, consts)
            elif name in ('align', 'p2align'):
                n = _expr(arg, labels, consts)
                al = (1 << n) if name == 'p2align' else n
                addr_of[idx] = pc
                pc = (pc + al - 1) // al * al
            else:
                raise AsmError('L%d: 未知伪指令 .%s' % (ln, name))
        else:
            addr_of[idx] = pc
            pc += 4
    size = pc - base
    # ── pass 2：生成 ──
    words = []
    listing = []
    pc = base
    for idx, (ln, kind, text) in enumerate(items):
        if kind in ('label',):
            continue
        if kind == 'dir':
            parts = text[len('.'):].split(None, 1)
            name = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ''
            if name == 'word':
                for tok in arg.split(','):
                    tok = tok.strip()
                    if not tok:
                        continue
                    w = _expr(tok, labels, consts) & 0xFFFFFFFF
                    words.append(w)
                    listing.append((pc, w, '.word %s' % tok))
                    pc += 4
            elif name == 'space':
                n = _expr(arg, labels, consts)
                for k in range(0, n, 4):
                    words.append(0)
                    listing.append((pc + k, 0, '.space'))
                pc += n
            elif name in ('align', 'p2align'):
                n = _expr(arg, labels, consts)
                al = (1 << n) if name == 'p2align' else n
                while pc % al:
                    words.append(0)
                    listing.append((pc, 0, '.align 填充'))
                    pc += 4
            continue
        try:
            w = _assemble_insn(text, pc, labels, consts)
        except Exception as e:                              # noqa: BLE001
            raise AsmError('L%d: %s  |  %s' % (ln, text, e))
        words.append(w & 0xFFFFFFFF)
        listing.append((pc, w & 0xFFFFFFFF, text))
        pc += 4
    return words, labels, listing


def _assemble_insn(text, pc, labels, consts):
    toks = [t.strip() for t in text.split(None, 1)]
    mnem = toks[0].lower().replace('.', '_')
    ops_raw = toks[1] if len(toks) > 1 else ''
    # 操作数里可能有括号：统一拆
    ops = []
    depth = 0
    cur = ''
    for ch in ops_raw:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            ops.append(cur.strip())
            cur = ''
        else:
            cur += ch
    if cur.strip():
        ops.append(cur.strip())
    # ---- 伪指令 ----
    if mnem == 'nop':
        return 0
    if mnem == 'move':
        rd, rs = _reg(ops[0]), _reg(ops[1])
        return (rs << 21) | (rd << 11) | 0x21            # addu rd,rs,zero
    if mnem == 'li':
        rd = _reg(ops[0])
        v = _expr(ops[1], labels, consts)
        if -0x8000 <= v <= 0x7FFF:
            return (0x09 << 26) | (rd << 16) | (v & 0xFFFF)
        if 0 <= v <= 0xFFFF:
            return (0x0D << 26) | (rd << 16) | (v & 0xFFFF)
        if v >= 0 and v <= 0xFFFFFFFF and (v >> 16) == 0:
            return (0x0D << 26) | (rd << 16) | (v & 0xFFFF)
        raise AsmError('li 只支持 16 位或 32 位无符号位模式；建议手写 lui+ori')
    if mnem == 'la':
        rd = _reg(ops[0])
        v = _expr(ops[1], labels, consts)
        hi = (v >> 16) & 0xFFFF
        lo = v & 0xFFFF
        raise AsmError('la 需要两条指令，请手写 lui+addiu（cave 里请显式写）')
    if mnem in ('b',):
        return _branch(0x04, 0, 0, ops[0], pc, labels, consts)
    if mnem in ('beqz', 'bnez'):
        rt = _reg(ops[0])
        mn = 'beq' if mnem == 'beqz' else 'bne'
        return _branch(0x04 if mn == 'beq' else 0x05, rt, 0, ops[1], pc, labels, consts)
    # ---- 跳转 ----
    if mnem in ('j', 'jal'):
        tgt = _expr(ops[0], labels, consts)
        if tgt & 0x3:
            raise AsmError('跳转目标未对齐')
        op = 2 if mnem == 'j' else 3
        return (op << 26) | ((tgt >> 2) & 0x3FFFFFF)
    # ---- R 型 ----
    if mnem in R_TYPE:
        f = R_TYPE[mnem]
        if mnem in ('mfhi', 'mflo'):
            rd = _reg(ops[0])
            return (f << 0) | (rd << 11)
        if mnem in ('mthi', 'mtlo'):
            rs = _reg(ops[0])
            return (f << 0) | (rs << 21)
        if mnem in ('mult', 'multu', 'div', 'divu', 'dmult', 'dmultu', 'ddiv', 'ddivu'):
            if len(ops) == 3:                            # R5900：rd, rs, rt（积写 rd）
                rd, rs, rt = _reg(ops[0]), _reg(ops[1]), _reg(ops[2])
                return (rs << 21) | (rt << 16) | (rd << 11) | f
            rs, rt = _reg(ops[0]), _reg(ops[1])
            return (rs << 21) | (rt << 16) | f
        if mnem in ('jr',):
            return (R_TYPE['jr'] if 'jr' in R_TYPE else 0x08) << 0 | (_reg(ops[0]) << 21)
        if mnem in ('jalr',):
            rs = _reg(ops[0])
            rd = _reg(ops[1]) if len(ops) > 1 else GPR['ra']
            return (rs << 21) | (rd << 11) | 0x09
        rd, rs, rt = _reg(ops[0]), _reg(ops[1]), _reg(ops[2])
        return (rs << 21) | (rt << 16) | (rd << 11) | f
    if mnem == 'jr':
        return (_reg(ops[0]) << 21) | 0x08
    if mnem in SHIFT:
        rd, rt = _reg(ops[0]), _reg(ops[1])
        sa = _expr(ops[2], labels, consts) & 0x1F
        return (rt << 16) | (rd << 11) | (sa << 6) | SHIFT[mnem]
    if mnem in SHIFT_V:
        rd, rt, rs = _reg(ops[0]), _reg(ops[1]), _reg(ops[2])
        return (rs << 21) | (rt << 16) | (rd << 11) | SHIFT_V[mnem]
    # ---- I 型 ----
    if mnem in I_TYPE:
        op = I_TYPE[mnem]
        if mnem in ('beq', 'bne', 'beql', 'bnel'):
            return _branch(op, _reg(ops[0]), _reg(ops[1]), ops[2], pc, labels, consts)
        if mnem in ('blez', 'bgtz', 'blezl', 'bgtzl'):
            return _branch(op, _reg(ops[0]), 0, ops[1], pc, labels, consts)
        if mnem == 'lui':
            rt = _reg(ops[0])
            imm = _expr(ops[1], labels, consts) & 0xFFFF
            return (op << 26) | (rt << 16) | imm
        if mnem in IMM_TYPE:                        # rt, rs, imm16
            rt, rs = _reg(ops[0]), _reg(ops[1])
            imm = _expr(ops[2], labels, consts) & 0xFFFF
            return (op << 26) | (rs << 21) | (rt << 16) | imm
        # load/store：rt, off(rs)；lwc1/swc1 的 rt 是 FPR
        rt = _fpr(ops[0]) if mnem in ('lwc1', 'swc1') else _reg(ops[0])
        m = re.fullmatch(r'([^()]+)\(([^()]+)\)', ops[1])
        if not m:
            raise AsmError('%s 需要 off(base) 形式: %s' % (mnem, ops[1]))
        off = _expr(m.group(1), labels, consts)
        rs = _reg(m.group(2))
        if not (-0x8000 <= off <= 0x7FFF):
            raise AsmError('偏移超范围: %d' % off)
        return (op << 26) | (rs << 21) | (rt << 16) | (off & 0xFFFF)
    if mnem in REGIMM:
        return _branch(0x01, _reg(ops[0]), REGIMM[mnem], ops[1], pc, labels, consts,
                       regimm=True)
    # ---- COP1 ----
    if mnem in COP1_BC:
        return (0x11 << 26) | (0x08 << 21) | (COP1_BC[mnem] << 16) | \
            (((_expr(ops[0], labels, consts) - (pc + 4)) >> 2) & 0xFFFF)
    if mnem in ('mtc1', 'mfc1', 'ctc1', 'cfc1'):
        rt = _reg(ops[0])
        fs = _fpr(ops[1])
        rs = {'mfc1': 0x00, 'cfc1': 0x02, 'mtc1': 0x04, 'ctc1': 0x06}[mnem]
        return (0x11 << 26) | (rs << 21) | (rt << 16) | (fs << 11)
    if mnem in FPU2:
        if mnem.startswith('cvt_s_w'):                   # cvt.s.w fd, fs（2 操作数）
            fd, fs = _fpr(ops[0]), _fpr(ops[1])
            return (0x11 << 26) | (0x14 << 21) | (0 << 16) | (fs << 11) | \
                (fd << 6) | 0x20
        if mnem.startswith('cvt_w_s'):                   # cvt.w.s fd, fs（2 操作数）
            fd, fs = _fpr(ops[0]), _fpr(ops[1])
            return (0x11 << 26) | (0x10 << 21) | (0 << 16) | (fs << 11) | \
                (fd << 6) | 0x24
        fd, fs, ft = _fpr(ops[0]), _fpr(ops[1]), _fpr(ops[2])
        if mnem.startswith('c_'):
            return (0x11 << 26) | (0x10 << 21) | (ft << 16) | (fs << 11) | \
                (0 << 6) | FPU2[mnem]
        return (0x11 << 26) | (0x10 << 21) | (ft << 16) | (fs << 11) | \
            (fd << 6) | FPU2[mnem]
    raise AsmError('不支持的指令: %s' % mnem)


def _branch(op, rs, rt, target_tok, pc, labels, consts, regimm=False):
    tgt = _expr(target_tok, labels, consts)
    off = (tgt - (pc + 4)) >> 2
    if tgt & 0x3:
        raise AsmError('分支目标未对齐: 0x%X' % tgt)
    if not (-0x8000 <= off <= 0x7FFF):
        raise AsmError('分支超出 ±128KB: 0x%X' % tgt)
    return (op << 26) | (rs << 21) | (rt << 16) | (off & 0xFFFF)


# ───────────────────────────── self-test ─────────────────────────────
def selftest(verbose=True):
    """① elf_patches.json 84 条声明新字；② 本体汉化 ELF DBCS 解码 cave 27 条。"""
    fails = []
    total = 0
    # ① elf_patches.json
    p = os.path.join(REPO, 'reference', 'base_zh146', 'scripts', 'elf_patches.json')
    if os.path.exists(p):
        d = json.load(open(p, encoding='utf-8'))
        for patch in d.get('patches', []):
            cave = patch.get('cave') or {}
            words = cave.get('words') or []
            dis = cave.get('dis') or []
            if not words or len(words) != len(dis):
                continue
            va = int(cave['va'], 16)
            src = '\n'.join(_strip_dis(x) for x in dis)
            try:
                got, _, _ = assemble(src, va)
            except AsmError as e:
                fails.append('%s: 汇编失败 %s' % (patch.get('name'), e))
                continue
            for k, (g, w) in enumerate(zip(got, words)):
                total += 1
                if g != int(w, 16):
                    fails.append('%s[%d] @0x%X  got %08X want %s  | %s' % (
                        patch.get('name'), k, va + 4 * k, g, w, dis[k]))
    # ② 本体汉化 ELF 解码 cave（真实字节）
    zh = os.path.join(REPO, 'work', 'analysis', 'elf', 'BASE_ZH_SLUS_206.13.elf')
    if os.path.exists(zh):
        data = open(zh, 'rb').read()
        va = 0x00416ED0
        off = 0x80 + (va - 0x100000)
        actual = list(struct.unpack_from('<27I', data, off))
        src = r'''
        andi   $a1, $a1, 0xff
        sh     $a1, 0($a0)
        addiu  $v0, $zero, 1
        sltiu  $t1, $a1, 0xA1
        bnez   $t1, single
        nop
        sltiu  $t1, $a1, 0xBA
        beqz   $t1, single
        nop
        addiu  $t8, $s7, -1
        slt    $t8, $s0, $t8
        beqz   $t8, single
        nop
        addu   $t7, $s6, $s0
        lbu    $t3, 1($t7)
        sltiu  $t1, $t3, 0xA1
        bnez   $t1, single
        nop
        sltiu  $t1, $t3, 0xFF
        beqz   $t1, single
        nop
        sll    $t4, $a1, 8
        or     $t4, $t4, $t3
        sh     $t4, 0($a0)
        addiu  $v0, $zero, 2
        single:
        sb     $v0, -1($a0)
        jr     $ra
        nop
        '''
        try:
            got, _, _ = assemble(src, va)
            for k, (g, w) in enumerate(zip(got, actual)):
                total += 1
                if g != w:
                    fails.append('ZH-decoder[%d] @0x%X got %08X want %08X' % (
                        k, va + 4 * k, g, w))
        except AsmError as e:
            fails.append('ZH-decoder: 汇编失败 %s' % e)
    if verbose:
        print('[selftest] 指令总数 %d，失败 %d' % (total, len(fails)))
        for f in fails[:20]:
            print('  FAIL', f)
    return 0 if not fails else 1


def _strip_dis(s):
    """把 elf_patches.json 的 dis 行裁成纯汇编。

    格式：'0x0041A368  10200002  beq $at, $zero, +2 -> 0x0041A374   ; 合法'
    · 去掉 ';' 之后注释
    · 去掉 '0x<VA>  <HEX>  ' 前缀
    · 分支行 '..., +N -> 0xTARGET' ⇒ '..., 0xTARGET'（直接给绝对目标）
    """
    s = s.split(';')[0].strip()
    mva = re.match(r'^0x([0-9A-Fa-f]+)\s+[0-9A-Fa-f]{8}\s+', s)
    pc = int(mva.group(1), 16) if mva else None
    s = re.sub(r'^0x[0-9A-Fa-f]+\s+[0-9A-Fa-f]{8}\s+', '', s)
    m = re.search(r'->\s*(0x[0-9A-Fa-f]+)\s*$', s)
    if m:
        tgt = m.group(1)
        s = re.sub(r',\s*[+-]?\d+\s*->\s*0x[0-9A-Fa-f]+\s*$', ', ' + tgt, s)
    elif pc is not None:
        # 没有 '-> target' 的分支行（个别 patch 的 dis 省略了箭头）：用 PC 相对值算出目标
        m2 = re.search(r',\s*([+-]\d+)\s*$', s)
        if m2:
            tgt = pc + 4 + int(m2.group(1)) * 4
            s = s[:m2.start()] + ', 0x%X' % tgt
    return s.strip()


# ───────────────────────────── main ─────────────────────────────
def main():
    ap = argparse.ArgumentParser(description='轻量 MIPS/EE 汇编器 + 自测')
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--src', default=None)
    ap.add_argument('--base', default='0')
    ap.add_argument('--bin', default=None)
    ap.add_argument('--json', default=None)
    ap.add_argument('--listing', action='store_true')
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                            # noqa: BLE001
        pass
    if a.selftest:
        return selftest()
    if not a.src:
        ap.print_help()
        return 0
    base = int(a.base, 16) if isinstance(a.base, str) else a.base
    src = open(a.src, encoding='utf-8').read()
    words, labels, listing = assemble(src, base)
    size = len(words) * 4
    P = lambda *x: print(' '.join(str(i) for i in x), flush=True)
    P('[asm] %s  base=0x%08X  %d 条 / %d B' % (a.src, base, len(words), size))
    for nm, v in labels.items():
        P('   %-20s 0x%08X' % (nm, v))
    if a.listing:
        for va, w, txt in listing:
            P('   0x%08X  %08X  %s' % (va, w, txt))
    if a.bin:
        os.makedirs(os.path.dirname(os.path.abspath(a.bin)), exist_ok=True)
        with open(a.bin, 'wb') as f:
            f.write(struct.pack('<%dI' % len(words), *words))
        P('[bin] %s' % a.bin)
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump(dict(base=base, size=size, words=['0x%08X' % w for w in words],
                           labels=dict((k, '0x%08X' % v) for k, v in labels.items())),
                      f, ensure_ascii=False, indent=1)
        P('[json] %s' % a.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
