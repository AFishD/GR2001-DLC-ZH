# REPORT_PROFILE_SCROLL — 专家简介（SpecialistProfile）"首行不是姓名"的真正机理 + 修复（GR_ZH136）

> 轮次：**GR_PROFILE2**（产物 **GR_ZH136**）· 日期 2026-10-19
> 被测基底：`work\builds\GR_RELEASE\GR_ZH134.iso`（sha256 `165b7eb2…3ecd6a`，ELF Game CRC `653FBF69`，**只读**）
> 反汇编对象：`third_party\orig\ps2\slus_out\SLUS_206.13`（英文原盘 ELF，含完整 C++ 符号表，**只读**）
> 写入：`work\builds\GR_PROFILE2\**`、`tools\final_fix\repro_from_eng_profile2.ps1`、本文件
> **未动**：`third_party\**`、`work\builds\GR_RELEASE\**`、`work\builds\GR_PROFILE\**`、用户 PCSX2 目录、git

---

## 0. 一句话结论

**上一轮的"`comp[0xFC]=13`"是错的。** 实机（带仪器模拟器）在专家简介屏读出：

| 字段 | 实测值 | 含义 |
|---|---|---|
| `comp[0x1C]` style | `0x00020000` | 走"滚动窗口"绘制分支 ✓ |
| `comp[0xFC]` **滚动起点** | **0** | **窗口从第 0 行开始**（不是 13）|
| `comp[0x114]` 行数 | **47** | 引擎只拿到 47 行（不是折行模型算的 58）|
| `comp[0xF8]` 行距 / `comp[0x44]` 高 | 18 / 190 | 一屏 10 行 |
| `comp[0xF4]` | **180** | 已画 10 行（10×18）|
| `comp[0x40]` 宽 | 270 | 与上一轮一致 |

⇒ 窗口起点本来就是 0、滚动逻辑本来是好的。屏幕上第一行变成「特征：无」**不是滚动**，而是
**文本本身在进入引擎时被从开头截断了**：`<text>` 里第一个 **0xFF 字节**（= 汉字「著」的单字节码）
被 XML 词法器当成了 **EOF**，于是该文本节点在「显著特征」处被切断，前半段（姓名、兵种、台词、
[体检档案]、出生…性别）整段丢失，剩下的后半段被当成同名的第二个 `text` 节点、**覆盖式**写回条目。

**修复 = 让文本里不再出现 0xFF**（本盘把「显著」→「明显」、「卓著」→「卓越」，共 22 处）：
`GR_ZH136` = `GR_ZH134` + 这 22 处文本改写，**ELF 一个字节没改**（Game CRC 仍 `653FBF69`，
旧存档/即时存档继续可用），**滚动代码一行没动**。

推荐盘：`work\builds\GR_PROFILE2\GR_ZH136.iso`
**sha256 `172b35cc940431e99a128ed1ff5d5f80941362a2bf1a281d2a0d8b09ee408140`** / md5 `a9c18781ba6d141a489e6acb3aa8f630` / 1,648,164,864 B / ELF CRC `653FBF69`

---

## 1. A —— "13" 从哪来（实测 + 指令级）

### 1.1 怎么测的（可重跑）

仪器 = 历轮同一台 `work\builds\GR_PRODCRASH\runs_g1eq\emu_hist\gsrunner\pcsx2-gsrunner.exe`
（sha256 `e5825306…`）。它支持：

| 开关 | 作用 |
|---|---|
| `-grinputlive <file>` | **运行期**追加按键/命令（`<btn> tap|hold|release`、`snap <tag>`、`dump <tag>`、`drawwin a b`）|
| `-grmemwatch <addr> <size> <iv>` | 每帧把一段 EE RAM 落盘（本盘盯 `0x5EA690`=SF studio 指针）|
| `-grdrawwin a b` | 在帧窗口内记录**绘制站点 + 参数 + 文本字节**（`drawlog.txt`）|
| `-grscanframes N` | 第 N 帧落 32 MB EE RAM 全量转储 |

为了能进到该屏，构造了**仅用于诊断**的盘：
`work\builds\GR_PROFILE2\diag\GR_ZH136_diag_unlock.iso` = 候选盘 + `0x00346058`
`lbu $v0,-23816($at)`（读 `PS2PressStart::s_m_gbUnlockAllSF`）→ `addiu $v0,$zero,1`
（1 词，CRC `D11F1D90`）。**该盘只用于验证，不是交付物**；交付盘不含此改动。

会话：`work\builds\GR_PROFILE2\runs\live2\`（格式化记忆卡→建档→主菜单→特别收录→专家）。
关键转储：`prof1_f00028613_eeram.bin`（32 MB，帧 28613，专家屏静态时）+ `drawlog.txt`（5 帧绘制日志）。

### 1.2 屏上到底画了什么（drawlog，实机）

`drawlog.txt` 的 `PC=219EB0`（`RSFontMgr::DrawString`）行按 y 排序后，文本面板这一块逐行是：

```
特征：无 / [个人履历] / 1975年9月30日出生于 / 英国伦敦肯辛顿。 / 父亲（托马斯）系退休外交官，
母亲（克洛德，卒于1990年） / 为法国籍。 / 全家依靠投资收益过着富足的生活 / 。
```

即 **10 行窗口画的是组件第 0…9 行**，而组件第 0 行本身就是「特征：无」。
（截图 `runs\live2\b3.png`、`p1.png` 与 `out\drawlog_profile.txt` 完全对得上。）

对照实验：在屏上按 **↓ 一次** → 首行变 `[个人履历]`、标题仍是「斯通」（`runs\live2\c1.png`）
⇒ **↓ 是"文本下滚一行"**（`IncrementScrollStart`），不是换人。滚动功能本来是好的。

### 1.3 组件对象与行数组（RAM 实证）

`prof1_f00028613_eeram.bin` 里按 `__vt__6RSHTML = 0x005978C0` 扫描，唯一的 270×190 对象：

```
VA=0x0125C250  RSHTML  style=00020000  W=270 H=190 lh=18
               cnt(0x114)=47   fC(0xFC)=0   f0(0xF0)=0   f4(0xF4)=180
```

它的文本 `RSUIString`（+0xA0）数据在 **0x007A9AB0**，原始字节：

```
a3 fa ab e8 a8 ba a2 ad 7b 70 7d 5b ee ea 8b ad d4 5d 7b 62 72 7d 31 39 37 35 ...
特    征    ：   无    {p}   [     个   人   履   历   ]   {br}  1  9  7  5
```

⇒ **引擎拿到的字符串第一行就是「特征：无」**；`显著` 两个字已经不在串里。

### 1.4 前半段丢在哪：`RSXMLLexan::GetCharData @0x00544450`

```asm
00544584  sb    $v0,0($a0)          ; buf[len] = 刚读到的字符
00544588  80830000  lb    $v1,0($a0) ; ★ 有符号字节加载
0054458c  2402ffff  addiu $v0,$zero,-1
00544590  14620006  bne   $v1,$v0,0x005445AC   ; != -1 → 正常字符
00544594  2402003c  addiu $v0,$zero,60         ; ('<' 的延迟槽)
00544598  0c040da0  jal   0x00103680           ; 再取一字节
005445a0  2403000f  addiu $v1,$zero,15
005445a4  10000015  beq   $zero,$zero,0x005445FC ; ★ 返回 token 类型 15 = EOF，累计内容**丢弃**
005445a8  ae430000  sw    $v1,0($s2)
```

`lb` 把字节 **0xFF** 符号扩展成 **-1**，与 `addiu $v0,$zero,-1` 相等 ⇒ **0xFF 被当成 EOF**。
这是经典 `char c = get(); if (c == EOF)` 错误：EOF 只能由 `get()` 的**返回值**判断，不能由存进
`char` 的字节判断。本作的字库把 **U+8457 著** 编成**单字节 0xFF**（`charset_compiled_zh16.json`
的 `codes["著"]=255`），于是每个含「著」的 `<text>` 都会在这里被腰斩。

被腰斩后的后果（与 `SFStudio::ParseItem @0x001F70E0` 一起看）：

```asm
001f7150  ...  jal 0x0053E820        ; RSXMLTag::Compare(name,"text")   (0x5777A8 = "text")
001f7168  2664001c  addiu $a0,$s3,28 ; item + 0x1C
001f716c  jal 0x0053E9E0             ; RSString::operator=  ★"覆盖"而不是追加
```

词法器返回 EOF 后解析器收尾这个节点；文件余下部分被当成**同名的第二个 `<text>` 节点**，
`ParseItem` 再把它的值**赋值**到 `SFItem_T+0x1C` ⇒ 条目文本 = **0xFF 之后的那一段**，前半段永久丢失。

### 1.5 数据侧对照：13 条专家档案，第一条 0xFF 都在切点上（+2 字节）

`work\builds\GR_PROFILE2\out\ff_test.txt`（对 `EN_SPECIAL_FEATURE.XML` 逐条统计）：

| 条目 | 「显著特征」起始字节偏移 | 该条**第一个 0xFF** 偏移 | 差 |
|---|---|---|---|
| T0050 | 266 | 268 | **+2** |
| T0051 | 238 | 240 | **+2** |
| T0052 | 262 | 264 | **+2** |
| T0053 | 271 | 273 | **+2** |
| T0054 | 271 | 273 | **+2** |
| T0055 | 283 | 285 | **+2** |
| T0056 | 281 | 283 | **+2** |
| T0057 | 269 | 271 | **+2** |
| T0058 | 268 | 270 | **+2** |
| T0059 | 272 | 274 | **+2** |
| T0060 | 306 | 308 | **+2** |
| T0061 | 221 | 223 | **+2** |
| T0062 | 287 | 289 | **+2** |

结构恒为 `显 a3dc | 著 FF | 特 a3fa | 征 abe8`：**显**随前段一起被丢弃、**著**被当 EOF 吃掉、
于是留存文本正好从「特征」开始 —— 这就是用户看到的「第一行 = 特征：无」。

> 为什么不是滚动造成的（逐条否定）：
> * RAM 里 `comp[0xFC]=0`（§1.3），窗口起点就是第 0 行；
> * 按 ↓ 窗口确实移动（§1.2），说明滚动未被"钉住"；
> * 上一轮 cand1（`DrawHTML` 里 `start:=0`）在这块 RAM 上**不会改变任何像素**（起点本来就是 0），
>   却会把 `Increment/DecrementScrollStart` 的效果全部废掉 —— 这是**用坏滚动换取零收益**。

---

## 2. 方案与站点表

| # | 层 | 站点 | 改法 | 结果 |
|---|---|---|---|---|
| 1 | **文本层（采用）** | `MENU.IMG#283 EN_SPECIAL_FEATURE.XML`，22 处 `0xFF` | `显著 a3dc ff` → `明显 a4cb a3dc`（17 处）；`卓著 adee ff` → `卓越 adee a1d2`（5 处） | 文本节点不再被腰斩；**ELF/滚动/图集 0 改动** |
| 2 | ELF（**否决**） | `0x00544588` `lb`→`lbu` | 让 0xFF 变普通字符 | **真 EOF 再也检测不到**：文件末尾的 text 节点会无限循环写爆 7 KB 形参缓冲（`0x0064A120`）⇒ 否决 |
| 3 | ELF（**否决**） | `0x00544590` `bne`→`beq +8`（走"建串"路径） | 保住前半段 | 同上：EOF token 永不返回，文件尾死循环 ⇒ 否决 |
| 4 | 上一轮 cand1/cand2 | `0x21BCC0` / `0x21C10C+0x21C13C` | 强制/冻结 `comp[0xFC]=0` | ** placebo**：起点本来就是 0；代价是滚动失效 ⇒ 否决 |

站点表（文本层，逐处可复核，`work\builds\GR_PROFILE2\out\zh136_textfix.json`）：

| 条目 | 容器偏移 | 旧字节 | 新字节 | 说明 |
|---|---|---|---|---|
| T0031 | 24665 | `A3DCFF` | `A4CBA3DC` | 显著→明显（AK-74 条目）|
| T0043 | 33274 | `ADEEFF` | `ADEEA1D2` | 卓著→卓越 |
| T0044 | 33681 | `ADEEFF` | `ADEEA1D2` | 卓著→卓越 |
| T0045 | 34066 | `A3DCFF` | `A4CBA3DC` | 显著→明显 |
| T0046 | 34397 | `A3DCFF` | `A4CBA3DC` | 显著→明显 |
| T0050…T0056 | 35863…44930 | `A3DCFF` | `A4CBA3DC` | **13 位专家的「显著特征」标签（本屏症状源）** |
| T0056 / T0060 / T0061 | 45341 / 51302 / 52727 | `ADEEFF` | `ADEEA1D2` | 履历段里的「战功卓著」|
| T0057…T0062 | 46432…53784 | `A3DCFF` | `A4CBA3DC` | 其余专家 |
| T0069 | 70091 | `A3DCFF` | `A4CBA3DC` | 开发手记里的「显著升级」|

> 22 处合计 **+22 字节**；容器是定长槽（解压 116,486 B），差额由 `</SpecialFeatures>` 之后的
> **CRLF 填充尾巴**冲销（36144 → 36122 B），与方法论（`patch_zh134_textfix2.py`）完全一致。
> 重压后帧 41,448 B ≤ 槽 49,700 B。

---

## 3. B —— 验证（数字）

### 3.1 静态自证（`work\builds\GR_PROFILE2\GR_ZH136.meta.json`，8/8 PASS）

| # | 项 | 结果 |
|---|---|---|
| 1 | 基底 sha256 == 声明的 GR_ZH134 | `165b7eb2…3ecd6a` ✓ |
| 2 | 基底 ELF Game CRC | `653FBF69` ✓ |
| 3 | 候选 ELF **逐字节 == 基底 ELF** | ✓（CRC 仍 `653FBF69`，**存档兼容**）|
| 4 | ISO 尺寸不变 | 1,648,164,864 B ✓ |
| 5 | SFXML 解压长 116,486 / 69 条 / 键序不变 | ✓ |
| 6 | SFXML 里 0xFF 计数 | **22 → 0** ✓ |
| 7 | 全盘差异**全部**落在 SFXML 条目区间 | 33,857 B，区间 `0x623B1000..0x623BD224`，越界 0 ✓ |
| 8 | 候选盘 sha256 / md5 | `172b35cc…408140` / `a9c18781ba6d141a489e6acb3aa8f630` ✓ |

文本内容抽检（`out\verify_text2.txt`）：

```
T0050  显著特征：无  ->  明显特征：无
T0043  极其卓著      ->  极其卓越
T0060  战功卓著      ->  战功卓越
T0061  战功卓著      ->  战功卓越
```

### 3.2 屏上效果（实机，诊断盘 = 候选盘 + 解锁 1 词）

因为测试记忆卡是全新档、`特别收录 → 专家` 一行默认是灰条，所以**屏上验证**用
`work\builds\GR_PROFILE2\diag\GR_ZH136_diag_unlock.iso`（候选盘 + `0x346058` 解锁 1 词，
CRC `D11F1D90`）。**交付盘不含这 1 词。**

会话 `work\builds\GR_PROFILE2\runs\live3`（`-grinputlive` 实时驱动，同一记忆卡：档名「S」）：

| 帧 | 动作 | 证据 |
|---|---|---|
| 16871 | 进入「专家 → 斯通」 | `fixed1.png` + `fixed1_f00016871_eeram.bin` |
| 18629 | 按 **↓ 一次** | `fixed2.png` + `fixed2_f00018629_eeram.bin` |

**进入时（修复后）屏上第一行就是姓名**（`fixed1.png`）：

```
杰克·斯通 中士
兵种：狙击手
“没错，是我开枪打死了他。
还有他，还有她，还有那辆车。
念及当时的情况，
我认为这是最妥当的回应。”
[体检档案]
出生日期：1975年9月30日
身高：6英尺（183厘米）
```

RAM 回读（同一对象 `0x0125C250`）：

| 时刻 | `comp[0xFC]` | `comp[0x114]` | `comp[0xF4]` | 说明 |
|---|---|---|---|---|
| **修复前**（`runs\live2\prof1_f00028613_eeram.bin`）| 0 | **47** | 180 | 文本被 0xFF 腰斩，首行「特征：无」|
| **修复后·进入**（`fixed1_f00016871`）| **0** | **61** | 180 | 文本完整（多回 14 行 = 姓名…性别）|
| **修复后·↓一次**（`fixed2_f00018629`）| **1** | 61 | 180 | **滚动起点 +1 ⇒ 滚动仍然有效** |

`fixed2.png` 与之一致：首行变「兵种：狙击手」，末行出现「体重：180磅（82公斤）」，
标题仍是「斯通」（说明 ↓ 是文本滚动、不是换人）。

> 另外，`runs\verify136` 那次 24000 帧固定导航跑批（导航漂移、最后进了片头动画）也留下了一份
> 22000 帧 RAM：条目文本 `0x0137CC50` 已经是
> `杰克·斯通 中士{br}兵种：狙击手{br}…`（修复前的同位置是 `特征：无{p}…`）。可作旁证。

### 3.3 回归（6000 帧冷启动冒烟 + 1 帧粒度对比）

| 跑批 | 盘 | 帧 | 截图 | 0 字节截图 | TLB Miss | Trap/unmapped | 退出码 |
|---|---|---|---|---|---|---|---|
| `smoke_ZH136` | `GR_ZH136.iso` | 6000 | **573** | 0 | **0** | **0** | 0 |
| `smoke_ZH134_fresh` | `GR_RELEASE\GR_ZH134.iso`（对照，本轮重跑）| 6000 | **573** | 0 | **0** | **0** | 0 |

逐帧配对（`work\builds\GR_PROFILE\tools\cmp_snaps.py`，按文件名 1:1）：

```
paired frames      : 573
byte-identical PNG : 573        <-- 全部逐字节相同
differing          : 0
zero-byte snaps    : 0
only in A / only B : 0 / 0
```

运行期 RAM 回读（32 MB EE RAM，第 2000 帧）：

| 对比 | 差异字节 | 说明 |
|---|---|---|
| ZH134（旧基线 `GR_PROFILE\runs\smoke_ZH134_base`） vs ZH134（本轮重跑）| **0** | 仪器完全确定 ⇒ 差异可归因 |
| ZH136 vs ZH134 | **198,946** | 差异全在堆/字符串池页（`0x21000`、`0x55B000`、`0x5D5000`、`0x63A000/0x63B000`…），值是**指针与文本**：SFXML 文本 +22 B 导致解压/驻留顺序变化。**ELF 逐字节相同**（CRC 都是 `653FBF69`）⇒ 没有任何代码字节变化 |

> 结论：冷启动 6000 帧**像素 0 差异**（573/573 逐字节相同），RAM 差异只来自"文本多了 22 字节"
> 这一件事，且 **ELF 0 改动**。这一屏本身的变化由 §3.2 的定向实拍证明。

### 3.4 从英文原盘逐字节可复现 —— **✅ 通过**

`tools\final_fix\repro_from_eng_profile2.ps1`（本轮新增；只读既有脚本与产物）
实跑输出（`work\builds\GR_PROFILE2\logs\repro_profile2.log`，exit 0）：

```
[0] ENG ISO   sha256 2b42ea7ce9bd0a85972a07ca59b1b9d79422ed318b85737db3cfd17daa788531  ✓
    K2 dump   sha256 11f371f294e4f8e353c21931a9c38d73c1309832a21e74cfb3e31d7095daadd9  ✓
[1] base      sha256 d7f83d7ec4a8fe1ec8d60de4b17b94513bd1540dc929d3b667086f4910443ca0  ✓
[2] stage     sha256 e65e77fbb696ec5dd9dfaf5b6ca5bbc62d26bfa00e1f5c238fa150c4868791a1  ✓
[3] edge      sha256 db3f8b997a9dfaa89e5147cbeb75341d71d271cedbd53a2dd1c8aa1bee8aeefb  ✓
[4] GR_ZH133  sha256 3fb12c8d16c2448e5c8976896b8132d65b3f6c8cf0e679f709aaf2b2572cdf95  ✓
[5] GR_ZH134  sha256 165b7eb2c667fc0c373b193f054ecd525d04124e5c57f9e69f6e69e4043ecd6a  ✓
[6] + patch_profile2_text.py  (22 处 0xFF 改写)
    produced  sha256 172b35cc940431e99a128ed1ff5d5f80941362a2bf1a281d2a0d8b09ee408140
    OK  与 work\builds\GR_PROFILE2\GR_ZH136.iso **逐字节相同**
    ELF sha256 a0c8499c…  Game CRC = 653FBF69  ⇒ 未改代码
[7] 逐字节相同；scratch 目录已打印并删除
```

⇒ **GR_ZH136 完全可从英文原盘逐字节复现**（6 段链路的每个中间产物哈希都与既有声明一致）。

---

## 4. 给用户的测试步骤

**盘**：`work\builds\GR_PROFILE2\GR_ZH136.iso`（ELF 与 GR_ZH134 逐字节相同 ⇒ **旧存档/即时存档可继续用**，不必新开档）

1. 主菜单 → **特别收录** → **专家** → 任选一位（第一位是「斯通」）。
2. 看文本框**最上面一行**：
   * 改前：`特征：无`（「显」「著」两字被吃）
   * 改后（期望）：**`杰克·斯通 中士`**（第 1 行 = 姓名行），往下依次是 兵种、台词、`[体检档案]`…
3. **确认滚动仍可用**：按 **↑ / ↓**，窗口应**逐行**移动（不会换人、不会跳页）；
   按 **◄ / ►**（标题栏两端的箭头）应切换上/下一位专家，切换后窗口回到第 0 行。
4. 顺手复核 4 条被改写的其它文本（同一容器）：
   * 特别收录 → 武器 → AK-74：正文「这**明显**提高了射击精度」
   * 奖章：`极其卓越` / `战功卓越`（原「卓著」）
   * 特别收录 → 开发手记 3：「随着战术 AI 的**明显**升级」
5. 若仍有异常，请拍：该屏整屏 + 按 ↓ 之后的整屏。

---

## 5. 未达成 / 诚实清单

1. **`0x00544588 lb` 这条引擎 bug 没有在 ELF 里修**：把 `lb`→`lbu` 会让真 EOF 失去检测、
   在文件尾死循环；要正规修需要在 `GetCharData` 里加"用 `get()` 返回值判 EOF"的 cave（≥3 条指令 + 跳转），
   风险显著高于"把 0xFF 从文本里拿掉"。本轮选择**零 ELF 改动**的数据侧修复。
2. **`著` 这个字在本作里仍然只能以 0xFF 存在**：本轮只改了 **SFXML（`MENU.IMG#283`）**里的 22 处。
   * 同一份 XML 在 `GR.IMG` 还有一份（容器登记表里 `EN_SPECIAL_FEATURE.XML×2`），
     本轮**没有**动它 —— 实机证明游戏读的是 `MENU.IMG#283` 这一份（否则屏上不会变）；
   * DE/ES/FR/IT 四种语言的 SFXML 里也各有 0xFF，但本作（EN/中）不读它们，未处理；
   * **其它 XML 容器**（任务简报 XML 等）本轮**没有**普查 0xFF。建议下一轮做一次全 XML 容器的
     0xFF 普查（工具已就绪：`scan_iso_str.py` / `ff_contexts.py`）。
3. **译文改了 22 个字**（显著→明显、卓著→卓越）：这是**有意的**、语义等价的改写，
   原因是引擎容不下 0xFF；若用户坚持原文，需要走 §5.1 的"换码 + 图集搬槽"路线。
4. 专家屏的**实机 A/B** 用的是"候选盘 + 解锁 1 词"（诊断盘），交付盘本身没在自动导航里跑到该屏
   （测试档没有解锁进度）。**屏幕截图证据**见 `runs\live3\fixed1.png` / `fixed2.png`。
5. 冷启动 6000 帧不经过该屏 ⇒ 回归只能证明"别处没动"（573/573 像素相同），
   不能证明"这一屏变好"；后者由 §3.2 的定向实拍证明。
6. **RAM 回读差异不是 0**：ZH136 vs ZH134 有 198,946 B 差异（堆/文本池页），
   原因是 SFXML 文本 +22 B 改变了容器的解压/驻留顺序；**ELF 逐字节相同**，像素 573/573 相同。
   本项目的旧口径"只有补丁字节变化"对**文本层补丁**不适用，本轮如实登记为"文本变化引起的堆差异"。

### 5.1 若一定要保留「显著/卓著」原文

需要在**图集/码表**层把「著」从单字节码 `0xFF` 搬到一对正常双字节码（新 pair 槽 + 字形搬移），
再把 SFXML（以及一切含「著」的 XML 文本）重编码。工作量与风险都远大于本轮，
且不再满足"ELF/图集 0 改动"这条线 —— 本轮不做，如实登记。

---

## 6. 复现命令

```powershell
$py = 'C:\Users\84363\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 反汇编取证（只读英文原盘 ELF）
& $py tools\re\toolbelt\cave_dis.py "third_party\orig\ps2\slus_out\SLUS_206.13" dis 0x544450 0x544660
& $py work\builds\GR_PROFILE2\tools\elfpeek.py "third_party\orig\ps2\slus_out\SLUS_206.13" str 0x5777A8

# 2) 数据侧取证（SFXML 里 0xFF 分布 / 切点）
& $py work\builds\GR_PROFILE2\tools\ff_test.py        # 13 条专家：first_FF = cut+2
& $py work\builds\GR_PROFILE2\tools\ff_contexts.py    # 全容器 22 处 0xFF 的上下文

# 3) 出候选盘（只读 GR_ZH134；只写 GR_PROFILE2）
& $py work\builds\GR_PROFILE2\tools\patch_profile2_text.py `
      --iso work\builds\GR_RELEASE\GR_ZH134.iso `
      --out work\builds\GR_PROFILE2\GR_ZH136.iso `
      --report work\builds\GR_PROFILE2\out\zh136_textfix.json

# 4) 自证 8 项
& $py work\builds\GR_PROFILE2\tools\make_meta2.py

# 5) 从英文原盘端到端复现
powershell -NoProfile -ExecutionPolicy Bypass -File tools\final_fix\repro_from_eng_profile2.ps1

# 6) 屏上效果（诊断盘 = 候选盘 + 解锁 1 词；只在 GR_PROFILE2\diag 下）
& $py work\builds\GR_PROFILE2\tools\iso_patch.py work\builds\GR_PROFILE2\GR_ZH136.iso `
      work\builds\GR_PROFILE2\diag\GR_ZH136_diag_unlock.iso `
      --site 0x346058=0x24020001 --expect 0x346058=0x9022A2F8
powershell -NoProfile -ExecutionPolicy Bypass -File work\builds\GR_MERGEFIX\runs\run133.ps1 `
      -Name verify136 -Iso work\builds\GR_PROFILE2\diag\GR_ZH136_diag_unlock.iso `
      -Frames 24000 -Snap 200 -ScanFrames 22000 `
      -Nav work\builds\GR_PROFILE2\runs\verify136\nav.txt `
      -OutRoot work\builds\GR_PROFILE2\runs
```

---

## 7. 验证记录（本轮实跑汇总）

| 项 | 命令 / 产物 | 结果 |
|---|---|---|
| 文本层出盘 | `patch_profile2_text.py --iso GR_ZH134 --out GR_ZH136` | 22 处改写，+22 B 由 CRLF 尾巴冲销，blob 仍 116486 B；重压 41,448 B ≤ 槽 49,700 B |
| 8 项自证 | `make_meta2.py` → `GR_ZH136.meta.json` | **8/8 PASS** |
| 屏上效果 | `runs\live3\fixed1.png` / `fixed2.png` + 两份 32 MB RAM | 首行 = 姓名行；↓ 后 `comp[0xFC]` 0→1 |
| 6000 帧冒烟 | `runs\smoke_ZH136` | 573 截图 / 0 空图 / TLB 0 / Trap 0 / exit 0 |
| 1 帧粒度对比 | `cmp_snaps.py smoke_ZH136 vs GR_PROFILE\runs\smoke_ZH134_base` | **573/573 逐字节相同，0 差异** |
| RAM 回读 | 第 2000 帧 32 MB ×3 跑批 | ZH134 重跑 **0 差异**；ZH136 差异 198,946 B（堆/文本池，ELF 相同）|
| 从 ENG 复现 | `repro_from_eng_profile2.ps1` | **逐字节相同**（`172b35cc…`），ELF CRC 仍 `653FBF69` |

### 7.1 本轮新增/改动文件

| 文件 | 作用 |
|---|---|
| `work\builds\GR_PROFILE2\GR_ZH136.iso` | **推荐交付盘** |
| `work\builds\GR_PROFILE2\GR_ZH136.meta.json` | 8 项自证 |
| `work\builds\GR_PROFILE2\diag\GR_ZH136_diag_unlock.iso` | **仅验证用**（候选 + 解锁 1 词；CRC `D11F1D90`）|
| `work\builds\GR_PROFILE2\tools\patch_profile2_text.py` | 出盘工具（22 处 0xFF 改写）|
| `work\builds\GR_PROFILE2\tools\make_meta2.py` | 自证脚本 |
| `work\builds\GR_PROFILE2\tools\iso_patch.py` | 通用 1..N 词就地打补丁 + 全盘 diff 落账（含 ELF CRC）|
| `work\builds\GR_PROFILE2\tools\ram_prof.py` / `find_rshtml.py` / `scan_wide_stores.py` | RAM 侧取证（vptr 扫描 / 字段解码 / 宽存储扫描）|
| `work\builds\GR_PROFILE2\tools\{ff_test,ff_contexts,cut_offsets,cut_chars,chunk_test,cut_bytes}.py` | 0xFF 取证链（哪一条、第几字节、切点）|
| `work\builds\GR_PROFILE2\tools\{mw_parse,parse_drawlog,verify_fixed_ram,ramdiff2,check136}.py` | memwatch / drawlog / RAM 对比 |
| `work\builds\GR_PROFILE2\tools\{elfpeek,dump_sfxml,verify_text,verify_text2}.py` | ELF/容器只读取证 |
| `tools\final_fix\repro_from_eng_profile2.ps1` | 从 ENG 原盘的端到端复现（新增，未改既有脚本）|
| `work\builds\GR_PROFILE2\runs\{live1,live2,live3,verify136,smoke_ZH136,smoke_ZH134_fresh}` | 跑批与证据 |

**未改动**：`third_party\**`、`work\builds\GR_RELEASE\**`、`work\builds\GR_PROFILE\**`、
`tools\final_fix\` 既有文件（只读引用）、用户 PCSX2 目录、git。
