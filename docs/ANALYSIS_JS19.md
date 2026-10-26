# ANALYSIS_JS19 — JS_ZH19 上一版中文构筑的译文与字符映射还原

> **执行者**：js19-recovery（task-6）· **日期**：2026-10-21 · **口径**：只读原盘/转储，不改任何输入
> **状态**：已完成。本文所有数字均来自本仓库脚本实测，可复现（§6）

---

## 0. 一句话结论

**JS_ZH19（上一会话对同一资料片的中文构筑）的 2,278 条已翻译 LANG 条目已 100% 还原**：
2,275 条含汉字（共 **22,594 汉字 / 881 个不同字 / 0 条未解析码**），另 693 条未翻译（英文原样）。
还原路径 = **ELF cave 公式定几何 → 图集逐格 OCR 定 cell→char（1209/1283 有墨格 xor==0）→
按 cave 状态机解 pair/single 双字节流 → 用 693 条未译条目做逐字节回归自证（655/693 完全一致，
其余 38 条差异已逐条查明是 JS19 把西文重音字节改画成汉字，不是解码错误）**。

译文质量：**人工级、术语统一、富文本标记 `{p}` 完整保留**，可作为本工程的高价值翻译记忆（TM）；
但**未经校对，不可直接作为交付译文**（有 1 条语义偏差、1 条错译、若干可润色项，见 §4）。
**881 个用字全部落在本工程 `charset_compiled_zh16.json` 内 ⇒ 复用这份 TM 不需要新画任何字形。**

---

## 1. 输入与口径

| 文件（相对仓库） | 大小 | sha256（前 16） | 角色 |
|---|---|---|---|
| `work/analysis/js19/JS_ZH19_ELF_from_dump.bin` | 5,319,720 | `80e2559992105156…` | 上一版补丁后 ELF；**Game CRC = 3A320B22**（PCSX2 口径，本次复核） |
| `work/analysis/js19/payloads/00009_COMMON.PAK.bin` | 763,676 | `59becb28e60d3dfc…` | 中文图集（`new_font_revised`，psm=19 PSMT8 512×512） |
| `work/analysis/js19/payloads/00576_EN_STRINGS.RES.bin` | 69,355 | `99da1d1f710a463b…` | LANG 资源（11 个 LZO 子流，展开 177,441 B） |
| `work/analysis/js19/payloads/00580_FONT.RES.bin` | 4,460 | `856f907ce524c42d…` | 字库定义（LZO 展开 7,488 B，3 face × 224 条 10B 记录） |
| `third_party/orig/ps2/[PS2] Tom Clancy's Ghost Recon - Jungle Storm (U).iso` | 1,229,225,984 | — | 英文原盘（只读，用于取英文 LANG 做对照） |
| `assets/charset/charset_compiled_zh16.json` | — | — | 本工程字符集（2300 pair + 103 single，只作对照，**不是**解码依据） |
| `third_party/fonts/方正像素16.ttf` | — | — | 字形来源（OCR 模板） |

> 说明：JS19 的**图集、FONT.RES、LANG 都是上一版按自己的口径重写过的**；它的 pair 编码与
> 本工程字符集**不是同一套**（§3.4），所以背景里「用本工程字符集解码是乱码」是对的
> （例：文本 `A2E4` 在本工程字符集是「年」，在 JS19 里是「®」）。

---

## 2. 方法（五步，每步都有独立自证）

```
ELF cave 常量 ──► 图集几何(62 列 × 8×16, Y0=2, SKIP_ROW=12,+3)
                      │
TTF 16px 渲染 ──► 字形配方校准(16×16 →OR 半采样→ 8×16) ──► 逐格 OCR ──► slot→char
                      │                                              ▲
LANG 字节流 ──► cave 状态机切码 ──pair→slot──────────────┘
                      └─single→ FONT.RES FT 记录 rect ──► 图集格 ──► char
                                    ↓
                        2971 条解码 → 693 条未译条目回归自证
```

### 2.1 图集几何：ELF cave 常量 + 像素自证（双证据）

`elf-analyst` 已把 JS19 cave（VA `0x1808A8..0x180C98`，file_off = VA − 0xFFF00）逐条反汇编，
UV 块（`0x180A48`）的常量如下（本任务引用，不作假设）：

| 含义 | 值 | VA | 指令字 |
|---|---|---|---|
| pair 索引基（FT 记录数） | 0xE0 = 224 | 0x180A78 | `258500E0 addiu $a1,$t4,0xE0` |
| 每行 cell 数 NCOL | **0x3E = 62** | 0x180A90 | `240E003E addiu $t6,$zero,0x3E` |
| row = slot / 62 | — | 0x180A94 | `018E001A div $zero,$t4,$t6` |
| cell 宽 CW | **8** | 0x180AA4 | `240F0008 addiu $t7,$zero,0x8` |
| U0 = 8·col + 2；U1 = +0xA | 2 / 10 | 0x180AAC/B0 | `25C50002` / `25CC000A` |
| SKIP_ROW | **12** | 0x180AB4 | `240F000C` |
| row ≥ 12 时 row += 3 | **+3** | 0x180AC4 | `25AD0003` |
| cell 高 CH | **16** | 0x180AC8 | `240F0010` |
| V0 = 16·row + 2；V1 = +16 | 2 / 0x12 | 0x180AD0/D4 | `25CD0002` / `25CE0012` |

**像素侧自证**（`tools/recovery/js19_atlas_introspect.py`）：

* 图集 = 单 GIF 包：16 B tag + 262,144 B，PSMT8 每 texel 1 B；像素值只有 `0`（墨，66,352 px）与 `15`（底）。
* 按上式切格，`ink` 剖面完全吻合：`y=208..239` 恰好 32 px 空档（= 3 行被 SKIP），
  `x=0,1` 恒空、格从 `x=2` 起；**行 0..18 每行 62 格全部有墨，行 19 有 34 格** ⇒ 有墨格 **1,283 / 1,446**。
* 每个格子的位图是 **8×16** 的汉字——即上一版把汉字**横向压缩一半**（≈ ASCII 宽度）来省图集。

> ⚠ 与另一份分析（font-engineer 的 `32 列 × 16×16`）的差异已澄清：按 16 px 周期切会得到「640 格」的错觉；
> 逐格 OCR 的 xor==0 只可能出现在正确的 8×16 切分上（§2.2），故以 62 列 × 8×16 为准。

### 2.2 字形配方校准：16×16 → OR 半采样 → 8×16

本工程既有配方 = `PIL truetype(方正像素16, 16px) → 32×32 画 (8,8) → 裁 [8:24,8:24] → <128 为墨`。
上一版明显沿用了同一配方，再**横向合并相邻两列**（任何一个为墨则墨）。用图集前 64 格
（图集第 0..7 格依次是 区 移 挥 备 机 记 入 图，与本工程字符集 `pair_of` 顺序一致）做假设检验：

| 压缩方式 | 前 62 格平均 xor | xor==0 格数 |
|---|---|---|
| 取偶数列 `a[:,0::2]` | 20.8 | 0 |
| 取奇数列 `a[:,1::2]` | 15.7 | 0 |
| **OR 合并 `a[:,0::2] \| a[:,1::2]`** | **0.65** | **61 / 62** |
| AND 合并 | 35.8 | 0 |

⇒ **配方 = OR 半采样**（唯一 outlier 是上一版改画过的一格）。这一步让 OCR 从"猜测"变成"精确匹配"：
全图 **1,209 / 1,283 有墨格 xor == 0 且唯一命中**，其余 74 格是未被文本使用的低置信格。

### 2.3 逐格 OCR（cell → char）

* 候选集 2,729 字（ASCII 可打印 + 中文标点 + 本工程 charset 2300+103 + 常用汉字 3,500 去重），
  可渲染模板 2,382 个；
* 用 (N×128) 布尔矩阵做汉明距离（`dist = popA+popB−2·A·Bᵀ`，numpy 一次算完）；
* 判据：`dist==0 且与次优差 ≥2` → `high`；`≤2` → `medium`；否则 `low`（不做硬凑，低置信保留原值）。
* 结果：`high 1,209 / low 74 / blank 163`；文本**实际用到**的 813 个 pair 槽里只有 **1 个**低置信
  （slot 161，见 §3.3，已用上下文定为 `®`）。

### 2.4 编码状态机（这是全任务最关键的一步）

JS19 文本不是"朴素双字节流"。cave decoder（VA `0x1808C8`）是**有状态**的：

```
b = 当前字节
若 b < 0xA1                                  → 单字节码（len=1）
否则若 b < 0xAE 且 下一字节 ∈ [0xA1,0xFF)     → 双字节 pair（len=2，cell=(lead<<8)|trail）
否则                                          → 单字节码（len=1）   ← 0xAE..0xFE 全部走这里
```

指令字：`0x1808D4 2CA900A1 sltiu $t1,$a1,0xA1` / `0x1808E0 2CA900AE sltiu $t1,$a1,0xAE` /
`0x180900 91EB0001 lbu $t3,1($t7)` / `0x180910 2D6900FF sltiu $t1,$t3,0xFF` / `0x180924 A48C0000 sh`。

* **pair 槽**：`slot = (lead−0xA1)*94 + (trail−0xA1)`（cave `0x180998..0x1809B0`；
  其中 `+0xE0` 是 FT 记录表 index，UV 块 `0x180A8C addiu $t4,$a1,−0xE0` 又减回去）。
  容量 = (0xAE−0xA1)×94 = **1,222**（lead 只 0xA1..0xAD）。
* **UV**：`row=slot//62, col=slot%62, x=2+8·col, y=2+16·(row+3·[row≥12])`，采样窗 **8×16**。
* 全量扫描结果：**pair 14,455 次**（lead 全部落在 0xA1..0xAD，trail 0xA1..0xFE）+
  **单字节高码 9,765 次** + 单字节 ASCII 71,025 次 ⇒ 与 cave 门限完全自洽，**没有"数据与几何不匹配"**。

> 背景里"lead 范围 0xA1..0xFE、2066 个 pair"来自**朴素 bigram** 统计（把 0xAE..0xFE 的单字节码也当 lead 了）；
> 正确口径是 14,455 个 pair token、1,222 槽容量。该纠正已同步给 elf-analyst/lead。

### 2.5 单字节码（0xAE..0xFE 等）

单字节码分支回到原版 DLC 函数（cave `0x180B08 → j 0x21A218`）：
`FT 记录 index = code − 0x20`（FontDefinition 的 base = 0x20），取 `FONT.RES` 里 10 B 记录
`{u8 f0}{u8 advance}{u16 u0}{u16 v0}{u16 u1}{u16 v1}` 的矩形去采样图集。

上一版把**新的汉字**也塞进了单字节高码（省一半字节），做法是让 FT 记录的矩形直接指向图集网格格：

* rect 的 `u0` **漏加了 +2**（字形画在 `8*col+2`、采样从 `8*col` 起）⇒ 单字节汉字右移 2 px、右缘被裁 2 px。
  这是**上一版的数据 bug**（cave 的 U0 带 +2，说明"画"的位置对、是 rect 记录里没带），但不影响解码：
  按 ink 实际位置取整格即可，OCR 与 pair 格结果一致（§3.3 表中 `AF..C1` 就是连续 19 格）。
* 实测解析出 **168 个单字节码** = 高码（≥0xAE）**79 个** + ASCII（<0xA1）**88 个** + Latin-1 透传（0xA9）1 个：
  - `0xBA..0xFE`：与本工程 charset `codes` **逐字相同**（战 要 在 开 器 弹 射 队 训 火 组 一 动 习 面 务 准 可 会 出 里 换 进 下 如 地 以 到 中 定 斗 是 任 后 放 置 不 切 命 向 和 退 装 枪 标 使 员 人 爆 选 这 个 设 手 随 视 戏 游 目 前 指 更 它 有 雷 何 上）；
  - `0xAF..0xB9`（9 个，本工程没有）：**的 你 键 练 用 击 小 时 按** —— JS19 自己补的高频字码位；
  - `0xAE/E7/F1`：保留 cp1252 语义 `® / ç / ñ`（西文残留，见 §3.3）；
  - `0xA9`（作为单字节出现 1 次）：`©`，出现在未翻译的版权声明里。

### 2.6 三重自证

1. **像素级**：1,209/1,283 有墨格模板 xor==0（§2.2）。
2. **回归级**：693 条**未改动**（字节与英文原盘完全相同）的条目，用同一套映射解码后与英文原文比较：
   **655 条完全一致**；38 条不一致**全部**是法语人名里的重音字母（`Frédéric`/`François`/`Pendariès`…），
   因为 JS19 把 `é/è/ê` 的字节位改画成了汉字（`Frédéric → Fr员d员ric`）。**已验证**：对这 38 条改用
   「单字节码按 Latin-1 透传」解同一批原始字节，**38/38 与英文原文完全一致** ⇒ 差异 100% 来自
   JS19 的码表替换（它的取舍/显示 bug），**不是解码错误**。
3. **语义级**：2,275 条译文全部可读、术语一致、`{p}` 段落标记保留（§3.2/§4）。

---

## 3. 还原结果

### 3.1 字符映射规模（`work/analysis/js19/js19_charset.json`）

| 项 | 数量 |
|---|---|
| 图集网格格（pair 容量） | 1,222（lead 0xA1..0xAD × trail 0xA1..0xFE） |
| 图集有墨格 / OCR xor==0 | **1,283 / 1,209**（唯一命中） |
| 文本实际用到的 pair 槽 | **813**（14,455 个 pair token） |
| 文本用到的单字节码 | **168**（其中高码 79 个，9,765 token） |
| 未解析码 | **0** |
| 低置信映射（使用中） | **0**（1 个歧义已人工判定，§3.3） |

### 3.2 译文解码结果（`work/analysis/js19/js19_lang_decoded.csv`）

| 指标 | 数值 |
|---|---|
| LANG 条目 | 2,971（67 个组，与英文原盘条目数/组结构一致） |
| 已翻译（字节与英文不同） | **2,278** |
| 其中含汉字 | **2,275**（3 条只改了标点/大小写：`PING= `→`PING =`、`Ping`→`PING`、`MODS`→`MOD`；另有 38 条**未译**条目因重音字节被 JS19 改画，显示层也含汉字——CSV `note` 列已逐条标记「勿复用于注入」） |
| 未翻译（英文原样） | 693（其中 group 61 整组 393 条 = 制作人员名单，未译） |
| 汉字总数 | **22,594** |
| 不同汉字 | **881** |
| 唯一英文串（去重后） | **1,792**（483 个重复 id，如 `Victory!` 11 条、`Excellent!` 21 条） |
| 同英不同译 | **3 组**（且都是标点/用词微差：`Good Job !`→干得好！/干得好!；`Enemy Camp`→敌军军营/营地；`Rank`→军衔/无） |
| 中英混排条目 | 246（绝大多数是品牌词：`START`、`PlayStation®2`、`Ubi.com`、`MB/KB`、`MEMORY CARD`） |
| 译文/原文长度比 | **0.301**（汉字≈0.3×英文字符数，正常） |
| 翻译覆盖的组 | 67 组中 63 组有译文；大头：group 57（在线/法务文本）1,273、64 → 141、60 → 53、11..17 训练各 43 |

### 3.3 歧义与人工判定（全部记录在 charset json 的 `note`）

| 位置 | 判定 | 依据 |
|---|---|---|
| pair slot 161（pair `A2E4`） | **`®`** | OCR 最佳候选 `*`（dist 13）不可用；27 条上下文全是 `PlayStation®2`；本体 charset 同位置（slot 160）也正是 `®` |
| 单字节 `0xAE` | `®` | 条目 `Change DUALSHOCK®2…`（英文原样，未译） |
| 单字节 `0xE7` | `ç` | `Français` / `François Roy` / `Jean-François Dupuis`（未译人名） |
| 单字节 `0xF1` | `ñ` | `Español`（未译） |
| 单字节 `0xA9` | `©` | 版权声明（未译） |
| 未译 693 条中的 38 条重音人名 | 保留英文原文 | JS19 显示层会画成汉字（其 bug），我们 TM 里按英文记录，标注不可复用其显示 |

### 3.4 JS19 的 pair 字表 vs 本工程 charset：为什么直接解码是乱码

把 OCR 出的「JS19 slot→字」与本工程 `pair_of` 的「slot→字」对齐（1,212 个 pair 格）：

* **1,141 个字能在本工程 pair 表里找到** ⇒ 两套字表**同源**（同一批 2300 字表演化而来）；
* 槽位关系分三段：`slot 0..135` **严格同序**（delta=0）；`slot 137` 起整体**错位 −1**（多插了 1 个字，如全角 `；`）；
  `slot ≈700` 起错位 **−19/−20**（又插了 18 个字，多为全角标点/符号）；
* 本工程字表里的 **PUA/空槽（如 slot 15/19/63/110/…）被 JS19 用本体尾部扩字（slot≥1900，如 星 择 引 吗 文 给）填掉了**；
* 所以同一 pair 在两套表里指向不同字：`A2E4` 本工程=`年`、JS19=`®`；直接用本工程 charset 解 JS19 文本会得到
  「大部分字对、整体错位」的乱码（实测样例：`Victory!` 会被解成「辑化帕」）。

**结论**：JS19 的 pair 编码**不能**直接借用本工程编码；但它翻译的**文本内容**与**字→pair 的对应关系**
已随 `js19_charset.json` 完整还原，可无损映射到本工程编码。

---

## 4. 译文质量评价（随机分层抽样 44 条，本文点评其中 38 条）

抽样方法：从 2,275 条含汉字条目按长度分三层（短 ≤30 字 / 中 31–120 / 长 >120）随机抽，
种子固定（`random.seed(200119)`），全量 44 条见 `work/analysis/js19/js19_quality_sample.csv`；
下表点评 38 条 = 其中 36 条 + 可疑条目清单里补充的 2 条（`57.96` / `57.799`）。

评价符号：**✓ 可用**（准确自然，可直接进 TM）· **○ 可润色**（意思对，用词/标点可优化）·
**▲ 需复核**（语义有偏差）· **● 不可用**（错译）

### 4.1 短串（UI / 提示）

| ID | 英文 | JS19 译文 | 评价 |
|---|---|---|---|
| 9.3 | Defeat! | 失败！ | ✓ |
| 0.2 | Firefight | 遭遇战 | ✓ 术语准 |
| 15.42 | Training | 训练 | ✓ |
| 21.8 | 1. Seize Airfield | 1. 夺取机场 | ✓ |
| 31.12 | 3. Reach Extraction Zone | 3 - 到达撤离区 | ✓（编号符 `.`→`-`，可润色） |
| 65.36 | Lieutenant General | 中将 | ✓ 军衔准确 |
| 37.3 | September 22, 2008 | 2008年9月22日 | ✓ 日期本地化正确 |
| 57.1177 | Username | 用户名 | ✓ |
| 57.105 | CONNECT | 连接 | ✓ |
| 50.14 | Objective | 目标 | ✓ |
| 60.1 | Move Forward | 向前移动 | ✓ |
| 13.31 | Good Job! | 干得好！ | ✓ |
| 24.14 | Convoy | 车队 | ✓ |
| 57.904 | Support | 支援队员 | ✓（兵种名，符合语境） |
| 57.939 | DEMO | 爆破手 | ✓（demolition 兵种） |
| 57.531 | INSTRUCTIONS | 指导 | ○（建议「说明」） |
| 57.1085 | Mouse Hunt | 捉人游戏 | ○（游戏模式名，可改「猎鼠行动」） |
| 2.9 | Be a mouse for 3 minutes. | 当满 3 分钟的目标. | **▲ 语义偏差**（原文是"当 3 分钟老鼠"，译成了"目标"；标点用半角） |

### 4.2 中串（训练/系统提示）

| ID | 英文（节选） | JS19 译文（节选） | 评价 |
|---|---|---|---|
| 57.1005 | Are you sure? You will lose your progress for this mission. | 你确定吗？你将丢失本任务的进度。 | ✓ |
| 57.425 | Check your game progress. | 查看你的游戏进度。 | ✓ |
| 57.1174 | Caution! If you wish to save your game data, insert a memory card (8MB) (for PlayStation®2) with at least 160KB of free space… | 注意!如需保存游戏数据,请插入至少有 160KB 可用空间的记忆卡(8MB)(PlayStation(R)2 专用)并选择重试;选择取消则继续且不保存. | ✓（品牌/容量保留；`PlayStation(R)2` 是它自己转的写法） |
| 14.1 | Use the Fire Weapon button to place the claymore in the center of the blast pit… | 用开火键将地雷放置在弹坑中央。把它对准靶子假人--放置时它会朝向你面对的方向。地雷放好后，退到安全的掩体里准备引爆。 | ✓ 通顺、术语一致（claymore→地雷） |
| 16.5 | Open doors using the Perform Action button… | 用动作键来开门。开门的时候尽量不要正对着门--这可能使你马上成为门后敌人的靶子。 | ✓ |
| 17.16 | Notice how the rocket reticule differs from the rifle and grenade reticules… | 你应该注意到火箭筒的准星和步枪与手雷的都不一样。你必须要等准星变成最小的时候才能开火… | ✓ |
| 13.17 | This is the rocket range. Here you'll learn how to fire antitank rockets… | 这里是火箭筒训练区。你要学习如何使用反坦克火箭筒。随时按 START 键退出训练。 | ✓ |
| 12.24 | If you hold the Set button down while adding a waypoint you'll see a firing arc… | 添加路径点时按住设置键会出现一个射击扇面。用右摇杆可以改变射击扇面的朝向… | ✓ 术语好（waypoint→路径点、firing arc→射击扇面） |
| 11.11 | This is the machine gun range… | 这里是机枪训练区。你要学习如何使用固定的机枪… | ✓ |
| 16.27 | Press and hold the Character Selection button… platoon. | 按住角色选择键可以呼出角色选择界面。在这里你可以查看排里其他队员的状态。 | ✓ |
| 16.20 | The sniper rifle is equipped with a scope… | 狙击步枪装有用于远距离射击的瞄准镜。用放大/缩小键进行连续变焦… | ✓ |
| 17.21 | In addition to standing upright, you can crouch and go prone… | 除了站立，你还可以蹲下和卧倒。在战场上，压低身体是避免中弹的好办法… | ✓ |
| 11.6 | Press the Fire Weapon button to launch a grenade… | 按开火键来发射榴弹。标准的榴弹发射器每开一炮就要装一次弹。榴弹遭到撞击后会马上爆炸… | ○（后半句主语略生硬） |
| 57.96 | Ubi.com Account | Ubi.com 户口 | **● 错译**（account 应为「账号/账户」；建议「Ubi.com 账号」） |
| 57.799 | I Link | I Link 联机 | ○（品牌+功能，可接受） |
| 57.1147 | Saving data. Do not remove memory card (8MB) (for PlayStation®2) in MEMORY CARD slot 1, reset, or switch off the console. | 正在保存数据。请勿移除记忆卡槽1里的记忆卡(8MB) (for PlayStation®2)，重启或关闭主机。 | ○（`(for …)` 英文残留） |

### 4.3 长串（任务简报，最能看出译者水平）

| ID | 英文（节选） | JS19 译文（节选） | 评价 |
|---|---|---|---|
| 50.12 | Some enemy armored vehicles escorting two trucks have become lost. You have been tapped to take all of them out.{p}Intel has again marked some good ambush points… | 两辆卡车在敌军装甲车的护送下走失了。上级点名要你们把它们连同装甲车全部解决。{p}情报再次在你们的指挥地图上标出了几个合适的伏击点。赶快赶到这些位置，打装甲车一个措手不及。{p}打坦克和装甲运兵车需要反坦克火箭… | ✓ **高质量**：任务语气、`{p}` 保留、术语（APC→装甲运兵车）准确 |
| 47.8 | Welcome to your first tactical exercise… your objective is to eliminate the opposing force…{p}There are enemy patrols in the area… | 欢迎参加第一次战术演习。本次任务的目标是消灭对方部队。{p}该区域有敌军巡逻队。查看指挥地图，可以看到情报已经为你们和你的小队标出了几个合适的射击位置… | ✓ 高质量 |
| 48.9 | Here's the situation, Intel has discovered that one of our downed airmen was being transported in a train… | 情况是这样的：情报发现，我们一名被击落的飞行员正被用火车运往某地审讯。多亏几枚放得很准的炸药，火车已经脱轨。{p}你们的任务是打进去，救出我们的飞行员… | ✓ 高质量（叙事语气自然） |
| 57.1137 | Insufficient space on memory card (8MB)… An additional 94KB is needed to manage Your Network Configuration file. | 记忆卡插槽 1 的记忆卡(8MB)(PlayStation(R)2 专用)空间不足.请插入至少有 160KB 可用空间的记忆卡(8MB)(PlayStation(R)2 专用),或用主机内置整理功能清理空间.管理网络设置文件还另需 94KB. | ✓ 信息完整，标点半角（可润色） |

### 4.4 质量结论

* **总体**：这是**人工级**译文（非机翻）：术语统一（fireteam→战斗小组、extraction zone→撤离区、
  waypoint→路径点、APC→装甲运兵车、claymore→地雷、loadout→配置）、语气按语境切换（任务简报/系统提示/名单）、
  富文本 `{p}` 全部保留、长度控制良好（0.30×，适合 PS2 UI）。
* **可复用度**：本文点评的 38 条中 **✓ 31 条（82%）、○ 5 条（13%）、▲ 1 条（3%）、● 1 条（3%）**，
  即 **约 8 成可直接进 TM，1 成多建议润色，<5% 需重译**（这是"已经翻译了的 2,275 条"内部的合格率，
  不含 693 条未翻译条目）。
* **已知缺陷**：① 2.9 类语义偏差；② `Ubi.com 户口` 错译；③ 半角标点混用（`. , ; !`）；
  ④ 品牌词/容量保留英文（对 PS2 UI 通常是对的）；⑤ 未翻译 693 条（含制作名单 393 条）；
  ⑥ 38 条法语重音人名在 JS19 显示层是汉字（我们不要复刻这个 bug）。
* **交付纪律**：本还原**未经校对**，仅作 **TM/参考**。逐条置信度列已写入 CSV（`confidence` 列：
  `verified`=未改动英文原样 / `high`=全码高置信解码）。

---

## 5. 对本工程的直接价值

1. **TM**：2,275 条中文（去重 1,792 个英文串）可直接用于资料片翻译记忆：
   `work/analysis/js19/js19_tm_unique.csv`（EN→ZH 去重表）、`js19_lang_decoded.csv`（带 ID/置信度/备注）。
2. **字库**：用字 **881 个，全部**在本工程 `pair_of ∪ codes` 内 ⇒ **复用 JS19 译文不需要新画任何字形**，
   也不会撑爆本工程字集；这对 task-3 的字库方案是直接利好（无需为资料片预留新字位）。
3. **LANG 注入接口参考**（实测 JS19 的做法，供 text-engineer/Lead 参考）：
   * 条目**长度可自由变化**（它的条目长度差 −1..−13 字节很常见），引擎按组 count 解析，不依赖定长；
   * 重建后 LANG blob `used_end=128,062`（英文 177,433），**尾部 49,379 B 全部零填充**，blob 总长仍 = 177,441
     ⇒ 只要保持 `real` 不变、尾部补零即可；
   * LZO 仍是 **11 个子流、rlen = [16384×10, 13601]** 固定切块；压缩帧只占 57,963 B，**尾部 11,392 B 零填充**
     以保持 `stored = 69,355` 不变 ⇒ **原地替换、GR.IMG 条目字段一个都不改**；
   * 结论：LANG 注入可以在**不扩 IMG** 的前提下完成（只要新文本压缩后 ≤ 原槽，JS19 余量很大）。
4. **构建逻辑反例**：JS19 的 FONT.RES 尾部样式表有 off-by-22 损坏（count=15 但物理 16 条）、
   cave 删掉了 def NULL 兜底（其崩溃根因，见 `docs/ANALYSIS_ELF*.md`）——我们要**避免照抄**这两处；
   单字节码 rect 的 `u0` 漏 +2（右缘裁 2 px）也不要复刻。

---

## 6. 复现步骤（脚本都在 `tools/recovery/`，只读输入）

```bat
set PYTHONIOENCODING=utf-8
set PY=C:\Users\84363\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe

%PY% tools\recovery\js19_probe.py langstats          :: LANG 字节/组统计
%PY% tools\recovery\js19_atlas_introspect.py cells   :: 按 cave 公式打印逐格位图
%PY% tools\recovery\js19_glyph_calib.py              :: 压缩方式假设检验（OR 半采样）
%PY% tools\recovery\js19_ocr.py                      :: 全图 1446 格 OCR → js19_atlas_ocr.json
%PY% tools\recovery\js19_en_ref.py                   :: 英文原盘 LANG + 逐条对齐 → en_lang.json
%PY% tools\recovery\js19_fontres.py                  :: FONT.RES 3 face × 224 条 FT 记录
%PY% tools\recovery\js19_single_map.py               :: 单字节码 → rect → 格 OCR
%PY% tools\recovery\js19_final_map.py                :: 组装 js19_charset.json + 未译条目回归自证
%PY% tools\recovery\js19_decode_final.py             :: 解码全部条目 → js19_lang_decoded.csv
%PY% tools\recovery\js19_tm_stats.py                 :: TM 去重/用字/可疑条目 → js19_tm_*.csv/json
%PY% tools\recovery\js19_atlas_png.py                :: 带格线标注的图集预览 PNG
%PY% tools\recovery\js19_blob_probe.py               :: LANG blob/子流尺寸（注入接口参考）
%PY% tools\recovery\js19_chart_rel.py                :: JS19 字表 ↔ 本工程 charset 槽位对照
%PY% tools\recovery\js19_qa.py                       :: 交付物自检（CSV/json/统计/用字 全 PASS）
```

关键断言（脚本内已 assert/自检，可重复跑）：

* `js19_glyph_calib.py`：前 62 格中 61 格 OR 半采样 xor==0；
* `js19_final_map.py`：693 条未译条目回归 → 655 ==、38 条差异全部为「重音拉丁人名」；
* `js19_decode_final.py`：`unknown_chars == 0`，`low_conf == 0`。

## 7. 风险与边界

| 风险 | 说明 | 缓解 |
|---|---|---|
| 译文未经校对 | 抽样有 1 条语义偏差、1 条错译，半角标点混用 | 只作 TM；翻译组按 `confidence` 列分级采用，逐条校对 |
| 693 条未翻译 | 含 group 61（制作名单，393 条）等 | 本工程需自行翻译；JS19 没有可复用内容 |
| 未译条目里的 38 条重音人名 | JS19 显示成汉字（其 bug） | 我们注入时用本工程编码/ASCII，不复制该 bug |
| JS19 编码不可直接借用 | pair 表与本工程错位（§3.4），单字节码 0xAF..0xB9 是本工程没有的 | 只用它还原的**文本**，编码一律重映射到本工程 charset |
| 图集/FONT.RES 侧 | JS19 的 FONT.RES 尾部损坏、cave 无 NULL 兜底、rect u0 漏 +2 | 本任务只还原数据，不复用其构建逻辑；字库方案以 task-3 为准 |
| 低置信 OCR 格 | 74 格（文本未使用） | 已在 `js19_charset.json` 中保留 `low` 标记，未硬凑 |

## 8. 附录

### 8.1 产出文件（`work/analysis/js19/`）

| 文件 | 内容 |
|---|---|
| **`js19_charset.json`** | 图集几何 + 编码规则 + `pair`(813)/`single`(168) → char 全表（含 slot/rect/dist/conf/count） |
| **`js19_lang_decoded.csv`** | 2,971 条：`g,i,text_en,text_zh_js19,confidence,note,changed,len_en,len_zh,cjk_ratio` |
| **`js19_font_atlas_cells.png`** | 图集 2× 带格线/行号/区域标注 + 右侧统计 + 底部 24 格 OCR 对照 |
| `js19_atlas_ocr.json` | 1,446 格逐格 OCR 原始结果（char/dist/second/conf/ink/坐标） |
| `js19_tm_unique.csv` | 去重 EN→ZH（1,792 条）+ 来源 id + confidence |
| `js19_tm_stats.json` / `js19_tm_issues.csv` / `js19_tm_conflicts.csv` | TM 统计 / 可疑条目（16 条，均为品牌词保留）/ 同英不同译（3 组） |
| `js19_chars_needed.json` | 881 用字清单 + 出现次数 + 是否在本工程 charset 内 |
| `js19_quality_sample.csv` | 长度分层抽样 44 条（供翻译组话标） |
| `js19_ft_records.json` / `js19_single_codes.json` / `js19_single_map.json` | FONT.RES 记录 / 单字节码 rect / 单字节码 OCR |
| `js19_atlas_4x.png` / `js19_atlas_8bpp.png` / `js19_atlas_engine.png` | 原图集预览（8bpp 墨像素 / 放大） |
| `en_lang.json` / `lang_alignment.csv` | 英文原盘 LANG 参考 + 逐条对齐 |
| `js19_decode_stats.json` / `js19_tm_overlap.json` | 统计 |

### 8.2 ELF cave 常量与指令（引用 elf-analyst 的反汇编，全部已逐字复核）

| 块 | VA | 语义 |
|---|---|---|
| draw_advance | 0x1808A8 | `lbu v0,0xDD(sp); addu s5,s5,v0; j 0x219950`（步长 1/2） |
| decode | 0x1808C8 | gate `sltiu 0xA1` / `sltiu 0xAE`；trail `[0xA1,0xFF)`；写 `(lead<<8)\|trail` |
| charwidth | 0x180948 | slot+224；count=def+0x44（=FONT.RES fld[4]×fld[5]=224）；越界→16 |
| uv | 0x180A48 | slot=(lead−0xA1)*94+(trail−0xA1)；NCOL=62、CW=8、CH=16、Y0=2、SKIP_ROW=12、+3 |
| measure / wrap | 0x180B38 / 0x180BD8 | 宽度测量、折行（同 gate 0xAE） |

> 反汇编文本：`work/analysis/elf/js19_cave_pseudoasm.txt`（elf-analyst 产出，252 条）
> Game CRC：**3A320B22**（`python tools/analysis/elf_probe.py --elf-path work/analysis/js19/JS_ZH19_ELF_from_dump.bin crc`）

### 8.3 数据统计速查

* 图集：512×512 PSMT8，单 GIF 包，texel 只有 0(墨)/15(底)，墨 66,352 px。
* 网格：62 列 × 8×16，行 0..11 在 y=2..178，行 12..19 在 y=242..354（SKIP_ROWS=3 ⇒ y=194..242 空档），
  ASCII/单字节 FT 带在 y=370..450。
* LANG：11 个子流（rlen 16384×10+13601），展开 177,441 B，67 组 / 2,971 条；
  JS19 重建后 `used_end=128,062`，尾部 49,379 B 零填充。
