# ANALYSIS_ISO —— 《幽灵行动：丛林风暴》PS2 (SLUS-20820, 美版) 全盘资源结构分析

> 任务：P1-A（task-1）全盘资源结构分析。
> 作者：iso-analyst（Team Lead 的 4 个并行分析师之一）。
> 基线：`third_party/orig/ps2/[PS2] Tom Clancy's Ghost Recon - Jungle Storm (U).iso`
> 　1,229,225,984 B，sha256 `292f5a6a050e82e05efb5bf9fd5ce3bc12706a8ae57c78b729348a5c80fd0767`，卷标 `SLUS_20820`。
> 复现：`tools/analysis/iso_img_scan.py` / `iso_layer.py` / `iso_pak_scan.py` / `iso_base_compare.py`（全部只读，`--help`）。
> 约定：标「**实证**」= 由本脚本现场统计/逐字节断言得到；标「**推测**」= 由命名、同类类比或跨盘对照推断，未逐字节证实。

---

## 0. 一页摘要

1. **ISO 层**：单容器布局，`GR.IMG`（LBA 61000，1,104,291,830 B）内含全部 3,111 个游戏资源；
   根目录另只有 `SYSTEM.CNF` / `SLUS_208.20`(ELF) / `DNAS.BIN`+`OFFLINE.BIN`+`ONLINE.BIN`(私有 MWo3 头，网络/认证模块，与汉化无关) / `MODULES/`(15 个 IRX + DNAS280.IMG) / `LICENSE/`(LIBEENET.TXT)。
   卷 600,208 扇区，已用 543,009，**未分配 57,199 扇区（111.7 MiB / 117.1 MB 十进制）**，其中 GR.IMG 前有 **55,961 扇区（109.3 MiB）连续空闲**；卷尾仅余 6,154 B。
2. **GR.IMG 头/条目表语义已全部实证**（见 §3）：12×u32 条目里 `[0]`=名字偏移、`[1]`=按名字升序的链表 next、`[4]`=压缩标志、`[6]`=stored、`[7]`=real、`[8]`=off、`[9]`=名字键（跨盘恒定，非内容校验和）、`[10]`=**12-bit 名字哈希**（桶号公式 3111/3111 完全吻合）、`[11]`=哈希桶冲突链 next；哈希桶表 4096 槽（1602 个桶，链覆盖全部 3111 条、无环无重、最长链 16）。
3. **载荷帧规则重大修正**：LZO 条目内的子流存在「**clen==rlen ⇒ 原样未压缩块**」，全盘 **355 个**（296 个在中间、59 个在末尾）。带此规则后 **1197/1197 条 LZO 条目全部可解、0 例外**。此结论已同步到核心库：**更新后的 `dlclib.lzo_subs()` 已支持该规则**（复验：全表 3111/3111 条 `entry_payload` 展开 0 失败，`CP03_PRISON.MIS` 正常）。
4. **玩家可见英文文本只集中在 6 类资源**（§5）：`EN_STRINGS.RES`(LANG，67 组 / 2,971 条 / **159,071 B**)；`EN_SPECIAL_FEATURE.XML`(SFXML，81 条非空 `<text>` / **96,438 B**)；45 个 `.MIS` 中的显示字段（字面量合计 **26,187 B**，其中 43 个任务用 `*Id` 引用 LANG，映射公式 `id=(组<<20)|组内序号` 已实证）；766 个 `.ATR` 的 `<ActorName>`(**9,583 B**)；14 个 `.GTF` 的 Name/Comment(1,566 B，同时 `*Id`→LANG)；`EN_STRINGS.TXT`(**228 键值 / 值 1,648 B**，武器/物品/Kit 名)。其余 ASCII 串全部为二进制噪声（视频/音频/贴图）或开发残留。
5. **40 个 PAK** = 纹理图集包，record 级结构已解（141 条记录：136 条 GS 纹理 + 5 条内嵌 JPEG）；字库图集记录 `COMMON.PAK/new_font_revised` = psm19 512×512 / clut 1040 B / px 262,160 B（16B GIF tag + 262,144B 像素）**原样未压缩**（ty=0）⇒ 字库方案改它不需压缩算法；其余 PAK 的纹理段是**未识别压缩算法**（已排除 LZO1X/zlib/deflate/LZ4/LZF/LZSS/PackBits，见 §6）。
6. **对汉化的结论（§8）**：数据层需要动的只有「文本资源 + 字库定义/图集」；**所有名字/条目结构都不能变**，因此条目表 `[0][1][9][10][11]`、名字区、哈希桶表、排序链一律**不动**。GR.IMG 条目排布几乎无空隙（除尾部 64 KiB 与 41 个 2,044 B 空隙，条目间 slack 合计 105,609 B），**载荷变大必须搬条目**（推荐搬到容器末尾 + 改 `[6][7][8]` + 头 `+0x0`=新 data_end+0x10000 + ISO root dir size + PVD volume_space），font-engineer 的方案 B 已验证该路线；若中文压缩后变小则可原地缩 `stored` 留下空洞。

---

## 1. 方法与复现

| 脚本 | 作用 | 主要产出 |
|---|---|---|
| `tools/analysis/iso_img_scan.py` | GR.IMG 头/条目表/哈希表/排序链 + 3111 条逐条展开 + ASCII 普查 | `assets/manifests/gr_img_index.json`（1.61 MB）、`work/analysis/iso/gr_img_entries.tsv`、`text_samples.tsv`、`text_census_by_resource.tsv`、`text_resource_stats.json` |
| `tools/analysis/iso_layer.py` | ISO9660/PVD/目录树/关键文件/空间账本 | `work/analysis/iso/iso_layer.json` |
| `tools/analysis/iso_pak_scan.py` | 40 个 PAK 记录级解析 + 与本体同名 PAK 对比 | `work/analysis/iso/pak_records.json` |
| `tools/analysis/iso_base_compare.py` | 资料片 vs 本体（资源名集合/载荷 sha/LANG/SFXML/资源数） | `work/analysis/iso/base_compare.json`、`base_new_in_dlc.txt`、`base_inherited.txt`、`base_only_in_base.txt`、`base_changed_payload.txt` |

运行（PowerShell，只读原盘）：

```powershell
$env:PYTHONIOENCODING="utf-8"
python tools\analysis\iso_img_scan.py          # 全量扫描
python tools\analysis\iso_img_scan.py --header # 只看容器结构（秒级）
python tools\analysis\iso_layer.py             # ISO 层
python tools\analysis\iso_pak_scan.py          # PAK
python tools\analysis\iso_base_compare.py      # 与本体对比（读本体盘 ~30 s）
```

脚本内置断言（任一失败会打印 `[FAIL]`）：
容器头 12 字段交叉验证 10 项、名字偏移链连续覆盖、名字排序链形状、哈希桶链覆盖、
「桶号 = ((u32[10]>>16)<<6)|(u32[10]&0x3F)」3111/3111、LZO 展开总长 == real（1197/1197）、
PAK 记录恰好铺满到 0x63 终结符（40/40）。

---

## 2. ISO9660 层（实证）

### 2.1 PVD（扇区 16）关键字段

| 字段 | 值 | 说明 |
|---|---|---|
| 卷标 volume_id | `SLUS_20820` | 与 ELF 名一致 |
| system_id | `PLAYSTATION` | |
| volume_space_size | **600,208 扇区**（LE==BE），×2048 = **1,229,225,984 B** | 与实际文件大小精确相等，无尾部对齐浪费 |
| logical_block_size | 2048 | |
| path_table_size | 42 B | L 表 @LBA 257，M 表 @LBA 259；条目 2 个：MODULES(262)、LICENSE(263) |
| root dir | @LBA **261**，size **558 B** | 目录记录 1 个扇区足够 |
| created | **2004-02-13 08:00:00 +09:00** | PS2 母盘制作时间（日本时区） |
| modified/expires/effective | 全 0（未设置） | |
| 扇区 17 | type=**255**（终结符） | 无 SVD |

### 2.2 目录树与文件（23 个文件 / 2 个目录）

| 路径 | LBA | 字节 | 性质（实证） |
|---|---|---|---|
| `SYSTEM.CNF;1` | 295 | 59 | 纯文本：`BOOT2 = cdrom0:\SLUS_208.20;1 / VER=1.02 / VMODE=NTSC` |
| `SLUS_208.20;1` | 296 | 5,319,720 | **ELF32 / MIPS / ET_EXEC**，entry 0x100008，phnum 5（主程序；ELF 分析见 ANALYSIS_ELF.md） |
| `DNAS.BIN;1` | 2894 | 618,624 | 头 `MWo3` + u32=1；内嵌字符串 `dnas.bin`；**推测**=DNAS 在线认证封装模块（与汉化无关） |
| `OFFLINE.BIN;1` | 3197 | 313,216 | 头 `MWo3` + u32=2；内嵌 `offline.bin`；**推测**=离线网络/认证载荷 |
| `ONLINE.BIN;1` | 3350 | 707,840 | 头 `MWo3` + u32=3；内嵌 `online.bin`；**推测**=在线网络载荷 |
| `MODULES/` (DIR) | 262 | 1,052 | 16 条记录：`DEV9.IRX`、`DNAS280.IMG`、`EENETCTL.IRX`、`ENT_DEVM.IRX`、`ENT_SMAP.IRX`、`EZENTCTL.IRX`、`EZNETCNF.IRX`、`LGAUD.IRX`、`LIBSD.IRX`、`MCMAN.IRX`、`MCSERV.IRX`、`NETCNF.IRX`、`PADMAN.IRX`、`RPC.IRX`、`SIO2MAN.IRX`、`USBD.IRX`（IRX 全是标准 ELF 小端 MIPS 模块） |
| `LICENSE/` (DIR) | 263 | 158 | 仅 `LIBEENET.TXT;1` @5032 / 12,687 B（实证：PS2 `Programmer Tool Runtime Library Release 2.8` 的 BSD 许可文本，非游戏 UI） |
| `GR.IMG;1` | **61000** | **1,104,291,830** | 唯一资源容器，见 §3 |

### 2.3 空间账本（扩盘依据）

| 指标 | 值 |
|---|---|
| 卷扇区 | 600,208（1,229,225,984 B） |
| 目录+文件已分配 | 543,009 扇区（其中 GR.IMG 539,205 扇区） |
| 卷内未分配 | **57,199 扇区 = 117,143,552 B ≈ 111.7 MiB**（含卷首系统区/ PVD/路径表/root dir 等 ~296 扇区不可动） |
| 真实连续空闲①（卷首系统区之后） | LBA 0..262 —— 含 PS2 保护/系统区，**不可用** |
| 真实连续空闲② | LBA **4090..5032（942 扇区 = 1.84 MiB）**（USBD.IRX 之后、LIBEENET.TXT 之前） |
| 真实连续空闲③ | LBA **5039..61000（55,961 扇区 = 109.3 MiB）**（LIBEENET.TXT 之后、GR.IMG 之前） |
| GR.IMG 之后卷尾 | **6,154 B**（3 扇区+10 B；GR.IMG 声明的 size 不占满末扇区） |

**扩盘两种做法（均不改 ELF）**：
* **A 原地延长**：GR.IMG 当前紧贴卷尾，直接在 ISO 末尾追加并放大 GR.IMG extent：
  更新 PVD `volume_space`(LE/BE) + root dir 里 `GR.IMG;1` 的 data length(LE/BE)；ISO 现用 DVD5 的 26.2%，余量 3.4 GB+。
* **B 前移扩容**：把 GR.IMG 整体搬到 LBA 5039 起（空闲 55,961 扇区），再向右延伸；ISO 总长可不变，
  但需改 root dir 里的起始 LBA(LE/BE) 与 size。**实证**：GR.IMG 前连续空闲 55,961 扇区 ≥ 一次 COMMON.PAK/图集增长的量级。
* 附：**GR.IMG 内部尾部 65,536 B 空洞**（见 §3.2）可直接用于小增长。

---

## 3. GR.IMG 容器（实证）

### 3.1 容器头 12×u32（绝对偏移 = 61000×2048 = 0x1D7D0000）

| 偏移 | 值（本盘） | 语义 | 证据 |
|---|---|---|---|
| `+0x00` | **1,104,291,830** | 容器总字节数 | == ISO9660 root dir 里 `GR.IMG;1` 的 data length；且 == data_end + **0x10000**（见 §3.2） |
| `+0x04` | 222,064 | 名字区结束偏移 | == names_start + 51,856 |
| `+0x08` | 2048 | 扇区大小 | |
| `+0x0C` | 151,424 | 条目表结束偏移 | == 0x830 + 3111×48（精确） |
| `+0x10` | 170,208 | 名字区起始偏移 | == 条目表 end + 2400 + 16384 |
| `+0x14` | 223,232 | 载荷区起点 | == min(off) == 第 0 条 ACTION.PAK 的 off |
| `+0x18` | 1 | 版本/标志（含义未定） | 本盘=1；本体两份容器也=1（**推测**：格式版本） |
| `+0x1C` | 0 | 保留 | |
| `+0x20` | 153,824 | **哈希桶表偏移**（4096×u32，16,384 B） | 桶表+链覆盖 3111 条（§3.4） |
| `+0x24`/`+0x28`/`+0x2C` | 0/0/0 | 保留 | |

> **+0x00 的生成规则（三盘验证）**：`h[0] == max(off+stored) + 0x10000`。
> DLC GR=1,104,226,294+65,536；本体 (USA) GR=1,550,497,792+65,536；本体 MENU=58,235,346+65,536。
> ⇒ 64 KiB 是打包器固定尾垫（不是偶然对齐）；扩盘/搬条目后新 `h[0]` 应按「新 data_end + 0x10000」写。

### 3.2 容器内部布局（本盘精确偏移）

| 区间 | 长度 | 内容 |
|---|---|---|
| `0x00000`..`0x0082F` | 2,096 B | 容器头（12×u32 + 保留） |
| `0x00830`..`0x24F80` | 3111×48 = 149,328 B | **条目表**（每项 12×u32） |
| `0x24F80`..`0x258E0` | 2,400 B | 全零填充（用途未明；**推测**=打包器对齐/预留） |
| `0x258E0`..`0x298E0` | 16,384 B | **哈希桶表**（4096×u32，`0xFFFFFFFF`=空槽，值=条目号+1） |
| `0x298E0`..`0x36370` | 51,856 B | **名字区**（3111 个 `\0` 结尾名字，顺序=条目号顺序） |
| `0x36370`..`0x36800` | 1,168 B | 全零填充 |
| `0x36800`..`0x41D127F6` | 1,104,003,062 B | **载荷区**（条目间几乎首尾相接，见 §3.6） |
| `0x41D127F6`..`0x41D227F6` | **65,536 B** | 全零尾垫（= 容器声明大小 − data_end） |

> 十进制：data_start=223,232；data_end=**1,104,226,294**；容器=**1,104,291,830**；`GR.IMG` 结束于 ISO 字节 1,229,219,830，卷尾余 6,154 B。
>
> **统计**：sum(stored)=1,103,897,453；sum(real)=1,189,009,276；data 区 = data_end−data_start = 1,104,003,062 B；
> 其中「载荷字节+条目间空隙」分解：1,103,897,453 + 105,609 = 1,104,003,062（+尾垫 65,536 见上）。

### 3.3 条目表 12×u32 字段语义

每条 48 B（`base + 0x830 + idx×48`，小端）。

| 字段 | 语义 | 证据 / 覆盖 | 与名字/载荷/偏移的依赖 |
|---|---|---|---|
| `u32[0]` | **name_off**：名字在名字区内的累计偏移（Σ(前序名长+1)） | 3111/3111 连续覆盖名字区（末值+末名长+1 = 51,856 = 名字区长） | 只依赖名字集合/条目顺序 |
| `u32[1]` | **name_sort_next**：按名字**字节序升序**的单链表 next（1-based 条目号，0=尾） | 唯一 head=#326 `(COOP) DEFEND.GTF`、tail=#971 `_G_US_SUPPORT_CUBA.ATR`；链长 3111、顺序 == `sorted(names, key=bytes)`（3111/3111） | 只依赖名字集合/顺序 |
| `u32[2]` | 0（保留） | 3111/3111 = 0 | — |
| `u32[3]` | 0（保留） | 3111/3111 = 0 | — |
| `u32[4]` | **compressed**：0=原样载荷，1=LZO 帧流 | 0×1914 / 1×1197；且 0 条目 stored==real(1914/1914)，1 条目除 5 个 WAV 外 stored<real | 与载荷格式相关（改动载荷保持同格式即可不变） |
| `u32[5]` | ≡1（含义未定） | 3111/3111 = 1；**推测**=格式版本/ref 标志 | 恒定 |
| `u32[6]` | **stored**：盘上占用字节（LZO=帧字节总和，原样=文件长度） | 与 [7]+[4] 自洽；见 §3.5 | **改载荷大小时要改** |
| `u32[7]` | **real**：展开后负载字节（LZO=Σrlen，原样=文件长度） | 3111 条全部与展开结果相符（1197/1197 LZO 精确） | **改载荷大小时要改** |
| `u32[8]` | **off**：相对容器头 0 的载荷偏移 | 全部 **16 字节对齐**（3111/3111 off%16==0；本体 4070+686 条同样 100% 16 对齐）；条目不重叠、无负 slack | **搬条目时要改** |
| `u32[9]` | **name_key**（32-bit 名字派生键）：同名资源在「本体 GR / 本体 MENU / 资料片」三处完全一致，且内容大幅改动后仍不变 | 本体 vs 资料片同名 1562 条：**1562/1562 相同**（含 EN_STRINGS.RES 128,668→177,441、COMMON.PAK 400,659→763,676 等被改资源）；全表 distinct=2405（有碰撞，最大组 7） | **不是**载荷校验和/偏移派生；只依赖名字。**推测**=完整名字哈希/构建期资源 ID；算法未解（汉化不改名 ⇒ 无需重算） |
| `u32[10]` | **12-bit 名字哈希（打包）**：`hi6 = u32[10]>>16`(6 bit)、`lo6 = u32[10]&0x3F`(6 bit) | **哈希桶号 = (hi6<<6)\|lo6，3111/3111 完全吻合**（见 §3.4） | 只依赖名字；保留原值即可 |
| `u32[11]` | **hash_chain_next**：同桶冲突链的 next（1-based 条目号，0=链尾） | 4096 槽桶表里 1602 个非空桶，沿 [11] 遍历恰好覆盖 3111 条、无环无重、最长链 16、平均 1.942 | 只依赖名字集合；保留原值 |

**异常/边界（全部已列清，无未解释的“坏条目”）**：
* **5 条 stored>real**：`C_CHATTER_IN.WAV(3308/3300)`、`C_CHATTER_IN2.WAV(4498/4490)`、`C_CHATTER_OUT.WAV(4432/4424)`、`C_CHATTER_OUT2.WAV(6084/6076)`、`I_ERROR1.WAV(1856/1848)`。
  实测载荷 = `{u32 real}{u32 real}` + **原样 RIFF WAVE**（即 8 B 伪帧头 + 未压缩 wav）⇒ stored=real+8，**不是异常压缩**。
* **95 条零长条目**（stored==real==0）：SS 77 条、SB 16 条、`Q.SAV`、以及一条平台占位 TXT；这些条目 off 指向后继（或共享）位置，引擎按长度 0 处理。
* 重名 0、忽略大小写重名 0、条目重叠 0。

### 3.4 哈希桶表 + 名字排序链（全部实证，自检通过）

* 哈希桶表 @`+0x20`：**4096 个 u32 槽**，`0xFFFFFFFF` 为空；非空槽 = **1602** 个，值=条目号+1。
* **桶号公式（本报告关键新发现）**：`bucket = ((u32[10] >> 16) << 6) | (u32[10] & 0x3F)`（等价于 u32[10] 内藏一个 12-bit 名字哈希；hi6 在 bit[21:16]，lo6 在 bit[5:0]）。**3111/3111 与盘上桶表一致**。
* 冲突链：从桶值-1 出发，沿条目 `u32[11]`-1 前进直到 0；覆盖 3111 条、无环、无重复，最长链 16（平均 1.942）。
* 名字排序链：`u32[1]` 唯一 head=#326，走 3111 条到 tail=#971，顺序与名字字节升序**完全相同** ⇒ 该链 = 按名字排序的资源枚举链（**推测**：引擎目录枚举/资源加载顺序用）。
* **对汉化的意义**：名字不改 ⇒ 名字区、这两个链、哈希桶表全部**零改动**；条目载荷搬家（off 改变）不影响它们（桶表/链存的是**条目号**，不是偏移）。

### 3.5 载荷帧格式（含 raw 块规则；规则已并入核心库）

**原样条目**（`stored==real`，1914 条）：盘上字节即负载；内部可能自带压缩/打包（如 PAK/RSB 自带结构），但条目层不解释。

**LZO 条目**（`stored!=real`，1197 条）：负载 = 顺序帧：

```
帧 := {u32 clen}{u32 rlen}{clen 字节 payload}
· clen <  rlen：payload = LZO1X 压缩流，展开 rlen 字节
· clen == rlen：payload = 原样未压缩块（直接当 rlen 字节用）   ← ★ 本次新发现的规则
real = Σ rlen ；stored = Σ(8+clen)（本盘 LZO 条目 intra_slack 全为 0）
```

**实证统计**：1197 条 LZO 条目共 **13,393 帧**；其中 **355 个 raw 块**（296 个在条目中间、59 个在条目末尾）；
按帧数分布：1 帧 557 条、2 帧 150 条、3 帧 87 条、…、最大 **198 帧**（长视频/大资源）；**1197/1197 条全部精确展开到 real，0 失败**。

**★ 对核心库的影响（已解决）**：
本报告完成时 `tools/dlc/dlclib.py` 的 `lzo_subs()` 已按本结论更新为「`clen==rlen` ⇒ 原样块」。
更新前它会把所有帧都当 LZO 解、遇到 raw 块提前终止 ⇒ 全盘 **107 条**被误判为「不可解」：
`BMZ 65 / CHZ 10 / MOL 8 / LNG 6 / WAV 5 / POB 3 / QOB 2 / POZ 2 / MAZ 2 / MIS 1（CP03_PRISON.MIS）/ ICO 1 / QOZ 1 / LOG 1`。
**复验（更新后）**：3111/3111 条 `entry_payload()` 展开 0 失败；`CP03_PRISON.MIS` 子流 = `[{clen 4954 → 16384}, {clen 969 == rlen 969 原样}]`，总长 17,353 == real ✓。

### 3.6 条目间 slack / 文件尾空间（对“能不能原地改大”至关重要）

以 off 排序后，`slack(i) = off(i+1) − (off(i)+stored(i))`，最后一条以容器 size 为界：

| 指标 | 值 |
|---|---|
| slack == 0 的条目 | **438 条** |
| 1 ≤ slack ≤ 2047 | 2,672 条 |
| slack ≥ 2048 | 1 条（最后一条 #3110 占整个 65,536 B 尾垫） |
| slack 合计（含尾垫） | **171,145 B** |
| slack 合计（不含尾垫） | **105,609 B** |
| 最大单条（不含尾垫） | **41 条 PSS 前的 2,044 B/条 = 83,804 B**（`C01.PSS`…`UBI_ADVERT.PSS` 等全部 41 个 `.PSS` 视频条目之前，规律性排布） |
| 其余 2,631 条小空隙合计 | **21,805 B**（平均 ≈8 B/条；其中 438 条为 0） |
| 负 slack（重叠） | **0** |

**结论**：GR.IMG 条目**几乎背靠背**——一般条目没有几百字节以上余量。
⇒ 任何**变大的载荷**（字库图集、文本重压后变大）都必须**搬条目**（或整体重排）；
　 任何**变小的载荷**可原地更新并缩小 `stored`（留下空洞合法，font-engineer 已按此思路做过本体工程）。
> 参考：font-engineer 的 P1-C 方案 B 正是把 `COMMON.PAK`(#9, 763,676 B) 搬到 data_end 后的 64 KiB 尾垫 + 卷尾扩容区，只改 #9 的 `[6][7][8]`；本报告 §3.3 已确认其余 8 个字段与哈希结构不依赖偏移/内容。

---

## 4. 资源类型分类（3111 条，64 种扩展名）

### 4.1 分类总表（「与汉化关系」列是重点）

**A. 文本 / 定义类（XML 家族；实证：payload 以 `<XxxFile>` 开头，可直接按 XML/文本读）**

| 扩展名 | 条数 | raw/LZO | stored | real | 类别与说明 | 与汉化关系 |
|---|---|---|---|---|---|---|
| `.ATR` | 766 | 766/0 | 511,990 | 511,990 | `<ActorFile>` 角色(AI)定义；含 `<ActorName>`/`<ClassName>` 等 | ★ 有显示名（角色名/兵种） |
| `.KIT` | 191 | 191/0 | 76,865 | 76,865 | `<KitFile>` 装备包（纯文件引用） | 间接（名由 TXT/LANG 决定） |
| `.GUN` | 66 | 0/66 | 69,863 | 178,672 | `<GunFile>` 武器定义；`<NameToken>WPN_xxx` | 间接（NameToken→EN_STRINGS.TXT） |
| `.MIS` | 45 | 0/45 | 670,806 | 2,641,606 | `<MissionFile>` 任务定义/简报/脚本 | ★ 任务名/地名/日期/简报（多数经 `*Id`→LANG） |
| `.ENV` | 37 | 36/1 | 20,063 | 20,771 | `<EnvironmentFile>` 环境定义 | 无（仅文件引用） |
| `.TOE` | 20 | 1/19 | 8,703 | 23,688 | `<TOEFile>` 编制表 | 无 |
| `.GTF` | 14 | 0/14 | 33,310 | 146,957 | `<GameTypeFile>` 多人模式定义（含 ScriptCompiled） | ★ 模式名/说明（`*Id`→LANG） |
| `.XML` | 11 | 4/7 | 300,889 | 714,027 | 见 §4.2；其中 5 个是 SFXML 五语副本 | ★ EN_SPECIAL_FEATURE.XML |
| `.PRJ` | 10 | 10/0 | 9,230 | 9,230 | `<ProjectileFile>` 抛射物 | 无 |
| `.VCL` | 7 | 7/0 | 2,952 | 2,952 | `<VehicleFile>` 载具 | 无 |
| `.ITM` | 7 | 6/1 | 4,469 | 6,402 | `<HandHeldItemFile>` 手持道具（NameToken） | 间接 |
| `.CSF` | 2 | 2/0 | 752 | 752 | `<CampaignStateFile>` 战役存档模板 | 无（仅测试存档） |
| `.PSF` | 2 | 2/0 | 602 | 602 | `<ProfileStateFile>` 档案存档模板 | 无 |
| `.KIL` | 2 | 0/2 | 2,932 | 40,724 | `<KitRestriction>` 装备限制 | 无（Name 属性为内部 ID） |

**B. 语言表 / 文本数据**

| 扩展名 | 条数 | raw/LZO | stored | real | 说明 | 与汉化关系 |
|---|---|---|---|---|---|---|
| `.RES` | 8 | 0/8 | 513,428 | 2,094,631 | `*_STRINGS.RES` 5 语 LANG（各 66-67 组/2,232-2,974 条）；`FONT.RES` 字库定义；`IKE.RES`/`NTSC_IKE.RES` 菜单布局 | ★★ EN_STRINGS.RES 主文本；FONT.RES 字库 |
| `.TXT` | 8 | 2/6 | 16,908 | 42,272 | `*_STRINGS.TXT` 5 语 token→文本表（各 228 键）；EN 值 1,648 B | ★ 武器/物品/Kit 名 |
| `.DIR` | 37 | 29/8 | 12,913 | 38,885 | 路径清单（`045_MENU\MISSION\...`） | 否（开发/索引） |
| `.LST` / `.XBS` / `.WRD` | 1 / 9 / 6 | — | 4,509 / 23,961 / 1,619 | 25,470 / 110,123 / 1,619 | 语音清单/声音事件表/语音识别词表 | 否（非显示） |
| `.LOG` / `.SDF` / `.CONFIG` / `.BAT` | 1 / 1 / 1 / 2 | — | 12,911 / 7,391 / 860 / 725 | 148,303 / 24,708 / 2,495 / 725 | PC 开发残留（`e:\gr\...` 路径、ScriptEd 定义、打包配置、清理脚本） | 否 |

**C. 图像 / 图集**

| 扩展名 | 条数 | raw/LZO | stored | real | 说明 | 与汉化关系 |
|---|---|---|---|---|---|---|
| `.PAK` | 40 | 40/0 | 4,503,824 | 4,503,824 | 纹理图集包（GS 纹理记录 + JPEG 记录，见 §6） | ★★ 字库图集 `COMMON.PAK/new_font_revised`；菜单/简报/加载图（可能有烘焙英文） |
| `.RSB` | 199 | 199/0 | 11,183,215 | 11,183,215 | 贴图包（Red Storm Bitmap；自带内部结构） | ★ 可能有烘焙英文（菜单/徽标） |
| `.ICO` | 3 | 0/3 | 126,663 | 286,000 | 内存卡图标 | 否 |
| `.BMZ` | 299 | 1/298 | 60,946,710 | 91,813,848 | 压缩贴图（推测；LZO 多帧，含大量 raw 块） | 否（角色/物体贴图） |

**D. 模型 / 地图 / 动画（与汉化无关）**：`.POB` 183、`.QOB` 177、`.QOZ` 101、`.CHA` 66、`.XBG` 66、`.CHZ` 65、`.POZ` 62、`.AOL` 32、`.MAZ` 32、`.MOL` 32、`.POL` 32、`.SHT` 32、`.ANM` 7、`.SCN` 3、`.CHR` 1
（头特征实证：POB=`BeginPOB`、QOB=`BeginModel`、ANM=`BeginANM`、SHT=`RoomData`、AOL=`Version`；其余为同类二进制，推测为模型/地图布局/LOD）

**E. 音频 / 视频（与汉化无关，不做配音）**：`.SS` 101（207.3 MB）、`.SB` 101（20.4 MB）、`.SH` 101、`.WAV` 5、`.AUD` 3、`.THC` 4；`.PSS` 42（580.6 MB 视频）、`.TM` 2（155.1 MB）、`.MPG` 1（1.6 MB）

**F. 其它数据**：`.IDC` 35（索引表）、`.CTX` 6、`.GCD` 6、`.SAV` 2、`.CSF_BIN` 3、`.PSF_BIN` 2、`.LNG` 6（多语种**语音识别模型**数据，非文本）、`.KEYS`/`.BUT`/`.ASS` 各 1（按键映射、DedServer 脚本）、`.RPF` 1（回放模板）、`.GRM` 1

### 4.2 11 个 `.XML` 明细

| 文件 | 大小(real) | 内容 | 玩家可见文本 |
|---|---|---|---|
| `EN_SPECIAL_FEATURE.XML` | 133,359 | `<SpecialFeatures>`：画廊/专家档案（`<studio>/<group>/<picname>/<text>`） | **★ 81 条非空 `<text>` / 96,438 B** |
| `DE/ES/FR/IT_SPECIAL_FEATURE.XML` | 140-145 KB | 同上，4 语副本 | US 版不读（保留原样即可） |
| `CAMPAIGN.XML` | 1,486 | 战役任务顺序/英雄（文件引用） | 否 |
| `OPTIONS.XML` | 3,737 | 默认设置（控制器/画面/声音） | 否 |
| `UNLOCKED_HEROES.XML` | 397 | 已解锁英雄（`.atr` 引用） | 否 |
| `UNLOCKED_MISSIONS.XML` | 598 | 已解锁任务（`.mis` 引用） | 否 |
| `BEST_TIMES.XML` | 14 | `<BestTimes/>` 空 | 否 |
| `CMBTMODL.XML` | 823 | 战斗模型系数 | 否 |

### 4.3 字库相关（与本报告交叉的结论；细节见 ANALYSIS_FONT.md）

* `FONT.RES` #580：LZO，stored 4,460 / real 7,466；3 个 face（large/default/huge）；LZO 1 帧（无 raw 块）。
* `COMMON.PAK` #9：**原样**（stored==real=763,676）；10 条记录；字库图集记录：
  `new_font_revised` ty=0 **psm=19(PSMT8) 512×512 / clut=1040 B / px=262,160 B**（=16 B GIF tag + 512×512 字节像素，raw 无压缩）；
  另有 `pda-lcd-02`(psm20 256×256 clut80)、`pda_counterparts`(psm19 256×256)、kit 图标 ×4、`reticle_misc`、`ingame_bgd_controller`。
* 文本折行还牵涉 `IKE.RES`/`NTSC_IKE.RES`（各 555,974 B，34 帧；菜单布局记录，本报告只确认“无显示文本值”，布局与 TEXT 组件宽度见本体工程 REPORT_* 与 text/font 分析）。

### 4.4 可能“烘焙英文”的贴图/视频候选（**无法离线证伪，列清单供实机确认**）

| 来源 | 候选记录/文件 | 理由 |
|---|---|---|
| `MENU.PAK`(GR#25) | `multi_pressstart`(512×256)、`gr_ds_logo`、`dnas_lg`、`ranks2`(256×64)、`rank_insignia`、`modes`、`gamedifftype_icon`、`movie_select`、`online-plus`、`decorations`、`gr_ds`，以及 5 张 JPEG：`dmg_logo`/`gr_ds_gr`/`shell_screen_adjust`/`start_bg`(130 KB)/`shell_bgd_controller`(94 KB) | 名字直指 UI 文本/徽标/“Press Start”类画面 |
| `LOADING.PAK`(GR#24) | `load-screen`(640×480 纹理)、`load-circle`、`load_icon`、38 张 `*_shots` 任务加载截图 | 加载画面常带任务名/提示文字 |
| 各任务 `*.PAK` | `<map>_brfg-box`（简报框背景）、`<map>_briefing`（简报图）、`TAC0x_*_briefing` | 简报是地图截图/说明图，可能带烘焙英文 |
| `ACTION.PAK`(GR#0) | `icons_interface`、`background_interface`、`radar`、`reticle_*`、`m03_bridge_overlay` | HUD 图标/准星/雷达，通常为图形；`background_interface` 可能有字 |
| `RSB` 199 个 | 名字含 menu/logo/title/briefing 等（需按名字筛） | 同类贴图 |
| `.PSS` 42 个 / `TM` 2 / `MPG` 1 | 片头/广告/过场 | 视频内文字若有则是烘焙像素；ASCII 普查未发现字幕流（**推测**无独立字幕） |

> 结论：这些“烘焙英文”**不是本报告能定论的**（没有 OCR 就不算实证）。它们不属于“文本表”汉化路径，
> 若要处理必须图像级重绘（PAK ty=2 还涉及未识别压缩算法）。建议按 PLAN.md §4 单独列清单、实机核对后再决定。

---

## 5. 英文文本普查（全部 3111 条展开后统计）

### 5.1 方法

对每个条目：原样条目直接取盘上字节；LZO 条目按 §3.5 规则展开（含 raw 块）⇒ 得到 **展开后 payload**；
用 `[\x20-\x7e]{4,}` 统计“可打印 ASCII 串”，并逐资源做结构化解析（LANG/SFXML/XML/MIS/ATR/GTF/TXT…）。
机器可读明细：`assets/manifests/gr_img_index.json` 每条含 `text_runs/text_bytes/text_ratio`；
`work/analysis/iso/text_samples.tsv` 含每个文本类资源的样本串。

### 5.2 全盘 ASCII 总量（含噪声，勿当“文本量”）

* 全部 3111 条 payload 合计 **10,367,343 个 ASCII 串（≥4 字符）/ 74,912,746 字符**。
* 但这**绝大多数是二进制噪声**：Top 条目全是视频/音频/贴图——`MUSIC.TM`（16.0 M 字符）、`UBI_ADVERT.PSS`（4.8 M）、`UBI_ADVERT_PAL.PSS`（4.6 M）、`MENU.TM`（2.0 M）、`IT_INTRO_PAL.PSS`（0.93 M）、`CP01_HUNTING_LODGE.BMZ`（0.76 M）……
* 判别依据：这些资源的 ASCII 串无空格分隔/无英文词形（如 `b'm~*+r@*w'`、`b' 0 !2EEVF22&'`），或长串概率符合随机字节。
* **结论：玩家可见文本必须按“资源类型 + 结构化解析”定位，不能按 ASCII 量排序。**

### 5.3 结构化文本资源逐类统计（★ 汉化范围的核心表）

| 资源 | 条数 | 解析结果 | 文本字节 | 说明/证据 |
|---|---|---|---|---|
| `EN_STRINGS.RES`（LANG） | 1 | `parse_lang` 成功：**67 组 / 2,971 条** | **159,071 B** | payload 177,441（LZO 69,355，11 帧），used_end 177,433，尾部 8 B |
| `EN_SPECIAL_FEATURE.XML`（SFXML） | 1 | `<text>` **98 个 / 非空 81** | **96,438 B**（`<text>` 正文）；去标签全文 103,397 字符 | 含 cp1252 非 ASCII（如 0xBE=¾）；其它 4 语副本不属 EN 范围 |
| `*.MIS` | 45 | XML；显示字段：Name/MapName/LocationText/DateText/TimeText/BriefingText | 字面量合计 **26,187 B**（Name 759、MapName 619、Location 836、Date 600、Time 225、BriefingText 23,148/21 个；另 `RecommendedGameTypes` 16 B ⇒ text-engineer 口径 26,203 B） | 全部 XML 文本 1,032,719 B 中 **999,302 B 是 `ScriptSource`+`ScriptCompiled`（AI/任务脚本，非文本）** |
| `*.ATR` | 766 | XML；`<ActorName>` 766 条（**distinct 279 个名字**，大量变体共用） | **9,583 B**（名字） | 另有 ClassName 7,605 B、FolderName 2,770 B、KitPath 2,692 B 等内部字段 |
| `*.GTF` | 14 | XML；`<Name>`14 + `<Comment>`14 | **1,566 B** | Name 142 + Comment 1,424；同时 `NameId/CommentId`→LANG |
| `EN_STRINGS.TXT` | 1 | token→英文键值表：**228 键** | 键 2,260 B / **值 1,648 B** | 段：weapons and items / actions / actors / keys / Kit restriction files；如 `WPN_M4`→`M4` |
| 其它 4 语 `*_STRINGS.TXT` | 4 | 各 228 键 | 各 ~1.6 KB 值 | 不属 EN 范围 |
| `.XML`（除 SFXML） | 6 | 见 §4.2 | ≈0 | 只有文件引用/配置值 |
| `.DIR` / `.LST` / `.XBS` / `.WRD` | 37/1/9/6 | 路径/文件名清单、语音识别词 | 非显示文本 | — |
| 开发残留 `.LOG/.SDF/.CONFIG/.BAT` | 5 | PC 端日志/脚本编辑器定义/打包配置/清理脚本 | 非显示文本 | 含 `e:\gr\closing source gm 10\...` 路径 |
| `IKE.RES`/`NTSC_IKE.RES` | 2 | 菜单布局资源（含组件名如 `TITLE_TEXT`、`PRESSSTARTBTN`、屏幕名） | 无显示文本值 | 组件名是查找键；实际字符串来自 LANG；但 TEXT 组件宽度影响折行 |

**⇒ “玩家可见英文”最终分布（实证结论）**：

```
LANG EN_STRINGS.RES        159,071 B  (2,971 条)      ← 主战场（UI/任务/教程/多人/菜单/制作名单…）
SFXML EN_SPECIAL_FEATURE    96,438 B  (81 条)         ← 专家档案/武器说明（画廊）
MIS 字面量显示字段           26,187 B  (45 文件)       ← 与 LANG 高度重复（43 个任务 *Id→LANG）
ATR <ActorName>              9,583 B  (766 条)        ← 角色名（是否上屏待实机）
EN_STRINGS.TXT 值            1,648 B  (228 键)        ← 武器/物品/Kit 名
GTF Name+Comment             1,566 B  (14 条)         ← 与 LANG 重复（*Id→LANG）
其它 XML/DIR/LST/WRD/XBS       0       （无显示文本）
```

### 5.4 LANG 67 组分布（`EN_STRINGS.RES`，实证）

> 组号口径：本表用 `dlclib.parse_lang` 的 **0-based g**；text-engineer 的 `assets/text/source/manifest_lang.json` 用 **1-based（G001 = g0）**，对照时注意 -1。
> 富文本标记（text-engineer 统计）：LANG 内 `{p}`×136、`{br}`×5；非 ASCII 字节共 104 个（cp1252：®×48、é×34、ç×5、ö×4、î×3、ñ×2、è×2、ë×2、©/É/ó/ô 各 1）。

| 组 | 条数 | 文本字节 | 内容（抽样判读） |
|---|---|---|---|
| 0-10 | 5,6,10,6,6,6,5,8,6,8,10 | 92..445 | 各游戏模式的胜负/平局/提示串（Firefight/Recon/Siege/… 及其说明） |
| 11-17 | 各 49（共 343） | 各 ~7.4 KB | **教程/操作提示长文本 ×7 套**（"The assault rifle is your primary infantry weapon…"） |
| 18-32 | 15-24（共 15 组） | 60..2,160 | **各任务专属串**：Mission Complete/Failed、目标提示、任务名/地图名/地点/日期（`*Id` 指向这里） |
| 33-37 | 各 7 | 56..82 | 多人地图名/标题/地点（MP01-MP05） |
| 38 | 25 | 2,159 | "Objective N completed" 类 |
| 39-43 | 各 7 | 56..76 | CP01-CP05 地图名/标题 |
| 44-46 | 7,8,12 | 329..458 | 基地被占/胜负类 |
| 47-51 | 13..19 | 781..1,033 | G/U/DP 系列任务串 |
| 52-56 | 各 7 | 57..78 | DP01-DP05 地图名 |
| 57 | **1,324** | **61,393** | 通用 UI 字符串（Ok/Delete/Resume/Press START/controller type/Character Selection/Options 等；1,317 条非空） |
| 58 | 41 | 478 | 存档确认类（DELETE SAVE / DELETE REPLAY / …） |
| 59 | 1 | 8 | `mainmenu` |
| 60 | 53 | 675 | 按键动作名（Quit/Move Forward/…） |
| 61 | 393 | 6,552 | **GAME CREDITS 制作名单**（含 `<title>`/`<br>` 富文本标记） |
| 62 | 24 | 144 | 贴图名（`01.rsb`…） |
| 63 | 10 | 143 | SF 画廊贴图名 |
| 64 | 145 | 1,841 | 选项/设置项 |
| 65 | 42 | 340 | 军衔名（No Rank/Private/PVT/…） |
| 66 | 7 | 79 | 菜单音效 wav 名 |

### 5.5 MIS/GTF 的 `<XxxId>` → LANG 映射（实证公式）

* 45 个 MIS 中 **43 个**同时有 `NameId/MapNameId/LocationId/DateId/TimeId/BriefingId`；**43/43 全部能在 LANG 中解析到条目**。
* 公式：**`id = (LANG 组号 << 20) | 组内序号`**（如 `C01_PLANTATION.MIS` 的 `NameId=18874370=0x1200002` → g=18, i=2 → `C01 - Watchful Yeoman`，与该 MIS 的 `<Name>` 字面量逐字相同）。
* 一致率：`Name` 43/43、`LocationText` 43/43、`DateText` 43/43、`TimeText` 43/43、`MapName` 41/43。
  **2 处字面量与 LANG 不一致（陈旧字面量）**：`G03_THE_ROCK.MIS` 写 `J01 Totem Ground` 而 LANG(g27,i2)=`J01 Dig Site`；`U03_RESCUE.MIS` 写 `J07 Whisper Shadow` 而 LANG(g32,i4)=`J07 Prison Camp`。
* `BriefingId` 43 个（LANG 里为目标任务的 briefing 长文）；另有 21 个 MIS 带字面量 `BriefingText`（合计 23,148 B，与 LANG 内容对应）。
* ⇒ **任务名/简报的“显示源”极可能是 LANG**（`*Id`），MIS 字面量是构建期副本；这一点必须实机确认（见 §10 风险）。

### 5.6 翻译工作量估算（供 P3 排期；非精确译文量）

| 类别 | 英文源字节 | 条目数 | 备注 |
|---|---|---|---|
| LANG | 159,071 | 2,971 | 必翻；含教程长文/制作名单/军衔/选项 |
| SFXML | 96,438 | 81 | 专家档案+武器说明长文 |
| EN_STRINGS.TXT 值 | 1,648 | 228 | 武器/物品/Kit 名，大部分是专名（M4/AK74…） |
| ATR ActorName | 9,583 | 766 | 人名（转写为主） |
| MIS 字面量 | 26,187 | 45 | 与 LANG 重复；若只翻 LANG 则此项为“同步校对”量 |
| GTF | 1,566 | 14 | 与 LANG 重复 |
| **合计（去重前）** | **≈294,493 B** | ≈4,105 项 | 去重后有效翻译量主要在 LANG+SFXML（≈255 KB 英文） |

> 参考本体工程：英文 LANG 文本 114,740 B → 中文数据量约为英文的 **48.6%**（资源级实测口径）。按同口径估算，
> 资料片中文 LANG 文本量约 **77 KB**，中文 SFXML 约 **47 KB** —— 即中文总数据量小于英文，**重压后大概率变小**，
> 这直接影响“原地改 vs 搬条目”的取舍（见 §8.4）。

### 5.7 与 text-engineer 独立 dump 的交叉验证

text-engineer 的 `tools/dlc/dump_text.py` 产出 `assets/text/source/source_stats.json`（独立实现），与本报告的数字对照：

| 指标 | 本报告 | text-engineer | 一致性 |
|---|---|---|---|
| LANG 组/条/文本字节 | 67 / 2,971 / 159,071 | 67 / 2,971 / 159,071 | ✅ 完全一致 |
| LANG blob/used_end/尾 | 177,441 / 177,433 / 8 | 177,441 / 177,433 / 8 | ✅ |
| SFXML `<text>` / 非空 / 字节 | 98 / 81 / 96,438 | 98 / 81 / 96,438 | ✅ |
| MIS 显示字段字节 | 26,187（6 字段） | 26,203（+RecommendedGameTypes 16 B） | ✅（口径差） |
| EN_STRINGS.TXT 键/值字节 | 228 / 1,648 | 228 / 1,648 | ✅ |
| ATR `ActorName` | 766 条 / 9,583 B | 766 条 / distinct 279 | ✅ |

其 `units` 统计（可直接作 P3 排期口径）：**total 4,485 项，其中 translatable 3,372**（LANG 2,851 / SFXML 81 / SFXML 标题 174 / MIS 248 / ATR 10 / TXT 8；keep 1,096）；
**player_visible_bytes = 283,279 B，player_visible_en_chars = 235,829**。
（与本报告 §5.6 的 294,493 B 差异主要在：ATR 名字只把 10 条计入“可译”、而 GTF/MIS 字面量与 LANG 的重复被其按单元去重。）

---

## 6. 40 个 `*.PAK` 纹理图集包（记录级结构，实证）

### 6.1 PAK 记录格式（三个记录类型）

```
PAK := 记录* 0x63
记录 := {u32 ty}{u32 nl}{nl 字节名字(可带 '\0')}   (ty=0/2：纹理记录；ty=3：JPEG 记录)
  ty=0 纹理记录（原样子段）:  {u32 psm}{u32 w}{u32 h}{u32 s1_len}{s1_len 字节}
                                [psm!=0 时]{u32 s2_len}{s2_len 字节}
  ty=2 纹理记录（压缩子段）:  同上字段，但每个子段 = {u32 未压缩长度}{压缩流}
  ty=3 JPEG 记录:            {u32 jpeg_size}{jpeg_size 字节 JPEG(SOI..EOI；EXIF 内嵌缩略图)}
psm==0 的记录只有 1 个子段（无像素段）。
```

* ty=0 = 原样 GS 纹理段（**实证**：`COMMON.PAK` 的 CLUT 段开头 16 B = GIF tag `40 80 00 00 00 00 00 08…`，长度 1040=16+1024；像素段 `px=16+w*h`）。
* ty=2 = 压缩纹理段（**实证**：每段前 4 B 恰为该段解压长度，如 CLUT=1040、像素=16+w*h；**压缩算法未识别**，见 §6.4）。
* ty=3 = JPEG（**实证**：JPEG 字节以 `FF D8 FF E0` + `JFIF` 开头、以 `FF D9` 结尾，`jpeg_size` 与下一记录对齐）。
* 记录区以 `u32 0x63` 终结符结束，之后无数据（**40/40 个 PAK 精确铺满**）。
* **修正**：`dlclib.parse_pak_records` 只识别 ty=0/2 的连续纹理段（遇到 psm=0 或 ty=3 会中断），且名字需 `rstrip('\0')`；完整口径见本表。

### 6.2 40 个 PAK 汇总（实测）

| PAK | stored | 记录数 | ty=0 | ty=2 | JPEG | 关键记录 |
|---|---|---|---|---|---|---|
| `COMMON.PAK`(#9) | 763,676 | **10** | 10 | 0 | 0 | `new_font_revised`(512×512 PSMT8, px=262,160)、`pda-lcd-02`(PSMT4 256×256)、`pda_counterparts`、kit 图标×4、`reticle_misc`、`ingame_bgd_controller` |
| `MENU.PAK`(#25) | 670,155 | **17** | 0 | 12 | **5** | 12 GS 纹理（`dnas_lg`、`gamedifftype_icon`、`gr_ds_logo`、`ranks2`、`multi_pressstart`、`modes`、`rank_insignia`、`platoonscreen`、`decorations`、`online-plus`、`movie_select`、`gr_ds`）+ 5 JPEG（`dmg_logo`/`gr_ds_gr`/`shell_screen_adjust`/`start_bg`/`shell_bgd_controller`） |
| `LOADING.PAK`(#24) | 1,225,516 | **41** | 0 | 41 | 0 | 38 张任务加载图（`*_shots`）+ `load-screen`(640×480)/`load-circle`/`load_icon` |
| `ACTION.PAK`(#0) | 53,141 | **15** | 0 | 15 | 0 | 准星 ×7、`icons_interface`、`background_interface`、`radar`、`ranks2`、`m03_bridge_overlay` |
| 8 个战役任务包 `C01-C08_*.PAK` | 64,048..92,393 | 各 2-3 | 0 | 2-3 | 0 | `<map>_brfg-box`（简报框）+ 任务图 |
| 5 个 `CP0x/DP0x/MP0x/G0x/U0x_*.PAK` | 10,232..115,779 | 各 1-2 | 0 | 1-2 | 0 | 任务/多人地图贴图 + `*_brfg-box` |
| 5 个 `TAC0x_*_PAK` | 30,312..39,964 | 各 2 | 0 | 2 | 0 | `mp0x_brfg-box` + `tac0x_*_briefing` |

合计：**40 个 PAK / 141 条记录（136 纹理 + 5 JPEG）**；全部 `stored==real`（条目层原样），每 PAK 末尾 `0x63`。

### 6.3 与本体同名 PAK 对比（实证）

* 本体（USA）9 个同名 PAK 及其规模（本体 GR.IMG 内）：
  `ACTION.PAK` 209,704 B / 122 rec（120 ty2 + 2 ty0）、`COMMON.PAK` 400,659 B（`arrow` + `new_font_revised` 等）、
  `LOADING.PAK` 4,704,281 B / 45 rec、`MENU.PAK` 3,099,360 B / 173 rec（123 纹理 + **50 JPEG**）、5 个 `TAC0x`（各 2 rec）。
  资料片对应：`ACTION.PAK` 53,141 B / 15 rec、`COMMON.PAK` 763,676 B / 10 rec、`LOADING.PAK` 1,225,516 B / 41 rec、`MENU.PAK` 670,155 B / 17 rec（12 纹理 + 5 JPEG）。
  ⇒ 资料片菜单/加载图集**大幅精简**（MENU 173→17、LOADING 45→41），并**新增 31 个 PAK**（8 战役 + CP/DP/MP/G/U 系列简报图集）。
* `COMMON.PAK`：本体记录 0（`arrow`）的字段序/对齐与本资料片略有差异（本体解析器在该记录后中断；`new_font_revised` 记录本身与资料片同构：psm=19、512×512、clut=1040、px=262160）。**该差异不影响本工程构建链**。
* 本体中文成品盘 `COMMON.PAK` 的 `new_font_revised` = **1024×644 PSMT4 / px=329,744**（字库工程已完成的重排结果，见 ANALYSIS_FONT.md）。
* 资料片**英文**盘 `new_font_revised` = **512×512 PSMT8 / px=262,160**（=16+262,144，raw）。

### 6.4 ty=2 压缩算法：已排除的候选（未识别，列此备查）

对 ty=2 子段（结构 = `{u32 未压缩长度}` + 压缩流）做过以下候选取证，**全部不符**：
LZO1X（含 raw-block 变体）、zlib、raw deflate、LZ4 block、LZF、LZSS（8-bit flag / 高位或低位标志 / literal 极性两版）、PackBits。
佐证：同一 PAK 内所有 CLUT 子段的前 12 B 完全相同（`10 04 00 00 80 00 02 68 17 10 8A 85`，
即 `u32 未压缩长度=1040` + 8 B 固定前缀），之后各段不同 ⇒ 是“固定头 + 压缩数据”；
盘上字节数普遍只有解压长度的 10%~90%（个别 CLUT 段略大于解压长度，可能含额外头部/填充），**确有压缩**。
▶ **影响评估**：汉化不需要重压 ty=2 子段（字库图集在 ty=0 的 `COMMON.PAK`，菜单/简报图若不做烘焙文字重绘也不需要动）；
▶ 若将来要改菜单图（烘焙英文），需要先逆向该算法或整体替换文件（不在本次范围）。
（**推测**：这是 RSE 自研纹理压缩/PS2 GS 专用打包；ELF 内嵌 `minilzo.c` 字符串只说明 LZO 用于 IMG 层。）

---

## 7. 与本体《Ghost Recon (2001, USA)》对比（task-1 第 7 项）

本体盘：`C:\Users\84363\Desktop\Ghost_Recon_2001_Locolization\third_party\orig\ps2\Tom Clancy's Ghost Recon (USA).iso`
（1,648,164,864 B；root 只有 `SLUS_206.13`/`GR.IMG`/`MENU.IMG`/`MODULES`/`SYSTEM.CNF`；GR.IMG@LBA 19175 / 4,070 条；MENU.IMG@LBA 776286 / 686 条）

### 7.1 资源名集合

| 指标 | 数量 |
|---|---|
| 本体资源名（GR∪MENU 去重） | **4,070** |
| 资料片资源名 | **3,111** |
| **继承**（资料片与本体同名） | **1,562**（其中 1,562 个在本体 GR.IMG、567 个也在本体 MENU.IMG） |
| **资料片新增** | **1,549** |
| **本体独有**（资料片删掉） | **2,508** |

继承/新增/独有清单：
`work/analysis/iso/base_inherited.txt`、`base_new_in_dlc.txt`、`base_only_in_base.txt`（各一行一个名字）。

### 7.2 同名资源内容对比（载荷 sha256，实证）

* 同名 1,562 条中：**载荷逐字节相同 729 条，已改 833 条**。
* 已改的扩展名分布：ATR 248、KIT 104、SH 73、SB 57、RSB 50、GUN 40、SS 40、BMZ 26、MIS 22、DIR 18、ENV 15、IDC 12、CHA/CHZ/AOL/MAZ/MOL/SHT 各 11、GTF 10、PAK 9、RES 8、XML 7、TXT 6、…（即大量“重编译”型差异）。
* **名字键（u32[9]/u32[10]）在 1,562 个同名资源上 100% 相同**（含内容已改的条目）⇒ 再次证明二者只由名字决定，**不是载荷校验和**。
* 详细清单：`work/analysis/iso/base_changed_payload.txt`。

### 7.3 文本资源量对比（实证）

| 资源 | 本体 GR.IMG | 本体 MENU.IMG | 资料片 | 差异（资料片−本体） |
|---|---|---|---|---|
| `EN_STRINGS.RES` 组数 | 66 | 66 | **67** | +1（新增一组任务串） |
| 　条目数 | 2,232 | 2,232 | **2,971** | **+739** |
| 　文本字节 | 114,740 | 114,617 | **159,071** | **+44,331 (+38.6%)** |
| 　stored / real | 47,619 / 128,668 | 47,570 / 128,545 | 69,355 / 177,441 | +21,736 / +48,773 |
| `EN_SPECIAL_FEATURE.XML` `<text>` | 69 / 非空 58 | 69 / 58 | **98 / 81** | +29 / +23 |
| 　`<text>` 文本字节 | 84,123 | 84,065 | **96,438** | **+12,315** |

其它文本/定义资源数量（本体 GR / 本体 MENU / 资料片）：
`MIS 46/46/45`、`ATR 1193/267/766`、`GTF 11/11/14`、`GUN 49/49/66`、`KIT 141/109/191`、`XML 20/17/11`、`RES 8/7/8`、`TXT 12/6/8`、`DIR 40/31/37`。
资料片新增文本类资源里与汉化相关的共 **581 个**（其中 ATR 518、MIS 23、GTF 4、PAK 31（简报图集）等）。

---

## 8. 对汉化的结论（★ 本报告最终交付）

### 8.1 必须改（数据层，按优先级）

| # | 资源 | 位置 | 量 | 说明 |
|---|---|---|---|---|
| 1 | **LANG** `EN_STRINGS.RES` | GR#576 | 67 组 / 2,971 条 / 159,071 B | **唯一主文本表**。资料片只有 **1 份**（不像本体有 MENU+GR 两份）⇒ 不存在“双拷贝必须同写”的问题。payload LZO 11 帧；尾部仅 8 B 余量 |
| 2 | **SFXML** `EN_SPECIAL_FEATURE.XML` | GR#3101 | 81 条非空 `<text>` / 96,438 B | 专家档案/武器说明。另有 4 语副本（DE/ES/FR/IT）**不要动** |
| 3 | **`EN_STRINGS.TXT`** | GR#577 | 228 键 / 值 1,648 B | 武器/物品/Kit 名。**本体工程结论**：`MENU.IMG#30` 拷贝已被汉化（中文实际显示），⇒ 引擎运行时可能读它。本盘只有 GR 单拷贝。**需要注入通道**（本体工程一直缺；DLC 侧 `stored 2,822 / real 7,092`，同样贴紧） |
| 4 | **MIS 字面量 + GTF 字面量**（与 LANG 同步） | 45+14 个 | ~27.7 KB | 与 LANG 重复；`*Id` 43/43 → LANG。**建议**：LANG 必翻；MIS/GTF 字面量做同样译文（至少要处理 2 个陈旧 MapName）。显示路径待实机确认（§10） |
| 5 | **ATR `<ActorName>`** | 766 个 | 9,583 B | 角色名。本体工程曾汉化“专家档案/角色名”相关屏（IKE/语言表），说明这类名字有显示路径；是否由 ATR 直读需实机 |
| 6 | **字库**：`FONT.RES`(GR#580) + `COMMON.PAK`(GR#9) 的 `new_font_revised` 图集 | | FONT.RES real 7,466 B；图集 raw 262,160 B | 由 font-engineer 负责（ANALYSIS_FONT.md）。本报告提供：图集记录为 **ty=0 原样段**、`stored==real`、16 B GIF tag + 512×512 PSMT8；`COMMON.PAK` 扩容需搬条目（§3.6） |

### 8.2 可选 / 待实机确认（TBD，不阻塞主线）

* **烘焙英文贴图/JPEG/视频**（§4.4 清单）：无法离线证伪；若实机看到英文，只能图像级重绘。PAK ty=2 压缩算法未识别，重绘成本高。
* **IKE.RES / NTSC_IKE.RES 布局**：没有显示文本值，但中文折行可能需要改 TEXT 组件宽度（本体工程改过 270→286→294；资料片菜单布局需单独核）。
* **PSS/TM/MPG 视频内字幕**：ASCII 普查未发现字幕流（**推测**无独立字幕；视频内文字为烘焙像素）。

### 8.3 明确不需要改

* 所有**名字/条目结构**：名字区、哈希桶表、名字排序链、`[0][1][9][10][11]` 一律不动（§3.3/§3.4）。
* 音频/视频/模型/地图/动画（SB/SH/SS/WAV/PSS/TM/MPG/POB/QOB/…）：保留原盘字节。
* 非 EN 语言的 `DE/ES/FR/IT_STRINGS.RES/.TXT/SPECIAL_FEATURE.XML`：不属美版汉化范围，保留。
* 开发残留（DIR/LST/XBS/WRD/LOG/SDF/CONFIG/BAT）与 `DNAS/OFFLINE/ONLINE/MODULES/LICENSE`：不动。
* ELF：本报告不含结论；ELF/引擎能力见 ANALYSIS_ELF.md（若 ELF 分析结论是“需补丁”，另计）。

### 8.4 工程约束与已确认的实现路线

1. **GR.IMG 条目贴紧**：除 64 KiB 尾垫与 41 个 2,044 B 空隙，其余条目间空隙合计仅 21,805 B（平均 ≈8 B/条，其中 438 条为 0）。
   * 载荷**变大** ⇒ 必须**搬条目**（推荐搬到 data_end 之后并延长容器），同时改该条目 `[6][7][8]`（+必要时 `[4]`）。
   * 载荷**变小** ⇒ 可原地更新、缩小 `[6]`（保留空洞；`[7]`=新 real）。
   * 无论哪种：**`[0][1][9][10][11]` 原样保留**；哈希桶表/名字表/排序链零改动；头 `+0x00` 按「新 data_end + 0x10000」维护；ISO 侧同步 root dir `GR.IMG;1` 的 size(LE/BE) 与 PVD `volume_space`(LE/BE)。
   * 本盘已有先例/验证：font-engineer 的 `COMMON.PAK` 方案 B（见 ANALYSIS_FONT.md）。
2. **核心库修复（已解决）**：`tools/dlc/dlclib.py` 的 `lzo_subs()/entry_payload()` 已支持「`clen==rlen` ⇒ 原样块」；复验 3111/3111 条 0 失败（§3.5）。
3. **文本注入通道（已落地，text-engineer）**：`tools/dlc/inject_text.py` 已覆盖 LANG/SFXML/MIS/ATR/STRINGS_TXT 的 blob 生成与校验；`tools/dlc/rebuild.py`/`build.py` 负责写回 ISO（条目表/偏移/ISO 尺寸自动维护）。“读原槽→替换→整份重压→校验帧长≤原 stored 或搬条目”的流程按本报告 §8.4-1 的规则实现即可。
4. **扩盘余量**：可用连续空闲 56,903 扇区（111.1 MiB）+ 卷尾可延长（DVD5 现用 26.2%）；若只扩文本/图集，完全够用（§2.3）。
5. **中文数据量预估**：按本体工程口径（中文约英文 48.6%），LANG 中文 ~77 KB、SFXML ~47 KB，合计仍远小于英文 ⇒ 重压后**大概率变小**，多数文本条目可原地缩 `stored`；仅字库图集（+66 KB）与个别变大条目必须搬。

---

## 9. 产出清单

| 文件 | 说明 |
|---|---|
| `docs/ANALYSIS_ISO.md` | 本报告 |
| `assets/manifests/gr_img_index.json` | **3111 条全量机器可读清单**（1.61 MB）：头 12 字段+逐字段语义、哈希表/排序链统计、每条 `{i,name,ext,res_class,kind,status,nsub,nraw,stored,real,off,frame_bytes,intra_slack,text_runs,text_bytes,text_ratio,sha256,is_text,player_visible}`、扩展名汇总、文本资源结构化统计、异常与玩家可见资源表 |
| `tools/analysis/iso_img_scan.py` | GR.IMG 全量分析（`--header/--quick/--limit`） |
| `tools/analysis/iso_layer.py` | ISO9660/PVD/目录树/关键文件/空间账本（`--no-sha256`） |
| `tools/analysis/iso_pak_scan.py` | 40 PAK 记录级解析 + 与本体/本体中文盘对比（`--summary/--no-base`） |
| `tools/analysis/iso_base_compare.py` | 资料片 vs 本体对比（`--no-payload-sha`） |
| `work/analysis/iso/gr_img_entries.tsv` | 3111 条明细（含 slack、kind、文本统计、sha256） |
| `work/analysis/iso/text_samples.tsv` | 文本类资源样本串（1.8 MB） |
| `work/analysis/iso/text_census_by_resource.tsv` | **按文本量排序**的 3111 条 ASCII 普查清单（含 `is_text` 标记与 ratio） |
| `work/analysis/iso/text_resource_stats.json` | LANG/SFXML/XML/MIS/ATR/GTF 等结构化文本统计 |
| `work/analysis/iso/iso_layer.json` / `pak_records.json` / `base_compare.json` | 中间结果 |
| `work/analysis/iso/base_*.txt` | 继承/新增/本体独有/已改载荷 名单 |

（`work/**` 为 gitignored 中间产物；`assets/**`、`docs/**`、`tools/**` 进库。）

---

## 10. 风险与未解问题

| # | 问题 | 影响 | 现状/建议 |
|---|---|---|---|
| R1 | **PAK ty=2 压缩算法未识别** | 无法替换菜单/简报纹理（烘焙英文）；不影响字库（COMMON.PAK 是 ty=0 原样） | 已排除 7 类常见算法；列为 TBD，不动 |
| R2 | **`u32[9]` 的算法未解**（32-bit 名字键） | 只有**改名/新增资源名**才需要重算；本工程不改名 | 实证“只依赖名字、跨盘恒定”，保留原值即可 |
| R3 | **12-bit 名字哈希的具体哈希函数未解** | 同上（改名/新增才需要） | 桶号公式已 3111/3111 实证；桶表不动即可 |
| R4 | **显示路径待实机**：MIS `BriefingText` vs `BriefingId`、ATR `ActorName` 是否直读、`EN_STRINGS.TXT` 运行时是否读取 | 决定“只翻 LANG 还是必须同步 MIS/ATR/TXT” | 建议 P3 先全量翻 LANG+SFXML+TXT；MIS/ATR 按语义同步准备（成本低） |
| R5 | **烘焙英文贴图/视频文字**（§4.4） | 无法离线确认；若存在则为“非文本表”工作项 | 实机核对后单独列清单；不假装完成 |
| R6 | ~~dlclib 缺 raw-block 规则~~ | **已解决**：核心库已支持该规则；复验 3111/3111 条展开 0 失败 | §3.5 记录原始 107 条误判清单与复验数字 |
| R7 | 本体 `COMMON.PAK` 记录 0（`arrow`）字段序与资料片略有差异 | 只影响“跨盘精确对比”工具 | 不属于构建链；已在 `pak_records.json` 记录 base 侧解析告警 |
| R8 | 中文重压后若**变大**（个别长句/富文本实体码） | 需要搬条目，构建链复杂度上升 | 已给出搬条目字段清单（§8.4）；字库方案 B 已验证该机制 |

---

## 附录 A：64 种扩展名全量统计（自动化输出，便于复查）

来源 `assets/manifests/gr_img_index.json → summary.ext`（n=条数；raw/lzo；stored/real 字节；runs 为该扩展名全部条目的 ASCII 串总数，含二进制噪声；text_bytes 同前）。
注意：`text_bytes` 是**可打印 ASCII 串的总字符数**，对 XML 类资源会把标签/属性值也算进去（如 ATR 的 469,662 B ≫ 其结构化文本 154,906 B），**不等于**玩家可见文本量（后者以 §5.3 为准）。

| ext | n | raw | lzo | stored | real | class | text_bytes |
|---|---|---|---|---|---|---|---|
| ATR | 766 | 766 | 0 | 511,990 | 511,990 | text | 469,662 |
| BMZ | 299 | 1 | 298 | 60,946,710 | 91,813,848 | image | 17,062,135 |
| RSB | 199 | 199 | 0 | 11,183,215 | 11,183,215 | image | 2,261,444 |
| KIT | 191 | 191 | 0 | 76,865 | 76,865 | text | 71,064 |
| POB | 183 | 67 | 116 | 2,073,899 | 4,981,539 | model | 321,302 |
| QOB | 177 | 42 | 135 | 990,552 | 1,871,876 | model | 125,974 |
| SB | 101 | 101 | 0 | 20,367,152 | 20,367,152 | audio | 427,957 |
| SH | 101 | 101 | 0 | 248,744 | 248,744 | audio | 24 |
| QOZ | 101 | 8 | 93 | 248,773 | 489,612 | model | 1,655 |
| SS | 101 | 101 | 0 | 207,257,600 | 207,257,600 | audio | 3,854,431 |
| CHA | 66 | 0 | 66 | 159,765 | 188,760 | model | 14,388 |
| GUN | 66 | 0 | 66 | 69,863 | 178,672 | text | 165,609 |
| XBG | 66 | 66 | 0 | 21,054 | 21,054 | model | 4,253 |
| CHZ | 65 | 0 | 65 | 2,101,320 | 4,037,264 | model | 37,518 |
| POZ | 62 | 3 | 59 | 486,789 | 1,110,348 | model | 14,873 |
| MIS | 45 | 0 | 45 | 670,806 | 2,641,606 | text | 2,507,241 |
| PSS | 42 | 42 | 0 | 580,550,824 | 580,550,824 | video | 20,748,620 |
| PAK | 40 | 40 | 0 | 4,503,824 | 4,503,824 | image | 545,218 |
| DIR | 37 | 29 | 8 | 12,913 | 38,885 | text(dev) | 36,745 |
| ENV | 37 | 36 | 1 | 20,063 | 20,771 | text | 19,292 |
| IDC | 35 | 35 | 0 | 2,312,128 | 2,312,128 | data | 738,323 |
| AOL | 32 | 0 | 32 | 866,536 | 2,038,770 | model | 395,311 |
| MAZ | 32 | 0 | 32 | 16,370,867 | 38,199,120 | model | 1,879,886 |
| MOL | 32 | 0 | 32 | 20,492,041 | 31,221,057 | model | 2,088,904 |
| POL | 32 | 17 | 15 | 17,021 | 35,164 | model | 6,868 |
| SHT | 32 | 0 | 32 | 11,276,431 | 19,193,425 | model | 673,891 |
| TOE | 20 | 1 | 19 | 8,703 | 23,688 | text | 22,044 |
| GTF | 14 | 0 | 14 | 33,310 | 146,957 | text | 146,201 |
| XML | 11 | 4 | 7 | 300,889 | 714,027 | text | 678,904 |
| PRJ | 10 | 10 | 0 | 9,230 | 9,230 | text | 8,514 |
| XBS | 9 | 0 | 9 | 23,961 | 110,123 | text(dev) | 33,973 |
| RES | 8 | 0 | 8 | 513,428 | 2,094,631 | text/binary | 1,002,370 |
| TXT | 8 | 2 | 6 | 16,908 | 42,272 | text(dev) | 28,478 |
| ANM | 7 | 7 | 0 | 5,192 | 5,192 | model | 575 |
| VCL | 7 | 7 | 0 | 2,952 | 2,952 | text | 2,684 |
| ITM | 7 | 6 | 1 | 4,469 | 6,402 | text | 5,898 |
| LNG | 6 | 0 | 6 | 2,495,216 | 2,873,206 | binary | 134,258 |
| CTX | 6 | 0 | 6 | 6,693 | 11,544 | data | 228 |
| GCD | 6 | 6 | 0 | 3,168 | 3,168 | data | 25 |
| WRD | 6 | 6 | 0 | 1,619 | 1,619 | text(dev) | 1,164 |
| WAV | 5 | 0 | 5 | 20,178 | 20,138 | audio | 130 |
| THC | 4 | 4 | 0 | 51,728 | 51,728 | audio | 53 |
| CSF_BIN | 3 | 2 | 1 | 1,893 | 28,593 | save | 6,347 |
| ICO | 3 | 0 | 3 | 126,663 | 286,000 | image | 698 |
| AUD | 3 | 3 | 0 | 1,266 | 1,266 | audio | 340 |
| SCN | 3 | 0 | 3 | 65,149 | 307,408 | model | 26,774 |
| SAV | 2 | 1 | 1 | 13,435 | 117,823 | save | 15,698 |
| CSF | 2 | 2 | 0 | 752 | 752 | text | 680 |
| PSF | 2 | 2 | 0 | 602 | 602 | text | 558 |
| PSF_BIN | 2 | 2 | 0 | 200 | 200 | save | 142 |
| KIL | 2 | 0 | 2 | 2,932 | 40,724 | text | 36,142 |
| TM | 2 | 2 | 0 | 155,136,000 | 155,136,000 | video | 18,031,053 |
| BAT | 2 | 2 | 0 | 725 | 725 | text(dev) | 679 |
| LST | 1 | 0 | 1 | 4,509 | 25,470 | text(dev) | 24,040 |
| KEYS | 1 | 0 | 1 | 1,016 | 4,516 | binary(dev) | 4,230 |
| BUT | 1 | 0 | 1 | 644 | 2,231 | binary(dev) | 2,104 |
| ASS | 1 | 0 | 1 | 646 | 2,231 | binary(dev) | 2,104 |
| RPF | 1 | 0 | 1 | 5,533 | 18,831 | binary | 3,020 |
| CHR | 1 | 0 | 1 | 42,653 | 75,076 | model | 8,168 |
| GRM | 1 | 0 | 1 | 2,077 | 6,108 | binary | 789 |
| MPG | 1 | 0 | 1 | 1,134,207 | 1,568,224 | video | 39,527 |
| CONFIG | 1 | 0 | 1 | 860 | 2,495 | binary(dev) | 2,309 |
| LOG | 1 | 0 | 1 | 12,911 | 148,303 | text(dev) | 145,549 |
| SDF | 1 | 0 | 1 | 7,391 | 24,708 | binary(dev) | 23,708 |

## 附录 B：关键资源索引（GR.IMG#）

| 资源 | # | 说明 |
|---|---|---|
| `ACTION.PAK` | 0 | HUD 图集（15 rec） |
| `COMMON.PAK` | 9 | 字库图集/kit/pda 图集（10 rec，ty=0 原样） |
| `MENU.PAK` | 25 | 菜单图集（12 tex + 5 JPEG） |
| `LOADING.PAK` | 24 | 加载图集（41 rec） |
| `EN_STRINGS.RES` | 576 | LANG（真文本表） |
| `EN_STRINGS.TXT` | 577 | token→英文（武器/物品/Kit 名） |
| `DE/ES/FR/IT_STRINGS.RES` | 574/578/581/584 | 其它语言 LANG（不汉化） |
| `FONT.RES` | 580 | 字库定义（3 face） |
| `IKE.RES` / `NTSC_IKE.RES` | 583 / 586 | 菜单布局 |
| `EN_SPECIAL_FEATURE.XML` | 3101 | SFXML（专家档案；另有 DE/ES/FR/IT 副本） |
| `CAMPAIGN.XML` | 349 | 战役顺序 |
| `BEST_TIMES.XML` | 3097 | 空表 |
| `OPTIONS.XML` | 3108 | 默认设置 |
| `UNLOCKED_HEROES.XML` / `UNLOCKED_MISSIONS.XML` | 3109 / 3110 | 存档解锁状态（#3110 是容器最后一条，独占 64 KiB 尾垫） |

---

*本报告的全部数字均由 `tools/analysis/` 下四个脚本在英文原盘上现场计算；若盘面 sha256 变化，脚本内置断言会失败并提示。*
