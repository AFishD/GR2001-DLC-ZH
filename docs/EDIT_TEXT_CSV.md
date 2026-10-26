# 文本表 dump → 编辑 → 写回（edit_text.py）

对应本体工程的 `tools/text_csv/` 工作流：**把游戏里的全部文本 dump 成 CSV → 人工改文本/断行 → 按 CSV 反向写回 ISO**。
本作（丛林风暴 DLC）的实现是 `tools/dlc/edit_text.py`，断行标记用 **`{WRAP}`**（`{Warp}` / `{wrap}` 等大小写不限）。

---

## 0. 三步上手

```powershell
# ① dump：重新抽取对照表，并给每张表追加空列 text_edited（已有编辑不会被覆盖）
python tools\dlc\edit_text.py prepare

# ② 用 Excel 打开 work\analysis\text\tables\ 下的表，只改 text_edited 列：
#    · 文字修改：直接改
#    · 手动断行：在要断的地方写 {WRAP}
#    · {{BTN:E0B1}} / {{BTN:E0B5}}：手柄图标标记，不要动

# ③ 写回：从英文原盘完整重建 ISO（字体/ELF 补丁照旧叠加），并做往返自检
python tools\dlc\edit_text.py inject --out work\builds\EDIT.iso --verify
```

只想校验/看合并结果，不写盘：

```powershell
python tools\dlc\edit_text.py inject --dry-run
```

---

## 1. 产出的表

`prepare` 会产出（在 `work/analysis/text/tables/`）：

| 文件 | 内容 | 有编辑价值的 |
|---|---|---|
| `lang_bilingual.csv` | LANG 文本（菜单/提示/简报/特别收录等 2971 条） | ✅ |
| `sfxml_text_bilingual.csv` | SFXML 文本（界面文案 98 条） | ✅ |
| `sfxml_titles_bilingual.csv` | SFXML 标题（174 条） | ✅ |
| `mis_bilingual.csv` | 任务文件字段（任务名/简报/日期等 248 条） | ✅ |
| `atr_bilingual.csv` | .ATR 角色名（766 条） | ✅ |
| `strings_txt_bilingual.csv` | EN_STRINGS.TXT（武器/装备显示名 228 条） | ✅ |
| `bilingual_all.csv` | 上面全部合并的只读总表 | （对照用） |
| `summary.json` | 各表条数/统计 | — |

列含义（各表相同）：

| 列 | 只读 | 说明 |
|---|---|---|
| `key` | ✅ | 条目 key（LANG 形如 `G012.I012`；MIS 形如 `C01_PLANTATION.MIS#Name`；ATR 形如 `ATR:DEMOLITIONS-01.ATR:ActorName`；TXT 形如 `TXT:WPN_M4`） |
| `text_en` | ✅ | 英文原文（对照用） |
| `text_zh` | ⚠ | dump 时的中文（用于对照；**未编辑的行注入时用它**，所以不要清空） |
| `text_edited` | ✏ | **要改的列**：非空 ⇒ 用这里的文本，否则用 `text_zh` |
| `status` | ✅ | `translated` / `kept_en` / `empty` |
| `byte_len_en` / `byte_len_zh` | ✅ | 字节长度参考 |

> 建议只改 `text_edited`：这样 dump 原文与你的改动分开，重新 `prepare` 时也方便对照。

---

## 2. `{WRAP}` 人工断行

* 写法：`{WRAP}` / `{Warp}` / `{wrap}` / `{wArP}` 都认。
* 注入时会被换成引擎的换行标记 **`{br}`**（实际落盘字节）。
* 规则（否则拒绝写回并报错）：
  1. 不能放在文本**开头/结尾**（会产生空行）；
  2. 不能和另一个 `{WRAP}`、`{p}`、`{br}` **紧挨着**；
  3. 写法必须完整：`{WRAP`、`{WRAPP}`、`{WRP}` 之类会被拦下。

例：

```
用动作键来开门。{WRAP}开门的时候尽量不要正对着门——这可能使你马上成为门后敌人的靶子。
```

→ 盘上：`用动作键来开门。{br}开门的时候…`，游戏里就在标记处固定换行。

> 说明：引擎仍会按 29 个全宽字**自动折行**；`{WRAP}` 只是在你指定的位置**强制提前断行**。
> 想完全手动控制断行，就在每行末尾都写 `{WRAP}`（注意不要贴到自动折行点上，否则可能多出短行）。

---

## 3. 写回做了什么

`inject`：

1. 读全部表 → `text_edited` 优先、否则 `text_zh`，合并成完整译文表
   `work/translation/merged/translations_edited.csv`（`resource,id,text_zh,source`）；
2. 校验 `{WRAP}` 与字符集；
3. 调 `build.py --stage all`：从**英文原盘**完整重建（字库、行盒锚点、串守卫、折行/图标修复、ELF 全部照旧叠加），
   `GRJS_TRANS` 指向合并表；
4. `--verify`：把新盘重新 dump 到 `work/analysis/text/_roundtrip/`，逐条核对编辑是否落盘。

输出默认 `work/builds/GR_JS_ZH_edited.iso`（`--out` 可改）。

---

## 4. 常见报错

| 报错 | 原因 / 处理 |
|---|---|
| `没有找到任何可注入文本` | `text_edited` 全空；先改表再 inject |
| `{WRAP} 不能放在文本开头或结尾` | 把标记往中间挪，或删掉 |
| `两个 {WRAP} 紧挨着` | 删掉一个（连续两个换行请用 `{p}`） |
| `断点标记写法不对：'{WRAPP}'` | 拼写必须是 `{WRAP}` |
| 构筑阶段 `缺字` 报错 | 改的文本里有字符集外的字；换字或把字加进字符集 |
| 编辑没生效 | 检查是否改在 `text_edited` 列；或表格没保存成 UTF-8 CSV |

---

## 5. 与本体工程命名的差异

本体工程用 `{WRAP}`→`{br}`（round36 起），本工具完全沿用这一口径；
图标标记也沿用 `{{BTN:XXXX}}`（`E0B1`=△、`E0B5`=✕）。
不同点只有：本作 dump 表按资源各一张（无 `_long/_short` 之分），注入走 `build.py` 全量重建。
