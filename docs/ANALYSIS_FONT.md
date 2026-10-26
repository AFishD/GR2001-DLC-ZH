# ANALYSIS_FONT — 《幽灵行动：丛林风暴》PS2 (SLUS-20820 / 美版) 中文字库 + 图集移植方案

> **执行者**：字库/图集工程师（task-3）· **日期**：2026-10-21
> **输入（全部只读）**：
> - 资料片英文原盘 `third_party/orig/ps2/[PS2] Tom Clancy's Ghost Recon - Jungle Storm (U).iso`
>   （1,229,225,984 B / sha256 `292f5a6a…fd0767`）
> - 本体汉化成品 `…\Ghost_Recon_2001_Locolization\work\builds\FINAL\Tom Clancy's Ghost Recon (ZH_CN).iso`
>   （1,648,164,864 B / sha256 `4ded92e2fee535ac00893af60faee630323af124aa38a89d1777d1721d04617a`）
> - 本项目 `assets/charset/charset_compiled_zh16.json`（145,740 B / sha256 `56586168…cef504`）
>
> **一句话结论**：**可行**。推荐 **方案 B = 1024×644 PSMT4 图集（2350 槽原样保留）**；
> 原型已产出**可验证的新 ISO**（28/28 项回读自证 PASS，独立 `7z t` 校验 `Everything is Ok`），
> 位置 `work/analysis/font/GR_JS_ZH_FONT_planB.iso`（1,230,051,328 B / sha256 `803cdcb6…c986d862`）。
> 方案 A（1024×512 原地等大小替换）**内容装不下**，实测否决（§4.1）。
> 本方案**依赖 ELF 侧 DBCS/UV 补丁**（elf-analyst 已确认：资料片引擎原生单字节文本栈，
> 必须移植本体最终 ELF 的 5 个函数 + cave；几何参数见 §7，已与 elf-analyst 双向核对）。

---

## 0. 结论速览

| # | 问题 | 结论 | 关键数字 / 证据 |
|---|---|---|---|
| 1 | 中文图集几何 | **1024×644 / psm 0x14 (PSMT4 4bpp)**，11 段 GIF 流，64 列 × 16px 格 | 容器 329,744 B；payload 329,200 B；`px_size` 字段 329,744（§2） |
| 2 | slot→格位公式 | `slot=(lead-0xA1)*94+(trail-0xA1)`；`x=16*(slot%64)`，`y=3+16*(row+2*[row≥12])` | 容量 (0xBA-0xA1)×94 = **2350**；与本体最终 ELF 立即数（0x4170AC/E8/F8 = 0x40/2/3）逐字一致（elf-analyst 反汇编复核） |
| 3 | FONT.RES 差额 244 B | **资料片尾部样式表多 7 条**（15 条 522 B vs 本体 8 条 278 B） | 三 face 记录数/内容在英文盘与资料片**逐字节相同**：672/672 条 same（§3） |
| 4 | 中文 FONT.RES 能否直接用 | **不能**（会丢 128 条 huge 记录 + 7 条资料片样式） | 采用**合并 FONT.RES**：中文 large/default(224+224)+huge(96 条 ASCII+128 条退化)+资料片 522B 尾部 = 恰好 7,466 B；LZO 帧仅 1,572 B ≤ 原槽 4,460 B（§3.5） |
| 5 | 方案 A（1024×512 原地换） | **不可行**（不是风险问题：内容装不下） | 1966 真汉字 + ASCII/单字节带 159 格 = 2125 > 2048 格，且无新字余量；还丢 494 个 slot（§4.1） |
| 6 | 推荐方案 | **方案 B：1024×644 / 2350 槽 / 新 COMMON.PAK 追加到 GR.IMG 末尾 + ISO 尾部扩 403 扇区** | 只改 GR#9 条目三字段 + GR.IMG 头 + 根目录 size + PVD volume_space；其余 **3109 条条目逐字节不变**（§5、§6） |
| 7 | 新字容量 | **298 格（零引用 PUA 占位槽，引擎安全上限）**；50 个「未映射空槽」= trail 0xB1/0xB5 哨兵槽，**禁止使用** | 36 个 col-63 槽（x=1008 贴右缘）引擎采不到；哨兵槽会触发引擎图标特判写坏内存（§2.6 / §8 R11）；截至 2026-10-22 已用 **33**，剩 **265**（§10） |
| 8 | ASCII/单字节 | **完全不改语义**：仍走 FONT.RES 的 FT 记录（`idx=code-0x20`，10B/条，rect=采样窗） | 中文 pair 不占 FT 记录；图集里 ASCII/单字节像素随 seed 整块拷贝，逐 texel xor==0（§5.6） |
| 9 | 上一版 JS_ZH19（512×512 8bpp 原地换）能否复用 | **不能作为主方案**（对偶容量 **1,222 格** < 1,966 真汉字） | JS19 图集：**62 列 × 8×16 格**（x0=2/y0=2/skip_row=12/skip_rows=3，pair_cap=1222）已被 js19-recovery 的 OCR + pair map **验证**（不是数据/几何不匹配）；其 FONT.RES **style 表 off-by-22**（展开 7,488 = 7,466 + 22）是崩溃主因（§4.4） |

---

## 1. 资产实测（全部在只读盘上现读，非历史报告）

### 1.1 三张盘的身份与字库位置

| 盘 | 尺寸 | 字库定义 | 图集 |
|---|---|---|---|
| 资料片英文原盘 | 1,229,225,984 B | **GR.IMG#580 `FONT.RES`**：stored 4,460 / real 7,466 / 单 LZO 帧 | **GR.IMG#9 `COMMON.PAK`** 的 `new_font_revised`：psm=19(PSMT8) 512×512 / clut 1040 / px 262,160 |
| 本体英文原盘（对照） | 1,648,164,864 B | MENU.IMG#4 `FONT.RES`：stored 4,421 / real 7,222（GR#906 同内容） | MENU.IMG#3 `COMMON.PAK`：`new_font_revised` psm=19 512×512 / px 262,160 |
| 本体汉化成品 | 1,648,164,864 B | MENU.IMG#4 `FONT.RES`：展开 **5,942 B**（sha256 `c7876128483c2b5b…`）；GR#906 是副本但有 24 B 差（X 的 FT 记录：zh130 只更新了 MENU 侧）→ **seed 取 MENU#4** | MENU.IMG#3 `COMMON.PAK`（stored 468,243 / sha256 `07bf96dd…`）：`new_font_revised` **psm=20 1024×644 / clut 1040 / px 329,744** |

> 资料片根目录没有 MENU.IMG——**只有一份字库**（GR#580 + GR#9），移植面比本体小。
> 本体 GR.IMG#3451 里还有一份 1024×512 psm20 的**英文死拷贝**（早期方案产物，引擎不读），不作为输入。

### 1.2 本体成品图集（= 唯一像素来源 / seed）

| 项 | 值 |
|---|---|
| 记录名 / 所在 | `new_font_revised` / MENU.IMG#3 COMMON.PAK（PAK 记录 #1） |
| psm / w / h / clut / px | **0x14 (PSMT4) / 1024 / 644 / 1040 / 329,744** |
| 容器 | 329,744 B；sha256 `cf4fbbd8d3e6666ae0eef66b8f3a37655d51f97a3095976eacff842b97f5585c` |
| 封包 | **23 个 GIF 包** = 11 × (`PT`16B + `A+D TRXPOS`16B + `IMAGE tag`16B) + 11 段数据 + 1 个 16B 末尾空 `IMAGE` tag |
| payload | 329,200 B = 10×32,768 + 1,520（末段 2 行 + 496 B 半行 = 642.97 行） |
| 数据段 SSAY | `0, 64, 128, 192, 256, 320, 384, 448, 512, 576, 640` |
| texel 直方图 | 索引 0 = 148,935（墨）；索引 1 = 510,521（空）；**只有 0/1 两种值** |
| CLUT | 1,040 B = 16B `IMAGE` tag（NLOOP=4 → 16 色）+ 16 色 ×4 B + padding；palette[0]=`7FFFFFFF`（白，A=0x7F）为墨、[1..15]=`00FFFFFF`（全透明） |

### 1.3 资料片原图集（要被替换的对象）

| 项 | 值 |
|---|---|
| 记录名 | `new_font_revised`（COMMON.PAK 记录 #6，共 10 条记录） |
| psm / w / h / clut / px | 0x13 (PSMT8) / 512 / 512 / 1040 / 262,160 |
| 容器 | 262,160 B = 16B GIF tag + 262,144 B 像素（单包）；sha256 `15e40e7d…f538da`；空白索引 0x0F |
| 记录布局 | `{u32 type}{u32 nameLen}{name}{u32 psm,w,h,clut}{CLUT（clut B）}{u32 px_size}{px 数据}` |
| 另一条 psm20 记录 | `pda-lcd-02`：psm=20 256×256 **clut=80** ⇒ **资料片引擎原生支持 PSMT4**，且 psm20 的 CLUT 原生形状 = 16B tag + 16 色 = 80 B（本方案就按这个形状建 CLUT，§3.5） |

### 1.4 字符集（`assets/charset/charset_compiled_zh16.json`）

| 项 | 值 |
|---|---|
| 单字节码 | **103 个**：0x80..0xA0（33）+ 0xBA..0xFF（70），**没有一个落在 lead 区间 [0xA1,0xBA)** |
| 对偶码 | **2,300 个**（pair_of），lead 25 个（0xA1..0xB9）× trail 0x91 个（0xA1..0xFE）+ 特殊 0xB9FE(×图标) |
| 其中真汉字 | **1,966 个（全部有字形）**；PUA 占位键 334 个（其中 36 个是 col-63 不可采样槽） |
| slot 分布 | 0..2349（不连续：有空洞），最大值 2349 |
| 注 | FINAL 盘 = ZH146 产品线（zh139/140/141 共补 25 个新字），比历史文档的“1954 字/2300 槽”多 12 字；**以本表实测为准** |

---

## 2. 图集几何（1024×644 PSMT4）——布局表

### 2.1 容器结构（GIF 封包流，不是裸图）

```
偏移 0x00000: [PT tag 16B][A+D(TRXPOS SSAX=0,SSAY=0) 16B][IMAGE tag nloop=2048 qwords 16B][32768B 数据 → 行 0..63]
偏移 0x08030: [PT][A+D SSAY=64][IMAGE 2048][32768B → 行 64..127]
… 共 11 段（SSAY = 0,64,128,192,256,320,384,448,512,576,640）…
偏移 0x501E0: [PT][A+D SSAY=640][IMAGE nloop=95 qwords][1520B → 行 640..642.97]
偏移 0x50800: [IMAGE tag nloop=0, EOP=1]（16B 空包，结束）
总长 = 11×48 + 329,200 + 16 = 329,744 B
```

- **硬件把包头当 DMA 命令吃掉** ⇒ 包头字节永远不是像素；每段数据落在 TRXPOS(SSAY) 指定的行。
- ⇒ **引擎看到的图 = 连续 1024×643 行的矩形图，没有行相位、没有列回绕、没有 6 格/段错位**。
  旧 dump 工具的 “flat 口径”（整块当裸图逐行读）是错的，**不要**用它算 UV/写像素。
- 实际被数据覆盖 642.97 行；`h=644` 里最后 ~1 行不被任何采样窗使用（不影响渲染）。
- **`ATLAS_PHI` 行相位（历史口径澄清）**：62 列 / 1024×512 旧配时代，容器每段 48B 头会让「裸容器 flat 视图」相对引擎图每段右移 96 texel（= 6 格），于是 `PHI[row]=6×(段号+1) mod 64`。对 64 列的 K2 口径，**引擎采样就是 `x=16*col, y=yrow(row)`（无相位、无回绕）**；`PHI` 只用于把「引擎坐标」换算回「裸容器坐标」，**不能**用来算 UV。本方案读写像素一律按封包段表定位，不碰包头。
- 注：任务背景里写的「8 段 GIF 包」是 1024×512 时代数字；**实测成品是 11 段**（10×64 行 + 末段 2.97 行）。

### 2.2 网格与 slot→格位公式

| 常量 | 值 | 证据 |
|---|---|---|
| NCOL（每行格数） | **64** | 本体最终 ELF VA 0x4170AC 立即数 0x40 |
| CW × CH | **16 × 16**（PSMT4 texel） | 引擎 cave 里 `U0=16*col, V0=16*row+3` |
| Y0 | **3** | VA 0x4170F8 立即数 3 |
| SKIP_ROW / SKIP_ROWS | **12 / 2** | VA 0x4170E8 立即数 2 |
| lead / trail 区间 | lead **∈[0xA1,0xBA)**（gate=0xBA）；trail ∈[0xA1,0xFE] | 本体最终 ELF 4 处 `sltiu …,0xBA` |
| 容量 | **2350** = (0xBA-0xA1)×94 | 同上 |

```
slot  = (lead-0xA1)*94 + (trail-0xA1)            # 0..2349
row   = slot // 64 ;  col = slot % 64
x     = 16 * col                                  # 格左上角（texel）
y     = 3 + 16 * (row + (2 if row >= 12 else 0))  # 行 0..11 在 y=3..179；行 12..36 在 y=227..611
u0,u1 = x, x+16 ;  v0,v1 = y, y+16               # PSMT4，texel 单位
```

**行 r=12 之前有 32 行高的空隙（y=195..227）**，专门放 ASCII/单字节码的 FT 记录带（§2.4）；
**r=36 行（y=611）只有 col 0..45 属于对偶槽容量**（slot 2304..2349），col 46..63 让给 ASCII 带。

> ELF 侧订正（elf-analyst 实测）：本体 ELF 的 CharWidth cave 里 `mult` 是 **R5900 三操作数**，
> 乘积真实写入 ⇒ `slot=(lead-0xA1)*94+(trail-0xA1)` 在盘上真实生效，历史文档“乘积被丢”的说法作废。

### 2.3 引擎图布局（1024×644 文字示意图）

```
y=0..2       : 空（3 行留白）
y=3..178     : CJK 网格行 0..11（12 行 × 64 格，格 16×16，行距 16）
y=179..194   : 行 11 的下 15 行（正常格高）
y=195..226   : ★ 32 行高空隙：单字节/ASCII FT 记录带（见 §2.4）
y=227..626   : CJK 网格行 12..36（25 行 × 64 格；行 36 = y=611..626）
y=611..626   : 行 36 = 对偶槽 slot 2304..2349（col 0..45）+ ASCII 带（col 46..63，x=736..1018）
y=627..642   : ASCII 带第二行（x=0..368；此 y 段没有对偶槽）
y=643        : 不被采样（容器只传到 642.97 行）
```

### 2.4 ASCII / 单字节码的 FT 记录带（**不在网格行上**，引擎按记录矩形直接采样）

| 带 | 记录数 | 去重矩形 | x 范围 | face 分布 | 说明 |
|---|---|---|---|---|---|
| `v=611..627 h=16` | 86 | 22 | 736..1018 | large 38 / default 38 / huge 10 | ASCII 上段（与行 36 的 col 46..63 重叠） |
| `v=627..643 h=16` | 135 | 45 | 0..368 | large/default/huge 各 45 | ASCII 下段 |
| `v=195..211 h=16` | 124 | 62 | 0..992 | large 62 / default 62 | 单字节码带 1 |
| `v=211..227 h=16` | 180 | 72 | 0..986 | large 72 / default 72 / huge 36 | 单字节码带 2 |
| `v=211..224 h=13` | 10 | 4 | 256..311 | 三面 | ç/ñ 等 13px 记录 |
| `v=208..224 h=16` | 9 | 3 | 992..1016 | 三面 | U/V/W 等特殊记录 |

**实测：全部 544 条 FT 矩形与 2350 个对偶槽格位零交叠（0 px）** ⇒ 2350 个 slot 全部可用；
`huge` 面在中文版只有 96 条（code 0x20..0x7F 的 ASCII），其余面覆盖 224 条（ASCII + 单字节带）。

### 2.5 逐行账本（FINAL 成品实测；`used` = charset 里映射到该行的对偶键数）

| r | y | slots | used | 真汉字 | PUA | 有墨格 | 空格 | col63 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 3 | 64 | 62 | 61 | 1 | 61 | 3 | 1 |
| 1 | 19 | 64 | 62 | 61 | 1 | 61 | 3 | 1 |
| 2 | 35 | 64 | 64 | 63 | 1 | 63 | 1 | 1 |
| 3 | 51 | 64 | 62 | 61 | 1 | 61 | 3 | 1 |
| 4 | 67 | 64 | 62 | 61 | 1 | 61 | 3 | 1 |
| 5 | 83 | 64 | 64 | 63 | 1 | 63 | 1 | 1 |
| 6 | 99 | 64 | 62 | 61 | 1 | 61 | 3 | 1 |
| 7 | 115 | 64 | 62 | 61 | 1 | 61 | 3 | 1 |
| 8 | 131 | 64 | 64 | 63 | 1 | 63 | 1 | 1 |
| 9 | 147 | 64 | 62 | 61 | 1 | 61 | 3 | 1 |
| 10 | 163 | 64 | 62 | 61 | 1 | 61 | 3 | 1 |
| 11 | 179 | 64 | 64 | 63 | 1 | 63 | 1 | 1 |
| 12 | 227 | 64 | 62 | 61 | 1 | 63 | 1 | 1 |
| 13 | 243 | 64 | 62 | 61 | 1 | 61 | 3 | 1 |
| 14 | 259 | 64 | 63 | 62 | 1 | 62 | 2 | 1 |
| 15 | 275 | 64 | 63 | 62 | 1 | 62 | 2 | 1 |
| 16 | 291 | 64 | 62 | 61 | 1 | 61 | 3 | 1 |
| 17 | 307 | 64 | 62 | 61 | 1 | 61 | 3 | 1 |
| 18 | 323 | 64 | 64 | 63 | 1 | 63 | 1 | 1 |
| 19 | 339 | 64 | 62 | 61 | 1 | 61 | 3 | 1 |
| 20 | 355 | 64 | 62 | 61 | 1 | 61 | 3 | 1 |
| 21 | 371 | 64 | 64 | 63 | 1 | 63 | 1 | 1 |
| 22 | 387 | 64 | 62 | 61 | 1 | 61 | 3 | 1 |
| 23 | 403 | 64 | 62 | 61 | 1 | 61 | 3 | 1 |
| 24 | 419 | 64 | 64 | 63 | 1 | 63 | 1 | 1 |
| 25 | 435 | 64 | 62 | 61 | 1 | 61 | 3 | 1 |
| 26 | 451 | 64 | 62 | 61 | 1 | 61 | 3 | 1 |
| 27 | 467 | 64 | 64 | 63 | 1 | 63 | 1 | 1 |
| 28 | 483 | 64 | 62 | 61 | 1 | 61 | 3 | 1 |
| 29 | 499 | 64 | 62 | 61 | 1 | 61 | 3 | 1 |
| 30 | 515 | 64 | 64 | 63 | 1 | 63 | 1 | 1 |
| 31 | 531 | 64 | 62 | **50** | 12 | 50 | 14 | 1 |
| 32 | 547 | 64 | 62 | 0 | 62 | 0 | 64 | 1 |
| 33 | 563 | 64 | 64 | 0 | 64 | 0 | 64 | 1 |
| 34 | 579 | 64 | 62 | 0 | 62 | 0 | 64 | 1 |
| 35 | 595 | 64 | 62 | 0 | 62 | 0 | 64 | 1 |
| 36 | 611 | **46** | 46 | 5 | 41 | 5 | 41 | 0 |
| **合计** | | **2350** | **2300** | **1966** | **334** | **1968** | **382** | **36** |

- `有墨格 1968` = 1966 真汉字 + 2 个残留墨的 PUA 槽（补画新字时需先清格，见 §5.7）。
- 真汉字图集墨量 = **148,935 texel**（`texel==0`）；抽样 30 个汉字与 `third_party/fonts/方正像素16.ttf`
  逐像素比对 **30/30 xor==0**（复现：`python tools/font/font_probe.py --iso <盘>`）。

### 2.6 容量与空闲格（决定“资料片新字”能加多少）

| 项 | 数量 | 说明 |
|---|---:|---|
| 对偶槽容量 | 2,350 | gate 0xBA 决定 |
| 其中**引擎采不到**的 col-63 槽 | **36** | 格 x=1008..1023 右缘贴图集边界 1024，历史实测采样不到（本体把 36 个字从 col-63 迁走） |
| 有效可用槽 | **2,314** | 2350 − 36 |
| 已用真汉字 | 1,966 | 全部有字形（本体成品） |
| 可改给新字的 PUA 占位槽 | **298** | 334 PUA − 36(col63)；全部**零墨 + 零引用**（正文没引用过） |
| 完全未映射的空槽 | **50（全部不可用）** | ★ 这 50 个槽的 trail 恰好全是 **0xB1/0xB5** —— 本体 `_trail_fix_hashr` 实证：引擎 DrawString/CharWidth 对这两个字节有**硬编码图标特判**，命中会逐字符写坏内存。它们是**哨兵槽**，不是可用空槽 |
| **资料片新字容量（安全）** | **298** | = 298 PUA 回收槽；截至 2026-10-22 已分配 33（slot 2036..2069），**剩 265**（§10） |

> ▶ 容量口径修正：早期把 50 个哨兵槽算进「346/348」是**高估**；安全上限 = **298**。若未来缺字 > 298，再评估
> 加高图集（1024×676，+64 槽）或迁 col-63 槽（需全盘重编码，代价大）（§8 R5）。
> ▶ 另：334 个 PUA 占位槽中，36 个落在 col-63（不可用），其余 298 个全部零墨、且 PUA 字符在 3,001 条译文里
> 引用次数 = 0 ⇒ 可安全回收（回收 = 删 PUA 键、以**同一对偶码**登记真字，pair 总数不变）。

---

## 3. FONT.RES 三方 diff

### 3.1 结构（三盘同构）

```
{u32 nameLen=20}{"new_font_revised.rsb"}{u32 nfaces=3}
每个 face：{u32 nameLen}{name}{14×u32 fld}{nrec × 10B 记录}   nrec = fld[4]*fld[5]
尾部：{u32 count}{count × 样式记录}   样式记录 = {u32 nameLen}{name}{25 B 字段}
记录：{u8 f0}{u8 advance}{u16 u0}{u16 v0}{u16 u1}{u16 v1}   （idx = code-0x20）
```

### 3.2 三方对照表

| 项 | 本体英文 | **资料片** | 本体中文（FINAL） |
|---|---|---|---|
| 展开长度 | 7,222 B | **7,466 B** | 5,942 B |
| 帧 | 1 帧（clen 4,413 / rlen 7,222），存 4,421 | 1 帧（clen 4,452 / rlen 7,466），存 4,460 | 1 帧（clen 1,498 / rlen 5,942），存 4,421 |
| face 记录数 | 224 / 224 / 224 | **224 / 224 / 224** | 224 / 224 / **96** |
| large/default 的 fld | `[10,26,26,26,32,7,…]` | **与本体英文逐字节相同** | `[10,26,32,32,32,7,…]`（fld[2],[3] 26→32） |
| huge 的 fld | `[10,42,52,42,16,14,…]` | 同本体英文 | `[10,16,52,42,16,6,…]`（nrec 96 = 仅 ASCII 0x20..0x7F） |
| ASCII 记录矩形 | large/default 14×26、huge 27×42 | **672 条与本体英文全部相同（same=224×3, diff=0）** | 重绘为 **8×16**（三面共用 ASCII 带；ç/ñ 7×13；0x92/0xAE 16×16） |
| 尾部样式表 | 278 B / **8 条** | **522 B / 15 条** | 278 B / 8 条（仅 1 个 float 与英文不同：1.64→1.0） |

### 3.3 差额 244 B 是什么（精确回答）

- 尾部样式表 = `{count}{count 条记录}`，每条 = `{u32 nameLen}{name}{25 B}`：
  - 本体：8 条 = `default×2, large×4, huge×2` → `4 + 8×4 + (2×7+4×5+2×4) + 8×25 = 278 B`
  - 资料片：15 条 = `default×5, large×8, huge×2` → `4 + 15×4 + (5×7+8×5+2×4) + 15×25 = 522 B`
- **244 B = 7 条多出来的样式记录**（`default`+3、`large`+4；含 0.3/0.45/0.6/0.8 等 float 缩放/参数）。
- 结论：**资料片引擎可能按样式 index 取样式（0..14）** ⇒ 中文 FONT.RES 的 8 条尾部**不能**直接用在资料片。

### 3.4 中文 FONT.RES 能否直接用于 DLC

**不能直接用**，有三个硬伤：
1. 尾部只有 8 条样式（资料片 15 条）→ 若引擎按 index≥8 取样式会越界；
2. huge 面只有 96 条记录（资料片声明 224）→ loader 若固定读 224 条会越界读；
3. 中文 ASCII/单字节记录指向**中文图集的 8×16 带**，与资料片的英文图集坐标无关（这一点反而是我们要的，见 §5）。

### 3.5 合并 FONT.RES（本方案采用，恰好 7,466 B）

| 组成部分 | 来源 | 说明 |
|---|---|---|
| large（224 条）+ default（224 条） | **本体中文** | ASCII 8×16 带 + 单字节带，与中文图集完全对应 |
| huge（96 条 ASCII） | **本体中文** | code 0x20..0x7F |
| huge 的 96..223（128 条） | **填入退化记录** `(0,0,0,0,0,0)`，且 `fld[5]=14`（16×14=224） | 保持“224 条/face”声明，**不改变 loader 的 count/base 假设**；非 ASCII 单字节若用 huge 面画出来是空白（不是乱码） |
| 尾部 522 B / 15 条样式 | **资料片原盘** | 保留资料片可能引用的 style index ≥ 8；同时保住 244 B 差额 |

- 合并后展开 **7,466 B**（= 资料片原 real）；LZO(level7, m1, m4) 压缩帧 **1,572 B**（clen 1,564）
  ≤ 原槽 **4,460 B**（余 2,888 B）⇒ **原地覆盖 GR#580，stored/real/off 三字段一个都不用改**，尾部补 0。
- 自证：large/default 224/224 条与中文源**逐条相同**；huge 前 96 条相同、后 128 条为退化记录；尾部与资料片逐字节相同。

---

## 4. 方案对比（A vs B），含原型实测

### 4.1 方案 A：1024×512 PSMT4 原地等大小替换（**否决**）

**设计**：psm19 512×512 PSMT8 262,160 B → psm20 1024×512 PSMT4，像素 = 1024×512/2 = 262,144 B + 16 B GIF tag = **262,160 B（字节数完全相等）**，
50 列 × ... ⇒ 64 列 × 32 行 = **2048 格**（需把网格常量改成 Y0=0/SKIP=0）。

**原型实测（`python tools/font/build_font.py --plan-a`）**：
- ✅ 容器结构合法：单包 `[16B GIFTAG nloop=0x4000 EOP=1 FLG=2][262,144B]` = 262,160 B，回读引擎图 **xor=0**；
- ❌ **内容装不下**：真汉字 1,966 个；ASCII/单字节 FT 带的**唯一矩形并集面积 40,664 px² ≈ 159 个 16×16 格**
  ⇒ 需要 `1966 + 159 = 2125 格 > 2048 格`；即使把三面 ASCII 压到最小也无解，且**没有余量给资料片新字**；
- ❌ 512 行以外直接丢 **494 个 slot**（行 30..36 全部越界，包括 zh139/140/141 新补的 25 字所在的 31/32+ 行）；
- ❌ 还要重写全部 544 条 FT 记录 + 全盘文本重编码（码位重排），工作量与风险远大于 B。

**结论：方案 A 不可行**（不是“风险略高”，是容量数学上不够）。其唯一优点是 ISO 体积不变。

### 4.2 方案 B：1024×644 / 2350 槽（**推荐**）

- 图集/槽位/码位 = **本体成品原样**：2,300 个 pair 映射一个字节都不动 → 已有中文译文**零重编码**；
- 新增 PAK 66,624 B（262,160 → 329,744 换图集，净 +67,584；CLUT 从 1,040 换成资料片原生 80 B 形状，−960）；
- 放置策略：**新 COMMON.PAK 追加到 GR.IMG 末尾**（不推挤 #10..#3110，避免改 3,101 个条目的偏移字段），
  只改 GR#9 的三字段 + GR.IMG 头声明大小 + 根目录 GR.IMG size + PVD volume_space，ISO 尾部扩 403 扇区；
- 代价：旧 COMMON.PAK 位置 763,676 B 变成死区、GR.IMG 尾部 64KB pad 被新 PAK 覆盖；
  总“浪费”约 0.75 MB（占盘 0.06%），换来的好处是**其余 3,109 条条目逐字节不变**（可全量自证）。

### 4.3 对比表

| 维度 | 方案 A（1024×512 原地） | **方案 B（1024×644 扩盘/重定位）** |
|---|---|---|
| ISO 体积 | 不变 | 1,229,225,984 → 1,230,051,328（**+825,344 B / 403 扇区**） |
| ISO9660 修改 | 无 | PVD volume_space + 根目录 GR.IMG size + GR.IMG 头 + GR#9 三字段 |
| 槽位 | 2048（丢失 494 slot） | **2350（原样）** |
| 真汉字能否全保 | ❌ 1966+159 > 2048 | ✅ 1966 全部保留（xor==0） |
| 新字容量 | 0（还倒欠） | **346 格零墨可直接补画** |
| 码位/文本重编码 | 必须全盘重编码 | **不需要**（pair 映射不变） |
| FONT.RES 改动 | 全部 544 条 FT 记录重写 | 合并式（§3.5），ASCII 语义不变 |
| 工作/风险 | 高 | 低（原型已 28/28 PASS） |
| 结论 | ❌ 否决 | ✅ **推荐** |

### 4.4 上一版 JS_ZH19（512×512 PSMT8 原地换）实测评估 —— A' 备选，**否决为主方案**

> 输入物证：`work/analysis/js19/payloads/00009_COMMON.PAK.bin`、`00580_FONT.RES.bin`
> （2026-10-21 16:19 上一版 Chinese 构筑的 PCSX2 转储；其 ELF 已交 elf-analyst 反汇编）。
> **复现**：`python tools/font/js19_analyze.py`（只读上述 payload，输出 `work/analysis/font/js19_geometry.json`：
> 网格/行账本/face 布局/尾部异常）。★ 其中"网格"是**早期估算**；实际几何以 js19-recovery 的
> **OCR + pair map** 为准（`work/analysis/js19/js19_charset.json`：62 列 × 8×16、pair_cap=1222，见下表）。

**实测结果（全部现读，非推测）**

| 项 | JS19 实测 |
|---|---|
| COMMON.PAK | 763,676 B（与英文原盘同尺寸），sha256 `59becb28e60d3dfc…`；10 条记录同名同序 |
| `new_font_revised` | **psm=19 (PSMT8) 512×512 / clut=1040 / px=262,160**（与英文原盘记录形状完全一致）；容器 sha256 `542c88f6cae48683…` |
| 像素取值 | **只有两种索引：0（墨，66,352 px）与 15（空，195,792 px）**；16B GIF tag + 262,144 B 单包 |
| CLUT | 1040 B，tag NLOOP=0x40（256 色）；palette[0]=`7FFFFFFF`（墨），其余沿用原盘 alpha 表 |
| CJK 网格（**OCR + pair map 验证**） | **62 列 × 8×16 格**：`x = 2 + 8*col`（col 0..61，x0=2）、`y(r) = 2 + 16*(r + 3*[r>=12])`（y0=2 / SKIP_ROW=12 / SKIP_ROWS=3）；cell 8×16 px |
| 对偶容量 | **1,222 格** = **13 lead × 94 trail**（`js19_charset.json.geometry.pair_cap`，与 ELF 侧 cave 常量互证：`sltiu 0xAE`/`0xA1`/`0xFF`，见 `docs/ANALYSIS_ELF_DBCS_PORT.md §6.3`）；**< 1,966 真汉字（差 744 格）** ⇒ 只能承载缩减字集 |
| 解码器 / gate（js19-recovery 实测） | `byte<0xA1 → single`；`0xA1≤byte<0xAE 且 next∈[0xA1,0xFF) → pair(2B)`；否则 single。pair lead 仅 **A1..AD**，trail A1..FE |
| 数据层还原结果（js19-recovery） | 2,971 条文本中 **2,278 条有变化**、其中 **2,275 条中文 / 22,594 个汉字**；`unknown_chars=0`、`low_conf=0`；已用 pair 813（OCR 高置信 812）、single 168；cave gate 是**有状态**的（elf-analyst：真 pair 只命中 14,455 次） |
| 数据层一致性 | ★ **JS19 的数据层是自洽、可完整还原的**（不是"数据/几何不匹配"）；`js19_charset.json` / `js19_decode_stats.json` 为证 |
| FONT.RES 尾部（崩溃主因） | 544 B、count 字段=15，但物理上 **16 条**自描述记录；第 8 条（rec7 huge）只剩 **11 B**（正常 33 B）⇒ 展开 **7,488 = 7,466 + 22**；顺序解析从 rec8 起漂移 ⇒ 字体指针变垃圾（emulog `[[a0+0x28]+0x24]`，a0=0xFFFFFFFC）；另有 **def NULL 防护缺失** |
| FONT.RES | stored 4,460 / 展开 **7,488 B**（clen 1,736）；3 face **224/224/224**；large/default 的 fld 与本体中文相同（fld[2,3]=32），huge fld[1]=16/fld[5]=14；large 与 default 记录 224/224 完全相同，huge 与它们只有 96/224 相同 |

**结论（回答“B 是否仍推荐”）**：
1. **B 仍是唯一能承载现有 1,966 字译文 + 298 格新字余量的方案**。JS19 的 512×512 路线对偶容量只有 **1,222 格**
   （62 列 × 8×16，OCR/pair map 验证），还差 744 格；要复用就得把译文压缩到 ≤1,222 字——等于重做一套大幅缩水的翻译，不可接受。
2. JS19 只证明了「**同尺寸替换 + 补丁 ELF 能进到标题画面**」，**没有**证明 1024×644/PSMT4 的 loader 路径；
   B 的 loader 风险仍按 §8 R1 用模拟器验证（本体同引擎代码 + 资料片自身 psm20 记录是现有证据）。
3. **JS19 的数据/几何是自洽可还原的**（js19-recovery：2,275 条中文 / 22,594 汉字全解出，unknown=0），
   问题只出在 **FONT.RES style 表 off-by-22** 与 **def NULL 防护缺失** —— 后者导致 38s 后的 TLB Miss
   （`[[a0+0x28]+0x24]`，a0=0xFFFFFFFC）与崩溃。不能把"崩溃"归因于"JS19 几何错误"。
4. **A' 定位**：仅在“最终必须保持 ISO 原尺寸”这一硬约束下才考虑；届时需要：重做 **≤1,222 字**缩减译文
   （geometry 62×8×16 / pair_cap=1222 / gate A1..AD 已由 OCR+pair map 验证，无需再逆向）+ 修 FONT.RES style 表。
   **不作为主方案，也不作为当前备选**（B 的扩盘代价只有 +0.06% 体积，风险收益明显更优）。

> ★ **ELF 侧定论（elf-analyst，2026-10-21 晚）**：JS19 的崩溃不是 cave 逻辑问题，而是**加载期 FONT.RES 尾部损坏**：
> 展开 7,488 = 7,466 + 22，物理上第 8 条（rec7 huge）只剩 11 B（正常 33 B，缺 22 B）⇒ 顺序解析从 rec8 起漂移；
> emulog 中 `[[a0+0x28]+0x24]`（a0=0xFFFFFFFC）说明**字体指针本身是垃圾**。即：抄 JS19 不仅容量不够，
> **其 FONT.RES 结构本身也是坏的（style 表 off-by-22）**；B 方案的 FONT.RES 必须整表结构自洽（我们用 33 项回读自证把关）。

> ★ **JS19 的另一条教训（elf-analyst 伪汇编，`work/analysis/elf/js19_cave_pseudoasm.txt`）**：JS19 的折行函数
> `0x21B780` 在 block F（`0x180BD8`）被 cave 替换，其逻辑为「`CharWidth + CharHeight` 相加后累加」——
> 把高度当宽度用，语义可疑；且该 wrap 路径与我们 v2 覆盖的 DrawString/CharWidth/UV/StringWidth 主链**不同**。
> 所以「抄 JS19 几何」不仅是容量不够，它的折行路径本身也未经验证 —— 这正是 B 方案不复用 JS19 的第二个理由。

---

## 5. 推荐方案 B：字节级步骤

> 实现：`tools/font/fontlib.py`（库）+ `tools/font/build_font.py`（构建/自证）。以下所有数字都是实测输出。

### 5.1 输入 → 输出

```
输入：DLC 英文原盘（只读）
      third_party/ref/zh_font_seed/  ← tools/font/extract_seed.py 从本体成品一次性提取（本地自备）
        FONT_RES.MENU4.zh.bin  5,942 B  sha256 c7876128…（引擎真正读的副本）
        FONT_RES.GR906.zh.bin  5,942 B  sha256 6eb1b15f…（副本，差 24B，留档）
        COMMON_PAK.MENU3.zh.bin 468,243 B sha256 07bf96dd…（含 1024×644 图集记录）
        charset_compiled_zh16.json 145,740 B（与 assets 同源，sha256 互校验）
        meta.json（全部来源/偏移/大小/sha256/几何/账本）
      assets/charset/charset_compiled_zh16.json（本项目资产）
输出：新 ISO + build_report.json + PNG 预览
```

### 5.2 步骤 ①：新 FONT.RES（原地覆盖 GR#580，尺寸不变）

1. 解 GR#580 的 LZO 帧 → 资料片展开态 7,466 B；
2. 取 seed 的中文 FONT.RES 展开态 5,942 B（3 face：224/224/96 + 278 B 尾部）；
3. 按 §3.5 合并：中文 large/default + 中文 huge 96 条 + 128 条退化记录（huge `fld[5]=14`）+ 资料片 522 B 尾部
   ⇒ **7,466 B**；
4. LZO 压缩（level 7, m1+m4）→ 帧 `{u32 clen=1,564}{u32 rlen=7,466}{comp}` = 1,572 B；
5. 写回 `GR#580` 的 `iso_off = GR.IMG 基址 + 39,818,976`（= 绝对偏移 164,746,976），后面补 0 到原 `stored=4,460`；
   **条目的 stored/real/off 全部不改**（real 恰好仍是 7,466）；
6. 断言：展开长度 == real；三 face nrec == 224/224/224；尾部 == 资料片 522 B；帧 ≤ 4,460。

### 5.3 步骤 ②：新 COMMON.PAK（+66,624 B）

1. 解析原 COMMON.PAK 的 10 条记录（记录链以 `{u32 0x63}{u32 0}` 哨兵结尾）；
2. 定位 `new_font_revised`（记录 #6，头部偏移 `hdr_off`、结束 `rec_end`）；
3. 新记录 = 原记录的 `type/nameLen/name`（逐字节保留）+ 新字段 +
   `psm=0x14, w=1024, h=644, clut=80` + **新 CLUT（80 B）** + `u32 px_size=329,744` + **中文图集容器 329,744 B（seed 逐字节拷贝）**：
   - 新 CLUT（资料片 psm20 原生形状，取自 `pda-lcd-02` 实测）：
     `[16B GIF tag: w0=4|(1<<15)=0x8004, w1=2<<26=0x08000000, w2=w3=0]`
     `+ 16 色 ×4B（palette[0]=0x7FFFFFFF 墨；[1..15]=0x00FFFFFF 透明）` = 80 B；
   - 像素容器 = **seed 里的 329,744 B 原样拷贝**（11 段 GIF 流 + 末尾 16B 空 tag；**一个字节都不重编码**）；
4. 新 PAK = `原 PAK[:hdr_off] + 新记录 + 原 PAK[rec_end:]` ⇒ **763,676 → 830,300 B（Δ+66,624）**；
5. 断言（回读）：10 条记录名字/顺序不变；除目标记录外每条记录字节不变；图集记录几何 == (20,1024,644,80,329744)；
   记录内像素容器 == seed。

### 5.4 步骤 ③：写入 GR.IMG 与 ISO9660（**精确修改点**）

实测资料片 GR.IMG（ISO9660 root 里 `GR.IMG;1` LBA = **61000**，size = **1,104,291,830**）：

| 量 | 值 |
|---|---|
| GR.IMG 条目表头 | `+0x0` = 声明总大小（== 根目录 GR.IMG size）；`+0x4` names_end；`+0x10` names_off；`+0x830` 条目表起点，48 B/条 × 3,111 |
| 条目表末 | `max(off+stored)` = **1,104,226,294**；声明大小 = 它 + `0x10000`（64 KB pad，实测同构） |
| 放置点 | `new_off = align16(1,104,226,294) = 1,104,226,304`（GR.IMG 内偏移；绝对 = 124,928,000 + 该值 = `1,229,154,304`） |
| 新 PAK 长 | 830,300 B ⇒ `new_last_end = 1,105,056,604` |
| 新声明大小 / 根目录 size | **1,105,122,140** = new_last_end + 0x10000 |
| 新 ISO 尺寸 | `align2048(124,928,000 + 1,105,122,140) = 1,230,051,328`（= 600,611 扇区，+403 扇区 / +825,344 B） |

修改点（全部相对 ISO 文件绝对偏移；写前先 `shutil.copyfile` 到新文件，原盘只读）：

| # | 位置 | 原值 → 新值 | 长度 |
|---|---|---|---|
| ① | ISO 尾部 | 原 1,229,225,984 → **truncate/extend 到 1,230,051,328**（新增区全 0） | — |
| ② | PVD（扇区 16）`+80` / `+84` | volume_space LE / BE：600,208 → **600,611** | 4+4 B |
| ③ | 根目录里 GR.IMG 记录 `rec_off=534,976`：`+10`(LE) / `+14`(BE) | size：1,104,291,830 → **1,105,122,140** | 4+4 B |
| ④ | GR.IMG `+0x0`（绝对 124,928,000） | 声明总大小：同上 → **1,105,122,140** | 4 B |
| ⑤ | GR.IMG 条目 #9 表项（`tab_off = 124,930,528`）`+24/+28/+32` | `stored/real = 830,300`；`off = 1,104,226,304`（**只改这三个 u32**） | 12 B |
| ⑥ | 新 PAK | 写入绝对偏移 **1,229,154,304**，长度 830,300 | 830,300 B |
| ⑦ | GR#580 载荷 | 覆盖绝对偏移 **164,746,976**（1,572 B 帧 + 2,888 B 零填充） | 4,460 B |

**不改**：条目 #9 的其余 9 个字段（含 `[0][1][9][10][11]`）、其它 3,110 条条目的所有字段与载荷、
名字表/条目表其它区域、GR.IMG 内部其它数据、其余 root 条目、ISO 其余扇区。旧 PAK 位置（GR.IMG+0xE0020）成为死区。

> ✅ 条目表 12 字段语义已由 iso-analyst 全盘实证（3111/3111）：`[0]`=名字区累计偏移、`[1]`=按名字升序的链表 next、
> `[4]`=raw/LZO 标志（#9=0 raw）、`[5]`≡1、`[6]`/`[7]`=stored/real（raw 条目恒相等）、`[8]`=容器内偏移（全盘 16 字节对齐）、
> `[9]`=名字派生键、`[10]`=12-bit 名字哈希（桶号 `((u32>>16)<<6)|(u32&0x3F)`）、`[11]`=哈希桶冲突链 next。
> ⇒ **只有 `[6][7][8]` 需要改，其余必须原样保留原盘值（不依赖载荷/偏移）**；本原型按此实现并逐项断言（§5.5）。

### 5.5 步骤 ④：回读自证（**33 项，全部 PASS**）

`tools/font/build_font.py --out-iso …` 写盘后自动跑 `fontlib.verify_plan_b()`，逐项断言（节选，完整见 `build_report.json`；
输出文件被模拟器占用时可加 `--verify-only <iso>` 只回读自证，不重新出盘）：

```
ok  PVD volume_space LE==BE==600,611 扇区 (ISO 1,230,051,328 B)
ok  ISO 尺寸 == 预期；根目录 GR.IMG size == 1,105,122,140 (LE/BE 双写)
ok  GR.IMG 头 +0x0 == 根目录 size；头/根 size/max(off+stored)+0x10000 三者自洽
ok  IMG 条目数一致 (3111)
ok  3111 条条目表除 #9 的 [6][7][8] 外逐字段不变 (违例 0)
ok  只有 #9 COMMON.PAK 与 #580 FONT.RES 载荷变化，其余 3109 条逐字节不变
ok  #580 FONT.RES 条目表 12 字段不变（原地覆盖）
ok  新 COMMON.PAK 10 条记录、名字/顺序不变
ok  new_font_revised = psm20 1024x644 px=329744
ok  图集容器逐字节 == seed
ok  引擎图 = 11 段 GIF 封包（每段 48B 头；无相位）
ok  回读引擎图 vs seed 图集逐 texel xor==0 (差异 0)
ok  2350 个网格 slot 逐格 xor==0 (差异 0)
ok  FONT.RES 展开 7466 == real 7466；三 face 224/224/224；尾部 522B；blob sha == 预期
ok  #9 [6]==[7]==新载荷长度 830300；[4]=0（raw）
ok  #9 [0][1][9][10][11]（name_off/名字升序链/名字键/哈希桶/冲突链）与英文原盘完全相同
ok  #9 新 off=0x41D12800 16 字节对齐；新 data_end 只增不减（旧 1,104,226,294 → 新 1,105,056,604）
```

**独立校验**：`7z t <新 ISO>` → `Type = Iso, Everything is Ok`（Volume: SLUS_20820）。

### 5.6 像素搬运/保留规则（4bpp 半字节安全）

- **本方案不搬运任何已有像素**：中文图集容器 329,744 B 从 seed **逐字节拷贝**（= 1966 个汉字 + ASCII/单字节带全部原样）；
- 4bpp 写像素规则（`fontlib.atlas_write_pixels`，补画新字时用）：按封包段表定位数据区，
  **偶 x 写低 nibble（保留高 nibble）、奇 x 写高 nibble（保留低 nibble）**，绝不整字节覆盖；
- ASCII 像素保留规则：FONT.RES 里 large/default 的 ASCII/单字节 FT 记录**原样使用中文版**，
  它们指向的图集像素随容器整块保留 ⇒ 语义不变、像素不变（xor==0）；
- 汉字像素保留规则：2,300 个 pair 的码位/槽位映射原样（charset 不重排）⇒ 每格像素与本体成品 xor==0。

### 5.7 未画新字的补画流程（生产步骤 —— 已实现为 §10 的 `tools/font/expand_charset.py`）

1. 输入 = `work/translation/merged/missing_chars.json`（缺字表，频次降序；随译文更新可重跑）；
2. 从 **298 个零引用 PUA 占位槽**里按 slot 升序分配（跳过 col-63；**50 个 trail=0xB1/0xB5 哨兵槽禁用**）；
3. 渲染配方与本体 1,966 个字**同一配方**：`PIL truetype(方正像素16, 16px) → 32×32 白底 → text((8,8)) → [8:24,8:24] → <128`；
4. `fontlib.draw_glyphs()` 写回（4bpp 半字节安全），写后逐格回读 `xor==0`、非目标像素零改动、GIF 段头不变；
5. 同步 charset：删掉被回收 PUA 键、以**同一对偶码**登记真字（已有文本编码一个字节都不动，pair 总数不变）；
6. `assets/charset/charset_expand_dlc.json` 记录 `char→slot/pair/来源/槽类型`（单一真源）；详见 **§10**。

---

## 6. 原型验证结果（实测）

### 6.1 产物清单

| 产物 | 路径 | 大小 / sha256 |
|---|---|---|
| **方案 B 原型 ISO** | `work/analysis/font/GR_JS_ZH_FONT_planB.iso` | 1,230,051,328 B / `803cdcb6a08d0ff9a8e9bd67d5ff09118c198e9e9059b525fb7fda48c986d862` |
| 构建报告（全部数字+28 项自证） | `work/analysis/font/build_report.json` | — |
| 新 ISO 独立探测报告 | `work/analysis/font/probe_new_iso.json` | — |
| 图集引擎图 PNG | `work/analysis/font/planB_atlas_engine_1024x644.png` | 70,069 B |
| 30 汉字放大 PNG | `work/analysis/font/planB_sample30_cjk.png` | 2,575 B |
| ASCII/单字节带放大 PNG | `work/analysis/font/planB_ascii_band.png` | 2,914 B |
| docs 配图（≤200KB） | `docs/img/font_atlas_1024x644.png`、`docs/img/font_sample30_cjk.png` | 70,069 / 2,575 B |
| 字库 seed（本地自备，不进 git） | `third_party/ref/zh_font_seed/`（4 文件 + meta.json） | 见 `meta.json` |

### 6.2 关键对照数字

| 项 | 原盘 | 原型 | 说明 |
|---|---|---|---|
| COMMON.PAK | 763,676 B | **830,300 B** | Δ+66,624（图集 +67,584、CLUT 形状 −960） |
| 图集记录几何 | psm19 512×512 262,160 | **psm20 1024×644 329,744** | 引擎图 11 段 |
| FONT.RES | 4,460 存 / 7,466 real | 4,460 存（帧 1,572）/ 7,466 real | 原地覆盖，条目字段不变 |
| GR.IMG | 1,104,291,830 | **1,105,122,140** | 新 PAK 追加在末尾 |
| ISO | 1,229,225,984 / 600,208 扇区 | **1,230,051,328 / 600,611 扇区** | +825,344 B |
| 其余 3,109 条条目 | — | **逐字节不变** | 全量比对通过 |
| 图集像素 | — | **xor==0（整平面 + 2350 格）** | 回读自证 |

### 6.3 复现命令

```powershell
$PY = 'C:\Users\84363\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# ① 一次性提取 seed（本体成品 ISO → third_party/ref/zh_font_seed/）
& $PY tools\font\extract_seed.py
# ② 探测任意盘的图集（只读；可出 PNG）
& $PY tools\font\font_probe.py --iso "<盘.iso>" --png --json work\analysis\font\probe.json
# ③ 出方案 B 原型 ISO 并跑 33 项回读自证（约 3~10 秒；写 ~1.2 GB 到 work/，gitignored）
#    若输出文件正被模拟器占用，可改用 --verify-only <iso> 只回读自证
& $PY tools\font\build_font.py --plan-a --demo-new-chars --docs-img `
      --out-iso work\analysis\font\GR_JS_ZH_FONT_planB.iso
# ④ 逆向上一版 JS_ZH19 的图集几何（只读 payload dump）
& $PY tools\font\js19_analyze.py
```

---

## 7. 给 ELF 补丁的几何参数（回答 lead 的 5 问；已与 elf-analyst 双向核对）

1. **图集最终几何**：psm=**0x14 (PSMT4 4bpp)**，w=**1024**，h=**644**；每行 **64 格**；格 **16×16 texel**；
   `slot=(lead-0xA1)*94+(trail-0xA1)`；`row=slot>>6, col=slot&63`；总槽上限 **2350**（0..2349）。
2. **UV 公式**：`u0=16*col, u1=u0+16`；`row>=12` 时 `row+=2`；`v0=16*row+3, v1=v0+16`。
   **不需要处理 GIF 段/TRXPOS 的“段内行偏移”**：loader 把整个容器按 DMA 命令流发到 GS，VRAM 里就是连续行
   ⇒ ComputeCharTextureCoords 直接用上面的 (u0,v0)，不要用“裸容器”物理偏移（那是历史坑：每段会错 6 格）。
   `CharWidth` 对 pair 恒 **16px**；单字节仍走 FT 记录（`idx=code-0x20`，10B 记录，rect=采样窗）。
3. **扩盘方案常量**：新图集记录在 **GR#9 COMMON.PAK 的记录 #6（`new_font_revised`）**：
   `psm=0x14,w=1024,h=644,clut=80,px=329,744`；记录布局 = `24B 头 + 80B CLUT + 4B px_size + 329,744B 容器`。
   ELF 里不需要新增“图集地址”常量（loader 走 PAK 记录）；**需要**的只有 §7.1 的几何常量 + gate。
4. **ASCII FT 语义不变**：`new_font_resvised.rsb` 仍 3 face × **224 条**记录（10 B/条，`+1=advance`,`+2 u0`,`+4 v0`,`+6 u1`,`+8 v1`）；
   large/default 用中文版（ASCII 8×16 + 单字节带），huge 前 96 条 ASCII + 后 128 条退化；**Chinese pair 不占 FT 记录**。
5. **方案 A 的 slot 重映射**：**不需要**（方案 A 已否决）。若将来真要 2048 槽压缩，重映射表可由
   `charset.pair_of` 按“真汉字排序 → 前 2048 个可用格”程序生成，但必须先做全盘文本重编码，代价见 §4.1。

### 7.1 ELF 补丁需要的立即数（与本体最终 ELF 逐字一致）

| 参数 | 值 | 本体最终 ELF 位置（供 elf-analyst 对照） |
|---|---|---|
| gate（lead 上界） | **0xBA** | 4 处 `sltiu …,0xBA`：VA 0x416EE8 / 0x417160 / 0x41751C / 0x5656A4 |
| NCOL | **64 (0x40)** | VA 0x4170AC 立即数 |
| Y0 | **3** | VA 0x4170F8 立即数 |
| SKIP_ROW / SKIP_ROWS | **12 / 2** | VA 0x4170E8 立即数（2）；SKIP_ROW=12 在 UV cave 内 |
| CELL | **16** | `U0=16*col`；`V0=16*row+3` |

---

## 8. 风险与 TBD（如实登记）

| # | 风险 | 影响 | 缓解/建议 |
|---|---|---|---|
| R1 | **资料片纹理上传器是否接受 1024×644 / PSMT4 / 80B CLUT**（**已降级为中风险**） | 若接受不了 → 图集不显示/花屏 | elf-analyst 全 ELF 扫描**未见 psm/h 上限比较**；DLC 原生就有 psm20 资产（pda-lcd-02，clut=80）⇒ **psm20+80B CLUT 是 DLC 原生路径**；CLUT 块格式经双向确认 = 12B 头(`0x08000000,0,0`)+16 色×4B+u32 px_size；px=像素+16B tag。唯一无先例的是 **h=644**（DLC 现存最大 512×512）⇒ 保留模拟器 smoke 验证（emu-analyst）；失败备选 `--clut-mode zh`（1040B 形状） |
| R2 | FONT.RES `huge` 面 96..223 = 128 条退化记录 | 若 huge 面被用于非 ASCII 单字节码 → 画空白（不是乱码） | 本体中文盘同样把 huge 减到 96 条并被接受；若需要，可后续把 128 条填成对应 ASCII/单字节记录 |
| R3 | ~~GR.IMG 条目表 `[0][1][9][10][11]` 语义未定论~~ **已解决**（iso-analyst 全盘实证：这些字段只依赖**名字**，与载荷/偏移无关；`[9]` 名字派生键、`[10]` 名字哈希桶、`[11]` 冲突链、`[0]`/`[1]` 名字区偏移/升序链） | 无（本方案只改 `[6][7][8]` 是正确且充分的） | 保留原值并在 33 项自证里断言 `#9 [0][1][9][10][11]` 与英文原盘完全相同（PASS） |
| R4 | ISO 尺寸变化（+403 扇区，非原盘镜像尺寸） | 模拟器/OPL 无碍；刻盘需重新制作；某些校验工具会提示 | 属预期（扩盘方案）；最终交付若要求“与原盘同尺寸”，可改走“原地推挤 #10.. 后移 33 扇区”的零增长变体（需 R3 先确认） |
| R5 | 资料片新字 > **298**（安全容量；早期口径 346 已修正，见 R11） | 放不下 | 截至 2026-10-22 已用 33、剩 **265**；超了再评估加高图集（1024×676，+64 槽）或迁 col-63 槽（需全盘重编码） |
| R6 | 中文 ASCII 是 8×16 重绘字体，与资料片原 14×26/27×42 英文视觉不同 | 英文界面字形变窄 | 这是本体成品的既定风格；中文语境下可接受；如需保留英文原字形，需要另存一张 ASCII 图集（工作量大） |
| R7 | 图集只传到 642.97 行，第 643 行不被写 | 无（没有采样窗到达 643+） | 无需处理；`h=644` 仅为声明尺寸 |
| R8 | 旧 COMMON.PAK 位置 763,676 B + 64 KB pad 成死区 | 体积 +0.06% | 可接受；后续如做“GR.IMG 紧凑重排”可回收（需重排全部条目） |
| R9 | ~~`font+0x24` 固定宽度标志来源未定~~ **已解决（elf-analyst 反汇编 + 三盘实测）** | 无 | `font+0x24` **不来自 face 头**，而来自 FONT.RES **尾部 style 块**：每条 style = `{u32 namelen, name, 4×u32, u8 b4, 2×f32}`（共 namelen+29 B），`b4→font+0x24`。实测 DLC 15 条 style、本体 EN 8 条、本体 ZH 8 条的 **b4 全部=0** ⇒ 固定宽度早退永不触发；我们的合并 FONT.RES 顺序反解析：count=15、剩余 0 B、b4 全 0（§3.5/§10.5） | face 头映射（copy-ctor @0x218F10）：`fld[12]`=base char(+0x20，中英都=32，未动)；`nrec=fld[4]×fld[5]`(+0x44)；记录表指针 +0x38。本体 ZH 成品盘 large/default `fld[2]/[3]=32`、huge `fld[1]=16` 与我们的值逐字一致 ⇒ 无需 A/B 变体 | ★ A′ 度量规整只改 face `fld[1]` 与 style 的 `f5/f6` 浮点，**不碰 style 的 `b4`（仍全 0）** ⇒ R9 的结论不受 A′ 影响。
| R10 | `huge` 面 `fld[5]=14 / nrec=224`（96 条 ASCII + 128 条退化记录）；本体 ZH 成品盘是 `fld[5]=6 / nrec=96` | 若 huge 面被用于 code≥128 的高位单字节码 → **引擎钳位到记录 0（def+0x44 count 判断：idx≥count ⇒ idx=0，不是越界）→ 画空白**；两种 nrec 选择都安全、视觉等价 | 保持 224 不必改：`nrec` 覆盖 code 32..255、公式内；elf-analyst 反汇编实证 CharWidth/UV 原版均为**越界钳位到记录 0**（`0x21A3DC bltz/slt→bnez→move v1,zero`），**不会**读到 style 块。实机 smoke 只需确认 huge 标题/大字正常，不会崩溃 | ★ A′ 后 huge `fld[1]` 仍=16、`fld[5]=14/nrec=224` 与 128 条退化记录均未变（style #7 的 f6 1.63→1.0 只影响 CharHeight，不影响 nrec/索引）。
| R11 | **50 个「未映射空槽」是 trail=0xB1/0xB5 哨兵槽** | 若当普通空槽用 → 引擎图标特判命中，**逐字符写坏内存**（本体 `_trail_fix_hashr` 实证：曾把 42 个对偶码迁走、8 个退役） | `expand_charset.py` 显式跳过 trail∈{0xB1,0xB5} 与 `_trail_fix_hashr.sentinel_slots`；安全容量按 **298** 计（不是 346/348）。如未来缺字超 298，先加高图集而不是动哨兵槽 |
| R12 | 字符集扩充后 `pair_of` 总数仍 2300（不是 2300+N） | 无（设计使然） | 扩充 = **回收零引用 PUA 占位键**（删 PUA 键、同一对偶码登记真字）⇒ 码位/槽位不变、已有文本编码不动；真字 1,966→1,999、PUA 334→301（33 字）；`codes` 103 条不变。安全容量里没有未占用的安全码位，所以「新增 pair 数」不可能 >0 |
| R13 | **实机反馈：large 面中文 pair 字形纵向拉伸/顶部裁剪**（标题「档案」顶部被切、按钮中文基线略低） | pair 字形 quad 高度 = `CharHeight = fld[1] × style.f6`（DLC 反汇编 0x21A440 实测），而 pair 源 UV 只有 16 行 ⇒ large/default（fld[1]=26）拉伸 1.63×，f6=1.64 的 style 拉伸 2.6×（标题）；ASCII 按 FT 记录矩形走不受影响 | **首选 B**：ELF cave 对 pair 分支把 quad 高度/采样高度固定为 16（垂直锚点顶/底/居中待实机选）；数据侧只提供常量。**降级 A-2**：large/default `fld[1]` 26→16 + tail 前 8 条 style 用本体 ZH 值（仅 #5 f5/f6 1.64→1.0）⇒ 中文大字 16px 正常，但英文大字会缩小 ~40%（ASCII 与 pair 共用 CharHeight）。已构建 A/B 变体盘见 §11 |
| R14 | **A′ 后仍存在的「记录 16px vs 度量」不一致**（复核结论，不改代码）：① `fld[13]`（def+0x24）仍为 26/26/42（A′ 只把 fld[1] 归 16；字体绘制路径无读取，但 EN/ZH 原盘二者恒等，若无 UI 行距异常可不管）；② style `f6=0.8` 的 5 条（#6/#8/#10/#13 及 #14 的 f6=1）⇒ CharHeight=16×0.8=12（int 12）⇒ 小字样式纵向 0.8 压扁（这与原盘 EN/ZH 的「小样式=0.8×字高」比例一致，属历史行为）；③ style `f5<1`（0.8/0.6 的 #6/#8/#9/#10/#11/#13/#14）⇒ pair CharWidth 恒 16 不乘 f5，而 ASCII advance=8×f5（6 或 5）⇒ 同一行中文/英文步进比 2.0→2.7~3.2×，小字混排略松、极窄 UI 有溢出风险 | 预期影响小：绘制路径验证 37/37 PASS；建议实机重点看小样式 UI（HUD/列表）是否溢出或压扁 | 处置建议：**不要**给 pair CharWidth 乘 f5<1（16px 字形会与相邻字重叠）；若发现溢出 → 改短文案（数据侧）或把该 style f6/f5 归 1.0（会失去小字层级）；`fld[13]` 若出现行距异常再一并归 16 | ★ 2026-10-22 抽查：菜单/对话框类画面（nav_menu 225s）小字 f6=0.8（确认 ink h≈10.5/quad12）未见裁切、HUD 中英混排无溢出 ⇒ 该风险降为『观察（仅游戏内 HUD 未覆盖）』。


---

## 9. 文件名 / sha256 清单（复现核对用）

| 文件 | 大小 | sha256 |
|---|---:|---|
| 资料片原盘 | 1,229,225,984 | `292f5a6a050e82e05efb5bf9fd5ce3bc12706a8ae57c78b729348a5c80fd0767` |
| 本体成品盘 | 1,648,164,864 | `4ded92e2fee535ac00893af60faee630323af124aa38a89d1777d1721d04617a` |
| seed `FONT_RES.MENU4.zh.bin` | 5,942 | `c7876128483c2b5b5a2af5edce458db528d9da73cfc138da29327b2f3c3b3a71` |
| seed `FONT_RES.GR906.zh.bin` | 5,942 | `6eb1b15f2456cef238416af59db52c0681b0ae54b864f2fcd840be0f1076f304` |
| seed `COMMON_PAK.MENU3.zh.bin` | 468,243 | `07bf96dd217e1801fc45cabbc60b87142c8108d171527d335b7a88a07358c450` |
| seed `charset_compiled_zh16.json` | 145,740 | `5658616833ba4c4b862bbd71c4905da79f0316acc93ab4b43f75120cf1cef504` |
| 中文图集容器（seed 内） | 329,744 | `cf4fbbd8d3e6666ae0eef66b8f3a37655d51f97a3095976eacff842b97f5585c` |
| DLC 原 `new_font_revised` 容器 | 262,160 | `15e40e7d68e586427a4147d124ac534c30d7d38b6f94def3461325f048f538da` |
| 合并 FONT.RES 展开态 | 7,466 | `7453115e6232a5b6baf5e6170edb55c7dd5bc20d70465ef1cf99ec7567b79a5d` |
| 合并 FONT.RES LZO 帧 | 1,572 | `701040c6aac76d72dd1fad498202295e5545a2b9b3cc4f73764ee827ebb09123` |
| 补画后图集容器（33 字） | 329,744 | `4a0340107e05c92b32965ed223f2a880f967c69d9b16c6c7c610930c8a898fd6` |
| 补画后 charset（pair 2300 / 真字 1999 / PUA 301） | 149,088 | `de54df1691dc929c88062185d1e48b72cb8e3c75d69854954f482129912c4afd` |
| `charset_expand_dlc.json`（单一真源） | 7,610 | `fb3782e696daafd198c2023c77c24694b30a98277c2a038cdf190d04cb387ab1` |
| 新 COMMON.PAK（补画后） | 830,300 | `ca34d7f67204caf5c2366fa1dbe0c6361dedfd64582ab93b0ea068f222108dff` |
| 旧原型 COMMON.PAK（补画前，已被上两行取代） | 830,300 | `1e57ab1dfd36ed69356e91367ad20326dad76057931d6dcaeaec1c070d63c9e5` |
| **新 ISO（补画前旧原型）** | **1,230,051,328** | `803cdcb6a08d0ff9a8e9bd67d5ff09118c198e9e9059b525fb7fda48c986d862` |

> ▶ 含「补画 33 字」的新测试盘请用 `python tools\dlc\build.py --stage all --out <out.iso>` 现场出盘；
> 上面旧 ISO 的 sha 只是补画前原型的记录（容器不同 ⇒ PAK/ISO sha 都会变）。

> 附：旧任务背景里的“图集 8 段”与“已画 1954 字形”**已过期**——实测为 **11 段**、**1,966 个真汉字**
> （FINAL = ZH146，zh139/140/141 各补了字）；“空 PUA 槽约 300”实测 **298 个可用 + 36 个 col-63 不可用**。
> 以上均以本体成品 ISO 现读为准（复现脚本 `tools/font/font_probe.py` / `tools/font/extract_seed.py`）。

---

## 10. 字符集扩充流程（缺字补画 / 可重跑；2026-10-22 实装）

> 方案 B 的最后一环：把**译文里出现、但 charset 里没有**的汉字，用 TTF 16×16 画进图集的
> 「零引用 PUA 占位槽」，并把 `char → 对偶码` 写回字符集。工具：`tools/font/expand_charset.py`。

### 10.1 输入 / 输出

| 方向 | 文件 | 说明 |
|---|---|---|
| 只读 | `third_party/ref/zh_font_seed/COMMON_PAK.MENU3.zh.bin` | 中文图集容器（329,744 B，sha 已在 seed meta 校验） |
| 只读 | `work/translation/merged/missing_chars.json` | 缺字表（`chars` 顺序=频次降序；随译文更新重算，**可重跑**） |
| 只读 | `work/translation/merged/translations_all.csv` | 全部译文（3,001 条，用于 PUA 引用计数 + 全量 encode 自证） |
| **回写** | `assets/charset/charset_compiled_zh16.json` | 全工程唯一字符集：新增 `pair_of` 条目；`codes` 103 条不动 |
| **回写** | `assets/charset/charset_expand_dlc.json` | 单一真源：`char→slot/pair/来源/槽类型` + 容量账 + sources sha |
| work | `work/analysis/font/container_expanded_1024x644.bin` | 补画后容器（可回滚/比对） |
| work | `work/analysis/font/expand_report.json` | 自证报告（每字槽位/格位/xor/示例译文/容量） |
| work | `work/analysis/font/charset_before_dlc_expand.json` | 回写前快照 |

### 10.2 槽位规则（确定性 + 安全边界）

1. **禁止** trail ∈ {0xB1,0xB5} 的槽：本体 `_trail_fix_hashr` 实证引擎对这两个字节有图标特判，命中写坏内存。
   实测 50 个「未映射空槽」**全部**是这类哨兵槽 ⇒ 一个都不能用（早期 346/348 容量口径据此修正为 **298**）。
2. 用**零引用 PUA 占位槽**：非 col-63、非哨兵、槽内零墨、且该 PUA 字符在 3,001 条译文里引用数 = 0；
   按 slot 升序分配（确定性）。
3. 跳过 col-63（x=1008 右缘贴 1024，引擎采不到；36 个 PUA 落在其中）。
4. **永不覆盖**已登记真汉字槽（无论译文是否引用）；已有 assignment 一律保留（重跑幂等）。
5. 分配顺序 = `missing_chars.json` 的 `chars` 顺序（频次降序）× 上述 slot 升序 ⇒ 同一输入必得同一映射。

### 10.3 当前分配（2026-10-22，33 字）

| # | 字符 | slot | row/col | 格位 (x,y) | pair | 被回收的 PUA |
|---:|---|---:|---|---|---|---|
| 1..11 | 订 港 税 邀 赔 钥 偿 睛 瑞 厅 译 | 2036..2046 | row31 col28..38 | (832,531)..(992,531) | B6DF..B6E9 | U+E264..U+E26E |
| 12..26 | 丛 碧 骑 洋 锤 枢 岔 橡 蜘 蛛 辅 裁 瓜 谁 伐 | 2048..2062 | row31 col40..54 | (0,547)..(224,547) | B6EB..B6F9 | U+E270..U+E27E |
| 27..33 | 葡 萄 芬 滴 亥 弗 汗 | 2063..2069 | row31 col55..61 | (240,547)..(336,547) | B6FA..B7A2 | U+E27F..U+E285 |

> slot 2047 跳过（col-63）；33 个新字全部落在 row31（y=547），互不重叠。
> 详细逐字表见 `assets/charset/charset_expand_dlc.json` 的 `assignments`（含 cell/xor/ink/old_pua）。

### 10.4 回写语义（为什么 pair 数不变）

- 回收 = 删除一个 PUA 占位键、以**同一对偶码**登记真字 ⇒ `pair_of` 总数 **2300 不变**；
  真字 1,966 → **1,999**，PUA 334 → **301**；`codes` 103 条不变。
- 已有文本的编码字节**一个都不动**（码位/槽位不变；旧 PUA 字符在正文引用数=0，删除无副作用）。
- 容量：安全 298、已用 33、**剩余 265**（`charset_expand_dlc.json.capacity`）。

### 10.5 渲染与自证（每次运行都跑）

1. 配方与本体 1,966 字相同：`PIL truetype(方正像素16,16px) → 32×32 白底 → text((8,8)) → [8:24,8:24] → <128`；
2. `fontlib.draw_glyphs()` 半字节安全写回；逐字回读 **xor==0**；
3. **非目标像素零改动**：解码全图对比，改动槽集合 == 目标槽集合（`atlas_non_target_changed=0`）；
4. 目标格「无墨→有墨」；容器长度不变（329,744）；11 段 GIF 段头字节零改动；
5. 字符集：逐字 `encode_strict(char)` == 对偶字节、`decode` 回环一致；
6. 全量译文：3,001 条 `encode_strict` **全部通过**（本次 141,811 B 编码成功）；
7. 示例译文：33 个新字各找一条真实语料（如「J04 - 海洋之锤」「J02 铁路枢纽」「在道岔上安放爆破装药」）
   单独 encode_strict → 全 OK（`expand_report.json.examples`）；
8. 幂等：写完立即重读重规划，**新增必须 = 0**。

### 10.6 构建期接口（build.py 已接）

`tools/dlc/build.py::font_provider()` 现在：

```python
import expand_charset as EC
container, exp = EC.expand_container(seed['container'])   # 读 charset + expand json，补画并校验（只读、不写文件）
new_pak, info = F.build_new_pak(dlc['pak'], dlc['recs'], seed,
                                clut_mode='native', container=container)
```

- `EC.apply(container, assignments, ttf_path=None) -> (new_container, rows)` —— 给定 assignments 直接补画（底层接口）；
- `EC.expand_container(container) -> (new_container, report)` —— 构建期一键（从 expand json/charset 取 assignment）；
- 常量：`EC.CHARSET` / `EC.EXPAND_JSON` / `EC.MISSING_JSON` / `EC.CORPUS_CSV` / `EC.OUTDIR`。

### 10.7 增量流程（译文继续增加时）

```
① 译文更新 → tools/dlc/merge_translations.py 重算 translations_all.csv / missing_chars.json
② python tools\font\expand_charset.py          # 自动追加新字（已有 assignment 保留；幂等、确定性）
③ python tools\dlc\check_translated.py --all  # -> ALL OK（缺字已归零）
④ python tools\dlc\build.py --stage all --out work\builds\JS_ZH_final.iso
```

- 重跑时若 `missing_chars.json` 里出现**已登记**的字：不重分配，只校验（幂等自检新增=0）；
- 若新字超过剩余 265 槽：工具会明确报「安全槽位耗尽」并终止（届时按 §8 R5 评估加高图集）。
- `charset_compiled_zh16.json` / `charset_expand_dlc.json` 必须是**同一版本**一起提交（前者决定编码，后者决定画哪些字）。

### 10.8 复现命令与产物 sha

```
python tools\font\expand_charset.py              # 规划+补画+回写+自证（约 0.3 s）
python tools\font\expand_charset.py --dry-run    # 只算不写
python tools\font\expand_charset.py --verify-only# 只校验现有 charset/expand json/容器
```

| 产物 | 大小 | sha256 |
|---|---:|---|
| `assets/charset/charset_compiled_zh16.json`（补画后） | 149,088 | `de54df1691dc929c88062185d1e48b72cb8e3c75d69854954f482129912c4afd` |
| `assets/charset/charset_expand_dlc.json` | 7,610 | `fb3782e696daafd198c2023c77c24694b30a98277c2a038cdf190d04cb387ab1` |
| `work/analysis/font/container_expanded_1024x644.bin` | 329,744 | `4a0340107e05c92b32965ed223f2a880f967c69d9b16c6c7c610930c8a898fd6` |
| `work/analysis/font/expand_report.json` | 51,197 | `4646b711571601155723214744a736849dd3d53b0fa0cbe429af6b6f5a42f20b` |


---

## 11. pair 字形的垂直度量问题与 A/B 数据（实机反馈；2026-10-22）

> 实机（PCSX2）中文已正常显示（档案/空插槽/返回/创建/按键说明等），**唯一视觉问题**：large 面中文 pair
> 字形**纵向拉伸、标题顶部被 UI 裁掉**；按钮行中文基线略低。default 面正文基本正常。
> 证据：`work\analysis\emu\all_test\alltest_native_130s.png`（汉化版） vs
> `work\analysis\emu\baseline\baseline_en_native_130s.png`（英文原版，同菜单）。

### 11.1 引擎侧度量公式（DLC SLUS_208.20 反汇编实测）

| 函数 | VA | 行为 |
|---|---|---|
| `CharWidth` | 0x21A360 | 固定宽标志=0 时：空格→`font+0x14`(style f2)；图标 0xB1/0xB5→20；否则 `advance(记录字节1) × font+0x1C(style f5)`；**pair 在 idx≥count 时兜底返回 16**（我们的 cave 0x180928 同款） |
| `CharHeight` | 0x21A440 | `int( float(def+0x0C) × font+0x20 )` = **`fld[1] × style.f6`**（`0x21A4B0` 取 def+0x0C；`0x21A4A0` 取 font+0x20） |
| `DrawString` | 0x2195F0 | 每字形 quad=`(x, y, x+CharWidth, y+CharHeight)`（0x2196CC/0x21982C/0x219894）；随后 `AddOneWord(font,&xy,&uv,..)` |
| `ComputeCharTextureCoords` | 0x21A210 | 单字节：按 FT 记录（`def+0x38`，10B/条）取 `(u0,v0,u1,v1)`；pair：cave 返回 `U0=16*col, V0=16*row+3, U1=U0+16, V1=V0+16` |

- `fld[1]`（=def+0x0C，字高基数）：large 26 / default 26 / **huge 16**（我们的合并版；EN 原版 huge=42）。
- `fld[4]×fld[5]=nrec`；`fld[12]=32`=base char；`fld[8]/fld[9]=512.0` 纹素归一化（绘制路径未见读取）。
- **ASCII 字形尺寸按 FT 记录矩形（0x21A210 的 u/v 值）走，pair 字形按 CharHeight 当 quad 高** —— 这是裁剪的根因（不是 face 数值错：
  large/default 的 fld 数值与本体 ZH 成品盘逐字节一致）。

### 11.2 实机量测（capture 1475×1106 ↔ 640×480；threshold>170）

| 对象 | 实测 ink 高（native） | 预期/解释 |
|---|---:|---|
| 英文原版标题 "Profiles"（ASCII large） | ≈21 | 记录矩形 26，CharHeight=26（fld[1]=26×f6=1） |
| 汉化按钮 "- 空插槽 -"（pair） | ≈22 | CharHeight=26、pair UV=16 ⇒ 纵向拉伸 26/16=1.63（13/16×26≈21） |
| 汉化标题 "档案"（pair） | ≈36 | 与该 style 的 CharHeight=**42**（26×1.64，style #5）吻合 ⇒ 顶部越出 26px 标题带被裁 |

### 11.3 数据侧方案 A（精确改法）与 ASCII 影响

| 方案 | 改动 | 效果 | ASCII 影响 |
|---|---|---|---|
| **A-1** | `large.fld[1] 26→16`、`default.fld[1] 26→16`（huge 已 16）；可选 `fld[13]` 同改 | CharHeight=16×f6：f6=1 ⇒ pair 16px 方形；f6=1.64 ⇒ 26（仍 1.63×）；f6=0.8 ⇒ 12.8 | ASCII 与 pair 共用 CharHeight ⇒ 我们 8×16 的 ASCII 带从"被拉高到 26"变成 1:1 的 16px；**英文大标题比当前/原版缩小约 40%** |
| **A-2** | A-1 + tail 前 8 条 style 换成本体 ZH 值（实测**仅 #5 不同**：f5/f6 1.64→1.0；其余 7 条逐字节相同；#8..#14 保留 DLC） | 标题 style CharHeight=16×1.0=**16px 完美方形**；其余常用 style f6∈{0.8,1} ⇒ 12.8~16 | 同 A-1（英文大字变小但不拉伸）；UI 垂直居中/行距可能有 1~4px 位移（fld[7] 行距未动） |
| **A-3** | 只改 tail #5 的 f5/f6 1.64→1.0（face 不动） | 若标题命中 #5：CharHeight 42→26（改善但仍有 1.63×） | 仅 style#5 用户（大字标题）受影响 |

> 结论：**数据侧改不彻底且会连带缩小英文 UI**。首选 **B（ELF cave）**：pair 分支把 quad 高度/采样高度固定 16，
> 垂直锚点三选一（顶对齐 `y+16` / 底对齐≈基线 `y+(CharHeight-16)` / 居中 `(CharHeight-16)/2`），ASCII 完全不动。

### 11.4 已构建 A/B 变体盘（text+ELF 取自当前 all_test，只差 FONT.RES）

| 变体 | 关键改动 | 文件 | sha256 前 16 |
|---|---|---|---|
| A1b | fld[1]=16（large/default；huge 原就 16） | `work\builds\ab_font\A1b_fld1_all16_only.iso` | `3b1aafa9f0259e18` |
| A2b | A-2：fld[1]=16 + style#5 f5/f6=1.0 | `work\builds\ab_font\A2b_fld1_all16_style5_1.iso` | `51cf9ab07c349e13` |
| A3 | 只 style#5 f5/f6=1.0（face 不动） | `work\builds\ab_font\A3_style5_only.iso` | `9fe71460892eeefc` |

- 复现：`python work\translation\mk_font_variants.py`（首版：A1/A2 连 fld[13] 一起改）与
  `python work\translation\fix_variants.py`（修正 style 偏移后的 A2b/A3）。
- 判定：emu 各抓 130s 同菜单 native 截图，比较 ①标题是否方形/不裁剪 ②按钮中文基线 ③英文 UI 缩放。
  若 A2b 标题方形但英文大字明显变小 ⇒ 走 B；若 A2b 视觉可接受且 B 来不及 ⇒ A-2 定版。


---

## 12. v3 渲染修复（A′ 度量规整）—— 实机 pair/ASCII 拉伸裁剪的定版修复（2026-10-22）

> 现象（v4 实机）：中文 normal 渲染成功，但 **large 面中文 pair 字形纵向拉伸/顶部被裁**（标题"档案"顶部被切），
> 按钮中文基线偏低；ASCII 同样被纵向拉伸（因我们已把全部 FT 记录重写成 16px 高）。
> 修复：纯数据改动（不改 ELF/图集），已实装于 `tools/font/fontlib.py::normalize_face_metrics()`，
> 由 `ft_merge_for_dlc()` 末尾调用，产物 v5 ISO 实机验证通过。

### 12.1 根因（反汇编 + 实机量测双向确认）

- 引擎 `DrawString` 对**每个字形**（ASCII 与 pair 相同）用 `quad 高 = CharHeight`，而
  `CharHeight = fld[1] × style.f6`（详见 §11.1）。
- 本工程把三个 face 的 FT 记录**全部重写成 16px 高**（ASCII 8×16 带、中文 16×16 pair），
  但合并 FONT.RES 的 face 头 `fld[1]` 仍是本体中文的 **large/default=26**，
  尾部 style 的高度缩放 `f6` 还有 **#5=1.64 / #7=1.63 / #12=1.2** ⇒ CharHeight 最高到 **42.6**。
- 后果：16px 字形被映射到 26~42px 的 quad ⇒ 纵向拉伸 1.63×~2.63×；标题带的 UI 裁剪区只有 ~26px ⇒ 顶部被切。
- 英文原版不受影响只是因为它的 FT 记录高（26/42）恰好等于 CharHeight；我们的 16px 记录不再等值。

### 12.2 改法（纯数据，幂等，结构解析定位、不写死偏移）

`normalize_face_metrics(blob)`：
1. 三个 face 的 **`fld[1]`（def+0x0C，CharHeight 基数）→ 16**（= 图集格高/记录高）；
2. 尾部**所有 style 的 `f5`/`f6` > 1.0 → 1.0**（命中 #5/#7/#12；`f5` 归 1 才能让 pair 的固定 CharWidth=16
   与 ASCII 的 `advance×f5` 口径一致）；
3. **不动**：`fld[2]/fld[3]`（=32，中英 UI 布局字段，绘制路径不读）、`fld[4]/fld[5]`、`fld[12]` base char=32、
   `nrec=224`、尾部长度 522/15 条、所有 `b4=0`、以及全部图集/记录字节。
实测改动 3×4 + 6×4 = **36 字节**；合并 FONT.RES real 仍 7,466 B，LZO 帧 **1,572→1,555 B**（≤原槽 4,460）。
幂等：`normalize(normalize(x)) == x`（实测 True）。

### 12.3 效果与 ASCII 影响

- normal 样式（f6=1）：CharHeight = 16×1.0 = 16 ⇒ ASCII/中文 pair 均 **1:1 16px**，不再拉伸、不再裁剪；
- 标题样式（#5 归一后 f6=1.0）：标题从 2.6× 拉伸变为 16px 方形；
- **代价**：英文大字从（原版）26px 变为 16px（我们的 16px ASCII 带本来就是中文盘口径）⇒ 英文大标题/大字变小约 40%，
  但字形不再模糊/拉伸；这是"16px 中文图集"方案下不可两全的取舍。

### 12.4 验证与产物

| 项 | 值 |
|---|---|
| 工具 | `tools/font/fontlib.py::normalize_face_metrics()`（`ft_merge_for_dlc()` 末尾调用，幂等） |
| 合并 FONT.RES real | 7,466 B，sha256 `4610c410fc36e57b…`（v5 盘内实测一致） |
| LZO 帧 | **1,555 B** ≤ 原槽 4,460 B |
| 新 COMMON.PAK | 830,300 B，sha256 `8215156a9d405338…` |
| **v5 ISO** | `work\builds\JS_ZH_v5.iso`，**1,229,264,896 B**，sha256 `ba9452bf4d71ba16…`，**verify 37/37 PASS** |
| 回归 | 幂等复跑：`normalize` 后字节不变；重建 blob 与 v5 盘内一致 |
| 数据侧 A/B 变体（仅留档，不进库） | `work\builds\ab_font\v2_*.iso`（A1b/A2b/A3/A′，见 §11.4） |

### 12.5 复核：A′ 后是否还有「记录 16px vs 度量」不一致（结论见 §8 R14）

| 项 | 现状 | 风险 | 建议 |
|---|---|---|---|
| `fld[13]`（def+0x24） | 26/26/42（未归 16） | 字体绘制路径无读取；仅当引擎别处用它做行距/基线才有影响 | 观察 v5 实机行距；异常时把它也归 16 |
| style `f6=0.8`（#6/#8/#10/#13） | CharHeight=12（int(16×0.8)） | 小样式纵向 0.8 压扁；与原盘「小样式=0.8×字高」比例一致，属历史行为 | 保留（小字层级）；异常再归 1.0 |
| style `f5<1`（0.8/0.6） | pair CharWidth 恒 16，ASCII advance=8×f5 | 中文/英文步进比 2.0→2.7~3.2×；小字混排略松、极窄 UI 可能溢出 | **不要**给 pair 乘 f5<1（16px 字形会重叠）；溢出则改短文案或该样式归 1.0 |
| `fld[2]/[3]=32`、`fld[4]/[5]`、base char、nrec | 与本体 ZH 成品盘一致、未被 A′ 改动 | 无（绘制路径不读 fld[2]/[3]） | 保持 |
| huge 128 条退化记录 / nrec=224 | A′ 未动 | 见 R10（钳位到记录 0，画空白） | 保持 |


### 12.6 v5 实机验收量测（2026-10-22 18:34，PCSX2 / 640×480 游戏坐标，阈值 RGB>140）

> 截图：`work\analysis\emu\v5\v5_native_130s.png`（v5） vs `work\analysis\emu\all_test\alltest_native_130s.png`（v4 修复前）
> vs `work\analysis\emu\baseline\baseline_en_native_130s.png`（英文原版）。量测脚本：
> `work\analysis\emu\measure_text.py`（等价口径；本表为 RGB>140 阈值，游戏像素）；回归可用 elf 的 `work\analysis\emu\v5_metrics.py`（一键输出 EN↔v5 的 Δh/Δy1 摘要）。

| 对象 | 英文原版 ink 高 | v4（A′ 前） | **v5（A′ 后）** | 结论 |
|---|---:|---:|---:|---|
| 标题「档案」（大字号） | 21.7（"Profiles"） | **39.9**（拉伸+顶部被切） | **14.8** | ✅ 回到 16px 字形口径（ink≈15/16），方形、不裁剪；标题 ink 顶部 y=19.3、距面板下缘余量 >9px |
| 按钮「- 空插槽 -」（正文） | 12.6（"EMPTY SLOT"） | **23.0**（1.63× 拉伸） | **13.5** | ✅ 16px 字形（ink≈13.5/16），与英文按钮同量级；基线 y1=208.6 vs 英文 205.6（+3px，pair 16px 单元在 26px 行内 top 对齐的残余，不裁剪，可接受） |
| 档案宽度（2 字） | — | 31.2 | 31.2 | 宽度未变（pair CharWidth=16/字），说明修复只影响纵向 |
| 底部「没有《幽灵行动》的存档数据。」 | — | — | 正常 16px、无裁剪 | ✅（截图目视 + bbox） |

- 目视（v5）：标题/按钮/底部正文均正常，标题不再被裁，英文 logo 为美术资源不受影响；
  英文大字号变小（26→16px）是 A′ 的已知取舍（§12.3），本屏英文仅 logo 美术，无可见回归。
- 残余观察（R14）：本轮 130s 截图只有存档菜单；小样式（f6=0.8→12px）与极窄 UI 的溢出风险需在
  HUD/列表类画面继续抽查（v5 145s~320s 同屏未提供新画面）。若最终验收要求"中文按钮基线与英文完全对齐"，
  可启用 elf-analyst 的 cave 底对齐 fallback（`0x219890` hook，standby，见 §8 R13）。

> ★ **独立复核（elf-analyst）**：`work\analysis\emu\v5_metrics.py` + `v5_text_metrics.csv` 复现同表
> （标题 14.8 / 按钮 13.5 / 基线 +3.1 game px，与我们 +3.0 的差 0.1 为阈值/框选细节）——两边口径一致；
> 复核结论：+3.1px 基线差来自「**记录高度变化**（原盘 26/42px 行盒 → 我们统一 16px 行盒）」，不是引擎拉伸、
> 也不是 A′ 未修净；v5 内部 ASCII/CN 同为 16px 行盒、内部一致。**目前建议不做**（若严格对齐：cave 只能改 y，
> 需先确认 16px cell 底部有 3px 余量；或下次重绘 pair 时把内容在 cell 内下移 1–2px）。详见 `docs/ANALYSIS_ELF.md §12.6.2`（含全文件 sha 校验与五项复核表）。

#### 12.6.1 小字样式 / HUD 抽查（2026-10-22 19:09，`work\analysis\emu\nav_menu\navmenu_native_225s.png`）

> 该 run 的 ISO = `work\builds\FINAL\GR_JS_ZH.iso`（sha `ba9452bf…` == v5，FINAL 包即 v5 副本），
> 画面 = 存档文件名键盘对话框 + 底部 HUD 提示行。量测口径同上（RGB>140、640×480）。

| 对象 | ink 高 | 样式/结论 |
|---|---:|---|
| 标题「档案」 | 14.9 | normal，✅ 不裁剪 |
| 对话框「文件名：」 | 15.5 | normal，✅ |
| 小字按钮「确认」 | **10.5** | 小样式（f6=0.8 ⇒ quad 12）⇒ 预期纵向略扁，**未见上下裁切**，✅ 可接受 |
| 底部 HUD 提示（「L1 R1 移动 / R2 大写锁定 / ⓐ 删除 / ⓑ 返回 / ⓧ 接受」） | 13.0 | normal，中英混排步进正常、**无溢出/换行错位**，✅ |
| 槽位「- 空插槽 -」 | 13.0 | normal，✅ |

- ★ **elf-analyst 独立复核（五项全部一致）**：标题 14.9 / 文件名 15.5 / 小字确认 10.5 / HUD 提示 13.0 / 空插槽 13.0；并**全文件 sha256 校验** `work\builds\FINAL\GR_JS_ZH.iso = ba9452bf4d71ba16a9a60ac72ef94c9db9f9b08967213f790417c927570e9185` == v5 盘（同源）。见 `docs/ANALYSIS_ELF.md §12.6.2` / `work/analysis/elf/v3_render_fix.json → status.v5_small_style`。
- 结论：**R14 的小字压扁属预期语义（原盘小样式即 0.8×字高），非回归；未见"被裁一半"或溢出**。
- 覆盖范围：该 run 只有菜单/对话框类画面，**游戏内 HUD/任务列表尚未覆盖**；若最终验收要求，可补一次进游戏的 smoke
  （重点：小字样式 + 极窄 UI），其余风险按 §8 R14 保持"观察"。

## 13. 补记：A″ —— 为什么 style 缩放也要全归 1.0（v6）

A′ 只把 >1 的 style 高度/宽度缩放归 1.0，但 **0.8/0.6 的小样式仍会让中英混排上下错位**：
实测引擎 ASCII 字形的 quad 尺寸走 FT 记录（恒 16px），而中文 pair 的 quad 高 = CharHeight
= ld[1] × style.f6、宽恒 16（不乘 f5）。只要 f6≠1，同一行里中文字号 ≠ 英文字号、且
中文以 quad 顶为锚点缩放（看起来更小且偏上）⇒ 「明显的上下偏移」。

**A″**：
ormalize_face_metrics() 把 15 条 style 的 f5/f6 **全部置 1.0**。效果：全部文本
16px、中英基线对齐（v6 实机 2008年3月15日 | 13:00 | 晴天 行已对齐）；代价是原版的大/小
字号层级被拉平。回归断言：erify.py C14（fld[1]=16 且所有 f5/f6=1.0）。

## 14. A‴ 行盒锚点（v9，2026-10-22）—— UI 垂直对齐定版

**问题**（用户实机反馈）：A′/A″ 把 `fld[1]` 归 16 后，`CharHeight = fld[1]×style.f6` 同时是
「字形 quad 高」与**19 个 UI 布局调用者**的行盒高 ⇒ 按钮/标题/帮助条的行盒口径与 EN 原盘不同，
整屏文字上下错位（标题偏上 ~6.5px、按钮族 ~±3px、帮助条偏低 ~3px）。

**A‴（v9，纯数据 12B + 纯 ELF 4 处补丁）**：
1. `fontlib.restore_face_metrics()`：三个 face 的 `fld[1]` 恢复 EN 原值（large 26 / default 26 /
   huge 42）⇒ **布局行盒 = EN 口径**；15 条 style 的 f5/f6 保持 1.0（横向宽度与 v7 完全一致，
   CharHeight = 26/26/42，不再随 f6 变化）。
2. ELF `0x219894 0xE6970000 → 0x0815D741 (j 0x575D04)`；`0x219898 0xE6C00000 → nop`。
3. 死区 cave @VA 0x575D04（A 段 116 B）+ 0x5752F0（B 段 32 B，二者均为函数对齐零填充区，
   无 j/jal 目标、无字面量/lui+addiu 引用）：
   * 基础：`y1 = y + (CharHeight−16)/2`、`y2 = y1 + 16` ⇒ 16px 字形在 CharHeight 行盒内**垂直居中**；
     居中族净位移 0（与 v7 同位）、底对齐族 −5px（上移）、常量/顶对齐族 +5px（下移）。
   * 标题带：`y < 40` 再 `+7px`（对应本体 ZH61「子界面标题 +7」口径；实测标题 ink 中心 38.0
     vs EN 38.6）。
   * 底栏：`y ≥ 400` 且文本左缘 `x < 400`（滚动帮助条）再 `−3px`，右侧按键提示不动。
4. 图标路径（0x219850–0x21988C）保持原样：恢复 CharHeight=26 后图标 20px 居中和 EN 一致。

**实测结果**（PCSX2 2.8.2 DX12，同导航 EN/v7/v9 对照，640×480 游戏像素）：
| 组件 | EN ink | v7 | **v9** |
|---|---|---|---|
| 主菜单大标题 | 24.75–52.52（中心 38.6） | 18.24–34.30（−8.5） | **29.96–46.01（中心 38.0）** ✓ |
| 主菜单列表项 | 137.73–151.18 | 138.60–154.22 | 138.60–154.22（±1） |
| 底部帮助条 | 424.32–436.90 | 无（被裁/滚动中） | **421.49–437.11（中心 429.3）** ✓ |
| 右侧按键提示 | 424.69–438.58 | 424.69–439.44 | 421.65–435.97（−3） |
| 游戏内教学弹窗/任务信息 | — | 0–1.3 | 0–1.3 ✓ |

* 证据：`work/analysis/emu/{v8final,v9d}`、`work/analysis/elf/align_plan.md`、
  `work/analysis/emu/align_measure.md`、`work/analysis/ref/offsets_base.md`。
* 回归：`verify.py --stage all` **38/38**（新增 A‴ cave/锚点由 E3 全补丁在盘断言覆盖）。
* 身份：ELF sha256 `fbe3ef7127563997…`、Game CRC **`E601C271`**、v9 ISO sha256 `47789a0b…`。

### 14.1 v10 补记：中段 −4px

A‴ cave 追加 C 段（VA 0x182F84，60 B）：**40 ≤ y < 400 的中段正文再上移 4px**。
实测 Player Mode 列表项 ink 底由 +4.3px 变为 **0.0**（分屏/选项/影片三行与 EN 完全一致），
主菜单 4 项 154.26→149.92（EN 150.35）、任务信息正文 132.54→128.20（EN 127.34）。
cave 布局：A(0x575D04，标题+底栏) → C(0x182F84，中段) → B(0x5752F0，写 y1/y2)。
新 CRC `D09038B4`，v10 ISO sha256 `8eb0604dfee5c67a…`。

### 14.2 v11 补记：中段改 −2px

用户实机判定 v10 的 −4px 过头（列表项略高）⇒ cave C 常量 4.0f→2.0f（取 v9/v10 中间值）。
Player Mode 列表 ink 底：v9 +4.3 / v10 0 / **v11 +2.2**（EN 基准），偏上问题消除。
新 CRC `D0903834`、v11 ISO sha256 `cbb4f9c853fd4d…`。

## 15. 图标哨兵槽保护（放置符 → 手柄按键图标）

本作部分文字栏位是**占位符**：引擎在绘制时把单字节码 **0xB1（△）/0xB5（✕）** 替换成手柄按键图标
（`DrawString` 里 8 处图标常量，DBCS 补丁已把它们零扩展为 `0x00B1/0x00B5`）。
与之配套，图集里 **trail ∈ {0xB1,0xB5} 的 50 个对偶格是「图标哨兵槽」**，引擎有硬编码特判，
**禁止分配给汉字**（见 §2.6 / R11）。

保护措施（`tools/font/atlas_guard.py`，构筑与校验都会跑）：

| 项 | 检查 | 实测 |
|---|---|---|
| I1 | 字符集 `pair_of` 无 trail∈{B1,B5} 的对偶码 | 0 占用 ✓ |
| I2 | 成品图集 50 个哨兵格像素与 seed 逐 texel 相等 | 全等 ✓（slot 768/772 的图标像素受保护） |
| I3 | 文本内单字节 0xB1/0xB5 数量与原盘逐条一致 | EN 0 条 / 成品 0 条 ✓ |

图集纹理表格图与图标格放大图：`docs/img/atlas_table_zh.png`、`docs/img/atlas_table_en.png`、
`docs/img/atlas_icon_cells_zoom.png`（生成：`tools/font/dump_atlas_table.py`）。

> 注：图标像素所在的 2 个哨兵格（slot 768 = (0xA9,0xB1)、slot 772 = (0xA9,0xB5)）在 seed 里
> 带的是**残留字形碎片**；引擎图标是硬编码绘制，不采样这两格，但按 R11 必须保持原样不动。
