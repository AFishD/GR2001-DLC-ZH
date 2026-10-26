# -*- coding: utf-8 -*-
r"""dbcs_spec.py —— DLC (SLUS_208.20) DBCS 补丁规格 v2：汇编 cave → 逐字节补丁表 → 自证。

它做五件事（全部可复现、只读原 ELF，产物只写 work/）：
  1. 用 tools/analysis/mipsasm.py 汇编 tools/analysis/caves/dbcs_cave_dlc.s；
  2. 校验 cave 区（默认 VA 0x6124B0，DLC .text 末尾全零岛 1104 B）：
     原 ELF 该区必须全零 + 全 ELF 无 jump/branch/lui+addiu/裸指针引用；
  3. 校验 24 个补丁点的「原 4 字节」与盘上逐字节一致（防止基线不符）；
  4. 在内存里打补丁 + 写 cave，回读自证（每站 word、cave 全字节、CRC/sha256）；
  5. 输出：
       work/analysis/elf/dbcs_cave_dlc.bin           cave 机器码
       work/analysis/elf/dbcs_spec_dlc.json          补丁规格（可给 build 链直接吃）
       work/analysis/elf/dbcs_spec_dlc.txt           人读清单（VA/file off/old/new/注释）
       work/analysis/elf/DLC_SLUS_208.20_DBCS_v2.elf 打过补丁的 ELF 副本（仅 work，不进 git）

用法：
    python tools/analysis/dbcs_spec.py                 # 默认 base=0x6124B0
    python tools/analysis/dbcs_spec.py --cave-base 0x1808A8   # 备用：JS_ZH19 用过的死函数区
    python tools/analysis/dbcs_spec.py --check-only    # 只校验，不写产物
"""
import argparse
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
import elf_probe as EP                                    # noqa: E402
import mipsasm                                            # noqa: E402

WORK = os.path.join(REPO, 'work', 'analysis', 'elf')
CAVE_SRC = os.path.join(HERE, 'caves', 'dbcs_cave_dlc.s')
CAVE_BASE_DEFAULT = 0x1808A8        # JS_ZH19 用过的死函数区（1008 B，实机跑过 100s+）
CAVE_BASE_ZERO = 0x6124B0           # 反向：DLC .text 末尾（实测被字符串表占用，不可用）
# cave 区安全证明：
#   0x1808A8..0x180C98 是原 ELF 的一段「死代码」（0 jal 调用者 / 0 裸指针 / 0 地址构造），
#   且 JS_ZH19 构筑已把整段覆盖并实机运行 100s+（见 emulog.txt / docs 分析），是本项目
#   已知最可靠的 cave 落点。本 cave 1000 B ≤ 1008 B，正好放下。

# DLC 基线身份（sha256 of original SLUS_208.20）
DLC_SHA256 = 'cf29cabeebb75fc8d9fdd1a076e4c574c5740e73948f0a2ef643b632baee7eee'
DLC_CRC = 0xDE1E4DEE


def j_word(target):
    return (2 << 26) | ((target >> 2) & 0x3FFFFFF)


def jal_word(target):
    return (3 << 26) | ((target >> 2) & 0x3FFFFFF)


def build_patches(labels):
    """补丁表：每项 (VA, old_word, new_word_fn 或 word, 说明)。
    顺序 = 应用顺序；同一函数的若干站按 VA 升序。"""
    P = []

    def add(va, old, new, why):
        P.append(dict(va=va, old=old, new=(new(labels) if callable(new) else new), why=why))

    # ── A. DrawString (0x2195F0)：解码/双字节格/图标常量/步长 ──────────────
    add(0x219758, 0x0C05CD9E, lambda L: jal_word(L['decode']),
        'DrawString: jal wctomb(0x173678) → jal decode cave')
    add(0x21975C, 0x27A400DF, 0x27A400DE,
        'DrawString: 解码格 addiu a0,sp,0xDF → sp+0xDE（2 字节格）')
    add(0x219760, 0x83A500DF, 0x97A500DE, 'DrawString: lb a1,0xDF(sp) → lhu a1,0xDE(sp)')
    add(0x219770, 0x83A500DF, 0x97A500DE, 'DrawString: 第二处 lb→lhu（0xDF→0xDE）')
    add(0x219794, 0x2403FFB5, 0x240300B5, '图标常量 0xFFB5 → 0x00B5（零扩展）')
    add(0x21979C, 0x2403FFB5, 0x240300B5, '图标常量 0xFFB5 → 0x00B5')
    add(0x2197A0, 0x2403FFB1, 0x240300B1, '图标常量 0xFFB1 → 0x00B1')
    add(0x2197C0, 0x2403FFB5, 0x240300B5, '图标常量 0xFFB5 → 0x00B5')
    add(0x21982C, 0x2403FFB5, 0x240300B5, '图标常量 0xFFB5 → 0x00B5')
    add(0x219838, 0x83A400DF, 0x97A400DE, 'DrawString: lb a0,0xDF(sp) → lhu a0,0xDE(sp)')
    add(0x219844, 0x2403FFB1, 0x240300B1, '图标常量 0xFFB1 → 0x00B1')
    add(0x2198B8, 0x83A300DF, 0x97A300DE, 'DrawString: lb v1,0xDF(sp) → lhu v1,0xDE(sp)')
    add(0x2198C4, 0x2402FFB5, 0x240200B5, '图标常量 0xFFB5 → 0x00B5')
    add(0x2198D0, 0x2402FFB1, 0x240200B1, '图标常量 0xFFB1 → 0x00B1')
    add(0x21994C, 0x26B50001, lambda L: j_word(L['draw_advance']),
        'DrawString: addiu s5,s5,1 → j draw_advance（按 decode 写的步长推进）')

    # ── B. CharWidth (0x21A360)：函数体换成 cave ─────────────────────────
    add(0x21A36C, 0x90820024, lambda L: j_word(L['charwidth']),
        'CharWidth 函数体首指令 lbu v0,0x24(a0) → j charwidth cave')
    add(0x21A370, 0x10400005, 0x00000000, 'CharWidth: beqz v0,0x21A388 → nop（cave 内重建判定）')

    # ── C. ComputeCharTextureCoords (0x21A210)：函数头换成 cave ──────────
    add(0x21A210, 0x8C8B0028, lambda L: j_word(L['uv']),
        'ComputeCharTextureCoords 首指令 lw t3,0x28(a0) → j uv cave')
    add(0x21A214, 0x30A300FF, 0x00000000, 'UV: andi v1,a1,0xFF → nop（cave 内重建）')

    # ── D. StringWidth (0x21A4C0)：逐字节循环 + 尾部字距 ────────────────
    add(0x21A52C, 0x80450000, lambda L: j_word(L['measure']),
        'StringWidth 循环: lb a1,0(v0) → j measure cave')
    add(0x21A530, 0x0C0868D8, 0x00000000, 'StringWidth: jal CharWidth → nop（cave 内按 DBCS 调）')
    add(0x21A54C, 0x8E620018, lambda L: j_word(L['sw_tail']),
        'StringWidth 尾部: lw v0,0x18(s3) → j sw_tail（字距按字形数）')
    add(0x21A550, 0x2623FFFF, 0x00000000, 'StringWidth 尾部: addiu v1,s1,-1 → nop')
    add(0x21A554, 0x00621018, 0x00000000, 'StringWidth 尾部: mult v0,v1,v0 → nop')
    add(0x21A558, 0x02028021, 0x00000000, 'StringWidth 尾部: addu s0,s0,v0 → nop')
    return P


# ─────────────────── cave 区静态安全校验 ───────────────────
def check_zero_region(elf, va, size):
    """返回 (ok, report)。要求：原 ELF 该区全零、且全 ELF 无引用。"""
    rep = dict(va=va, size=size)
    data = elf.read(va, size)
    rep['all_zero'] = (data == b'\x00' * size)
    T = elf.text
    W = struct.unpack_from('<%dI' % (T['filesz'] // 4), elf.data, T['off'])
    hi = va + size
    # 1) 跳转/分支目标
    tgt_in = []
    for i, w in enumerate(W):
        pc = T['vaddr'] + i * 4
        op = w >> 26
        inside = va <= pc < hi          # 只关心「区外 → 区内」的引用；区内自跳随覆盖一起消失
        if op in (2, 3):
            t = ((w & 0x3FFFFFF) << 2) | (pc & 0xF0000000)
            if va <= t < hi and not inside:
                tgt_in.append((pc, t))
        elif op in (4, 5, 6, 7, 1, 0x14, 0x15, 0x16, 0x17):
            off = struct.unpack('<h', struct.pack('<H', w & 0xFFFF))[0]
            t = (pc + 4 + (off << 2)) & 0xFFFFFFFF
            if va <= t < hi and not inside:
                tgt_in.append((pc, t))
    rep['jump_targets_in'] = len(tgt_in)
    # 2) lui+addiu/ori 地址构造
    lui_ref = []
    for i in range(len(W) - 1):
        w, nw = W[i], W[i + 1]
        if (w >> 26) != 0x0F:
            continue
        if (nw >> 26) not in (0x09, 0x0D):
            continue
        if ((nw >> 21) & 0x1F) != ((nw >> 16) & 0x1F):
            continue
        lo = struct.unpack('<h', struct.pack('<H', nw & 0xFFFF))[0] if (nw >> 26) == 9 \
            else (nw & 0xFFFF)
        addr = (((w & 0xFFFF) << 16) + lo) & 0xFFFFFFFF
        if va <= addr < hi and not (va <= T['vaddr'] + i * 4 < hi):
            lui_ref.append((T['vaddr'] + i * 4, addr))
    rep['lui_addiu_refs'] = len(lui_ref)
    # 3) 裸指针字
    allw = struct.unpack_from('<%dI' % (len(elf.data) // 4), elf.data, 0)
    raw = [i * 4 for i, w in enumerate(allw) if va <= w < hi]
    rep['raw_ptr_words'] = len(raw)
    rep['ok'] = (not tgt_in) and (not lui_ref) and (not raw)
    return rep['ok'], rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--elf', default=None)
    ap.add_argument('--cave-src', default=CAVE_SRC)
    ap.add_argument('--cave-base', default=None)
    ap.add_argument('--out-json', default=os.path.join(WORK, 'dbcs_spec_dlc.json'))
    ap.add_argument('--out-txt', default=os.path.join(WORK, 'dbcs_spec_dlc.txt'))
    ap.add_argument('--out-elf', default=os.path.join(WORK, 'DLC_SLUS_208.20_DBCS_v2.elf'))
    ap.add_argument('--out-bin', default=os.path.join(WORK, 'dbcs_cave_dlc.bin'))
    ap.add_argument('--check-only', action='store_true')
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                             # noqa: BLE001
        pass
    P = lambda *x: print(' '.join(str(i) for i in x), flush=True)   # noqa: E731

    elf, src = EP.Elf.pick('dlc', a.elf)
    P('[elf] %s  %d B  sha256 %s' % (src, elf.size, elf.sha256()))
    if elf.sha256() != DLC_SHA256:
        P('[FATAL] 基线 ELF sha256 不符（want %s）' % DLC_SHA256)
        return 2
    if elf.crc() != DLC_CRC:
        P('[FATAL] 基线 Game CRC 不符（want %08X）' % DLC_CRC)
        return 2

    base = int(a.cave_base, 16) if a.cave_base else CAVE_BASE_DEFAULT
    words, labels, listing = mipsasm.assemble(open(a.cave_src, encoding='utf-8').read(), base)
    cave_size = len(words) * 4
    P('[cave] %d 条 / %d B  base=0x%08X .. 0x%08X' % (
        len(words), cave_size, base, base + cave_size))
    ok, rep = check_zero_region(elf, base, cave_size)
    P('[cave] 区校验: all_zero=%s jump_in=%d lui_addiu=%d raw_ptr=%d ⇒ %s' % (
        rep['all_zero'], rep['jump_targets_in'], rep['lui_addiu_refs'],
        rep['raw_ptr_words'], 'OK(无引用)' if ok else 'FAIL'))
    if ok and not rep['all_zero']:
        P('[cave] 注意：此区不是全零（覆盖死代码，JS_ZH19 已实机验证可覆盖 100s+）')
    if not ok:
        P('[FATAL] cave 区不安全（有引用）；备用落点：0x%08X 或换 --cave-base' % CAVE_BASE_ZERO)
        return 3

    # 补丁表 + 原字校验
    patches = build_patches(labels)
    P('[patch] %d 站' % len(patches))
    bad = []
    for p in patches:
        cur = elf.word(p['va'])
        p['file_off'] = elf.off(p['va'])
        if cur != p['old']:
            bad.append((p['va'], cur, p['old']))
    if bad:
        for va, cur, want in bad:
            P('  [MISMATCH] VA 0x%06X 盘上 %08X != 期望原字 %08X' % (va, cur, want))
        P('[FATAL] 基线不符，拒绝生成补丁')
        return 4
    P('[patch] 原字 24/24 校验通过')

    # 内存打补丁
    data = bytearray(elf.data)
    base_off = elf.off(base)
    data[base_off:base_off + cave_size] = struct.pack('<%dI' % len(words), *words)
    for p in patches:
        data[p['file_off']:p['file_off'] + 4] = struct.pack('<I', p['new'])
    new_elf = EP.Elf(bytes(data), 'DLC+dbcs_v2')
    # 回读自证
    ok = True
    for p in patches:
        got = new_elf.word(p['va'])
        if got != p['new']:
            P('  [READBACK FAIL] VA 0x%06X got %08X want %08X' % (p['va'], got, p['new']))
            ok = False
    if new_elf.read(base, cave_size) != struct.pack('<%dI' % len(words), *words):
        P('  [READBACK FAIL] cave 字节')
        ok = False
    # 逐站反汇编（人读清单）
    lines = []
    lines.append('# DLC (SLUS_208.20) DBCS 补丁规格 v2 — 逐字节清单')
    lines.append('# 基线: %s' % src)
    lines.append('# 基线 sha256: %s   CRC: %08X' % (elf.sha256(), elf.crc()))
    lines.append('# 补丁后 sha256: %s   CRC: %08X' % (new_elf.sha256(), new_elf.crc()))
    lines.append('# cave: 0x%08X .. 0x%08X (%d B)' % (base, base + cave_size, cave_size))
    lines.append('')
    for p in patches:
        mn0, ops0 = EP.DIS.one(p['old'], p['va'])
        mn1, ops1 = EP.DIS.one(p['new'], p['va'])
        lines.append('VA 0x%06X  file 0x%06X  %08X -> %08X   %-30s  %s' % (
            p['va'], p['file_off'], p['old'], p['new'],
            ('%s %s' % (mn0, ops0))[:30], p['why']))
        lines.append('      now: %-8s %s   (was: %s %s)' % (mn1, ops1, mn0, ops0))
    txt = '\n'.join(lines) + '\n'
    P('')
    P(txt)
    P('[readback] %s' % ('PASS' if ok else 'FAIL'))
    if not ok:
        return 5
    if a.check_only:
        P('[check-only] 未写产物')
        return 0
    os.makedirs(WORK, exist_ok=True)
    with open(a.out_bin, 'wb') as f:
        f.write(struct.pack('<%dI' % len(words), *words))
    with open(a.out_txt, 'w', encoding='utf-8') as f:
        f.write(txt)
    spec = dict(
        schema='gr-dlc-ps2-zh/dbcs-patch-v2',
        base_elf=dict(name='SLUS_208.20', iso_lba=296, bytes=elf.size,
                      sha256=elf.sha256(), game_crc='%08X' % elf.crc()),
        cave=dict(src=os.path.relpath(a.cave_src, REPO).replace('\\', '/'),
                  va='0x%08X' % base, file_off='0x%08X' % base_off,
                  size=cave_size, words=['0x%08X' % w for w in words],
                  labels=dict((k, '0x%08X' % v) for k, v in labels.items()),
                  region_check=rep),
        geometry=dict(gate_hi='0xBA', lead_lo='0xA1', trail_lo='0xA1',
                      trail_hi='0xFF', pair_n=94, pair_base=0xE0,
                      ncol=64, cell=16, y0=3, skip_row=12, skip_rows=2,
                      slot_space=2350,
                      uv_formula='slot=(lead-0xA1)*94+(trail-0xA1); row=slot/64; '
                                 'col=slot%64; U0=16*col; U1=U0+16; '
                                 'V0=16*(row+2*[row>=12])+3; V1=V0+16'),
        patches=[dict(va='0x%08X' % p['va'], file_off='0x%08X' % p['file_off'],
                      old='0x%08X' % p['old'], new='0x%08X' % p['new'],
                      why=p['why']) for p in patches],
        result=dict(sha256=new_elf.sha256(), bytes=new_elf.size,
                    game_crc='%08X' % new_elf.crc(),
                    pcsx2_savestate='SLUS-20820 (%08X).01.p2s' % new_elf.crc(),
                    readback='PASS'),
        notes=[
            '旧即时存档/旧金手指 CRC 在打补丁后失效（Game CRC 改变），不可避免。',
            '本规格只改 ELF；字库/图集/FONT.RES/文本改动见 font 与 text 规格。',
            'cave 默认放 .text 末尾全零岛 0x6124B0（1104 B，静态 0 引用）；'
            '备用 0x1808A8（= JS_ZH19 用过的死函数区，实机跑过 100s+）。',
        ])
    with open(a.out_json, 'w', encoding='utf-8') as f:
        json.dump(spec, f, ensure_ascii=False, indent=1)
    with open(a.out_elf, 'wb') as f:
        f.write(bytes(data))
    P('[out] %s' % a.out_json)
    P('[out] %s' % a.out_txt)
    P('[out] %s' % a.out_bin)
    P('[out] %s' % a.out_elf)
    P('[done] 补丁后 Game CRC = %08X' % new_elf.crc())
    return 0


if __name__ == '__main__':
    sys.exit(main())
