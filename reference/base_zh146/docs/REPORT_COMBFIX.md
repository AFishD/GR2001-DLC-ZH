# REPORT_COMBFIX —— 「任务完成提示处卡死」的失效模式判定 + 四张组合修复盘 + 验证

> ⚠ **历史错误断言订正（2026-10-18 收尾轮）**：本文含已被实测/实机否证的表述 —— 见 `docs/CORRECTIONS.md` §7。
> 原文保留作过程记录；**结论冲突时以 `docs/CORRECTIONS.md` + `docs/STATUS.md` 为准**。

* 轮次：**GR_COMBFIX**（2026-10-18，Asia/Hong_Kong）
* 输入（**直接采用，不重查**）：6 份新 F10 手抓 dump（`work\builds\GR_HOOKEMU_QT2\qt\hookdumps\hook_{10470,13112,14025,16893,19095,19671}_hotkey_f10\**`）+ 同目录 `logs\emulog.txt`（4,697 行）；
  `docs\REPORT_SPINFIX.md`（F4/F1F2 站点、残余风险）、`docs\REPORT_OOMFIX.md`（解压器 NULL 检查）、`docs\REPORT_USERDUMP_ANALYSIS.md`、`docs\REPORT_HEAP_EXHAUSTION.md`
* 产物：`work\builds\GR_COMBFIX\**`（**4 张盘** + 11 个存档变体 + 16 个 run + 全部工具/日志/JSON）、本报告、`docs\HOOKEMU_QT2_GUIDE.md` §9 追加
* 只读：所有既有 ISO / 产物 / `third_party\**` / 用户 PCSX2 目录（只 `open(...,'rb')` 与 `Copy-Item` 出来；用户的 `pcsx2-qt.exe`（pid 31760）**只等不杀**）
* 未 commit / 未切分支 / 未 merge；**全程未使用 `Select-Object -First N`**

---

## 0. 结论速览（TL;DR）

| 问题 | 答案 |
|---|---|
| 「任务完成处卡死」是什么 | **① 又一次 malloc 自旋**——但是**另一条回边**：`0x102180 → 0x1021A0 → 0x1021D0 → 0x1021D4`（malloc 的「请自己的桶」快路径）。F4 只挂了 binmap 扫描的回边 `0x102588`，**覆盖不到它**（`REPORT_SPINFIX.md` §4.3 残余风险③原文预告） |
| 指令级铁证 | 用户 dump（frame 19671）`pc=0x102180`、**`v0=0`**、`a0=0x55B7A0`(mstate)、`a1=0x80010`(nb)、`a2=0x1FFFFFFE`(size 掩码)、`a3=0x55BB88`(桶 126 伪 chunk)、`r10=0x7E`(**桶号 126**)；RAM 里桶 126 = `0xF968B859`（越界）。见 §2.3 |
| 是不是 ②（F4 bail→NULL→调用侧未处理） | **不是**：本次日志 `Trap` **0** 行、`Unrecognized op` **0** 行、`ReportErrorAsync` **0** 行、`0x7E7E7E7E` 式跳飞 **0** 次；`badvaddr=0`、`cause=0x20`（只是 pending 中断位，不是异常） |
| 是不是 ③（文本/UI 资源加载失败/等待） | **不是**：最后 309 条 PC 采样**全部**落在 `0x102180/0x1021A0/0x1021D0`（外加内核 `EENULL` syscall 桩 `0x81FF0`）；`0x102180` 处 `v0=0` 只可能来自「已经绕过至少一圈」，而绕圈而不退出的唯一条件是低端 `0x8/0x14` 读回 0（真机 TLB Miss ⇒ 0） |
| 桶 126 又坏了吗 | **坏了，而且是新值**：6 份 dump（frame 10470…19671）**全部**是 `0xF968B859/0xF968B859`（fd=bk），且这个 4 字节值在 32 MB 里只出现在这两个槽（前 5 份）；不是上一轮的 `0x6ED47823`/`0xA73D37F0` |
| 是同一根因的残余还是新问题 | **同一根因（桶链被毒化 + 分配器信任链头）的残余**，卡死站点从 binmap 回边换到了 own-bin 回边。见 §2.6 |
| 出了哪些盘 | `COMBFIX_A`（F4+OOMFIX）、`COMBFIX_B`（+F1+F1b）、`COMBFIX_C`（**+F7 = 本轮新病灶的最小修复**）、`COMBFIX_2400`（产品线 = **F4+OOMFIX+F7**）；4 张全部 8 项自证 OK，见 §3.3 |
| 修好了吗 | **是（本机能给出的最强证据）**：把「own-bin 的桶」毒化后，未修/F4/A/B 四张盘都是 `0x102180→0x1021A0→0x1021D0` 纯三块死循环；**`COMBFIX_C` 下 F7 cave 命中 3 次、F4 cave 命中 1 次、malloc 正常返回 2,031 次、解压器 14 次**；6000 帧冒烟：`COMBFIX_A`/`COMBFIX_C`/`COMBFIX_2400` **191 张截图 / TLB 0 / Trap 0 / 与各自基底逐帧 sha256 完全相同（逐像素 0 差异）**，`COMBFIX_B` 有 **6 帧**差异（帧 660..810，**定位到 F1 的 cave `0x0055B730`**，见 §4.3） |
| 为什么不把 F1/F1b 放进推荐组合 | ① 它们**拦不住**本次的"野 `free(garbage)` + 大块插链"（它们校验的是**推导出来的** P，不是传进来的 C）；② 本机实测：`COMBFIX_B` 现场**照样死在同一条三块循环上**；③ 它们的 cave 带来实测 6 帧像素差异 ⇒ **收益未证、代价已测**，故 `COMBFIX_B` 只作诊断盘 |
| 给用户的下一步 | §5：**`COMBFIX_C.iso` 先测**（把存档按新 CRC `CF9B8C97` 改名，或从记忆卡/关卡开头进），走到「任务完成」提示处看能否进结算 |

---

## 1. 素材清点 / 纪律 / 污染 / 磁盘

### 1.1 新 dump 与日志（只读）

| 素材 | 读数 |
|---|---|
| `hook_10470_hotkey_f10\` | frame 10470，reason=hotkey_f10，pc=0x00411FB0，ring_entries_total=4,809,790 |
| `hook_13112_hotkey_f10\` | frame 13112，pc=0x001A78C4，ring_total=5,568,356 |
| `hook_14025_hotkey_f10\` | frame 14025，pc=0x00411FB0，ring_total=5,778,743 |
| `hook_16893_hotkey_f10\` | frame 16893，pc=0x00458330，ring_total=6,584,137 |
| `hook_19095_hotkey_f10\` | frame 19095，pc=0x004B56E0，ring_total=7,132,880 |
| **`hook_19671_hotkey_f10\`** | frame 19671，**pc=0x00102180**，ring_total=7,273,608 |
| 每个 dump 目录 | `ee_ram.bin` 33,554,432 B、`iop_ram.bin` 2,097,152 B、`ring.bin` 6,291,456 B、`ring.txt` ≈14.3 MB（262,144 条）、`watch_00500000_00581000.bin` 528,384 B、`meta.txt` 1,146 B、`regs.txt` 38,741 B（含 **`recent_block_pcs`：4096 条「块入口/帧/异常」采样**） |
| `logs\emulog.txt` | 4,697 行；`[0.0605]` HookWatch ACTIVE → `[404.2448] (VMManager) Pausing...`；6 次 `F10 pressed`（188.78/248.09/268.63/328.69/376.90/395.91 s） |

### 1.2 纪律与污染

* 模拟器**独占检查**：本工程每次起跑前轮询 `Get-Process pcsx2*`，命中就写 `OTHERS_RUNNING.txt` 并**继续跑**（只记录不杀）。全程 1 个他人实例：`pcsx2-qt` pid 31760（起于 14:51:12，即用户自己那次现场）。
* 该污染只影响墙钟；本机 gsrunner 逐帧确定（§4.3 的逐帧 sha256 对照可证）。
* 写入只落在 `work\builds\GR_COMBFIX\**` 与 `docs\REPORT_COMBFIX.md`（+ 指南追加）。
* 磁盘：开工 `Get-PSDrive C` 余 **11.5 GB**；4 张盘 6.59 GB；中途 4.73 GB 时清理了**本轮自己的**中间物（needle 机制的 `*_eeram.bin`/`*_iopram.bin` 与每个 run 的 `mc\` 副本，**不含**任何用户给的 dump/报告/脚本/既有盘），回收 **1,183 MB**；结束时约 4.1 GB（§8）。

---

## 2. A. 「任务完成提示处卡死」的失效模式判定

### 2.1 日志读数（逐项，含两处澄清）

**(1) `FATAL` 那一行：不存在。**
`Select-String -Pattern 'fatal' -CaseSensitive:$false` 全日志只命中 **1 行**：

```
L58: [0.0605] HookWatch: triggers: 12 trigger PC(s), fatal EE exceptions, F10 hotkey, TRIGGER file in '...\hookdumps'
```

这是**触发器配置的说明文字**（"致命 EE 异常时落盘" 这一种触发方式的描述），不是事件。同族检查：`EE FATAL` **0 行**、`EE EXCEPTION` **0 行**、`exception_*` 落盘目录 **0 个** ⇒ **本次卡死没有产生任何「致命 EE 异常」**。
（为什么 TLB Miss 不算异常：PCSX2 只在**解释器**路径把 TLB Miss 变成 EE 异常——`vtlb.cpp:534-545` `if (Cpu == &intCpu) { cpuTlbMissR/W(...); }`；**重编译器**路径只打印一行并返回 0，`HookWatch::OnException`（挂在 `R5900.cpp:100 cpuException()` 上）**不会被调用**。这解释了为什么 50 条 TLB Miss 一条 `EE EXCEPTION` 都没带出来。）

**(2) `TLB Miss` 50 行 = 打印上限，不是"只有 50 次"。**
`vtlb.cpp:557-559`：

```cpp
static int spamStop = 0;
if (spamStop++ < 50 || IsDevBuild)
    Console.Error(message);
```

⇒ **只有前 50 条会打印**。因此：
* 首条：`L2680 [139.3401] TLB Miss, pc=0x101dac addr=0xf968b869 [load]`
* 末条：`L3708 [267.4018] TLB Miss, pc=0x102584 addr=0xf968b86d [load]`
* **138–267 s 之后的 miss 一律不可见**——卡死在 ≈388 s，它的 miss 全在被截断的部分里。
* ⚠ 日志里的 `pc=` 是 **PCSX2 重编译器的块起始 PC**（"memory ops don't flush the PC"，`vtlb.cpp:451-452` 的注释），所以 `pc=0x102178` 对应的访存指令其实是 `0x102180 ld v1,8(v0)`、`pc=0x1021d0` 就是 `0x1021D0 lw v0,20(v0)`。**地址是精确的**，PC 要按块首读。

50 行分成 7 批（PC 分组 + 地址）：

| 时间 | 行数 | PC（块首） | 地址 | 归属 |
|---|---|---|---|---|
| 139.3401–139.3405 | 9 | `0x101dac`/`0x101dd8`/`0x101e34`/`0x101e6c`/`0x102008` | `0xf968b869`/`0xf968b86d`/`0x14`/`0x10`/`0x7660778`/`0xf968b861` | **free()+大块插链**（毒化那一刻） |
| 179.8830 | 2 | `0x1024d0`/`0x102584` | `0xf968b861`/`0xf968b86d` | malloc binmap 扫描（F4 拦下） |
| 224.7162–224.7171 | 19 | `0x101d10`/`0x101dac`/`0x101dd8`/`0x101de4`/`0x101e08`/`0x101e34`/`0x101e6c`/`0x101fe0`/`0x102000`/`0x102008` | `0x6e6a340`/`0x6ed4782b`/`0x6ed47837`/`0x14`/`0x10` | free()+插链（**旧坏值 0x6ED47823** 也在链里） |
| 237.8102 | 14 | `0x101d10`/`0x101dd8`/`0x101de4`/`0x101e08`/`0x101e34`/`0x101e6c`/`0x101fe0`/`0x102000`/`0x102008` | `0x14e228f7`/`0x14e228ff`/… | free()+插链（第三个坏指针） |
| 250.8237 / 264.4051 / 267.4017 | 2+2+2 | `0x1024d0`/`0x102584` | `0xf968b861`/`0xf968b86d` | malloc binmap 扫描（各 2 条 = 一轮就 bail） |

**注意 179.9 / 250.8 / 264.4 / 267.4 s 这四次的形态**：每次**只有 2 条**（`0x1024d0` + `0x102584`），第 3 条（真机原来那条 `addr=0x8`）**没有出现** ⇒ 这四次都被 **F4 当场拦下**、malloc 退到 top 切分继续跑。这正是 F4 正常工作的"签名"。

**(3) 触发落盘的原因与帧号**：6 次落盘**全部**是 `reason=hotkey_f10`（用户按 F10），帧号 10470/13112/14025/16893/19095/19671；`dump_on_trigger=0`（配置里关掉了自动触发）、`trigger_once=1`，因此**没有任何一次是分配器 trigger 或异常自动落盘**。最后 `[404.2448] (VMManager) Pausing...` = 用户手动暂停（其前一小时无任何 `ReportErrorAsync`）。

**(4) 「最后 1,000 条命中」的模式**（`tools\ring_tail.py`，输出 `out\ring_tail.json`）：
* 每份 dump 的 `ring.txt` 都是**满环 262,144 条**，覆盖的帧区间随 dump 走（如 19671 那份覆盖 **18572→19569**，≈998 帧）；
* **19671 那份的尾部 1,000 条只跨 8 帧（19562–19569）**，PC 全部是分配器内部写：`0x101EFC`×246 / `0x101EEC`×245 / `0x101E44`×193 / `0x102014`×99 / `0x101E40`×42 / `0x1020C0`×40 / `0x102018`×35 / `0x101DE4`×19，地址集中在 `0x55B7A0`(mstate/binmap)×259、`0x55B7C8`、`0x55B7E8`、`0x55BAC0`、`0x55B828`；
* 尾部**最后 3 条记录的帧号都是 19569**，而 dump 发生在 **19671** ⇒ **19569 帧之后，被监视的 512 KB 窗口一个字节都没被写过**（`0x102180/0x1021A0/0x1021D0` 是纯读循环，本来就不写）。⇒ 卡死时刻 ≈ **frame 19569**（≈388 s）。
* 对照前 5 份：尾部 1,000 条的帧区间都是 5 帧（如 10465–10469），PC 以 `0x40574C`（非分配器，游戏逻辑）与分配器桶写并存 ⇒ 当时游戏**正常推进**。

### 2.2 六份 dump 的读数（含「F4 在位」证明）

`tools\probe_ram.py` → `out\probe_ram.json`：

| dump | frame | pc | r02(v0) | r04(a0) | r05(a1) | r06(a2) | r07(a3) | r10(t2) | 说明 |
|---|---|---|---|---|---|---|---|---|---|
| 10470 | 10470 | 0x00411FB0 | 0 | 4 | 0x80010 | — | — | 0 | 常规游戏代码 |
| 13112 | 13112 | 0x001A78C4 | 0x40C90000 | 0x1FFE950 | … | | | | 常规 |
| 14025 | 14025 | 0x00411FB0 | 0 | 4 | … | | | | 常规 |
| 16893 | 16893 | 0x00458330 | … | | | | | | 常规 |
| 19095 | 19095 | 0x004B56E0 | … | | | | | | 常规 |
| **19671** | **19671** | **0x00102180** | **0** | **0x0055B7A0** | **0x00080010** | **0x1FFFFFFE** | **0x0055BB88** | **0x7E** | **malloc own-bin 自旋中** |

* **F4 补丁 6 份全在位**：`0x00102588 = 0x081068D7`（`j 0x0041A35C`）、`0x0041A35C = 0x0322082B`（F4 cave 首字）——即 `SPINFIX_F4.iso` 的代码确实进了 RAM（冷启动装载 ELF，不是读旧存档）。
* `0x00539174 = 0xAE620004`（**原字**）⇒ 用户手上这张盘**没有** OOMFIX。
* **桶 126 = `0xF968B859`（fd=bk）在 6 份里完全一致**；这个 4 字节值在 32 MB 中的出现次数：前 5 份**只有 `0x0055BB98/9C` 两处**（"不是从别处拷来的，是算出来/写进去的"），第 6 份出现 **6 次**（另 4 处 `0x00952110 / 0x00DBCC60 / 0x01495E90 / 0x01694520`，均在堆内）。
* 堆顶（`0x0055B7A8`）随时点右移、`heap_end` 恒为 `0x01F98020`：`0x1B8C520`(10470) → `0x1B94540`(16893) → `0x1C26750`(19671)，**top 剩余 4.24 MB → 3.61 MB**。

### 2.3 ★ 指令级证据链（七条）

**(1) 卡死现场的寄存器把循环钉死。** frame 19671：`pc=0x102180`、`v0=0`、`a0=0x55B7A0`(mstate)、`a1=0x80010`(nb=512 KB+16)、`a2=0x1FFFFFFE`(size 掩码)、`a3=0x55BB88`(桶 126 伪 chunk)、`t2=0x7E=126`(桶号)。
`t2`、`a2`、`a3` 三个值**同时**只在一条路径上成立——own-bin 扫描（见 (3) 的 0x102158–0x10217C）。

**(2) 站点字（从**用户 dump 的 ee_ram** 现场反汇编，与基底逐字相同）：**

```
0x102150  beq $zero,$zero,+1 -> 0x102158     ; t2 = idx（dispatch 计算完）
0x102158  sll  $v0,$t2,1
0x10215C  addiu $v0,$v0,2
0x102160  sll  $v0,$v0,2                     ; v0 = 8*idx + 8
0x102164  addu $v0,$a0,$v0                   ; v0 = mstate + 8*idx + 8 = &bin[idx].fd
0x102168  addiu $a3,$v0,-16                  ; a3 = bin[idx] 伪 chunk（idx=126 → 0x0055BB88 ✓）
0x10216C  lw   $v0,4($v0)                    ; ★★ v0 = bin[idx].bk  ← 第一次信任链头
0x102170  beql $v0,$a3,+28 -> 0x1021E4       ; 桶空（bk==伪 chunk）才跳过；否则扫链
0x102174  addiu $t2,$t2,1                    ; （BEQL 未取时该延迟槽被 nullify ⇒ t2 保持 idx ✓）
0x102178  lui  $v1,0x1FFF
0x10217C  ori  $a2,$v1,0xFFFE                ; a2 = 0x1FFFFFFE（size 掩码）✓
0x102180  ld   $v1,8($v0)                    ; ★★ v1 = 链头->head（v0=0xF968B859 ⇒ TLB Miss ⇒ 0）
0x102184  and  $t1,$v1,$a2                   ; size
0x102188  subu $t0,$t1,$a1                   ; t0 = size - nb
0x10218C  slti $v1,$t0,32
0x102190  bne  $v1,$zero,+3 -> 0x1021A0      ; size < nb+32 → 去 0x1021A0
0x102198  beq  $zero,$zero,+17 -> 0x1021E0   ; 否则（块大得多）→ 换下一个桶
0x1021A0  bltz $t0,+11 -> 0x1021D0           ; size < nb → 看链的下一个
0x1021A4..0x1021CC  …（摘下这一块并切分，本现场走不到）
0x1021D0  lw   $v0,20($v0)                   ; ★★ v0 = 链头->bk（v0=0 ⇒ TLB Miss ⇒ 0）
0x1021D4  bne  $v0,$a3,-22 -> 0x102180       ; ★★★ 回边：v0 != 伪 chunk 就继续扫
```

**(3) 为什么 `v0=0` 就永远出不来。** 进入循环时 `v0 = bin126.bk = 0xF968B859`（RAM 里就是这么写的）。因为 `0xF968B859` 属**未映射 KUSEG**：
* `0x102180 ld v1,8(0xF968B859)` → TLB Miss（`addr=0xF968B861`）⇒ v1 = **0**；
* 于是 `size=0 < nb=0x80010` ⇒ `0x1021A0 bltz` 取 ⇒ `0x1021D0 lw v0,20(0xF968B859)` → TLB Miss（`addr=0xF968B86D`）⇒ **v0 = 0**；
* `0x1021D4 bne 0,0x55BB88` **取** ⇒ 回 `0x102180`，此时 `obsolete v0=0` ⇒ `ld v1,8(0)` ⇒ 再走一遍 `0x1021A0 → 0x1021D0 → 0x1021D4`：
  **只要 `0x8` 与 `0x14` 读回 0，这就是一个纯读的死循环。**

**(4) 真机上 `0x8/0x14` 确实读回 0**（而不是读到 RAM 里的内容）：用户 dump 的 `ee_ram.bin` 里 `0x8..0xF = 0x07EA090E0F2B1F00`、`0x14 = 0x00008427`（**非零**），但现场 `pc=0x102180` 时 `v0` 已经是 **0**。假如那两次访存能读到 RAM，`size = 0x07EA090E0F2B1F00 & 0x1FFFFFFE = 0x0F2B1F00`（254 MB）⇒ `t0 = size - nb > 0` ⇒ `0x102198 beq $zero,$zero,+17` 直接跳到 `0x1021E0`，**循环一轮就出去了**，绝不会出现"还在 0x102180 且 v0=0"这种状态。⇒ **两处访存都是 TLB Miss（页 0 未映射）**，这也是用户在旧现场（10:52 那份 dump）日志里看到的 `TLB Miss … addr=0x8 / 0x14` 的同一机制。
（本机要复现这条链，必须**人为把 `0x8/0x14` 清零**来等价"读回 0"，见 §4.2。）

**(5) 落盘/停滞时间线吻合**：最后一条被监视写 = frame **19569**（§2.1(4)），`0x00101E44/0x00102014` 这些 PC 正是 `free()` 的"大块插链"（`0x101E44` = 插链四连 `sw`）。也就是说：**任务完成时先发生了一大批 free()/插链（帧 19562–19569），紧接着一个 512 KB 级的 malloc 请求踩进 own-bin → 死循环**。

**(6) 请求尺寸对得上**：`a1 = nb = 0x80010`。malloc 的桶号 dispatch（`0x1020E0`–`0x10214C`）：

```
v1 = nb >> 9
v1 >= 1365 ?  …  : (v1 >= 341 ? t2 = (nb>>15)+119      ; 0x102130/0x102140
                              : t2 = 126 )              ; 0x102144/0x102148
```
`nb=0x80010` ⇒ `v1 = 0x400 = 1024`，`1024 < 1365`、`1024 >= 341` ⇒ **`t2 = (0x80010>>15)+119 = 2+119 = 121`**… 等等，这只覆盖 `[341,1365)`；`1024` 落在 `[341,1365)` ⇒ 走 `0x102130` 的"else"分支到 `0x102144`，`at = (v1<1365) = 1` ⇒ **不跳**，落到 `0x102148 addiu $t2,$zero,126` ⇒ **idx = 126** ✓。
（对照：`nb=0x10020`（64 KB 级，解压器 L1 场景）⇒ `v1=0x80=128 < 341` 且 `>= 85` ⇒ `t2 = (nb>>15)+119 = 121` ⇒ **桶 121**。这解释了为什么同一张盘在 64 KB 请求上"没事"、在这次 512 KB 请求上"必死"。）

**(7) 精确执行环（本机 d1，见 §4.2）**：`SPINFIX_F4.iso` + 毒化 own-bin 桶，`exectrace_tail.txt` 的最后 64 条**全部**是 `00102180 / 001021A0 / 001021D0` 的三块循环；`pcsample.txt` 在 frame 48/52/56 分别采样到 `0x1021D0 / 0x1021A0 / 0x1021A0`。

### 2.4 判定

**① 又一次 malloc 自旋（同一根因的残余），发生在 F4 未覆盖的 own-bin 回边 `0x1021D4`。**

* **不是 ②**：本次 `Trap`/`Unrecognized op`/`ReportErrorAsync`/`Pausing(自动)` 全 0（`out\analyze_*` 与 §4.1）；`badvaddr=0`、`cause=0x20`；没有 `0x7E7E7E7E` 未对齐跳飞。OOMFIX 要治的"NULL 缓冲→写低端→Trap"链**没有出现**。
* **不是 ③**：如果卡在等待资源/输入/回放，PC 采样不会在 300+ 个采样点上**只**落在 3 个相邻块上；而且被监视窗口的写在 19569 之后**完全停止**（纯读死循环的自然结果）。
* **是的 ①**：`pc/v0/a0/a1/a2/a3/t2` 六个寄存器 + 桶 126 的坏值，把循环钉在 `0x10216C→0x102180→0x1021D0→0x1021D4` 这条**自己桶**快路径上；F4 的站点（`0x102588`）在这条路径上**根本不会被执行**（0x1021D4 与 0x102588 是两条不同的回边）。

### 2.5 桶数组与堆账目（6 份 dump 的同一口径审计，`tools\heap_audit.py` → `out\heap_audit_new.json`）

结构按 `REPORT_HEAP_EXHAUSTION.md` 的口径，本工具**先自证结构**：`mstate_0x55B7A0`、`top` 字段 `0x55B7A8`、常量 `0x55B7AC = 0x0055B798`（6 份全部相符）、桶 i 伪 chunk = `0x55B798+8i`、chunk 头在 `+8`（size 掩码 `0x1FFFFFFE`）、fd/bk 在 `+16/+20`。

| frame | top | top 剩余 | 链式遍历（base 0x65AEA0→top） | 桶：空/非空/**坏** | 链上"空闲块" | **最大单块空闲** | 桶 126 |
|---|---|---|---|---|---|---|---|
| 10470 | 0x1B8C520 | 0x40BB00 (4.24 MB) | 42,821 块，**恰好到顶**，0 个坏头 | 94/34/**2** | 139 块 / 50,000 B | 0x3F10 (16 KB) @0x1B37F80 | **0xF968B859** |
| 13112 | 0x1B8C520 | 0x40BB00 | 42,769 块，到顶，0 坏头 | 99/29/**2** | 134 块 / 48,048 B | 0x3F10 @0x1B37F80 | **同值** |
| 14025 | 0x1B8C520 | 0x40BB00 | 42,759 块，到顶，0 坏头 | 89/39/**2** | 149 块 / 48,832 B | 0x3F10 @0x1B37F80 | **同值** |
| 16893 | 0x1B94540 | 0x403AE0 (4.21 MB) | 42,809 块，到顶，0 坏头 | 88/40/**2** | 151 块 / 80,400 B | 0x4520 @0x1AAA080 | **同值** |
| 19095 | 0x1B94540 | 0x403AE0 | 42,857 块，到顶，0 坏头 | 93/35/**2** | 143 块 / 52,960 B | 0x3F10 @0x1B37F80 | **同值** |
| **19671** | **0x1C26750** | **0x3718D0 (3.61 MB)** | 40,982 块，到顶，0 坏头 | 49/79/**2** | **716 块 / 926,128 B** | **0x593E0 (365 KB) @0x00EB7600** | **同值** |

* 「坏 2」中的一个**永远是桶 0**（`bin0.fd == top` 是设计别名，`idx=0` 分配器永不使用）——与上一轮同口径；**真正被写坏的只有桶 126**。
* **桶 126 再次被写坏，而且是新值 `0xF968B859`**；前 5 份里这个值只出现在那两个槽位（RAM 全检索），第 6 份多出 4 处堆内出现（`0x952110/0xDBCC60/0x1495E90/0x1694520`）。
* **堆没有耗尽**：卡死时（19671）top 还剩 3.61 MB、另有 365 KB 的连续空闲块。本次请求 `0x80010`（512 KB）**本来可以从 top 切分满足**（`0x10262C` 的 top-split 路径完好）——卡住的是**搜索路径**，不是内存。

### 2.6 与「F4 修复前/后」的读数对照：同一根因的残余，不是新问题

| 时点/现场 | TLB Miss | Trap | 卡死站点 | 判定 |
|---|---|---|---|---|
| F4 前（`REPORT_SPINFIX` a1/a2，本机同配方） | 2 | **2,647,472** | `0x1024D0/0x102584`（binmap 回边）→ 解压器拿到 NULL → 写低端 → Trap | 老链 |
| F4 后（`REPORT_SPINFIX` b1/b5 = `SPINFIX_F4.iso`+S1） | 2（只有 2 条，没有第 3 条） | **0** | 无（F4 bail → top 切分 → 解压器 14 次全部成功） | 已修 |
| **本次真机**（`SPINFIX_F4.iso`） | 50（上限）+ 被截断的若干 | **0** | **`0x102180/0x1021D0/0x1021D4`（own-bin 回边）** | **同一根因的残余** |

三条证据说明"本次的坏桶 = 老病灶的延续"：
1. 毒化时刻在**很早就已发生**：139.3401 s 的第一批 TLB Miss 就是 `free()+插链` 在写一个"假 chunk"（地址全部是 `0xF968B859±0x8/0x10/0x14`），而桶 126 在 **frame 10470（14:54:21，第一次 F10）就已是 `0xF968B859`**；之后到 frame 19569 之间的 12,000 帧里，malloc 一直在绕开它（64 KB 请求落桶 121；binmap 扫描走到 126 时被 F4 拦下 4 次）。
2. F4 **在位且有效**：6 份 dump 的站点/cave 逐字在位；138–267 s 的四次 binmap 遭遇都只出现 2 条 miss（= 一轮 bail 的签名）。
3. 卡死链条与 `REPORT_USERDUMP_ANALYSIS.md` 的定案**同型**（"桶里有非 chunk 的指针 → 分配器把 TLB Miss 读回的 0 当成链接，永不返回"），只是这次命中的是**另一条回边**——正是 `REPORT_SPINFIX.md` §4.3 残余风险③写明的那个缺口（"`0x10216C`（请求自己的桶）与 `0x102200`（unsorted 桶）两条快路径没有校验"）。

---

## 3. B. 四张组合修复盘（`work\builds\GR_COMBFIX\`）

### 3.1 补丁清单与站点

| 补丁 | VA | ISO off | ELF off | 原字（反汇编） | 新字 | 语义/出口 |
|---|---|---|---|---|---|---|
| **OOMFIX**（GR_OOMFIX 原样） | `0x00539174` | `0x004CC9F4` | `0x04391F4` | `AE620004 sw $v0,4($s3)` | `08154012 j 0x00550048` | 解压器 malloc 返回 0 → cave 里 `s0=0` → 调用者失败分支（该资源被跳过） |
| **F4**（SPINFIX 原样；A/B/C 从基底继承，2400 由本工具打） | `0x00102588` | `0x00095E08` | `0x0002608` | `1459FFD1 bne $v0,$t9,-47` | `081068D7 j 0x0041A35C` | binmap 扫描回边：`t9 < v0 < 0x1FFFFFFE`；不合法 → `j 0x102590` |
| **F1**（SPINFIX 原样，逐字节相同） | `0x00101DC0` | `0x00095640` | `0x0001E40` | `00AA2823 subu $a1,$a1,$t2` | `08156DCC j 0x0055B730` | free() `next != top` 支：重算 P 并校验 `mstate < P < C`、`P%8==0`；不合法 → `j 0x101DE4` |
| **F1b**（本轮新写） | `0x00101D60` | `0x000955E0` | `0x0001DE0` | `00A42823 subu $a1,$a1,$a0` | `08177B31 j 0x005DECC4` | free() `next == top` 支的同族校验；合法 → `j 0x101D68`，不合法 → `j 0x101D78`（先撤销延迟槽的 `v1 += prev_foot`） |
| **F7**（本轮新写，**新病灶的最小修复**） | `0x001021D4` | `0x00095A54` | `0x0002254` | `1447FFEA bne $v0,$a3,-22` | `08177B31 j 0x005DECC4` | own-bin 回边：`a3 < v0 < a2(=0x1FFFFFFE)`；合法 → `j 0x102180`，不合法 → `j 0x1021E0`（既有的"换下一个桶"出口） |

**F7 为什么这一版就够（对应 §2.3 的链条）**：坏链头在第一次被读到时就已经是"未映射值"，F7 在**回边那一刻**做范围判断（`v0 > 桶哨兵 a3` 且 `v0 < size 掩码 a2`）：
* 第一轮：`0xF968B859` 立刻被判非法 → `0x1021E0`（t2++ → 既有的"本桶无可用块"续搜）⇒ **回边不再发生**；
* 万一坏值落在 `[0x1FFFFFFE, …)` 之类的窄带，下一轮 `v0` 被 TLB Miss 读成 0，`a3 < 0` 不成立 ⇒ **同样 bail**。
* 两个出口都是**既有路径**（`0x102180` = 原 `bne` 的回头路；`0x1021E0` = 原"桶走空"的落点），没有新语义；scratch 只用 `$at/$v1`，两处出口之后 `$v1` 都会被重写（`0x102180 ld $v1,8(v0)` / `0x1021F0 xor $v1,...`，指令级核过）。

**F1b 为什么不能照抄 SPINFIX §4.3 的"同一个 cave 体"**（这是本轮必须偏离原文的地方，给出指令级理由）：
1. **延迟槽**：站点 `0x101D60` 的延迟槽是 `0x101D64 daddu $v1,$v1,$a2`（`v1` = 合并后的 size），`j` 之前它就执行了 ⇒ 合法出口必须是 **`0x101D68`**（不是 `0x101D64`，否则 `v1` 会被加两次）。
2. **不合法出口必须先撤销**：bail 到 `0x101D78` 后，路径会走到 `0x101D94 sd $v1,8($a1)` —— 如果 `v1` 里带着那个**不可信的 prev_foot**，就会把垃圾尺寸写进 C 的 head（二次污染）。所以 cave 里必须 `dsubu $v1,$v1,$a2`（`a2` 此刻仍是 64 位 prev_foot，且 bail 路径上 `a2` 会被 `0x101D7C` 重写，撤销顺序天然安全）。
3. **a0 在这一支里不是 mstate**：`0x101D48 andi $a0,$t2,1` 已经把 `a0` 改写成 PREV_INUSE 标志，所以 cave 不能用 `a0` 当下界；改用 `0x101D20` 设好的 `t0 = mstate - 8`（`$t0` 从 `0x101D20` 到站点 `0x101D60` 之间**没有任何写入**，逐条核过）→ `addiu $v0,$t0,8` 还原 mstate，从而仍是**精确**的 `mstate < P`。

### 3.2 cave 落点（以及一条硬约束：**已经不存在"真正的死区"**）

| cave | VA | 长度 | 归属 | 为什么可用 |
|---|---|---|---|---|
| `CAVE_F1` | `0x0055B730` | 68 B | SPINFIX 原样 | 零区 0x55B730..0x55B780 的前 68 B；⚠ 邻居是数据对象填充（`s_bCDMode/act_align/act_data/main_arena`），**不是死代码**（老问题，见 §4.4 残余风险） |
| `CAVE_F1b` | `0x005DECC4` | 56 B | 本轮新写 | 零区 0x5DECC4..0x5DED00（60 B）的前 56 B；`__data_end`→`__bss_start` 的段尾填充（SPINFIX F2 的原落点，当时已跑过 6000 帧冒烟） |
| `CAVE_F7` | `0x005DECC4` | 36 B | 本轮新写 | 同上（C/2400 盘里 F1b 不在场，这 60 B 全给它） |
| `CAVE_F4` | `0x0041A35C` | 36 B | SPINFIX 原样 | iomanX 死代码区，36 B 零区**正好**用满 |
| `CAVE_OOMFIX` | `0x00550048` | 44 B | GR_OOMFIX 原样 | VU0 微码之前的 56 B 零区 |

**硬约束（本轮的新事实，工具 `tools\combfix_cave.py` / `combfix_cave2.py` → `out\cave_candidates*.json`）**：
* 全 ELF 装载段（VA `0x00100000`..`0x005DED00`）里，零 run ≥ 32 B 共 **132** 个、≥ 48 B 共 **101** 个、≥ 72 B 共 **69** 个；
* 用「ELF 全零 **且** 8 份运行时快照（6 份新 dump + 2 份旧 dump）逐字节全零」筛（这就是 SPINFIX/OOMFIX 当年的 cave 判据），**排除已用掉的 4 处之后，≥32 B 的候选是 0 个**；把"大 run 里被运行时写过"的部分也按字节屏蔽、只找**干净子段**（≥40 B）——**同样是 0 个**；
* 结论：**除了已有的 4 处（80 B / 60 B / 36 B / 56 B），ELF 里没有别的"从未被写过"的零区**。这是本轮 cave 选址的硬约束，也是 F1b 与 F7 共用 `0x5DECC4` 的原因。
* 已避开的区域（`meta.json` 的 `ref_regions` 逐字节断言）：DBCS cave 全区 `0x416E00..0x417800`、4 个闸门 `0x416EE8/0x417160/0x41751C/0x5656A4`、ZH cave block B `0x565600..0x565B00`、分配器镜像 `0x101C00..0x102700`（只放行本盘声明的站点字）、解压器 `0x539110..0x539310`（只放行 OOMFIX 站点）、调用者 `0x51BE10..0x51C000`、RSFont `0x21AC00..0x21AE00`。

### 3.3 四张盘

| 盘 | 基底 | 补丁 | ISO sha256 | 尺寸 | **CRC(PCSX2)** | ELF sha256 | 存档名（用户改名用） | 自证 |
|---|---|---|---|---|---|---|---|---|
| **`COMBFIX_A.iso`** | `SPINFIX_F4.iso` | F4(继承) + OOMFIX | `e12f2770d041f5ac02079c37fcb7137a49310538adb79dba026224cbb4edccc2` | 1,648,164,864 | **C36C1073** | `2a4c8c01…c1ee8` | `SLUS-20613 (C36C1073).01.p2s` | 8/8 OK |
| **`COMBFIX_B.iso`** | `SPINFIX_F4.iso` | F4(继承) + OOMFIX + **F1 + F1b** | `3959498be967447b0404745885a0fc7f616c85d97dfa7833979b563531c16b41` | 同 | **3AA01EA7** | `ae8d6900…7850` | `SLUS-20613 (3AA01EA7).01.p2s` | 8/8 OK |
| **`COMBFIX_C.iso`** | `SPINFIX_F4.iso` | F4(继承) + OOMFIX + **F7** | `5c4c9f70ee3d15dc406354c599dfe2bb1b80a0d16c4a1c2b73b2d036f4b31f4d` | 同 | **CF9B8C97** | `75c74f94…48a4` | `SLUS-20613 (CF9B8C97).01.p2s` | 8/8 OK |
| **`COMBFIX_2400.iso`** | `GR_REBUILD2400.iso`（产品线） | **F4 + OOMFIX + F7**（与 C 同集合，**不含 F1/F1b**） | `d8007873957f81ab44f37cf4c773ac5bdf0d3d66fd5f975b48f69abea21b2ab5` | 同 | **CFDB8C97** | `6fce4f45…8e73a` | `SLUS-20613 (CFDB8C97).01.p2s` | 8/8 OK |

* 差异统计（只算非零差异字节）：A = **10 run / 29 B**、B = **39 run / 115 B**、C = **18 run / 53 B**、2400 = **25 run / 78 B**，**全部落在声明的站点/ cave 窗口内**。
* ★ **2400 盘中途重出过一次**（如实记录）：第一版按任务书字面写成 `F4+OOMFIX+F1+F7`（sha256 `18febf47…`，CRC `2F8F8151`，diff 40 run/122 B），6000 帧冒烟出现与 `COMBFIX_B` 相同的 **6 帧**差异（`runs\smoke_COMBFIX_2400`，该 run 目录保留作对照；旧 ISO 已被重出覆盖，只剩这份 run 作证）。定案后**去掉 F1/F1b 重出**（理由见 §0），现行 2400 盘 = 上表 sha256/CRC，逐帧 **0 差异**（`runs\smoke_COMBFIX_2400b`）。
* **8 项自证**（每盘 `meta.json` 内）：`size_unchanged` / `diff_only_in_declared_windows` / `every_window_touched` / `readback_all_ok` / `gates_untouched_4` / `dbcs_zh_other_caves_untouched` / `elf_header_untouched` / `elf_lba_size_unchanged` —— **4 张盘全部 True**；4 个闸门回读 `2CA900BA / 2D0900BA / 2D4B00BA / 2D6C00BA`。
* `meta.json` 每盘都含：基底 sha256/ELF sha256/LBA、逐站点 VA/ISO/ELF/原字/新字/反汇编/出口/延迟槽说明、每个 cave 的全部字+反汇编+落点理由、`ref_regions` 逐区结果、`diff_runs` 全表、产物 sha256/尺寸/ELF sha256/**CRC**/存档名、`inherited_patches`（A/B/C 的 F4 来源于基底，逐字断言在位）。
* 出盘命令（逐字，在仓库根）：

```powershell
python work\builds\GR_COMBFIX\tools\combfix_apply.py --flavor A    --out work\builds\GR_COMBFIX\COMBFIX_A.iso
python work\builds\GR_COMBFIX\tools\combfix_apply.py --flavor B    --out work\builds\GR_COMBFIX\COMBFIX_B.iso
python work\builds\GR_COMBFIX\tools\combfix_apply.py --flavor C    --out work\builds\GR_COMBFIX\COMBFIX_C.iso
python work\builds\GR_COMBFIX\tools\combfix_apply.py --flavor 2400 --out work\builds\GR_COMBFIX\COMBFIX_2400.iso
```

### 3.4 ⚠ 只改 ISO 在读旧存档时不生效（沿用）；**以及本轮踩到的第二个坑**

* 沿用 `REPORT_OOMFIX.md` §5.1 / `REPORT_SPINFIX.md` §3.4：`.p2s` 里 `eeMemory.bin` 是整块 32 MB 主存，读档后 BIOS 不再从光盘装载 ELF ⇒ **补丁必须同时打进存档**。
* **新坑（本轮实测）**：`spinfix_state_fix.py` 只读 meta 的 `sites` / `caves`；A/B/C 的 **F4 写在 `inherited_patches`** 里 ⇒ 第一次生成的存档**少了 F4**。证据：首跑 `v2_C_S1b`（`COMBFIX_C.iso` + 缺 F4 的存档）里 F7 生效后**倒在未受保护的 binmap 回边**——执行环是 `0x1024D0 → 0x102550 → 0x102584` 的三块循环（`runs\v2_C_S1b\exectrace_tail.txt`），正是"没有 F4"的样子。
* 修法：新工具 `tools\combfix_statefix.py` 把 `sites + caves + inherited_patches` 合成一份标准 spec（落在 `out\statepatch_COMBFIX_*.json`）再调用 `spinfix_state_fix.py`，并回读断言。**用户实机同理：盘与存档必须是同一份代码**。

---

## 4. C. 验证

* exe：`work\builds\GR_COMBFIX\emu\gsrunner\pcsx2-gsrunner.exe`（从 `GR_SPINFIX\emu` 整目录复制，sha256 与 `REPORT_SPINFIX` 记录一致）
* 输入：`work\builds\GR_SPINFIX\inputs\in_l1_f30.txt`（`30 l1 press`）；冒烟用 `tools\capture\nav_menu_only.txt`
* 独占：每次起跑前轮询 `pcsx2*`，命中只记录（本轮全程 1 个他人实例 pid 31760）
* ⚠ `-grwatch/-grmemwatch` 十进制、`-grhook` 十六进制（沿用）

### 4.1 现场矩阵一：SPINFIX 的「坏桶存档」S1（桶 126 = `0x6ED47823`）

| run | 盘 | 存档（补丁已同时打进） | 帧 | **Trap** | Unrecog | **TLB** | 解压器 `0x539110` | F4 cave `0x41A35C` | OOMFIX cave `0x550048` | F1 cave `0x55B730` | 结果 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `a1_base_S1` | `LAY_fix1_bytecount`（未修） | S1_bin126_user | 46（上限） | **70,266** | 53 | 2 | 2 | — | — | — | 老链：malloc NULL → 解压器写低端 → `Trap at 0x80000274` |
| `b1_F4_S1` | `SPINFIX_F4` | S1_F4 | 300 | **0** | 0 | 2 | **14** | **1** | — | — | ★ 复现 SPINFIX 结论 |
| `b2_A_S1` | `COMBFIX_A` | S1_A | 300 | **0** | 0 | 2 | 14 | 1 | **14** | — | ✓ A 盘无回归 |
| `b3_B_S1` | `COMBFIX_B` | S1_B | 300 | **0** | 0 | 2 | 14 | （未挂） | 14 | **501** | ✓ F1 cave 501 次全部走合法支（无一例非法） |
| `b4_C_S1` | `COMBFIX_C` | S1_C | 300 | **0** | 0 | 2 | 14 | （未挂） | 14 | — | ✓ C 盘无回归 |
| `b5_C_S3` | `COMBFIX_C` | S3_base（**健康**基底存档）+C | **600** | **0** | 0 | **0** | 14 | — | 14 | — | ✓ 健康现场 600 帧干净 |

* 三张盘的 TLB 都是**恰好 2 条**（`pc=0x1024cc addr=0x6ed4782b` / `pc=0x102584 addr=0x6ed47837`）——与用户原来的前两条**同址同 PC**，且**没有第 3 条**（不 spin）✓
* `a1` 的原始读数存 `runs\a1_base_S1\emulog_sample.txt`（head 120 + tail 60；原 100 MB 日志按纪律裁剪后删除）。

### 4.2 现场矩阵二 ★：**本轮新病灶的等价现场**（own-bin 毒化 + 低端读回 0）

**为什么要造这个现场**：本机 L1@30 场景的请求是 `nb=0x10020`（64 KB）⇒ 桶号 **121**，而用户真机这次是 `nb=0x80010`（512 KB）⇒ 桶号 **126**。要让"同一条指令链"在本机出现，就把**桶 121**（`0x55BB70/74`）也毒化成用户真机那个值 `0x6ED47823`；再把 `0x8..0xF`、`0x14..0x17` 清零以等价"低端页未映射 ⇒ 读回 0"（§2.3(4) 已证明这是真机成立、本机不成立的那个条件）。
存档（`tools\combfix_state.py` → `states\combfix_states.meta.json`）：

| 存档 | 内容 | sha256 |
|---|---|---|
| `S1b_bin121_bad.p2s` | S1 + 桶 121 = `0x6ED47823`（+8 B） | `1f3e4f50…25c1` |
| `S1b_bin121_0xA73D.p2s` | 同上，毒值换成存档自带的 `0xA73D37F0`（KSEG1 别名型） | `073f19be…55bf` |
| **`S1b_bin121_low0.p2s`** | 上面 + `0x8..0xF`/`0x14..0x17` = 0（+9 B 非零差异；合计 17 B） | `c295af47…d75e` |

跑法：`-grstate <S1b 变体（已按盘打补丁）>` + `-grinput in_l1_f30.txt`，60 帧，`-grpcsample 1 -grpcring 262144`：

| run | 盘 | 补丁 | frame 48/52/56 的 PC | `exectrace_tail.txt` 尾部 | TLB | 判定 |
|---|---|---|---|---|---|---|
| `o1_LAY_S1b` | `LAY_fix1_bytecount` | 无 | `0x1021D0 / 0x1021A0 / 0x1021A0` | **`0x102180/0x1021A0/0x1021D0` 纯三块循环**（44/42/42） | 2 | **死循环（未修）** |
| `o2_A_S1b` | `COMBFIX_A` | F4+OOMFIX | `0x1021A0×3` | **同一条三块循环** | 2 | **F4 覆盖不到** ★ |
| `o3_B_S1b` | `COMBFIX_B` | +F1+F1b | `0x1021D0 / 0x1021A0 / 0x1021A0` | **同一条三块循环** | 2 | F1/F1b 也不覆盖 |
| **`o4_C_S1b`** | **`COMBFIX_C`** | **+F7** | **`0x3E1050 / 0x42E070 / 0x42E488`** | 游戏逻辑块（`0x42Exxx` × 40+ 种，无循环） | 8 | **★ 死循环被截断，游戏继续** |
| （对照）`d1_F4_S1b` | `SPINFIX_F4` | F4 | `0x1021D0/0x1021A0/0x1021A0` | 同上三块循环；hooklog 撞 200,000 行上限，`0x102180` 命中 **198,488** 次 | 2 | 再次确认 F4 的空洞（`-grpcring`+`-grpcsample` 版） |

**`o4`（COMBFIX_C）的完整链路，逐条 hook 证据**（hooklog 2,052 行）：

```
hook pc=00102050 frame=44 … a1=00010020 a3=0129F33C v0=00000000        ; malloc(nb=0x10020)
hook pc=005DECC4 frame=44 … a0=0055B7A0 a1=00010020 a2=1FFFFFFE a3=0055BB60 v0=00000000   ; ★ F7 cave 进入（a3 = 桶121 伪 chunk = 0x55BB60 ✓）
hook pc=001021E0 frame=44 …                                            ; ★ F7 bail → 既有「换下一个桶」出口
TLB Miss, pc=0x1024cc addr=0x6ed4782b / 0x102584 addr=0x6ed47837        ; binmap 扫描撞上桶 126（S1 的坏值）
hook pc=0041A35C frame=44 …                                            ; ★ F4 cave 进入 → bail
hook pc=00539110 frame=44 … / hook pc=0010269C frame=44 …              ; 解压器继续 / malloc 正常返回
（全程 60 帧：F7 cave 3 次、F7 bail 3 次、F4 cave 1 次、malloc 返回 2,031 次、解压器 14 次、
  无 Trap / 无 Unrecognized op / 无 ReportErrorAsync / 无 recLUT trap）
```

⇒ **单变量可辨**：`o1`（未修）、`o2`（F4+OOMFIX）、`o3`（+F1+F1b）三张盘都死在同一条三块循环上，只有 `o4`（+F7）出来；`d1`/`o2` 精确复现了用户真机 `pc=0x102180, v0=0` 的状态。

### 4.3 6000 帧冷启动冒烟 + 逐帧 sha256 对照

跑法：`tools\combfix_smoke.ps1`（`-grmaxframes 6000 -grsnap 30 -grscanframes 2000`，输入 `tools\capture\nav_menu_only.txt`，冷启动），对照用 `oomfix_frames.py`，像素级用 `tools\pxdiff.py`。

| run | 盘 | 截图 | 帧区间 | TLB | Trap | Unrecog | 与基底逐帧 sha256 | 补丁存活（第 5970 帧 RAM 回读） |
|---|---|---|---|---|---|---|---|---|
| `smoke_COMBFIX_A` | `COMBFIX_A.iso` | **191**（去重 161） | 270..5970 | **0** | **0** | 0 | vs `SPINFIX_F4`：共同 191 / **相同 191 / 不同 0** ⇒ **逐像素 0 差异** | 22 字全部逐字相符 ✓ |
| `smoke_COMBFIX_B` | `COMBFIX_B.iso` | 191（去重 161） | 270..5970 | 0 | 0 | 0 | vs `SPINFIX_F4`：共同 191 / **相同 185 / 不同 6**（帧 **660/690/720/750/780/810**） | 55 字全部逐字相符 ✓ |
| **`smoke_COMBFIX_C`** | **`COMBFIX_C.iso`** | **191**（去重 161） | 270..5970 | **0** | **0** | 0 | vs `SPINFIX_F4`：共同 191 / **相同 191 / 不同 0** ⇒ **逐像素 0 差异** | **32 字全部逐字相符 ✓** |
| `smoke_SPINFIX_F4` | `SPINFIX_F4.iso`（A/B/C 的基底） | 191（去重 161） | 270..5970 | 0 | 0 | 0 | —（本轮同会话重跑） | — |
| **`smoke_COMBFIX_2400b`** | **`COMBFIX_2400.iso`**（重出后：F4+OOMFIX+F7） | **191** | 270..5970 | **0** | **0** | 0 | vs `GR_REBUILD2400`：**共同 191 / 相同 191 / 不同 0** ⇒ 逐像素 0 差异 | 32 字全部逐字相符 ✓ |
| `smoke_GR_REBUILD2400` | `GR_REBUILD2400.iso`（产品线基底） | 191（去重 161） | 270..5970 | 0 | 0 | 0 | —（本轮同会话重跑） | — |
| ~~`smoke_COMBFIX_2400`（旧版，含 F1）~~ | 旧 `COMBFIX_2400.iso`（F4+OOMFIX+F1+F7，CRC 2F8F8151） | 191 | 270..5970 | 0 | 0 | 0 | vs `GR_REBUILD2400`：相同 185 / **不同 6**（同样的 660..810） | 50 字逐字相符 ✓ |

* 六次跑全部 `=== run end, frames=6000 ===`（单次 102 s），**TLB 0 / Trap 0 / Unrecognized op 0 / Pausing 0**，截图 191 张（≥190 判据满足）。
* **6 帧差异的像素级统计**（`COMBFIX_B` vs `SPINFIX_F4`；`tools\pxdiff.py`，583×437）：

| 帧 | 差异像素 | 占比 | bbox | 最大通道差 |
|---|---|---|---|---|
| 660 | 27,975 | 10.98 % | (87,171)-(504,281) | 39 |
| 690 | 23,811 | 9.35 % | (87,156)-(489,289) | 39 |
| 720 | 686 | 0.27 % | (306,156)-(379,180) | 11 |
| 750 | 5,194 | 2.04 % | (109,171)-(438,250) | **120** |
| 780 | 4,965 | 1.95 % | (131,218)-(452,297) | **112** |
| 810 | 23,480 | 9.22 % | (100,156)-(488,297) | 26 |

* **落点分析（本轮把老问题向前推了一步）**：这三个 "含 F1 的盘"（`SPINFIX_F1F2`、`COMBFIX_B`、旧 `COMBFIX_2400`）出现的**都是同一批 6 帧**；而**只改 `0x005DECC4`** 的 `COMBFIX_C`（F7，36 B）与 `COMBFIX_2400b`（F7，36 B）都是 **0 差异**。`SPINFIX_F1F2` 在 `0x005DECC4` 放的是 **F2（44 B）**、`COMBFIX_B` 放的是 **F1b（56 B）**——两份内容完全不同却出现完全相同的 6 帧 ⇒ **致因不是 `0x005DECC4`，而是 `0x0055B730` 的 F1 cave**（"cave 落在活跃数据旁"的老问题**被定位到具体那一个 cave**）。
* 影响面：这 6 帧都在**开机引导/厂标阶段**（660–810，早于主菜单），不是游戏内画面；`COMBFIX_A`/`COMBFIX_C`/新 `COMBFIX_2400` **逐像素 0 差异**。
* 严格隔离（F1-only / F1b-only 两张诊断盘）**未做**：4 张盘额度已满，列入 §6 未达成项。
* 逐帧对照命令：`python work\builds\GR_OOMFIX\tools\oomfix_frames.py <runA> <runB> [--pixel]`；补丁存活：`spinfix_ramcheck.py --ram <run>\win_f00005970_eeram.bin --meta <disc>.meta.json`（A/B/C 还需带上 `inherited_patches` 里的 F4，本轮用 `out\statepatch_*.json` 一并核过）。

### 4.4 静态论证：新字反汇编回读 + 为什么能截断链

**F7 cave `0x005DECC4`（36 B，9 字）** —— 从产物再反汇编回读：

```
0x005DECC4  00E2082B  sltu $at,$a3,$v0     ; at = (v0 > 桶哨兵 a3)，严格：v0 == a3（桶走空）也判非法
0x005DECC8  0046182B  sltu $v1,$v0,$a2     ; v1 = (v0 < 0x1FFFFFFE)，a2 由 malloc 在 0x10217C 设为 size 掩码
0x005DECCC  00230824  and  $at,$at,$v1
0x005DECD0  10200003  beq  $at,$zero,+3 -> 0x005DECE0
0x005DECD4  00000000  nop
0x005DECD8  08040860  j    0x00102180      ; 合法 -> 回本桶扫描循环体（= 原 bne 的回头路）
0x005DECDC  00000000  nop
0x005DECE0  08040878  j    0x001021E0      ; bail -> 既有「换下一个桶 / 退到 binmap」出口
0x005DECE4  00000000  nop
```

**F1b cave `0x005DECC4`（56 B，14 字）**：

```
0x005DECC4  00A40823  subu  $at,$a1,$a0     ; at = P = C - (int32)prev_foot（原 0x101D60 搬进 cave）
0x005DECC8  25020008  addiu $v0,$t0,8       ; v0 = mstate（t0 = mstate-8，0x101D20 设定，站点前无写入）
0x005DECCC  0041102B  sltu  $v0,$v0,$at     ; mstate < P
0x005DECD0  0025682B  sltu  $t5,$at,$a1     ; P < C
0x005DECD4  004D1024  and   $v0,$v0,$t5
0x005DECD8  10400006  beq   $v0,$zero,+6 -> 0x005DECF4   ; 不合法 -> .bail
0x005DECDC  30220007  andi  $v0,$at,7       ; 延迟槽：P % 8 == 0 ?
0x005DECE0  14400004  bne   $v0,$zero,+4 -> 0x005DECF4   ; 未对齐 -> .bail
0x005DECE4  00000000  nop                   ; 延迟槽：不动 $a1（bail 路径 0x101D94 还要用 a1 = C）
0x005DECE8  00202821  addu  $a1,$at,$zero   ; a1 = P
0x005DECEC  0804075A  j     0x00101D68      ; 回原流程（0x101D64 已由本站点延迟槽执行）
0x005DECF0  00000000  nop
0x005DECF4  00A6182F  dsubu $v1,$v1,$a2     ; ★ 撤销延迟槽 0x101D64 加进来的 prev_foot
0x005DECF8  0804075E  j     0x00101D78      ; .bail：跳过前块合并（= 原 PREV_INUSE 出口，a1 仍为 C）
```

**F1 cave `0x0055B730`（68 B）与 F4 cave `0x0041A35C`（36 B）**：与 `REPORT_SPINFIX.md` §3.1/§4.3 给出的逐字相同（本轮工具只做回读断言，没有改动）。

**OOMFIX cave `0x00550048`（44 B）**：与 `REPORT_OOMFIX.md` §2.2 逐字相同（含 `daddu $s0,$zero,$zero`）。

**残余风险（逐条，含"老问题是否解决"的明确回答）**

| 项 | 残余风险 | 后果 | 备注/建议 |
|---|---|---|---|
| **F1/F1F2 cave 落点邻接活跃数据（老问题）** | **已定位到具体 cave，但仍未解决**：本轮把 6 帧差异归因到 **F1 的 `0x0055B730`**（理由：`SPINFIX_F1F2` 在该区无 F1b、`COMBFIX_B` 有 F1b，两份在 `0x005DECC4` 的内容完全不同却出现**同一批** 660..810 六帧；而只改 `0x005DECC4` 的 `COMBFIX_C`/`COMBFIX_2400` 逐帧 0 差异） | 6 帧（引导阶段）像素差异，最大通道差 120 | **推荐盘（A/C/2400）已不含 F1 ⇒ 0 差异**；`COMBFIX_B` 只作诊断/研究用 |
| **F1b/F7 的 cave 也不是"真死区"** | 用 `0x005DECC4`（段尾填充，紧邻 BSS 的 `_overlay_group_addresses`），它是 SPINFIX F2 当年的落点 | 与 F1 同源的"非死区"风险；**本轮实测该区（F7 36 B）在 6000 帧里 0 差异、且第 5970 帧逐字存活** | §3.2 已证明 **ELF 里不存在别的 ≥40 B 的"从未被写过"零区**，这是硬约束 |
| **F7 只护住 own-bin 回边** | `0x102200`（unsorted 桶）那条快路径仍未校验（SPINFIX §4.3 残余风险③的另一半） | 若坏指针出现在 unsorted 桶，仍可能自旋 | 下一轮可把同一 cave 挂到 `0x102200` 的回边（需要第三个 36 B 洞——按 §3.2 目前**没有**，需先找死代码段） |
| **F7 的上界是 512 MB**（用 `a2 = 0x1FFFFFFE`，与 F4 同） | 坏值落在 `[32MB,512MB)` 时多跑一轮 | 多 2 行 TLB Miss 日志 | 第二轮 `v0` 归 0 会被 `a3 < v0` 拦下 ⇒ 仍不自旋 |
| **F1b 依赖 `t0 = mstate-8`** | 站点前无写入已逐条核过；换基底必须重核 | 误判概率极低 | `meta.json` 已锁基底 sha256 + ELF sha256 |
| **F1b 与 F7 共用 `0x005DECC4`** | 两者**不同盘**出现（B 里有 F1b，C/2400 里有 F7），不共存 | — | `meta.json` 的 `ref_regions` 会断言"该区除声明字外与基底相同" |
| **OOMFIX 的 s0=0** | 失败资源被跳过（泄漏一块 + 少一个资源） | 该资源不加载 | 沿用 `REPORT_OOMFIX.md` 结论；本轮 A/B/C/2400 里 OOMFIX 成功路径命中 14 次、失败路径 0 次（现场没有 OOM） |
| **归因（是否汉化造成）** | **仍未判定** | — | 沿用前两轮；本轮没有做"同场景汉化 vs 英文"的定量对照 |

---

## 5. D. 给用户的实机测试步骤

1. **先测哪张**：**`work\builds\GR_COMBFIX\COMBFIX_C.iso`**（= `SPINFIX_F4` + OOMFIX + **F7**）。
   * 产品线（2400 基底）用 **`COMBFIX_2400.iso`**（同一套补丁；**不含 F1/F1b**，逐帧 0 差异）；
   * `COMBFIX_A.iso` = 你手上那张 + OOMFIX（**治不了这次的新卡死**，只作对照）；
   * `COMBFIX_B.iso` = A + F1/F1b（**也治不了这次的新卡死**，而且 6000 帧里有 6 帧像素差异——它的价值是"试着防止再写出坏桶"，只作研究）。
2. ⚠ **存档必须与盘一致**：
   | 盘 | CRC | 你要把即时存档改成 |
   |---|---|---|
   | `COMBFIX_C.iso` | `CF9B8C97` | `SLUS-20613 (CF9B8C97).01.p2s` |
   | `COMBFIX_2400.iso` | `CFDB8C97` | `SLUS-20613 (CFDB8C97).01.p2s` |
   | `COMBFIX_A.iso` | `C36C1073` | `SLUS-20613 (C36C1073).01.p2s` |
   | `COMBFIX_B.iso` | `3AA01EA7` | `SLUS-20613 (3AA01EA7).01.p2s` |
   放进 `%LOCALAPPDATA%\PCSX2\sstates\` 再读档；**否则读档读不到**。
   ★ **更稳的办法**：**不要用旧的即时存档**——用**记忆卡存档**或**从关卡开头进**，这样盘上的补丁一定生效（旧的 `.p2s` 会把 32 MB 主存整块恢复，盘上的补丁会被存档里的旧代码盖掉）。
   ★ 注意：**如果继续用你原来那份"已经中毒"的即时存档**（桶 126 = `0xF968B859`），`COMBFIX_C`/`COMBFIX_2400` 也能救（F7 会在 own-bin 回边把坏链头拦下）；但 `COMBFIX_A`/`B` **救不了**（它们没有 F7）。
3. **怎么走到卡死场景**：读档/从关卡开头 → 打到**完成全部目标** → 出现「任务完成」提示后**继续按确认/等它切结算**（就是原来卡住的那一步）。
4. **判据**：
   * **能进结算/继续玩** = 修好了（本机：未修/F4/A/B 都是 60 帧内死在 `0x102180→0x1021A0→0x1021D0` 三块循环；`COMBFIX_C` 里同一现场 F7 cave 命中 3 次后 malloc 正常返回 2,031 次、跑到 300/600 帧无 Trap）；
   * 日志里**可能仍会出现 1–2 行** `TLB Miss … addr=0x…`（`0x6ED4782B/0x6ED47837`、`0xF968B861/0xF968B86D` 之类）——**这是正常的**（F7/F4 的检查在那两条读之后），关键是**不会再有第 3 行、不会无限重复**；
   * 如果还是卡：把 `emulog.txt` + 当时按的键 + 盘 sha256 发回来。**建议同时按 F10**（HookWatch 会落一份 32 MB RAM 现场）。
5. **下一次取证（想让日志别再被截断）**：`vtlb.cpp` 的 TLB Miss 打印上限写死 50 行（源码级常量），本机无法从配置改；可行的是把 `watch` 收窄到 `0x0055B7A0-0x0055C000`（`REPORT_SPINFIX.md` §5 的 `hook_config_next.ini`）并把 ring 提到 2 M 条，这样"哪些桶在被写"看得更清。

---

## 6. 未达成项（如实列）

1. **无法用用户真机的同一现场复现**：用户只给了 6 份 `ee_ram.bin` + `regs.txt`（没有 GS/内核/存档结构），不能直接当 `.p2s` 用。本机的复现是**等价现场**（毒化 own-bin 的桶 121 + 低端清零以等价"TLB Miss 读回 0"），不是同一份存档。
2. **`0x8/0x14` 的 TLB Miss 无法在用户那份日志里直接看到**（第 50 行上限在 267.4 s 就打满了）。本轮是用**寄存器状态反推**证明的（§2.3(4)：若那两处能读到 RAM，`v0` 不可能是 0 且 PC 不可能停在 `0x102180`）。要直接看到，需要在卡死瞬间落盘（用户下一次按 F10 时，`-grwatch` 已经把 `0x0055B7A0-0x0055C000` 看住了，但 TLB 打印上限改不了）。
3. **F7 只覆盖 own-bin 回边**：`0x102200`（unsorted）路径仍未校验；要补需要第三个 36 B 洞，而 §3.2 的扫描表明**当前没有**（必须先找到新的死代码段）。
4. **F1/F1F2 的 cave 落点没换**（老问题仍在）：`0x0055B730` 依旧是"非死区"。本轮**没有**做 F1-only / F1b-only 的隔离盘（4 张盘额度已满），也**没有**做"把 F1/F1b 的 cave 挪到死代码段"的实验（没有可用洞）。
5. **`COMBFIX_2400` 只做了 6000 帧冒烟与逐帧对照**，没有做"2400 现场 + 坏桶存档"的同现场验证（2400 的存档来自另一条线的 CRC，用户手上的存档是 LAY 线 `7A761FCA`）。
6. **F1-only / F1b-only 的严格隔离盘没做**（要两张诊断盘，4 张额度已满）：本轮只到"6 帧差异**只**在含 F1（`0x0055B730`）的盘上出现、只改 `0x005DECC4` 的盘 0 差异"这一步；要 100% 闭环还需 `SPINFIX_F4+F1`（不含 F1b）与 `SPINFIX_F4+F1b`（不含 F1）两张各跑 6000 帧。**给出下一轮的最省做法**：在 `combfix_apply.py` 里加一个 `flavor=D`（`use=['OOMFIX','F1']`）跑一次冒烟即可判定 —— 若 D 也出 6 帧，则致因是 F1 的 cave 无疑。
7. **归因（是否汉化造成）仍未判定**：没有做"同场景汉化 vs 英文"的定量对照。
8. **用户真机 "512 KB 请求" 的触发点没有定位**：只知道它在任务完成时发生（`nb=0x80010`、`ra=0x10270C`，即调用者是分配器内部的包装），没有定位到"哪个资源/哪段代码请求 512 KB"。

---

## 7. 产物清单 + 复跑命令

| 路径 | 内容 |
|---|---|
| `COMBFIX_A.iso` / `.meta.json` | F4 + OOMFIX（CRC C36C1073） |
| `COMBFIX_B.iso` / `.meta.json` | + F1 + F1b（CRC 3AA01EA7） |
| **`COMBFIX_C.iso`** / `.meta.json` | **+ F7（本轮首推，CRC CF9B8C97）** |
| `COMBFIX_2400.iso` / `.meta.json` | 产品线 **F4+OOMFIX+F7**（CRC **CFDB8C97**；旧版含 F1 的 2400 盘已被覆盖，只有 `runs\smoke_COMBFIX_2400` 留作对照） |
| `states\S1_*.p2s` / `S3_C.p2s` / `S1b_*.p2s` / `S1_F4.p2s` | 11 个存档变体（坏桶 126 / own-bin 毒化 / 健康 + 各盘补丁） |
| `states\combfix_states.meta.json` | S1b 变体的注入点回读与低端 RAM 记录 |
| `tools\combfix_apply.py` | 出盘工具（基底指纹 + 站点断言 + cave 零区断言 + 回读反汇编 + 8 项自证 + CRC/存档名 + meta） |
| `tools\combfix_cave.py` / `combfix_cave2.py` | cave 审计（ELF 零 run × 8 份运行时快照 × j/jal 目标 × 字面量 × 禁碰区；"干净子段"扫描） |
| `tools\combfix_state.py` | 造 own-bin 毒化存档（含 `low0` 变体） |
| `tools\combfix_statefix.py` | ★ 把 `sites+caves+inherited_patches` 合成 spec 再打存档（修 3.4 的坑） |
| `tools\combfix_run.ps1` / `combfix_batch.ps1` / `combfix_smoke.ps1` | 单跑 / 现场矩阵 / 6 盘冒烟（都带独占检查、只记录不杀） |
| `tools\combfix_analyze.py` / `ring_tail.py` / `probe_ram.py` / `heap_audit.py` / `dis_ram.py` | 日志读数 / ring 尾部模式 / dump 探针 / 堆审计 / 现场 RAM 反汇编 |
| `runs\a1_*`,`b1..b5_*`,`o1..o4_*`,`d1/d2_*`,`v1/v2_*`,`smoke_*` | 16 个现场（每个有 `cmdline.txt`；`OTHERS_RUNNING.txt` 记录他人实例） |
| `out\*.json` / `out\*.txt` | 上述全部数字的原始输出（`probe_ram` / `heap_audit_new` / `ring_tail` / `cave_candidates*` / `cave_clean_subruns` / `analyze_*` / `statepatch_*` / `build_all.log`） |

复跑（在仓库根；`$py` = `C:\Users\84363\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe`）：

```powershell
# 出盘（4 张，逐字节自证）
& $py work\builds\GR_COMBFIX\tools\combfix_apply.py --flavor C --out work\builds\GR_COMBFIX\COMBFIX_C.iso
# 造 own-bin 毒化存档 + 把补丁（含继承的 F4）打进存档
& $py work\builds\GR_COMBFIX\tools\combfix_state.py
& $py work\builds\GR_COMBFIX\tools\combfix_statefix.py --state work\builds\GR_COMBFIX\states\S1b_bin121_low0.p2s `
      --meta work\builds\GR_COMBFIX\COMBFIX_C.meta.json --iso work\builds\GR_COMBFIX\COMBFIX_C.iso `
      --out work\builds\GR_COMBFIX\states\S1b_low0_C.p2s
# 现场矩阵（S1 坏桶 + own-bin 毒化）
powershell -NoProfile -ExecutionPolicy Bypass -File work\builds\GR_COMBFIX\tools\combfix_batch.ps1
# 6000 帧冒烟（4 盘 + 2 基底）
powershell -NoProfile -ExecutionPolicy Bypass -File work\builds\GR_COMBFIX\tools\combfix_smoke.ps1
# 读数 / 对照 / 补丁存活
& $py work\builds\GR_COMBFIX\tools\combfix_analyze.py work\builds\GR_COMBFIX\runs\o4_C_S1b
& $py work\builds\GR_OOMFIX\tools\oomfix_frames.py work\builds\GR_COMBFIX\runs\smoke_COMBFIX_C work\builds\GR_COMBFIX\runs\smoke_SPINFIX_F4
& $py work\builds\GR_SPINFIX\tools\spinfix_ramcheck.py --ram work\builds\GR_COMBFIX\runs\smoke_COMBFIX_C\win_f00005970_eeram.bin --meta work\builds\GR_COMBFIX\COMBFIX_C.meta.json
```

---

## 8. 磁盘（如实）

| 时点 | C 盘可用 |
|---|---|
| 开工前 | 11.5 GB |
| 4 张盘写完后 | 4.9 GB |
| 冒烟开跑前 | 4.73 GB |
| **清理本轮中间物后** | **4.10 GB** |
| 结束时 | **3.01 GB**（中间重出过一版 2400 盘，两份 2400b/2400 冒烟 run 也占了一些） |

清理明细（**只删本轮 `work\builds\GR_COMBFIX\**` 内的可重跑中间物**，回收 1,183 MB）：needle 机制的 32 MB `*_eeram.bin` 与 2 MB `*_iopram.bin`（38 个）、每个 run 的 `mc\` 记忆卡副本；`a1_base_S1` 的 100 MB Trap 日志裁成 `emulog_sample.txt`（9.8 KB）后删原文件。**用户给的 dump / 报告 / 脚本 / 既有盘一个字节都没动。**

**终值**（`Get-PSDrive C`）：可用 **3.01 GB**；本轮目录 `work\builds\GR_COMBFIX\` = 4 张盘 6.59 GB + 存档 `states\` 0.13 GB + `runs\` 约 0.75 GB + `emu\` 0.2 GB；**未再清理**（剩余量够复查与重跑，用户给的素材一字未动）。
