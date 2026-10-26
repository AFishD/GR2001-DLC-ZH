# ANALYSIS_ELF —— DLC (SLUS_208.20) ELF / 引擎能力分析

> 执行者：elf-analyst（task-2）· 2026-10-21
> 只读：ISO / ELF / PCSX2 转储与日志；所有写入只在 `docs/ANALYSIS_ELF*.md`、`tools/analysis/*`、`work/analysis/elf/`。
> 配套深度报告（移植蓝本 / JS19 / 补丁规格 v2）：**`docs/ANALYSIS_ELF_DBCS_PORT.md`**
> 工具：`tools/analysis/elf_probe.py`（通用探针）、`elf_port.py`（本体汉化差异）、`elf_js19.py`（JS19 取证）、
> `mipsasm.py`（轻量 MIPS 汇编 + 83 条已知字节自测）、`dbcs_spec.py`（规格生成 + 回读自证）
> 产物：`work/analysis/elf/`（大中间产物、反汇编 dump，gitignored）

---

## 0. 结论速览（先回答最关键的问题）

| # | 问题 | 结论（证据见对应章节） |
|---|---|---|
| **A** | **DLC 引擎能不能画双字节(DBCS)中文？** | **原生不能**（4 条硬证据，§4）。**但可以补**：用与本体汉化同款的方法在 ELF 里加 ~1 KB cave，**100% 必须 ELF 补丁，数据层无解**（单字节空间仅 224 码位，装不下 2300 对偶）。 |
| **B** | 2300 对偶 lead 闸门要打补丁吗？ | **不需要打任何"原生闸门"——DLC 原版根本没有闸门**。全 5,317,888 B `.text` 扫描：`sltiu` 立即数 = 0xA1 的仅 2 处且上下文无关，0xC0 邻域内 **0 个** `0xAE/0xB1/0xB5/0xBA` 闸门。lead 区间由**新增 decoder cave 自己定义**（v2 用 `0xA1..0xBA`，25 lead × 94 = 2350 槽）。 |
| **C** | 本体四件套崩溃修复 F4/F7/F7b/OOMFIX 要移植吗？ | **暂不移植（标记风险自担）**。DLC 的 dlmalloc 与本体是同一家族但**不同编译**：4 个原字节模式里 F4/F7 **0 命中**，F7b 的 `ld v1,8(v0)` 命中 2 处（`0x101F6C`/`0x1929E8`）、OOMFIX 的 `sw v0,4(s3)` 命中 24 处（都是泛型），**没有可字节平移的同构站点**；需重新逆向（DLC 分配器候选区 `0x101D00..0x102600`）。DBCS 主线优先。 |
| **D** | Game CRC | 原版 **`DE1E4DEE`**（PCSX2 口径 = 全 ELF u32 LE 异或；5,319,720 恰为 4 的倍数）。v2 DBCS 补丁后 **`FD9E6AED`**（`SLUS-20820 (FD9E6AED).01.p2s`）⇒ **旧即时存档/旧金手指失效，不可避免**。 |
| **E** | ELF 是否 stripped | **是**（`shnum=11`，`.symtab` size=0）；本体英文 ELF **有** `.symtab`（38,721 符号）可用，DLC 侧函数靠"本体符号指纹 + 字段偏移 + 调用图"定位，已全部定位。 |
| **F** | 是否有现成蓝本 | **有，且是实机验证过的**：① 本体汉化最终 ELF 的 DBCS cave（`0x416E00..0x417800` / `0x565600..0x565B00`）；② **JS_ZH19**（上一会话构筑，已从 PCSX2 cdvd 转储提取完整 ELF，CRC `3A320B22`）——但它是**半成品/反面教材**：几何/gate 用旧值、FONT.RES 尾部 off-by-22 导致 38s TLB Miss 崩溃（§7）。 |

---

## 1. 对象与方法

| 对象 | 路径 | 身份 |
|---|---|---|
| DLC ELF（原版） | DLC ISO @LBA **296**（ISO9660 root 里的 `SLUS_208.20`） | 5,319,720 B，sha256 `cf29cabe…baee7eee`，CRC `DE1E4DEE` |
| 本体英文 ELF | `…Locolization/third_party/orig/ps2/slus_out/SLUS_206.13` | 37,453,732 B，sha256 `5fec662f…cb94105`（**有符号表**，只读参考） |
| 本体汉化最终 ELF | `…Locolization/work/builds/FINAL/…(ZH_CN).iso` @LBA295 | 37,453,732 B，sha256 `a0c8499c…40ba12e`（**DBCS 补丁蓝本**） |
| JS_ZH19 ELF | `%LOCALAPPDATA%\PCSX2\cdvd-dump\JS_ZH19 (2026-10-21 16-19-47).dump` | 5,319,720 B，sha256 `80e25599…0594f6`，CRC `3A320B22`（= PCSX2 日志，提取正确） |

方法：
1. **ELF 解析**：`elf_probe.py` 直接解析 ELF32 头/程序头/节头，`VA↔file_off` 一律走 PT_LOAD 段表（不写死公式）。
   DLC：`file_off = VA − 0xFFF00`（PH[0] off=0x100, vaddr=0x100000, filesz=0x512900）。本体：`file_off = VA − 0xFFF80`。
2. **反汇编**：capstone `MIPS64+LE` + R5900 专有指令补丁（`lq/sq`、`pcpyld/pcpyud`、**三操作数 `mult rd,rs,rt`**）。
   > 实测：本体英文 ELF 里 `mult rd!=0` 有 **1198 处**（rd==0 的 264 处），ee-gcc 大量使用「积直接写 rd」的三操作数形式——本体工程旧文档「mult 乘积被丢弃」的结论是**错的**（详见 `ANALYSIS_ELF_DBCS_PORT.md` §3.2）。
3. **跨 ELF 对齐**：归一化指令键（R 型用 funct、其余用 opcode）滑窗匹配；本体符号表提供函数名与边界。
4. **数据取证**：从 PCSX2 cdvd 转储提取 JS19 的 ELF 与 payload；从 `emulog.txt` 取 TLB Miss 记录。
5. **规格自证**：`mipsasm.py` 汇编 cave → `dbcs_spec.py` 校验原字 → 内存打补丁 → 回读 → 输出补丁表与 CRC。

---

## 2. ELF 基础信息（DLC 原版）

```
size      5,319,720 B (0x512C28)
sha256    cf29cabeebb75fc8d9fdd1a076e4c574c5740e73948f0a2ef643b632baee7eee
md5       25047831eb6e4fd346f2b0ee7db911f1
e_type    2 (ET_EXEC)  e_machine 8 (MIPS)  e_flags 0x20924000  e_entry 0x00100008
phoff 0x34 (entsize 32, num 5)   shoff 0x512A70 (entsize 40, num 11)   shstrndx 1
symbols   0 (stripped)
```

程序头：

| # | type | off | vaddr | filesz | memsz | flags |
|---|---|---|---|---|---|---|
| 0 | PT_LOAD | `0x100` | `0x100000` | `0x512900` | `0x592700` | RWE |
| 1 | PT_LOAD | `0x512A00` | `0x1E00000` | 0 | `0x118400` | RWE |
| 2 | PT_LOAD | `0x512A00` | `0x692700` | 0 | `0xC7380` | RWE |
| 3 | PT_LOAD | `0x512A00` | `0x692700` | 0 | `0xD2000` | RWE |
| 4 | PT_LOAD | `0x512A00` | `0x764700` | 0 | 0 | RW |

节头：11 个——只有 1 个**装载节**（.text，off=0x100 / vaddr=0x100000 / size=0x512900），
其余是空的 `.strtab/.symtab`、`.shstrtab`(0x512A00, 0x2D B)、`.comment`(GCC 版本)、`.reginfo`。**无调试节、无 `.relmain`**。

- `.text` sha256 = `f77ac54f4ea26af97b65ee467264de5158975be45829e9d7222b39645389e287`
- `.text` 实际尾部（`0x612300..0x612900`）**不是零填充**：含 `GSFAIL/CHATALL/JOINNEW/IRCIP%d/…` 等调试/网络字符串表
  ⇒「把 cave 放 .text 末尾」的直觉方案**不可用**（v2 因此改用 `0x1808A8`，见 §9）。
- 内嵌可打印 ASCII 串（≥4B）：**17,722 条 / 117,880 B**；其中字体/UI 相关 534 条（筛选清单见 §8）。

---

## 3. 文本/字体栈函数定位（DLC，实证）

DLC 已 stripped，用 BASE-EN `.symtab` 的函数指纹 + 字段偏移 + 调用图定位（`file_off = VA − 0xFFF00`）：

| 功能 | DLC VA | file_off | 关键证据 |
|---|---|---|---|
| `RSFontMgr::DrawString` | `0x2195F0` | `0x1196F0` | 帧 0xE0；`jal strlen(0x16DE00)`；每字节 `lb` → `jal wctomb` → `jal CharWidth` → `jal UV` → `jal AddOneWord`；`addiu s5,s5,1` |
| `wctomb`（单字节桩） | `0x173678` | `0x173778` | `beqz a0; move v0,0; sb a1,(a0); addiu v0,1; jr ra`（全 .text 唯一调用点 `0x219758`） |
| `RSFont::CharWidth` | `0x21A360` | `0x11A460` | `lbu 0x24(a0)` 早退；`0xFFB5/0xFFB1`→20；`def=+0x28`；`idx*10`；`lbu rec+1`；`lwc1 [a0+0x1c]` |
| `RSFont::ComputeCharTextureCoords` | `0x21A210` | `0x11A310` | 叶子；`andi a1,0xFF`；`(c−[def+0x20])&0xFF`；`idx<count`；记录 +2/+4/+6/+8 u16→float |
| `RSFont::StringWidth` | `0x21A4C0` | `0x11A5C0` | `strlen`；逐字节 `jal CharWidth`；尾部 `(len−1)*[font+0x18]` |
| `RSFontMgr::AddOneWord` | `0x2193B0` | `0x1194B0` | 主包 `+0x44` / `slti 0x500`；副包 `+0x68` / `slti 2`（与本体同构） |
| `RSFont::CharHeight` | `0x2199A0` | `0x1199A0` | `lw v0,0x18(a0)` |
| `font+0x24` getter | `0x2199B0` | `0x1199B0` | `lbu v0,0x24(a0)` |
| `font+0xc` getter | `0x2199E0` | `0x1199E0` | `lw v0,0xc(a0)` |
| UV thunk | `0x2199D0` | `0x1199D0` | `a3=a2+4; t0=a2+8; t1=a2+0xC; j 0x21A210` |
| `strlen` | `0x16DE00` | `0x16DF00` | 与 BASE `strlen(0x406F28)` 归一化 100% 同构 |
| 字体管理器全局 | `[0x626950]` | — | `0x1FCC20` 返回该全局；`0x1FCC10` = map-lookup thunk（`j 0x1FCD00; a0+=4`） |

**字段偏移与本体逐项一致**（font+0x14/0x18/0x1c/0x24/0x28；def+0x20/0x38/0x44；FT 记录 10B：+1 宽度、+2/+4/+6/+8 = U0/V0/U1/V1）——这是「可移植」的根本依据。
但**代码生成不同**（本体 `pcpyld`+`sq` / DLC `move`+`sq`；DrawString 寄存器分配也不同：DLC s2=串基址、s5=游标、s7=长度）⇒ **必须重新汇编，不能字节平移**。

---

## 4. DBCS 支持定性：**原生不支持**（4 条硬证据）

### 证据 1：`wctomb` 是单字节桩（`0x173678`，5 insn）

```
beqz  a0, +3        ; if (dst == NULL) return 0
move  v0, zero
sb    a1, 0(a0)     ; 否则只写 1 字节
addiu v0, zero, 1
jr    ra
```
与本体英文 ELF 的 `wctomb(0x40BFC8)` 语义完全相同（单字节身份转换）。全 `.text` **唯一调用点** `0x219758`（在 DrawString 内）。

### 证据 2：DrawString 是逐字节循环

```
0x219750 addu v0,s2,s5        ; s2=串基址, s5=字节游标
0x219754 lb   a1,0(v0)        ; 带符号取 1 字节
0x219758 jal  wctomb          ; "转换"（实为写回同 1 字节）
0x219760 lb   a1,0xDF(sp)     ; 读回 1 字节
0x219764 jal  CharWidth
...
0x21994C addiu s5,s5,1        ; ★ 游标恒 +1 字节
0x219950 slt  v1,s5,s7
0x219954 bnez → 0x219750
```

### 证据 3：CharWidth / UV 都按单字节 + 224 条 FT 记录索引

- CharWidth（`0x21A360`）：`dsll32/dsra32` 符号扩展字节；`(c − [def+0x20]) & 0xFF` → `idx < count(224)`；记录 `idx*10`；`lbu rec+1` = 宽度。`0xFFB5/0xFFB1` 被当作**图标字节**特殊返回 20。
- UV（`0x21A210`）：`andi a1,0xFF`；`(c − base)&0xFF`；越界 **clamp 到记录 0**（**没有网格回退**）。记录 UV 在 +2/+4/+6/+8。
- 单字节码空间 = `code 0x20..0xFF` 共 **224 个** ⇒ 物理上装不下任何汉字集合。

### 证据 4：全 `.text`（5,317,888 B）无 DBCS 闸门

`elf_probe.py gate-scan`（`sltiu/slti`，立即数扫描 `0xA0..0xC0, 0xFE, 0xFF`）：

| 命中 | VA | file_off | 指令 | 判定 |
|---|---|---|---|---|
| 1 | `0x11EB90` | `0x01EC90` | `slti v0,a1,0xFF` | 与 DBCS 无关（普通范围判定） |
| 2 | `0x176850` | `0x076950` | `sltiu v0,v0,0xA1` | 上下文为 0x10 阈值判定，无关 |
| 3 | `0x349F54` | `0x24A054` | `sltiu at,a1,0xA1` | 函数 prologue 后无 trail 检查，无关 |
| — | — | — | `sltiu …,0xAE/0xB1/0xB5/0xBA/0xFF` | **0 处** |

⇒ DLC 原版**没有**「按字节阈值走双字节解码」的任何代码路径。**结论：DBCS 必须通过 ELF 补丁新增。**

### 补充：数据层无解

| 方案 | 可行性 |
|---|---|
| 单字节码 + 扩充 FT 记录 | 单字节仅 256 值（0x20..0xFF = 224 格），汉字集需 ≥1900 字 ⇒ **不可能** |
| 多 face 分摊（large/default/huge） | face 按字号选择、非按内容，UI 布局会串 ⇒ **不可行** |
| 改 FONT.RES 记录数 + 改 `def+0x44` | 最多把单字节码域扩到 256 仍不够；且 `CharWidth/UV` 用 `def+0x20 base char` 做减法，超出 0xFF 无路 |
| **⇒ 结论** | **必须 ELF 补丁**（decoder + CharWidth + UV + 测量/字距 + 步长），即本体汉化方案与 v2 规格 |

---

## 5. lead 区间闸门（2300 对偶）分析

### 5.1 DLC 原版：无闸门，也就无需"打原闸门补丁"

本体工程的 4 处 `sltiu` 闸门（`0x416EE8`/`0x417160`/`0x41751C`/`0x5656A4`，word 尾 `0x00BA`）**不是原版引擎代码**——它们全部落在**汉化新增的 cave 里**（cave 地址原本是游戏从不调用的 `sce*` libc 函数）。因此：
- DLC 侧没有"原生闸门"可打；`elf_patches.json → gates_readback` 的 4 站对 DLC **不适用**（既无原字也无地址对应）；
- **lead 区间 = 新增 decoder cave 里的立即数**。v2 规格用 `sltiu t1,a1,0xBA` ⇒ lead ∈ `[0xA1,0xBA)` = 25 个 lead，`slot=(lead−0xA1)*94+(trail−0xA1)` ∈ `[0,2350)`，与 charset 2300 对偶 + 50 空槽相容；
- trail 闸门：`sltiu …,0xFF` ⇒ trail ∈ `[0xA1,0xFF)` = 94。
- 若将来要扩到 26 lead（`0xA1..0xBA` 含 0xBA = 2350 槽），只需把 `.equ GATE_HI` 改成 `0xBB`（仍不碰任何原版字节）。

### 5.2 与 font-engineer 几何的对齐

font-engineer 定稿：`gate=0xBA, NCOL=64, CELL=16, Y0=3, SKIP_ROW=12, SKIP_ROWS=2, slot 0..2349`。
我从本体最终 ELF 反汇编核对，**三处立即数逐字相同**：`0x4170AC`（`addiu t6,zero,0x40` = NCOL 64）、
`0x4170E8`（`addiu t5,t5,2` = SKIP_ROWS 2）、`0x4170F8`（`addiu t5,t6,3` = Y0 3），另 `0x4170D8`（SKIP_ROW=12）、`0x4170B4`（`addiu t7,zero,0x10`=CELL 16）。
⇒ v2 cave 的 `.equ` 全部用这组值（见 `ANALYSIS_ELF_DBCS_PORT.md` §7.1）。

---

## 6. 本体四件套崩溃修复（F4/F7/F7b/OOMFIX）在 DLC 的命中情况

来源：`reference/base_zh146/scripts/elf_patches.json` 的 8 个 patch（四件套 + G2/G1b/F8a/F8b）。
方法：把每站「原 4 字节」在 DLC `.text` 精确搜索；再做上下文结构判定（dlmalloc 家族对齐）。

| patch | 原字 | 本体 VA | DLC 精确命中 | 结构判定 |
|---|---|---|---|---|
| F4 | `0x1459FFD1`（`bne v0,t9,-47`） | `0x102588` | **0** | DLC 有 20 处 `bne …,,-47` 但寄存器/偏移不同 |
| F7 | `0x1447FFEA`（`bne v0,a3,-22`） | `0x1021D4` | **0** | 同上 |
| F7b | `0xDC430008`（`ld v1,8(v0)`） | `0x102208` | 2 处：`0x101F6C`、`0x1929E8` | 都在 DLC 分配器候选区（`0x101D00..0x102600`），但周边指令序列不同 |
| OOMFIX | `0xAE620004`（`sw v0,4(s3)`） | `0x539174` | 24 处 | 泛型写，无一在解压器上下文 |
| G2 | `0xDC4B0008` | `0x1024D0` | 0 | — |
| G1b | `0xDCAA0008` | `0x101D10` | 0 | — |
| F8a | `0x10000004` | `0x403B40` | 936 处 | 泛型 `beq zero,zero,+4` |
| F8b | `0x2CC20008` | `0x403B50` | 11 处 | 泛型 `sltiu v0,a2,8` |

**DLC 分配器候选区**：`0x101D00..0x102600`（`ld rx,8(ry)` 密集、`chunk_free/chunk_alloc` 结构同构；
归一化序列匹配率仅 6–8% ⇒ 是**同一 dlmalloc 家族的不同编译**，不是可平移的同一份代码）。

**结论**：
- 四件套**无法按原字节/原偏移移植**；DLC 是否需要这类修复**未获证**（DLC 的中文文本量远小于本体、负载不同）；
- **建议：暂不移植（标记风险自担）**；DBCS 主线完成后，如果实测出现 malloc/解压相关的卡死/TLB，再对 `0x101D00..0x102600` + 解压器（`0x539000` 附近）做**定点逆向**，按 DLC 实际指令重写补丁（可复用 `elf_patches.json` 的**修复逻辑**，但需重新汇编）。
- 这符合 Lead 的优先级：DBCS 是主线，四件套是「有证据才做」。

---

## 7. Game CRC

工具：`elf_probe.py crc`（PCSX2 口径：整份 ELF 按 `<u32` 异或；与本体工程 `tools/final_fix/elf_crc.py` 同算法）。
ELF 5,319,720 B 恰为 4 的倍数，无尾字节。

| 状态 | Game CRC | 即时存档名 |
|---|---|---|
| **DLC 原版** | **`DE1E4DEE`** | `SLUS-20820 (DE1E4DEE).01.p2s` |
| **v2 DBCS 补丁后**（`dbcs_spec.py` 自证） | **`FD9E6AED`** | `SLUS-20820 (FD9E6AED).01.p2s` |

- 校验方法：任意改动 ELF 任一字节 → CRC 变；`dbcs_spec.py` 输出补丁后 sha256 `ae25d48d…b9f7d334`。
- **风险（不可避免）**：CRC 变 ⇒ PCSX2 即时存档目录/文件名变、旧金手指/旧存档不通用；发布说明必须写清「请新开档」。
- 参考：本体工程交付 CRC `653FBF69`；JS_ZH19 CRC `3A320B22`（用于验证转储提取正确性）。

---

## 8. 内嵌字符串（与 UI/字体相关的精选）

总数 17,722 条（≥4B）；字体/UI 相关 534 条。**这些字符串被文本渲染路径显示，汉化时需确认是否也要翻译**（尤其 `PS2_PRESS_START` 等菜单提示）：

| VA | file_off | 字符串 | 说明 |
|---|---|---|---|
| `0x57E570` | `0x47E670` | `PS2_PRESS_START` | 标题画面提示 |
| `0x57E5C0` | `0x47E6C0` | `PS2_CHOOSE_PROFILE` | 选档提示 |
| `0x57E600` | `0x47E700` | `PS2_TE` | 提示（被截断/短串） |
| `0x57E610` | `0x47E710` | `PS2_QUICK_MISSION_NEWORLOAD` | 快速任务菜单 |
| `0x57E630` | `0x47E730` | `PS2_MULTI_SPLITSCREEN` | 多人分屏 |
| `0x57E658` | `0x47E758` | `ONLINEMENU` | 在线菜单 |
| `0x57E668` | `0x47E768` | `<ERROR>` | 错误提示 |
| `0x57D950/57D970` | `0x47DA50/70` | `Memory allocation failure` | 内存分配失败提示（两个副本） |
| `0x57F8B0` | `0x47F9B0` | `\MENU.IMG;1` | 资源路径 |
| `0x57F8C0` | `0x47F9C0` | `host0:q:\ike\menu.img` | 开发期路径（不显示） |
| `0x57E478` 区 | — | `ps2_press_start` 等被 `PS2_` 系列覆盖 | 见 `work/analysis/elf/dlc_info.json` 与 `elf_probe.py strings --font` 输出 |

补充观察：
- ELF 里存在 `std::basic_istream<wchar_t,…>`、`std::codecvt<wchar_t,char,int>` 等 **wide-char C++ 运行库**符号串——说明运行时 **C++ 标准库有 wchar 设施**，但**游戏文本渲染器不消费**（§4 证据链）⇒ 不能"用 wide 字符串直接画"。
- 路径/调试/网络类字符串（`save\game`、`IRCIP`、`assertion …`）不显示，**不需要翻译**；本清单只列玩家可见提示。

---

## 9. 补丁方案摘要（v2，详规见 `ANALYSIS_ELF_DBCS_PORT.md` §7）

**必须 ELF 补丁**。v2 规格（`tools/analysis/dbcs_spec.py` 生成 + 自证）：

- **cave**：`0x1808A8..0x180C90`，**1000 B / 250 条指令**，源码 `tools/analysis/caves/dbcs_cave_dlc.s`；
  分块：decoder(27) / draw_advance(4) / charwidth(61) / uv(57) / measure(26) / sw_tail(32)。
- **cave 落点依据**：原 ELF 该段是**死代码**（`jump_in=0 / lui_addiu=0 / raw_ptr=0`），且 **JS_ZH19 已整段覆盖并实机运行 100 s+ 无异常**（emulog 佐证）。
- **25 站补丁**（VA / file_off / 原 4B / 新 4B 全表见 PORT 文档 §7.3）：
  - DrawString：`jal wctomb`→decoder、解码格 1B→2B、4 处 `lb`→`lhu`、8 处图标常量零扩展、游标步长→cave；
  - CharWidth：函数体→cave（**保留原版 `font+0x24` 早退** + **def==NULL 兜底**）；
  - UV：函数头→cave（单字节回原记录路径；对偶网格 `NCOL=64/CELL=16/Y0=3/SKIP_ROW=12/SKIP_ROWS=2`）；
  - StringWidth：循环→DBCS 逐字；尾部字距→按**字形数**（JS19 漏了这一步）。
- **结果**：补丁后 `sha256 ae25d48d…`、**CRC `FD9E6AED`**；原字 24/24 校验通过、全量回读 PASS。
- **几何参数化**：`GATE_HI/NCOL/CELL/Y0/SKIP_ROW/SKIP_ROWS/PAIR_BASE` 全在 `.s` 顶部 `.equ`，改几何只改常数重汇编（不需要 mini 汇编之外的工具链）。
- **不做的事**：不改 DLC ELF 文件本身（Lead 集成 build 链）；v2 不含 UI wrap/折行 cave（`0x21B780` 等，JS19 有，v3 可选）；不含四件套。

**风险清单**（详见 PORT 文档 §9）：实机验证缺失（必须跑）；cave 余量仅 8 B（v3 扩展需再评估死函数边界）；`font+0x24` 已澄清（= FONT.RES style 块 u8，DLC/本体/本体中文成品盘全体为 0，固定宽度早退不触发，映射见 PORT §7.5）；`def+0x44=224` 假设需与 FONT.RES 一致（v2 的 `PAIR_BASE=224` 与此绑定）；长段落折行/图标/字幕行距需实机回归。

---

## 10. 与 JS_ZH19（上一会话构筑）的关系与教训

`work/analysis/elf/js19_report.txt`（`elf_js19.py all`）完整取证。要点：

1. **同源**：JS19 decoder 与本体汉化 cave **27/27 逐指令同构（100%）**、CharWidth 82% ⇒ 它就是本体汉化 DBCS cave 的 DLC 移植，**方法论已验证**。
2. **半成品（2026-10-21 晚修正口径）**：几何 NCOL=62/CW=8/CH=16/Y0=2/SKIP_ROWS=3、gate 0xAE（13 lead≈1222 槽）经 js19-recovery 的图集 OCR **实测验证自洽**（真 pair 14,455、lead 仅 A1..AD；全图 1209/1283 有墨格 xor==0），其数据层已完整还原 **2,275 条中文译文 / 22,594 汉字**；JS19 未 patch StringWidth 尾部字距（行宽偏大）与 rect `u0` 漏 +2（字形左移 2px）是其视觉缺陷，不是几何错误。
3. **崩溃根因（双向实证）**：其 FONT.RES 尾部样式表 **count=15 vs 实际 16 条、第 8 条被截断 22 B**（展开 7488 = 7466+22）⇒ 顺序解析漂移、字体/样式结构损坏 ⇒ 垃圾字体指针；叠加其 cave **删掉 `font+0x24` 早退、无 def==NULL 兜底** ⇒ 38 s 起 50 条 TLB Miss（`0x1809B8 addr=0x44`=def NULL；`0x18097C addr=0x20`=a0=-8；`0x208F30 addr=0x24`=a0=-4，连**原版 getter** 都被波及）。
4. **v2 的修正**：恢复 +0x24 早退、加 NULL 兜底、几何/gate 换本工程定稿值（64/16/3/12/2、gate 0xBA）、补 StringWidth 尾部。

---

## 11. 复现与产物索引

| 产物 | 路径 |
|---|---|
| 主报告 | `docs/ANALYSIS_ELF.md`（本文件） |
| 移植蓝本 / JS19 / 规格 v2 深度报告 | `docs/ANALYSIS_ELF_DBCS_PORT.md` |
| 通用探针 | `tools/analysis/elf_probe.py` |
| 本体汉化差异工具 | `tools/analysis/elf_port.py` |
| JS19 取证工具 | `tools/analysis/elf_js19.py` |
| 轻量 MIPS 汇编器 | `tools/analysis/mipsasm.py`（`--selftest`：83 条已知字节） |
| 补丁规格生成器 | `tools/analysis/dbcs_spec.py` |
| cave 源码 | `tools/analysis/caves/dbcs_cave_dlc.s` |
| DLC info/CRC/strings/gate-scan | `work/analysis/elf/dlc_info.json`、`dlc_gate_scan.json` |
| BASE 差异/重定向/cave dump | `work/analysis/elf/zh_diff.{txt,json}`、`zh_redirects.txt`、`zh_caves.txt`、`zh_cave_core_*.txt` |
| DLC 字体栈函数 dump | `work/analysis/elf/dlc_*.txt` |
| JS19 报告/JSON | `work/analysis/elf/js19_report.txt`、`js19_analysis.json`、`js19_cave_0x1808A8.txt` |
| **v2 规格** | `work/analysis/elf/dbcs_spec_dlc.{json,txt}`、`dbcs_cave_dlc.bin`、`DLC_SLUS_208.20_DBCS_v2.elf` |

```powershell
$py = "C:\Users\84363\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
$env:PYTHONIOENCODING="utf-8"
& $py tools\analysis\mipsasm.py --selftest
& $py tools\analysis\elf_probe.py info
& $py tools\analysis\elf_probe.py crc
& $py tools\analysis\elf_probe.py gate-scan --imm "0xA1,0xAE,0xB1,0xB5,0xBA,0xFF,0xFE" --ops sltiu,slti --ctx 3
& $py tools\analysis\elf_probe.py strings --font --min 5
& $py tools\analysis\elf_port.py extract
& $py tools\analysis\elf_port.py diff
& $py tools\analysis\elf_port.py redirects
& $py tools\analysis\elf_port.py caves --out work\analysis\elf\zh_caves.txt
& $py tools\analysis\elf_js19.py all
& $py tools\analysis\dbcs_spec.py
```

---

## 12. v3 渲染修复：大字/标题垂直拉伸裁剪的根因与补丁（2026-10-21 晚实机定位）

**症状**（`work\analysis\emu\all_test\alltest_native_130s.png` / `_330s.png`）：存档页标题「档案」字形被竖向拉伸约 2.7×、顶部贴面板边/被裁；正文（`文件名：`、`- 空插槽 -`、按钮行、底部说明）正常。
**结论：不是 cave 的问题，是 FONT.RES 数据不一致** —— FT 记录已全部改成 16px 高，但 face 头的「字体高度」字段没跟着改。

### 12.1 引擎的绘制数学（DLC 反汇编实证）

| 环节 | 实证 |
|---|---|
| 字体高度 | `f21 = round(def+0x0C × font+0x20)`：`0x21A440`（getter，固定宽度字体则返回 font+0x10）；`def+0x0C` = **FONT.RES face 头 fld[1]**（getter `0x21A4B0` 读 `[font+0x28]+0xC`）；`font+0x20` = style 块 p20 高度缩放（getter `0x21A4A0`） |
| 字形 quad | `x..x+CharWidth`、**`y..y+f21`**；UV `(u0,v0,u1,v1)` 线性映射进 quad；普通字形**没有**额外 y 偏移（只有图标 `0xFFB5/0xFFB1` 特判：`y += f21/2 − 11`，quad 高 20） |
| 竖向布局 | `0x21A440` 另有 **19 个调用者**做竖向居中/行距（例 `0x21C6A4`: `y = y_off + (boxH − f21)/2`）⇒ **fld[1] 同时决定“字形高度”和“排版高度”** |

### 12.2 数据侧实测（`work\builds\JS_ZH_all_test.iso`）

| 项 | 实测 |
|---|---|
| FT 记录 | **所有 face 的记录都已被重写为 16px 高**：ASCII = 8×16 连续带（全字宽 8）、中文 pair = 16×16；`dlc_en` 原版是 26/26/42 px 高 |
| face 头 fld[1] | large=**26**、default=**26**、huge=**16**（原版 26/26/42）⇒ **large/default 的字体高度与实际字图不一致** |
| 结果 | large/default 面：quad = 26×p20；huge 面：quad = 16×p20。普通样式 p20=1.0 ⇒ huge 面 16px 1:1（所以正文正常）；**标题用 large/default + style #5（p20=1.64）⇒ f21 = 26×1.64 = 42.6** |
| 像素验证 | 标题「档案」ink 高 **38.6px**，图集 16px 字形 ink≈14.5 ⇒ 拉伸 **2.66×** = 42.6/16 ✓（与“large/default + p20 1.64”完全吻合）；EN 原盘同位置 “Profiles” ink 21.7px（26px 记录 1:1） |

### 12.3 修复方案（优先数据层，交给 font-engineer）

规格：`work/analysis/elf/v3_render_fix.json`（含逐字节偏移）。

- **方案 A（最小可行，推荐先做）**：把 large/default 的 `fld[1]` 由 26 改为 **16**（展开 blob 偏移 `41` / `2348`，共 8 B；huge 已=16）。
  预期：正文全部 1:1；标题 quad 42.6→**26.2**（仍 1.64× 拉伸，ink≈23.8，不再 38.6）；竖向居中按 16 计算 ⇒ 不再上移裁剪。
- **方案 B（彻底 1:1，数据层完整版）**：A + 把 15 条 style 的 `p1C`/`p20` 全部归 **1.0**（另 120 B，偏移见 JSON）。
  预期：所有面/所有样式严格 1:1 16px（ASCII 前进 8px、中文 16px），排版高度完全一致；代价是丧失“大/小字样式”层级（标题与正文同高）。
- **方案 C（ELF 3 字补丁，B 的替代）**：把 `font+0x20` getter `0x21A4A0` 原地改成恒返 1.0f：
  `0x21A4A0 3C023F80 (lui v0,0x3F80)` / `0x21A4A4 03E00008 (jr ra)` / `0x21A4A8 44820000 (mtc1 v0,f0)`（原字 `03E00008/C4800020/00000000`）。
  效果等同 B（f21 = fld[1]，仍需 A 把 fld[1] 改 16），但保留 FONT.RES 的 style 数值；**会改变 Game CRC**（需重算），无需 cave 空间。
- **不建议**现在做“按字形类型改 y/quad 高度”的 ELF cave 补丁：cave 余量仅 8 B，需先扩 cave 区（`0x180C98+` 死函数边界待验证），且数据方案已能解决。

### 12.4 附带发现（建议一并修）

- **宽度不一致**：cave 的 CharWidth 对 pair 恒返 16，**没有乘 `font+0x1C`(p1C 宽度缩放)**；而引擎 ASCII 路径会乘 p1C。p1C≠1 的样式下（0.6/0.8/1.2/1.64）中文与英文在同一行的前进宽度规则不一致 ⇒ 方案 B 把 p1C 归 1 可顺带消除；若保留样式，应把 cave CharWidth 的 pair 分支补上 p1C 乘法（cave 需 +6 条指令 ≈ 24 B，需扩 cave 或把该分支挪到零区）。
- **验证方法**：重 build FONT.RES（保持 LZO 帧可放回同槽）→ 重建 ISO → emu smoke 到 130s → 量「档案」ink bbox：期望高 **≈23–26px**（原 38.6）、顶部距面板线 ≥4px；再抽查一处 large/default 面正文（应为 16px 1:1）。

### 12.5 证据文件

`work/analysis/elf/v3_render_fix.json`（修复规格）、`work/analysis/emu/zoom_cn_title.png`（标题放大）、`_en130.png`（EN 对照）、`crop_title.png`、`alltest_native_130s.png`、`alltest_native_330s.png`。

### 12.6 落地状态（2026-10-21 晚，A′ 已采纳）

- **A′ 已实装**（font-engineer `fontlib.normalize_face_metrics()`，`ft_merge_for_dlc` 末尾、幂等）：三 face `fld[1]→16` + 所有 style `f5/f6>1→1.0`（#5/#7/#12）⇒ **普通样式 1:1、标题不再上移裁剪**。
- **v5 盘**：`work/builds/JS_ZH_v5.iso`（1,229,264,896 B，sha256 `ba9452bf4d71ba16…`，verify 37/37 PASS；FONT.RES real sha `4610c410…`，LZO 帧 1,555 B）。A′ 对照盘 `work/builds/ab_font/v2_Aprime_fld1_16_norm.iso`（与 v5 同数据方案，不必重复实机跑）。
- **v3 cave（DrawString 0x219890 底对齐块）暂不启用**：作为 fallback 保留（若实机发现"必须保留大标题层级"或小字/fld[13] 问题无法数据侧解决再启用）。启用前提已就绪：`0x180C98..0x180E80` 外部引用=0（jump-in/lui-in/raw-ptr 全 0），cave 可从 1000 B 扩到 ~1528 B；pair 底对齐公式 `y' = y + (CharHeight − 16)`、`y1 = y + CharHeight`。
- **残余观察项（font 侧已登记 R14/§12.5）**：① `fld[13]` 仍 26/26/42（绘制路径不读；若 v5 行距异常再归 16）；② style `f6=0.8` → CharHeight=12（小字纵向压扁，与原盘语义一致）；③ style `f5<1` 时 pair CharWidth 恒 16 vs ASCII×f5（中英步进比偏大）——**不建议**给 pair CharWidth 乘 f5（16px 字形会重叠），溢出位置改短文案即可。
- **验收**：v5 实机截图后用 `work/analysis/emu/measure_text.py --png <png> --box 28,12,72,60 --label title [--compare <EN>]` 量标题 ink 高：A′ 后期望 **≈16px**（修前 36.4），顶部距面板线 ≥4px。

#### 12.6.1 v5 实机验收度量（独立复核，与 font-engineer 数字一致）

口径：RGB>140、640×480 游戏坐标（`work/analysis/emu/v5_metrics.py` / `measure_text.py`）。

| 对象 | EN 原版 | v4（A′ 前） | **v5（A′ 后）** | 结论 |
|---|---:|---:|---:|---|
| 标题「档案」ink 高 | 21.7（Profiles） | **39.9** | **14.8** | A′ 后回到 16px 口径、方形、不裁剪 ✓ |
| 按钮「- 空插槽 -」ink 高（row2） | 12.6（EMPTY SLOT） | **23.0** | **13.5** | 拉伸消除 ✓（row3：v5 13.0） |
| 标题宽（2 字） | — | 31.2 | 31.2 | 未变（宽度未被改）✓ |
| 按钮基线 y1 | 205.4 | 212.8 | **208.5** | 残余 **+3.1 game px**（中英基线差，可接受） |

- 残余 +3.1px 来源：原盘记录 26/42px 高（CharHeight 26/42），我们记录统一 16px（CharHeight 16），字形基线在“行盒”内的相对位置随记录高度变化；**不是引擎拉伸**。若要严格对齐（+3.1→0），启用 standby 的 cave 底对齐块并给 pair 一个常数下移（见 §12.5），或数据侧重绘 pair 字形时把内容下移 1-2px（注意 16px cell 底部余量）。
- 未覆盖：style f6=0.8（#6/#8/#10/#13）小字 → CharHeight=12（16px 字形被压 0.8，纵向略扁，与原盘“小样式=0.8×字高”语义一致）；HUD/列表画面待 emu 补拍后量 h≈12 属预期。

#### 12.6.2 v5 小字样式实测复核（`nav_menu` 截图；ISO 已验证同为 v5）

对象：`work/analysis/emu/nav_menu/navmenu_native_225s.png`（`work/builds/FINAL/GR_JS_ZH.iso`，sha256 **`ba9452bf…570e9185` = v5 盘**，本行由我独立 sha256 校验）。
口径：RGB>140、640×480 游戏坐标（`v5_metrics.py` 同款 `measure_text.py`）。**独立复核结果与 font-engineer 表逐项一致**：

| 对象 | ink 高 | 判定 |
|---|---:|---|
| 标题「档案」 | 14.9 | normal ✓ |
| 对话框「文件名：」 | 15.5 | normal ✓ |
| 小字「确认」（f6=0.8 ⇒ CharHeight=12） | **10.5** | 纵向 0.8 压扁、**无上下裁切** ✓（原盘“小样式=0.8×字高”语义，不需要动） |
| 底部 HUD 提示（L1 R1 移动 / R2 大写锁定 / 删除 / 返回 / 接受） | 13.0 | normal、中英混排步进正常、无溢出/错位 ✓ |
| 槽位「- 空插槽 -」 | 13.0 | normal ✓ |

- **覆盖缺口**：本 run 只到菜单/对话框，**游戏内 HUD / 任务列表画面未覆盖**；R14 因此降为“观察项（仅游戏内 HUD 未覆盖）”，不需要 cave/调 f6。
- 若后续游戏内截图出现「小字被裁一半」（h 明显 <10 或上下缺笔画）才需要动作：方案仍是 §12.5 的 cave 底对齐块或数据侧调 f6；仅“压扁”不处理。

## 13. v9 增补：DrawString 行盒锚点补丁（A‴）

在 v3/A′/A″ 之后再补 4 处（共 32 段 ELF 补丁 = DBCS 26 + 最近邻 2 + 行盒锚点 4）：

| VA | 原词 | 新词 | 语义 |
|---|---|---|---|
| `0x219894` | `E6970000`（`swc1 f23,(s4)`） | `0815D741`（`j 0x575D04`） | 非图标分支 y1 改由 cave 计算 |
| `0x219898` | `E6C00000`（`swc1 f0,(s6)`） | `00000000` | y2 预存点 nop（cave 统一写 y1/y2） |
| `0x575D04` | 0×29 words（函数对齐零填充） | 29 words | cave A：`dy=(CharHeight−16)/2`；`y<40` 再 +7；`y≥400 且 x<400` 再 −3 |
| `0x5752F0` | 0×8 words（同上） | 8 words | cave B：`y1=y+dy`、`y2=y1+16`，跳回 `0x21989C` |

* 选址复核：两段零填充均在函数 `jr ra` 之后、下一函数之前；全文件 j/jal 目标、32 位字面量、
  `lui+addiu` 地址构造三者均 0 命中（脚本见 `work/analysis/elf/align_plan.md §2`）。
* 与本体等价性：base `CharHeight 0x21ACD0` ↔ DLC `0x21A440` 逐词同构；base DrawString quad 组装
  `0x219B70/78/90/98` ↔ DLC `0x219700/08/20/28` 同构 ⇒「恢复 CharHeight=EN + quad 钉 16」是 EN 等价形态。
* 回归：`verify.py` E1/E2/E3 覆盖全部 32 段补丁在盘 + 新 ELF sha/CRC；`all` 阶段 38/38。

### 13.1 v10 追加：cave C（中段 −4px）

| VA | 长度 | 内容 |
|---|---|---|
| `0x182F84` | 60 B | cave C：`40 ≤ y < 400 → dy −= 4`（与 A 段标题/底栏互斥；A 末尾 `j 0x182F84`，C 末尾 `j 0x5752F0`） |

补丁总数 **33 段** = DBCS 26 + 最近邻 2 + 行盒锚点 5（2 站点词 + A/B/C 三段 cave）。
新 ELF sha256 `04687ed252e96bb0…`、CRC `D09038B4`；`verify.py --stage all` 38/38。
选址复核同 §13：零填充、无 j/jal 目标、无字面量、无 `lui+addiu` 构造。

### 13.2 v11：cave C 常量 4.0f → 2.0f

仅替换 cave C 中 `lui t0,0x4080`（4.0f）为 `lui t0,0x4000`（2.0f），其余字节不变。
新 ELF sha256 `4c47d284ebb8bd87…`、CRC `D0903834`；`verify.py --stage all` 38/38。

## 14. v14 串越界/NULL 守卫（战役卡死修复）

崩溃定案与修复细节见 [`CRASH_CAMPAIGN_ANALYSIS.md`](CRASH_CAMPAIGN_ANALYSIS.md) §11。

* 站点 A：`0x4015F0`（RSString 构造入口）→ cave @`0x5841C4`：容量 `a1<=0` 时钳到 1。
* 站点 C：`0x401F98`（子串结尾取 data）→ cave @`0x59EF20`：shared/data 任一为 NULL 时
  跳函数尾声 `0x401FC0`（不写 0 地址、不做无效赋值）。
* 生成器：`tools/dlc/build.py --stage spec`（串守卫已内置；`GRJS_NO_STRING_GUARD=1` 关闭做 A/B）。
* 新身份：ELF sha256 `5d28fc7195221336d4afb5a96999ebe9ce383ab4bd88773078d0959c3afd0e62`，
  Game CRC `E0C456E2`，38 段补丁。

## 15. 换行边界修复（v15：DBCS 折行）

**症状**：换行处字符错乱、行尾出现手柄按键图标（例：「对下面的靶子练习一下射击」显示成
「对下面的靶子△现一下射击」）。

**根因**：UI 折行函数（`0x21B620`）的字符循环 `0x21B778..0x21B7C4` 是**按字节**的：

```
0x21B778 jal 0x401D20      ; 取第 s0 个“字节”的指针
0x21B780 lb  a1, 0(v0)     ; 读一个字节当字符码
0x21B784 jal 0x21A360      ; CharWidth
0x21B7B4 addiu s0, s0, 1   ; 索引 +1（字节）
```

中文对偶码 2 字节，这个循环会把一个字拆成两半：
* 行宽在「半个字」处越界 → 行尾只剩 lead 字节（或整字被截断）；
* 若行尾恰是 lead 字节 **0xB1/0xB5**，`DrawString` 会把它当单字节图标码 → **画 △/✕ 图标**；
* 下一行从 trail 字节开始解码 → 前后字符全错（0xA3+… 被当成另一个对偶码）。

**修复**（3 站点 + 3 段 cave，cave @ `0x5BFE0C`）：

| 站点 | 原指令 | 改为 | 作用 |
|---|---|---|---|
| `0x21B778` | `jal 0x401D20` 取字节指针 | `j cave A` | 直接读 RSString 数据指针，按 DBCS 规则组 16 位码；步长（1/2）存 `sp+0x9C` |
| `0x21B7B4` | `addiu s0,s0,1` | `j cave B` | 索引 += 步长（原延迟槽 `lw v0,176(sp)` 保留） |
| `0x21B7A0` | `addu v0,s3,v1` | `j cave C` | 宽度补偿：原字节循环每字节加一次 `font[0x18]`，对偶码合并后补一次 |

cave A 关键片段：`lw t1,4(a0) → lw t1,4(t1) → addu t1,t1,s0 → lbu t2,0(t1)`，
然后 `lead∈[0xA1,0xBA) 且 trail∈[0xA1,0xFF) 且 index<len-1` 才组码，否则按单字节。
JS19（本体汉化）的 wrap cave（BASE `0x21CD70` → `0x417500`）就是同一修法，本作按 DLC 结构重写。

**验证**：训练任务弹窗（长中文段落）——修复后所有换行落在完整字符边界，无图标、无错字
（`docs/img/wrap_after_v16.png`）；训练任务运行 220s 无 TLB Miss。

**身份**：42 段 ELF 补丁，ELF sha256 `d90d2fe6…`，Game CRC `6C4AF325`。

### 15.1 行首 +1 修正（第二处，已根治，问题截图 `docs/img/wrap_v15_line_start_bug.png`）

v15 修完「行尾半边字/△」后，训练弹窗又暴露出第二处：「用右摇杆」的「摇」在**行首**显示成「是」。
实测与复现：

| 实验 | 结果 |
|---|---|
| 短文本 `摇星键练试A1摇杆转身`（v15 盘） | 全部字符正确 |
| 长文本 `摇×40`（v15 盘） | 第 1 行正确；**第 2 行首字 = trail 字节解码**（是/错字） |
| 同上（v14 盘，原引擎折行） | 第 2 行首字正确 |

⇒ 引擎在折行后创建下一行文本时，行首索引比「溢出的那个字」多 **+1 字节**（原设计假定断点是
空格并跳过 1 字节）。中文对偶码被跳过 lead 后，行首从 trail 开始解码：trail 若落在单字节码表
（如 0xD9=是）就显示成该字，否则整行错位。

**根因定位**：折行函数尾 `0x21B8B4..0x21B8C8`：

```
0x21B8B4 jal strlen(line1)     → v0 = 行长
0x21B8BC addiu v1, v0, 1       → 行长 + 1（假定断点是空格、跳过 1 字节）
0x21B8C0 lw v0, [0x138]        → 行首索引
0x21B8C4 addu v0, v0, v1       → 下一行行首 = 行首 + 行长 + 1   ← 中文被跳过 lead
```

**修法**：站点 `0x21B8C4` → `j cave H`（cave @`0x57B78C`，52 B）：
取断点字节，若是 0x20（空格）保留 +1，否则把 +1 去掉；随后照旧执行原有空格跳过循环。

**验证**：训练任务弹窗第 2 行开头恢复「摇杆转身」；探针盘（「摇」×40）第 2 行起首字全部正确；
训练任务运行 220s 无 TLB Miss。v16 已进 FINAL（ELF `8e742b36…`，CRC `755C961C`）。
剩余小问题：ASCII 单词可能在折行处被拆开（START → STA/RT），属折行质量优化，不影响可读性。

## 16. 手柄按键图标码（v17）

**问题**：译文把原版引擎绘制的按键图标写成了 ✕/△ 文本符号（`U+2715`/`U+25B3`），
实际显示为字体里的文本字形而不是手柄图标。

**根因**：原英文盘这些位置存的是**单字节图标码** `0xB1`（△）/`0xB5`（✕）；`DrawString`
有 8 处常量专门判断这两个码并绘制按键图标（DBCS 规格里已把 `0xFFB1/0xFFB5` 零扩展为
`0x00B1/0x00B5`）。译文改用文本符号后就走了普通字形路径。

**修法**：译文改写为引擎图标标记 `{{BTN:E0B5}}`（✕）/`{{BTN:E0B1}}`（△）——编码器
`Charset.encode` 会把标记还原成单字节 `0xB5/0xB1`。共 28 处 / 21 条，图标两侧保留空格
（图标字节后必须是 <0xA1 的字节，否则会被 DBCS 解码器当成 lead 吞掉下一个汉字头字节）。

**验证**：训练提示实测显示原版手柄图标（`docs/img/icons_after_v17.png`）。

**已知副作用（待修）**：图标两侧的 ASCII 空格会触发引擎“按空格断行”，中文提前换行、行数
变多而溢出提示框。下一步方案：把图标码改到非 DBCS 头字节区（如 `0x90`），去掉空格后中文
按字连续折行；需要同步改 10 处图标常量（8 站点 + CharWidth cave 2 条）。

## 17. 提示框“整体下移一行/多出空行/末行挤出框”（v19）

**症状**：长文本提示框里文字整体偏下、像开头多了一个空行，末行被挤出框外（开门提示、小队指令提示）。

**根因**：折行函数尾 `0x21B888` 判断 `s4 = 限宽 - 本行实测宽 - 字距`：

```
0x21B888  bgez s4, 0x21B8B4     ; s4 >= 0 视为“放得下”
0x21B890  把 [0x138] 推入行首列表  ; s4 < 0 分支
```

当首行宽度几乎占满（中文按 16px/字排满时 s4 只差一点点为负），会被误判为“放不下”：
把**仍是本行行首**的 `[0x138]`（首行时为 0）重复推进行列表 ⇒ 开头多一个空行、整体下移一行，
行数多一行 ⇒ 末行被挤出提示框。

**修法**：站点 `0x21B888` → cave `0x5880A4`（28 B）：`s4 > -16` 一律按“放得下”处理，
只有真正超出 16px 以上才走原分支。

**验证**：开门提示（2 行）文字从框顶开始、行 2 完整在框内；小队指令提示（4 行）行数正确、末行在框内
（`docs/img/hint_before_v19.png` → `docs/img/hint_after_v19.png`、`docs/img/hint_door_after_v19.png`）。

## 18. 图标码换区（v19，配合 §16）

图标两侧必须是 ASCII 空格（图标字节后必须是 <0xA1 的字节），而引擎折行会**优先在空格处断行**，
导致中文提示行被截短、行数变多。v19 把引擎图标码从 `0xB1/0xB5`（在 DBCS 头字节区
`[0xA1,0xBA)` 内，后接汉字会被 DBCS 解码器当 lead 吞掉）换到 `0x90/0x84`（非 lead 区）：

* 8 处 DrawString 图标常量 + CharWidth cave 2 条常量 → 新码；
* 译文 `{{BTN:E0B1}}/{{BTN:E0B5}}` 编码为 `0x90/0x84`（`textlib.py` 的 `ICON_TOKEN_BYTES`），
  图标与汉字直接相邻、无需空格；
* 选用的两个单字节码原本映射「池」「促」——「池」未使用，「促」在特别收录 T0040 改写为「让」，
  避免字符集编码冲突。

**验证**：提示框内 `✕`/`△` 显示为原版手柄图标，且中文整段连续换行（`docs/img/hint_after_v19.png`）。

## 19. 行宽统一（v20：29 个全宽字）

**问题**：不同提示框折行位置不一致——有的 29 个全宽字换行，有的 30 个字才换行（贴右边框）。

**根因**：折行可用宽度 `s7 = 控件宽 − 内边距` 因控件而异，个别提示框恰好多出约一个字宽。

**修法**：折行函数 `strlen` 之后（站点 `0x21B6AC`）插入 cave `0x59FFC4`：
`s7 = min(s7, 464)`（464 = 29 × 16px），并同步 `s4`。这样所有框统一在 29 个全宽字处换行，
右边自然留出空隙；窄框（s7 < 464）不受影响。

**验证**：训练提示行宽统一（29 字），右侧留白；加载画面「载入中...」标点修正（LANG G058.I494）。

---

## 20. 任务简报页（简介）换行回归与修复（v21）

**现象（v20）**：战役任务“简介”页左栏简报文字不自动换行，行宽约 27 个全宽字（≈430px）
超出深色文本框（≈262px），文字压到右侧地图/照片面板上。

**定位**：
· 该页正文来自 LANG 组（如 C01 的 G019.I006，含 {p} 分段），由通用折行函数 0x21B620 排版；
· 文本框可见宽度 ≈262px（约 19~20 个 ASCII 字符宽），但该控件交给折行函数的可用宽度 s7 ≈440px；
· 提示框（s7≈460）、信息栏（s7≈500）都正常，说明问题只在这一类“窄栏宽控件给错宽度”的界面；
· v16~v20 把折行从「按字节计宽」改成「按 DBCS 字对计 16px」后，中文每行能塞进更多字，
  这个错配才以“右侧溢出”的形式暴露（英文原版按 8px ASCII 计宽，行宽同样超框，但很少触发注意）。

**修复（v21，数据侧硬折行）**：
· 新增 tools/dlc/wrap_text.py：按「全宽字单元」硬折行（插入 {br}），ASCII 记 0.5 单元、
  CJK/全角/图标标记 1 单元；优先在标点后断行、不拆英文单词、保留 {p} 分段；
· 用 --only-briefing 自动挑出“同组含 1./2./X- 目标项”的 16 个简报组（G019~G033、G039），
  对其中 16 条长简报文本按 15 单元折行（=240px，留出右边距）；
· 结果表 work/translation/merged/translations_v21.csv；盘上写 {br}，引擎不再自动折行，
  普通提示框/信息栏文本不受影响。

**备选（若后续要根治）**：把简报页控件的宽度字段从 440 改成 262（UI 布局数据待定位），
或让 0x21B620 对窄控件改用可见宽度；数据侧 hard-wrap 是当前不依赖逆向 UI 数据的稳妥解。


---

## 21. 复用本体工程译文（v21）

用本体（Ghost Recon 2001, SLUS-20613）汉化工程的现成译文，对「英文原文完全一致」的条目做复用：
· 全量对照：4485 条中英文一致 1714 条（38.2%），其中 1335 条 DLC 现有中文已与本体逐字相同；
· 新增可复用 42 条（全部是 EN_STRINGS.TXT 显示名/操作/兵种名，跨资源取自本体 SFXML_TITLE / LANG）；
· 28 条冲突（21 条口径差异、7 条用词差异）一律不覆盖；
· 产物：work/translation/reuse/base_reuse_candidates.csv（全量判定）、base_reuse_report.md、
  translations_reuse.csv（v20 + 42 条 source=base_reuse）；
· v21 译文表 = translations_reuse.csv + 简报硬折行。

**风险**：武器显示名变长（M4→M4 短突击步枪），军械库/装备栏槽位需实测；兵种名两套写法
（突击队员/突击兵）统一术语时再定。

---

## 22. 任务简报页（简介）换行回归与修复（v21）

**现象（v20）**：战役 C01「简介」页左栏简报文字不自动换行，行宽约 27 个全宽字（≈430px）
超出深色文本框（≈262px），压到右侧地图/照片面板上。

**根因**：
· 该页正文来自 LANG 组（如 C01 的 G019.I006，含 {p} 分段），由通用折行函数 0x21B620 排版；
· 文本框可见宽度 ≈262px，但控件交给折行函数的可用宽度 s7 ≈440px（比可见框宽 1.7×）；
· 提示框/信息栏 s7 正确，所以只有这类“窄控件给宽 s7”的界面暴露；v16~v20 把折行从按字节计宽
  改成按 DBCS 字对计 16px 后，中文每行能塞更多字，才以“右侧溢出”的形式显现。

**修复（v21，数据侧硬折行）**：
· 新增 `tools/dlc/wrap_text.py`：按「全宽字单元」硬折行（ASCII=0.5、CJK/全角/图标=1），
  优先标点后断行、不拆英文单词、保留 {p} 分段；
· `--only-briefing` 自动识别“同组含 1./2./X- 目标项”的 16 个简报组（G019~G033、G039），
  对 16 条长简报按 **15 单元**（≈240px）折行；
· 结果表 `work/translation/merged/translations_v21.csv`，盘上写 {br}，引擎不再自动折行，
  提示框/信息栏不受影响。实测：简报行宽落在 240px，右侧留出空隙，文字不再压地图。

**备选（如需根治）**：把简报页控件的宽度字段从 440 改成 262（UI 布局数据待定位），
或让 0x21B620 对窄控件改用可见宽度。

---

## 23. 简报页/菜单标题垂直锚点（v22）

**现象（v20）**：C01 简介页里“简介”标题、右上 GR-C01、以及菜单标题整体比英文原版**偏下**；
任务目标列表也略低。

**定位**（用 v22/v21/英文原盘同页截图逐像素量测，脚本 `work/measure_brief.py`）：
· 顶部条带（y<40）在 A‴ 里统一 +7px，是为“本体中文大标题”校准的；本作 DLC 的标题/右上角
  GR-C01 用不到这个 +7，导致整条顶部文字比 EN 低 7px（截图上约 14px，缩放 3.28×）；
· 中段正文 -2px 对任务目标列表略保守，比 EN 再高 1px 更接近用户观感。

**修复（v22）**：行盒锚点常量改为 **标题带 +0、中段 -3、底栏不变**（数据/ELF 常量，无新逻辑）：
· `build.py` 支持环境变量覆盖：`GRJS_ANCHOR_TITLE` / `GRJS_ANCHOR_MID` / `GRJS_ANCHOR_BOTTOM`；
· v22 产物 `work/builds/G…v22.iso`，verify 40/40；
· 同页量测：简介标题 top 69→54（EN=56）、GR-C01 top 83→69（EN=59）、目标行再上 1px。
  残留：GR-C01 仍比 EN 低约 3px（它用的字号/缩放系数与标题不同，需按控件单独调，待下一轮验证）。

---

## 24. 闭环导航（导航脚本）

见 `docs/NAV_CLOSED_LOOP.md`：`tools/emu/nav_briefing.py` 以画面特征为“状态钩子”，
自动开机→主菜单→单人菜单→战役画廊→FMV→简介页，输出截图 + 状态链日志；
已在 v21/v22/英文原盘/3 个锚点探针盘上各跑通 1 次。

---

## 25. 锚点 cave 迁移与 FMV 卡死排查（v23 研究轮）

**现象**：把锚点 cave 扩到 148B 时曾放到文件 0x486568（VA 0x586468，原盘 568B 全零），
实机启动后过场 FMV 卡在一帧、emulog 出现 EE: Unrecognized op 7661732e（把 ASCII 当指令执行）
+ TLB Miss, pc=0x59b2fc + Trap exception at 0x005b4958。判定：该零区被运行时数据/代码覆盖或
不是纯函数对齐填充，**不可作为 cave**。

**处置**：锚点逻辑拆到两段已验证死区：
· cave A @ VA 0x575D04（原 v11 cave A 区，132B 可用）：dy 居中 + 顶部条带分区；
· bottom 段 @ VA 0x59EF50（串守卫 C cave 之后的零填充尾，80B）：y>=400 且 x>400 再 -3；
链保持：cave A → cave C(0x182F84，中段位移) → cave B(0x5752F0，写 y1/y2) → DrawString 0x21989C。
迁回后同 ISO 连续 6 次启动/进菜单/播 FMV/进简介页均正常，无 TLB/Trap。

**仍待解决**：顶部“简介”与右上“GR-C01”在 DrawString 里拿到的是**同一组参数**
（CharHeight=26、y≈36），按 x/y/字号分区都没能分开；实测两种取舍：
· 让 GR-C01 对齐 EN（top 59）：简介被一起上抬到 44（偏高 ~10px）；
· 让简介/菜单标题回调（title +4）：GR-C01 反而下移到 ~78。
下一步建议：查 GR-C01 的 style 索引与 f5/f6 缩放口径（用户判断原版有缩放系数），
或换成按“字符串/字形来源（pair vs ASCII）”分区。

---

## 26. 任务目标行与标题分离（v23）+ GR-C01 调用点定位

**v23 修复**：中段位移从 cave C 移到 bottom 段，并按 y 分档：
· y < 270（游戏坐标，含“任务目标”标题）→ 不动；
· 270 <= y < 400（目标行/正文）→ dy -= mid（默认 6）；
· y >= 400（底栏）→ dy -= bottom（默认 3）。
实测（同页对比）：obj_header top=553（与 v22 相同，未动），目标行 718→711（上移 7px），
简介/GR-C01 与 v22 相同（54/69）。cave C 的中段常量置 0（逻辑已移走，保持链完整）。

**GR-C01 调用点定位（下轮用）**：
· 文件 0x1B4C00/0x1B4C58 两处 lui 0x59 + addiu 0xE188 指向字符串 "GR-"（ELF VA 0x58E188）；
· 所在函数片段 VA 0x2B4A80..0x2B4B40：先用 0x401E00（字符串拼接，a1="GR-"、a2=sp+0xE0 的任务代码）
  组成 "GR-C01"，再 lw t9,0(s0); lw t9,0x104(t9); jalr t9（widget 虚表 +0x104 = SetText）设置到控件 s0；
· 即：**文本内容路径已找到，控件 y 坐标在控件创建处设置**（不在该片段内）；下一轮从该函数调用者/控件
  构造处找 y 常量（附近字符串表还有 TITLE_TEXT_2 / LOCATION / SIDE_BOX / MAIN_BOX 等简报字段键）。
· 顶部条带“简介 vs GR-C01”按 x/y/字号/字宽/CharHeight/sp+0xDF 六种判据均未能稳定分离（实验记录见提交历史）。

---

## 27. v24 锚点定版 + 小队界面字形/换行问题（2026-10-24）

**v24 锚点定版**（替代 v23 的 y=270 单档方案）：
· bottom 段：y >= 270 → dy -= 3（然后回 cave C）；
· cave C：恢复 34 <= y <= 400 → dy -= 3。
净效果：菜单类（y<270）只吃 cave C 的 -3（= v22 位置，与 EN 对齐）；简报目标行（270..400）吃
bottom -3 + cave C -3 = -6（= v23 的上移量）；简报“任务目标”标题与 v22 相同；底栏只 -3。
实测：主菜单 6 项与 v22 逐项相同（269../546.. 组），obj_header top 553（=v22），目标行 711（v23 值）。
副产物：	ools/dlc/wrap_sfxml.py（SFXML 窄面板硬折行）。

**小队设置界面字形实测（v23/v24 干净冷启动，非旧存档）**：
· 截图见 work/analysis/emu/squad_v23/：member_selected.png 右下角兵种显示 **“爆罗手”**、
  _zoom_class4.png 显示 **“突击向”**（应 突击队员）——**问题可复现，不是旧即时存档**。
· 盘上字节正确：LANG G058.I903=突击队员=A2B6B9FDC1E9、G058.I902=爆破手=EBA3C8F0、
  ATR ActorName=突击兵/狙击手 均解码正确（work/glyph_issue_report.md）。
· 现象规律：错误字恰好是“第二字节 +0x20”（队 C1→向 E1、破 trail C8→罗 E8；员 E9→越界→空白），
  而其它同串字正常 → 指向**该 UI 文本渲染路径的字形索引/缓存与主 DrawString 路径不同**
  （可能是前端另一份 RSFont/标签渲染器，或它使用的 FontDefinition base char=0）。
· 下一轮：用 1 张「诊断字符串」探针盘（把 4 个兵种名替换成“队队队队/破破破破/员员员员/向向向向”）
  抓一次小队界面即可反推映射规则，再决定修 charset/图集还是补第二渲染路径。

**小队界面换行/提示**（待办）：
· 成员/武器信息右侧说明面板换行错位：候选条目 SFXML T0016-T0060（武器）、T0070-T0091（成员/兵种），
  已备 	ools/dlc/wrap_sfxml.py，待从截图量出面板宽度后按 units 重折；
· 底部按键提示实际是 ◯ 信息（2 字）；用户希望显示 队员信息（4 字不滚动）→ 定位到具体 LANG 键后
  改译文并实机确认宽度。

---

## 28. 小队设置界面三类文字问题定案（v25–v27）

### 28.1 兵种名“突击向/爆罗手/狙空白”的根因（已定案）

**不是**字符集/图集/FONT.RES 错版，而是**兵种标签控件自己的文本预处理**：

- 控件：`panel+0x208`，UI 模板 `OPTION2`（VA 0x593FF8），刷新函数 VA 0x3299E0，Rifleman 分支 0x329A70–0x329AA8；
- 取串链 `0x40A4E0 → 0x400400 → 0x401670` 只拷贝 RSString，不改字节；
- 之后控件把字符串**逐字节查 Latin-1 小写表**（VA 0x568130，按字节直接索引；表项 C1→E1、C8→E8，
  即 0xC0–0xDF 段 +0x20）**并截断到 5 字节 / 3 字形**。

因此：`突击队员`(6B) 截成 `A2B6 B9FD C1` 再折叠 C1→E1 ⇒ 显示“突击向”；`爆破手`(4B) 的破 trail C8→E8
⇒ 显示“爆罗手”；凡是名字里含 0xC0–0xDF 字节的都会错，其余字节不变（所以同屏别的字正常）。
详细取证见 `work/frontend_text_report.md`、`work/analysis/frontend_text/`。

**修法（数据侧，已采用）**：兵种短名一律改成 **5 字节且不含 0xC0–0xDF** 的三字名：

| 兵种 | 旧 | 新 | 盘上字节 |
|---|---|---|---|
| Rifleman | 突击队员 | 突击兵 | A2B6 B9FD A2B3 |
| Support | 支援队员 | 支援兵 | A4B0 A4AF A2B3 |
| Demolition | 爆破手/爆破兵 | 炸弹兵 | A1AF BF A2B3 |
| Sniper | 狙击手 | 狙击手 | A2EC B9FD F0 |

覆盖 LANG G058.I902–I905 + 短名副本 I934–I938/I940/I942/I943 与 SFXML_TITLE A0162–A0165。
实机已验证：v26 的“突击兵”显示正确；v27 统一后复测（见 squad_v27 采集报告）。
（代码侧根治候选：把表 VA 0x568130 的 0xC0–0xDF 段改成恒等；需 A/B 探针确认该表确实被此路径引用，暂未采用。）

### 28.2 角色说明/武器说明换行（已修）

- 现象：SFXML 长段（T0088–T0091 兵种说明、T0016–T0060 武器说明）在窄面板按 ~848px 折行、
  压出 ~750px 金框，右边每行被切 2–3 字。
- 修法：`tools/dlc/wrap_sfxml.py` 按 **19 全宽字/行** 硬折行（`{br}`），去掉 TM 旧断行；
  译文表 `work/translation/merged/translations_v25.csv` 起包含该折行。
- 实机验证（v25）：角色说明 4 行全部在框内，正文最右 x=1652、面板右边框 x=1665，**留 13px**，无丢字。
- 遗留：硬折行没有词内保护（第 2/3 行把“装药”拆开），后续可在折行器加“优先在标点/空格断行”。

### 28.3 底部 Circle 提示 4 字（已改，仍有周期性回退）

- 名册提示原为 `◯ 队员`（LANG G058.I229）；改成 `队员信息` 后实测可**完整平铺 4 字**（框够宽、不截断、不滚动）。
- 但采集发现 Circle 项会约 1.4s 周期在「信息」2 字与「队员信息」4 字两态间跳——
  说明该按钮槽位有两个 hint 条目交替显示（另一条是 `信息`，LANG G058.I029/I034 一类）。
  下一轮把同槽位的两条 hint 文案统一成同一串即可稳定。

---

## 29. 小队兵种名：EE RAM 取证（v25 轮）

**方法**：`tools/emu/save_squad_state.py` 跑到「小队设置→自动分配→选中队员」后按 F1 存 PCSX2 即时存档；
`tools/analysis/ss_extract.py` 用 PCSX2 自带 `zstd.dll`（zip method 93）解出 `eeMemory.bin`，在 32MB EE RAM 里搜字符串。

**结果**：
- LANG 主表（RAM 0x5C6D.. 区）里的四条原串都是**干净**的：
  突击队员 `A2B6B9FDC1E9`、支援队员 `A4B0A4AFC1E9`、爆破手 `EBA3C8F0`、狙击手 `A2ECB9FDF0`；
- 但**动态字符串池**（0x601B03 附近，紧邻 “P. Santiago / P. Perry” 等名册字符串）里出现的是
  **已被改写**的 `EBA3E8F0` =「爆罗手」。
- ⇒ 错字发生在**控件把文本构造成自身字符串的这一步**，不是 DrawString/字形查找（此前 6 种字形判据全灭也与此吻合）。

**变换规律（部分可预测）**：`爆破手 EBA3C8F0 → 爆罗手 EBA3E8F0`（C8→E8，即 Latin-1 小写 À→à 的 +0x20），
`突击队员 A2B6B9FDC1E9 → 突击向员`（C1→E1），再配合「最多 3 字形」截断 ⇒ 实机「突击向」。
但「支援兵/狙击兵/炸弹兵」的实机结果与单纯逐字节小写不符（分别出现 4 字「走组亦练」、首字空白、弹→切），
说明还有一次**错位重解析**；数据侧换字不可靠（已实测 v26–v30 五版）。

**下一步（下轮）**：
1. 在 PCSX2 里对池地址（0x601B03 附近的字符串节点）设**写监视/断点**，或在 `SetText` 调用点
   （0x329AA8 的 vtable+0x104）下断，回溯到做变换的函数；
2. 若变换是共享的 tolower 工具，可考虑在**该控件专用路径**上跳过它（cave 或调用点 patch）；
3. 备选：把兵种标签改由**不走该控件的文本字段**渲染（例如与标题「小队设置」同一条 SetText 路径——
   实测标题里的「队」渲染正确）。

---

## 30. 兵种名 / 武器说明界面：插桩与按键矩阵（继续轮）

### 30.1 兵种名：已排除的链路与仍在追的链路

- 首个疑点（`0x3299E0` 名册刷新，四个分支 jalr 到 `vtable+0x104`）**不是**实际路径：
  在该函数 4 个 `jalr t9` 处插桩（cave 写 scratchpad/顶端 RAM），实机跑到名册并 F1 存档后，
  scratch 始终为 0 ⇒ 该函数没有为名册兵种名设置文本。
- 另外找到一处**同样构造 I902–I905 键**的代码 `0x1F15B0`：走
  `0x40A4E0(取 LANG)→0x402AE0(RSString→C 串)→0x3FF4F0/0x3FF830(控件文本 setter)`；
  在 `0x1F16B0` 插桩同样未命中，说明它设的是名册槽位的**姓名**（S. Terry 等）而非兵种名。
- 已确认字符串 interner `0x40C660/0x40C810` 只做逐字节比较/拷贝，不做变换；
  `0x40C440` 只是取全局 interner。⇒ 变换发生在这条链的**更早一步**（或另一条设置路径）。
- 已定位的“证据点”：v25 存档的 EE RAM 动态串池里有 **`EBA3E8F0`=爆罗手**（输入 `EBA3C8F0`，C8→E8），
  LANG 主表在 RAM 里却是干净的 `EBA3C8F0`；说明某处把干净串复制成脏串。

**下一轮做法**：在真正设置兵种名的 setter 之前做**累积环形缓冲插桩**（每次调用记录入参字节+返回地址），
用“进入一次小队界面会设置哪几条串”来反查，而不是猜函数；工具：`work/ss_extract.py`（zstd 解存）、
`tools/emu/save_squad_state.py`（跑到名册并 F1）。

### 30.2 武器说明界面入口：按键矩阵结果

在三个状态（小队设置空槽 / 自动分配后名册 / 角色说明页）逐一试键并记录画面 diff：

| 状态 | 无反应的键 | 有变化的键 |
|---|---|---|
| 小队设置（空槽） | R1(e) L1(q) Square(a) L2(1) R2(2) Left(f) Right(h) | Down/Up(g/t) 移动光标 |
| 自动分配后名册（选中队员） | R1(e) L1(q) Square(a) Right(h) Left(f) | Up/Down 换人；Circle(s) 打开角色说明；Triangle(w) 返回 |
| 角色说明页 | R1(e) L1(q) Right/Left | Down/Up 滚动正文；Triangle 返回 |

英文盘同路径同样没有武器说明界面。**R1 只在简报页生效**（切换右侧地图/航拍图），
在名册上无任何反应 ⇒ 用户描述的「R1 切换到选择队员武器界面」在本作此流程下不可达，
或需要另一入口（例如任务开始前的装备/kit 菜单）。下轮：在简报页/战役画廊/训练入口再找「装备」入口，
或由用户提供该界面截图/更精确步骤。

### 30.3 底部提示条：marguee 机制

小队设置页底部 `自动分配` 提示在截图里显示为「自动分」——提示条是**按固定宽度滚动/截断**的 marquee。
这解释了「队员信息」4 字会以 2 字/4 字交替出现：窗口窄于文本时进入滚动模式。
若要求 4 字稳定平铺，需要改提示条控件宽度（UI 布局），或改用 ≤3 字文案。

---

## 31. 武器说明界面：入口找到 + 换行修复（v31）

### 31.1 入口（此前一直没找到）

名册（自动分配后）里 **R1 不是换界面，而是把焦点移到中间「装备」栏**（该栏出现金色边框）；
此时按 **Circle** 打开「武器属性」页：标题 `Kit：1 - M4 短突击步枪/爆破装药`，
左栏武器/装备列表，右栏武器说明 + 精准度/后坐力/稳定性/杀伤力解释，底部提示「使用左右方向键」。
（左右方向键切换装备，每件装备右栏说明不同。）

复现脚本：`work/weapon_capture.py`（已放入 `tools/emu/weapon_capture.py`）：
简报 → Cross → 小队设置 → Cross 自动分配 → Up 选人 → **R1(e)** → **Circle(s)** → 截图。

### 31.2 换行修复

实测右面板金框 x=326..590（游戏坐标），宽 **16.5 个全宽字**；v25 的 19 字折行会压到边框（右缘 586，被裁）。
v31 改为：
- SFXML 武器说明 `T0016-T0060` → **15 全宽字/行** 重折；
- LANG `G058.I047`（精准度/后坐力/稳定性/杀伤力 说明）→ **15 字/行**，保留「精准度{br}」小标题结构；
- 兵种说明 `T0088-T0091` 仍保持 19 字（角色说明面板更宽）。

v31 实机（`work/analysis/emu/weapon_capture31/wc_weapon_attr_0.png`）：说明文字全部落在金框内，
无越框/裁字；`M4 卡宾枪是 M16 步枪的缩短版本。` / `它发射同样的 5.56 x 45 mm 弹药，` 等行完整。

---

## 32. 兵种名：DrawString 拿到的字节已被改坏（v25 轮，决定性证据）

**方法**：在 RSFont::DrawString 内部的 strlen 调用点 `0x21964C`（此时 s2=文本指针、t 寄存器已可安全复用）
插入 cave，把每次绘制的 `{字符串指针, 前 20 字节}` 记入 0x1FFF000 的 64 项环形缓冲，然后跑到小队名册并存档。

**结果**（`work\analysis\emu\trace_probe18`）：

- 名册右下兵种名绘制时，DrawString 收到的指针 = `0x00601B02`，字节 = `20 EB A3 E8 F0`，
  即 **“空格 + 爆罗手”**（LANG 主表是 `EA A3 C8 F0`=爆破手）。
- 同样指针 0x601B02 处正是之前发现的 interned 串池节点。⇒ **错误发生在进入 DrawString 之前**：
  某处构造/改写出的字符串已经含 `C8→E8`，并额外带一个前导空格。
- 其余同屏文本（装备、M4 短突击步枪、爆破装药、得分、领导能力…）都正常，说明问题只在那条“空格+兵种名”的构造链。

**后续插桩尝试（未完成，记录以免重走）**：
- 在文本 setter `0x3FF7E0` 入口（该函数内唯一调用 interner `0x40C810`）插桩，带字符串过滤（首字节空格 + 第二字节≥0x80），
  实机在启动 7s 左右出现 `memcpy(0)` TLB 错 —— 说明该 setter 在启动早期会被以非文本参数调用，
  入口处不能无条件访问 a1；需要更保守的指针合法性判定或在 `0x3FF7FC` 之后（a1 已被当作文本使用）插桩。
- 另：`0x1F15B0`（构造 I902–I905 key 的函数）与 `0x3299E0`（名册刷新）实测都不被该界面调用。

**下一步**：在 `0x3FF7E0` 的 `0x3FF7F4` 之后（它已把 s0 当文本使用）插桩，或对 interned 节点 0x601B02 的写入者做记录，
把 ra 与“空格+兵种名”一起记下，即可定位构造该字符串的调用点。

---

## 33. 兵种名乱码根因 = 引擎大小写折叠循环的高字节负索引（v32 修复）

### 33.1 线索（用户提示 + 本体工程旧会话记录）

用户提示本体汉化工程出现过同样问题（「支组进项对」）。在
`reference/dsh-session-session-25776770-*/session.v4.jsonl` 里检索到本体 ZH72 定案：

- 本体现象：小队屏兵种字段显示 ` 支组进向\t`；
- 根因：引擎大小写折叠循环按 **符号扩展字节** 索引 ctype 表（`表基址 + (s8)c`），
  ASCII 正常；高字节（≥0x80）索引为负，落进表下方的 rodata 字符串里，
  撞上 bit0/bit1 的字节就执行 `c += 0x20` / `c -= 0x20`（mod 256）；
- 本体修复：`GR_ZH72` 在 LowerCase/UpperCase 两个折叠循环里加「高字节守卫」（12 词）。

### 33.2 移植到 DLC：同源缺陷，同样的三处证据

| 项 | 本体（SLUS-206.13） | DLC（SLUS-20820） |
|---|---|---|
| ctype 表基址 | `0x585961` | **`0x57F9A1`**（表内容逐字节相同，0x00..0x7F 全等） |
| LowerCase 循环 | `0x407060` | **`0x16DF38`**（`lb/sra/lui 0x58/lbu -0x65F/andi 1/addiu +0x20/sb`） |
| UpperCase 循环 | `0x408910` | **`0x16FB78`**（同型，`andi 2 / addiu -0x20`） |
| 调用者数量 | 3 / 8 | 3 / 9（含 0x400124/0x4028E0/0x408F20 等） |

**字节级对上现有症状**（全部是「高字节撞表外字节后被 ±0x20」）：

| 原字 | 原字节 | 被折叠后 | 实际显示 |
|---|---|---|---|
| 队 | `C1` | `E1` | 向（突击队员→突击向） |
| 破 | `C8` | `E8` | 罗（爆破手→爆罗手） |
| 员 | `E9` | `09` | TAB → FT 记录 223 的窄字形/截断 |
| 弹 | `BF` | `DF` | 切（炸弹兵→炸切兵） |
| 援 | `AF` | `CF` | 程/组一类（支援兵→…) |

DrawString 抓到的是 `20 EB A3 E8 F0`＝“空格 + 爆罗手”（前导空格是名册格式，不是错误），
证明改写发生在文本构造阶段（`Substring(1)` 后调 `LowerCase` 整形），与本体记录一致。

### 33.3 修复（v32，纯 ELF 4 词，无 cave）

在两个折叠循环的 `sll/sra` 两词处改成「判 c<0x80，否则直接跳过折叠与回写」：

| VA | 原词 | 新词 | 作用 |
|---|---|---|---|
| `0x16DF48` | `00031600` | `8000612C` | `sll v0,v1,24` → `sltiu at,v1,0x80` |
| `0x16DF4C` | `00021603` | `07002010` | `sra v0,v0,24` → `beq at,zero,+7`（跳过折叠/回写） |
| `0x16FB88` | `00031600` | `8000612C` | UpperCase 同型 |
| `0x16FB8C` | `00021603` | `07002010` | UpperCase 同型 |

ASCII 路径语义逐位不变（`v0` 仍是零扩展字节）；高字节不再进表、不再回写；
`at` 为该叶函数未用的临时寄存器。构建入口：`tools/dlc/build.py`
（`casefold_guard_patches()`，环境变量 `GRJS_NO_CASEFOLD=1` 可做 A/B）。

### 33.4 实机验证（v32）

- ELF sha256 `24316899A4E73A56…`，Game CRC 仍 `0406EA00`；`verify.py --stage all` **40/40**；
- 小队名册实机截图：Eric Rogers → **爆破手**、Chris Corum / Stuart Terry → **突击队员**
  （`work/analysis/emu/class_probe32/cc_class_0*.png`），不再是「爆罗手 / 突击向 / 突击向员」；
- 与 v25 同类截图对照（`docs/img/compare_class_v25_v32.png`）。

---

## 34. v36：武器说明再窄 1 字 / 提示条固定 4 字 / 逐文本锚点（B组、难度）

### 34.1 武器属性右面板再缩 1 个全宽字

v31 把武器说明按 15 全宽字重折后仍偏右；v33 起改为 **14 字/行**
（`work/make_v33_trans.py`：SFXML `T0016-T0060` + LANG `G058.I047` 同改，保留「精准度{br}」小标题结构）。
v36 实机：文字右缘离金框再远约 16px，换行正常（`work/analysis/emu/wc36/wc_weapon_attr_0.png`）。

### 34.2 底部提示条「◯ 队员信息」交替 = 0.7s 定时器在两条 LANG 文本间切换（不是滚动）

静态分析（详细报告 `docs/REPORT_HINT_CYCLE.md`）：
- 界面类 = 单人小队设置（构造 `0x2B7D30`，vtable `0x5AB580/0x5AB5F0`）；
- tick `0x2C86C0`：0.7s（double @`0x58F188`）到点翻转字节 `0x7A4`；
  `0x2C87A0 beqz v0,0x2C8800`：`0x7A4!=0` → 槽 2 文本 = `G058.I029`「信息」；
  `0x7A4==0` → 语境分支：名册 `0x6DA`→`I229`「队员信息」、装备焦点→`I572`「武器」、属性焦点→`I1253`「统计」。
- 英文原盘同样在 `Info`⇄`Soldier` 之间切，只是两个都是 2 字不明显；空间量测 4 字态 149px、右侧还余 50px ⇒ 无需改宽度。

**v35/v36 修复（2 个 ELF 词，无 cave）**：

| VA | 原词 | 新词 | 作用 |
|---|---|---|---|
| `0x2C87A0` | `beqz v0,0x2C8800` | `b 0x2C8800` | 永远走语境分支：名册恒「队员信息」、装备焦点恒「武器」、属性焦点恒「统计」 |
| `0x2B8578` | `ori a2,v0,0x1D`（I029） | `ori a2,v0,0xE5`（I229） | 激活初值即 I229，消掉进入后 ≤0.7s 的「信息」闪 |

v36 实机连拍 24 帧：`◯ 队员信息` 字节完全一致（无交替），见 `docs/img/compare_hint_v25_v36.png`。

### 34.3 逐文本上下修正：cave D（只对指定文本加偏移）

此前锚点 cave A/B/C 按 y 区间整体加减（菜单 −3、目标行 −6、底栏 −3），
导致 B 组标题与难度三项等列表文字整体偏高。v36 新增 **cave D（VA 0x57D1A8，168B 零岛）**：
在 cave A 之后、bottom/cave C 之前，按 **绘制字符串前 4 字节** 匹配，命中才额外下移：

| 字符串 | 首 4 字节（小端） | 额外 dy |
|---|---|---|
| 新兵 | `B3A2E9A1` | +6.0 px |
| 老兵 | `B3A2A2A5` | +6.0 px |
| 精英 | `FEA3B7A2` | +6.0 px |
| B组 | `0000C442` | +4.0 px |

规则表在 `tools/dlc/build.py` 的 `_CAVE_D_RULES`，加减 px 直接改数字即可（重建后即生效）；
未命中的文本完全走原 cave A→bottom→cave C 逻辑，行为不变。

实机（v36）：
- 战役选择界面 新兵/老兵/精英 回到行内居中（`docs/img/compare_difficulty_v32_v36.png`）；
- 小队设置 B组标题下移，与 A组同一视觉基线（`docs/img/compare_bgroup_v32_v36.png`）；
- 简报正文 / 任务目标 / 主菜单 / 角色说明 / 武器属性 等未命中规则的界面均无变化（回归截图同目录）。

### 34.4 版本状态

- **v36 = 当前候选**：v32 兵种名根因修复 + v31 武器说明折行（14 字）+ v35 提示条固定 4 字 + v36 逐文本锚点。
- ELF sha256 `7b24f3373382b74d…`；**Game CRC 变为 `82185737`**（PCSX2 旧即时存档需新开档/改名）。
- `verify.py --stage all` **40/40**；ELF 补丁 56 段。

### 34.5 v40：队员姓名行也纳入逐文本锚点（cave E）

用户澄清「A组居中、B组下面的人名靠上」指的是 **B 组三行队员姓名**（R. Perry / E. Rogers / C. Escobar），不是 B组标题。
v40 增加 cave E（VA 0x57D598，96B）：当 **y ∈ [230,330]** 且字符串首 4 字节满足 (w>>8)&0xFFFF == 0x202E（形如 X. ，即 名字首字母 + '.' + 空格）时，额外 dy += 3.0。
规则常量在 	ools/dlc/build.py 的 _NAME_ROW_Y / _NAME_ROW_DELTA，可直接改数值。

同时 cave D 的 4 条精确匹配规则仍优先命中（新兵/老兵/精英 +6、B组 +4）；两条 cave 都只改命中的文本，
其余文本仍走原 cave A→bottom→cave C 的旧逻辑。

注意：0x57D0C4 处的零岛在启动时会被游戏数据覆盖（v37/v38 实测启动崩溃），已换到 0x57D598 并通过整段启动/进屏验证。

---

## 35. v42：折行 token 化 + 队员姓名/难度再下移（用户截图反馈轮）

用户截图指出三处残留：
1. 武器说明折行把英文/数字拆断（`45/mm`、`由2./52公斤`、`M2/03` 等）；
2. B 组下面三行队员姓名仍偏高（A 组居中）；
3. 战役选择界面难度三项（新兵/老兵/精英）仍偏高。

### 35.1 折行：token 感知（tools/dlc/wrap_sfxml.py）

原实现按单字符宽度贪心折行，ASCII 0.5 单元，断点可能落在词/数字中间；
v42 改为 **token 化**：
- `{{BTN:xxxx}}` = 1 单元、不拆；
- 连续 ASCII 串（`[A-Za-z0-9.,%+/\'-]`，如 `M16A2`、`5.56`、`2.52`、`600发`前段）= 一个 token，整体不拆（超宽时独占一行）；
- 其余按 CJK 1 单元 / ASCII 0.5 单元；
- 行首不留空格、行首不排收尾标点。

效果：`M4 卡宾枪是 M16 步枪的缩短版 / 本。它发射同样的 5.56 x 45mm / 弹药，并使用同样的弹匣。`
不再出现 `45/mm`、`由2./52公斤` 之类拆断（`docs/img/compare_weapon_wrap_v40_v42.png`）。

### 35.2 逐文本锚点参数调整（cave D/E）

| 文本 | v40 | v42 |
|---|---|---|
| 新兵/老兵/精英 | +6px | **+10px** |
| B组标题 | +4px | +4px（不变） |
| 队员姓名行（y235–345 且形如 `X. `） | +3px | **+8px** |

实机：B 组三行人名（R. Perry / E. Rogers / C. Escobar）回到蓝条内居中，与 A 组一致；
难度三项在暗条内居中（`docs/img/compare_bnames_v36_v42.png`、`compare_difficulty_v40_v42.png`）。

### 35.3 状态

- v42 候选：ELF sha256 `979C1B6B…`，Game CRC `1FEFDC28`，verify 40/40。
- 仍待用户确认：训练列表（训练1–7）、快速任务列表（C01…C08）等界面的行内文字上下位置是否需要同样逐条微调。

---

## 36. v46：折行空行根因 + 锚点“去区间化”统一基线（列表类界面）

### 36.1 武器说明“多出单个换行”的根因

- 引擎 **DrawString 不折行**；自动折行在文本控件方法 `0x21B620`（vtable `0x5A7240`），宽度
  `s7 = [widget+0x40] − [widget+0xB4]`，字符记账 `CharWidth + font[+0x18]`（实测 font+0x18=1 ⇒ 全宽 17px、ASCII 9px）。
  cave M 的 500 上限因指令编码问题实际可疑（见 work/analysis/wrap2/FINDINGS.md §6），但本问题与它无关。
- 真正原因：译文 CSV 的 T0016–T0060 中有 26/45 条残留字面 `\r\n`（4 个字符），
  注入脚本把它反转义成 CRLF 再转成 **一个额外 `{br}`**，与手工 `{br}` 叠加成 `{br}{br}`（空行），
  拆转义时还会留下 1–2 字孤行。
- 修复：只对 T0016–T0060 清除字面 `\r\n` 后按 **14 全宽字 + 17/9px 引擎口径** 重折（词不拆、标点不落行首），
  候选表 `work/analysis/wrap2/translations_v43_candidate.csv`（即 `translations_v35.csv`）：
  251 行 / 0 空行 / 0 二次折行 / 最宽 243px（金框 263.9px）。

### 36.2 列表行上下错位的根因与“去区间化”锚点

- 旧锚点：cave A 居中 `(CH−16)/2` + cave C（40≤y<400 −3）+ bottom（y≥270 −3）⇒ **y=270 处 3px 跳变**、
  y=400 处再反跳，训练 6/7、快速任务 C05+、练习 5、右侧标题等正好跨阈值，出现“部分居中部分靠上”。
- v46 改为**统一基线**：cave A 的 dy 再加常量 −3（`GRJS_ANCHOR_DY_OFFSET=-3`），
  同时把 mid/bottom 两段置 0、停用 cave C/D/E；效果：
  - y<270：与旧版逐像素相同（主菜单/简报/副标题不回归）；
  - y≥400：与旧版相同（底栏不变）；
  - **y 270–400：统一下移 3px，跨 270 的跳变消失**（训练/战术/快速/难度列表同屏一致）。
- B 组三行队员姓名另加 cave F（`0x57D1A8`）：`265≤y≤340` 且形如 `X. ` → 再 +5px
  （A 组 y<265 不受影响），解决“B 组人名偏高”。
- 难度中央选择器不再被字符串规则误伤（cave D 停用），与上下箭头对齐。

### 36.3 状态与验证

- v46 候选：ELF sha `550A2E8F…`，Game CRC `A73037FC`，verify 40/40。
- 已实机核对：小队名册（A/B 组人名、开始按钮）、战役难度（三行+选择器）、训练列表 1–7、主菜单、简报。
- 待核对：战术演习列表（练习 1–5）、快速任务列表（C01–C08）——模拟器导航每次按键跳 2 行、无法稳定进入这两屏，
  但二者与训练列表同属 vtable 0x5A7240 列表控件，统一基线后应与训练一致。

---

## 37. v46 验证记录（列表类界面统一基线）与模拟器导航限制

### 37.1 已验证（v46 实机截图）

| 界面 | 结果 | 截图 |
|---|---|---|
| 小队设置（分配后） | A/B 组三行人名均在条带内居中；开始按钮文字居中 | `docs/img/roster_v46.png` |
| 战役难度 | 新兵/老兵/精英三行与中央选择器/箭头一致 | `docs/img/campaign_v46.png` |
| 训练列表 | 训练 1–7 同一基线（不再第 6 行跳 3px）；右侧「越野训练」标题居中 | `docs/img/training_v46.png` |
| 武器属性 | 无 `{br}{br}` 空行/孤行；行宽不越金框 | `docs/img/weapon_attr_v46.png` |
| 主菜单 / 简报 | 与 v42 一致（y<270 与 y≥400 文本像素级不变） | `work/analysis/emu/camp46/step_00_mainmenu.png` 等 |

### 37.2 未能在模拟器内验证：战术演习、快速任务

该两屏在单人菜单第 1/3 行（奇偶性），而 PCSX2 PostMessage 注入单次按键实测固定移动 **2 行**
（训练↔战役），无法到达奇数行；已尝试 hold 4–30ms、L1/R1/方向键/Select/Start 均不移动或仍跳 2 行。
两屏与训练列表同属文本控件 vtable `0x5A7240`，v46 的“去区间化统一基线”对同控件必然同样生效；
需用户实机确认（若仍有个别行偏差，可按行给 `_CAVE_D_RULES` 式规则微调）。

### 37.3 结论

v46 的修复方向（常数 dy + 无 y 区间跳变 + 按文本规则微调）已消除“同一列表部分居中部分靠上”的根因；
剩余验证依赖用户实机反馈。

---

## 38. 用「即时存档改菜单光标」进入奇数行，验证战术演习/快速任务（v46）

PCSX2 PostMessage 注入单次按键固定移动 2 行，奇数行（战术演习/快速任务）无法直接导航。
解决办法（仅用于取证，不影响成品盘）：
1. 在单人菜单存即时存档（row0 与 row2 各一份）；
2. 解 p2s 里的 eeMemory.bin，diff 两份 RAM：DLC 版光标字段 = **0x116CB1C**（4 字节，row0=1, row2=3）；
3. 把值改成 2/4 后重打包 p2s（ZIP_STORED 亦可被 PCSX2 接受），F3 载入 → 高亮直接落在目标行；
4. 按 Cross 进入并截图。

v46 实机结果：
- **战术演习**（docs/img/tactics_v46.png）：练习 1–5 行内文字基线一致，右侧「射击」标题居中；
- **快速任务**（docs/img/quickmission_v46.png）：C01–C08 行内文字基线一致，右侧 难度/游戏类型 选择器与标题同屏一致。
- 工具：work/patch_state.py、work/load_menu_state.py、work\save_spmenu_state.py、work\scan_spdiff.py。

若用户实机仍见个别行偏差，可按行加 _CAVE_D_RULES 式规则（按 y 范围+字符串前缀）微调，不再动全局基线。

---

## 39. 训练/任务提示框（屏幕上方消息条）折行研究（v49–v52 实验）

### 39.1 现象与结论

- 现象：训练关顶部提示条（如“越野训练将教你如何在场景中移动……”）里，
  有的行在句子/词组中间提前断行，有的行宽到框边才断；每行约 30 个汉字。
- 提示框文本走 **另一条绘制/折行路径**，与菜单/简报的 SetMarkupText 不同：
  - `{br}` 不被解析，会作为普通字符显示（“b r”字样）⇒ 不能用标记强制断行；
  - 文本里插 `\n` 也不起作用（编码阶段被丢弃，渲染与原文一致）；
  - 全局折行宽度上限 cave M（0x21B6AC 处，clamp s7≤500）对该提示框**不生效**
    （实测仍是 30 字/行，说明该框折行时 s7 来自别处/另一次计算）。
- v52 中新增 cave H2（0x57D280）：ASCII 单词不跨行，实测 “START” 不再被拆成 “STA/RT”；
  但“每行 29 汉字”还差 1 字（框自然宽度约 30 字）。

### 39.2 下阶段定位方案（未完成）

1. 在提示条显示时存即时存档，解 EE RAM；
2. 用已编码的提示文本字节在 RAM 中定位 RSString data 指针，向上找文本控件对象；
3. 读 `[widget+0x40]`、`[widget+0xB4]`（折行宽度 = 两者之差）与 `[widget+0x?]` 宽高字段；
4. 找到该控件的宽度来源（布局常量或创建代码立即数），把 30 字改为 29 字（约 −17px），
   只作用于提示条控件，避免影响其他面板。

### 39.3 附：磁盘清理

删除无用构筑镜像（v21–v51、probe*）、模拟器运行时目录与 >50MB 的 emulog，
释放 **118 GB**（C: 7.8 GB → 125.8 GB）。保留 `work/builds/v52.iso`（实验）、
`work/builds/FINAL/GR_JS_ZH_v46_candidate.iso`（当前交付）与原始 EN 盘。

---

## 40. v58：提示框折行只做“英文词不跨行”，29 字宽度待继续

### 40.1 v58 内容（干净、可交付的实验版）

- 基于 v46（去区间化锚点 + cave F + 武器简介 CRLF 修复），**新增 cave H2**：
  在 0x21B620 折行的“断点行首修正”处，若断点落在 ASCII 单词中间，则回退到单词开头，
  保证 `START`/`M18`/`DEAD` 等英文词不被拆成两行。
- 未加入任何全局宽度 clamp：cave M / cave M2 均已从补丁表移除，避免影响其他面板。
- 实机验证：训练提示条、战术/快速任务、主菜单、简报、武器属性、小队设置均正常启动；
  其中简报/武器属性/菜单与 v46 逐像素一致（H2 只在折行断点生效，短行不触发）。
- ELF sha256 `1F81476C…`，Game CRC `A5049565`，verify 40/40。

### 40.2 为什么 29 字/行还没做到（关键证据）

- 训练提示条（屏幕上方消息框）**不使用文本控件折行函数 0x21B620**：
  在提示条显示期间存即时存档并读诊断计数器，cave M/M2/H2 的进入计数均为 0；
  即该框在别处自行排版。
- 该框的折行宽度约为 30 个全宽字（实测行宽 514px / 17.1px），
  且文本中 `{br}` 会原样显示、`\n` 被编码器丢弃 ⇒ 无法用文本控制断行。
- 因此要严格 29 字，必须找到提示框自己的排版函数/宽度常量并只改这一处；
  当前已缩小范围（DrawString 调用者 hook 试验中），但当天未完成。

### 40.3 后续计划

1. 用 DrawString 入口 hook（记录 a0/a1/ra）定位绘制提示条文本的调用者；
2. 反汇编该调用者，找行宽常量（约 514–520px 或按字符数 30）；
3. 只对提示条控件减 17px（30→29 字），回归核对训练 1–7、任务更新提示；
4. 不动其他界面（简报/武器/菜单/名册已在 v46/v58 验证）。

---

## 41. 定位提示框排版的尝试（失败记录与下一步）

### 41.1 已确认

- 训练提示条（HUD 消息框）**不经过** 0x21B620 折行函数：
  提示条显示时的即时存档里，cave M/M2/H2 计数器全为 0。
- 该框每行约 30 个全宽字（实测 514px / 17.1px），`{br}` 原样显示、`\n` 被丢弃。
- 因此只能改提示框自己的排版代码/宽度常量。

### 41.2 本轮尝试（均未成功，但排除了错误路线）

1. **条件式 DrawString hook**（0x219640，检查 s3/s2 是否指向文本区）：
   存档里诊断槽全 0 ⇒ 条件从未命中（a0 很可能不是 RSString，或该行未走此调用）。
2. **无条件环形缓冲 hook**（记录每次 DrawString 的 a0/a1/a2/a3/t2/ra 到 0x569400）：
   编译通过（v61），但启动卡死。原因候选：
   - 0x219640 处 clobber 了 t0/t1/t9，而它们可能仍是 DrawString 的后续参数；
   - 0x569400 可能落在启动期会被使用的数据区；
   - hook cave 用了 t 寄存器而未保存/恢复。
3. 静态搜索宽度立即数（490–545 的 addiu/ori）得到 2000+ 处，未定位到单独作用于提示框的常量。

### 41.3 下一步（更稳的做法）

1. hook 时**保存/恢复所有会破坏的寄存器**（t0–t3、t9 先存栈或 k0/k1），并只用 k0/k1 做 scratch；
2. 环形缓冲改放**已验证安全**的零区（如 0x57D300 之后的自由区），且只记录 `ra`（4 字节/调用）；
3. 拿到提示条文本的 DrawString 调用者 ra 后，反汇编该函数找行宽常量；
4. 或采用“二分试探”：把候选宽度常量从 30 字改 29 字，逐屏观察训练提示条行数变化（每次只改一个候选，便于回退）。

### 41.4 当前交付

- v58 候选（H2 英文词保护，其余界面零污染）仍为可交付实验版。
- 29 字严格化未完成，v59–v61 仅诊断用途，已从构筑表移除。

---

## 42. cave M（0x21B6AC 宽度上限）实验：会破坏提示框渲染，已回退

- v65：在 v58 上恢复 cave M（s7 上限 494，含 s4 同步）。
  训练提示条只显示 1 行、其余行消失，行尾伸出框外被裁切。
- v66：去掉 `daddu s4,s7` 同步，仅 clamp s7。
  提示条文字横向溢出框外、与下一行重叠，仍然只画 1–2 行。
- 结论：0x21B6AC 处的 s7 不是提示框的“可用行宽”（至少不是唯一状态量），
  强行 clamp 会破坏控件内部的布局/裁剪状态 ⇒ **不能再从这里改提示框宽度**。
- 已回退：cave M 相关补丁全部移除，build.py 与 v58 的干净状态一致
  （ELF SHA256 `1F81476C…`，Game CRC `A5049565`，verify 40/40）。

### 下一步唯一正确方向

提示框是**独立于文本控件折行的 HUD 排版代码**。需要：
1. 在 DrawString 被提示框调用时抓到调用者 ra（hook 时要保存 t0–t3/t9，且 scratch 放在安全零区）；
2. 反汇编该 HUD 函数，找到行宽/字符数常量（约 514–520px 或 30 字）；
3. 只改这一处常量（30→29 字，约 −17px），并回归训练 1–7。

在此之前，v58 为最佳可交付：英文单词不跨行、其他界面零污染。

---

## 43. 提示框“严格 29 汉字/行”的最终解法：行尾插空格顶宽

### 43.1 原理

提示框不受文本控件折行（0x21B620）控制，自身按约 514px 宽折行（≈30 个全宽字）。
与其改其排版代码（已验证会破坏渲染），不如让引擎**在我们要的位置断行**：

- 在当前行累计到 29 个全宽字（ASCII 计 0.5）后，插入 **1 个半角空格**；
- 空格宽度 9px：本行累计 29×17+9 = 502px ≤ 514px 放得下；
- 下一个汉字使宽度 502+17 = 519px > 514px ⇒ 引擎**恰好在空格后断行**；
- 行尾空格不可见，屏幕可见部分正好 **29 个汉字**。

### 43.2 实施范围（只改提示/消息文本，不碰其他界面）

`translations_v41.csv` 仅对以下 LANG 组做 29 字空格对齐（其余资源逐字节不变）：
- 训练提示：G012–G018（训练 1–7 全部提示文本）
- 任务更新/提示：G027、G032、G048、G049

不动：G058（各 UI 面板，宽度 14/19 字）、带 `{br}` 的简报正文（G019–G026 等）、
SFXML、菜单、名册、武器属性。

### 43.3 实机验证（v73）

- 训练 1：`越野训练将教你如何在场景中移动。用左摇杆前后左右移动，用右`（29）
  / `摇杆转身和调整视角上下。用力推左摇杆即可奔跑。随时按 START` / `键退出训练。`
  —— 行宽 29、START 完整、无溢出；
- 训练 7：`这里是指挥训练区。你要学习如何使用指挥界面向小队的其他队员`（29）
  / `下达命令。随时按 START 键退出训练。` —— 由原来的 30 字变为 29 字；
- 简报页、名册、战役画廊与 v46/v58 逐像素一致（仅提示类文本被替换）。

### 43.4 交付

- `GR_JS_ZH_v73_candidate.iso`：ELF `1F81476C…`，Game CRC `A5049565`，verify 40/40。
- 如后续某些提示文本被显示到更宽的容器里（不会断行），行内会多出 1 个半角空格宽的间隙，
  可把该组从 `make_v39_trans.py` 的 GROUPS 里移除后重生成。

---

## 44. 简报「任务目标」行被 y 轴统一基线带偏 3px 的修复（cave G）

### 44.1 现象与根因

- v46 为了让训练/战术/快速任务的列表跨 y=270 不再跳变，把 y≥270 的所有文本统一改成了
  `dy = (CH-16)/2 - 3`（原先 y 270–400 是 `-6`，y≥400 是 `-3`）。
- 简报页「任务目标」列表的分隔/分栏线是**固定 screen-space** 绘制的，正文行被整体 +3px 下移后，
  第 2/3/X 行就与分栏线错位（第 1 行 y<270 未受影响）。
- 实测（capture 像素，行墨迹中心）：
  - v42（改动前）：item2 728.4 / item3 766.9 / item4 802.9
  - v73（改动后）：item2 732.3 / item3 764.5 / item4 800.2
  - 差值≈7 capture px ≈ **3 游戏像素**，与上述推导吻合。

### 44.2 修复：cave G（0x57D2F0）

在 cave F 之后串入 cave G：仅对 **y≥265** 且首字节满足以下条件的文本再 `-3px`：
- 数字 + `'.'`（"1. …" "2. …" "3. …"）；LANG 编码首 4 字节如 `31 2e 20 ..`
- 首字节 `'X'`（"X - 无队员阵亡"）；编码 `58 20 2d 20`

实现要点（踩过的坑）：
- `srl` 的目标寄存器要写 rd 字段（曾误写 0x000A5A02 → rd=t3，pattern 永远不匹配）；
- cave 内 `j` 必须是 **绝对地址**（`(PC>>2)`），写成相对偏移会跳到 0x4017 导致崩溃；
- cave G 只需 100B，放在 H2 之后的 0x57D2F0 零区（H2 结束于 0x57D2EC）。

### 44.3 验证（v80）

- 任务目标行墨迹中心回到 v42 的位置：item2 728.4 / item3 766.9 / item4 802.9（item1 680.5 不变）；
- 视觉核对（v42 / v73 / v80 三联图）：v80 与 v42 一致，行居中于分栏线之间；
- 训练提示 29 字/行不受影响（y<265），START 仍完整；
- 其他界面（菜单、名册、武器、战役/战术/快速任务列表）未改动。

---

## 45. 启动「Loading... / Please wait!」文本汉化

### 45.1 位置与结构

ELF 里有两张 **5 语言载入提示槽表**（纯 ASCII 字符串，原位覆盖，指针不变）：

| 表 | 文件偏移 | 内容 |
|---|---|---|
| A | 0x487040–0x487109 | FR「Chargement en cours... / Veuillez patienter」、DE、IT、ES、EN「Loading... / Please wait」 |
| B | 0x48D810–0x48D868 | 同上 5 语言的单行「载入中…」（另一处对话框） |

槽长按相邻字符串间隔计算；英文首行 10 B（"Loading..." + NUL = 11 B）。

### 45.2 做法

`build.py --stage spec` 新增 `BOOT_TEXT_SLOTS` / `boot_text_patches()`：
- 用 `textlib.Charset` 把中文编码成对偶码字节（与 LANG 注入同一套码表）；
- 按槽长选文案，原位写「中文 + NUL + 零填充」，补丁长度对齐 4 字节（ELF 补丁表要求）；
- 5 语言全部换成中文，避免语言配置不同而漏翻：
  - 长槽：「正在载入中...」/「请稍候，正在载入...」
  - 中槽：「载入中...」
  - 短槽（DE 8 B）：「载入...」
  - wait 槽：「请等待...」

### 45.3 实机验证（v81）

- 启动约 99 s 的加载圆环画面：`Loading...` → **「载入中...」**（游戏字体渲染，字形正常），
  见 `docs/img/loading_v81.png`；
- 其他界面不受影响（只改 ELF 字符串槽）；
- verify 40/40，ELF `4DA16CCF…`，Game CRC `E0325951`。

### 45.4 关于「读盘提示是预渲染纹理」

- PS2 开机时主机的 **"Reading disc..."** 是 **BIOS/主机固件** 绘制，不在游戏 ISO 内，
  无法通过改盘汉化；
- 本游戏自己的加载画面背景（load-screen 纹理）经检查**不含烘焙文字**，"Loading..." 是文本，
  已按上面方案汉化。若后续看到某屏确有烘焙文字，需要单独做纹理重绘（LOADING.PAK 的纹理段是
  ty=2 压缩，压缩算法尚未识别，暂不可无损替换）。

---

## 46. 开机「读盘/记忆卡」提示属于 PS2 BIOS，不属于游戏盘

用户反馈的「插入光盘后一开始的读盘提示」（截图里是 Accessing memory card (8MB) ... in MEMORY CARD slot 1、
以及更早的 Reading disc...）是 **PS2 主机系统固件（OSDSYS/BIOS）** 绘制的界面，不在游戏 ISO 内。

证据：
- 在英文原盘 ISO 中检索这些整句（ASCII 与 UTF-16LE），命中 **0**：
  Accessing memory card / Do not remove / MEMORY CARD slot / Reading disc；
- 游戏 ISO 只能替换 GR.IMG/MENU.IMG 内的资源与 ELF，无法影响 BIOS 代码/字库；
- PCSX2 配置里 EnableFastBoot = true 时会跳过 BIOS 浏览器/记忆卡界面，直接进游戏；
  若看到该界面，说明是「启动 BIOS」/Fast Boot 关闭，或使用的是主机实机。

处理建议：
1. **游戏侧**：v81 已把游戏自己的加载圆环文本 Loading... → 载入中...（ELF 字符串槽，见 §45），
   实机验证通过；
2. **BIOS 侧**：要汉化这些 BIOS 对话框只能改 **BIOS ROM**（受版权保护，且 SCPH-70000 等型号的
   EROM 是加密/压缩的），不属于本汉化盘的交付内容；可使用社区完整中文 BIOS（自行承担版权风险）；
3. 若只需跳过该画面：PCSX2 设置 → BIOS → 勾选 **Fast Boot**，并选择「Boot ISO (fast)」启动。

### 附：与本体汉化工程（reference/base_zh146）的对照

检索 reference 会话（base_zh146）后确认：本体汉化把**游戏自己绘制**的「读卡/记忆卡对话框」（标题 Press START 之后、
带 PS2 主机底图的那一屏）当作 RES 文本处理，字符串是 G58.I797/I791（PROGRESS §27，GR_ZH63 修复居中与断句）——
也就是说**游戏内**的读卡提示是可翻译的，并非 BIOS。

本资料片里与「Accessing memory card (8MB) … Do not remove …」完全对应的 LANG 条目是 **G058.I1162**
（另有 I1147/I1156/I1163/I1167 等同一族）；v81 已把这些全部替换成中文（中文串回读确认）。

同时做了两项排除：
1. 原盘里这句英文**只有 1 份**：GR.IMG #576 EN_STRINGS.RES（差异扫描全 3111 个条目，其余 0 命中）；
   v81 里该资源已整体替换为中文，全盘再搜 Accessing memory card = **0 命中**；
2. 预渲染纹理核对：把 BOOT_NOPAD.RSB / BOOT_NOPAD_1.RSB / LANGUAGE_SELECT.RSB / SHELL_BGD_PS2.RSB /
   LOAD_NEW_1/2.RSB / LOAD-CIRCLE.RSB 全部按 RSB（28B 头 + 256×RGBA 调色板 + 8bpp 索引）解码为 PNG：
   分别是「不支持手柄」5 语言预渲染图、语言选择旗帜、世界地图底图、加载渐变/圆环——**没有**「Accessing memory card」
   这句话的烘焙文字。

因此：用户截图里的英文对话框是 **PS2 BIOS/OSDSYS 画面**（PCSX2 用所选 BIOS 渲染，原盘/汉化盘都一样）；
而游戏内按 START 后的读卡对话框文本已在 v81 汉化，如仍见英文需按具体出现时机再核对资源。

---

## 47. 最终版 v1.0 交付说明（2026-10-26）

最终成品：`work/builds/FINAL/GR_JS_ZH_v1.0_final.iso`
- sha256 `29883b66b8e1d3f2cbedf283deeb956484260b041d918aba3ec37495611b4d24`；ELF `4DA16CCF…`；Game CRC `E0325951`；verify 40/40；
- ELF 侧最终补丁集：DBCS v2 + 图标码换区 + 行盒锚点 + cave F（B组姓名 +5px）
  + cave G（简报任务目标行 −3px）+ 串越界/NULL 守卫 + 大小写折叠守卫
  + cave H2（折行英文词保护）+ 启动载入槽表 15 处汉化；
- 已知范围外：PS2 BIOS 读盘/记忆卡界面（见 §46）。
