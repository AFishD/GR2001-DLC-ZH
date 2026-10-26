# REPORT_FF_SWEEP — 全盘 0xFF（汉字「著」的单字节码）普查 + 认证出盘（GR_ZH137）

> 轮次：**GR_PROFILE3 / round FF-SWEEP** · 日期 2026-10-19
> 普查对象（只读）：`work\builds\GR_PROFILE2\GR_ZH136.iso`
> （sha256 `172b35cc940431e99a128ed1ff5d5f80941362a2bf1a281d2a0d8b09ee408140`，ELF Game CRC `653FBF69`）
> 对照原盘（只读）：`third_party\orig\ps2\Tom Clancy's Ghost Recon (USA).iso`
> （sha256 `2b42ea7ce9bd0a85972a07ca59b1b9d58…` 全文见 §3.0）
> 写入：`work\builds\GR_PROFILE3\**`、`tools\ff_sweep\**`、`tools\final_fix\repro_from_eng_zh137.ps1`、本文件
> **未动**：`third_party\**`、`work\builds\GR_PROFILE2\**`（只读）、`work\builds\GR_RELEASE\**`（只读）、
> 用户 PCSX2 目录、git、既有 spec/脚本

---

## 0. 一句话结论

**A 类 = 0。** 全盘 **4,713 个容器**、**26,483,238 个 0xFF 字节**逐一过结构判定后，
**没有任何一个 0xFF 落在会被 XML 词法器读到的文本里**：

* `MENU.IMG#283 EN_SPECIAL_FEATURE.XML`（上一轮修的 22 处）**已经是 0 个**（`ff=0`，69 条 `<text>` 全干净）；
* 全部 **10 份** `*_SPECIAL_FEATURE.XML`（EN/DE/ES/FR/IT × MENU/GR）**都是 0 个 0xFF**（其中 9 份**与英文原盘逐字节相同**）；
* 语言表 `EN_STRINGS.RES`（MENU#25 + GR#902）**条目正文里 0 个 0xFF**；两份各剩的 **1 个 0xFF 是 u32 长度字段 `0xFF000000`=255**（结构字节，不是文本）；
* 其余 0xFF 全部落在**与英文原盘逐字节相同**的二进制资产里（贴图/调色板/视频音频流/ELF 代码），
  以及**我们改过的** 19 个容器中的非文本区（字库图集像素、CLUT、IKE 对象记录、内存卡贴图、ELF 代码/表）。

⇒ 上一轮的 22 处就是**全部**。本轮**不需要任何字节改动**，因此交付盘
`GR_ZH137` = `GR_ZH136` 的**认证副本（逐字节相同）**：本轮的产品是"**证明已经没有残留**"，
不是又一份补丁；`GR_ZH137.iso` 的意义是"这一版经过了全盘 0xFF 普查闸门"。

推荐盘：`work\builds\GR_PROFILE3\GR_ZH137.iso`
**sha256 `172b35cc940431e99a128ed1ff5d5f80941362a2bf1a281d2a0d8b09ee408140`** /
md5 `a9c18781ba6d141a489e6acb3aa8f630` / 1,648,164,864 B / **ELF Game CRC `653FBF69`（未改代码 ⇒ 旧存档可用）**

---

## 1. A —— 普查方法（可复跑，只读）

### 1.1 普查层级：容器载荷（引擎真正看到的那一层）

原始 ISO 是 1.57 GB 的压缩/二进制数据，直接数 0xFF 没有意义；引擎只会读**容器载荷**
（LZO 子流解压后的字节）。工具链：

| 步骤 | 工具（本轮新增，`tools\ff_sweep\`） | 做什么 |
|---|---|---|
| ① 容器枚举 | `recon_containers.py`（复用 `font_usage.build_container_list`） | **4,713** 个容器（GR.IMG + MENU.IMG + 22 个 ISO 独立文件），逐个解压、数 0xFF |
| ② 结构判定 | `sweep_ff.py` | 对每个容器算出**全部文本区间**：LANG 条目正文 / `<text>` 正文 / 每个 XML 属性 / TXT 全文 / MIS·ATR（XML 伪装）；再逐 0xFF 落类 A/B/C |
| ③ 交叉验证 | `scan_textual_ff.py` | **不依赖容器格式**：用 numpy 找出"两侧都是本盘对偶码"的 0xFF，再用字符集解码逐一确认（必须解成「著」且落在 ≥2 个连续汉字里、窗口可映射率 ≥0.90） |
| ④ 归属取证 | `evidence_touched.py` / `ff_locate.py` / `probe_lang_entry.py` / `pak_probe.py` / `ff_pages.py` | 对**被本地化写过的**容器逐字节对比英文原盘，给出"这个 0xFF 是原来的 / 是结构字段 / 是像素"的证据 |
| ⑤ 出表 | `census_table.py` / `report_stats.py` | 容器级 + 逐字节清单（CSV）与统计 |
| ⑥ 出盘闸门 | `gate_no_ff_text.py` | **构建闸门**：只要任一文本区间出现 0xFF 就 FAIL（本轮已纳入复现脚本第 [7] 步） |

### 1.2 总数（容器 × 0xFF）

来源：`work\builds\GR_PROFILE3\out\sweep_zh136.json` + `census_summary.json`

| kind | 容器数 | 含 0xFF 的容器 | 0xFF 字节数 | 载荷字节数 | 本地化改过 | **A 类** |
|---|---:|---:|---:|---:|---:|---:|
| MEDIA（PSS/SS/TM/M2V 视频音频流） | 310 | 275 | 20,784,773 | 1,363,099,219 | 0 | **0** |
| RSB（贴图包） | 1506 | 1424 | 2,969,523 | 176,782,940 | 9 | **0** |
| OTHER（BMB/BMZ/MOL 等） | 1209 | 571 | 2,060,983 | 51,755,128 | 0 | **0** |
| ELF（SLUS_206.13 主程序） | 1 | 1 | 432,378 | 37,453,732 | 1 | **0** |
| PAK（COMMON.PAK 等） | 44 | 38 | 143,936 | 20,243,045 | 2 | **0** |
| RES（FONT/IKE/DE·ES·FR·IT 语言表） | 13 | 3 | 72,546 | 2,124,519 | 3 | **0** |
| ISO_FILE（SYSTEM.CNF/*.IRX/IOPRP 等） | 22 | 21 | 19,097 | 1,187,290 | 0 | **0** |
| **LANG（EN_STRINGS.RES ×2）** | 2 | 2 | **2** | 257,213 | 2 | **0** |
| SFXML（EN_SPECIAL_FEATURE.XML ×2） | 2 | **0** | **0** | 232,974 | 1 | **0** |
| XML（其它配置 + 德/西/法/意 SF 副本） | 35 | **0** | **0** | 1,321,879 | 0 | **0** |
| MIS（任务数据，实为 XML） | 92 | **0** | **0** | 5,279,740 | 0 | **0** |
| TXT（CONSOLE/CONTROLS/EN_STRINGS…） | 17 | **0** | **0** | 118,825 | 1 | **0** |
| ATR（人物/队伍定义，实为 XML） | 1460 | **0** | **0** | 889,234 | 0 | **0** |
| **合计** | **4713** | **2335** | **26,483,238** | **1,660,745,738** | **19** | **0** |

* **A 类 0 处 / B 类 26,483,238 处 / C 类 0 处**（分类总数 == 0xFF 总数，无遗漏）。
* **4,694 个容器与英文原盘逐字节相同**（本地化从未写过它们）⇒ 里面的 0xFF 是**原版内容**，与中文翻译无关。
* 剩下的 **19 个容器**是本轮全部需要逐个交代的对象（§1.4）。

### 1.3 只可能出现在文本里的 0xFF：三张表全部为 0

| 检查 | 覆盖 | 0xFF | 证据文件 |
|---|---|---|---|
| LANG 条目**正文** | 2 份 × 2,232 条 | **0** | `gate_zh137.json` |
| `<text>` 正文 | 10 份 SF 副本（共 690 条）+ 其它 XML/MIS/ATR | **0** | `gate_zh137.json` |
| XML **属性值**（含 123 个中文标题） | 全部 XML 副本 | **0** | `gate_zh137.json` |
| **合计（闸门口径）** | **1,608 个文本容器 / 143,599 个文本区间 / 2,436,537 B** | **0** | `work\builds\GR_PROFILE3\out\gate_zh137.json` |

**反向对照（证明闸门真的抓得住）**：同一把闸门跑上一版 `GR_RELEASE\GR_ZH134.iso`
→ `MENU.IMG#283` 报 **22 个 0xFF 在文本区间内 ⇒ FAIL**（`out\gate_zh134.json`）；
跑 `GR_ZH137` / `GR_ZH136` / 英文原盘 → **PASS（0）**。

**格式无关的第二把网**（`scan_textual_ff.py`，decode-verified）：
全盘有 **37 个容器、89 处**"0xFF 夹在汉字码之间"的候选；
**89/89 处**在英文原盘的**同一个偏移**也是 0xFF，且 37 个容器**全部与英文原盘逐字节相同**
（命中全在 `.BMZ/.BMB/.MOL/.PSS/.TM` 贴图与视频流里，是压缩数据的巧合）⇒ **新增 0 处**。

### 1.4 19 个"本地化写过"的容器：逐个交代（B 类判定依据）

来源：`out\evidence_touched.txt`、`out\census_ff_touched.csv`、`out\census_containers.csv`

| # | 容器 | kind | 载荷变化 | 0xFF（新/旧） | 判定与依据 |
|---|---|---|---:|---:|---|
| 1 | `MENU.IMG#283 EN_SPECIAL_FEATURE.XML` | SFXML | 116,430→**116,486** | **0 / 0** | 22 处已修净；69 条 `<text>` + 397 个属性全无 0xFF |
| 2 | `MENU.IMG#25 EN_STRINGS.RES` | LANG | 128,545（等长） | **1 / 0** | 唯一 1 个 = `@0xB053` **u32 长度字段 `FF 00 00 00`=255**（G047.I008 的正文长 255 B）；**正文无 0xFF**（§1.5） |
| 3 | `GR.IMG#902 EN_STRINGS.RES` | LANG | 128,668（等长） | **1 / 0** | 同上（同一张表的第二份拷贝，同一偏移 0xB053） |
| 4 | `MENU.IMG#3 COMMON.PAK` | PAK | 400,659→**468,243** | 838 / 838 | 字库图集：`new_font_revised` 1024×644 PSMT4 像素 + GIF 包头 + CLUT；**无文本结构**；0xFF 与英文副本同型（270 段长度 3 + 28 个孤立） |
| 5 | `GR.IMG#3451 COMMON.PAK` | PAK | 400,659（等长） | 838 / 838 | 同一资源的另一份；**0xFF 逐偏移与英文原盘相同**（新增 0） |
| 6 | `MENU.IMG#4 / GR.IMG#906 FONT.RES` | RES | 7,222→5,942 | **0** / 7 | 改后已无 0xFF |
| 7 | `MENU.IMG#282 NTSC_IKE.RES` | RES | 319,009（等长） | 24,182 / 24,182 | **新增 0 个 0xFF**；全容器只有 **4 个字节不同**（OBJ0..3 行高 31→26 的历史补偿），0xFF 全在 IKE 调色板/对象数据里 |
| 8 | `GR.IMG#912 IKE.RES` | RES | 319,009（等长） | 24,182 / 24,182 | **与英文原盘逐字节相同** |
| 9–17 | `MENU.IMG#5/6/10/11/15/16/19/20/21 *_MESSAGE_MC_*.RSB` | RSB | 69,404（等长） | 各 256 / 256 | 内存卡提示贴图；**0xFF 逐偏移与英文原盘相同**（新增 0）；差异全在贴图像素块（最长连续改动 1,310 B） |
| 18 | `MENU.IMG#30 EN_STRINGS.TXT` | TXT | 6,930→6,628 | **0 / 0** | 纯文本清单，改后无 0xFF |
| 19 | `ISO_FILE SLUS_206.13`（ELF） | ELF | 37,453,732（等长） | 432,378 / 432,383 | 代码/数据字节（481 段补丁，2,089 B）；**格式无关扫描在 ELF 里 0 处"汉字夹 0xFF"**；XML 词法器从不解析 ELF |

> 结论：**没有任何一个 0xFF 位于会被 XML 词法器读到的文本里**（A=0）；
> 所有"文本区"的 0xFF 计数为 0；所有"非文本区"的 0xFF 都有上面的逐容器证据。

### 1.5 `EN_STRINGS.RES` 的 2 个 0xFF：是长度字段，不是文本（本轮最重要的纠偏）

`probe_lang_entry.py` 实读（`out\probe_lang_b053.txt`）：

```
entry #764  G047.I007  record[0xB048..0xB053) len=5    data='10:00'
entry #765  G047.I008  record[0xB053..0xB158) len=255  data='欢迎参加第一次战术演习。本次任务的目标是消灭对方部队。{p}…'
raw:  … 05 00 00 00 31 30 3A 30 30 00 00 | FF 00 00 00 | B5 EC AA C8 …
                     ↑ 上一条记录尾             ↑ 本条 u32 长度 = 255   ↑ 正文起点
```

* 0xFF 是 **`0xFF000000` 的低字节**（长度 255），由 **译文恰好 255 字节**引起（英文原文更短 ⇒ 原盘这里没有 0xFF）。
* 语言表是**长度前缀**格式，引擎按 `len` 读，不做"0xFF=EOF"判定 ⇒ **不截断、不缺字**。三条证据：
  1. **解析自洽**：`parse_lang` 走过这个 0xFF 字节后，**后面 1,467 条记录全部正常解析**
     （合计 2,232 条，`used_end=71,178`，且 `G047.I009` 正好从 `0xB158` 开始 = 长度 255 的下一格）
     —— 如果这个字节被当成"文本/终止"，后面的表结构不可能是完整对齐的；
  2. **同一读取器的实机表现**：训练简报屏 `runs\live137c\c_t2.png`（`信息 / 训练1 - 越野训练 /
     March 15, 2008 | 13:00 | 晴天 / 任务目标`）全部来自这张语言表的长度前缀条目，整屏正常；
  3. **本盘 22 处已修**：XML 侧才是"0xFF=EOF"的那条路（§0/§2），与语言表读取器无关。
* 因此这是 **B 类（结构字段）**，**不改**：为消掉它去改文本长度属于"为指标改内容"，本轮明确拒绝。
  （诚实说明：我们**没有**专门为"某一条 255 字节条目"的所在屏拍照；上面的 2 是同读取器的旁证。）

### 1.6 其余 B 类的判定依据（为什么它们"不属于文本"）

| 判据 | 用在哪 | 说明 |
|---|---|---|
| **载荷与英文原盘逐字节相同** | 2,320 个含 0xFF 的容器 | 本地化从未写过这些容器 ⇒ 不可能是中文「著」；原版就这么发布 |
| **结构定位**：0xFF 落在已知文本区间之外 | LANG ×2（长度字段）、TXT/XML/MIS/ATR（0 个） | 结构解析给出的区间是"引擎按文本读"的**全部**字节 |
| **格式无关复检**：0xFF 两侧不是汉字码 / 解码后落进私有区 | 所有二进制容器 | `scan_textual_ff.py` 的 89 处命中全部被"同偏移在英文原盘也是 0xFF"解释 |
| **像素/调色板**：PAK/RSB/IKE 的 0xFF 位于 PSMT4/CLUT/贴图块内 | COMMON.PAK、9 个 MESSAGE RSB、NTSC_IKE | `pak_probe.py` / `ff_pages.py` 的页直方图 + PAK 记录定位 |
| **代码/数据**：ELF 的 0xFF 是程序字节 | SLUS_206.13 | 格式无关扫描 0 命中；2,089 B 差异逐段对应历年 ELF 补丁 |

### 1.7 对上一轮报告的两处订正（诚实登记）

1. 上一轮 §5.2 写"DE/ES/FR/IT 四种语言的 SFXML 里也各有 0xFF" —— **本轮实测：0 个**
   （10 份 SF 副本全 `ff=0`，其中 9 份与英文原盘逐字节相同；`out\sfxml_copies.txt`）。
2. 上一轮 §4 让用户去"特别收录 → 武器 → **AK-74**"复核 —— **该条目不存在**：
   `Weapon` 工作室只有 31 件（定向地雷(M18)…传感器(AN/GSQ-187)）。
   被改的那条是 **`AN-94 突击步枪`**（正文里提到"俄制 AK-74 的继任者…这明显提高了射击精度"）。
   本轮已改到正确的条目上实拍（§3.4-②）。

---

## 2. B —— 替换清单与偏移账：**空**

| 项 | 值 |
|---|---|
| A 类处数 | **0** |
| 本轮文本替换 | **无**（0 处） |
| 容器内长度变化 / CRLF 尾巴冲销 | **无**（blob 长度全部不变） |
| 条目表展开尺寸变化 | **无** |
| ELF 改动 | **无**（0 字节；Game CRC 仍 `653FBF69`） |
| ISO 整体差异 | **0 字节**（`make_zh137.py` 第 5 项自证：0 differing chunk） |

作为参照，上一轮那 22 处（**已在本盘内，本轮只是复核**，`out\census_ff_touched.csv` 可查全部逐字节记录）：

| 组 | 处数 | 旧字节 → 新字节 | 语义 |
|---|---:|---|---|
| 「显著」→「明显」 | 17 | `A3 DC FF` → `A4 CB A3 DC` | 显 a3dc 保留；著 FF → 明 a4cb（+1 B，由 `</SpecialFeatures>` 后的 CRLF 填充尾巴冲销） |
| 「卓著」→「卓越」 | 5 | `AD EE FF` → `AD EE A1 D2` | 卓 adee 保留；著 FF → 越 a1d2（+1 B，同上） |

磁盘上没有 "A 类替换清单"可写 —— 因为**普查证明已经没有了**。

---

## 3. C —— 验证（全部数字）

### 3.0 指纹

| 对象 | sha256 | 备注 |
|---|---|---|
| 英文原盘 | `2b42ea7ce9bd0a85972a07ca59b1b9d79422ed318b85737db3cfd17daa788531` | 只读 |
| 普查对象 GR_ZH136 | `172b35cc940431e99a128ed1ff5d5f80941362a2bf1a281d2a0d8b09ee408140` | 只读 |
| **交付盘 GR_ZH137** | `172b35cc940431e99a128ed1ff5d5f80941362a2bf1a281d2a0d8b09ee408140` | **与 ZH136 逐字节相同** |
| GR_ZH137 md5 | `a9c18781ba6d141a489e6acb3aa8f630` | |
| 尺寸 | 1,648,164,864 B | 不变 |
| ELF（LBA 295，37,453,732 B） | sha256 `a0c8499cf30f1cc5c44dfb49502270ed0ecbdccb30c023246b227591c40ba12e` | **Game CRC `653FBF69`** |

### 3.1 静态自证（`work\builds\GR_PROFILE3\GR_ZH137.meta.json`，**12/12 PASS**）

| # | 项 | 结果 |
|---|---|---|
| 1 | 基底 sha256 == 声明的 GR_ZH136 | ✓ `172b35cc…408140` |
| 2 | 基底 ELF Game CRC | ✓ `653FBF69` |
| 3 | 候选 ELF 与基底**逐字节相同** | ✓（CRC 同） |
| 4 | ISO 尺寸不变 | ✓ 1,648,164,864 B |
| 5 | **全盘差异 0 字节**（零改动出盘） | ✓ 0 differing chunk |
| 6 | **逐容器"新解 == 旧解逐字"** | ✓ **4713/4713** 容器载荷逐字节相同 |
| 7 | 全盘普查 **A 类 = 0**（C=0），26,483,238 个 0xFF 全部 B 类 | ✓ |
| 7b | LANG 条目 / `<text>` 正文 / TXT 全文里 0xFF = 0 | ✓ 1,608 个文本容器，0 违规 |
| 7c | **载荷级旧码 = 0**（`scan_legacy_residue`，本盘闸门 `0xBA`） | ✓ 0 处 |
| 7d | SFXML 槽 116,486 B / 69 条；LANG 2,232 条 ×2 | ✓ |
| 8 | sha256 / md5 / 尺寸记录 | ✓ |
| 8b | 候选 sha256 == 基底 sha256 | ✓ |

零点证据（可复跑）：

```
python tools\ff_sweep\gate_no_ff_text.py --iso work\builds\GR_PROFILE3\GR_ZH137.iso
containers checked : 1608
text spans         : 143599
text span bytes    : 2436537
0xFF inside spans  : 0
RESULT             : PASS (no 0xFF in any text span)

python tools\ff_sweep\scan_textual_ff.py work\builds\GR_PROFILE3\GR_ZH137.iso \
       --old "<ENG ISO>" --out out\textual_ff_zh137.json
containers with hits: 37 ; hits: 89 ; hits that are also 0xFF in ENG: 89
containers with NEW hits: 0
```

### 3.2 回归：6000 帧冷启动冒烟 + 1 帧粒度

| 跑批 | 盘 | 帧 | 截图 | 0 字节 | TLB Miss | Trap/unmapped | 退出码 | 耗时 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `runs\smoke_ZH137` | **GR_ZH137** | 6000 | **573** | 0 | **0** | **0** | 0 | 103 s |
| `smoke_ZH136`（上一轮，同仪器同导航） | GR_ZH136 | 6000 | 573 | 0 | 0 | 0 | 0 | 102 s |
| `runs\fg_ZH137`（**-grsnap 1**） | GR_ZH137 | 600 | **337** | 0 | 0 | 0 | 0 | 12 s |
| `runs\fg_ZH136`（**-grsnap 1**） | GR_ZH136 | 600 | 337 | 0 | 0 | 0 | 0 | 12 s |

逐帧配对（`cmp_snaps.py`，按文件名 1:1）：

```
smoke_ZH137 vs smoke_ZH136 : paired 573 ; byte-identical 573 ; differing 0 ; zero-byte 0 ; only-in-A/B 0/0
fg_ZH137    vs fg_ZH136    : paired 337 ; byte-identical 337 ; differing 0 ; zero-byte 0 ; only-in-A/B 0/0
```

⇒ **1 帧粒度**（600 帧逐帧）与 6000 帧冒烟都是 **0 差异**（本盘与 ZH136 逐字节相同，符合预期）。
收尾：跑批全部 `post-run pcsx2 count = 0`；全轮**只轮询不杀**外来 pcsx2（`OTHERS_RUNNING.txt` 未出现）。

### 3.3 从英文原盘逐字节可复现 —— ✅ 通过

`tools\final_fix\repro_from_eng_zh137.ps1`（本轮新增；既有脚本一行未改；实跑 `logs\repro_zh137.log`，exit 0，657 s）：

```
[0] ENG ISO sha256 2b42ea7c…8531 ✓ ; K2 dump sha256 11f371f2…add9 ✓
[1] base      d7f83d7ec4a8fe1ec8d60de4b17b94513bd1540dc929d3b667086f4910443ca0 ✓
[2] stage     e65e77fbb696ec5dd9dfaf5b6ca5bbc62d26bfa00e1f5c238fa150c4868791a1 ✓
[3] edge      db3f8b997a9dfaa89e5147cbeb75341d71d271cedbd53a2dd1c8aa1bee8aeefb ✓
[4] GR_ZH133  3fb12c8d16c2448e5c8976896b8132d65b3f6c8cf0e679f709aaf2b2572cdf95 ✓
[5] GR_ZH134  165b7eb2c667fc0c373b193f054ecd525d04124e5c57f9e69f6e69e4043ecd6a ✓
[6] + patch_profile2_text.py (22 处 0xFF 改写) → 172b35cc…408140 ✓
[7] FF 闸门 gate_no_ff_text.py → PASS（文本区间 0xFF = 0）
[8] 认证盘 GR_ZH137 = 172b35cc…408140 / md5 a9c18781… / 1,648,164,864 B ; ELF CRC 653FBF69 ✓
[9] 与 work\builds\GR_PROFILE3\GR_ZH137.iso 逐字节相同 ✓
[10] scratch 目录已打印并删除
```

### 3.4 屏内实证（实机截图 + 32 MB RAM 回读；**诊断盘 = 候选盘 + 解锁 1 词**）

会话：`work\builds\GR_PROFILE3\runs\live137b`（`-grinputlive` 实时驱动；记忆卡先格式化并建档，随后从存档启动）
诊断盘：`work\builds\GR_PROFILE3\diag\GR_ZH137_diag_unlock.iso`
（= GR_ZH137 + `0x00346058 9022A2F8 → 24020001`，CRC `D11F1D90`；**交付盘不含此 1 词**）

| 屏 | 截图 | RAM 回读（32 MB EE） | 结果 |
|---|---|---|---|
| **① 特别收录 → 专家 → 斯通** | `runs\live137b\expert137.png`（帧 9,555） | `expert137_f00009555_eeram.bin` → `out\ram_expert.txt` | **首行就是姓名**：`@0x007A9AB0` 起是 `杰克·斯通 中士{br}兵种：狙击手{br}“没错，是我开枪打死了他。…`（上一轮同一对象的串首是 `特征：无{p}…`；该地址前紧邻的 4 个 `FF` 是邻接数据/字库字节，探针窗口显示为 `…命著著著著杰克·斯通…`，不属于该串）|
| **② 特别收录 → 武器 → AN-94 突击步枪** | `runs\live137b\wpn_an94.png`（帧 32,644） | `wpn_an94_f00032644_eeram.bin` → `out\ram_an94.txt` | 正文整段可见，含 `这明显提高了射击精度；{br}全自动模式射速为600发/分。`（RAM 命中 12 处）|
| **③ 特别收录 → 奖章 → 银星勋章** | `runs\live137b\award_zhuoyue.png`（帧 50,246） | `award_zhuoyue_f00050246_eeram.bin` → `out\ram_award.txt` | 正文整段可见，末行 `但依然必须展现出明显的卓越功绩。`（RAM 命中 10 处）——「明显」「卓越」两个替换词同屏 |

辅助截图：`b_menu.png`（主菜单）、`b_expertlist.png`（专家列表=斯通）、`award_b.png`（国会最高勋章）、
`award1.png`、`back1.png`；`name*.png`/`menu*.png`（建档/格式化/保存流程，顺带覆盖存档 UI 文案）；
`runs\live137c\c_menu2.png`（主菜单）、`c_t1.png`（训练列表）、**`c_t2.png`（任务简报/载入屏：
`信息 / 训练1 - 越野训练 / March 15, 2008 | 13:00 | 晴天 / 任务目标` —— 全部来自 LANG 长度前缀条目）**。

### 3.5 数据侧其它闸门

| 项 | 结果 |
|---|---|
| 图集 / FONT.RES / PAK 结构 | **未动**（GR_ZH137 == GR_ZH136；`new_font_revised` 1024×644，18 段 GIF 包，逐字节同） |
| LANG 表结构 | 66 组 / 2,232 条 ×2，`used_end=71178`，逐字节同 |
| SFXML 槽 | 116,486 B（`stored=49,700`），69 条 `<text>`，键序不变 |
| 载荷级旧码（`0xB1..gate`，gate=0xBA） | **0** |
| 窗口外差异 | **0**（全盘 0 差异） |

### 3.6 三闸门（项目既有自检，`tools\ff_sweep\three_gates.py`）

| 闸门 | 结果 | 说明 |
|---|---|---|
| `selfcheck_charset` | **PASS** 30/30 | 单字节 103 + 对偶 2,300 编解码逐字节自洽；lead 区间 `[0xA1,0xBA)` 内无单字节码；`0xFF → 著` 的映射本身合法（问题只在 XML 词法器把它当 EOF） |
| `selfcheck_newlines` | **PASS** 49/49 | `{br}`/`{p}`/`{WRAP}` 口径不变 |
| `selfcheck_anchors` | **WARN 5/6** | 唯一不符：`LANG G057.I195`（1-based 记作 **G058.I195**）现为 `'顺序'`，而锚点表里写死期望含 `'命令'`。**与 0xFF 无关、本轮未引入**：`lang_find.py` 实读两份拷贝都是 `'顺序'`，英文原文是 `'Order'`（同组其它条目：`Left and right to change soldiers order.` ⇒ 这里就是"次序/顺序"义）；`GR_ZH134` 上**完全同样报这一条** ⇒ 是锚点表的陈旧期望，不是数据缺陷 |

> 所以严格口径上"三闸门全 PASS"**不成立**：2 个 PASS + 1 个 WARN（1 条陈旧锚点）。
> 本轮**没有**去改这句译文（超出 0xFF 范围，且 `'顺序'` 对 `'Order'` 是合理译法）。

---

## 4. 给用户的测试步骤

**盘**：`work\builds\GR_PROFILE3\GR_ZH137.iso`
（ELF 与 GR_ZH136/GR_ZH134 **逐字节相同** ⇒ **新开档或旧存档/即时存档都可以**；CRC 仍是 `653FBF69`）

> 本盘与 `GR_ZH136` **是同一份字节**：如果你已经在测 ZH136，**不需要换盘**；
> ZH137 的价值是"这一版过了全盘 0xFF 闸门"，可以直接作为发布候选。

1. **专家简介**：主菜单 → 特别收录 → 专家 → 任选一位（第一位「斯通」）。
   期望：文本框**第一行就是** `杰克·斯通 中士`，往下是 `兵种：狙击手`、台词、`[体检档案]`…；
   按 ↑/↓ 逐行滚动，按 ◄/► 换人（换人后窗口回到第 0 行）。
2. **武器（上一轮改写的 2 条之一）**：特别收录 → 武器 → 向右翻到 **`AN-94 突击步枪`**（第 22 件）。
   期望：正文从 `该步枪是俄制AK-74的继任者，` 开始，含 `这明显提高了射击精度；`，**一行不缺**。
3. **奖章（另两条改写）**：特别收录 → 奖章 → 第 3 件 `银星勋章`。
   期望：末行 `但依然必须展现出明显的卓越功绩。`；第 1 件 `国会最高勋章`、第 4 件 `战功星章` 同样完整。
4. **开发手记**：特别收录 → 访谈 → `开发访谈 3`（`开发手记：第三辑`），正文含 `随着战术AI的明显升级，`。
5. 若仍有异常，请拍：该屏整屏 + 按 ↓ 之后的整屏，并注明**你测的是哪个容器/哪一条文本**。

---

## 5. 未达成 / 诚实清单

1. **本轮没有"修"任何一处 —— 因为一处都不剩**。A 类 = 0 是普查结论，不是漏查：
   4,713 个容器全枚举、26,483,238 个 0xFF 全部落类、文本区间 0 命中、格式无关扫描"新增命中 0"、
   并有一把能在 ZH134 上**报出 22** 的闸门做反向对照。
2. **`0x00544588 lb` 这条引擎 bug 仍然没在 ELF 里修**（沿用上一轮的判断）：
   `lb`→`lbu` 会让真 EOF 失去检测、文件尾死循环；正规修需要 cave（≥3 指令 + 跳转）。
   本轮继续走"数据侧不让 0xFF 出现在文本里"的路线，并把它固化成**构建闸门**。
3. **`EN_STRINGS.RES` 里的 2 个 0xFF（长度字段 255）保留不改**：它们是结构字节，
   引擎按长度读、不截断；要消掉只能改译文长度，属于"为指标改内容"，不做。
   ⇒ 因此"全盘 0xFF 计数 = 0"这个更强的主张**不成立**（本轮的判据是"**文本区间** 0xFF = 0"）。
4. **二进制容器里的 0xFF 没有逐字节列全**：2,320 个未改动容器合计约 2,648 万个 0xFF，
   逐字节清单需要 ~2 GB CSV。处理方式：容器级计数 + 每容器首/尾样本（`census_ff_samples.csv`，9,251 行）
   + "与英文原盘逐字节相同"的哈希级证明；**改动过的 15 个含 0xFF 容器则是逐字节全列**
   （`census_ff_touched.csv`，36,659 行，含 24,182 个 IKE、432,378 个 ELF 的汇总行）。
5. **屏内实证用的是"候选盘 + 解锁 1 词"的诊断盘**（`diag\GR_ZH137_diag_unlock.iso`，CRC `D11F1D90`）；
   测试卡是全新档、特别收录默认上锁，所以只能这样进屏。**交付盘不含这 1 词**。
6. **实机导航是"人肉实时驱动"**（截图判位后逐个追加按键），因此过程截图里夹着走错菜单的中间帧
   （`live137b\award1.png` 误入游戏场景、`live137b\b_sf_expert.png` 误入选项、`live137c\c_back.png`
   又误入训练关卡）。**证据帧是 §3.4 列出的那 3 张**（外加 `live137c\c_t2.png` 的 LANG 简报屏），
   其余只作为"确实在真机上手操作"的旁证。
   ⇒ 想省事的话：**这 4 张都可以用 `GR_ZH136` 的同名截图替代**，因为两盘逐字节相同。
7. **`GR.IMG#3` 与 `MENU.IMG#3` 的 COMMON.PAK 不同**（前者 400,659 B 未扩展、后者 468,243 B 已扩展为 1024×644）——
   这是历年字库扩容的结果，本轮**未动**；两份的 0xFF 都是图集/CLUT 字节，已分别取证。
8. **`work\builds\GR_RELEASE\**` 一个字节没动**（按纪律）；GR_ZH137 只落在 `GR_PROFILE3\**`。
   若要把 ZH137 提升为发布盘，需要用户明确指示后再替换 `GR_RELEASE\**` 里的成品。
9. **`selfcheck_anchors` 有 1 条陈旧期望**（`LANG G058.I195`：`'顺序'` vs 写死的 `'命令'`，英文 `'Order'`）。
   它在 `GR_ZH134` 上同样报（§3.6），与 0xFF 无关；本轮**不改**这句译文，只如实登记。
10. **实机只覆盖了 3 个"曾经会被腰斩"的屏**（专家 / AN-94 / 银星勋章）+ 1 个 LANG 简报屏。
    另外 19 处被改写的文本（其它专家、开发手记等）只有**静态**证明（`out\sf_text_map.txt` 逐条
    解码可见完整句子）+ 闸门 0 命中，没有逐屏拍照。

---

## 6. 复现命令（全部只读输入）

```powershell
$py = 'C:\Users\84363\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$eng = "third_party\orig\ps2\Tom Clancy's Ghost Recon (USA).iso"

# 1) 全盘普查（约 48 s）
& $py tools\ff_sweep\sweep_ff.py --iso work\builds\GR_PROFILE2\GR_ZH136.iso --old $eng `
      --out work\builds\GR_PROFILE3\out\sweep_zh136.json
& $py tools\ff_sweep\census_table.py --iso work\builds\GR_PROFILE2\GR_ZH136.iso --old $eng `
      --sweep work\builds\GR_PROFILE3\out\sweep_zh136.json --outdir work\builds\GR_PROFILE3\out
& $py tools\ff_sweep\report_stats.py work\builds\GR_PROFILE3\out\sweep_zh136.json `
      work\builds\GR_PROFILE3\out\census_summary.json `
      work\builds\GR_PROFILE3\out\textual_ff_zh136.json --out work\builds\GR_PROFILE3\out\report_stats.txt

# 2) 格式无关复扫（约 31 s）
& $py tools\ff_sweep\scan_textual_ff.py work\builds\GR_PROFILE2\GR_ZH136.iso --old $eng `
      --out work\builds\GR_PROFILE3\out\textual_ff_zh136.json

# 3) 被改过的容器逐个取证
& $py tools\ff_sweep\evidence_touched.py work\builds\GR_PROFILE2\GR_ZH136.iso --old $eng `
      --out work\builds\GR_PROFILE3\out\evidence_touched.txt

# 4) 构建闸门（ZH134 应 FAIL=22；ZH136/ZH137/ENG 应 PASS=0）
& $py tools\ff_sweep\gate_no_ff_text.py --iso work\builds\GR_RELEASE\GR_ZH134.iso `
      --json work\builds\GR_PROFILE3\out\gate_zh134.json
& $py tools\ff_sweep\gate_no_ff_text.py --iso work\builds\GR_PROFILE3\GR_ZH137.iso `
      --json work\builds\GR_PROFILE3\out\gate_zh137.json

# 5) 认证出盘 + 12 项自证
& $py tools\ff_sweep\make_zh137.py --base work\builds\GR_PROFILE2\GR_ZH136.iso `
      --out work\builds\GR_PROFILE3\GR_ZH137.iso `
      --meta work\builds\GR_PROFILE3\GR_ZH137.meta.json `
      --sweep work\builds\GR_PROFILE3\out\sweep_zh136.json `
      --census work\builds\GR_PROFILE3\out\census_summary.json

# 6) 从英文原盘端到端复现（约 11 min）
powershell -NoProfile -ExecutionPolicy Bypass -File tools\final_fix\repro_from_eng_zh137.ps1

# 7) 回归（6000 帧冒烟 + 600 帧逐帧）
& powershell -NoProfile -ExecutionPolicy Bypass -File work\builds\GR_MERGEFIX\runs\run133.ps1 `
      -Name smoke_ZH137 -Iso "…\GR_PROFILE3\GR_ZH137.iso" -Frames 6000 -Snap 10 -ScanFrames 2000 `
      -Nav tools\capture\nav_menu_only.txt -OutRoot "…\GR_PROFILE3\runs"
& $py work\builds\GR_PROFILE\tools\cmp_snaps.py work\builds\GR_PROFILE3\runs\smoke_ZH137 `
      work\builds\GR_PROFILE2\runs\smoke_ZH136

# 8) 屏内实证（诊断盘 + 实时驱动；截图与 RAM 回读见 §3.4）
& $py work\builds\GR_PROFILE2\tools\iso_patch.py work\builds\GR_PROFILE3\GR_ZH137.iso `
      work\builds\GR_PROFILE3\diag\GR_ZH137_diag_unlock.iso `
      --site 0x346058=0x24020001 --expect 0x346058=0x9022A2F8
& $py tools\ff_sweep\ram_text_probe.py work\builds\GR_PROFILE3\runs\live137b\expert137_f00009555_eeram.bin `
      --text "杰克·斯通" --text "兵种：狙击手"
```

---

## 7. 本轮新增/改动文件

| 文件 | 作用 |
|---|---|
| `work\builds\GR_PROFILE3\GR_ZH137.iso` | **推荐交付盘**（= ZH136 的认证副本） |
| `work\builds\GR_PROFILE3\GR_ZH137.meta.json` | 12 项自证 + 普查总数 |
| `work\builds\GR_PROFILE3\diag\GR_ZH137_diag_unlock.iso` | **仅验证用**（候选 + 解锁 1 词，CRC `D11F1D90`） |
| `tools\ff_sweep\recon_containers.py` | 容器级 0xFF 普查（快扫，含英文对照计数） |
| `tools\ff_sweep\sweep_ff.py` | 主普查：结构文本区间 + 逐 0xFF A/B/C 判定 |
| `tools\ff_sweep\scan_textual_ff.py` | **格式无关**的"汉字夹 0xFF"扫描（numpy + 解码确认） |
| `tools\ff_sweep\census_table.py` | 产出 `census_containers.csv` / `census_ff_touched.csv` / `census_ff_samples.csv` / `census_summary.json` |
| `tools\ff_sweep\evidence_touched.py` | 19 个"被改过"容器的逐字节取证 |
| `tools\ff_sweep\gate_no_ff_text.py` | **构建闸门**（文本区间 0xFF 必须为 0；ZH134 上会 FAIL=22） |
| `tools\ff_sweep\make_zh137.py` | 出盘 + 12 项自证 |
| `tools\ff_sweep\report_stats.py` | 报告用统计汇总 |
| `tools\ff_sweep\{ff_locate,probe_lang_entry,pak_probe,ff_pages,sfxml_copies,sf_items,sf_text_map,text_hazards,ram_text_probe}.py` | 取证小工具（LANG 记录 / PAK 记录 / 页直方图 / SF 副本与条目序 / 文本区危险字节 / RAM 文本回读） |
| `tools\ff_sweep\{three_gates,lang_entry,lang_find}.py` | 项目三闸门跑批 / LANG 单条对照 / 按文本反查 LANG 条目 |
| `tools\final_fix\repro_from_eng_zh137.ps1` | 从 ENG 原盘的端到端复现（**新增**，既有脚本未改） |
| `docs\REPORT_FF_SWEEP.md` | 本文件 |
| `work\builds\GR_PROFILE3\{out,logs,runs}\**` | 普查表、日志、回归与实机证据 |

**未改动**：`third_party\**`、`work\builds\GR_PROFILE2\**`（只读引用其工具与产物）、
`work\builds\GR_RELEASE\**`、`work\builds\GR_PROFILE\**`、`tools\final_fix\` 既有文件、用户 PCSX2 目录、git。

### 7.1 关键数字速查

| 指标 | 值 |
|---|---|
| 容器总数 | 4,713 |
| 含 0xFF 的容器 | 2,335（未改动 2,320 + 改动过 15） |
| 0xFF 总字节 | 26,483,238 |
| **A 类（文本区间内，必须修）** | **0** |
| B 类（二进制/结构/原版字节） | 26,483,238 |
| C 类（待定） | 0 |
| 文本容器 / 文本区间 / 区间字节 | 1,608 / 143,599 / 2,436,537 |
| 文本区间内 0xFF（闸门口径） | **0**（ZH134 对照：22） |
| 本地化改过的容器 | 19 |
| 与英文原盘逐字节相同的容器 | 4,694 |
| 本轮 ISO 差异 | **0 字节** |
| 6000 帧冒烟 / 逐帧对比 | 573 截图，573/573 相同；337/337 相同 |
| 从 ENG 复现 | ✅ 逐字节相同（657 s） |
| **推荐盘 sha256 / md5 / CRC** | `172b35cc…408140` / `a9c18781…f630` / `653FBF69` |
