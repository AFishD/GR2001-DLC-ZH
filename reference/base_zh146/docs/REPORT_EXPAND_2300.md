# REPORT_EXPAND_2300 — 路线 A：在 2,300 可登记 / 2,264 可寻址天花板内做字库扩容（成品 `GR_ZH139`）

> 轮次：`round-expand2300` · 分支 **`feat/expand2300`**（从 `fix/font` 切出；**未 push / 未 force**）
> 成品：**`work\builds\GR_RELEASE\GR_ZH139.iso`**（+ `GR_ZH139.meta.json`）
> 基底：`work\builds\GR_RELEASE\GR_ZH138.iso`（`7396f55c…a2f2`）
> 写入范围：`work\builds\GR_EXPAND\**`、`work\builds\GR_RELEASE\GR_ZH139*`、`tools\font_pipeline\data\*`、
> `tools\final_fix\*`、`tools\text_csv\gate_pairs.json`、`docs\REPORT_EXPAND_2300.md`、`docs\STATUS.md`
> **未动**：`third_party\**`、用户 PCSX2 目录、`work\builds\GR_TAILWIDEN\**`、既有成品盘、ELF（**0 字节**）

---

## 0. 一句话结论

**天花板内确实还有 323 个可登记的对偶槽，但"该填哪个字"的证据只剩 13 个。**
本轮把 **13 个有证据的缺字**画进 13 个**零引用 PUA 占位槽**（码位/槽位不变，只换 `pair_of` 的键名），
图集只多 969 个墨点、**只变 13 格**，**文本 0 字节改动**、**ELF 0 字节改动** ⇒ Game CRC 仍 `653FBF69`；
其余 **310 槽保留为 PUA 占位**（无需求证据，工具已就绪，一条命令可补）。

| 项 | `GR_ZH138`（基底） | **`GR_ZH139`（本盘）** |
|---|---|---|
| 尺寸 | 1,648,164,864 B | **1,648,164,864 B**（同） |
| sha256 | `7396f55c…541a2f2` | **`33b9acd9341f6e8f382e87545c4f75a0399eb4ba12f3bb02d4b58d3acb06bae5`** |
| md5 | `4a7a5150bc467480f970c547e20742fe` | **`38a764f4be875e4c3d13178308415004`** |
| ELF sha256 / Game CRC | `a0c8499c…` / `653FBF69` | **`a0c8499c…` / `653FBF69`**（逐字节相同） |
| 图集 | 1024×644 PSMT4 / 11 段 / px_size 329,744 | **完全相同**（几何 0 改动） |
| 有字形 / 登记 | 1,941 / 2,300 | **1,954 / 2,300** |
| PUA 占位 | 359（36 个 col-63） | **346**（36 个 col-63） |
| 墨量（NIB==0） | 146,070 | **147,039**（+969） |
| 逐 texel 与 TTF `xor==0` | 1,935 | **1,948**（+13） |
| 全盘差异 | — | **768 B / 252 个连续 run**，100% 落在图集像素容器内（bbox `0x5ECC8406..0x5ECCBF59`，跨度 15,187 B） |

---

## A. 缺口分析（**先看这一节**）

> 生成器：`work\builds\GR_EXPAND\tools\a1_state.py`（2,350 槽普查）· `a2_gap.py`（三路语料缺口）·
> `a3_plan.py`（逐槽映射 + 零引用对账）
> 明细：`work\builds\GR_EXPAND\out\gap_plan.md` / `gap_plan.csv`（323 行逐槽）/ `a1_state.json` /
> `a2_gap.json` / `a3_plan.json`

### A.1 现役盘（`GR_ZH138`）的字库账本（实测，不是引用文档）

| 项 | 实测 |
|---|---|
| 图集 | 1024×644 / psm 0x14 / `px_size` 329,744 = 329,728+16 / **11** 个数据段 / payload 329,200 |
| 三闸门 | `w=1024<1025` ✓ · `px_size == w*h/2+16` ✓ · `(w*h/2)=329,728 % 2048 == 0` ✓ |
| gate | **0xBA**（ELF 4 处站点一致） |
| 对偶容量 / 已登记 | 2,350 / **2,300**（`pair_of`） |
| 单字节码 | 103（`codes`） |
| 有字形 / 无字形 | **1,941 / 359**（无字形的 359 个**全部**是 PUA 占位） |
| 真汉字缺字形 | **0** |
| col-63 槽 | 36（全部 PUA、零墨、**引擎采样矩形右缘 == 贴图宽 1024 ⇒ 永久不可用**） |
| 可替换 PUA 槽 | **323** = 359 − 36，逐槽实测：零墨 323/323、`usable` 323/323、FT 矩形交叠 0 px ×323 |
| **对偶码被文本引用** | 323 个候选里 **0 个**被引用（见 A.4 的逐槽 `refs` 列） |

### A.2 ★ 建议新增的字：**13 个**（按证据强度分档）

| # | 字 | 档 | 证据（可回查） | 语料命中 | 目标槽 | 新码 | 墨量 |
|---|---|---|---|---|---|---|---|
| 1 | **兄** | A | `REPORT_text_reduce.md` #14「字库无 弟/兄/姐」（T0054/T0061） | 草稿 1 | 1981 | `B6A8` | 55 |
| 2 | **凉** | A | 同上 #13「字库无 凉/季」（T0065 季节） | — | 1988 | `B6AF` | 61 |
| 3 | **啪** | A | `REPORT_r71_scene_reduce.md` #6「字库无 啪」（T0069 枪声） | — | 2013 | `B6C8` | 85 |
| 4 | **姐** | A | `REPORT_text_reduce.md` #14「字库无 弟/兄/姐」 | — | 2014 | `B6C9` | 76 |
| 5 | **孩** | A | 同上 #7「字库无 女/闺/孩/妹」（T0069） | — | 2015 | `B6CA` | 67 |
| 6 | **爹** | A | 同上 #1「字库无 父/爸/爹」（13 条传记） | — | 2016 | `B6CB` | 65 |
| 7 | **闺** | A | 同上 #7「字库无 女/闺/孩/妹」 | — | 2017 | `B6CC` | 77 |
| 8 | **勃** | B | 译者"丰富版"草稿原文片段（`reduce_rules.py`） | 草稿 1 | 2018 | `B6CD` | 73 |
| 9 | **揽** | B | 同上 | 草稿 1 | 2019 | `B6CE` | 80 |
| 10 | **暖** | B | 同上 | 草稿 1 | 2020 | `B6CF` | 87 |
| 11 | **租** | B | 同上 | 草稿 1 | 2021 | `B6D0` | 82 |
| 12 | **讶** | B | 同上 | 草稿 1 | 2022 | `B6D1` | 57 |
| 13 | **醒** | B | 同上 | 草稿 1 | 2023 | `B6D2` | 104 |

- **档 A（7 个）**：`docs` 的替换表里**明写"字库无 X"** —— 当初正是因为没字形，译文才被改写
  （"女儿→千金"、"父亲→家长"、"妹妹→家中最小的"…）。这 7 个字就是那些改写还欠的账。
- **档 B（6 个）**：项目自己的「丰富版」草稿（`tools\rounds\zh98\temp\r64\reduce_rules.py` 的
  **原文片段**）里出现、至今没进字库的字。那份草稿正是 round64「693 种缺字」的统计来源。
- **档 C（0 个）**：官方 PC 中文对照表 `tools\hanliu\texts\pc_official_zh.csv`
  （2,902 行 / **1,248 个不同汉字**）**全部已在字库** ⇒ 没有新增。
- **可渲染性**：13 个全部过 `方正像素16.ttf` 同一配方（`ok`）；`ttf_missing`/`overflow`/`zombie` = **0**。

### A.3 为什么不是 323 个（语料代表性已经过反向验证）

| 语料 | 规模 | 该语料里"字库没有的汉字" |
|---|---|---|
| 官方 PC 中文对照表（`pc_official_zh.csv`） | 2,902 行 / 1,248 个不同汉字 | **0 个** |
| 译者丰富版草稿（`reduce_rules.py` 原文片段） | 1,486 条规则 / 1,304 个不同汉字 | **6 个**（勃 揽 暖 租 讶 醒） |
| `docs` 的"字库无 X"替换表 | 45 条具名条目 | **7 个**（兄 凉 啪 姐 孩 爹 闺） |
| 盘上现役文本（`GR_ZH138` 的 3 张文本表） | 2,301 条 / 66,997 单元 | **0 个真汉字**（唯一 1 个未映射**字节**单元见 A.5） |

**反向验证**：round67 当年加进字库的 329 个字，**329/329 全部**出现在我这份草稿语料里
（`a2_gap.py` 实测）⇒ 语料不是"抽样太窄"，而是**已经把当年那 693 个缺字池覆盖住了**；
今天的缺口只剩 13 个，是因为后续 2,400 线扩容已经把那批字吃掉。

⇒ 其余 **310 个 PUA 槽没有任何"哪个字需要它"的证据**。把槽填成随便哪个字：
① 不改善任何现有画面（现役文本零引用）；② 将来真需要那个槽时，仍要再做一次换位；
③ 却会让"空白可用槽"这个体检指标从 310 变 0，掩盖真实余量。
**所以本轮不填无证据的字**，槽位保持 PUA，工具随时可补（`--plan` 一条命令、幂等）。

### A.4 要换掉的 323 个 PUA 占位槽（筛选条件 + 映射表）

筛选（**全部逐槽实测，不引用任何静态标注表**）：

1. `pair_of` 的键是私有区字符 **U+E000..U+F8FF**（PUA 占位）；
2. **不在 col-63**（x=1008..1023；`REPORT_GLYPH_FIX` 已定案：引擎采样矩形右缘 == 贴图宽 1024 取不到）；
3. 格内**零墨**（16×16 全空）；
4. `classify == usable` 且与 **FT 记录矩形交叠 0 px**（3 个 face × 544 条记录全画一遍求交）；
5. 该对偶码在盘上文本里**零引用**（引擎口径逐单元对齐：2,301 条 / 66,997 单元，见 `gap_plan.csv` 的 `refs` 列）；
6. trail 不在 **0xB1/0xB5** 哨兵上（本来就被 `_trail_fix_hashr` 排除在 2,300 之外）。

逐槽结果：**323/323 全过**（零墨 323、usable 323、FT 交叠 0、引用 0）。
完整 323 行映射表 = `work\builds\GR_EXPAND\out\gap_plan.csv`
（列：`slot / pair / pua_char / refs / ink / cls / row / col / x / y / action / new_char / tier / 证据`）。
本轮 `action=ADD` **13 行**（上表），其余 **310 行 = `RESERVE`**（PUA 保持）。

### A.5 盘上唯一"画不出来"的东西 —— 不是缺字，是文本字节

| 现象 | 定位 | 结论 |
|---|---|---|
| 显示成 `与警用损□狙击枪` | `SFXML:T0036` 里 1 个**未映射字节** `0xA2`（全盘 66,997 个单元里只有这 1 个） | **缺的不是字**：`顶` 早在字库且有字形。这是"残段与意图字不等长"的**文本字节**问题（`docs\REPORT_TEXT_FIX2.md` §C 已定性），要用文本轮的 `font_compact.plan_reencode` 修，**不是字库轮能修的** |

---

## B. 实施（只动文本以外的图集 + charset 元数据；ELF 0 字节）

### B.1 工具

| 文件 | 作用 |
|---|---|
| `work\builds\GR_EXPAND\tools\patch_zh139_chars.py`（= `tools\final_fix\patch_zh139_chars.py` 逐字节副本） | 本轮的写盘器：读 plan → 逐项断言 → 只写 13 格像素 → 改 charset |
| `tools\font_pipeline\data\charset_expand_zh139.json` | **tracked** 的 13 字清单（char/slot/pair/档位/证据），复现链的输入 |
| `tools\font_pipeline\data\charset_compiled_zh16.json.before_zh139` | 本轮**改之前**的 charset 原样副本（复现链的输入，与 `.before_zh130` 同规矩） |
| `tools\final_fix\repro_from_eng_zh139.ps1` | 从**英文原盘**逐字节复现（见 C.7） |

### B.2 渲染配方（与现役 1,941 个字形**逐字同款**）

```
ImageFont.truetype('third_party/fonts/方正像素16.ttf', 16)
→ 32×32 白底 canvas → draw.text((8,8), ch) → 取 canvas[8:24, 8:24] → <128 为墨（2 值，无灰度）
```
（与 `gen_font16.render16` / `patch_zh138_glyphs61.render16` / `verify_font_state.r16` 同一份配方）

### B.3 charset 变更（`28a1dd47…` → `23801c8f…`）

- `pair_of` **2,300 条不变**、`codes` **103 条不变**；
- 只有 **13 个键换名**：PUA 占位 → 真字，**`(lead,trail)` 与槽位号完全不动**
  （`B6A8` 兄 / `B6AF` 凉 / `B6C8` 啪 / `B6C9` 姐 / `B6CA` 孩 / `B6CB` 爹 / `B6CC` 闺 /
  `B6CD` 勃 / `B6CE` 揽 / `B6CF` 暖 / `B6D0` 租 / `B6D1` 讶 / `B6D2` 醒）；
- 新增元数据块 `_expand_2300`（工具/版本/基底/槽位/字符/换掉的 PUA 键/逐字证据/墨量/规则）；
- `_font_compact.used` 1,941 → **1,954**、`iso_version` → `GR_ZH139`（`pair_of` 条数与 `free_slots` 不变）；
- 逐项断言：`removed==13`、`added==13`、`codes_same==True`、`pair_preserved==True`（`c1_verify.py` 44b）。

### B.4 文本层：**0 条**条目需要重编码（这不是"没做"，是"不需要"）

用 `font_compact` 自己的字节级引擎 `CodeMap(before, after)` 在**产物盘**上对账：

```
[codemap] changed_pairs = 13 个: B6A8,B6AF,B6C8,...,B6D2
[remap ] 2301 条文本 / 66997 单元: 改动单元 0 / 改动字节 0
[c3] PASS ⇒ 重编码单元 0 / 字节 0 (13 个新码位在盘上文本里零引用)
```

- 13 个被换名的对偶码在盘上文本里**引用数 = 0**（A.4 第 5 条），所以"换名"不会改变任何一条文本；
- 其余 2,287 个对偶码 + 103 个单字节码的**码位逐条不变** ⇒ 重映射是恒等映射；
- 产物与基底的文本容器**逐字节相同**（LANG blob `3d5ebcfa…`、SFXML blob `d9cfb381…`，`c1` 43b PASS）。

> ⚠ 关于 `font_compact.plan_compact`：它在现盘上会报"**有改动**"，但那是它想把这 2,284 个字
> **紧凑重排**到 slot 0..2299（本盘按设计**不做**紧凑重排，与上一轮相同）；`plan_reencode`
> 只在它判定"有改动"时才被调用，所以这里改用 `CodeMap` 直接给出等价的字节级结论。

### B.5 幂等（产物上再跑一次 = 0 改动）

```
[plan] 13 个目标 (0 待画 / 13 已在盘上)
墨量 147031 → 147031 (+0) ; 改动 texel 0 ; 变化格 0 ; 格外 0 ; 保护窗 0
产物 sha256 33b9acd9…bae5   ← **与输入盘逐字节相同**
charset sha256 23801c8f… → 23801c8f…   ← 一个字都没改（`n_new==0` 时直接跳过 charset 落盘）
```

---

## C. 验证（全部实测；脚本与 JSON 都在 `work\builds\GR_EXPAND\out\`）

### C.1 三闸门 + 几何（`c1_verify.py` §3，35 项基线全过）

| 闸门 | 实测 |
|---|---|
| `w < 1025` | 1024 ✓ |
| `px_size == w*h/2 + 16` | 329,744 = 329,728 + 16 ✓ |
| `(w*h/2) % 2048 == 0` | 329,728 = 161×2048 ✓ |
| 段数 / payload / psm | 11 段 / 329,200 / 0x14 ✓ |
| 4bpp 回环 `pack(nibble) == 容器原字节` | True ✓ |

### C.2 `hashr_dump_font.py` 口径（**唯一正确的 dump 入口**）

| 指标 | `GR_ZH138`（用它自己的 charset） | `GR_ZH139` | 差 |
|---|---|---|---|
| 有字形 / 已用 | **1,941 / 2,300** | **1,954 / 2,300** | **+13** ✓ |
| 缺字形（PUA 占位） | 359 | **346** | −13 |
| 截断（模板有墨、盘上整行全空） | **0** | **0** | 0 |
| 空白 / 越窗 / 极稀 | 359 / 1 / 0 | 346 / 1 / 0 | −13 |
| 字形几何体检 错误 / 警告 | 360 / 2 | **347 / 2** | −13 |

> ★ 交叉验证：用 **ZH139 的 charset** 去 dump **ZH138 的盘**，会报"**截断 13**"—— 正好是
> 这 13 个字（说明它们在本轮之前确实是"有码无字形"）。

### C.3 逐 texel / 墨量 / 逐格

| 断言 | 结果 |
|---|---|
| 13 个新格与 16px 模板逐 texel `xor == 0` | **13/13** ✓ |
| 墨量增量 == 13 个模板墨点总数 | **+969 == 969** ✓（NIB 口径 146,070 → **147,039**） |
| 改动的 texel 数 | **969**（= 模板墨点，全部是"加墨"） |
| 变化格数 / 是否全在目标 | **13 格**（1981/1988/2013..2023）/ `all_in_target=True` ✓ |
| 其它 2,337 个格 | **0 格变化** ✓ |
| 目标格之外 texel 变化 | **0** ✓ |
| FT 记录矩形内像素变化 | **0** ✓ |
| 48B 段包头（11 个） | **逐字节相同** ✓ |

### C.4 全盘差异窗口

| 项 | 值 |
|---|---|
| 有差异的字节数 | **768 B**（969 个墨点 texel → 768 个字节：201 对横向相邻墨点共用一个字节） |
| 连续差异 run | **252 个**（最短 1 B） |
| 外接框 | `0x5ECC8406 .. 0x5ECCBF59`（跨度 15,187 B） |
| 图集像素容器窗口 | `[1590196333, 1590526077)` = `0x5ECB900D..0x5ECBFAFD` |
| **窗口外字节** | **0** ✓（252 个 run 全部落在窗口内） |
| `FONT.RES` 展开 blob | 与基底逐字节相同 ✓ |
| ELF | 逐字节相同（`a0c8499c…`）⇒ **Game CRC `653FBF69`** ✓ |
| 文本容器 blob | 逐字节相同 ✓ |

> 交叉工具核对：`tools\final_fix\iso_diff_spans.py`（上一轮的工具，独立实现）在同一对盘上给出
> `same_size=True / differing_bytes=768 / spans=1 / bbox=['0x5ECC8000','0x5ECCC000']` —— 与上表一致
> （它按 4 KB 粒度归并 bbox，故"spans=1"）。

### C.5 载荷级旧码 / 引用

| 断言 | 结果 |
|---|---|
| 遗留旧单字节码（gate 0xBA 口径，逐条目扫） | **0** ✓ |
| 未映射字节单元 | **1**（`0xA2 @ SFXML:T0036`，基底继承，见 A.5） |
| 13 个新码位在文本里的引用 | **0** ✓ |

### C.6 实机回归（模拟器）

| 项 | `GR_ZH139` |
|---|---|
| 6000 帧冷启动（`-grsnap 1`，`nav_menu_only.txt`，空卡 + 同 BIOS） | exit **0** / 跑满 `run end, frames=6000` |
| 截图 | **5,737**（≥190 ✓） |
| `TLB Miss` | **0** ✓ |
| `Trap/jump` | **0** ✓ |
| 收尾残留 | 本次运行进程 **0**（运行结束后 `pcsx2` 计数里那 1 个进程是**另一路**在 16:58:47 起的，pid/启动时间可查） |
| 1 帧粒度 vs `GR_ZH138` | **5,737 / 5,737 逐像素相同（0 差异）** —— 预期结果：现役文本**零引用**新字（A.4/C.5），所以画面必须**一模一样**；这同时是"没有视觉回归"的正面证据（`work\builds\GR_EXPAND\out\frame_diff_zh138_zh139.json`：`frames_common=5737, identical=5737, differing=0`） |

### C.7 从英文原盘逐字节复现

`tools\final_fix\repro_from_eng_zh139.ps1`（新增；只读 `tools\final_fix\repro_from_eng_zh138.ps1`）：
**实测通过（17:00:45 → 17:12，`-SkipProductCopy -KeepIntermediate`）**，逐段 sha256 全等，最后一段
产出 **`33b9acd9341f6e8f382e87545c4f75a0399eb4ba12f3bb02d4b58d3acb06bae5`** = 交付成品（逐字节相同）。

| 段 | 输入 → 工具 | 产物 sha256 | 判定 |
|---|---|---|---|
| 输入 | ENG 原盘 `2b42ea7c…` ⊕ K2 转储 `11f371f2…`（`rebuild_base.py`） | `d7f83d7e…443ca0` | ✓ 等声明值 |
| 2 | 基底 + `apply_fix.py --spec fix_spec_merged.json` | `e65e77fb…8791a1` | ✓ |
| 3 | + `patch_zh130_glyph_edge.py` | `db3f8b99…8aeefb` | ✓（门禁 15/15） |
| 4 | + `patch_zh133_stale_hashr.py` | `3fb12c8d…2cdf95` | ✓（门禁 13/13） |
| 5 | + `patch_zh134_textfix2.py` | `165b7eb2…3ecd6a` | ✓ |
| 6 | + `patch_profile2_text.py` | `172b35cc…408140` | ✓ |
| 7 | FF gate（文本区间内 0xFF 必须 0） | 1,608 容器 / 143,599 文本段 | ✓ PASS |
| 8 | + `patch_zh138_glyphs61.py` | `7396f55c…541a2f2` | ✓ = `GR_ZH138` |
| 9 | + `patch_zh139_chars.py --plan charset_expand_zh139.json` | **`33b9acd9…cb06bae5`** | ✓ = `GR_ZH139` |
| 10 | 身份 + ELF CRC + FF gate + 差异窗口 | md5 `38a764f4…` / CRC `653FBF69` / `differing_bytes=768` | ✓ 全过 |

> ⚠ 一处口径说明：复现链里 `patch_zh139_chars.py` 写的是**草稿副本** charset（`--charset`），
> 该副本的 sha256 是 `4952d1d3…`，与仓库里最终那份 `23801c8f…` **不同**——差别只在元数据块
> `_expand_2300.base` 记录的**输入盘路径**（`...repro_zh139\GR_ZH138.iso` vs `...GR_RELEASE\GR_ZH138.iso`）。
> **`pair_of` / `codes` 逐条相同、ISO 逐字节相同**（`c1_verify.py` 44b 已断言）。

---

## D. 用户测试步骤（5 分钟）

1. 用 **`work\builds\GR_RELEASE\GR_ZH139.iso`** 启动（PCSX2 直接"运行 ISO"）。
2. 存档兼容：Game CRC 仍是 **`653FBF69`** ⇒ `SLUS-20613 (653FBF69).01.p2s` 瞬间存档与
   `GR_ZH133..ZH138` 的存档**继续可用**，不需要新开档。
3. 本轮**没有任何画面变化**（文本 0 改动、现役文本不引用新字）—— 看到与 `GR_ZH138` 完全一样的画面
   就是**正确结果**；这一轮的收益是"**下一轮文本修订不再被字库卡住**"。
4. 想核对字库本身：在任意能显示汉字的界面确认 `兄 凉 啪 姐 孩 爹 闺 勃 揽 暖 租 讶 醒` 这 13 个字
   现在有字形（可以用 `work\builds\GR_FONTFIX\out\evidence\` 里上一轮的做法出一个对照图，
   或直接跑 `python tools\rounds\hashr\tools\hashr_dump_font.py --iso <ZH139> --out <dir>` 看
   "有字形 1954 / 已用 2300"）。
5. 若发现任何画面/声音异常，回退到 `GR_ZH138.iso`（同目录，`7396f55c…`）即可 —— 两盘只差 **768 B**（全在图集里）。

---

## E. 未达成 / 残余（如实登记）

| # | 项 | 状态与原因 |
|---|---|---|
| 1 | 323 个槽**没有**全部填满 | **有意为之**：只有 13 个有证据（A.2/A.3）。剩余 310 槽保持 PUA，`patch_zh139_chars.py --plan` 一条命令可补（幂等） |
| 2 | `SFXML:T0036` 的 `0xA2` 残段 | **未修**：缺的不是字（`顶` 有字形），是文本字节不等长；属文本轮（`plan_reencode`），本轮按任务约束不动文本 |
| 3 | `T0051/T0068/T0069` 三处残段 | 同上，**未修**（文本字节问题） |
| 4 | 1 帧粒度的"新字可见"证据 | 本轮**0 差异是预期结果**（现役文本不引用新字）；"新字真的能显示"由**静态逐格 + TTF 逐 texel** 给出，不是实机截图 |
| 5 | `旗`(slot 832) 墨贴图集左缘 / `验` `骚` 1~2 texel 微差 | **基底继承，未动**（本轮只往空槽加墨） |
| 6 | 模拟器独占口径 | 本轮运行 16:57:17–16:59:37；另一路的运行在 16:58:47 起（**不是我启动的**），有约 50 s 重叠。按纪律只等不杀；帧内容为帧驱动渲染，5,737 帧对照结果见 C.6 |
| 7 | `font_compact.plan_reencode` 未直接调用 | 它只在 `plan_compact` 判定"有改动"时才跑，而现盘上那个"改动"是**紧凑重排**（本盘按设计不做）⇒ 改用同一模块的 `CodeMap` 做等价的字节级对账（0 单元 / 0 字节） |

---

## F. 复跑命令（全部只读或只写自己的目录）

```powershell
# 1) 槽位普查 (只读)
python work\builds\GR_EXPAND\tools\a1_state.py --iso work\builds\GR_RELEASE\GR_ZH138.iso
# 2) 缺口分析 (三路语料 + 可渲染性)
python work\builds\GR_EXPAND\tools\a2_gap.py
# 3) 323 槽逐槽映射 + 零引用对账
python work\builds\GR_EXPAND\tools\a3_plan.py --iso work\builds\GR_RELEASE\GR_ZH138.iso
# 4) 出盘 (幂等; 幂等时 charset 一个字都不写)
python work\builds\GR_EXPAND\tools\patch_zh139_chars.py `
    --base work\builds\GR_RELEASE\GR_ZH138.iso --out work\builds\GR_RELEASE\GR_ZH139.iso `
    --plan tools\font_pipeline\data\charset_expand_zh139.json
# 5) 静态验证 (35 项基线 + 10 项专项)
python work\builds\GR_EXPAND\tools\c1_verify.py --iso work\builds\GR_RELEASE\GR_ZH139.iso `
    --ref work\builds\GR_RELEASE\GR_ZH138.iso --json-out work\builds\GR_EXPAND\out\verify_zh139.json
# 6) 重编码对账 / 7) 6000 帧 / 8) 1 帧粒度 / 9) 从 ENG 复现
python work\builds\GR_EXPAND\tools\c3_reencode_check.py --iso work\builds\GR_RELEASE\GR_ZH139.iso
powershell -NoProfile -ExecutionPolicy Bypass -File work\builds\GR_EXPAND\tools\c2_smoke.ps1
python work\builds\GR_EXPAND\tools\c4_frame_diff.py --a work\builds\GR_FONTFIX\runs\fg_ZH138 `
    --b work\builds\GR_EXPAND\runs\fg_ZH139 --tag-a GR_ZH138 --tag-b GR_ZH139 `
    --json work\builds\GR_EXPAND\out\frame_diff_zh138_zh139.json
powershell -NoProfile -ExecutionPolicy Bypass -File tools\final_fix\repro_from_eng_zh139.ps1
```
