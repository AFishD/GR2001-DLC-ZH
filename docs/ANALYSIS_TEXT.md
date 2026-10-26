# ANALYSIS_TEXT —— 《幽灵行动：丛林风暴》PS2 (SLUS-20820) 文本资源分析

> 作者：text-engineer · 日期：2026-10-21 · 盘：`third_party/orig/ps2/[PS2] Tom Clancy's Ghost Recon - Jungle Storm (U).iso`
> sha256 `292f5a6a050e82e05efb5bf9fd5ce3bc12706a8ae57c78b729348a5c80fd0767`
> 本文所有数字均可由 `tools/dlc/dump_text.py` 复现（命令见 §14）。标注 **[实证]** 的是本次逐字节实测；
> 标注 **[推测]** 的是从文本内容/本体工程惯例推断、尚未用 ELF/实机闭环的结论。

---

## 0. 摘要（先看这里）

| 项 | 数字 | 口径 |
|---|---|---|
| 玩家可见文本资源 | **6 类 / 4,485 条单元** | LANG + SFXML 正文 + SFXML 标题 + MIS 字段 + ATR 人名 + EN_STRINGS.TXT |
| 需翻译单元 | **3,372 条**（其余 1,113 条为空/按本体惯例保留英文） | `work/analysis/text/tm_stats.json` |
| LANG | **67 组 / 2,971 条**（非空 2,897 / 空 74） / 文本 159,071 B | GR#576 EN_STRINGS.RES |
| SFXML | **98 条 `<text>`**（17 空 + 25 个 `<text/>` 自闭合） + **174 个标题** | GR#3101，blob 133,359 B |
| MIS | **45 个任务** / 7 类显示字段 / 26,203 B；**95% 字段与 LANG 同文** | GR#341..#389 |
| ATR | 766 个 `<ActorName>`（279 个不同人名）；**人名按本体惯例保留英文**，仅 8 个兵种名可译 | GR#626.. 等 |
| EN_STRINGS.TXT | 228 对 token→显示名；本体成品盘只译了 **10 个**（物品/套件名） | GR#577 |
| 翻译记忆可复用 | **exact 1,599 + norm 156 + fuzzy_high 128 = 1,883 条（55.8%）**；严格复用 52.1% | 本体 2,638 条语料 |
| 用字 | TM 复用文本用字 **1,894 个 / 40,441 次，全部在本体字符集内**；新增字统计估计 **278 个**（容量 346） | `needed_chars.json` |
| 注入 | LANG/SFXML 重压后 **stored 净减**（-14,278 / -7,088 B）；MIS 因我们的 LZO 编码器弱约 2%，16K 帧会 +12.7 KB，但 `rebuild.py` 重排即可，总 GR.IMG 仍净减 | `inject_report.json` |

**结论**：文本层没有「不可解」的硬阻塞。LANG/SFXML 体量足以覆盖 95% 的 MIS 文本；真正的成本在
① 1,487 条无 TM 的新增文本（约 32,000 汉字）；② 字库可能要补画 ~20 个已点名缺字、统计上 ~278 个新字
（< 346 容量，够用）；③ MIS payload 变大靠 `rebuild.py` 重排消化，不需要手写偏移。

---

## 1. 环境与方法

* 环境：`C:\Users\84363\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe`；
  核心库 `tools/dlc/dlclib.py`（Lead 所有，未改动）+ 本工程新增 `tools/dlc/textlib.py` / `dump_text.py` / `inject_text.py`。
* 只读原盘（`mmap` 只读打开）。所有解析结果可重跑。
* 证据来源：
  * 原盘逐字节解析（LANG/SFXML/MIS/ATR/TXT/XML/LZO 分块全盘扫描）；
  * 本体英文盘 `Ghost Recon (USA).iso`（MENU.IMG#25 LANG / #283 SFXML / #30 EN_STRINGS.TXT）；
  * 本体译文资产 `assets/text/{merge,enrich}/*.csv`（GR_ZH141/140）；
  * 本体成品中文盘 `work/builds/FINAL/Tom Clancy's Ghost Recon (ZH_CN).iso`（只读，用于提取 MIS 中文名与 TXT 已译值做 TM）。

---

## 2. 资源结构总览

| 资源 | GR# | 盘上形态 | 解压后 | 说明 |
|---|---|---|---|---|
| EN_STRINGS.RES | 576 | LZO，11 子流（10×16,384 + 13,601） | 177,441 B | 语言表；stored 69,355 B；slack **5 B** |
| EN_SPECIAL_FEATURE.XML | 3101 | LZO | 133,359 B | 特别收录；stored 55,639 B；slack **9 B** |
| *.MIS ×45 | 341..389 等 | LZO，每条 1–9 子流 | 2,641,606 B 合计 | XML 任务定义；stored 合计 670,806 B；slack 多为 0–14 B |
| *.ATR ×766 | 626.. | **raw** XML | 单条 ~400–900 B | 人物定义（ActorName/ClassName/武器/属性） |
| EN_STRINGS.TXT | 577 | LZO | 7,092 B | token→显示名表（228 对）；stored 2,822 B；slack 10 B |
| CAMPAIGN.XML | 349 | LZO | 1,486 B | 只有 `.mis`/`.atr` 文件名 → 无玩家文本 |
| OPTIONS.XML | 3108 | LZO | 3,737 B | 设置项/数值；`<ChatMsg text="">` 全为空串 → 无静态玩家文本 |
| UNLOCKED_HEROES.XML / UNLOCKED_MISSIONS.XML | 3109/3110 | raw | 397 / 598 B | 只有 `.atr`/`.mis` 文件名 → 无玩家文本 |
| BEST_TIMES.XML / CMBTMODL.XML | 3097/1655 | raw | 14 B / 823 B | 空文件 / 数值 → 无玩家文本 |
| 其它语言副本 | 574/578/581/584（STRINGS.RES）、3100/3102/3104/3107（SPECIAL_FEATURE） | LZO | — | DE/ES/FR/IT 版；**美版英文模式只读 EN 副本**，汉化不改其它语言（见 §7） |

LZO 子流规则 **[实证，全盘 3,111 条扫描]**：
`{u32 clen}{u32 rlen}{payload}` 顺序拼接；`real = Σrlen`；**`clen == rlen` 表示该块原文直存**
（107 个条目出现，如 `CP03_PRISON.MIS` 尾块 969 B 是 ASCII XML 而非 LZO）。`textlib.parse_chunks` 已按此实现；
`dlclib.lzo_subs` 由 Lead 同步修复。

---

## 3. LANG（EN_STRINGS.RES，GR#576）

### 3.1 结构与统计 **[实证]**

```
{u32 ngroups=67}
组1:                     {u32 count} + count×({u32 len}{data}{u16 attr})
组k(k≥2): {u32 0}        {u32 count} + count×({u32 len}{data}{u16 attr})
```

| 项 | 值 |
|---|---|
| 组数 / 条数 | **67 / 2,971**（非空 2,897、空 74） |
| 文本字节 | **159,071 B** |
| blob / 有效区 / 尾部 | 177,441 / 177,433 / 8 B 全 0 填充 |
| 压缩后 stored | 69,355 B（11 子流：10×16,384 + 13,601） |
| attr | **2,971 条全部 0x0000**（重建时原样保留即可） |
| 条目长度 | 平均 53.54 B，最长 1,963 B（DNAS 条款） |
| 同文重复 | 249 组重复，重复多出 **585 条**（翻译可去重/保证一致） |
| 控制字符 | **0 个** C0/DEL —— 换行不是真 `\r\n`，而是富文本标记（见下） |
| 非 ASCII | 仅 104 字节 / 12 种，全部是 **Windows-1252** 可打印字符 |
| 富文本标记 | `{p}`×136、`{br}`×5；无 `{{BTN:...}}`（本作 LANG 不用手柄图标码） |

**cp1252 字节映射 [实证]**（`decode_en` 口径，与本体工程 `EN_CP1252` 一致并补全）：
`0xA9→©×1`、`0xAE→®×48`、`0xC9→É×1`、`0xE7→ç×5`、`0xE8→è×2`、`0xE9→é×34`、`0xEB→ë×2`、
`0xEE→î×3`、`0xF1→ñ×2`、`0xF3→ó×1`、`0xF4→ô×1`、`0xF6→ö×4`。
高发区是 `/®` 商标与 `Français/Español` 等语言名。**没有** 0xB1/0xB5 图标码、没有未定义 cp1252 字节。

### 3.2 组语义表（G001..G067，供翻译组参考）

> 组语义由首条文本 + 组内模式推断 **[推测，未做 ELF 字符串 ID 交叉验证]**，但分组边界是实测的。
> `id` 口径：`G%03d.I%03d` = 1 起组号 + 0 起组内序（与本体资产 CSV 一致）。**空的 74 条不要译，也不要在译文中新增内容。**

| 组 | 条数 | 内容 | 翻译注意 |
|---|---|---|---|
| G001 | 5 | MP 模式通用：Victory!/Defeat!/Firefight/规则句 | 术语统一（见 §8.4） |
| G002 | 6 | 同上（Recon/时间到判负） | |
| G003 | 10 | Mouse Hunt（猫鼠）规则/胜负 | |
| G004 | 6 | Last Man Standing | |
| G005 | 6 | Sharpshooter | |
| G006 | 6 | Firefight（含 `Enemy : ` 计数前缀，**保留尾空格**） | |
| G007 | 5 | Recon（撤离） | |
| G008 | 8 | King of the Hill（You are now king） | |
| G009 | 6 | Last Man Standing（队伍版） | |
| G010 | 8 | Hostage / 人质事件 | |
| G011 | 10 | 占领/防守模式 | |
| G012–G018 | 49×7 | **训练关帮助正文 7 份重复**（M01..M07 各一份；射击/爆破/机枪/障碍/夜视/指挥/ROE 教程） | 7 组文本几乎相同，翻译一次后按 TM 批量填；核对个别 map 差异 |
| G019–G026 | 19/15/16/15/19/20/20/18 | **Jungle Storm 战役 C01–C08**：`Mission Complete`、MapName、`Cxx - 代号`、Location、Date、Time、简报正文、目标列表、目标名 | 任务名/简报量最大的一段（8 条约 1,200 B 简报） |
| G027–G033 | 21/15/15/20/24/18/17 | 战役 J01–J08 + 中间任务消息（“Ordonez has been killed”等） | 含大量动态提示句 |
| G034–G038 | 7×5 | MP01–MP05 地图元数据（MapName/Name/Location/Date/Time） | 日期/时间点 → 建议 `2010年3月20日`/`06:30` |
| G039 | 25 | U05 战役目标/完成提示 | |
| G040–G044 | 7×5 | CP01–CP05（Hunting Lodge/Island/Prison/Island Village/Market）元数据 | |
| G045–G047 | 7/8/12 | MP 基地占领/倒计时/控制点提示 | |
| G048–G052 | 13/16/17/19/18 | TAC01–TAC05 战术关（Shooting/Rescue/Demolition/AntiVehicle/Defend） | |
| G053–G057 | 7×5 | DP01–DP05（Stronghold/Farm Day/Creekbed/Wilderness/Ravine）元数据 | |
| **G058** | **1,324** | **通用 UI 大组**：菜单/HUD/兵种名（Rifleman/Sniper/Support/Demolition…）/训练提示/DNAS 法律长文/账号创建/多人大厅/存档提示/计数前缀 | 翻译量最大（含 7 条空）；法律长文可整段保留边界但必须译；`%`/`{…}` 占位符原样保留 |
| G059 | 41 | 系统提示（DELETE SAVE / DEFAULT JOIN PASSWORD / RESTART…） | |
| G060 | 1 | `mainmenu`（内部 key） | **不译** |
| G061 | 53 | 按键动作名（Quit/Move Forward/Peek Left…） | 与 EN_STRINGS.TXT `//actions` 对应，术语统一 |
| G062 | 393 | 制作人员名单（`<title>`/`<br>` 标记） | 人名按惯例保留英文；职称可译；`<title>`/`<br>` 标记必须保留 |
| G063 | 24 | `01.rsb`…（截图文件名） | **不译**（内部文件名） |
| G064 | 10 | `sf_DS1_08.rsb`…（截图文件名） | **不译** |
| G065 | 145 | 选项菜单标签/说明（Options/Pad Look Reverse Z/Gameplay…） | |
| G066 | 42 | 军衔（No Rank/Private/PVT…） | 与 UI 军衔缩写统一 |
| G067 | 7 | `i_main1.wav`…（音频文件名） | **不译** |

`dump_text.py` 的 `classify_lang_keep()` 会自动给文件名/格式串/纯数字打 `keep:` 标记；
`lang_source.csv` 的 `flags` 列可见，翻译组**遇到 `keep:` 的行跳过**。LANG 的 keep 共 120 条（含 74 条空条目）。

---

## 4. SFXML（EN_SPECIAL_FEATURE.XML，GR#3101）

### 4.1 结构 **[实证]**

```
<SpecialFeatures>
  <studio name="…" pic="…">            ×10
    <group name="…" pic="…" unlock="…"> ×41
      <picname [unlock="…"]>…</picname> ×252（内部图片名，不译）
      <item name="…" pic="…" unlock="…"> ×123   ← 显示标题
        <text>…</text>           ×98（正文；另有 25 个 <text/> 自闭合空元素）
        <moviename>…</moviename> ×27（视频内部名，不译）
        <soundname>…</soundname> ×60（音频内部名，不译）
```

* blob 133,359 B；stored 55,639 B；slack **9 B**。
* `<text>` 正文合计 **96,438 B**；17 条是 `<text></text>` 空正文（不要新增翻译）。
* 显示文本 = 10 studio + 41 group + 123 item 标题 + 98 正文 = **272 个字符串**。
* 富文本：`{p}`×33、`{br}`×28（在 `<text>` 正文中）；无真 `\r\n` 字节。

### 4.2 与本体（Ghost Recon 2001）对比 **[实证]**

| 项 | 本体 | 资料片 | 差异 |
|---|---|---|---|
| 资源 | MENU.IMG#283 | GR#3101 | 容器不同 |
| blob | 116,430 B | 133,359 B | +16,929 B |
| `<text>` | 69 | **98** | +29（其中 42 条正文全新，56 条英文与本体相同） |
| `<item>` | 94 | **123** | +29（新武器/新专辑） |
| studio / group | 10 / 41 | 10 / 41 | 同名同数 |
| 标题（A 类） | 145 | **174** | 10+41+123；**79 个 item 名与本体同名**，新增 44 个（Music 1–12、新枪名等） |

**TM**：SFXML 正文 exact 39 / fuzzy_high 14 / 其余 28 条需新译；标题 exact 133 / 需新译 41。
（本体标题译文在 `assets/text/merge/GR_ZH141_text_sf_titles.csv`，id `A0001..` 与本文口径一致。）

---

## 5. MIS（45 个任务定义）

### 5.1 结构与统计 **[实证]**

* 位置：GR#341..#389（45 个 `.MIS`）；条目 = LZO 分块帧，解压后是纯文本 XML（`<MissionFile>`）。
* 分块数 1–9；**CP03_PRISON.MIS 第二个子流 `clen==rlen`（969 B 原样 XML）**——解析必须支持。
* 45 个合计 real 2,641,606 B / stored 670,806 B。

| 玩家可见字段 | 条数 | 说明 |
|---|---|---|
| `<Name>` | 45 | 任务标题（如 `C01 - Watchful Yeoman`），标题栏直接显示 |
| `<MapName>` | 45 | 地图名（如 `C01 Plantation`） |
| `<LocationText>` | 45 | 地点（如 `Punta Tabacal`） |
| `<DateText>` | 45 | 日期（如 `March 20, 2010`）→ 建议本地化 |
| `<TimeText>` | 45 | 时间（如 `06:30`）→ 保持 24h |
| `<BriefingText>` | 21 | 简报正文（含 `{p}` 段落标记，无真换行） |
| `<RecommendedGameTypes>` | 2 | `16 to 36`（玩家数区间） |
| 非显示 | — | `<MapNameId>/<NameId>/<BriefingId>/<Points>/<ScriptCompiled>` 等内部值不译 |

显示字段合计 **26,203 B**。

### 5.2 ★ MIS 与 LANG 的同文关系（翻译提效关键）**[实证]**

| 字段 | 总数 | 与 DLC LANG 某条**字节完全相同** | 结论 |
|---|---|---|---|
| Name | 45 | **43** | 译 LANG 即自动覆盖；仅 `G01 - Volcano`、`U04 - Murder` 需 MIS 单独译 |
| MapName | 45 | **41** | 缺 `G01 Volcano`、`J01 Totem Ground`、`J07 Whisper Shadow`、`U04 Murder` |
| LocationText | 45 | **45** | 全部走 LANG |
| DateText | 45 | **43** | 缺 G01/U04 的 `April 10, 2009` |
| TimeText | 45 | **45** | 全部走 LANG |
| BriefingText | 21 | **16** | 5 条简报不在 LANG（C02/C07/G03/TAC02/U03）需单独译 |
| RecommendedGameTypes | 2 | 0 | `16 to 36` 直接译 |

`mis_source.csv` 的 `lang_ref` 列已逐条标出对应 LANG id；`inject_text.py` 也会分别接受 `MIS:文件:字段` 与
`文件#字段` 两种 id。**建议翻译顺序：先译 LANG → 用 `lang_ref` 回填 MIS → 只补 5+2+4+2 个例外。**

**与本体 40 个 MIS 的结构对照**：本体 46 个 MIS（含 MP01–05/TRAINING_MP）字段集合与资料片同构（多 `Snow/DemoRecommend` 等少数可选字段）；
资料片去掉了 `Snow` 等，新增 `RecommendedGameTypes`。共享地图名（T01–T07、TAC01–05、DP01–05、MP01–05）可从本体 TM 复用
（DLC 的 `<Name>` 多了 ` - ` 连接符，`norm` 匹配命中；本体成品盘只译了 40 个 MIS 的 Name/MapName、**没有译简报正文**，
所以简报只能靠 DLC LANG 的 16 条 + 5 条新译）。

---

## 6. ATR / EN_STRINGS.TXT / 其它 XML

### 6.1 ATR（766 个，raw XML）**[实证]**

* 字段：`ActorName`(766) / `ClassName` / `FolderName` / `ModelFace` / `Weapon` / 属性数值…
* `ActorName`：766 条、**279 个不同人名**（如 Kareem Armstrong、Jack Stone、Susan Grey）。
* 本体惯例：本体成品中文盘 ATR **逐字节未改**（对比 1193 个同名 ATR 只有 8 个 `ActorName` 变化，且是
  `@MP_atr_rif → Rifleman` 这类占位符替换）⇒ **资料片人名同样建议保留英文**（不占中文字库；也避免 `a-z`
  小写在本体 16px 字库缺字形的问题）。
* 例外：10 条（8 类）MP 兵种显示名（`Rifleman/Demolition/Support/Sniper` + `Cuban …`）可译，均已标 `flags=` 空；
  其余 756 条标 `keep_english`。

### 6.2 EN_STRINGS.TXT（GR#577）**[实证]**

* 228 对 `"TOKEN" "显示名"`，5 段：`// weapons and items`、`// actions`、`// actors`、`// keys`、`// Kit restriction files`。
* **这是活资源**：本体成品中文盘 MENU.IMG#30 被改写过（10 个 value 译成中文：Extra Ammo/Binoculars/Sensor/
  Claymore/Demo Charge + 7 个 Kit restriction 名称）。⇒ 说明引擎/构筑链会读它。
* 但本体**没有译武器名与按键名**（M4/MP5/AK47/key_a… 保留英文）⇒ 资料片按同一策略：
  **武器名/按键名/actor 占位符保留英文**，只译物品名与套件限制名（`strings_txt_source.csv` 已用 `flags` 标注）。
* token 是 `WPN_*`/`ITM_*`/`key_*` 等内部名，**绝不可把 token 列翻译/改动**。

### 6.3 其它 XML：结论 = 无玩家可见静态文本 **[实证]**

| 文件 | 结论 |
|---|---|
| CAMPAIGN.XML | 只有 `.mis` 文件名 + `.atr` 英雄文件名（16 Mission / 11 Hero） |
| UNLOCKED_HEROES.XML / UNLOCKED_MISSIONS.XML | 只有 11 个 `.atr` / 15 个 `.mis` 文件名 |
| OPTIONS.XML | 设置项与数值；`<ChatMsg text="">` ×N 默认全空串 |
| BEST_TIMES.XML | `<BestTimes/>` 空文件 |
| CMBTMODL.XML | 弹道系数等纯数值 |

`other_xml_audit.csv` 是逐文件审计表（含 verdict）。**这些文件不需要译**。

### 6.4 多语言副本 **[实证]**

* `DE/EN/ES/FR/IT_STRINGS.RES` 五份 LANG + `DE/EN/ES/FR/IT_SPECIAL_FEATURE.XML` 五份。
* 美版（SLUS-20820）英文模式读 EN 副本；资料片没有中文选项。
* **汉化策略**：只改 EN 副本（576 / 3101）；其它语言副本保持原样（若引擎按系统语言选文件，
  NTSC-U 默认英文，风险低）。**[推测]** 语言选择逻辑未在 ELF 侧闭环，列为 TBD。

---

## 7. 翻译资产与翻译记忆（TM）

### 7.1 语料来源

| 来源 | 条数 | 用途 |
|---|---|---|
| 本体英文盘 LANG（MENU#25） | 2,232 | 英文原句 |
| 本体译文资产 `GR_ZH141_text_short/long/long_nowrap` | 2,192 条 LANG 中文 | 中文译文（按 `LANG:G###.I###` 对齐） |
| 本体英文盘 SFXML（MENU#283） | 69 | 英文原句 |
| 本体 SFXML 正文译文（资产） | 58+11 条 | 中文 |
| 本体 SFXML 标题资产 `GR_ZH141_text_sf_titles.csv` | 136（en+zh） | 10 studio + 41 group + 94 item 旧标题 |
| 本体成品盘 EN_STRINGS.TXT 已译值 | 10 | 物品/套件名 |
| 本体成品盘 MIS Name/MapName 中文 | 242 | 共享地图/任务名 |

→ 语料 **2,638 条**（`work/analysis/text/tm_context.json` 可审计）。

### 7.2 匹配规则

1. **exact**：解码后引擎文本逐字节相同；
2. **norm**：大小写/空白/引号（’→'）/破折号归一后相同；
3. **fuzzy**：bigram 倒排剪枝 + `difflib.SequenceMatcher ≥0.85`；≥0.92 记 `fuzzy_high`（可直接预填），
   0.85–0.92 记 `fuzzy_low`（需人工复核）。
4. 同资源优先（LANG 优先 LANG，MIS 优先 LANG，标题优先标题）。

### 7.3 复用率 **[实证，`tm_stats.json` / `tm_matches.csv`]**

| 资源 | 可译单元 | exact | norm | fuzzy_high | fuzzy_low | none | 严格复用率 |
|---|---|---|---|---|---|---|---|
| LANG | 2,851 | 1,311 | 155 | 105 | 39 | 1,241 | 51.4% |
| SFXML 正文 | 81 | 39 | 0 | 14 | 0 | 28 | 48.1% |
| SFXML 标题 | 174 | 133 | 0 | 0 | 0 | 41 | 76.4% |
| MIS 字段 | 248 | 103 | 1 | 9 | 13 | 122 | 41.9% |
| ATR 兵种名 | 10 | 6 | 0 | 0 | 0 | 4 | 60% |
| STRINGS_TXT | 8 | 7 | 0 | 0 | 0 | 1 | 87.5% |
| **合计** | **3,372** | **1,599** | **156** | **128** | **52** | **1,437** | **52.05%** |

* 含 `fuzzy_high` 的可直接预填率 = **55.84%**（1,883 条）；`fuzzy_low` 52 条需审；
* 无 TM 的 1,437 条 ≈ **32,241 汉字**（按「已匹配语料 中文 40,441 字 / 英文 131,185 字符 = **0.308 字/英文字符**」换算）；
  预计全文本 ~72,700 汉字（本体语料 50,961 汉字的 1.43 倍）。
* 复用中文 40,441 字；`text_en` 总可见字符 235,829（不含空格）。
* 工作文件：
  * `tm_matches.csv`：每条 DLC 文本的匹配类型/来源 id/基线英文/可复用中文（可直接做审校底稿）；
  * `translation_worklist.csv`：只含 3,372 可译单元，`status=tm_*` 的行已预填中文、`todo` 待译；
  * `tm_stats.json`：全部统计；`tm_context.json`：语料快照。

### 7.4 重复文本（翻译一致性）

LANG 内部 **249 组重复 / 585 条冗余**（最高频：`<br>`×45、`Mission Complete`×21、`Excellent!`×21、`Good Job!`×15…）。
这些重复串已由 TM 归一化（翻译一次即全部覆盖），但**新译部分**仍建议保持同一译法；`lang_source.csv` 的
`flags=dupN` 与 `note` 已标出同文 id。

### 7.5 术语统一建议（判据：本体译法 + 本作语境）

| en | zh（沿用本体/建议） | 证据 |
|---|---|---|
| Ghost Recon | 幽灵行动 | 本体 SFXML 标题「幽灵行动®任务1」 |
| Victory! / Defeat! | 胜利！/ 失败！ | 本体译文资产 |
| Mission Complete / Mission Failed | 任务完成 / 任务失败 | LANG |
| Rifleman / Demolitions / Support / Sniper | 步枪手 / 爆破兵 / 支援 / 狙击手 | LANG G058 兵种名（本体） |
| Recon / Assault / Defend | 侦察 / 突击 / 防御 | LANG MP 规则 |
| extraction / waypoint | 撤离点 / 航点 | LANG 提示 |
| fireteam / platoon | 火力小组 / 排 | LANG 训练 |
| Campaign / Multiplayer / Options / Credits | 战役 / 多人模式 / 选项 / 制作人员 | 本体 LANG |
| Specialist | 专家 | 本体 SFXML「专家1/2」 |
| Ghost / hostile / civilian | 幽灵 / 敌人 / 平民 | 本体惯例 |

> 全量对照见 `work/analysis/text/tm_matches.csv`（列 `reusable_zh`）。

---

## 8. 用字清单与字库容量

### 8.1 结论 **[实证]**

* TM 复用的 40,441 个汉字中，**不同字 1,894 个，全部在本体 2,403 字符集内**（`known_all_in_charset=true`）。
  即：翻译只要沿用本体语料用字，**不需要画任何新字**。
* 统计外推：新增 32,241 汉字会带来约 **278 个新字**（本体语料随机抽 70% 篇幅的去重字数差 → 每千字边际新字率 8.63
  → 乘新增篇幅）。这是「新内容按本体同款文风/词表翻译」的期望值。
* 已点名的新字候选（**实测不在本体字符集**）：
  * tier1 = 20 个（由本资料片真实关键词的建议译名得出）：`丛 圭 枢 泰 洋 港 炉 熔 狩 疗 礁 耕 蒸 蓬 蛛 蜒 蜿 蟒 赎 锤`；
    对应术语如 丛林/卡马圭/铁路枢纽/泰坦之箭/海洋熔炉/狩猎小屋/医疗/卢卡斯礁/自耕农/蒸汽之刃/蓬塔/银蛛/蜿蜒/巨蟒/救赎/海洋之锤。
  * tier2 = 28 个（常用音译汉字池中缺字，专名音译备用）：见 `assets/text/source/needed_chars_font.json`。
  * 合计 48 个 → 交字体工程师（其口径：可用新字容量 **346**）。
* 容量判断：`recommended_new_chars=278 ≤ 346`，**够用但不宽裕**；另有字符集里「已画但本体正文没用到的字」82 个可先复用。
  如果翻译大量使用生僻专名，需要提前告知字体端走「图集加高 +64 槽」方案。

### 8.2 文件

* `work/analysis/text/needed_chars.json`：完整清单（known 1,894 字含频次/来源资源；estimated 1,987 字频次估算；
  candidates 20 + 统计字段）。
* `assets/text/source/needed_chars_font.json`（同时拷到 work）：字体工程师约定格式
  `{"total":48,"chars":[{char,count,evidence,tier,priority}], "statistical_estimate":278, "overflow_note":…}`。
* 字符集口径差异：本文「空 PUA 槽 334」按 `charset_compiled_zh16.json` 的 PUA 键统计；
  字体工程师实测「可补画 346 格」= 298 PUA + 50 未映射空槽 − 2 残墨 **（以其为准）**。

---

## 9. 编码 / 富文本规则（翻译必读）

| 规则 | 说明 |
|---|---|
| `{p}` / `{br}` | 引擎富文本：`{p}`=分段（空一行）、`{br}`=硬换行。**本盘所有文本资源都是标记，没有真 CR/LF**（LANG 0 个、SFXML 0 个、MIS 0 个）。翻译要换行请写 `{p}`/`{br}`；若在 CSV 里写了真换行（`\r\n` 字面转义），`inject_text.py` 会自动转成 `{br}`/`{p}`（1 换行→`{br}`、空行→`{p}`）。 |
| `{{BTN:E0B1}}` / `{{BTN:E0B5}}` | 手柄按键图标（△/✕）；引擎直接画图、不吃字库。**数量/位置必须与原条一致**（`inject_text` 校验）。本作 LANG/SFXML/MIS 实测没有该标记，但译文不要新增。 |
| 0xFF 禁忌 | 字符集把「著」编成单字节 `0xFF`，XML 词法器用有符号 -1 判 EOF ⇒ **SFXML/MIS/ATR 的译文出现 0xFF 会被截断**。`inject_text` 对 XML 类资源报 error；LANG 报 warning。遇到「著」换词（显著→明显）。 |
| 控制字符 | 译文禁止 `\x00`、`\x0b` 等 C0/DEL（`inject_text` 会拦）。 |
| ASCII 大小写 | 本体 16px 中文字库里 `a-z` 等小写/`^_\`|~` **没有字形**（本体工程已知限制）。因此：ATR 人名保留英文时也建议**全大写或保持原文**（引擎按英文字库画？——**TBD**：资料片字库由字体工程师方案决定）；中文译文里的英文缩写（M4/AK47/C4）都是大写+数字，安全。 |
| CSV 转义 | 本工程 CSV 一律 UTF-8 with BOM / CRLF；正文列的真 CR/LF/TAB 写成字面 `\r` `\n` `\t`（单行单元格）。`text_en` 列只读。 |
| id 列 | `LANG:G019.I002` / `SFXML:T0010` / `SFXML_TITLE:A0001` / `MIS:文件#字段` / `ATR:文件#ActorName` / `TXT:token`；**不要改 id**，注入按 id 找位置。 |

---

## 10. 文本注入约束分析（关键）

### 10.1 各资源 slack（stored 的物理余量）**[实证]**

| 资源 | stored | 下一条 off − (off+stored) | 结论 |
|---|---|---|---|
| GR#576 LANG | 69,355 | **5 B** | 重压后必须 ≤ 69,360，否则原位写不下 |
| GR#3101 SFXML | 55,639 | **9 B** | 同上 |
| 45 个 MIS | 670,806 合计 | **0–14 B**（多为 0–8） | 任何增长都需重排 |
| EN_STRINGS.TXT | 2,822 | 10 B | |
| ATR（raw） | =real | 同 MIS（3–10 B） | 译文变短才行；人名保留英文则不动 |

### 10.2 实际重压预测（`inject_report.json` + `inject_bounds.json`）**[实证]**

用当前 merged 译文（2,954 条）构建 payload（`--check-only`）：

| 资源 | 原 real → 新 real | 原 stored → 新 stored（我们的编码器） | 变化 |
|---|---|---|---|
| LANG | 177,441 → **115,708** | 69,355 → **55,077**（估算） | **-14,278 B** |
| SFXML | 133,359 → **95,438** | 55,639 → **48,551** | **-7,088 B** |
| MIS ×45 | 2,641,606 → 2,641,xxx | 670,806 → 约 **683,5xx** | **+12.7 KB**（LZO 编码器差异，见下） |
| 合计 | — | — | **stored 净 −8,629 B** |

> 具体值以 `work/analysis/text/inject_report.json → layout` 为准（每次译文变化会重算）。

**为什么 MIS 会变大**：本工程 `dlclib.lzo_pack`（`tools/lib/lzo1x_c.py`）比原盘压缩器弱约 **2%**：
同数据重压测试——LANG +2,465 B、SFXML +1,988 B、MIS-sub0 合计 **+5,432 B**（每块 +92..164 B）。
LANG/SFXML 因为中文短、压缩后仍大幅变小；MIS 的显示文本占比小，压缩差就是净增长。
**缓解**：`tools/dlc/inject_text.py --translations …`（实际注入）：
* 方案 A（推荐、当前）：payload 交给 `rebuild.py`，它按 16,384 B 分块重压并**重排整个 GR.IMG 条目偏移/条目表/根目录大小**，
  因此变大的条目不会撞到下一条；ISO 尺寸按需增长（原盘 1.17 GB，DVD5 余量充足）。
* 方案 B（已验证压缩率、未定引擎兼容性 **[推测]**）：MIS 用 64 KB 块或整条 1 帧重压，16K 帧的"24/45 条超预算"会变成
  **0/45 超预算**（总 Δ 分别 −11,966 / −15,444 B）。但引擎解压器是否接受 `rlen > 16,384` 的帧**未验证**，
  除非 ELF 侧确认缓冲区大小，否则不要用。
* 单条 MIS 只在 sub0（首 16,384 B 块）有显示字段；`inject_text` 校验过所有字段都不跨块。

### 10.3 注入接口约定 **[实证，已实现]**

```python
from tools.dlc.inject_text import build_replacements
blob_repl, report = build_replacements(
    iso_path,                       # 英文原盘
    [translated_csv, ...],          # 最终译文表（路径列表；resource,id,text_zh[,source]）
    allow_marker_drift=True,        # build 中间盘：标记漂移只告警（--strict 时必须 False）
    allow_missing_chars=True,       # 中间盘：缺字用 '?' 占位并告警（--strict 时必须 False）
    strict=False)
# blob_repl: {条目号(int): 新 payload blob(bytes)} → 直接喂 rebuild.build_img(..., blob_repl=...)
# report['payload_index']: [{entry_idx,name,blob_len}]（build.py 打印用）
```

命令行（Lead 的测试命令，已跑通 exit 0 / 结论 OK）：

```powershell
python tools\dlc\inject_text.py `
  --iso "third_party\orig\ps2\[PS2] Tom Clancy's Ghost Recon - Jungle Storm (U).iso" `
  --translations work\translation\merged\translations_test.csv `
  --check-only --allow-marker-drift
# --strict = 最终构建：缺字/标记漂移任何一条都失败；--out-dir 才写 <idx>_<name>.blob + replacements.json
```

### 10.4 注入前自动校验（全部写进 report）**[实证]**

1. **基盘指纹**：被抽 814 个条目的 blob sha256 与 `assets/text/source/text_source.json` 比对（本次 814/814 通过）；
2. **LANG 结构**：67 组 / 2,971 条 / (g,i) 序列 / 每组 count 重建后完全一致；attr 2 B 原样保留；
3. **逐条编码**：译文能按本体字符集编码成字节（缺字逐字列出，可 `allow_missing_chars` 降级）；
4. **往返**：encode→decode 与译文一致（`{{BTN:XXXX}}` 归一化后比较）；
5. **控制字符 / 0xFF**：见 §9；
6. **富文本标记计数**：`{p}/{br}/{{BTN:…}}` 与原条相等（`--allow-marker-drift tm` 只放过 TM 行）；
7. **未知 id / 重复 id / 空值**：逐条报告（未知 id = 译文表里有、源清单没有，通常是 id 写错）。

### 10.5 其它资源

* **ATR**：raw payload，`real==stored`；译名比原名短 → 直接替换；若保留英文则完全不动。
* **EN_STRINGS.TXT**：LZO；译文值一般变短；若编译链不读它，也可完全不改（本体惯例只译 10 条）。
* **XML（CAMPAIGN 等）**：无玩家文本，不需 replace。
* **多语言副本**：不动。

---

## 11. 产出清单

### assets/text/source/（翻译/注入用，git 跟踪）

| 文件 | 内容 |
|---|---|
| `text_source.json` | ★ **机器可读唯一真源**（schema `grjs-text-src/1`）：4,485 items（含原字节 hex / blob_off / blob_len）+ 814 entries（blob sha256） |
| `entries_sha256.json` | 条目指纹清单（注入前核对基盘） |
| `lang_source.csv` | 2,971 条 LANG（key,group,text_en,text_zh,flags,byte_len_en,non_ascii,notes） |
| `sfxml_text_source.csv` / `sfxml_titles_source.csv` | 98 条正文 / 174 个标题 |
| `mis_source.csv` | 248 个 MIS 字段（含 `lang_ref` 同文 LANG id） |
| `atr_source.csv` | 766 个 ActorName（`keep_english` 标注） |
| `strings_txt_source.csv` | 228 对 token→显示名 |
| `other_xml_audit.csv` | 其它 XML 审计（无玩家文本） |
| `translation_master.csv` | 扁平总表（key,text_en,text_zh,notes），给翻译工具/人 |
| `source_stats.json` / `README.md` | 统计 / 说明 |
| `needed_chars_font.json` | 给字体工程师的新字保守全集 |

### work/analysis/text/（大产物，gitignored）

`tm_matches.csv`、`tm_stats.json`、`tm_context.json`、`translation_worklist.csv`、`needed_chars.json`、
`needed_chars_font.json`、`inject_bounds.json`、`inject_report.json`、`source_stats.json`、`*.log`。

### tools/dlc/

`textlib.py`（解析/编码/TM/字频公共库）、`dump_text.py`（dump/tm/chars/plan/all/audit）、
`inject_text.py`（译文 → payload + 校验，供 rebuild.py）。

---

## 12. 风险与 TBD

| # | 风险 | 等级 | 现状 / 处理 |
|---|---|---|---|
| 1 | **MIS payload 变大**（我们的 LZO 编码器比原盘弱 2%，16K 帧 +12.7 KB） | 中 | 已由 `rebuild.py` 全盘重排解决；`inject_report.layout` 每次可核对。若重建后 ISO 尺寸/Game CRC 有要求（CRC 只由 ELF 决定，不受影响） |
| 2 | 引擎是否接受 `rlen > 16,384` 的解压帧（方案 B 的提前量） | 待验证 | 未采用；已由构造链 **58 条 payload（全量译文）** 的 16K 帧路径验证可用 |
| 3 | LANG 组语义表是**内容推断**，未与 ELF 字符串 ID 交叉验证 | 低 | 对翻译无影响；若做逐组 UI 验收，可能有个别组语义需订正 |
| 4 | 5 条 MIS 简报 + 2 个任务名/4 个地图名/2 个日期不在 LANG | 低 | 已在 `mis_source.csv` 标出，需 MIS 单独译 |
| 5 | SFXML 新增 42 条正文 / 44 个 item 标题无 TM | 低 | 已进翻译批次 |
| 6 | 缺字：已点名 20（术语）+28（音译备用）；统计估计 278；容量 346 | 中 | `needed_chars_font.json` 已交；翻译阶段优先使用字符集已有字 |
| 7 | `0xFF`（著）与 XML 词法器 | 低 | 注入器硬拦（XML 类资源 error） |
| 8 | 小写 ASCII 在中文 16px 字库可能无字形（ATR 人名/SFXML 新枪名若保留英文） | 中 | 人名按本体惯例保留英文；字体方案（1024×644 图集）需字体工程师确认英文字形覆盖，**TBD** |
| 9 | 多语言副本（DE/ES/FR/IT）未处理 | 低 | 美版英文模式只用 EN；语言选择逻辑未做 ELF 闭环，**TBD** |
| 10 | 制作人员名单（G062 393 条）人名/职称译法 | 低 | 按惯例人名保留英文、职称可译；翻译批次覆盖 |
| 11 | 日期/时间本地化格式 | 低 | 建议 `2010年3月20日` / `06:30`；与本体风格可通过 TM 参考 |
| 12 | 加密/签名（DNAS 长文）译了也不影响连接逻辑 | 低 | 纯文本显示 |

---

## 13. 证据强度说明

* **[实证]**：条目数/字节数/偏移/编码/压缩尺寸/同文映射/TM 命中——全部可由本仓库脚本复现；
* **[推测]**：LANG 组语义归属、引擎对 >16K 帧的支持、多语言选择逻辑、字体小写覆盖——未做 ELF 反汇编/实机闭环，
  已在表中标注，后续由 ELF/字库/实机任务验证。

---

## 14. 复现命令

```powershell
$env:PYTHONIOENCODING="utf-8"
$py = "C:\Users\84363\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"

# ① 只读原盘 → assets/text/source/*（CSV+manifest+统计+用字候选）＋ work 分析产物
& $py tools\dlc\dump_text.py all          # = dump + tm + chars + plan
# 单独跑：dump / tm / chars / plan；audit 打印资源统计 JSON

# ② 注入侧：译文表 → payload blob + 校验（不写 ISO）
& $py tools\dlc\inject_text.py `
  --iso "third_party\orig\ps2\[PS2] Tom Clancy's Ghost Recon - Jungle Storm (U).iso" `
  --translations work\translation\merged\translations_all.csv `
  --check-only --allow-marker-drift
# 去掉 --check-only 并给 --out-dir 即写出 **58 个** <idx>_<name>.blob（LANG+SFXML+45 MIS+10 ATR+TXT；译文不全时数量更少）；--strict 供最终构建
```

关键常量：`LANG_IDX=576`、`SFXML_IDX=3101`、`TXT_IDX=577`、`CHUNK=16384`、`ISO_SHA256=292f5a6a…0767`。
