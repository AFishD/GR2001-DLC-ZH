# 运行时冒烟测试（PCSX2）可行性报告

> 项目：《幽灵行动：丛林风暴》PS2 美版（SLUS-20820）完全汉化工程
> 任务：task-5（P1-E 运行时验证）· 作者：emu-analyst
> 结论日期：2026-10-21

---

## 0. 结论 TL;DR

**可用 ✅**。本机可以用 PCSX2 对汉化/原型 ISO 做「冷启动 → 等 N 秒 → 脚本按键导航 → 截图 → 关闭」的运行时冒烟测试；
截图走 **PCSX2 自带 F8 原生截图**，是模拟器帧缓冲（1475×1106），不含窗口 UI / OSD / RTSS，可直接做 A/B。

| 项 | 结论 |
|---|---|
| PCSX2 | 本机便携版 **v2.8.2**（`C:\Users\84363\AppData\Local\PCSX2\pcsx2-qt.exe`，15,257,088 B，sha256 head `a3e85ae9aa0e1451`） |
| 渲染后端 | D3D12 可用；`-renderer sw`（软件 GS）+ D3D12 呈现也可用 |
| BIOS | 有（`third_party\emu\run\bios`，本报告统一用 **SCPH-70012_BIOS_V12_USA_200.bin**） |
| 无头能力 | **半无头**：PCSX2 需要交互式桌面会话与一个可激活的窗口；不依赖"窗口在最前"（PrintWindow），但 **F8 原生截图需要窗口短暂激活（会抢占前台焦点 ~0.5–1.5 s/次）** |
| 稳定性 | 2026-10-21 当天连续成功 6 次 205 s 级运行（英文原盘 ×1、planB 字库原型 ×2、生产字库盘 ×1、DBCS ELF 盘 ×1；另 1 次偶发窗口异常已重跑通过），收尾 kill 正常、无残留进程 |
| 帧级确定性 | ❌ wall-clock 口径（±数秒），不是帧级；真正帧级 A/B 需要修复 `pcsx2-gsrunner`（见 §6） |
| **实测解锁的两把钥匙** | ✅ 英文原盘能跑到标题/Profiles/名字输入；✅ `JS_ZH_font.iso` 与 `JS_ZH_elf.iso` 都能正常启动并正确渲染英文界面文本，**PCSX2 日志 0 TLB Miss / 0 Trap**（详见 §4.3） |

**最小可用命令**（在工程根目录）：

```powershell
$env:PYTHONIOENCODING="utf-8"
python tools\emu\run_smoke.py `
  --iso "work\builds\JS_ZH_elf.iso" `
  --seconds 205 --out work\analysis\emu\elf `
  --keys "15:space,102:space,118:return,133:space,148:return"
```

已成功的基线证据：`work\analysis\emu\baseline\`（标题 / Profiles / 名字输入键盘屏、native + window 截图、summary.json、emulog）。

**当前限制（一句话）**：能亲眼看到并截到「启动→标题→菜单→名字输入」全流程画面和英文/中文字形渲染，但它是 wall-clock 冒烟，
不是帧级确定性回放；截图瞬间会把 PCSX2 窗口切到前台（可在 `--no-native` 关闭）。

---

## 1. 本机环境

| 项 | 值 |
|---|---|
| 模拟器 | 便携版 PCSX2 **2.8.2**（`pcsx2-qt.exe`，ProductVersion 2.8.2.0）；`portable.txt` + `portable.ini` 已存在 ⇒ 数据根 = 安装目录 |
| 安装位置 | `C:\Users\84363\AppData\Local\PCSX2`（用户自备，**只读使用**） |
| 干净运行副本 | `work\analysis\emu\runtime\pcsx2-qt`（≈175 MB，gitignored，本工具自动生成） |
| BIOS | `SCPH-70012_BIOS_V12_USA_200.bin`（4 MB，来自本体工程 `third_party\emu\run\bios`，只读复制） |
| CPU / GPU | Ryzen 5 7600X（6C/12T，AVX2/AVX512）/ NVIDIA RTX 4070 Ti SUPER（D3D12） |
| 显示 | 3840×2160 @200%（本工具的 Win32 调用全部做了 per-monitor DPI-aware 处理） |
| 干扰项 | 本机常驻 **RTSS + MSI Afterburner**（OSD 只污染窗口截图，不影响 F8 原生截图） |
| 其它 | 交互式桌面为活动桌面（可 EnumWindows / SetForegroundWindow） |

PCSX2 版本证据（`emulog.txt` 首行、`summary.json`、`emulog_info.version`）：

```
PCSX2 v2.8.2
Savestate version: 0x9a590000
```

---

## 2. 方案：为什么复制一份「干净便携 runtime」

用户安装的 PCSX2 是 **便携模式**（目录内有 `portable.txt`），此时 `-datapath` / `-portable` 都被便携模式锁定，
直接运行会读写用户自己的 `inis/PCSX2.ini`、`memcards`、`sstates`、`logs`。因此 `run_smoke.py` 的策略是：

1. **首次运行**：把安装目录的 exe / DLL / `resources` / `QtPlugins` / `D3D12` 复制到
   `work\analysis\emu\runtime\pcsx2-qt\`（≈175 MB，在 `work/` 下、gitignored，不碰用户配置）；
   从本体工程复制一个 USA v12 BIOS；创建空数据目录；写 `portable.txt`/`portable.ini`。
2. **每次运行**：重写一份**固定的干净 `inis\PCSX2.ini`**（见 §2.1），保证 PCSX2 设置不漂移。
3. **收尾**：`taskkill /PID /T /F` 结束进程；结束前再抓一张 `final` 截图。

### 2.1 干净 PCSX2.ini 的关键点（都是踩坑得来的）

| ini 项 | 值 | 原因 |
|---|---|---|
| `[EmuCore/GS] Renderer` | `15`（D3D12） | 本机可用；`-renderer sw`(13) 也可 |
| `[EmuCore/GS] VsyncEnable` | `0` | 避免 vsync 卡时间线 |
| `[EmuCore/GS] FrameLimitEnable` | `true` | 保持 60 fps 的接近真实节奏；`--unlimited` 可关 |
| `[MemoryCards] Slot1/2_Enable` | **`false`** | 不给记忆卡 ⇒ 游戏弹自己的「No memory card…press X to continue」对话框，一次 Cross 即过；**避免 PCSX2 自己的模态错误框**（两个实例共享 runtime 时会弹「读取记忆卡失败」并污染测试） |
| `[Filenames] BIOS` | `SCPH-70012_BIOS_V12_USA_200.bin` | 明确指定，避免用户 BIOS 列表漂移 |
| `[Logging] EnableFileLogging` | `true` | `-logfile` 落 emulog，用于口径判定 |
| `[Hotkeys]` | **必须显式写** `Screenshot=Keyboard/F8` 等 | ⚠ 若干净 ini 里没有 `[Hotkeys]` 段，PCSX2 **不会注册任何热键**，F8/暂停/即时存档全部无效（这是本任务最大的坑） |
| `[Pad1]` | 键盘绑定 `Start=Keyboard/Return`、`Cross=Keyboard/Space` 等 | 供脚本化导航注入（`--keys/--press`） |
| `[UI] PauseOnFocusLoss` | `false` | 避免焦点切换导致暂停（虽然本机默认也是 false） |

### 2.2 截图：两条腿（用途不同）

| 方式 | 实现 | 产物 | 用途 |
|---|---|---|---|
| **原生截图（主证据）** | 激活窗口 → `SendInput` F8（PCSX2 hotkey）→ 从 runtime `snaps/` 取新 PNG | `*_native_<tag>.png`，1475×1106（模拟器帧缓冲） | **文本/字形/画面 A/B 的唯一可信来源**；无 UI、无 OSD |
| 窗口截图（辅助） | `PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT)` | `*_window_<tag>.png`，2126×1403（含标题栏/工具栏/RTSS OSD） | 证明"进程活着 + 有窗口"；**不要**用它对文本下定论：D3D12 swapchain 在 PrintWindow 下只能拿到部分画面（常见现象：大面积黑 + 右下角一小块游戏画面） |

> 备用方案（未默认启用）：把窗口置顶后用桌面 BitBlt/ImageGrab 截屏。实测会被其它前台窗口遮挡，
> 且本机用户正在用机器，因此**不作为默认**；`wincap.screen_capture_window()` 保留接口。

### 2.3 输入注入 / 菜单导航

- 干净 ini 的 `[Pad1]` 用**键盘绑定**：`Start=Return`、`Cross=Space`、`Triangle=W`、`Circle=S`、`Square=A`、
  方向键、`L1=Q`、`R1=E`、`L2=1`、`R2=2`。
- 注入流程：`force_focus(hwnd)`（AttachThreadInput + SetForegroundWindow + SetFocus）→ `PostMessage` 左键点一下渲染区
  → `SendInput` 键盘按键（**注意 Win32 `INPUT` 结构在 x64 下必须是 40 字节**，否则 SendInput 直接返回 0，按键静默丢失）。
- **冷启动时间线（英文原盘 / 字库盘通用，`-fastboot`，无记忆卡）**：

```
  0 – 7 s    BIOS / PS2 logo
  8 – 30 s   厂标 FMV（Red Storm 等）
 34 – 89 s   片头 movie
 ~100 s      Loading...（"Loading..." 文本已由游戏字体渲染）
 ~115–117 s  标题画面 "Tom Clancy's GHOST RECON JUNGLE STORM / Press START button"
 按下 START(Return)  → ~130 s  Profiles（- EMPTY SLOT - / Back / Create）
 按下 Cross(Space)   → ~145 s  FILE NAME 名字输入键盘（a-z / 0-9 / Ok / L1R1 Move）
```

- 因此推荐导航脚本：`--keys "15:space,102:space,118:return,133:space,148:return"`
  （15 s 按掉可能的"无记忆卡"对话框；102 s 处理 Loading 前后的对话框余量；118 s START；133 s Create；148 s 进名字输入）。
- 时间线有 **±数秒抖动**（wall-clock），所以判定一律以 native 截图的**内容**为准，不靠定时器。

### 2.4 收尾

`--seconds` 到点 → 抓 `final` → `taskkill /PID /T /F` → 等进程退出 → 读 emulog 判定。
`summary.json` 记录 `killed_by_tool`、`process_returncode`、`duration_actual_s`、所有截图统计与 `verdict`。

---

## 3. 工具与复现命令

### 3.1 工具清单（`tools/emu/`）

| 文件 | 作用 |
|---|---|
| `run_smoke.py` | **主工具**：准备干净 runtime → 启动 ISO → 定时窗口/原生截图 → 脚本按键导航 → 收尾 → `summary.json` + `RUN_LOG.txt` |
| `wincap.py` | Win32 窗口枚举/PrintWindow 截图/DPI 感知/SendInput 键盘/窗口激活（ctypes，无第三方依赖，Pillow 除外） |
| `compare_smoke.py` | 两次 run 的 native 截图按 tag 配对做逐像素 A/B（输出 JSON + 差异带分布） |
| `rebuild_js19_repro.py` | （备用，Lead 已要求暂停执行）从 dump 提取的 JS19 ELF + 3 payload 重建复现盘 |

`run_smoke.py` 参数：

```
--iso PATH            必填，要启动的 ISO
--seconds N           跑多少墙钟秒（默认 60）
--capture-at a,b,c    在这些秒数抓图（默认 15,30,45,60；native + window 各一张）
--keys "S:KEY,S:KEY"  脚本导航，KEY 支持 + 连按，如 "118:return,133:space"
--press S:KEY         同 --keys（可重复）
--out DIR             输出目录（截图/emulog/summary.json）
--tag NAME            截图文件名前缀
--runtime DIR         干净 runtime 目录（默认 work/analysis/emu/runtime/pcsx2-qt）
--renderer dx12|sw|vulkan|ogl|dx11
--native/--no-native  是否抓 F8 原生截图（默认开；关掉则不抢焦点，只抓窗口）
--statefile PATH      以指定 .p2s 存档启动（将来做帧级 A/B 用）
--keep                调试：跑完不杀进程
```

### 3.2 标准配方

```powershell
# 0) 环境（一次性）
$env:PYTHONIOENCODING="utf-8"

# 1) 英文原盘基线（标题/Profiles/名字输入 + Loading + FMV）
python tools\emu\run_smoke.py `
  --iso "third_party\orig\ps2\[PS2] Tom Clancy's Ghost Recon - Jungle Storm (U).iso" `
  --seconds 205 --capture-at 20,70,100,116,130,145,160,180,200 `
  --keys "15:space,102:space,118:return,133:space,148:return" `
  --tag baseline_en --out work\analysis\emu\baseline

# 2) 任意汉化/原型盘，同一配方（把 --iso/--out 换掉即可）
python tools\emu\run_smoke.py `
  --iso "work\builds\JS_ZH_font.iso" `
  --seconds 205 --capture-at 20,70,100,116,130,145,160,180,200 `
  --keys "15:space,102:space,118:return,133:space,148:return" `
  --tag fontprod --out work\analysis\emu\font_prod

# 3) A/B 像素对照
python tools\emu\compare_smoke.py `
  --a work\analysis\emu\baseline --b work\analysis\emu\font_prod `
  --out work\analysis\emu\ab_baseline_vs_fontprod.json
```

---

## 4. 实测证据

### 4.1 英文原盘基线：`work\analysis\emu\baseline\`

`summary.json` → `verdict = {boot_ok: true, window_ok: true, native_screenshot_ok: true, render_ok: true, success: true}`，
`serial=SLUS-20820`、`crc=DE1E4DEE`、`version=2.8.2`（注意：这是**英文原盘**的 CRC；JS_ZH19 的 CRC 是 3A320B22）。

| 帧 | 截图（native，1475×1106） | 内容 |
|---|---|---|
| ~20 s | `baseline_en_native_020s.png` | BIOS/PS2 启动后初始画面（FMV 前） |
| ~46 s | `baseline_en_native_045s.png` | 厂标/片头 FMV |
| ~71 s | `baseline_en_native_070s.png` | 片头 FMV |
| ~86 s | `baseline_en_native_085s.png` | 片头 FMV（游戏画面） |
| **~100 s** | **`baseline_en_native_100s.png`** | **Loading...（游戏字体渲染的英文文本）** |
| **~115 s** | **`baseline_en_native_115s.png`** | **标题画面：Tom Clancy's GHOST RECON JUNGLE STORM / Press START button / 版权文本** |
| **~130 s** | **`baseline_en_native_130s.png`** | **Profiles：- EMPTY SLOT - / No Tom Clancy's... / Ⓐ Back Ⓧ Create** |
| **~145 s** | **`baseline_en_native_145s.png`** | **FILE NAME 名字输入键盘（英文 a-z/0-9 字形）** |
| ~160/180/200 s | `..._160s/180s/200s.png` | 停留名字输入屏（注入按键未必改变选中格） |

窗口截图同目录 `*_window_*.png`（含 PCSX2 工具栏、RTSS OSD）：仅作进程/窗口存活证据。

### 4.2 字库原型（planB，中文图集 + 合并 FONT.RES，文本仍英文）：`work\analysis\emu\font_proto\`

运行命令与基线相同（只换 ISO）。结果：

| 帧 | 文件 | 结论 |
|---|---|---|
| **~116 s 标题** | `fontproto2_native_116s.png` | 与英文基线标题**逐像素相同**（sha256 `73c04b3c…` 两者一致）⇒ 标题画面是预渲染贴图，不受字库影响 |
| **~145 s 名字输入屏** | `fontproto2_native_145s.png` | **全部英文文本正常显示**：`Profiles` / `FILE NAME` / `a–z` `0–9` 键名 / `- EMPTY SLOT -` / `L1R1 Move` / `R2 Caps lock` / `Back` / `Accept` **无空白、无花屏、无错位**；字形风格与英文原盘不同（来自中文图集的 ASCII 字形），但字宽/间距/位置正常 |
| ~117 s Profiles | `fontproto2_native_116s.png`（标题）、`fontproto2_native_145s.png`（键盘） | Profiles 屏在 130 s native 抓取失败（焦点竞争），window 图可作旁证 |

> **R1 判定：通过**。中文图集里的 ASCII 字形被游戏字体系统正确上传/采样/绘制；
> 「换 1024×644 PSMT4 图集 → 纹理上传器不接受 → 英文文本空白/花屏」的最坏情况**没有发生**。

### 4.3 生产路径盘（`work/builds/`，`build.py` 顺序重排布局）：`work\analysis\emu\font\`、`work\analysis\emu\elf\`

两张盘用与基线完全相同的配方各跑 205 s：

| 盘 | 结果 | emulog CRC | 截图目录 |
|---|---|---|---|
| `work\builds\JS_ZH_font.iso`（1,229,285,376 B；只换中文图集 + 合并 FONT.RES，ELF 未打补丁） | `verdict.success=true`，20 张截图（9 张 native） | `DE1E4DEE`（= 英文原盘） | `work\analysis\emu\font\` |
| `work\builds\JS_ZH_elf.iso`（同尺寸；中文图集 + **DBCS v2 ELF 补丁**） | `verdict.success=true`，19 张截图（8 张 native） | `FD9E6AED`（补丁后） | `work\analysis\emu\elf\` |

关键证据（native 截图，1475×1106，模拟器帧缓冲）：

| 检查项 | 结果 |
|---|---|
| **标题画面** | `font_native_116s.png` / `elf_native_116s.png` / 英文基线 `baseline_en_native_115s.png` **sha256 全部相同**（`73C04B3C…`）⇒ ELF 补丁和字库替换都**不影响**标题渲染（预渲染贴图） |
| **英文界面文本** | Profiles（`*_native_130s.png`）、FILE NAME 名字键盘（`*_native_145s.png`）：`Profiles` / `FILE NAME` / `a–z 0–9` / `- EMPTY SLOT -` / `L1R1 Move` / `R2 Caps lock` / `Back` / `Accept` **全部正常可读，无空白/花屏/错位** |
| **字形来源** | font 与 elf 的 145 s 名字键盘 **逐像素相同**（`6C1871B3…`），与英文基线不同（`32434613…`）：差异只在**字形风格**（ASCII 字形来自中文图集），文字内容/位置/宽度正常 ⇒ loader 正确接受 1024×644 PSMT4 图集（R1 通过） |
| **A/B：ELF vs FONT** | `compare_smoke.py` 9 个共享 tag：**6 个 0 差异**（20s、116s 标题、145/160/200s、final）；070s/100s 差异是片头 FMV/Loading 的 wall-clock 相位差，130s 差 0.317%（背景动画相位）⇒ **DBCS ELF 补丁没有可见副作用** |
| **TLB / 崩溃** | 两盘 `summary.json → emulog_info.errors = []`：**0 条 TLB Miss / Trap exception / Jump to unmapped / ReportErrorAsync**；均跑满 205 s，未见卡死/异常退出 |
| 结论 | **R1 通过**；**DBCS v2 ELF 补丁在「启动→片头→标题→Profiles→名字输入」路径上行为干净**。注意：本次**未进入实际任务/游玩**（TLB Miss 的历史复现点是进游戏后 38 s，见 §7 待办） |

对照报告 JSON：`work\analysis\emu\ab_baseline_vs_font.json`、`ab_elf_vs_font.json`、`ab_baseline_vs_elf.json`。

> 说明：2026-10-21 第一次跑 `JS_ZH_font.iso` 时出现过一次 **PCSX2 窗口只有 314×50 + 全程 0 张截图**的偶发现象
> （窗口创建/前台竞争导致），同配方重跑即恢复正常；工具已放宽窗口识别阈值并保留 `window_*` 旁证，遇到时**重跑一次**即可。

### 4.4 全量中文测试盘 `work\builds\JS_ZH_all_test.iso`：`work\analysis\emu\all_test\`

（中文图集 + DBCS v2 ELF + 中文文本 2950/3389 条；CRC `FD9E6AED`）

| 检查项 | 结果 |
|---|---|
| 启动/标题 | ✅ 正常，标题 `alltest_native_116s.png` 与英文基线逐像素相同（预渲染贴图） |
| **Profiles「档案」页** | ✅ `alltest_native_130s.png`：标题「档案」、`- 空插槽 -`×3、底部「《幽灵行动》的存档数据。」、按钮「返回 / 创建」——**中文可读、无乱码/吞字** |
| **名字输入「文件名」页** | ✅ `alltest_native_145s.png`：`文件名：`、`- 空插槽 -`、`L1R1 移动`、`R2 大写锁定`、`删除`、`返回`、`接受`、`确认`——**全部正常** |
| 布局小问题 | ⚠ 左上角「档案」贴屏幕左上边缘有轻微截断/重叠；底部帮助行最左的「《」疑似贴边。属于**布局/锚点**问题，不是字库/编码问题（截图已交 Lead） |
| TLB/崩溃 | ✅ `emulog_info.errors = []`，跑满 330 s 无异常 |
| 深度导航 | ⚠ 本轮未过名字输入（D-pad 注入问题：Cross 有效、方向键无效）→ 已修复：`[Pad1]` 增加左摇杆绑定 + SendInput 方向键加 `EXTENDEDKEY` 标志；修复后 `work\analysis\emu\nav3\nav3_native_210s.png` 可见光标已能在键盘屏内移动 |

### 4.5 正式候选盘 v1 / v5（中文全量 + 字库度量规整）：`work\analysis\emu\v1\`、`work\analysis\emu\v5\`

| 盘 | CRC | 结果 | 截图 |
|---|---|---|---|
| `work\builds\JS_ZH_v1.iso`（3372/3372 译文 + DBCS v2 ELF + 中文图集） | FD9E6AED | ✅ 启动/标题/Profiles/文件名 中文正常；**0 TLB/异常**；深导航未过名字输入（卡在「确认」前） | `v1\v1_native_130s.png`（档案页）、`v1_native_145s.png`（文件名） |
| `work\builds\JS_ZH_v5.iso`（v1 + **A′ FONT.RES 度量规整**：face CharHeight 26→16、style 高度/宽度缩放 >1 归 1.0） | FD9E6AED | ✅ 标题「档案」**方形、不裁剪**；按钮「- 空插槽 -」大小/基线正常；中文 UI 无乱码/吞字/溢出；**0 TLB/异常**；跑满 345 s | `v5\v5_native_130s.png`（档案页，最终对照）、`v5_native_145s.png`（文件名） |

**A′ 度量修复的前后量化**（`work\analysis\emu\measure_text.py`，640×480 游戏坐标，`--box 28,12,72,60`，阈值 120）：

| 指标 | all_test（修复前） | v5（A′ 后） | 参考 |
|---|---|---|---|
| 「档案」标题 ink 高 | **40.8 px**（拉伸/贴顶） | **15.2 px**（≈16 px 方形，不裁剪） | 期望 23–26；font-engineer 独立口径 39.9→14.8 |
| 「- 空插槽 -」按钮字高 | 23.0 px | 13.5 px（font-engineer 同口径） | 正常 |
| 英文标题 / 预渲染贴图 | — | 与英文基线逐像素相同（标题 LOGO 是贴图，不随字库变） | — |
| 像素差异（v5 vs all_test，130s 同屏） | — | 约 4.4–5.3%（全部来自文字/字形变化） | — |

**已知残余（不阻塞定版）**：v5 深导航仍未进入主菜单/任务简报/HUD（名字输入→确认的 D-pad 注入不稳定，属**测试工具/输入注入**问题，不是游戏/汉化问题）；因此**「Campaign 简报页折行 / HUD 小字」尚未实机覆盖**。可达界面里的小字样式（底部帮助条、按钮）未见上/下裁切或横向溢出。建议后续提供 ① 一个建好档的 `.p2s` 存档 或 ② 记忆卡存档，即可用 `--statefile` 直接跳到 HUD/简报页做最终抽查。

---

## 5. 坑 / 限制（把话写死）

1. **需要交互式桌面**：PCSX2 Qt 必须有窗口（`-nogui` 会隐藏窗口且拿不到画面）；本机是活动桌面所以可用，
   纯 headless/服务化环境不可用。
2. **F8 原生截图需要窗口激活**：工具会 `AttachThreadInput + SetForegroundWindow` 抢一次前台（约 0.5–1.5 s），
   用完把原前台窗口还回去。**每抓一张 native 图抢一次**；如果用户正在用机，建议：少放 `--capture-at`、或 `--no-native` 只抓窗口图。
3. **PrintWindow 对 D3D12 只拿到部分画面**：窗口截图不能用于文本验证；只用 native。
4. **RTSS / MSI Afterburner OSD**：只出现在窗口截图，不影响 native；但窗口截图里会有 CPU/GPU/RAM/FPS 大字。
5. **干净 ini 必须写 `[Hotkeys]`**，否则 F8/暂停/存档热键全不生效（第一版工具就栽在这里）。
6. **`[MemoryCards]` 关闭**：否则 PCSX2 会弹自己的「读取记忆卡失败」模态框；两个 PCSX2 实例共用一个 runtime 时必现。
   关闭记忆卡后游戏会弹自己的 "No memory card…press X" 对话框，按 Cross（Space）继续即可。
7. **时间线是 wall-clock**：同一 ISO 不同次运行的标题/菜单出现时刻 ±数秒；像素级 A/B 只在同一 tag 语义下比对
   （我们的 tag 是"墙钟秒"，不是"游戏内帧号"）。真正帧级需要 gsrunner（§6）或 savestate 对齐（`--statefile` 已支持）。
8. **一次 run 约 3.5 分钟**（205 s 墙钟 + 启动/收尾），不适合每改一个字节就跑；建议用作阶段门禁。
9. **PCSX2 升级会漂移**：runtime 是复制出来的，不会自动升级；如需复现历史截图，固定这份 runtime 的 sha256。
10. **两条内存卡/存档**：本报告的全流程都没有用真实存档（无 card），所以「读档→某菜单」的验证需要另配 savestate/记忆卡。
11. **偶发「窗口 314×50 + 0 截图」**：2026-10-21 首跑 `JS_ZH_font.iso` 遇到过一次（疑似窗口创建/前台竞争），同配方重跑即恢复；
    工具已放宽窗口识别阈值（≥200×60 且优先有标题窗口），遇到时**重跑一次**并在 `summary.json.windows_seen` 里核对窗口尺寸。
12. **本次未验证「进游戏/任务内」路径**：所有 run 都停在「标题→Profiles→名字输入」。历史上 JS_ZH19 的 TLB Miss 在进游戏 38 s 后出现，
    要复现/验证需要一条能跳过 name-entry 的导航（需要记忆卡存档或后续做 `--statefile` 存档点），见 §7。

---

## 6. 备选方案：工程内仪器化 `pcsx2-gsrunner`（当前不可用）

本体工程 `third_party\emu\pcsx2\pcsx2-gsrunner\pcsx2-gsrunner.exe` 是**带 GR 研究仪器**的 PCSX2 GS Runner
（版本 `v2.8.2-1-gcd5e3304c`，9,801,216 B），源码在 `pcsx2_src\pcsx2-gsrunner\GRResearch.cpp` 可见其能力：

| 开关 | 能力（帧级、确定性） |
|---|---|
| `-grdumpdir DIR` | 研究模式输出目录（`grlog.txt`、`cdvd.log`） |
| `-grmaxframes N` | 跑满 N 帧自动退出（帧级，不是墙钟） |
| `-grsnap N` | 每 N 帧落一张 PNG（GS 线程直出，不需要窗口焦点） |
| `-grinput FILE` | 脚本化手柄注入：`<frame> <Button> press|hold|release`（帧级精确） |
| `-grstate FILE` | 启动即加载 .p2s 存档 |
| `-grneedle` / `-grmemwatch` / `-grpcring` / `-grwatch` | 内存 needle 扫描 / RAM 落盘 / 执行块环形 trace / 写监视 |
| `-grbios` / `-grmemcards` / `-grsetting` | BIOS / 记忆卡目录 / 设置覆盖 |

**当前状态：不可用 ❌**（2026-10-21 实测）：

- 带 GR 参数跑 ISO 时进程静默退出/崩溃：默认 D3D12 下退出码 `0xC0000409`（约 13–14 s，GS/VM 初始化阶段），
  无 `grlog.txt` / 无截图产出；`-renderer sw` 下也无产物。
- 直接原因候选：该 exe 的运行目录缺 **D3D12 Agility `D3D12Core.dll`**（安装版 PCSX2 的 `D3D12\` 子目录）；
  但工作目录里已有 `bios/`、`resources/`，且 `-help`/`-version` 正常 ⇒ 是**构建/运行环境差异**，不是完全坏。
- 历史证据：本体工程曾用同一仪器跑出 6000 帧 / 5738 张逐帧截图（`-grsnap 1`），说明它**修好后价值极大**。

> 建议：如果后续要做「中文文本渲染的帧级 A/B」，优先修复 gsrunner（补 D3D12Core.dll / 按 `third_party\emu\pcsx2_src` 重建），
> 而不是日常用 Qt 冒烟。Qt 冒烟作为「先证明能启动、能出标题/菜单、能截图」的门禁就够。

---

## 7. 给汉化盘做 A/B 的用法（建议流程）

1. **同配方**：同一个干净 runtime、同一个 BIOS、同一个 `--seconds/--capture-at/--keys`、同一个 renderer（dx12）。
2. **A 盘**（英文原盘）先跑出基线 → `baseline` 目录；**B 盘**（汉化盘）同配方跑 → `font_prod`/`zh` 目录。
3. `compare_smoke.py --a baseline --b zh` 对 native 截图按 tag 配对，输出逐像素差异率与 y 带分布；
   - 标题画面（预渲染贴图）应 **0 差异**（除非换了贴图）；
   - 文本屏（Loading / Profiles / 名字输入）应 0 差异（英文文本未被翻译时），若字形被换会出现"字形风格差异但文本仍可读"；
   - 真正验证**中文**需要等文本层（EN_STRINGS/SFXML/MIS）注入后的盘：同一屏会出现**中文字形**，届时 native 截图就是决定性证据。
4. 需要「同一画面、可重复」的严格对照时：先在 A 盘跑到目标屏 → `--keys` 到该屏 → 记下 tag；
   或在 emulator 里按 F1 存档、之后用 `--statefile` 直接从该屏启动（同一 ISO 内有效；跨 ISO 会带入旧字库/RAM，**不能**用于字库 A/B）。

---

## 8. 复现环境登记

| 项 | 值 |
|---|---|
| 工具版本 | 本报告随附 `tools/emu/*.py`（`run_smoke.py` schema `gr-js-smoke/1`） |
| PCSX2 | 2.8.2 便携版；exe 15,257,088 B，sha256 head `a3e85ae9aa0e1451` |
| runtime 副本 | `work\analysis\emu\runtime\pcsx2-qt`（≈175 MB；含 BIOS、干净 ini） |
| 干净 ini | `work\analysis\emu\runtime\pcsx2-qt\inis\PCSX2.ini`（由 `run_smoke.py` 生成，内容见 §2.1） |
| 基线 run | `work\analysis\emu\baseline`（26 张截图、summary.json、emulog.txt、console.txt） |
| 字库 R1 run | `work\analysis\emu\font_proto`（planB 盘，18 张截图） |
| 生产字库 run | `work\analysis\emu\font_prod`（`work\builds\JS_ZH_font.iso`） |
| 每次 run 判定 | `summary.json` → `verdict.success`；口径 = emulog 有 disc serial + 有窗口 + 至少一张 non-blank native 截图 |

---

## 附录 A：判定口径定义

`run_smoke.py` 的 `verdict`：

| 字段 | 定义 |
|---|---|
| `boot_ok` | emulog 存在，且解析到 `Serial: SLUS-xxxxx` 或 `(SYSTEM.CNF)` 等启动行 |
| `window_ok` | 抓到过 PCSX2 主窗口（native 或 window 截图成功） |
| `native_screenshot_ok` | 至少一张 native 截图 `is_blank=false`（均值/唯一色数启发式） |
| `render_ok` | native 或 window 至少一张非空白 |
| `success` | 以上全 true |

截图 `is_blank` 启发式：luma 均值 < 2 且（4×4 抽样）唯一色数 ≤ 2。

## 附录 B：已知问题清单（按优先级）

1. ~~F8 热键不生效~~ → **已修**：干净 ini 必须含 `[Hotkeys]`。
2. ~~SendInput 静默失败~~ → **已修**：x64 `INPUT` 结构 40 字节。
3. ~~两个实例共享 runtime → 记忆卡模态错误~~ → **规避**：先确保无其他 pcsx2 进程；`[MemoryCards]` 关闭。
4. ~~窗口截图 D3D12 只有部分画面~~ → **规避**：文本/画面对照一律用 native F8 截图。
5. 原生截图焦点抢占（体验问题）→ 可 `--no-native` 或减少 `--capture-at` 次数。
6. gsrunner 帧级仪器修复（TODO，见 §6）。
