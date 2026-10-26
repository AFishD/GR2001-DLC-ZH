# MOD_GUIDE —— 汉化修改指南（做法与陷阱）

> 面向「要再改一处内容」的你。这里写的是**这个游戏这个盘**特有的做法与坑。
> 重建整盘看 `docs/BUILD_GUIDE.md`。

---

## 0. 心智模型：一层一层剥

```
ISO9660 (2048 B/扇区)
 └─ SLUS_208.20 (LBA 296, 5,319,720 B)          ← 主程序；DBCS 补丁打在这里
 └─ GR.IMG      (LBA 61000, 1,104,291,830 B)    ← 唯一大容器，3,111 个资源
      └─ 条目表 @ +0x830，每项 12×u32 (48 B)
           [0] 名字偏移 [1] 名字序链 [4] 压缩标志 [5]≡1
           [6] stored  [7] real  [8] 条目内偏移  [9][10] 名字键 [11] 哈希链
                iso_off = lba*2048 + off
                名字表 @ +0x10 起（'\0' 分隔，顺序 == 条目顺序）
      └─ 条目载荷 = 若干 LZO1X 子流 {u32 clen}{u32 rlen}{payload}
           · clen != rlen → LZO 解压到 rlen
           · clen == rlen → **原样存储块**（引擎直接拷贝；全盘 355 个）
           · 子流按 16,384 B 解压块切分（ceil(real/16384) 段）
```

**要点**：引擎看到的是**子流解压后**的 payload。汉化改动全部在 payload 层做，
由 `tools\dlc\rebuild.py` 重排/重打帧；`--stage` 每次从英文原盘重来。

关键资源索引：

| 资源 | 条目 | 说明 |
|---|---|---|
| `EN_STRINGS.RES` | GR#576 | LANG 语言表（67 组 / 2,971 条） |
| `FONT.RES` | GR#580 | 字库定义（3 face × 224 条 + 522 B 样式尾部） |
| `COMMON.PAK` | GR#9 | 10 条记录；`new_font_revised` = 字形图集 |
| `EN_SPECIAL_FEATURE.XML` | GR#3101 | 特别收录（98 个 `<text>` + 174 个标题） |
| `*.MIS` | 45 个 | 任务文件；玩家可见字段（Name/MapName/Date/Briefing…） |
| `EN_STRINGS.TXT` | GR#577 | 武器/道具 token → 显示名 |
| `SLUS_208.20` | ISO 根 | ELF（DBCS 补丁） |

---

## 1. 改文本（最常见）

### 1.1 三个地方

| 种类 | 位置 | 结构 |
|---|---|---|
| **LANG** | GR#576 | `{u32 ngroups}` + 每组 `{u32 count}` + `count ×({u32 len}{data}{u16 attr})`，组间 1 个 u32 分隔；attr 全 0 |
| **SFXML** | GR#3101 | 纯 XML，正文在 `<text>…</text>`；标题是 `<studio|group|item name="…">` 属性 |
| **MIS** | 45 个 `*.MIS` | 看着二进制，其实是 XML（LZO 5 子流拼起来；见 §3） |

### 1.2 流程

1. 改 `assets/text/translated/batch_*.csv`（列 `resource,id,text_zh`）；
2. `python tools\dlc\merge_translations.py` 合并；
3. `python tools\dlc\char_coverage.py` 查缺字（>0 则 `python tools\font\expand_charset.py`）；
4. `python tools\dlc\build.py --stage all --out ... --force`；
5. `verify.py` / `audit.py` / 可选 PCSX2 冒烟。

### 1.3 坑

* **CSV 里禁止真换行**：`\r\n` 写成字面 `\r\n`；`{p}`/`{br}` 是引擎富文本标记，原样保留、数量与原文一致（TM 行允许历史 `{br}` 软换行，注入时 `--allow-marker-drift`）。
* **`{p}` 段落 vs `{br}` 换行**：新译尽量按原文标记结构；SFXML 长文手动软换行只用于 TM 历史译文。
* **禁止 `0xFF`**：字符集把 `著` 映射成单字节 `0xFF`，XML 词法器会当 EOF。本工程在合并阶段做强制替换（显著→明显、著→着…），`inject_text` 也会在 SFXML/MIS 上拦。
* **人名保留英文**（引擎字库含 ASCII）；文件名/URL/金额/电话保留。
* **长度**：资源重排由 rebuild 负责，单条长度不设硬上限（但 UI 显示会把过长文本截断/溢出，尽量短）。

---

## 2. DBCS 编码与字库

### 2.1 编码口径（与本体成品盘一致）

```
lead  ∈ [0xA1, 0xBA)   （26 个）
trail ∈ [0xA1, 0xFE]   （94 个）
slot = (lead-0xA1)*94 + (trail-0xA1)   → 0..2350
```
* ASCII 走单字节码（`codes` 103 条）；
* 汉字用对偶码（`pair_of` 2300 条；扩充时回收零引用 PUA 槽，不新增 pair 数）；
* 图集（`COMMON.PAK` 的 `new_font_revised`）：**psm=0x14 PSMT4、1024×644、80 B CLUT**；
  网格 `NCOL=64、16×16`，`x=16*(slot%64)`，`y=3+16*(row+2*[row>=12])`。

### 2.2 加新字（缺字）

1. 译文合并后跑 `char_coverage.py`，缺字写入 `work\translation\merged\missing_chars.json`；
2. `python tools\font\expand_charset.py`：分配零引用 PUA 槽 → TTF 渲染 16×16 → 写图集容器 → 更新
   `assets/charset/charset_compiled_zh16.json` 与 `charset_expand_dlc.json`（幂等）；
3. 重新 build；`audit.py` 缺字必须为 0。
> 安全容量 298 格（334 PUA − 36 个引擎采不到的 col63 槽），已用 45，剩 253。

### 2.3 字体渲染度量（v3 已修复，务必保持）

引擎字形 quad 高度 = `round(fld[1] × style.f6)`（fld[1] = face 头字段 def+0x0C；f6 = 尾部 style 高度缩放）。
我们的 FT 记录全部是 **16 px 高**，所以必须保证 `fld[1]=16` 且 `style.f5/f6 ≤ 1.0`——
否则 quad 会被拉大去映射 16px 字形，出现**纵向拉伸/越界裁剪**（v2 的原 bug）。

* `fontlib.ft_merge_for_dlc()` 末尾调用 `normalize_face_metrics()` 自动规整（幂等）：
  三 face `fld[1]=16`；尾部 style 中 f5/f6>1 的归 1.0。改 FONT.RES 时不要绕过该函数。
* 回归断言：`verify.py` 的 **C14**（fld[1]=16 且 style 缩放 ≤1.0）；细节见 `docs/ANALYSIS_FONT.md` §12。
* 为什么全归 1.0（v6/A″）：ASCII 字形 quad 尺寸走 FT 记录（恒 16px），而 pair(中文) 的 quad 高 = CharHeight = fld[1]×style.f6、宽恒 16；只要 f6≠1，中文与英文的大小/垂直位置就不一致 → 混排行出现明显上下偏移。统一 1.0 后全部 16px、混排对齐；代价是原版字号层级被拉平（标题不再更大）。
  比由设计 2.0 变 2.7~3.2×；若极窄 UI 溢出 → 改短文案或该 style 归 1.0（不建议 cave 乘 f5<1，会字叠字）。

---

## 3. MIS 任务文件

* 45 个 `*.MIS` 的 payload = 5 个 LZO 子流（16 KB 分块），XML 在开头；
* 玩家可见字段：`Name` / `MapName` / `LocationText` / `DateText` / `TimeText` / `BriefingText` / `RecommendedGameTypes`；
* 43 个任务的 `*_Id`（`(LANG组<<20)|组内序号`）指向 LANG——**游戏里实际显示以 LANG 为准**，MIS 字面量是副本/回退；
* 注入由 `inject_text.py` 按 manifest 偏移 splice，再重新打帧（rebuild 重排），不做原地 LZO 令牌改写。

---

## 4. ELF 补丁（DBCS）

* 规格：`tools/analysis/dbcs_spec.py` → `work/analysis/elf/dbcs_spec_dlc.json`；打好的补丁表：`tools/dlc/elf_patches.json`（**28 段** = 25 站 DBCS + 1000 B cave + **2 处字库最近邻过滤**）。
  打好的补丁表：`tools/dlc/elf_patches.json`（26 段 = 25 站 + 1000 B cave @ VA 0x1808A8）。
* 几何参数在 cave 源 `.equ`：`GATE_HI=0xBA / NCOL=64 / CELL=16 / Y0=3 / SKIP_ROW=12 / SKIP_ROWS=2 / PAIR_BASE=224`；
  改几何只改 `.equ` 重汇编，不碰原版字节。
* **Game CRC 会变**：`DE1E4DEE → ED1D6AD4`（DBCS + 字库最近邻过滤补丁），旧即时存档/金手指失效（发布说明要写「请新开档」）。
* 字库采样：v7 起把 `RSFontMgr` 字库路径的 `SetLinearSampling(true→false)` + `UIPacket::SetLinearSampling` 状态缓存早退 `beq→nop` 打上（参考本体 ZH50 过滤集；DLC 站点 `0x219314` / `0x4FD5CC`）。中文图集是 1-bit，双线性会导致笔画漏墨/发虚。
* 不要删 cave 里的

---

## 5. 贴图内烘焙英文（未做，如实记录）

菜单/简报框/logo 等贴图（40 PAK 里 136 张 GS 纹理 + 5 JPEG、199 RSB）可能含烘焙英文。
ASCII 普查无法证明；本轮**未重绘贴图**。候选清单见 `docs/ANALYSIS_ISO.md` §4.4 与
`docs/REPORT_FINAL_DELIVERY.md` 残余清单。标题 logo、Tom Clancy 版权页等保持原样。

### 2.3b A‴ 行盒锚点（v9）

* `fontlib.restore_face_metrics()`：face `fld[1]` 恢复 EN 26/26/42（布局行盒=EN），style f5/f6 保持 1.0；
* ELF 5 处：`0x219894 j`、`0x219898 nop` + 三段零填充 cave（A 0x575D04 / C 0x182F84 / B 0x5752F0）：基础居中 `y1=y+(CharHeight-16)/2`、`y2=y1+16`；标题 y<40 +7、中段 40<=y<400 -2、底栏 y>=400 且 x<400 -3
  `y2=y1+16`；标题带 `y<40` 再 +7、底栏 `y>=400 且 x<400` 再 -3）；
* 回归：`verify.py --stage all` 38/38；新 CRC `E601C271`（旧存档失效）。
