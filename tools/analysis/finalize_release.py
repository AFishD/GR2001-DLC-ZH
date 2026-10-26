# -*- coding: utf-8 -*-
"""finalize_release.py —— v1.0 最终版：重命名成品盘、写 BUILD_INFO/README/SHA，更新仓库文档。"""
import hashlib
import io
import json
import os
import re

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
FIN = os.path.join(REPO, 'work', 'builds', 'FINAL')
OLD_ISO = os.path.join(FIN, 'GR_JS_ZH_v81_candidate.iso')
NEW_ISO = os.path.join(FIN, 'GR_JS_ZH_v1.0_final.iso')


def read(p):
    return io.open(p, encoding='utf-8').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


# ---------- 1) 成品盘 ----------
if os.path.exists(OLD_ISO):
    if os.path.exists(NEW_ISO):
        os.remove(NEW_ISO)
    os.replace(OLD_ISO, NEW_ISO)
assert os.path.exists(NEW_ISO), NEW_ISO
h = hashlib.sha256(open(NEW_ISO, 'rb').read()).hexdigest()
size = os.path.getsize(NEW_ISO)

for f in os.listdir(FIN):
    if f in ('BUILD_INFO.json',) or (f.startswith('BUILD_INFO_') and f != 'BUILD_INFO_FINAL.json'):
        os.remove(os.path.join(FIN, f))

info = dict(
    version='v1.0-final', iso=os.path.basename(NEW_ISO), bytes=size, sha256=h,
    base_iso_sha256='292f5a6a050e82e05efb5bf9fd5ce3bc12706a8ae57c78b729348a5c80fd0767',
    elf_sha256='4da16ccf4e5eb9509bb064bba5e9fb6b09f568a9fb4d5fc3a74831bc6c408bc4',
    game_crc='E0325951', verify='40/40',
    changes=[
        '全文本中文 3,372/3,372（LANG 2,494 / SFXML 81 / MIS 45），缺字 0',
        '训练/任务提示：严格 29 汉字/行（行尾不可见半角空格顶宽，引擎在空格处断行），英文单词不跨行',
        '简报「任务目标」行与分栏线对齐（cave G，y≥265 数字/X 开头行 −3px）',
        '启动加载画面「Loading...」→「载入中...」，「Please wait」槽 →「请等待...」（ELF 5 语言槽表 15 处）',
        '队员设置姓名/开始按钮、难度滚动栏、训练/战术/快速任务列表基线、武器属性简介折行修复',
        'PS2 BIOS 的「Reading disc / Accessing memory card」属主机固件画面，不在游戏盘内（见 docs/ANALYSIS_ELF.md §46）',
    ],
    verify_cmd='python tools\\dlc\\verify.py --iso work\\builds\\FINAL\\GR_JS_ZH_v1.0_final.iso --stage all',
)
write(os.path.join(FIN, 'BUILD_INFO_FINAL.json'), json.dumps(info, ensure_ascii=False, indent=2) + '\n')

readme = '''《幽灵行动：丛林风暴》PS2 简体中文汉化版 v1.0（最终版）
================================================

文件：GR_JS_ZH_v1.0_final.iso
SHA256：%s
尺寸：%d B
基底：Tom Clancy's Ghost Recon: Jungle Storm (U), SLUS-20820 英文原盘
      （原盘 sha256 292f5a6a…0767）
汉化：全文本中文 3,372/3,372 条（LANG 2,494 / SFXML 81 / MIS 45），缺字 0
字体：中文 16×16 点阵图集（1024×644 PSMT4），2,350 槽
ELF SHA256：4DA16CCF4E5EB9509BB064BBA5E9FB6B09F568A9FB4D5FC3A74831BC6C408BC4
Game CRC：E0325951（与原版不同 —— 补丁所致；旧即时存档不兼容，请新开档或改名）

内容与修复（v1.0 汇总）：
1) 全文本中文：菜单 / 简报 / 任务名 / 制作名单 / 特别收录 / 训练提示等。
2) 训练/任务提示：严格 29 个汉字/行（行尾不可见半角空格顶宽，引擎在空格处断行），
   ASCII 单词不跨行（START 完整）。
3) 简报「任务目标」：与面板分栏线对齐（cave G 修正 y≥265 的目标行 −3px）。
4) 启动加载画面：Loading... →「载入中...」，Please wait 槽 →「请等待...」
   （ELF 内 5 语言槽表共 15 处原位替换）。
5) 队员设置：A/B 组姓名行居中；B 组三人名 +5px；开始按钮居中。
6) 难度选择：三行与中央滚动栏居中一致。
7) 训练/战术演习/快速任务：列表行统一基线，不再部分居中部分靠上/靠下。
8) 武器属性简介：清除字面 CRLF 造成的空行/孤行，按 14 全宽字重折，词不拆。

说明：
- 游戏内读卡/记忆卡对话框文本（G058.I1162 等）已中文化。
- PS2 主机 BIOS 的「Reading disc... / Accessing memory card...」是主机固件画面，
  不属于游戏盘内容，无法通过本 ISO 汉化（详见 docs/ANALYSIS_ELF.md §46）。
- 标题画面「Press START button」等引擎内置英文不在本轮范围内。

验证：python tools\\dlc\\verify.py --stage all → 40/40
''' % (h, size)
write(os.path.join(FIN, 'README.txt'), readme)
write(os.path.join(FIN, 'SHA256SUMS.txt'), '%s  %s\n' % (h, os.path.basename(NEW_ISO)))

# ---------- 2) README.md ----------
p = os.path.join(REPO, 'README.md')
s = read(p)
new_status = '''## 当前状态（最终版 v1.0，2026-10-26）

**汉化已完成，最终成品：`work\\builds\\FINAL\\GR_JS_ZH_v1.0_final.iso`**
（sha256 `%s`，Game CRC `E0325951`，verify 40/40）

= 英文原盘 + 中文图集/合并 FONT.RES + 45 缺字补画 + DBCS v2 ELF + 3,372/3,372 条译文
+ 战役卡死修复（RSString 串越界/NULL 守卫）
+ 换行边界根治（DBCS 整字折行 + 行首 +1 修正）
+ 手柄图标恢复（引擎图标码换区）
+ 队员设置/难度/任务列表基线统一 + 简报任务目标行对齐（cave G）
+ 训练/任务提示严格 29 汉字/行（行尾半角空格顶宽）
+ 启动加载画面 Loading... →「载入中...」「请等待...」（ELF 5 语言槽表）

唯一构筑脚本 `tools\\dlc\\build.py`（stage: spec/font/text/elf/all）可从英文原盘一键复现；
verify.py **40/40** 通过、audit.py 缺字 0。PS2 BIOS 的读盘/记忆卡提示属主机固件，不在游戏盘内
（见 [`docs/ANALYSIS_ELF.md`](docs/ANALYSIS_ELF.md) §46）；其余细节见
[`docs/REPORT_FINAL_DELIVERY.md`](docs/REPORT_FINAL_DELIVERY.md) 与 [`docs/STATUS.md`](docs/STATUS.md)。

''' % h[:16] + '…' if False else '''## 当前状态（最终版 v1.0，2026-10-26）

**汉化已完成，最终成品：`work\\builds\\FINAL\\GR_JS_ZH_v1.0_final.iso`**
（sha256 `%s`，Game CRC `E0325951`，verify 40/40）

= 英文原盘 + 中文图集/合并 FONT.RES + 45 缺字补画 + DBCS v2 ELF + 3,372/3,372 条译文
+ 战役卡死修复（RSString 串越界/NULL 守卫）
+ 换行边界根治（DBCS 整字折行 + 行首 +1 修正）
+ 手柄图标恢复（引擎图标码换区）
+ 队员设置/难度/任务列表基线统一 + 简报任务目标行对齐（cave G）
+ 训练/任务提示严格 29 汉字/行（行尾半角空格顶宽）
+ 启动加载画面 Loading... →「载入中...」「请等待...」（ELF 5 语言槽表）

唯一构筑脚本 `tools\\dlc\\build.py`（stage: spec/font/text/elf/all）可从英文原盘一键复现；
verify.py **40/40** 通过、audit.py 缺字 0。PS2 BIOS 的读盘/记忆卡提示属主机固件，不在游戏盘内
（见 [`docs/ANALYSIS_ELF.md`](docs/ANALYSIS_ELF.md) §46）；其余细节见
[`docs/REPORT_FINAL_DELIVERY.md`](docs/REPORT_FINAL_DELIVERY.md) 与 [`docs/STATUS.md`](docs/STATUS.md)。

''' % h
# 用正则替换“## 当前状态 …”到下一个“## 我需要看哪一篇”
s2 = re.sub(r'## 当前状态.*?\n(?=## 我需要看哪一篇)', lambda m: new_status, s, count=1, flags=re.S)
if s2 == s:
    print('WARN: README 状态段未替换')
write(p, s2)

# ---------- 3) STATUS.md ----------
p = os.path.join(REPO, 'docs', 'STATUS.md')
s = read(p)
head = '''# STATUS —— 现状

更新时间：2026-10-26（**最终版 v1.0**，verify 40/40）

## 一句话

**汉化已完成并交付最终版**：中文图集 + 合并 FONT.RES + DBCS v2 ELF + A‴ 行盒锚点 +
串越界/NULL 守卫（战役卡死修复）+ 3,372/3,372 条译文 + 列表/提示框排版修复 +
简报任务目标对齐 + 训练提示严格 29 汉字/行 + 启动加载文本汉化；
从英文原盘一键重建、verify 40/40 通过。

## 最终成品盘

```
work/builds/FINAL/GR_JS_ZH_v1.0_final.iso (%d B, CRC E0325951, sha256 %s)
  = 英文原盘 + 中文图集(1024×644 PSMT4) + 合并 FONT.RES + 45 缺字补画
  + DBCS v2 ELF + 字库最近邻过滤 + A‴ 行盒锚点 + 串越界/NULL 守卫
  + 3,372/3,372 译文（LANG/SFXML/MIS/ATR/TXT）
  + cave G（简报任务目标行 −3px 对齐分栏线）
  + 29 汉字/行提示（行尾半角空格顶宽）+ ELF 5 语言载入槽表汉化
  verify: 40/40 PASS ; audit: 缺字 0
```

''' % (size, h)
s2 = re.sub(r'# STATUS —— 现状.*?(?=## 基线身份)', lambda m: head, s, count=1, flags=re.S)
if s2 == s:
    print('WARN: STATUS 头部未替换')
write(p, s2)

# ---------- 4) REPORT_FINAL_DELIVERY.md ----------
p = os.path.join(REPO, 'docs', 'REPORT_FINAL_DELIVERY.md')
s = read(p)
s = s.replace('> 版本：v4 候选（2026-10-21）',
              '> 版本：**v1.0 最终版（2026-10-26）**（本报告 A 节之后的正文为早期版本记录，最终交付以 A.0 为准）')
s = s.replace('''| 路径 | work\\builds\\FINAL\\GR_JS_ZH.iso（= JS_ZH_v6.iso；本地生成，不入库） |
| 尺寸 | 1,229,264,896 B（原盘 1,229,225,984 B，+38,912 B） |
| sha256 | ed54ee7794e94fce938d12bf715b4913367520f7c6e91d78adff795c62e51917 |
| Game CRC | `ED1D6AD4`（原版 `DE1E4DEE`；ELF 打 DBCS 补丁后改变，旧存档/金手指失效，需新开档） |''',
'''| 路径 | work\\builds\\FINAL\\GR_JS_ZH_v1.0_final.iso |
| 尺寸 | %d B |
| sha256 | %s |
| Game CRC | `E0325951`（原版 `DE1E4DEE`；ELF 打 DBCS 补丁后改变，旧存档/金手指失效，需新开档） |''' % (size, h))
s = s.replace('| 自证 | python tools\\dlc\\verify.py --stage all → **38/38 断言通过** |',
              '| 自证 | python tools\\dlc\\verify.py --stage all → **40/40 断言通过** |')
marker = '## Z. 最终版（v1.0，2026-10-26）'
if marker not in s:
    s = s.rstrip() + '''

---

## Z. 最终版（v1.0，2026-10-26）

- 最终成品：`work/builds/FINAL/GR_JS_ZH_v1.0_final.iso`
  - sha256 `%s`，Game CRC `E0325951`，verify **40/40**；
- 自此版本起包含的增量修复（v21→v81 汇总）：
  1) 队员设置：A/B 组姓名行居中、B 组三人名 +5px、开始按钮居中；
  2) 难度选择：三行与中央滚动栏对齐；
  3) 训练/战术/快速任务列表：统一基线，消除部分居中/部分靠上；
  4) 武器属性简介：清除字面 CRLF 空行，14 全宽字重折；
  5) 简报「任务目标」行：cave G（y≥265、数字/X 开头）−3px 与分栏线对齐；
  6) 训练/任务提示：严格 29 汉字/行（行尾半角空格顶宽，引擎在空格处断行），英文单词不拆；
  7) 启动加载画面：Loading... →「载入中...」，Please wait →「请等待...」（ELF 5 语言槽表）；
- 已知范围外：PS2 BIOS 的「Reading disc / Accessing memory card」为固件画面，不在游戏盘内（§46）。
''' % h
write(p, s + '\n' if not s.endswith('\n') else s)

# ---------- 5) ANALYSIS_ELF §47 ----------
p = os.path.join(REPO, 'docs', 'ANALYSIS_ELF.md')
s = read(p)
if '## 47.' not in s:
    s = s.rstrip() + '''

---

## 47. 最终版 v1.0 交付说明（2026-10-26）

最终成品：`work/builds/FINAL/GR_JS_ZH_v1.0_final.iso`
- sha256 `%s`；ELF `4DA16CCF…`；Game CRC `E0325951`；verify 40/40；
- ELF 侧最终补丁集：DBCS v2 + 图标码换区 + 行盒锚点 + cave F（B组姓名 +5px）
  + cave G（简报任务目标行 −3px）+ 串越界/NULL 守卫 + 大小写折叠守卫
  + cave H2（折行英文词保护）+ 启动载入槽表 15 处汉化；
- 已知范围外：PS2 BIOS 读盘/记忆卡界面（见 §46）。
''' % h
write(p, s + '\n' if not s.endswith('\n') else s)

print('FINAL', h, size)
