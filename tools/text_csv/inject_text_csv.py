# -*- coding: utf-8 -*-
r"""inject_text_csv.py — 把人工编辑过的文本注入回盘 (纯字节补丁, 不重建 ISO)

配套: tools/text_csv/dump_text_csv.py ; 格式与操作说明见 tools/text_csv/FORMAT.md

★ round37: 文本表**按 kind 拆成多张** —— 注入端支持多表:
  · `--csv` 可给**多次** (`--csv a.csv --csv b.csv`), 也可给**一个目录**
    (`--csv work/builds/GR_ZH92/text`) ⇒ 自动读该目录下所有 `*_text_*.csv`;
  · 多张表**按 `id` 合并** (顺序: 先给的表在前);
  · 同一个 `id` 出现在两张表里、而 `text_edited` **不同** ⇒ **报错 (退出码 1) 且不写盘**
    —— 这正是"改了一张、另一张没改"的歧义; `text_edited` 相同则去重放行。
  · 老格式的**合并大表** (一张表装全部行) 仍然能注入 (行为完全一致), 但会明确提示
    「请改用多表」并给出重新 dump 的命令。

规则 (与 FORMAT.md 一致):
  · 只处理 text_edited 列; text_zh 只作参考
  · ★ round34 只读参考列 text_en (英文原文): **完全忽略** —— 读 CSV 后第一件事就是把它从
    每一行里删掉 (见 main 里的 `IGNORED_COLS` 处理), 所以这一列里写什么垃圾都不影响产物。
    已实测: 把 text_en 改成乱码/中文/空/私有区字符/写错的 {{BTN:ZZZZ}} ⇒ 产物 sha256 不变。
    ★ round36 同样把只读列 `wrap_hint` / `wrap_preview` (引擎自动折行提示) 整列丢掉。
  · ★ round36 换行/断点口径 (与 dump 严格互逆, 见 FORMAT.md §3):
        1 个换行 → {br};  空行 (连续 ≥2 个换行) → {p};
        `{WRAP}` / `{Warp}` (大小写不限) = **人工断点** → **一个真换行** ⇒ 盘上 {br}
        (round35 及更早是"整段丢弃、不写盘", 用户报障「断点不生效」就是这里)。
      位置校验: 断点标记**不能**出现在文本最开头/最末尾, 也不能紧邻另一个标记或换行
        (那些位置会写出连续标记 {br}{br}, CSV 无法无损表示) ⇒ 报错拦截 (退出码 1)。
  · 与源盘当前字节**逐字节相同**的行自动跳过
    ⇒ 「dump 后不改动」注入 = 产物与基底 sha256 完全相同
  · 空单元格 / 未填 = 不改动这一条; 要清空一条请填哨兵 [[empty]]
  · 变长时按容器**原有子流划分**重压 (只重压内容变了的子流), 用容器尾部陈旧区吸收增量,
    保持解压总长与压缩帧都不超过原槽位 ⇒ IMG 条目表 off/stored/real 一律不动
  · 语言表两份拷贝 (MENU.IMG#25 / GR.IMG#902) 同步写, 并断言两份内容一致
  · ★ 写盘前先做**字库覆盖预检**: 每一条要写入的文本逐字符检查
      ① 字符集里能编码 (单字节码 / lead 合法的对偶码);
      ② 盘上真有字形 (FT 记录表 + COMMON.PAK 字库图集, 不是只看 JSON);
      ③ 编码器不产生 lead≥0xAE 的死 pair。
    有任何缺字 ⇒ **默认拒绝写盘** (退出码 3), 并列出缺字清单与处理建议;
    确要强行写入用 `--force` (会显著告警)。只想预检不写盘用 `--check-only`。
  · ★ round33 手柄按键图标标记 `{{BTN:XXXX}}`:
      - 解析: 还原成原来的控制字节 (**与 dump 前逐字节一致**);
      - 向后兼容: CSV 里若仍是**原始私有区字符** U+E0xx (round32 及更早的 dump), 照旧注入;
      - 写错的标记 (`{{BTN:ZZZZ}}` / 缺右边 `}}` / 未知码位 …) ⇒ **在任何写盘动作之前
        全 CSV 前瞻拦下**, 逐条报「哪一条、哪个标记、怎么写才对」, 退出码 1,
        **--force 也不能绕过** (写错的标记没有任何字节能表示它);
      - 字库预检**整体跳过**这些标记 (引擎直接画图标, 不吃字库) ⇒ 不会误报缺字。
  · ★ round36 断点标记 `{WRAP}` / `{Warp}`: 同样**写错就拦、位置非法就拦** (退出码 1,
    --force 也不能绕过)。另外: 若是 round35 及更早的**旧格式 CSV** (`text-csv/1` `text-csv/2`),
    长段里的 `{WRAP}` 是当年 dump **自动生成**的「引擎会在这折行」提示 (现役盘 1548 个),
    与人工断点无法区分 ⇒ 编辑过的长段**拒绝注入**, 要求重新 dump (见 FORMAT.md §3.6)。

★ round63: **属性级写入通道** —— 「特别收录」的**条目标题** (XML 属性 `name=`) 现在可注入
  ────────────────────────────────────────────────────────────────────────────────
  背景: 标题**不在** `<text>` 元素里, 而在 `<item|group|studio name="…">` 的**属性**里
  ⇒ 从来没进过任何可注入表 (round62 的 `docs/REPORT_sf_titles_dump.md` 有完整根因)。
  round63 补上两件东西: 表由 `tools/text_csv/dump_sf_titles_csv.py` 产出
  (`<版本>_text_sf_titles.csv`, 命名落在 `*_text_*.csv` 里 ⇒ `--csv <目录>` 会自动读入),
  本注入器负责**按属性回写**。

  · **只认 `id = SFXML:A####`** 的行 (A = attribute; 与正文行的 `SFXML:T####` 永不撞 id);
    这类行的 `kind` 恒为 `sf_titles`, 并且必须带 `tag` / `entry_index` / `offset` /
    `len_bytes` 四列。**只写注入目标那一份** = `tcslib.RES['SFXML']['copies'][0]`
    (现役盘 = `MENU.IMG#283`); 另外 9 份副本 (DE/ES/FR/IT 西文原码 + `GR.IMG#4058`
    英文原样) **一个字节都不动** (本工具根本不写它们的槽位)。
  · 定位口径 (为什么不能只看 offset): 标题**改了字数**就会让后面所有属性的偏移漂移 ⇒
    唯一权威定位是 **`entry_index` (第 N 个 name 属性, blob 顺序)**; `tag` 列用来复核
    ("这个序号上确实是 item/group/studio"); `offset`/`len_bytes` 是**与源盘对表**的校验:
      - 盘上现值 == `text_edited`  ⇒ **已经写过了** ⇒ 跳过 (幂等: 同一份表再跑 = 0 改动);
      - 盘上现值 == `text_zh`      ⇒ 位置可信 ⇒ 写入 (偏移漂移只**告警**并列出);
      - 两者都不是                 ⇒ **拒绝** (表与源盘不同步, 硬写会盖掉别人/别轮的改动);
      - `text_zh` 为空 (font_compact 的"强制重编码副本"会清空它) ⇒ 按新字符集重编写入。
  · **支持改字数**: 标题变长时, 增长吃 `</SpecialFeatures>` 之后的**陈旧尾巴**
    (现役盘 38238 B); 变短则尾部补零。**总长超出可用空间 / 重压后帧超出槽位 ⇒ 中止**
    (退出码 1, **不截断、不静默丢字**)。解压 blob 的**总长严格不变** ⇒ IMG 条目表的
    `off/stored/real` 一个字节都不动。
  · 硬门禁 (任一不过就**不写盘**):
      ① **反向重建**: 把新 blob 里被编辑的区间换回**盘上原字节**, 必须逐字节等于原 blob
         ⇒ 数学上保证"除被编辑的区间外一个字节都没变" (改长/改短同样成立);
      ② 字符集 + 字形预检 (与正文同一条通道; 缺字 ⇒ 退出码 3, 指名道姓说缺哪个字);
      ③ 槽位装不下 ⇒ 退出码 1 (报告需要多少 B / 只有多少 B);
      ④ 写盘后**重新 load 回读**: 每个被编辑的属性解出来 == `text_edited`, 其余属性与
         69 个 `<text>` **逐字节不变**, SFXML 结构计数不变;
      ⑤ 幂等: 同一份表对同一张盘再跑一次 ⇒ 0 改动、产物 sha256 不变。
  · 标题专属的额外拦截 (**--force 也不能绕过**; 写错的标题没有任何字节序列能表示它):
      - 换行 / `{br}` / `{p}` / `{WRAP}` ⇒ 拒绝 (标题是**单行** XML 属性值);
      - `"` `<` `&` ⇒ 拒绝 (会破坏 XML 属性语法: 引擎解析会崩或把标题截断);
      - `[[empty]]` (清空) ⇒ 拒绝 (会把条目名整条删掉);
      - 纯 ASCII 的 studio 名 (`Music` / `Awards` …) 是**五份语言的共同结构名**,
        不是给人看的文案 ⇒ 工具不拦, 但**强烈建议不要汉化** (证据见 round63 报告);
      - 标题栏宽度固定 ⇒ 超过 14 个字的标题只**告警** (版式必须实机验)。

用法:
  python tools/text_csv/inject_text_csv.py --csv work/builds/GR_ZH92/text \
         --src work/builds/GR_ZH92/GR_ZH92.iso --dst work/builds/GR_ZH93/GR_ZH93.iso
  python tools/text_csv/inject_text_csv.py --csv a_long.csv --csv a_short.csv ...
  python tools/text_csv/inject_text_csv.py --csv <老的大表>.csv ...      # 仍能用, 会提示改用多表
  python tools/text_csv/inject_text_csv.py ... --only SFXML:T0010 --dry-run
  python tools/text_csv/inject_text_csv.py ... --check-only      # 只预检, 不写盘
  # ★ round63 标题 (属性) 通道:
  python tools/text_csv/inject_text_csv.py --csv <版本>_text_sf_titles.csv ^
         --src <盘> --check-only                 # 缺字/写法错都会在这里被拦下
  python tools/text_csv/inject_text_csv.py --csv work/builds/GR_ZH110/text ^
         --src work/builds/GR_ZH110/GR_ZH110.iso --dst <新盘>
  python tools/text_csv/inject_text_csv.py --csv <表> --src <盘> --dst <新盘> --only SFXML:A0116

退出码:
  0  成功 (预检通过; --check-only 时表示「可以注入」)
  1  结构性错误 (CSV 与源盘不符 / 超槽 / 回读不符 / 标记写法或位置错误 / 旧格式 CSV /
     多张表里同一个 id 的 text_edited 不一致 / 属性行 (SFXML:A####) 定位或写法非法)
  2  参数或环境错误 (文件打不开 / --csv 路径不存在等)
  3  字库覆盖预检不通过 (有缺字, 未写盘) —— 加 --force 可强行继续
"""
import argparse
import datetime
import json
import os
import re
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
try:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:                                                   # noqa: BLE001
    pass
import tcslib as T                                                # noqa: E402


def die(msg, code=1):
    """人话报错并退出 (code 见 EXIT_* 约定)。"""
    sys.stderr.write(msg.rstrip() + '\n')
    sys.stderr.flush()
    sys.exit(code)


def _excepthook(etype, value, tb):
    """★ 中文 SystemExit 的消息必须自己打 —— Python 默认走 stderr 原始编码
    (中文 Windows = GBK) 且不经过 reconfigure ⇒ 全是乱码。"""
    if etype is SystemExit:
        if isinstance(value.code, str):
            sys.stderr.write(value.code.rstrip() + '\n')
            sys.stderr.flush()
            sys.exit(EXIT_STRUCT)
        sys.exit(value.code or 0)
    sys.__excepthook__(etype, value, tb)


sys.excepthook = _excepthook

EMPTY_SENTINEL = '[[empty]]'

# 退出码 (约定见模块 docstring 与 tools/text_csv/FORMAT.md §8)
EXIT_OK, EXIT_STRUCT, EXIT_USAGE, EXIT_CHARSET = 0, 1, 2, 3

KIND_LABEL = {
    'not_in_charset': '字符集里没有',
    'dead_pair': '只有不可用双字节码',
    'no_glyph': '盘上字库没有字形',
    'ascii_no_glyph': 'ASCII 在 default face 里没找到字形 (仅告警)',
}
KIND_ADVICE = {
    'not_in_charset': '该字不在本盘字符集里。要么改写文案换成常用字, 要么先扩字符集+字库再注入。',
    'dead_pair': '该字在字符表里只有 lead≥0xAE 的双字节码, 引擎读不了 (会显示成乱码)。'
                 '请改用别的字, 或把该字加进单字节码/合法 lead 段。',
    'no_glyph': '字符集里有这个字, 但盘上字库 (FT 记录/图集) 里没有它的字形, 写进去会显示空白。'
                 '要么改写文案, 要么先扩字库。',
    'ascii_no_glyph': 'ASCII 在 default face 的记录表里没找到字形 —— 但引擎的 ASCII 单字节路径'
                      '在其它 face 里有字形 (现役盘小写 a-z 用了 5648 处且实机可读), '
                      '所以只告警、不阻断。',
}
# 只告警、不阻断的 kind (ASCII 字形检查覆盖不全, 见 tcslib.check_text 注释)
WARN_KINDS = ('ascii_no_glyph',)


def _disp(ch):
    """人话显示一个字符: 可打印的直接给, 控制/不可见给码点。"""
    o = ord(ch)
    if o < 0x20 or o == 0x7F:
        return 'U+%04X' % o
    return ch


# ───────────────────────────── CSV 读取 ─────────────────────────────
#   ★ round37: 表的读取/合并都在 tcslib 里 (dump / inject / make_build / diff 共用同一口径):
#       T.expand_csv_inputs  参数 (文件 / 目录 / 多次) → 有序去重的表路径
#       T.read_table_rows    读一张表 (UTF-8 BOM, 容忍 CR, 忽略空行)
#       T.merge_table_rows   多张表按 id 合并 + 歧义检测 (text_edited 不同 ⇒ conflicts)
NEED_COLS = ('id', 'resource', 'entry_index', 'offset', 'len_bytes', 'text_edited')


def load_table_inputs(specs):
    """把 ``--csv`` 的若干参数 (可多次 / 可给目录) 读成**一份合并行表**。

    返回 ``(rows, report, cols)``。report 里有每张表的路径/kind/行数、合并统计、
    只读列丢弃计数、``conflicts`` (同一个 id 的 text_edited 不一致 ⇒ 调用方必须报错退出)。

    ★ round39: **view-only 表一律拒绝** (退出码 1, 不写盘) —— 两道防线:
        ① 文件名里有 ``_view_`` (dump_containers.py 的命名空间, 与 ``*_text_*.csv`` 互斥);
        ② 表里有 ``injectable`` 列且值 = ``no`` (防"改名后蒙混过关")。
    """
    paths, notes = T.expand_csv_inputs(specs)
    errs = [n for n in notes if n['level'] == 'error']
    if errs:
        view = [n for n in errs if n['code'] == 'view-only-table']
        if view:
            print('\n[!!] 拒绝注入: 给进来的是 **view-only 表** (只能看/校对, 不能注入):')
            for n in view:
                print('   %s' % (os.path.relpath(n['path'], T.REPO).replace('\\', '/')
                                 if n['path'].startswith(T.REPO) else n['path']))
            print('\n  为什么拒绝: 这些表是 tools/text_csv/dump_containers.py 的「全容器文本普查」')
            print('  产物 (.ATR / .MIS / .XML / .TXT / .RES / ELF / 贴图名 / 调试串 …)。')
            print('  它们**没有** id / entry_index / offset / len_bytes 这些注入必需的定位列,')
            print('  而且那些容器的格式没被逆向、做不到逐字节往返 —— 强行写回会**毁盘**。')
            print('\n  怎么办: ① 想改游戏正文, 请改这三张表里的 text_edited 列 (它们可注入):')
            print('             <版本>_text_long.csv / _long_nowrap.csv / _short.csv')
            print('           它们和 view 表在**同一个 text/ 目录**里。')
            print('          ② 想只看/校对 view 表: 用 Excel 打开就行, 本工具不会动它。')
            print('          ③ 想注入整个目录: --csv <该目录> —— 注入器自动扫描的是 '
                  '*_text_*.csv,')
            print('           天然扫不到 _view_*.csv, 所以给目录是安全的。')
            print('  ★ 一个字都没写盘。')
            sys.exit(EXIT_STRUCT)
        print('\n[!!] --csv 解析失败:')
        for n in errs:
            print('   %s' % n['msg'])
        print('   说明: --csv 可以给**多个文件** (--csv a.csv --csv b.csv 或 --csv a.csv b.csv),')
        print('         也可以给一个**目录** ⇒ 自动读该目录下所有 *_text_*.csv (多表布局)。')
        sys.exit(EXIT_USAGE)
    if not paths:
        print('\n[!!] --csv 没有给出任何可读的表')
        sys.exit(EXIT_USAGE)

    tables, cols_ref, dropped, n_cells = [], None, [], 0
    for p in paths:
        rows, cols = T.read_table_rows(p)
        # ★ round39 防线②: 表内自述 injectable=no ⇒ view-only (改名也拦得住)
        n_view = T.view_rows(rows)
        if n_view:
            print('\n[!!] 拒绝注入: 这张表里有 %d 行自述 **injectable = no** (view-only):' % n_view)
            print('   %s' % (os.path.relpath(p, T.REPO).replace('\\', '/')
                             if p.startswith(T.REPO) else p))
            print('  这是 tools/text_csv/dump_containers.py 产出的「全容器文本普查」表 ——')
            print('  只能看/校对, **不能注入**: 那类容器的格式没被逆向, 写回去会毁盘。')
            print('  怎么办: 改游戏正文请用 <版本>_text_long.csv / _short.csv 的 text_edited 列;')
            print('         如果这张表是你手工改名来的, 请把它改回 *_view_*.csv 并另存一份。')
            print('  ★ 一个字都没写盘。')
            sys.exit(EXIT_STRUCT)
        for need in NEED_COLS:
            if need not in cols:
                print('\n[!!] %s 缺列 %r (列 = %s)' % (p, need, cols))
                print('   这张表不是 dump_text_csv.py 产出的文本表, 或文件被改坏了。')
                sys.exit(EXIT_USAGE)
        if cols_ref is None:
            cols_ref = cols
        elif cols != cols_ref:
            print('[!!] 警告: 各张表的列不一致 —— 按**列名**取值, 继续 (请人工确认)')
        d, n = drop_ignored_cols(rows, cols)
        dropped += [c for c in d if c not in dropped]
        n_cells += n
        tables.append((p, rows))

    merged, rep = T.merge_table_rows(tables)
    rep['cols'] = cols_ref
    rep['paths'] = paths
    rep['notes'] = notes
    rep['ignored_cols'] = dropped
    rep['ignored_cells'] = n_cells
    return merged, rep, cols_ref


def find_meta(paths):
    """找表集对应的 meta.json (第一份存在的) → ``(meta, path)``; 没有就 ``(None, None)``。"""
    for p in paths:
        for cand in T.table_meta_paths(p):
            if os.path.isfile(cand):
                try:
                    return json.load(open(cand, encoding='utf-8')), cand
                except Exception as e:                              # noqa: BLE001
                    print('!! meta.json 解析失败 (%s): %s' % (cand, e))
    return None, None


def rel_or_abs(p):
    """仓库内路径给人看 (相对, 正斜杠); 仓库外给绝对路径。"""
    p = os.path.abspath(p)
    r = os.path.relpath(p, T.REPO)
    return r.replace('\\', '/') if not r.startswith('..') else p.replace('\\', '/')


def csv_arg(a):
    """给"重新 dump / 重新注入"命令用的路径: 一张表就给那张表; 多张表就给**共同目录**。"""
    paths = getattr(a, '_csv_paths', None) or []
    if not paths:
        return '.'
    if len(paths) == 1:
        return paths[0]
    d = os.path.dirname(paths[0])
    return d if all(os.path.dirname(p) == d for p in paths) else paths[0]


def reject(a, mode, extra=None, code=None):
    """拒绝注入: 打印结论 + (可选) 写报告 + 退出 (默认退出码 1 = 结构性错误)。"""
    if a.report:
        out = dict(format=FMT_CURRENT + '-inject',
                   csv=[os.path.abspath(p) for p in (getattr(a, '_csv_paths', None) or [])],
                   src=os.path.abspath(a.src), src_sha256=T.sha256_file(a.src),
                   dst=None, dst_sha256=None, mode=mode, changed=0, warnings=[],
                   generated=datetime.datetime.now().isoformat(timespec='seconds'))
        if extra:
            out.update(extra)
        json.dump(out, open(a.report, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('[report] %s' % a.report)
    sys.exit(EXIT_STRUCT if code is None else code)


def print_table_inputs(rep, verbose=True):
    """打印「读了哪几张表 / 合并成多少行」一节 (人话)。"""
    print('# 输入表: %d 张 (--csv 可多次; 也可以直接给目录 ⇒ 自动读 *_text_*.csv)'
          % len(rep['files']))
    for f in rep['files']:
        kind = f['kind'] or '(合并大表)'
        print('#   %-14s %5d 行  %s' % (kind, f['rows'],
                                        os.path.relpath(f['path'], T.REPO).replace('\\', '/')
                                        if f['path'].startswith(T.REPO) else f['path']))
    print('# 合并  : %d 张表共 %d 行 → 按 id 合并后 **%d 行**%s'
          % (len(rep['files']), rep['rows_in'], rep['merged'],
             ('; 去重 %d 行 (同一个 id 在两张表里内容相同)' % len(rep['duplicates']))
             if rep['duplicates'] else ''))
    if rep.get('ignored_cols'):
        print('# 只读列: %s —— **完全忽略** (%d 个非空单元格已丢弃, 不参与注入; '
              '改了也不会进游戏) ✓' % (','.join(rep['ignored_cols']), rep['ignored_cells']))
    for n in rep.get('notes', []):
        if n['level'] == 'warn':
            print('# [提示] %s' % n['msg'])
        elif n['level'] == 'info' and n['code'] in ('dir-extra', 'duplicate'):
            print('# [提示] %s' % n['msg'])


# ★ round34: text_en = 英文原文, **只读参考列** —— 注入器一个字都不看。
# ★ round36: wrap_hint / wrap_preview = 「引擎现在会自动折在哪」的只读提示, 同样一个字都不看。
#   这里不是"忘了处理", 而是**结构性保证**: 读进来立刻整列丢掉,
#   后面所有代码 (断点扫描 / 按键标记扫描 / 字库预检 / 写入) 都不可能再看到它们。
#   ⇒ 用户把 text_en 改成乱码/中文/空/PUA/写错的 {{BTN:ZZZZ}}, 产物 sha256 都不变;
#     把 wrap_hint 改成任何东西也不会让文本变一个字。
IGNORED_COLS = ('text_en', 'wrap_hint', 'wrap_preview')


def drop_ignored_cols(rows, cols):
    """从每一行里删掉 IGNORED_COLS 列。返回 (删掉的列名, 删掉的非空单元格数)。"""
    dropped, n_cell = [], 0
    for c in IGNORED_COLS:
        if c in cols:
            dropped.append(c)
            for r in rows:
                if r.pop(c, ''):
                    n_cell += 1
    return dropped, n_cell


def id_match(rid, pats):
    if not pats:
        return True
    return any(p == rid or (p.endswith('*') and rid.startswith(p[:-1])) for p in pats)


# ═══════════ ★ round63: 属性级写入通道 (SFXML 的 name= 标题) ═══════════
#   一张表里可以**同时**有正文行 (SFXML:T####) 和属性行 (SFXML:A####) —— 两者定位口径
#   完全不同 (元素 vs 属性), 所以这里用 **id 前缀**把两类行分开走各自的通道:
#     · 正文行: 老通道, 一行代码都没动 (有 <text> 元素的偏移 + entry_index=T####);
#     · 属性行: 新通道 plan_attr_edits(), 按 entry_index=A#### (序号) 定位属性。
#   ★ 只写注入目标那一份 (copies[0], 现役盘 = MENU.IMG#283); 其余 9 份副本一个字节不动。
ATTR_KIND = 'sf_titles'
ATTR_ID_RE = re.compile(r'^SFXML:A(\d+)$')
ATTR_LOC_RE = re.compile(r'^A(\d+)$')
ATTR_MAX_WARN = 14          # 标题栏宽度提示阈值 (只告警; 版式必须实机验)
#   标签/属性扫描口径 —— 与 tools/text_csv/dump_containers.py / dump_sf_titles_csv.py
#   用的是**同一批正则**; 注入时还会用 tag 列 + text_zh 复核 (见 plan_attr_edits), 所以
#   万一将来一边改了, 另一边会**在写盘前报错**而不是悄悄写错位置。
XML_TAG_RE = re.compile(rb'<([A-Za-z_][\w:.-]*)\b([^>]*)>')
XML_ATTR_RE = re.compile(rb'([A-Za-z_][\w:.-]*)\s*=\s*"([^"]*)"')
XML_TITLE_TAGS = ('item', 'group', 'studio')
XML_TITLE_ATTR = 'name'
# 会破坏 XML 属性语法的字节 (**标题是单行属性值, 所以控制字节也不许有**)。
XML_BAD_BYTES = {
    0x22: '" —— 会把这个 name="…" 属性**提前截断**',
    0x26: '& —— XML 里是实体引用的开头 (要写 &amp;)',
    0x3C: '< —— XML 里是标签开头',
}


def is_attr_row(r):
    """这一行是不是**属性行** (SFXML 的 name= 标题)? 判据只有 id = ``SFXML:A####``。"""
    return bool(ATTR_ID_RE.match((r.get('id') or '').strip()))


def parse_xml_attrs(blob):
    """按 blob 顺序列出 ``<item|group|studio name="…">`` 的属性值。

    返回 ``[(k, tag, off, val)]``; k = 第几个 (1-based) = 表里的 ``entry_index`` (A####)。
    **必须是纯函数**: 同一个 blob 调两次结果一样 (定位/回读都靠它)。
    """
    out = []
    for m in XML_TAG_RE.finditer(blob):
        tag = m.group(1).decode('latin-1')
        if tag.lower() not in XML_TITLE_TAGS:
            continue
        for am in XML_ATTR_RE.finditer(m.group(2)):
            if am.group(1).decode('latin-1') != XML_TITLE_ATTR:
                continue
            val = am.group(2)
            out.append((len(out) + 1, tag, m.start(2) + am.start(2), val))
    return out


# ─────────────── 手柄按键标记 {{BTN:XXXX}} 预检 (round33) ───────────────
#   标记是**引擎直接拿码位去画图标**的占位符, 用户必须原样保留。
#   round33 之前 dump 写成私有区 U+E0xx ⇒ Excel 显示成方框, 用户根本看不见。
#   现在写成 ASCII 标记; 写错的标记**绝不能**被当成普通文本写进盘
#   (否则游戏里会真的显示 "{{BTN:..." 这串字符) ⇒ 这里做一次全 CSV 前瞻扫描,
#   在任何写盘动作之前就拦下, 且 **--force 也不能绕过**。

def scan_btn_marks(rows, cs, cols=('text_zh', 'text_edited')):
    """全 CSV 前瞻扫描按键标记。

    返回 (问题列表, 合法标记计数 dict)。
    问题项 = dict(id, column, entry, container, pos, frag, why, text)
    """
    probs, used = [], {}
    for r in rows:
        rid = (r.get('id') or '?').strip()
        for col in cols:
            v = r.get(col) or ''
            if '{' not in v and '}' not in v:
                continue                       # 快速路径: 完全没花括号
            for m in T.BTN_RE.finditer(v):
                code = int(m.group(1), 16)
                if cs.btn_code_ok(code) is None:     # 只统计**真正可用**的标记
                    k = T.BTN_FMT % code             # 统一大写, 免得 {{btn:e0b1}} 另算一个
                    used[k] = used.get(k, 0) + 1
            _pua, bad = cs.scan_marks(v)
            for (pos, frag, why) in bad:
                probs.append(dict(id=rid, column=col,
                                  entry=(r.get('entry_index') or '').strip(),
                                  container=(r.get('container') or '').strip(),
                                  pos=pos, frag=frag, why=why, text=v))
    return probs, used


def print_btn_marks(pre_probs, used, verbose=True):
    """打印「按键标记扫描」一节 (人话)。返回 (n_marks, n_problems)。"""
    n_marks = sum(used.values())
    if verbose:
        if n_marks:
            print('# 按键标记: 共 %d 处 / %d 个不同的标记: %s'
                  % (n_marks, len(used), ' '.join(sorted(used))))
        else:
            print('# 按键标记: CSV 里没有出现 {{BTN:XXXX}} (正常: 只有少数条目含按键图标)')
    if not pre_probs:
        return n_marks, 0
    print('\n[!!] 发现 %d 处**写错的按键标记** —— 拒绝注入 (--force 也不能绕过):'
          % len(pre_probs))
    for p in pre_probs[:12]:
        print('  ── %s  (%s 列%s)' % (p['id'], p['column'],
                                      '  @' + p['container'] if p['container'] else ''))
        print('     你写的是: %r' % p['frag'])
        print('     问题    : %s' % p['why'])
    if len(pre_probs) > 12:
        print('  …(还有 %d 处, 见 --report)' % (len(pre_probs) - 12))
    print('\n  正确写法只有一种: {{BTN:XXXX}} —— 双花括号 + BTN + 冒号 + 4 位十六进制。')
    print('  例如: {{BTN:E0B1}}')
    if used:
        print('  ★ 本 CSV 里现成的正确标记有: %s' % ' '.join(sorted(used)))
        print('    最稳的做法: 在 Excel 里**直接从 note 列复制**一个现成的标记粘贴过去。')
    else:
        print('  ★ 本 CSV 里没有现成的正确标记 —— 若这里本来不该有按键图标,')
        print('    请把整段标记**连花括号一起删干净**。')
    print('  ★ 为什么必须拦: 写错的标记**没有任何字节序列**能表示它, 只能改 CSV。')
    print('    若放行, 游戏里会原样显示出 "{{BTN:..." 这串英文字符。')
    return n_marks, len(pre_probs)


# ─────────── 人工断点标记 {WRAP} 预检 (round36 语义变更) ───────────
#   round36 起 `{WRAP}` / `{Warp}` (大小写不限) 是**人工断点**:
#     · 只有 `text_edited` 列里的标记才算断点 (text_zh 是只读参考列, 里面的标记不生效);
#     · 注入时在该位置写出**一个真换行** (盘上 {br});
#     · **写法错误** (`{WRAP` / `{WRP}` / `{WRAPP}` …) ⇒ 拒绝注入 (退出码 1);
#     · **位置非法** (行首 / 行尾 / 紧邻另一个标记或换行) ⇒ 拒绝注入 (退出码 1):
#       那些位置会写出连续标记 {br}{br}, 而 CSV 无法无损表示它。
#   ⇒ 与按键标记一样, 在**任何写盘动作之前**全 CSV 前瞻拦下, 且 `--force` 也不能绕过。

def scan_wrap_marks(rows, cols=('text_zh', 'text_edited')):
    """全 CSV 前瞻扫描人工断点标记。

    返回 ``(问题列表, 统计 dict)``。
      问题项 = dict(id, column, entry, container, pos, frag, why, text, kind)
        kind = 'syntax' (写法错) / 'placement' (位置非法)
      统计 = dict(edited=总个数, edited_rows=[(id, n)...], zh=只读列里的个数,
                  zh_rows=[(id, n)...])
    """
    probs, st = [], dict(edited=0, edited_rows=[], zh=0, zh_rows=[])
    for r in rows:
        rid = (r.get('id') or '?').strip()
        for col in cols:
            v = r.get(col) or ''
            if '{' not in v:
                continue
            n = T.count_wrap_marks(v)
            if n:
                if col == 'text_edited':
                    st['edited'] += n
                    st['edited_rows'].append((rid, n))
                else:
                    st['zh'] += n
                    st['zh_rows'].append((rid, n))
            _clean, bad = T.scan_wrap_marks(v)
            for (pos, frag, why) in bad:
                probs.append(dict(id=rid, column=col,
                                  entry=(r.get('entry_index') or '').strip(),
                                  container=(r.get('container') or '').strip(),
                                  pos=pos, frag=frag, why=why, text=v, kind='syntax'))
            if col != 'text_edited':
                continue                  # 位置规则只管"会被写进盘"的那一列
            for (pos, frag, why) in T.scan_wrap_placement(v):
                probs.append(dict(id=rid, column=col,
                                  entry=(r.get('entry_index') or '').strip(),
                                  container=(r.get('container') or '').strip(),
                                  pos=pos, frag=frag, why=why, text=v, kind='placement'))
    return probs, st


def print_wrap_marks(pre_probs, st, verbose=True):
    """打印「人工断点标记扫描」一节 (人话)。返回 (n_marks, n_problems)。"""
    n_marks = st['edited']
    if verbose and not pre_probs:
        if n_marks:
            print('# 人工断点: text_edited 里有 %d 个 %s / {Warp} 标记 (分布在 %d 行) —— '
                  '注入时**变成真换行** ({br}) ✓'
                  % (n_marks, T.WRAP_MARK, len(st['edited_rows'])))
            for (rid, n) in st['edited_rows'][:8]:
                print('#   %s ×%d' % (rid, n))
            if len(st['edited_rows']) > 8:
                print('#   …(还有 %d 行)' % (len(st['edited_rows']) - 8))
        else:
            print('# 人工断点: text_edited 里没有 %s / {Warp} 标记 (没有人工断点, 正常)'
                  % T.WRAP_MARK)
        if st['zh']:
            print('# [提示] text_zh 列里也有 %d 个同类标记 (分布在 %d 行: %s) —— '
                  '**那一列是只读参考, 标记不生效**;'
                  % (st['zh'], len(st['zh_rows']),
                     ' '.join(rid for rid, _n in st['zh_rows'][:6])))
            print('#        断点请写在 text_edited 列 (而且 text_zh 里带标记说明这可能是旧格式表, '
                  '见 FORMAT.md §3.6)')
    if not pre_probs:
        return n_marks, 0
    n_syn = sum(1 for p in pre_probs if p['kind'] == 'syntax')
    n_pos = len(pre_probs) - n_syn
    print('\n[!!] 发现 %d 处**有问题的断点标记** (%d 处写法错 + %d 处位置不对) —— '
          '拒绝注入 (--force 也不能绕过):' % (len(pre_probs), n_syn, n_pos))
    for p in pre_probs[:12]:
        print('  ── %s  (%s 列%s)' % (p['id'], p['column'],
                                      '  @' + p['container'] if p['container'] else ''))
        print('     你写的是: %r  (第 %d 个字符附近)' % (p['frag'], p['pos'] + 1))
        print('     问题    : %s' % p['why'])
    if len(pre_probs) > 12:
        print('  …(还有 %d 处, 见 --report)' % (len(pre_probs) - 12))
    print('\n  正确写法: %s 或 {Warp} —— 花括号 + 4 个字母 (大小写不限), 例如：'
          '地雷由曲面的%s方形硬质弹体' % (T.WRAP_MARK, T.WRAP_MARK))
    print('  它是什么意思: **人工断点** —— 注入时就在这里换行 (盘上写出 1 个 {br})。')
    print('  位置要求: 不能写在文本**最开头/最末尾**, 也不能紧挨着另一个标记或换行')
    print('            (那些位置会写出连续换行 {br}{br}, CSV 存不下这种状态)。')
    print('  怎么办  : ① 写法错 ⇒ 按上面的正确写法改写 (或从别的行复制现成的);')
    print('            ② 位置不对 ⇒ 把标记挪到**两个字之间**; 想空一行请在 CSV 里敲'
          '**一个空行**(连续 2 个回车)。')
    print('  ★ 为什么必须拦: 写错的标记没有任何字节序列能表示它, 放行的话游戏里会原样'
          '显示出 "{WRAP" 这串英文字符;')
    print('    位置非法的标记则会写出一份"再 dump 就报错"的盘 (往返自检过不了)。')
    if n_marks or st['zh']:
        print('  (本表里另有 %d 个**写得正确**的断点标记 —— 它们不受影响, 改好上面几处即可)'
              % n_marks)
    return n_marks, len(pre_probs)


# ─────────── 旧格式 CSV (text-csv/1, text-csv/2) 的长段保护 (round35/36) ───────────
#   round35 及更早的 dump 会把「引擎自动折行点」写成 `{WRAP}` 塞进 text_zh/text_edited
#   (现役盘 1548 个)。round36 起 `{WRAP}` 是**人工断点** ⇒ 拿那种旧表注入, 那些自动提示
#   会被**一次性固化成硬换行** (盘上结构被改掉)。
#   工具链无法替人分辨"这 1548 个标记里哪几个是人写的" ⇒ 对**被编辑过的长段**直接拒绝,
#   让用户重新 dump 一份新格式 CSV (新格式里正文列一个标记都没有, 断点只可能是人写的)。
#   ★ round37: `text-csv/4` = 按 kind 拆的多张表; `text-csv/3` = round36 的**合并大表**
#     (还能注入, 结果与多表等价, 但会明确提示「请改用多表」—— 见 merged_table_notice)。
FMT_CURRENT = T.FMT_TABLES                # text-csv/4 (多表)
FMT_LEGACY_MERGED = 'text-csv/3'          # 合并大表: 能用, 但提示改用多表
FMT_LEGACY = ('text-csv/1', 'text-csv/2')


def merged_table_notice(rep, meta_format, meta_path, src, merge_note=''):
    """给的是**老格式的合并大表**时的提示 (仍照旧注入, 但明确劝改用多表)。"""
    big = [f for f in rep['files'] if not f['kind']]
    if not big:
        return False
    print('\n' + '=' * 78)
    print('[!! 提示] 你给的是一张**合并的大表** (一张表装全部 %d 行):' % rep['merged'])
    for f in big:
        print('     %s' % (os.path.relpath(f['path'], T.REPO).replace('\\', '/')
                           if f['path'].startswith(T.REPO) else f['path']))
    print('   ★ 新版布局是**按 kind 拆开的多张表** (命名 <版本>_text_<kind>.csv):')
    print('       _long.csv        可写 %s 控制断点的长段' % T.WRAP_MARK)
    print('       _long_nowrap.csv 语言表长段 (简报等)')
    print('       _short.csv       按钮 / 条目名 / 短提示')
    print('   本次**照旧按老口径注入** (结果与多表逐字节等价), 但**建议改用多表**:')
    print('     · 一张表只装一类文本 ⇒ 不会出现"改了一张、另一张忘了改";')
    print('     · 文件名就写着 kind ⇒ 一眼看出哪张是干什么的;')
    print('     · 注入时把 text/ **目录**给 --csv, 多张表会被全部读入 (漏不了)。')
    print('   重新 dump 成多表 (你改过的 text_edited 会被 --carry-edited 原样搬过去):')
    print('     python tools/text_csv/dump_text_csv.py --iso %s \\'
          % (os.path.relpath(src, T.REPO).replace('\\', '/') if src.startswith(T.REPO) else src))
    print('        --out <同目录>/<版本>_text.csv --carry-edited %s'
          % (os.path.relpath(big[0]['path'], T.REPO).replace('\\', '/')
             if big[0]['path'].startswith(T.REPO) else big[0]['path']))
    print('   (旧格式 = %s; 若它是 round35 及更早的 text-csv/1 或 /2, 长段里的 %s 是'
          % (meta_format or '未知/无 meta', T.WRAP_MARK))
    print('    引擎自动折行的旧提示, 那种表**会被拒绝**, 见 FORMAT.md §3.6)')
    if merge_note:
        print('   %s' % merge_note)
    print('=' * 78)
    return True


def legacy_risky_rows(rows, only, meta_format):
    """旧格式 CSV 里「被编辑过的 wrap_w>0 长段」—— 这些行不能安全注入。"""
    if meta_format not in FMT_LEGACY:
        return []
    bad = []
    for r in rows:
        rid = (r.get('id') or '').strip()
        if not id_match(rid, only):
            continue
        if (r.get('kind') or '').strip() != 'long':
            continue
        try:
            w = int((r.get('wrap_w') or '0').strip() or 0)
        except ValueError:
            w = 0
        if w <= 0:
            continue
        cell = r.get('text_edited') or ''
        if cell == '' or cell == (r.get('text_zh') or ''):
            continue                        # 没改过 ⇒ 本来就不会写
        bad.append(rid)
    return bad


def legacy_wrap_in_zh(rows, only):
    """**不看 meta** 的内容判据: 哪些行的 ``text_zh`` 里带着合法断点标记。

    round36 的 dump **绝不会**往 text_zh 里写标记 ⇒ 一出现就说明这是 round35 及更早的旧表
    (或有人把标记贴到了只读列)。返回 ``[(id, 标记数, 该行是否会被写入)]``。
    """
    out = []
    for r in rows:
        rid = (r.get('id') or '').strip()
        if not id_match(rid, only):
            continue
        n = T.count_wrap_marks(r.get('text_zh') or '')
        if not n:
            continue
        cell = r.get('text_edited') or ''
        try:
            w = int((r.get('wrap_w') or '0').strip() or 0)
        except ValueError:
            w = 0
        risky = (w > 0 and cell != '' and cell != (r.get('text_zh') or '')
                 and T.count_wrap_marks(cell) > 0)
        out.append((rid, n, risky))
    return out


# ───────────────────────── 容器 ─────────────────────────

class Container:
    """一个资源在一份 IMG 拷贝里的实例 (只读装载 + 编辑列表)"""

    def __init__(self, iso, name, copy_spec, cs):
        self.name, self.cs = name, cs
        self.img, self.lba, self.idx, self.tag = copy_spec[:4]
        self.entry = iso.img_entry(self.lba, self.idx)
        raw = iso.read(self.entry['iso_off'], self.entry['stored'])
        self.subs = T.lzo_subs(raw)
        self.raws = [raw[s[3]:s[3] + 8 + s[1]] for s in self.subs]   # 原压缩帧 (含头)
        self.blob = b''.join(s[0] for s in self.subs)
        self.sizes = [s[2] for s in self.subs]
        self.frame_len = sum(s[1] + 8 for s in self.subs)
        self.slot = self.entry['stored']
        self.edits = []                     # [(start, end, newbytes, row)]
        if name == 'LANG':
            self.ents, self.used_end = T.parse_lang(self.blob)
        else:
            self.used_end = T.xml_tail_start(self.blob)
            self.ents = [dict(k=k, off=o, ln=ln, data=b)
                         for (k, o, ln, b) in T.parse_sfxml(self.blob)]
            # ★ round63: 属性级通道 (SFXML 的 name= 标题) —— 定位表 (按 blob 顺序)
            self.attrs = [dict(k=k, tag=t, off=o, ln=len(v), data=v)
                          for (k, t, o, v) in parse_xml_attrs(self.blob)]

    def locate(self, locator):
        """返回 (payload_off, payload_len, payload_bytes)"""
        if self.name == 'LANG':
            m = re.fullmatch(r'G(\d+)\.I(\d+)', locator)
            if not m:
                return None
            g, i = int(m.group(1)) - 1, int(m.group(2))
            for e in self.ents:
                if e.g == g and e.i == i:
                    return e.data_off, e.length, e.data
            return None
        m = ATTR_LOC_RE.fullmatch(locator)          # ★ round63: 属性行 (A####)
        if m is not None:
            k = int(m.group(1))
            for e in self.attrs:
                if e['k'] == k:
                    return e['off'], e['ln'], e['data']
            return None
        m = re.fullmatch(r'T(\d+)', locator)
        if not m:
            return None
        k = int(m.group(1))
        for e in self.ents:
            if e['k'] == k:
                return e['off'], e['ln'], e['data']
        return None

    def attr_tag(self, locator):
        """属性行定位到的那个属性的标签名 (复核用; 找不到给 None)。"""
        m = ATTR_LOC_RE.fullmatch(str(locator or ''))
        if m is None:
            return None
        k = int(m.group(1))
        for e in self.attrs:
            if e['k'] == k:
                return e['tag']
        return None

    def span(self, off, ln):
        """该条在 blob 里**必须整体替换**的字节区间。
        LANG 条目自带 {u32 len} 前缀 ⇒ 长度字段必须一起改写, 否则结构错位。"""
        if self.name == 'LANG':
            return off - 4, off + ln
        return off, off + ln

    def marshal(self, new):
        if self.name == 'LANG':
            return struct.pack('<I', len(new)) + new
        return new

    def iter_payloads(self, blob):
        """枚举该 blob 内的 (locator, payload)"""
        if self.name == 'LANG':
            ents, _ = T.parse_lang(blob)
            return [('G%03d.I%03d' % (e.g + 1, e.i), e.data) for e in ents]
        return [('T%04d' % k, b) for (k, _o, _l, b) in T.parse_sfxml(blob)]

    def iter_attrs(self, blob):
        """★ round63: 枚举该 blob 内的属性 (locator, payload); 非 SFXML 给空表。"""
        if self.name != 'SFXML':
            return []
        return [('A%04d' % k, v) for (k, _t, _o, v) in parse_xml_attrs(blob)]

    def attr_locs(self, blob):
        """★ round63: ``{A####: (tag, off, len)}`` (新 blob 里每个属性的位置)。"""
        return dict(('A%04d' % k, (t, o, len(v)))
                    for (k, t, o, v) in parse_xml_attrs(blob))

    def build_blob(self):
        """应用编辑, 返回 (new_blob, delta)。

        ★ 硬门禁 (round63, 两类通道**都**过): **反向重建** —— 把新 blob 里被编辑的区间
          换回**盘上原字节**, 必须逐字节等于原 blob。它在数学上等价于"除被编辑的区间外
          一个字节都没变", 而且**改长/改短同样成立** (改长时后面的字节会整体平移,
          单纯逐字节 diff 是看不出来的)。
        ★ 增长吸收: 解压 blob 的**总长严格不变** (IMG 条目表的 real 字段 = 总解压长,
          不许动) ⇒ 增长吃 `</SpecialFeatures>` 之后的**陈旧尾巴**, 缩短则尾部补零;
          **需要超过陈旧尾巴就中止** (不截断、不静默丢字)。
        """
        if not self.edits:
            return self.blob, 0
        ed = sorted(self.edits, key=lambda x: x[0])
        raw = T.splice(self.blob, [(a, b, nb) for (a, b, nb, _r) in ed])
        delta = len(raw) - len(self.blob)
        # ── 硬门禁①: 反向重建 (与"除编辑区间外逐字节不变"等价) ──
        shift, undo = 0, []
        for (a, b, nb, _r) in ed:
            undo.append((a + shift, a + shift + len(nb), self.blob[a:b]))
            shift += len(nb) - (b - a)
        rebuilt = T.splice(raw, undo)
        if rebuilt != self.blob:
            k = next((i for i in range(min(len(rebuilt), len(self.blob)))
                      if rebuilt[i] != self.blob[i]), min(len(rebuilt), len(self.blob)))
            raise SystemExit(
                '!! %s 硬门禁不通过: 把新内容换回盘上原字节后与源 blob 不符 (首处 @%d) —— '
                '拒绝写盘。这是工具链缺陷, 请把本行原样报给工程侧。' % (self.tag, k))
        if delta == 0:
            outside = [i for i in range(len(raw)) if raw[i] != self.blob[i]
                       and not any(a <= i < b for (a, b, _nb, _r) in ed)]
            if outside:
                raise SystemExit('!! %s 硬门禁不通过: 有改动落在被编辑区间之外 (%s)'
                                 % (self.tag, outside[:5]))
        if delta > 0:
            tail_free = len(self.blob) - self.used_end
            if delta > tail_free:
                raise SystemExit(
                    '!! %s 装不下: 这次改动让内容**变长 %+d B**, 而 </SpecialFeatures> '
                    '之后的陈旧尾巴只有 %d B (超 %d B)。\n'
                    '   说明: 解压总长被 IMG 条目表的 real 字段钉死 (不许动条目表), '
                    '所以增长只能吃陈旧尾巴; 本工具**不会**截断、也不会静默丢字。\n'
                    '   怎么办: ① 精简这次改动的文本 (少改几个字/少改几条); '
                    '或 ② 分多次注入, 每次 --only 小批。'
                    % (self.tag, delta, tail_free, delta - tail_free))
            new = raw[:len(self.blob)]
        elif delta < 0:
            new = raw + b'\x00' * (-delta)
        else:
            new = raw
        return new, delta

    def repack(self, new_blob):
        assert len(new_blob) == len(self.blob), '解压总长必须不变'
        frame, q, n_rep = bytearray(), 0, 0
        for k, S in enumerate(self.sizes):
            c = new_blob[q:q + S]
            q += S
            if c == self.subs[k][0]:
                frame += self.raws[k]                       # 未变子流: 原压缩字节照搬
                continue
            cc = T.lzo_compress(c, level=7, use_m1=True, use_m4=True)
            back, err, _ = T.lzo1x_decompress(cc, out_size=S)
            assert err is None and back == c, '子流 %d 回环失败' % k
            frame += struct.pack('<II', len(cc), S) + cc
            n_rep += 1
        return bytes(frame), n_rep


# ───────────────────── 字库覆盖预检 (写盘前) ─────────────────────

def encode_cell_or_die(rid, cell, cs, cell_stat=None, what='文本'):
    """CSV 单元格 → 盘上字节 (与正文/属性**同一个口径**); 出错就人话报错并退出。

    ★ round63: 原先是 main() 里的一整段 try/except (只服务正文行); 属性行 (标题) 也要
      同一套人话报错, 所以原样提成一个函数 —— **报错文案一字未改**。
    """
    try:
        return T.cell_to_bytes_text(cell, cs, cell_stat if cell_stat is not None else {})
    except T.WrapPlacementError as ex:
        raise SystemExit(
            '!! %s 的人工断点标记**位置不对**, 拒绝注入 (--force 也不能绕过):\n'
            '   %s\n'
            '   说明: %s / {Warp} 是**人工断点**, 注入时会在那里写出 1 个真换行 ({br})。\n'
            '         写在文本最开头/最末尾、或紧挨着另一个标记/换行, 都会写出'
            '**连续换行** {br}{br}\n'
            '         (引擎画成空行) —— 而 CSV 只能无损表示 1 个换行, 再 dump 回来'
            '往返自检会失败。\n'
            '   怎么办: ① 把标记挪到**两个字之间**; 或 ② 想空一行 ⇒ 在那个位置敲'
            '**一个空行**(连续 2 个回车)。'
            % (rid, str(ex).replace('\n', '\n   '), T.WRAP_MARK))
    except T.WrapMarkError as ex:
        raise SystemExit(
            '!! %s 的人工断点标记写错了, 拒绝注入 (--force 也不能绕过):\n'
            '   %s\n'
            '   说明: %s / {Warp} 是**人工断点** (注入时变成真换行 {br});\n'
            '         写错的标记既不是断点、也不该变成正文 ⇒ 直接拒绝。\n'
            '   怎么办: ① 按上面的正确写法改写; 或 ② 想断行就把标记删掉、直接敲回车。'
            % (rid, str(ex).replace('\n', '\n   '), T.WRAP_MARK))
    except T.BtnMarkError as ex:
        raise SystemExit(
            '!! %s 的按键标记有问题, 拒绝注入 (--force 也不能绕过):\n'
            '   %s\n'
            '   说明: {{BTN:XXXX}} 是手柄按键图标的占位标记 —— 写错了**不会**被当成\n'
            '         普通文字写进去, 而是直接拒绝; 否则游戏里会真的显示出\n'
            '         "{{BTN:..." 这串英文字符。\n'
            '   怎么办: ① 按上面的「正确写法」改写; 或 ② 从该条的 note 列\n'
            '           复制现成的标记粘贴过来 (最稳); 或 ③ 这里本来不该有按键图标,\n'
            '           就把整段标记连花括号一起删干净。'
            % (rid, str(ex).replace('\n', '\n   ')))
    except T.CharsetError as ex:
        raise SystemExit(
            '!! %s 编码失败: %s\n'
            '   说明: 这个字在字符表里**根本没有可用的编码** —— 没有任何字节序列能表示它,\n'
            '         所以连 --force 也写不进去 (写出去只会是别处的乱码)。\n'
            '   怎么办: 请把这个字换成常用字 (上面「字库覆盖预检」一节已列出位置与建议)。'
            % (rid, ex))


def charset_precheck(rows, only, cs, iso, verbose=True):
    """★ 写盘前预检: 每一条**会被写入**的文本, 逐字符检查字库覆盖。

    范围 = 与注入器实际写入集合同口径:
      · 在 --only 选中的 id 内;
      · text_edited 非空 (或 == 哨兵 [[empty]], 此时文本为空 ⇒ 无字可查);
      · text_edited != text_zh (与现值相同 ⇒ 这一条根本不会写)。
    对每条文本逐字符查三件事:
      ① 字符集里能编码; ② 盘上真有字形 (FT 记录/图集); ③ 不是 lead≥0xAE 的死 pair。
    另做**反向检查**: 文本里出现「本盘字符集没有、但英文原盘有」的 ASCII/符号。

    返回 dict: 供打印 + 写进 --report 的「字库覆盖预检」一节。
    """
    guard = T.GlyphCache(cs, iso)
    checked = 0
    marks = {}                       # 标记 -> 出现次数 (引擎直接画图标, 不吃字库)
    n_wrap = 0                       # 人工断点 (注入时变真换行, 不查字库)
    per_char = {}                    # (kind, char) -> dict(char, cp, kind, reason, locator, hits[])
    en_only = {}
    for r in rows:
        rid = r['id'].strip()
        if r['resource'].strip().upper() not in T.RES:
            continue                                     # 未知 resource 的行本来就不写
        if not id_match(rid, only):
            continue
        cell = r['text_edited']
        if cell.strip() == EMPTY_SENTINEL:
            continue                                     # 清空一条 ⇒ 没有新文本
        if cell == '' or cell == r['text_zh']:
            continue                                     # 空 / 未改动 ⇒ 不会写
        checked += 1
        n_wrap += T.count_wrap_marks(cell)               # 人工断点: 变成 {br}, 不进字形检查
        for m in T.BTN_RE.finditer(cell):                # 按键标记: 只计数, 不进字形检查
            code = int(m.group(1), 16)
            if cs.btn_code_ok(code) is None:
                k = T.BTN_FMT % code
                marks[k] = marks.get(k, 0) + 1
        for it in guard.check_text(cell):
            key = (it['kind'], it['char'])
            e = per_char.get(key)
            if e is None:
                e = dict(it)
                e['hits'] = []
                per_char[key] = e
            if len(e['hits']) < 5:
                e['hits'].append(dict(id=rid, entry=r['entry_index'].strip(),
                                      container=r['container'].strip(),
                                      pos=cell.find(it['char'])))
        for (ch, cp, in_atlas) in guard.en_only_ascii(cell):
            e = en_only.get(ch)
            if e is None:
                e = dict(char=ch, cp=cp, in_atlas=in_atlas, ids=[])
                en_only[ch] = e
            if len(e['ids']) < 5:
                e['ids'].append(rid)
    return dict(guard=guard, checked=checked, marks=marks, wrap_marks=n_wrap,
                chars=sorted(per_char.values(),
                             key=lambda x: (x['kind'], -len(x['hits']), x['cp'])),
                en_only=sorted(en_only.values(), key=lambda x: x['cp']))


def print_precheck(pre, force=False, check_only=False):
    """打印「字库覆盖预检」一节 (人话)。返回 (n_issue_chars, n_dead, n_en_only)。"""
    g = pre['guard']
    print('\n===== 字库覆盖预检 (写盘前) =====')
    print('# 字库: %s' % g.atlas_note())
    for n in g.notes():
        print('!! %s' % n)
    print('# 待检查(会被写入) %d 条; 逐字符检查完成' % pre['checked'])
    if pre.get('marks'):
        print('# 其中含手柄按键图标标记 %d 处: %s'
              % (sum(pre['marks'].values()), ' '.join(sorted(pre['marks']))))
        print('#   这些标记由引擎**直接画图标**, 不吃字库 ⇒ 已整体跳过字形检查, '
              '不会、也不该被报成缺字 ✓')
    if pre.get('wrap_marks'):
        print('# 其中含人工断点标记 %s/{Warp} %d 个 —— 注入时变成**真换行** {br}, '
              '标记本身不写盘, 同样不进字形检查 ✓' % (T.WRAP_MARK, pre['wrap_marks']))
    chars = [x for x in pre['chars'] if x['kind'] not in WARN_KINDS]      # 阻断项
    warns = [x for x in pre['chars'] if x['kind'] in WARN_KINDS]          # 仅告警
    if warns:
        print('[提示] %d 个 ASCII 字符在 default face 里没找到字形 —— 仅告警不阻断'
              ' (现役盘小写 a-z 用了 5648 处且实机可读, 字形在其它 face): %s'
              % (len(warns), ' '.join(_disp(x['char']) for x in warns[:16])))
    n_dead = sum(1 for x in chars if x['kind'] == 'dead_pair')
    n_miss = len(chars) - n_dead
    if not chars:
        print('[ok] 字库覆盖完全: 每条文本的每个字符都能编码, 且盘上都有字形 ✓')
    else:
        print('[!!] 发现 %d 个「有问题的字」(共影响 %d 处文本):'
              % (len(chars), sum(len(x['hits']) for x in chars)))
        for x in chars:
            ch, cp = x['char'], x['cp']
            print('  ── %s U+%04X  「%s」' % (KIND_LABEL.get(x['kind'], x['kind']),
                                              cp, _disp(ch)))
            print('     原因: %s' % x['reason'])
            if x['locator'] and x['locator'] != '无':
                print('     字形位置: %s' % x['locator'])
            for h in x['hits']:
                print('     出现在: %s (%s) 第 %d 个字符 [%s]'
                      % (h['id'], h['container'], h['pos'] + 1, h['entry']))
            if len(x['hits']) >= 5:
                print('     …(更多出现位置见 --report)')
            print('     怎么办: %s' % KIND_ADVICE.get(x['kind'], '请人工核对'))
    if pre['en_only']:
        print('\n[提示] 反向检查: 这些字符本盘字符集(JSON)里没有, 但英文原盘有 (%d 个):'
              % len(pre['en_only']))
        n_hard = 0
        for e in pre['en_only']:
            if e['in_atlas']:
                mark = '现役图集里仍有字形 ⇒ 能正常显示, 不阻断'
            else:
                mark = '（仅提示, 不阻断: ASCII 字形在其它 face 里有）'
                n_hard += 1
            print('  %s U+%04X  %s   出现在: %s'
                  % (_disp(e['char']), e['cp'], mark, ', '.join(e['ids'])))
        print('  说明: 这些字符没有写进 charset JSON (现役盘靠引擎的 ASCII 单字节路径 + 图集字形);'
              '\n        本项**只提示不阻断** —— 现役盘小写 a-z 用了 5648 处且实机可读。'
              '\n        (%d 个在现役图集里找到字形 / %d 个没找到, 但都不阻断)'
              % (len(pre['en_only']) - n_hard, n_hard))
    if chars and not force:
        print('\n[拒绝写盘] 预检不通过: %d 个字有问题 (%d 个「字符集没有 / 盘上无字形」 + '
              '%d 个「死 pair」)。' % (len(chars), n_miss, n_dead))
        print('  怎么办: ① 按上面每条的建议改写文案 (最省事); 或 ② 先扩字库; '
              '或 ③ 确要强行写入加 --force (会写出空白/乱码, 请自负)。')
    elif chars:
        print('\n[!! 警告] --force 已指定: 预检不通过 (%d 个字有问题), 仍继续注入。'
              % len(chars))
        print('  产物里这些字会显示为空白或乱码, 请务必人工核对。')
    if check_only:
        print('[check-only] 只预检, 未写盘。')
    return n_miss, n_dead, len(pre['en_only'])


# ═══════════ ★ round63: 属性级写入通道 —— 规划「特别收录」标题的改动 ═══════════
#   表: <版本>_text_sf_titles.csv (由 tools/text_csv/dump_sf_titles_csv.py 产出)
#   行: id = SFXML:A####, kind = sf_titles, 带 tag / entry_index / offset / len_bytes
#   目标: **只写** tcslib.RES['SFXML']['copies'][0] (现役盘 = MENU.IMG#283)
#   定位: 权威是 entry_index (第 N 个 name 属性) —— 改字数会让后面的 offset 漂移;
#         tag 复核 + text_zh/text_edited 比对决定"能不能写" (见 docstring 的规则表)。

def plan_attr_edits(rows, conts, cs, only, force, verbose=True):
    """规划属性行 (``SFXML:A####`` = 「特别收录」标题) 的改动。

    返回 ``(plan, st, probs)``:
      plan  = [dict(id, r, loc, off, k, tag, old, new, delta, cell, csv_stale)]
      st    = 统计 (candidates/changed/skipped_*/grow/shrink/same/warnings/stale)
      probs = 结构性问题的**人话清单** (调用方打印; 非空 ⇒ 拒绝写盘, --force 除外)
    """
    plan, probs = [], []
    st = dict(rows=0, candidates=0, changed=0, skipped_untouched=0, skipped_already=0,
              skipped_other=0, grow=0, shrink=0, same=0, delta_total=0,
              stale=[], warnings=[], long=0, csv_stale=[])
    cl = conts.get('SFXML') or []
    for r in rows:
        if not is_attr_row(r):
            continue
        rid = (r.get('id') or '').strip()
        st['rows'] += 1
        if (r.get('resource') or '').strip().upper() != 'SFXML':
            probs.append(dict(hard=True, id=rid, why=(
                '属性行的 resource 必须是 SFXML, 这里写的是 %r' % r.get('resource'))))
            continue
        if not id_match(rid, only):
            st['skipped_other'] += 1
            continue
        st['candidates'] += 1
        cell = r.get('text_edited') or ''
        if cell == '' or cell == (r.get('text_zh') or ''):
            st['skipped_untouched'] += 1
            continue
        # ── 标题专属的写法硬门槛 (写错的标题没有任何字节序列能表示它) ──
        if cell.strip() == EMPTY_SENTINEL:
            probs.append(dict(hard=True, id=rid, why=(
                '标题不能清空 ([[empty]]): name="" 会把这条「特别收录」的条目名整条删掉。'
                '要改就写新标题; 确实想清空请手工改盘 (本工具不做)。')))
            continue
        bad = None
        if '\n' in cell or '\r' in cell:
            bad = '单元格里有换行 —— 标题是**单行** XML 属性值, 不能换行'
        elif '{br}' in cell or '{p}' in cell:
            bad = '单元格里出现了引擎标记的字面量 {br}/{p} —— 标题是单行属性值, 不能换行'
        elif T.WRAP_RE.search(cell):
            bad = ('单元格里有 %s —— 那是**长段正文**的人工断点, 标题用不上 (标题不能换行)'
                   % T.WRAP_MARK)
        if bad:
            probs.append(dict(hard=True, id=rid, why=bad + '。'))
            continue
        if len(cell) > ATTR_MAX_WARN:
            st['long'] += 1
            st['warnings'].append(
                '%s: 新标题 %d 个字 (超过 %d) —— 标题栏宽度固定, 可能溢出/被截断, '
                '请在**实机**上看版式' % (rid, len(cell), ATTR_MAX_WARN))
        cell_stat = {}
        new = encode_cell_or_die(rid, cell, cs, cell_stat)      # 写法错/缺字在这里就退出
        jb = [b for b in new if b in XML_BAD_BYTES or b < 0x20 or b == 0x7F]
        if jb:
            probs.append(dict(hard=True, id=rid, why=(
                '标题里有会破坏 XML 属性语法的字符: %s (第 %d 个字节 = 0x%02X)。'
                '它会把这个 name="…" 属性截断或让引擎解析失败 ⇒ 拒绝。'
                % (XML_BAD_BYTES.get(jb[0], '控制字符 (换行/回车/制表等)'), new.index(jb[0]),
                   jb[0]))))
            continue
        # ── 定位 (权威 = entry_index = A####) ──
        if len(cl) != 1:
            probs.append(dict(hard=True, id=rid, why=(
                'tcslib.RES["SFXML"]["copies"] 不是恰好 1 份 (实际 %d 份) —— 属性通道'
                '只写注入目标那一份, 份数变了就必须先人工确认 (拒绝写盘)' % len(cl))))
            continue
        loc = (r.get('entry_index') or '').strip()
        found = cl[0].locate(loc)
        if found is None:
            probs.append(dict(hard=False, id=rid, why=(
                '源盘里找不到第 %s 个 name 属性 (容器里有 %d 个) —— 表可能来自别的盘'
                % (loc, len(cl[0].attrs)))))
            continue
        off, ln, old = found
        k = int(ATTR_LOC_RE.fullmatch(loc).group(1))
        tag_disk = cl[0].attr_tag(loc)
        tag_csv = (r.get('tag') or '').strip()
        if tag_csv and tag_csv != tag_disk:
            probs.append(dict(hard=False, id=rid, why=(
                'CSV 的 tag=%r 与源盘第 %s 个 name 属性的标签 %r 不符 —— 表与源盘不同步'
                % (tag_csv, loc, tag_disk))))
            continue
        old_text = cs.decode(old)[0]
        try:
            fresh = (cs.encode_strict(old_text) == old)
        except T.CharsetError:
            fresh = False
        if not fresh:
            st['stale'].append(rid)
        zh = r.get('text_zh') or ''
        force_reencode = (zh == '')                 # font_compact 的重编码副本会清空 text_zh
        if new == old:
            st['skipped_already'] += 1              # ★ 幂等: 盘上已经是目标文本
            continue
        csv_off, csv_len = int(r.get('offset') or 0), int(r.get('len_bytes') or 0)
        off_stale = (csv_off, csv_len) != (off, ln)
        # ★ 「这份表是不是还在说这条属性」的硬判据 (与 offset 是否漂移**无关**):
        #   盘上现值必须 == text_zh (= dump 时看到的旧文), 否则说明这条已经被别人改过
        #   (别轮注入 / 字库重排), 硬写会盖掉那个改动 ⇒ 拒绝 (--force 可越过)。
        #   唯一例外: text_zh 被清空 (font_compact 的"强制重编码副本"就是这么干的,
        #   那时**要求**按当前字符集重写), 位置仍由 entry_index + tag 复核。
        if not force_reencode and old_text != zh:
            probs.append(dict(hard=False, id=rid, why=(
                '表与源盘不同步: 盘上第 %s 个属性 (%s) 现在是 %r, 而表里 text_zh 写的是 %r '
                '(text_edited 又是第三个值 %r) —— 硬写会盖掉别处的改动'
                % (loc, tag_disk, old_text[:24], zh[:24], cell[:24]))))
            continue
        if off_stale:
            st['csv_stale'].append(rid)
        delta = len(new) - len(old)
        st['changed'] += 1
        st['delta_total'] += delta
        st['grow' if delta > 0 else ('shrink' if delta < 0 else 'same')] += 1
        plan.append(dict(id=rid, r=r, loc=loc, off=off, k=k, tag=tag_disk,
                         old=old, new=new, delta=delta, cell=cell,
                         cell_stat=cell_stat, off_stale=off_stale,
                         force_reencode=force_reencode,
                         old_text=T.pua_to_marks(old_text),
                         new_text=T.pua_to_marks(cs.decode(new)[0])))
    if probs and force:
        hard = [p for p in probs if p['hard']]
        if hard:
            print('\n[!!] --force 也不能绕过这 %d 处**写法错误** (属性行):' % len(hard))
            for p in hard[:10]:
                print('  ── %s\n     %s' % (p['id'], p['why']))
    return plan, st, probs


def print_attr_plan(plan, st, conts, verbose=True):
    """打印「属性级通道 (特别收录标题)」一节 (人话)。"""
    c = (conts.get('SFXML') or [None])[0]
    print('\n===== 属性级通道: 「特别收录」标题 (SFXML 的 name= 属性) =====')
    if not st['rows'] and not verbose:
        return
    if c is not None:
        print('# 目标容器: %s  槽 %d B / 解压 %d B / </SpecialFeatures> @%d '
              '(陈旧尾巴 %d B 可吸收"改长")'
              % (c.tag, c.slot, len(c.blob), c.used_end, len(c.blob) - c.used_end))
        print('# 只写这一份 (copies[0]); 另外 9 份副本 (DE/ES/FR/IT 西文原码 + GR.IMG#4058 '
              '英文原样) **一个字节都不动** ✓')
    print('# 表里属性行 %d 行; 候选 %d; 要写 %d (改长 %d / 改短 %d / 等长 %d, 净 %+d B); '
          '未改跳过 %d; 已写过(幂等)跳过 %d; 不在 --only 内 %d'
          % (st['rows'], st['candidates'], st['changed'], st['grow'], st['shrink'],
             st['same'], st['delta_total'], st['skipped_untouched'],
             st['skipped_already'], st['skipped_other']))
    if st['csv_stale']:
        print('# [提示] %d 行的 offset/len 与源盘不符 (前面的改动让偏移漂移了) —— '
              '按 entry_index 定位继续: %s%s'
              % (len(st['csv_stale']), ' '.join(st['csv_stale'][:8]),
                 ' …' if len(st['csv_stale']) > 8 else ''))
    if st['long']:
        print('# [提示] %d 条新标题超过 %d 个字 —— 标题栏宽度固定, '
              '**必须实机看版式** (见 docs/REPORT_sf_titles_inject.md 已知限制)'
              % (st['long'], ATTR_MAX_WARN))
    for w in st['warnings'][:8]:
        print('!! %s' % w)
    if not plan:
        return
    print('\n%-14s %-6s %-9s %4s %4s %6s  %s' %
          ('id', 'tag', '定位', '旧B', '新B', 'Δ', '原文 → 新文'))
    for d in plan:
        print('%-14s %-6s %-9s %4d %4d %+6d  %s → %s'
              % (d['id'], d['tag'], d['loc'], len(d['old']), len(d['new']), d['delta'],
                 d['old_text'][:22], d['new_text'][:22]))


# ───────────────────────────── main ─────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description='把编辑过的文本表注入回盘 (支持**按 kind 分类的多张表**; 写盘前做字库覆盖预检). '
                    '★ round63 起也支持**属性级写入**: 「特别收录」的条目标题 '
                    '(SFXML 的 <item|group|studio name="…">) —— 表 = '
                    '<版本>_text_sf_titles.csv (id = SFXML:A####), 支持改字数。',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='属性 (标题) 通道要点:\n'
               '  · 只认 id = SFXML:A#### 的行 (kind=sf_titles); 只写 '
               'copies[0] = 现役盘 MENU.IMG#283, 另外 9 份副本一个字节都不动;\n'
               '  · 定位按 entry_index (A####, 第 N 个 name 属性) —— 改字数会让后面的\n'
               '    offset 漂移, 所以 offset/len_bytes 只用来与源盘对表 (对不上会告警/拒绝);\n'
               '  · 改字数: 增长吃 </SpecialFeatures> 之后的陈旧尾巴 (现役盘 38238 B),\n'
               '    超出可用空间 / 装不下槽位 ⇒ 中止 (不截断、不静默丢字);\n'
               '  · 标题必须**单行**, 不能含 " < & , 不能用 [[empty]] 清空 (都会破坏 XML);\n'
               '  · 同一份表对同一张盘再跑一次 = 0 改动 (幂等)。\n'
               '示例:\n'
               '  python tools/text_csv/inject_text_csv.py --csv <版本>/text '
               '--src <盘> --check-only\n'
               '  python tools/text_csv/inject_text_csv.py --csv <表>.csv '
               '--src <盘> --dst <新盘> --only SFXML:A0116\n')
    ap.add_argument('--csv', required=True, action='append', nargs='+', metavar='表/目录',
                    help='文本表: 可给**目录** (自动读该目录下所有 *_text_*.csv), '
                         '也可给一个或多个文件 (--csv a.csv --csv b.csv, 或 --csv a.csv b.csv); '
                         '多张表按 id 合并')
    ap.add_argument('--src', required=True, help='基底 ISO (只读, 不修改)')
    ap.add_argument('--dst', default=None, help='输出 ISO (--check-only 时可省略)')
    ap.add_argument('--only', default='', help='只注入指定 id (支持前缀 *), 逗号分隔')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--check-only', action='store_true',
                    help='只做字库覆盖预检, 不写盘 (退出码反映结果)')
    ap.add_argument('--report', default=None)
    ap.add_argument('--force', action='store_true',
                    help='字库覆盖预检不通过 / CSV 与源盘结构不符时也继续 (会显著告警)')
    ap.add_argument('--selfcheck', action='store_true',
                    help='★ 只做**解码闸门自检** (旧单字节码 0xB1..gate-1 残留) 然后退出, '
                         '不读表、不写盘。闸门从 --src 的 ELF 实测读出: gate=0xB1 的老盘窗口为空 '
                         '(零行为变化); 抬过闸门的盘上若有未迁移的裸字节 ⇒ 退出码 2 + 逐码清单')
    a = ap.parse_args()

    # ═══ ★ 闸门自检模式 (--selfcheck): 不读表、不写盘, 只回答"这张盘能不能安全注入" ═══
    if a.selfcheck:
        cs0 = T.Charset()
        iso0 = T.Iso(a.src)
        gate0 = T.read_decode_gate(iso0)
        extra0 = T.load_gate_pairs()
        win = list(T.legacy_window(gate0))
        print('# inject_text_csv.py --selfcheck — 解码闸门自检 (只读)')
        print('#   src        = %s' % a.src)
        print('#   实测闸门   = 0x%02X  (ELF 4 站点 %s)'
              % (gate0, [hex(v) for v in (T.ELF_GATE_SITES)]))
        print('#   检查窗口   = %s'
              % ('(空 — 闸门 ≤ 0xB1, 本盘没有"旧单字节码"概念)' if not win
                 else '0xB1..0x%02X' % (gate0 - 1)))
        print('#   gate_pairs = %d 条 (%s)' % (len(extra0), T.GATE_PAIRS_FILE))
        warn = T.charset_gate_warnings(cs0, gate0, {_ch: tuple(_p) for _p, _ch in extra0.items()})
        if warn:
            print('#   [表级预警] charset codes 里还有 %d 个字落在 [0xA1,0x%02X) '
                  '(它们不能按单字节码写出):' % (len(warn), gate0))
            for (_c, b, pr, src) in warn:
                print('#       %r = 0x%02X  (对偶码 %s, 来自 %s)'
                      % (_c, b, ('0x%02X%02X' % pr) if pr else '**没有**', src or '—'))
        conts0 = {}
        for name, spec in T.RES.items():
            conts0[name] = [Container(iso0, name, cp, cs0) for cp in spec['copies']]
        tot, bad = 0, []
        for name, cl in conts0.items():
            for c in cl:
                try:
                    r = T.legacy_selfcheck_container(c, c.blob, gate0, extra0)
                    tot += r['n']
                    print('#   %-24s 解压 %7d B · 残留 0 处 ✓' % (c.tag, len(c.blob)))
                except T.LegacyCodeError as ex:
                    bad.append(c.tag)
                    print('%s' % ex)
        iso0.close()
        if bad:
            print('\n# 结论: **不可安全注入** —— %s 有未迁移的旧单字节码。' % ', '.join(bad))
            return 2
        print('\n# 结论: ✓ 本盘所有文本容器在闸门 0x%02X 下都没有"旧单字节码"残留%s'
              % (gate0, ' (窗口为空)' if not win else ''))
        return 0

    specs = [x for grp in a.csv for x in (grp if isinstance(grp, list) else [grp])]
    only = [x.strip() for x in a.only.split(',') if x.strip()]
    print('# inject_text_csv.py — %s 注入器 (多表布局)' % FMT_CURRENT)
    rows, rep, cols = load_table_inputs(specs)
    a._csv_paths = rep['paths']
    # ★ round34/36: text_en / wrap_hint / wrap_preview 是**只读参考列** —— 结构性丢弃,
    #   绝不参与注入 (读进来立刻整列删掉, 后面所有代码都看不到它们)。
    print_table_inputs(rep)
    print('# 列  : %s' % ','.join(cols))
    print('# only: %s%s%s' % (only or '(全部)',
                              '   DRY-RUN' if a.dry_run else '',
                              '   CHECK-ONLY' if a.check_only else ''))

    # ★★ round37: 多表歧义 —— 同一个 id 在两张表里 text_edited 不同 ⇒ 拒绝, 不写任何盘 ★★
    if rep['conflicts']:
        print('\n[!!] 发现 %d 处**多表歧义**: 同一个 id 出现在两张表里, 而 text_edited **不一致** ——'
              % len(rep['conflicts']))
        for c in rep['conflicts'][:10]:
            print('  ── %s' % c['id'])
            print('     A: %s' % (os.path.relpath(c['path_a'], T.REPO).replace('\\', '/')
                                  if c['path_a'].startswith(T.REPO) else c['path_a']))
            print('        你写的: %r' % (c['edited_a'] or '')[0:80])
            print('     B: %s' % (os.path.relpath(c['path_b'], T.REPO).replace('\\', '/')
                                  if c['path_b'].startswith(T.REPO) else c['path_b']))
            print('        你写的: %r' % (c['edited_b'] or '')[0:80])
        if len(rep['conflicts']) > 10:
            print('  …(还有 %d 处)' % (len(rep['conflicts']) - 10))
        print('\n  为什么必须拦: 工具不知道该听哪一张 ⇒ 硬选一张就会**悄悄丢掉另一张的改动**。')
        print('  怎么办: ① 打开上面两张表, 把那一条的 text_edited 改成**相同**内容')
        print('          (同一条只应该出现在一张表里; 通常是把它的 kind 弄混了);')
        print('          ② 或者只给其中**一张表**给 --csv (那样另一张的改动不会被注入)。')
        print('  ★ 一个字都没写盘。')
        reject(a, 'rejected-by-ambiguous-id',
               dict(ambiguity=dict(count=len(rep['conflicts']), items=rep['conflicts'][:50]),
                    tables=rep['files'],
                    policy='同一个 id 在两张表里的 text_edited 必须一致; 不一致 ⇒ 退出码 1, 不写盘'))

    meta, meta_path = find_meta(rep['paths'])
    meta_format = None
    if meta:
        meta_format = meta.get('format')
        h = T.sha256_file(a.src)
        same = (not meta.get('iso_sha256')) or meta['iso_sha256'] == h
        print('# meta: %s | %s | 源盘 sha256 %s'
              % (meta.get('format'), meta.get('generated'), meta.get('iso_sha256', '?')[:16]))
        if not same:
            print('!! 警告: 表里记录的源盘 sha256 与 --src 不一致 (表可能来自别的盘)')
        _tk = (meta.get('tables') or {})
        if _tk.get('kinds'):
            print('# meta.tables: %d 张表 / %s / 共 %d 行'
                  % (_tk.get('tables', 0), ','.join(_tk['kinds']), _tk.get('rows_total', 0)))
    else:
        print('# meta: (没找到 .meta.json —— 少一层校验, 继续)')

    # ★ 老格式的**合并大表** ⇒ 明确提示「请改用多表」(行为照旧, 结果与多表等价)
    merged_table_notice(rep, meta_format, meta_path, a.src,
                        merge_note=('本次输入里 %d 张表, 合并后 %d 行 —— 其中**合并大表** %d 张'
                                    % (len(rep['files']), rep['merged'],
                                       len([f for f in rep['files'] if not f['kind']]))))

    cs = T.Charset()

    # ★★ 按键标记 + 人工断点标记 前瞻扫描 —— 必须在任何写盘动作之前完成, --force 也不能绕过 ★★
    #    (不查 ISO, 纯 CSV 内容检查, 所以 --check-only / --dry-run 同样会被拦下)
    btn_probs, btn_used = scan_btn_marks(rows, cs)
    n_btn, n_btn_bad = print_btn_marks(btn_probs, btn_used)
    wrap_probs, wrap_st = scan_wrap_marks(rows)
    n_wrap, n_wrap_bad = print_wrap_marks(wrap_probs, wrap_st)

    # ★★ 旧格式 CSV (text-csv/1, text-csv/2) 的长段保护 ★★
    #   round35 及更早的 dump 把「引擎自动折行点」写成 {WRAP} 塞进正文列 (现役盘 1548 个)
    #   ⇒ round36 起 {WRAP} 是人工断点, 拿旧表注入会把那些自动折行**固化成硬换行**。
    legacy = legacy_risky_rows(rows, only, meta_format)
    zh_wrap = legacy_wrap_in_zh(rows, only)
    zh_risky = [rid for (rid, _n, risky) in zh_wrap if risky]
    if zh_wrap and not legacy:
        print('\n[!! 注意] 这份 CSV 的 **text_zh**(只读参考列) 里有 %d 处 %s 标记 (分布在 %d 行): %s'
              % (sum(n for (_r, n, _k) in zh_wrap), T.WRAP_MARK, len(zh_wrap),
                 ' '.join(r for (r, _n, _k) in zh_wrap[:6])))
        print('   round36 的 dump **绝不会**往 text_zh 里写标记 ⇒ 这份表很可能是 round35 及更早的'
              '旧格式 (或有人把标记贴到了只读列)。')
        print('   旧表里那些标记是「引擎会在这里自动折行」的**自动提示**, 现在会被当成'
              '**人工断点**写进盘。')
        if zh_risky:
            print('   !! 其中 %d 行**既被编辑过、又带着这些标记** ⇒ 拒绝注入 (会固化成硬换行): %s'
                  % (len(zh_risky), ' '.join(zh_risky[:8])))
            if not a.force:
                print('   怎么办: 重新 dump 一份新格式表 (新格式正文列里一个标记都没有):')
                print('           python tools/text_csv/dump_text_csv.py --iso %s --out %s '
                      '--carry-edited %s'
                      % (rel_or_abs(a.src), rel_or_abs(os.path.join(os.path.dirname(csv_arg(a)),
                                                                    'REDUMP_text.csv')),
                         rel_or_abs(csv_arg(a))))
                print('           (--carry-edited 会把你改过的 text_edited 原样搬过去, 见 FORMAT.md §0)')
                reject(a, 'rejected-by-legacy-csv',
                       dict(legacy_csv=dict(meta_format=meta_format or '无 meta',
                                            text_zh_wrap_rows=zh_wrap, risky=zh_risky),
                            tables=rep['files'], only=only))
            print('   [!! 警告] --force 已指定: 继续注入 (自动折行会被固化成硬换行, 自负)')
        else:
            print('   ⇒ 这些行没有被编辑过, 本来就不会写盘; 但请**不要**用这份表改长段,'
                  ' 建议重新 dump (见 FORMAT.md §3.6)。')
    if legacy:
        print('\n[!!] 这份表是**旧格式** (%s): 正文列里的 %s 当年是「引擎会在这里自动折行」的'
              '提示, 现在会被当成**人工断点**写进盘,' % (meta_format or '无 meta', T.WRAP_MARK))
        print('     里面有 %d 条**被编辑过的长段** (wrap_w>0) ⇒ 拒绝注入:' % len(legacy))
        print('       %s%s' % (' '.join(legacy[:8]), ' …' if len(legacy) > 8 else ''))
        print('     怎么办: ① 重新 dump 一份新格式表并把改动搬过去 (推荐, 一条命令):')
        print('               python tools/text_csv/dump_text_csv.py --iso %s --out '
              '<同目录>/<版本>_text.csv --carry-edited %s'
              % (rel_or_abs(a.src), rel_or_abs(csv_arg(a))))
        print('               然后在**新表**里用 %s 明确标出你想断行的位置'
              '(或直接敲回车)' % T.WRAP_MARK)
        print('             ② 只改短文本/wrap_w=0 的条目 ⇒ 不受影响, 可照旧注入')
        print('     确要照旧注入加 --force (那 1548 个自动提示会变成真·硬换行, 盘上结构被改变)。')
        if not a.force:
            reject(a, 'rejected-by-legacy-csv',
                   dict(legacy_csv=dict(meta_format=meta_format, rows=legacy),
                        tables=rep['files'], only=only))
        print('     [!! 警告] --force 已指定: 继续用旧格式表注入 (请自行核对结果)')

    if btn_probs or wrap_probs:
        print('\n[拒绝注入] 有 %d 处标记问题 (%d 处按键标记 + %d 处断点标记), 未写任何文件。'
              % (n_btn_bad + n_wrap_bad, n_btn_bad, n_wrap_bad))
        reject(a, 'rejected-by-mark',
               dict(only=only, tables=rep['files'],
                    btn_marks=dict(total=n_btn, distinct=sorted(btn_used), problems=btn_probs),
                    wrap_breaks=dict(mark=T.WRAP_MARK, total=wrap_st['edited'],
                                     in_text_zh=wrap_st['zh'], problems=wrap_probs)))

    iso = T.Iso(a.src)
    h_src = T.sha256_file(a.src)
    print('# src : %s  sha256=%s' % (iso.path, h_src))

    # ★★ 字库覆盖预检 —— 必须在任何写盘动作之前完成 ★★
    pre = charset_precheck(rows, only, cs, iso)
    n_miss, n_dead, n_en_only = print_precheck(pre, force=a.force, check_only=a.check_only)
    fatal = [x for x in pre['chars'] if x['kind'] not in WARN_KINDS]
    if fatal and not a.force:
        if a.report:
            _write_report(a, pre, rows, only, h_src, None, [], None)
        iso.close()
        sys.exit(EXIT_CHARSET)
    if a.check_only:
        # ★ round63: --check-only 也要把**属性行 (标题)** 的写法/定位问题查一遍 ——
        #   只读 SFXML 那一个容器 (不动 LANG), 且**只有表里真有属性行时才做**
        #   ⇒ 纯正文表的 --check-only 行为逐字未变。
        rc_attr = attr_check_only(rows, cs, iso, only, a.force)
        if a.report:
            _write_report(a, pre, rows, only, h_src, None, [], None)
        iso.close()
        sys.exit(rc_attr if rc_attr else EXIT_OK)
    if not a.dst:
        iso.close()
        print('!! 缺少 --dst (非 --check-only 时必须给输出盘)')
        sys.exit(EXIT_USAGE)

    conts = {}
    for name, spec in T.RES.items():
        conts[name] = [Container(iso, name, cp, cs) for cp in spec['copies']]
        c0 = conts[name][0]
        print('# %-6s %s  blob=%d 子流尺寸=%s 帧=%d 槽=%d'
              % (name, '+'.join(c.tag for c in conts[name]), len(c0.blob), c0.sizes,
                 c0.frame_len, c0.slot))
        if len(conts[name]) > 1:
            p0 = conts[name][0].iter_payloads(conts[name][0].blob)
            for c in conts[name][1:]:
                p1 = c.iter_payloads(c.blob)
                if p0 != p1:
                    raise SystemExit('!! %s 两份拷贝内容不一致, 拒绝注入' % name)

    stats = dict(candidates=0, changed=0, skipped_untouched=0, skipped_same=0,
                 skipped_other=0, warnings=[], empty_cells=0, wrap_breaks=0, max_run=0,
                 stale_rows=[])
    plan = []
    for r in rows:
        rid, res = r['id'].strip(), r['resource'].strip().upper()
        if is_attr_row(r):
            continue          # ★ round63: 属性行 (标题) 走**另一条通道** (下面 plan_attr_edits)
        if res not in conts:
            stats['warnings'].append('%s: 未知 resource %r' % (rid, res))
            continue
        if not id_match(rid, only):
            stats['skipped_other'] += 1
            continue
        stats['candidates'] += 1
        loc = r['entry_index'].strip()
        found = conts[res][0].locate(loc)
        if found is None:
            raise SystemExit('!! %s: 源盘里找不到条目 %s' % (rid, loc))
        off, ln, old = found
        if (int(r['offset']) != off or int(r['len_bytes']) != ln) and not a.force:
            raise SystemExit('!! %s: CSV 的 offset/len (%s/%s) 与源盘 (%d/%d) 不符 —— '
                             'CSV 已过期/来自别的盘 (--force 可忽略)'
                             % (rid, r['offset'], r['len_bytes'], off, ln))
        cell = r['text_edited']
        if cell.strip() == EMPTY_SENTINEL:
            cell = ''
            stats['empty_cells'] += 1
        elif cell == '':
            stats['skipped_same'] += 1
            continue
        # ★ 未人工改动 = text_edited 与 dump 出来的 text_zh 完全相同 ⇒ 这一条不动
        #   (dump 时两列预填同样内容; 只要编辑者动过这一格, 就按他写的换行注入)
        if cell == r['text_zh']:
            stats['skipped_untouched'] += 1
            continue
        # ★ round39: 「这份表是不是过期」的硬判据 (只在**真要写**这一条时才查) ——
        #   把**盘上原字节**按当前字符集解出来, 必须能逐字节写回去。做不到 ⇒
        #   这份表的 text_zh/text_edited 是用**另一版字符集** dump 的: 那时看着"没改过"
        #   的行, 用现在的字符集重新编码会变成**别的字** ⇒ 会悄悄把文本写坏
        #   (实测: 现役盘表 + 换过字符集的工具链 = 29 条被改写)。
        try:
            _t_old, _ = cs.decode(old)
            stale = (cs.encode_strict(_t_old) != old)
        except T.CharsetError:
            stale = True
        if stale:
            stats['stale_rows'].append(rid)
        for tag in ('{br}', '{p}'):
            if tag in cell:
                stats['warnings'].append('%s: 单元格里出现字面量 %s —— 换行请直接敲回车, '
                                         '不要手写引擎标记' % (rid, tag))
        if r['kind'] == 'short' and '\n' in cell:
            stats['warnings'].append('%s: 短文本(kind=short)里加了换行; 若该处不是 RSHTML '
                                     '组件, {br} 可能被原样画出 (首次请用 --only 小批验证)'
                                     % rid)
        if r['kind'] == 'locked':
            stats['warnings'].append('%s: kind=locked (字节回环不稳定), 仍按 CSV 注入, '
                                     '请人工核对' % rid)
        cell_stat = {}
        new = encode_cell_or_die(rid, cell, cs, cell_stat)
        if new == old:
            stats['skipped_same'] += 1
            stats['wrap_breaks'] += cell_stat.get('n_wrap', 0)
            continue
        if len(new) > int(r['max_bytes']):
            stats['warnings'].append('%s: 新长度 %d B 超过该条 max_bytes %s'
                                     % (rid, len(new), r['max_bytes']))
        stats['changed'] += 1
        stats['wrap_breaks'] += cell_stat.get('n_wrap', 0)
        stats['max_run'] = max(stats.get('max_run', 0), cell_stat.get('max_run', 0))
        plan.append((res, r, loc, old, new))

    if stats['wrap_breaks']:
        print('# 人工断点: 本次把 %d 个 %s / {Warp} 标记**变成真换行** ({br}), 已写进盘的设计里 ✓'
              % (stats['wrap_breaks'], T.WRAP_MARK))

    # ★★ round39: 「这份表是旧字符集 dump 的」⇒ 拒绝写盘 ★★
    #   症状: 看着"没改过"的行, 用现在的字符集重新编码会变成别的字 —— 悄悄写坏文本。
    #   判据: 盘上原字节 → 当前字符集 decode → encode_strict 回不去原字节。
    if stats['stale_rows']:
        n_st = len(stats['stale_rows'])
        print('\n[!!] 这份表**不是当前字符集 dump 出来的** —— 有 %d 条 (占候选 %d 条的 %.0f%%) '
              '无法用本盘字符集逐字节还原:' % (n_st, stats['candidates'],
                                              100.0 * n_st / max(1, stats['candidates'])))
        print('     %s%s' % (' '.join(stats['stale_rows'][:10]),
                             ' …' if n_st > 10 else ''))
        print('   为什么必须拦: 这些行的 text_zh/text_edited 是**旧字符集**下的写法;')
        print('     用现在的字符集重新编码会变成**别的字** ⇒ 你以为"没改过"的行也会被改写。')
        print('   怎么办: 重新 dump 一份 (同时用 --carry-edited 把人工改动搬过去):')
        print('     python tools/text_csv/dump_text_csv.py --iso %s --out %s '
              '--carry-edited %s'
              % (rel_or_abs(a.src),
                 rel_or_abs(os.path.join(os.path.dirname(csv_arg(a)), 'REDUMP_text.csv')),
                 rel_or_abs(csv_arg(a))))
        print('   ★ 一个字都没写盘。')
        reject(a, 'rejected-by-stale-charset',
               dict(stale_charset=dict(count=n_st, rows=stats['stale_rows'][:100],
                                       charset=os.path.relpath(T.CHARSET, T.REPO)),
                    tables=rep['files'], only=only))
    if stats.get('max_run', 0) >= 3:
        stats['warnings'].append(
            '有单元格里出现 %d 个**连续换行** (多个空行) —— 它们会被折叠成 **1 个 {p}** '
            '(段间空一行); 引擎没有"更多空行"的表示法' % stats['max_run'])

    print('\n# 候选 %d 行; 实际改动 %d; 未改动(与 text_zh 相同)跳过 %d; '
          '与源盘等价跳过 %d; 不在 --only 内 %d%s'
          % (stats['candidates'], stats['changed'], stats['skipped_untouched'],
             stats['skipped_same'], stats['skipped_other'],
             ('; 显式清空 %d' % stats['empty_cells']) if stats['empty_cells'] else ''))
    for w in stats['warnings'][:20]:
        print('!! %s' % w)

    # ── ★ round63: 属性级通道 (「特别收录」标题 = SFXML 的 name= 属性) ──
    #   表: <版本>_text_sf_titles.csv (id = SFXML:A####); 只写 copies[0] (现役盘 MENU.IMG#283)。
    #   与正文行**完全分开**跑, 所以只有标题表的运行不会碰正文, 反之亦然。
    attr_plan, ast, aprobs = plan_attr_edits(rows, conts, cs, only, a.force)
    if ast['rows'] or aprobs:
        print_attr_plan(attr_plan, ast, conts)
        if aprobs:
            hard = [p for p in aprobs if p['hard']]
            soft = [p for p in aprobs if not p['hard']]
            print('\n[!!] 属性行 (标题) 有 %d 处问题: %d 处**写法错** (--force 也不能绕过) + '
                  '%d 处与源盘不同步 (--force 可忽略):'
                  % (len(aprobs), len(hard), len(soft)))
            for p in aprobs[:12]:
                print('  ── %s%s' % (p['id'], '' if p['hard'] else '   ← --force 可忽略'))
                print('     %s' % p['why'])
            if len(aprobs) > 12:
                print('  …(还有 %d 处)' % (len(aprobs) - 12))
            if hard or not a.force:
                print('\n  怎么办: ① 写法错 ⇒ 按上面每条改 CSV (标题必须**单行**、不含 '
                      '" < & 、不能用 [[empty]] 清空);')
                print('          ② 与源盘不同步 ⇒ 用 dump_sf_titles_csv.py 重新 dump 一份标题表, '
                      '把你改过的 text_edited 搬过去;')
                print('          ③ 只忽略"不同步"这一类可以加 --force '
                      '(**写法错永远不能绕过**)。')
                print('  ★ 一个字都没写盘。')
                reject(a, 'rejected-by-attr-rows',
                       dict(attr_problems=aprobs, attr_stats=dict(ast),
                            tables=rep['files'], only=only))
        if ast['stale']:
            print('\n[!!] 有 %d 条属性行的**盘上现值**不能用当前字符集逐字节还原 '
                  '(这份标题表不是当前字符集 dump 出来的) ⇒ 拒绝写盘:'
                  % len(ast['stale']))
            print('     %s%s' % (' '.join(ast['stale'][:10]),
                                 ' …' if len(ast['stale']) > 10 else ''))
            print('   怎么办: 用当前工具链重新 dump 一份标题表 (改动请搬过去):')
            print('     python tools/text_csv/dump_sf_titles_csv.py --iso %s --out %s'
                  % (rel_or_abs(a.src),
                     rel_or_abs(os.path.join(os.path.dirname(csv_arg(a)), 'REDUMP_text.csv'))))
            print('   ★ 一个字都没写盘。')
            reject(a, 'rejected-by-stale-charset',
                   dict(stale_charset=dict(count=len(ast['stale']), rows=ast['stale'][:100],
                                           charset=os.path.relpath(T.CHARSET, T.REPO),
                                           channel='sf_titles (属性行)'),
                        tables=rep['files'], only=only))

    # ── 逐行明细 (编辑前/后字节数 + 渲染行数) ──
    detail = []
    for res, r, loc, old, new in plan:
        for c in conts[res]:
            f = c.locate(loc)
            assert f and f[2] == old, '%s/%s 两份拷贝内容不一致' % (res, loc)
            sp0, sp1 = c.span(f[0], f[1])
            c.edits.append((sp0, sp1, c.marshal(new), r))
        old_t, _ = cs.decode(old)
        new_t, _ = cs.decode(new)
        w = int(r['wrap_w'] or 0)
        cst = {}
        T.cell_to_bytes_text(r['text_edited'], cs, cst)
        # ★ round36: 人工断点落点核对 —— 人写的 {WRAP} 到底落在盘上哪里
        want_pos = T.wrap_break_positions(r['text_edited'])       # 每个断点前面的字符数
        br_before = [p for (k, p) in T.tag_break_positions(old_t) if k == 'br']
        br_after = [p for (k, p) in T.tag_break_positions(new_t) if k == 'br']
        br_added = sorted(_multiset_sub(br_after, br_before))
        detail.append(dict(id=r['id'], container=r['container'], entry=loc,
                           kind=r['kind'], wrap_w=w,
                           bytes_before=len(old), bytes_after=len(new),
                           delta=len(new) - len(old),
                           render_lines_before=(T.wrap_line_count(old_t, w) if w
                                                else len(T.TAG_RE.findall(old_t)) + 1),
                           render_lines_after=(T.wrap_line_count(new_t, w) if w
                                               else len(T.TAG_RE.findall(new_t)) + 1),
                           hard_breaks_before=old_t.count('{br}') + old_t.count('{p}'),
                           hard_breaks_after=new_t.count('{br}') + new_t.count('{p}'),
                           breaks_br_before=old_t.count('{br}'),
                           breaks_br_after=new_t.count('{br}'),
                           breaks_p_before=old_t.count('{p}'),
                           breaks_p_after=new_t.count('{p}'),
                           wrap_breaks=cst.get('n_wrap', 0),
                           wrap_break_positions=want_pos,
                           br_positions_before=br_before,
                           br_positions_after=br_after,
                           br_added_by_wrap=br_added,
                           wrap_landed_ok=(br_added == sorted(want_pos)),
                           cell_max_newline_run=cst.get('max_run', 0),
                           max_bytes=int(r['max_bytes']),
                           # ★ 报告/控制台里给**人看的**写法: 私有区占位换成 {{BTN:XXXX}}
                           #   (折行模型仍旧吃私有区形式, 见 tcslib.Charset.decode 注释)
                           text_before=T.pua_to_marks(old_t),
                           text_after=T.pua_to_marks(new_t),
                           btn_marks_before=sorted({T.BTN_FMT % ord(c) for c in old_t
                                                    if 0xE000 <= ord(c) <= 0xE0FF}),
                           btn_marks_after=sorted({T.BTN_FMT % ord(c) for c in new_t
                                                   if 0xE000 <= ord(c) <= 0xE0FF})))
    if detail:
        print('\n%-18s %-8s %10s %10s %8s %8s %8s %6s %6s %8s' %
              ('id', 'kind', 'len_before', 'len_after', 'delta', '行(前)', '行(后)',
               'br前', 'br后', '人工断点'))
        for d in detail:
            print('%-18s %-8s %10d %10d %+8d %8s %8s %6d %6d %8d'
                  % (d['id'], d['kind'], d['bytes_before'], d['bytes_after'], d['delta'],
                     d['render_lines_before'], d['render_lines_after'],
                     d['breaks_br_before'], d['breaks_br_after'], d['wrap_breaks']))

    # ── ★ round36: 人工断点落点核对 (人写的 {WRAP} → 盘上的 {br}) ──
    wrap_rows = [d for d in detail if d['wrap_breaks']]
    if wrap_rows:
        print('\n# ── 人工断点落点核对 (text_edited 里的 %s/{Warp} → 盘上新增的 {br}) ──'
              % T.WRAP_MARK)
        print('# 位置口径: 「第 N 个字符之后」= 断点前面有 N 个字符 (N 数的是可见字符, '
              '不含 {br}/{p} 标记本身)')
        for d in wrap_rows:
            ok = '✓ 一一对应' if d['wrap_landed_ok'] else '!! **与预期不符**, 请人工核对'
            print('# %s: %s ×%d; 该条 {br} 总数 %d → %d'
                  % (d['id'], T.WRAP_MARK, d['wrap_breaks'],
                     d['breaks_br_before'], d['breaks_br_after']))
            print('#   你写的断点位置: %s'
                  % ', '.join('第 %d 个字符之后' % p for p in d['wrap_break_positions']))
            print('#   盘上新增 {br} 位置: %s   %s'
                  % (', '.join('第 %d 个字符之后' % p for p in d['br_added_by_wrap']), ok))
            plain = _plain(d['text_after'])
            for p in d['br_added_by_wrap']:
                print('#     ⏎ 第 %d 个字符之后: …%s⏎%s…'
                      % (p, plain[max(0, p - 10):p], plain[p:p + 10]))

    # ── ★ round63: 属性行的 edits —— **只**写 copies[0] (另外 9 份副本不在 copies 里, 
    #    所以物理上不可能被写到; 下面还再断言一次) ──
    if attr_plan:
        if len(conts.get('SFXML') or []) != 1:
            raise SystemExit('!! 属性通道只写 copies[0], 但 SFXML 有 %d 份拷贝 ⇒ 拒绝写盘'
                             % len(conts.get('SFXML') or []))
        cxml = conts['SFXML'][0]
        for d in attr_plan:
            sp0, sp1 = cxml.span(d['off'], len(d['old']))     # span(off, 长度) ⇒ (start, end)
            assert cxml.blob[sp0:sp1] == d['old'], '%s 属性区间回读不符' % d['id']
            cxml.edits.append((sp0, sp1, cxml.marshal(d['new']), d['r']))

    # ── 重压 + 超槽检查 ──
    # ★ 闸门自检 (默认路径): 本盘 ELF 实测闸门之下 `0xB1..gate-1` 的裸字节会让引擎吞掉
    #   后一个字节 ⇒ 乱码/崩。窗口为空 (gate ≤ 0xB1) 时**零行为变化**。
    gate = T.read_decode_gate(iso)
    gate_pairs = T.load_gate_pairs()
    if list(T.legacy_window(gate)):
        print('\n[gate] 本盘 ELF 解码闸门 = 0x%02X ⇒ 自检窗口 0xB1..0x%02X '
              '(pair 表 %d + gate_pairs %d 条)'
              % (gate, gate - 1, len(cs.pair_of), len(gate_pairs)))
        warn = T.charset_gate_warnings(cs, gate, {_ch: tuple(_p) for _p, _ch in gate_pairs.items()})
        for (_c, b, pr, src) in warn:
            print('[gate] ⚠ charset codes 里的 %r = 0x%02X 落在前导区间内 '
                  '(对偶码 %s ← %s) —— 本字若被注入会写成裸前导字节。'
                  % (_c, b, ('0x%02X%02X' % pr) if pr else '**没有**', src or '—'))

    writes = []
    for name, cl in conts.items():
        for c in cl:
            new_blob, delta = c.build_blob()
            if list(T.legacy_window(gate)):
                r = T.legacy_selfcheck_container(c, new_blob, gate, gate_pairs)
                print('   [gate] %s: 旧单字节码残留 %d 处 ✓' % (c.tag, r['n']))
            frame, n_rep = c.repack(new_blob)
            over = len(frame) - c.slot
            print('\n== %s (%s) ==' % (name, c.tag))
            print('   编辑 %d 条; 解压 %d → %d B (%+d, 尾部陈旧区 %d B)'
                  % (len(c.edits), len(c.blob), len(new_blob), delta,
                     len(c.blob) - c.used_end))
            print('   压缩帧 %d → %d B / 槽 %d (%s%d); 重压子流 %d/%d'
                  % (c.frame_len, len(frame), c.slot, '余 ' if over <= 0 else '超槽 ',
                     -over, n_rep, len(c.sizes)))
            assert len(new_blob) == len(c.blob), '解压总长必须不变'
            if over > 0:
                raise SystemExit(
                    '!! 超槽 %d B: 压缩后装不进原槽位。\n'
                    '   本次改动: %s\n'
                    '   请精简文本, 或分多次注入 (每次 --only 小批)。'
                    % (over, _hint(detail)))
            writes.append(dict(res=name, tag=c.tag, iso_off=c.entry['iso_off'],
                               slot=c.slot, frame=frame, blob=new_blob, c=c))

    if a.dry_run:
        print('\n[dry-run] 未写任何文件')
        return

    if os.path.abspath(a.dst) == os.path.abspath(a.src):
        raise SystemExit('!! --dst 不能等于 --src (请另存新盘)')
    shutil.copyfile(a.src, a.dst)
    if writes:
        with open(a.dst, 'r+b') as f:
            for w in writes:
                f.seek(w['iso_off'])
                f.write(w['frame'] + b'\x00' * (w['slot'] - len(w['frame'])))
                f.seek(w['iso_off'])
                back = f.read(w['slot'])
                got = b''.join(s[0] for s in T.lzo_subs(back))
                if got != w['blob']:
                    raise SystemExit('!! %s 回读不符' % w['tag'])
                print('[write] %-22s @ISO 0x%X 帧 %d B + 零填至槽 %d B; 回读一致 ✓'
                      % (w['tag'], w['iso_off'], len(w['frame']), w['slot']))

    # ── 全盘差异窗口断言 ──
    windows = [(w['iso_off'], w['slot']) for w in writes]
    n_diff, outside = _diff_windows(a.src, a.dst, windows)
    print('\n[diff] 全盘差异 %d B / %d 个写入窗口; 窗口外差异: %s'
          % (n_diff, len(windows), outside[:5] if outside else '无 ✓'))
    if outside:
        raise SystemExit('!! 出现窗口外差异')

    # ── 容器自洽复检 (从产物盘重新解析) ──
    _verify_output(a.dst, conts, plan, cs, attr_plan=attr_plan)

    h_dst = T.sha256_file(a.dst)
    print('\n[hash] src %s' % h_src)
    print('[hash] dst %s' % h_dst)
    print('[hash] %s' % ('逐字节相同 (无改动)' if h_src == h_dst
                         else '已按 CSV 修改 %d 条正文 + %d 个标题 (属性)'
                              % (len(detail), len(attr_plan))))

    out = dict(format=FMT_CURRENT + '-inject',
               csv=[os.path.abspath(p) for p in rep['paths']],
               tables=rep['files'],
               tables_merged_rows=rep['merged'],
               tables_duplicates=rep['duplicates'],
               src=os.path.abspath(a.src), src_sha256=h_src,
               dst=os.path.abspath(a.dst), dst_sha256=h_dst,
               only=only, changed=stats['changed'], skipped_same=stats['skipped_same'],
               warnings=stats['warnings'], rows=detail,
               btn_marks=dict(total=n_btn, distinct=sorted(btn_used), problems=[]),
               wrap_breaks=dict(mark=T.WRAP_MARK, spellings=[T.WRAP_MARK, '{Warp}'],
                                in_text_edited=wrap_st['edited'],
                                rows=dict(wrap_st['edited_rows']),
                                in_text_zh_readonly=wrap_st['zh'],
                                breaks_written=stats['wrap_breaks'],
                                positions=[dict(id=d['id'],
                                                cell_break_positions=d['wrap_break_positions'],
                                                br_positions_after=d['br_positions_after'],
                                                br_added=d['br_added_by_wrap'],
                                                landed_ok=d['wrap_landed_ok'])
                                           for d in detail if d['wrap_breaks']],
                                policy=('人在 text_edited 里写的 %s / {Warp} = **人工断点**: '
                                        '注入时在该位置写出一个真换行 (盘上 {br}); '
                                        '标记本身不写盘。位置非法 (行首/行尾/紧邻换行或另一个'
                                        '标记) 或写法错误 ⇒ 拒绝注入 (退出码 1)'
                                        % T.WRAP_MARK)),
               csv_meta_format=meta_format, csv_meta=rel_or_abs(meta_path) if meta_path else None,
               generated=datetime.datetime.now().isoformat(timespec='seconds'))
    # ── 「字库覆盖预检」一节 ──
    out['charset_precheck'] = charset_precheck_section(pre, a.force)
    # ── ★ round63: 「属性级通道 (特别收录标题)」一节 ──
    out['attr_channel'] = attr_channel_section(attr_plan, ast, conts)
    if a.report:
        json.dump(out, open(a.report, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('[report] %s' % a.report)
    iso.close()
    sys.exit(EXIT_OK)


def attr_check_only(rows, cs, iso, only, force):
    """★ round63: ``--check-only`` 时对**属性行 (标题)** 做的只读检查。

    只读 ``tcslib.RES['SFXML']['copies'][0]`` 一个容器 (不碰 LANG), 跑完整的
    `plan_attr_edits` (写法门槛 + tag/序号复核 + 与源盘对表 + 编码/缺字) 并打印结果。
    返回 0 (可以注入) 或 EXIT_STRUCT (有结构性问题; 写法错连 --force 都不行)。
    表里没有属性行 ⇒ 直接返回 0, 什么都不打印 (纯正文表行为不变)。
    """
    if not any(is_attr_row(r) for r in rows):
        return EXIT_OK
    spec = T.RES['SFXML']['copies'][0]
    c = Container(iso, 'SFXML', spec, cs)
    conts = {'SFXML': [c]}
    print('\n# [check-only] 属性行 (标题) 检查: 目标容器 %s 槽 %d B / 解压 %d B'
          % (c.tag, c.slot, len(c.blob)))
    plan, ast, probs = plan_attr_edits(rows, conts, cs, only, force)
    print_attr_plan(plan, ast, conts)
    if not probs:
        if ast['rows']:
            print('[ok] 属性行写法/定位/tag 全部通过 ✓'
                  '%s' % (' (本次会写 %d 个标题)' % ast['changed'] if ast['changed'] else ''))
        return EXIT_OK
    hard = [p for p in probs if p['hard']]
    print('\n[!!] 属性行 (标题) 有 %d 处问题: %d 处写法错 (--force 也不能绕过) + '
          '%d 处与源盘不同步 (--force 可忽略):' % (len(probs), len(hard), len(probs) - len(hard)))
    for p in probs[:12]:
        print('  ── %s%s' % (p['id'], '' if p['hard'] else '   ← --force 可忽略'))
        print('     %s' % p['why'])
    if len(probs) > 12:
        print('  …(还有 %d 处)' % (len(probs) - 12))
    print('\n  怎么办: ① 写法错 ⇒ 按上面每条改 CSV (标题必须**单行**、不含 " < & 、'
          '不能用 [[empty]] 清空);')
    print('          ② 与源盘不同步 ⇒ 用 dump_sf_titles_csv.py 重新 dump 一份标题表, '
          '把你改过的 text_edited 搬过去。')
    print('  ★ 一个字都没写盘 (--check-only)。')
    return EXIT_STRUCT if (hard or not force) else EXIT_OK


def attr_channel_section(attr_plan, ast, conts):
    """★ round63: 报告里的「属性级通道 (特别收录标题)」一节。

    没有属性行时给 ``dict(rows=0, ...)`` —— 老调用方 (纯正文注入) 看到的仍是老结构,
    只是多了一个自述"本次没有属性行"的键。
    """
    c = (conts.get('SFXML') or [None])[0]
    return dict(
        channel='SFXML name= 属性 (「特别收录」条目标题)',
        id_prefix='SFXML:A####',
        rows=ast.get('rows', 0),
        candidates=ast.get('candidates', 0),
        changed=ast.get('changed', 0),
        skipped_untouched=ast.get('skipped_untouched', 0),
        skipped_already=ast.get('skipped_already', 0),
        skipped_other=ast.get('skipped_other', 0),
        grow=ast.get('grow', 0), shrink=ast.get('shrink', 0), same=ast.get('same', 0),
        delta_total_bytes=ast.get('delta_total', 0),
        long_titles_warned=ast.get('long', 0),
        csv_offset_drifted=ast.get('csv_stale', []),
        stale_charset_rows=ast.get('stale', []),
        warnings=ast.get('warnings', []),
        target=dict(container=(c.tag if c else None), slot=(c.slot if c else None),
                    blob_bytes=(len(c.blob) if c else None),
                    used_end=(c.used_end if c else None),
                    tail_free_bytes=((len(c.blob) - c.used_end) if c else None),
                    copies=len(conts.get('SFXML') or []),
                    only_target='只写 copies[0] (现役盘 MENU.IMG#283); 另外 9 份副本不动'),
        rows_detail=[dict(id=d['id'], locator=d['loc'], tag=d['tag'],
                          offset_before=d['off'], bytes_before=len(d['old']),
                          bytes_after=len(d['new']), delta=d['delta'],
                          off_stale=d['off_stale'], force_reencode=d['force_reencode'],
                          text_before=d['old_text'], text_after=d['new_text'])
                     for d in (attr_plan or [])],
        policy=('属性行按 entry_index (A####) 定位 (改字数会让后面的 offset 漂移); '
                'tag 列复核序号; offset/len_bytes 与源盘对表; '
                '盘上现值 == text_edited ⇒ 已写过 (幂等跳过); '
                '现值既非 text_zh 也非 text_edited ⇒ 拒绝 (表与源盘不同步, --force 可忽略)。'
                '改字数: 增长吃 </SpecialFeatures> 之后的陈旧尾巴, 超出即中止 '
                '(不截断、不静默丢字); 解压总长与 IMG 条目表 off/stored/real 一律不变。'))


def charset_precheck_section(pre, force):
    """把预检结果整理成报告里的一节 (dict)。"""
    g = pre['guard']
    return dict(
        verdict=('fail' if ([x for x in pre['chars'] if x['kind'] not in WARN_KINDS] and not force)
                 else ('forced' if [x for x in pre['chars'] if x['kind'] not in WARN_KINDS]
                       else 'pass')),
        forced=bool(force),
        font_source=g.atlas_note(),
        font_notes=g.notes(),
        checked_entries=pre['checked'],
        btn_marks=dict(total=sum(pre.get('marks', {}).values()),
                       distinct=sorted(pre.get('marks', {})),
                       policy='按键图标标记由引擎直接画图标, 不吃字库 ⇒ 整体跳过字形检查'),
        wrap_marks=dict(mark=T.WRAP_MARK, total=pre.get('wrap_marks', 0),
                        total_breaks=pre.get('wrap_marks', 0),
                        policy=('人工断点标记注入时变成真换行 {br}; 标记本身不写盘 '
                                '⇒ 不进字形检查')),
        problem_chars=len(pre['chars']),
        missing_chars=sum(1 for x in pre['chars'] if x['kind'] != 'dead_pair'),
        dead_pair_chars=sum(1 for x in pre['chars'] if x['kind'] == 'dead_pair'),
        chars=[dict(kind=x['kind'], char=x['char'], cp=x['cp'],
                    reason=x['reason'], locator=x['locator'],
                    advice=KIND_ADVICE.get(x['kind'], ''), hits=x['hits'])
               for x in pre['chars']],
        en_only_ascii=pre['en_only'],
    )


def _write_report(a, pre, rows, only, h_src, h_dst, detail, stats):
    """--check-only / 预检失败 时也把报告写出来 (含「字库覆盖预检」一节)。"""
    out = dict(format=FMT_CURRENT + '-inject',
               csv=[os.path.abspath(p) for p in (getattr(a, '_csv_paths', None) or [])],
               src=os.path.abspath(a.src), src_sha256=h_src,
               dst=os.path.abspath(a.dst) if a.dst else None, dst_sha256=h_dst,
               mode=('check-only' if a.check_only else 'rejected-by-precheck'),
               only=only, changed=(stats['changed'] if stats else 0),
               warnings=(stats['warnings'] if stats else []),
               rows=detail or [],
               charset_precheck=charset_precheck_section(pre, a.force),
               generated=datetime.datetime.now().isoformat(timespec='seconds'))
    json.dump(out, open(a.report, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('[report] %s' % a.report)


def _hint(detail):
    return ', '.join('%s %+d' % (d['id'], d['delta']) for d in detail[:6])


def _plain(text):
    """把引擎正文里的 {br}/{p} 标记去掉 ⇒ 只剩可见字符 (给「断点位置」取前后文用)。"""
    return (text or '').replace('{br}', '').replace('{p}', '')


def _multiset_sub(a, b):
    """多重集合差 ``a - b`` (返回 list)。用于算「本次新增了哪些 {br}」。"""
    out, rest = [], list(b)
    for x in a:
        if x in rest:
            rest.remove(x)
        else:
            out.append(x)
    return out


def _diff_windows(src, dst, windows):
    win = sorted(windows)
    n, outside = 0, []
    with open(src, 'rb') as f1, open(dst, 'rb') as f2:
        pos = 0
        while True:
            x, y = f1.read(1 << 22), f2.read(1 << 22)
            if not x:
                break
            if x != y:
                for i in range(len(x)):
                    if x[i] != y[i]:
                        n += 1
                        p = pos + i
                        if not any(w0 <= p < w0 + wl for w0, wl in win):
                            outside.append(hex(p))
                            if len(outside) > 8:
                                return n, outside
            pos += len(x)
    return n, outside


def _verify_output(dst, conts, plan, cs, attr_plan=None):
    """从产物盘重新解析: 条目表字段不变 / 结构不变 / 编辑条目符 / 其余条目逐字节不变

    ★ round63: 再验一遍**属性通道** (「特别收录」标题): 每个被编辑的属性解出来必须
      == 表里的 `text_edited`; 其余属性逐字节不变; `<text>` 元素与结构计数不变。
    """
    iso2 = T.Iso(dst)
    edited = {}
    for res, r, loc, old, new in plan:
        edited[(res, loc)] = new
    attr_want = {}
    for d in (attr_plan or []):
        attr_want[d['loc']] = d['new']
    print('\n[verify] 产物容器自洽复检:')
    for name, cl in conts.items():
        for c in cl:
            e2 = iso2.img_entry(c.lba, c.idx)
            assert (e2['stored'], e2['off'], e2['real']) == \
                   (c.entry['stored'], c.entry['off'], c.entry['real']), \
                '%s 条目表 off/stored/real 被改动' % c.tag
            subs2 = T.lzo_subs(iso2.read(e2['iso_off'], e2['stored']))
            blob2 = b''.join(s[0] for s in subs2)
            assert len(blob2) == len(c.blob), '%s 解压长度变化' % c.tag
            pay = c.iter_payloads(blob2)
            pay0 = c.iter_payloads(c.blob)
            assert len(pay) == len(pay0)
            n_chg = n_same = 0
            for (loc, data), (loc0, data0) in zip(pay, pay0):
                want = edited.get((name, loc))
                if want is not None:
                    assert data == want, '%s %s 回读内容不符' % (c.tag, loc)
                    n_chg += 1
                else:
                    assert data == data0, '%s %s 意外变化' % (c.tag, loc)
                    n_same += 1
            extra = ''
            if name == 'LANG':
                extra = ('; ngroups=%d 结构重解析 OK'
                         % struct.unpack_from('<I', blob2, 0)[0])
            else:
                cnt = {k.decode(): blob2.count(k) for k in
                       (b'<text>', b'</text>', b'<studio', b'<item', b'<group',
                        b'</SpecialFeatures>')}
                assert cnt == {k.decode(): c.blob.count(k) for k in
                               (b'<text>', b'</text>', b'<studio', b'<item', b'<group',
                                b'</SpecialFeatures>')}, 'SFXML 结构破坏'
                extra = (', 结构计数 %s 不变' % cnt)
            print('  %-22s 条目 %d: 改动 %d / 逐字节不变 %d%s'
                  % (c.tag, len(pay), n_chg, n_same, extra))
            # ── ★ round63: 属性通道回读 (只对 SFXML 有意义) ──
            if name == 'SFXML':
                a_new, a_old = c.iter_attrs(blob2), c.iter_attrs(c.blob)
                assert len(a_new) == len(a_old) == len(c.attrs), \
                    '%s 属性个数变化 (%d → %d)' % (c.tag, len(a_old), len(a_new))
                n_ac = n_as = 0
                for (loc, val), (loc0, val0) in zip(a_new, a_old):
                    want = attr_want.get(loc)
                    if want is not None:
                        assert val == want, \
                            '%s %s 回读的标题不符: %r != %r' % (c.tag, loc, val, want)
                        got = cs.decode(val)[0]
                        exp = cs.decode(attr_want[loc])[0]
                        assert got == exp, '%s %s 回读解出的文本不符' % (c.tag, loc)
                        n_ac += 1
                    else:
                        assert val == val0, '%s %s 标题意外变化' % (c.tag, loc)
                        n_as += 1
                print('  %-22s 属性 %d: 改动 %d / 逐字节不变 %d '
                      '(tag 序列与结构计数同时复核 ✓)'
                      % (c.tag, len(a_new), n_ac, n_as))
                if attr_want:
                    assert n_ac == len(attr_want), \
                        '属性通道: 表里要改 %d 个, 产物里只核到 %d 个' % (len(attr_want), n_ac)
    iso2.close()


if __name__ == '__main__':
    # ★ 用 sys.exit(main()) 传退出码: --selfcheck 发现旧单字节码残留时返回 2
    #   (普通路径 main() 返回 None ⇒ 仍是 0, 行为不变)
    sys.exit(main())
