# STATUS —— 现状

更新时间：2026-10-26（**最终版 v1.0**，verify 40/40）

## 一句话

**汉化已完成并交付最终版**：中文图集 + 合并 FONT.RES + DBCS v2 ELF + A‴ 行盒锚点 +
串越界/NULL 守卫（战役卡死修复）+ 3,372/3,372 条译文 + 列表/提示框排版修复 +
简报任务目标对齐 + 训练提示严格 29 汉字/行 + 启动加载文本汉化；
从英文原盘一键重建、verify 40/40 通过。

## 最终成品盘

```
work/builds/FINAL/GR_JS_ZH_v1.0_final.iso (1229266944 B, CRC E0325951, sha256 29883b66b8e1d3f2cbedf283deeb956484260b041d918aba3ec37495611b4d24)
  = 英文原盘 + 中文图集(1024×644 PSMT4) + 合并 FONT.RES + 45 缺字补画
  + DBCS v2 ELF + 字库最近邻过滤 + A‴ 行盒锚点 + 串越界/NULL 守卫
  + 3,372/3,372 译文（LANG/SFXML/MIS/ATR/TXT）
  + cave G（简报任务目标行 −3px 对齐分栏线）
  + 29 汉字/行提示（行尾半角空格顶宽）+ ELF 5 语言载入槽表汉化
  verify: 40/40 PASS ; audit: 缺字 0
```

## 基线身份（英文原盘）

```
third_party/orig/ps2/[PS2] Tom Clancy's Ghost Recon - Jungle Storm (U).iso
1,229,225,984 B ; sha256 292f5a6a050e82e05efb5bf9fd5ce3bc12706a8ae57c78b729348a5c80fd0767
卷标 SLUS_20820 ; ELF SLUS_208.20 @ LBA 296 ; GR.IMG @ LBA 61000 / 3,111 条
```

## 当前候选盘

```
work/builds/FINAL/GR_JS_ZH.iso  (= JS_ZH_v11.iso, 1,229,264,896 B, CRC D0903834, sha256 cbb4f9c8…)
  = 英文原盘 + 中文图集(1024×644 PSMT4) + 合并 FONT.RES(7,466B) + 45 缺字补画
  + DBCS v2 ELF（25 站 DBCS + 1000B cave + 2 处字库最近邻过滤）+ 3,372/3,372 译文（LANG/SFXML/MIS/ATR/TXT）
  + **A‴ 行盒锚点**（fld[1]=EN 26/26/42 + 16px 字形行盒居中 + 标题带 +7 + 帮助条 −3） + **字库最近邻过滤**（笔画无漏墨）
  verify: font 26/26, text 36/36, elf 28/28, all 38/38 PASS ; audit: 缺字 0 ; 剩余英文仅专名/文件名/军衔缩写
```

## 完成度（`tools/dlc/audit.py` 实测）

| 资源 | 条目 | 中文 | 说明 |
|---|---:|---:|---|
| LANG | 2,971 | 2,494 | 74 空 + 108 纯符号 + 295 英文（专名/文件名/军衔缩写） |
| SFXML 正文 | 98 | 81/81 | 17 空 |
| SFXML 标题 | 174 | 138 | 21 个武器型号/专家名保留 |
| MIS | 45 文件 | 可见字段 202/203 | TAC01 已回填 |
| ATR | 766 | 6 兵种名 + 760 人名保留 | |
| 字库 | 2,300+103 | 覆盖 1,302 种汉字 | 缺字 0；槽占用 1,908/2,350 |

## 硬件自证

* 身份重建：无改动重建 == 原盘逐字节（ISO/IMG/table/尾部 全证）
* 阶段断言：font 26/26、text 36/36、elf 28/28、all 38/38
* 实机（PCSX2 2.8.2 DX12）：启动/标题/FMV/Profiles/文件名页 **0 TLB Miss**；
  中文渲染确认（`work/analysis/emu/all_test/alltest_native_{130,145,330}s.png`）
* 可复现：两次独立 build 产物 sha256 一致

## 待办（收尾）

1. ~~实机深导航~~ **已用记忆卡 Mcd001.ps2 完成**：单人主菜单/训练列表/任务信息屏/进任务游玩，260s 0 TLB/0 异常、中文教学弹窗折行正常；战役简报屏未逐屏（同渲染路径，见 REPORT §D R3）；
2. ~~标题类大字垂直偏移/裁剪~~ **已修复（A′+A″ 纯数据）**：fld[1]=16 + 全部 style f5/f6=1.0；v6 实机确认标题完整、2008年3月15日 | 13:00 | 晴天 混排行对齐；
3. 贴图内烘焙英文（未重绘，如实记录，见 `docs/REPORT_FINAL_DELIVERY.md` §D）；
4. 文档终稿 + `fix_spec` 固定 + Git `test/*` → `main` 合并。

## Git

* `main` = P0 基线；`test/analysis` 主工作分支；另建 `test/build-font` / `test/build-elf` /
  `test/build-text` / `test/final` 快照分支；验收后 `--no-ff` 合入 `main`。
* 仓库 3.27 MiB，仅 tools/docs/assets/reference；ISO/TTF/dump/成品盘全在 `.gitignore`。

- 文本工作流：`tools/dlc/edit_text.py`（dump → 改 text_edited → `{WRAP}` 断行 → inject 写回，含往返自检）。

- v21（候选）：复用本体译文 42 条 + 16 条任务简报硬折行（15 全宽字/行，修简介页右侧溢出）。

- v22（候选）：简报页换行回归修复（v21 起）+ 标题带/中段锚点上移（title +7→0、mid -2→-3）；新增闭环导航 nav_briefing.py 与 NAV_CLOSED_LOOP.md。
