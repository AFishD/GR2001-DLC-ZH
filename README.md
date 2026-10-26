# 《幽灵行动：丛林风暴》PS2 汉化工程（SLUS-20820）

《Tom Clancy's Ghost Recon: Jungle Storm》(PS2, 美版 SLUS-20820) 的**完全汉化**工程。
资料片的数据结构与本体（SLUS-206.13）高度同源；本工程从本体的汉化工程
`Ghost_Recon_2001_Locolization` 继承工具链与资料，再针对资料片独立重建汉化链。

> **纪律**（继承本体工程）：
> 1. **基底只能是英文原盘**：`third_party/orig/ps2/[PS2] ... Jungle Storm (U).iso`
>    （sha256 `292f5a6a…0767`）。禁止拿历史汉化盘当基底。
> 2. **构筑脚本一律从原盘出发**，不依赖任何历史中间产物（无依赖链）。
> 3. **能用数据解决的绝不改 ELF** —— Game CRC 一变，玩家旧存档全废。
> 4. **文本区不得出现 `0xFF`** —— 引擎 XML 词法器把它当 EOF。

## 当前状态（最终版 v1.0，2026-10-26）

**汉化已完成，最终成品：`work\builds\FINAL\GR_JS_ZH_v1.0_final.iso`**
（sha256 `29883b66b8e1d3f2cbedf283deeb956484260b041d918aba3ec37495611b4d24`，Game CRC `E0325951`，verify 40/40）

= 英文原盘 + 中文图集/合并 FONT.RES + 45 缺字补画 + DBCS v2 ELF + 3,372/3,372 条译文
+ 战役卡死修复（RSString 串越界/NULL 守卫）
+ 换行边界根治（DBCS 整字折行 + 行首 +1 修正）
+ 手柄图标恢复（引擎图标码换区）
+ 队员设置/难度/任务列表基线统一 + 简报任务目标行对齐（cave G）
+ 训练/任务提示严格 29 汉字/行（行尾半角空格顶宽）
+ 启动加载画面 Loading... →「载入中...」「请等待...」（ELF 5 语言槽表）

唯一构筑脚本 `tools\dlc\build.py`（stage: spec/font/text/elf/all）可从英文原盘一键复现；
verify.py **40/40** 通过、audit.py 缺字 0。PS2 BIOS 的读盘/记忆卡提示属主机固件，不在游戏盘内
（见 [`docs/ANALYSIS_ELF.md`](docs/ANALYSIS_ELF.md) §46）；其余细节见
[`docs/REPORT_FINAL_DELIVERY.md`](docs/REPORT_FINAL_DELIVERY.md) 与 [`docs/STATUS.md`](docs/STATUS.md)。

## 我需要看哪一篇

| 我想…… | 看 |
|---|---|
| 了解整体计划与阶段 | [`docs/PLAN.md`](docs/PLAN.md) |
| 看 ISO / 资源结构分析 | [`docs/ANALYSIS_ISO.md`](docs/ANALYSIS_ISO.md) |
| 看 ELF / 引擎能力分析 | [`docs/ANALYSIS_ELF.md`](docs/ANALYSIS_ELF.md) |
| 看字库 / 图集方案 | [`docs/ANALYSIS_FONT.md`](docs/ANALYSIS_FONT.md) |
| 看文本表 / 翻译资产 | [`docs/ANALYSIS_TEXT.md`](docs/ANALYSIS_TEXT.md) |
| 知道现在到哪一步 | [`docs/STATUS.md`](docs/STATUS.md) |
| 把盘做出来 | [`docs/BUILD_GUIDE.md`](docs/BUILD_GUIDE.md) |
| 改文本 / 字库 / 任务名 | [`docs/MOD_GUIDE.md`](docs/MOD_GUIDE.md) |

## 一条命令（目标形态）

```powershell
python tools\dlc\build.py            # 英文原盘 → 汉化成品（逐阶段 sha256 自证）
python tools\dlc\verify.py           # 硬断言自证
```

## 仓库里有什么

```
tools/lib/          共用库（从本体工程继承：dump_font / repack_font / font_compact /
                    glyph_geometry / iso_tools / icon_table / zx_lib / lz77_decode / lzo1x_c）
tools/text_csv/     文本表工具（从本体工程继承：tcslib / dump_text_csv / inject_text_csv）
tools/dlc/          ★ 本工程新增：资料片专用工具链（dump / inject / font / build / verify）
tools/analysis/     只读分析脚本（ISO / ELF / 资源普查）
assets/charset/     字符集（继承本体 2300 对偶 + 103 单字节码，按资料片需要扩充）
assets/text/        译文资产（CSV：LANG / SFXML / MIS / 其它 XML）
assets/mis/         任务名对照表
assets/font/        汉化字库模板（从本体成品提取的「中文字库资产」）
reference/          本体工程的文档与阶段脚本（只读参考）
docs/               本工程文档
work/               ★ 不进库 —— 中间盘 / dump / 分析产物
third_party/        ★ 不进库 —— 英文原盘 ISO / 像素字体 TTF / 模拟器
```

## Git 纪律

* `main`：只在**验证通过后**合并进来的稳定主线。
* `test/*`：每个方向一个测试分支（analysis / font / text / build …），完成后才允许合并。
* 大文件（ISO / dump / TTF）与第三方版权内容**永不入历史**（见 `.gitignore` 白名单）。
* 入库资产一律是可复现的**源材料**（脚本 / 文本 / JSON 字符集），不是成品盘。

---

## 云端仓库内容说明（版权/第三方内容已剔除）

本仓库只包含 **工程代码、文档、字符集与中文译文**。以下内容因版权或体积原因**不入库**，需要你本地自备：

| 内容 | 说明 |
|---|---|
| 英文原盘 ISO | 版权内容；构建时放入 	hird_party/orig/ps2/ |
| PCSX2 模拟器 / BIOS / 记忆卡 | 第三方版权；自行准备 |
| 字体种子（TTF/PSMT 图集） | 版权字体；按 docs/ANALYSIS_FONT.md 自备 |
| 游戏抽取原文（\ssets/text/source/\、\ssets/text/merge/\） | 游戏原文受版权保护；用 \python tools/dlc/build.py --stage dump-text\ 从自己的原盘重新生成 |
| 游戏截图（\docs/img/\） | 游戏画面版权；文档中的截图链接需要本地截图 |
| 运行时产物 \work/\ | 构建中间产物，不入库 |

重新构建（需要本地原盘）：

    python tools\dlc\build.py --stage dump-text   # 生成 assets/text/source
    python tools\dlc\build.py --stage all --out work\builds\GR_JS_ZH.iso --force
    python tools\dlc\verify.py --iso work\builds\GR_JS_ZH.iso --stage all

汉化成品盘（含游戏数据）**不在本仓库、也不会上传**，请本地构建或另行分发。
