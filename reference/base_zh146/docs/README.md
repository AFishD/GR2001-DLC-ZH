# docs 索引

22 篇，分四类：**现状** · **指南** · **关键报告** · **试错/归档**。
其余历史文档（292 篇）已移除，清单见 [`archive/REMOVED_DOCS.md`](archive/REMOVED_DOCS.md)，
内容仍可从 git 历史取回。

---

## 一、现状与指南（先看这四篇）

| 文件 | 作用 | 什么时候看 |
|---|---|---|
| [`STATUS.md`](STATUS.md) | 一句话现状 + 正式版身份 + 残余清单 + 目录结构 | 每次回来先看 |
| [`BUILD_GUIDE.md`](BUILD_GUIDE.md) | 环境/依赖/一键构建/18 阶段说明/失败排查/自证清单 | 要把盘做出来 |
| [`MOD_GUIDE.md`](MOD_GUIDE.md) | 文本表 / 字库图集 / DBCS 编码 / 折行 / 任务名 / ELF 补丁的做法与陷阱 | 要改内容 |
| [`CORRECTIONS.md`](CORRECTIONS.md) | 历史订正记录（哪些早期结论被推翻） | 发现文档互相矛盾时 |

## 二、关键报告（14 篇，按主题）

### 卡死（游戏内画面定死 / 指针错）
| 文件 | 内容 |
|---|---|
| [`REPORT_DISASM_ROOTCAUSE.md`](REPORT_DISASM_ROOTCAUSE.md) | 根因：分配器桶链被写坏后野读写 |
| [`REPORT_COMBFIX.md`](REPORT_COMBFIX.md) | 四件套总纲（F4 / OOMFIX / F7 / F7b），239 B / 70 段 |
| [`REPORT_F7B.md`](REPORT_F7B.md) | 第四件 F7b：unsorted 桶快路径 |

### 字库与图集
| 文件 | 内容 |
|---|---|
| [`REPORT_FONT_FIX.md`](REPORT_FONT_FIX.md) | FONT.RES 结构、4bpp/PSMT4 图集、repack 口径 |
| [`REPORT_EXPAND_2300.md`](REPORT_EXPAND_2300.md) | 对偶容量扩到 2300（lead 0xA1..0xBA × trail 0xA1..0xFE） |
| [`REPORT_GLYPH_FIX.md`](REPORT_GLYPH_FIX.md) | ★ 右缘采样缺陷（col 63 / FT `u1=1024`）⇒ "乱码" |

### 文本与编码
| 文件 | 内容 |
|---|---|
| [`REPORT_TEXT_FIX2.md`](REPORT_TEXT_FIX2.md) | 文本层修正 #2 |
| [`REPORT_MERGE_141.md`](REPORT_MERGE_141.md) | 合并文本层：39 正文 / 93 空行 / 57 标题 / 26 LANG |
| [`REPORT_PROFILE_SCROLL.md`](REPORT_PROFILE_SCROLL.md) | ★ `0xFF` 被 XML 词法器当 EOF ⇒ 专家档案被截断 |
| [`REPORT_FF_SWEEP.md`](REPORT_FF_SWEEP.md) | 全盘 0xFF 普查（4713 容器 / 2648 万个 0xFF，A 类 = 0） |

### 排版与任务名
| 文件 | 内容 |
|---|---|
| [`REPORT_ZH143_WRAP8.md`](REPORT_ZH143_WRAP8.md) | 特别收录折行 286→294（含"+8px 只放标点"假设的证伪） |
| [`REPORT_MISSION_NAME.md`](REPORT_MISSION_NAME.md) | ★ M15 `White Razor` → `白刃` 的 v3 口径（LZO 令牌重编码） |
| [`REPORT_MIS_NAMES.md`](REPORT_MIS_NAMES.md) | 29/40 个 `*.MIS` 的 `<Name>` 汉化（历史：等长 + 空格填充） |
| [`REPORT_MISNAMES_FINAL.md`](REPORT_MISNAMES_FINAL.md) | ★ **40/40** 个任务名（可变长度 / 零填充）—— 现行正式版用的就是这一版 |

### 术语
| 文件 | 内容 |
|---|---|
| [`REPORT_TERM_UNIFY.md`](REPORT_TERM_UNIFY.md) | 术语统一（人物/兵种/装备译名） |

## 三、试错与交付

| 文件 | 作用 |
|---|---|
| [`RETROSPECT.md`](RETROSPECT.md) | **试错记录**：9 条走过的弯路 + 4 条未解决项 |
| [`REPORT_FINAL_DELIVERY.md`](REPORT_FINAL_DELIVERY.md) | 本轮（收尾交付）全部硬数字：选盘理由、结构前后对比、删除清单、复现结果 |

## 四、归档

| 路径 | 内容 |
|---|---|
| [`archive/elf_specs/`](archive/elf_specs/) | 9 份 ELF 补丁试验表（含被否决的 G1 / debrief / prodcrash 变体） |
| [`archive/REMOVED_DOCS.md`](archive/REMOVED_DOCS.md) | 292 篇被移除文档的清单（名字 + 字节数） |

---

## 约定

* **正文只写结论与判据**，过程放报告里；报告写完就不再改（除订正）。
* 任何"我猜"的句子要么删掉，要么标 `待证`。
* 文档里出现的路径必须真实存在（本轮把 `tools/iso_build`、`tools/re`、`tools/hanliu`
  等旧路径全部收敛到 `tools/final_fix` 与 `tools/lib`）。
