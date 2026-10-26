# BUILD_GUIDE —— 从英文原盘一键重建汉化盘

> 面向「未来的你」：隔了几个月回来，只想知道**怎么从零把这张盘做出来**。
> 所有命令都在仓库根执行；PowerShell 7 / Python 3.12 已验证。

---

## 0. 一句话

```powershell
python tools\dlc\build.py --stage all --write-spec      # 英文原盘 → 汉化盘（font + text + ELF）
python tools\dlc\verify.py --iso <产物> --stage all    # 硬断言自证（37 条）
python tools\dlc\audit.py  --iso <产物>                # 完整性审计（译文覆盖/缺字/CRC）
```

`build.py` 每个阶段都**从英文原盘重建**（不消费上一阶段产物），逐阶段比对
`tools/dlc/fix_spec.json` 里声明的 sha256；不符立刻退出。

---

## 1. 需要「本地自备」的东西（**不进版本库**）

`.gitignore` 已排除，缺任何一项 `build.py` 会立即报错。

| 项 | 期望路径 | 指纹 | 说明 |
|---|---|---|---|
| **英文原盘 ISO** | `third_party\orig\ps2\[PS2] Tom Clancy's Ghost Recon - Jungle Storm (U).iso` | sha256 `292f5a6a…0767`（1,229,225,984 B） | 唯一合法基底（美版 SLUS_20820） |
| **本体汉化成品 ISO**（字库 seed 源） | `C:\Users\84363\Desktop\Ghost_Recon_2001_Locolization\work\builds\FINAL\Tom Clancy's Ghost Recon (ZH_CN).iso` | sha256 `4ded92e2…17a` | 一次性提取中文字库 seed；`third_party\ref\zh_font_seed\` 已提取好（4 bin + meta.json） |
| **像素字体** | `third_party\fonts\方正像素16.ttf` | 2,632,936 B | 补画缺字时渲染字形（字体有版权，不进库） |
| PCSX2（可选） | `C:\Users\84363\AppData\Local\PCSX2\` | v2.8.2 | 实机冒烟/截图验证（`tools\emu\run_smoke.py`） |

> 字库 seed 已提取并登记 sha256；若删了可用 `python tools\font\extract_seed.py` 从本体成品盘重建。

---

## 2. 依赖

| 组件 | 版本 | 备注 |
|---|---|---|
| Python | 3.12（3.8+ 均可） | 标准库 + numpy + Pillow |
| numpy / Pillow | 1.26 / 12.3 | 图集运算 / TTF 渲染 |
| PCSX2 | 2.8.2（可选） | `tools\emu\run_smoke.py` 冒烟 |
| 7z（可选） | — | 产物完整性独立校验 |

---

## 3. 构建链：文件与阶段

```
tools/dlc/
    build.py            ★ 唯一构筑脚本：阶段 list/spec/font/text/elf/all/dump-text
                          · font/text/elf/all：从英文原盘重建 ISO
                          · spec：生成 ELF 补丁表 elf_patches.json（DBCS+过滤/行盒+串守卫）
                          · dump-text：导出文本表格（原文 + 译文对照 CSV）
    verify.py           ★ 唯一校验入口（38 条硬断言 + 回归 sha256）
    audit.py              完整性审计（回读成品盘统计）
    fix_spec.json         单一真源：输入指纹 / 各阶段实测 sha256
    elf_patches.json      ELF 补丁表（44 段：25 站 DBCS + 1000B cave + 2 处字库最近邻过滤
                          + 5 段行盒锚点 + 5 段串越界/NULL 守卫 + 6 段折行修复（含行首 +1 修正）；
                          由 `build.py --stage spec` 生成）
    dlclib.py             盘面/IMG/LANG/SFXML/PAK/LZO 访问库（只读）
    rebuild.py            ISO 重建引擎（identity：无改动重建 == 原盘逐字节）
    inject_text.py        译文 → 资源 payload（58 个 blob）
    merge_translations.py 译文来源合并（新译 > TM > JS19 兜底 > MIS 自动回填）
    char_coverage.py      译文用字覆盖 / 缺字清单
    dump_text.py          文本抽取库（build.py --stage dump-text 的内核；也可单独跑）
tools/font/
    dump_atlas_table.py   字库纹理「表格图」导出（含 EN 原版对照、图标格放大图）
    atlas_guard.py        图标哨兵槽检测/保护（字符集占用、图集像素、文本图标码）
    split_translation.py / check_translated.py  翻译批次切分与校验
tools/font/
    fontlib.py            FONT.RES/PAK/图集 结构实现
    extract_seed.py       从本体成品盘提取字库 seed（一次性）
    expand_charset.py     字符集扩充：缺字 → 空槽补画（幂等/确定性）
    build_font.py         字库方案 B 原型（独立可跑）
tools/analysis/           只读分析（ISO/ELF/资源扫描；dbcs_spec.py 生成补丁规格）
tools/emu/                PCSX2 冒烟：run_smoke.py + wincap.py + compare_smoke.py
```

## 3c. 字库纹理表格图（`tools/font/dump_atlas_table.py`）

```powershell
python tools\font\dump_atlas_table.py --iso work\builds\FINAL\GR_JS_ZH.iso --tag zh
python tools\font\dump_atlas_table.py --iso "<英文原盘>" --tag en
```

| 产物（work/analysis/font/） | 内容 |
|---|---|
| `atlas_engine_<tag>.png` | 图集引擎图 1:1 |
| `atlas_table_<tag>.png` | **表格图**：2× 放大 + 16px 格网格 + 行列号 + 红框=图标哨兵槽 + 绿框=PUA 回收槽 |
| `atlas_slots_<tag>.csv` | 槽位表：slot/row/col/lead/trail/char/kind/ink_px |
| `atlas_icon_cells_zoom.png` | 50 个图标哨兵格 8× 放大（红框=有墨图标像素格） |
| `atlas_compare.png` | EN 原版 512×512 vs 成品 1024×644 对照 |

### 图标占位符 / 哨兵槽保护（构筑硬断言）

`tools/font/atlas_guard.py` 定义并检查三件事，`build.py --stage all` 与 `verify.py` 都会跑：

| 编号 | 断言 | 说明 |
|---|---|---|
| I1 | 字符集不占用 50 个图标哨兵槽 | trail ∈ {0xB1,0xB5} 的对偶槽 = 引擎图标特判槽，永不分配 |
| I2 | 图集哨兵格像素 == seed | 图标像素（slot 768/772 有墨）不被补画/重排覆盖 |
| I3 | 文本图标占位码逐条一致 | 单字节 0xB1/0xB5（引擎画手柄按键）数量与原盘一致（`--stage dump-text` 产出 `text_icons.csv`） |

`verify.py` 现有 **40 条硬断言**（38 + I1/I2），I3 在 `--stage dump-text` 的图标报告里核对。

## 3b. 文本表格 dump（`--stage dump-text`）

```powershell
python tools\dlc\build.py --stage dump-text
```

产物（默认 `work/analysis/text/tables/`，`--out-dir` 可改）：

| 文件 | 内容 |
|---|---|
| `en/*.csv` | 英文原盘逐资源原文表（LANG / SFXML 正文+标题 / MIS / ATR / TXT / 其它 XML 审计） |
| `lang_bilingual.csv` 等 6 张 | **原文/译文对照表**：`key, text_en, text_zh, status, byte_len_en, byte_len_zh` |
| `bilingual_all.csv` | 全部资源合并总表（`resource, key, text_en, text_zh, status`） |
| `summary.json` | 各表行数 / 已译 / 保留英文 / 空 |

`status` 取值：`translated`（已译）/ `kept_en`（按规范保留英文，如人名/文件名/武器型号）/
`empty`（原文为空）。译文来自构筑实际使用的 `work/translation/merged/translations_all.csv`
（`--iso` 可指定别的译文表 CSV；`GRJS_TRANS` 环境变量同样生效）。

### 三个阶段在做什么

| # | stage | 内容 | 产物关键点 |
|---|---|---|---|
| 1 | `font` | 中文图集 1024×644 PSMT4 + 合并 FONT.RES + 45 缺字补画 | GR#9 COMMON.PAK（+66,624 B）、GR#580 FONT.RES（7,466 B blob） |
| 2 | `text` | LANG + SFXML + 45 个 MIS + ATR/TXT 译文注入 | 58 个资源 payload；LANG blob 177,441→约 100 KB |
CRC `DE1E4DEE → D0903834`；旧存档失效 |
| 4 | `all` | font + text + elf 全量 | 最终候选盘 |

---

## 4. 一条龙（推荐）

```powershell
$env:PYTHONIOENCODING="utf-8"

# 1) 合并译文（改过 assets/text/translated/*.csv 后必跑）
python tools\dlc\merge_translations.py        # → work\translation\merged\translations_all.csv
python tools\dlc\char_coverage.py             # 缺字清单（应为 0；若有→下一步）
python tools\font\expand_charset.py           # 自动补画新增缺字（幂等）

# 2) 从英文原盘重建（逐阶段 sha256 自证）
python tools\dlc\build.py --stage all --out work\builds\JS_ZH_final.iso --force

# 3) 校验 + 审计
python tools\dlc\verify.py --iso work\builds\JS_ZH_final.iso --stage all
python tools\dlc\audit.py  --iso work\builds\JS_ZH_final.iso

# 4) 实机冒烟（可选）
python tools\emu\run_smoke.py --iso work\builds\JS_ZH_final.iso --seconds 330 `
    --out work\analysis\emu\final --keys "15:space,102:space,118:return,133:space,148:space"
```

> `GRJS_TRANS=<path>` 可用环境变量指定译文总表（测试 A/B 时用）。
> `--write-spec` 把实测 sha256 写进 `fix_spec.json`；不写则进入「回归模式」严格比对。

---

## 5. 改文本 / 加字 / 改 ELF 时怎么更新期望 sha256

1. 改资产后先跑 `merge_translations.py`（+ `expand_charset.py` / `char_coverage.py`）；
2. `build.py --stage all --write-spec` 记录新 sha256（日志逐阶段打印）；
3. `verify.py` 全绿；
4. 更新 `docs/STATUS.md` 的正式版身份与 `docs/REPORT_FINAL_DELIVERY.md`。
> 期望 sha256 是**回归测试**：任何一步意外改变内容都会立刻被抓住。

---

## 6. 纪律（继承本体工程）

1. **基底只能是英文原盘**（sha256 校验）；禁止拿历史汉化盘当基底。
2. **每个阶段都从原盘重建**，不依赖历史中间产物（无依赖链）。
3. **文本区不得出现 `0xFF`**（引擎 XML 词法器当 EOF）。
4. 能用数据解决的绝不改 ELF；DBCS 补丁是唯一不可避免的 ELF 改动（有实机证据）。
5. 大文件（ISO/dump/TTF）与第三方版权内容**永不入 git 历史**。

---

## 7. 最小验证清单（交付前逐条打勾）

- [ ] `build.py --stage all` 三个阶段全部 `OK == fix_spec.json`
- [ ] `verify.py --stage all` 37/37 通过
- [ ] `audit.py`：缺字 0；剩余英文仅为专名/文件名/军衔缩写（见报告白名单）
- [ ] 产物 sha256 == `fix_spec.json` 的 `all` 阶段
- [ ] PCSX2 冒烟：TLB Miss 0、菜单/简报中文正常（截图存证 `work\analysis\emu\`）
- [ ] `git status` 干净；`third_party/**`、`work/**` 无文件被跟踪

## 附录：文本表 dump → 编辑 → 写回（edit_text.py）

`tools/dlc/edit_text.py` 提供与本体工程 `tools/text_csv/` 等价的文字工作流：

```powershell
python tools\dlc\edit_text.py prepare                          # dump + 各表加 text_edited 列
python tools\dlc\edit_text.py inject --out work\builds\EDIT.iso --verify
```

* 只改 `text_edited` 列；`{WRAP}`（大小写不限）→ 引擎换行 `{br}`，可手动控制断行；
* `inject` 从英文原盘完整重建（字体/ELF 补丁照旧叠加），并用 `--verify` 重新 dump 往返核对；
* 详细格式/报错见 [EDIT_TEXT_CSV.md](EDIT_TEXT_CSV.md)。

## 附录：窄栏文本硬折行（wrap_text.py）

任务简报页等“控件可见宽度小于折行宽度”的界面，用数据侧硬折行解决：

    python tools\dlc\wrap_text.py --in work\translation\merged\translations_reuse.csv ^
        --out work\translation\merged\translations_v21.csv --units 15 --only-briefing

* --units 15 = 每行最多 15 个全宽字（≈240px，匹配简报框 262px 可用宽）；
* --only-briefing 自动识别“同组含 1./2./X- 目标项”的简报组；
* 盘上写 {br}；{p} 分段保留，英文单词不拆。

## 默认译文表

build.py 与 edit_text.py prepare 现在自动取最新合并译文表：
translations_v21.csv → translations_v20.csv → translations_all.csv（可用 GRJS_TRANS 覆盖）。

## 附录：自动抓「简介」页（nav_briefing.py）

    python tools\emu\nav_briefing.py --iso work\builds\FINAL\GR_JS_ZH_v22_candidate.iso ^
        --out work\analysis\emu\navauto_v22

闭环状态机（画面特征判定，不用固定秒数）：主菜单(黄≈9658) → 单人菜单(黄≈4585，高亮条闭环到“战役”)
→ 战役画廊(黄≈10699，默认 ISLAND THUNDER) → 过场 FMV → 简介页(黄≈6545)，到页连拍 3 张。

## 行盒锚点 A/B（v22 起）

build.py 支持环境变量覆盖行盒锚点常量，便于实机 A/B：

    GRJS_ANCHOR_TITLE=0.0 GRJS_ANCHOR_MID=3.0 GRJS_ANCHOR_BOTTOM=3.0 ^
    python tools\dlc\build.py --stage all --out <iso> --force

（默认值 = v22：title 0 / mid 3 / bottom 3）
