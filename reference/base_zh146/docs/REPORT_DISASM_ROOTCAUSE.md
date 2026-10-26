# GR_DISASM · 反汇编根因报告：游玩中卡死 / 2fps 挂起

> ⚠ **历史错误断言订正（2026-10-18 收尾轮）**：本文含已被实测/实机否证的表述 —— 见 `docs/CORRECTIONS.md` §4、§5。
> 原文保留作过程记录；**结论冲突时以 `docs/CORRECTIONS.md` + `docs/STATUS.md` 为准**。

> 生成：2026-10-17 · 执行者：GR_DISASM 子代理
> **全程只读**：所有 ISO / 产物 / PCSX2 目录只读；写入仅限 `work\builds\GR_DISASM\**`、
> `docs\REPORT_DISASM_ROOTCAUSE.md`、`docs\DISASM_TEST_GUIDE.md`。**没有写任何 ISO。**
> **所有结论都给了 VA + 指令 + 数据来源**，可用本目录工具逐条复现。
> 工具：`work\builds\GR_DISASM\tools\{ddump_scan,dediff_elf,de_dis,de_sites,de_capscan,de_fontmgr,de_abi_fp,de_abi_fp2,de_abi_fp3,dfix_apply}.py`
> 证据：`work\builds\GR_DISASM\audit\*`（原始输出）· `temp\*`（从块转储取回的 13 个 ELF）

---

## 0. 本轮新取回的素材（把"两条路径"的对比变成对称）

`%LOCALAPPDATA%\PCSX2\cdvd-dump\` 下 **21 个 `*.dump` 全部含完整的 `SLUS_206.13`**
（LBA 295..18582，18,288 扇区）。取回命令与逐盘覆盖表：`audit/dump_scan.txt`。

```powershell
python work\builds\GR_DISASM\tools\ddump_scan.py --extract '<dump 关键词>' <out.elf>
```

| 取回文件（`work\builds\GR_DISASM\temp\`） | 来源 dump | sha256（前 12） | ELF 是什么 |
|---|---|---|---|
| `BASE_ZH113b_SLUS_206.13.elf` | `GR_ZH113b (18-47-05)` | `3465580fac39` | **基底盘（gate 0xB1）的真 ELF** |
| `TXT02_SLUS_206.13.elf` | `TXT_02_orig_text` | `3465580fac39` | ★ 与基底**逐字节相同** |
| `AB04_SLUS_206.13.elf` | `AB_04_fontres_real5942` | `3465580fac39` | ★ 同上 |
| `SENT06_SLUS_206.13.elf` | `SENT_06_icon_all_off_zh113b` | `596f43f3…` | 基底 + 12 处图标补丁 |
| `SENT02_SLUS_206.13.elf` | `SENT_02_icon_path_off` | `ce6f2522…` | 另一组图标补丁 |
| `CVAR04_SLUS_206.13.elf` | `CVAR_04_text` | `5fec662f…` | ★ **= 原盘 ELF（无汉化 cave）** |
| `SENT01_SLUS_206.13.elf` | `SENT_01_trail_fix` | `5fec662f…` | ★ 同上（= 原盘 ELF） |
| `HASHR2400_SLUS_206.13.elf` | `GR_HASHR2400` | `5cb59175…` | ★ **= K2 的 ELF（gate 0xBA）** |
| `ZH125_SLUS_206.13.elf` | `GR_ZH125` | `17a5dd4d…` | K2 的基底 |
| `F365a/b`, `ZH113bfix`, `HK01` | 其余 dump | | 同血统其它变体 |

**三条硬结论（全部由 sha256 判定，`audit/elf_hashes.txt`）：**

1. `TXT_02`（基底 + 英文文本，**实机不卡**）与 `BASE_ZH113b`（基底盘）**ELF 逐字节相同**
   ⇒ **"不卡的盘"与"卡的盘"用的是同一份代码**；差别只在**数据（文本）**。
2. `CVAR_04`（**实机崩**）与 `SENT_01` 的 ELF **= 原盘 ELF**（`third_party\orig\ps2\slus_out\SLUS_206.13`）
   ⇒ **中文文本 + 完全未改动的原版代码也会崩** ⇒ 触发物**不是汉化 cave**，而是
   **中文文本数据本身的规模/内容**（配合引擎原有的硬编码容量）。
3. `HASHR2400` 与 `K2` **ELF 逐字节相同** ⇒ 这两张 2400 盘共享同一条代码路径（gate 0xBA）。

4. ★ **重建产物也已实测（只读）**：`work\builds\GR_REBUILD\GR_REBUILD2400.iso` 的
   `SLUS_206.13`（LBA 295，37453732 B）sha256 = `5cb59175…`，
   **与 K2 的 ELF 逐字节相同** ⇒ 重建盘落在 **B 线（gate 0xBA）**；
   本报告的 21 处站点原字断言在它上面 **21/21 全部通过**
   （原始输出 `audit/check_rebuild_iso.txt`）⇒ 补丁脚本可直接作用其上。

## 1. ★ 两条路径的差异：只有 **8 个字节**

`audit/diff_base_vs_k2.txt`（工具 `dediff_elf.py`，逐字节 diff + 按字归并）：

```
# A = temp\BASE_ZH113b_SLUS_206.13.elf   (gate 0xB1)
# B = ..\GR_CSFIX\temp\K2_SLUS_206.13.elf (gate 0xBA)
# size A/B = 37453732 / 37453732 ; segs A = [(1048576, 128, 5106944)]
# 差异 run = 8，差异字节 = 8
```

| # | VA | ELF off | A 字（0xB1 线） | B 字（0xBA 线） | A 指令 | B 指令 |
|---|---|---|---|---|---|---|
| 1 | `0x00416EE8` | `0x316F68` | `2CA900B1` | `2CA900BA` | `sltiu $t1,$a1,0x00B1` | `sltiu $t1,$a1,0x00BA` |
| 2 | `0x004170AC` | `0x31712C` | `240E003E` | `240E0040` | `addiu $t6,$zero,62` | `addiu $t6,$zero,64` |
| 3 | `0x004170E8` | `0x317168` | `25AD0003` | `25AD0002` | `addiu $t5,$t5,3` | `addiu $t5,$t5,2` |
| 4 | `0x004170F8` | `0x317178` | `25CD0002` | `25CD0003` | `addiu $t5,$t6,2` | `addiu $t5,$t6,3` |
| 5 | `0x004170FC` | `0x31717C` | `25CE0012` | `25CE0013` | `addiu $t6,$t6,18` | `addiu $t6,$t6,19` |
| 6 | `0x00417160` | `0x3171E0` | `2D0900B1` | `2D0900BA` | `sltiu $t1,$t0,0x00B1` | `sltiu $t1,$t0,0x00BA` |
| 7 | `0x0041751C` | `0x31759C` | `2D4B00B1` | `2D4B00BA` | `sltiu $t3,$t2,0x00B1` | `sltiu $t3,$t2,0x00BA` |
| 8 | `0x005656A4` | `0x465724` | `2D6C00B1` | `2D6C00BA` | `sltiu $t4,$t3,0x00B1` | `sltiu $t4,$t3,0x00BA` |

**⇒ 两版之间没有任何"另一条排版/绘制路径"。** 4 处是 DBCS **前导区间上界**（gate），
另 4 处**全在同一段函数（`0x4170A4..0x417134`，汉字槽位 → 图集 UV 的换算）**里，
是**图集几何常量**：

* `0x4170AC` = **图集每行格数 ncol**（62 → 64）。这与本地化工具自己登记的图集几何
  完全对上（`work\builds\GR_HASHR\audit\charset_meta.txt`）：
  `_expand_fa2400`：「图集 h 640→644 / **网格 62→64 列** / decode gate 0xB1..0xB5→0xBA」；
  `_expand_cap2400.atlas` = `{w:1024,h:644,ncol:64,nrow:37,cells:2368}`。
* `0x4170E8/0x4170F8/0x4170FC` = **行相位**：`row<12` 时是否做 `+3/+2` 行位移，
  以及 V 的起点 `+2/+3`、终点 `+18/+19`。

### 1.1 两条路径的 gate 语义（由此产生的**唯一功能性差别**）

`audit/k2_cave.txt`（解码 cave 全文，BASE 与 K2 只差 `0x416EE8` 那一个字节）：

```
0x416ED0  andi $a1,$a1,0x00FF     ; 当前字节
0x416ED4  sh   $a1,0($a0)         ; 先写"单字节码" 0x00??
0x416ED8  addiu $v0,$zero,1       ; 默认步长 1
0x416EDC  sltiu $t1,$a1,0xA1      ; < 0xA1 ⇒ 单字节
0x416EE8  sltiu $t1,$a1,0xB1/0xBA ; ★★ GATE：>= gate ⇒ 单字节（前导区间 = [0xA1,gate)）
0x416EF4  addiu $t8,$s7,-1
0x416EF8  slt   $t8,$s0,$t8       ; 还有下一字节？
0x416F08  lbu   $t3,1($t7)
0x416F0C  sltiu $t1,$t3,0xA1
0x416F18  sltiu $t1,$t3,0xFF
0x416F24  sll   $t4,$a1,8
0x416F28  or    $t4,$t4,$t3
0x416F2C  sh    $t4,0($a0)        ; 否则写打包值 (lead<<8)|trail
0x416F30  addiu $v0,$zero,2       ; 步长 2
0x416F34  sb    $v0,-1($a0)       ; ★ 步长写到 sp+221
```

* **A 线（gate 0xB1）**：前导区间 `[0xA1,0xB1)` ⇒ **`0xB1` 与 `0xB5` 是"单字节码"**
  ⇒ 解码结果恰好等于 `0x000000B1 / 0x000000B5` ⇒ **能命中引擎的「按键图标」特判**。
  而 DrawString 的 6 条比较 + CharWidth cave 的 2 条比较**已被汉化改成零扩展**
  （`240300B5 / 240300B1`，`audit/sites_orig_vs_base.txt` 第 22–45 行），
  与 `lhu $a1,222($sp)` 同一口径 ⇒ **确实命中**。
* **B 线（gate 0xBA）**：`0xB1/0xB5` 落进前导区间 ⇒ 只要后一字节 ∈ `[0xA1,0xFE)`
  就打包成 `0xB1xx ≥ 0xA1A1` ≠ `0x000000B1` ⇒ **该特判不可达**
  （唯一残余入口：串尾孤立的 `0xB1/0xB5`，或后随字节 `<0xA1`/`>=0xFF`）。

### 1.2 ★ 副包容量 2 被反复命中会怎样（用户点名的第 ②问）

`audit/base_addoneword.txt`（`0x219F50` 全文，BASE 与 K2 逐字节相同）：

```
0x219F50  addiu $sp,$sp,-64
0x219F6C  bne   $t0,$zero,+66 -> 0x21A078     ; ★ t0 != 0 ⇒ 走"副包"分支
--- 主包分支（t0 == 0）---
0x219F74  lw    $t9,40($s0)                   ; s0 = fontmgr；+0x28 = 主顶点包对象
0x219F7C  lw    $a1,68($s0)                   ; ★ a1 = 主包顶点计数（写入下标！）
0x219F84  jalr  [t9+0x1C]                     ; 加顶点（下标 = 计数）
0x219F8C  lw    $a1,68($s0) ; jal 0x515960    ; 设 UV
0x219F9C  lw    $t9,40($s0) ; …+0x24… jalr    ; 设颜色
0x219FB4  addiu $v1,$v1,1 ; sw $v1,68($s0)    ; 计数++
0x219FC0  sw    $v1,60($s0)                   ; +0x3C = 上次 flush 计数
0x219FCC  slti  $v1,$v1,1280                  ; ★★ 主包容量哨兵 = 1280
0x219FD0  bne   $v1,$zero,+104 -> 0x21A174    ; < 1280 ⇒ 直接返回
--- 满 ⇒ flush ---
0x219FD8  … jal 0x518DE0 ; … jal 0x519AC0 …   ; GIF 传输
0x21A010  lw $v0,104($s0) ; beq ⇒ 0x5172E0(…, s0+0x4C)   ; 副包也一起送
0x21A03C  lbu $v1,72($s0)                     ; ★★★ fontmgr+0x48
0x21A040  beq $v1,$zero,+76 -> 0x21A174       ; ★★★ == 0 ⇒ **不复位计数！**
0x21A048  sw $zero,68($s0)                    ; 主包计数 = 0
0x21A04C  jalr [[s0+0x28]+0x28]               ; 复位主包
0x21A05C  sw $zero,104($s0)                   ; 副包计数 = 0
0x21A060  jalr [[s0+0x4C]+0x28]               ; 复位副包
--- 副包分支（t0 != 0）---
0x21A078  lw    $t9,76($s0)                   ; ★ +0x4C = 副顶点包对象
0x21A080  lw    $a1,104($s0)                  ; ★ a1 = 副包顶点计数（写入下标！）
0x21A0B8  addiu $v1,$v1,1 ; sw $v1,104($s0)
0x21A0C4  sw    $v1,96($s0)
0x21A0D0  slti  $v1,$v1,2                     ; ★★ 副包容量哨兵 = 2
0x21A0D4  bne   $v1,$zero,+39 -> 0x21A174
--- 满 ⇒ flush（同上，含 0x21A140/0x21A144 的同一条件闸门）---
0x21A140  lbu $v1,72($s0)
0x21A144  beq $v1,$zero,+11 -> 0x21A174       ; ★★★ == 0 ⇒ 不复位
0x21A14C  sw $zero,68($s0) ; … ; 0x21A160 sw $zero,104($s0) ; 复位两个包
```

**算式（写入量 vs 容量）**

| 包 | 顶点写入下标 | 容量哨兵 | 哨兵检查时机 | 复位条件 | 缓冲实际大小 |
|---|---|---|---|---|---|
| 主包 `fontmgr+0x28` | `[fontmgr+0x44]`（计数） | `count < 1280` | **写入并 `count++` 之后** | `fontmgr+0x48 != 0` | 由类构造决定（本 ELF 内无容量常量，见 §5 未达成 U3） |
| 副包 `fontmgr+0x4C` | `[fontmgr+0x68]`（计数） | `count < 2` | **写入并 `count++` 之后** | `fontmgr+0x48 != 0` | 同上；**必须恰好能放 2 个顶点** |

**⇒ 机制（可写成一行）：**
每次 `AddOneWord(t0=1)`（= 命中图标特判）**只写 1 个顶点**，但因为它把副包计数推到 2，
**同时触发"主包 + 副包一起 flush 成 GIF 包"**。所以：

* **对渲染**：几乎每个图标字符都强制一次 GIF 传输 ⇒ 每帧 GIF 包数暴涨 ⇒ **帧率塌方**；
  若上层对包队列/链接有上限 ⇒ **包链错位 ⇒ 挂起**。这与用户实测
  「火箭筒后短暂 2fps、特效放完自恢复」完全吻合（爆炸瞬间 HUD 文本里出现一批
  `0xB1/0xB5`；放完就没了）。
* **对内存（真正的写坏候选）**：容量哨兵在**写入之后**才检查，且**复位以
  `fontmgr+0x48` 为条件**。只要在 `count` 已达容量的那一刻 `fontmgr+0x48 == 0`，
  计数**永不复位**，之后每次调用都写在下标 `≥ 容量` 处 ⇒ **顶点缓冲越界写** ⇒
  紧邻的堆块头（dlmalloc）被改坏。**这条路径与 gate 无关，两版共用同一份字节**
  ⇒ 是目前唯一能同时解释 A/B 两线的静态候选（见 §4 站点 #3）。

---

## 2. 汉字渲染链路的完整指令级走查

下面每一段都取自 **BASE ELF（`temp\BASE_ZH113b_SLUS_206.13.elf`）的真实字节**；
BASE 与 K2 的差别只在 §1 表里的 8 个字节。

### 2.1 `DrawString` `0x219A70`（每帧调用的主文本函数）

```
0x219A70  addiu $sp,$sp,-224
0x219A74  j 0x00565930        ; ★★ 汉化：原为 sd $ra,160(sp)
0x219A78  sq  $fp,144(sp)     ; ★★ 仍在盘上，但被拦截器的返回目标跳过（见 2.5）
0x219A7C..0x219A98  sq $s7..$s0
0x219AB0  pcpyld $s5,$a0,0    ; s5 = fontmgr（本函数的 this）
0x219AD0  s7 = v0 (= strlen(a1))          ; 0x219AC8 jal 0x406F28
0x219BC4  addu $v0,$s6,$s0                ; v0 = 串 + 游标
0x219BC8  lb   $a1,0($v0)                 ; 当前字节
0x219BCC  jal  0x00416ED0                 ; ★ 汉化：原为 jal 0x40BFC8 (wctomb 桩)
0x219BD0  addiu $a0,$sp,222               ; ★ 汉化：原为 sp+223（1 字节格）
0x219BD4  lhu  $a1,222($sp)               ; ★ 汉化：原为 lb $a1,223($sp)
0x219BD8  jal  0x0021AD10                 ; CharWidth
0x219BE4  lhu  $a1,222($sp)               ; 与 0x20 比较
0x219C08/0C14/…  与 0x00B5 / 0x00B1 比较（6 处，见站点表）
0x219C20..0x219C30  普通字形：a0=s3, a1=解码值, a2=sp+176,a3=sp+180,t0=sp+184,t1=sp+188
                    jal 0x0021ADE0 → j 0x00417050   ; ★ 汉化换成了自己的槽位→UV cave
0x219D40..0x219D58  AddOneWord(a0=s5, a1=sp+192, a2=sp+176, a3=s4, t0=0)   ; 主包
0x219D64..0x219D78  AddOneWord(…, t0=1)                                    ; ★ 副包（图标）
0x219DAC  lbu  $v0,221($sp)               ; ★ 汉化：取解码 cave 写下的步长
0x219DB0  addu $s0,$s0,$v0                ; ★ 汉化：s0 += 步长；原为 addiu $s0,1
0x219DB4  slt  $v1,$s0,$s7 ; bne ⇒ 循环
0x219DC0  ld   $ra,160($sp)
0x219DC4  lq   $fp,144(sp)                ; ★★ 每次都执行 —— 但 144(sp) 从未被写过
```

**每帧可达性**：`DrawString` 在 `.text` 内共 **37 个 `jal` 调用点**
（`audit/abi_fp_victims.txt`），覆盖 HUD/弹药/罗盘/队伍列表/任务文字等所有文本；
`0x219DAC` 的 `lbu` + `addu` 是 **译文串长度 → 字节游标** 的唯一推进方式，
所以**每次绘制汉字串都会执行**。

### 2.2 解码 cave `0x416ED0`（替换原 stub `0x416ED0`，原文是 `sub_416D28(6)` 桩）

见 §1.1 引用。要点：

* 输入：`a0` = 输出格地址（DrawString 给 `sp+222`），`a1` = `lb` 取出的**符号扩展字节**。
* 输出：`sh` 写 2 字节在 `0($a0)` / `sb` 写 1 字节步长在 `-1($a0)`。
* **步长恒 ∈ {1,2}**（`0x416ED8 addiu $v0,zero,1`；`0x416F30 addiu $v0,zero,2`）
  ⇒ **不会出现步长 0 的死循环**（这一条是排除项，已实测）。

### 2.3 CharWidth cave `0x416F40`（替换原 CharWidth 函数体）

```
0x416F40  srl   $t0,$a1,8                ; lead
0x416F44  bne   $t0,$zero,+17 -> 0x416F8C  ; 对偶码 → 0x416F8C
--- 单字节路径 ---
0x416F4C  andi  $t3,$a1,0x00FF
0x416F50/54  t3 == 0x20 ?  → 0x41701C（宽度 = [a0+0x14]）
0x416F5C/60  t3 == 0xB5 ?  → 0x417028（★ 硬编码宽度 20）
0x416F68/6C  t3 == 0xB1 ?  → 0x417028（★ 硬编码宽度 20）
0x416F74  lw $a2,40($a0)                 ; a2 = 图集/记录表对象
0x416F78  lb $v1,32($a2)                 ; base 字符
0x416F7C  subu $t0,$t3,$v1 ; andi $t0,$t0,0xFF
0x416F84  beq $zero,$zero,+30 -> 0x417000 ; 无条件跳
--- 对偶码路径 ---
0x416F8C  andi $t1,$t0,0x00FF            ; = lead
0x416F90  addiu $t1,$t1,-161
0x416F94  andi $t2,$a1,0x00FF            ; = trail
0x416F98  addiu $t2,$t2,-161
0x416F9C  addiu $t6,$zero,94 (0x5E)      ; ★ trail 区间长度 = 0xFF-0xA1 = 94
0x416FA0  mult  $t1,$t6                  ; ★★ 乘积从未被读（见 §5 U1）
0x416FA4  addu  $t0,$t0,$t2
0x416FA8  addiu $t0,$t0,224 (0xE0)
0x416FAC  lw $a2,40($a0) ; 0x416FB0 lw $v1,68($a2)   ; count
0x416FB4  sltu $v0,$t0,$v1 ; bne ⇒ 0x416FC8
0x416FBC  addiu $v0,$zero,16 ; 0x416FC0 beq ⇒ 0x41702C   ; 越界 ⇒ 返回 16（安全）
0x416FC8  lw $a2,56($a2)                 ; 记录表 [obj+0x38]
0x416FCC  sll $v0,$t0,2 ; addu ; sll 1   ; ★ 步长 = 20 字节
0x416FD8  addu $v0,$v0,$a2 ; 0x416FDC lbu $v0,1($v0)  ; 记录 +1 = 字宽
0x416FE0.. mul.s + jal 0x118EE0（取整）⇒ 0x41702C 返回
0x417000  lw $v1,68($a2) ; sltu ; bne ⇒ 0x416FC8 / 越界时 addiu $t0,zero,0
0x41701C  lw $v0,20($a0)                 ; 空格宽度
0x417028  addiu $v0,$zero,20             ; ★ 图标宽度 = 20
0x41702C  ld $ra,0($sp) ; jr $ra ; addiu $sp,$sp,16
```

**⇒ CharWidth 的每次调用都会走这里**（`0x21AD18` 的原始函数体已被替换成 `j 0x416F40`，
原文残留 `0x21AD20..0x21ADD8` 成为**死代码**，`audit/reach_cw_body.txt` 实测 0 条外部入口）。

### 2.4 槽位 → UV：`0x417038` / 入口 `0x417050`（替换 `0x21ADE0` 的函数头）

```
0x417050  lw   $t2,40($a0)               ; t2 = [obj+0x28] = 图集/记录表对象
0x417054  andi $v1,$a1,0x00FF            ; trail
0x417058  srl  $t4,$a1,8                 ; lead
0x41705C  bne  $t4,$zero,+6 -> 0x417078  ; 对偶码
0x417064  lb   $a1,32($t2) ; subu ; andi ; beq ⇒ 0x417098   ; 单字节：index = byte - base
--- 对偶码 ---
0x417078  andi $t4,$t4,0x00FF
0x41707C  addiu $t4,$t4,-161             ; lead - 0xA1
0x417080  andi $t5,$v1,0x00FF
0x417084  addiu $t5,$t5,-161             ; trail - 0xA1
0x417088  addiu $t6,$zero,94             ; ★ trail 区间 = 94
0x41708C  mult  $t4,$t6                  ; ★★ 乘积从未被读（见 §5 U1）
0x417090  addu  $t4,$t4,$t5
0x417094  addiu $a1,$t4,224 (0xE0)
0x417098  lw   $v1,68($t2)               ; 记录表条数 count
0x41709C  sltu $v0,$a1,$v1
0x4170A0  bne  $v0,$zero,+36 -> 0x417134 ; ★ index < count ⇒ 用记录表
--- 网格回退路径（index >= count）---
0x4170A8  addiu $t4,$a1,-224             ; slot
0x4170AC  addiu $t6,$zero,62 / 64        ; ★★ 图集每行格数（本报告 §1 差异 #2）
0x4170B0  div   $t4,$t6
0x4170B4  mflo  $t5                      ; row
0x4170B8  mult  $t5,$t6 ; mflo $t6 ; subu $t4,$t4,$t6   ; col = slot % ncol
0x4170C4  addiu $t7,$zero,16 ; mult ; mflo $t6
0x4170D0  addiu $a1,$t6,0                ; ★ U0 = 16*col（无行相位）
0x4170D4  addiu $t4,$t6,16               ; U1 = U0+16
0x4170D8  addiu $t7,$zero,12 ; slt ; bne ⇒ 0x4170EC
0x4170E8  addiu $t5,$t5,3 / 2            ; ★★ 差异 #3：row>=12 的行位移
0x4170EC  addiu $t7,$zero,16 ; mult ; mflo $t6
0x4170F8  addiu $t5,$t6,2 / 3            ; ★★ 差异 #4：V0
0x4170FC  addiu $t6,$t6,18 / 19          ; ★★ 差异 #5：V1
0x417100..0x417130  4 个 float 写到 a2/a3/t0/t1（调用者给的栈格），jr $ra
--- index < count ⇒ 记录表路径 ---
0x417134  lw  $t2,56($t2)                ; 记录表基址 [obj+0x38]
0x417138  j   0x0021AE20                 ; 回到引擎原有的读取代码
```

引擎原有的 `0x21AE20`（**原盘 ELF 里就有**，`audit/` 未收但可用
`de_dis.py <orig> dis 0x21AE20 0x21AF30` 复现）：

```
0x21AE20  sll  $v1,$a1,2 ; addu $v1,$v1,$a1 ; sll $v1,$v1,1   ; ★ a1*10 ⇒ 20 字节/条
0x21AE2C  addu $a1,$v1,$t2
0x21AE30  lhu  $a1,2($a1)  → cvt → swc1 f0,0($a2)     ; U0
0x21AE70  lhu  $a1,4($a1)  → …        → swc1 f0,0($a3) ; V0
0x21AEB0  lhu  $a1,6($a1)  → …        → swc1 f0,0($t0) ; U1
0x21AEF0  lhu  $v1,8($v1)  → …        → swc1 f0,0($t1) ; V1
```

**⇒ 20 字节记录步长得到双路印证**（cave 里的 `sll/addu/sll` 与引擎原文的
`sll/addu/sll` 完全同构）。

### 2.5 DrawString 拦截器 `0x565930`（用户点名的 ABI 违例）

```
0x565930  sw $t0,16($sp) ; sw $t1,20($sp) ; sw $t2,24($sp) ; sw $v0,28($sp)
0x565940  lui  $t0,0x002C ; addiu $t0,$t0,-32000 (0x8300)   ; t0 = 0x2B8300
0x565948  subu $t0,$ra,$t0
0x56594C  sltiu $v0,$t0,12736 (0x31C0)   ; ra ∈ [0x2B8300,0x2BB4C0) ?
0x565950  beq  $v0,$zero,+15 -> 0x565990 ; 不在该区间 ⇒ 直接返回
0x565958  addu $t1,$a1,$zero
0x56595C  lbu  $t2,0($t1)                ; 扫串
0x565968  sltiu $v0,$t2,0xA1
0x56596C  beq  $v0,$zero,+3 -> 0x56597C  ; ★ 遇到第一个 >= 0xA1 的字节 ⇒ 加行高
0x565974  addiu $t1,$t1,1 ; j 0x56595C
0x56597C  swc1 $f0,32($sp) ; lui $t0,0x4090 (4.5f) ; mtc1 ; add.s $f13,$f13,f0
0x56598C  lwc1 $f0,32($sp)
0x565990  lw $t0,16($sp) ; lw $t1,20($sp) ; lw $t2,24($sp) ; lw $v0,28($sp)
0x5659A0  sd   $ra,160($sp)              ; ★ 补回被替换掉的 sd $ra,160(sp)
0x5659A4  j    0x00219A7C                ; ★★★ 直接跳到 0x219A7C，**永久跳过 0x219A78 sq $fp,144(sp)**
0x5659A8  nop
```

**⇒ 后果（ABI 违例，逐字可证）：**
`DrawString` 的尾声 `0x219DC4 lq $fp,144(sp)` **每次都执行**，而 `144(sp)` 这一格
**从未被写过**（写它的指令就是被跳过的 `0x219A78`）
⇒ **`DrawString` 返回时把调用者的 `$fp`(s8) 换成未初始化栈槽的内容**。

**受害者的严格判定**（工具 `de_abi_fp3.py`，活跃性分析：调用后再写 `$fp` 即视为"被修好"）：

```
# 目标 ['0x00219A70'] ；调用点 37 个
--- 函数 @ 0x002B82F0（含调用点 0x2BA250 … 0x2BB404，共 20 个）---
      0x002B8308  sq $fp,128($sp)   W  ⇒ 破坏被修好
      0x002BA52C  jal 0x00219A70    CALL(杀掉 $fp)
      0x002BA5C0  pcpyld $a0,$fp,$zero   ★★ 受害者：读被杀掉的 $fp
--- 函数 @ 0x002DDCF8（含调用点 0x2DE708, 0x2DE798, 0x2DE804, 0x2DE9B0, 0x2DEA40, 0x2DEAA8）---
      0x002DE804  jal 0x00219A70    CALL(杀掉 $fp)
      0x002DE874  lw $fp,512($sp)   W  ⇒ 破坏被修好（编译器溢出重载把值修回来了）
      0x002DE878  addiu $a0,$fp,48  ★★ 表面受害者（实为良性，已被重载修好）
```

**⇒ 严格判定后只剩 1 个真受害者：`0x2BA5C0`。** 它的形态极其危险：

```
0x2BA52C  jal 0x219A70            ; DrawString #5（clobber $fp）
0x2BA540  lui $at,0x005E
0x2BA544  lw  $v0,28888($at)      ; v0 = [0x5E70D8]
0x2BA548  pcpyld $fp,$v0,$zero    ; ★ fp = [0x5E70D8]
0x2BA5C0  pcpyld $a0,$fp,$zero    ; ★ a0 = fp
0x2BA5C4  addiu $t0,$sp,160
0x2BA5E0  jal 0x219A70            ; ★★ 用 fp 当 this 再调 DrawString
```

**这条路径是"文件顺序 vs 实际控制流"的问题**：`0x2BA548` 在直线序里位于
`0x2BA5C0` **之前**，会把 `fp` 重新赋成 `[0x5E70D8]`（该全局就是字体管理器）。
⇒ **按直线序它不构成受害者**；只有存在一条**绕过 `0x2BA540` 而到达 `0x2BA5C0` 的**
控制流时才会把垃圾 `fp` 当 `this` 用（那会让 `AddOneWord` 用垃圾基址写顶点 ⇒
正是一个"野指针写入"）。**本轮未做完整 CFG 求解 ⇒ 记入未达成 U2。**

★ 但无论如何，**这条 ABI 违例已被排除为本次挂起的触发物**，理由见 §3.2。

### 2.6 `DrawLetters` `0x2164C0`（用户点名的 `+3 → +5`）

`audit/diff_orig_vs_base` 第 20 行：`0x00216578 1B A=addiu $a3,$s1,3  B=addiu $a3,$s1,5`。

```
0x2164C0  addiu $sp,$sp,-144
0x2164DC  lw $s0,56($a0)                  ; 表格记录基址
0x2164E0  lw $s1,60($a0)
0x2164F4  sb $zero,141($sp)               ; ★ sp+141 = 串尾 NUL
0x2164FC  v0 = 12 ; div $s2,$v0 ; mfhi    ; s2 % 12
0x216520  lw $s0,56($s3)                  ; 每 12 个换行：重置记录基址
0x216524  jal 0x21ACD0 (a0=[s3+152])      ; ★ 取"每行步进"（走 measure 路径）
0x21652C  addiu $v0,$v0,2 ; addu $s1,$s1,$v0
0x216540  addiu $v0,$s2,65 (0x41)         ; 'A' + s2
0x216544  sb   $v0,140($sp)               ; ★★ 写进 **sp+140 的 1 字节格**
0x216574  a2 = s0 + 7
0x216578  addiu $a3,$s1,5                 ; ★★ 汉化：原为 +3（行的 Y 偏移）
0x21657C  addiu $a1,$sp,140 (0x8C)        ; ★★ 串指针 = sp+140 ⇒ 实际只有 2 字节
0x216588  jal 0x219EB0 (a1=sp+140, a2=s0+7, a3=s1+5, t0=sp+112, t1=[s3+152])
0x21659C  addiu $s2,$s2,1
0x2165A0  slti  $v0,$s2,104
0x2165A4  bne   → 0x2164FC
0x2165A8  addiu $s0,$s0,20                ; ★ 表记录步长 = 20 字节
```

**判定**：`sp+140` 是 **2 字节**格（1 字符 + NUL），`s2 ∈ [0,104)` ⇒ `'A'+s2 ∈ [0x41,0xA9)`；
`sb $zero,141($sp)` 终止 ⇒ **写入量 2 字节 == 容量 2 字节，不越界** ✓。
`s2 ≥ 0x60` 时字节 `0xA1..0xA8` 会落进 DBCS 前导区间，但解码 cave 的
`s0 < len-1` 守卫使它们退化为**单字节** ⇒ 步长 1、不吞字节。
**`+3 → +5` 只是行的 Y 间距（渲染参数），与任何缓冲容量无关。** ⇒ **本条排除。**

### 2.7 `RSUIString::Substring` `0x540F60`（用户点名的 u16 截断）

```
0x540F60  addiu $sp,$sp,-128
0x540FAC  subu  $v1,$s2,$s3               ; v1 = end - start
0x540FB0  addiu $v0,$v1,1
0x540FB4  bgtz  $v0,+5 -> 0x540FCC
0x540FB8  addiu $a1,$zero,1
0x540FBC  sh $zero,0($s0) ; sb $zero,2($s0) ; sw $zero,4($s0)   ; 空串
0x540FCC  addiu $v0,$v1,2
0x540FD0  sb    $a1,2($s0)                ; refcount = 1
0x540FD4  sh    $v0,0($s0)                ; ★★ 长度按 **u16** 存：(end-start+2)
0x540FD8  jal 0x102CC0 (a0 = lhu 0(s0))   ; malloc(长度)
0x540FE0  sw    $v0,4($s0)                ; data
0x540FE4..0x540FF0  lw a0,[s0+4] ; lhu a2,[s0] ; jal 0x403AE8   ; memcpy(dst, ?, a2)
```

**判定**：读回的正是刚写的 u16 ⇒ 分配与拷贝**同一口径**
（`lhu` 截断后一致）⇒ **不会因为 16 位截断而越界**；只有长度 > 65533 才会不一致，
中文串远达不到。**本条排除（保留为"若将来出现超长串"的已知隐患）。**

### 2.8 汉化新增的"测量/排版"cave（`0x565660` / `0x565760` / `0x5657C8` / `0x56583C` / `0x417140`）

`audit/base_cave_C.txt` 全文。最关键的是 **`0x565670`（替换 `0x21AC90`，即
`RSFont::Measure` 的尾部）**：

```
0x565670  v0 = 0                ; 字节游标
0x565674  t1 = 0                ; n_dbc = 对偶字数
0x565678  t6 = s0 - 1           ; s0 = 字节长度
0x56567C  t2 = (v0 < t6) ; beq ⇒ 0x565700
0x565688  t3 = s2 + v0          ; s2 = 串基址
0x56568C  t3 = lbu [t3]
0x565690  sltiu t4,t3,0xA1 ; bne ⇒ 0x5656F0（单字节 ⇒ v0 += 1）
0x5656A4  sltiu t4,t3,0xB1/0xBA ; ★★ 第 4 个 GATE（= §1 差异 #8）
0x5656A8  beq  t4,zero,0x5656F0
0x5656B0..0x5656D4  下一字节判定（[0xA1,0xFF) 才算 trail）
0x5656DC  addiu t1,t1,1          ; n_dbc++
0x5656E0  addiu v0,v0,2          ; i += 2
0x5656F0  addiu v0,v0,1
0x565700  subu  t6,t6,t1         ; ★★ t6 = (len-1) - n_dbc  = 字形数 - 1
0x565704  lw    t7,24(s3)
0x565708  mult  t6,t7 ; mflo t7
0x565710  addu  s1,s1,t7         ; 排版宽度 += (字形数-1) × 字距
0x565714  addu  $v0,$s1,$zero
0x565718  j     0x0021ACA4
```

**⇒ 这就是"字形数 vs 字节数"的口径公式：**

```
字形数(glyphs) = 字节长度 L − 对偶数 D          （D = 满足 lead∈[0xA1,gate) 且 trail∈[0xA1,0xFF) 的 (i,i+1) 对数）
排版推进项     = (字形数 − 1) × [font+0x18]      ← 原盘是 (L−1) × [font+0x18]（且 mult 结果被丢）
```

`0x417150`（替换 `0x21AC74`，即 Measure 的**逐字宽度循环**）也做了对称改造：
`0x4171AC addiu $s4,$s4,2`（对偶字前进 2 字节）／`0x4171B8/0x4171C0` 单字节分支走回
`0x21AC7C` 的 `s4 += 1`。**⇒ 测量侧与绘制侧（`0x219DB0 addu $s0,$s0,$v0`）口径一致。**

### 2.9 汉化自己加的"容量钳位"（反证：作者当时也在打容量问题）

```
0x417600  addiu $sp,$sp,-24 ; sd $ra,0($sp) ; sd $a0,8($sp) ; sd $a1,16($sp)
0x417610  lw    $t9,152($a0)
0x417614  beq   $t9,$zero,+8 -> 0x417638
0x417620  addiu $v0,$zero,16
0x417630  slt   $t3,$v0,$a1
0x417634  movz  $a1,$v0,$t3               ; ★ a1 = min(a1, 16)
0x417638  lw    $a0,8($sp) ; addu $v0,$a1,$zero
0x417640  sw    $v0,248($a0)              ; ★★ [obj+0xF8] = 钳位后的值
0x417644  ld $ra,0($sp) ; jr $ra ; addiu $sp,$sp,24
```

* `0x21BD68`（原：`addiu $v0,zero,18 / sw $v0,248($s0)`）
  → `j 0x417680`，改为 `0x417600(s0, 18)` ⇒ **`[s0+0xF8]` 在 `[s0+0x98]!=0` 时被钳到 16**。
* `0x4176A0`：`addiu $v0,$zero,16 ; jr $ra` —— 把一个 `jal 0x21ACD0`（CharWidth）
  **换成了恒返回 16**（`0x21CB30 jal 0x004176A0`）。
* `0x2DE5A4`：`jal 0x0021ACD0` 被换成 `lui $v0,0x41A8 (21.0f) / mtc1 $v0,f1`
  ⇒ **把一个实测宽度换成了硬编码 21.0**。

**⇒ 结论**：`+0xF8` 是一个**被汉化当作"容量/上限"处理的字段**，且 `[obj+0x98]`
（字体对象指针）非 0 时才钳位。这三处说明作者**早就知道存在容量/上限压力**，
但它们的取值（16 / 21）都是**排版常量**，不改变任何缓冲大小。

---

## 3. §5 清单逐条判定

| # | §5 条目 | 每帧可达？ | 写入量 / 容量 算式 | 判定 |
|---|---|---|---|---|
| 1 | `AddOneWord` 主包 `slti 1280` | ✔ 每字符 1 次 | 写 1 顶点于下标 `count`；哨兵在 `count++` **之后** | **容量语义正确**（1280 = 可写下标 0..1279）；风险在复位条件（见 #3） |
| 2 | `AddOneWord` 副包 `slti 2` | ✔ 命中图标时 | 同上，容量 2 | **每次命中都强制 flush 两个包** ⇒ 帧率塌方（§1.2） |
| 3 | `fontmgr+0x48` 为 0 时复位被跳过 | 取决于标志 | `count` **无上界** ⇒ 下标 ≥ 容量 ⇒ **越界写** | ★★★ **最高优先：唯一"写入下标无上界"的静态站点，且与 gate 无关** |
| 4 | `DrawLetters` 表步长 20 × 104、12 列换行、`sp+0x8C` 2 字节格、`+3→+5` | ✔ 只在"字母测试页" | 写 2 字节 / 容量 2 字节 | **不越界**（§2.6）。`+3→+5` 是 Y 间距 |
| 5 | `DrawString` 拦截器跳过 `sq $fp,144(sp)` | ✔ 每次 DrawString | — | **ABI 违例成立**，但**已排除为本次触发物**（§3.2）；保留为潜在野指针源（§2.5，1 个真受害者） |
| 6 | `RSUIString::Substring` u16 截断 | 按需 | 分配与拷贝同读 `lhu` | **不越界**（§2.7） |
| 7 | `DrawString` 解码格 `sp+223` / `0x40BFC8` wctomb 桩 | ✔ | 2 字节格（`sp+222..223`）+ 步长 `sp+221` | **在 224 字节帧内，不越界**（§2.1）；原桩已被解码 cave 取代 |
| 8 | 汉字渲染链路的字形数/字节数口径 | ✔ | `字形数 = L − D`（§2.8） | **口径已转换且自洽**；`mult` 乘积被丢弃一事见 U1 |

### 3.1 逐条"写坏内存"判定的排序（见 §4 站点清单）

### 3.2 ★ 为什么把 `$fp` 违例**排除**为本次挂起的触发物

`TXT_02`（**同一份 ELF** + 英文文本）**实机不卡**。而 `$fp` 违例与文本内容无关：
`DrawString` 每次返回都会破坏 `$fp`，**英文串一样会触发**。
⇒ **若 `$fp` 违例足以造成挂起，`TXT_02` 也必然卡。它不卡 ⇒ `$fp` 不是触发物。**
（它仍是真实缺陷：`0x2BA5C0` 的形态是"拿 `$fp` 当字体管理器传给 DrawString"，
一旦那条控制流成立就是野指针写。⇒ 保留在修复集里当**加固**，不当根因。）

同理排除：`DrawLetters`、`Substring`、解码格（都与文本语言无关或已证不越界）。

**⇒ 剩下必须由"中文文本"打开的，只有两类：**
* **(a) gate 命中图标特判**（A 线成立；B 线几乎不可达）→ §1.2 的强制 flush。
* **(b) 顶点包计数器的复位闸门**（两线共用同一份字节）→ #3 的越界写。

这与用户的实测判据（`SENT_06` 在 A 线把"永久挂起"降级为"短暂 2fps"；
B 线另有其路）**同时吻合**：A 线 = (a)+(b) 双因，B 线 = 只剩 (b)。
`SENT_06` 关掉 (a) 后 A 线症状减轻但未消失（用户读数："降级为短暂 2fps、放完自恢复"
—— 也就是**不再永久挂起**，但仍有卡顿），正说明 **(b) 仍在**。

---

## 4. ★ 最可能"写坏内存"的站点清单（排序）

> 每条给：VA / ISO 偏移 / 函数 / 机制 / 为什么可能越界 / 如何验证
> ISO 偏移 = `VA − 0x6C780`（由 PT_LOAD off=0x80 / va=0x100000 推出）

### #1（最高）`0x21A040` / `0x21A144` —— 顶点包复位闸门 ⇒ 写入下标无上界

| 项 | 值 |
|---|---|
| VA / ISO | `0x0021A040` / `0x1AD8C0`；`0x0021A144` / `0x1AD9C4` |
| 原字 | `1060004C`（`beq $v1,$zero,+76`）/ `1060000B`（`beq $v1,$zero,+11`） |
| 函数 | `AddOneWord` `0x219F50`（主包 flush 尾 / 副包 flush 尾） |
| 机制 | `count` 在**写入之后**才与容量（1280 / 2）比较；满则 flush，flush 后**仅当 `fontmgr+0x48 != 0`** 才把 `count` 归零 |
| 为何能越界 | `fontmgr+0x48 == 0` 时 `count` 保持 ≥ 容量，下次调用把顶点写到下标 `count ≥ 容量` ⇒ **顶点缓冲越界写** ⇒ 相邻堆块头（dlmalloc）被改坏 |
| 与 gate 的关系 | **无关**（BASE 与 K2 逐字节相同）⇒ 可同时解释两条路径 |
| 如何验证 | ① 应用 `dfix_apply.py --set pkt`（2 个字，把复位改成无条件）后实机跑 A/B 两线；② 或在 PCSX2 断点 `0x21A048`/`0x21A04C` 记录 `[s0+0x44]`、`[s0+0x48]`、`[0x637AF0]` 的时序，看是否出现 `count ≥ 1280` 且 `+0x48 == 0`；③ 反查谁写 `fontmgr+0x48`（本轮未完成，见 U3） |

### #2（高）图标特判链 —— 副包容量 2 ⇒ 每 2 个图标强制 flush 双包

| 项 | 值 |
|---|---|
| VA / ISO | 12 处，见 `dfix_apply.py --list`；核心 7 处在 `0x219C08..0x219D38`，2 处在 `0x416F5C/0x416F68` |
| 函数 | `DrawString` `0x219A70` + `CharWidth cave` `0x416F40` |
| 机制 | 命中 ⇒ 走 `0x219C48..0x219C8C` 的硬编码 UV 块 + `0x219CB8..0x219CF8` 的硬编码字距（20.0f/11.0f）⇒ `0x219D64/0x219D68` 用 `t0=1` 调 `AddOneWord` ⇒ 副包 |
| 写入量 vs 容量 | 每次命中写 **1** 个副包顶点，容量 **2** ⇒ 第 2 个字符就触发 `0x219FD8..0x21A034` 的**双包 flush + GIF 传输** |
| 为何能写坏 | 直接后果是 GIF 包风暴（帧率）；**次级后果**是每次都走 #1 的复位闸门 ⇒ 把 #1 的窗口从"偶发"变成"每 2 个图标一次" |
| 如何验证 | `dfix_apply.py --set icon`（= SENT_06 同型补丁，A 线已实机证明能改变行为）；B 线用它做"图标路径是否真不可达"的判决实验 |

### #3（中）`0x41708C` / `0x416FA0` —— `mult` 之后没有 `mflo`，地址算式丢项

| 项 | 值 |
|---|---|
| VA / ISO | `0x00417088/8C/90/94`（F_UV）、`0x00416F9C/A0/A4/A8`（CharWidth cave） |
| 原字 | `240E005E` `018E6018` `018D6021` `258500E0` / `240E005E` `012E4018` `010A4021` `250800E0` |
| 机制 | 意图显然是 `slot = (lead−0xA1)×94 + (trail−0xA1)`（本地化工具登记的公式：`work\builds\GR_HASHR\audit\charset_meta.txt` → `"formula": "slot=(lead-0xA1)*94+(trail-0xA1)"`），但字面读**乘积从未被读**（`mult` 后直接 `addu`，HI/LO 无消费者） |
| 写入量 vs 容量 | 若字面成立：槽位只有 `(lead−0xA1)+(trail−0xA1) ∈ [0,117]` ⇒ `+0xE0` 后 ∈ `[224,341]`，**永远跨不过 lead 边界**；而 gate 把**前导空间**从 16×94=1504 扩到 25×94=2350（`_expand_fa2400`: `slot_space: 2350`）⇒ **容量口径跟着改了、地址口径没改** |
| 风险方向 | 这是**布局/寻址**缺陷，不是直接越界（两处都有 `sltu idx,count` 守卫）。但它是唯一"容量口径与地址口径不一致"的地方，且**两条线共用** |
| 为何只排第 3 | ★ 与本工程**既有实机取证矛盾**：`docs\REPORT_atlas_artifact.md` §3 记录「引擎口径图：grid 行 0..18 的抽样字，逐像素 **0 误差**命中在 `x = 16×col`」，该行还直接引用了 `0x4170C0 col = slot % 62` / `0x4170D0 U0 = 16*col` 这两条指令 ⇒ 说明 `slot` 就是登记值。**⇒ 静态推导与实机取证不一致，记为 U1，不得盲改** |
| 如何验证 | 见 `DISASM_TEST_GUIDE.md` 的探针 P3（`--set probe-slot`，**只在探针盘上用**） |

### #4（加固）`0x5659A4` —— DrawString 拦截器跳过 `sq $fp,144(sp)`

| 项 | 值 |
|---|---|
| VA / ISO | `0x005659A4` / `0x4F9224` |
| 原字 | `0808669F`（`j 0x00219A7C`）→ 新 `0808669E`（`j 0x00219A78`） |
| 机制 | §2.5；`0x219A78 sq $fp,144(sp)` 仍在盘上，只需要把返回目标往前挪 1 条 |
| 受害者 | 严格活跃性分析：37 个调用点里 **1 个真受害者**（`0x2BA5C0`，把 `$fp` 当字体管理器再调 DrawString）；另有 1 个表面受害者（`0x2DE878`，已被编译器的溢出重载修好） |
| 已排除为触发物 | §3.2（同 ELF + 英文文本不卡） |
| 如何验证 | 应用后实机对比（应与未应用无异，属"零风险加固"）；静态上可用 `de_abi_fp3.py` 复现判定 |

### #5（仅登记，不建议改）其它

| VA | 内容 | 判定 |
|---|---|---|
| `0x219C40` | `2403FFB5`（符号扩展）落在 `0x00B1` 命中的分流点上 | **惰性**：`$a1=0x00B1` 与 `0xFFFFFFB5` 恒不等 ⇒ 恒跳 `0x219C74`（即"B1 用第二套 UV"），改了不改变走向 |
| `0x21AD38/4C` | CharWidth 原文残留 | **死代码**（0 条外部入口） |
| `0x1FF8D0` / `0x2071B4` | `subu $v0,$v1,$v0` → `addiu $v0,$v1,-21 / -16` | 把**换行宽度**从变量改成硬编码常量（21 / 16 列）；只影响排版 |
| `0x2BEE5C..7C` | 6 个浮点常量被微调（0x4310→0x4306 等） | UI 坐标 |
| `0x2DE5A4` | `jal CharWidth` → 硬编码 `21.0f` | UI 宽度常量（§2.9） |
| `0x407078` / `0x408928` | 键码表查询加了 `sltiu at,$v1,128` 守卫 | **汉化主动加的越界防护**（说明作者知道 ≥0x80 会打坏表） |
| `0x519AC8` | `beq $a2,$v1,+84 → nop` | 在 `0x519AC0`（GIF 传输参数函数，被 `AddOneWord` 调用）内改了控制流；**未达成 U4：未追这条支路的下游后果** |

---

## 5. 未达成项（如实列出）

| 编号 | 未达成的内容 | 已做到哪一步 | 需要什么才能闭环 |
|---|---|---|---|
| **U1** | `0x41708C`/`0x416FA0` 的 `mult` 是否真的丢项 | 拿到了 12 份汉化 build 的同 6 个字（全部相同）；拿到了本地化工具登记的公式 `slot=(lead-0xA1)*94+(trail-0xA1)` | ★ 与 `docs\REPORT_atlas_artifact.md` §3 的"实机 0 误差"**矛盾** ⇒ 需要一支探针盘（改 `probe-slot` 后看字形是否**变错**；若变错 ⇒ 乘积确实生效，我的字面读法有误；若字形**变对** ⇒ 静态推导成立） |
| **U2** | `0x2BA5C0` 是否真的可达（绕过 `0x2BA540`） | 拿到完整函数反汇编与 `$fp` 活跃性 | 完整 CFG 求解（本轮的线性扫描不足以判定），或实机在 `0x2BA5C0` 下断点 |
| **U3** | 谁写 `fontmgr+0x48`；顶点缓冲的**实际容量**从哪来 | 找到 `+0x28/+0x4C/+0x44/+0x68` 的大量写点，但偏移在多类对象上同名，未收敛到 RSFontMgr 的构造器 | 用 Ghidra（`work\tools\ghidra`，项目 `GRLocEE.gpr` 已在）做类/虚表恢复，或按 `AddOneWord` 的 `[[s0+0x28]+0x1C]` 虚表槽反查类 |
| **U4** | `0x519AC8` 被 NOP 掉的分支的下游后果 | 已定位指令与所在函数（被 `AddOneWord` 调用） | 反汇编 `0x519AC0..0x519D00` 并追 `+84` 目标的语义 |
| **U5** | 未在真机 / 模拟器上验证任何修复 | **按要求全程没有跑模拟器，也没有写 ISO** | 盘重建完成后按 `DISASM_TEST_GUIDE.md` 逐候选实机验证 |
| **U6** | `DrawString` 的 `s7`（串长）与解码 cave 的 `s7` 是同一寄存器 | 已核对 `0x219AD0 s7 = v0(strlen)` 且 cave 内 `0x416EF4 addiu $t8,$s7,-1` 直接用它 | 无需额外工作；记录在此以便复核 |

---

## 6. 复现命令（每条结论都可重跑）

```powershell
cd work\builds\GR_DISASM

# 0) 列出所有块转储、确认含完整 ELF
python tools\ddump_scan.py

# 1) 取回两张盘的真 ELF（基底 gate 0xB1 / K2 gate 0xBA）
python tools\ddump_scan.py --extract 'GR_ZH113b (2026-10-15 18-47-05)' temp\BASE_ZH113b_SLUS_206.13.elf
python tools\ddump_scan.py --extract 'GR_FA2400_K2' temp\K2_SLUS_206.13.elf   # 写我自己目录，不动 GR_CSFIX
#    校验：temp\K2_SLUS_206.13.elf 应与 ..\GR_CSFIX\temp\K2_SLUS_206.13.elf 同 sha256（5cb59175…）

# 2) 两条路径的全部差异（8 个字节）
python tools\dediff_elf.py temp\BASE_ZH113b_SLUS_206.13.elf '..\GR_CSFIX\temp\K2_SLUS_206.13.elf'

# 3) 汉化相对原盘改了哪些站点
python tools\dediff_elf.py '..\..\..\third_party\orig\ps2\slus_out\SLUS_206.13' `
                          temp\BASE_ZH113b_SLUS_206.13.elf --json audit\diff_orig_vs_base.json
python tools\de_sites.py audit\diff_orig_vs_base.json

# 4) 关键函数逐条反汇编
python tools\de_dis.py temp\BASE_ZH113b_SLUS_206.13.elf dis 0x219A70 0x219E00   # DrawString
python tools\de_dis.py temp\BASE_ZH113b_SLUS_206.13.elf dis 0x219F50 0x21A190   # AddOneWord
python tools\de_dis.py temp\BASE_ZH113b_SLUS_206.13.elf dis 0x416ED0 0x4171C0   # 解码/宽度/槽位 cave
python tools\de_dis.py temp\BASE_ZH113b_SLUS_206.13.elf dis 0x565900 0x565AC0   # 拦截器
python tools\de_dis.py temp\BASE_ZH113b_SLUS_206.13.elf dis 0x2164C0 0x2165E0   # DrawLetters
python tools\de_dis.py temp\BASE_ZH113b_SLUS_206.13.elf dis 0x540F60 0x541010   # Substring

# 5) $fp ABI 违例的受害者判定
python tools\de_abi_fp3.py temp\BASE_ZH113b_SLUS_206.13.elf 0x219A70

# 6) 补丁脚本（检查 / 应用 / 自证）
python tools\dfix_apply.py --list
python tools\dfix_apply.py --elf temp\BASE_ZH113b_SLUS_206.13.elf --check --all12
python tools\dfix_apply.py --iso <盘.iso> --out <新盘.iso> --set icon+fp+pkt
```

**ISO 偏移换算**：`ISO 偏移 = VA − 0x6C780`；`ELF 文件偏移 = VA − 0xFFF80`
（由 `PT_LOAD off=0x80 / vaddr=0x100000`、ELF 头在 ISO `0x93800` 推出）。
例：`0x21A040 → ISO 0x1AD8C0 → ELF 0x11A0C0`。
