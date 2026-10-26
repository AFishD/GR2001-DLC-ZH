# STATUS —— 现状（2026-10-21 · 收尾交付）

> **一句话**：汉化内容已完工，本轮把仓库收敛成「一条构筑链 + 一份正式版 + 22 篇文档」，
> 并且**从英文原盘一键重建的产物与正式版逐字节相同**。

---

## 1. 正式版身份

```
文件      work\builds\GR_RELEASE\GR_ZH146.iso     ← 名字保持不变（改名只会让 CRC 认知混乱）
尺寸      1,648,164,864 B
sha256    4ded92e2fee535ac00893af60faee630323af124aa38a89d1777d1721d04617a
md5       8732e73f04e0af18060b0e990ec94a6c
ELF       SLUS_206.13 @ LBA 295 / 37,453,732 B
          sha256 a0c8499cf30f1cc5c44dfb49502270ed0ecbdccb30c023246b227591c40ba12e
Game CRC  653FBF69   ⇒ 即时存档名 SLUS-20613 (653FBF69).01.p2s（旧存档继续可用）
身份文件  work\builds\GR_RELEASE\GR_ZH146.meta.json  （"formal": true）
```

**为什么是它**（详见 `docs/REPORT_FINAL_DELIVERY.md` §A.2）：

1. **内容最完整**：40/40 个 `*.MIS` 的 `<Name>` 全中文（`GR.IMG`+`MENU.IMG` 共 80/80 条目），
   M15 = `M15 - 白刃`，**0 个仍英文**；可变长度 + **零填充**（不是早期的"空格凑长度"）。
2. **自证全过**：`verify.py` 28/28，含 FF 闸门（4,756 容器 / 146 文本类 / 0 个 `0xFF`）。
3. **可逐字节复现**：`build.py` 16 阶段从英文原盘重建，产物 sha256 == `4ded92e2…`；
   **精简后的提交树又完整重跑了一遍，仍是同一串字节**。
4. ELF 0 字节改动 ⇒ Game CRC 未变，旧存档继续可用。

### 内容自评

| 项 | 数量 |
|---|---|
| 对偶字槽 | **2,300**（`lead 0xA1..0xBA` × `trail 0xA1..0xFE`） |
| 已画字形 | **1,954**，空 PUA 槽 ~300 |
| 单字节码 | 103 |
| 任务名中文 | **40 / 40**（M15 = `M15 - 白刃`，80/80 条目） |
| 文本层 | LANG 2,232 条 + SFXML 69 条 `<text>` + 39 条正文 / 93 空行 / 57 特别收录标题 / 26 LANG 行 |
| 特别收录折行 | **294 px**（面板 306） |

---

## 2. 残余清单（没做完的，别当成做完了）

| # | 残余 | 影响 | 下一步 |
|---|---|---|---|
| R1 | **FF 全盘普查能力未复刻** | 原 `tools/ff_sweep/*`（全盘 2,648 万个 0xFF 逐个归因）从未提交，`work/` 清理后丢失 | 现行 `verify.py --ff-gate` 已覆盖**判据**（文本区 0 个 `0xFF`）；如需"每个 0xFF 逐一归因"，要重写 |
| R2 | **git 历史里仍有旧 blob** | 历史提交含旧工具 / 旧 dump；且并发进程已在 2026-10-21 ~15:20 擅自重写过一次（`master` = 单提交 `44825b5`） | 下一轮以 `release/final-slim` 的树为准，重做一次干净历史 |
| R3 | **未跑模拟器** | 本轮只做离线逐字节自证 | 冒烟一次：任务名居中、特别收录折行、专家档案滚动 |
| R4 | **旧分支未 push / 未清理** | `archive/*`、`fix/*`、`feat/*`、`round*` 等 | 由用户决定推送或删除 |
| R5 | **5 张历史盘 sha256 未登记** | 并发进程在 14:48–15:12 清空了 `GR_RELEASE`，未及哈希 | 从各自 meta 或链条常量回溯（见 `REPORT_FINAL_DELIVERY.md` §A.3） |

---

## 3. 目录结构（本轮重构后）

```
README.md                仓库门面（三条纪律 + 导航）
.gitignore               白名单：只放行 tools/** 与 docs/**
tools/
  final_fix/             ★ 唯一构筑链（54 文件）
    build.py             【唯一入口】16 阶段，按 fix_spec.json 执行
    verify.py            【唯一校验】28 条硬断言 + FF 闸门
    fix_spec.json        【单一真源】输入指纹 / 阶段表 / 期望 sha256 / 闸门
    elf_patches.json     ELF 补丁逐字节表（apply_fix.py 输入）
    README.md            用法速查
    assets/charset/      2300 对偶字符集（+ .before_zh130 / .before_zh139 快照）
    assets/text/         enrich/（43 条富文本）+ merge/（4 张合并表）
    assets/mis/          map.tsv（40 个任务名对照）
    *.py                 16 个阶段脚本 + mislib/mispatch/misvar/lzokit/zxshim + 2 个保留诊断
  lib/                   共用库：dump_font / repack_font / font_compact / glyph_geometry
                         / iso_tools / icon_table / zx_lib / lz77_decode / lzo1x_c
  text_csv/              文本表工具：tcslib / dump_text_csv / inject_text_csv
                         + gate_pairs.json + FORMAT.md
docs/                    22 篇 + archive/（9 份 ELF 试验表 + 1 份删除清单）
work/                    ★ 不进库 —— 中间盘 / 正式版 / 取证
  builds/GR_RELEASE/GR_ZH146.iso   ← 正式版
third_party/             ★ 不进库 —— 本地自备（英文原盘 / 转储 / TTF），只留 readme.md
```

### 和重构前比

| | 重构前 | 重构后 | 变化 |
|---|---:|---:|---:|
| 跟踪文件数 | 1,889 | **90** | −1,799（−95.2%） |
| 跟踪字节数 | 21,546,891 B（20.5 MB） | **5.12 MiB（≈5,371 KB）** | −16,175,364 B（−75.1%） |
| `tools/` | 1,681 文件 / 17 子目录 | 54 文件 / 3 子目录 | |
| `docs/` | 192 文件（100+ 篇散报告） | 32（22 篇 + 10 归档） | |
| `third_party/` 入库 | 13 文件 | 1（`readme.md`） | |
| 构筑入口 | 14 个 `repro_from_eng_*.ps1` | **1 个 `build.py`** | |

---

## 4. 怎么重建 / 怎么改

* 重建：`python tools\final_fix\build.py --force` → 见 `docs/BUILD_GUIDE.md`
* 改内容：见 `docs/MOD_GUIDE.md`
* 自证：`python tools\final_fix\verify.py`

---

## 5. 历史盘登记

见 `docs/REPORT_FINAL_DELIVERY.md` §A.3（9 张盘的处置；其中 3 张有本轮实测 sha256）。
