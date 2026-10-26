# REPORT_FONT_FIX — 字库生成链修复 + 61 个缺字形补齐 + 文档订正 + 旧资料归档

> **轮次**：`fix/font`（2026-10-20）· 执行者：字库修复子代理
> **输入**：`docs/REPORT_FONT_STATE.md`（上一轮只读盘点：35/35 PASS、98.858% 可重建、三个真缺陷 + 61 缺字形）
> **产出**：**`work/builds/GR_RELEASE/GR_ZH138.iso`** + `GR_ZH138.meta.json`
> **写入范围**：`work/builds/GR_FONTFIX/**`、`work/builds/GR_RELEASE/**`、`tools/font_pipeline/**`、
> `tools/text_csv/**`、`tools/iso_build/{repack_font,font_compact}.py`、`docs/**`、`docs/_obsolete/font_legacy/**`。
> 其它一切只读（`third_party/**`、用户 PCSX2 目录、既有成品盘、`GR_FONTSTATE/**`、`GR_PROFILE3/**`）。

---

## 0. 结论速览

| # | 任务 | 结果 | 一句话证据 |
|---|---|---|---|
| A1 | `tcslib.py` 几何常量 → 实测值 | ✅ **修好** | 62/2/3 → **64/3/2**（`ATLAS_PHI={}`、`GRID_MOD=NCOL`）；裸跑 `dump_font.py` 与 `hashr_dump_font.py` 产出 **6/6 文件逐字节相同**，假截断报告 **1,458,682 B → 106,195 B** |
| A2 | `repack_font.py` import 绑死的 `NCOL` | ✅ **修好** | 新增 `read_elf_grid()` / `sync_geometry_from_iso()`，`plan()`+`apply()` 都先从盘上 ELF 现读 + 断言；反向测试 T1：故意把 tcslib 改回 62/2/3 ⇒ 工具**以盘为准**纠正并打印 |
| A3 | `font_compact.py::plan_compact` 中止 | ✅ **修好** | `CompactError 420/2300` → 在 GR_ZH137 上**跑通**（PUA 359 豁免 / 已登记缺字形 61 单列 / 来源不明 0）；反向测试 T2：篡改 1 个槽 ⇒ **立即拒绝** |
| A4 | 35/35 回归 + 审计一致 | ✅ | `verify_font_state.py` 在 GR_ZH137 上 **35/35 PASS**（改后）；裸跑与包装器审计**逐字节同一口径** |
| B | 61 个缺字形补齐 | ✅ | 61/61 槽 **xor==0** vs TTF；墨量 **141,343 → 146,070（+4,727）**；逐格对比 **只有这 61 格变，格外 0** |
| C1 | `FONT_CURRENT_STATE.md` 订正 | ✅ | 旧文（62/2/3/1024×512）归档；新文 = **64/3/2/1024×644**，抬头写明"以盘上 ELF 立即数为准 + 日期" |
| C2 | `_expand_fa2400.migrated_codes` 四字顺序 | ✅ | 击/小/时/按 的 `pair_new`+`slot` 与 **盘上 + pair_of + gate_pairs.json** 一致（按=2345…击=2348）；`docs/CORRECTIONS.md §10.3` |
| C3 | "107 单字节码"→103 + `_font_compact` 版本戳 | ✅ | 状态文档口径已全为 **103**（`grep` 0 命中 107）；戳更新到 **GR_ZH138 / used 1941 / free_slots 50 / r58.1** |
| C4 | ASCII 343/343 vs **英文源盘** | ⚠ **口径否证 + 给出实测** | 记录数 343/343 成立；但"逐 texel 与英文原盘相同"**不成立/不可比**（记录几何 343/343 全不同）；**能站住的同族对比 = 343/343 记录 + 343/343 像素与基底完全相同** |
| D1 | 候选盘 + meta | ✅ | `GR_ZH138.iso` sha256 `7396f55c…a2f2` / md5 `4a7a5150…` / ELF CRC **653FBF69** / 1,648,164,864 B |
| D2 | 从 ENG ISO 逐字节可复现 | ✅ | 新增 `tools/final_fix/repro_from_eng_zh138.ps1`，实测 8 段全过（详见 §D2） |
| D3 | 三闸门 / 审计 / 1 帧粒度 / 6000 帧冒烟 / 回读 | ✅（1 帧粒度见说明） | 35+5 项 PASS；5,737/5,737 帧逐像素相同；两盘各 6000 帧 / **TLB 0 / Trap 0** / 5,737 截图；61/61 回读 xor==0 |
| D4 | 未达成项如实登记 | ✅ | 见 §F |
| E1 | 21 份旧资料归档 | ✅ | `docs/_obsolete/font_legacy/`：**7 份搬走 + 14 份冻结快照**，2,484,052 B，**没有物理删除任何文件**，`MANIFEST.json` 逐条 sha256 |
| E2 | 本报告 | ✅ | 本文件 |
| E3 | `STATUS.md` 更新 + 分支 | ✅ | 新增 §0.00；分支 **`fix/font`** 从 `fix/text2` 切出，**未 push** |

**一句话**：**字库生成链修好了（下一轮构筑不会再卡）**，**61 个"登记了却看不见"的字现在画上了**（图集只动这 61 格），
**盘还是那张盘**（ELF 一字没动 ⇒ CRC `653FBF69` ⇒ 旧存档继续可用），并把这轮暴露的**错误口径**从文档与元数据里清掉了。

---

## A. 修生成链（让下一轮构筑能跑）

### A1. `tools/text_csv/tcslib.py`：几何常量改实测值

**改了什么**

| 常量 | 旧值 | 新值 | 依据 |
|---|---|---|---|
| `NCOL` | 62 | **64** | 盘上 ELF VA `0x4170AC` imm `0x40`（ISO `0x3AA92C`） |
| `GRID_Y0` | 2 | **3** | VA `0x4170F8` imm 3（ISO `0x3AA978`） |
| `GRID_SKIP_ROWS` | 3 | **2** | VA `0x4170E8` imm 2（ISO `0x3AA968`） |
| `ATLAS_PHI` | `{0..24: 6/12/18/24/30/36/42}`（62 列拟合表） | **按容器几何生成**：`PHI[r] = 6×(yrow(r)//64+1) mod 64` | K2 容器 11 段、每段 48B 包头 ⇒ 裸容器相对引擎图右移 **6 格/段**；拟合表从行 14 起就对不上 |
| `atlas_flat_x_shift` | `96×(min(y//64,7)+1)`（最多 8 段） | **`96×(y//64+1)`** | 8 段是 1024×512 时代的产物；K2 是 11 段 |
| `GRID_MOD` | 写死 64 | **`= NCOL`** | 派生量，避免下次改 NCOL 时静默错位 |

同时把同一文件里 6 处 62 列口径的注释/说明（`atlas_cell_xy_engine` 文档串、`atlas_flat_x_shift`、
FontGuard 前言、`ATLAS_X0` 的 legacy 说明）改成 **K2 口径 + 历史留档**，并显式写出三个 VA / ISO 偏移。

**证据 1：派生量自洽**（`p2_plan_gate.json` + `verify_zh138.json` 的专项 36）

```
tcslib: NCOL=64 Y0=3 SKIP_ROWS=2 SKIP_ROW=12 GRID_MOD=64 lead_hi=0xBA capacity=2350
ATLAS_PHI = {0..3:6, 4..7:12, 8..11:18, 12..13:24, 14..17:30, 18..21:36, 22..25:42,
             26..29:48, 30..33:54, 34..36:60}                     # 由容器几何生成
atlas_cell_xy_engine(s) == atlas_flat_pos(atlas_cell_xy_engine_view(s))   # 2,350/2,350
dump_font.grid_row_alignment() == {每行: 0}                          # 不再假报"字形不在采样格上"
```

> ⚠ 这里改过一版口径（如实记）：最初把 `ATLAS_PHI` 清成 `{}`（理由是"NCOL==64 没有回绕"），
> 结果 `dump_font.grid_row_alignment()` 把**行 0..28 全部**报成"字形偏 22~42 格、不在引擎采样格上"
> —— 那是**假警报**（实测 1,935/1,937 个格与 TTF `xor==0`）。正确做法是把 PHI 定义成
> **裸容器相对引擎图的真实错位**（每段 6 格），`grid_row_alignment` 于是恒为 0；
> 同时 `atlas_flat_x_shift` 去掉"最多 8 段"的截断（K2 有 11 段），两者才能逐 slot 对齐。
> 62 列那张**拟合**表已废弃（从行 14 起就与 K2 容器不符）。

**证据 2：裸跑审计 == 官方包装器（逐字节）**

```powershell
python tools\iso_build\dump_font.py            --iso …\GR_ZH137.iso --out <d> --prefix GR_ZH137 --no-png
python tools\rounds\hashr\tools\hashr_dump_font.py --iso …\GR_ZH137.iso --out <d> --prefix GR_ZH137 --no-png   # 同一目录, 覆盖写
```
两次产物在**同一目录**里覆盖后逐文件 sha256 对比：**6/6 相同**（`atlas_README.txt` / `font_charset.csv` /
`font_ft.csv` / `font_summary.json` / `truncation_report.{json,md}`）。
`hashr_dump_font.py` 现在打印的覆写是 "64→64 / 2→2 / 3→3"（became a no-op），
**说明它的配方已下沉进 `tcslib`**，不再依赖包装器。

**证据 3：1.4 MB 假 truncation 不再出现**

| 口径 | `truncation_report.md` | findings | truncated | empty | overflow | sparse | errors | warnings | `row_shift` 命中 |
|---|---|---|---|---|---|---|---|---|---|
| 旧（裸跑，tcslib 62/2/3） | **1,458,682 B** | 2,227 | 890 | 357 | 166 | 113 | 1,272 | 955 | **1,751** |
| 新（裸跑，tcslib 64/3/2） | **106,195 B** | **423** | **61** | 420 | **1** | **0** | 421 | **2** | **61** |

新的 61 条 `truncated` **正好**是 §B 那 61 个缺字格（"窗内一个墨点都没有"是**真的**），
420 条 `empty` = 359 PUA 占位（设计如此）+ 61 缺字；`errors 421 = 420 empty + 1 ink_out`。

**残留的 1 条 `ink_out`（与本轮无关，如实记）**：`旗` slot 832 cell `(0,243)` —— 该格左缘贴图集 x=0，
字形被图集边界裁掉一点。基底继承，本轮不动。

### A2. `tools/iso_build/repack_font.py`：不再 import 时绑死 `NCOL`

> ⚠ 任务书写的是 `tools\font_pipeline\repack_font.py` / `font_compact.py`；**实际路径是 `tools\iso_build\`**
> （`tools/font_pipeline/` 下没有这两个文件）。本轮改的是实际文件。

```python
NCOL, CW, CH = tcslib.NCOL, tcslib.CW, tcslib.CH     # ← 仍是 import 时快照, 但只作初值
ELF_GRID_IMM = (('NCOL', 0x4170AC), ('SKIP_ROWS', 0x4170E8), ('Y0', 0x4170F8))

def read_elf_grid(iso_path): ...                     # 只读: 从盘上 ELF 立即数读三个值
def sync_geometry_from_iso(iso_path, verbose=True):  # ★ 以盘为准; 不符就进程内覆写 + 打印
    ...  # 最后 assert 模块级 NCOL/CW/CH 与盘一致
```

* `plan()` 第一行、`apply()` 第一行都调用 `sync_geometry_from_iso()`；
* `summary` 里落一个 `geom_from_elf`（含 `source` 与 `yrow` 公式）—— 以后任何一次重排都能追溯口径；
* `TOOL_VERSION` r46.1 → **r46.2**。

**证据（正常路径）**：`p2_plan_gate.json → repack_plan.ok=true`，
打印 `[geom] NCOL=64 CW=16 CH=16 Y0=3 SKIP_ROW=12 SKIP_ROWS=2 (ELF 0x4170AC/E8/F8 实测)`。

**证据（反向测试 T1，证明它真的在读盘）**：

```
before: NCOL=62 Y0=2 SKIP_ROWS=3          ← 人为把 tcslib 改回旧值
[geom] ★ 盘上 ELF 立即数 = NCOL=64 Y0=3 SKIP_ROWS=2, 而 tcslib 是 NCOL=62 Y0=2 SKIP_ROWS=3
       ⇒ **以盘为准**进程内覆写 (不改源文件)
after : NCOL=64 Y0=3 SKIP_ROWS=2 (repack_font.NCOL=64)      [PASS]
```

### A3. `tools/iso_build/font_compact.py::plan_compact`：`420/2300` 门禁

**根因**：旧门禁把"在用字、但 charset 指的槽位在图集里是空的"整块判成 **"charset 与盘对不上"**，
超过 2% 就 `raise`。现役盘上是 **420** 个：**359 个 PUA 占位（刻意留白）+ 61 个已登记的缺字形**。

**修法（三分类 + 零容忍）**，判据函数放在 `repack_font.py`（两个工具共用一份真源）：

| 类别 | 判据 | 处理 |
|---|---|---|
| `pua` 359 | 码位在 `U+E000..U+F8FF` | **豁免**（占位键，无字符/无字形，永远空） |
| `registered_missing` 61 | 在 charset 元数据 `_expand_cap2400.real_chars` 里登记过，**且**该槽位的字与 `pair_of` **一致** | **不豁免**：仍逐字计入 `missing_glyph_before` 并打印；只是它属于"已登记的缺字形"这个**已知缺陷**，不是"charset 版本不对" |
| `unexplained` | 其余 | **1 个就中止**（比旧的 2% 阈值更严），错误信息点名到字 |

> **为什么不能"只豁免 PUA"**：只豁免 359 的话剩 61/2300 = **2.65% > 2%** ⇒ GR_ZH137 仍然中止，
> 与"修好生成链"直接矛盾。所以把 61 单列成**具名已知缺陷**（并由 §B 在 GR_ZH138 上清零），
> 而不是把它们并进 PUA 豁免里 —— 61 个字的字表、槽位、缺字计数一个都没被抹掉。

同样修法也应用到 `repack_font.plan()` 的同一道门（同一个缺陷的另一个实现）。

**证据（正向）**：`p2_plan_gate.json`

```
[!!] 有 420/2300 个在用字的"当前槽位"在图集里是空的 —— 分三类:
     · PUA 占位 359 个  (豁免)
     · 已登记未绘制 61 个  (不是版本问题; 仍计入缺字形): 鼠弧撒兽埋匍匐签趴钮冶坡坞怖脉喀寨贩党杠浏猎猫草陪净努堤墩峭…
     · **来源不明 0 个**
plan_compact ok=True ; repack_plan ok=True
glyphs: used=2300 moved=2284 kept=16 missing_glyph_before=61 pua_placeholder_before=359
```

**证据（反向 T2，证明门禁没被放水）**：把 slot 63 的 PUA 占位 `\ue22a` 换成没登记的真汉字 `龘` ⇒

```
· PUA 占位 358 个 / 已登记未绘制 61 个 / **来源不明 1 个**: 龘
CompactError: !! 拒绝重排: 1/2300 个在用字在 charset 指的槽位上是空的, 且既不是 PUA 占位、也没在
              charset 元数据里登记 —— charset JSON 与这张盘对不上 (龘)。
对照: 原 charset → ok, used=2300 pua=359 missing=61        [PASS / PASS]
```

### A4. 回归：`verify_font_state.py` 仍 35/35

```powershell
python work\builds\GR_FONTSTATE\tools\verify_font_state.py --iso work\builds\GR_PROFILE3\GR_ZH137.iso `
       --json-out work\builds\GR_FONTFIX\out\verify_zh137_after_fix.json
# => [RESULT] PASS (35 项, FAIL 0)      K2 几何: NCOL=64 Y0=3 SKIP_ROWS=2 gate=0xBA
```

基线（A1~A3 改动前）同样 35/35（`verify_zh137_baseline.json`）⇒ **三处代码改动没有破坏任何既有断言**。

> ⚠ **C2/C3 之后这一条要换个姿势看**（如实记）：那条 35 项里的 `charset sha256` 钉的是
> **旧 charset 文件**（`04c44f5c…`）。C2（订正 `migrated_codes` 四字顺序）与 C3（`_font_compact` 戳）
> **必须改那个文件** ⇒ 用**新** charset 跑老脚本会得到 `34/35`，唯一的 FAIL 就是这条"钉旧文件"的断言
> （实测 `[FAIL] charset sha256 got=28a1dd47… want=04c44f5c…`）。
> 两种正确读法都已实测：
>
> | 跑法 | 结果 | 含义 |
> |---|---|---|
> | `--charset <旧快照>`（`git show 19c8fc35:…` ⇒ `04c44f5c…`，138,155 B） | **35/35 PASS** | A1~A3 的代码改动对"旧盘 + 旧 charset"零影响 |
> | `--iso GR_ZH138 --charset <新>`（`fontfix_verify_zh138.py`，EXPECT 换成新值） | **35/35 + 5/5 PASS，漂移 0** | 新盘与新 charset 自洽 |
>
> 旧快照留在 `work\builds\GR_FONTFIX\out\charset_zh137_snapshot.json`（不进 git）。

---

## B. 补齐 61 个缺字形（本轮的可见收益）

### B1. 对象

`charset._expand_cap2400.real_chars` 登记了槽 **1872..1935** 的 64 个真汉字 `{槽位: [字, 频次]}`；
其中 **61 个槽在盘上零墨**（另 3 个 1896 / 1900 / 1919 早已画好）。逐个（按槽位序）：

```
鼠 弧 撒 兽 埋 匍 匐 签 趴 钮 冶 坡 坞 怖 脉 喀 寨 贩 党 杠 浏 猎 猫 草 陪 净 努 堤 墩 峭 巩
幢 店 廉 怒 怪 恼 慎 拾 掂 掘 搏 棘 洪 湿 狗 缉 缕 缴 腊 舱 蛇 螯 逞 遗 锚 闯 陡 鞋 颠 驳
```

槽位 → 格位（K2 公式）：row 29 col 16..63（`y=499`）+ row 30 col 0..15（`y=515`）。

### B2. 工具与"只改这些格"的保证

`work/builds/GR_FONTFIX/tools/patch_zh138_glyphs61.py`，只做一件事：
用**与现有 1,874 个槽完全相同的配方**渲染（`ImageFont.truetype(方正像素16, 16)` → 32×32 白底 →
`text((8,8))` → `[8:24,8:24]` → `<128` 为墨），写进各自**已登记**的槽位。

写前/写后硬断言（任一不过就**不写盘**）：

| # | 断言 | 结果 |
|---|---|---|
| 1 | 目标数 == 61 且全部在 `_expand_cap2400.real_chars` 里 | 61 ✅ |
| 2 | 每个目标格当前**零墨**（只加墨、不擦任何像素） | 61/61 ✅ |
| 3 | 每个目标格分类 `usable`（不越界、不压 FT 记录矩形） | 61/61 ✅ |
| 4 | 模板非空（字体里真有这个字） | 61/61 ✅ |
| 5 | 改动 texel 数 == 61 个模板墨点总数 | 4,727 == 4,727 ✅ |
| 6 | 目标格之外变化的 texel == 0 | ✅ |
| 7 | 保护窗（FT 记录矩形）变化 == 0 | ✅ |
| 8 | 11 个 48B 包头逐字节不变 | ✅ |
| 9 | 回读：61/61 与模板 `xor==0`；其它 2,289 格 0 变化；容器外字节不变 | ✅ |

### B3. 数字（texel 级）

| 项 | 值 |
|---|---|
| 墨量（规范口径：初值 0xF、`nibble==0` 为墨） | **141,343 → 146,070**，**+4,727** |
| 61 个模板墨点总数 | **4,727**（对账相等） |
| 61 槽 `xor` vs TTF 模板 | **61/61 == 0**（≥ 阈值的 0 个） |
| 逐格对照 vs GR_ZH137 | 2,350 槽里**只有 61 格**变化；**格外 0 texel**；范围 = slot 1872..1935 |
| 全盘字节差异 | **3,760 B / 1 个区间** `0x5ECC6000..0x5ECCA000`（= `MENU.IMG@+0x97000`，图集像素容器） |
| 像素平面 sha256 | `4fda5590…` → **`77087f15be4ae367d8ef95dbe83a145a124d315f56d0d6af9e3b5984af292ef6`** |
| 图集几何 | 1024×644 / psm 0x14 / px_size 329,744 / 11 段 / payload 329,200 —— **全部不变** |

> ⚠ **两个墨量数字差 8，已查清**：`repack_font.Atlas.decode()` 按"整行"解码，会丢掉末段那
> **半行**（496 B = 992 texel）里的墨；规范口径（`verify_font_state` 的 NIB 逐 texel 填充）不丢。
> 所以工具内部 `141,335 → 146,062 (+4,727)`、规范口径 `141,343 → 146,070 (+4,727)` ——
> **增量相同**，61 个格都在整行区间内，与这 8 个 texel 无关。

**前后对照图**（引擎格位直取，红 = 新画的，灰 = 原空）：
`work/builds/GR_FONTFIX/out/evidence/glyphs61_before_after.png`
与 TTF 模板对照：`work/builds/GR_FONTFIX/out/evidence/glyphs61_vs_ttf.png`（61/61 xor==0）。

---

## C. 订正文档与元数据

### C1. `docs/FONT_CURRENT_STATE.md`

* 旧文（27,067 B，明写"现役 `NCOL=62 / Y0=2 / SKIP_ROWS=3 / 1024×512`"）**冻结归档**到
  `docs/_obsolete/font_legacy/docs/FONT_CURRENT_STATE.md.pre_zh138`；
* 现文**整篇重写**：抬头写明"**以盘上 ELF 立即数为准** + 2026-10-20"，给三个 VA / ISO 偏移、
  K2 格位公式、容器几何、容量账本、本轮 4 项改动、识别过时文档的技巧；
* `docs/README.md` 索引同步（`FONT_CURRENT_STATE.md` 行改成"2026-10-20 重写为 K2 实测值"，
  新增 `font_legacy/` 归档小节）。

### C2. `_expand_fa2400.migrated_codes` 四字顺序（**写反了**）

| 字 | 旧元数据（错） | 订正后（盘上 + `pair_of` + `gate_pairs.json` 三方一致） |
|---|---|---|
| 按 | B9FD slot 2348 | **B9FA slot 2345** |
| 时 | B9FC slot 2347 | **B9FB slot 2346** |
| 小 | B9FB slot 2346 | **B9FC slot 2347** |
| 击 | B9FA slot 2345 | **B9FD slot 2348** |

实测复核（盘上这四格的像素 vs 各自 TTF 模板）：`xor` 全 0；`pair_of` 现为
`按=[185,250] 时=[185,251] 小=[185,252] 击=[185,253]`，与订正后的元数据逐条相等。
记入 **`docs/CORRECTIONS.md §10.3`**。

### C3. "107 单字节码" → **103**；`_font_compact` 版本戳

* `grep -n "107" docs\STATUS.md docs\RELEASE_NOTES_2400.md docs\BUILD_VERSIONS.md …` ⇒ **0 命中**（状态文档早已是 103，
  唯一残留是 `RISK_BUDGET_r84.md` 里"r84 时点 107 条记录"的历史陈述 —— 已加注"FA2400 后 = 103"）；
* `CORRECTIONS.md §10.2` 明确记一条（107 → 103 = FA2400 删掉 击/小/时/按 的单字节码）；
* `charset._font_compact` 从 **`GR_ZH113_B` / `ff3abd3c…` / `used 1504` / `free_slots null`**
  更新为 **`GR_ZH138` / `7396f55c…` / `used 1941` / `free_slots 50` / `tool_version r58.1` /
  `atlas_pixel_sha256 77087f15…`**，并附一段 `note_stamp_20261020` 解释 `used` 的口径
  （本盘**未做**紧凑重排 ⇒ `used` 是"有字形的登记槽"，不是 r58 时代的 1504）。

### C4. ASCII `343/343` vs **英文源盘**：口径否证 + 实测数字

**先给结论**：上一轮 `REPORT_GLYPH_FIX.md` L176 的 343/343，"源盘"指的是**该补丁的输入盘**
（ZH129 → ZH130 的一次前后对照），**不是**英文原盘。用英文原盘复跑，"逐 texel 相同"这个口径**不成立**，
原因是**两边的记录几何根本不同**（不是盘坏了）：

| 项 | 英文原盘 | 现役 GR_ZH138 |
|---|---|---|
| 图集 | **512×512**，psm `0x13`（8bpp） | **1024×644**，psm `0x14`（4bpp） |
| FT 记录条数 | 224 / 224 / **224** | 224 / 224 / **96** |
| ASCII 记录矩形 | `large`/`default` 面 **14×26**；`huge` 面 **27×42** | 三面**共用**同一套 **8×16**（ç/ñ **7×13**；0x92/0xAE **16×16**） |
| 例：`0x41 'A'` | `(309,0)-(323,26)` | `(192,627)-(200,643)` |

实测（`p3_ascii_vs_eng.py` / `p11_ascii_scaled.py`，两个盘都现读）：

| 比较 | 数字 |
|---|---|
| 参与比较的记录（三 face × `0x21..0x9C`，非退化） | **343** |
| 记录矩形**完全相同**的条数 | **0 / 343**（`rect_mismatch = 343`）⇒ 逐 texel 比较**无定义** |
| 把英文记录**最近邻缩放**到现役尺寸后 `xor==0` | **1 / 343**；`xor ≤ 4` 只有 5 / 343；平均 `xor` **32.43**、平均 IoU **0.167** |
| **同族对比**（GR_ZH137 → GR_ZH138）：记录字段相同 | **343 / 343** |
| **同族对比**：字形像素逐 texel 相同 | **343 / 343** |

⇒ **能站住的说法**：① ASCII 记录 **343/343 存在且非退化**；② GR_ZH137→GR_ZH138 这 343 条记录与像素
**逐 texel 相同**（本轮没碰 ASCII）；③ **不能**说"与英文原盘逐 texel 相同" —— 现役盘的 ASCII 带是
**8×16 重绘**（英文原盘是 13/14×26 的 8bpp 字形），两者不是同一份位图。
记入 `CORRECTIONS.md §10.6` 与本报告 §F。

---

## D. 候选盘 + 验证

### D1. 身份

| 项 | 值 |
|---|---|
| 盘 | **`work/builds/GR_RELEASE/GR_ZH138.iso`**（+ `GR_ZH138.meta.json`） |
| 大小 | 1,648,164,864 B（与基底逐字节同尺寸） |
| sha256 | **`7396f55cd8d4d7ea5dd7806a355a25c8413c59a2bf1296547722e54bd541a2f2`** |
| md5 | `4a7a5150bc467480f970c547e20742fe` |
| ELF | `SLUS_206.13` @LBA 295，37,453,732 B，sha256 `a0c8499c…`（**与 GR_ZH137 逐字节相同**） |
| Game CRC | **`653FBF69`** ⇒ 即时存档名 `SLUS-20613 (653FBF69).01.p2s` 不变 ⇒ **旧存档可用** |
| 相对基底 | GR_ZH137 `172b35cc…408140`；**差异 3,760 B / 1 个区间**，全在图集像素容器内 |

### D2. 从 ENG ISO 逐字节复现（新增脚本）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\final_fix\repro_from_eng_zh138.ps1
```

实测输出（8 段，逐段 sha256 断言；中间盘用后即删，删除前打印清单）：

```
[0] ENG original 2b42ea7c…  ; K2 dump 11f371f2… ; font 方正像素16 1453d424… ; spec/tools 全部就位
[1] ENG + K2 --rebuild_base.py-->      d7f83d7ec4a8fe1ec8d60de4b17b94513bd1540dc929d3b667086f4910443ca0  ✓
[2] + fix_spec_merged.json -->        e65e77fbb696ec5dd9dfaf5b6ca5bbc62d26bfa00e1f5c238fa150c4868791a1  ✓
[3] + patch_zh130_glyph_edge -->      db3f8b997a9dfaa89e5147cbeb75341d71d271cedbd53a2dd1c8aa1bee8aeefb  ✓
[4] + patch_zh133_stale_hashr -->     3fb12c8d16c2448e5c8976896b8132d65b3f6c8cf0e679f709aaf2b2572cdf95  ✓
[5] + patch_zh134_textfix2 -->        165b7eb2c667fc0c373b193f054ecd525d04124e5c57f9e69f6e69e4043ecd6a  ✓
[6] + patch_profile2_text  -->        172b35cc940431e99a128ed1ff5d5f80941362a2bf1a281d2a0d8b09ee408140  ✓ (= ZH136/ZH137)
[7] FF gate on ZH136: PASS (1,608 容器 / 143,599 文本区间 / 2,436,537 B / 0 个 0xFF)
[8] + patch_zh138_glyphs61 -->        7396f55cd8d4d7ea5dd7806a355a25c8413c59a2bf1296547722e54bd541a2f2  ✓
[9] ELF CRC 653FBF69 ✓ ; FF gate on ZH138: PASS ; ISO diff vs ZH137: 3,760 B / 1 span
[10] 发布到 work\builds\GR_RELEASE\GR_ZH138.iso（同卷 Move，不额外占盘）
```

**确定性加证**：另用 `patch_zh138_glyphs61.py` **直接**在 GR_ZH137 上打补丁，
产物 sha256 = `7396f55c…a2f2` —— **与整链产物同一个 sha**（说明第 8 步是纯数据、可重复；
校验副本用完即删，删前打印清单）。再补一次：从本次整链**刚重建出来的** `GR_ZH136.iso`
打同一个补丁，产物依旧是 `7396f55c…a2f2`。

> ⚠ **一处脚本 bug（已修，如实记）**：把这两个工具复制到 `tools\final_fix\` 之后，
> 它们原来按 `'..'` 的个数推断仓库根 ⇒ 在新位置 `import tcslib` 失败（`ModuleNotFoundError`，
> 整链在第 8 步 exit=1、GR_ZH136 被保留）。现已改为**向上找 `docs/` + `tools/text_csv/tcslib.py`**
> 定位仓库根；`work\builds\GR_FONTFIX\tools\*` 与 `tools\final_fix\*` 两份副本**逐字节相同**，
> 各自都跑通，整链重跑 exit=0。

### D3. 验证

**(a) 三闸门 + 35 项基线 + 5 项专项**（`p4_verify_zh138.py`；原 `verify_font_state.py` **只读未改**，
用 importlib 载入后只替换 `EXPECT`）：

```
[RESULT] PASS   (35 项, FAIL 0)          期望值漂移 0 项
[p4] baseline: 35 项, FAIL 0 ; 专项: 5 项, FAIL 0
  [PASS] 36 engine==engine_view (2350 slots)          got=0
  [PASS] 37 61 newly-filled cells xor==0 vs TTF       got=61 drawn / 0 bad
  [PASS] 38 ink delta == sum(template ink) of the 61  got=4727
  [PASS] 39 vs ref: only the 61 cells changed         got=61 cells
  [PASS] 39b full-plane texel delta == 61 templates   got=4727
```

其中 35 项里的关键行：ISO sha ✓ · ELF gate/NCOL/Y0/SKIP_ROWS ✓ · charset sha `28a1dd47…` ✓ ·
`pair_of 2300` / `codes 103` ✓ · `1024×644 / psm 0x14 / px_size 329,744 / 11 段 / payload 329,200` ✓ ·
三闸门 ✓ · 4bpp 回环 True ✓ · 墨量 146,070 ✓ · `有字形 1941 / 无字形 359 / PUA 359 / col-63 36 / 真汉字缺字形 0` ✓ ·
`xor==0 1935 / ≤8 1937 / >8 0` ✓ · FT `224/224/96`、`u1max 1018`、ASCII 124/124 ✓。

**(b) 审计**：裸跑 `dump_font.py` 与 `hashr_dump_font.py` 逐字节一致（§A1）；本盘 truncation 报告里
`truncated` **61 → 0**、`empty` **420 → 359**（剩下的全是设计内的 PUA 占位）。

**(c) 1 帧粒度 vs GR_ZH137**（`p6_frame_diff.py`；两盘各 6,000 帧、`-grsnap 1`、同一 `nav_menu_only.txt`、
同一份 mc/bios）：

```
A=GR_ZH137 (5737 帧) B=GR_ZH138 (5737 帧) 共同 5737 ; 相同 5737 ; **不同 0**
```

**如实说明**：这条导航走的是 **logo → 片头视频 → 主菜单**，**没有任何一帧显示这 61 个字**，
所以"0 帧不同"是**预期结果**，它证明的是**没有视觉回归**（而不是"收益可见"）。
可见收益由**静态逐格证据**给出（§B3 的 61 格对照图 + 逐格 xor）——
这也是本盘的改动**只有 61 个字形格**这一事实的直接推论。

**(d) 6000 帧冒烟**（`p7_smoke_frames.ps1`，两盘串行、跑前轮询零 pcsx2、只等不杀）：

| 盘 | exit | 截图 | 用时 | TLB Miss | Trap | 跑满 | 收尾残留进程 |
|---|---|---|---|---|---|---|---|
| GR_ZH137 | 0 | **5,737** | 123 s | **0** | **0** | `frames=6000` | 0 |
| GR_ZH138 | 0 | **5,737** | 121 s | **0** | **0** | `frames=6000` | 0 |

（判据要求 ≥190 截图 ⇒ 5,737 ≫ 190；两盘用同一份 `mc_pristine` / `bios` / `nav`。）

**(e) 图集回读逐格比对**：`patch_zh138_glyphs61.py` 写盘后**重新从产物解一遍**：
61/61 `xor==0`；其它 2,289 格 `0` 变化；11 段包头逐字节相同；容器外字节不变；
四元组 `(w,h,psm,px_size)` 不变。

### D4. 关于"新解 == 旧解"门禁

`font_compact.apply()` 自带的那道 "**新解 == 旧解**（逐字重编码幂等）" 门禁**不适用于本盘**：
本轮**没有跑**紧凑重排 / 重编码（`plan_compact` 的目标是把 2,300 个字形压到 slot 0..2299，
本盘保持既有空洞布局不变）。本盘改的是**图集像素**，与"码位↔字节"映射无关 ⇒
`pair_of` / `codes` / 任何文本容器都一字未动（FONT.RES 展开 blob sha256 `c7876128…` 与基底相同）。
**替代门禁** = 上面 (a)~(e)，其中对"像素级同一性"的要求由 `39/39b`（逐格 + 全平面 texel）承担。

---

## E. 归档 + 文档

### E1. 21 份旧资料 → `docs/_obsolete/font_legacy/`

来源 = `work/builds/GR_FONTSTATE/out/B_assets.csv` 里 **verdict=stale 的 21 行**（行 13..33）。
**先打印完整清单（含大小/sha256）再动手**，逐条复核 sha256：

| 动作 | 份数 | 含义 |
|---|---|---|
| **move** | **7** | 纯数据、**无任何活引用** ⇒ 真搬进归档目录（git 可回滚；原位置不再残留） |
| **copy / rewrite** | **14** | 仍在**活引用链**上（`import`/`exec`/读表）或在只读写入区 ⇒ 原位保留 + **冻结快照** |

合计 **2,484,052 B (2.37 MB)**。**没有物理删除任何文件**。

`move` 的 7 份：`charset_compiled_zh16.json.pre_font_v2`、`ft_expanded_zh1{6,4}.bin`、
`atlas_zh1{6,4}.png`、`charset_expand_zh113.csv`、`docs/han_v2/charset_stats.json`。
`keep+snapshot` 的 14 份（含 3 份**不能搬**的活引用）：

| 文件 | 谁在用 |
|---|---|
| `tools/iso_build/dump_font.py` | `repack_font` / `font_compact` / `verify_font_state` **import** 它 |
| `tools/font_pipeline/gen_font16.py` | `build_font.py` 用 **exec** 跑它 |
| `tools/font_pipeline/data/name_dot_plan.csv` | `apply_name_dots.py` 读它 |

其余 11 份 = 13px 期 charset/统计、hashr/txmig 一次性脚本、GR_GLYPHFIX 的审计输出、
GR_MERGEFIX 的 charset 分段产物、以及**旧版 `FONT_CURRENT_STATE.md`**。
索引：`docs/_obsolete/font_legacy/README.md`（逐条理由 + 回滚命令）· 机读：`MANIFEST.json`。
`docs/README.md` 已加 `font_legacy/` 小节。

### E2. 本报告

`docs/REPORT_FONT_FIX.md`（本文件）。

### E3. `docs/STATUS.md` + 分支

* `STATUS.md` 新增 **§0.00（2026-10-20 fix/font 轮）**：成品身份 / 字库口径 / 验证 / 残余；
* 分支 **`fix/font`**（从 `fix/text2` 切出），提交但**不 push**。

---

## F. 未达成 / 口径订正（如实登记）

| # | 项 | 状态 | 说明 |
|---|---|---|---|
| 1 | **"ASCII 343/343 与英文源盘逐 texel 相同"** | ❌ **口径不成立** | 见 §C4：英文原盘 512×512 8bpp、记录 14×26 / 27×42；现役 1024×644 4bpp、三面共用 8×16。记录几何 **343/343 全不同**，最近邻缩放后也只有 1/343 `xor==0`（平均 xor 32.43 / IoU 0.167）⇒ 现役 ASCII 是**重绘**，不是英文图集的位图拷贝。**能站住的数字**：记录 **343/343** 存在；**ZH137→ZH138 记录 343/343 + 像素 343/343 相同** |
| 2 | **"1 帧粒度差异只出现在显示这 61 字的画面"** | ⚠ **未拍到** | 本轮导航（`nav_menu_only`）到主菜单为止，**没有一帧显示这 61 个字** ⇒ 实测 0 帧差异。要拍到需要一条能走到提到这些字的界面的导航（或专门的字体测试页盘）。**补拍建议**见 §G |
| 3 | **`font_compact.apply()` 的 "新解==旧解" 门禁** | ⚠ **不适用** | 本盘没跑重排/重编码（见 §D4）；该门禁对"只改图集像素"的改动无意义 |
| 4 | **紧凑重排在现役盘上会搬 2,284 个字** | ⚠ **未执行（有意）** | `plan_compact` 现在能跑通，但它会把字形压到 slot 0..2299（`pixels_changed=178,488`）。本盘**保持既有布局**（与基底可比、改动最小）。若将来要重排，那是一次独立的全量重编码轮 |
| 5 | **图集既有告警 1 处 `ink_out`（`旗` slot 832 贴左缘）+ 2 处微差（`验`/`骚` 1~2 texel）** | ⚠ **未修** | 基底继承，与本轮目标无关；已记入 `GR_ZH138.meta.json.residual` |
| 6 | `tasks` 里写的 `tools\font_pipeline\{repack_font,font_compact}.py` | ⚠ **路径订正** | 实际在 `tools\iso_build\`；本轮改的是实际文件（`tools/font_pipeline/` 下没有这两个文件） |
| 7 | `RISK_BUDGET_r84.md` 的 "107 条单字节记录" | ⚠ **历史陈述，加注** | 那是 r84 时点的事实；已在文件里加注"FA2400 后 `codes` = **103**"，不改历史正文 |

---

## G. 复现 / 验证命令速查

> **脚本位置**：`work/**` 不入库（`.gitignore`），所以本轮所有验证/取证脚本都在
> `tools\final_fix\fontfix_*.py` 留了**逐字节相同**的**可入库副本**；下面用后者。
> `work\builds\GR_FONTFIX\tools\p*.py` 是等价的**工作副本**（报告正文里的证据就是用它跑出来的）。

```powershell
$PY = 'C:\Users\84363\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# ① 从英文原盘整链复现 GR_ZH138（约 12 分钟，峰值 ~3.3 GB）
powershell -NoProfile -ExecutionPolicy Bypass -File tools\final_fix\repro_from_eng_zh138.ps1

# ② 35 项基线 + 5 项专项（原 verify 脚本只读，只换 EXPECT）
& $PY tools\final_fix\fontfix_verify_zh138.py `
      --iso work\builds\GR_RELEASE\GR_ZH138.iso `
      --ref work\builds\GR_PROFILE3\GR_ZH137.iso `
      --json-out work\builds\GR_FONTFIX\out\verify_zh138.json

# ③ 生成链三缺陷的正/反向证据
& $PY tools\final_fix\fontfix_plan_gate.py        # 正向: plan_compact/repack_plan 都跑通
& $PY tools\final_fix\fontfix_negative_tests.py   # 反向: T1 盘上 ELF 优先 / T2 篡改必拒

# ④ 裸跑审计 == 官方包装器（6/6 文件逐字节相同）
& $PY tools\iso_build\dump_font.py --iso work\builds\GR_RELEASE\GR_ZH138.iso --out <d> --prefix X --no-png
& $PY tools\rounds\hashr\tools\hashr_dump_font.py --iso work\builds\GR_RELEASE\GR_ZH138.iso --out <d> --prefix X --no-png

# ⑤ 1 帧粒度 + 6000 帧冒烟（模拟器独占；跑前轮询零 pcsx2，只等不杀）
powershell -NoProfile -ExecutionPolicy Bypass -File tools\final_fix\fontfix_smoke_frames.ps1
& $PY tools\final_fix\fontfix_frame_diff.py --a work\builds\GR_FONTFIX\runs\fg_ZH137 `
      --b work\builds\GR_FONTFIX\runs\fg_ZH138 --tag-a GR_ZH137 --tag-b GR_ZH138

# ⑥ 只改 61 格的自证（逐格 + 全盘字节区间）
& $PY tools\final_fix\fontfix_selftest.py
& $PY tools\final_fix\iso_diff_spans.py --a work\builds\GR_PROFILE3\GR_ZH137.iso `
      --b work\builds\GR_RELEASE\GR_ZH138.iso

# ⑦ ASCII vs 英文源盘（口径否证 + 实测）
& $PY tools\final_fix\fontfix_ascii_vs_eng.py
& $PY tools\final_fix\fontfix_ascii_scaled.py

# ⑧ 前后对照图（静态取证）
& $PY tools\final_fix\fontfix_evidence_png.py

# ⑨ 旧资料归档（先打印清单，再搬/快照，逐条复核 sha256）
& $PY tools\final_fix\fontfix_archive_legacy.py --dry-run
& $PY tools\final_fix\fontfix_archive_legacy.py
```

**补拍建议（第 2 项未达成）**：如果要有"可见收益"的实机证据，
① 走到提到这 61 个字里任意一个的界面（武器/任务/档案名），或
② 用 `tools/iso_build/make_font_testpage.py` 出一张**字体测试页盘**（独立盘、不进交付），
在同一导航下对 ZH137/ZH138 各跑 1 帧粒度对照 —— 那时差异帧的 bbox 应**正好**落在那 61 个格对应的屏幕位置。
