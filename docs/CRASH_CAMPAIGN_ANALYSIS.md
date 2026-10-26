# CRASH_CAMPAIGN_ANALYSIS —— 战役片头结束后卡死：复现、二分与下一步

> 状态：**已稳定复现；已排除汉化 ELF / 文本内容 / 字库图集 / 度量 / BIOS 差异**。
> 结论方向：引擎内**越界访问未做边界判断**（与本体汉化项目记录的崩溃根因同族），
> 下一步=按 DLC 实际指令移植分配器/解压器守卫（F4/F7/F7b/OOMFIX 等价物）。

## 1. 症状

用户实机：主菜单 → 战役 → 选择战役 → 播完/跳过战役片头动画 → **卡死（黑屏，EE 跑飞）**。
PCSX2 emulog 关键行：

```
[   83.6818] FMV started
[   85.0443] FMV ended
[   86.6134] TLB Miss, pc=0x401f98 addr=0x0 [store]
[   86.6147] TLB Miss, pc=0x4016ec addr=0x1cb696f8 [store]
...
[   86.6168] cpuTlbMiss pc:4016ec ... ; pc:80000000 ...
```

崩溃点 `0x401704` / `0x401f98` 均在 **EE 侧字符串/引用计数库**（RSString 族）：

* `0x4016F4  lui v0,0x5B ; addiu v0,0x7798 ; sw v0,(s0)` —— 恢复 vtable
* `0x401704  lbu v0,2(v1)`（v1 = `[s0+4]` 共享块指针）—— **共享块指针是垃圾值**
* `0x401F98  lw v0,(a0) ; lw v0,4(v0)` —— 虚表指针被垃圾覆盖

⇒ 不是"画错了"，是**堆里的字符串对象被写坏**（与本体项目 `REPORT_DISASM_ROOTCAUSE` /
`REPORT_COMBFIX` 的"桶链被毒化"同型）。

## 2. 稳定复现（可重复）

用户 `%LOCALAPPDATA%\PCSX2\sstates\SLUS-20820 (D0903834).01.p2s` = 战役选择界面即时存档。

```powershell
python tools\emu\run_smoke.py --iso work\builds\JS_ZH_v11.iso --memcard Mcd001.ps2 `
  --statefile work\analysis\emu\user_crash_state.p2s --seconds 120 `
  --out work\analysis\emu\crashrepro2 --capture-at 6,12,20,40,60,75,90 `
  --keys "15:space" --key-hold 200 --key-gap 400
```

结果（复现 3 次一致）：`FMV 17.5s→64.0s`（战役片头 46.5s），结束后 **3.6s** 出现同一串
TLB Miss（pc=0x401704，垃圾地址 0x7f7f8082/0xf3f37375/…）→ 卡死。

**注意**：savestate 只在**同一张盘布局**下有效（存档里含 boot 期解析的 GR.IMG 目录表/LBA）。
因此"换数据版本"的 A/B 必须用**原地替换**（保持每个条目 stored/real 与整体布局不变），见 §3。

## 3. 二分矩阵（全部 ✓=已排除）

| # | 变量 | 做法 | 结果 |
|---|---|---|---|
| 1 | 汉化 ELF 补丁（DBCS/字库过滤/行盒锚点） | `ELV_orig.iso` = 同一份 v11 数据 + **完全未改的 EN ELF**（CRC DE1E4DEE） | **仍崩**（同点同签名）⇒ ELF 补丁无罪 |
| 2 | 行盒锚点 A‴ | `ELV_skip_align.iso` = 仅撤锚点 5 段 | **仍崩** |
| 3 | 全部文本内容 | `INPL_blank_all.iso` = 58 个文本资源里所有 ≥0x80 字节原地改成 0x20（结构/长度不变，等于"全英文空格"） | **仍崩**（3.6s 同点）⇒ 文本内容无罪 |
| 4 | 字库图集 COMMON.PAK | `FINPL_pak_en.iso` = 原版 EN 图集（763,676 B）补零到 v11 槽（830,300 B） | **仍崩** |
| 5 | FONT.RES 度量 fld | `FTV_en_metrics.iso` = 三个 face 的 fld 全部换 EN 值（长度/位置不变，重压恰好 1528 B 入槽） | **仍崩** |
| 6 | BIOS 差异（savestate 与运行 BIOS 不同） | 换用用户同款 `SCPH-90006_BIOS_VX_HK_2.20.bin` | **仍崩** ⇒ 不是 BIOS/savestate 伪影 |

仍**未能**原地替换验证的剩余数据差异：
* FONT.RES **记录区**（3 face × 224 条 × 12B；EN 记录压缩后 4460 B > 槽 1528 B，放不下）；
* FONT.RES **尾部样式表**（522 B，45 条；换 EN 后重压 1572 B > 槽 1528 B）；
* 各文本/字库资源的 **LZO 重压形态**（我们自写 packer 与原盘子流形态不同）；
* GR.IMG 整体重排（条目 off 全部按新尺寸重算，布局与 EN 不同）。

## 4. 参考本体汉化项目（`Ghost_Recon_2001_Locolization`）的同类记录

本体的崩溃根因（多轮记录，最终定案）：

1. `docs/REPORT_DISASM_ROOTCAUSE.md` §1、§3：**中文文本 + 原版 ELF 也会崩** ⇒ 触发物与汉化
   cave 无关，是文本数据规模/内容配合引擎**硬编码容量**；静态站点唯一"写入下标无上界"=
   **字体管理器顶点包**：容量哨兵在**写入之后**才检查、复位又以 `fontmgr+0x48` 为条件
   ⇒ count 越界后每次调用都**越界写** ⇒ 相邻 dlmalloc 堆块头被改坏。
2. `docs/RETROSPECT.md` §4：**实际根因 = 分配器桶链被写坏后拿坏指针在 RAM 内外读写**
   ⇒ 无限自旋/野读写；四件套把"链头非法"从自旋改成走既有出口：
   * F4 `0x00102588`（大块桶扫描：链头不在 RAM 就 bail）
   * F7 `0x001021D4`（own-bin 回边：链头非法就 bail）
   * F7b `0x00102208`（unsorted 快路径：链头越界就 bail）
   * OOMFIX `0x00539174`（解压器 malloc 返回 NULL 不再写 NULL+4）
   合计 239 B / 70 段。
3. `docs/CORRECTIONS.md` §3：中文总字节只有英文 48.6% ⇒ **不是"更长"，是"越界访问没有判断"**。

**这就是用户说的"先前原版有类似的 BUG，原因是内存越界没有进行判断"** ——
修复方式 = 在引擎的越界读/写点加**边界判断**（bail 到既有出口）。

## 5. DLC 侧的对应落点（已定位，待施工）

DLC ELF（SLUS_208.20）的 dlmalloc 与本体同族但地址/编译不同，已用双字签名定位：

| 语义 | DLC VA | 依据 |
|---|---|---|
| unsorted 桶循环（读 `ld v1,8(v0)`） | `0x101F6C`，回边 `0x101FC8 bne v0,t2,0x101F6C` | 与本体 F7b 同构 |
| own-bin 路径（`lw v0,0x14(v0)` 链） | `0x101FC4` / `0x101FD0` 起 | |
| 大块桶扫描 / 切分 | `0x102210`、`0x102490` 附近 | 与本体 F4 同构 |
| 尺寸掩码 | `lui 0x1FFF ; ori 0xFFFE` → `0x1FFFFFFE`（`0x101F4C-0x101F54`） | 与本体完全相同 |
| 解压器（OOMFIX 等价点） | `0x539000` 附近（ANALYSIS_ELF §C 已登记） | 待逐指令核对 |

施工方式（沿用本体口径，脚本 `cave_verify` 七条检查）：
1. 每个越界读前用 `sltu` 判断指针是否落在 EE RAM 范围内（`0x00100000..0x02000000`）；
2. 非法 → `j` 到该路径**既有**出口（如 unsorted 空桶出口），不发明新语义；
3. cave 放死区（40 B 级），逐条反汇编自检 + `verify.py` 加盘断言。

## 6. 复现/实验脚本（本轮新增，均可重跑）

| 脚本 | 作用 |
|---|---|
| `work/build_patch_inplace.py <blank_all|blank_mis|blank_lang|blank_atr|blank_other>` | 原地抹除文本内容（布局不变，savestate 可用） |
| `work/build_font_inplace.py <pak_en|pak_zero>` | 原地换/清 COMMON.PAK（同尺寸） |
| `work/build_font_variant.py <en_metrics|en_tail|en_both>` | 原地换 FONT.RES 的 fld/尾部样式（同长度/重压入槽） |
| `work/build_elfvariant.py <skip_align|orig|dbcs_only|filter_only|align_only>` | 同数据换 ELF 补丁子集 |
| `work/dump_cdvd.py <dump>` | 解析 PCSX2 BDV2 CDVD dump（LBA 序列/文件归属） |
| `work/detect_menu.py <png>` | 主菜单选中项检测（自动导航用） |

证据目录：`work/analysis/emu/{crashrepro2,v11_press15,inpl_blank,inpl_paken,ftv_metrics,elv_orig,elv_noalign,crash_bios22}`。

## 7. 下一步（按优先级）

1. **移植分配器守卫**（F4/F7/F7b 等价）：在 §5 站点加 `sltu` 边界判断 + cave bail；
   每加一处用同一 savestate 复跑验证是否退出 TLB 循环。
2. **OOMFIX 等价点**（解压器 malloc NULL 检查）：等级资源加载正是解压器高频路径，与"片头后
   载入关卡"时序吻合。
3. 若守卫后仍崩：用 gsrunner（本体同款仪器）挂 `-grreglog/-grmemwatch` 在 `0x401704` 前
   记录持有坏指针的对象来源，定位**写入者**（本体当年未定位、只做了防御）。
4. 备选：把 FONT.RES 记录区/尾部样式表做成"可在同槽位内表达的等价内容"完成剩余数据二分
   （需要重排压缩形态，工作量约 1 轮）。

## 8. 分配器守卫移植（本轮施工）与结果

按「整套补丁完整移植」指示，已把本体四件套的**等价守卫**写进 DLC ELF：

* 当时新增 `alloc_guards.py` 生成器并接入补丁表（**该实验已移出正式构筑链**；
  `GRJS_ALLOC_GUARDS=1` 时叠加）。共 **25 段 / 8 个守卫 + 1 个共享 bail**：
  * M1-M4（malloc 侧，站点 `0x101E7C` / `0x101F6C` / `0x101FE8` / `0x1022B4`）：
    从桶链/树取出的 chunk 指针必须落在 EE RAM；非法 ⇒ 恢复 s0 后跳 malloc 既有尾声
    `0x102494`（**返回 NULL**，等价 OOM 路径）。
  * F1-F4b（free 侧，站点 `0x1024D0` / `0x1024F8` / `0x102510` / `0x102568`）：
    入口/前后邻块指针要 16B 对齐且在 EE RAM 内；非法 ⇒ 本次 free 变 no-op（`jr ra`）。
  * 站点统一 2 词（`j cave` + `nop`），原两条指令挪进 cave；合法执行后跳 site+8。
* cave 选址采用**四重校验**：ISO 全零 + 无 j/jal 目标 + 无字面量/lui+addiu 构造 +
  **两份运行期 EE RAM 快照全零**。据此排除 `0x575348`（该区运行期会被写，正是早期
  cave C 崩在 `0x575384` 的真因），选到 `0x57D280`(240B) / `0x5BFE0C`(176B) / `0x59FFC4`(68B)。
* 实验盘：`work/builds/JS_ZH_v12guard.iso`（ELF sha `ce6ce7b7…`、CRC `87A5AE45`）。
* **结果：同一 savestate 复跑，卡死签名完全不变**（FMV 62.9s 结束后 3.6s，`pc=0x401704`
  读垃圾指针）⇒ 分配器**读侧**守卫无法阻止这次崩塌：坏指针是在**写入侧**就已经写进
  字符串对象/堆块了。本体当年修的是「分配器自旋」，我们这次是「对象字段被改写后的析构崩溃」，
  所以下一步必须找**写入者**（本体根因文档的候选同样是"顶点缓冲越界写"这类写侧缺陷）。

## 9. 新工具：运行期 RAM 取证（本轮打通）

`.p2s` 是 **ZIP**（内层 zstd，method 93），7-Zip 可直接解出 32 MB `eeMemory.bin`：

```powershell
& "C:\Program Files\7-Zip\7z.exe" e <state>.p2s -o<dir> eeMemory.bin -y
```

* `work/find_cave_pads.py`：ISO 零区 × 运行期 RAM 快照 → 可信 cave 池（见 §8）；
* `work/analysis/emu/crash_state_ram/`：崩溃瞬间 EE RAM（run_smoke 在 67s 发 F1 存档后解出），
  可直接扫描对象/堆；
* 崩溃 TLB 地址字节模式 `82 80 7f 7f`（即 `0x7f7f8082`）出现在崩溃瞬间 RAM 的
  `0x190D37B / 0x1942308 / …`（高段流式/纹理缓冲）——可作追"写入者"的锚点。

## 10. 下一批守卫（写侧，待施工）

1. **memcpy/memset 目标守卫**：DLC 拷贝循环在 `0x16A380..0x16A3F4`（32B/16B/8B/1B 分级），
   对应本体 F8 思路——目标指针落 0 页/越界时中止，避免野写。
2. **字体管理器顶点缓冲容量守卫**：本体 `REPORT_DISASM_ROOTCAUSE` §3 的 ★★★ 站点
   （容量哨兵在写入之后才检查、复位以 flag 为条件 ⇒ count 越界后持续越界写）；
   DLC 的 `RSFontMgr::AddOneWord` 一带需同样补"写入前 count 上限判断"。
3. **RAM 差分**：用户 pre-crash state 与崩溃瞬间 state 的 EE RAM 求差，定位被改写的
   字符串对象及其邻居，反推写入者（缓冲区/结构体归属）。

## 11. 根因定案与 v14 修复（2026-10-22 夜）

### 11.1 决定性证据：崩溃点的现场寄存器

用「ELF 内嵌诊断 cave」把崩溃前最后一次调用的寄存器落盘（`work/legacy_tools/crash_log_patch.py`（诊断脚本，已移出正式链），
cave 放 0x57D280 / 0x59EF20，日志区 0x59FFC4 / 0x5BFDD4），再用**状态机导航**
（`tools/emu/nav_post.py`：PostMessage 发键 + PrintWindow 抓帧，全程不碰模拟器外程序）
到达崩溃点后 F1 存档，从 `.p2s`（ZIP，内层 zstd，7-Zip 可解）取 `eeMemory.bin` 读日志：

```
site2 log @0x5BFDD4:
  a0=01FFE35C sp=01FFE300 ra=00401F58 s2=01FFE3F8 s0=274 s1=275
  src_shared=010B1500 src_data=010B1520  (源串 274 字节)
```

即：`0x401F20(dst, src, start=275, end=274)` —— **start > end**，源串长度恰为 274。
该函数用 `end-start+1 = 0` 去构造临时串：`0x4015F0` 里 `0x103470(8)` 拿 shared 块、
`0x401490(shared, 0)` 分配 0 字节正文 → **返回 NULL**；随后：
`lw v0,(a0)`（shared）→ `lw v0,4(v0)`（data=NULL）→ `addu v0,v0,a2` → `sb zero,(v0)` =
**写 0 地址** ⇒ 与 emulog 的 `TLB Miss pc=0x401F98/0x401FA0 addr=0x0 [store]` 完全对应。

### 11.2 为什么英文原版不崩

原版文本长度/分段让 start/end 始终合法，容量 ≥1，分配不会返回 NULL。
汉化后该路径的字符串长度为 274 字节、且分段索引越界 1 —— 引擎**对 start<=end 与分配结果
都没有判断**（正是「内存越界没有进行判断」）。

### 11.3 修复（两个最小守卫，内置于 `tools/dlc/build.py --stage spec`）

| 守卫 | 站点 | 做法 |
|---|---|---|
| A | `0x4015F0` 串构造入口 | 容量 `a1 <= 0` 时钳到 1（cave @0x5841C4） |
| C | `0x401F98` 子串结尾取 data | shared/data 任一为 NULL → 直接跳函数尾声 `0x401FC0`（cave @0x59EF20） |

两条都只是「加判断」，不改任何正常路径语义；cave 均放在四重校验（ISO 全零 + 无跳转目标 +
无字面量 + 两份运行期 EE RAM 快照全零）通过的零填充区。

### 11.4 验证

同一 `nav_post.py` 导航脚本、同一 ISO 数据、同一内存卡：

| 版本 | 结果 |
|---|---|
| v11（FINAL 基线） | `49.5s` 首次 TLB Miss（pc=0x401F98，addr=0x0）→ 卡死 |
| **v14（含串守卫）** | 进入 `C01 - 警惕的农夫` 任务（任务信息/载入/游戏内均正常），**稳定运行 460s（含约 300s 游戏内），TLB Miss = 0** |

界面/文本/字体与前版完全一致（守卫只加在错误处理路径上）；构建 38/38 断言通过。

### 11.5 新增工具（本轮留存）

| 工具 | 作用 |
|---|---|
| `tools/emu/nav_post.py` | **不干扰外部程序**的导航：PostMessage 定向发键 + PrintWindow 抓渲染子窗口；片头连点 Start 跳过；画面状态机（标题/存档/主菜单/单人子菜单/高亮行检测） |
| `tools/emu/nav_state.py` | 早期版本（SendInput + F8），保留作对照 |
| `tools/dlc/build.py --stage spec` | 串守卫已内置（默认叠加；`GRJS_NO_STRING_GUARD=1` 可关） |
| `tools/dlc/build.py --stage dump-text` | 文本表格导出（原文/译文对照 CSV） |
| `work/legacy_tools/crash_log_patch.py` | 崩溃现场寄存器落盘（诊断用，已从正式构筑链移出） |
| `work/legacy_tools/alloc_guards.py` | 分配器越界守卫实验（未纳入正式线） |
| `work/find_cave_pads.py` | cave 四重校验选池 |
| `work/crash_diff.py` | 崩溃前/后 EE RAM 差分找被写坏对象 |

## 12. 换行边界修复（v15）

用户实机截图：「对下面的靶子**练习**一下射击」显示为「对下面的靶子**△**现一下射击」，
且换行处前后字符与原文出入很大。定位结论：**UI 折行循环按字节推进**，把中文对偶码拆开：

* 行尾只剩 lead 字节时，`DrawString` 若遇到 **0xB1/0xB5**（引擎图标码）就画手柄按键图标 ⇒ △；
* 下一行从 trail 字节起解码 ⇒ 换行处字符错乱。

与 §11 的串守卫无关（那是崩溃），这是纯排版缺陷，但同样源于「DBCS 化只改了核心路径、
UI 布局路径仍按单字节假设」——本体（JS19）当年也踩过，wrap cave 即其修法。

**修复**：站点 `0x21B778 / 0x21B7B4 / 0x21B7A0` + cave `@0x5BFE0C`（详见 `ANALYSIS_ELF.md` §15）。
**验证**：训练任务弹窗换行全部落在整字边界（`docs/img/wrap_after_v16.png`），运行 220s 无异常。
**身份**：42 段补丁，ELF `d90d2fe6…`，CRC `6C4AF325`，FINAL sha256 `7cad4628…`，verify 40/40。

### 12.1 进展与现状（2026-10-23 晚）

* 已完成：折行循环 DBCS 化（站点 `0x21B778/0x21B7B4/0x21B7A0` + cave `0x5BFE0C`）——
  行尾不再出现 △ 图标，换行落在整字边界；训练任务运行 220s 无异常。
* **已完成（v16 根治）**：定位到折行函数尾 `0x21B8C4` 把「下一行行首」算成 `行首+行长+1`
  （原设计假定断点是空格、跳过 1 字节）。中文对偶码因此被跳过 lead、从 trail 解码
  （「摇」A1D9 → 「是」D9）。修法：站点 `0x21B8C4` → cave `0x57B78C`，仅当断点字节 == 0x20
  时才 +1。验证：训练弹窗第 2 行「摇杆转身」正确、探针盘「摇×40」行首全部正确、220s 无 TLB。
* 阻塞已解除：FINAL 已更新为 v16（ELF `8e742b36…`，CRC `755C961C`，sha256 `e2507948…`）。
* 剩余小问题：ASCII 单词可能被折行拆开（START → STA/RT），后续可做词边界回退。
