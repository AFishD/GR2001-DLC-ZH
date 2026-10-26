# BUILD_GUIDE —— 从英文原盘一键重建正式版

> 面向"未来的你"：隔了三个月回来，只想知道**怎么从零把这盘做出来**。
> 所有命令都在仓库根执行，PowerShell 5.1 与 Python 3.8 已验证。
> 相关：`docs/STATUS.md`（现状）· `docs/MOD_GUIDE.md`（怎么改内容）· `tools/final_fix/README.md`

---

## 0. 一句话

```powershell
python tools\final_fix\build.py
```

16 个阶段、约 15–20 分钟、峰值磁盘约 6.5 GB，产出
`work\builds\FINAL\GR_ZH146.iso`（sha256 `98ed8579…ff9a`），最后自动跑 `verify.py` 的 28 条硬断言。

---

## 1. 需要"本地自备"的东西（**不进版本库**）

仓库里**故意不含**下列文件（版权 + 体积），`.gitignore` 已排除。缺少任何一项，`build.py`
会在第 0 步就报错退出，不会跑一半。

| 项 | 期望路径 | 指纹 | 说明 |
|---|---|---|---|
| **英文原盘 ISO** | `third_party\orig\ps2\Tom Clancy's Ghost Recon (USA).iso` | sha256 `2b42ea7ce9bd0a85972a07ca59b1b9d79422ed318b85737db3cfd17daa788531`（1,648,164,864 B） | 唯一的合法基底。**必须**是美版 SLUS-206.13 |
| **K2 cdvd 块转储** | `%LOCALAPPDATA%\PCSX2\cdvd-dump\GR_FA2400_K2 (2026-10-17 15-08-20).dump` | sha256 `11f371f294e4f8e353c21931a9c38d73c1309832a21e74cfb3e31d7095daadd9`（74,286,520 B） | 取回被原盘压缩掉的块（第二块转储） |
| **像素字体** | `third_party\fonts\方正像素16.ttf` | （不校验；2,632,936 B） | 只用于把字表渲染进字库格子 |

> **为什么要 K2 转储**：英文原盘的 `SLUS_206.13` / 部分容器在 ISO 上是**块压缩**的，
> 单纯解 LZO 拿不到原始字节；K2 转储是模拟器在真机读取路径上抓的**扇区级**原始内容，
> 用来覆盖那些扇区。`rebuild_base.py` 会把「原盘 ⊕ K2 转储」合成 `GR_REBUILD2400.iso`。

可选覆盖：

```powershell
python tools\final_fix\build.py `
  --eng-iso  "D:\iso\Ghost Recon (USA).iso" `
  --k2-dump  "D:\dump\GR_FA2400_K2.dump" `
  --font-ttf "D:\fonts\方正像素16.ttf" `
  --out      "D:\out\GR_ZH146.iso"
```

---

## 2. 依赖

| 组件 | 版本 | 备注 |
|---|---|---|
| Python | **3.8**（3.8.0 实测） | 只需要标准库 + 下面两个 |
| numpy | 1.24.4 | 图集/位图运算 |
| Pillow | 10.4.0 | 字形渲染（TTF → 16px 位图） |
| PowerShell | 5.1 | **只有**本项目脚本用；`.ps1` 一律 ASCII，中文只在 `.py`/`.md` |

```powershell
python -c "import numpy, PIL; print(numpy.__version__, PIL.__version__)"
```

> ⚠ **PowerShell 5.1 两个坑**（踩过，别再踩）：
> ① 不要 `Get-Content -Raw | Set-Content -Encoding utf8` —— 会给文件加 BOM，Python 读 JSON 直接炸；
> ② `.ps1` 里的中文按 ANSI 解释，所以本轮起**所有脚本改成 `.py`**，不再写 `.ps1`。

---

## 3. 目录：构建链用到的每一块

```
tools/final_fix/
    build.py          ★ 唯一入口（按 fix_spec.json 执行 16 个阶段）
    verify.py         ★ 唯一校验入口（28 条硬断言 + FF 闸门）
    fix_spec.json     ★ 单一真源：阶段表 / 输入指纹 / 每阶段期望 sha256 / 闸门
    elf_patches.json    ELF 补丁逐字节表（apply_fix.py 的输入）
    assets/charset/     字符集：2300 对偶槽 + 103 单字节码（含 .before_zh130/.before_zh139 快照）
    assets/text/        文本表：enrich/（富文本）+ merge/（合并层 4 张 CSV）
    assets/mis/         任务名对照表 map.tsv（40 个 *.MIS 的目标名）
    <16 个阶段脚本>      每个阶段一个，独立可跑、可 --help、失败可单独重跑
tools/lib/            共用库：tcslib 之外的字体/图集/容器实现（dump_font/repack_font/
                      font_compact/glyph_geometry/iso_tools/zx_lib/lz77_decode/icon_table）
tools/text_csv/       文本表工具：dump_text_csv.py（导出）/ inject_text_csv.py（注入）/ tcslib.py
```

`build.py` 把三个目录都塞进子进程的 `PYTHONPATH`，所以阶段脚本之间可以直接互相 `import`。

---

## 4. 16 个阶段在干什么

| # | id | 工具 | 产出 sha256（前 12 位） | 一句话 |
|---|---|---|---|---|
| 1 | `base` | `rebuild_base.py` | `d7f83d7ec4a8` | 英文原盘 ⊕ K2 转储 ⇒ 2400 产品线基底 |
| 2 | `elf` | `apply_fix.py` | `e65e77fbb696` | 卡死修复四件套 F4 / F7 / F7b / OOMFIX（239 B / 70 段） |
| 3 | `glyph_edge` | `patch_zh130_glyph_edge.py` | `db3f8b997a9d` | 字库**右缘采样**修正（36 对偶换位 + `X` 三 face） |
| 4 | `stale` | `patch_zh133_stale_hashr.py` | `3fb12c8d16c2` | 旧码残留追赶（文本里遗留的旧哨兵码） |
| 5 | `text2` | `patch_zh134_textfix2.py` | `165b7eb2c667` | 文本层修正 #2 |
| 6 | `profile` | `patch_profile2_text.py` | `172b35cc9404` | 「著」= `0xFF` 被 XML 词法器当 EOF ⇒ 13 条专家档案改写 |
| 7 | `gate_ff` | `verify.py --ff-gate` | （不改盘） | **闸门**：文本区出现任何 `0xFF` 就 FAIL |
| 8 | `glyphs61` | `patch_zh138_glyphs61.py` | `7396f55cd8d4` | 61 个「有码无字」补画到自己的格子 |
| 9 | `chars139` | `patch_zh139_chars.py` | `33b9acd9341f` | 13 个实证生字 ⇒ 13 个零引用 PUA 槽 |
| 10 | `chars140` | `patch_zh140_chars.py` | `9ecd07af7396` | 9 个富文本生字 ⇒ 9 个 PUA 槽 |
| 11 | `enrich` | `inject_text_csv.py` | `83757ff1d1bf` | 富文本表注入（43 条 SFXML 长条目） |
| 12 | `chars141` | `patch_zh141_chars.py` | `a4238ef2ad45` | 3 个真字形 `…` `×` `惧` ⇒ 槽 2033..2035 |
| 13 | `merge_text` | `inject_text_csv.py` | `23b3f95187b8` | 合并文本层：39 正文 / 93 空行 / 57 特别收录标题 / 26 LANG 行 |
| 14 | `ike142` | `patch_zh142_ike.py` | `28e4bc915774` | 特别收录正文折行 270 → 286，面板 290 → 306 |
| 15 | `ike143` | `patch_zh143_ike.py` | `52145319c15d` | 折行再 +8px（286 → 294，面板不动） |
| 16 | `misnames40` | `patch_misnames40.py` | `4ded92e2fee5` | **40/40** 个 `*.MIS` 的 `<Name>` 汉化（可变长度 + 零填充） |

16 从 15 的产物出发，是全链唯一的"内容层"收尾。`build.py` 用引用计数决定
什么时候删中间盘（`consumers_after()`），不需要人工 `rm`。

### 每阶段的自证

`build.py` 对**每个**阶段比对 `fix_spec.json` 里的 `expect_sha256`：

```
  sha256 7d4e3297...   12.3s
  OK    == fix_spec.json
```

不符就立刻 `[FAIL]` 退出，绝不拿一张可疑的盘继续往下打。

---

## 5. 校验

```powershell
python tools\final_fix\verify.py                       # 校验默认成品
python tools\final_fix\verify.py --iso <别的盘>         # 校验任意一张
python tools\final_fix\verify.py --ff-gate --iso <盘>   # 只跑 FF 闸门（快）
```

28 条硬断言分 6 组：

| 组 | 内容 |
|---|---|
| **A 身份** | 尺寸 / sha256 / md5 / ISO9660 PVD / `SLUS_206.13` 在位 |
| **B ELF** | ELF sha256 / **Game CRC `653FBF69`** / ELF 大小 / ELF LBA 295 |
| **C 任务名** | `*.MIS` 40 个 / **中文 40 / 英文 0** / M15 = `M15 - 白刃` / 两副本一致 |
| **D 字库** | 2300 个对偶 / 103 个单字节码 / `…` `×` `惧` 已映射 |
| **E 文本** | LANG 条目 > 2000 / SFXML 69 条 `<text>` / 折行宽度 = 294 |
| **F 闸门** | 文本区 0 个 `0xFF` / 容器 > 4000 / 文本容器全可解压 / 与 `fix_spec.json` 一致 |

**Game CRC 为什么必须不变**：PCSX2 的即时存档名是 `SLUS-20613 (<CRC>).01.p2s`。
CRC 变了 ⇒ 玩家的旧存档/即时存档全部失效。`653FBF69` 是 2400 产品线一路继承下来的值，
从 `GR_ZH133` 起就没变过。

---

## 6. 幂等

* `--out` 已存在且 sha256 == `fix_spec.json` ⇒ 直接打印「已是最新（幂等）」并只跑校验，**不重建**。
* 要强制重建：`--force`。
* 同一份输入跑两次，产物 sha256 必然相同（本轮实测见 `docs/REPORT_FINAL_DELIVERY.md` §C）。

---

## 7. 常见坑 / 失败排查

| 症状 | 原因 | 处理 |
|---|---|---|
| `缺少「本地自备」输入 eng_iso` | 没放英文原盘 | 见 §1 表格 |
| `k2_dump 指纹不符` | 用了别的转储（比如 `GR_ZH113b`） | 必须用 `GR_FA2400_K2 (2026-10-17 15-08-20).dump` |
| 某阶段 `指纹不符` + 期望/实际两位不同 | 上游 assets 被改了 | 先 `git status tools/final_fix/assets`；改内容本来就该重算该阶段的期望值（§8） |
| `patch_zh143_ike.py` 报 `src sha256 != expected GR_ZH142` | 上游 `ike142` 没产出那张盘 | 说明第 14 步失败过；看第 14 步日志 |
| `verify.py` 报 `LANG 表条目 <= 2000` | 文本注入把表写坏了 | 回看 `merge_text` 阶段 |
| `verify.py` 报 `FF 闸门 FAIL` | 有人把「著」写回单字节 `0xFF` | 见 `MOD_GUIDE.md` §4 |
| 磁盘不够 | 峰值约 6.5 GB | `--outdir D:\tmp` 换盘 |
| 跑到一半 Ctrl-C | 中间盘留在 `_stages` | 直接重跑；`build.py` 会覆盖同名阶段盘 |

**不要**做的事：

* ✗ 拿 `GR_ZH145.iso` 之类的历史成品当基底（链条会断，不可复现）
* ✗ 手改 `build.py` 里的阶段顺序（流程在 `fix_spec.json`）
* ✗ 在 `tools/final_fix/` 里再放一个 `repro_*.ps1`（本轮已把这些全部合并进 `build.py`）

---

## 8. 改了内容之后怎么更新"期望指纹"

改文本/字库/任务名 ⇒ 各阶段 sha256 必然变。正确做法：

1. 先跑一次 `python tools\final_fix\build.py --force --no-verify --keep-intermediate`，
   记下**受影响阶段**的真实 sha256（日志里每阶段都打印）；
2. 只把这些阶段的 `expect_sha256` 和 `product.sha256/md5/bytes` 改成新值；
3. 再跑一次全链 + `verify.py`，确认 28 条全过；
4. 更新 `docs/STATUS.md` 的正式版身份与 `docs/REPORT_FINAL_DELIVERY.md`。

> 期望值不是"装饰"，它是**回归测试**：任何一步意外改变内容都会立刻被抓住。

---

## 9. 环境变量

| 变量 | 作用 |
|---|---|
| `GR_REPORT` | 任务名阶段（`patch_misnames40.py`）写报告用的目录 |
| `PYTHONPATH` | `build.py` 自动为子进程设置，不需要手工设 |

---

## 10. 最小验证清单（交付前逐条打勾）

- [ ] `build.py` 跑完，16 个阶段全部 `OK == fix_spec.json`
- [ ] 成品 sha256 == `98ed8579f1b536432eb3d25843c41986b8e27eaeb1fec1035f2a74c866c2ff9a`
- [ ] `verify.py` 28/28 通过，`VERIFY OK`
- [ ] `git status` 干净，`git ls-files | wc` 与 `docs/STATUS.md` 记的数字一致
- [ ] `third_party/**`、`work/**` 里没有任何文件被 `git add`
