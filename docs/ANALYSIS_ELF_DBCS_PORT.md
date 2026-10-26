# ANALYSIS_ELF_DBCS_PORT —— DBCS 移植蓝本（本体汉化 → DLC）+ JS_ZH19 蓝本与修复 + 补丁规格 v2

> 执行者：elf-analyst（task-2）· 2026-10-21 · 只读原盘/ELF，产物全在 `work/analysis/elf/`
> 关联主报告：`docs/ANALYSIS_ELF.md`（ELF 基础信息 / DBCS 定性 / 闸门 / 四件套 / CRC / 字符串）
> 工具：`tools/analysis/elf_probe.py`（ELF 通用）、`elf_port.py`（本体差异）、`elf_js19.py`（JS19 取证）、
> `mipsasm.py`（轻量 MIPS 汇编，83 条已知字节自测）、`dbcs_spec.py`（规格生成+回读自证）
> cave 源码：`tools/analysis/caves/dbcs_cave_dlc.s`

---

## 0. 结论速览

| # | 问题 | 结论 |
|---|---|---|
| 1 | DLC 引擎原生支持 DBCS？ | **不支持**。`wctomb` 是单字节桩；DrawString 逐字节 + 游标+1；CharWidth/UV 都按单字节 `andi 0xFF` 索引 224 条 FT 记录；全 .text 无 DBCS lead/trail 闸门（见主报告 §4） |
| 2 | 本体汉化的 DBCS 是"数据+少量常量"吗？ | **不是**。"本体英文 ELF → 汉化最终 ELF" 共 **481 段 / 2089 字节**差异，其中 **53 处跳转重定向**指向**新增 cave 代码**（cave A `0x416E00..0x417800`、cave B `0x565600..0x565B00`，~2.5 KB 手写 MIPS）。数据层不够，**必须 ELF 补丁** |
| 3 | 这些 cave 能直接搬到 DLC？ | **不能直接搬二进制**；但**可以按同构重汇编**。DLC 的 RSFont/RSFontMgr 数据结构字段偏移与本体**逐项一致**（font+0x14/0x18/0x1c/0x24/0x28；def+0x20/0x38/0x44；10B FT 记录 +1=宽度 +2/+4/+6/+8=U0/V0/U1/V1），但代码生成不同（本体用 `pcpyld` 把参数搬进 128 位寄存器，DLC 用 `move`，同函数指令序列相似度仅 30–50%）⇒ **必须重新汇编**，不能按字节平移 |
| 4 | JS_ZH19（上一会话构筑）是什么？ | **同源移植的半成品**：其 decoder 与本体汉化 cave **逐指令同构 27/27=100%**、CharWidth 82%；几何（NCOL=62/CW=8/CH=16/Y0=2/SKIP_ROWS=3）+ gate 0xAE（13 lead≈1222 槽）**已被 js19-recovery 的图集 OCR 实测验证自洽**（其数据层 2,275 条译文已完整还原，见 §6.3）；cave 放在死函数区 `0x1808A8`。真正的问题在 FONT.RES 尾部与 NULL 防护层（问题 5） |
| 5 | JS_ZH19 为什么 38s 崩溃？ | **双重原因**：① 数据层——它重写的 FONT.RES **尾部样式表 off-by-22 损坏**（count=15 但实际 16 条，第 8 条记录被截断 22B，展开 7488B = 原 7466+22）；② ELF 层——其 CharWidth cave **删掉了原版 `font+0x24` 固定宽度早退**、且**无 def==NULL 兜底**，任何"未加载/坏"字体都会硬 fault。证据：emulog 50 条 TLB Miss / 3 个唯一站点，`pc=0x1809B8 addr=0x44`（a2=NULL）、`pc=0x18097C addr=0x20`（a0=0xFFFFFFF8）、`pc=0x208F30 addr=0x24`（a0=0xFFFFFFFC，**原版代码**也被波及 ⇒ 字体指针本身就是垃圾，指向数据结构损坏） |
| 6 | DLC 补丁 v2 可行性 | **可行**。`tools/analysis/dbcs_spec.py` 已生成并自证：**25 站补丁 + 1000 B cave**，原字 24/24 校验通过、回读 PASS、补丁后 **Game CRC = FD9E6AED**。cave 落点 `0x1808A8`（JS19 实机验证过的死函数区，1008 B ≥ 1000 B） |
| 7 | 与 font-engineer 几何的对齐 | cave 的 `GATE_HI/NCOL/CELL/Y0/SKIP_ROW/SKIP_ROWS/PAIR_BASE` 全部 `.equ` 参数化，默认 = **0xBA/64/16/3/12/2/224**（与本体最终 ELF 立即数逐字一致）。改几何只改 6 个常数重汇编 |

---

## 1. 素材与身份（全部实证）

| 代号 | 文件 | 字节 | sha256 | Game CRC |
|---|---|---|---|---|
| **DLC-EN** | `third_party/orig/ps2/[PS2] … Jungle Storm (U).iso` @LBA296 | 5,319,720 | `cf29cabe…baee7eee` | `DE1E4DEE` |
| **BASE-EN** | `…Locolization/third_party/orig/ps2/slus_out/SLUS_206.13` | 37,453,732 | `5fec662f…cb94105` | （本体代码的基线） |
| **BASE-ZH** | `…Locolization/work/builds/FINAL/…(ZH_CN).iso` @LBA295 | 37,453,732 | `a0c8499c…40ba12e` | `653FBF69`（本体工程交付口径） |
| **JS19** | `%LOCALAPPDATA%\PCSX2\cdvd-dump\JS_ZH19 (2026-10-21 16-19-47).dump` 提取 | 5,319,720 | `80e25599…0594f6` | `3A320B22`（= PCSX2 日志 CRC，证明提取逐字节正确） |

- BASE-EN/BASE-ZH 有 `.symtab`（38,721 条符号）——**本体英文 ELF 有符号表可用**，本报告的函数名全部来自它。
- DLC-EN **已 stripped**（shnum=11，`symtab` size=0）⇒ DLC 侧函数只能靠"符号表函数指纹 + 字段偏移 + 调用图"定位，已全部定位（§3）。
- 三份 ELF 都从 ISO 内按 ISO9660 root 目录读取（`elf_probe.py` 内置只读 ISO 解析），缓存到 `work/analysis/elf/*.elf`，可复现。

---

## 2. BASE-EN → BASE-ZH 全量差异（DBCS 补丁清单）

工具输出：`work/analysis/elf/zh_diff.txt`、`zh_diff.json`、`zh_redirects.txt`、`zh_caves.txt`。

```
diff runs 481 / bytes 2089
分类统计: {'cave': 319, 'other': 92, 'text-stack': 29, 'text-stack-2': 15, 'guard': 10, 'layout': 16}
```

### 2.1 字体/文本栈站点（text-stack，29 站 + text-stack-2 15 站）

| VA | 原 4B → 汉化 4B | 作用 |
|---|---|---|
| `0x219A74` | `FFBF00A0` → `0815964C` | DrawString: `sd ra,0xA0(sp)` → `j 0x565930` 拦截器（给 DBCS 文本加行高，再补回 ra 保存） |
| `0x219ADC` | `44820000` → `08105C80` | DrawString: `mtc1 v0,f0` → `j 0x417200`（宽度==0x1A 时改 0x10 的特例） |
| `0x219BCC` | `0C102FF2` → `0C105BB4` | **`jal wctomb(0x40BFC8)` → `jal 0x416ED0`（DBCS decoder）** |
| `0x219BD0` | `27A400DF` → `27A400DE` | 解码输出格 `sp+0xDF` → `sp+0xDE`（1B → 2B 格） |
| `0x219BD4` | `83A500DF` → `97A500DE` | `lb` → `lhu`（读解码值） |
| `0x219BE4` | `83A500DF` → `97A500DE` | 同上（第二处读） |
| `0x219BD7/0x219BE7/0x219CA3` | `83`→`97`（opcode 低字节） | `lb`→`lhu` |
| `0x219C09/C11/C15/C95/CAD/D25/D39` | `FF`→`00`（8 处） | 图标常量 `0xFFB5/0xFFB1` → `0x00B5/0x00B1`（零扩展） |
| `0x219CA0` | `83A400DF`→`97A400DE` | 图标判定前 `lb`→`lhu` |
| `0x219DAC` | `00000000` → `93A200DD` | `nop` → `lbu v0,0xDD(sp)`（步长） |
| `0x219DAE..` | 6B | `addu s0,s0,v0`（游标 += 1/2） |
| `0x219FF4/0x21A0F8/0x21A1C4/0x21A2C4` | `addiu …,zero,1` → `0` | AddOneWord/字库管理器的 4 处标志 |
| `0x21AC74` | `0C086B44` → `08105C54` | `StringWidth`: `jal CharWidth` → `j 0x417150`（DBCS 测量循环 cave） |
| `0x21AC90` | `8E620018` → `0815959C` | `StringWidth`: `lw v0,0x18(s3)` → `j 0x565670`（字距按字形数 cave） |
| `0x21AD18` | `90820024`+.. → `08105BD0` | **CharWidth 函数体 → `j 0x416F40`**（cave 重建整个函数体） |
| `0x21ADE0` | `8C8A0028`+.. → `08105C14` | **ComputeCharTextureCoords 函数头 → `j 0x417050`**（cave 重建槽位→UV） |
| `0x21BD68/0x21C048/0x21CA50/0x21CB30/0x21CC08/0x21CD70/0x21CFD8/0x21D940` | `j 0x41xxxx/0x565xxx` | UI 文本布局/测量/行距/容量钳位等 8 处（DBCS 字幕、折行、滚动修正） |

### 2.2 重定向（j/jal 目标被改）共 53 处

其中 20 处指向 cave A/B（DBCS 核心 + UI 文本）；其余 33 处是四件套/守卫/布局（见主报告 §6）。
**结论：本体的 DBCS 能力 = 新增 ~2.5 KB cave 代码 + 53 处跳转重定向 + ~40 处常量/指令微调。**

### 2.3 cave 区

| 区 | VA 范围 | 长度 | 原内容 | 汉化后用途 |
|---|---|---|---|---|
| cave A | `0x416E00..0x417800` | 2560 B | Sony `sceRemove/sceMkdir/sceFormat/...` 等**游戏从不调用的 libc/sce 函数** | decoder / CharWidth / UV / 测量循环 / UI 修正块 |
| cave B | `0x565600..0x565B00` | 1280 B | 原 ELF 该段**全零填充**（`.text` 内零岛） | StringWidth 尾部 / DrawString 拦截器 / 槽位辅助 / wrap |

（复现：`elf_port.py caves --out work/analysis/elf/zh_caves.txt`，逐指令带 file_off。）

---

## 3. 本体汉化的 DBCS 新代码（逐指令 + 语义）

> 以下地址均为 VA；`file_off = VA − 0xFFF80`（BASE 的 PT_LOAD off=0x80 va=0x100000）。
> 完整逐指令 dump 见 `work/analysis/elf/zh_cave_core_0x416ED0.txt`、`zh_cave_b_0x565660.txt`。

### 3.1 Decoder cave `0x416ED0`（108 B / 27 insn；调用点 `0x219BCC`）

```
andi  a1,a1,0xFF          ; 调用者用 lb 取字节（带符号）→ 先零扩展
sh    a1,0(a0)            ; 先按单字节写入 2B 格
addiu v0,zero,1           ; 默认步长 1
sltiu t1,a1,0xA1 ; bnez → single
sltiu t1,a1,0xBA ; beqz → single     ★ lead ∈ [0xA1,0xBA)（25 个 lead）
addiu t8,s7,-1 ; slt t8,s0,t8 ; beqz → single   ; 还有后继字节？
addu  t7,s6,s0 ; lbu t3,1(t7)        ; trail = 下一字节
sltiu t1,t3,0xA1 ; bnez → single
sltiu t1,t3,0xFF ; beqz → single     ; trail ∈ [0xA1,0xFF)（94 个）
sll   t4,a1,8 ; or t4,t4,t3
sh    t4,0(a0)            ; 写打包值 (lead<<8)|trail
addiu v0,zero,2
single:
sb    v0,-1(a0)           ; ★ 步长写在 格-1 字节（DrawString 的 sp+0xDD）
jr    ra ; nop
```

**寄存器契约**（与调用者强耦合，移植时必须对齐）：
`a0` = 输出格指针；`a1` = 当前字节；`s6` = 字符串基址；`s0` = 字节游标；`s7` = strlen。
写入：`0(a0)/1(a0)` = 16 位码；`-1(a0)` = 步长 1/2。

### 3.2 CharWidth cave `0x416F40`（244 B / 61 insn；替换 `RSFont::CharWidth` 函数体）

入口承接原函数 prologue（`addiu sp,-0x10; sd ra,0(sp)`），自己负责 `ld ra,0(sp); jr ra; addiu sp,0x10`。

| 分支 | 行为 |
|---|---|
| 双字节（`srl t0,a1,8` 非 0） | `t1=(lead&0xFF)-0xA1`；`t2=(trail&0xFF)-0xA1`；`t6=94`；`mult t1,t6`（R5900 三操作数，积写 t1）⇒ `t1=(lead-0xA1)*94`；`t0=t1+t2+0xE0` ⇒ **slot = 224 + (lead-0xA1)*94 + (trail-0xA1)** |
| 越界 | `lw v1,0x44(def)`；`sltu slot,count`；不满足 ⇒ **`addiu v0,zero,0x10`（pair 宽恒 16）** |
| 记录命中 | `lw a2,0x38(def)`；`slot*10`（`sll 2; addu; sll 1`）；`lbu v0,1(rec)`（记录 +1 = 宽度字节）；`lwc1 f1,[font+0x1c]`；`mul.s f12`；`jal 0x118EE0`（取整） |
| 单字节 | `c=0x20`→`[font+0x14]`；`c=0xFFB5/0xFFB1`（图标）→20；否则 `idx=(c-[def+0x20])&0xFF`，`idx<count` → 记录宽度，否则 **clamp 到 0** |

字段偏移：`font+0x14`=空格宽，`font+0x1c`=宽度缩放，`font+0x28`=FontDefinition*；
`def+0x20`=base char，`def+0x38`=记录表，`def+0x44`=count(=224)；FT 记录 **10 B**，+1=宽度字节。

### 3.3 ComputeCharTextureCoords cave `0x417050`（236 B / 59 insn；替换函数头）

单字节：还原 `idx=(c-[def+0x20])&0xFF`、`idx<count` 判定后 **`j 0x21AE20`**（跳回原引擎的记录读取路径，读 def+0x38 记录 +2/+4/+6/+8 的 u16 UV → float）。
双字节（网格）：

```
lw    t2,0x28(a0)          ; def
lw    v1,0x44(t2)          ; count
sltu  slot,v1  ; 命中 → j 0x21AE20（若 pair 也落 FT 记录，保留兼容）
addiu t4,a1,-0xE0          ; 224
addiu t6,zero,0x40         ; ★ NCOL = 64
div   t4,t6 ; mflo row ; mult row,NCOL ; subu col=slot-row*64
addiu t7,zero,0x10         ; ★ CELL = 16
mult  t6,col,16 ; mflo     ; U0 = 16*col
addiu a1,t6,0              ; U0
addiu t4,t6,0x10           ; U1 = U0+16
addiu t7,zero,0xC          ; ★ SKIP_ROW = 12
slt   t7,row,12 ; bnez → skip
addiu row,row,2            ; ★ SKIP_ROWS = 2
addiu t7,zero,0x10 ;
mult  t6,row,16 ; mflo
addiu t5,t6,3              ; ★ V0 = 16*row + 3（Y0=3）
addiu t6,t6,0x13           ; V1 = 16*row + 19 = V0+16
→ 4 个 cvt.s.w / swc1 写回 a2/a3/t0/t1；jr ra
```

**证明：cave 完全不碰 GIF 段/TRXPOS/容器物理偏移**——与 font-engineer 的"loader 把容器当 DMA 流、VRAM 连续行=引擎图"口径一致。

### 3.4 测量循环 cave `0x417150`（116 B；替换 StringWidth 内 `jal CharWidth` 的逐字循环）

对每个字节：`lbu`；若 `lead∈[0xA1,0xBA)` 且下一字节 `trail∈[0xA1,0xFF)` ⇒ 打包 16 位、`jal 0x21AD10`（→CharWidth cave）、`s1 += width`、`s4 += 2`；否则单字节、`s4 += 1`。

### 3.5 StringWidth 尾部 cave `0x565670`（172 B；替换 `0x21AC90`）

扫描字符串数出对偶数 `n_dbc`：`glyphs = len − n_dbc`；`s1 += (glyphs−1) × [font+0x18]`（字距只按字形数加，不按字节数）。原版直接用 `len−1`。

### 3.6 DrawString 拦截器 `0x565930` + 小特例 `0x417200`

- `0x219A74`（原 `sd ra,0xA0(sp)`）→ `j 0x565930`：检查调用者返回地址落在某 UI 区间 + 字符串含 DBCS 首字节 → 给行高 `f13 += 4.5`，再补 `sd ra,0xA0(sp)` 并跳回 `0x219A7C`（**跳过原 `sq fp,0x90(sp)`**，这是本体工程自己的 ABI/行距 hack）。
- `0x219ADC`（原 `mtc1 v0,f0`）→ `j 0x417200`：`if (v0==0x1A) v0=0x10;` 再 `mtc1`。

### 3.7 数据常量表

**没有独立数据表**：lead/trail 范围、94、224、64/16/3/12/2 全部是**指令立即数**；字库/图集几何全在代码里。
⇒ DLC port 只需重新汇编 cave（改 6 个 `.equ`），不需要在 ELF 里放数据表（v2 规格同样保持零数据表）。

### 3.8 cave 的"载体"经验（对 DLC 关键的移植决策）

本体工程把 cave 写进 **Sony SDK libc 里游戏不调用的函数**（`sceRemove/sceMkdir/sceFormat`…）+ **.text 内零岛**。
这是"不扩 ELF 也能拿到 2.5 KB 可执行空间"的关键。DLC 侧对应策略（§8.3）：用 JS19 已实机验证过的死函数区 `0x1808A8`。

---

## 4. DLC 侧同构函数（全部实证定位）

DLC-EN 已 stripped，但用 BASE-EN 的 `.symtab` 函数指纹（归一化指令序列）+ 字段偏移 + 调用图，把整条字体/文本栈定位如下（`file_off = VA − 0xFFF00`）：

| 功能 | DLC VA | file_off | 判定依据 |
|---|---|---|---|
| `RSFontMgr::DrawString` | `0x2195F0` | `0x1196F0` | 帧 0xE0/prologue 与本体同名函数同构；`jal strlen(0x16DE00)`、每字节 `lb`+`jal wctomb`、`jal CharWidth`、`jal UV`、`jal AddOneWord`、`addiu s5,s5,1` |
| `wctomb`（单字节桩） | `0x173678` | `0x173778` | `beqz a0; move v0,0; sb a1,(a0); return 1`（5 insn；全 .text 唯一调用点 `0x219758`） |
| `RSFont::CharWidth` | `0x21A360` | `0x11A460` | `lbu 0x24(a0)` 固定宽度早退；`0xFFB5/0xFFB1` 图标→20；`def=+0x28`；`idx*10` 记录；`lbu rec+1`；`lwc1 [a0+0x1c]` 缩放 |
| `RSFont::ComputeCharTextureCoords` | `0x21A210` | `0x11A310` | 叶子；`andi a1,0xFF`；`(c−[def+0x20])&0xFF`；`idx<count`；记录 +2/+4/+6/+8 的 u16→float |
| `RSFont::StringWidth` | `0x21A4C0` | `0x11A5C0` | `strlen`；逐字节 `jal CharWidth`；尾部 `(len−1)*[font+0x18]` |
| `RSFontMgr::AddOneWord` | `0x2193B0` | `0x1194B0` | 主包 `+0x44`/`slti 0x500`、副包 `+0x68`/`slti 2`（与本体 AddOneWord 同构） |
| `RSFont::CharHeight` | `0x2199A0` | `0x1199A0` | `lw v0,0x18(a0)` |
| `[a0+0x24]` getter | `0x2199B0` | `0x1199B0` | `lbu v0,0x24(a0)` |
| `[a0+0xc]` getter | `0x2199E0` | `0x1199E0` | `lw v0,0xc(a0)` |
| UV 调用 thunk | `0x2199D0` | `0x1199D0` | `a3=a2+4; t0=a2+8; t1=a2+0xC; j 0x21A210` |
| `strlen` | `0x16DE00` | `0x16DF00` | `jal 0x2199F0` → `j 0x16DE00`；与 BASE `strlen(0x406F28)` 归一化 **100%** 同构 |
| FONT 图集上传入口（推测） | `0x1FCC10/0x1FCC20` | — | `0x1FCC20` 返回全局字体管理器 `[0x626950]`；`0x1FCC10` = map-lookup（thunk `j 0x1FCD00; a0+=4`） |

**字段偏移逐项对照（BASE-ZH cave 用到的全部字段，DLC 实测一致）**：

| 字段 | 含义 | BASE | DLC | 证据 |
|---|---|---|---|---|
| `font+0x14` | 空格宽 | ✔ | ✔ | DLC `0x21A3A8` 区 `lw v0,0x14(a0)` |
| `font+0x18` | 行距/字距 | ✔ | ✔ | `0x2199A0 lw v0,0x18(a0)` |
| `font+0x1c` | 宽度缩放 | ✔ | ✔ | `0x21A430 lwc1 f0,0x1c(a0)` |
| `font+0x24` | 固定宽度标志 | ✔ | ✔ | `0x2199B0 lbu`；CharWidth 原版早退 |
| `font+0x28` | FontDefinition* | ✔ | ✔ | CharWidth/UV 都 `lw 0x28(a0)` |
| `def+0x20` | base char | ✔ | ✔ | `lbu 0x20(def)` |
| `def+0x38` | FT 记录表 | ✔ | ✔ | `lw 0x38` |
| `def+0x44` | 记录数（224） | ✔ | ✔ | `lw 0x44` |
| FT 记录 | 10 B | ✔ | ✔ | `idx*10`（`sll 2; addu; sll 1`）；+1 宽度；+2/+4/+6/+8 = U0/V0/U1/V1 |

**代码生成差异（为什么必须重新汇编）**：BASE-EN 用 `pcpyld` 把参数搬入 128 位 GPR 再 `sq`（如 `0x219AAC 70A0B628`），DLC-EN 用 `move`+`sq`、且 DrawString 的参数顺序/寄存器分配不同（DLC: `s2`=串基址、`s5`=游标、`s7`=长度；BASE: `s6`=串基址、`s0`=游标、`s7`=长度）。BASE-EN 与 DLC-EN 同名函数的归一化指令序列相似度仅 **30–50%**（例：DrawString 33%、CharWidth 38%、UV 50%）。

---

## 5. 同源判定：JS_ZH19 是本体汉化 cave 的移植

`work/analysis/elf/js19_report.txt`（工具 `elf_js19.py compare`，用「归一化指令键」序列做对齐）：

| cave 块 | JS19 | BASE-ZH | 对齐相似度 |
|---|---|---|---|
| decoder | `0x1808C8`（27 insn） | `0x416ED0`（27） | **27/27 = 100%** |
| CharWidth | `0x180948`（55） | `0x416F40`（61） | 45/55 = 82% |
| UV | `0x180A48`（59） | `0x417050`（59） | 10/59 = 17%（按 DLC 重写，但单字节分支/网格结构同源） |
| measure | `0x180B38`（25） | `0x417150`（29） | 12/25 = 48% |
| wrap（0x21B780） | `0x180BD8`（40） | `0x417500`（40） | 18/40 = 45% |

⇒ **JS19 的 decoder/CharWidth 与本体汉化逐指令同构**（只改立即数与寄存器），其余为同源改写。
⇒ JS19 的 cave 移植方法论（替换函数头/体 + 双字节格 + 步长 + 图标常量零扩展）**就是本工程要复用的方法论**；
其 cave 几何/数据在 2026-10-21 晚被 js19-recovery 的图集 OCR 实测验证**自洽可还原**（见 §6.3），真正的缺陷只在 FONT.RES 尾部 style 表与 def==NULL 防护层（§6.4/§6.5）。

---

## 6. JS_ZH19 蓝本：逐项拆解

### 6.1 补丁点（`elf_js19.py diff`；与原版 DLC-EN 差异 133 段 / 821 B）

| VA | 原 4B → JS19 4B | 作用 |
|---|---|---|
| `0x1808A8..0x180C98` | 整段 1008 B 替换 | **JS19 cave 区**（覆盖原死函数；原 ELF 该段 0 调用者/0 指针引用） |
| `0x219758` | `0C05CD9E` → `0C060232` | `jal wctomb` → `jal 0x1808C8`（decoder） |
| `0x21975C` | `27A400DF` → `27A400DE` | 解码格 → `sp+0xDE` |
| `0x219760/0x219770/0x219838/0x2198B8` | `83..DF` → `97..DE` | 4 处 `lb`→`lhu`（0xDF→0xDE） |
| `0x219795/79D/7A1/7C1/82D/845/8C5/8D1` | `FF`→`00`（8 处） | 图标常量零扩展（`0xFFB5/0xFFB1`→`0x00B5/0x00B1`） |
| `0x21994C` | `26B50001` → `0806022A` | `addiu s5,s5,1` → `j 0x1808A8`（advance stub） |
| `0x21A36C` | `90820024`(+`10400005` 首字节) → `08060252` | **CharWidth 函数体 → `j 0x180948`** |
| `0x21A210` | `8C8B0028`(+1B) → `08060292` | **UV 函数头 → `j 0x180A48`** |
| `0x21A530` | `0C0868D8` → `080602CE` | `StringWidth: jal CharWidth` → `j 0x180B38`（测量循环） |
| `0x21B780` | `80450000` `0C0868D8` → `080602F6` `nop` | **UI wrap/折行函数 → `j 0x180BD8`** |
| FONT.RES | 3 face 记录全重写、face 头字段改（large/default fld[2..4]=0x20；huge fld[1]=0x10）、尾部样式表改 | 数据层（见 §6.4） |

> JS19 **没有** patch `0x21A54C`（StringWidth 尾部字距）⇒ 其字距按字节数（=2×字形数）→ 中文行宽偏大（视觉 bug，不是崩溃原因）。

### 6.2 cave 分块（`0x1808A8..0x180C98`，1008 B）

| VA | 块 | 语义 |
|---|---|---|
| `0x1808A8` | advance stub | `lbu v0,0xDD(sp); addu s5,s5,v0; j 0x219950`（16 B） |
| `0x1808C8` | decoder | 与本体 3.1 **逐指令相同**，但 **gate = `sltiu t1,a1,0xAE`（lead ∈ [0xA1,0xAE)，13 lead）**；trail `[0xA1,0xFF)` |
| `0x180948` | CharWidth | 单字节/对偶；slot = 224+(lead−0xA1)*94+(trail−0xA1)；**删掉了 `lbu 0x24(a0)` 固定宽度早退**；无 def==NULL 兜底 |
| `0x180A48` | UV | **旧几何：NCOL=0x3E(62)、CW=8（U0=8*col+2，U1=+0xA）、Y0=2、SKIP_ROW=12、SKIP_ROWS=3、CH=16（V0=16*row+2，V1=+0x12）**；单字节分支 `j 0x21A218` |
| `0x180B38` | measure | StringWidth 循环 DBCS（步长 2）；与本体同构 |
| `0x180BD8` | wrap | `0x21B780` 的折行/测量替换：`lw a0,0x98(obj)` 取字体 → CharWidth/CharHeight → 按步长推进 → `j 0x21B778/0x21B7C8` |

### 6.3 几何/数据一致性（2026-10-21 晚修正：js19-recovery OCR 实测闭环）

> 本节取代早前"JS19 数据与 cave 几何矛盾"的判断——那是建立在 task 背景里**朴素 bigram 统计**（lead 161..254）上的误读。
> JS19 解码器是**有状态**的：只有 `lead∈[0xA1,0xAD] && next∈[0xA1,0xFF)` 才吃 2 字节，其余（含 0xAE..0xFE）都是单字节码。

| 项 | JS19 ELF cave 常量 | 实测结论（js19-recovery） |
|---|---|---|
| gate | `0xAE`（lead ∈ [0xA1,0xAD]，13 lead） | **正确**：重扫 176,441 B LANG，真 pair **14,455 次**（2B/次），lead 只出现 A1..AD ⇒ 1222 槽容量内；0xAE..0xFE 共 **9,765 次**是单字节高码，走 record 路径 |
| NCOL / CW / CH | 62 / 8px / 16px，Y0=2，SKIP_ROW=12、SKIP_ROWS=3 | **正确**：按此常量逐格切片，ink 投影 y=208..239 恰 32px 空档（=3 行跳过）、x 向 8px 周期；**不是 32×16×16** |
| 图集 → 字形映射 | `slot=(lead−0xA1)*94+(trail−0xA1)` → row/col → 8×16 cell | **正确**：TTF(方正像素16) 16px→32×32→[8:24,8:24]→OR 合并相邻两列→8×16；前 62 格 xor 61/62=0，全图 **1209/1283 有墨格 xor==0 唯一命中** |
| 数据可还原性 | — | **完全可还原**：14,455 pair 全部命中，解出 **2,275 条中文译文 / 22,594 汉字 / 881 种字 / 0 未解析码**；693 条未改英文同映射解码，655 条与英文逐字节一致（余 38 条为法式重音名字的取舍） |
| 单字节高码 | — | 也闭环：`idx=c−0x20`→记录→rect；rect `u0` 漏 +2（与 cave 的 `U0=8*col+2` 对应）⇒ 字形左移 2px/右缘裁切（视觉 bug，不影响解码） |
| 真正的缺陷 | — | **仅两处**：① FONT.RES 尾部 style 表 off-by-22（§6.4）；② cave 删掉 `font+0x24` 早退且无 def==NULL 兜底（§6.5） |
| 容量对照（为何不能照抄 JS19 几何） | pair_cap = 13×94 = **1,222** | **不够本工程用**：本体字符集真实汉字 **1,966**（本工程 2,350 slot 规划），1,222 < 1,966 差 744 格 ⇒ JS19 的 `gate 0xAE / 62×8×16` 只能承载缩减字集；本工程 v2 用 `gate 0xBA / NCOL=64 / CELL=16 / 2,350 slot` 是正确选择（ELF 侧 cave 几何由 `.equ` 参数化，与 JS19 解耦） |

### 6.4 JS19 FONT.RES 尾部损坏（实证，可复现 `elf_js19.py fontres`）

```
展开 7488 B（原版 7466 B），nfaces=3, face 名 large/default/huge 均在
face 头: large/default fld[2..4] 26→0x20(32)；huge fld[1] 0x2A→0x10(16)
尾部样式表 544 B（原版 522 B）：
  count 字段 = 15
  实际含 16 条名字记录；rec7（huge）只占 11 B（"04000000 68756765 0000"），
  正常记录 = 4B len + name + 1B NUL + 24B 固定字段 = 33 B ⇒ **缺 22 B**
  ⇒ 23..544 全部前移/错位；顺序解析会在 rec8 起漂移，读到错误 len/名字/face 索引
```
⇒ 这正是 font-engineer 独立从数据侧发现的 "off-by-one 损坏"；本报告用 ELF 侧+数据侧双向证实。

### 6.5 38s 崩溃取证（emulog.txt，只读）

`%LOCALAPPDATA%\PCSX2\logs\emulog.txt`（JS19 最后一次运行，16:21:28）：
- 30.29–30.30s：`Dumping 512x512 texture …` ×3（COMMON.PAK 三张 512×512，含 `new_font_revised`）⇒ 图集上传成功。
- **37.938–38.055s：50 条 TLB Miss，3 个唯一站点**：

| pc | 指令 | 次数 | 故障地址 | 反推基址 | 归属 |
|---|---|---|---|---|---|
| `0x1809B8` | `lw $v1,0x44($a2)` | 36 | `0x44` | `a2 = 0` ⇒ **font->def == NULL** | JS19 CharWidth cave |
| `0x208F30` | `lw $v0,0x28($a0)` | 12 | `0x24` | `a0 = 0xFFFFFFFC (-4)` | **原版代码**（`[[a0+0x28]+0x24]` getter，被 UI 测量/居中调用） |
| `0x18097C` | `lw $a2,0x28($a0)` | 2 | `0x20` | `a0 = 0xFFFFFFF8 (-8)` | JS19 CharWidth cave 单字节入口 |

- 38.055s 后不再有 TLB Miss，游戏继续到 92s+（后续还有大量 texture dump）⇒ **一次性/局部坏状态**，不是每帧都崩。

**根因链（按证据强度排序）**：
1. **数据层（已证实）**：JS19 的 FONT.RES 尾部 off-by-22 → 字体/样式结构在加载期被错误解析，产生**垃圾字体指针**（`-4`、`-8` 这种小负数只可能来自损坏的指针/错误码混用），并让部分 font 的 `def` 保持 NULL。这是唯一能同时解释「原版 getter 也被波及」的原因。
2. **ELF 层（已证实，放大因素）**：JS19 CharWidth cave **删掉了原版 `font+0x24` 固定宽度早退**（原版遇到"未就绪/固定宽度"字体直接返回 `[font+0xc]`、不碰 def）。于是「def=NULL 的字体」从"能安全画"变成"必然硬 fault"。
3. **ELF 层（已证实，放大因素）**：JS19 cave **没有任何 def==NULL 兜底**（CharWidth 的 `lw 0x44(a2)`、UV 的同类路径都是裸解引用）。
4. 已排除：几何/数据不匹配——js19-recovery 图集 OCR 已证 JS19 数据层自洽可还原（§6.3）；字形左移 2px 是 rect `u0` 漏 +2 的视觉 bug，与 TLB 无关。

**修复建议（已并入 v2 规格）**：
- 数据层：FONT.RES 尾部**严格**按 `count + 自描述记录` 重写，写完做「反解析回读校验」（`dbcs_spec.py` 式的 readback；font 侧建议 `font_engineer` 也加）。
- ELF 层：CharWidth cave **恢复 `font+0x24` 早退**；CharWidth/UV **都加 `def==NULL` 安全回退**（宽度返回 `[font+0xc]`；UV 写 0/0/0/0）。
- 验收：先在无中文字体的界面（主菜单/训练关）跑 60s，再进有中文的界面；关注 TLB Miss 计数必须为 0。

---

## 7. DLC 补丁规格 v2（已生成并回读自证）

> 生成器：`tools/analysis/dbcs_spec.py`（`--cave-src` 可换几何）
> cave 源码：`tools/analysis/caves/dbcs_cave_dlc.s`（250 条指令 / 1000 B，6 个 `.equ` 参数化）
> 规格 JSON：`work/analysis/elf/dbcs_spec_dlc.json`；人读清单：`work/analysis/elf/dbcs_spec_dlc.txt`
> 打过补丁的 ELF 副本（仅 work，不进 git）：`work/analysis/elf/DLC_SLUS_208.20_DBCS_v2.elf`

### 7.1 几何/常量（= 本部最终 ELF 立即数 + font-engineer 定稿）

```
gate_hi   = 0xBA      lead ∈ [0xA1,0xBA)（25 lead）    trail ∈ [0xA1,0xFF)（94）
pair_n    = 94        pair_base = 0xE0 (224 = FT 记录数/face)
NCOL=64  CELL=16  Y0=3  SKIP_ROW=12  SKIP_ROWS=2
slot = (lead-0xA1)*94 + (trail-0xA1)                   # 0..2349
row=slot/64; col=slot%64
U0=16*col; U1=U0+16
row += 2 if row>=12
V0=16*row+3; V1=V0+16
pair CharWidth = 16 恒定
```

### 7.2 cave 布局（base `0x1808A8`，1000 B；备用 `0x6124B0` 实测被字符串表占用，不可用）

| VA | 块 | 条数 | 用途 |
|---|---|---|---|
| `0x1808A8` | `decode` | 27 | 替换 wctomb：lead/trail 判定 + 2B 格 + 步长 |
| `0x180918` | `draw_advance` | 4 | DrawString 游标 += 步长 |
| `0x180928` | `charwidth` | 61 | CharWidth 全函数体（含 +0x24 早退、def NULL 兜底、单字节/对偶） |
| `0x180A78` | `uv` | 57 | 槽位→UV（单字节回原记录路径；对偶网格；def NULL 写零） |
| `0x180B7C` | `measure` | 26 | StringWidth 逐字 DBCS |
| `0x180C00` | `sw_tail` | 32 | StringWidth 尾部字距（按字形数） |

> 与 JS19 对比：v2 **保留** +0x24 早退、**新增** NULL 兜底、**不再**放 wrap 块（v3 可选）、几何换成 64/16/3/12/2、gate 0xBA。
> 完整标签表见 `dbcs_spec_dlc.json → cave.labels`。

### 7.3 逐字节补丁表（25 站；原字 24/24 逐字节校验通过 + 回读 PASS）

| # | VA | file_off | 原 4B → 新 4B | 作用 |
|---|---|---|---|---|
| 1 | `0x219758` | `0x119858` | `0C05CD9E` → `0C06022A` | `jal wctomb` → `jal 0x1808A8`（decoder） |
| 2 | `0x21975C` | `0x11985C` | `27A400DF` → `27A400DE` | 解码格 `sp+0xDF`→`sp+0xDE` |
| 3 | `0x219760` | `0x119860` | `83A500DF` → `97A500DE` | `lb`→`lhu` |
| 4 | `0x219770` | `0x119870` | `83A500DF` → `97A500DE` | `lb`→`lhu` |
| 5–9 | `0x219794/79C/7A0/7C0/82C` | +0x1100… | `2403FFB5/FFB1` → `240300B5/B1` | 图标常量零扩展（5 处） |
| 10 | `0x219838` | `0x119938` | `83A400DF` → `97A400DE` | `lb`→`lhu` |
| 11 | `0x219844` | `0x119944` | `2403FFB1` → `240300B1` | 图标常量 |
| 12 | `0x2198B8` | `0x1199B8` | `83A300DF` → `97A300DE` | `lb`→`lhu` |
| 13–14 | `0x2198C4/8D0` | `0x1199C4/D0` | `2402FFB5/FFB1` → `240200B5/B1` | 图标常量 |
| 15 | `0x21994C` | `0x119A4C` | `26B50001` → `08060246` | `addiu s5,1` → `j 0x180918` |
| 16 | `0x21A36C` | `0x11A46C` | `90820024` → `0806024A` | CharWidth 体 → `j 0x180928` |
| 17 | `0x21A370` | `0x11A470` | `10400005` → `00000000` | 原 beqz → nop |
| 18 | `0x21A210` | `0x11A310` | `8C8B0028` → `0806029E` | UV 头 → `j 0x180A78` |
| 19 | `0x21A214` | `0x11A314` | `30A300FF` → `00000000` | 原 andi → nop |
| 20 | `0x21A52C` | `0x11A62C` | `80450000` → `080602DF` | StringWidth 循环 → `j 0x180B7C` |
| 21 | `0x21A530` | `0x11A630` | `0C0868D8` → `00000000` | 原 jal → nop |
| 22 | `0x21A54C` | `0x11A64C` | `8E620018` → `08060300` | StringWidth 尾 → `j 0x180C00` |
| 23–25 | `0x21A550/554/558` | `0x11A650/54/58` | `2623FFFF`/`00621018`/`02028021` → `00000000` | 原尾部 3 字 → nop |

（完整表 + 每站新旧反汇编见 `work/analysis/elf/dbcs_spec_dlc.txt`。）

### 7.4 结果指纹

```
基线 ELF:  sha256 cf29cabe…baee7eee   CRC DE1E4DEE
补丁后:    sha256 ae25d48d4bb309e072000036dc266b5b3b6b262b786ee680c0ee28a8b9f7d334
           Game CRC FD9E6AED
           PCSX2 即时存档名 SLUS-20820 (FD9E6AED).01.p2s   ← 旧存档/旧金手指失效，不可避免
```

### 7.5 FONT.RES 结构 / 字段映射（与 font 协作结论，2026-10-21）

> 本节是回答 font-engineer「face 头 14×u32 → font 结构偏移，尤其 font+0x24 是哪个字段」的反汇编结论；
> 复现脚本：`work/analysis/font/extract_fontres.py`（产出三份盘展开后的 `.fontres.bin` + `fontres_structs.txt`）。

**FONT.RES 布局（实测 = 反汇编顺序）**：

```
{u32 atlas_namelen, atlas_name, u32 nfaces}
per face: {u32 namelen, name, u32 fld[14], nrec×10B FT 记录}      nrec = fld[4] × fld[5]
{u32 nstyles}
per style: {u32 namelen, name, u32 f0,f1,f2,f3, u8 b4, f32 f5, f32 f6}   = namelen + 29 B
```

**style 块 → RSFont 字段**（`RSFont::ReadResource` @VA `0x21A580`，DLC）：
`f0→font+0xC`、`f1→font+0x10`、`f2→font+0x14`、`f3→font+0x18`、**`b4→font+0x24`**、`f5→font+0x1C`、`f6→font+0x20`；
（`font+0x4` = 名字；`font+0x25` 另一个 u8 标志；`font+0x28` = FontDefinition 指针由管理器绑定；copy-ctor `0x219140` 逐字段印证。）

**face 头 14×u32 → FontFace(def) 对象**（copy-ctor @`0x218F10` 实证）：

| face 头 | def 偏移 | face 头 | def 偏移 |
|---|---|---|---|
| fld[4] | +0x00 | fld[10] | +0x18 |
| fld[5] | +0x04 | fld[11] | +0x1C |
| fld[0] | +0x08 | **fld[12]** | **+0x20 = base char（=32/0x20）** |
| fld[1] | +0x0C | fld[13] | +0x24 |
| fld[2] | +0x10 | fld[8] | +0x28 (float 512.0) |
| fld[3] | +0x14 | fld[9] | +0x2C (float 512.0) |
| | | fld[6] | +0x30 (float) |
| 记录表指针 | **+0x38** | fld[7] | +0x34 (float 行距类 0/208/416) |
| **nrec=fld[4]×fld[5]** | **+0x44** | | |

⇒ **base char = fld[12]，中英两版都是 32，未改动**；**nrec 必须 = fld[4]×fld[5]**（large/default 32×7=224，huge 16×14=224）。

**关键澄清：`font+0x24`（固定宽度早退标志）不是 face 头字段**，而是 **style 块里的 u8 `b4`**。
实测：DLC 原版 15 条 style 的 b4 全 = 0；本体 EN 8 条全 = 0；**本体中文成品盘（BASE-ZH FINAL）8 条全 = 0**
⇒ 对现有 FONT.RES，**固定宽度早退永远不触发**；font 侧改 face 头 fld[2]/fld[3] 与它无关。

**铁证（本体中文成品盘 FONT.RES，同 RS 引擎、实机跑通）**：
```
large/default: fld = [10, 26, 32, 32, 32, 7, 0, 0|208.0, 512.0, 512.0, 0, 0, 32, 26]   nrec=224
huge         : fld = [10, 16, 52, 42, 16, 6, 0, 416.0,   512.0, 512.0, 0, 0, 32, 42]   nrec=96
styles=8，font+0x24 全 0，font+0x14=3/4/6，font+0x18=1/2，font+0x1C/0x20=1.0/1.64/0.8/1.63
```
与 EN 原版对比只差：large/default `fld[2]`、`fld[3]` 26→32；huge `fld[1]` 42→16；huge `fld[5]` 14→6（nrec 224→96）。
⇒ font 侧的 CN face 值与成品盘逐字一致，可判定无害；**建议 huge 采用 `fld[5]=6 / nrec=96` 与成品盘一致**（若确需 224 条则保持 14，仍在引擎公式内，但需实机 smoke）。

### 7.6 cave 落点选择（依据）

- `0x1808A8..0x180C98`：原 ELF 是一段**死代码**——`elf_probe.py callers` 证 0 个 jal/分支从区外进入、0 个裸指针字、0 个 `lui+addiu` 地址构造（`dbcs_spec.py` 内置校验：`jump_in=0 lui_addiu=0 raw_ptr=0`）；
  且 **JS_ZH19 已把该区整段覆盖并实机运行 100s+**（emulog 到 92s 无相关异常）⇒ 运行时安全有实证。
- 大小：1000 B ≤ 1008 B（JS19 覆盖范围），余量 8 B。
- 备选：`0x6124B0`（原以为是 .text 末尾零岛）**实测不可用**——该处是字符串/表格数据区（`GSFAIL/CHATALL/JOINNEW/IRCIP%d/…`）。
- 备选 2（若 v3 加 wrap 块需更多空间）：继续向后评估 `0x180C98..` 的死函数边界（本报告只验证到 0x180C98）。

---

## 8. 移植判断总表（Lead 要的 a/b/c 回答）

| 函数 | BASE-ZH 到 JS19 的相似度 | DLC-EN 与 BASE-EN 的相似度 | 结论 |
|---|---|---|---|
| decoder | **100%（27/27 同构）** | 结构同构（寄存器/地址不同） | **按 DLC 寄存器重汇编**（v2 已做：s2/s5/s7） |
| CharWidth | 82% | 38%（代码生成差异大） | **重汇编**（v2 已做：保留 +0x24 早退 + NULL 兜底） |
| ComputeCharTextureCoords | 17%（按 DLC 重写） | 50% | **重汇编**（v2 的几何由 `.equ` 参数化） |
| StringWidth 循环 | 48% | — | **重汇编**（v2 measure） |
| StringWidth 尾部 | JS19 未做 | — | **v2 新增**（字形数字距） |
| DrawString 解码/步长/图标常量 | 直接同款 patch | — | **常量级 patch（v2 的 25 站里 15 站）** |
| wrap/折行（0x21B780） | 45% | — | **v3 可选**（JS19 有；需更多 cave 空间与实机验证） |
| 数据层（图集/FONT.RES/文本） | — | — | 不在本报告；见 font/text 分析 |

**一句话**：DBCS 100% 必须 ELF 补丁；补丁 = 5 处函数级 hook + 15 处常量/load 级 patch + 1000 B cave；
与本体同构但**必须重新汇编**；蓝图已验证（BASE-ZH 交付盘 + JS19 实机），v2 规格已生成并回读自证。

---

## 9. 风险与未决

| 风险 | 说明 / 缓解 |
|---|---|
| **实机验证缺失** | v2 只在静态层面自证（原字/回读/CRC）；必须按验收流程实机跑（见 §6.5 修复建议）。DBCS 补丁改变 CRC，旧存档作废 |
| **cave 余量 8 B** | 若 v3 加 wrap 块或修 bug 需扩展 cave，需评估 `0x180C98+` 死函数边界（或另找 cave），并重跑 `dbcs_spec.py` |
| **`font+0x24` 语义（已澄清，风险关闭）** | 反汇编实证 `font+0x24` **不是** face 头字段，而是 FONT.RES style 块的 u8（`ReadResource @0x21A580`；style = `{u32 namelen,name,4×u32,u8,2×f32}` = namelen+29B）。DLC 15 条 / 本体 EN 8 条 / **本体中文成品盘 8 条 style 的该字节全为 0** ⇒ 固定宽度早退不会触发。详见 §7.5 |
| **TAIL/字形几何** | v2 假定 `def+0x44 = 224`（与 FONT.RES 每 face 224 条一致）；font 侧若改记录数，须同步 `PAIR_BASE` |
| **UI wrap/折行** | v2 未 patch `0x21B780` 等 wrap 路径 ⇒ 长中文段落可能按字节折行（视觉问题，不崩溃）；v3 处理 |
| **多 DrawString 变体** | DLC 只有 1 个调用 `wctomb` 的 DrawString（`0x219758` 唯一调用点）；其它 UI 文本走 `StringWidth`/wrap/CharWidth，v2 已覆盖测量路径；若发现新的整串绘制入口需补 |
| **其它用字路径** | `AddOneWord` 的 4 处标志位（BASE-ZH 改过）v2 未动；若实机出现"图标/换行错位"再评估 |

---

## 10. 复现命令

```powershell
$py = "C:\Users\84363\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
$env:PYTHONIOENCODING="utf-8"

# 0) 工具自测（83 条已知字节：elf_patches.json 全部 cave + BASE-ZH decoder 27 条）
& $py tools\analysis\mipsasm.py --selftest

# 1) 抽三份 ELF 到 work/analysis/elf/（只读 ISO）
& $py tools\analysis\elf_port.py extract

# 2) BASE-EN → BASE-ZH 全量差异 + 分类 + cave 反汇编
& $py tools\analysis\elf_port.py diff
& $py tools\analysis\elf_port.py redirects
& $py tools\analysis\elf_port.py caves --out work\analysis\elf\zh_caves.txt

# 3) JS_ZH19 取证（身份/差异/cave/崩溃/FONT.RES/同源性）
& $py tools\analysis\elf_js19.py all

# 4) DLC DBCS 补丁规格 v2（汇编 cave + 25 站补丁 + 回读 + CRC）
& $py tools\analysis\dbcs_spec.py
#    备用 cave 落点：& $py tools\analysis\dbcs_spec.py --cave-base 0x1808A8

# 5) ELF 通用探针（主报告用）
& $py tools\analysis\elf_probe.py info
& $py tools\analysis\elf_probe.py crc
& $py tools\analysis\elf_probe.py gate-scan --imm "0xA1,0xAE,0xB1,0xB5,0xBA,0xFF,0xFE" --ops sltiu,slti --ctx 3
& $py tools\analysis\elf_probe.py strings --font --min 5
```

## 12. v7 增补：字库纹理最近邻过滤（参考本体 ZH50 过滤集）

原始 DBCS v2 规格（25 调用点 + 1000B cave）之后，v7 再补 2 处**纯 ELF 词替换**，用于关闭字库纹理的
双线性采样（中文图集是 PSMT4 1-bit，双线性会导致笔画边缘发虚/漏墨）：

| VA (DLC SLUS_208.20) | 原词 | 新词 | 语义 |
|---|---|---|---|
| `0x219314` | `24050001` | `24050000` | `RSFontMgr`(0x2192D0) 的 `jal UIPacket::SetLinearSampling` 延迟槽 `li a1,1→0` |
| `0x4FD5CC` | `10830038` | `00000000` | `UIPacket::SetLinearSampling`(0x4FD5B0) 状态缓存早退 `beq a0,v1→nop` |

来源：本体汉化工程 `docs/PATCH_INVENTORY.md §C 纹理过滤 (最近邻) —— ZH50 集`
（base SLUS_206.13：`0x219FF4/0x21A0F8/0x21A1C4/0x21A2C4` 四处 `li a1,1→0` + `0x519AC8` `beq→nop`；
其 `UIPacket::SetLinearSampling` = `0x519AC0`）。DLC 地址由 `elf_probe.dump_dis` 反汇编定位并回读确认。

补丁进 `tools/dlc/elf_patches.json`（`EXTRA_PATCHES`，可重生成）；新身份：
ELF sha256 `7f3970798c5374422e4e8cdbce9dbb1e5073f315058cb29408fc3f256d0dfcef`、Game CRC `ED1D6AD4`。
