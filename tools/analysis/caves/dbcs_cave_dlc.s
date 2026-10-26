# -*- mode: mips-asm -*-
# ============================================================================
# dbcs_cave_dlc.s —— 《幽灵行动：丛林风暴》DLC (SLUS_208.20) DBCS 支持 cave · v2
# ----------------------------------------------------------------------------
# 由 tools/analysis/mipsasm.py 汇编（轻量 MIPS/EE 汇编器，带 83 条已知字节自测）。
# 由 tools/analysis/dbcs_spec.py 装载：分配到 DLC ELF .text 的未用区、生成逐字节补丁表。
#
# 设计来源：本体汉化最终 ELF (SLUS_206.13, sha a0c8499c…) 的 DBCS cave
#   （decoder@0x416ED0 / CharWidth@0x416F40 / UV@0x417050 / measure@0x417150 /
#     StringWidth tail@0x565670），按 DLC 的寄存器/地址/原函数布局改写；
#   并与 JS_ZH19 上一版构筑的 cave（VA 0x1808A8..，sha 80e25599…）逐块对照。
#
# 几何参数（font-engineer 定稿；与本 cave 的 .equ 一一对应）：
#   gate = 0xBA  ⇒ lead ∈ [0xA1,0xBA)（25 个 lead），trail ∈ [0xA1,0xFF)（94）
#   pair slot = (lead-0xA1)*94 + (trail-0xA1) ∈ [0,2350)
#   PAIR_BASE = 224（= FONT.RES 每 face 的 FT 记录数；pair 不占 FT 记录）
#   NCOL=64, CELL=16, Y0=3, SKIP_ROW=12, SKIP_ROWS=2
#   row = pair_slot/64, col = pair_slot%64
#   U0 = 16*col,        U1 = U0+16
#   if row>=12: row += 2
#   V0 = 16*row + 3,    V1 = V0+16
#   pair CharWidth = 16（恒定）
#
# DLC 原函数事实（实证，见 docs/ANALYSIS_ELF_DBCS_PORT.md）：
#   RSFontMgr::DrawString      VA 0x2195F0   (file 0x1196F0)
#   wctomb 单字节桩             VA 0x173678
#   RSFont::CharWidth          VA 0x21A360   (prologue: addiu sp,-0x20; sd ra,0x10; sq s0,0)
#   RSFont::ComputeCharTextureCoords VA 0x21A210（叶子函数，无 prologue）
#   RSFont::StringWidth        VA 0x21A4C0
#   FontDefinition: def+0x20=base char, def+0x38=记录表, def+0x44=count(224)
#   FT 记录 10B: +1=宽度字节, +2=U0, +4=V0, +6=U1, +8=V1（u16）
#   RSFont: +0x14=空格宽, +0x18=行距, +0x1c=宽度缩放, +0x24=固定宽度标志(nonzero 时
#           原版 CharWidth 直接返回 [font+0xc] 且不碰 def —— 本 cave 必须保留 !)
# ============================================================================

# ── 几何/常量（改几何只改这里） ─────────────────────────────────────────────
.equ GATE_HI,     0xBA      # lead 上界（不含）
.equ PAIR_N,      94        # trail 区间长度 = 0xFF-0xA1
.equ PAIR_BASE,   0xE0      # =224 = FT 记录数
.equ CELL,        16        # cell 宽/高（px）
.equ NCOL,        64        # 图集每行 cell 数
.equ Y0,          3         # 网格 V 起点偏移
.equ SKIP_ROW,    12        # 行 >= 12 时加 SKIP_ROWS 行高空隙
.equ SKIP_ROWS,   2

# ── DLC 原函数中的关键地址（全部实证） ────────────────────────────────────
.equ ADDR_DRAW_LOOP,   0x219950   # DrawString 循环尾部 slt（步长推进之后）
.equ ADDR_CW_EPILOGUE, 0x21A420   # CharWidth 尾声起点
.equ ADDR_CW_FIXED,    0x21A378   # CharWidth 固定宽度分支（jal [font+0xc]）
.equ ADDR_UV_SINGLE,   0x21A218   # UV 单字节路径（lbu base char 处）
.equ ADDR_SW_LOOPEND,  0x21A538   # StringWidth 循环 s0+=v0 / s4+=1 处
.equ ADDR_SW_LOOPTOP,  0x21A540   # StringWidth 循环条件
.equ ADDR_SW_RET,      0x21A55C   # StringWidth `move v0,s0`（尾声前）

# ============================================================================
# 1) 解码 cave（替换 wctomb 桩调用）
#    入口：a0 = 输出 2 字节格指针；a1 = DrawString 用 `lb` 取出的带符号字节
#    出口：0(a0)/1(a0) 写小端 16 位码（单字节 0x00?? / 对偶 (lead<<8)|trail）
#          -1(a0) 写步长 1 或 2
#    依赖调用者活寄存器（DLC DrawString）：s2=串基址, s5=字节游标, s7=串长
#    clobber: v0,v1,a1,t0,t1,t3,t4,t7,t8（均为 caller-saved）
# ============================================================================
decode:
    andi    $a1, $a1, 0xFF
    sh      $a1, 0($a0)              # 先按单字节写
    addiu   $v0, $zero, 1            # 默认步长 1
    sltiu   $t1, $a1, 0xA1
    bnez    $t1, decode_single
    nop
    sltiu   $t1, $a1, GATE_HI        # ★ gate：lead ∈ [0xA1,0xBA)
    beqz    $t1, decode_single
    nop
    addiu   $t8, $s7, -1             # len-1
    slt     $t8, $s5, $t8            # 还有下一字节？
    beqz    $t8, decode_single
    nop
    addu    $t7, $s2, $s5
    lbu     $t3, 1($t7)              # trail
    sltiu   $t1, $t3, 0xA1
    bnez    $t1, decode_single
    nop
    sltiu   $t1, $t3, 0xFF
    beqz    $t1, decode_single
    nop
    sll     $t4, $a1, 8
    or      $t4, $t4, $t3
    sh      $t4, 0($a0)              # 写打包值 (lead<<8)|trail
    addiu   $v0, $zero, 2            # 步长 2
decode_single:
    sb      $v0, -1($a0)
    jr      $ra
    nop

# ============================================================================
# 2) DrawString 游标推进（替换 0x21994C 的 addiu s5,s5,1）
#    DrawString 在 0x219950 继续 slt/bnez；步长字节由 decode cave 写在 sp+0xDD
# ============================================================================
draw_advance:
    lbu     $v0, 0xDD($sp)
    addu    $s5, $s5, $v0
    j       ADDR_DRAW_LOOP
    nop

# ============================================================================
# 3) CharWidth cave（替换 RSFont::CharWidth 0x21A360 的函数体）
#    入口时原函数 prologue 已执行：sp -= 0x20, [sp+0x10]=ra, [sp]=s0
#    a0 = RSFont*, a1 = 解码值（单字节 0x00?? / 对偶 lead<<8|trail）
#    返回 v0 = 宽度（像素，int）
#    ★ 必须保留原版 font+0x24 固定宽度早退，否则未加载字体(def==0)会硬 fault
#      —— JS_ZH19 的 cave 漏了这条，是其崩溃的放大因素之一。
# ============================================================================
charwidth:
    lbu     $v0, 0x24($a0)           # 原版固定宽度标志
    beqz    $v0, cw_normal
    nop
    j       ADDR_CW_FIXED            # 原路径：jal [font+0xc] → 尾声
    nop
cw_normal:
    sll     $a1, $a1, 16             # 统一成零扩展低 16 位（兼容调用者用 lb 送负数字节）
    srl     $a1, $a1, 16
    srl     $t0, $a1, 8              # lead 候选
    sltiu   $t1, $t0, 0xA1
    bnez    $t1, cw_single
    nop
    sltiu   $t1, $t0, GATE_HI
    beqz    $t1, cw_single           # lead 不在 [0xA1,0xBA) ⇒ 单字节（含符号扩展残留）
    nop
    addiu   $t9, $zero, 1            # t9=1：对偶路径
    j       cw_dual
    nop
    # ---- 单字节（ASCII / 图标） ----
cw_single:
    move    $t9, $zero               # t9=0：单字节路径
    andi    $t3, $a1, 0xFF
    addiu   $t1, $zero, 0x20
    beq     $t3, $t1, cw_space
    nop
    addiu   $t1, $zero, 0xB5
    beq     $t3, $t1, cw_icon
    nop
    addiu   $t1, $zero, 0xB1
    beq     $t3, $t1, cw_icon
    nop
    lw      $a2, 0x28($a0)           # def
    beqz    $a2, cw_fallback          # ★ def 未就绪 → 安全回退
    nop
    lbu     $v1, 0x20($a2)           # base char
    subu    $t0, $t3, $v1
    andi    $t0, $t0, 0xFF
    j       cw_lookup
    nop
    # ---- 对偶（pair） ----
cw_dual:
    andi    $t1, $t0, 0xFF           # lead
    addiu   $t1, $t1, -0xA1
    andi    $t2, $a1, 0xFF           # trail
    addiu   $t2, $t2, -0xA1
    addiu   $t6, $zero, PAIR_N
    mult    $t0, $t1, $t6            # R5900 三操作数：t0 = (lead-0xA1)*94
    addu    $t0, $t0, $t2
    addiu   $t0, $t0, PAIR_BASE      # slot = 224 + pair_slot
    lw      $a2, 0x28($a0)
    beqz    $a2, cw_sixteen          # ★ def 未就绪 → pair 用 16
    nop
cw_lookup:
    lw      $v1, 0x44($a2)           # count
    sltu    $v0, $t0, $v1
    bnez    $v0, cw_rec
    nop
    bnez    $t9, cw_sixteen          # 对偶越界 → 16
    nop
    move    $t0, $zero              # 单字节越界 → 记录 0（原版语义）
    j       cw_rec
    nop
cw_sixteen:
    addiu   $v0, $zero, CELL         # pair 宽度恒 16
    j       cw_ret
    nop
cw_rec:
    lw      $a1, 0x38($a2)           # 记录表
    sll     $v0, $t0, 2
    addu    $v0, $v0, $t0
    sll     $v0, $v0, 1              # idx*10
    addu    $v0, $v0, $a1
    lbu     $v0, 1($v0)              # 记录 +1 = 宽度字节
    mtc1    $v0, $f1
    cvt.s.w $f1, $f1
    lwc1    $f0, 0x1c($a0)           # 宽度缩放
    mul.s   $f0, $f1, $f0
    cvt.w.s $f0, $f0
    mfc1    $v0, $f0
    j       cw_ret
    nop
cw_space:
    lw      $v0, 0x14($a0)           # 空格宽
    j       cw_ret
    nop
cw_icon:
    addiu   $v0, $zero, 20           # 图标宽恒 20
    j       cw_ret
    nop
cw_fallback:
    lw      $v0, 0x0C($a0)           # = 原版 +0x24!=0 路径的返回字段
cw_ret:
    ld      $ra, 0x10($sp)
    lq      $s0, 0($sp)
    jr      $ra
    addiu   $sp, $sp, 0x20

# ============================================================================
# 4) 槽位→UV cave（替换 RSFont::ComputeCharTextureCoords 0x21A210 入口）
#    入口：a0=RSFont*, a1=解码值, a2/a3/t0/t1 = 4 个 float 输出指针
#    单字节 → 原版 FT 记录路径（j ADDR_UV_SINGLE，需 t3=def, v1=code&0xFF）
#    对偶   → 网格公式（NCOL/CELL/Y0/SKIP_*）
#    ★ def==0 时写 0,0,0,0 而不是硬 fault
# ============================================================================
uv:
    sll     $a1, $a1, 16             # 统一成零扩展低 16 位（兼容符号扩展调用者）
    srl     $a1, $a1, 16
    srl     $t4, $a1, 8              # lead 候选
    sltiu   $t2, $t4, 0xA1
    bnez    $t2, uv_single
    nop
    sltiu   $t2, $t4, GATE_HI
    beqz    $t2, uv_single           # lead 不在 [0xA1,0xBA) ⇒ 单字节
    nop
    j       uv_dual
    nop
uv_single:
    lw      $t3, 0x28($a0)           # def
    beqz    $t3, uv_zero
    nop
    andi    $v1, $a1, 0xFF
    j       ADDR_UV_SINGLE
    nop
uv_dual:
    lw      $t3, 0x28($a0)
    beqz    $t3, uv_zero
    nop
    andi    $t4, $t4, 0xFF           # lead
    addiu   $t4, $t4, -0xA1
    andi    $t5, $a1, 0xFF           # trail
    addiu   $t5, $t5, -0xA1
    addiu   $t6, $zero, PAIR_N
    mult    $t7, $t4, $t6            # t7 = (lead-0xA1)*94
    addu    $t7, $t7, $t5            # t7 = pair_slot
    addiu   $t6, $zero, NCOL
    divu    $t7, $t6
    mflo    $t4                      # row = pair_slot / NCOL
    mfhi    $t5                      # col = pair_slot % NCOL
    addiu   $t6, $zero, CELL
    mult    $t8, $t5, $t6            # t8 = 16*col
    addiu   $t5, $t8, 0              # U0 = 16*col
    addiu   $t7, $t8, CELL           # U1 = U0+16
    addiu   $t6, $zero, SKIP_ROW
    slt     $t6, $t4, $t6            # row < 12 ?
    bnez    $t6, uv_noskip
    nop
    addiu   $t4, $t4, SKIP_ROWS      # row += 2
uv_noskip:
    addiu   $t6, $zero, CELL
    mult    $t8, $t4, $t6            # t8 = 16*row
    addiu   $t4, $t8, Y0             # V0 = 16*row + 3
    addiu   $t8, $t8, Y0+CELL        # V1 = V0 + 16
    mtc1    $t5, $f0
    cvt.s.w $f0, $f0
    swc1    $f0, 0($a2)              # U0
    mtc1    $t4, $f0
    cvt.s.w $f0, $f0
    swc1    $f0, 0($a3)              # V0
    mtc1    $t7, $f0
    cvt.s.w $f0, $f0
    swc1    $f0, 0($t0)              # U1
    mtc1    $t8, $f0
    cvt.s.w $f0, $f0
    swc1    $f0, 0($t1)              # V1
    jr      $ra
    nop
uv_zero:
    mtc1    $zero, $f0
    swc1    $f0, 0($a2)
    swc1    $f0, 0($a3)
    swc1    $f0, 0($t0)
    swc1    $f0, 0($t1)
    jr      $ra
    nop

# ============================================================================
# 5) StringWidth 逐字节循环 cave（替换 0x21A52C lb + 0x21A530 jal CharWidth）
#    入口时 v0 = s2+s4（串+游标，由 0x21A548 延迟槽算好）
#    s1=len, s2=串, s3=font, s0=宽度累加, s4=字节游标
# ============================================================================
measure:
    lbu     $a1, 0($v0)
    addiu   $t0, $s4, 1
    sltu    $t8, $t0, $s1            # cursor+1 < len ?
    beqz    $t8, measure_single
    nop
    sltiu   $t1, $a1, 0xA1
    bnez    $t1, measure_single
    nop
    sltiu   $t1, $a1, GATE_HI
    beqz    $t1, measure_single
    nop
    lbu     $t3, 1($v0)
    sltiu   $t1, $t3, 0xA1
    bnez    $t1, measure_single
    nop
    sltiu   $t1, $t3, 0xFF
    beqz    $t1, measure_single
    nop
    sll     $a1, $a1, 8
    or      $a1, $a1, $t3            # 打包值
    move    $a0, $s3
    jal     0x21A360                 # → CharWidth（已 patch → cave）
    nop
    addu    $s0, $s0, $v0
    addiu   $s4, $s4, 2
    j       ADDR_SW_LOOPTOP
    nop
measure_single:
    move    $a0, $s3
    lbu     $a1, 0($v0)              # 零扩展（本 cave 的 CharWidth 按零扩展约定）
    jal     0x21A360
    nop
    j       ADDR_SW_LOOPEND
    nop

# ============================================================================
# 6) StringWidth 尾部 cave（替换 0x21A54C..0x21A558 四字：字距按“字形数”而非字节数）
#    入口：s1=len, s2=串, s3=font, s0=宽度累加
#    公式：glyphs = len - n_dbc；s0 += (glyphs-1) * [font+0x18]
# ============================================================================
sw_tail:
    move    $v0, $zero               # i
    move    $t1, $zero               # n_dbc
    addiu   $t6, $s1, -1             # len-1
sw_loop:
    slt     $t2, $v0, $t6
    beqz    $t2, sw_done
    nop
    addu    $t3, $s2, $v0
    lbu     $t3, 0($t3)
    sltiu   $t4, $t3, 0xA1
    bnez    $t4, sw_single
    nop
    sltiu   $t4, $t3, GATE_HI
    beqz    $t4, sw_single
    nop
    addu    $t3, $s2, $v0
    lbu     $t5, 1($t3)
    sltiu   $t4, $t5, 0xA1
    bnez    $t4, sw_single
    nop
    sltiu   $t4, $t5, 0xFF
    beqz    $t4, sw_single
    nop
    addiu   $t1, $t1, 1
    addiu   $v0, $v0, 2
    j       sw_loop
    nop
sw_single:
    addiu   $v0, $v0, 1
    j       sw_loop
    nop
sw_done:
    subu    $t6, $t6, $t1            # 字形数-1
    lw      $t7, 0x18($s3)           # 字距
    mult    $t6, $t7
    mflo    $t6
    addu    $s0, $s0, $t6
    j       ADDR_SW_RET
    nop
