# 底部按键提示条「信息 ⇄ 队员信息」交替：机制定案与最小修复

- 分析对象：`work\builds\v33.iso`（ELF sha256 `24316899…`，Game CRC `0406EA00`）/ 英文原盘 `third_party\orig\ps2\[PS2] Tom Clancy's Ghost Recon - Jungle Storm (U).iso`
- 分析方式：**纯静态**（ELF 反汇编 + LANG 解析 + 读既有截图/连拍 JSON），未启动 PCSX2。
- 所有脚本都在本目录（`work\analysis\hint\`），全部只读原盘/ISO，不写任何现存文件。

---

## 0. 结论（先看这段）

1. **不是 marquee/滚动，也不是“多个 hint 条目轮播列表”。**
   是**同一个 ○ 槽位（hint 条槽位 2）的文本被一个 0.7 s 的周期定时器反复重设**，在两个 LANG id 之间来回切：
   - `G058.I029` = `Info` → 中文「信息」（2 字）
   - `G058.I229` = `Soldier` → 中文「队员信息」（4 字）

2. 判定「哪一个」取决于一个字节 `0x7A4`（每 0.7 s 取反一次）和一个“当前焦点/语境”标志：
   - `0x7A4 != 0` → 槽 2 = `G058.I029`「信息」
   - `0x7A4 == 0` → 槽 2 = 语境动作：`0x6DA`→`G058.I229`「Soldier」、`0x6DC`→`G058.I572`「Weapon」、`0x6DD`→`G058.I1253`「Stats」
   名册里选中队员时 `0x6DA=1`，所以就是「信息」⇄「队员信息」。

3. **英文原盘本来就是这个二态交替**（`Info` ⇄ `Soldier`，同一段代码、同两个 LANG id）。汉化后之所以“看起来像 bug”，是因为：
   - v25 两态是「队员」/「信息」——都是 2 字、等宽，交替几乎看不出来；
   - v26（以及当前 v33）`I229` 是 4 字「队员信息」，两态宽度从 74 px 跳到 149 px，交替就非常显眼。

4. **空间足够，4 字能完整平铺**：4 字态实测 149 px（x1079–1228），到右边 △ 图标（x1278）还有 50 px 余量，5× 放大图里 4 个字形完整、无半字/截断/拖影。**不需要缩成 3 字，也不需要改宽度常量。**

5. **最小修复（推荐，纯 ELF 2 词，无 cave）**：
   - `VA 0x2C87A0 / file 0x1C88A0`：`10400017`（`beqz v0,0x2C8800`）→ `10000017`（`b 0x2C8800`）
     ⇒ 永远走“语境动作”分支：名册恒为 `I229`「队员信息」；装备栏焦点恒为「武器」；属性焦点恒为「统计」。不再回退到「信息」。
   - `VA 0x2B8578 / file 0x1B8678`：`3446001D`（`ori a2,v0,0x1D`）→ `344600E5`（`ori a2,v0,0xE5`）
     ⇒ 界面激活时槽 2 的初始文本也直接是 `I229`，消掉进入后 ≤0.7 s 的「信息」闪一下。
   - 副作用：Game CRC `0406EA00` → `0446EAF8`（详见 §5.4；可用补偿词保持 CRC，见 §5.5）。

6. 涉及 LANG id 清单（详见 §3）：**`G058.I029`、`G058.I229`**（本屏交替的两个）；`G058.I034`（重复的 Info，未被本路径引用）；`G058.I572`/`I1253`（装备/属性焦点的另一态）；`G058.I280`/`I459`/`I1094`（浏览/进入战场/返回）。

---

## 1. 定位路径（怎么从 LANG id 反查到这条代码）

- LANG key 编码：`key = 0x3900000 | index`（G058 = 组号 58 → `(58-1)<<20 = 0x3900000`）。
  代码里的形态固定为 `lui v0,0x390` +（`jal 0x40A4E0` 的延迟槽）`ori a2,v0,0xNNN`；`0x40A4E0` 是 LANG 取值函数。
- `work\analysis\hint\map_keys.py` 扫描全 `.text` 的 `lui 0x390`+`ori/addiu` 组合，共还原 **1089 个 key 站点**（`key_sites.txt`）。
- 其中 **`G058.I229`（Soldier）在整个 ELF 里只有 1 个代码引用**：`VA 0x2C881C`。
  它紧挨着 `G058.I029`（Info）在 `VA 0x2C87B8` 的引用——两者在同一个函数 `0x2C86C0` 内，相距 0x64 字节。
  同函数还有 `I572`（0x2C8880）与 `I1253`（0x2C88E4）。⇒ 这就是交替的源头。

---

## 2. 机制取证

### 2.1 这段代码属于哪个界面

- 所在类：**单人小队设置（platoon）界面**（类构造 `VA 0x2B7D30`；界面模板名 `GAMEINFO_PS2`，另会打开 `SINGLE_BRIEFING` / `PS2_QUICK_MISSION_NEWORLOAD` 对话框）。
  - 构造函数 `VA 0x2B7D30`：写 vtable `0x5AB580`（obj+0）与 `0x5AB5F0`（obj+8），并把 `0x6DA/0x6DC/0x6DD/0x764/0x77C…` 清零。
  - 类内引用的 UI 字符串（`refs_in_range.py`）：`AUTOASSIGN`、`A_ASSIGN`、`B_ASSIGN`、`ALPHA`、`BRAVO`、`HERO0..HERO11`、`RECRUIT*`、`LEFTKIT`/`RIGHTKIT`、`KITWEAPON1/2`、`POINTS`、`RANKIMAGES*`、`SPECIMAGES*`、`Auto Assign`、`Unassign All`、`Enter the battlefield.`、`SINGLE_BRIEFING`、`GAMEINFO_PS2`。
    这些与实机截图上的「自动分配 / A组 / B组 / 专家 / 装备 / 得分 / 开始」一一对应（`squad_setup.png`、`squad_auto.png`）。
  - 实机截图的底栏文字与这些完全对得上（`hint_squad_auto.png`：`Enter the battlefield.` + △Back + ✕Accept；`hint_member_selected.png`：L1R1 Browse + ○Info + △Back）。

- `VA 0x2B8140` = 该界面的“激活/显示提示条”函数（vtable@`0x5AB678`）。关键几条：

```
0x2B8168  sw  zero,0x7A0(s1)      ; 0.7s 计时器累加器清零
0x2B8170  sb  v0(=1),0x7A4(s1)    ; ★ 0x7A4 初值 = 1 → 先显示“Info”
0x2B8174  sw  zero,0x7A8(s1)      ; 0.2s 计时器累加器清零
0x2B8178  sb  v0(=1),0x7AC(s1)    ; （另一个 0.2s 小闪烁的状态）
0x2B8558  jal 0x20D980            ; 取 hint 条槽位 2 的控件（a1=2）
0x2B8570  lui v0,0x390
0x2B8574  jal 0x40A4E0            ; LANG 取值
0x2B8578  ori a2,v0,0x1D          ; ★ 槽 2 初值 = G058.I029 “Info”
0x2B85A8  jal 0x20D980            ; 槽位 5（a1=5）
0x2B85C0  ori a2,v0,0x118         ; 槽 5 = G058.I280 “Browse”
0x2B8624  sb  1,0x77D(s1)         ; ★ 提示条“激活”标志（每帧 tick 的门闩）
0x2B8660  ori a2,v0,0x1CB         ; G058.I459 “Enter the battlefield.”（底栏中部说明文字，走 0x20BC10 路径）
0x2B86BC  sb  0,0x77D(s1)         ; 关闭时清 0
```

  （槽位取件函数 `0x20D980(mgr, i) = *(mgr + 0x110 + i*4)`，`mgr = 0x124EF0()` = UI/控件管理器；`0x126640()` 是本地化/LANG 管理器，作为 `0x40A4E0` 的第 2 参数。）

### 2.2 每帧 tick：`VA 0x2C86C0`（vtable `0x5AB5F0` + 0x58）

只贴关键段（完整反汇编：`dis_2C8600.txt`）：

```
0x2C86C0  prologue
0x2C86CC  jal 0x1FA880 / 0x124100 / 0x1465C0
0x2C86E4  lwc1 f1,0x7A0(s0)
0x2C86E8  add.s f0,f1,f0
0x2C86F0  swc1 f0,0x7A0(s0)        ; 0x7A0 += dt（秒）
          ...                         （同样把 dt 累加进 0x7A8）
0x2C8708  lbu v0,0x7AD(s0)         ; 另一个 0.2s 小闪烁（与文字无关）
0x2C8720  ld  a1,0x58F190          ; = 0.2（double）
0x2C8724  jal 0x197E80             ; 到期判断
          ... → 0x7AC 取反 + 虚调用 vtable+0xF8

0x2C875C  lbu v0,0x77D(s0)         ; ★ 提示条未激活就直接返回
0x2C8778  jal 0x197E80             ; ★ 0x7A0 累计值 >= 0.7 ?（a1=0x58F188）
0x2C8780  beqz v0,0x2C8928         ; 未到期 → 直接走收尾
0x2C8788  sw  zero,0x7A0(s0)       ; 到期：清零
0x2C8790-98  0x7A4 = (0x7A4==0) ^ 1   ; ★ 每 0.7s 翻转一次
0x2C879C  lbu v0,0x7A4(s0)
0x2C87A0  beqz v0,0x2C8800         ; ★ 0x7A4==0 → 语境动作分支
0x2C87A8  jal 0x126640             ;   否则：取 LANG
0x2C87B8  lui v0,0x390
0x2C87C0  ori a2,v0,0x1D           ;   ★ 槽 2 = G058.I029 “Info”
0x2C87D0  jal 0x20D980 (a1=2)      ;   槽 2 控件
0x2C87E0  jalr vtable+0x104        ;   SetText

0x2C8800  lbu v0,0x6DA(s0)         ; 语境 1：士兵焦点
0x2C8804  beqz v0,0x2C8864
0x2C881C  lui v0,0x390
0x2C8824  ori a2,v0,0xE5           ;   ★ 槽 2 = G058.I229 “Soldier”
0x2C8834  jal 0x20D980 (a1=2)
0x2C8844  jalr vtable+0x104

0x2C8864  lbu v0,0x6DC(s0)         ; 语境 2：武器/装备焦点
0x2C8888  ori a2,v0,0x23C          ;   I572 “Weapon”
0x2C88C8  lbu v0,0x6DD(s0)         ; 语境 3：属性焦点
0x2C88EC  ori a2,v0,0x4E5          ;   I1253 “Stats”

0x2C8928  jal 0x2C8CF0 (s0,-1)     ; 收尾（每帧都走）
```

- `0x6DA/0x6DC/0x6DD` 就是“当前焦点/语境的提示类别”，都由同一类在选中士兵/切到装备/属性时置 1（见 §3 表的“触发条件”列）。
- 注意：**文本只在计时器到期的这一拍被重设**，不是每帧重设；所以两态各持续 0.7 s。
- 该函数体内 `jal` 目标只有：`0x124100 / 0x124EF0 / 0x126640 / 0x1465C0 / 0x197E80 / 0x19DCA0 / 0x1FA880 / 0x20D980 / 0x2C8CF0 / 0x4016D0 / 0x40A4E0`。
  **没有 `StringWidth(0x21A4C0)`、`CharWidth(0x21A360)`、折行(0x21B620)` 或任何宽度比较** ⇒ 与“超宽滚动/裁剪”无关。

### 2.3 两个时间常量

| 常量 | VA | 值 | 用途 |
|---|---|---|---|
| 0.7 s | `0x58F188` | double `0.7` | **文字二态翻转**（本问题） |
| 0.2 s | `0x58F190` | double `0.2` | 另一个小闪烁（`0x7AC` → 子控件虚调用 `vtable+0xF8`），与文字无关 |

实测（`work\analysis\emu\squad_v26\fb_series.json`，0.14 s/帧连拍）每态持续：
`0.766 / 0.593 / 0.706 / 0.702 s`，周期 ≈ 1.4 s = 0.7 × 2，**与常量 0.7 完全吻合**。
（`hb_series.json` 是 0.3 s 粗采样，量化后看起来像 0.3/0.6 s，不要用它算周期。）
早前记录里“约 0.35 s”应是半周期或粗采样误读；代码常量与细采样都指向 **0.7 s/态**。

### 2.4 为什么不是 marquee（逐条排除）

| marquee/滚动的特征 | 实测 | 结论 |
|---|---|---|
| 代码里按控件宽度判定/量宽 | tick 函数无 `StringWidth/CharWidth` 调用，无宽度比较 | ✗ |
| 出现中间偏移/半字/拖影 | 24 帧连拍只有两种完整字形，左端同为 x1077/1079（差 2 px 是「信」「队」字形左边距） | ✗ |
| 文本被窗口裁掉 | 4 字态 149 px 全部画出（1079–1228），5× 放大 `evid_hint_zoom.png` 完整 | ✗ |
| 越宽越滚 | 4 字比 2 字宽 75 px，但仍然完整显示，右侧还有 50 px | ✗ |
| 只有 ○ 项在变 | L1R1「浏览」（x381–576）与 △「返回」（x1278–1399）像素位置逐帧不变 | ✓ 单槽位换文本 |

⇒ **单槽位文本替换**，由上面的 0.7 s 定时器驱动。

### 2.5 槽位 ↔ 按钮的对应关系

- 槽位号是**按钮枚举**，不是横排位置：
  - 本屏 `0x2B8140` 把槽 2 设成 `Info`；实机 ○ 图标后唯一的文字就是「信息/队员信息」⇒ **槽 2 = ○**。
  - 同一条提示条的其他界面把 `Back` 写槽 1（如 `0x2F7DB8`、`0x31114C`）、把 `Browse` 写槽 5（`0x2B85A8`、`0x3111EC`、`0x31B8BC`），而本屏槽 5 = `Browse`（截图最左 L1R1「浏览」）。
  - 槽 1/2/3/5 分别对应 △/○/□/L1R1 一类；如后续要 100% 坐实，可 dump `GAMEINFO_PS2` 模板的 hint 控件表（本次未做，不影响结论）。

---

## 3. LANG 清单（EN 原文来自英文原盘，中文取自 v33 盘内 EN_STRINGS.RES）

| LANG id | EN | v33 盘上中文 | 在本屏的角色 | 代码引用点（全 ELF） |
|---|---|---|---|---|
| **G058.I029** | `Info` | **信息** | **交替态 A**（0x7A4≠0 时无条件显示） | `0x2B8570`（激活初值）、`0x2C87B8`（tick）+ 另 4 处非本屏 |
| **G058.I229** | `Soldier` | **队员信息** | **交替态 B**（0x6DA=1） | **仅 `0x2C881C`（全 ELF 唯一）** |
| G058.I034 | `Info` | 信息 | 重复的 Info，**本路径不引用**（全 ELF 无代码 key 站点） | — |
| G058.I572 | `Weapon` | 武器 | 装备栏焦点态（0x6DC=1） | `0x2C8880`（+ 属性面板标题 `0x2BB670` 等共 3 处） |
| G058.I1253 | `Stats` | 统计 | 属性焦点态（0x6DD=1） | `0x2C88E4`（全 ELF 唯一） |
| G058.I265 | `Rank` | 军衔 | **另一个类**的交替（`0x327620`，Info⇄Rank），不是本屏 | `0x32773C` |
| G058.I280 | `Browse` | 浏览 | 槽 5（L1/R1） | 7 处 |
| G058.I459 | `Enter the battlefield.` | 进入战场。 | 未选中队员时底栏中部的说明文字（非按钮槽） | `0x2B8660`（`0x20BC10` 路径） |
| G058.I1094 | `Back` | 返回 | 槽 1（△） | 多处（共享） |

标志置位点（证明“选中队员 → 0x6DA=1”）：
- `0x6DA=1`：`0x2B8B08`（选中士兵，循环 9 项后置位）、`0x2BC88C`、`0x2C06A0`；清 0：`0x2C059C`、构造 `0x2B7EAC`。
- `0x6DC=1`：`0x2BDD04`、`0x2C05B4`；`0x6DD=1`：`0x2BE28C`。

---

## 4. 空间判定：4 字放得下

| 项 | 数值（内容区像素坐标，见 `measure_v26.txt` / `fb_series.json`） |
|---|---|
| 2 字态「信息」 | x1077–1150，74 px |
| 4 字态「队员信息」 | x1079–1147（队员，69 px）+ x1155–1228（信息，74 px），共 **149 px** |
| ○ 图标 | x1024–1062 |
| 下一个 △ 图标起点 | **x1278** ⇒ 4 字右端到它还空 **50 px**（≈1.3 个字宽） |
| 是否截断/半字 | 否；`evid_hint_zoom.png`（5×）、`crop_hint_compare.png` 四字完整 |
| 字号 | 单字 ≈35 px（screen）/ ≈13.4 px（640 宽游戏坐标），4 字 ≈53.6 游戏 px |

⇒ **不是“box 宽度 < 4 全宽字”**。不需要改宽度常量，也不需要缩成 3 字。
（余量 ≈1.3 个字：即使再加 1 个字（5 字）也仍放得下；但没有必要。）

---

## 5. 修复建议

### 5.1 方案 A（推荐）：纯 ELF 2 词，无需 cave

| # | VA | ELF file_off | 原词 | 新词 | 作用 |
|---|---|---|---|---|---|
| A | `0x2C87A0` | `0x1C88A0` | `10400017`（`beqz v0,0x2C8800`） | `10000017`（`b 0x2C8800`） | 永远走“语境动作”分支：名册恒 `I229`「队员信息」；装备焦点恒 `I572`「武器」；属性焦点恒 `I1253`「统计」。Info 分支变成死代码（无害）。 |
| B（可选，消除开场闪烁） | `0x2B8578` | `0x1B8678` | `3446001D`（`ori a2,v0,0x1D`） | `344600E5`（`ori a2,v0,0xE5`） | 界面激活时槽 2 初值就设成 `I229`，不再先显示 0.7 s 的「信息」。 |

- 只打 A：进入名册后最多 0.7 s 内仍可能看到「信息」（激活初值 + 首次 tick 之前），随后永久「队员信息」。
- A+B：从第一帧起就是「队员信息」，全程静止。
- `file_off` 是 **ELF 文件内偏移**（= VA − 0xFFF00，本 DLC 的 PT_LOAD 关系）；`tools/dlc/build.py` 的 ELF 补丁就是对 `iso.elf()` 的字节数组按这个偏移改。已在 v33 ISO 的 `SLUS_208.20` 上逐字核对（`check_iso_sites.py`，两处均为原词、无冲突）。
- 两处都落在主代码、无跳转目标冲突、不占用 cave、不改任何数据结构。
- 编码已复核：`0x10000017` 反汇编为 `b 0x2c8800`；`0x344600E5` 为 `ori $a2,$v0,0xe5`。
- 副作用：装备/属性焦点下不再出现「信息」半态（原本是 `Info⇄Weapon` / `Info⇄Stats` 闪烁）；现在恒为「武器」/「统计」。若认为这两个语境也需要“信息”字样，见 5.3 变体 C（但不建议）。

### 5.2 方案 B（纯数据，不推荐：会污染别的界面）

- 把 `G058.I029` 改成「队员信息」→ 两态同串，名册静止 4 字。但 `I029` 在 ELF 里共 **6 处**引用：
  - `0x2B8570`（本屏激活）、`0x2C87B8`（本屏 tick）
  - `0x2D42A0`（另一个界面的提示条**槽 0**）、`0x30AF10`（某个面板文本控件）
  - `0x3262AC`、`0x3276E4`（另一个类，Info⇄军衔）
  ⇒ 这些地方都会变成「队员信息」，明显错。
- 把 `G058.I229` 改成「信息」→ 两态同串但只剩 2 字，不满足需求。
- 因此**没有“只改一个 LANG 条目”就能两全的纯数据方案**；`I229` 只被本屏 1 处引用，是唯一可以安全专门化的条目（它已经是「队员信息」）。

### 5.3 变体 C（1 词，不推荐）

- `VA 0x2C87C0`：`3446001D` → `344600E5`（Info 分支改读 `I229`）。
- 名册：两态都是「队员信息」→ 静止 4 字（达成目标）。
- 但装备/属性焦点会变成「队员信息 ⇄ 武器」/「队员信息 ⇄ 统计」，语义错，所以不如方案 A。

### 5.4 落地步骤（不改 tools/ 下的文件，由 Lead 执行）

1. 在 `tools/dlc/build.py` 的 `ELF_EXTRA_PATCHES`（第 91 行起）追加两条（格式与现有条目一致）：
   ```python
   dict(file_off=0x1C88A0, orig_hex='10400017', new_hex='10000017',
        why='提示条槽2：beqz→b，恒走语境动作（名册恒 队员信息；0x2C87A0）'),
   dict(file_off=0x1B8678, orig_hex='3446001D', new_hex='344600E5',
        why='提示条槽2 初值：I029→I229（0x2B8578）'),
   ```
2. `python tools/dlc/build.py --stage spec` 重新生成 `tools/dlc/elf_patches.json`（会自动记录新 sha256/CRC）。
3. 正常 rebuild → 实机验证（见 5.6）。

**CRC**（PCSX2 Game CRC = 全 ELF 按 u32 异或）：
- v33：`0406EA00`
- 只打 A：`0406EA00 ^ (0x10400017 ^ 0x10000017) = 0446EA00`
- A+B：`0446EAF8`（与 `crc_sim.py` 模拟一致；新 ELF sha256 `3896ba2f…`）
- 影响：PCSX2 即时存档文件名/目录随 CRC 变，旧 .p2s 不再自动关联（本项目发布说明本来就有“CRC 变→请新开档”）。若要让 Lead 直接复用 v33 的即时存档，见 5.5。

### 5.5 可选：把 CRC 钉回 `0406EA00`

- 由于 Game CRC 只是全文件 u32 异或，把 **XOR 差值 `0x004000F8`（A+B 时）** 写进任意一个“已验证未被引用、不会被执行的 4 字节 0 填充词”，最终 CRC 就回到 `0406EA00`，v33 的 PCSX2 即时存档可继续用（ELF 内存布局完全没变，只有 8 字节代码语义变化，状态兼容）。
- 必须先用 `python tools/analysis/elf_probe.py cave --min 16 --check` + 人工确认该词无 lui/addiu 地址引用、不在任何函数体内，再写。**本次没有替 Lead 选定具体填充词**（避免引入新的风险点）；如果不做补偿，就按 5.4 接受新 CRC。
- 另一个不改 ELF 的土办法：把旧 `.p2s` 复制/改名成新 CRC 文件名，PCSX2 通常可直接加载（同布局、同 RAM 镜像）。

### 5.6 验证清单（下一轮实机，需 Lead 的 PCSX2）

- [ ] 进入名册、选中队员，静止观察 ≥ 3 s：○ 后应恒为「队员信息」，不再出现「信息」。
- [ ] 4 字完整、不截断，右端仍离 △ 图标 ~50 px（`crop_hint_compare.png` 同口径复测）。
- [ ] 按 R1 把焦点移到装备栏：○ 后应为静态「武器」（原为 `信息⇄武器`）；属性焦点应为静态「统计」。
- [ ] 返回名册、切换队员：仍恒为「队员信息」（tick 仍每 0.7 s 重设同一串，不应闪烁/重排）。
- [ ] 未选中队员时：底栏应仍是「进入战场。」+△返回+✕接受，没有多出 ○ 项。

### 5.7 静态复核命令

```
python tools/analysis/elf_probe.py disasm --range 0x2C86C0:0x2C8930
python tools/analysis/elf_probe.py disasm --range 0x2B8140:0x2B8700
python work\analysis\hint\map_keys.py          # key→站点（key_sites.txt）
python work\analysis\hint\keys_in_range.py     # 本类用到的 LANG 串
python work\analysis\hint\check_iso_sites.py   # 在 v33 ISO 的 ELF 里核对补丁点
python work\analysis\hint\crc_sim.py           # 模拟 A/B 补丁后的 CRC
```

---

## 6. 风险 / 还没确认的点

1. **没有实机跑补丁**（约束：不启动 PCSX2）。静态链完整，但最终需 §5.6 一轮验证。
2. 槽位 2 = ○ 是从“本屏把槽 2 设成 Info + 截图上 ○ 后唯一文字就是 Info”推出来的，没有逐项 dump `GAMEINFO_PS2` 模板的 hint 控件表；不影响修复（补丁只改槽 2 的文本来源）。
3. 方案 A 会去掉装备/属性焦点的「信息」半态（变成静态「武器」/「统计」）。若 Lead 希望保留那里的闪烁，需要更复杂的按语境分支（不建议，收益低）。
4. CRC 会变（除非 §5.5 补偿）；旧即时存档/金手指需按项目既有说明处理。
5. `G058.I034`（重复的 `Info`）没有被本路径引用；若别处（SFXML/运行期数据）用到它，改它与本问题无关，也别动。

---

## 7. 证据与脚本索引（都在本目录）

| 文件 | 说明 |
|---|---|
| `scan_keys.py` / `lang_key_refs.txt` | 全 ELF 扫 `0x03900000..` key 与 `lui 0x390` 站点 |
| `map_keys.py` / `key_sites.txt` | key→代码站点（1089 个），按 key 列出 |
| `keys_in_range.py` | 本界面类（0x2B7D30–0x2C9800）引用的 LANG 串 |
| `scan_slots.py` / `slots.txt` | 全 ELF `jal 0x20D980`（hint 槽位取件）站点与槽号 |
| `dis_2C8600.txt` | tick 函数 0x2C86C0–0x2C8930 完整反汇编 |
| `dis_2B8300.txt` / `dis_ctor.txt` | 激活函数 0x2B8140 片段 / 构造 0x2B7D30 |
| `dis_327600.txt` | 另一个类 0x327620（Info⇄军衔，用于排除） |
| `refs_in_range.py` | 类内 UI 模板/字符串引用（证明是 platoon/简报界面） |
| `dump_lang.py` / `lang_g058_hint.txt` | G058 里按钮/提示相关条目（EN） |
| `lang_from_iso.py` / `lang_from_iso.txt` | 从 v33 盘内 LANG 读出的中文与字节（I029/I229/I572/…） |
| `check_iso_sites.py` | 在 v33 ISO 的 ELF 里核对三个补丁点原始字节 |
| `crc_sim.py` | 模拟 A/B 补丁后的 ELF sha256 与 Game CRC |
| `find_pad.py` / `probe_*.py` / `scan_odd.py` / `decode_test.py` | 辅助探查（vtable、常量、填充区、字符集验证） |

外部证据（既有，未改动）：
- `work\analysis\emu\squad_v26\crop_hint_compare.png`（5× 两态对照）、`evid_hint_zoom.png`、`crop_hint.png`、`crop_hint_2char.png`
- `work\analysis\emu\squad_v26\fb_series.json` / `hb_series.json`、`measure_v26.txt`
- `work\analysis\emu\squad_en\hint_squad_auto.png`（未选中态：进入战场/Back/Accept）、`hint_member_selected.png`（Info/Back/Browse）
