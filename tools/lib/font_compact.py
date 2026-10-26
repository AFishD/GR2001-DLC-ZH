# -*- coding: utf-8 -*-
r"""font_compact.py — **字库紧凑重排 + 全盘重编码** (round56 起; round57 修"短串漏网"; round58 补全覆盖面)

## ★ round58 补的是什么 (重编码覆盖面补全 ⇒ 不再靠"扫得够巧")

round57 之后 Lead 普查发现: 盘上**含中文的容器有 30 个** (按容器名统计, 见
`docs/REPORT_reencode_coverage.md`), 而本工具只覆盖 3 个 (LANG×2 + EN SFXML) + ELF 5 段 ⇒
**每重排一轮, 剩下那些容器里的旧编码中文就会被新字库解成别的字**。实证: `MENU.IMG#30
EN_STRINGS.TXT` 从 round46 第一次紧凑重排起就一直是坏的 (它的字节停在 round46 **之前**的
码表上), r57 报告 §6.1 把它列为"待 Lead 决策"。修法 (本文件 r58 新增部分):

  · **容器级文本登记表** `CONTAINER_TEXT_REGISTRY` (★ 按**容器名/模式**登记, 不写死索引):
      `*_STRINGS.RES` / `*_STRINGS.TXT` / `*_SPECIAL_FEATURE.XML` / `IGORHELP.TXT`
    ⇒ 命中即"整个容器都可能载有引擎文本", 不再依赖 `(lba, idx)` 白名单, 也不依赖扫描运气;
  · **容器级判据** (不依赖 C 字符串 / NUL 边界 —— 这正是 `EN_STRINGS.TXT` 那 8 条引号串
    两轮都漏的原因): 容器内**每一段"源 charset 能解出 ≥2 连续汉字"的字节**都重映射,
    阈值与全盘细扫一致 (2); 结构字节零改动 (LANG 格式容器进一步限制在**条目载荷**内,
    长度前缀/属性一个字节不碰); **逐段闭环**校验 (新解 == 源解, 逐字相同), 做不到 ⇒
    抛错、不写盘, 错误信息带**容器名 + 字节偏移**;
  · **一次性"陈旧码表追平"迁移** `STALE_MIGRATIONS` (内容寻址 + 输入盘 sha256 钉死):
    `GR_ZH107` 已经是紧凑盘 ⇒ 布局 0 改动 ⇒ 重编码这一遍本来根本不会跑; 但盘上那批登记容器
    还停在旧码表上, 必须**追平**到现役码表。清单只对 `from_iso_sha256` 那张盘生效
    (下一轮自动失效, 不会误伤), 每条按**槽位字节 sha256** 内容寻址 + 文本指纹;
  · **LZO 字面量原位改写** (`Slot.repack_literal_patch`): 登记容器里有些只差 1~2 个字节,
    而我们的 LZO 压缩器比游戏原压缩器弱 ~3.6% ⇒ 整体重压会**超槽**。改动字节若在 LZO 流里
    是**字面量**, 就只改那几个字面量字节: 帧长逐字节不变、令牌结构不变, 改完回环校验。
    重压能装下时优先走重压 (帧更短), 两条路都失败才中止;
  · **门禁加强** (r58 新增 A3): 对**每一个**登记容器给出结论并逐条校验 ——
      ① 已迁移 ⇒ `现役解(盘上) == 陈旧解(迁移前)` 逐字相同;
      ② 盘上已在现役码表 ⇒ `现役解(盘上) sha256 == 清单记录值`;
      ③ 其余 ⇒ `陈旧解(盘上) == 现役解(盘上)` (该容器与码位无关, 不需要动)。
    三者必居其一 ⇒ "登记容器全覆盖"是**可证**的, 不是"扫得够巧";
  · **报告**: 逐容器列出 段数 / 重映射段数 / 未变段数 / 改了字节数 / 跳过理由。

## ★ round57 修的是什么 (实机 A/B 抓到的回归)

`GR_ZH106` 载入画面把「**请等待！**」显示成「**部等效！**」。根因 = 重编码覆盖面有两个洞:

  ① **扫描阈值 ≥4 连续汉字** ⇒ 只有 3 个字的「请等待」**整个被漏掉**;
  ② **ELF (非 IMG 区) 不在重编码覆盖范围** ⇒ 老码串 `a3 d6 a1 f8 a2 df` 原封不动留在盘上,
     charset 换过码位后, 同一串字节就被新字库解成别的字。

修法 (本文件 r57 新增部分):

  · `SCAN_MIN_CJK` 4 → **2**: 「≥2 连续汉字」就算候选 ⇒ 短串进视野;
  · 新增**细扫** `scan_short_text()`: 粗扫的候选区间下限是 12 B, 而「请等待!」只有 7 B
    (整条串会被丢掉), 所以细扫把下限降到 4 B, 预筛换成 **"区间内含 ≥1 个旧码表的合法对偶码位置"**
    (随机字节命中率 ≈1.8%/位置, 比 "≥4 连续高位字节" 精确约 20 倍) ⇒ 全盘可扫而不爆炸;
  · **判据** (区分真文本 / 二进制巧合, 标定见 `docs/REPORT_elf_reencode_fix.md`):
      ① 段所在"无控制字节极大区间"两侧**都是 0x00** ⇒ 是一条完整 C 字符串;
      ② 整串能被旧码表 greedy 解析**完整消费** (无解不出的字节);
      ③ 串内**对偶码字符占比 ≥ 0.5**  ← 决定性指标: 真文本 0.50~0.75, 二进制巧合 0.00~0.33;
      ④ 串内**至少 1 个对偶码的码位本轮变过** (否则这条串换码后字节一模一样, 根本不用动);
    在 `GR_ZH105` 上, IMG 之外 12 146 段候选里**只**选中 6 段 (= ELF 载入提示条里的 5 条
    「请等待!」+ 1 条与它同串的「载入中...」), **零假阳** —— 那 8 段 pair_ratio=1.00 的
    二进制巧合 (接齿/治飞/能集/概起/移两菜值渡涸销) 全部被③挡下;
  · **已知文本区登记表** `KNOWN_TEXT_REGIONS`: 项目自己的补丁记录里写明的非容器文本区
    (当前 = ELF 的 5 语言载入槽表, 见 `docs/han_v2/BOOT_SCREENS.md` §7.2)。区内的短串
    用同一套流程重映射, 但**不要求③** (那儿的字节是我们自己写进去的) ⇒ 未来再重排、
    连「载入中」的码位也变了时, 这里不会重演 GR_ZH106 的漏网;
  · **门禁加强**: 每一段都做"旧码表解基底字节 vs 新码表解盘上字节"**逐字比对** (A 类检查),
    任何一段做不到 ⇒ 中止、把盘恢复成原样、不写 charset。

## round56 原文 (实现主体, 仍然有效)

## 用户要什么

> 每次构筑时都把**可用空格整理到最末端**, 而不是像现在这样零散地分布在图片中。

盘上 1504 个对偶槽位 (slot) 里, 1175 个在用、329 个空着; 空位**零散**地散在
row 2/9/10/11/13/18/19/20/21/22/23/24 (`GR_ZH105` 实测)。本工具每一轮构筑做两件事:

  ① **搬字**: 把在用字形按确定性顺序 (当前 slot 升序 = 图集行主序) 压到 **slot 0..N-1**,
     其余格**全部清零** ⇒ 可用格从此**整齐地待在末尾 `slot N..1503`**;
  ② **重编码**: 码位变了 ⇒ 盘上**所有**旧编码文本必须整体换码。这一条是本轮重写的重点:
     旧工具 `repack_font.py` 只重编码"可注入文本表" ⇒ 漏掉了 **SFXML 的 `name=` 标题属性**,
     这正是 round51 查实的「特别收录标题变成别的字」的根因
     (见 `docs/REPORT_single_cell_verify.md` §2)。

## 与旧工具 (repack_font.py) 的关系

   · **搬字逻辑**: 复用 `repack_font` 里已经闭环的像素容器/格位口径
     (`Atlas` / `enumerate_cells` / `protect_mask` / `classify` / `char_order`) —— 这部分
     round46 起就在实机上跑通了, 不重写、不复制, 直接 import 用 (该文件一行都不改);
   · **重编码**: 全新的一套 (本文件), 覆盖面见下;
   · **门禁**: 全新的一套 (本文件): 写盘前 + 写盘后都做"逐字一致"自检。

## 重编码覆盖面 (逐容器, 全部实测)

| # | 容器 | 做法 | 为什么 |
|---|---|---|---|
| ① | 3 张可注入文本表 (`--inject-csv` 的每一份) | 拷一份**只清 `text_zh` 列** ⇒ 注入器认为每行都被人工改过 ⇒ 用**新** charset 重编 (`repack_font.make_reencode_tables`, 直接复用) | 用户译文一个字不动, 但字节整体换码 |
| ② | **SFXML 的 `name=` 属性** (`MENU.IMG#283`) | 就地**逐字**重映射 (`旧码位 → 新码位`, 对偶↔对偶 = 2 字节→2 字节), 重压回写 | ★ 旧工具漏的就是这里 (round51 根因) |
| ③ | SFXML 的 `<text>` 元素 | **同一份容器级重映射**顺带覆盖 (`<text>` 也在 SFXML blob 里) | 已含在 ② 的容器重写里; 注入器之后还会按用户表重写一遍, 两条路一致 |
| ④ | `EN_STRINGS.RES` 的两份副本 (`MENU.IMG#25` / `GR.IMG#902`) | 逐**条目载荷**重映射 (长度字段/attr 一个字节不动), 重压回写 | 注入器会重写"改过的行"; **没改过的行**靠这一步才不会变成别的字 |
| ⑤ | **全盘扫描兜底** | 粗扫 (≥12 B 区间, "≥2 连续汉字") 找长文本; **细扫** (≥4 B 区间, 对偶码预筛, "≥2 连续汉字") 找**短串** —— 落在已重写容器里的算已覆盖; 落在**别的"真文本"容器**里的就地重映射 (走通用容器重写); 落在 **IMG 之外**的真文本段 (粗扫判据 `texty` 或细扫判据 `short_text`) 一律**原位重映射** (同长度覆盖); 其余按判据归为**二进制巧合**并逐项报告 | "漏一个容器/一条短串就出事" |
| ⑥ | **已知文本区登记表** (r57) | `KNOWN_TEXT_REGIONS` = 项目补丁记录里写明的非容器文本区 (ELF 5 语言载入槽表): 区内的 C 字符串**免除判据③**, 照样原位重映射 | 那儿的字节是我们自己写进去的; 免除"对偶码占比"门槛后, 以后再重排也不会漏 |
| ★ | **全盘一致性自检 (硬门禁)** | 见下 | 保险丝 |

## ★ 全盘一致性自检 (硬门禁)

写盘**之后**、改 charset 之前, 跑完整门禁; 任何一项不过 ⇒ **中止 (不写 charset) 并删除刚写出的盘**:

  **A. 重写容器的逐字闭环** (最强口径): 对每个被重写的容器,
     `新 charset 解(盘上现在的字节)` 必须与 `旧 charset 解(基底字节)` **逐字相同**;
     另断言: 改动字节**全部**落在"重映射过的字符区间"内、`<0x80` 的字节一个都没变、
     IMG 条目表的 `off/stored/real` 一个字节没动、解压总长不变、重压帧 ≤ 槽位、回读解压逐字节一致。
  **B. 全盘扫描复核**:
     · 基底上全盘扫出的每一段"干净 ≥4 连续汉字"都按容器归类;
     · 落在**重写容器**里的段 —— 由 A 覆盖;
     · 落在**未重写容器**里的段 —— 按标定判据 (见下) 分类:
         `真文本` ⇒ **必须**已被重写, 否则中止 (并列出容器/偏移);
         `二进制巧合` ⇒ 跳过, 逐容器计数写进报告 (含证据);
     · 判据标定 (`docs/REPORT_font_compact.md` §4): 真文本段 =
       `最长汉字串 ≥6 且 汉字数 ≥16 且 不同汉字 ≥10 且 对偶码汉字占比 ≥0.5`。
       在 `GR_ZH105` 上, 这条判据**只**选出 3 个容器 = `EN_STRINGS.RES`×2 + `EN_SPECIAL_FEATURE.XML`
       (= 全部已知文本容器), 而 `.BMZ/.PSS/.PAK/.IDC/...` 的 65 万段巧合**全部**被排除
       (巧合段的"对偶码汉字占比" = 0.00~0.07, 真文本 = 0.87)。
  **C. 字库/字符集自检**: 图集回读 == 目标图; 每个字的像素逐像素原样落到新格;
     FT 记录矩形覆盖的像素 0 改动; 48B 包头逐字节不动; `charset` 的 `pair_of` 逐字等于设计值,
     其它字段 (含 `codes`) 逐字节不变。
  **D. 紧凑性断言**: 在用字形 = **slot 0..N-1**, 空闲 = **slot N..1503** (逐槽位核对)。
  **E. 幂等**: 对产物再跑一次 `plan()` ⇒ 0 像素改动 / 0 码位变更 (产物 sha256 不变)。

## 用法

  # 只算不写 (看会搬多少字、会不会动文本)
  python tools/iso_build/font_compact.py --iso work/builds/GR_ZH105/GR_ZH105.iso --dry-run

  # 出盘 + 改 charset + 另出"强制重编码"文本表
  python tools/iso_build/font_compact.py --iso <src.iso> --out-iso <dst.iso> \
      --text-src work/builds/GR_ZH105/text --reencode-out <out>/temp/font_compact/reencode \
      --report <out>/temp/font_compact/compact_report.json

  # 幂等复核 (对已紧凑的盘再跑): 应报"无需重排", 且**不产出任何文件**
  python tools/iso_build/font_compact.py --iso <dst.iso> --dry-run

★ 被 `make_build.py` 当作构筑的一等步骤自动调用 (文本注入**之前**), 见 `--no-font-compact`。

⚠ 人工单跑的前提: charset JSON 必须与这张盘**同一版本** (理由同旧工具: 重排按 charset 给的
   槽位去图集取字形)。`plan_compact()` 里有"大面积取空就拒绝"的粗探针 + 逐字像素自检。
"""
import argparse
import collections
import io
import json
import os
import re
import shutil
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:                                                    # noqa: BLE001
    pass

import numpy as np                                                   # noqa: E402
import tcslib                                                        # noqa: E402
import dump_font                                                     # noqa: E402
import repack_font as RF                                             # noqa: E402

RE_MOD = re                # ★ 别名: 本文件里多处形参叫 `re` (重编码方案 dict), 会遮蔽 re 模块

TOOL = 'tools/iso_build/font_compact.py'
TOOL_VERSION = 'r58.1'
ROUND = 'round58'
NCOL, CW, CH = tcslib.NCOL, tcslib.CW, tcslib.CH
LEAD_LO, LEAD_HI = tcslib.LEAD_LO, tcslib.LEAD_HI


def _sync_geometry(iso_path, verbose=True):
    """★ 2026-10-20 fix/font: 几何常量不再信 **import 时**的快照, 一律以**盘上 ELF 立即数**为准。

    旧 tcslib 的 62 列 / Y0=2 / SKIP_ROWS=3 让本模块算出的格位全错 (而调用方看不出来);
    现在 `repack_font.sync_geometry_from_iso()` 会从盘上 VA 0x4170AC/E8/F8 重读并**以盘为准**
    覆写 tcslib, 本函数再把本模块的名字重新绑定; decode gate 也从盘上 4 站点现读。
    返回 dict (NCOL/SKIP_ROWS/Y0/gate/...), 便于写进报告。
    """
    global NCOL, CW, CH, LEAD_LO, LEAD_HI
    g = RF.sync_geometry_from_iso(iso_path, verbose=verbose)
    iso = tcslib.Iso(iso_path)
    try:
        gate = tcslib.read_decode_gate(iso)
    finally:
        iso.close()
    if gate != tcslib.LEAD_HI:
        if verbose:
            print('  [geom] ★ 盘上 decode gate=0x%02X ≠ tcslib.LEAD_HI=0x%02X ⇒ 以盘为准'
                  % (gate, tcslib.LEAD_HI), flush=True)
        tcslib.LEAD_HI = tcslib.PAIR_LEAD_HI = gate
    NCOL, CW, CH = tcslib.NCOL, tcslib.CW, tcslib.CH
    LEAD_LO, LEAD_HI = tcslib.LEAD_LO, tcslib.LEAD_HI
    g['gate'] = LEAD_HI
    assert (NCOL, CW, CH) == (g['NCOL'], tcslib.CW, tcslib.CH), \
        'font_compact: NCOL=%r 与盘上 ELF 立即数 %r 不一致' % (NCOL, g['NCOL'])
    return g
# 确定性顺序 = 旧工具同款: 按**当前槽位**升序 (图集行主序), 同槽按码点 ⇒ 重排后再跑是 0 改动
ORDER_KEY = 'current_slot_asc'
MENU_LBA, GR_LBA = 776286, 19175

# ── 全盘扫描 / "真文本 vs 二进制巧合" 判据 (阈值标定见报告 §4; 在 GR_ZH105 上零误报) ──
SCAN_MIN_CJK = 2                # ★ r57: 从 4 降到 2 —— 只有 3 个字的「请等待」曾被 ≥4 整个漏掉
SCAN_MIN_BYTES = 4              # 容器展开态: 候选区间最小长度
SCAN_RAW_MIN_BYTES = 12         # 粗扫 (长文本): 全盘原始字节的候选区间下限
SCAN_SHORT_MIN_BYTES = 4        # ★ r57 细扫 (短串): 下限 4 B = 2 个汉字
SCAN_RUNHI = 4                  # 预处理: 段内必须有 ≥4 个连续高位字节 (真中文的必要条件)
SCAN_CHUNK = 1 << 24
SCAN_PAD = 4096                 # 分块扫描的重叠区 (避免真文本被块边界切断)
TEXTY_MIN_CJK = 16              # 真文本: 段内汉字数
TEXTY_MIN_DISTINCT = 10         # 真文本: 不同汉字数
TEXTY_MIN_PAIR_RATIO = 0.5      # 真文本: 汉字里靠"对偶码"(2 字节) 解出的比例
TEXTY_MIN_MAXRUN = 6            # 真文本: 最长连续汉字
SHORT_MIN_PAIR_RATIO = 0.5      # ★ r57 短串真文本判据③: 串内**对偶码字符占比**下限
SHORT_MIN_CSTR_BYTES = 4        # 短串判据: 串最短长度 (2 个对偶码汉字 = 4 B)
BAD_TEXT_BYTES = frozenset(list(range(0x00, 0x20)) + list(range(0x7F, 0xA0))) - {9, 10, 13}

# ── ★ r57: 已知文本区登记表 (非容器区; 项目自己的补丁记录里写明的) ──
#   区内的 C 字符串**免除判据③** (不要求"对偶码占比 ≥0.5") —— 那儿的字节是我们自己写进去的,
#   而未来再重排时可能连「载入中」的码位也变, 那条串 (对偶码占比只有 0.33) 必须照样换码。
ELF_LBA_HINT = 295              # PS2 ELF 所在 LBA (GR_ZH105/106 实测)
ELF_MAGIC = b'\x7fELF\x01\x01\x01'
KNOWN_TEXT_REGIONS = (
    dict(name='ELF 载入提示条 5 语言槽表 (Loading... / Please wait!)',
         elf_rel=(0x478020, 0x4780F4),      # ELF 相对偏移; 绝对 = ELF 基址 + 该值
         ratio_min=0.0, min_cjk=2,
         provenance='docs/han_v2/BOOT_SCREENS.md §7.2 (GR_ZH15 起 tmp/bootscreen/elf_patch.py '
                    '写入的 5 语言槽: FR/DE/IT/ES/EN × {载入中…, 请等待!})'),
)

# ═══════════════════════ ★ r58: 容器级文本登记表 ═══════════════════════
# 为什么需要 (round58 的缘起):
#   round57 修完「请等待!」之后 Lead 普查: 盘上含中文的容器有 30 个, 而本工具的"已知文本容器"
#   是按 `(lba, idx)` 写死 3 个 + 全盘扫描的 `texty` 判据 (要求"最长汉字串 ≥6")。短串/键值表
#   因此系统性漏网: `MENU.IMG#30 EN_STRINGS.TXT` 的中文值是 `"传感器"` 这样的 **8 字节引号串**
#   (最长 3 个汉字, 且**不是 NUL 结尾**的 C 字符串 ⇒ 细扫的判据①也抓不到) ⇒ 它从 round46
#   第一次紧凑重排起就一直是坏的 (r57 报告 §6.1 "待 Lead 决策" 说的就是它)。
#
# 判据 (**容器级**; 与全盘细扫的"短串"判据不同, 这里不要求 C 字符串边界):
#   ① 容器名匹配登记表 ⇒ 整个容器都按"可能载有引擎文本"处理;
#   ② 容器内每一段"源 charset 能解出 ≥ `min_cjk` 连续汉字"的字节都是重映射候选 (阈值 2);
#   ③ 结构字节零改动: 改动必须落在"被重映射的字符区间"内; LANG 格式容器进一步限制在
#      **条目载荷**内 (长度前缀 / 属性字节一个都不碰);
#   ④ 逐段闭环: `目标 charset 解(改后) == 源 charset 解(改前)` 逐字相同;
#   ⑤ 逐容器报告: 段数 / 重映射段数 / 未变段数 / 改动字节数 / 跳过理由。
CONTAINER_TEXT_REGISTRY = (
    dict(pattern=r'^(?:EN|DE|ES|FR|IT)_STRINGS\.RES$', min_cjk=2, kind='lang',
         why='语言表 (LANG 格式, 逐条目载荷): 注入器只重写"用户改过的行" ⇒ 没改的行必须由本工具'
             '整体换码, 否则下次重排后那些行会解成别的字',
         provenance='docs/REPORT_font_compact.md §3 ④; GR_ZH105 实测 2232 条目'),
    dict(pattern=r'^(?:EN|DE|ES|FR|IT)_STRINGS\.TXT$', min_cjk=2, kind='text',
         why='纯文本键值表 (`\\r\\n\\t"键"\\t"值"`): 中文值只有 3~4 个汉字, 且**不是 NUL 结尾**'
             '的 C 字符串 ⇒ 细扫判据①抓不到 —— round57 §6.1 待决的那 8 条串就在这里',
         provenance='docs/REPORT_elf_reencode_fix.md §6.1 (MENU.IMG#30); '
                    'docs/PATCH_INVENTORY.md「GR_ZH57 … EN_STRINGS.TXT 条目重写」'),
    dict(pattern=r'^(?:EN|DE|ES|FR|IT)_SPECIAL_FEATURE\.XML$', min_cjk=2, kind='sfxml',
         why='SFXML: `name=` 属性 + `<text>` 元素都会显示; `name=` 属性 round51 起才被覆盖',
         provenance='docs/REPORT_single_cell_verify.md §2 (round51 根因)'),
    dict(pattern=r'^IGORHELP\.TXT$', min_cjk=2, kind='text',
         why='纯文本帮助文件 (无 NUL 边界, 无固定行长)',
         provenance='GR.IMG#4062 (全容器普查 txt 类)'),
)


def registry_match(name):
    """容器名 → 登记表条目; 没登记返回 None。★ 一律按**名字**匹配, 不写死索引。"""
    for e in CONTAINER_TEXT_REGISTRY:
        if re.match(e['pattern'], name or '', re.I):
            return e
    return None


# ═══════════════ ★ r58: 一次性"陈旧码表追平"迁移 (内容寻址 + 盘指纹钉死) ═══════════════
#
# 为什么需要: `GR_ZH107` 已经是**紧凑盘** (在用字形 = slot 0..1174) ⇒ `plan_compact()` 报 0 改动
# ⇒ 按老流程 "重编码" 这一遍根本不会跑, 而那批登记容器**还停在旧码表上** (round46 第一次紧凑
# 重排漏掉的), 不追平就会一直显示错字 (要等下一次真重排才被覆盖)。
#
# 三层安全:
#   ① `from_iso_sha256`: 清单**只对 GR_ZH107 那张盘**生效 (换盘 / 下一轮自动失效, 不会误伤);
#   ② `entries` 按**槽位字节 sha256 内容寻址** (不按索引) + 逐条文本指纹; 角色只有两种:
#        `migrate` = 该容器的字节是**陈旧码表**写的 ⇒ 追平到现役;
#        `current` = 该容器**已经在现役码表上** (陈旧解反而是乱码) ⇒ 绝不能按陈旧码表重映射;
#      清单里没有、但命中登记表的容器 ⇒ 由门禁证明"陈旧解 == 现役解"(与码位无关, 不需要动);
#   ③ 门禁 A3 对**每一个**登记容器逐条校验 (见 gate())。
STALE_MIGRATIONS = (
    dict(
        name='r58: 登记容器"陈旧码表追平" (round46 第一次紧凑重排漏掉的那批)',
        from_iso_sha256='de918f668301e8a15286b0dc55e30715491b0bc9b415d91b1bc3232919828ef0',
        from_iso_version='GR_ZH107',
        stale_charset='work/builds/GR_ZH94/temp/r46/charset_before_repack.json',
        stale_label='G0 = round46 第一次紧凑重排**之前**的码表',
        provenance=(
            'G0 判定依据 (三条独立证据): ① 仓库里 6 份 round46 前的 charset 快照'
            '(GR_ZH92/93/94 的 font/charset_matching_this_disk、GR_ZH94/temp/r46/'
            'charset_before_repack、GR_ZH95/temp/font_repack/charset_before、'
            'work/_planc/charset_before_planc) 解 MENU.IMG#30 的 10 个键值**完全一致**; '
            '② 那 10 个值逐条等于 docs/PATCH_INVENTORY.md「GR_ZH57 … MENU.IMG EN_STRINGS.TXT '
            '条目重写」记录的**设计值** (追加弹药/望远镜/传感器/定向雷/爆破装药/无限制/仅手枪/'
            '仅主武器/标准装备/仅原版 —— 含"额不在字表 ⇒ 追加弹药"这个细节); '
            '③ round46 之后的 G1 (charset_before_r56) 解出来是 色加弹、/昨远镜/亲手枪/亲主武器/'
            '亲原版 (4 条已坏), 现役 G2 解出来是 乎加弹巡/航远镜/侧抛器/… (更坏) '
            '⇒ G1/G2 都是"被打坏"的读法, 只有 G0 是原字。详见 '
            'docs/REPORT_reencode_coverage.md §2。'),
        entries=(
            dict(role='migrate', name='EN_STRINGS.TXT', where='MENU.IMG#30',
                 slot_sha256='7706ff1b6bf0f788d0ea1526d45ad58e4c732e83f38b219ba5d3f490c8bd28c0',
                 stale_text_sha256='97c21b5eb02b77df2a77173f3d4f9bae00fcde1a5cb1640965a96ca310672df5',
                 current_text_sha256='9f71cb0db9ec0702c17f2cd63b99ab40ab1d8cd5aa8225245f095ad241aa7159',
                 changed_bytes=15,
                 expect_contains=('追加弹药', '望远镜', '传感器', '爆破装药', '无限制',
                                  '仅手枪', '仅主武器', '标准装备', '仅原版'),
                 why='round57 §6.1 待决的那 8 条引号串; 陈旧→现役 13 个字 / 26 字节 (实际不同 15 B)'),
            dict(role='migrate', name='DE_STRINGS.RES', where='MENU.IMG#26 + GR.IMG#900 (同字节)',
                 slot_sha256='9e89145adca104e4a71cd5f99322477e360851741ecb0deef7a7e73fc8b4efcf',
                 stale_text_sha256='1e23e5ac56d3129088fabbf4e6974e2a1da85f821d585b4adf8c775c0fc80b18',
                 current_text_sha256='7000fd5651d702af733cd0e81d974d8efa1f68e44b189311e99f4fcc2964a2cc',
                 changed_bytes=1,
                 expect_contains=(),
                 why='陈旧/现役只差 1 个字符 (德语 "Hauptmenü" 里的重音字节撞上对偶码 a8 b9); '
                     '整体重压超槽 1985 B ⇒ 走 LZO 字面量原位改写'),
            dict(role='migrate', name='ES_STRINGS.RES', where='MENU.IMG#27 + GR.IMG#904 (同字节)',
                 slot_sha256='eefcf8351ebf83e5dbdeeed34e681bcc18ea09f0b29aa43947519d3f736bedf9',
                 stale_text_sha256='de54cd72af3702c60804691c245dab6d62ceab99ed52fbae8a6250f4c814fed3',
                 current_text_sha256='608a6410b268a9f8c4d784ac7da24a01303f9c5ca02b4fb3660361bd636e9db6',
                 changed_bytes=1,
                 expect_contains=(),
                 why='陈旧/现役只差 1 个字符 (西语 "Menú Principal" 里的重音字节撞上对偶码 a8 b2); '
                     '整体重压超槽 1989 B ⇒ 走 LZO 字面量原位改写'),
            dict(role='current', name='EN_STRINGS.RES', where='MENU.IMG#25',
                 slot_sha256='077269dedae5924d2fa433b44578ec3acd4a264c62264a797e8d8b1aad29a0a7',
                 current_text_sha256='8a4445d6128c38e826c8bd9534fdd299926be1652349b45a0dd0b72a65b2709d',
                 why='注入器每轮整表重写的语言表; 盘上已经是现役码表 (陈旧解是乱码) ⇒ '
                     '**不能**按陈旧码表重映射'),
            dict(role='current', name='EN_STRINGS.RES', where='GR.IMG#902',
                 slot_sha256='c1d1de4c015973cb72fe9cc4aa9550b558d42c6a3b929ec05afde26ce8144021',
                 current_text_sha256='1d42458b3112fdca155885558c84f706c1070b4e6b3a812f5e133709f542954c',
                 why='同上 (GR 侧副本)'),
            dict(role='current', name='EN_SPECIAL_FEATURE.XML', where='MENU.IMG#283',
                 slot_sha256='58c491f2c268f365521a918bd6985f29ebe21ee20398774e0ba20f8c576e38b0',
                 current_text_sha256='174c413ea710788c6e56ef4ba1c5213d8541cb6d03c9fb76a4cf19b8f095c280',
                 why='注入器每轮重写的 SFXML; 盘上已经是现役码表 (陈旧解是 堡兵/质家1 这类乱码) ⇒ '
                     '**不能**按陈旧码表重映射'),
        ),
    ),
)


def pending_migration(iso_sha256, verbose=False):
    """输入盘的 sha256 → 命中的迁移清单 (只读; 没有返回 None)。"""
    for m in STALE_MIGRATIONS:
        if m['from_iso_sha256'] == iso_sha256:
            return m
    return None


def migration_index(mig):
    """迁移清单 → {槽位 sha256: 记录}。"""
    if not mig:
        return {}
    return dict((e['slot_sha256'], e) for e in mig['entries'])


def resolve_repo_path(p):
    """清单里的路径按**仓库相对**解析 (与工具落点无关, 换机也能跑)。"""
    return p if os.path.isabs(p) else os.path.join(REPO, p)


# SFXML 里"引擎会拿去显示"的属性 (round51 从 SFXML 结构实测得出)
SFXML_TEXT_ATTRS = ('name',)
SFXML_ITEM_RE = re.compile(rb'<(item|group|studio)\b([^>]*)>')
SFXML_ATTR_RE = re.compile(rb'([A-Za-z_][\w:.-]*)\s*=\s*"([^"]*)"')
SFXML_TEXT_EL_RE = re.compile(rb'<text>([^<]*)</text>')


class CompactError(Exception):
    """门禁不过 / 结构不对 —— 一律**中止且不写共享状态**。"""


def rel(p):
    try:
        r = os.path.relpath(p, REPO)
    except ValueError:
        return p.replace('\\', '/')
    return r.replace('\\', '/') if not r.startswith('..') else p.replace('\\', '/')


def sha256_b(b):
    import hashlib
    return hashlib.sha256(b).hexdigest()


# ═══════════════════════ ① 字符集视角 (旧 → 新) ═══════════════════════

def charset_view(cs_old, pair_new):
    """拿旧 charset + 新的 `pair_of` 造一个**只改码位**的 Charset 实例 (其余字段原样)。

    ★ 铁律: 只改 `pair_of` 的码位 —— `codes` (单字节码) 一个都不动 ⇒
      单字节字形的采样窗 (FT 记录) 不需要动, 文本里的单字节字符也逐字节不变。
    """
    cs = tcslib.Charset.__new__(tcslib.Charset)
    cs.enc_single = dict(cs_old.enc_single)
    cs.enc_pair = {ch: tuple(pair_new[ch]) for ch in cs_old.enc_pair}
    cs.codes = dict(cs_old.codes)
    cs.pair_of = {v: k for k, v in cs.enc_pair.items()}
    return cs


class CodeMap:
    """旧 charset → 新 charset 的**逐字**码位映射 (字节级重映射引擎)。

    · `remap_units(data)`: 用引擎同款 greedy 规则把 `data` 解成 (字节区间, 字符),
      再逐字把**新编码**写回**同一字节区间** —— 长度必须逐字相等, 否则抛 `CompactError`;
    · 自检: 重映射后用新 charset 解回来, 必须与旧 charset 解出来的**逐字相同**。
    """

    def __init__(self, cs_old, cs_new):
        self.old, self.new = cs_old, cs_new
        self.changed_pairs = set()
        for p, ch in cs_old.pair_of.items():
            if cs_new.pair_of.get(p) != ch:
                self.changed_pairs.add(p)
        for p, ch in cs_new.pair_of.items():
            if cs_old.pair_of.get(p) != ch:
                self.changed_pairs.add(p)

    def remap_units(self, data, label='?'):
        """返回 (new_bytes, stats) —— stats: units/changed/bytes/only_hi/spans。"""
        text, offs = self.old.decode(data)
        n = len(data)
        out = bytearray(data)
        units = changed = nbytes = 0
        only_hi = True
        spans = []
        for i, ch in enumerate(text):
            a = offs[i]
            b = offs[i + 1] if i + 1 < len(text) else n
            old_b = data[a:b]
            units += 1
            try:
                new_b = self.new.encode_strict(ch)
            except tcslib.CharsetError as e:
                raise CompactError('%s: 字符 %r (U+%04X, 字节 %s) 在新 charset 里编不出来: %s'
                                   % (label, ch, ord(ch), old_b.hex(' '), e))
            if len(new_b) != len(old_b):
                raise CompactError(
                    '%s: 字符 %r 的编码长度变了 (%d→%d 字节, 字节 %s) —— 拒绝改写'
                    % (label, ch, len(old_b), len(new_b), old_b.hex(' ')))
            if new_b != old_b:
                for k in range(len(new_b)):
                    if new_b[k] != old_b[k] and (new_b[k] < 0x80 or old_b[k] < 0x80):
                        only_hi = False
                out[a:b] = new_b
                changed += 1
                nbytes += len(new_b)
                spans.append((a, b))
        new_data = bytes(out)
        back, _ = self.new.decode(new_data)
        if back != text:
            k = next((i for i in range(min(len(back), len(text))) if back[i] != text[i]),
                     min(len(back), len(text)))
            raise CompactError('%s: 重映射后**解回来不是同一个文本** @%d (%r → %r)'
                               % (label, k, text[max(0, k - 6):k + 6],
                                  back[max(0, k - 6):k + 6]))
        # 改动的字节必须全部落在"被重映射的字符区间"内
        out_of_span = [i for i in range(n) if out[i] != data[i]
                       and not any(a <= i < b for (a, b) in spans)]
        if out_of_span:
            raise CompactError('%s: 有改动落在字符区间之外 (%s)' % (label, out_of_span[:5]))
        return new_data, dict(units=units, changed_units=changed, changed_bytes=nbytes,
                              spans=spans, only_high_bytes=only_hi)


# ═══════════════════════ ② 容器 (LZO 子流槽) 读写 ═══════════════════════

def lzo1x_literal_origins(payload, out_size):
    """★ r58: LZO1X 解码 + **逐字节来源标注** (给"字面量原位改写"用)。

    返回 `(out, origin, err)`; `origin[i]` = 输出第 i 个字节在 `payload` 里的**字面量**偏移,
    或 -1 (该字节是匹配拷贝/RLE 展出来的)。

    ★ 逐句照抄项目自己的解码器 `tools/gr_tools/lz77_decode.py::lzo1x_decompress`
      (与 ffmpeg av_lzo1x_decode 逐位一致), **只多记一份来源** —— 不重新逆向、不改那个文件。
      用途: LZO 的字面量是"原样拷贝"的裸数据字节 ⇒ 只改字面量的**值**不改变流结构、
      也不改帧长; 而匹配拷贝是从**已解出**的输出里复制 ⇒ 改了字面量, 后续从同一位置复制出来的
      字节自然也跟着变 (正是我们要的)。
    """
    data, ip, n = payload, 0, len(payload)
    out, origin = bytearray(), []

    def GETB():
        nonlocal ip
        if ip >= n:
            raise IndexError('input depleted at ip=%d' % ip)
        b = data[ip]
        ip += 1
        return b

    def emit_lit(cnt):
        for k in range(cnt):
            out.append(data[ip + k])
            origin.append(ip + k)
        return cnt

    def emit_match(cnt, back):
        o = len(out)
        for k in range(cnt):
            out.append(out[o - back + k])
            origin.append(-1)

    state, err = 0, None
    try:
        x = GETB()
        if x > 17:                                  # 首令牌: 字面量段
            ip += emit_lit(x - 17)
            x = GETB()
        while err is None:
            if out_size is not None and len(out) >= out_size:
                break                               # 已达声明输出长度 (尾 3 字节尾域)
            if x > 15:
                if x > 63:                          # M2
                    cnt = (x >> 5) - 1
                    back = (GETB() << 3) + ((x >> 2) & 7) + 1
                elif x > 31:                        # M3
                    cnt = x & 31
                    if cnt == 0:
                        while True:
                            x = GETB()
                            if x:
                                cnt += 31 + x
                                break
                            cnt += 255
                    x = GETB()
                    back = (GETB() << 6) + (x >> 2) + 1
                else:                               # M1 (back == 1<<14 ⇒ 流结束)
                    cnt = x & 7
                    if cnt == 0:
                        while True:
                            x = GETB()
                            if x:
                                cnt += 7 + x
                                break
                            cnt += 255
                    back = (1 << 14) + ((x & 8) << 11)
                    x = GETB()
                    back += (GETB() << 6) + (x >> 2)
                    if back == (1 << 14):
                        break
            elif not state:                         # 长字面量段
                cnt = x & 15
                if cnt == 0:
                    while True:
                        x = GETB()
                        if x:
                            cnt += 15 + x
                            break
                        cnt += 255
                ip += emit_lit(cnt + 3)
                x = GETB()
                if x > 15:
                    continue
                cnt = 1
                back = (1 << 11) + (GETB() << 2) + (x >> 2) + 1
            else:                                   # M4
                cnt = 0
                back = (GETB() << 2) + (x >> 2) + 1
            o = len(out)
            if back > o:
                err = 'INVALID BACK %d at out=%d ip=%d' % (back, o, ip - 1)
                break
            emit_match(cnt + 2, back)
            state = cnt = x & 3                     # 匹配后置字面量
            ip += emit_lit(cnt)
            if out_size is not None and len(out) >= out_size:
                break
            if ip >= n:
                break
            x = GETB()
    except IndexError as e:                                          # noqa: BLE001
        err = str(e)
    return bytes(out), origin, err


class Slot:
    """一个 IMG 条目在盘上占的槽位: `[off/stored/real]` + LZO 子流帧。

    ★ 重压时**未变的子流原帧照搬** (只重压真正变了的) ⇒ 帧长几乎不涨, 天然不超槽;
    ★ 写回只覆盖该条目自己的槽 (off..off+stored), **IMG 条目表一个字节都不动**。
    """

    def __init__(self, iso, tag, lba, idx):
        self.iso, self.tag, self.lba, self.idx = iso, tag, lba, idx
        self.entry = iso.img_entry(lba, idx)
        self.name = self.entry['name']
        self.slot = self.entry['stored']
        self.raw = iso.read(self.entry['iso_off'], self.slot)
        self.subs = tcslib.lzo_subs(self.raw)
        if self.subs:
            self.mode = 'lzo'
            self.blob = b''.join(s[0] for s in self.subs)
            self.sizes = [s[2] for s in self.subs]
            self.raws = [self.raw[s[3]:s[3] + 8 + s[1]] for s in self.subs]
            last = self.subs[-1]
            used = last[3] + 8 + last[1]
            self.tail = self.raw[used:]
        else:
            self.mode = 'raw'
            self.blob = self.raw
            self.sizes, self.raws, self.tail = [], [], b''

    @property
    def key(self):
        return ('%s#%d' % ('MENU.IMG' if self.lba == MENU_LBA else 'GR.IMG', self.idx))

    def repack(self, new_blob, label='?'):
        """新 blob (长度必须与原件相同) → 帧字节 (≤ 槽位)。

        ★ r58: 重压**装不下**时自动退到 `repack_literal_patch()` (字面量原位改写, 帧长不变)。
          为什么需要: 我们的 LZO 压缩器比游戏原压缩器弱 ~3.6% ⇒ 有些容器 (例如
          `DE_STRINGS.RES` 9 个子流, 整体重压 +1985 B) 只要改 1 个字节就超槽, 但那一两个字节
          在流里恰好是**字面量** ⇒ 原位改值即可, 连帧长都不用变。
          返回 `(frame, n_recompressed, frame_len, method)`; `method` ∈ {'recompress',
          'literal-patch'}。
        """
        if len(new_blob) != len(self.blob):
            raise CompactError('%s: 解压总长变了 %+d B' % (label, len(new_blob) - len(self.blob)))
        if self.mode == 'raw':
            return new_blob, 0, len(new_blob), 'raw'
        frame = bytearray()
        q = 0
        n_rep = 0
        for k, S in enumerate(self.sizes):
            c = new_blob[q:q + S]
            q += S
            if c == self.subs[k][0]:
                frame += self.raws[k]                          # 未变子流: 原压缩帧照搬
                continue
            cc = tcslib.lzo_compress(c, level=7, use_m1=True, use_m4=True)
            back, err, _ = tcslib.lzo1x_decompress(cc, out_size=S)
            if err is not None or back != c:
                raise CompactError('%s: 子流 %d 重压回环失败' % (label, k))
            frame += struct.pack('<II', len(cc), S) + cc
            n_rep += 1
        over = len(frame) - self.slot
        if over <= 0:
            return bytes(frame), n_rep, len(frame), 'recompress'
        # ---- ★ r58 兜底: LZO 字面量原位改写 (帧长逐字节不变) ----
        alt = self.repack_literal_patch(new_blob, label)
        if alt is None:
            raise CompactError('%s: 重压后超槽 %d B (帧 %d > 槽 %d), 且改动字节里有**非字面量** '
                               '(匹配拷贝) ⇒ 无法原位改写 —— 需要扩容条目, 本工具拒绝 '
                               '(会动 IMG 条目表)' % (label, over, len(frame), self.slot))
        return alt[0], 0, len(alt[0]), 'literal-patch'

    def repack_literal_patch(self, new_blob, label='?'):
        """★ r58: 只改 LZO 流里**字面量**的值 ⇒ 帧长逐字节不变、令牌结构不变。

        返回 `(frame, n_patched)` 或 None (有任何改动字节是匹配拷贝 ⇒ 做不到)。
        ★ 改完**逐子流回环校验** (解出来必须 == new_blob), 校验不过一律返回 None。
        """
        if self.mode != 'lzo':
            return None
        frame = bytearray()
        n_patched = 0
        q = 0
        for k, S in enumerate(self.sizes):
            old_c = self.blob[q:q + S]
            new_c = new_blob[q:q + S]
            q += S
            if old_c == new_c:
                frame += self.raws[k]                          # 原帧照搬
                continue
            diffs = [i for i in range(S) if old_c[i] != new_c[i]]
            pay = bytearray(self.raws[k][8:])
            out, origin, err = lzo1x_literal_origins(bytes(pay), out_size=S)
            if err is not None or out != old_c:
                return None
            if any(origin[i] < 0 for i in diffs):
                return None                                    # 有匹配拷贝字节 ⇒ 原位改不了
            for i in diffs:
                pay[origin[i]] = new_c[i]
            back, err2, _ = tcslib.lzo1x_decompress(bytes(pay), out_size=S)
            if err2 is not None or back != new_c:               # 回环校验
                return None
            frame += self.raws[k][:8] + bytes(pay)              # 头 8 字节原样 (comp_len 不变)
            n_patched += len(diffs)
        if len(frame) != len(self.raw):                         # 帧长必须逐字节不变
            return None
        return bytes(frame), n_patched

    @staticmethod
    def write(f, iso_off, slot, frame):
        f.seek(iso_off)
        f.write(frame + b'\x00' * (slot - len(frame)))


def img_entry_count(iso, lba):
    """IMG 的**权威**条目数 = 名字表里的名字个数 (不看条目表, 免得把表尾垃圾当条目)。"""
    base = lba * tcslib.SEC
    noff = struct.unpack_from('<I', iso.mm, base + 0x10)[0]
    nend = struct.unpack_from('<I', iso.mm, base + 4)[0]
    names = [x for x in bytes(iso.mm[base + noff:base + nend]).split(b'\x00') if x]
    return len(names)


def enumerate_containers(iso, limit=8192):
    """两个 IMG 的**全部**条目 ⇒ [(tag, lba, idx, entry)]。

    ★ 与 `repack_leak_scan.build_region_map` 的差别: 那个函数遇到第一条空条目就 break ⇒
      区间表被截断 (GR.IMG#545 是空的, 于是 #546..#909 全没进表)。本函数按**名字表**定条目数,
      遇到空洞只跳过、不中断。
    """
    out = []
    for tag, lba in (('MENU.IMG', MENU_LBA), ('GR.IMG', GR_LBA)):
        n = min(img_entry_count(iso, lba), limit)
        for idx in range(n):
            try:
                e = iso.img_entry(lba, idx)
            except Exception:                                        # noqa: BLE001
                break
            if e['stored'] <= 0 or e['stored'] > 0x7FFFFFFF or e['off'] <= 0:
                continue
            out.append((tag, lba, idx, e))
    return out


def is_lzo_container(entry):
    """该条目在盘上是不是 LZO 压缩的 (stored < real 且 real 合理)?"""
    return 0 < entry['stored'] < entry['real'] < 0x7FFFFFFF


# ═══════════════════════ ③ 全盘扫描 + 真文本判别 ═══════════════════════

def parse_units(buf, cs):
    """引擎同款 greedy 解析 → [(byte_off, nbytes, char)]; 遇到解不出的字节就断。"""
    out, i, n = [], 0, len(buf)
    pair_of, codes = cs.pair_of, cs.codes
    while i < n:
        v = buf[i]
        if v < 0x80:
            out.append((i, 1, chr(v))); i += 1
        elif LEAD_LO <= v < LEAD_HI and i + 1 < n and (v, buf[i + 1]) in pair_of:
            out.append((i, 2, pair_of[(v, buf[i + 1])])); i += 2
        elif v in codes:
            out.append((i, 1, codes[v])); i += 1
        else:
            break
    return out


def _badlut():
    global _BADLUT_CACHE
    if _BADLUT_CACHE is None:
        a = np.zeros(256, dtype=bool)
        a[list(BAD_TEXT_BYTES)] = True        # 控制字符 (除 \t\n\r) + C1 区 = 肯定不是文本
        _BADLUT_CACHE = a
    return _BADLUT_CACHE


_BADLUT_CACHE = None


def candidate_spans(arr, min_bytes=SCAN_MIN_BYTES, runhi=SCAN_RUNHI):
    """numpy 预筛: 「无控制字节」的极大区间 且 区间内有 ≥runhi 个**连续高位字节**。

    ★ 真中文的必要条件 (一个汉字 = 2 个 ≥0xA1 的字节; 单字节汉字也 ≥0x80) ⇒ 预筛不丢真文本,
      却能把 1.6 GB 里的绝大多数二进制区间挡在 Python 逐字节解析之外 (提速 ~50×)。
    """
    n = len(arr)
    if n < min_bytes:
        return []
    bad = np.flatnonzero(_badlut()[arr])
    hi = arr >= 0x80
    if runhi > 1:
        if n < runhi:
            return []
        r = hi[:n - runhi + 1].copy()
        for k in range(1, runhi):
            r &= hi[k:n - runhi + 1 + k]
        rfull = np.zeros(n, dtype=bool)
        rfull[:len(r)] = r
    else:
        rfull = hi
    csum = np.concatenate(([0], np.cumsum(rfull, dtype=np.int64)))
    starts = np.concatenate(([0], bad + 1))
    ends = np.concatenate((bad, [n]))
    out = []
    for s, e in zip(starts.tolist(), ends.tolist()):
        if e - s >= min_bytes and csum[e] - csum[s] > 0:
            out.append((s, e))
    return out


def runs_in_span(seg, cs, min_cjk=SCAN_MIN_CJK):
    """一个"无控制字节"区间内: greedy 解析 → 取 ≥min_cjk 连续汉字的段 (相对区间起点)。"""
    hits = []
    units = parse_units(seg, cs)
    if not units:
        return hits
    cur = []
    for u in units:
        if '\u4e00' <= u[2] <= '\u9fff':
            cur.append(u)
        else:
            if len(cur) >= min_cjk:
                hits.append(_mk_hit(cur, 0))
            cur = []
    if len(cur) >= min_cjk:
        hits.append(_mk_hit(cur, 0))
    return hits


def blob_runs(blob, cs, min_cjk=SCAN_MIN_CJK, base_off=0):
    """容器展开态/原始段 → "干净 ≥min_cjk 连续汉字"的候选段 (带 base_off 偏移 + 所在干净区间)。

    口径: ① 先按"肯定不是文本"的字节 (控制字符/C1 区) 切段 (numpy 预筛);
          ② 段内 greedy 解析 (无未映射回落字节);
          ③ 汉字连续段 ≥min_cjk 才算一段。
    ★ 不要求"整段都是文本" —— 真文本周围总有二进制结构; 只要**这一截**是干净中文。
    """
    if not blob:
        return []
    arr = np.frombuffer(blob, dtype=np.uint8)
    hits = []
    for (s, e) in candidate_spans(arr, min_bytes=min_cjk, runhi=SCAN_RUNHI):
        for h in runs_in_span(blob[s:e], cs, min_cjk):
            h['off'] += base_off + s
            h['span'] = (base_off + s, base_off + e)
            hits.append(h)
    return hits


def _mk_hit(cur, seg_base):
    text = ''.join(u[2] for u in cur)
    return dict(off=seg_base + cur[0][0], nbytes=cur[-1][0] + cur[-1][1] - cur[0][0],
                text=text, maxcjk=len(cur),
                n_cjk=len(cur), distinct_cjk=len(set(text)),
                pair_ratio=sum(1 for u in cur if u[1] == 2) / len(cur))


def texty(hit):
    """★ 标定过的"真文本"判据 (见报告 §4): 巧合段的对偶码占比 ≈ 0.0~0.07, 真文本 ≈ 0.87。"""
    return (hit['maxcjk'] >= TEXTY_MIN_MAXRUN and hit['n_cjk'] >= TEXTY_MIN_CJK
            and hit['distinct_cjk'] >= TEXTY_MIN_DISTINCT
            and hit['pair_ratio'] >= TEXTY_MIN_PAIR_RATIO)


def best_hit(hits):
    if not hits:
        return None
    return max(hits, key=lambda h: (h['n_cjk'], h['distinct_cjk']))


def scan_raw_iso(iso, cs, verbose=True, min_bytes=SCAN_RAW_MIN_BYTES):
    """全盘原始字节扫描 (IMG 之外 + 未压缩条目 + **压缩数据**) —— 每段都带 ISO 绝对偏移。

    ⚠ 落在 LZO 压缩条目里的命中是**压缩数据**里的巧合 (真文本要看展开态, 由容器扫描负责),
      调用方按 `lzo_containers` 把它们分出来。
    """
    t0 = time.time()
    hits, n = [], iso.size
    off = 0
    while off < n:
        end = min(n, off + SCAN_CHUNK)
        buf = bytes(iso.mm[off:end])
        arr = np.frombuffer(buf, dtype=np.uint8)
        for (s, e) in candidate_spans(arr, min_bytes=min_bytes):
            for h in runs_in_span(buf[s:e], cs):
                h['off'] += off + s
                h['span'] = (off + s, off + e)
                hits.append(h)
        off = end
    if verbose:
        print('  [扫描] 全盘原始字节 (≥%d B 区间): %.1fs, 命中 %d 段'
              % (min_bytes, time.time() - t0, len(hits)))
    return hits


def who(regions, off):
    lo, hi = 0, len(regions) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        a, b, nm = regions[mid]
        if off < a:
            hi = mid - 1
        elif off >= b:
            lo = mid + 1
        else:
            return nm
    return '(IMG 之外 / 未归属)'


# ═══════════════════════ ③b ★ r57 细扫: 短串 (=C 字符串) 真文本 ═══════════════════════

def pair_lut(cs):
    """旧码表的"合法对偶码"查找表: lut[(lead<<8)|trail] —— 细扫的预筛 (numpy 向量化)。"""
    lut = np.zeros(1 << 16, dtype=bool)
    for (a, b) in cs.pair_of:
        lut[(a << 8) | b] = True
    return lut


def find_elf_base(iso, limit_lba=4096):
    """LBA 扫描找 PS2 ELF 的基址 (0x7F 'E' 'L' 'F'), 优先已知的 LBA 295。"""
    hint = ELF_LBA_HINT * tcslib.SEC
    if bytes(iso.mm[hint:hint + len(ELF_MAGIC)]) == ELF_MAGIC:
        return hint
    for lba in range(16, limit_lba):
        off = lba * tcslib.SEC
        if bytes(iso.mm[off:off + len(ELF_MAGIC)]) == ELF_MAGIC:
            return off
    return None


def known_text_regions(iso, verbose=True):
    """已知文本区 (非容器) ⇒ [(lo, hi, spec)]。登记表见文件顶部 `KNOWN_TEXT_REGIONS`。"""
    base = find_elf_base(iso)
    out = []
    for spec in KNOWN_TEXT_REGIONS:
        if base is None:
            if verbose:
                print('  [!!] 找不到 ELF (LBA%d 起扫) ⇒ 已知文本区 %r 本次无法登记'
                      % (ELF_LBA_HINT, spec['name']))
            continue
        rel = spec['elf_rel']
        out.append(dict(spec, lo=base + rel[0], hi=base + rel[1], elf_base=base))
    if verbose and out:
        for r in out:
            print('  [已知] %s @0x%X..0x%X (ELF@0x%X + 0x%X..0x%X) —— %s'
                  % (r['name'], r['lo'], r['hi'], r['elf_base'], r['elf_rel'][0],
                     r['elf_rel'][1], r['provenance']))
    return out


def in_regions(knowns, off):
    for r in knowns:
        if r['lo'] <= off < r['hi']:
            return r
    return None


def span_of(mm, n, off):
    """off 所在的"无控制字节极大区间" (直接查 mmap, 不受分块影响)。"""
    bad = _badlut()
    s = off
    while s > 0 and not bad[mm[s - 1]]:
        s -= 1
    e = off
    while e < n and not bad[mm[e]]:
        e += 1
    return s, e


def cstr_of(mm, n, off):
    """off 所在的、以 0x00 定界的 C 字符串区间。"""
    s = off
    while s > 0 and mm[s - 1] != 0:
        s -= 1
    e = off
    while e < n and mm[e] != 0:
        e += 1
    return s, e


def _clean_units(buf, cs):
    """greedy 解析 + **是否消费掉全部字节** (遇到解不出的字节即断) ⇒ (units, clean)。"""
    u = parse_units(buf, cs)
    clean = bool(u) and u[-1][0] + u[-1][1] == len(buf)
    return u, clean


def scan_short_text(iso, cs, regions, knowns, changed_pairs, verbose=True):
    """★ r57 细扫: 全盘找 **≥2 连续汉字**的短串, 并按"C 字符串判据"分出真文本 / 二进制巧合。

    为什么要另起一套细扫 (而不是把粗扫的 `SCAN_RAW_MIN_BYTES` 降下来):
      粗扫的候选区间下限是 12 B, 而「请等待!」这类串只有 7 B ⇒ **整条串都被丢掉**
      (GR_ZH106 载入画面乱码就是这么漏的)。把下限降到 4 B 又不加预筛会让候选爆炸
      (4 字节级的二进制巧合上千万), 所以预筛换成 **"区间内含 ≥1 个旧码表的合法对偶码位置"**
      —— 随机字节命中率 ≈ 1175/65536 ≈ 1.8%/位置, 比 "≥4 连续高位字节" 精确约 20 倍。

    判据 (`docs/REPORT_elf_reencode_fix.md` §3, 在 GR_ZH105 上标定, IMG 之外零假阳):
      ① 段所在"无控制字节极大区间"(span) 两侧**都是 0x00**  ⇒ 是一条完整 C 字符串;
      ② 整串能被旧码表 greedy 解析**完整消费** (无解不出的字节);
      ③ 串内**对偶码字符占比 ≥ `SHORT_MIN_PAIR_RATIO`**
         (真文本 0.50~0.75; 二进制巧合 0.00~0.33 —— 巧合串里混着大量单字节码噪声字);
      ④ 串内**至少 1 个对偶码的码位本轮变过** (否则这条串换码后字节一模一样, 不用动)。
    落在 `knowns` (已知文本区) 里的段: 只需 ①②④ —— 那儿的字节是我们自己写进去的。

    返回 dict(candidates, stats): candidates 按 **span** 去重 (一条串 = 一个写盘动作)。
    """
    t0 = time.time()
    n = iso.size
    mm = iso.mm
    lut = pair_lut(cs)
    badlut = _badlut()
    cands = {}
    sample_pairs, sample_other = [], []
    stats = dict(spans=0, runs=0, runs_in_img=0, runs_outside=0, cand_runs=0, cand_spans=0,
                 skipped_by_reason={}, n_pair_runs=0, n_pair_runs_outside=0)
    pos = 0
    while pos < n:
        end = min(n, pos + SCAN_CHUNK)
        lo = max(0, pos - SCAN_PAD)
        hi = min(n, end + SCAN_PAD)
        buf = np.frombuffer(bytes(mm[lo:hi]), dtype=np.uint8)
        m = buf.size
        pairpos = np.zeros(m, dtype=bool)
        if m >= 2:
            idx = (buf[:-1].astype(np.uint32) << 8) | buf[1:].astype(np.uint32)
            pairpos[:m - 1] = lut[idx]
        bad = badlut[buf]
        starts = np.concatenate(([0], np.flatnonzero(bad) + 1))
        ends = np.concatenate((np.flatnonzero(bad), [m]))
        csum = np.concatenate(([0], np.cumsum(pairpos, dtype=np.int64)))
        for s, e in zip(starts.tolist(), ends.tolist()):
            if e - s < max(SCAN_SHORT_MIN_BYTES, SCAN_MIN_CJK) or csum[e] - csum[s] == 0:
                continue                       # 无对偶码位置 ⇒ 换码后字节不变, 不用管
            gs, ge = lo + s, lo + e
            if not (pos <= gs < end):
                continue                       # 落在重叠 padding 里 ⇒ 上一块已处理
            stats['spans'] += 1
            seg = bytes(mm[gs:ge])
            for h in runs_in_span(seg, cs, SCAN_MIN_CJK):
                off = gs + h['off']
                stats['runs'] += 1
                stats['n_pair_runs'] += (h['pair_ratio'] >= 1.0)
                if RE_MOD.match(r'^(MENU\.IMG|GR\.IMG)#\d+ ', who(regions, off)):
                    stats['runs_in_img'] += 1      # 由容器扫描负责 (见 plan_reencode 的说明)
                    continue
                stats['runs_outside'] += 1
                reason, info = classify_short_text(mm, n, off, cs, changed_pairs, knowns, cands)
                if reason is None:
                    stats['cand_runs'] += 1
                    continue
                stats['skipped_by_reason'][reason] = \
                    stats['skipped_by_reason'].get(reason, 0) + 1
                # 留证: ① "段内每个汉字都是对偶码"的段 (Lead 点名的"12 段"就是这一类) **全部留**;
                #       ② 其余每类留少量样例
                if h['pair_ratio'] >= 1.0:
                    stats['n_pair_runs_outside'] += 1
                    if len(sample_pairs) < 400:
                        sample_pairs.append(dict(off=off, nbytes=h['nbytes'], text=h['text'],
                                                 pair_ratio=1.0,
                                                 span=list(span_of(mm, n, off)), reason=reason,
                                                 cstr_text=info.get('text', '')[:60],
                                                 cstr=list(info.get('cstr', (0, 0)))))
                elif len(sample_other) < 60:
                    sample_other.append(dict(off=off, nbytes=h['nbytes'], text=h['text'],
                                             pair_ratio=round(h['pair_ratio'], 3),
                                             span=list(span_of(mm, n, off)), reason=reason,
                                             cstr_text=info.get('text', '')[:60],
                                             cstr=list(info.get('cstr', (0, 0)))))
        pos = end
    stats['cand_spans'] = len(cands)
    if verbose:
        print('  [扫描] 细扫(短串: ≥%d B 区间 + 对偶码预筛): %.1fs; 候选区间 %d, ≥%d 连续汉字段 %d '
              '(其中"全部是对偶码"的 %d) = IMG 内 %d (交给容器扫描) + IMG 之外 %d;'
              % (SCAN_SHORT_MIN_BYTES, time.time() - t0, stats['spans'], SCAN_MIN_CJK,
                 stats['runs'], stats['n_pair_runs'], stats['runs_in_img'],
                 stats['runs_outside']))
        print('         判为**真文本** %d 段 → %d 条串 (要原位重映射); 跳过 %d 段, 理由: %s'
              % (stats['cand_runs'], stats['cand_spans'],
                 sum(stats['skipped_by_reason'].values()),
                 ', '.join('%s=%d' % kv for kv in
                           sorted(stats['skipped_by_reason'].items(), key=lambda kv: -kv[1]))
                 or '(无)'))
        print('         其中"段内汉字全是 2 字节对偶码"的段: 全盘 %d (IMG 之外 %d, 全部留证在报告里)'
              % (stats['n_pair_runs'], stats['n_pair_runs_outside']))
    stats['skipped_sample'] = sample_pairs + sample_other
    stats['pair_runs_outside'] = sample_pairs
    return dict(candidates=list(cands.values()), stats=stats)


def classify_short_text(mm, n, off, cs, changed_pairs, knowns, cands):
    """判一个 ≥2 连续汉字的段是不是"短串真文本"。返回 (跳过理由 or None, 串信息)。

    命中时把结果按 **span** 记进 `cands` (同一条串里的多个汉字段只对应一个写盘动作)。
    判据见 `scan_short_text()` 的 docstring。
    """
    lo, hi = span_of(mm, n, off)
    seg = bytes(mm[lo:hi])
    info = dict(lo=lo, hi=hi)
    if len(seg) < SHORT_MIN_CSTR_BYTES:
        return 'span_too_short', info
    # ① 两侧 0x00 ⇒ 完整 C 字符串 (span 是"无控制字节极大区间", 两侧必然是控制字节或盘边界)
    if not (lo > 0 and hi < n and mm[lo - 1] == 0 and mm[hi] == 0):
        return 'not_nul_bounded', info
    c_lo, c_hi = cstr_of(mm, n, off)
    info['cstr'] = (c_lo, c_hi)
    if c_lo != lo or c_hi != hi:
        return 'not_nul_bounded', info
    # ② 整串可被旧码表完整消费
    units, clean = _clean_units(seg, cs)
    if not clean:
        return 'unclean_decode', info
    n_units = len(units)
    pairs = [(seg[u[0]], seg[u[0] + 1]) for u in units if u[1] == 2]
    n_pair = len(pairs)
    info.update(units=n_units, pairs=n_pair, text=''.join(u[2] for u in units))
    # ④ 串内至少 1 个对偶码的码位本轮变过 (否则换码后字节一模一样, 不用动)
    if not any(p in changed_pairs for p in pairs):
        return 'no_code_change', info
    known = in_regions(knowns, off)
    ratio = n_pair / max(1, n_units)
    info['pair_ratio'] = round(ratio, 3)
    # ③ 串内对偶码字符占比 (已知文本区免除 —— 那儿的字节是我们自己写进去的)
    if known is None and ratio < SHORT_MIN_PAIR_RATIO:
        return 'low_pair_ratio', info
    key = (lo, hi)
    if key not in cands:
        cands[key] = dict(lo=lo, hi=hi, text=info['text'], nbytes=len(seg),
                          pairs=n_pair, units=n_units, pair_ratio=round(ratio, 3),
                          runs=[], known=(known['name'] if known else None),
                          provenance=(known['provenance'] if known else None),
                          cstr=(c_lo, c_hi))
    cands[key]['runs'].append(off)
    return None, info


# ═══════════════════════ ④ 搬字方案 (复用 repack_font 的格位口径) ═══════════════════════

def plan_compact(iso_path, charset_path=None, verbose=True, charset_obj=None):
    """只读地算出**搬字 + 换码**方案 (不写任何文件)。

    `charset_obj` 给定时直接用这个 Charset 实例 (不再从 JSON 读) —— 门禁 E 用它拿
    "**已提交后**的 charset" 去复算幂等性 (此时 JSON 还没写, 但不该因此误判)。
    """
    t0 = time.time()
    charset_path = charset_path or tcslib.CHARSET
    geom = _sync_geometry(iso_path, verbose=verbose)
    font = dump_font.load_font(iso_path)
    atlas_meta, faces = font['atlas'], font['faces']
    w, h, psm = atlas_meta['w'], atlas_meta['h'], atlas_meta['psm']
    A = RF.Atlas(atlas_meta['pak'], atlas_meta['px_off'], atlas_meta['px_size'], w, h, psm)
    cs = charset_obj if charset_obj is not None else tcslib.Charset(charset_path)

    # ---- charset 与这张盘对不对得上 (粗探针; 与旧工具同款) ----
    iso_sha = tcslib.sha256_file(iso_path)
    _js = RF._load_charset_json(charset_path)
    rec = ((_js.get('_font_compact') or {}).get('iso_sha256')          # ★ 本工具优先
           or (_js.get('_font_repack') or {}).get('iso_sha256'))       # 旧工具的戳作兜底
    if rec and rec != iso_sha and verbose:
        print('  [note] charset 记录的"上次写入的盘"是 %s…, 本次输入盘是 %s… —— 两者不同。'
              % (rec[:12], iso_sha[:12]))
        print('         正常构筑里这表示"基底被本轮的 --patch 改过"(没问题); 人工单跑请看文件顶部 ⚠。')

    protect, rects = RF.protect_mask(faces, w, h)
    cells = RF.enumerate_cells(w, h)
    cls = RF.classify(cells, protect, w, h)
    usable = [c['slot'] for c in cells if cls[c['slot']][0] == 'usable']
    counts = {}
    for c in cells:
        k = cls[c['slot']][0]
        counts[k] = counts.get(k, 0) + 1
    n_slots = tcslib.pair_capacity()

    items, dead = RF.char_order(cs)
    used_slots = [s for s, _ch in items]
    N = len(items)
    if N > len(usable):
        raise CompactError('可用格不够: 可用 %d < 在用字形 %d' % (len(usable), N))
    # charset 与盘对不对得上: 在用字的槽位在图集里不该是空的 (粗探针)
    # ★ 2026-10-20 fix/font: 判据换成**三分类 + 零容忍** (`repack_font.classify_blank_slots`):
    #   ① PUA 占位 359 → 豁免 (刻意留白); ② 已登记未绘制 61 (元数据 `_expand_cap2400.real_chars`)
    #   → 单列成"已知缺字形", 仍逐字上报但不再打死字库步骤; ③ 其余 → **1 个就中止**。
    #   (只豁免 PUA 的话 61/2300=2.65% 仍会触发旧 2% 阈值 ⇒ ZH137 跑不通, 见 docs/REPORT_FONT_FIX.md)
    old_img = A.eng
    blank_pairs = [(s, ch) for s, ch in items
                   if not old_img[cells[s]['y']:cells[s]['y'] + CH,
                                  cells[s]['x']:cells[s]['x'] + CW].any()]
    bl = RF.classify_blank_slots(blank_pairs, _js, cs)
    ok_blank, blank_line = RF.report_blank_slots(bl, N)
    if not ok_blank:
        raise CompactError('!! 拒绝重排: %d/%d 个在用字在 charset 指的槽位上是空的, 且既不是 '
                           'PUA 占位、也没在 charset 元数据里登记 —— '
                           'charset JSON 与这张盘对不上 (%s)。'
                           % (len(bl['unexplained']), N,
                              ''.join(ch for _s, ch in bl['unexplained'][:20])))

    # ---- ★ 分配: 第 i 个字 → 第 i 个可用格 (可用格按 slot 升序) ----
    move = {}
    for i, (_s, ch) in enumerate(items):
        move[ch] = usable[i]
    new_slots = [move[ch] for _s, ch in items]
    if len(set(new_slots)) != N:
        raise CompactError('新槽位有重复 —— 分配不是单射')

    # ---- 目标引擎图: 清零全部可用格 → 逐字写入新格 → 别人的采样窗最终说了算 ----
    En = old_img.copy()
    um = np.zeros((h, w), dtype=bool)
    for c in cells:
        if cls[c['slot']][0] == 'usable':
            um[c['y']:c['y'] + CH, c['x']:c['x'] + CW] = True
    En[um] = False
    moved = kept = 0
    for s, ch in items:
        ns = move[ch]
        ox, oy = cells[s]['x'], cells[s]['y']
        nx, ny = cells[ns]['x'], cells[ns]['y']
        En[ny:ny + CH, nx:nx + CW] = old_img[oy:oy + CH, ox:ox + CW]
        moved += (ns != s)
        kept += (ns == s)
    En[protect] = old_img[protect]

    # ---- 写盘前自检 ----
    bad_prot = int((En[protect] != old_img[protect]).sum())
    if bad_prot:
        raise CompactError('自检失败: FT 记录矩形被改了 %d 个像素' % bad_prot)
    bad_glyph = []
    for s, ch in items:
        ns = move[ch]
        ox, oy = cells[s]['x'], cells[s]['y']
        nx, ny = cells[ns]['x'], cells[ns]['y']
        if not np.array_equal(En[ny:ny + CH, nx:nx + CW], old_img[oy:oy + CH, ox:ox + CW]):
            bad_glyph.append(ch)
    if bad_glyph:
        raise CompactError('自检失败: %d 个字形的像素没有原样落到新格 (%s)'
                           % (len(bad_glyph), ''.join(bad_glyph[:10])))
    # 新格必须都是"可用格", 且不是记录码占死的格
    for s, ch in items:
        ns = move[ch]
        if cls[ns][0] != 'usable' or tcslib.ATLAS_ENGINE_SINGLE_CELLS.get((ns // NCOL,
                                                                          ns % NCOL)):
            raise CompactError('自检失败: %r 被分配到禁用/被压的格 slot %d' % (ch, ns))

    # ---- 码位变更 ----
    code_changes = []
    pair_new = dict(cs.enc_pair)
    for s, ch in items:
        ns = move[ch]
        lead, trail = tcslib.pair_from_slot(ns)
        if not (LEAD_LO <= lead < LEAD_HI):
            raise CompactError('%r 的新 lead 0x%02X 越出引擎可读区间' % (ch, lead))
        pair_new[ch] = (lead, trail)
        if ns != s:
            code_changes.append(dict(char=ch, old_slot=s, new_slot=ns,
                                     old_code='%02X%02X' % cs.enc_pair[ch],
                                     new_code='%02X%02X' % (lead, trail),
                                     old_cell=[cells[s]['x'], cells[s]['y']],
                                     new_cell=[cells[ns]['x'], cells[ns]['y']]))
    cs_new = charset_view(cs, pair_new)
    cmap = CodeMap(cs, cs_new)

    # ---- ★ 紧凑性 (用户的核心诉求): 在用 = slot 0..N-1, 空闲 = slot N..1503 ----
    new_set = set(new_slots)                            # ★ 新分配 (不是旧码位!)
    free_slots = sorted(set(range(n_slots)) - new_set)
    max_used = max(new_set)
    # ★ round67 扩容到 1504 = 网格上限后, 空闲格可能是**空集** ⇒ min()/max() 会抛
    #   ValueError: min() iterable argument is empty。空集时 "空闲格全在末端" 天然成立。
    min_free = min(free_slots) if free_slots else None
    prefix_ok = (sorted(new_set) == list(range(N)))
    tail_ok = (free_slots == list(range(N, n_slots)))
    weak_ok = (min_free is None) or (max_used < min_free)   # 所有空闲格都在所有在用格之后
    if not weak_ok:
        raise CompactError('分配后仍有空闲格夹在在用格之间 (max(used)=%d > min(free)=%d) '
                           '—— "可用格全在最末端"做不到' % (max_used, min_free))

    diff = En != old_img
    n_px = int(diff.sum())
    ink0, ink1 = int(old_img.sum()), int(En.sum())
    n_free_usable = len(usable) - N
    free_rows = {}
    for s in free_slots:
        free_rows.setdefault(s // NCOL, []).append(s % NCOL)
    # ---- ★ r58: 一次性"陈旧码表追平"迁移是否适用于**这张输入盘** ----
    mig = pending_migration(iso_sha)
    mig_info = None
    if mig:
        mig_info = dict(name=mig['name'], from_iso_version=mig.get('from_iso_version'),
                        stale_charset=mig['stale_charset'], stale_label=mig['stale_label'],
                        n_entries=len(mig['entries']),
                        roles=dict((r, sum(1 for e in mig['entries'] if e['role'] == r))
                                   for r in ('migrate', 'current')))
        if verbose:
            print('  [迁移] ★ 输入盘 %s 命中"陈旧码表追平"迁移清单: %s'
                  % (iso_sha[:12], mig['name']))
            print('         陈旧码表 = %s  (%s)' % (mig['stale_charset'], mig['stale_label']))
            print('         清单 %d 条: 要追平 %d 条 / 已在现役码表 %d 条 (其余登记容器由门禁证明'
                  '与码位无关)'
                  % (len(mig['entries']), mig_info['roles']['migrate'],
                     mig_info['roles']['current']))
    reencode_only = bool(mig) and n_px == 0 and not code_changes
    summ = dict(
        tool=TOOL, tool_version=TOOL_VERSION, round=ROUND, order_key=ORDER_KEY,
        iso=rel(iso_path), iso_sha256=iso_sha, charset=rel(charset_path),
        geom_from_elf=geom,
        changed=(n_px > 0 or bool(code_changes) or bool(mig)),
        reencode_only=reencode_only,
        stale_migration=mig_info,
        pixels_changed=n_px, atlas=dict(w=w, h=h, psm=psm, segments=len(A.segs),
                                        ink_before=ink0, ink_after=ink1, ink_delta=ink1 - ink0),
        cells=dict(total=n_slots, usable=len(usable), oob=counts.get('oob', 0),
                   record_cell=counts.get('record_cell', 0), ft_rect=counts.get('ft_rect', 0),
                   ft_records=len(rects)),
        glyphs=dict(used=N, moved=moved, kept=kept, dead_pairs=len(dead),
                    # ★ 2026-10-20: 只数**真缺字形**; PUA 占位单列 (它们是"故意空", 不是缺字)
                    missing_glyph_before=len(bl['registered_missing']),
                    pua_placeholder_before=len(bl['pua']),
                    blank_slots_before=len(blank_pairs),
                    blank_classification=blank_line,
                    missing_glyph_chars=''.join(ch for _s, ch in bl['registered_missing'])),
        layout=dict(used_slots=[min(new_set), max_used],
                    free_slots=([min_free, max(free_slots)] if free_slots else []),
                    n_used=N, n_free=len(free_slots), n_free_usable=n_free_usable,
                    used_prefix_ok=prefix_ok, free_tail_ok=tail_ok, weak_tail_ok=weak_ok,
                    free_by_row=dict((str(r), len(c)) for r, c in sorted(free_rows.items())),
                    note=('目标: 在用字形 = slot 0..%d; 空闲 = slot %d..%d (其中可用格 %d 个)'
                          % (N - 1, N, n_slots - 1, n_free_usable))),
        code_changes=len(code_changes),
        changed_pair_codes=len(cmap.changed_pairs),
        seconds=round(time.time() - t0, 1),
    )
    return dict(summary=summ, atlas=A, cells=cells, cls=cls, items=items, move=move, target=En,
                protect=protect, faces=faces, font=font, cs=cs, cs_new=cs_new, cmap=cmap,
                usable=usable, code_changes=code_changes, pair_new=pair_new,
                max_used=max_used, min_free=min_free, n_used=N, migration=mig)


# ═══════════════════════ ⑤ 重编码方案 (文本容器 + 全盘兜底) ═══════════════════════

def sfxml_text_spans(blob):
    """SFXML 里"引擎会显示"的字节区间: `name=` 属性值 + `<text>` 元素内容。"""
    spans = []
    for m in SFXML_TEXT_EL_RE.finditer(blob):
        spans.append((m.start(1), m.end(1), 'text'))
    for m in SFXML_ITEM_RE.finditer(blob):
        for am in SFXML_ATTR_RE.finditer(m.group(2)):
            key = am.group(1).decode('latin-1')
            if key in SFXML_TEXT_ATTRS:
                a = m.start(2) + am.start(2)
                spans.append((a, a + len(am.group(2)), 'name'))
    return sorted(spans)


# ═══════════ ★ r58: 容器级判据 (段 = 一段"能解出 ≥min_cjk 连续汉字"的字节) ═══════════

def try_parse_lang(blob):
    """安全版 `tcslib.parse_lang`: 结构不合 (畸形 length / 越界) 时返回 None, 不抛异常。

    ★ r58 需要它: 登记表把 `*_STRINGS.RES` 全收进来了, 而实测 `DE_STRINGS.RES` 的
      ngroups=66 里有一条 length 越界 ⇒ `parse_lang` 直接 `struct.error`。这种容器就退
      "容器级整块重映射" (同样逐段闭环), 而不是被排除在外。
    """
    try:
        ents, used_end = tcslib.parse_lang(blob)
    except Exception:                                                # noqa: BLE001
        return None
    if used_end > len(blob) or not ents:
        return None
    return ents, used_end


def cjk_segments(text, mp, n, min_cjk=2):
    """文本 → "≥min_cjk 连续汉字"的**段**列表 (带字节区间)。

    ★ 与全盘细扫的区别: **不要求** C 字符串边界 (NUL 包夹) —— 这正是 `EN_STRINGS.TXT`
      那 8 条 `"键"\\t"值"` 引号串两轮都漏掉的原因 (r57 报告 §6.1)。
    返回 [dict(lo, hi, chars, n_pair)]; `n_pair` = 段内由 **2 字节对偶码** 解出的字数
    (只有这些字会因码位重排而变; 单字节码/ASCII 与重排无关)。
    """
    runs, cur = [], []
    for i, ch in enumerate(text):
        if '\u4e00' <= ch <= '\u9fff':
            cur.append(i)
            continue
        if len(cur) >= min_cjk:
            runs.append(cur)
        cur = []
    if len(cur) >= min_cjk:
        runs.append(cur)
    out = []
    for idxs in runs:
        a, b = idxs[0], idxs[-1] + 1
        lo = mp[a]
        hi = mp[b] if b < len(mp) else n
        n_pair = sum(1 for i in idxs
                     if (mp[i + 1] if i + 1 < len(mp) else n) - mp[i] == 2)
        out.append(dict(lo=lo, hi=hi, chars=''.join(text[i] for i in idxs), n_pair=n_pair))
    return out


def verify_segments(blob, new_blob, src_cs, dst_cs, label, min_cjk=2):
    """★ r58 容器级**逐段闭环**: 每一段"源码表解出 ≥min_cjk 连续汉字"的字节,
    `目标码表解(改后同区间)` 必须与 `源码表解(改前同区间)` **逐字相同**。

    返回 `(segments, n_changed, n_unchanged)`; 任何一段对不上 ⇒ `CompactError`
    (错误信息带**容器名 + 字节偏移**, 便于直接定位)。**不依赖 C 字符串边界**。
    """
    t_src, mp = src_cs.decode(blob)
    t_dst, _ = dst_cs.decode(new_blob)
    if len(t_src) != len(t_dst):
        raise CompactError('%s: 重映射后字符数变了 (%d → %d) —— 逐字闭环不可能成立'
                           % (label, len(t_src), len(t_dst)))
    segs = cjk_segments(t_src, mp, len(blob), min_cjk)
    n_chg = n_same = 0
    for s in segs:
        a, b = s['lo'], s['hi']
        d_src = src_cs.decode(blob[a:b])[0]
        d_dst = dst_cs.decode(new_blob[a:b])[0]
        if d_src != d_dst:
            k = next((i for i in range(min(len(d_src), len(d_dst))) if d_src[i] != d_dst[i]), 0)
            raise CompactError(
                '%s: ★ 段闭环失败 @容器偏移 %d..%d (第 %d 字): 源解 %r ≠ 目标解 %r —— 拒绝写盘'
                % (label, a, b, k, d_src, d_dst))
        if any(new_blob[i] != blob[i] for i in range(a, b)):
            n_chg += 1
        else:
            n_same += 1
    return segs, n_chg, n_same


def plan_reencode(iso, res, verbose=True):
    """只读地算出全部重编码写盘动作 (含通用容器重写 + 全盘兜底), 写盘前**先把关**。

    返回 dict(units=[...], writes=[(iso_off, bytes, label)], scan={...}, new_blobs={...})
    """
    cs_old, cmap = res['cs'], res['cmap']
    containers = enumerate_containers(iso)
    regions = sorted((e['iso_off'], e['iso_off'] + e['stored'],
                      '%s#%d %s' % (tag, idx, e['name'])) for (tag, _lba, idx, e) in containers)
    region_modes = dict(((e['iso_off'], e['iso_off'] + e['stored']),
                         ('lzo' if is_lzo_container(e) else 'raw',
                          '%s#%d %s' % (tag, idx, e['name'])))
                        for (tag, _lba, idx, e) in containers)
    print('  [扫描] 容器表 %d 条 (MENU.IMG / GR.IMG 全量, 含空洞之后)' % len(containers))

    # ---- ★ r57: 已知文本区 (非容器; 登记表 + ELF 定位) ----
    knowns = known_text_regions(iso, verbose=verbose)

    # ---- ★ r58: 容器级文本登记表 (按**名字/模式**; 不再写死 (lba,idx)) ----
    registered, reg_by_key = {}, {}
    for (tag, lba, idx, e) in containers:
        rent = registry_match(e['name'])
        if rent:
            key = '%s#%d %s' % (tag, idx, e['name'])
            registered[(lba, idx)] = rent
            reg_by_key[key] = dict(entry=rent, tag=tag, lba=lba, idx=idx, name=e['name'])
    for kind, pat in (('lang', r'^(?:EN|DE|ES|FR|IT)_STRINGS\.RES$'),
                      ('sfxml', r'^(?:EN|DE|ES|FR|IT)_SPECIAL_FEATURE\.XML$'),
                      ('text', r'^(?:EN|DE|ES|FR|IT)_STRINGS\.TXT$')):
        if not any(re.match(pat, k.split(' ', 1)[1]) for k in reg_by_key):
            raise CompactError('!! 登记表里 %s 类容器一个都没匹配上 (%s) —— 这张盘结构不对?'
                               % (kind, pat))
    print('  [登记] 容器级文本登记表: 命中 %d 个容器 (%s)'
          % (len(reg_by_key),
             ', '.join('%s×%d' % (p, n) for p, n in
                       sorted(collections.Counter(k.split(' ', 1)[1]
                                                  for k in reg_by_key).items()))))

    # ---- ★ r58: 一次性"陈旧码表追平"迁移 (内容寻址; 只对清单钉死的那张盘生效) ----
    mig = res.get('migration')
    mig_idx = migration_index(mig)
    stale_cs, cmap_stale = None, None
    if mig:
        stale_cs = tcslib.Charset(resolve_repo_path(mig['stale_charset']))
        cmap_stale = CodeMap(stale_cs, res['cs_new'])
    mig_roles = {}
    if mig_idx:
        for (tag, lba, idx, e) in containers:
            # 只看**槽位原始字节**的 sha256 (内容寻址) —— 不做解压, 免得白扫一遍全盘
            rec = mig_idx.get(sha256_b(iso.read(e['iso_off'], e['stored'])))
            if rec is not None:
                mig_roles[(lba, idx)] = rec
        print('  [迁移] 清单命中盘上 %d 个容器 (要追平 %d / 已在现役码表 %d)'
              % (len(mig_roles),
                 sum(1 for r in mig_roles.values() if r['role'] == 'migrate'),
                 sum(1 for r in mig_roles.values() if r['role'] == 'current')))

    # ---- 全盘原始字节扫描 (兜底: IMG 之外 + 判据复核) ----
    raw_hits = scan_raw_iso(iso, cs_old, verbose=verbose)
    in_img = outside_runs = 0
    raw_texty_list = []
    for h in raw_hits:
        nm = who(regions, h['off'])
        h['container'] = nm
        if re.match(r'^(MENU\.IMG|GR\.IMG)#\d+ ', nm):
            # ★ 落在某个 IMG 条目里的命中: **一律由"容器扫描"负责** ——
            #   压缩条目 ⇒ 那是压缩字节的巧合 (真文本看展开态);
            #   未压缩条目 ⇒ 展开态 == 原始字节, 容器扫描已经逐段看过并分类过。
            h['in_img'] = True
            in_img += 1
            continue
        h['in_img'] = False
        outside_runs += 1
        if texty(h):
            raw_texty_list.append(h)
    print('  [扫描] 全盘原始命中 %d 段 = IMG 条目内 %d (交给容器扫描) + IMG 之外 %d; '
          'IMG 之外判为**真文本**的 %d 段'
          % (len(raw_hits), in_img, outside_runs, len(raw_texty_list)))
    for h in raw_texty_list[:10]:
        print('         ★ %s @%d %r' % (h['container'], h['off'], h['text'][:40]))

    # ---- 逐容器扫描 (展开 LZO) + 判别 ----
    units = []                      # 要重写的容器
    cov_by_container = {}           # 逐容器扫描统计 (报告用)
    texty_keys, rewritten_keys = set(), set()
    new_text_containers = []
    _EXCL = set(res.get('exclude_text_containers') or ())
    excluded_texty = []
    if _EXCL:
        print('  [排除] 调用方登记了 %d 个"二进制巧合"容器 (跳过 texty 判据): %s'
              % (len(_EXCL), ', '.join(sorted(_EXCL))))
    t0 = time.time()
    for (tag, lba, idx, e) in containers:
        key = (lba, idx)
        rent = registered.get(key)
        is_known = (key in registered) or bool(mig_roles.get(key))
        slot = Slot(iso, tag, lba, idx)
        hits = blob_runs(slot.blob, cs_old) if slot.blob else []
        bh = best_hit(hits)
        ckey = '%s#%d %s' % (tag, idx, e['name'])
        is_texty = bool(hits) and texty(bh)
        # ★ r-zh130 新增 (opt-in): 调用方可以显式把某个容器登记为"二进制巧合"
        #   (`res['exclude_text_containers']`, 按 `TAG#idx NAME` 或裸文件名匹配)。
        #   用途: 压缩图像 (.BMZ/.QOZ) 的解压流偶尔能通过 texty() 判据 (实测
        #   `GR.IMG#171 M03_RRBRIDGE_SKY.BMZ` / `#2466 MAN_OLD02.BMZ`), 而它们的槽位
        #   重压会超槽 ⇒ plan 阶段中止。不给这个参数时**行为与以前逐字节相同**。
        if is_texty and (ckey in _EXCL or e['name'] in _EXCL):
            excluded_texty.append(dict(container=ckey, lba=lba, idx=idx, n_runs=len(hits),
                                       n_cjk=bh['n_cjk'], maxcjk=bh['maxcjk'],
                                       distinct=bh['distinct_cjk'],
                                       pair_ratio=round(bh['pair_ratio'], 3),
                                       text=bh['text'][:60],
                                       why=res.get('exclude_reason') or '调用方登记为二进制巧合'))
            print('  [排除] %s: 命中 texty 判据但被调用方登记为二进制巧合 (%d 段, maxcjk %d) '
                  '⇒ 按非文本处理' % (ckey, len(hits), bh['maxcjk']))
            is_texty = False
        if hits:
            cov_by_container[ckey] = dict(
                runs=len(hits), texty=is_texty, covered=is_known,
                best=dict(n_cjk=bh['n_cjk'], distinct=bh['distinct_cjk'],
                          pair_ratio=round(bh['pair_ratio'], 3), maxcjk=bh['maxcjk'],
                          text=bh['text'][:60]))
        if is_texty:
            texty_keys.add(ckey)
            if not is_known:
                new_text_containers.append((tag, lba, idx, e, bh))
        if is_known or is_texty:
            rewritten_keys.add(ckey)
            units.append(dict(tag=tag, lba=lba, idx=idx, entry=e, slot=slot, hits=hits,
                              known=is_known, best=bh, reg=rent,
                              mig=mig_roles.get(key)))
    print('  [扫描] 容器展开 + 逐容器判别: %.1fs; 要处理的容器 %d 个 (其中**新发现**的文本容器 %d 个)'
          % (time.time() - t0, len(units), len(new_text_containers)))
    for u in units:
        if not u['known']:
            print('         ★ 新发现文本容器 %s#%d %s: %d 段, 最长汉字串 %d'
                  % (u['tag'], u['idx'], u['entry']['name'], len(u['hits']),
                     u['best']['maxcjk']))

    # ---- 逐容器重映射 ----
    writes = []
    reg_report = []
    for u in units:
        tag, idx, name = u['tag'], u['idx'], u['entry']['name']
        label = '%s#%d %s' % (tag, idx, name)
        blob = u['slot'].blob
        rent, mrec = u['reg'], u['mig']
        # 该容器用哪一套"源→目标"映射: 迁移容器用 陈旧→现役, 其余用 现役→目标
        use_stale = bool(mrec and mrec['role'] == 'migrate')
        cmap_u = cmap_stale if use_stale else cmap
        src_cs_u = stale_cs if use_stale else cs_old
        if rent is not None:
            kind = rent['kind']
        elif (name or '').endswith('_STRINGS.RES'):
            kind = 'lang'
        elif (name or '').endswith('_SPECIAL_FEATURE.XML'):
            kind = 'sfxml'
        else:
            kind = 'generic'
        min_cjk = rent['min_cjk'] if rent else SCAN_MIN_CJK
        # ---- 迁移清单命中: 先对指纹 (对不上 ⇒ 抛错、绝不写盘) ----
        if mrec is not None:
            t_now = cs_old.decode(blob)[0]
            t_stale = stale_cs.decode(blob)[0] if stale_cs else t_now
            if mrec['role'] == 'migrate':
                got = sha256_b(t_stale.encode('utf-8'))
                if got != mrec['stale_text_sha256']:
                    raise CompactError(
                        '!! 迁移指纹不符: %s 的"陈旧码表解" sha256 %s ≠ 清单记录 %s —— '
                        '拒绝按陈旧码表重映射 (清单按内容寻址, 不符即说明这个容器不是清单里那个)'
                        % (label, got[:16], mrec['stale_text_sha256'][:16]))
                lack = [x for x in mrec.get('expect_contains', ()) if x not in t_stale]
                if lack:
                    raise CompactError('!! 迁移指纹不符: %s 的陈旧解里找不到 %s'
                                       % (label, '、'.join(lack)))
            elif mrec['role'] == 'current':
                got = sha256_b(t_now.encode('utf-8'))
                if got != mrec['current_text_sha256']:
                    raise CompactError(
                        '!! %s 被清单标为"已在现役码表", 但现役解 sha256 %s ≠ 记录 %s '
                        '⇒ 拒绝写入 (免得按陈旧码表把它改坏)'
                        % (label, got[:16], mrec['current_text_sha256'][:16]))
                # ★ 角色 = current 只表示"它的字节在**本轮的输入码表**上": 陈旧映射绝不能用在它
                #   身上; 但本轮若有码位变更, 它照样要走**前向**重映射 (use_stale 已是 False) ⇒
                #   这里**不能** continue, 落到下面的通用重映射分支。
        if kind == 'lang' and try_parse_lang(blob) is None:
            # ★ r58: 结构没被完全逆向/有畸形条目的语言表 (实测 `DE_STRINGS.RES`: ngroups=66 但
            #   某条 length 越界 ⇒ parse_lang 抛错) ⇒ 退回**容器级**整块重映射 (同样的逐段闭环),
            #   而不是拒绝 —— 否则这个容器就永久漏在覆盖面之外。
            kind = 'text'
            detail_note = 'lang 结构解析失败 ⇒ 退容器级整块重映射'
        else:
            detail_note = None
        if kind == 'lang':
            # ★ 逐**条目载荷**重映射: 长度前缀/attr 一个字节都不能碰
            ents, used_end = try_parse_lang(blob)
            out = bytearray(blob)
            tot_u = tot_c = tot_b = 0
            for en in ents:
                nb, st = cmap_u.remap_units(en.data, '%s [%d.%d]' % (label, en.g + 1, en.i))
                out[en.data_off:en.data_off + en.length] = nb
                tot_u += st['units']; tot_c += st['changed_units']; tot_b += st['changed_bytes']
            new_blob = bytes(out)
            # 载荷之外的字节一个都不许变
            spans = [(en.data_off, en.data_off + en.length) for en in ents]
            bad = [i for i in range(len(blob)) if out[i] != blob[i]
                   and not any(a <= i < b for (a, b) in spans)]
            if bad:
                raise CompactError('%s: 有改动落在条目载荷之外 (%s)' % (label, bad[:5]))
            detail = dict(kind=kind, entries=len(ents), used_end=used_end,
                          units=tot_u, changed_units=tot_c, changed_bytes=tot_b,
                          payload_spans=len(spans))
            # 逐条目逐字复核
            ents2, _ = try_parse_lang(new_blob) or ([], 0)
            if len(ents2) != len(ents):
                raise CompactError('%s: 重映射后语言表条目数变了 (%d → %d)'
                                   % (label, len(ents), len(ents2)))
            for e1, e2 in zip(ents, ents2):
                t1, _ = src_cs_u.decode(e1.data)
                t2, _ = res['cs_new'].decode(e2.data)
                if t1 != t2:
                    raise CompactError('%s [%d.%d] 重映射后逐字不一致' % (label, e1.g + 1, e1.i))
            detail['verify_entries_equal'] = len(ents)
        elif kind == 'sfxml':
            new_blob, st = cmap_u.remap_units(blob, label)
            spans = sfxml_text_spans(blob)
            changed = [i for i in range(len(blob)) if new_blob[i] != blob[i]]
            inside = [i for i in changed if any(a <= i < b for (a, b, _k) in spans)]
            if not st['only_high_bytes']:
                raise CompactError('%s: 有 <0x80 的字节被改了 —— 拒绝' % label)
            detail = dict(kind=kind, units=st['units'], changed_units=st['changed_units'],
                          changed_bytes=st['changed_bytes'],
                          only_high_bytes=st['only_high_bytes'],
                          text_spans=len(spans),
                          changed_inside_text_spans=len(inside),
                          changed_outside_text_spans=len(changed) - len(inside),
                          name_attrs=sum(1 for s in spans if s[2] == 'name'),
                          text_elements=sum(1 for s in spans if s[2] == 'text'))
        else:
            new_blob, st = cmap_u.remap_units(blob, label)
            changed = sum(1 for i in range(len(blob)) if new_blob[i] != blob[i])
            detail = dict(kind=kind, units=st['units'], changed_units=st['changed_units'],
                          changed_bytes=st['changed_bytes'], changed_total=changed)
        if detail_note:
            detail['note'] = detail_note
        # ---- ★ r58 容器级逐段闭环 (登记容器都要过; 失败 ⇒ 抛错、不写盘) ----
        if rent is not None or mrec is not None:
            segs, n_chg, n_same = verify_segments(blob, new_blob, src_cs_u, res['cs_new'],
                                                  label, min_cjk=min_cjk)
            detail['segments'] = len(segs)
            detail['segments_changed'] = n_chg
            detail['segments_unchanged'] = n_same
            detail['segments_min_cjk'] = min_cjk
            detail['pair_run_segments'] = sum(1 for s in segs if s['n_pair'] > 0)
            # 真实"改了多少个字节"(区别于 changed_bytes = 被改字符的编码长度之和)
            detail['diff_bytes'] = sum(1 for i in range(len(blob)) if new_blob[i] != blob[i])
            reg_report.append(dict(
                container=label, name=name, kind=kind,
                role=('migrate' if use_stale
                      else ('current' if (mrec or {}).get('role') == 'current' else 'registered')),
                where=(mrec or {}).get('where'),
                why=(mrec or {}).get('why') or (rent or {}).get('why'),
                blob=len(blob), segments=len(segs), segments_changed=n_chg,
                segments_unchanged=n_same, pair_run_segments=detail['pair_run_segments'],
                changed_bytes=detail.get('changed_bytes', 0),
                diff_bytes=detail['diff_bytes'],
                changed_tokens=detail.get('changed_units', 0),
                changed=(new_blob != blob),
                src=('陈旧码表 (' + mig['stale_label'] + ')') if use_stale else '现役码表',
                fingerprint=('陈旧解 sha256 %s == 清单记录' % mrec['stale_text_sha256'][:16]
                             if use_stale else
                             ('现役解 sha256 %s == 清单记录' % mrec['current_text_sha256'][:16]
                              if (mrec or {}).get('role') == 'current' else None))))
        if new_blob == blob:
            print('  [重编码] %-42s 无需改 (0 字节)%s'
                  % (label, ('  ← 登记容器: 段 %d / 与码位无关' % detail.get('segments', 0))
                     if (rent is not None or mrec is not None) else ''))
            continue
        frame, n_rep, flen, method = u['slot'].repack(new_blob, label)
        writes.append(dict(tag=tag, lba=u['lba'], idx=idx, name=name, label=label, raw=False,
                           iso_off=u['entry']['iso_off'], stored=u['slot'].slot,
                           old_off=u['entry']['off'], old_real=u['entry']['real'],
                           frame=frame, frame_bytes=flen, substreams_repacked=n_rep,
                           detail=detail, mode=u['slot'].mode, method=method,
                           src_cs=src_cs_u,
                           old_bytes=u['slot'].raw, old_blob=u['slot'].blob,
                           slot_sha_before=sha256_b(u['slot'].raw),
                           slot_sha_after=sha256_b((frame + b'\x00' * (u['slot'].slot
                                                                      - len(frame))))))
        print('  [重编码] %-42s %s: 改 %d 字 / %d 字节, %s → %d B (槽 %d)'
              % (label, detail['kind'], detail.get('changed_units', 0),
                 detail.get('changed_bytes', 0),
                 ('重压 %d 子流' % n_rep) if method == 'recompress'
                 else 'LZO 字面量原位改写 (帧长不变)', flen, u['slot'].slot))
    # ---- 兜底: 落在**非压缩区**的"真文本"段 ⇒ 原位重映射 (长度不变) ----
    for h in raw_texty_list:
        if h['container'] in rewritten_keys:
            continue
        s, e = h['span']
        seg = bytes(iso.mm[s:e])
        nb, st = cmap.remap_units(seg, 'raw@%d %s' % (s, h['container']))
        if nb == seg:
            continue
        writes.append(dict(tag='RAW', lba=None, idx=None, name='(ISO 原始区)', raw=True,
                           label='RAW@%d %s' % (s, h['container']), iso_off=s, stored=None,
                           frame=nb, frame_bytes=len(nb), substreams_repacked=0,
                           old_bytes=seg, old_blob=seg,
                           detail=dict(kind='raw', units=st['units'],
                                       changed_units=st['changed_units'],
                                       changed_bytes=st['changed_bytes']),
                           mode='raw', slot_sha_before=None, slot_sha_after=None))
        print('  [重编码] %-42s raw: 改 %d 字 / %d 字节 (原位)'
              % (writes[-1]['label'], st['changed_units'], st['changed_bytes']))

    # ---- ★ r57 兜底: **短串** (=C 字符串) 真文本 ⇒ 原位重映射 (长度不变) ----
    #   粗扫的候选区间下限是 12 B ⇒ 「请等待!」这类 7 B 的短串**整条被丢掉** (GR_ZH106 的回归)。
    short = scan_short_text(iso, cs_old, regions, knowns, cmap.changed_pairs, verbose=verbose)
    short_writes = 0
    for c in sorted(short['candidates'], key=lambda c: c['lo']):
        seg = bytes(iso.mm[c['lo']:c['hi']])
        label = 'SHORT@%d%s%s' % (c['lo'], (' [%s]' % c['known']) if c['known'] else '',
                                  (' %s' % who(regions, c['lo'])
                                   if who(regions, c['lo']) != '(IMG 之外 / 未归属)' else ''))
        nb, st = cmap.remap_units(seg, label)
        c['old_bytes'], c['new_bytes'] = seg, nb
        c['changed_units'] = st['changed_units']
        c['changed_bytes'] = st['changed_bytes']
        if nb == seg:
            print('  [重编码] %-52s 无需改 (0 字节; 串内码位都没变)' % label)
            continue
        writes.append(dict(tag='SHORT', lba=None, idx=None, name='(ISO 短串区)', raw=True,
                           label=label, iso_off=c['lo'], stored=None,
                           frame=nb, frame_bytes=len(nb), substreams_repacked=0,
                           old_bytes=seg, old_blob=seg,
                           detail=dict(kind='short', units=st['units'],
                                       changed_units=st['changed_units'],
                                       changed_bytes=st['changed_bytes'],
                                       text=c['text'], decoded_new=res['cs_new'].decode(nb)[0],
                                       decoded_old=cs_old.decode(seg)[0],
                                       pair_ratio=c['pair_ratio'], runs=c['runs'],
                                       known=c['known'], provenance=c['provenance']),
                           mode='raw', slot_sha_before=None, slot_sha_after=None))
        short_writes += 1
        print('  [重编码] %-52s 短串: 改 %d 字 / %d 字节 (%r)'
              % (label, st['changed_units'], st['changed_bytes'], c['text']))
    short['stats']['writes'] = short_writes
    short['stats']['no_change'] = sum(1 for c in short['candidates']
                                      if c['new_bytes'] == c['old_bytes'])
    short['detail'] = [dict(off=c['lo'], nbytes=c['nbytes'], text=c['text'],
                            pair_ratio=c['pair_ratio'], pairs=c['pairs'], units=c['units'],
                            runs=c['runs'], known=c['known'],
                            old_hex=c['old_bytes'].hex(' '), new_hex=c['new_bytes'].hex(' '),
                            changed_bytes=c['changed_bytes'],
                            decoded_old=cs_old.decode(c['old_bytes'])[0],
                            decoded_new=res['cs_new'].decode(c['new_bytes'])[0])
                       for c in sorted(short['candidates'], key=lambda c: c['lo'])]

    # ---- 兜底复核: 判为"真文本"的段必须**全部**已被重写 ----
    missed = []
    for h in raw_texty_list:
        if h['container'] in rewritten_keys:
            continue
        if not any(w['raw'] and w['iso_off'] <= h['off'] < w['iso_off'] + w['frame_bytes']
                   for w in writes):
            missed.append(h)
    for k in sorted(texty_keys - rewritten_keys):
        missed.append(dict(container=k, off=-1, text=cov_by_container[k]['best']['text'],
                           reason='容器判为真文本但未重写'))
    # ★ r57: 细扫判为短串真文本的候选, 必须段段有写盘动作 (除非"串内码位一个都没变")
    for c in short['candidates']:
        if c['new_bytes'] == c['old_bytes']:
            continue
        if not any(w['raw'] and w['iso_off'] == c['lo'] and w['frame_bytes'] == c['nbytes']
                   for w in writes):
            missed.append(dict(container='(短串)', off=c['lo'], text=c['text'],
                               reason='细扫判为真文本但未重写'))
    if missed:
        for h in missed[:10]:
            print('  [!!] 判为真文本但**没有**被重编码: %s @%s %r'
                  % (h.get('container'), h.get('off'), (h.get('text') or '')[:40]))
        raise CompactError('!! 有 %d 段"真文本"落在未重写的容器里 —— 拒绝写盘' % len(missed))

    scan = dict(
        raw_runs=len(raw_hits),
        raw_runs_in_img=in_img, raw_runs_outside_img=outside_runs,
        raw_texty_outside=len(raw_texty_list),
        raw_texty_remapped=sum(1 for w in writes if w.get('raw')),
        containers_scanned=len(containers),
        containers_with_runs=len(cov_by_container),
        containers_rewritten=len(units),
        containers_texty=len(texty_keys),
        new_text_containers=[dict(tag=t, idx=i, name=e['name'], text=bh['text'][:60])
                             for (t, _l, i, e, bh) in new_text_containers],
        by_container=dict(sorted(cov_by_container.items(), key=lambda kv: -kv[1]['runs'])[:40]),
        texty_containers=sorted(texty_keys),
        noise_runs=sum(v['runs'] for v in cov_by_container.values() if not v['texty']),
        noise_containers=sum(1 for v in cov_by_container.values() if not v['texty']),
        note=('"真文本"判据 = 最长汉字串 ≥%d 且 汉字数 ≥%d 且 不同汉字 ≥%d 且 对偶码汉字占比 ≥%.2f; '
              '"二进制巧合"段一律不改 (证据见 docs/REPORT_font_compact.md §4)'
              % (TEXTY_MIN_MAXRUN, TEXTY_MIN_CJK, TEXTY_MIN_DISTINCT, TEXTY_MIN_PAIR_RATIO)))
    # ★ r57: 细扫 (短串) 一节 —— 用户要求的三项计数 + 跳过理由 + 证据
    scan['min_cjk'] = SCAN_MIN_CJK
    scan['short'] = dict(
        min_cjk=SCAN_MIN_CJK, min_span_bytes=SCAN_SHORT_MIN_BYTES,
        min_pair_ratio=SHORT_MIN_PAIR_RATIO,
        spans=short['stats']['spans'], runs=short['stats']['runs'],
        runs_all_pairs=short['stats']['n_pair_runs'],
        runs_all_pairs_outside=short['stats']['n_pair_runs_outside'],
        pair_runs_evidence=short['stats']['pair_runs_outside'],
        runs_in_img=short['stats']['runs_in_img'],
        runs_outside_img=short['stats']['runs_outside'],
        text_runs=short['stats']['cand_runs'], text_cstrs=short['stats']['cand_spans'],
        remapped=short_writes, no_code_change=short['stats']['no_change'],
        skipped=sum(short['stats']['skipped_by_reason'].values()),
        skipped_by_reason=dict(sorted(short['stats']['skipped_by_reason'].items(),
                                      key=lambda kv: -kv[1])),
        known_regions=[dict(name=k['name'], lo=k['lo'], hi=k['hi'], elf_rel=list(k['elf_rel']),
                            provenance=k['provenance']) for k in knowns],
        detail=short['detail'],
        coincidence_sample=short['stats']['skipped_sample'],
        note=('短串判据: ① 段两侧 0x00 (完整 C 字符串) ② 整串可被旧码表完整解析 '
              '③ 串内对偶码字符占比 ≥%.2f (已知文本区免除) ④ 串内 ≥1 个对偶码码位本轮变过; '
              '标定见 docs/REPORT_elf_reencode_fix.md §3' % SHORT_MIN_PAIR_RATIO))
    # ★ r58: 容器级登记表 / 迁移 一节 —— 逐容器给数字 (段数 / 重映射段数 / 未变段数 / 改动字节)
    scan['registry'] = dict(
        patterns=[dict(pattern=e['pattern'], min_cjk=e['min_cjk'], kind=e['kind'],
                       why=e['why'], provenance=e['provenance'])
                  for e in CONTAINER_TEXT_REGISTRY],
        containers_total=len(reg_by_key),
        containers=reg_report,
        containers_changed=sum(1 for r in reg_report if r['changed']),
        changed_bytes=sum(r['changed_bytes'] for r in reg_report),
        diff_bytes=sum(r['diff_bytes'] for r in reg_report),
        segments=sum(r['segments'] for r in reg_report),
        segments_changed=sum(r['segments_changed'] for r in reg_report),
        segments_unchanged=sum(r['segments_unchanged'] for r in reg_report),
        note=('容器级判据: 命中登记表的容器里, 每一段"源 charset 能解出 ≥min_cjk 连续汉字"的字节'
              '都要重映射 + **逐段闭环**; 不依赖 C 字符串 / NUL 边界; 结构字节零改动 '
              '(LANG 格式进一步限制在条目载荷内)'))
    if mig:
        scan['migration'] = dict(
            name=mig['name'], from_iso_version=mig.get('from_iso_version'),
            from_iso_sha256=mig['from_iso_sha256'], stale_charset=mig['stale_charset'],
            stale_label=mig['stale_label'], provenance=mig['provenance'],
            entries=[dict(role=e['role'], name=e['name'], where=e['where'],
                          slot_sha256=e['slot_sha256'], why=e['why'],
                          stale_text_sha256=e.get('stale_text_sha256'),
                          current_text_sha256=e.get('current_text_sha256'),
                          changed_bytes=e.get('changed_bytes'))
                     for e in mig['entries']],
            matched=len(mig_roles),
            remapped=sum(1 for r in reg_report if r['role'] == 'migrate'),
            already_current=sum(1 for r in reg_report if r['role'] == 'current'),
            note=('一次性迁移: 只对 from_iso_sha256 那张盘生效; entries 按**槽位字节 sha256** '
                  '内容寻址; 角色 = migrate (陈旧码表写的 ⇒ 追平到现役) / current '
                  '(已在现役码表 ⇒ 绝不动); 清单之外命中登记表的容器由门禁证明"与码位无关"'))
    return dict(units=units, writes=writes, scan=scan, regions=regions,
                rewritten_keys=rewritten_keys, texty_keys=texty_keys,
                knowns=knowns, short=short, region_modes=region_modes,
                pre_hits=raw_hits, raw_texty_outside=raw_texty_list,
                registry=reg_report, reg_by_key=reg_by_key, migration=mig,
                excluded_texty=excluded_texty,
                mig_roles=mig_roles, migrated_keys=set(
                    '%s#%d %s' % (t, i, e['name']) for (t, _l, i, e) in containers
                    if (_l, i) in mig_roles))


# ═══════════════════════ ⑥ 写盘 ═══════════════════════

def apply(src_iso, out_iso, res, re, do_charset=True, verbose=True):
    """把方案落到盘上 (像素容器 + 重编码容器); **不**动 charset (由 commit_charset 负责)。

    ★ 写盘前把**被覆盖区间的原始字节**存进 `re['writes'][*]['old_bytes']` ——
      这样门禁可以在"就地改盘"的流程里照样做"旧 charset 解基底字节"的比对 (不必再留一份源盘)。
    """
    A, summ, font = res['atlas'], res['summary'], res['font']
    pak_e, px_off = font['pak_e'], A.px_off
    empty = A.empty_index()[0]
    ys, xs = np.where(res['target'] != A.eng)
    ink = res['target'][ys, xs]
    hdr_before = A.headers()
    A.write_pixels(ys, xs, ink, empty)
    for (doff, hb) in hdr_before:
        if bytes(A.cont[doff - tcslib.ATLAS_PREFIX_BYTES:doff]) != hb:
            raise CompactError('有 48B 包头被改了 (doff=0x%X)' % doff)

    if os.path.abspath(src_iso) != os.path.abspath(out_iso):
        shutil.copyfile(src_iso, out_iso)
    # 记录像素容器区间的原始字节 (供门禁用; 就地改盘的流程里源盘已经不存在了)
    re['atlas_write'] = dict(iso_off=pak_e['iso_off'] + px_off, nbytes=len(A.cont),
                             old_bytes=bytes(font['atlas']['pak'][px_off:px_off + A.px_size]),
                             new_bytes=bytes(A.cont))
    with open(out_iso, 'r+b') as f:
        f.seek(pak_e['iso_off'] + px_off)
        f.write(bytes(A.cont))
        for w in re['writes']:
            if w.get('raw'):
                f.seek(w['iso_off'])
                f.write(w['frame'])                    # 非压缩区: 同长度原位覆盖
            else:
                Slot.write(f, w['iso_off'], w['stored'], w['frame'])
    if os.path.getsize(src_iso) != os.path.getsize(out_iso):
        raise CompactError('ISO 尺寸变了')
    summ['wrote_iso'] = rel(out_iso)
    summ['iso_sha256_after'] = tcslib.sha256_file(out_iso)
    summ['atlas_pixel_sha256'] = sha256_b(np.packbits(res['target'].reshape(-1)).tobytes())
    summ['reencode'] = dict(containers=len(re['writes']),
                            short_spans=sum(1 for w in re['writes']
                                            if w['detail'].get('kind') == 'short'),
                            frame_bytes=sum(w['frame_bytes'] for w in re['writes']),
                            changed_bytes=sum(w['detail'].get('changed_bytes', 0)
                                              for w in re['writes']))
    if verbose:
        print('  [pack] 回写 %d 像素 (空色=索引 %d); 48B 包头未动 ✓' % (len(ys), empty))
        print('  [pack] 回写 %d 个重编码容器 / %d 段原始区'
              % (sum(1 for w in re['writes'] if not w.get('raw')),
                 sum(1 for w in re['writes'] if w.get('raw'))))
    return summ


# ═══════════════════════ ⑦ ★ 全盘一致性自检 (硬门禁) ═══════════════════════

def restore(dst_iso, res, re, verbose=True):
    """把 `dst_iso` 恢复成**紧凑/重编码之前**的样子 (只用 apply 存下的快照; 幂等)。

    ★ 门禁不过时用: 绝不在盘上留"改了一半"的中间态 (charset 那边由调用方回滚)。
    """
    n = 0
    with open(dst_iso, 'r+b') as f:
        aw = re.get('atlas_write')
        if aw:
            f.seek(aw['iso_off'])
            f.write(aw['old_bytes'])
            n += 1
        for w in re.get('writes', []):
            if w.get('old_bytes') is None:
                continue
            f.seek(w['iso_off'])
            f.write(w['old_bytes'])          # 容器 = 整槽原始字节; 原始区 = 区间原始字节
            n += 1
    if verbose:
        print('  [restore] 已把 %s 的 %d 个改动区间写回"紧凑前"的字节' % (rel(dst_iso), n))
    return n


def gate(dst_iso, res, plan, verbose=True, src_iso=None):
    """写盘后的完整门禁; 任何一项不过 ⇒ 抛 CompactError (调用方负责删产物/不回滚 charset)。

    ★ 不需要源盘: "基底字节"由 `apply()` 存下的 `old_bytes` / `old_blob` 快照提供
      ⇒ **就地改盘**的构筑流程 (make_build) 与"另出盘"流程走同一套门禁。
    """
    out = dict(checks=[])
    cs_old, cs_new, cmap = res['cs'], res['cs_new'], res['cmap']
    A, summ = res['atlas'], res['summary']

    def ok(name, detail):
        out['checks'].append(dict(check=name, ok=True, detail=detail))
        if verbose:
            print('  [门禁 ✓] %-46s %s' % (name, detail))

    iso_d = tcslib.Iso(dst_iso)
    font = dump_font.load_font(dst_iso)
    A2 = RF.Atlas(font['atlas']['pak'], font['atlas']['px_off'], font['atlas']['px_size'],
                  A.w, A.h, A.psm)
    # ---- C①: 图集引擎图 == 目标图 ----
    if not np.array_equal(A2.eng, res['target']):
        raise CompactError('门禁 C: 盘上解出的引擎图与目标图差 %d 个像素'
                           % int((A2.eng != res['target']).sum()))
    ok('C1 图集回读 == 目标图', '%d 像素改动' % summ['pixels_changed'])
    # ---- C②: 每个字形的像素逐像素落在新格 ----
    bad = []
    for s, ch in res['items']:
        ns = res['move'][ch]
        ox, oy = res['cells'][s]['x'], res['cells'][s]['y']
        nx, ny = res['cells'][ns]['x'], res['cells'][ns]['y']
        if not np.array_equal(A2.eng[ny:ny + CH, nx:nx + CW], A.eng[oy:oy + CH, ox:ox + CW]):
            bad.append(ch)
    if bad:
        raise CompactError('门禁 C: %d 个字形搬运不正确 (%s)' % (len(bad), ''.join(bad[:10])))
    ok('C2 逐字像素原样落在新格', '%d/%d' % (len(res['items']), len(res['items'])))
    # ---- C③: 采样窗 (FT 记录矩形) 0 改动 ----
    prot = res['protect']
    if int((A2.eng[prot] != A.eng[prot]).sum()):
        raise CompactError('门禁 C: FT 记录矩形被改了 %d 像素' % int((A2.eng[prot] != A.eng[prot]).sum()))
    ok('C3 别人的采样窗 (FT 记录矩形) 0 改动', '%d px 保护' % int(prot.sum()))
    # ---- C④: 48B 包头 ----
    if [bytes(A2.cont[d - tcslib.ATLAS_PREFIX_BYTES:d]) for (_f, d, _n) in A2.segs] != \
       [hb for (_d, hb) in A.headers()]:
        raise CompactError('门禁 C: 像素容器 48B 包头被改了')
    ok('C4 像素容器 48B 包头逐字节不变', '%d 段' % len(A.segs))

    # ---- A: 重写容器逐字闭环 (基底的"旧字节"由 apply 存的快照提供 ⇒ 就地改盘也能验) ----
    #   ★ r58: "源 charset" 逐条取 `w['src_cs']` —— 一次性"陈旧码表追平"迁移的容器, 它们的
    #     旧字节是**陈旧码表**写的 (`cs_old` 反而会解成乱码), 比对必须拿那一代的码表当源。
    for w in plan['writes']:
        w_src = w.get('src_cs') or cs_old
        if w.get('raw'):
            got = iso_d.read(w['iso_off'], w['frame_bytes'])
            if got != w['frame']:
                raise CompactError('门禁 A: %s 原位字节与计划不一致' % w['label'])
            t1, _ = w_src.decode(w['old_bytes'])
            t2, _ = cs_new.decode(got)
            if t1 != t2:
                raise CompactError('门禁 A: %s 原位重映射后逐字不一致' % w['label'])
            # ★ r57: 逐**段**闭环 (用户口径) —— 改动的字节必须**全部**落在"旧码表解析出的
            #   2 字节对偶码"区间内 (即 2 字节对 2 字节, 长度不变, ASCII/单字节码一个都不动)。
            _u, _clean = _clean_units(w['old_bytes'], w_src)
            pair_pos = set()
            for (u_off, u_nb, _ch) in _u:
                if u_nb == 2:
                    pair_pos.update((u_off, u_off + 1))
            outside = [i for i in range(w['frame_bytes'])
                       if got[i] != w['old_bytes'][i] and i not in pair_pos]
            if outside:
                raise CompactError('门禁 A: %s 有改动落在"2 字节对偶码区间"之外 (%s) —— 拒绝'
                                   % (w['label'], outside[:5]))
            if w['detail']['kind'] == 'short':
                _u2, clean_new = _clean_units(got, cs_new)
                if not clean_new:
                    raise CompactError('门禁 A: %s 短串在新码表下解不干净' % w['label'])
                if len(cs_old.decode(w['old_bytes'])[0]) != len(cs_new.decode(got)[0]):
                    raise CompactError('门禁 A: %s 短串字符数变了 (长度不变被破坏)' % w['label'])
                ok('A %s (短串原位)' % w['label'],
                   '%d B → %d B 长度不变, %r 逐字一致 (改 %d 字节)'
                   % (w['frame_bytes'], len(got), t2, w['detail']['changed_bytes']))
            else:
                ok('A %s (原始区原位)' % w['label'], '%d 字节, 逐字一致' % w['frame_bytes'])
            continue
        e2 = iso_d.img_entry(w['lba'], w['idx'])
        if (e2['off'], e2['stored'], e2['real']) != (w['old_off'], w['stored'], w['old_real']):
            raise CompactError('门禁 A: %s 的 IMG 条目表 off/stored/real 变了 (%s → %s)'
                               % (w['label'], (w['old_off'], w['stored'], w['old_real']),
                                  (e2['off'], e2['stored'], e2['real'])))
        s1_blob = w['old_blob']
        s2 = Slot(iso_d, w['tag'], w['lba'], w['idx'])
        if len(s1_blob) != len(s2.blob):
            raise CompactError('门禁 A: %s 解压总长变了' % w['label'])
        if w['detail']['kind'] == 'lang':
            ents1, _ = tcslib.parse_lang(s1_blob)
            ents2, _ = tcslib.parse_lang(s2.blob)
            if len(ents1) != len(ents2):
                raise CompactError('门禁 A: %s 语言表条目数变了' % w['label'])
            nchg = 0
            for x1, x2 in zip(ents1, ents2):
                t1, _ = w_src.decode(x1.data)
                t2, _ = cs_new.decode(x2.data)
                if t1 != t2:
                    raise CompactError('门禁 A: %s [%d.%d] 新 charset 解出的文本与旧的不同 (%r → %r)'
                                       % (w['label'], x1.g + 1, x1.i, t1[:20], t2[:20]))
                nchg += (x1.data != x2.data)
            # 结构字节 (载荷之外) 一个都没变
            spans = [(x.data_off, x.data_off + x.length) for x in ents1]
            bads = [i for i in range(len(s1_blob)) if s1_blob[i] != s2.blob[i]
                    and not any(a <= i < b for (a, b) in spans)]
            if bads:
                raise CompactError('门禁 A: %s 有改动落在条目载荷之外 (%s)' % (w['label'], bads[:5]))
            ok('A %s (LANG)' % w['label'],
               '%d 条目逐字一致, %d 条载荷换码, 结构字节 0 改动' % (len(ents1), nchg))
        else:
            t1, _ = w_src.decode(s1_blob)
            t2, _ = cs_new.decode(s2.blob)
            if t1 != t2:
                k = next((i for i in range(min(len(t1), len(t2))) if t1[i] != t2[i]), 0)
                raise CompactError('门禁 A: %s 新 charset 解出的文本与旧 charset 不同 @%d (%r → %r)'
                                   % (w['label'], k, t1[max(0, k - 8):k + 8],
                                      t2[max(0, k - 8):k + 8]))
            ch = sum(1 for i in range(len(s1_blob)) if s1_blob[i] != s2.blob[i])
            if w['detail']['kind'] == 'sfxml' and not w['detail'].get('only_high_bytes', True):
                raise CompactError('门禁 A: %s 有 <0x80 的字节被改' % w['label'])
            ok('A %s (%s)' % (w['label'], w['detail']['kind']),
               '整块逐字一致 (%d 字符), 改动 %d 字节' % (len(t1), ch))
    # ---- A': 槽字节 sha == 计划值; 像素容器区间 == 计划值 ----
    for w in plan['writes']:
        if w.get('raw') or w['slot_sha_after'] is None:
            continue
        got = sha256_b(iso_d.read(w['iso_off'], w['stored']))
        if got != w['slot_sha_after']:
            raise CompactError('门禁 A: %s 槽位字节与计划不一致' % w['label'])
    aw = plan['atlas_write']
    if iso_d.read(aw['iso_off'], aw['nbytes']) != aw['new_bytes']:
        raise CompactError('门禁 A: 像素容器区间的字节与计划不一致')
    ok('A0 盘上字节 == 计划值', '%d 个容器 + %d 段原始区 + 像素容器 %d B'
       % (sum(1 for w in plan['writes'] if not w.get('raw')),
          sum(1 for w in plan['writes'] if w.get('raw')), aw['nbytes']))

    # ---- ★ r57 A2: 写盘区间两两不重叠 (重叠 = 同一段被改两次, 必有一次是错的) ----
    iv = sorted((w['iso_off'], w['iso_off'] + w['frame_bytes'], w['label'])
                for w in plan['writes'])
    for k in range(1, len(iv)):
        if iv[k][0] < iv[k - 1][1]:
            raise CompactError('门禁 A2: 写盘区间重叠 —— %s 与 %s' % (iv[k - 1][2], iv[k][2]))
    ok('A2 写盘区间两两不重叠', '%d 个区间 (其中短串 %d)'
       % (len(iv), sum(1 for w in plan['writes'] if w['detail'].get('kind') == 'short')))

    # ---- ★ r57 B0: 短串闭环复核 (逐条串: 旧码表解基底 == 新码表解盘上; 且长度不变) ----
    n_short_ok = 0
    for w in plan['writes']:
        if w['detail'].get('kind') != 'short':
            continue
        got = iso_d.read(w['iso_off'], w['frame_bytes'])
        t1 = cs_old.decode(w['old_bytes'])[0]
        t2 = cs_new.decode(got)[0]
        if t1 != t2:
            raise CompactError('门禁 B0: 短串 %s 换码后文本变了 (%r → %r)'
                               % (w['label'], t1, t2))
        if len(got) != len(w['old_bytes']):
            raise CompactError('门禁 B0: 短串 %s 长度变了 —— ELF 必须长度不变' % w['label'])
        n_short_ok += 1
    for c in plan.get('short', {}).get('candidates', []):
        if c['new_bytes'] == c['old_bytes']:
            continue
        if not any(w['detail'].get('kind') == 'short' and w['iso_off'] == c['lo']
                   for w in plan['writes']):
            raise CompactError('门禁 B0: 短串候选 @0x%X 判为真文本却没写盘' % c['lo'])
    ok('B0 短串逐条闭环 (旧解 == 新解, 长度不变)', '%d 条 (判为真文本的候选 %d 条, 其余码位未变)'
       % (n_short_ok, len(plan.get('short', {}).get('candidates', []))))

    # ---- ★ r58 A3: **登记容器全覆盖** (三类必居其一, 逐个容器校验; 有洞 ⇒ 中止不写 charset) ----
    mig = plan.get('migration')
    mig_roles = plan.get('mig_roles') or {}
    stale_cs = tcslib.Charset(resolve_repo_path(mig['stale_charset'])) if mig else None
    wr_by_key = dict(((w['lba'], w['idx']), w) for w in plan['writes'] if not w.get('raw'))
    reg_ok, reg_missing = [], []
    for (tag, lba, idx, e) in enumerate_containers(iso_d):
        rent = registry_match(e['name'])
        if not rent:
            continue
        label = '%s#%d %s' % (tag, idx, e['name'])
        min_cjk = rent['min_cjk']
        blob = Slot(iso_d, tag, lba, idx).blob
        mrec = mig_roles.get((lba, idx))
        if mrec is not None and mrec['role'] == 'migrate':
            # (1) 已迁移: `现役解(盘上)` 必须 == `陈旧解(迁移前)` —— 迁移前字节从写盘快照取
            w = wr_by_key.get((lba, idx))
            if w is None:
                raise CompactError('门禁 A3: %s 被标为 migrate, 但盘上没有对应写盘动作' % label)
            t_old, t_new = stale_cs.decode(w['old_blob'])[0], res['cs_new'].decode(blob)[0]
            if t_old != t_new:
                k = next((i for i in range(min(len(t_old), len(t_new))) if t_old[i] != t_new[i]), 0)
                raise CompactError('门禁 A3: %s 迁移后逐字不一致 @%d (%r -> %r)'
                                   % (label, k, t_old[max(0, k - 8):k + 8],
                                      t_new[max(0, k - 8):k + 8]))
            got = sha256_b(t_old.encode('utf-8'))
            if got != mrec['stale_text_sha256']:
                raise CompactError('门禁 A3: %s 的陈旧解指纹 %s != 清单 %s'
                                   % (label, got[:16], mrec['stale_text_sha256'][:16]))
            segs, n_chg, n_same = verify_segments(w['old_blob'], blob, stale_cs, res['cs_new'],
                                                  label, min_cjk=min_cjk)
            reg_ok.append(dict(container=label, role='migrate', segments=len(segs),
                               segments_changed=n_chg, segments_unchanged=n_same,
                               changed_bytes=w['detail'].get('changed_bytes', 0),
                               diff_bytes=w['detail'].get('diff_bytes', 0),
                               method=w.get('method'),
                               verdict='陈旧解 == 现役解 (逐字相同, 逐段闭环 OK)'))
        elif mrec is not None and mrec['role'] == 'current':
            got = sha256_b(res['cs_new'].decode(blob)[0].encode('utf-8'))
            if got != mrec['current_text_sha256']:
                raise CompactError('门禁 A3: %s 标为 current 但现役解指纹 %s != 清单 %s'
                                   % (label, got[:16], mrec['current_text_sha256'][:16]))
            reg_ok.append(dict(container=label, role='current', segments=0, segments_changed=0,
                               segments_unchanged=0, changed_bytes=0, method=None,
                               verdict='已在现役码表 (现役解 sha256 == 清单记录 OK)'))
        elif stale_cs is None or res['code_changes']:
            reg_ok.append(dict(container=label, role='registered', segments=0, segments_changed=0,
                               segments_unchanged=0, changed_bytes=0, method=None,
                               verdict=('无陈旧码表清单 ⇒ 只登记'
                                        if stale_cs is None else '本轮有码位变更 ⇒ 走前向重映射')))
        else:
            # (3) 清单之外: 必须证明"该容器与码位无关" —— 陈旧解 == 现役解
            t_now, t_stale = res['cs_new'].decode(blob)[0], stale_cs.decode(blob)[0]
            if t_now != t_stale:
                k = next((i for i in range(min(len(t_now), len(t_stale))) if t_now[i] != t_stale[i]),
                         0)
                reg_missing.append(dict(container=label, at=k))
                continue
            segs = cjk_segments(t_now, res['cs_new'].decode(blob)[1], len(blob), min_cjk)
            reg_ok.append(dict(container=label, role='independent', segments=len(segs),
                               segments_changed=0, segments_unchanged=len(segs), changed_bytes=0,
                               method=None,
                               verdict='陈旧解 == 现役解 ⇒ 与码位无关, 不需要动 OK'))
    if reg_missing:
        for r in reg_missing[:10]:
            print('  [!!] 登记容器 %s 的"陈旧解" != "现役解", 但它不在迁移清单里、也没被重写 @%d'
                  % (r['container'], r['at']))
        raise CompactError('门禁 A3: 有 %d 个登记容器的重编码覆盖面**有洞** (既不在迁移清单、'
                           '也没被重写, 却与陈旧码表解读不同) —— 拒绝写 charset' % len(reg_missing))
    out['registry'] = dict(
        containers=len(reg_ok),
        by_role=dict((r, sum(1 for x in reg_ok if x['role'] == r))
                     for r in sorted(set(x['role'] for x in reg_ok))),
        segments=sum(x['segments'] for x in reg_ok),
        segments_changed=sum(x['segments_changed'] for x in reg_ok),
        segments_unchanged=sum(x['segments_unchanged'] for x in reg_ok),
        changed_bytes=sum(x['changed_bytes'] for x in reg_ok),
        detail=reg_ok)
    ok('A3 登记容器全覆盖 (三类必居其一)',
       '%d 个容器: 迁移 %d / 已在现役码表 %d / 与码位无关 %d; 段 %d = 重映射 %d + 未变 %d; '
       '改动 %d 字节 (实际不同字节 %d)'
       % (len(reg_ok), out['registry']['by_role'].get('migrate', 0),
          out['registry']['by_role'].get('current', 0),
          out['registry']['by_role'].get('independent', 0)
          + out['registry']['by_role'].get('registered', 0),
          out['registry']['segments'], out['registry']['segments_changed'],
          out['registry']['segments_unchanged'], out['registry']['changed_bytes'],
          sum(x.get('diff_bytes') or 0 for x in reg_ok)))

    # ---- B: 全盘扫描复核 (用 plan 阶段扫好的基底命中; 未写入区的字节没动 ⇒ 可直接从产物读) ----
    hits = plan.get('pre_hits') or scan_raw_iso(iso_d, cs_old, verbose=False)
    raw_writes = [w for w in plan['writes'] if w.get('raw')]
    in_img = raw_covered = out_of_scope_texty = 0
    noise_unchanged = noise_changed = 0
    noise_examples = []
    noise_by_container = {}
    for h in hits:
        nm = h.get('container') or who(plan['regions'], h['off'])
        if RE_MOD.match(r'^(MENU\.IMG|GR\.IMG)#\d+ ', nm):
            in_img += 1                            # 由容器扫描 + 门禁 A / 容器判别覆盖
            continue
        if any(w['iso_off'] <= h['off'] < w['iso_off'] + w['frame_bytes'] for w in raw_writes):
            raw_covered += 1                       # 原位重映射, 已由门禁 A 覆盖
            continue
        if texty(h):
            out_of_scope_texty += 1
            raise CompactError('门禁 B: IMG 之外的"真文本"段没被重编码: %s @%d %r'
                               % (nm, h['off'], h['text'][:40]))
        seg = iso_d.read(h['off'], h['nbytes'])
        t1, _ = cs_old.decode(seg)
        t2, _ = cs_new.decode(seg)
        noise_by_container[nm] = noise_by_container.get(nm, 0) + 1
        if t1 == t2:
            noise_unchanged += 1
        else:
            noise_changed += 1
            if len(noise_examples) < 5:
                noise_examples.append(dict(container=nm, off=h['off'], text=t1[:40]))
    iso_d.close()
    out['scan'] = dict(src_runs=len(hits), in_img_entries=in_img, in_raw_rewrites=raw_covered,
                       out_of_scope_texty=out_of_scope_texty,
                       noise_unchanged=noise_unchanged, noise_changed=noise_changed,
                       noise_by_container=dict(sorted(noise_by_container.items(),
                                                      key=lambda kv: -kv[1])[:20]),
                       noise_examples=noise_examples,
                       note=('IMG 条目内的命中由"容器扫描 + 容器判别"负责 (压缩数据里的巧合不算文本, '
                             '真文本看展开态); 这里只复核 IMG 之外的段'))
    ok('B 全盘扫描复核', '命中 %d 段 = IMG 条目内 %d (容器扫描负责) + 原位重映射 %d + '
                         'IMG 之外二进制巧合 %d (换码后意义不变的 %d) + 范围外真文本 %d; '
                         '细扫: ≥%d 连续汉字段 %d (IMG 之外 %d) → 真文本 %d 段'
       % (len(hits), in_img, raw_covered, noise_unchanged + noise_changed,
          noise_unchanged, out_of_scope_texty,
          (plan.get('scan') or {}).get('short', {}).get('min_cjk', SCAN_MIN_CJK),
          (plan.get('scan') or {}).get('short', {}).get('runs', 0),
          (plan.get('scan') or {}).get('short', {}).get('runs_outside_img', 0),
          (plan.get('scan') or {}).get('short', {}).get('text_runs', 0)))

    # ---- D: 紧凑性断言 (用户的核心诉求, 逐槽位核对) ----
    cs_now = res['cs_new']
    used_now = sorted(tcslib.pair_slot(*v) for ch, v in cs_now.enc_pair.items()
                      if LEAD_LO <= v[0] < LEAD_HI)
    if len(set(used_now)) != res['n_used']:
        raise CompactError('门禁 D: 在用槽位数 %d ≠ %d' % (len(set(used_now)), res['n_used']))
    free_now = sorted(set(range(tcslib.pair_capacity())) - set(used_now))
    checks = dict(used_is_prefix=(used_now == list(range(res['n_used']))),
                  free_is_tail=(free_now == list(range(res['n_used'], tcslib.pair_capacity()))))
    out['layout'] = dict(n_used=res['n_used'], n_free=len(free_now),
                         used_min=used_now[0], used_max=used_now[-1],
                         free_min=free_now[0], free_max=free_now[-1], **checks)
    if not (checks['used_is_prefix'] and checks['free_is_tail']):
        raise CompactError('门禁 D: 紧凑性不满 —— 在用 %s / 空闲 %s'
                           % ('=0..%d' % (res['n_used'] - 1) if checks['used_is_prefix'] else '不连续',
                              '=%d..1503' % res['n_used'] if checks['free_is_tail'] else '不连续'))
    ok('D 紧凑性: 在用 = slot 0..%d, 空闲 = slot %d..%d' % (res['n_used'] - 1, res['n_used'],
                                                              tcslib.pair_capacity() - 1),
       '逐槽位核对 %d + %d' % (len(used_now), len(free_now)))

    # ---- E: 幂等 ----
    res2 = plan_compact(dst_iso, charset_path=res['charset_path'], verbose=False,
                        charset_obj=res['cs_new'])
    if res2['summary']['changed']:
        raise CompactError('门禁 E: 对产物再跑一次 plan 仍有改动 (%d 像素 / %d 码位) —— 不幂等'
                           % (res2['summary']['pixels_changed'], res2['summary']['code_changes']))
    ok('E 幂等: 对产物再跑一次 plan', '0 像素改动 / 0 码位变更')
    out['checks_ok'] = len(out['checks'])
    return out


# ═══════════════════════ ⑧ charset 提交 ═══════════════════════

def commit_charset(charset_path, res, summ, verbose=True):
    """只改 `pair_of` 的码位 + 追加 `_font_compact` 元信息; 其余字段**逐字节**不变。"""
    before = io.open(charset_path, encoding='utf-8').read()
    js = json.loads(before)
    before_pairs = dict((k, list(v)) for k, v in js['pair_of'].items())
    for ch, code in res['pair_new'].items():
        lead, trail = code
        if not (LEAD_LO <= lead < LEAD_HI):
            raise CompactError('%r 的新 lead 0x%02X 越出引擎可读区间' % (ch, lead))
        js['pair_of'][ch] = [lead, trail]
    prev = js.get('_font_compact') or {}
    js['_font_compact'] = dict(
        note=('round56 起: 构筑管线每轮自动把在用字形**紧凑重排**到 slot 0..N-1, 未使用区域清零, '
              '并把盘上全部旧编码文本整体重编码 (**r58 起**: 容器级登记表 *_STRINGS.RES / '
              '*_STRINGS.TXT / *_SPECIAL_FEATURE.XML / IGORHELP.TXT 全部逐段闭环重映射 + '
              '全盘粗扫长文本 + 细扫短串(≥2 连续汉字, 含 ELF 载入提示条) + 一次性"陈旧码表追平"'
              '迁移); 顺序 = %s' % ORDER_KEY),
        tool=TOOL, tool_version=TOOL_VERSION,
        last_applied=time.strftime('%Y-%m-%d %H:%M:%S'),
        first_applied=prev.get('first_applied') or time.strftime('%Y-%m-%d %H:%M:%S'),
        used=summ['glyphs']['used'], moved_last=summ['glyphs']['moved'],
        codes_changed_last=summ['code_changes'],
        free_slots='%d..%d' % (summ['glyphs']['used'], tcslib.pair_capacity() - 1),
        atlas_pixel_sha256=summ.get('atlas_pixel_sha256'),
        reencode=summ.get('reencode'),
        iso_sha256=summ.get('iso_sha256_after') or summ.get('iso_sha256'))
    io.open(charset_path, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(js, ensure_ascii=False, indent=1) + '\n')
    after = json.load(io.open(charset_path, encoding='utf-8'))
    # ---- 自检: 除 pair_of 与 _font_compact 外, 其余字段逐一相同 ----
    for k in set(before_pairs) | set(after['pair_of']):
        pair_new = after['pair_of'][k]
        if k in res['pair_new']:
            if tuple(pair_new) != tuple(res['pair_new'][k]):
                raise CompactError('charset 自检: %r 的 pair_of 不是设计值 %s'
                                   % (k, res['pair_new'][k]))
        elif before_pairs.get(k) != list(pair_new):
            raise CompactError('charset 自检: %r 的 pair_of 不该改却被改了' % k)
    j0, j1 = json.loads(before), json.load(io.open(charset_path, encoding='utf-8'))
    for k in set(j0) | set(j1):
        if k in ('pair_of', '_font_compact'):
            continue
        if j0.get(k) != j1.get(k):
            raise CompactError('charset 自检: 字段 %r 变了 (只允许改 pair_of + 追加 _font_compact)' % k)
    # ---- 逐字自检: 每个在用字都能编码成新槽位的字节 ----
    cs2 = tcslib.Charset(charset_path)
    for s, ch in res['items']:
        want = bytes(tcslib.pair_from_slot(res['move'][ch]))
        if cs2.encode_strict(ch) != want:
            raise CompactError('charset 自检: %r 编码 %s ≠ 期望 %s'
                               % (ch, cs2.encode_strict(ch).hex(), want.hex()))
    if verbose:
        print('  [json] charset 已更新 %d 个码位 (只改 pair_of), 自检 ✓ (%s)'
              % (len(res['pair_new']), rel(charset_path)))
    return len(res['pair_new'])


def stamp_charset(version, iso_sha, charset_path=None):
    """把"这份 charset 配的是哪张盘"记进 charset JSON (旁证字段; 失败不影响构筑)。"""
    charset_path = charset_path or tcslib.CHARSET
    try:
        js = json.load(io.open(charset_path, encoding='utf-8'))
        fc = js.get('_font_compact')
        if not isinstance(fc, dict):
            fc = dict(note='round56 起: 构筑管线每轮自动紧凑重排字库 (font_compact.py)')
            js['_font_compact'] = fc
        fc['iso_sha256'] = iso_sha
        fc['iso_version'] = version
        fc['stamped'] = time.strftime('%Y-%m-%d %H:%M:%S')
        io.open(charset_path, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(js, ensure_ascii=False, indent=1) + '\n')
        return True
    except Exception as e:                                           # noqa: BLE001
        print('[font-compact] ⚠ charset 打戳失败 (不影响构筑): %s' % e)
        return False


# ═══════════════════════ ⑨ 报告 / CLI ═══════════════════════

def print_report(summ, verbose=True):
    g, c, lay = summ['glyphs'], summ['cells'], summ['layout']
    print('')
    print('─' * 78)
    print('字库紧凑重排 + 全盘重编码 — %s' % ('**有改动**' if summ['changed'] else '无需重排 (0 改动)'))
    print('─' * 78)
    print('  图集        : %dx%d psm=0x%02X, %d 段封包, 墨点 %d → %d'
          % (summ['atlas']['w'], summ['atlas']['h'], summ['atlas']['psm'],
             summ['atlas']['segments'], summ['atlas']['ink_before'], summ['atlas']['ink_after']))
    print('  对偶槽位    : %d = **在用 %d** + 空闲 %d (其中可用格 %d, 记录码占死 %d)'
          % (c['total'], g['used'], lay['n_free'], lay['n_free_usable'], c['record_cell']))
    print('  ★ 布局      : 在用 = slot %d..%d ; 空闲 = slot %d..%d'
          % (lay['used_slots'][0], lay['used_slots'][1], lay['free_slots'][0],
             lay['free_slots'][1]))
    print('                prefix_ok=%s  tail_ok=%s' % (lay['used_prefix_ok'],
                                                       lay['free_tail_ok']))
    print('  搬运        : %d 个字 (原地不动 %d), 改码位 %d 个, 清空可用格 %d 个'
          % (g['moved'], g['kept'], summ['code_changes'], lay['n_free_usable']))
    if summ.get('reencode'):
        print('  重编码      : %d 个容器 / %d 字节改动'
              % (summ['reencode']['containers'], summ['reencode']['changed_bytes']))
    if summ.get('stale_migration'):
        m = summ['stale_migration']
        print('  ★ 陈旧追平  : %s (陈旧码表 = %s; 清单 %d 条: 追平 %d / 已现役 %d)'
              % (m['name'], m['stale_label'], m['n_entries'], m['roles']['migrate'],
                 m['roles']['current']))
    if summ.get('gate') and summ['gate'].get('registry'):
        rg = summ['gate']['registry']
        print('  登记容器    : %d 个逐条校验 ✓ (%s); 段 %d = 重映射 %d + 未变 %d, 改动 %d 字节'
              % (rg['containers'],
                 ', '.join('%s %d' % kv for kv in sorted(rg['by_role'].items())),
                 rg['segments'], rg['segments_changed'], rg['segments_unchanged'],
                 rg['changed_bytes']))
    if summ.get('scan') and summ['scan'].get('short'):
        s = summ['scan']['short']
        print('  短串兜底    : 细扫 ≥%d 连续汉字段 %d (IMG 之外 %d) → 真文本 %d 段 / %d 条串, '
              '写盘 %d 条, 跳过 %d 段' % (s['min_cjk'], s['runs'], s['runs_outside_img'],
                                          s['text_runs'], s['text_cstrs'], s['remapped'],
                                          s['skipped']))
        for c in s.get('detail', [])[:12]:
            print('                · @0x%-8X %-14r (对偶码比 %.2f, 改 %d 字节)%s'
                  % (c['off'], c['text'], c['pair_ratio'], c['changed_bytes'],
                     '  ← 已知文本区: %s' % c['known'] if c['known'] else ''))
    print('─' * 78)


def main():
    ap = argparse.ArgumentParser(description='字库紧凑重排 + 全盘重编码 (round56; 取代 repack_font)')
    ap.add_argument('--iso', required=True, help='源盘 (只读; 除非 --in-place)')
    ap.add_argument('--out-iso', default=None, help='紧凑 + 重编码后的盘 (有改动时必须给)')
    ap.add_argument('--charset', default=None, help='charset JSON (默认 tcslib.CHARSET)')
    ap.add_argument('--no-charset', action='store_true', help='不写 charset JSON (调试)')
    ap.add_argument('--dry-run', action='store_true', help='只算不写')
    ap.add_argument('--in-place', action='store_true', help='直接改 --iso 自己 (构筑管线内部用)')
    ap.add_argument('--text-src', default=None, help='"强制重编码"文本表的来源 (表/目录)')
    ap.add_argument('--reencode-out', default=None, help='重编码表输出目录')
    ap.add_argument('--report', default=None, help='方案 summary 写 JSON')
    ap.add_argument('--moves-out', default=None, help='逐字搬运明细写 JSON')
    ap.add_argument('--json', action='store_true', help='终端只打一行 JSON 摘要')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()
    charset_path = a.charset or tcslib.CHARSET

    res = plan_compact(a.iso, charset_path, verbose=not a.quiet)
    res['charset_path'] = charset_path
    summ = res['summary']
    if not a.quiet and not a.json:
        print_report(summ)

    if not summ['changed']:
        if not a.quiet:
            print('  [幂等] 字库已经紧凑 + 码位无需变更 ⇒ **不产出任何文件** (产物就是输入盘)')
        summ['wrote_iso'] = None
        summ['iso_sha256_after'] = summ['iso_sha256']
        re_ = dict(units=[], writes=[], scan=None, regions=[])
    else:
        if a.dry_run:
            if not a.quiet:
                print('  [dry ] 有改动, 但 --dry-run ⇒ 不写盘')
            summ['wrote_iso'] = None
            re_ = dict(units=[], writes=[], scan=None, regions=[])
        else:
            out = a.iso if a.in_place else a.out_iso
            if not out:
                raise SystemExit('!! 有改动但没有 --out-iso (或加 --in-place / --dry-run)')
            print('')
            print('──── 重编码方案 (文本容器 + 全盘兜底扫描)')
            iso = tcslib.Iso(a.iso)
            re_ = plan_reencode(iso, res, verbose=not a.quiet)
            iso.close()
            summ['scan'] = re_['scan']
            print('')
            print('──── 写盘')
            apply(a.iso, out, res, re_, verbose=not a.quiet)
            print('')
            print('──── ★ 全盘一致性自检 (硬门禁)')
            try:
                g = gate(out, res, re_, verbose=not a.quiet)
            except CompactError as e:
                print('')
                print('!' * 78)
                print('[!!] ★ 全盘一致性自检**没过** ⇒ 中止, 不写 charset:')
                print('     %s' % e)
                restore(out, res, re_, verbose=not a.quiet)
                if os.path.abspath(out) != os.path.abspath(a.iso):
                    os.remove(out)
                    print('     [restore] 已删除半成品 %s (输入盘未动)' % rel(out))
                print('!' * 78)
                raise
            summ['gate'] = g
            if not a.no_charset:
                commit_charset(charset_path, res, summ, verbose=not a.quiet)
            if not a.quiet and not a.json:
                print('  [out ] → %s  sha256 %s…' % (rel(out), summ['iso_sha256_after'][:16]))

    if a.text_src and a.reencode_out:
        if summ['changed'] and not a.dry_run:
            print('[reencode] 生成"强制重编码"文本表 (只清 text_zh 列; text_edited 一字不动):')
            summ['reencode_tables'] = RF.make_reencode_tables(a.text_src, a.reencode_out)
        else:
            print('[reencode] %s ⇒ 不生成' % ('dry-run' if a.dry_run else '无需重排'))
    if a.report:
        os.makedirs(os.path.dirname(os.path.abspath(a.report)), exist_ok=True)
        io.open(a.report, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(dict(summary=summ, gate=summ.get('gate'), scan=summ.get('scan')),
                       ensure_ascii=False, indent=1) + '\n')
        print('[rep ] → %s' % rel(a.report))
    if a.moves_out:
        os.makedirs(os.path.dirname(os.path.abspath(a.moves_out)), exist_ok=True)
        io.open(a.moves_out, 'w', encoding='utf-8', newline='\n').write(json.dumps(dict(
            order_key=ORDER_KEY, moved=summ['glyphs']['moved'], kept=summ['glyphs']['kept'],
            changes=res['code_changes'],
            layout=[dict(slot=res['move'][ch], char=ch, x=res['cells'][res['move'][ch]]['x'],
                         y=res['cells'][res['move'][ch]]['y']) for _s, ch in res['items']],
        ), ensure_ascii=False, indent=1) + '\n')
        print('[rep ] → %s (逐字搬运明细)' % rel(a.moves_out))
    if a.json:
        print(json.dumps(dict(changed=summ['changed'], used=summ['glyphs']['used'],
                              moved=summ['glyphs']['moved'], code_changes=summ['code_changes'],
                              pixels_changed=summ['pixels_changed'],
                              used_prefix_ok=summ['layout']['used_prefix_ok'],
                              free_tail_ok=summ['layout']['free_tail_ok'],
                              iso_sha256=summ.get('iso_sha256_after') or summ['iso_sha256'],
                              wrote_iso=summ.get('wrote_iso'),
                              gate_checks=(len(summ['gate']['checks'])
                                           if summ.get('gate') else 0)),
                         ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
