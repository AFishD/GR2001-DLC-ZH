# REPORT_F7B —— 用户实机「发射火箭弹 / 按 L1」报错的定性 + 未加固回边 `0x102200` 的收口（F7b）+ 新成品 **GR_ZH127**

> 轮次：2026-10-18 F7B 轮（接在「脚本归位轮」之后）
> 成品：`work\builds\GR_RELEASE\GR_ZH127.iso`
> sha256 `7d4e32972a8616622b415bbbdf654ec5d2e09c2bba7adce40e9c66d99736936d` · Game CRC **`EF4F55D7`**
> 候选盘（本次现场全部在它上面跑）：`work\builds\GR_F7B\F7B_prod_full.iso`（逐字节 == 成品）

---

## 0. 结论速览

| 问题 | 答案 |
|---|---|
| 用户这次崩在哪条回边？ | **分配器 unsorted 桶快路径**：`0x1021E0` 读链头 fd → `0x102208` 无条件解引用。这正是旧文档 §「残余」里登记的那条（`0x102200` 一带） |
| 指令级证据 | 日志 `TLB Miss, pc=0x102200 addr=0x17dd8d3e [load]`（块首 0x102200 就在这条路径上），随后 `pc=0x102220 addr=0x17dd8d36 [store]`、`pc=0x1022c4 addr=0x17dd8d46/0x17dd8d4a [store]`；坏指针 **`0x17DD8D36`**（由 +0/+8/+0x10/+0x14 四个被访问地址反解出来）。用户日志（frame 13795）与本机复现（n1 运行）**同址同 PC** |
| 是不是 `0x102200`？ | **是。** 而且 **F4/F7 都挡不住它** —— 见 §A.4（这是本轮最重要的新事实） |
| 补丁 | **F7b**：站点 `0x00102208`（`ld $v1,8($v0)` → `j 0x00570BB0`），cave `0x00570BB0`（40 B） |
| cave 从哪来？ | 旧结论「ELF 里已无 ≥32 B 干净零区」是**判据太窄**：改用「ELF 全零 + **与 ELF 逐字节相同**的 10 份运行期快照 + `.symtab` 无符号覆盖 + 无指针/无跳转/无 `lui+addiu` 构造」后，在 **`0x570B90..0x570C00`（112 B 对齐填充）** 找到落点（该 ELF 是 **debug build，38,722 个符号**，符号空隙是精确的） |
| 验证 | 新现场：未修必死（TLB 29 + 卡在 `0x80000180` 异常向量，0 截图）/ 加 F7b 活到 600 帧（**TLB 0**、cave 命中 **162,744** 次、11 截图）；6000 帧冒烟 191 截图 TLB 0 Trap 0；与 `GR_ZH126` **逐帧 191/191 相同**；第 5970 帧 RAM 里补丁逐字节存活 |
| 复现 | **从英文原盘端到端逐字节成功**：ENG ⊕ K2 ⇒ 基底 `d7f83d7e…` ⇒ 四件套 ⇒ `7d4e3297…` == 成品 |

---

## A. 用户这次是「哪一条回边」的定性

### A.1 现场素材（只读）

| 素材 | 路径 | 说明 |
|---|---|---|
| 用户日志（本次运行） | `work\builds\GR_HOOKEMU_QT2\qt\logs\emulog.txt` | 用户 PCSX2 仍在运行、文件被独占且**已被下一次运行截断** ⇒ 关键行在事发当刻已抄录，另存副本见下 |
| 日志副本 | `work\builds\GR_F7B\out\userlog_20261018\emulog_run2_20261018_2045.txt` | 20:48 抓取的第二次运行日志（288 KB）；本次崩溃的关键行在**事发当刻**的 444 KB 版本里（原文逐条抄在 §A.2） |
| 崩溃现场（冻结） | `work\builds\GR_F7B\out\userlog_20261018\hook_13795_{exception_00000034,fatal_jump_0CAC6800}\` | 两个 dump 目录的 `meta.txt / regs.txt / ring.txt / ee_ram.bin` 已整份复制冻结（哈希与现场一致，见 §A.5） |

> ⚠ 纪律：`work\builds\GR_HOOKEMU_QT2\**` 全程**只读**（复制出来才算证据）；用户模拟器实例（pid 49364）全程**只记录不干涉**。

### A.2 关键行原文（frame 13795，t≈264 s）

```
[  264.2115] TLB Miss, pc=0x1024e8 addr=0x17dd8d36 [store]
[  264.2131] TLB Miss, pc=0x102220 addr=0x17dd8d36 [store]
[  264.2132] TLB Miss, pc=0x102220 addr=0x17dd8d36 [store]
[  264.2136] TLB Miss, pc=0x51c028 addr=0x7e7e7e7e [store]
[  264.2137] TLB Miss, pc=0x51c028 addr=0x7e7e7e7e [load]
[  264.2138] TLB Miss, pc=0x102220 addr=0x17dd8d36 [store]      ← ×~10（264.2131..264.2177）
[  264.2161] TLB Miss, pc=0x54b9a0 addr=0x7e7e7f62 [load]
[  264.2164] TLB Miss, pc=0x53f0c0 addr=0x4 [load]
[  264.2174] TLB Miss, pc=0x541700 addr=0xc [load]
[  264.2180] TLB Miss, pc=0x416f74 addr=0x54545500 [load]
[  264.2182] TLB Miss, pc=0x417000 addr=0x44 [load]
[  264.2184] TLB Miss, pc=0x416fc8 addr=0x38 [load]
[  264.2198] Trap exception at 0x00000000
[  264.2198] HookWatch: EE EXCEPTION code=00000034 (ExcCode=13) pc=00000000 bd=0 -> fatal, taking a dump
[  264.3525] ReportErrorAsync: R5900 Exception: Jump to unmapped recLUT page (PC: 0x0cac6800)
[  264.3525] HookWatch: EE FATAL: jump to unmapped recLUT page pc=0CAC6800 (frame=13795) -> taking a dump
```

更早的同族证据（同一次会话，帧号连续区间）：

```
[  217.1091] TLB Miss, pc=0x101d10 addr=0x17dd8d3e [load]
[  217.1092] TLB Miss, pc=0x101de4 addr=0x17dd8d3e [load]
[  217.1093] TLB Miss, pc=0x101e08 addr=0x17dd8d46 [load]
[  217.1095] TLB Miss, pc=0x101e34 addr=0x17dd8d4a [load]
[  217.1095] TLB Miss, pc=0x101e34 addr=0x14 [store]
[  217.1095] TLB Miss, pc=0x101e34 addr=0x10 [store]
[  217.1097] TLB Miss, pc=0x101e6c addr=0x17dd8d36 [store]
[  229.8749] （同一组 8 条重复一次：pc=0x101d10/0x101dd8/0x101de4/0x101e08/0x101e34/0x101e6c）
```

**分类（三选一）⇒ ①+②的连锁**：先是**分配器内部对坏指针的读写**（①，`pc` 全部落在 `0x101Dxx`（free 族）、`0x1024E8`（binmap 扫描）、`0x102220`（unsorted 快路径）三个分配器代码块内），最后以 **Trap / 跳飞**（②，`Trap exception at 0x00000000` + `Jump to unmapped recLUT page (PC: 0x0cac6800)`）收场。不是「纯自旋」（本机等价现场里未修盘会停在 `0x102180/0x1021A0/0x1021D0` 三块循环，用户这次没有停在那里）。

### A.3 坏指针是怎么反解出来的

崩溃 dump 的寄存器（`hook_13795_fatal_jump_0CAC6800\meta.txt`）：

```
pc=0CAC6800 epc=00000000 badvaddr=00000000 status=70030C13 cause=00000034
r05=0000000054545454  r19=00000000545454D8  r31=0000000000000008  ra=00000008
```

`TLB Miss` 的 pc 是**基本块首**（PCSX2 `vtlb.cpp:537` 打印的是 `cpuRegs.pc`，而 QT2 现场里的 `recent_block_pcs` 只有块首），据此把「块 → 可能的解引用指令」对上，得到被访问的四个地址：

| 地址 | 相对坏指针 | 对应字段（本工程已钉死的 chunk 布局：`+0x00 prev_foot(8)` / `+0x08 head(8)` / `+0x10 fd(4)` / `+0x14 bk(4)`） |
|---|---|---|
| `0x17DD8D36` | `P + 0x00` | `prev_foot`（被**写**） |
| `0x17DD8D3E` | `P + 0x08` | `head`（被**读**：`ld $v1,8($v0)`，即 0x102208 那条） |
| `0x17DD8D46` | `P + 0x10` | `fd`（被写） |
| `0x17DD8D4A` | `P + 0x14` | `bk`（被写） |

⇒ **坏指针 = `0x17DD8D36`**（= 399 MB；32 MB 主存之外，无 TLB 映射 ⇒ `vtlb_Miss` 读回 0、写被丢弃，游戏带伤继续跑，直到某处的计算把它放大成 `0x0CAC6800` 那样的跳飞目标）。

### A.4 ★ 本轮最重要的新事实：**F4/F7 的 512 MB 上界挡不住这个坏值**

`0x17DD8D36` = 399 MB，落在 **F4/F7 的盲带 `[32 MB, 512 MB)`** 里（F4/F7 的上界是 `0x1FFFFFFE`）：

* F4（`0x102588`，binmap 扫描回边）判据 `t9 < v0 && v0 < 0x1FFFFFFE` ⇒ 399 MB **通过** ⇒ 回边继续，`0x1024E8` 块继续写坏；
* F7（`0x1021D4`，own-bin 回边）判据 `a3 < v0 && v0 < 0x1FFFFFFE` ⇒ 399 MB **通过**；
* unsorted 快路径**根本没有判据**（这正是被登记为残余的那条）。

本机实测把这个结论钉死了：把 `0x55B7B0`（unsorted 链头 fd）毒化成 `0x17DD8D36` 后，**F7b 的上一版（照抄 F4/F7 的 `0x1FFFFFFE` 上界）跑了 600 帧仍然死**——
`runs\n2_unsorted_f7b\hooklog.txt` frame=243：

```
hook pc=00570BB0 frame=243 cycle=1193701944 a0=0055B7A0 a1=00003180 a2=0055B7A0 a3=0055B7B0 v0=17DD8D36 s0=00003178 s1=00000200 ra=0010270C
```

`v0=17DD8D36` 进入 cave、`0x1FFFFFFE` 判定通过 ⇒ 走了「合法」出口 ⇒ `TLB Miss, pc=0x570bcc addr=0x17dd8d3e [load]` ⇒ 最终与未修盘一样卡在 `0x80000180`。
**⇒ F7b 的上界必须收紧到 `0x02000000`（EE RAM 顶，32 MB）。** 合法 chunk 全在 `[heap_base 0x65AEA0, heap_end 0x01F98020) < 32 MB`，所以收紧后合法路径逐字节不变（§C.2 里 162,744 次命中中的 `v0=0x0071DCD0 / 0x0071E500` 都走了原路）。

### A.5 现场冻结与一致性

| 文件 | 现场 sha256 | 冻结副本 sha256 | 一致 |
|---|---|---|---|
| `hook_13795_fatal_jump_0CAC6800\meta.txt` | `1F50E310DEB973E1…`（前 16 位） | 同 | ✅ |
| `…\regs.txt` | `4E7D9FD5EDBEE474…` | 同 | ✅ |
| `…\ring.txt` | `9B4A9E253F408274…` | 同 | ✅ |
| `…\ee_ram.bin` | `C31EF4E6B7A5FD89…` | 同 | ✅ |

并且 `meta.txt` 的 `ring_entries_total=6164369` 与事发当刻日志里 HookWatch 打印的 dump summary **完全一致** ⇒ 用户在 20:41 的第二次尝试落下的 dump 与第一次**逐字节相同**（同一现场可复现）。

`ring.txt` 尾部（最后 44 条）显示：`frame=13795` 期间写 `0x55B7B0/0x55B7B4`（unsorted 链头）的值是 `0x6A2280 / 0x6A32A0 / … / 0x6A5B40` 这些**合法堆指针**——即崩溃前一刻分配器仍在正常地维护 unsorted 链，坏值是更早（t=217 s 的 free 族）被引进来、随后被读到这条快路径上的。

> 与执行者 `47bcee52` 的并行定性：本轮独立读同一份日志/ dump 得到上述结论；`docs\REPORT_ZH126_USER_ERROR.md` 若已产出，请以「同址同 PC」互证（本轮未读到该文件）。

---

## B. 补上未加固的回边（F7b）

### B.1 先解决「没有空洞」：判据放宽 + `.symtab` 精确空隙

旧轮结论（`REPORT_COMBFIX.md` §3.2）：ELF 里「全零 **且** 8 份运行期快照全零」的 ≥32 B 区间 = **0 个**。
本轮换判据（工具 `tools\final_fix\cave_verify_f7b.py`，8 项检查）：

| # | 检查 | 为什么它才是对的 |
|---|---|---|
| C1 | ELF 映像内该区间全零 | 不能覆盖既有代码/数据 |
| C2 | **每一份**运行期 `ee_ram` 快照在该区间与 ELF 逐字节相同 | 等价于「游戏从不写它」；比「快照里必须是 0」更宽（可以是非零死代码/填充） |
| C3/C4 | ELF 映像内、以及每份快照的整个 32 MB 里，**没有任何 32 位字**落在该区间 | 没有任何指针指向它 |
| C5 | 全映像里**没有 `lui`+`addiu`/`ori` 对**构造出落在该区间的地址 | 覆盖「用立即数拼地址」的引用方式 |
| C6 | **没有任何 branch / j / jal** 以该区间为目标 | 静态无入边（执行不可达） |
| C7 | `.symtab` 里 **没有任何 FUNC/OBJECT 符号覆盖**它 | 该 ELF 是 debug build（38,722 符号 + `.debug`/`.line`）⇒ 符号空隙是精确的 |

**用 `.symtab` 找空隙**（工具 `work/builds/GR_F7B/tools/elf_gaps.py`，全映像 5,106,944 B）：
FUNC(19,496) ∪ OBJECT(17,386) 之外的空隙共 22,246 段，其中 ≥36 B 有 **27 段**。按「邻居是符号 + 内容全零 + 与 8 份快照逐字节相同」排序，前几名：

| 候选 | 长度 | 内容 | 归谁 | 结论 |
|---|---|---|---|---|
| `0x00570B90..0x00570C00` | **112 B** | 全零 | `gRomName`（.data 尾）↔ `@1020` 字符串块（.rodata 头）之间的**对齐填充** | ★ 选用（取中间 40 B：`0x570BB0..0x570BD8`，左净空 32 B / 右净空 40 B） |
| `0x00561D48..0x00561D80` | 56 B | 全零 | `__malloc_current_mallinfo` ↔ `__ps2_libinfo__` | 备用 |
| `0x00561DDC..0x00561E00` | 36 B | 全零 | `sceCdCbfunc_number` ↔ `_sceCd_ncmdrdata` | 备用（sceCd 缓冲区旁，风险略高） |
| `0x00562F10..0x00562F40` | 48 B | 全零 | `_sceCd_rd_intr_data` ↔ `_sceCd_Read_cur_pos` | 备用 |
| `0x005DECBC..0x005DED00` | 68 B | F7 已占 36 B，余 8+24 B 不连续 | 段尾填充 | 不够 36 B 连续 |
| `0x00588658…` / `0x00588378…` 等 | 100 B~1.9 KB | **非零**（浮点常数表/字符串） | .rodata 无符号数据 | **排除**：改了会改行为 |

`cave_verify_f7b.py` 对 `0x570BB0`（40 B）的完整输出（原始 JSON：`work\builds\GR_F7B\out\cave_verify_f7b.json`）：
C1 全零 ✓ · C2 **8 份快照（含用户崩溃现场 2 份 + 20:02/16:44/16:57/17:12 的 5 份 + 本机 6000 帧冒烟第 5970 帧 1 份）全部 0 字节差异** ✓ · C3/C4 无指针字 ✓ · C5 无 `lui+addiu` 构造 ✓ · C6 无跳转目标 ✓ · C7 无符号覆盖 ✓。

### B.2 站点与 cave（逐字表）

| 项 | 值 |
|---|---|
| 站点 VA / ISO off / ELF off | `0x00102208` / `0x00095A88` / `0x0002288` |
| 原字 → 新字 | `0xDC430008`（`ld $v1,8($v0)`）→ `0x0815C2EC`（`j 0x00570BB0`） |
| 延迟槽 | `0x0010220C` = `0x00684824`（`and $t1,$v1,$t0`）**未改** |
| cave VA / ISO off / ELF off | `0x00570BB0` / `0x00504430` / `0x0470C30`，**40 B / 10 字** |
| 出口 | 合法 → `j 0x0010220C`（回原流程）；不合法 → `j 0x00102420`（**既有**出口：`0x1021F8` 那条 `beq` 在「unsorted 桶为空」时的落点） |

产物反汇编回读（`work\builds\GR_F7B\F7B_prod_full.meta.json` + `tools\rounds\culprit\tools\dis2.py`）：

```
0x00102208  0815C2EC  j 0x00570BB0
0x0010220C  00684824  and $t1, $v1, $t0          ; 延迟槽未改

0x00570BB0  00C2082B  sltu $at, $a2, $v0         ; at = (v0 > mstate 0x0055B7A0)，严格
0x00570BB4  3C030200  lui  $v1, 0x0200           ; v1 = 0x02000000 = EE RAM 顶
0x00570BB8  0043182B  sltu $v1, $v0, $v1         ; v1 = (v0 < 32 MB)
0x00570BBC  00230824  and  $at, $at, $v1
0x00570BC0  14200003  bne  $at, $zero, +3 -> 0x00570BD0
0x00570BC4  00000000  nop
0x00570BC8  08040908  j    0x00102420           ; bail：既有「unsorted 桶为空」出口
0x00570BCC  00000000  nop
0x00570BD0  08040883  j    0x0010220C           ; 合法：回原流程
0x00570BD4  DC430008  ld   $v1, 8($v0)          ; 延迟槽 = 被替换掉的那条原指令
```

**为什么语义安全（逐条）**

1. **合法路径 = 原语义**：`ld` 在 `j 0x0010220C` 的延迟槽里执行 ⇒ `v1` 与原来一样是 head，`0x10220C` 的 `and $t1,$v1,$t0` 照原样算出 size，`0x102210` 起完全没动。跳转去 cave 时 `0x10220C` 会先带旧 `v1` 跑一次（只写 `t1`，随后被覆盖），无副作用。
2. **bail 路径 = 既有出口**：`0x102420` 是 `0x1021F8`（`v0 == 桶哨兵`）那条 `beq` 的落点，寄存器约定完全一致（只读 `t2/a0/t4`；`t1/t3` 随后重写；`a1`(nb) 与 `a0`(mstate) 原样保留）。**没有新语义、没有新出口**。
3. **只在必要处收紧上界**：`0x02000000` 是 EE RAM 顶；合法 chunk `< 0x01F98020` ⇒ 合法判定结果与 `0x1FFFFFFE` 版本完全相同；差别只在「399 MB 这类坏值」上（§A.4 实测它必须被拦）。下界仍用 `mstate`（排除指向 bin 数组/低端映像的坏值）。
4. **scratch 只用 `$at/$v1`**：两处出口之后 `$v1` 都会被重写（`0x102420: sra $v1,…`／`0x10220C: and $t1,…` 之后 `0x102210` 不用 `$v1` 作为输入），逐条核过。

### B.3 出盘

| 盘 | 基底 | 补丁 | sha256 | CRC | 说明 |
|---|---|---|---|---|---|
| **`work\builds\GR_RELEASE\GR_ZH127.iso`** | `GR_REBUILD2400` | F4+OOMFIX+F7+**F7b** | `7d4e3297…936d` | **`EF4F55D7`** | ★ 交付成品 |
| `work\builds\GR_F7B\F7B_prod_full.iso` | `GR_REBUILD2400` | 同上 | `7d4e3297…936d` | `EF4F55D7` | 推荐候选（== 成品，逐字节） |
| `work\builds\GR_F7B\F7B_prod.iso` | `GR_ZH126.iso` | 仅 F7b | `7d4e3297…936d` | `EF4F55D7` | **交叉验证盘**：两条独立构筑路线得到同一 sha256 |
| `work\builds\GR_F7B\F7B_only.iso` | `GR_REBUILD2400` | 仅 F7b | `51cd6714…858a0` | `5AA2C68A` | 单变量诊断盘 |

* 相对基底 **108 B / 34 run**，`apply_fix.py` 逐项断言「只落在 8 个声明窗口内 / 每个窗口都被写到 / 7 个参照区除声明字外逐字节相同 / 4 个闸门未动 / ELF 头 0x1000 B 未动」全部 OK。
* 三个 meta：`F7B_prod_full.meta.json` / `F7B_prod.meta.json` / `F7B_only.meta.json`（含基底 sha256、逐站点 VA/ISO/ELF/原字/新字、cave 逐字与理由、`diff_runs` 全表、产物 sha256/md5/ELF sha256/CRC、存档名、8 项自证）。
* 临时诊断盘 4 张（跑完即删，sha256 记在 `fix_spec.json · archived_away_disks`）：`d_unsorted_prod` `9289f83d…fafaa`、`d_unsorted_f7b` `f174384f…33f7`、`d_b126_prod` `1e7e627a…09ef5`、`d_b121_prod` `e660a2dc…679b`。

**毒化现场的原理（本轮新发现，写下来给下一轮用）**：这个游戏的分配器 bin 数组（mstate `0x0055B7A0`，64 位 binmap + 每桶 8 B 环形 fd/bk）是**在 ELF 映像里静态初始化**的（空桶自指 `0x0055B798+8i`，`0x0055B7B0 = 0x0055B7A0` 等）。装载器原样拷进 RAM ⇒ **只要改 4 个数据字节**就能把一条坏链头交给分配器，不需要存档、不需要注入代码、完全可确定复现。工具 `work/builds/GR_F7B/tools/f7b_poison.py`。

---

## C. 验证（全部数字）

### C.1 静态

| 项 | 结果 | 原始输出 |
|---|---|---|
| cave 8 项检查（C1–C7 + 邻居净空） | 全部 OK，`verdict = ACCEPTED` | `work\builds\GR_F7B\out\cave_verify_f7b.json` |
| 符号空隙全扫描 | 22,246 段空隙 / ≥36 B 27 段（27 段逐个列出内容与邻居） | `work\builds\GR_F7B\out\elf_gaps_prod.json` |
| 新指令逐条反汇编回读 | 站点 + 10 字 cave 与 `fix_spec.json` 逐字一致 | §B.2 |
| 无入边证明 | 站点 `0x102208` **没有任何分支目标**（⇒ `t0` 必然由 `0x102204` 设好）；cave 区间无任何跳转目标（C6） | `f7b_build.py` 出盘断言 |
| 字节级身份 | 相对基底 108 B / 34 run 全在声明窗口；参照区/闸门/ELF 头未动 | `apply_fix.py` 出盘自洽（失败 0 条） |

### C.2 本机现场矩阵（exe = `work\builds\GR_F7B\emu\gsrunner\pcsx2-gsrunner.exe`，BIOS/VGA 与历史轮一致，跑前记录他人实例、**只记录不杀**）

盘与现场：`u*` = 产品线**基底**（0 补丁，代表「未修」）+ 毒化；`n*` = 产品线（`GR_ZH126`，无 F7b）或 `F7B_prod_full` + 毒化；`r*` = 历史 S1/S1b 等价现场。

| run | 盘 | 毒化目标 | 截图 | **TLB** | Trap | F7b cave 命中 | 跑完帧数 | 执行尾块 | 判定 |
|---|---|---|---|---|---|---|---|---|---|
| `u1_unsorted_base` | 基底（未修） | unsorted 链头 | **0** | **29** | 0 | — | 600 | `80000180`（异常向量，死循环） | **必死** |
| `n1_unsorted_prod` | `GR_ZH126`（无 F7b） | unsorted 链头 | **0** | **29** | 0 | — | 600 | `80000180` | **必死（F4/F7 覆盖不到）** |
| **`n2_unsorted_f7b`** | **`F7B_prod_full`** | unsorted 链头 | **11** | **0** | 0 | **162,744** | 600 | `00411FB0`（游戏逻辑） | **★ 活** |
| `u2_b126_base` | 基底（未修） | 桶 126 | 1 | 0 | 0 | — | 300 | `00208724/0020872C` | 非分配器自旋 |
| `r1_b126_prod` | `GR_ZH126` | 桶 126 | 1 | 0 | 0 | — | 300 | 同上 | F4 在位时**不产生任何坏指针解引用** |
| `r3_b126_f7b` | `F7B_prod_full` | 桶 126 | 1 | 0 | 0 | — | 300 | — | 与 r1 相同 ⇒ 无回归 |
| `u3_b121_base` | 基底（未修） | 桶 121 | **0** | **50** | 0 | — | 300 | **`001021D0/001021A0/00102180`**（纯三块自旋） | **必死（历史 S1b 同型）** |
| `r2_b121_prod` | `GR_ZH126` | 桶 121 | 1 | 50 | 0 | — | 300 | `00208724/0020872C` | F7 bail 把自旋截断 |
| `r4_b121_f7b` | `F7B_prod_full` | 桶 121 | 1 | 50 | 0 | — | 300 | — | 与 r2 相同 ⇒ 无回归 |

**判据读法（重要）**：

* **`u1` / `n1` 的 TLB 首行就是用户崩溃的同址同 PC**：`TLB Miss, pc=0x102200 addr=0x17dd8d3e [load]`，随后 `pc=0x1022c4 addr=0x17dd8d4a/0x17dd8d46 [store]`、`pc=0x10262c`，最后整机卡在 `0x80000180`（EE 异常向量）里 1.86 亿条块全是同一个 PC ⇒ **未修必死**（截图 0 张即可佐证画面早已不动）。
* **`n2` 把「必出」钉死**：同一张毒化盘，只多一条 F7b ⇒ **TLB 0 行**（坏指针根本没被解引用）、cave 命中 162,744 次、11 张截图、执行尾块回到游戏逻辑、跑满 600 帧。hooklog 首行即 `frame=243 … v0=17DD8D36`（§A.4 原文），尾行是 `v0=0x0071DCD0 / 0x0071E500` 这类**合法**堆指针 ⇒ 合法路径照走。
* `u3/r2/r4` 说明**历史 S1b 型自旋确实被 F7 截断**（未修 `0x102180/0x1021A0/0x1021D0` 三块循环 → 跑满 300 帧 + 出到 1 张截图），且 **F7B 盘与 `GR_ZH126` 读数逐项相同 ⇒ F7b 无回归**。
* `u2/r1/r3` 的「桶 126」在**开机即毒化**这种极端现场下不产生任何坏指针解引用（TLB 0），三张盘随后都停在同一个**与分配器无关**的资源等待自旋 `0x00208724/0020872C`（开机就坏掉的空闲链会让某些资源永远申请不到）。⇒ 该现场只适合做「F4 在位/不在位」的对照，不适合当「修好了吗」的判据；**本轮真正的判据是 unsorted 现场（u1/n1 vs n2）**。

### C.3 6000 帧冷启动冒烟 + 逐帧 sha256

| 盘 | 截图 | TLB | Trap | 未识别 | 暂停 | 跑完 |
|---|---|---|---|---|---|---|
| `GR_ZH126.iso`（对照） | 191 | 0 | 0 | 0 | 0 | ✅ 6000 |
| `F7B_prod_full.iso` | 191 | 0 | 0 | 0 | 0 | ✅ 6000 |
| `F7B_only.iso` | 191 | 0 | 0 | 0 | 0 | ✅ 6000 |

逐帧 sha256 对照（`f7b_frames.py`，逐张 PNG 取 sha256）：

| 对照 | 帧数 | 相同 | 不同 | 只在一侧 |
|---|---|---|---|---|
| `F7B_prod_full` vs `GR_ZH126` | 191 / 191 | **191** | **0** | 0 / 0 |
| `F7B_only` vs `GR_ZH126` | 191 / 191 | **191** | **0** | 0 / 0 |

⇒ **0 差异**（预期达成）。原始 JSON：`work\builds\GR_F7B\out\frames_prodfull_vs_zh126.json` / `frames_only_vs_zh126.json`。

### C.4 补丁存活（第 5970 帧 RAM 回读）

用 §C.3 冒烟里 `-grdumpwin 5970 5970` 落下的 32 MB EE RAM，与**盘上的 ELF 映像**逐字节比：

| 盘 | 校验窗口 | 结果 |
|---|---|---|
| `GR_ZH126` | 3 站点 + 3 cave = **128 B** | 128/128 相同 ✅ |
| `F7B_prod_full` | 4 站点 + 4 cave = **168 B** | 168/168 相同 ✅ |
| `F7B_only` | 1 站点 + 1 cave = **40 B** | 40/40 相同 ✅ |

⇒ cave `0x570BB0` 到第 5970 帧仍是盘上的那 40 B（与 §B.1 的 C2「运行期从不被写」互相印证）。原始 JSON：`out\ramcheck_*.json`。

### C.5 从英文原盘的端到端复现（**仍成立**）

```
powershell -NoProfile -ExecutionPolicy Bypass -File tools\final_fix\repro_from_eng.ps1
```

* `[0]` 英文原盘 sha256 `2b42ea7c…8531` ✅（K2 转储 `11f371f2…add9`，74,286,520 B）
* `[1]` `rebuild_base.py`：**4.0 s** 出基底，sha256 `d7f83d7e…443ca0` == 声明值 ✅（ELF `5cb59175…` 断言通过在 `[A1]`）
* `[2]` `apply_fix.py`：四件套出盘，**全部断言 OK / 失败 0 条**，sha256 `7d4e3297…936d` == 成品 ✅
* `[3]` 与 `work\builds\GR_RELEASE\GR_ZH127.iso` 以及 `work\builds\GR_F7B\F7B_prod_full.iso` **逐字节相同** ✅

---

## D. 交付与给用户的测试步骤

### D.1 新成品

| 项 | 值 |
|---|---|
| 路径 | **`work\builds\GR_RELEASE\GR_ZH127.iso`** |
| 尺寸 | 1,648,164,864 B |
| sha256 | `7d4e32972a8616622b415bbbdf654ec5d2e09c2bba7adce40e9c66d99736936d` |
| md5 | `cb0219f2e445e69676f6e59de869c1e8` |
| ELF sha256 | `082076c19b98619f96ec781bb17c3819f4ee3ae239f19f5db8181e95a1a146ec` |
| **Game CRC（PCSX2）** | **`EF4F55D7`** |
| 即时存档名 | `SLUS-20613 (EF4F55D7).01.p2s` |

轮次号：**126 已被占用**（`work\builds\GR_RELEASE\GR_ZH126.iso` 仍在盘上）⇒ 本轮取下一个未用号 **127**（只改文件名/引用，内容 = `F7B_prod_full.iso` 逐字节）。

### D.2 用户测试步骤（照做即可）

1. 用 **`GR_ZH127.iso`**（sha256 见上；不要用 `GR_ZH126.iso`，它没有 F7b）。
2. ⚠ **别用旧即时存档**：`.p2s` 会把整块 32 MB 旧主存盖回 RAM，盘上的补丁会被旧代码盖掉（文件名 CRC 也要对，旧档 CRC 是 `CFDB8C97`/`7A761FCA` 之类，读不到）。
   * 推荐：**从记忆卡存档继续**，或**从关卡开头进**；一定要用旧档 ⇒ 改名成 `SLUS-20613 (EF4F55D7).01.p2s` 再读。
3. 复现原来出错的场景：**发射火箭弹 / 按 L1 开面板**（以及上次的任务完成提示流程）。
4. 判据：
   * **不弹「R5900 Exception」、画面不冻、能继续玩** = 修好了；
   * 日志里**可能仍有 1~2 行 `TLB Miss`**（分配器在 F7b 判定**之前**读一次链头槽位是正常的）——**关键是不会连续重复、不会出现 `Trap exception` / `Jump to unmapped recLUT page`**；
   * 若还出错：把 `emulog.txt` + 当时按的键 + 盘 sha256 发回；**建议同时按 F10**（HookWatch 会落一份 32 MB RAM 现场）。

---

## E. 未达成项（如实列）

1. **没有做「同一份存档」的复现**：用户没给 `.p2s`，而历史轮的现场存档（S1/S1b/…）在本轮开始时**已不在仓库里**（`work\builds\GR_SPINFIX|GR_COMBFIX` 已被清理，仓库内 `.p2s` 数为 0）。本轮改用**毒化盘的等价现场**（4 字节数据补丁，原理见 §B.3），判据（同址同 PC 的 TLB + Trap/跳飞 vs 跑满帧）与用户现象一致，但**严格说不是同一份存档**。
2. **free() 一族回边仍无校验**（`0x101D10 / 0x101DE4 / 0x101E08 / 0x101E34 / 0x101E6C`）：用户日志里 t=217 s / 229 s 的 TLB Miss 就在这些 PC 上，**早于** unsorted 那次，是坏指针的上游来源。SPINFIX 的 F1/F1b 覆盖其中两条，但当年实测带来 6 帧像素差异故未纳入产品线。**本轮不动**（超出「补 unsorted 回边」的范围，且会动到已验证的补丁集合）。
3. **F4/F7 的上界仍是 `0x1FFFFFFE`（512 MB）**：坏值落在 `[32 MB, 512 MB)` 时会通过（§A.4 实测 399 MB 通过）。F7b 已改 `0x02000000`，F4/F7 **未收紧**。收紧配方（各 2 条字，已核过用途）写在 `fix_spec.json · known_residuals`【新登记 1】，属下一轮收口项。
4. **F7b 只校验指针范围，不校验尺寸**：与 F4/F7 同型；坏指针若恰好落在 `[0x55B7A0, 0x02000000)` 的**已映射**区内（例如指向 ELF 映像 `0x00100000` 一带）仍会被当 chunk 解引用。属已知边界（`known_residuals`【新登记 3】）。
5. **「开机即毒化」的桶 126/121 现场不是好判据**：两张盘（含未修基底）最后都停在同一个资源等待自旋 `0x00208724/0020872C`，与分配器校验无关（§C.2 判据读法）。真正判别性的是 unsorted 现场。
6. **归因（汉化是否抬高触发率）仍未判定**：没有做「同场景 汉化 vs 英文」的定量对照（沿用前几轮的未达成项）。
7. **云端公开快照未刷新**：`tools\final_fix\**` 与 `docs\**` 的本轮更新**尚未**推到 `public`（https://github.com/AFishD/GR2001-ZH.git）。见 §E.8。
8. **执行者 `47bcee52` 的 `docs\REPORT_ZH126_USER_ERROR.md` 本轮未出现在盘上**：本报告的 A 部分是独立取证；若该文件后续出现，请以「同址同 PC」互证。

---

## F. 复跑命令（全部在仓库根）

```powershell
$py = 'C:\Users\84363\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# ★ 端到端：英文原盘 ⇒ 基底 ⇒ 四件套 ⇒ 成品（并核与两处交付盘逐字节相同）
powershell -NoProfile -ExecutionPolicy Bypass -File tools\final_fix\repro_from_eng.ps1

# 校验新成品（身份 + 四件套在位 + 相对基底 108 B/34 处全在窗口内）
& $py tools\final_fix\apply_fix.py --verify-only `
      --iso  work\builds\GR_RELEASE\GR_ZH127.iso `
      --base work\builds\GR_F7B\base\GR_REBUILD2400.iso

# cave 选址 8 项证明（换成任意候选 VA/size 也可）
& $py tools\final_fix\cave_verify_f7b.py --elf work\builds\GR_F7B\elf\base_SLUS_206.13.elf `
      --va 0x00570BB0 --size 40 --snap work\builds\GR_F7B\runs\smoke_GR_ZH126\win_f00005970_eeram.bin

# 出盘（三个变体；工具与 fix_spec.json 逐字一致）
& $py work\builds\GR_F7B\tools\f7b_build.py --variant prod_full --base work\builds\GR_F7B\base\GR_REBUILD2400.iso `
      --out work\builds\GR_F7B\F7B_prod_full.iso --meta work\builds\GR_F7B\F7B_prod_full.meta.json
& $py work\builds\GR_F7B\tools\f7b_build.py --variant prod --base work\builds\GR_RELEASE\GR_ZH126.iso `
      --out work\builds\GR_F7B\F7B_prod.iso --meta work\builds\GR_F7B\F7B_prod.meta.json
& $py work\builds\GR_F7B\tools\f7b_build.py --variant only --base work\builds\GR_F7B\base\GR_REBUILD2400.iso `
      --out work\builds\GR_F7B\F7B_only.iso --meta work\builds\GR_F7B\F7B_only.meta.json

# 现场（毒化盘 + 6000 帧冒烟；脚本自带「他人实例只记录不杀」）
powershell -NoProfile -ExecutionPolicy Bypass -File work\builds\GR_F7B\tools\f7b_scenarios.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File work\builds\GR_F7B\tools\f7b_scenarios_base.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File work\builds\GR_F7B\tools\f7b_smoke.ps1

# 读数
& $py work\builds\GR_F7B\tools\f7b_scen_summary.py --json work\builds\GR_F7B\out\scenario_matrix.json
& $py work\builds\GR_F7B\tools\f7b_frames.py work\builds\GR_F7B\runs\smoke_F7B_prod_full work\builds\GR_F7B\runs\smoke_GR_ZH126
& $py work\builds\GR_F7B\tools\f7b_ramcheck.py --ram work\builds\GR_F7B\runs\smoke_F7B_prod_full\win_f00005970_eeram.bin `
      --iso work\builds\GR_F7B\F7B_prod_full.iso --meta work\builds\GR_F7B\F7B_prod_full.meta.json
& $py work\builds\GR_F7B\tools\elf_gaps.py --elf work\builds\GR_F7B\elf\prod_SLUS_206.13.elf --min 36 `
      --json work\builds\GR_F7B\out\elf_gaps_prod.json
```

---

## G. 纪律与磁盘（如实）

* **只读**：`work\builds\GR_HOOKEMU_QT2\**`（含用户日志/现场 dump，只复制出来）、`third_party\**`、`%LOCALAPPDATA%\PCSX2\**`（用户模拟器目录，一个字节都没写）。
* **模拟器独占**：每次起跑前轮询 `pcsx2*`；用户实例（pid 49364，20:43 启动，整个过程中一直在跑）**只记录不杀**，记录落在各 run 目录的 `OTHERS_RUNNING.txt`。本机自己的跑动全部串行。
* **零残留**：临时毒化盘跑完即删 —— `diag\` 4 张 + 5 个 run 目录内的 `poisoned_*.iso` 副本（共 9 张 1.6 GB），**删除前已打印清单**、每张的 sha256/补丁表已登记到 `fix_spec.json · archived_away_disks` 与各 run 的 `poison.meta.json`；`%TEMP%\gr_final_fix_from_eng` 由 `repro_from_eng.ps1` 自清。
* 全程 **未 commit / 未切分支 / 未 merge / 未 push**（云端快照仍未刷新，见 §E.7）。
* 磁盘：开工 `Get-PSDrive C` 余 82 GB；收尾（清理后）余 **73 GB**。`work\builds\GR_F7B\` 共 **7.21 GB**：3 张出盘（`F7B_prod` / `F7B_prod_full` / `F7B_only`）+ 1 张现场重建基底 + 9 个 run 的截图/日志/RAM dump/`hooklog` + elf 副本 + 工具。
