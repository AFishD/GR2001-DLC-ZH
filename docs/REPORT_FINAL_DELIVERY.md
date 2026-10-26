# REPORT_FINAL_DELIVERY —— 交付报告

> 项目：PS2《幽灵行动：丛林风暴》(Tom Clancy's Ghost Recon: Jungle Storm, 美版 SLUS-20820) 完全汉化
> 版本：**v1.0 最终版（2026-10-26）**（本报告 A 节之后的正文为早期版本记录，最终交付以 A.0 为准）
> 纪律：一切从**英文原盘**重建；不依赖历史中间产物；大文件/第三方版权内容不入 git。

---

## A. 交付物

### A.1 汉化 ISO（本地生成，不入库）

| 项 | 值 |
|---|---|
| 路径 | work\builds\FINAL\GR_JS_ZH_v1.0_final.iso |
| 尺寸 | 1229266944 B |
| sha256 | 29883b66b8e1d3f2cbedf283deeb956484260b041d918aba3ec37495611b4d24 |
| Game CRC | `E0325951`（原版 `DE1E4DEE`；ELF 打 DBCS 补丁后改变，旧存档/金手指失效，需新开档） |
| 重建 | `python tools\dlc\build.py --stage all --out ... --force`（逐阶段 sha256 自证） |
| 自证 | python tools\dlc\verify.py --stage all → **40/40 断言通过** |

### A.2 代码与资产（入 git）

* 构筑链：`tools/dlc/build.py`（**唯一构筑脚本**：spec/font/text/elf/all/dump-text） + verify/audit/rebuild/inject_text/merge/dlclib 等库
* 字库链：`tools/font/`（fontlib/extract_seed/expand_charset/build_font）
* 分析：`tools/analysis/`（ISO/ELF/资源；dbcs_spec/mipsasm 等）
* 模拟器：`tools/emu/`（run_smoke/wincap/compare_smoke）
* 译文资产：`assets/text/`（原文 source + 8 个翻译批次 + 合并管线）
* 字符集：`assets/charset/`（`charset_compiled_zh16.json` 2300 对偶 + 103 单字节；`charset_expand_dlc.json` 45 字扩充单一真源）
* 文档：`docs/`（BUILD_GUIDE / MOD_GUIDE / PLAN / STATUS / ANALYSIS_ISO / ANALYSIS_ELF / ANALYSIS_ELF_DBCS_PORT / ANALYSIS_FONT / ANALYSIS_TEXT / ANALYSIS_RUNTIME / TRANSLATION_GUIDE / 本报告）
* 参考：`reference/base_zh146/`（本体工程文档与阶段脚本，只读参考）

---

## B. 内容完成度

### B.1 文本（审计 `tools\dlc\audit.py` 实测）

| 资源 | 条目 | 已中文化 | 说明 |
|---|---:|---:|---|
| LANG（GR#576） | 2,971 | **2,494 中文** + 108 纯符号 + 74 空 | 剩余 295 英文均为专名/文件名/军衔缩写（白名单见 B.2） |
| SFXML（GR#3101） | 98 正文 + 174 标题 | **81/81 正文中文**；标题 138 中文 | 21 个英文标题 = 武器型号/专家姓名（规范保留） |
| MIS（45 个） | 玩家可见字段 | **202 中文 / 1 英文**（TAC01 BriefingText 已由 LANG 自动回填） | 日期已本地化为 `2010年3月20日` 格式 |
| ATR（766） | ActorName | 6 个兵种名中文；760 人名保留英文 | 符合规范 |
| EN_STRINGS.TXT（228） | 武器/道具名 | 8 个可译项中文 | 其余为型号保留 |
| GTF/XML/贴图 | — | 经审计无独立显示文本 / 未重绘 | 见残余清单 |

* 译文来源：新译 1,348 + 本体成品 TM 1,877 + 上一版 JS19 兜底 2 + MIS 自动回填/文本匹配 123 + 人工覆盖 ~30；
  合计 3,372/3,372 可译条目全覆盖。
* 缺字：**0**（45 个新字补画进空 PUA 槽；图集槽占用 1,908/2,350，安全余量 253）。

### B.2 剩余英文白名单（有意保留，不视为未完成）

* 人物姓名（制作名单 G062 221 条、任务内人物 Ordonez/Priego/Francisco Lever/Marco Abreu、专家档案姓名等）；
* 文件名（G063/G064/G067：`01.rsb`、`i_main1.wav` 等）；
* 军衔缩写（G066：PVT/PFC/CPL/SGT/… — UI 紧凑，规范保留）；
* 武器/装备型号与公司名（M4/M249/Groza_GL、Soundelux、Red Storm Entertainment Inc. 等）；
* 内部调试串（`mainmenu`、`PING`、`Var Tuning`、`I Link`）。
* XML/JSON 里 `{p}`/`{br}` 等引擎标记不计入文本。

---

## C. 技术自证

1. **identity 重建**：`tools\dlc\rebuild.py --identity` 无改动重建与原盘**逐字节相同**（布局/条目表/SEO 语义全证）。
2. **阶段自证**：font 26/26、text 36/36、elf 28/28、all 38/38 断言（`tools\dlc\verify.py`）。
3. **实机验证（PCSX2 2.8.2，DX12，`work\analysis\emu\`）**：
   * 中文图集 1024×644 PSMT4 + 80 B CLUT 被资料片 loader 正确接受（英文界面逐像素正常，R1 关闭）；
   * DBCS v2 ELF 补丁：启动→FMV→标题→Profiles/名字输入全流程 **0 TLB Miss / 0 异常**（多轮，`emulog_info.errors=[]`）；
   * 全量中文盘：档案页/文件名页/按钮/底部提示**中文正常显示**（134 张 native 截图存档）；
   * **A′ 度量规整后 v5 实测**：标题「档案」ink 高 39.9→**14.8**（≈16px，不裁剪，顶部余量>9px）、按钮 23.0→**13.5**；
     基线残差 +3.1px（中英行盒基线差，可接受）；结论由 font-engineer 与 elf-analyst 独立复测一致。
4. **完整性审计**（`tools\dlc\audit.py`）：见 B.1；缺字 0；CRC 与声明一致。
5. **可复现性**：两次独立运行 `build.py --stage all` 产物 sha256 一致（回退实现与官方 inject 逐字节一致）。
6. **实机深导航（用本机既有记忆卡 Mcd001.ps2 绕过建档案）**：
   * 单人游戏主菜单（单人游戏主菜单 / 训练 战术演习 战役 快速任务 / 学习 返回 接受）；
   * 训练任务列表（训练 1–训练 7、右侧 越野训练 预览、底部滚动说明）；
   * **任务信息/简报屏**（信息 / 训练 1 - 越野训练 / 2008年3月15日 | 13:00 | 晴天 / 任务目标 / 载入中。。。）；
   * **进入任务实机游玩**：中文教学弹窗多行自动折行正常，HUD/3D 正常；
   * 260s 会话（含 gameplay）emulog_info.errors=[]、CRC ED1D6AD4、
erdict.success=true；截图见 work/analysis/emu/final_ingame/ 等。

---

## D. 已知残余（如实记录，不假装完成）

| # | 残余 | 影响 | 后续 |
|---|---|---|---|
| R1 | ~~字体大小/垂直偏移~~ **已修复（A′ + A″，纯数据）**：A′ 把 3 个 face 的 
ld[1] 26/26/42→16；A″ 再把 15 条 style 的 f5/f6 全部归 1.0。原因：ASCII quad 尺寸走 FT 记录（恒 16px），中文 pair quad 高 = fld[1]×f6 ⇒ f6≠1 时中英混排上下偏移/大小不一；统一后 v6 实机截图混排行已对齐（2008年3月15日 | 13:00 | 晴天）。代价=原版字号层级被拉平（标题不再更大） |
| R2 | 贴图内烘焙英文未重绘（菜单框/logo/简报底图等；40 PAK 136 纹理 + 199 RSB 候选） | 部分图片内英文 | 需改图工具链，本轮未做；清单见 `docs/ANALYSIS_ISO.md` |
| R3 | ~~未做完整通关测试~~ **已进任务实机验证**（训练任务：列表→信息屏→载入→游玩，260s 0 TLB/0 异常，中文教学弹窗折行正常）；仍未逐一走完**战役**各任务简报/通关（脚本化菜单导航限制），但 Campaign 与训练走同一 LANG/MIS 渲染路径 | 长时稳定性/个别布局 | 用本机记忆卡继续深测（Mcd001.ps2） |
| R4 | 制作名单/人名按规范保留英文；军衔缩写保留 | 观感 | 可按需再汉化（工作量小） |
| R5 | LZO 重压比原盘编码器弱 ~2%（MIS payload +12.7 KB），由 rebuild 重排吸收 | 无 | 可用更强压缩器优化体积 |
| R6 | `fix_spec.json` 的期望 sha256 与文档身份需在最终验收后固定 | 流程 | 见 BUILD_GUIDE §5 |
| R7 | 上一版 JS19 的中文翻译已还原 2,275 条，仅作 TM 兜底使用（2 条实际采用） | 无 | 保留在 `work/analysis/js19/` 备查 |

---

## E. 关键数字速查

* 原盘：1,229,225,984 B / 600,208 扇区 / SLUS_20820 / 3,111 个资源 / 997 MB GR.IMG 载荷
* 汉化盘：+38,912 B（字库图集 +66,624，文本 -27,712 抵消）
* 图集：1024×644 PSMT4，2,350 槽；已画 1,998 真汉字 + 302 PUA；安全容量 298，剩 253
* FONT.RES：7,466 B（3 face×224 记录 + 522 B 样式尾部）
* ELF：5,319,720 B；25 个 DBCS 调用点 + 1,000 B cave + 2 处字库最近邻过滤 + 5 处行盒锚点；sha256 `04687ed2…`；CRC `D0903834`
* 文本：3,372/3,372 可译条目；LANG 中文 2,494；MIS 202；SFXML 81/81；缺字 0
* 自证：37/37；实机：0 TLB Miss / 0 异常；PCSX2 截图 100+ 张

## C.4 v7 增补：字库最近邻过滤（参考本体汉化 ZH50 过滤集）

**问题**：v6 及以前，中文笔画边缘发虚、部分字周围有 1–2px「漏墨」。根因不是字形数据，而是
**字体纹理仍走双线性采样**：本体汉化工程在 `docs/PATCH_INVENTORY.md §C 纹理过滤 (最近邻) —— ZH50 集`
里记录过同一问题（EN 引擎默认给字库路径 `SetLinearSampling(true)`），修法是 4 处 `li a1,1→0` +
`UIPacket::SetLinearSampling` 状态缓存早退 `beq→nop`。我们的中文图集是 **PSMT4 1-bit**（无原版 62 级 AA），
双线性必然把邻格像素混进来 ⇒ 漏墨/发虚。

**过滤补丁（v7，纯 ELF 2 处）**——按本体口径移植到 DLC `SLUS_208.20`（地址经反汇编定位）：

| VA | 原词 | 新词 | 语义 |
|---|---|---|---|
| `0x219314` | `24050001` | `24050000` | RSFontMgr 字库绘制路径（函数 `0x2192D0` 内）`jal SetLinearSampling` 延迟槽 `li a1,1→0` |
| `0x4FD5CC` | `10830038` | `00000000` | `UIPacket::SetLinearSampling`（`0x4FD5B0`）状态缓存早退 `beq a0,v1→nop`（否则 false 被缓存吞掉） |

* 补丁表：`tools/dlc/elf_patches.json`（28 段 = DBCS 26 + 过滤 2），由 `build.py --stage spec` 的
  `EXTRA_PATCHES` 生成并可复现；新身份 ELF sha256 `7f3970798c537442…d0dfcef`，Game CRC **`ED1D6AD4`**，
  v7 ISO sha256 `ed54ee7794e94fce…`。
* 实机对照（PCSX2 2.8.2，同屏 `文件名：`）：v6 软边/漏墨 → v7 **硬边像素级清晰**；
  证据图 `work/analysis/emu/_nearest_fix_compare.png`；主菜单/任务信息屏/游戏内教学弹窗同测。
* 回归：`verify.py` E1/E2/E3（ELF sha、CRC、28 处补丁在盘）38/38 通过。

## C.5 v9 增补：A‴ 行盒锚点（UI 垂直对齐定版）

**问题**：v7/v8 的字形虽已是 16px，但 `CharHeight` 同时是「字形 quad 高」和「19 个 UI 布局调用者
的行盒高」。A′/A″ 把 `fld[1]` 归 16 后，布局行盒与 EN 原盘（26/26/42）不一致 ⇒ 标题偏上、
按钮族/帮助条 ±3~8px 错位。

**A‴（v9）**：数据侧 12 B —— `fontlib.restore_face_metrics()` 把三个 face 的 `fld[1]` 恢复 EN
（26/26/42），style f5/f6 保持 1.0（横向口径不变）；ELF 侧 4 处补丁 ——
`0x219894 j 0x575D04`、`0x219898 nop` + 两段零填充区 cave：
* `y1 = y + (CharHeight−16)/2`、`y2 = y1+16`（16px 字形在 EN 行盒内垂直居中）；
* 标题带 `y<40` 再 +7px（本体 ZH61 子界面标题 +7 口径）；
* 底栏 `y≥400 且 x<400`（滚动帮助条）再 −3px，右侧按键提示不动。

**实测**（EN / v7 / v9，640×480）：主菜单大标题 ink 中心 EN 38.6 → v7 26.3 → **v9 38.0**；
主菜单列表项/任务信息/教学弹窗保持 ±1.3px；帮助条从「被裁/缺失」变为 **中心 429.3（EN 430.6）**。
证据：`work/analysis/emu/v9d`、`docs/ANALYSIS_FONT.md §14`、`docs/ANALYSIS_ELF.md §13`、
`work/analysis/elf/align_plan.md`、`work/analysis/emu/align_measure.md`。

## C.6 v10 增补：A‴ 中段 −4px（列表项/正文基线对齐）

v9 的 A‴ 只处理了标题带与底栏；用户实机再报「主菜单/玩家模式各列表项仍过低」。逐屏与 EN 原版
逐像素比对后确认：列表项、任务信息正文等**中段文本**的 ink 底边比 EN 基线低 3~5px（EN 字形 26px
贴底、我们的 16px 字形居中）。追加 cave C（VA 0x182F84，15 词）：

* 中段正文 **40 ≤ y < 400 → 再上移 4px**（不区分左右，列表项与信息正文一并修正）；
* 与 A 段（标题 y<40 +7、底栏 y≥400 且 x<400 −3）互斥，顺序 A → C → B。

**实测（Player Mode 列表，EN/v9/v10，单位游戏像素）**：

| 行 | EN ink 底 | v9 | **v10** |
|---|---|---|---|
| Split Screen/分屏 | 160.73 | 165.06（+4.3） | **160.73** ✓ |
| Online/在线 | 193.70 | 192.83 | 188.49 |
| Options/选项 | 220.60 | 224.94（+4.3） | **220.60** ✓ |
| Movies/影片 | 250.54 | 254.88（+4.3） | **250.54** ✓ |
| 主菜单 4 项 | 150.35 | 154.26 | **149.92** ✓ |
| 任务信息正文 | 127.34 | 132.54（+5.2） | **128.20** ✓ |

* 回归：`verify.py --stage all` **38/38**；33 段 ELF 补丁（DBCS 26 + 最近邻 2 + 行盒锚点 5）。
* 身份：ELF sha256 `04687ed252e96bb0…`、Game CRC **`D0903834`**、v10 ISO sha256 `8eb0604d…`。
* 证据：`work/analysis/emu/{v9d,v10c}`、`work/analysis/emu/_v10_list_cmp.png`。

## C.7 v11：中段上移量取中值 −2px（用户实机判定）

用户反馈 v10 的「中段 −4px」过头（列表项反而略高），要求**取 v9(0) 与 v10(−4) 的中间值**。
cave C 的常量 `4.0f → 2.0f`（仅 1 个 cave 词），其余锚点不变。

**实测（Player Mode 列表，ink 底边，游戏像素）**：

| 行 | EN | v9(0) | v10(−4) | **v11(−2)** |
|---|---|---|---|---|
| 分屏 | 160.73 | 165.06（+4.3） | 160.73（0） | **162.89（+2.2）** |
| 在线 | 193.70 | 192.83 | 188.49（−5.2） | **190.66（−3.0）** |
| 选项 | 220.60 | 224.94（+4.3） | 220.60（0） | **222.77（+2.2）** |
| 影片 | 250.54 | 254.88（+4.3） | 250.54（0） | **252.71（+2.2）** |

* 身份：ELF sha256 `4c47d284ebb8bd87…`、Game CRC **`D0903834`**、v11 ISO sha256 `cbb4f9c8…`；
  `verify.py --stage all` **38/38**（33 段 ELF 补丁）。
* 证据：`work/analysis/emu/v11`、`work/analysis/emu/_v11_list_cmp.png`。
* 如仍偏上/偏下，cave C 常量可在 1.0~3.0 之间微调（一处 4 字节词）。

## C.8 v14：战役卡死修复（RSString 子串越界/NULL 守卫）

**症状**：战役 → 选择战役 → 片头结束/跳过后卡死（TLB Miss pc=0x401F98 / 0x401704，addr=0x0）。

**根因（实测，见 `docs/CRASH_CAMPAIGN_ANALYSIS.md` §11）**：引擎子串构造函数 `0x401F20`
收到 `start=275 > end=274`（源串长度 274）→ 容量 `end-start+1 = 0` → `0x401490` 分配 0 字节
返回 **NULL** → 结尾 `sb zero,(v0)` 写 0 地址。引擎对 `start<=end` 与分配失败都没有判断。

**修复**（内置于 `tools/dlc/build.py --stage spec` 的串守卫；`GRJS_NO_STRING_GUARD=1` 可关）：

| 守卫 | 站点 | 做法 |
|---|---|---|
| A | `0x4015F0` 串构造入口 | 容量 `a1 <= 0` 时钳到 1 |
| C | `0x401F98` 子串结尾取 data | shared/data 任一为 NULL → 直接跳函数尾声 `0x401FC0` |

**验证**（`tools/emu/nav_post.py`：PostMessage 定向发键 + PrintWindow 抓帧，不干扰模拟器外程序；
片头连点 Start 跳过）：v11 在进入战役 `49.5s` 崩溃；v14 进入 `C01 - 警惕的农夫`，
稳定运行 460s（含约 300s 游戏内），**TLB Miss = 0**。界面/文本/字体与 v11 完全一致。

**身份**：ELF sha256 `5d28fc71…`；Game CRC `E0C456E2`；38/38 断言通过。

## C.9 v15：换行边界修复（DBCS 折行）

**症状**：换行处字符错乱、行尾出现手柄按键图标（「对下面的靶子练习一下射击」→「对下面的靶子△现一下射击」）。

**根因**：UI 折行循环 `0x21B778..0x21B7C4` 按**字节**取字符、索引 +1；中文对偶码被拆开，
行尾只有 lead 字节时若为 0xB1/0xB5 就被 `DrawString` 当图标码画 △，下一行从 trail 字节起解码错位。

**修复**：3 站点 + 3 段 cave（`0x21B778 / 0x21B7B4 / 0x21B7A0` → cave `0x5BFE0C`）：
按 DBCS 规则组 16 位码、索引按步长 1/2 推进，并补偿原宽度模型里每字节一次的 `font[0x18]`。

**验证**：训练任务长文本弹窗换行全部落在完整字符边界，无图标/错字（`docs/img/wrap_after_v16.png`），
训练任务运行 220s 无 TLB Miss。

**身份**：42 段补丁，ELF sha256 `d90d2fe6…`，Game CRC `6C4AF325`，FINAL sha256 `7cad4628…`，verify 40/40。

## C.10 v16：换行边界根治（行首 +1 修正）

v15 修好「行尾半边字/△」后，暴露第二处：折行函数尾把下一行行首算成 `行首+行长+1`（假定断点是空格、
跳过 1 字节）。中文对偶码被跳过 lead、从 trail 解码：「摇」(A1D9) 行首显示成「是」(D9)。

**修法**：站点 `0x21B8C4` → cave `0x57B78C`（52 B）：断点字节 == 0x20 才保留 +1，否则去掉。
**验证**：训练弹窗第 2 行「摇杆转身」正确；探针盘「摇×40」行首全部正确；训练任务 220s 无 TLB；
verify 40/40。**身份**：44 段补丁，ELF `8e742b36…`，CRC `755C961C`，FINAL sha256 `e2507948…`。

---

## Z. 最终版（v1.0，2026-10-26）

- 最终成品：`work/builds/FINAL/GR_JS_ZH_v1.0_final.iso`
  - sha256 `29883b66b8e1d3f2cbedf283deeb956484260b041d918aba3ec37495611b4d24`，Game CRC `E0325951`，verify **40/40**；
- 自此版本起包含的增量修复（v21→v81 汇总）：
  1) 队员设置：A/B 组姓名行居中、B 组三人名 +5px、开始按钮居中；
  2) 难度选择：三行与中央滚动栏对齐；
  3) 训练/战术/快速任务列表：统一基线，消除部分居中/部分靠上；
  4) 武器属性简介：清除字面 CRLF 空行，14 全宽字重折；
  5) 简报「任务目标」行：cave G（y≥265、数字/X 开头）−3px 与分栏线对齐；
  6) 训练/任务提示：严格 29 汉字/行（行尾半角空格顶宽，引擎在空格处断行），英文单词不拆；
  7) 启动加载画面：Loading... →「载入中...」，Please wait →「请等待...」（ELF 5 语言槽表）；
- 已知范围外：PS2 BIOS 的「Reading disc / Accessing memory card」为固件画面，不在游戏盘内（§46）。
