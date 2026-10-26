# MOD_GUIDE —— 汉化修改指南（做法与陷阱）

> 面向"要再改一处内容"的你。这里写的是**这个游戏这个盘**特有的做法与坑，
> 不是通用汉化教程。想重建整盘看 `docs/BUILD_GUIDE.md`。
> 每一条后面都标了证据文档，别凭记忆改。

---

## 0. 心智模型：一层一层剥

```
ISO9660 (2048 B/扇区)
 └─ SLUS_206.13 (LBA 295, 37,453,732 B)        ← 主程序，补丁打在这里
 └─ GR.IMG   (LBA 19175)                       ← 3500+ 个游戏资源
 └─ MENU.IMG (LBA 776286)                      ← 260+ 个菜单资源
      └─ 条目表 @ +0x830，每条 12×u32 (48 B)
           [0..5] 杂项  [6]=stored  [7]=real  [8]=条目内偏移  [9..11] 杂项
           iso_off = lba*2048 + off
           名字表 @ +0x10 起，'\\0' 分隔，顺序 == 表项顺序
      └─ 条目载荷 = 若干 LZO1X 子流 {u32 clen}{u32 rlen}{payload} 顺序拼接
           real = Σ rlen；stored = 实际占用（≥ 子流总长，允许尾部空隙）
```

**要点**：引擎看到的是**子流解压后**的 payload，不是 ISO 上的字节。
所有"文本/字库/XML"的改动都在 payload 层做，做完重新 LZO 压回去，
并保证新 `stored` 不越过**下一条目的 off**（`slack`）。

工具口径：`tools/text_csv/tcslib.py`（`Iso` / `lzo_subs` / `lzo_pack` / `parse_lang` / `parse_sfxml`）、
`tools/lib/zx_lib.py`（`entries` / `header` / 图集）。

---

## 1. 文本表 / CSV 流程

### 1.1 三种文本资源

| 种类 | 位置 | 结构 | 解析 |
|---|---|---|---|
| **LANG** | `EN_STRINGS.RES`：`MENU.IMG#25` + `GR.IMG#902`（两份，内容必须一致） | `{u32 ngroups}` 后每组 `{u32 count}` + `count × ({u32 len}{data}{u16 attr})`，组间 1 个 u32 分隔 | `tcslib.parse_lang` |
| **SFXML** | `EN_SPECIAL_FEATURE.XML`：`MENU.IMG#283`（+ GR 侧副本） | 纯 XML，正文在 `<text>…</text>` | `tcslib.parse_sfxml` |
| **MIS / ATR** | `*.MIS` / `*.ATR` | **看着是二进制，其实是 XML**（任务/人物定义） | `lzo_subs` 拼起来直接当 XML |

### 1.2 导出 → 改 → 注入

```powershell
# 导出（只读原盘，产出 CSV + 同名 .txt 快照便于 diff）
python tools\text_csv\dump_text_csv.py --iso <盘> --out work\text\ 

# 注入（把 CSV 写回一张新盘）
python tools\text_csv\inject_text_csv.py --csv work\text\ --src <基盘> --dst <新盘> --report r.json
```

CSV 分四类文件（`*_text_long.csv` / `short` / `sf_titles` / `nowrap`），`inject_text_csv.py --csv`
既可以给**目录**（自动收集该目录下全部 `*_text_*.csv`，见 `tcslib.expand_csv_inputs`），
也可以给单个文件。

### 1.3 坑

* **两份 LANG 都要写**（`MENU#25` 与 `GR#902`）。只写一份 ⇒ 菜单里改了、游戏里没改。
  `inject_text_csv.py` 已经两份一起写，但如果你手搓脚本，记得。
* **`len` 是字节数**，不是字符数。中文对偶码 2 B/字，ASCII 1 B/字。
* **不要超出条目 real 的余量**：payload 变长会推动后面所有条目，属于"重排"，本项目
  **从不**做重排（见 §7 的 slack 断言）。
* **换行符**：文本里是真实的 `\r\n`，写 CSV 时要转义（`\r` `\n` 两个字面字符），
  不要真的写进 CSV 字段。

---

## 2. DBCS 编码（2300 对偶 + 103 单字节）

### 2.1 编码表长什么样

`tools/final_fix/assets/charset/charset_compiled_zh16.json`：

```
codes    : 103 条   单字节 char -> byte            （ASCII + 少量符号，走 ASCII 兼容段）
pair_of  : 2300 条  字符 -> (b1, b2)               （汉字/标点，双字节）
```

对偶码空间：lead ∈ `0xA1..0xBA`（26 个），trail ∈ `0xA1..0xFE`（94 个），
`slot = (lead-0xA1)*94 + (trail-0xA1)`，`0 ≤ slot < 2300`。
引擎只认 `0xA1..0xBA` 开头的 lead —— **写出别的 lead 就是乱码/不显示**（`PAIR_LEAD_LO/HI`）。

### 2.2 ★ `0xFF` = EOF 的坑（最贵的一次教训）

字符集把 `U+8457 著` 映射成**单字节 `0xFF`**。而 PS2 的 XML 词法器

```
RSXMLLexan::GetCharData @0x00544450
  0x00544588  lb   $v1,0($a0)        ← 有符号字节加载
  0x0054458C  addiu $v0,$zero,-1
  0x00544590  bne  $v1,$v0,<正常字符>
```

用**有符号**比较 -1 判 EOF ⇒ 文本里一出现 `0xFF`，后面的字符全被吞掉，
`SFStudio::ParseItem` 还会**覆盖**（不是追加）节点内容 ⇒ 13 条专家档案只剩后半截
（"显著特征" 变成 "特征：无"）。

**结论 / 规矩**：

* 任何**会被 XML 词法器读到**的文本里**禁止**出现 `0xFF`；
* 需要写「著」就换词（`显著`→`明显`，`卓著`→`卓越`），或者给它一个**对偶码**；
* `verify.py --ff-gate` 是**硬闸门**，构建第 7 步就会拦下来；
* 附带一条：`EN_STRINGS.RES` 里每条记录开头的 `0xFF000000` 是 **u32 长度 255**，是结构字节，
  不是文本 —— 闸门会跳过长度字段，别把它当成命中。

证据：`docs/REPORT_PROFILE_SCROLL.md`、`docs/REPORT_FF_SWEEP.md`。

### 2.3 加新字

1. 在 `charset_expand_zhNNN.json` 里登记：`{char, pair(目标槽), 来源}`；
2. 用 `patch_zh139/140/141_chars.py` 那套（渲染 → 写图集格子 → 改 `pair_of` 键）；
3. **必须挑零引用的空 PUA 槽**（`slot_cell` + 引用计数扫描），否则会把已有字覆盖掉；
4. 改完把新的 charset 快照也提交（`.before_zhNNN` 命名），这样链条可回溯。

---

## 3. 字库与图集

### 3.1 布局

| 项 | 值 |
|---|---|
| 容器 | `FONT.RES`：`MENU.IMG#4` + `GR.IMG#906`（两份必须逐字节相同） |
| 图集 | **1024 × 644**，`psm = 0x14`（**PSMT4 / 4bpp**，每 texel 4 bit，每字节 2 texel） |
| 网格 | **64 列** × 行，单元格 **16 × 16** px |
| 段 | 图集容器按「段」组织：`(首行, 数据偏移, 字节数)`，尾部的 no-op 段会被过滤 |
| FT 记录 | 每个字有 face（large / default / huge …）的采样矩形 `(u0,v0,u1,v1)` |

一个字节装两个 texel ⇒ **左右邻居共享一个字节**，这是下面两个坑的物理来源。

### 3.2 ★ 右缘采样坑（"乱码"的真身）

引擎采样矩形 `u1 == 1024`（贴图宽度）时，**取不到那一列像素**：

| 字 | 码位 | 采样矩形 | 右缘 |
|---|---|---|---|
| `约` | 对偶 `A7EC` → slot 639 = row9 col**63** | (1008,147)-(1024,163) | **1024** |
| `金` | 对偶 `A8CE` → slot 703 = row10 col**63** | (1008,163)-(1024,179) | **1024** |
| `X` | ASCII `0x58`，三 face 记录同值 | (1016,208,1024,224) | **1024** |

用户报的"乱码"是 `X` / `约` / `金` —— 三个都是 col 63（最后一列）或 FT 矩形右缘压在 1024。
**位图本身没错**（逐 texel 与 TTF 渲染比对 xor=0）。

修法（`patch_zh130_glyph_edge.py`）：把这些字**换到别的槽**（36 对偶换位）+ 改 `X` 的三条
FT 记录矩形，并把换位结果写回 charset（`pair_of` 的键互换，`codes` 一个不动）。

**规矩**：新画字**不要落在最后一列**；写 FT 矩形时 `u1 ≤ 1023`。

证据：`docs/REPORT_GLYPH_FIX.md`、`docs/REPORT_glyph_align.md`。

### 3.3 ★ 4bpp 半字节坑

改一个 texel 时，`byte = atlas[(y*1024 + x)//2]`，`x` 偶数取低 4 bit、奇数取高 4 bit。
**不要整字节赋值**，否则会把邻居一起改掉（历史事故：整列出现"锯齿"）。

### 3.4 容量

2300 个对偶槽里目前 **1954 个有字形**，剩余空 PUA 槽约 300 —— 加新字够用，
但每个都要挑**零引用**的槽（见 `patch_zh139_chars.py` 的 slot 选择逻辑）。

---

## 4. 折行宽度

特别收录（`SPECIAL_FEATURES_GR_PS2`）的正文折行宽度**不是代码里的常量，是 IKE 布局数据**：

```
MENU.IMG#282 NTSC_IKE.RES → 解压 blob
  0x27AB8  TEXT\0 …              ← 组件记录
  0x27AB8+8   x, y, w, h = (35, 173, 286, 190)
  0x27AC8     w (u32)            ← ★ 折行宽度就是这里
  0x27A95     面板图片 pda-lcd-02.rsb 的目标宽 (float)
```

引擎算 `wrapW = comp[0x40] - comp[0xB4]`（后者为 0），所以**改数据就能改折行，ELF 一个字节都不用动**。
`GR_ZH142` 把它 270 → 286 并把面板 290 → 306；`GR_ZH143` 再 286 → 294（面板不动）。

改动只影响**一个子流**（`stored` 会 +/- 几十字节），`slack` 有 79 万字节余量，
**不会推动任何偏移**。断言：`stored` 变化后 `next.off - (off + stored) ≥ 0`。

坑：改宽了但面板没跟上 ⇒ 文字压到边框上；改窄了 ⇒ 折行位置变了但标题居中会偏。
两者的验收都在**画面上**，离线只能验证记录值（`verify.py` 断言 == 294）。

证据：`docs/REPORT_ZH143_WRAP8.md`、`docs/REPORT_WRAP_AND_TITLE.md`。

---

## 5. 任务名（`*.MIS` 的 `<Name>`）

### 5.1 结构

`M15_RED_SQUARE.MIS` 在 `GR.IMG#675` 与 `MENU.IMG#184` 各一份。条目 = **5 个 LZO 子流**，
名字在 **sub0**，解压后是一段纯文本 XML：

```xml
<Name>M15 - White Razor</Name>
```

**不是** NUL 结尾、**没有**长度前缀、**不是**定长（同盘 40 个名字 11..21 B 不等），
由 `</Name>` 定界。

### 5.2 为什么不能"就地替换"

`White Razor` 这 11 字节里有些字符被**后面的 LZO 匹配当成了复制源**
（`"te "` @out CF、`" R"` @out 274，级联约 25 处）。一旦改写这些字节，
那些匹配复制出来的内容就错了 ⇒ 必须**重新编码这些匹配令牌**。

### 5.3 正确做法：令牌级重编码 + 长度联动

```
1. 解压 sub0，定位 <Name>…</Name>，算出目标字节（如 白刃 = A7E6 A9EA，4 B）
2. 用插桩解码器（lz77_decode 的 Trace 版）建"输出偏移 → 产生它的令牌"的映射
3. 找出源区间与名字区间相交的匹配令牌，DP 求局部最优重编码
   （必要时把相邻问题区合并，用 M2→M3 升级把长度补齐）
4. 名字变短 ⇒ sub0 的 rlen 跟着变（16384 → 16377），条目的 real 与 stored 各 -7
5. 重压 sub0，拼回 5 子流，回读自证：解压结果必须**逐字节等于**
   "原解压流只把名字换掉"的期望
```

v1/v2 的弯路：把名字**写死成 11 字节**（用空格补）⇒ 标题被顶偏，因为标题是按名字宽度居中的。
v3 才承认"长度本来就可变"。**教训**：先证伪"格式要求定长"，再动手。

### 5.4 多个任务名一起改（现行做法）

`patch_misnames40.py` 用 `assets/mis/map.tsv` 驱动，一次改 **40 个任务 / 80 个条目**
（`GR.IMG` 与 `MENU.IMG` 各一份）。每个条目独立走 §5.3，每个都回读自证。

与早期 29 个版本的两个差别：

* **零填充**（不再用空格凑长度）—— 标题居中才对；
* **可变长度**：sub0 的 `rlen` 16384 → 16371..16382，条目 `real` 同步减少；
  载荷 `clen` 精确补回原值 ⇒ `sub1..N` 的偏移和条目 `stored` **全不变**。

`DP01–DP05` 的 `<MapName>` 与 `<Name>` 同值，两处一起改。

> 历史：`patch_zh145_misnames.py`（29 个，等长+空格）与 `patch_zh144_m15_title.py`（M15 v3）
> 已被这一版取代，但脚本仍留在目录里，可用来复现 `GR_ZH144` / `GR_ZH145` 两张中间盘。

证据：`docs/REPORT_MISSION_NAME.md`、`docs/REPORT_MIS_NAMES.md`。

---

## 6. ELF 补丁

### 6.1 什么时候要动 ELF

只有**逻辑**问题才动 ELF：卡死（分配器桶链）、NULL 写、EOF 判定。
**能用数据解决的绝不碰代码** —— 因为 Game CRC 变了，玩家旧存档全废。

### 6.2 四件套（当前 ELF 里只有这 4 处）

| 名 | 站点 VA | 原字 → 新字 | cave | 作用 |
|---|---|---|---|---|
| F4 | `0x00102588` | `0x1459FFD1` → `0x081068D7` | `0x0041A35C`（36 B） | malloc 大块桶：链头不在 RAM 内就 bail |
| OOMFIX | `0x00539174` | `0xAE620004` → `0x08154012` | `0x00550048`（44 B） | 解压器 malloc 返回 NULL 时不再写 NULL+4 |
| F7 | `0x001021D4` | `0x1447FFEA` → `0x08177B31` | `0x005DECC4`（36 B） | own-bin 回边：链头非法就 bail |
| F7b | `0x00102208` | `0xDC430008` → `0x0815C2EC` | `0x00570BB0`（40 B） | unsorted 桶快路径：链头越界就 bail |

合计 **239 字节 / 70 段**，全部在声明窗口内，窗口外 0 字节。
逐字节真源 = `tools/final_fix/elf_patches.json`，执行体 = `apply_fix.py`。

### 6.3 地址换算

```
elf_off = VA - 0x6C780 - 295*2048
iso_off = VA - 0x6C780
```

### 6.4 选 cave 的 7 条检查（`cave_verify_f7b.py` 的 C1–C7 口径）

1. 目标区间在 ELF 里**全零**
2. 多份运行期快照里**逐字节未变**（没人写它）
3. 不含**指针字**（避免被当数据引用）
4. 不是 `lui+addiu` 构造出的地址
5. 不是任何**跳转目标**
6. 不覆盖任何**符号**
7. 邻居净空（前后各留一段）

**只做"跳到 cave 再跳回"的最小改动**，不要在 cave 里造复杂逻辑。

证据：`docs/REPORT_COMBFIX.md`、`docs/REPORT_F7B.md`、`docs/REPORT_DISASM_ROOTCAUSE.md`。

---

## 7. 验证判据（什么才算"改对了"）

| 层 | 判据 | 工具 |
|---|---|---|
| 字节 | 阶段 sha256 == `fix_spec.json` 声明值 | `build.py` |
| 条目 | 解压后逐字节 == 期望（"只改了该改的"） | 各 patch 脚本内置 |
| 偏移 | 后续条目 `off` **一个都不动**；`slack ≥ 0` | 各 patch 脚本内置 |
| 文本 | 文本区 0 个 `0xFF` | `verify.py --ff-gate` |
| 编码 | 无旧码残留（哨兵码 738 / 换位码 2） | `tcslib.scan_legacy_residue` |
| 字库 | 2300 对偶 / 103 单字节 / 目标字可编码 | `verify.py` |
| 身份 | 尺寸 / sha256 / md5 / **Game CRC 653FBF69** | `verify.py` |
| 内容 | 中文任务名 29 / 英文 11 / M15 = `M15 - 白刃` | `verify.py` |

**"改对了"的最低标准**：`build.py` 全链 18 步指纹全对 + `verify.py` 28 条全过。
画面层面的验收（居中、折行、乱码）必须真机/模拟器看一次，离线判据替代不了。

---

## 8. 陷阱速查

| 坑 | 症状 | 规矩 |
|---|---|---|
| `0xFF` 进文本 | XML 节点被截断 | 见 §2.2 |
| 只写一份 LANG | 菜单与游戏文本不一致 | 两份都写 |
| 改 4bpp 整字节 | 邻居 texel 被改 | 只改半个字节 |
| 字画在 col 63 | 右缘取不到 ⇒ "乱码" | 避开最后一列 |
| FT 矩形 `u1=1024` | 同上 | `u1 ≤ 1023` |
| 名字长度写死 | 标题居中偏 | 长度可变，联动 rlen/real/stored |
| 原地改 LZO 字面量 | 复制源错 ⇒ 花屏/错字 | 令牌级重编码 |
| 拿历史成品当基底 | 不可复现 | 只从英文原盘 |
| `Get-Content -Raw \| Set-Content -Encoding utf8` | 加 BOM，Python 读 JSON 炸 | 用 Python 读写 UTF-8 |
| `.ps1` 里写中文 | PS 5.1 按 ANSI 解释 ⇒ 乱码 | 脚本一律 `.py` |
| 改完忘了更新期望指纹 | `build.py` 报指纹不符 | 见 `BUILD_GUIDE.md` §8 |
