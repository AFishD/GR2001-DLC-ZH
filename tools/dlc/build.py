# -*- coding: utf-8 -*-
r"""build.py —— 资料片汉化**唯一**构筑脚本（从英文原盘出发，无依赖链）。

一条命令做完全部构筑相关的事：

    python tools\dlc\build.py --stage list
    python tools\dlc\build.py --stage spec          # 重新生成 ELF 补丁表 elf_patches.json
    python tools\dlc\build.py --stage all           # 全量构筑（font + text + elf）→ ISO
    python tools\dlc\build.py --stage font|text|elf # 分阶段构筑（开发用）
    python tools\dlc\build.py --stage dump-text     # 抽取文本表格（原文/译文对照 CSV）

设计（对应 docs/PLAN.md 纪律 2）：
  · 每个阶段都**从英文原盘重建**：在原盘基础上叠加「截至本阶段的全部替换」；
    不存在「阶段 N 消费阶段 N-1 的 ISO」的隐式依赖（中间盘只是快照，可随时删）。
  · 内容替换 = {GR.IMG 条目名/索引: 新 payload blob} + 可选新 ELF；
    由 tools/dlc/rebuild.py 写回 ISO（条目表/ISO9660 尺寸自动维护）。
  · 每阶段产物比对 fix_spec.json 里的 expect_sha256（第一次用 --write-spec 生成）。
  · ELF 补丁表（elf_patches.json）也由本脚本 `--stage spec` 生成，不再有第二份构筑脚本：
    DBCS v2 规格 + 字库最近邻过滤 + A‴ 行盒锚点 + RSString 串越界/NULL 守卫。

内容来源（全部可复现、只读原盘/本地 seed）：
  font : tools/font/fontlib.py —— 中文图集 1024×644 PSMT4 + 合并 FONT.RES
  text : tools/dlc/inject_text.py —— LANG/SFXML/MIS 译文注入（assets/text/ 下资产）
  elf  : --stage spec 产出的 tools/dlc/elf_patches.json
"""
import argparse
import hashlib
import json
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, 'tools', 'font'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'analysis'))

import dlclib as L                                             # noqa: E402
import rebuild as R                                            # noqa: E402

SPEC_PATH = os.path.join(HERE, 'fix_spec.json')
ELF_SPEC_PATH = os.path.join(HERE, 'elf_patches.json')
ELF_DBCS_SPEC = os.path.join(REPO, 'work', 'analysis', 'elf', 'dbcs_spec_dlc.json')
ELF_BASE_ELF = os.path.join(REPO, 'work', 'analysis', 'elf', 'DLC_SLUS_208.20.elf')
BUILD_DIR = os.path.join(REPO, 'work', 'builds')
TEXT_TABLE_DIR = os.path.join(REPO, 'work', 'analysis', 'text', 'tables')

# 阶段表：id -> 标题
STAGES = [
    ('font', '中文字库：中文图集 1024×644 PSMT4 + 合并 FONT.RES（GR#9 / GR#580）'),
    ('text', '文本层：EN_STRINGS.RES + EN_SPECIAL_FEATURE.XML + *.MIS（全部译文）'),
    ('elf', 'ELF 补丁：DBCS 双字节 decoder cave + 字库过滤 + 行盒锚点 + 串守卫'),
    ('all', '全量（font + text + elf）'),
    ('spec', '重新生成 ELF 补丁表 elf_patches.json（DBCS 规格 + 过滤/行盒 + 串守卫）'),
    ('dump-text', '抽取文本表格（原文 + 译文对照 CSV）到 work/analysis/text/tables/'),
]


def P(*a):
    print(' '.join(str(x) for x in a), flush=True)


def sha256_file(path):
    return L.sha256_file(path)


def _elf_crc(buf):
    crc = 0
    for (w,) in struct.iter_unpack('<I', bytes(buf)[:len(buf) // 4 * 4]):
        crc ^= w
    return crc


# ═════════════════════════ ELF 补丁表（--stage spec） ═════════════════════════
# ★ 字体纹理采样：字库路径 SetLinearSampling(true→false) + 状态缓存早退 beq→nop。
#   来源：本体汉化工程 docs/PATCH_INVENTORY.md §C「纹理过滤 (最近邻) —— ZH50 集」
#     · RSFontMgr 字库绘制路径 0x2192D0: jal 0x4FD5B0(SetLinearSampling) 的延迟槽 li a1,1
#       @VA 0x219314（file 0x119414）
#     · UIPacket::SetLinearSampling 0x4FD5B0 状态缓存早退 beq a0,v1 @VA 0x4FD5CC（file 0x3FD6CC）
#   中文图集是 PSMT4 1-bit（无 62 级 AA），必须关掉双线性否则笔画边缘漏墨/发虚。
#
# ★ 字体 quad 高度/底对齐（A‴ v8，见 docs/ANALYSIS_FONT.md §14）：
#   DrawString 0x2195F0 非图标分支：y1 = f23（行顶），y2 = f23 + CharHeight（0x21984C 延迟槽）。
#   度量恢复后 CharHeight 回到 EN 口径（26/42…），但字形仍是 16px 图集 ⇒ quad 高钉 16px、
#   底对齐到 CharHeight 行盒底（y2 原指令保留；y1 = y2 − 16 由 cave 算）。
#   站点 0x219894 → j CAVE @VA 0x575D04；0x219898 预存点 nop；cave 终跳 0x21989C。
ELF_EXTRA_PATCHES = [
    dict(file_off=0x119414, orig_hex='01000524', new_hex='00000524',
         why='RSFontMgr 字库路径 SetLinearSampling(1→0)：文字纹理最近邻采样（参考本体 ZH50 过滤集）'),
    dict(file_off=0x3FD6CC, orig_hex='38008310', new_hex='00000000',
         why='UIPacket::SetLinearSampling 状态缓存早退 beq→nop（否则 false 被缓存吞掉）'),
    dict(file_off=0x83084, orig_hex='00' * 60,
         new_hex='2042083c00108844361017460900004500000000c843083c0010884436b80246040000'
                 '45000000000040083c0010884441080246bcd4150800000000',
         why='v11 cave C：中段正文 40<=y<400 再 -2px（v9 的 0 与 v10 的 -4 取中值）'),
    dict(file_off=0x4753F0, orig_hex='00' * 32,
         new_hex='40081746000081e68041083c00108844801001460000c2e62766080800000000',
         why='v11 cave B：写 y1/y2（16px 高）并跳回 DrawString 0x21989C'),
    # ★ 提示条 0.7s Info⇄Soldier 交替 → 固定显示语境文本（v35）
    #   A: 0x2C87A0 tick 里 beqz v0,0x2C8800（v0 = 0x7A4 半周期门闩）→ b 0x2C8800：
    #      永远走「语境分支」：名册恒 I229「队员信息」、装备焦点恒「武器」、属性焦点恒「统计」。
    dict(file_off=0x1C88A0, orig_hex='17004010', new_hex='17000010',
         why='提示条：beqz 0x2C87A0 → b（永远走语境分支，名册固定显示 队员信息）'),
    #   B: 0x2B8578 激活时槽 2 初值 ori a2,v0,0x1D(I029 Info) → 0xE5(I229 队员信息)，
    #      消掉进入后 ≤0.7s 的「信息」闪。
    dict(file_off=0x1B8678, orig_hex='1d004634', new_hex='e5004634',
         why='提示条：槽2 初值 I029 → I229（进入即显示 队员信息，无 Info 闪）'),
]

# ★ 行盒锚点常量 A/B 覆盖（见 docs/ANALYSIS_FONT.md §14；默认值=当前 v20/v21 成品）
_ANCHOR_DEFAULTS = dict(title=7.0, bottom=3.0, mid=2.0)


# ═══════════════ 行盒锚点 cave（拆分版，两段已验证死区） ═══════════════
# 链：DrawString 非图标分支 → cave A（标题带左右分区）→ cave C（中段位移，0x182F84）
#     → cave B（写 y1/y2，0x5752F0）→ DrawString 0x21989C
# cave A：VA 0x575D04（原 116B 零填充区，132B 可用）
# bottom 段：VA 0x59EF50（串守卫 C cave 之后的零填充尾，80B 可用）
CAVE_A_VA = 0x575D04
CAVE_A_FILE = CAVE_A_VA - 0xFFF00
BOTTOM_VA = 0x59EF50
BOTTOM_FILE = BOTTOM_VA - 0xFFF00
CAVE_C_VA = 0x182F84

T0 = 8
F1, F2, F20, F21, F23 = 1, 2, 20, 21, 23


def _f2w(x):
    return struct.unpack('<I', struct.pack('<f', float(x)))[0]


def _lui(rt, value):
    return 0x3C000000 | (rt << 16) | ((_f2w(value) >> 16) & 0xFFFF)


def _mtc1(rt, fs):
    return 0x44800000 | (rt << 16) | (fs << 11)


def _fp(fn, fd, fs, ft):
    return 0x46000000 | (ft << 16) | (fs << 11) | (fd << 6) | fn


def _c(fn, fs, ft):
    return 0x46000000 | (ft << 16) | (fs << 11) | fn


def _bc1f(off):
    return 0x45000000 | (off & 0xFFFF)


def _bc1t(off):
    return 0x45010000 | (off & 0xFFFF)


def _j(va):
    return (0x02 << 26) | ((va >> 2) & 0x3FFFFFF)


NOP = 0


def _anchor_vals():
    left = float(os.environ.get('GRJS_ANCHOR_TITLE_LEFT', 0.0))
    up = float(os.environ.get('GRJS_ANCHOR_TITLE_RIGHT_UP', 0.0))
    mid = float(os.environ.get('GRJS_ANCHOR_MID', 3.0))
    bottom = float(os.environ.get('GRJS_ANCHOR_BOTTOM', 3.0))
    dy_offset = float(os.environ.get('GRJS_ANCHOR_DY_OFFSET', 0.0))
    legacy = os.environ.get('GRJS_ANCHOR_TITLE')
    if legacy is not None:
        left = float(legacy)
        up = -float(legacy)
    return dict(left=left, right_up=up, mid=mid, bottom=bottom, dy_offset=dy_offset)


def _cave_a_words(vals):
    """dy=(CharHeight-16)/2；y<40 时按 x 分区（x<=480 → +left，否则 -right_up）。"""
    ins, labels = [], {}

    def emit(w):
        ins.append(w)
        return len(ins) - 1

    def label(name):
        labels[name] = len(ins)

    emit(_lui(T0, 16.0)); emit(_mtc1(T0, F2)); emit(_fp(0x01, F1, F21, F2))
    emit(_lui(T0, 0.5)); emit(_mtc1(T0, F2)); emit(_fp(0x02, F1, F1, F2))

    if vals.get('dy_offset'):
        emit(_lui(T0, vals['dy_offset'])); emit(_mtc1(T0, F2))
        emit(_fp(0x00, F1, F1, F2))             # dy += offset（统一基线，消除 y 区间跳变）
    emit(_lui(T0, 40.0)); emit(_mtc1(T0, F2))
    emit(_c(0x34, F23, F2))                    # y < 40 ?
    at_no_title = emit(_bc1f(0))
    emit(NOP)

    # 顶部条带按“字形来源”分区：sp+0xDF 高字节 != 0 ⇒ DBCS 对偶（“简介”等）→ 左；
    # == 0 ⇒ 单字节 ASCII（右上 GR-C01）→ 右。
    emit(0x83A800DF)                           # lb t0, 0xDF(sp)
    at_pair = emit(0x11000000)                 # beq t0, zero → left（实测 pair 的 0xDF==0）
    emit(NOP)

    # 右侧（GR-C01 等）：dy -= right_up，然后去 bottom 段
    emit(_lui(T0, vals['right_up'])); emit(_mtc1(T0, F2)); emit(_fp(0x01, F1, F1, F2))
    at_j_bottom1 = emit(_j(0)); emit(NOP)

    label('left')
    emit(_lui(T0, vals['left'])); emit(_mtc1(T0, F2)); emit(_fp(0x00, F1, F1, F2))
    at_j_c = emit(_j(CAVE_C_VA)); emit(NOP)

    label('no_title')
    at_j_bottom2 = emit(_j(0)); emit(NOP)

    def fix(addr, target):
        ins[addr] = (ins[addr] & 0xFFFF0000) | ((labels[target] - (addr + 1)) & 0xFFFF)

    fix(at_pair, 'left')
    fix(at_no_title, 'no_title')
    if os.environ.get('GRJS_ANCHOR_NAMEFIX'):
        dest = CAVE_F_VA
    else:
        dest = BOTTOM_VA if os.environ.get('GRJS_NO_TEXT_ANCHORS') else CAVE_D_VA
    ins[at_j_bottom1] = _j(dest)
    ins[at_j_bottom2] = _j(dest)
    return ins


def _bottom_words(vals):
    """y >= 270（游戏坐标）→ dy -= bottom(3)，然后回 cave C；y < 270 直接回 cave C。
    cave C 恢复为「40<=y<400 再 -mid(3)」，于是：
      菜单类（y<270）  = caveC -3          → 与 v22 一致
      目标行（270..400）= bottom -3 + caveC -3 = -6 → 比 v22 多上移 3
      底栏（y>=400）    = bottom -3（caveC 跳过） → -3
    """
    ins = [0] * 11
    labels = {}

    def put(i, w):
        ins[i] = w & 0xFFFFFFFF

    put(0, _lui(T0, 270.0))
    put(1, _mtc1(T0, F2))
    put(2, _c(0x34, F23, F2))          # c.olt y,270
    put(3, _bc1t(0))                    # y<270 → END
    put(4, _lui(T0, vals['bottom']))    # 延迟槽
    put(5, _mtc1(T0, F2))
    put(6, _fp(0x01, F1, F1, F2))       # dy -= bottom
    labels['end'] = 7
    put(7, _j(CAVE_C_VA))
    put(8, NOP)
    # 调整 bc1t 目标到 end
    ins[3] = (ins[3] & 0xFFFF0000) | ((labels['end'] - 4) & 0xFFFF)
    return ins[:9]



# 逐文本锚点修正（cave D，VA 0x57D1A5，171B 零岛）：只对指定字符串额外下移。
CAVE_D_VA = 0x57D1A8
CAVE_D_FILE = CAVE_D_VA - 0xFFF00
_CAVE_D_RULES = [
    # (首 4 字节小端, 额外下移 px)
    (0xB3A2E9A1, 10.0),  # 新兵
    (0xB3A2A2A5, 10.0),  # 老兵
    (0xFEA3B7A2, 10.0),  # 精英
    (0x0000C442, 4.0),   # B组
]


def _cave_d_words(fallthrough=None):
    ins = []
    labels = {}

    def emit(*ws):
        for w in ws:
            ins.append(w)

    # lw t0,0(s2)  —— s2 = 当前绘制字符串基址
    emit(0x8E480000)
    for idx, (pat, delta) in enumerate(_CAVE_D_RULES):
        labels['hit%d' % idx] = None
        emit((0x0F << 26) | (9 << 16) | ((pat >> 16) & 0xFFFF))
        emit((0x0D << 26) | (9 << 21) | (9 << 16) | (pat & 0xFFFF))
        labels['hit%d' % idx] = len(ins)
        emit(0)  # beq t0,t1 -> hit
        emit(NOP)
    j_bottom = len(ins)
    emit(_j(BOTTOM_VA if fallthrough is None else fallthrough))
    emit(NOP)
    # 每个命中块
    hit_pos = {}
    for idx, (pat, delta) in enumerate(_CAVE_D_RULES):
        hit_pos[idx] = len(ins)
        emit(_lui(T0, delta))
        emit(_mtc1(T0, F2))
        emit(_fp(0x00, F1, F1, F2))   # add.s f1,f1,f2
        emit(_j(BOTTOM_VA))
        emit(NOP)
    # 回填 beq 目标到对应 hit
    for idx in range(len(_CAVE_D_RULES)):
        at = labels['hit%d' % idx]
        tgt = hit_pos[idx]
        off = tgt - (at + 1)
        ins[at] = (0x04 << 26) | (8 << 21) | (9 << 16) | (off & 0xFFFF)
    return ins



# 逐文本锚点修正 cave E（VA 0x57D0C4，108B 零岛）：B 组三行队员姓名（形如 "R. Perry"）下移 3px。
CAVE_E_VA = 0x57D598
CAVE_E_FILE = CAVE_E_VA - 0xFFF00
_NAME_ROW_DELTA = 8.0
_NAME_ROW_Y = (235.0, 345.0)


def _cave_e_words():
    ins = []
    lab = {}

    def emit(*ws):
        for w in ws:
            ins.append(w)

    def fix(at, name):
        off = lab[name] - (at + 1)
        ins[at] = (ins[at] & 0xFFFF0000) | (off & 0xFFFF)

    # y < 230 -> skip
    emit(_lui(T0, _NAME_ROW_Y[0])); emit(_mtc1(T0, F2)); emit(_c(0x34, F23, F2))
    at1 = len(ins); emit(_bc1t(0)); emit(NOP)
    # 330 < y -> skip
    emit(_lui(T0, _NAME_ROW_Y[1])); emit(_mtc1(T0, F2)); emit(_c(0x34, F2, F23))
    at2 = len(ins); emit(_bc1t(0)); emit(NOP)
    # (str[0..3] >> 8) & 0xFFFF == 0x202E  →  形如 "X. "
    emit(0x8E4A0000)                       # lw t2,0(s2)
    emit(0x000B2A02)                       # srl t3,t2,8      (rt=11 rd=11 sa=8)
    emit(0x316BFFFF)                       # andi t3,t3,0xFFFF
    emit(0x3C090000); emit(0x3529202E)     # t1 = 0x0000202E
    at3 = len(ins); emit(0); emit(NOP)
    emit(_lui(T0, _NAME_ROW_DELTA)); emit(_mtc1(T0, F2)); emit(_fp(0x00, F1, F1, F2))
    lab['bottom'] = len(ins); emit(_j(CAVE_G_VA)); emit(NOP)
    lab['skip'] = len(ins); emit(_j(CAVE_G_VA)); emit(NOP)
    fix(at1, 'skip'); fix(at2, 'skip')
    off = lab['skip'] - (at3 + 1)
    ins[at3] = (0x05 << 26) | (11 << 21) | (9 << 16) | (off & 0xFFFF)  # bne t3,t1,skip
    return ins



CAVE_F_VA = 0x57D1A8
CAVE_F_FILE = CAVE_F_VA - 0xFFF00


def _cave_f_words():
    ins = []
    lab = {}

    def emit(*ws):
        for w in ws:
            ins.append(w)

    def fix(at, name):
        off = lab[name] - (at + 1)
        ins[at] = (ins[at] & 0xFFFF0000) | (off & 0xFFFF)

    emit(_lui(T0, 265.0)); emit(_mtc1(T0, F2)); emit(_c(0x34, F23, F2))
    at1 = len(ins); emit(_bc1t(0)); emit(NOP)
    emit(_lui(T0, 340.0)); emit(_mtc1(T0, F2)); emit(_c(0x34, F2, F23))
    at2 = len(ins); emit(_bc1t(0)); emit(NOP)
    emit(0x8E4A0000)                 # lw t2,0(s2)
    emit(0x000B2A02)                 # srl t3,t2,8
    emit(0x316BFFFF)                 # andi t3,t3,0xFFFF
    emit(0x3C090000); emit(0x3529202E)   # t1 = 0x0000202E  ("X. ")
    at3 = len(ins); emit(0); emit(NOP)
    emit(_lui(T0, 5.0)); emit(_mtc1(T0, F2)); emit(_fp(0x00, F1, F1, F2))
    lab['bottom'] = len(ins); emit(_j(CAVE_G_VA)); emit(NOP)
    lab['skip'] = len(ins); emit(_j(CAVE_G_VA)); emit(NOP)
    fix(at1, 'skip'); fix(at2, 'skip')
    off = lab['skip'] - (at3 + 1)
    ins[at3] = (0x05 << 26) | (11 << 21) | (9 << 16) | (off & 0xFFFF)
    return ins


CAVE_G_VA = 0x57D2F0   # H2(0x57D280..0x57D2EC) 之后的零区，128 B 可用
CAVE_G_FILE = CAVE_G_VA - 0xFFF00


def _cave_g_words():
    """简报「任务目标」行再上移 3px：y>=265 且首字符为数字+'.' 或 'X'。

    任务目标行的编码首 4 字节：
      "1. xx" → 31 2e 20 ..   (数字 + '.')
      "X - xx" → 58 20 2d 20  (X + 空格 + '-')
    这些行在 v46 去区间化后整体下移 3px，与任务目标面板的分栏线错位；本 cave 只修它们。
    """
    ins = []
    lab = {}

    def emit(*ws):
        for w in ws:
            ins.append(w)

    def fix(at, name):
        off = lab[name] - (at + 1)
        ins[at] = (ins[at] & 0xFFFF0000) | (off & 0xFFFF)

    emit(_lui(T0, 265.0)); emit(_mtc1(T0, F2)); emit(_c(0x34, F23, F2))
    at1 = len(ins); emit(_bc1t(0)); emit(NOP)
    emit(0x8E4A0000)                      # lw t2,0(s2)
    emit(0x314B00FF)                      # andi t3,t2,0xFF        b0
    emit(0x256CFFD0)                      # addiu t4,t3,-0x30
    emit(0x2D8D000A)                      # sltiu t5,t4,10
    at2 = len(ins); emit((0x04 << 26) | (13 << 21) | (0 << 16)); emit(NOP)  # beq t5,zero,is_x
    emit(0x000A6202)                      # srl t4,t2,8
    emit(0x318C00FF)                      # andi t4,t4,0xFF
    emit(0x240D002E)                      # addiu t5,zero,'.'
    at3 = len(ins); emit((0x05 << 26) | (12 << 21) | (13 << 16)); emit(NOP)  # bne t4,t5,skip
    at4 = len(ins); emit(_j(0)); emit(NOP)                                  # j apply
    lab['is_x'] = len(ins)
    emit(0x240C0058)                      # addiu t4,zero,'X'
    at5 = len(ins); emit((0x05 << 26) | (11 << 21) | (12 << 16)); emit(NOP)  # bne t3,t4,skip
    lab['apply'] = len(ins)
    emit(_lui(T0, 3.0)); emit(_mtc1(T0, F2)); emit(_fp(0x01, F1, F1, F2))
    lab['skip'] = len(ins); emit(_j(BOTTOM_VA)); emit(NOP)
    fix(at1, 'skip'); fix(at3, 'skip'); fix(at5, 'skip')
    fix(at2, 'is_x')
    tgt_va = CAVE_G_VA + lab['apply'] * 4
    ins[at4] = (0x02 << 26) | ((tgt_va >> 2) & 0x3FFFFFF)
    return ins


def _anchor_patches():
    if os.environ.get('GRJS_ANCHOR_MIN16'):
        # 16px 顶锚 + 5 个控件对齐站点改 16（见 docs/ANALYSIS_ELF.md §36）
        cave_words = [
            0x3C084180,  # lui t0, 16.0
            0x44881000,  # mtc1 t0, f2
            0x4602B800,  # add.s f0, f23, f2
            0xE6970000,  # swc1 f23, 0(s4)   y1 = y
            0xE6C00000,  # swc1 f0, 0(s6)    y2 = y+16
            0x08086627,  # j 0x21989C
            0x00000000,  # nop
        ]
        cave_blob = _pack_words(cave_words)
        out = [
            dict(file_off=0x119994, orig_hex='000097e6',
                 new_hex=struct.pack('<I', _j(CAVE_A_VA)).hex(),
                 why='DrawString 非图标分支 y1 存点 → j 锚点 cave A(VA 0x%X, 16px 顶锚)' % CAVE_A_VA),
            dict(file_off=0x119998, orig_hex='0000c0e6', new_hex='00000000',
                 why='DrawString 非图标分支 y2 预存点 → nop'),
            dict(file_off=CAVE_A_FILE, orig_hex='00' * len(cave_blob), new_hex=cave_blob.hex(),
                 why='锚点 cave A：16px 顶锚（y1=y, y2=y+16）'),
            dict(file_off=0x0FCB3C, orig_hex='23106200', new_hex='f0ff6224',
                 why='居中布局：subu v0,v1,v0 → addiu v0,v1,-16'),
            dict(file_off=0x0FCB80, orig_hex='23108200', new_hex='f0ff8224',
                 why='底对齐布局：subu v0,a0,v0 → addiu v0,a0,-16'),
            dict(file_off=0x103874, orig_hex='23106200', new_hex='f0ff6224',
                 why='居中布局：subu v0,v1,v0 → addiu v0,v1,-16（203774）'),
            dict(file_off=0x11C7B0, orig_hex='23106200', new_hex='f0ff6224',
                 why='居中布局：subu v0,v1,v0 → addiu v0,v1,-16（21C6B0）'),
            dict(file_off=0x11C7F4, orig_hex='23108200', new_hex='f0ff8224',
                 why='底对齐布局：subu v0,a0,v0 → addiu v0,a0,-16（21C6F4）'),
        ]
        for e in ELF_EXTRA_PATCHES:
            if e.get('why', '').startswith('v11 cave'):
                continue
            out.append(dict(e))
        return out
    vals = _anchor_vals()
    a_words = _cave_a_words(vals)
    b_words = _bottom_words(vals)
    a_blob = b''.join(struct.pack('<I', w & 0xFFFFFFFF) for w in a_words)
    b_blob = b''.join(struct.pack('<I', w & 0xFFFFFFFF) for w in b_words)
    assert len(a_blob) <= 132, len(a_blob)
    assert len(b_blob) <= 80, len(b_blob)
    no_ta = bool(os.environ.get('GRJS_NO_TEXT_ANCHORS'))
    d_words = [] if no_ta else _cave_d_words(CAVE_E_VA)
    d_blob = _pack_words(d_words)
    assert len(d_blob) <= 171, len(d_blob)
    out = [
        dict(file_off=0x119994, orig_hex='000097e6',
             new_hex=struct.pack('<I', _j(CAVE_A_VA)).hex(),
             why='DrawString 非图标分支 y1 存点 → j 锚点 cave A(VA 0x%X)' % CAVE_A_VA),
        dict(file_off=0x119998, orig_hex='0000c0e6', new_hex='00000000',
             why='DrawString 非图标分支 y2 预存点 → nop（cave 统一写 y1/y2）'),
        dict(file_off=CAVE_A_FILE, orig_hex='00' * len(a_blob), new_hex=a_blob.hex(),
             why='锚点 cave A：标题带 左+%.1f/右-%.1f（x<=480 分界）' % (vals['left'], vals['right_up'])),
        dict(file_off=BOTTOM_FILE, orig_hex='00' * len(b_blob), new_hex=b_blob.hex(),
             why='锚点 bottom 段：y>=400 且 x>400 再 -%.1f' % vals['bottom']),
    ]
    for e in ELF_EXTRA_PATCHES:
        if e.get('why', '').startswith('v11 cave C'):
            e2 = dict(e)
            e2['new_hex'] = _cave_set_float(e2['new_hex'], 10, vals['mid'])
            e2['why'] = 'v11 cave C：中段正文 -%.1fpx' % vals['mid']
            out.append(e2)
        else:
            out.append(dict(e))
    if os.environ.get('GRJS_ANCHOR_NAMEFIX'):
        f_words = _cave_f_words()
        f_blob = _pack_words(f_words)
        assert len(f_blob) <= 171, len(f_blob)
        out.append(dict(file_off=CAVE_F_FILE, orig_hex='00' * len(f_blob), new_hex=f_blob.hex(),
                        why='cave F：B组姓名行（y265-340, X.）再 +5px（0x57D1A8，%d B）' % len(f_blob)))
        g_words = _cave_g_words()
        g_blob = _pack_words(g_words)
        assert len(g_blob) <= 128, len(g_blob)
        out.append(dict(file_off=CAVE_G_FILE, orig_hex='00' * len(g_blob), new_hex=g_blob.hex(),
                        why='cave G：简报任务目标行（y265-400, 数字/X + ./-）再 -3px（0x57D2F0，%d B）' % len(g_blob)))
        return out
    if not no_ta:
        out.append(dict(file_off=CAVE_D_FILE, orig_hex='00' * len(d_blob), new_hex=d_blob.hex(),
                      why='逐文本锚点 cave D：新兵/老兵/精英 +10px、B组 +4px（0x57D1A8，%d B）' % len(d_blob)))
        e_words = _cave_e_words()
        e_blob = _pack_words(e_words)
        assert len(e_blob) <= 108, len(e_blob)
        out.append(dict(file_off=CAVE_E_FILE, orig_hex='00' * len(e_blob), new_hex=e_blob.hex(),
                      why='逐文本锚点 cave E：队员姓名行（y230-330, [A-Z]. ）+%.1fpx（0x57D598，%d B）' % (_NAME_ROW_DELTA, len(e_blob))))
    return out


def _cave_set_float(hexstr, word_index, value):
    b = bytearray(bytes.fromhex(hexstr))
    bits = struct.unpack('<I', struct.pack('<f', float(value)))[0]
    struct.pack_into('<I', b, word_index * 4, 0x3C080000 | ((bits >> 16) & 0xFFFF))
    return b.hex()


# ★ v14 串守卫（战役卡死修复，见 docs/CRASH_CAMPAIGN_ANALYSIS.md §11）：
#   现场：0x401F20(dst,src,start=275,end=274) → 容量 0 → 0x401490 返回 NULL data →
#         结尾 sb zero,(v0) 写 0 地址。引擎无 start<=end / 分配失败判断。
#   A. 0x4015F0 串构造入口：容量 a1<=0 钳到 1（cave @0x5841C4）。
#   C. 0x401F98 子串结尾：shared/data 任一 NULL → 跳函数尾声 0x401FC0（cave @0x59EF20）。
_STRING_GUARD_REGS = dict(zero=0, at=1, v0=2, v1=3, a0=4, a1=5, a2=6, a3=7,
                          t0=8, t1=9, t2=10, t3=11, t4=12, t5=13, t6=14, t7=15,
                          s0=16, s1=17, s2=18, s3=19, s4=20, s5=21, s6=22, s7=23,
                          t8=24, t9=25, sp=29, ra=31)


def _sg_j(a):
    return (0x02 << 26) | ((a >> 2) & 0x3FFFFFF)


def _sg_lw(rt, base, off):
    return ((0x23 << 26) | (_STRING_GUARD_REGS[base] << 21)
            | (_STRING_GUARD_REGS[rt] << 16) | (off & 0xFFFF))


def _sg_addiu(rt, rs, imm):
    return ((0x09 << 26) | (_STRING_GUARD_REGS[rs] << 21)
            | (_STRING_GUARD_REGS[rt] << 16) | (imm & 0xFFFF))


def _sg_beqz(rs, off):
    return (0x04 << 26) | (_STRING_GUARD_REGS[rs] << 21) | (off & 0xFFFF)


def _sg_bgtz(rs, off):
    return (0x07 << 26) | (_STRING_GUARD_REGS[rs] << 21) | (off & 0xFFFF)


def _pack_words(words):
    return b''.join(struct.pack('<I', w & 0xFFFFFFFF) for w in words)



# ═══════════════ 大小写折叠高字节守卫（v32；参本体 ZH72，12 词→改用 4 词） ═══════════════
# 引擎 LowerCase/UpperCase 逐字节查 ctype 表 0x57F9A1+(s8)c：高字节(>=0x80) 索引为负，
# 落进表下方 rodata，撞上 bit0/bit1 即被 +-0x20（队 C1→E1、员 E9→09、破 C8→E8…），
# 小队兵种名因此乱码。补丁：折叠前 sltiu 判 c<0x80，高字节直接跳过折叠与回写。
#   LowerCase 循环 0x16DF38：站点 0x16DF48(sll)/0x16DF4C(sra)
#   UpperCase 循环 0x16FB78：站点 0x16FB88(sll)/0x16FB8C(sra)
_CASEFOLD_GUARD = [
    (0x16DF48, '00160300', '8000612c', 'LowerCase 循环：sll v0,v1,24 → sltiu at,v1,0x80'),
    (0x16DF4C, '03160200', '07002010', 'LowerCase 循环：sra v0,v0,24 → beq at,zero,+7（高字节跳过折叠）'),
    (0x16FB88, '00160300', '8000612c', 'UpperCase 循环：sll v0,v1,24 → sltiu at,v1,0x80'),
    (0x16FB8C, '03160200', '07002010', 'UpperCase 循环：sra v0,v0,24 → beq at,zero,+7（高字节跳过折叠）'),
]


def casefold_guard_patches():
    return [dict(file_off=va - 0xFFF00, orig_hex=o, new_hex=n, why=w)
            for va, o, n, w in _CASEFOLD_GUARD]


def string_guard_patches():
    """返回 v14 串守卫补丁段（站点 + cave，共 5 段）。"""
    def va2file(va):
        return va - 0xFFF00

    NOP = 0
    cave_a = [
        _sg_bgtz('a1', 2),            # a1 > 0 → 跳到 index 3
        NOP,
        _sg_addiu('a1', 'zero', 1),   # 否则容量 = 1
        _sg_addiu('sp', 'sp', -0x30),  # 原指令
        _sg_j(0x4015F4),
        NOP,
    ]
    cave_c = [
        _sg_lw('v0', 'a0', 0),        # 原指令：v0 = shared
        _sg_beqz('v0', 8),            # shared == 0 → bail(index 10)
        NOP,
        _sg_lw('v1', 'v0', 4),        # v1 = data
        _sg_beqz('v1', 5),            # data == 0 → bail(index 10)
        NOP,
        _sg_lw('v0', 'a0', 0),        # 恢复原语义
        _sg_addiu('a1', 'sp', 0x58),  # 原 site+4 指令
        _sg_j(0x401FA0),
        NOP,
        _sg_j(0x401FC0),              # bail：函数尾声（不写 0 地址）
        NOP,
    ]
    assert len(cave_a) * 4 <= 44 and len(cave_c) * 4 <= 128
    return [
        dict(file_off=va2file(0x4015F0), orig_hex=struct.pack('<I', 0x27BDFFD0).hex(),
             new_hex=struct.pack('<I', _sg_j(0x5841C4)).hex(),
             why='串守卫A：串构造容量下限钳 1（站点 0x4015F0）'),
        dict(file_off=va2file(0x5841C4), orig_hex='00' * (len(cave_a) * 4),
             new_hex=_pack_words(cave_a).hex(), why='串守卫A cave：a1<=0 → a1=1'),
        dict(file_off=va2file(0x401F98), orig_hex=struct.pack('<I', 0x8C820000).hex(),
             new_hex=struct.pack('<I', _sg_j(0x59EF20)).hex(),
             why='串守卫C：子串结尾写 0 前判 shared/data NULL（站点 0x401F98）'),
        dict(file_off=va2file(0x401F9C), orig_hex=struct.pack('<I', 0x27A50058).hex(),
             new_hex='00' * 4, why='串守卫C：0x401F9C 已挪进 cave → nop'),
        dict(file_off=va2file(0x59EF20), orig_hex='00' * (len(cave_c) * 4),
             new_hex=_pack_words(cave_c).hex(), why='串守卫C cave：NULL 则跳函数尾声 0x401FC0'),
    ]


# ★ v15 折行修复（DBCS 换行边界）：
#   原引擎折行循环 0x21B778..0x21B7C4 按 **字节** 取字符并以 +1 推进：
#     jal 0x401D20 (取第 s0 字节指针) → lb a1,0(v0) → jal CharWidth → 累加宽度 → s0 += 1
#   中文对偶码为 2 字节 ⇒ 行宽在半个字处被截断：行尾剩一个 lead 字节（0xB1/0xB5 会被
#   DrawString 当图标码 → 画手柄按键图标），下一行从 trail 字节起解码 ⇒ 换行前后字符错乱。
#   修法（仿本体 BASE-ZH 的 wrap cave）：把取字符改成 DBCS 感知（lead∈[0xA1,0xBA)、
#   trail∈[0xA1,0xFF) 才组合成 16 位码，步长 1/2），并在 cave 内复刻宽度累加，索引按步长推进。
WRAP_CAVE_VA = 0x57D280
WRAP_SITE_VA = 0x21B778
WRAP_LOOP_TAIL_VA = 0x21B7C8


def _w_jal(a):
    return (0x03 << 26) | ((a >> 2) & 0x3FFFFFF)


def _w_j(a):
    return (0x02 << 26) | ((a >> 2) & 0x3FFFFFF)


def _w_lbu(rt, base, off):
    return (0x24 << 26) | (_STRING_GUARD_REGS[base] << 21) | (_STRING_GUARD_REGS[rt] << 16) | (off & 0xFFFF)


def _w_lw(rt, base, off):
    return (0x23 << 26) | (_STRING_GUARD_REGS[base] << 21) | (_STRING_GUARD_REGS[rt] << 16) | (off & 0xFFFF)


def _w_sw(rt, base, off):
    return (0x2B << 26) | (_STRING_GUARD_REGS[base] << 21) | (_STRING_GUARD_REGS[rt] << 16) | (off & 0xFFFF)


def _w_sltiu(rt, rs, imm):
    return (0x0B << 26) | (_STRING_GUARD_REGS[rs] << 21) | (_STRING_GUARD_REGS[rt] << 16) | (imm & 0xFFFF)


def _w_addiu(rt, rs, imm):
    return (0x09 << 26) | (_STRING_GUARD_REGS[rs] << 21) | (_STRING_GUARD_REGS[rt] << 16) | (imm & 0xFFFF)


def _w_beq(rs, rt, off):
    return (0x04 << 26) | (_STRING_GUARD_REGS[rs] << 21) | (_STRING_GUARD_REGS[rt] << 16) | (off & 0xFFFF)


def _w_bne(rs, rt, off):
    return (0x05 << 26) | (_STRING_GUARD_REGS[rs] << 21) | (_STRING_GUARD_REGS[rt] << 16) | (off & 0xFFFF)


def _w_b(off):
    return (0x04 << 26) | (off & 0xFFFF)


def _w_r(funct, rd, rs, rt, sa=0):
    return (_STRING_GUARD_REGS[rs] << 21) | (_STRING_GUARD_REGS[rt] << 16) | \
        (_STRING_GUARD_REGS[rd] << 11) | ((sa & 31) << 6) | funct


def wrap_dcs_patches():
    """折行 DBCS 修复：站点 0x21B778（取字符→解码）与 0x21B7B4（索引 +步长）。

    原循环：jal 0x401D20 取第 s0 字节指针 → lb a1,0(v0) → CharWidth → s0 += 1
    修法：直接读 RSString 数据指针（[a0+4]→[+4]），按 DBCS 规则组 16 位码、步长 1/2 存
    sp+0x9C，回 CharWidth；索引推进处改为 s0 += 步长。站点 1 的延迟槽是 `daddu a1,s0,zero`，
    站点 2 的延迟槽是 `lw v0,176(sp)`，均安全；不使用 cave 内函数调用。
    """
    NOP = 0
    CAVE_A = 0x5BFE0C
    words = []

    def emit(*ws):
        for w in ws:
            words.append(w)

    def here():
        return len(words) * 4

    def b_at(idx, target_off):
        w = words[idx]
        off = (target_off - (idx * 4 + 4)) // 4
        words[idx] = (w & 0xFFFF0000) | (off & 0xFFFF)

    emit(_w_lw('t1', 'a0', 4))                      # 0x00 shared
    emit(_w_lw('t1', 't1', 4))                      # 0x04 data
    emit(_w_r(0x21, 't1', 't1', 's0'))              # 0x08 ptr = data + index
    emit(_w_lbu('t2', 't1', 0))                     # 0x0C 首字节
    emit(_w_sltiu('t3', 't2', 0xA1))                # 0x10
    emit(_w_bne('t3', 'zero', 0))
    i_s1 = len(words) - 1
    emit(NOP)
    emit(_w_sltiu('t3', 't2', 0xBA))                # 0x1C
    emit(_w_beq('t3', 'zero', 0))
    i_s2 = len(words) - 1
    emit(NOP)
    emit(_w_lw('t3', 'sp', 0xB0))                   # 0x28 len-1
    emit(_w_r(0x2A, 't3', 's0', 't3'))              # slt t3, s0, t3
    emit(_w_beq('t3', 'zero', 0))
    i_s3 = len(words) - 1
    emit(NOP)
    emit(_w_lbu('t3', 't1', 1))                     # 0x38 trail
    emit(_w_sltiu('t9', 't3', 0xA1))
    emit(_w_bne('t9', 'zero', 0))
    i_s4 = len(words) - 1
    emit(NOP)
    emit(_w_sltiu('t9', 't3', 0xFF))
    emit(_w_beq('t9', 'zero', 0))
    i_s5 = len(words) - 1
    emit(NOP)
    emit(_w_r(0x00, 'a1', 't2', 'zero', 8))         # 0x4C sll a1, t2, 8
    emit(_w_r(0x25, 'a1', 'a1', 't3'))              # or a1, a1, t3
    emit(_w_addiu('t8', 'zero', 2))
    emit(_w_j(0x21B784), _w_sw('t8', 'sp', 0x9C))

    single = here()
    emit(_w_r(0x21, 'a1', 't2', 'zero'))            # addu a1, t2, zero
    emit(_w_addiu('t8', 'zero', 1))
    emit(_w_j(0x21B784), _w_sw('t8', 'sp', 0x9C))

    for i in (i_s1, i_s2, i_s3, i_s4, i_s5):
        b_at(i, single)

    # 宽度模型对齐：原字节循环对每个字节各加一次 font[0x18]，
    # 对偶码合并成一次迭代后少加一次 g ⇒ 对偶码分支补加 v0(=g)
    cave_g = here()
    emit(_w_lw('t8', 'sp', 0x9C))
    emit(_w_addiu('t8', 't8', -2))
    emit(_w_bne('t8', 'zero', 0))
    norm_i = len(words) - 1
    emit(NOP)
    emit(_w_r(0x21, 'v1', 'v1', 'v0'))              # v1 += g
    norm = here()
    emit(_w_r(0x21, 'v0', 's3', 'v1'))              # v0 = s3 + v1
    emit(_w_j(0x21B7A4), NOP)
    off = (norm - (norm_i * 4 + 4)) // 4
    words[norm_i] = (words[norm_i] & 0xFFFF0000) | (off & 0xFFFF)

    # 行首 +1 修正 cave（站点 0x21B8C4，独立 cave @0x57B78C）
    # 入口：v0 = [0x138] 旧行首，v1 = len(line1)+1；延迟槽已把旧值写回 [0x138]。
    # 目标：断点是空格才 +1；中文对偶码断点 → 下一行从 lead 开始。
    cave_h_words = []
    cave_h = 0x57B78C

    def hemit(*ws):
        for w in ws:
            cave_h_words.append(w)

    hemit(_w_r(0x21, 't1', 'v0', 'v1'))              # 0 t1 = 旧行首 + len + 1
    hemit(_w_addiu('t1', 't1', -1))                  # 4 断点字节索引
    hemit(_w_lw('t2', 's6', 4))                      # 8 RSString->shared
    hemit(_w_lw('t2', 't2', 4))                      # c ->data
    hemit(_w_r(0x21, 't2', 't2', 't1'))              # 10 &data[break]
    hemit(_w_lbu('t3', 't2', 0))                     # 14 断点字节
    hemit(_w_addiu('t4', 'zero', 0x20))              # 18
    hemit(_w_r(0x26, 't4', 't3', 't4'))              # 1c xor t4,t3,0x20
    hemit(_w_r(0x2B, 't4', 'zero', 't4'))            # 20 sltu t4,zero,t4 → 1=非空格
    hemit(_w_addiu('v0', 't1', 1))                   # 24 v0 = break+1（默认）
    hemit(_w_r(0x23, 'v0', 'v0', 't4'))              # 28 非空格则 -1
    CAVE_H2 = 0x57D280   # 0x57D280 起 240 B 全 0（cave F 之后、cave D 覆写区之外）
    hemit(_w_j(CAVE_H2))                             # 2c 跳到 H2（英文单词保护）
    hemit(NOP)
    cave_h_blob = _pack_words(cave_h_words)
    assert len(cave_h_blob) == 52, len(cave_h_blob)

    # cave H2：英文单词不跨行（把断点回退到 ASCII 单词开头，再写回行首 [0x138]）
    # 输入：v0 = 新行首索引；s6 = RSString；sp+0x138 = 上一行行首（cave H 入口处已写回）
    cave_h2_words = []

    def h2(*ws):
        for w in ws:
            cave_h2_words.append(w)

    h2(_w_lw('t2', 's6', 4))                         # 0  shared
    h2(_w_lw('t2', 't2', 4))                         # 4  data
    h2(_w_lw('t5', 'sp', 0x138))                     # 8  old start
    h2(_w_addiu('t5', 't5', 1))                      # c  min = old+1
    loop = len(cave_h2_words)
    h2(_w_r(0x2A, 't6', 't5', 'v0'))                 # 10 slt t6, t5, v0  (v0 > t5 ?)
    h2(_w_beq('t6', 'zero', 0))                      # 14
    i_done = len(cave_h2_words) - 1
    h2(NOP)
    h2(_w_r(0x21, 't7', 't2', 'v0'))                 # 1c t7 = data + v0
    h2(_w_lbu('t8', 't7', 0))                        # 20 cur
    h2(_w_lbu('t9', 't7', -1))                       # 24 prev
    h2(_w_sltiu('t6', 't8', 0x21))                   # 28 cur < 0x21 ?
    h2(_w_bne('t6', 'zero', 0)); i_d1 = len(cave_h2_words) - 1
    h2(NOP)
    h2(_w_sltiu('t6', 't8', 0x7F))                   # 30 cur < 0x7F ?
    h2(_w_beq('t6', 'zero', 0)); i_d2 = len(cave_h2_words) - 1
    h2(NOP)
    h2(_w_sltiu('t6', 't9', 0x21))                   # 38 prev < 0x21 ?
    h2(_w_bne('t6', 'zero', 0)); i_d3 = len(cave_h2_words) - 1
    h2(NOP)
    h2(_w_sltiu('t6', 't9', 0x7F))                   # 40 prev < 0x7F ?
    h2(_w_beq('t6', 'zero', 0)); i_d4 = len(cave_h2_words) - 1
    h2(NOP)
    h2(_w_addiu('v0', 'v0', -1))                     # 48 v0--
    j_idx = len(cave_h2_words)
    h2(_w_j(0x21B8C4))                               # 4c 回到 loop（占位，稍后改成 loop 地址）
    h2(NOP)
    done = len(cave_h2_words)
    h2(_w_j(0x21B8CC))                               # done: 回主流程
    h2(_w_sw('v0', 'sp', 0x138))
    # 修正 loop 跳转：j 到 loop 起始（本地 cave 地址）
    loop_va = CAVE_H2 + loop * 4
    cave_h2_words[j_idx] = _w_j(loop_va)
    # 修正 4 个 done 分支
    for idx in (i_d1, i_d2, i_d3, i_d4):
        off = (done - (idx + 1))
        cave_h2_words[idx] = (cave_h2_words[idx] & 0xFFFF0000) | (off & 0xFFFF)
    cave_h2_blob = _pack_words(cave_h2_words)
    assert len(cave_h2_blob) <= 200, len(cave_h2_blob)

    # cave M2：折行循环公共入口 0x21B6B0 处的宽度上限（某些控件从 0x21B6B0 直接进入，
    # 绕过 0x21B6AC 的 cave M；在这里再 clamp 一次，保证所有折行路径都 ≤500px）。
    CAVE_M2 = 0x5A0778   # 0x5A0773 起 309 B 全 0 的自由区
    cave_m2_words = []
    cave_m2_words.append(_w_addiu('t0', 'zero', 500))
    # 诊断：进入 M2 时把 s7/s4 落盘，供模拟器取即时存档后读取
    cave_m2_words.append(_lui(9, 0x57D3))
    cave_m2_words.append(_w_sw('s7', 't1', 0x00))
    cave_m2_words.append(_w_sw('s4', 't1', 0x04))
    cave_m2_words.append((8 << 21) | (23 << 16) | (1 << 11) | 0x2A)   # slt at,t0,s7
    cave_m2_words.append(_w_beq('at', 'zero', 0))
    keep2_i = len(cave_m2_words) - 1
    cave_m2_words.append(NOP)
    cave_m2_words.append(_w_r(0x21, 's7', 't0', 'zero'))              # daddu s7,t0,zero
    keep2 = len(cave_m2_words) * 4
    cave_m2_words.append(_w_r(0x21, 's4', 's7', 'zero'))              # daddu s4,s7,zero
    cave_m2_words.append(_w_addiu('a0', 'sp', 0x128))                 # 原 0x21B6B0 指令
    cave_m2_words.append(_w_j(0x21B6B4))
    cave_m2_words.append(NOP)
    off = (keep2 - (keep2_i * 4 + 4)) // 4
    cave_m2_words[keep2_i] = (cave_m2_words[keep2_i] & 0xFFFF0000) | (off & 0xFFFF)
    cave_m2_blob = _pack_words(cave_m2_words)
    assert len(cave_m2_blob) <= 96, len(cave_m2_blob)

    # 行宽余量 cave（站点 0x21B888 的 bgez s4）：s4 只差一点点（> -16）时仍按“放得下”处理；
    # 否则会走 0x21B890 分支，把仍是本行行首的 [0x138] 推进列表 ⇒ 多一个空行、整体下移一行。
    CAVE_S = 0x5880A4
    cave_s_words = []
    # slti at, s4, -16
    cave_s_words.append((0x0A << 26) | (20 << 21) | (1 << 16) | 0xFFF0)
    cave_s_words.append(_w_bne('at', 'zero', 0))
    over_i = len(cave_s_words) - 1
    cave_s_words.append(NOP)
    cave_s_words.append(_w_j(0x21B8B4))
    cave_s_words.append(NOP)
    over = len(cave_s_words) * 4
    cave_s_words.append(_w_j(0x21B890))
    cave_s_words.append(NOP)
    off = (over - (over_i * 4 + 4)) // 4
    cave_s_words[over_i] = (cave_s_words[over_i] & 0xFFFF0000) | (off & 0xFFFF)
    cave_s_blob = _pack_words(cave_s_words)
    assert len(cave_s_blob) == 28, len(cave_s_blob)

    # 行宽统一上限 cave（站点 0x21B6AC，紧跟 strlen 之后）：
    # 折行可用宽度 s7 上限 500（实测折行按 17px/全宽字记账 ⇒ 500/17 ≈ 29 字），各行右边留空隙。
    CAVE_M = 0x59FFC4
    cave_m_words = []
    # 行宽上限 500px：29 全宽字 = 493 < 500 放得下、30 字 = 510 > 500 放下不 → 每行最多 29 个汉字；
    # 留 7px 余量让行尾 ASCII 单词（如 START）尽量整体放行。
    cave_m_words.append(_w_addiu('t0', 'zero', 500))
    # slt at, t0, s7   （SPECIAL 指令：rs<<21 | rt<<16 | rd<<11 | 0x2A；旧代码把 0x2A 错当 opcode）
    cave_m_words.append((8 << 21) | (23 << 16) | (1 << 11) | 0x2A)
    cave_m_words.append(_w_beq('at', 'zero', 0))
    keep_i = len(cave_m_words) - 1
    cave_m_words.append(NOP)
    cave_m_words.append(_w_r(0x2D, 's7', 't0', 'zero'))   # daddu s7, t0, zero
    keep = len(cave_m_words) * 4
    cave_m_words.append(_w_r(0x2D, 's4', 's7', 'zero'))   # daddu s4, s7, zero
    cave_m_words.append(_w_sw('v0', 'sp', 0xCC))          # 原指令：存 strlen 结果
    cave_m_words.append(_w_j(0x21B6B0))
    cave_m_words.append(NOP)
    off = (keep - (keep_i * 4 + 4)) // 4
    cave_m_words[keep_i] = (cave_m_words[keep_i] & 0xFFFF0000) | (off & 0xFFFF)
    cave_m_blob = _pack_words(cave_m_words)
    assert len(cave_m_blob) == 36, len(cave_m_blob)

    cave_b = here()
    emit(_w_lw('t8', 'sp', 0x9C))                   # 步长
    emit(_w_r(0x21, 's0', 's0', 't8'))              # s0 += step
    emit(_w_j(0x21B7BC), NOP)

    blob = _pack_words(words)
    assert len(blob) <= 176, len(blob)
    return [
                
                
                
                
                
        
        



                
                
                
                
                
        dict(file_off=CAVE_H2 - 0xFFF00, orig_hex='00' * len(cave_h2_blob),
             new_hex=cave_h2_blob.hex(),
             why='折行 cave H2：ASCII 单词不跨行（0x57D280，%d B）' % len(cave_h2_blob)),

        dict(file_off=0x21B778 - 0xFFF00,
             orig_hex=struct.pack('<I', 0x0C100748).hex(),
             new_hex=struct.pack('<I', _w_j(CAVE_A)).hex(),
             why='折行：取字符→DBCS 解码 cave（站点 0x21B778）'),
        dict(file_off=0x21B7B4 - 0xFFF00,
             orig_hex=struct.pack('<I', 0x26100001).hex(),
             new_hex=struct.pack('<I', _w_j(CAVE_A + cave_b)).hex(),
             why='折行：索引 +1 → +步长 cave（站点 0x21B7B4）'),
        dict(file_off=0x21B7A0 - 0xFFF00,
             orig_hex=struct.pack('<I', 0x02631021).hex(),
             new_hex=struct.pack('<I', _w_j(CAVE_A + cave_g)).hex(),
             why='折行：宽度模型补加 font[0x18]（对偶码合并迭代少加一次 g，站点 0x21B7A0）'),
        dict(file_off=0x21B8C4 - 0xFFF00,
             orig_hex=struct.pack('<I', 0x00431021).hex(),
             new_hex=struct.pack('<I', _w_j(cave_h)).hex(),
             why='折行：下一行行首 +1 只在断点是空格时保留（站点 0x21B8C4）'),
        dict(file_off=0x21B888 - 0xFFF00,
             orig_hex=struct.pack('<I', 0x0681000A).hex(),
             new_hex=struct.pack('<I', _w_j(CAVE_S)).hex(),
             why='折行：行宽余量 (s4 小负) 不误判为放不下（站点 0x21B888）'),
        dict(file_off=CAVE_S - 0xFFF00, orig_hex='00' * len(cave_s_blob),
             new_hex=cave_s_blob.hex(),
             why='折行 cave S：s4 > -16 走“放得下”分支（0x5880A4，28 B）'),
        dict(file_off=cave_h - 0xFFF00, orig_hex='00' * len(cave_h_blob),
             new_hex=cave_h_blob.hex(),
             why='折行 cave H：断点空格判定 + 行首修正（0x57B78C，52 B）'),
        dict(file_off=CAVE_A - 0xFFF00, orig_hex='00' * len(blob),
             new_hex=blob.hex(),
             why='折行 cave：对偶码判定/步长/宽度补偿/行首修正（0x5BFE0C，%d B）' % len(blob)),
    ]


# ★ 图标码换区（v18）：把引擎识别的手柄图标单字节码 0xB1(△)/0xB5(✕) 换到
# 非 DBCS 头字节区 0x90/0x84，这样图标可与汉字紧邻（无需空格），从而避免
# 引擎「按空格断行」导致的提前换行/空行。需同步改 8 处 DrawString 常量 + CharWidth cave 2 条。
ICON_SITES = [
    # (file_off, orig_word, new_word)
    (0x00119894, 0x240300B5, 0x24030084),
    (0x0011989C, 0x240300B5, 0x24030084),
    (0x001198A0, 0x240300B1, 0x24030090),
    (0x001198C0, 0x240300B5, 0x24030084),
    (0x0011992C, 0x240300B5, 0x24030084),
    (0x00119944, 0x240300B1, 0x24030090),
    (0x001199C4, 0x240200B5, 0x24020084),
    (0x001199D0, 0x240200B1, 0x24020090),
]
ICON_CAVE_WORDS = [
    # (cave word index, orig_word, new_word)
    (54, 0x240900B5, 0x24090084),
    (57, 0x240900B1, 0x24090090),
]


def icon_code_patches(spec):
    """图标码换区补丁（在 DBCS 补丁之后应用）。"""
    out = []
    for off, orig, new in ICON_SITES:
        out.append(dict(file_off=off,
                        orig_hex=struct.pack('<I', orig).hex(),
                        new_hex=struct.pack('<I', new).hex(),
                        why='图标码换区：0x%04X → 0x%04X（非 lead 区，图标可与汉字紧邻）'
                            % (orig & 0xFFFF, new & 0xFFFF)))
    cave_off = int(spec['cave']['file_off'], 16)
    for idx, orig, new in ICON_CAVE_WORDS:
        off = cave_off + idx * 4
        out.append(dict(file_off=off,
                        orig_hex=struct.pack('<I', orig).hex(),
                        new_hex=struct.pack('<I', new).hex(),
                        why='图标码换区（CharWidth cave）：0x%04X → 0x%04X'
                            % (orig & 0xFFFF, new & 0xFFFF)))
    return out


def _apply_hex_patches(buf, patches, tag):
    for p in patches:
        off = p['file_off']
        oldb = bytes.fromhex(p['orig_hex'])
        newb = bytes.fromhex(p['new_hex'])
        assert len(oldb) == len(newb) and len(oldb) % 4 == 0, p
        cur = bytes(buf[off:off + len(oldb)])
        assert cur == oldb, ('%s 补丁点 0x%X 原字节不符: 期望 %s / 实际 %s'
                             % (tag, off, oldb.hex(), cur.hex()))
        buf[off:off + len(newb)] = newb


BOOT_TEXT_SLOTS = [
    # (file_off, 槽最大字节数(含 NUL), 中文)
    (0x487040, 32, '正在载入中...'),      # FR
    (0x487060, 24, '请稍候，正在载入...'),  # FR wait
    (0x487078, 8,  '载入...'),             # DE
    (0x487080, 16, '请等待...'),           # DE wait
    (0x487090, 32, '正在载入中...'),      # IT
    (0x4870B0, 16, '请等待...'),           # IT wait
    (0x4870C0, 16, '载入中...'),           # ES
    (0x4870D0, 24, '请等待...'),           # ES wait
    (0x4870E8, 16, '载入中...'),           # EN
    (0x4870F8, 12, '请等待...'),           # EN wait
    (0x48D810, 24, '正在载入中...'),      # FR (second table)
    (0x48D828, 8,  '载入...'),             # DE
    (0x48D830, 24, '正在载入中...'),      # IT
    (0x48D848, 16, '载入中...'),           # ES
    (0x48D858, 16, '载入中...'),           # EN
]


def boot_text_patches(orig_elf):
    """ELF 里 5 语言「载入提示条」槽表 → 中文（原位覆盖，槽长不变）。"""
    from textlib import Charset
    cs = Charset()

    def enc(t):
        out = bytearray()
        for ch in t:
            if ch in cs.pair:
                out += bytes(cs.pair[ch])
            elif ch in cs.single:
                out.append(cs.single[ch])
            elif ord(ch) < 0x80:
                out.append(ord(ch))
            else:
                raise SystemExit('boot text: 缺字 %r' % ch)
        return bytes(out)

    out = []
    for off, maxlen, txt in BOOT_TEXT_SLOTS:
        data = enc(txt) + b'\x00'
        pad = ((len(data) + 3) // 4) * 4
        assert pad <= maxlen, (hex(off), txt, len(data), maxlen)
        new_b = data + b'\x00' * (pad - len(data))
        cur = orig_elf[off:off + pad]
        out.append(dict(file_off=off, orig_hex=cur.hex(), new_hex=new_b.hex(),
                        why='启动载入提示「%s」（槽 %d B）' % (txt, maxlen)))
    return out


def spec_stage(verbose=True):
    """生成 tools/dlc/elf_patches.json（DBCS 规格 + 过滤/行盒 + 串守卫）。"""
    if not os.path.exists(ELF_DBCS_SPEC):
        raise SystemExit('缺少 DBCS 规格 %s（先跑 tools/analysis/dbcs_spec.py）' % ELF_DBCS_SPEC)
    spec = json.load(open(ELF_DBCS_SPEC, encoding='utf-8'))
    cave = spec['cave']
    cave_off = int(cave['file_off'], 16)
    cave_bytes = b''.join(struct.pack('<I', int(w, 16)) for w in cave['words'])
    assert len(cave_bytes) == cave['size'], (len(cave_bytes), cave['size'])

    if os.path.exists(ELF_BASE_ELF):
        orig_elf = open(ELF_BASE_ELF, 'rb').read()
    else:
        iso = L.Iso()
        orig_elf = iso.elf()
        iso.close()

    patches = []
    for p in spec['patches']:
        off = int(p['file_off'], 16)
        old = struct.pack('<I', int(p['old'], 16))
        new = struct.pack('<I', int(p['new'], 16))
        cur = orig_elf[off:off + 4]
        assert cur == old, 'DBCS 补丁点 0x%X 原字节不符: %s vs %s' % (off, cur.hex(), old.hex())
        patches.append(dict(file_off=off, orig=old.hex(), new=new.hex(), why=p.get('why', '')))
    cur = orig_elf[cave_off:cave_off + len(cave_bytes)]
    patches.append(dict(file_off=cave_off, orig=cur.hex(), new=cave_bytes.hex(),
                        why='DBCS decoder/CharWidth/UV/StringWidth cave（%d 条指令）'
                            % (len(cave_bytes) // 4)))
    buf = bytearray(orig_elf)
    for p in patches:
        buf[p['file_off']:p['file_off'] + len(p['orig']) // 2] = bytes.fromhex(p['new'])
    sha = hashlib.sha256(bytes(buf)).hexdigest()
    crc = _elf_crc(buf)
    exp_sha = spec['result']['sha256']
    exp_crc = spec['result']['game_crc']
    if verbose:
        P('[spec] DBCS 规格 %d 段 → sha256 %s（期望 %s）; CRC %08X（期望 %s）'
          % (len(patches), sha[:16], exp_sha[:16], crc, exp_crc))
    assert sha == exp_sha, 'DBCS 结果 sha256 与规格不符'
    assert ('%08X' % crc) == exp_crc.upper(), 'DBCS 结果 CRC 与规格不符'

    if os.environ.get('GRJS_OLD_ICON_CODE'):
        P('[spec] GRJS_OLD_ICON_CODE=1：图标码保持 0xB1/0xB5（仅用于 A/B 对照）')
    else:
        ip = icon_code_patches(spec)
        _apply_hex_patches(buf, ip, 'ICONCODE')
        patches += [dict(file_off=i['file_off'], orig=i['orig_hex'], new=i['new_hex'],
                         why=i['why']) for i in ip]
        if verbose:
            P('[spec] 叠加 %d 段图标码换区 → sha256 %s ; CRC %08X'
              % (len(ip), hashlib.sha256(bytes(buf)).hexdigest()[:16], _elf_crc(buf)))

    _apply_hex_patches(buf, _anchor_patches(), 'EXTRA')
    patches += [dict(file_off=e['file_off'], orig=bytes.fromhex(e['orig_hex']).hex(),
                     new=bytes.fromhex(e['new_hex']).hex(), why=e['why'])
                for e in _anchor_patches()]
    if verbose:
        P('[spec] 叠加 %d 段字库过滤/行盒锚点 → sha256 %s ; CRC %08X'
          % (len(ELF_EXTRA_PATCHES), hashlib.sha256(bytes(buf)).hexdigest()[:16], _elf_crc(buf)))

    wp = [] if os.environ.get('GRJS_NO_WRAP') else wrap_dcs_patches()
    if os.environ.get('GRJS_NO_WRAP'):
        P('[spec] GRJS_NO_WRAP=1：不叠加折行修复（仅用于 A/B 对照）')
    _apply_hex_patches(buf, wp, 'WRAP')
    patches += [dict(file_off=w['file_off'], orig=w['orig_hex'], new=w['new_hex'],
                     why=w['why']) for w in wp]
    if verbose:
        P('[spec] 叠加 %d 段折行 DBCS 修复 → sha256 %s ; CRC %08X'
          % (len(wp), hashlib.sha256(bytes(buf)).hexdigest()[:16], _elf_crc(buf)))

    if not os.environ.get('GRJS_NO_STRING_GUARD'):
        sg = string_guard_patches()
        _apply_hex_patches(buf, sg, 'STRINGGUARD')
        patches += [dict(file_off=g['file_off'], orig=g['orig_hex'], new=g['new_hex'],
                         why=g['why']) for g in sg]
        if verbose:
            P('[spec] 叠加 %d 段串越界/NULL 守卫 → sha256 %s ; CRC %08X'
              % (len(sg), hashlib.sha256(bytes(buf)).hexdigest()[:16], _elf_crc(buf)))
    else:
        P('[spec] GRJS_NO_STRING_GUARD=1：不叠加串守卫（仅用于 A/B 对照）')
    if not os.environ.get('GRJS_NO_CASEFOLD'):
        cf = casefold_guard_patches()
        _apply_hex_patches(buf, cf, 'CASEFOLD')
        patches += [dict(file_off=c['file_off'], orig=c['orig_hex'], new=c['new_hex'],
                         why=c['why']) for c in cf]
        if verbose:
            P('[spec] 叠加 %d 段大小写折叠高字节守卫 → sha256 %s ; CRC %08X'
              % (len(cf), hashlib.sha256(bytes(buf)).hexdigest()[:16], _elf_crc(buf)))
    else:
        P('[spec] GRJS_NO_CASEFOLD=1：不叠加大小写折叠守卫（仅用于 A/B 对照）')


    if not os.environ.get('GRJS_NO_BOOT_TEXT'):
        bt = boot_text_patches(orig_elf)
        _apply_hex_patches(buf, bt, 'BOOTTEXT')
        patches += [dict(file_off=b['file_off'], orig=b['orig_hex'], new=b['new_hex'],
                         why=b['why']) for b in bt]
        if verbose:
            P('[spec] 叠加 %d 段启动载入提示汉化 → sha256 %s ; CRC %08X'
              % (len(bt), hashlib.sha256(bytes(buf)).hexdigest()[:16], _elf_crc(buf)))
    else:
        P('[spec] GRJS_NO_BOOT_TEXT=1：不改启动载入提示（A/B 对照）')

    final_sha = hashlib.sha256(bytes(buf)).hexdigest()
    final_crc = '%08X' % _elf_crc(buf)
    # 归一化：多组补丁可能重叠（DBCS 站点/ cave 与图标码换区），或同一段被多次
    # 记录。记录里统一写成最终字节，并把「完全落在已记录区段内」的重复项合并掉。
    norm = []
    ranges = []
    for p in patches:
        off = p['file_off']
        n = len(p['orig']) // 2
        end = off + n
        if any(lo <= off and end <= hi for lo, hi in ranges):
            continue
        norm.append(dict(file_off=off,
                         orig=p['orig'],
                         new=bytes(buf[off:off + n]).hex(),
                         why=p['why']))
        ranges.append((off, end))
    patches = norm
    obj = dict(schema='grjs-elf-patches/1',
               source=os.path.relpath(ELF_DBCS_SPEC, REPO).replace('\\', '/'),
               base_elf=spec['base_elf'],
               cave_file_off=cave_off, cave_size=cave['size'],
               expect_elf_sha256=final_sha, expect_crc32=final_crc,
               crc_note='Game CRC 改变 ⇒ PCSX2 旧即时存档失效（发布说明要写「请新开档」）',
               patches=patches)
    with open(ELF_SPEC_PATH, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    if verbose:
        P('[spec] 写出 %s（%d 段补丁）; ELF sha256 %s ; CRC %s'
          % (os.path.relpath(ELF_SPEC_PATH, REPO), len(patches), final_sha[:16], final_crc))
    return 0


# ═════════════════════════ 文本表格（--stage dump-text） ═════════════════════════
_TEXT_TABLES = [
    ('lang_source.csv', 'LANG', 'lang_bilingual.csv'),
    ('sfxml_text_source.csv', 'SFXML', 'sfxml_text_bilingual.csv'),
    ('sfxml_titles_source.csv', 'SFXML_TITLE', 'sfxml_titles_bilingual.csv'),
    ('mis_source.csv', 'MIS', 'mis_bilingual.csv'),
    ('atr_source.csv', 'ATR', 'atr_bilingual.csv'),
    ('strings_txt_source.csv', 'STRINGS_TXT', 'strings_txt_bilingual.csv'),
]


def _dump_iso_tables(iso_path, out_dir):
    """把某个 ISO 的文本表格抽到 out_dir（复用 dump_text.py 的抽取函数）。"""
    sys.path.insert(0, HERE)
    import dump_text as D
    os.makedirs(out_dir, exist_ok=True)
    old_source, old_work = D.SOURCE, D.WORK
    D.SOURCE, D.WORK = out_dir, out_dir
    try:
        class _Args:
            pass
        a = _Args()
        a.iso = iso_path
        D.cmd_dump(a)
    finally:
        D.SOURCE, D.WORK = old_source, old_work


def _read_csv_rows(path):
    import csv
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        return list(csv.reader(f))


def _text_col(header):
    for name in ('text_en', 'text', 'value', 'name'):
        if name in header:
            return header.index(name)
    return None


def _key_col(header):
    for name in ('key', 'id', 'token'):
        if name in header:
            return header.index(name)
    return 0


def _latest_translation():
    """优先取最新合并译文表：translations_v21.csv → translations_v20.csv → translations_all.csv。"""
    base = os.path.join(REPO, 'work', 'translation', 'merged')
    for name in ('translations_v21.csv', 'translations_v20.csv', 'translations_all.csv'):
        p = os.path.join(base, name)
        if os.path.exists(p):
            return p
    return os.path.join(base, 'translations_all.csv')


def _load_translations(path):
    """读合并译文表 → {(resource, id): text_zh}。"""
    import csv
    out = {}
    if not path or not os.path.exists(path):
        return out
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            res = (row.get('resource') or '').strip()
            rid = (row.get('id') or '').strip()
            zh = row.get('text_zh') or ''
            if res and rid and zh:
                out[(res, rid)] = zh
    return out


def _translation_key(res, key):
    if res == 'ATR' and key.startswith('ATR:'):
        body = key[4:]
        if body.endswith(':ActorName'):
            body = body[:-len(':ActorName')] + '#ActorName'
        return (res, body)
    return (res, key)


def dump_text_stage(translations_csv=None, out_dir=None, verbose=True):
    """抽取文本表格并与译文对照，输出到 out_dir（默认 work/analysis/text/tables）。

    · 原文表：英文原盘（只读）→ <dir>/en/
    · 对照表：<dir>/*_bilingual.csv
        key / text_en / text_zh / status / byte_len_en / byte_len_zh
      译文取合并译文表（默认 work/translation/merged/translations_all.csv）。
    """
    base = os.path.abspath(out_dir or TEXT_TABLE_DIR)
    en_dir = os.path.join(base, 'en')
    en_iso = L.DEFAULT_ISO
    trans_path = (translations_csv or os.environ.get('GRJS_TRANS')
                  or _latest_translation())
    if not os.path.exists(en_iso):
        raise SystemExit('找不到英文原盘: %s' % en_iso)
    if verbose:
        P('=' * 96)
        P('文本表格 dump → %s' % base)
        P('  原文: %s' % os.path.basename(en_iso))
        P('  译文: %s' % trans_path)
    _dump_iso_tables(en_iso, en_dir)
    trans = _load_translations(trans_path)
    total = dict(rows=0, translated=0, kept_en=0, empty=0)
    summary = []
    import csv as _csv
    for src_name, res, out_name in _TEXT_TABLES:
        en_path = os.path.join(en_dir, src_name)
        if not os.path.exists(en_path):
            continue
        rows_src = _read_csv_rows(en_path)
        if not rows_src:
            continue
        header = rows_src[0]
        kc = _key_col(header)
        tc = _text_col(header)
        blen = header.index('byte_len_en') if 'byte_len_en' in header else None
        fi = header.index('flags') if 'flags' in header else None
        out_rows = []
        n_t = n_k = n_e = 0
        for r in rows_src[1:]:
            if len(r) <= kc:
                continue
            key = r[kc]
            en = r[tc] if tc is not None and len(r) > tc else ''
            zh = trans.get(_translation_key(res, key), '')
            flags = r[fi] if fi is not None and len(r) > fi else ''
            if not zh:
                if 'keep_english' in flags or 'keep:' in flags:
                    status = 'kept_en'
                    n_k += 1
                else:
                    status = 'empty'
                    n_e += 1
            elif zh == en:
                status = 'kept_en'
                n_k += 1
            else:
                status = 'translated'
                n_t += 1
            out_rows.append([key, en, zh, status,
                             (r[blen] if blen is not None and len(r) > blen else ''),
                             len(zh.encode('utf-8'))])
        out_path = os.path.join(base, out_name)
        with open(out_path, 'w', encoding='utf-8-sig', newline='') as f:
            w = _csv.writer(f, lineterminator='\r\n')
            w.writerow(['key', 'text_en', 'text_zh', 'status', 'byte_len_en', 'byte_len_zh'])
            w.writerows(out_rows)
        summary.append(dict(resource=res, file=out_name, rows=len(out_rows),
                            translated=n_t, kept_en=n_k, empty=n_e))
        total['rows'] += len(out_rows)
        total['translated'] += n_t
        total['kept_en'] += n_k
        total['empty'] += n_e
        if verbose:
            P('  [%-10s] %-28s %5d 行：译 %5d / 保留英文 %5d / 空 %4d'
              % (res, out_name, len(out_rows), n_t, n_k, n_e))

    all_path = os.path.join(base, 'bilingual_all.csv')
    with open(all_path, 'w', encoding='utf-8-sig', newline='') as f:
        w = _csv.writer(f, lineterminator='\r\n')
        w.writerow(['resource', 'key', 'text_en', 'text_zh', 'status'])
        for src_name, res, out_name in _TEXT_TABLES:
            p2 = os.path.join(base, out_name)
            if not os.path.exists(p2):
                continue
            for r in _read_csv_rows(p2)[1:]:
                w.writerow([res] + r[:4])
    # 图标占位码检测（单字节 0xB1/0xB5 = 引擎手柄按键图标）
    try:
        sys.path.insert(0, os.path.join(REPO, 'tools', 'font'))
        import atlas_guard as AG
        _iso_path = os.environ.get('GRJS_DUMP_ISO') or L.DEFAULT_ISO
        icon_rows = AG.scan_icon_codes(_iso_path)
        AG.write_icon_report(icon_rows, os.path.join(base, 'text_icons.csv'))
        total['icon_entries'] = len(icon_rows)
        if verbose:
            P('  [icons] 单字节图标占位码条目：%d（%s）'
              % (len(icon_rows), os.path.join(base, 'text_icons.csv')))
    except Exception as _ex:                                     # noqa: BLE001
        if verbose:
            P('  [icons] 扫描跳过: %r' % (_ex,))
    # 给各表追加 text_edited 列（供 tools/dlc/edit_text.py 反向写回；已有编辑会保留）
    try:
        import edit_text as _E
        added = 0
        for _p, _res in _E.tables(base):
            if _E.add_edited_column(_p):
                added += 1
        if verbose and added:
            P('  [edit] 已给 %d 张表追加 text_edited 列（可用 edit_text.py inject 写回）' % added)
    except Exception as _ex:                                     # noqa: BLE001
        if verbose:
            P('  [edit] 追加 text_edited 列跳过: %r' % (_ex,))
    stats = dict(base=base, translations=os.path.relpath(trans_path, REPO),
                 total=total, tables=summary)
    with open(os.path.join(base, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    if verbose:
        P('  ---------------- 合计 %d 行：译 %d / 保留英文 %d / 空 %d'
          % (total['rows'], total['translated'], total['kept_en'], total['empty']))
        P('  总表 bilingual_all.csv；统计 summary.json；目录 %s' % base)
    return 0


# ───────────────────────── 内容提供者 ─────────────────────────
def font_provider(verbose=True):
    """返回 {条目名: 新 blob}（fontlib 负责字节构造；失败抛异常）。

    ★ 字符集扩充（方案 B 最后一环）：先按 assets/charset/charset_expand_dlc.json
      把译文缺字补画进图集容器（开发期由 tools/font/expand_charset.py 规划并回写
      charset/expand json），再把「补画后的容器」交给 build_new_pak。
    """
    import fontlib as F
    import build_font as BF
    import expand_charset as EC

    seed = BF.load_seed()
    dlc = BF.load_dlc()
    container, exp = EC.expand_container(seed['container'])
    if verbose and exp.get('assignments'):
        P('  [font] 字符集扩充：补画 %d 字，容器 sha256=%s'
          % (exp['assignments'], exp['container_sha256'][:16]))
    new_pak, pak_info = F.build_new_pak(dlc['pak'], dlc['recs'], seed,
                                        clut_mode='native', container=container)
    font_frame, merged_ft, ft_info = F.build_new_ft_frame(
        dlc['font_raw'], dlc['ft_e'], seed['ft_blob'])
    # 新 COMMON.PAK 是 raw 资源 → 直接把 PAK 字节作为 blob（rebuild 原样写）
    # 新 FONT.RES 是 LZO 资源 → 给展开 blob（rebuild 按 16KB 块重压）
    repl = {'COMMON.PAK': new_pak, 'FONT.RES': merged_ft}
    # ★ 图标哨兵槽保护（v15）：50 个 trail∈{0xB1,0xB5} 的槽是引擎图标特判槽，禁止占用/覆盖
    sys.path.insert(0, os.path.join(REPO, 'tools', 'font'))
    import atlas_guard as AG
    ok_cs, bad_cs, _risk = AG.check_charset()
    assert ok_cs, '字符集占用了图标哨兵槽: %r' % (bad_cs[:5],)
    if verbose:
        P('  [font] 图标哨兵槽检查：字符集 0 占用；图集 %d 格与 seed 比对…'
          % len(AG.sentinel_slots()))
    if verbose:
        fi, fr = F.pak_find(F.pak_parse(new_pak), 'new_font_revised')
        P('  [font] 新 COMMON.PAK %d B (Δ%+d) ; 合并 FONT.RES blob %d B（原槽 %d B）'
          % (len(new_pak), len(new_pak) - len(dlc['pak']), len(merged_ft),
             dlc['ft_e']['stored']))
        P('         new_font_revised psm=%d %dx%d clut=%d px=%d off=%d'
          % (fr['psm'], fr['w'], fr['h'], fr['clut'], fr['px'], fr['px_off']))
        P('         FONT.RES 3 face nrec=%s tail=%d B ; 新帧 %d B ≤ 原槽 %d B'
          % ([f['nrec'] for f in ft_info['faces']], ft_info['tail_len'],
             len(font_frame), dlc['ft_e']['stored']))
    # 新 PAK 的图集哨兵格必须与 seed 逐 texel 相同（图标像素受保护）
    _fi, _fr = F.pak_find(F.pak_parse(new_pak), 'new_font_revised')
    _cont = new_pak[_fr['px_off']:_fr['px_off'] + _fr['px']]
    _tex, _empty, _pk, _segs = F.atlas_engine_image(_cont, _fr['w'], _fr['h'], _fr['psm'])
    seed_atlas = AG.load_seed_atlas()
    if seed_atlas is not None:
        import numpy as np
        a = AG.slot_cells(_tex, AG.sentinel_slots())
        b = AG.slot_cells(seed_atlas['tex'], AG.sentinel_slots())
        bad = [AG.sentinel_slots()[i]['slot'] for i, (ca, cb) in enumerate(zip(a, b))
               if ca is None or cb is None or not np.array_equal(ca, cb)]
        assert not bad, '图集哨兵格被改动（图标像素）: %r' % (bad[:8],)
        if verbose:
            P('  [font] 图标哨兵格像素 == seed：OK（%d 格）' % len(a))
    return repl


def text_provider(verbose=True):
    """返回 {条目名: 新 blob}（由 inject_text.py 构造；未就绪时返回 {} 并告警）。"""
    try:
        if os.environ.get('GRJS_INJECT_FALLBACK'):
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location('inject_text',
                                                  os.environ['GRJS_INJECT_FALLBACK'])
            I = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(I)
        else:
            import inject_text as I
    except ImportError:
        if verbose:
            P('  [text] !! tools/dlc/inject_text.py 尚未就绪 —— 跳过文本替换')
        return {}
    if not hasattr(I, 'build_replacements'):
        P('  [text] !! inject_text.py 缺少 build_replacements() —— 跳过')
        return {}
    trans = os.environ.get('GRJS_TRANS') or _latest_translation()
    if not os.path.exists(trans):
        P('  [text] !! 缺少合并译文表 %s（先跑 tools/dlc/merge_translations.py）' % trans)
        return {}
    # allow_marker_drift：TM（本体成品译文）里有意插入的 {br} 软换行与资料片原文 {p} 计数不同，
    #   这是**预期**的（新译文批次已被 check_translated.py 严格校验过标记数量）。
    repl, report = I.build_replacements(L.DEFAULT_ISO, [trans], allow_marker_drift=True)
    if verbose:
        P('  [text] 替换 %d 个资源' % len(repl))
        for k in ('lang_entries', 'lang_changed', 'lang_groups', 'sfxml_texts',
                  'sfxml_changed', 'mis_files', 'atr_files', 'txt_entries',
                  'missing_chars', 'marker_drift', 'warnings', 'errors'):
            if k in report:
                v = report[k]
                P('         %-14s %s' % (k, (v if not isinstance(v, (list, dict))
                                             else (len(v) if isinstance(v, list) else v))))
    return repl


def elf_provider(verbose=True):
    """返回新 ELF 字节；未就绪返回 None。"""
    spec = os.path.join(HERE, 'elf_patches.json')
    if not os.path.exists(spec):
        if verbose:
            P('  [elf] !! tools/dlc/elf_patches.json 尚未就绪 —— 保持原版 ELF')
        return None
    import json as _json
    obj = _json.load(open(spec, encoding='utf-8'))
    iso = L.Iso()
    elf = bytearray(iso.elf())
    iso.close()
    for patch in obj.get('patches', []):
        off = patch['file_off']
        orig = bytes.fromhex(patch['orig'])
        new = bytes.fromhex(patch['new'])
        cur = bytes(elf[off:off + len(orig)])
        assert cur == orig, 'ELF 补丁点 0x%X 原字节不符: 期望 %s / 实际 %s' % (
            off, orig.hex(), cur.hex())
        elf[off:off + len(new)] = new
    if verbose:
        P('  [elf] 应用 %d 处补丁；新 ELF sha256 %s (%d B)'
          % (len(obj.get('patches', [])), hashlib.sha256(elf).hexdigest(), len(elf)))
    return bytes(elf)


PROVIDERS = [('font', font_provider), ('text', text_provider), ('elf', elf_provider)]


def collect(stage, verbose=True):
    """按阶段收集全部替换（从原盘出发的累积替换）。

    font : 字库两件套（GR#9 / GR#580）
    text : font + 文本资源
    elf  : font + ELF 补丁（无文本；用于先验证 DBCS/字库渲染）
    all  : font + text + elf（正式版）
    """
    repl = {}
    elf = None
    for name, fn in PROVIDERS:
        if name == 'elf':
            if stage in ('elf', 'all'):
                elf = fn(verbose)
            continue
        if name == 'font' and stage in ('font', 'text', 'elf', 'all'):
            repl.update(fn(verbose))
        if name == 'text' and stage in ('text', 'all'):
            repl.update(fn(verbose))
    return repl, elf


# ───────────────────────── 主流程 ─────────────────────────
def load_spec():
    if os.path.exists(SPEC_PATH):
        return json.load(open(SPEC_PATH, encoding='utf-8'))
    return dict(schema='grjs-build/1', inputs={}, stages={})


def save_spec(spec):
    json.dump(spec, open(SPEC_PATH, 'w', encoding='utf-8', newline='\n'),
              ensure_ascii=False, indent=1)


def default_out(stage):
    names = {'font': 'JS_ZH_font.iso', 'text': 'JS_ZH_text.iso',
             'elf': 'JS_ZH_elf.iso', 'all': 'JS_ZH_final.iso'}
    return os.path.join(BUILD_DIR, names[stage])


def main(argv):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                          # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description='资料片汉化唯一构筑脚本（从英文原盘重建）')
    ap.add_argument('--stage', choices=[s[0] for s in STAGES] + ['list'], default='all')
    ap.add_argument('--out', help='输出 ISO 路径（构筑阶段）或输出目录（dump-text）')
    ap.add_argument('--out-dir', help='dump-text 输出目录（默认 work/analysis/text/tables）')
    ap.add_argument('--iso', help='dump-text 的译文表 CSV（默认取 merged 下最新版）')
    ap.add_argument('--force', action='store_true', help='已存在也重建')
    ap.add_argument('--write-spec', action='store_true', help='把实测 sha256 写入 fix_spec.json')
    ap.add_argument('--keep-intermediate', action='store_true')
    ap.add_argument('--no-verify', action='store_true')
    a = ap.parse_args(argv)

    if a.stage == 'list':
        P('阶段：')
        for sid, title in STAGES:
            P('  %-10s %s' % (sid, title))
        P('')
        P('用法示例：')
        P('  python tools\\dlc\\build.py --stage spec        # 生成 ELF 补丁表')
        P('  python tools\\dlc\\build.py --stage all         # 全量构筑 ISO')
        P('  python tools\\dlc\\build.py --stage dump-text   # 抽文本表格')
        return 0
    if a.stage == 'spec':
        return spec_stage()
    if a.stage == 'dump-text':
        return dump_text_stage(translations_csv=a.iso, out_dir=a.out_dir or a.out)

    t0 = time.time()
    orig = L.DEFAULT_ISO
    if not os.path.exists(orig):
        raise SystemExit('找不到英文原盘: %s' % orig)
    orig_sha = sha256_file(orig)
    P('=' * 96)
    P('构建阶段: %s' % a.stage)
    P('基底: %s' % orig)
    P('      sha256 %s (%d B)' % (orig_sha, os.path.getsize(orig)))
    assert orig_sha == L.ISO_SHA256, '基底不是声明的英文原盘！'

    repl, elf = collect(a.stage, verbose=True)
    out = a.out or default_out(a.stage)
    if not os.path.isabs(out):
        out = os.path.abspath(out)
    if os.path.exists(out) and not a.force:
        P('[skip] 产物已存在: %s（--force 覆盖）' % out)
        return 0
    os.makedirs(os.path.dirname(out), exist_ok=True)
    for p in (out, out + '.part'):
        if os.path.exists(p):
            os.remove(p)

    P('')
    P('替换条目 %d 个；ELF %s' % (len(repl), '有补丁' if elf else '原样'))
    info = R.rebuild_iso(orig, out, repl, elf_bytes=elf)
    h = sha256_file(out)
    P('')
    P('★ 产物: %s' % out)
    P('  bytes  %d' % os.path.getsize(out))
    P('  sha256 %s' % h)
    P('  用时 %.1fs' % (time.time() - t0))

    spec = load_spec()
    spec['inputs'] = dict(iso=dict(path=os.path.relpath(orig, REPO), sha256=orig_sha,
                                   bytes=os.path.getsize(orig)))
    spec.setdefault('stages', {})
    if a.write_spec or a.stage not in spec['stages']:
        spec['stages'][a.stage] = dict(out=os.path.relpath(out, REPO),
                                       bytes=os.path.getsize(out), sha256=h)
        save_spec(spec)
        P('  [spec] 已写入 fix_spec.json 阶段 %s' % a.stage)
    else:
        exp = spec['stages'][a.stage]['sha256']
        P('  [spec] 期望 %s ⇒ %s' % (exp, 'OK' if exp == h else 'FAIL'))
        if exp != h:
            if os.environ.get('GRJS_NO_SPEC_CHECK'):
                P('  [spec] GRJS_NO_SPEC_CHECK=1：文本编辑构筑，跳过与 fix_spec 的比对')
            else:
                raise SystemExit('阶段 %s sha256 与 fix_spec.json 不符！' % a.stage)

    if not a.no_verify:
        import verify
        ok = verify.verify_iso(out, stage=a.stage)
        P('VERIFY', 'OK' if ok else 'FAIL')
        if not ok:
            raise SystemExit(1)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
