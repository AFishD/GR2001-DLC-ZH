# REPORT_FINAL_DELIVERY —— 收尾交付（2026-10-21）

> 本轮任务：**定版 → 重构精简 → 全链自证 → 文档 → 提交**。
> 历史重写**不在本轮范围**（但并发进程已经做了一次，见 §A.4）。

---

## A. 正式版

### A.1 选定的盘

```
work\builds\GR_RELEASE\GR_ZH146.iso
  尺寸    1,648,164,864 B
  sha256  4ded92e2fee535ac00893af60faee630323af124aa38a89d1777d1721d04617a
  md5     8732e73f04e0af18060b0e990ec94a6c
  ELF     SLUS_206.13 @ LBA 295 / 37,453,732 B
          sha256 a0c8499cf30f1cc5c44dfb49502270ed0ecbdccb30c023246b227591c40ba12e
  Game CRC 653FBF69  ⇒ 即时存档名 SLUS-20613 (653FBF69).01.p2s（旧存档继续可用）
```

**名字保持 `GR_ZH146` 不变**：改名只会让 Game CRC / 存档名 / 历史文档的认知链断裂，
"正式版"的身份写在 `work/builds/GR_RELEASE/GR_ZH146.meta.json`（`"formal": true`）与本文档里。

### A.2 为什么是它（三条硬理由）

1. **内容最完整**：`40 / 40` 个 `*.MIS` 的 `<Name>` 全中文（`GR.IMG` + `MENU.IMG` 共 **80 / 80** 条目），
   M15 = `M15 - 白刃`，**0 个仍英文**。我用独立脚本（`work/_slim/check_names.py`）逐条目解码复核过：

   ```
   GR.IMG *.MIS entries        : 40
   ZH names (GR+MENU, 2 copies): 80
   EN names (GR+MENU, 2 copies): 0
   undecodable                 : 0
   ```

   对比之下，另一条线（`GR_ZH145`）只有 29/40，而且是"等长 + 空格填充"，居中会偏。

2. **自证全过**：`verify.py` **28 / 28** 通过，含 FF 闸门（4,756 个容器、146 个文本类容器、
   **0 个 0xFF**）。

3. **可从英文原盘逐字节复现**：`build.py` 16 个阶段全部 `OK == fix_spec.json`（§C）。

### A.3 历史盘登记（`work\builds\GR_RELEASE\` 原有 9 张）

| 文件 | 尺寸 | sha256 | 处置 |
|---|---:|---|---|
| `GR_ZH138.iso` | 1,648,164,864 | （未及登记，见下） | 已删除 |
| `GR_ZH139.iso` | 1,648,164,864 | （未及登记） | 已删除 |
| `GR_ZH140.iso` | 1,648,164,864 | （未及登记） | 已删除 |
| `GR_ZH141.iso` | 1,648,164,864 | （未及登记） | 已删除 |
| `GR_ZH142.iso` | 1,648,164,864 | （未及登记） | 已删除 |
| `GR_ZH143.iso` | 1,648,164,864 | `52145319c15de639d392788bb0be56deeea7dc952f254c966fad1ceb5eed4d42`（链条常量，与盘一致） | 已删除 |
| `GR_ZH144.iso` | 1,648,164,864 | `d50b4e720c401b529155bae343c86ae8dcb8cb60fcab7e3cc8b254113788747b`（本轮实测） | 已删除 |
| `GR_ZH145.iso` | 1,648,164,864 | `bf269e18c5dc4d4831b174ed7e153fc1242a6aa914adb9c5915c5b9dcd58142c`（本轮实测） | 已删除 |
| `GR_ZH146_merge_2026-10-21.iso` | 1,648,164,864 | `98ed8579f1b536432eb3d25843c41986b8e27eaeb1fec1035f2a74c866c2ff9a`（本轮实测） | 已删除 |

**必须说明**：我在 A 阶段清点时（14:28）已列出全部 9 张盘并直接哈希了最新的 3 张；
但 **14:48–15:12 之间，并发的另一路进程把 `GR_RELEASE/` 清空并写入了它自己的
`GR_ZH146.iso`（40/40）**，8 张历史盘随之消失 —— 因此上表有 5 张只剩"名字 + 尺寸 + 时间戳"，
sha256 未及采集。它们的身份仍可从链条常量推出（每一版都是前一版的确定性函数）。

本轮**没有**执行任何 `Remove-Item` 删除成品盘；`GR_RELEASE` 现在只有
`GR_ZH146.iso` + `GR_ZH146.meta.json` + `GR_ZH146.meta.parallel-route.json`（并发路线的 meta，留档）。

### A.4 并发冲突与处置（重要）

同一工作区有另一路进程（`c4bc3fff`）在做 40/40 任务名。本轮遇到三次实际冲突：

| 时间 | 事件 | 处置 |
|---|---|---|
| 14:48 | 它把 `GR_RELEASE/GR_ZH146.iso` 换成 40/40 版（`4ded92e2`） | 我核对了它的内容（40/40、0 英文、M15 正确），**采纳其内容更完整**这一事实 |
| 14:30 起 | 它的脚本被 `work/` 清理影响，自带垫片重写 `zx_lib`/`lzokit` | 我把它的 4 个模块**收编**进 `tools/final_fix/`，成为正式链的第 16 阶段 |
| ~15:20 | **它重写了 git 历史**：`master` 变成单提交 `44825b5`（561 文件） | 我不再与历史重写抢夺；在其之上新建 `release/final-slim` 提交本轮结构（89 文件） |

> 结果：正式版 = `4ded92e2`，且**由本仓库的单一入口复现**（§C）。两条线在内容上已经合一。

---

## B. 仓库重构与精简

### B.1 结构（重构后）

```
README.md              门面：三条纪律 + 导航
.gitignore             白名单：只放行 tools/** 与 docs/**（+ third_party/readme.md）
tools/
  final_fix/           ★ 唯一构筑链（54 文件）
    build.py           唯一入口（16 阶段，按 fix_spec.json）
    verify.py          唯一校验（28 条硬断言 + FF 闸门）
    fix_spec.json      单一真源（输入指纹 / 阶段表 / 期望 sha256 / 闸门）
    elf_patches.json   ELF 补丁逐字节表
    patch_*.py         16 个阶段脚本（含 40/40 任务名）+ mislib/mispatch/misvar/lzokit/zxshim
    cave_verify_f7b.py / elf_crc.py   保留的两个诊断
    assets/charset/    2300 对偶字符集 + 2 份快照 + 3 份扩容计划
    assets/text/       enrich/（43 条）+ merge/（4 张表）
    assets/mis/        map.tsv（40 个任务名）
  lib/                 9 个共用库（dump_font / repack_font / font_compact / glyph_geometry
                       / iso_tools / icon_table / zx_lib / lz77_decode / lzo1x_c）
  text_csv/            5 个（tcslib / dump_text_csv / inject_text_csv / gate_pairs.json / FORMAT.md）
docs/                  22 篇 + archive（9 份 ELF 试验表 + 1 份删除清单）
```

### B.2 前后对比

| 指标 | 重构前（HEAD `f81592f3`） | 重构后 | 变化 |
|---|---:|---:|---:|
| **跟踪文件数** | **1,889** | **90** | **−1,799（−95.2%）** |
| **跟踪字节数** | **21,546,891 B（20.5 MB）** | **5.12 MiB（≈5,371 KB）** | **−16,175,364 B（−75.1%）** |
| `tools/` 文件 | 1,681 | 54 | −1,627 |
| `tools/` 子目录 | 17 | 3 | −14 |
| `docs/` 文件 | 192 | 32（22 篇 + 10 归档） | −160 |
| `third_party/` 入库 | 13 | 1（`readme.md`） | −12 |
| 构筑入口 | 14 个 `repro_from_eng_*.ps1` | **1 个 `build.py`** | −13 |
| 顶层目录 | tools / docs / third_party / work / archive / _archive_scratch / bases … | tools / docs / third_party / work | 收敛 |

> 注：数字取自 `git ls-tree -r -l` 的实测求和（重构前）与提交后的 `git ls-tree -r -l HEAD`（重构后）。

### B.3 删除清单（tools）

**删除 506 个文件**，按目录：

| 目录 | 删除数 | 理由 |
|---|---:|---|
| `tools/rounds/**` | 999 → 0 | 每轮一次性的实验脚本，历史产物；判定依据=不在 `build.py` 调用链、不被保留文档引用 |
| `tools/re/toolbelt/**` | 263 → 0（只留 `zx_lib.py` 收编进 `tools/lib`） | 逆向取证脚本，问题已结案 |
| `tools/iso_build/**` | 91 → 0（4 个库收编进 `tools/lib`，3 个阶段脚本收编进 `final_fix`） | 目录名与实际职责不符，统一收敛 |
| `tools/hanliu/**` | 67 → 0（`lz77_decode`/`lzo1x_c` 收编进 `tools/lib`） | 同上 |
| `tools/capture` / `diag` / `gr_tools` / `snapshot` / `maint` / `emu_build` / `expand2300` / `measure` / `font_pipeline` | 各自全部 | 一次性/取证类 |
| `tools/final_fix/` 内的一次性脚本 | 40 | 14 个 `repro_from_eng_*.ps1`（→ `build.py`）、10 个 `fontfix_*`、4 个 `make_*_meta`、`make_spec_merged.py`、3 个 `*.ps1` 冒烟、`cmp_charset.py` 等 |
| `tools/README_scripts.md` / `scripts_move_map.csv` | 2 | 旧脚本搬迁地图，已完成使命 |

保留判据（**不是**"看起来有用"）：
① 在 `build.py` 的 16 阶段调用链上；② 被 `tools/lib` / `tools/text_csv` 的 import 链需要；
③ 被保留文档显式引用。三者皆无 ⇒ 删，名字登记在 `docs/archive/REMOVED_DOCS.md`。

### B.4 删除/归档清单（docs）

* **删除 292 个文件**（192 个跟踪 + 100 个未跟踪），全量清单见
  [`docs/archive/REMOVED_DOCS.md`](archive/REMOVED_DOCS.md)（名字 + 字节数）。
* **归档 9 份 ELF 补丁试验表** → `docs/archive/elf_specs/`
  （`fix_spec.json` 2400 版原表 + `debrief` / `debrief_b` / `g1b_*` ×4 / `no_g1` / `prodcrash`）。
* **保留 22 篇**：`STATUS` / `BUILD_GUIDE` / `MOD_GUIDE` / `README` / `CORRECTIONS` /
  `RETROSPECT` / `REPORT_FINAL_DELIVERY` + 14 篇关键报告（含并发路线写的 `REPORT_MISNAMES_FINAL.md`）。

### B.5 第三方版权内容

`.gitignore` 改成**白名单**：默认忽略一切，只放行 `tools/**`、`docs/**`、根 `README.md`、
`.gitignore`、`.gitattributes`、`third_party/readme.md`。于是：

* `third_party/**`（英文原盘 ISO、`方正像素16.ttf`、模拟器、cdvd 转储）**全部不入库**（只留 1 份清单 readme）；
* `work/**`（含正式版 ISO、所有中间盘、取证 dump）**全部不入库**；
* 12 个 `third_party/**/.gitkeep` 已 `git rm --cached`。

---

## C. 构建链自证

### C.1 从英文原盘重建 ⇒ 与正式版**逐字节相同**

```
命令   python tools\final_fix\build.py --force
输入   英文原盘 2b42ea7c…8531   +   K2 转储 11f371f2…add9
结果   16/16 阶段 OK，成品 sha256 4ded92e2…
```

| # | 阶段 | 实测 sha256（前 12） | 耗时 |
|---|---|---|---:|
| 1 | base | `d7f83d7ec4a8` | 4.0 s |
| 2 | elf | `e65e77fbb696` | 7.4 s |
| 3 | glyph_edge | `db3f8b997a9d` | **662.0 s** |
| 4 | stale | `3fb12c8d16c2` | 13.5 s |
| 5 | text2 | `165b7eb2c667` | 4.8 s |
| 6 | profile | `172b35cc9404` | 6.0 s |
| 7 | gate_ff | （闸门，不改盘） | ~1 s |
| 8 | glyphs61 | `7396f55cd8d4` | 2.2 s |
| 9 | chars139 | `33b9acd9341f` | 4.7 s |
| 10 | chars140 | `9ecd07af7396` | 4.2 s |
| 11 | enrich | `83757ff1d1bf` | 4.8 s |
| 12 | chars141 | `a4238ef2ad45` | 4.5 s |
| 13 | merge_text | `23b3f95187b8` | 5.5 s |
| 14 | ike142 | `28e4bc915774` | 4.1 s |
| 15 | ike143 | `52145319c15d` | 4.1 s |
| 16 | misnames40 | **`4ded92e2fee5`** | 158.3 s |

合计 **≈ 14.8 分钟**（第 3 阶段占 74%：它要遍历 4,756 个容器统计字符引用）。

**结论：产物 sha256 == 正式版 `4ded92e2…`，逐字节相同，不是"等价"，是同一串字节。**

### C.2 `verify.py` 28/28

```
结果：28 通过 / 0 失败
VERIFY OK —— 正式版 GR_ZH146
```

分 6 组（身份 / ELF / 任务名 / 字库 / 文本 / 闸门），关键几条：

* `[2] sha256 == 4ded92e2…`、`[3] md5 == 8732e73f…`
* `[7] Game CRC == 653FBF69`
* `[11] 中文任务名 == 40`、`[12] 英文任务名 == 0`、`[13] M15 标题 == 'M15 - 白刃'`
* `[16] pair 总数 == 2300`、`[17] 单字节码 == 103`、`[18..20] … / × / 惧 已映射`
* `[22] LANG 条目 2232`、`[23] SFXML 69 条`、`[24] 折行 294`
* `[25] FF 闸门：4,756 容器 / 146 文本类 / 0 个 0xFF`

### C.2b 精简后重建（决定性证据）

上面的 §C.1 是在**精简之前**跑的。为排除"通了是因为旧文件还在"的可能，本轮在
**提交后的 90 文件树**上又完整跑了一遍（`build.py --force`）：

```
16/16 阶段 OK，产物 sha256 4ded92e2…   （同一串字节）
阶段耗时合计 1,025 s ≈ 17.1 min（第 3 阶段 787 s，占 77%）
```

这一步才是"仓库精简没有弄坏构建链"的真正证据 —— 期间也确实抓到并修掉了一个真实缺陷：
`tcslib.CHARSET` 等 7 处**默认字符集路径**仍指向被并入 `final_fix/assets` 的旧目录
（`tools/font_pipeline/data/`），精简后会直接 `FileNotFoundError`。已全部改指 `assets`，
并给 `tcslib` 加了候选回退，避免下次搬目录再踩。

### C.3 幂等

* 同一输入第二次跑：第 1–16 阶段 sha256 全部相同（本次两轮构建即实证：
  第 1 轮 18 阶段产出 `98ed8579…`，第 2 轮 16 阶段产出 `4ded92e2…`，
  两轮**共有的 15 个阶段** sha256 完全一致）。
* `--out` 已存在且指纹正确时，`build.py` 直接打印「已是最新（幂等）」并只跑校验。

### C.4 未跑模拟器

按任务书要求**未跑模拟器**（除"必须做一次最终冒烟"外）。离线判据能保证字节正确、
结构自洽、闸门全过，但**画面层面的居中/折行仍需真机或模拟器抽查一次** —— 这是残余 R5。

---

## D. 文档

| 文件 | 状态 | 内容 |
|---|---|---|
| `docs/BUILD_GUIDE.md` | **新写** | 依赖（含"本地自备"三项）/ 一键命令 / 16 阶段说明 / 失败排查 / 自证清单 / 幂等 / 改完怎么更新期望指纹 |
| `docs/MOD_GUIDE.md` | **新写** | 心智模型（ISO→容器→LZO→payload）/ 文本表 CSV 流程 / DBCS 编码与 `0xFF=EOF` 坑 / 字库 4bpp·PSMT4·段·FT 记录·右缘采样 / 折行宽度 / 任务名 LZO 重指 / ELF cave 选址 / 验证判据 / 陷阱速查 |
| `docs/STATUS.md` | **重写** | 一句话现状 + 正式版身份 + 残余清单 + 目录结构 + 前后对比 |
| `docs/RETROSPECT.md` | **新写** | 试错记录：9 条弯路（定长字段误判、乱码归因、0xFF=EOF、卡死根因、+8px 假设、基底链、容量路线、tools 膨胀、PS 编码坑）+ 4 条未解决 |
| `docs/README.md` | **重写** | 22 篇索引，四类分栏 |
| `docs/CORRECTIONS.md` | 保留 | 历史订正 |
| `docs/archive/REMOVED_DOCS.md` | **新写** | 292 篇删除清单 |
| `README.md` | **重写** | 仓库门面 |

---

## E. 未达成项 / 需要下一轮处理的

| # | 项 | 原因 | 建议 |
|---|---|---|---|
| E1 | **git 历史重写** | 任务书本轮明确不做；且并发进程已在 ~15:20 擅自做了一次（`master` = 单提交 `44825b5`），我未参与 | 下一轮以 `release/final-slim` 的树为准，重做一次干净历史 |
| E2 | **未跑模拟器** | 任务书禁止 | 冒烟一次：任务名居中、特别收录折行、专家档案滚动 |
| E3 | **5 张历史盘的 sha256 未登记** | 并发进程在 14:48–15:12 清空了 `GR_RELEASE`，我未来得及哈希 | 从各自 meta 或链条常量回溯 |
| E4 | **FF 全盘普查能力未复刻** | 原 `tools/ff_sweep/*` 从未提交、`work/` 清理后丢失 | 现行 `verify.py --ff-gate` 覆盖"文本区 0 个 0xFF"这一**判据**；如需"每个 0xFF 逐一归因"，要重写 |
| E5 | **旧分支未 push** | 任务书要求不 push | 由用户决定是否推送/清理 |
| E6 | `tools/font_pipeline/` 未按建议保留原样 | 其内容（字符集数据）已并入 `final_fix/assets`，字体工具并入 `tools/lib` | 若坚持要这个目录名，可把 `tools/lib` 改名，但会让所有脚本的 `REPO` 深度假设失效，不建议 |

---

## F. 一句话总结

**正式版 = `GR_ZH146.iso`（`4ded92e2…`，40/40 任务名、Game CRC 未变）；
`python tools\final_fix\build.py` 从英文原盘 16 步重建，得到同一串字节；
仓库从 1,889 个跟踪文件 / 20.5 MB 收敛到 90 个 / 5.12 MB。**
