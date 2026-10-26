# -*- coding: utf-8 -*-
import hashlib
import io
import json
import os
import shutil

# 文档 §45
p = 'docs/ANALYSIS_ELF.md'
s = io.open(p, encoding='utf-8').read()
if '## 45.' not in s:
    s = s.rstrip() + '''

---

## 45. 启动「Loading... / Please wait!」文本汉化

### 45.1 位置与结构

ELF 里有两张 **5 语言载入提示槽表**（纯 ASCII 字符串，原位覆盖，指针不变）：

| 表 | 文件偏移 | 内容 |
|---|---|---|
| A | 0x487040–0x487109 | FR「Chargement en cours... / Veuillez patienter」、DE、IT、ES、EN「Loading... / Please wait」 |
| B | 0x48D810–0x48D868 | 同上 5 语言的单行「载入中…」（另一处对话框） |

槽长按相邻字符串间隔计算；英文首行 10 B（"Loading..." + NUL = 11 B）。

### 45.2 做法

`build.py --stage spec` 新增 `BOOT_TEXT_SLOTS` / `boot_text_patches()`：
- 用 `textlib.Charset` 把中文编码成对偶码字节（与 LANG 注入同一套码表）；
- 按槽长选文案，原位写「中文 + NUL + 零填充」，补丁长度对齐 4 字节（ELF 补丁表要求）；
- 5 语言全部换成中文，避免语言配置不同而漏翻：
  - 长槽：「正在载入中...」/「请稍候，正在载入...」
  - 中槽：「载入中...」
  - 短槽（DE 8 B）：「载入...」
  - wait 槽：「请等待...」

### 45.3 实机验证（v81）

- 启动约 99 s 的加载圆环画面：`Loading...` → **「载入中...」**（游戏字体渲染，字形正常），
  见 `docs/img/loading_v81.png`；
- 其他界面不受影响（只改 ELF 字符串槽）；
- verify 40/40，ELF `4DA16CCF…`，Game CRC `E0325951`。

### 45.4 关于「读盘提示是预渲染纹理」

- PS2 开机时主机的 **"Reading disc..."** 是 **BIOS/主机固件** 绘制，不在游戏 ISO 内，
  无法通过改盘汉化；
- 本游戏自己的加载画面背景（load-screen 纹理）经检查**不含烘焙文字**，"Loading..." 是文本，
  已按上面方案汉化。若后续看到某屏确有烘焙文字，需要单独做纹理重绘（LOADING.PAK 的纹理段是
  ty=2 压缩，压缩算法尚未识别，暂不可无损替换）。
'''
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s + '\n')
    print('§45 added')

fin = r'work\builds\FINAL'
src = r'work\builds\v81.iso'
dst = os.path.join(fin, 'GR_JS_ZH_v81_candidate.iso')
if os.path.exists(src):
    # 删除旧候选盘（只保留最新）
    for f in os.listdir(fin):
        if f.lower().endswith('.iso') and f != os.path.basename(dst):
            os.remove(os.path.join(fin, f))
    shutil.copy2(src, dst)
    h = hashlib.sha256(open(dst, 'rb').read()).hexdigest()
    info = dict(version='v81-candidate', iso=os.path.basename(dst),
                bytes=os.path.getsize(dst), sha256=h,
                changes=['启动加载画面文本「Loading...」→「载入中...」，wait 槽 →「请等待...」'
                         '（ELF 两张 5 语言槽表共 15 处原位替换）',
                         '保留 v80：任务目标行 y 修正（cave G）、训练提示 29 字/行、折行英文词保护',
                         'Game CRC E0325951（旧即时存档需新开档）'],
                elf_sha256='4da16ccf4e5eb9509bb064bba5e9fb6b09f568a9fb4d5fc3a74831bc6c408bc4',
                game_crc='E0325951', verify='40/40')
    json.dump(info, open(os.path.join(fin, 'BUILD_INFO_v81_candidate.json'), 'w',
                         encoding='utf-8'), ensure_ascii=False, indent=2)
    for f in os.listdir(fin):
        if f.startswith('BUILD_INFO_v') and f != 'BUILD_INFO_v81_candidate.json':
            os.remove(os.path.join(fin, f))
    sums = []
    for f in sorted(os.listdir(fin)):
        if f.lower().endswith('.iso'):
            sums.append('%s  %s' % (hashlib.sha256(open(os.path.join(fin, f), 'rb').read()).hexdigest(), f))
    open(os.path.join(fin, 'SHA256SUMS.txt'), 'w', encoding='utf-8', newline='\n').write('\\n'.join(sums) + '\\n')
    print('v81 candidate packaged', h)
else:
    print('v81.iso missing')
