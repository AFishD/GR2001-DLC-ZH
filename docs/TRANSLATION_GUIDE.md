# TRANSLATION_GUIDE —— 资料片汉化翻译规范（译者必读）

> 目标：把《幽灵行动：丛林风暴》(PS2) 的英文文本译成**简洁、准确、军事题材口吻**的简体中文。
> 本文件 + 各自批次的 `work/translation/batches/batch_*.csv` 就是你的全部输入。

## 0. 你只需要做一件事

打开分配给你的 `batch_*.csv`（UTF-8 BOM，列：`resource,id,text_en,text_zh,context`），
把**每一行**的 `text_zh` 填成中文译文，输出到 `assets/text/translated/<你的批次名>.csv`
（列保持 `resource,id,text_zh` 三列即可；不要加/删行，不要在单元格里放真换行）。

## 1. 硬规则（违反会导致盘坏/游戏崩溃）

1. **保留所有标记原样**：`{p}`（段落）、`{br}`（换行）、`{{BTN:E0B1}}` / `{{BTN:E0B5}}`（△/✕ 手柄图标）。
   标记的数量与相对位置尽量保持一致；不要翻译/改写标记本身。
2. **不要写真正的换行/Tab**：CSV 单元格里换行请保持 `\r\n` 字面转义（原样保留即可）。
   如果你的译文需要分段，沿用原文的 `{p}` 位置，不要自己造 `\r\n`。
3. **禁止出现 `0xFF` 字符**（它会让引擎 XML 词法器提前 EOF）；也不要出现控制字符。
4. **格式串/占位符原样保留**：`%0x%1x%2`、`%s`、`%d`、`<title>…</title>`、`<br>` 等，
   只翻译其中的人类文字部分。例：`<title>Project Management` → `<title>项目管理`。
5. **人名/地名策略**：
   * 人名（士兵、专家、政治人物）**保留英文原名**（如 `Will Jacobs`），不要音译（引擎字库含 ASCII）；
   * 地名/行动名可音译或意译，但**全工程必须一致**（见 §3 术语表）；
   * 文件名（含 `.rsb`/`.wav`/`.mis`）与纯 token（`WPN_M4`）**不翻译**，原样返回。
6. **保持简短**：UI 按钮/菜单项尽量 ≤ 6 个汉字；超长会溢出按钮/换行错位。
   原文很短（≤3 字符）的也保持短（如 `Ok`→`确定`，`Quit`→`退出`）。
7. **数字/单位**沿用原文（2010 年、06:30、10s 等）；日期可本地化为 `2010年3月20日`，时间保持 `06:30`。

## 2. 文风

* 军事/战术口吻：简报用「各位/任务/目标/侦察/掩护/撤离/歼灭」等军语；不要口语化卖萌。
* 术语统一优先于文采；不确定时查 §3 术语表与已有译文（`assets/text/merge/*.csv`）。
* 标点：用**中文全角**标点 `，。！？：；、（）《》「」`；省略号用 `……`，乘号用 `×`（工具链会补字形）。
* 英文缩写/代号（如 `MP01`、`C01`、`J02`、`DP05`、`X -`）保留。
* 任务/地图编号前缀保留：`C01 - Watchful Yeoman` → `C01 - 警惕的农夫`。

## 3. 术语表（本工程统一口径）

| 英文 | 中文 | 备注 |
|---|---|---|
| Ghost Recon / Ghosts | 幽灵行动 / 幽灵小队 | 游戏名 |
| Jungle Storm | 丛林风暴 | 资料片名 |
| Ghost | 幽灵 | 队员 |
| fireteam | 火力小组 | |
| assault rifle | 突击步枪 | |
| sniper rifle | 狙击步枪 | |
| submachine gun | 冲锋枪 | |
| machine gun | 机枪 / 班用自动武器 | M249 → 班用自动武器 |
| grenade launcher | 榴弹发射器 | |
| hand grenade | 手榴弹 | |
| claymore | 定向雷 / M18 定向反步兵地雷 | |
| demolition charge | 爆破装药 | |
| rocket launcher | 火箭筒 | |
| ammo / magazine | 弹药 / 弹匣 | 不要写「弹夹」 |
| suppressor | 消音器 | |
| scope | 瞄准镜 | |
| bipod | 两脚架 | |
| night vision | 夜视仪 | |
| sensor | 传感器 | |
| binoculars | 望远镜 | |
| kit | 装备方案 | |
| class（兵种） | 突击兵 / 支援兵 / 爆破兵 / 狙击手 / 步枪手 / 专家 / 重火器专家 | |
| rank 军衔 | 列兵/一等兵/下士/中士/上士/军士长/少尉/中尉/上尉/少校/中校/上校/准将/少将/中将/上将 | 参照 assets/text/merge CSV 一统 |
| multiplayer | 多人模式 | |
| co-op | 合作模式 | |
| objective | 目标 | |
| mission complete | 任务完成 | |
| mission failed | 任务失败 | |
| extraction zone | 撤离区 | |
| checkpoint | 检查点 | |
| hostage | 人质 | |
| intel | 情报 | |
| airstrike | 空袭 | |
| recon | 侦察 | |
| firefight | 遭遇战 | |
| defend | 防守 | |
| capture | 占领 / 夺取 | |
| neutralize | 清除 / 压制 | |
| eliminate | 歼灭 | |

（更全的术语与既有译文参考：`assets/text/merge/*.csv`、`work/analysis/text/tm_matches.csv`；
遇到不确定的军语，先在 `assets/text/merge/` 里搜英文原词看本体成品怎么译。）

## 4. 已知上下文（按批次 context 列）

* `G019..G033`：战役任务文本（地点/日期/时间/简报/目标/地名），是玩家读得最多的部分，**要仔细**。
* `G058`：混合 UI 文案（按钮/提示/专家档案/军械说明）。逐条看英文判断；短串求准求短。
* `G062`：制作人员名单。人名保留英文；职位（`<title>Project Management`）译中文；`<br>` 原样。
* `G012..G018`：训练场教程长句，注意操作按键名（Fire Weapon button → 开火键）与体感描述。
* `SFXML`：特别收录（武器介绍/专家档案/战役背景），长文，允许分段但保留 `{p}`。
* `MIS`：任务文件字段；其中 Name/MapName/Location/Date/Time 与 LANG 同文，**LANG 批次完成后会以 LANG 为准自动回填**，你按自己判断译即可。

## 5. 输出与自检

* 输出文件：`assets/text/translated/batch_<你的编号>.csv`（UTF-8 BOM，CRLF 无妨）。
* 完成前自查：行数 == 输入行数；每行 `text_zh` 非空；`{}`/`{{BTN:…}}` 数量与原文一致；
  无真换行；无 `0xFF`；无未翻译的英文整句（专有名词/代号除外）。
* 完成后 send_message 给 lead：批次名、完成行数、存疑行号列表（拿不准的个别行可留 `[?]` 标记在 notes）。
