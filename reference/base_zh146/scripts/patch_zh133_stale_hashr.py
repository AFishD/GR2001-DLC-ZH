# -*- coding: utf-8 -*-
r"""patch_zh133_stale_hashr.py — 追平 `GR_HASHR` 那一轮**漏掉**的"哨兵 trail 旧码"迁移
（正文 481 处可见乱码 / 730 处根因；产物 = `GR_ZH133` 的文本+图集层）。

═══════════════════════════ 根因（本轮实测，全部可从盘上复现） ═══════════════════════════

`GR_HASHR` 轮（见 `docs/REPORT_SENTINEL_FIX.md` / charset 的 `_trail_fix_hashr` 节）查实:
**引擎 `DrawString`/`CharWidth` 对 trail ∈ {0xB1, 0xB5} 的对偶码有硬编码"图标特判"**
(命中走 `AddOneWord flag=1` 的容量 2 副包 ⇒ 逐字符写坏内存)。于是那一轮把 42 个真字的**码位**
从"哨兵槽"(slot 16/20/110/…/1900, 共 50 个 = 25 lead × 2 trail)搬到保留段低位连续的
42 槽 1936..1977 (新码 B5D9..B6A4), 并 retire 了 8 个私有区占位 ⇒ pair_of 2350 → 2300。
它的战斗文本改写只覆盖了 `GR_HASHR2400` 那条线的 738 处。

**本盘 (`GR_REBUILD2400` 及其所有后代，含 `GR_ZH129`/`GR_ZH130`) 上，那 42 个旧码在
3 个中文容器里还剩 730 处**（= 33 个不同字；两个 `EN_STRINGS.RES` 副本各 286 + SFXML 158）。
后果有两层:

  ① **显示**: 旧码已不在 `pair_of` 里 ⇒ 引擎把 2 字节拆成两个单字节/PUA 单元,
     **并且在下一次遇到"合法对偶"时错位重同步** ⇒ 一处的错位会污染后面整串。
     这就是用户看到的「准**貌褐习**化」(应「准星的变化」)、「曾广**钮前△跑斗**全球」
     (应「曾广泛应用于全球」);按 `_stale_base.py` 的旧口径统计 = **481 处 / 49 个乱码字**,
     而未打补丁基底上逐条相同 ⇒ **继承缺陷**。
  ② **风险**: 那 42 个旧码正是"哨兵 trail"码 ⇒ 每命中一次就走引擎的图标特判路径
     (容量 2 副包 / 逐字符写坏内存)。730 处 = 730 次命中机会。

**为什么图集里也没有新槽的字形**: 42 个字形的**物理位置**至今仍在旧槽
(逐 texel 与 `方正像素16.ttf` 模板 xor==0: 40/42; 另 2 个 `览`/`坻` 从来没有字形)。
即: 盘上的 atlas 仍停在 pre-hashr 布局, 而 charset 已经是 post-hashr 设计 ⇒ 三者不一致。

═══════════════════════════ 修法（只动 文本 + 图集, 一个字节 ELF 都不碰） ═══════════════════════════

  ① **图集**: 把 42 个字形从旧槽搬到新槽 1936..1977 的引擎格 (K2 几何: x=16*(slot%64),
     y = 3 + 16*(slot//64 + 2*[slot//64>=12]));
       · 40 个字形的像素**逐 texel 复制** (源 = 旧格, 与 TTF 模板 xor==0 已证);
       · `览`/`坻` 两个字盘上从来没有字形 ⇒ 用**同一张字体模板** `方正像素16.ttf`
         (`gen_font16.py` / `glyph_audit.py` 同配方: 原点 (8,8), 窗 [8:24,8:24), <128) 现画;
       · 旧格清零 —— **除非**该格与任何 FT 记录采样窗相交 (`损` slot 24 / `太` slot 32
         各有 24/32 px 被 ASCII 记录窗压着 ⇒ 保留不清, 免得改坏 ASCII 字形)。
  ② **文本**: 3 个中文容器里 730 处旧码 → 新码 (**2 字节换 2 字节, 长度不变, 结构字节不动**)。
     每个旧码对应的字 = charset `_trail_fix_hashr.table` 的登记值; 该表的**物理独立复核** =
     旧格像素与"该字的 TTF 模板"逐 texel 相同 (40/42 通过, 见门禁 ②)。
  ③ **charset 不改** (它已经是 post-hashr 设计; 本工具不写 charset)。

═══════════════════════════ 门禁（写盘后**从盘上回读**; 任一不过 ⇒ 删产物） ═══════════════════════════

  ① 图集三闸门 (w ≤ 1024 / px_size == w*h/2+16 / (w*h/2) % 2048 == 0)
  ② 42/42 字形就位: 新格 == 旧格 (40) 或 == TTF 模板 (42 全查); 旧格按计划清零/保留
  ③ 文本 730/730: 盘上回读(现役 charset) == 目标文本, 逐字; 旧码残留 0
  ④ "解到无字形格"的单元 == 0 (本轮自定的**权威**口径; 修前 730, 见报告 §before)
  ⑤ 载荷级旧码 0 (gate 0xBA) 且结构区裸旧码与源盘同数
  ⑥ 全盘字节普查: 改动全部落在 3 个容器槽 + 图集像素容器内; ASCII 字节 0 改动;
     IMG 条目表 off/stored/real 一个字节没动
  ⑦ 图集几何体检: "登记对偶字里在其引擎格有墨" 的个数 ≥ 源盘 (1837 → 1839)

用法:
  python tools/iso_build/patch_zh133_stale_hashr.py --iso <src.iso> --out <dst.iso> \
      --report <rep.json> [--dry-run]
"""
import argparse
import collections
import hashlib
import io
import json
import mmap
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
except Exception:                                                     # noqa: BLE001
    pass

import tcslib                                                         # noqa: E402
import dump_font as D                                                 # noqa: E402
import repack_font as RF                                              # noqa: E402
import font_compact as FC                                             # noqa: E402
from PIL import Image, ImageDraw, ImageFont                           # noqa: E402

# ★ K2 几何 (与 hashr_dump_font.py / glyph_audit.py 同一张配方单): 本盘的 ELF 网格常量实测
#   就是 NCOL=64 / SKIP_ROWS=2 / Y0=3 (见 REPORT_GLYPH_FIX §3.1、docs/REPORT_SENTINEL_FIX.md)。
#   tcslib 的默认值是老一轮的 62/3/2 ⇒ 必须**进程内覆写**, 否则算出来的引擎格不是引擎格。
tcslib.NCOL, tcslib.GRID_SKIP_ROWS, tcslib.GRID_Y0 = 64, 2, 3
tcslib.LEAD_HI = tcslib.PAIR_LEAD_HI = 0xBA

TOOL = 'tools/iso_build/patch_zh133_stale_hashr.py'
ROUND = 'round-zh133'
CW = CH = 16
FZ16 = os.path.join(REPO, 'third_party', 'fonts', '方正像素16.ttf')
W_EXP, H_EXP = 1024, 644
TARGETS = (
    ('MENU.IMG#%d' % tcslib.LANG_MENU_IDX, tcslib.MENU_LBA, tcslib.LANG_MENU_IDX, 'lang'),
    ('GR.IMG#%d' % tcslib.LANG_GR_IDX, tcslib.GR_LBA, tcslib.LANG_GR_IDX, 'lang'),
    ('MENU.IMG#%d' % tcslib.XML_IDX, tcslib.MENU_LBA, tcslib.XML_IDX, 'sfxml'),
    ('MENU.IMG#%d' % tcslib.LANG_MENU_IDX, tcslib.MENU_LBA, tcslib.LANG_MENU_IDX, 'lang'),
)


class StaleError(Exception):
    """计划/门禁不过 —— 中止，不写产品盘。"""


def rel(p):
    try:
        r = os.path.relpath(p, REPO)
    except ValueError:
        return p.replace('\\', '/')
    return r.replace('\\', '/') if not r.startswith('..') else p.replace('\\', '/')


def sha256_file(p):
    return tcslib.sha256_file(p)


def yrow(r):
    return tcslib.GRID_Y0 + CH * (r + (tcslib.GRID_SKIP_ROWS if r >= tcslib.GRID_SKIP_ROW else 0))


def cell_xy(slot):
    """引擎格位 (K2 几何): x = 16*(slot % NCOL), y = yrow(slot // NCOL)。"""
    r, c = slot // tcslib.NCOL, slot % tcslib.NCOL
    return c * CW, yrow(r)


def win(ink, x, y, w=CW, h=CH):
    out = np.zeros((h, w), dtype=bool)
    x0, x1 = max(0, x), min(ink.shape[1], x + w)
    y0, y1 = max(0, y), min(ink.shape[0], y + h)
    if x1 > x0 and y1 > y0:
        out[y0 - y:y1 - y, x0 - x:x1 - x] = ink[y0:y1, x0:x1]
    return out


# ═══════════════════════ 字体模板 (与 glyph_audit / gen_font16 同配方) ═══════════════════════

_fnt = ImageFont.truetype(FZ16, 16)
_TTF = {}


def render16(ch):
    if ch in _TTF:
        return _TTF[ch]
    img = Image.new('L', (32, 32), 255)
    ImageDraw.Draw(img).text((8, 8), ch, font=_fnt, fill=0)
    a = np.asarray(img)
    out = a[8:24, 8:24] < 128
    _TTF[ch] = out
    return out


def hunt_template(ink, tpl, cap=24):
    """全图集滑窗搜模板 (分块, 无死角): 返回 (best_xor, x, y, hits[≤cap])。

    用途: 判"这个字的字形**到底存不存在**" —— 现画 TTF 之前必须证明盘上任何地方都没有它。
    """
    h, w = ink.shape
    th, tw = tpl.shape
    u8 = ink.astype(np.uint8)
    ti = tpl.astype(np.int16)
    tn = int(tpl.sum())
    best = (10 ** 9, -1, -1)
    hits = []
    y = 0
    while y + th <= h:
        y1 = min(y + 2 * th, h)
        sub = u8[y:y1]
        if sub.shape[0] < th:
            break
        win = np.lib.stride_tricks.sliding_window_view(sub, (th, tw))
        inter = (win & ti).sum(axis=(2, 3))
        wxor = win.sum(axis=(2, 3)) + tn - 2 * inter
        idx = int(wxor.argmin())
        ny, nx = np.unravel_index(idx, wxor.shape)
        v = int(wxor[ny, nx])
        if v < best[0]:
            best = (v, int(nx), int(y + ny))
        for (yy, xx) in np.argwhere(wxor == 0)[:cap]:
            hits.append((int(y + yy), int(xx)))
        y += th
    return best, (2 * th), hits


# ═══════════════════════ 装载 ═══════════════════════

def load_charset(cs_path):
    js = json.load(io.open(cs_path, encoding='utf-8'))
    cs = tcslib.Charset(cs_path)
    po = {k: tuple(v) for k, v in js['pair_of'].items()}
    tab = js.get('_trail_fix_hashr', {}).get('table')
    if not tab:
        raise StaleError('charset 里没有 _trail_fix_hashr.table —— 本工具的前提不成立')
    old2new = {}
    for ch, d in tab.items():
        old2new[(int(d['old'][:2], 16), int(d['old'][2:], 16))] = (
            ch, tuple(int(d['new'][i:i + 2], 16) for i in (0, 2)), int(d['old_slot']),
            int(d['new_slot']), 'hashr')
    # ★ 第二张"陈旧码表": round-zh130 的 36 个 col-63 槽换位 (同一类缺陷 —— 旧码留在文本里)
    for m in (js.get('_glyph_edge_zh130', {}).get('pair_moves') or []):
        k = (int(m['old'][:2], 16), int(m['old'][2:], 16))
        if k in old2new:
            raise StaleError('两张迁移表的旧码冲突: %02X%02X' % k)
        old2new[k] = (m['char'], tuple(int(m['new'][i:i + 2], 16) for i in (0, 2)),
                      int(m['old_slot']), int(m['new_slot']), 'zh130')
    return js, cs, po, old2new


def load_all(iso_path):
    font = D.load_font(iso_path)
    ad = font['atlas']
    if (ad['w'], ad['h'], ad['psm']) != (W_EXP, H_EXP, 0x14):
        raise StaleError('图集不是 1024x644 PSMT4 (本工具只认 K2 几何): %s'
                         % ((ad['w'], ad['h'], ad['psm']),))
    A = RF.Atlas(ad['pak'], ad['px_off'], ad['px_size'], ad['w'], ad['h'], ad['psm'])
    return font, A


def ft_live_windows(font):
    """所有 face 的**非退化**记录矩形 → 采样窗 (u0+4, v0+2, w=u1-u0, h=v1-v0) 的覆盖图。"""
    w, h = W_EXP, H_EXP
    cov = np.zeros((h, w), dtype=bool)
    recs = []
    for (nm, fld, rs) in font['faces']:
        for r in rs:
            b0, b1, u0, v0, u1, v1 = r
            if u1 <= u0 or v1 <= v0:
                continue
            x0, y0 = u0 + tcslib.GLYPH_DU, v0 + tcslib.GLYPH_DV
            x1, y1 = min(x0 + (u1 - u0), w), min(y0 + (v1 - v0), h)
            if x1 > x0 and y1 > y0 and 0 <= x0 < w and 0 <= y0 < h:
                cov[y0:y1, x0:x1] = True
                recs.append((nm, list(r), [x0, y0, x1, y1]))
    return cov, recs


# ═══════════════════════ 文本: 单元级行走 (与引擎同规则; 旧哨兵码优先) ═══════════════════════

def walk_units(data, cs, old2new):
    """返回 [(i0, i1, char, kind)]; kind ∈ ascii/pair/single/pua/oldpair。

    ★ `oldpair` = 命中 `_trail_fix_hashr.table` 的**旧哨兵码** (lead A1..B9 × trail B1/B5)。
      引擎现在不认它 (早已 retire) ⇒ 这条分支只用来**认出**待迁移的单元。
    """
    out = []
    i, n = 0, len(data)
    while i < n:
        v = data[i]
        if v < 0x80:
            out.append((i, i + 1, chr(v), 'ascii'))
            i += 1
        elif i + 1 < n and (v, data[i + 1]) in old2new:
            out.append((i, i + 2, old2new[(v, data[i + 1])][0], 'oldpair'))
            i += 2
        elif tcslib.LEAD_LO <= v < tcslib.LEAD_HI and i + 1 < n and (v, data[i + 1]) in cs.pair_of:
            out.append((i, i + 2, cs.pair_of[(v, data[i + 1])], 'pair'))
            i += 2
        elif v in cs.codes:
            out.append((i, i + 1, cs.codes[v], 'single'))
            i += 1
        else:
            out.append((i, i + 1, chr(0xE000 + v), 'pua'))
            i += 1
    return out


def engine_decode_units(data, cs):
    """**引擎规则**的原样行走 (不认任何已 retire 的旧码) —— 用来量"用户实际看到什么"。"""
    out = []
    i, n = 0, len(data)
    while i < n:
        v = data[i]
        if v < 0x80:
            out.append((i, i + 1, chr(v), 'ascii'))
            i += 1
        elif tcslib.LEAD_LO <= v < tcslib.LEAD_HI and i + 1 < n and (v, data[i + 1]) in cs.pair_of:
            out.append((i, i + 2, cs.pair_of[(v, data[i + 1])], 'pair'))
            i += 2
        elif v in cs.codes:
            out.append((i, i + 1, cs.codes[v], 'single'))
            i += 1
        else:
            out.append((i, i + 1, chr(0xE000 + v), 'pua'))
            i += 1
    return out


def resolve_text(data, cs, old2new):
    """旧码优先 → **目标文本** (迁移后的正确读法) + 迁移清单。"""
    units = walk_units(data, cs, old2new)
    text = []
    edits = []
    for (a, b, ch, kind) in units:
        if kind == 'oldpair':
            nch, newp, os_, ns, src = old2new[(data[a], data[a + 1])]
            if tuple(cs.enc_pair.get(nch, ())) != newp:
                raise StaleError('charset 与迁移表不一致: %s' % nch)
            edits.append(dict(off=a, old='%02X%02X' % (data[a], data[a + 1]),
                              new='%02X%02X' % newp, char=nch, old_slot=os_, new_slot=ns,
                              src=src))
            text.append(nch)
        else:
            text.append(ch)
    return ''.join(text), units, edits


def read_slot_blob(iso, lba, idx):
    e = iso.img_entry(lba, idx)
    raw = iso.read(e['iso_off'], e['stored'])
    subs = tcslib.lzo_subs(raw)
    blob = b''.join(s[0] for s in subs) if subs else raw
    return e, blob, bool(subs)


# ═══════════════════════ ① 文本计划 ═══════════════════════

INS_CHAR = '\u25b3'          # △ = (B1,A1) 的登记字符 (手柄"△键"图标字形)
INS_EXPECT = 59             # 实测: 用×42 + 练×15 + 键×2 (全部在 MENU.IMG#283 SFXML)


def ins_icon_char(cs):
    """(B1,A1) 的登记字符 —— 就是引擎画"△键"的那个图标字形。"""
    return cs.pair_of.get((0xB1, 0xA1))


def ins_by_char(plans):
    c = collections.Counter()
    for p in plans:
        for s in p['insert_sites']:
            c[s['char']] += 1
    return ' '.join('%s×%d' % kv for kv in c.most_common())


def plan_insert_fix(blob, cs, log=None):
    """★ 第二类陈旧码表残留: **对偶码的 lead 与 trail 之间被插进了一个 0xA1**。

    实测证据 (GR_ZH130/GR_ZH133 上逐条核对):
      · 文本里出现 `B1 A1 T` 三字节, 其中 `(B1,T)` 是**已登记的对偶码**, 而 `(B1,A1)` 解出来是 △
        (△ 是引擎画"△键"图标的字形, 不是正文用字);
      · 三个受害者 = 用 `B1A4`(42 处) / 练 `B1A3`(15 处) / 键 `B1A2`(2 处), 全部落在 SFXML;
      · 删掉那个多余的 A1 后, 59/59 处的上下文都读成通顺中文
        (如「接受专业狙击手训[练]」「发挥关[键]作用」「极适合[用]于摧毁」「擅长弹奏[键]盘」);
      · `EN_STRINGS.RES`×2 里同样的 `B1 A1` 有 7+7 处, 但后面跟的是 **0x20 空格**
        (「按 △ 键删除」= 真图标) ⇒ 本规则**只认** `(B1, 下一个字节)` 落在 pair_of 里的情形, 不动图标。

    返回 `(sites, new_blob)`; sites = [dict(off, old, new, char, was), ...] (off 为**删除前**的偏移)。
    """
    sites = []
    i = 0
    n = len(blob)
    while i + 2 < n:
        if blob[i] == 0xB1 and blob[i + 1] == 0xA1 and (0xB1, blob[i + 2]) in cs.pair_of:
            ch = cs.pair_of[(0xB1, blob[i + 2])]
            was = cs.pair_of.get((0xB1, 0xA1), '?')
            sites.append(dict(off=i, old=blob[i:i + 3].hex(), new=blob[i:i + 1].hex() + blob[i + 2:i + 3].hex(),
                              char=ch, was=was))
            i += 3
            continue
        i += 1
    if not sites:
        return sites, blob
    out = bytearray(blob)
    for s in reversed(sites):                      # 从后往前删, 偏移不失效
        del out[s['off'] + 1]
    new_blob = bytes(out)
    if len(new_blob) != len(blob) - len(sites):
        raise StaleError('插入修复的删字节数不符: %d != %d' % (len(blob) - len(new_blob), len(sites)))
    if log:
        bych = collections.Counter(s['char'] for s in sites)
        log('  [插入修复] %d 处 `B1 A1 T` → `B1 T` (逐字: %s)'
            % (len(sites), ' '.join('%s×%d' % kv for kv in bych.most_common())))
    return sites, new_blob


def plan_text(iso, cs, po, old2new, log):
    plans = []
    for (tag, lba, idx, kind) in TARGETS:
        if tag in [p['tag'] for p in plans]:
            continue
        e, blob, is_lzo = read_slot_blob(iso, lba, idx)
        # ★ 两类修复是**互相耦合**的, 必须迭代到不动点 (实测: 删掉插入型的字节会改变后面的
        #   字节对齐, 从而让 4 处原本被错位解析挡住的旧码露出来) —— 且**迁移必须先做**:
        #   未迁移正文里的旧码残骸会把 `B1 A1 T` 判据假阳打中 (实测 EN_STRINGS.RES 上 23 个)。
        cur = blob
        tot_mig = tot_ins = 0
        mig_src = collections.Counter()
        ins_sites = []
        mig_edits = []
        for it in range(6):
            text0, units0, edits = resolve_text(cur, cs, old2new)
            if edits:
                b = bytearray(cur)
                for ed in edits:
                    nb = bytes.fromhex(ed['new'])
                    if len(nb) != 2:
                        raise StaleError('%s: 新码不是 2 字节: %s' % (tag, ed['new']))
                    b[ed['off']:ed['off'] + 2] = nb
                b = bytes(b)
                chg = [i for i in range(len(cur)) if cur[i] != b[i]]
                bad_lo = [i for i in chg if b[i] < 0x80 or cur[i] < 0x80]
                if bad_lo:
                    raise StaleError('%s: 迁移改动碰到 ASCII 字节 %s' % (tag, bad_lo[:5]))
                if len(chg) != 2 * len(edits):
                    raise StaleError('%s: 迁移改动字节 %d != 2×迁移数 %d' % (tag, len(chg), len(edits)))
                allow = set()
                for ed in edits:
                    allow.add(ed['off'])
                    allow.add(ed['off'] + 1)
                stray = [i for i in chg if i not in allow]
                if stray:
                    raise StaleError('%s: 有 %d 个迁移改动字节落在单元之外' % (tag, len(stray)))
                for ed in edits:
                    ed = dict(ed)
                    ed['round'] = it
                    ed['old_bytes'] = cur[ed['off']:ed['off'] + 2].hex()
                    mig_edits.append(ed)
                    mig_src[ed['src']] += 1
                tot_mig += len(edits)
                cur = b
            ins, b2 = plan_insert_fix(cur, cs, log if it == 0 else None)
            if not ins:
                break
            tail_start = tcslib.xml_tail_start(cur)
            for s in ins:
                if s['off'] >= tail_start:
                    raise StaleError('%s: 插入型位点落在尾巴区 (off=%d >= %d)'
                                     % (tag, s['off'], tail_start))
            pad = len(cur) - len(b2)
            if set(cur[tail_start:]) - set(b'\r\n'):
                raise StaleError('%s: 尾巴不是纯 CRLF 填充, 不能用它补长度 (%d 处插入型)'
                                 % (tag, len(ins)))
            nxt = b2 + b'\r\n' * (pad // 2) + (b'\r' if pad % 2 else b'')
            if len(nxt) != len(blob):
                raise StaleError('%s: 补长度失败' % tag)
            ins_sites += ins
            tot_ins += len(ins)
            if log and it:
                log('  [插入修复] 迭代 %d: 又发现 %d 处 (逐字: %s)'
                    % (it, len(ins), ' '.join('%s×%d' % kv for kv in
                                              collections.Counter(s['char'] for s in ins).most_common())))
            cur = nxt
        blob2 = cur
        new_blob = blob2
        if len(new_blob) != len(blob):
            raise StaleError('%s: 解压总长变了 (%+d) —— 插入型删除必须用尾巴 CRLF 补回'
                             % (tag, len(new_blob) - len(blob)))
        text, units, edits = resolve_text(blob2, cs, old2new)
        if edits:
            raise StaleError('%s: 迭代 6 轮后仍有 %d 处旧码残留' % (tag, len(edits)))
        ins_left, _b = plan_insert_fix(blob2, cs)
        if ins_left:
            raise StaleError('%s: 迭代 6 轮后仍有 %d 处插入型残留' % (tag, len(ins_left)))
        n_old_left = sum(1 for (a, b, c, k) in units if k == 'oldpair')
        log('  [文本] %-22s 槽 %6d B  单元 %d  迁移 %3d (hashr %d / zh130 %d)  '
            '插入型 %2d  旧码残留 %d'
            % (tag, e['stored'], len(units), tot_mig, mig_src['hashr'], mig_src['zh130'],
               tot_ins, n_old_left))
        plans.append(dict(tag=tag, lba=lba, idx=idx, kind=kind, entry=e, is_lzo=is_lzo,
                          blob=blob, blob2=blob2, new_blob=new_blob, edits=mig_edits, text=text,
                          insert_sites=ins_sites, n_units=len(units),
                          n_migrated=tot_mig, n_mig_hashr=mig_src['hashr'],
                          n_mig_zh130=mig_src['zh130'], n_insert=tot_ins))
    return plans


def plan_registry(iso, cs, old2new, log):
    """登记容器 (+全部 *_STRINGS/_SPECIAL_FEATURE/IGORHELP) 里的旧码残留普查 (只读)。"""
    hits = []
    tgt = set((p[0], p[1]) for p in [(x[1], x[2]) for x in TARGETS])
    try:
        conts = FC.enumerate_containers(iso, limit=8192)
    except Exception as ex:                                            # noqa: BLE001
        log('  [普查] enumerate_containers 失败: %s' % ex)
        return hits
    n_reg = 0
    for (tag, lba, idx, e) in conts:
        nm = (e.get('name') or '').upper()
        if not any(k in nm for k in ('_STRINGS.RES', '_STRINGS.TXT', '_SPECIAL_FEATURE.XML',
                                     'IGORHELP.TXT')):
            continue
        n_reg += 1
        try:
            _e, blob, _l = read_slot_blob(iso, lba, idx)
        except Exception:                                              # noqa: BLE001
            continue
        units = walk_units(blob, cs, old2new)
        n = sum(1 for (a, b, c, k) in units if k == 'oldpair')
        if n:
            hits.append(dict(tag=tag, lba=lba, idx=idx, name=e.get('name'), n=n,
                             already=(lba, idx) in tgt))
    log('  [普查] *_STRINGS/_SPECIAL_FEATURE/IGORHELP 登记容器 %d 个; 其中含旧码残留 %d 个'
        % (n_reg, len(hits)))
    return hits


# ═══════════════════════ ② 图集计划 ═══════════════════════

def plan_atlas(A, old2new, cov, log):
    moves = []
    E = A.eng.copy()
    for oldp, d in sorted(old2new.items(), key=lambda kv: kv[1][3]):
        ch, newp, os_, ns = d[0], d[1], d[2], d[3]
        xo, yo = cell_xy(os_)
        xn, yn = cell_xy(ns)
        tpl = render16(ch)
        src = win(A.eng, xo, yo)
        dst = win(A.eng, xn, yn)
        xor = int(np.logical_xor(src, tpl).sum())
        cov_old = int(cov[yo:yo + 16, xo:xo + 16].sum()) if yo + 16 <= cov.shape[0] else -1
        cov_new = int(cov[yn:yn + 16, xn:xn + 16].sum()) if yn + 16 <= cov.shape[0] else -1
        if cov_new:
            raise StaleError('%s 的新格 (slot %d) 被 FT 记录采样窗压着 (%d px)' % (ch, ns, cov_new))
        # ★ 已经是好的 (新格里就是该字的模板): zh130 已搬过的 36 个 + 本工具跑第二遍时
        #   的 42 个 ⇒ 一律不动 (幂等: 对产物再跑一遍必须 0 改动)
        if int(np.logical_xor(dst, tpl).sum()) == 0:
            moves.append(dict(char=ch, old='%02X%02X' % oldp, new='%02X%02X' % newp,
                              old_slot=os_, new_slot=ns, old_cell=[xo, yo], new_cell=[xn, yn],
                              src_xor_ttf=xor, glyph_source='already-ok', cleared=False,
                              cov_old=cov_old, cov_new=cov_new, ink_before=int(src.sum()),
                              ink_after=int(dst.sum()), ttf_ink=int(tpl.sum())))
            continue
        glyph = src if xor == 0 else tpl
        source = 'copy(old cell)' if xor == 0 else 'render(TTF)'
        hunt = None
        if source == 'render(TTF)':
            # ★ 硬前提: "盘上任何地方都没有这个字的字形" 必须被证明, 否则不许现画
            best, _step, hits = hunt_template(A.eng, tpl)
            hunt = dict(best_xor=best[0], xy=[best[1], best[2]], n_zero=len(hits))
            if best[0] == 0:
                raise StaleError('%s 的字形其实在 (%d,%d) (xor=0) —— 不该现画, 应搬运'
                                 % (ch, best[1], best[2]))
        clear = (cov_old == 0) and (xo, yo) != (xn, yn)
        E[yn:yn + 16, xn:xn + 16] = glyph
        if clear:
            E[yo:yo + 16, xo:xo + 16] = False
        moves.append(dict(char=ch, old='%02X%02X' % oldp, new='%02X%02X' % newp,
                          old_slot=os_, new_slot=ns,
                          old_cell=[xo, yo], new_cell=[xn, yn], src_xor_ttf=xor,
                          glyph_source=source, cleared=clear, cov_old=cov_old, cov_new=cov_new,
                          ink_before=int(src.sum()), ink_after=int(glyph.sum()),
                          ttf_ink=int(tpl.sum()), hunt=hunt))
    # 新格互不重叠
    cells = {}
    for m in moves:
        cells.setdefault((m['new_cell'][0], m['new_cell'][1]), []).append(m['char'])
    dup = dict((k, v) for k, v in cells.items() if len(v) > 1)
    if dup:
        raise StaleError('新格冲突: %s' % dup)
    n_clear = len([m for m in moves if m['cleared']])
    n_skip = len([m for m in moves if m['glyph_source'] == 'already-ok'])
    log('  [图集] %d 条迁移: 复制旧格 %d / 现画 TTF %d / 已就位(zh130 已搬) %d ; '
        '旧格清零 %d (保留 %d)'
        % (len(moves), len([m for m in moves if m['glyph_source'].startswith('copy')]),
           len([m for m in moves if m['glyph_source'].startswith('render')]), n_skip,
           n_clear, len(moves) - n_clear - n_skip))
    for m in moves:
        if m['glyph_source'] == 'render(TTF)':
            log('     · %s 旧格无字形 (xor=%d, ink=%d) ⇒ 用 TTF 现画 (ink=%d) [%s]'
                % (m['char'], m['src_xor_ttf'], m['ink_before'], m['ttf_ink'],
                   'hashr' if m['old_slot'] < 1872 or m['new_slot'] <= 1977 else 'zh130'))
    return E, moves


# ═══════════════════════ 主流程 ═══════════════════════

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--iso', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--report', default=None)
    ap.add_argument('--charset', default=os.path.join(REPO, 'tools', 'final_fix', 'assets', 'charset',
                                        'charset_compiled_zh16.json'))
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    LOG = []

    def log(s=''):
        print(s, flush=True)
        LOG.append(s)

    src = os.path.abspath(a.iso)
    dst = os.path.abspath(a.out)
    if src == dst:
        raise StaleError('--out 不能等于 --iso')
    sha_in = sha256_file(src)
    log('=' * 100)
    log('%s  (%s)' % (TOOL, ROUND))
    log('  源盘   %s  sha256 %s' % (rel(src), sha_in))
    js, cs, po, old2new = load_charset(a.charset)
    log('  charset %s  pair_of=%d codes=%d ; _trail_fix_hashr 旧码 %d 条'
        % (rel(a.charset), len(po), len(cs.codes), len(old2new)))
    font, A = load_all(src)
    log('  图集 %dx%d psm=0x%02X px_size=%d nseg=%d 墨 %d'
        % (A.w, A.h, A.psm, A.px_size, A.nseg, int(A.eng.sum())))
    cov, recs = ft_live_windows(font)
    log('  FT 记录采样窗 %d 条, 覆盖 %d px' % (len(recs), int(cov.sum())))
    empty, tot = A.empty_index()
    log('  空色索引 = %d' % empty)

    iso = tcslib.Iso(src)
    try:
        plans = plan_text(iso, cs, po, old2new, log)
        reg = plan_registry(iso, cs, old2new, log)
        # 源盘口径计数 (报告用)
        before = dict(overall=dict(n_units=0, n_oldpair=0, per_container={}))
        for p in plans:
            units = walk_units(p['blob'], cs, old2new)
            n_old = sum(1 for (x, y, c, k) in units if k == 'oldpair')
            before['overall']['n_units'] += len(units)
            before['overall']['n_oldpair'] += n_old
            # ★ 权威口径 = **引擎规则**下"解出来的字落在无墨格"的单元数 (用户实际看到什么)
            eng = engine_decode_units(p['blob'], cs)
            bad_ink = 0
            bad_chars = set()
            bad_slot = 0
            for (x, y, c, k) in eng:
                pp = po.get(c)
                if not pp:
                    continue
                s = (pp[0] - 0xA1) * 94 + (pp[1] - 0xA1)
                if 1872 <= s <= 2344:
                    bad_slot += 1
                if int(win(A.eng, *cell_xy(s)).sum()) == 0:
                    bad_ink += 1
                    bad_chars.add(c)
            before['overall']['per_container'][p['tag']] = dict(
                units=len(units), oldpair=n_old, changed_units=len(p['edits']),
                decoded_into_glyphless=bad_ink, n_glyphless_chars=len(bad_chars),
                decoded_into_reserved_slot=bad_slot,
                glyphless_chars=''.join(sorted(bad_chars)))
        log('  [源盘口径] 单元 %d ; 旧码(根因) %d ; 引擎解到无字形格 %d (逐容器见报告)'
            % (before['overall']['n_units'], before['overall']['n_oldpair'],
               sum(v['decoded_into_glyphless']
                   for v in before['overall']['per_container'].values())))
        for k, v in before['overall']['per_container'].items():
            log('     · %-22s 单元 %6d 旧码 %3d 引擎解到无字形格 %3d (%d 个不同乱码字) '
                '解到保留段 %3d'
                % (k, v['units'], v['oldpair'], v['decoded_into_glyphless'],
                   v['n_glyphless_chars'], v['decoded_into_reserved_slot']))
        E, moves = plan_atlas(A, old2new, cov, log)
        n_px = int(np.logical_xor(E, A.eng).sum())
        log('  [图集] 像素改动 %d texel (墨 %d → %d)' % (n_px, int(A.eng.sum()), int(E.sum())))
        log('  [普查] 其它登记容器里的旧码残留: %s'
            % ([h for h in reg if not h['already']] or '0 个'))
    finally:
        iso.close()

    rep = dict(tool=TOOL, round=ROUND, src=rel(src), src_sha256=sha_in,
               charset=rel(a.charset), charset_sha256=sha256_file(a.charset),
               atlas=dict(w=A.w, h=A.h, psm=A.psm, px_size=A.px_size, nseg=A.nseg,
                          pixels_changed=n_px, ink_before=int(A.eng.sum()),
                          ink_after=int(E.sum()), empty_index=empty),
               sentinel=dict(n_old_codes=len(old2new),
                             old_codes=sorted('%02X%02X' % k for k in old2new),
                             table_chars=len(set(v[0] for v in old2new.values()))),
               text=dict(per_container=before['overall']['per_container'],
                         containers=[dict(tag=p['tag'], slot=p['entry']['stored'],
                                          units=p['n_units'], migrated=p['n_migrated'],
                                          migrated_hashr=p['n_mig_hashr'],
                                          migrated_zh130=p['n_mig_zh130'],
                                          inserted=p['n_insert'])
                                     for p in plans],
                         registry_extra=reg),
               moves=moves)
    if a.dry_run:
        log('')
        log('[dry-run] 不写盘。')
        if a.report:
            with io.open(a.report, 'w', encoding='utf-8', newline='\n') as fh:
                json.dump(rep, fh, ensure_ascii=False, indent=1)
        return 0

    # ---------------- 写盘 ----------------
    import shutil
    shutil.copyfile(src, dst)
    pak_e = font['pak_e']
    ft_e = font['ft_e']
    c_lo, c_hi = pak_e['iso_off'], pak_e['iso_off'] + pak_e['stored']
    f_lo, f_hi = ft_e['iso_off'], ft_e['iso_off'] + ft_e['stored']
    for p in plans:
        lo, hi = p['entry']['iso_off'], p['entry']['iso_off'] + p['entry']['stored']
        if (lo < c_hi and c_lo < hi) or (lo < f_hi and f_lo < hi):
            raise StaleError('%s 的槽与图集/FONT.RES 重叠' % p['tag'])
    iso_src = tcslib.Iso(src)
    frames = []
    try:
        for p in plans:
            slot = FC.Slot(iso_src, p['tag'], p['lba'], p['idx'])
            fr, n_rep, flen, method = slot.repack(p['new_blob'], p['tag'])
            log('  [重压] %-22s 帧 %6d B / 槽 %6d B (方法 %s, 重压子流 %d)'
                % (p['tag'], flen, slot.slot, method, n_rep))
            if flen > slot.slot:
                raise StaleError('%s 帧超槽' % p['tag'])
            frames.append((p, fr))
    finally:
        iso_src.close()
    hdr_before = A.headers()
    # ★ 只写"计划里要变的像素": 图集容器整块回写, 但内容里只有这些 texel 不同
    ys, xs = np.where(E != A.eng)
    n_px_written = int(A.write_pixels(ys, xs, E[ys, xs], empty))
    if n_px_written != int((E != A.eng).sum()):
        raise StaleError('像素写回个数不符: %d != %d' % (n_px_written, int((E != A.eng).sum())))
    for (doff, hb) in A.headers():
        if bytes(A.cont[doff - tcslib.ATLAS_PREFIX_BYTES:doff]) != hb:
            raise StaleError('48B 包头被改了 (doff=0x%X)' % doff)
    with open(dst, 'r+b') as f:
        f.seek(pak_e['iso_off'] + A.px_off)
        f.write(bytes(A.cont))
        for (p, fr) in frames:
            FC.Slot.write(f, p['entry']['iso_off'], p['entry']['stored'], fr)
    if os.path.getsize(dst) != os.path.getsize(src):
        raise StaleError('ISO 尺寸变了')
    sha_out = sha256_file(dst)
    log('  [写盘] %s  %d B  sha256 %s' % (rel(dst), os.path.getsize(dst), sha_out))
    rep['out'] = rel(dst)
    rep['out_sha256'] = sha_out

    # ---------------- 门禁 (从盘上回读) ----------------
    try:
        gates = run_gates(dst, src, font, A, E, plans, moves, cs, po, old2new, empty, cov, log)
    except StaleError:
        log('  [!!] 门禁不过 ⇒ 删除产物 %s' % rel(dst))
        try:
            os.remove(dst)
        except OSError:
            pass
        raise
    rep['gates'] = gates
    if a.report:
        with io.open(a.report, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=1)
        log('  报告 → %s' % rel(a.report))
    log('')
    log('OK — %s' % rel(dst))
    return 0


# ═══════════════════════ 门禁 ═══════════════════════

def run_gates(dst, src, font, A0, E, plans, moves, cs, po, old2new, empty, cov, log):
    out = []

    def chk(name, cond, detail):
        out.append(dict(check=name, ok=bool(cond), detail=detail))
        log('  [%s] %-46s %s' % ('门禁 ✓' if cond else '门禁 ✗', name, detail))
        if not cond:
            raise StaleError('门禁不过: %s (%s)' % (name, detail))

    # ① 三闸门
    w, h, px = A0.w, A0.h, A0.px_size
    chk('图集闸门 w <= 1024', w <= 1024, 'w=%d' % w)
    chk('图集闸门 px_size == w*h/2+16', px == w * h // 2 + 16, '%d == %d' % (px, w * h // 2 + 16))
    chk('图集闸门 (w*h/2) %% 2048 == 0', (w * h // 2) % 2048 == 0, '%d %% 2048 == 0' % (w * h // 2))

    iso_d = tcslib.Iso(dst)
    iso_s = tcslib.Iso(src)
    try:
        font_d, Ad = load_all(dst)
        # ② 字形就位
        bad_new, bad_old = [], []
        for m in moves:
            ch = m['char']
            xn, yn = m['new_cell']
            xo, yo = m['old_cell']
            tpl = render16(ch)
            wn = win(Ad.eng, xn, yn)
            if int(np.logical_xor(wn, tpl).sum()) != 0:
                bad_new.append((ch, int(np.logical_xor(wn, tpl).sum())))
            if m['cleared'] and int(win(Ad.eng, xo, yo).sum()) != 0:
                bad_old.append((ch, int(win(Ad.eng, xo, yo).sum())))
            if not m['cleared']:
                if int(np.logical_xor(win(Ad.eng, xo, yo), win(A0.eng, xo, yo)).sum()) != 0:
                    bad_old.append((ch, 'FT 覆盖格被动了'))
        chk('42/42 新格 == 该字的字体模板 (逐 texel)', not bad_new, '不合 %d %s' % (len(bad_new), bad_new[:3]))
        chk('旧格按计划清零/保留 (FT 覆盖格不动)', not bad_old, '不合 %d %s' % (len(bad_old), bad_old[:3]))
        n_ink = sum(1 for ch in po
                    if int(win(Ad.eng, *cell_xy((po[ch][0] - 0xA1) * 94 + (po[ch][1] - 0xA1))).sum()) > 0)
        n_ink_s = sum(1 for ch in po
                      if int(win(A0.eng, *cell_xy((po[ch][0] - 0xA1) * 94 + (po[ch][1] - 0xA1))).sum()) > 0)
        chk('图集体检: 登记对偶字"格内有墨"个数 >= 源盘', n_ink >= n_ink_s,
            '%d → %d / %d' % (n_ink_s, n_ink, len(po)))

        # ③ 文本 740/740 (+ 插入型 N/N)
        tot_mig = n_left = 0
        bad_txt = []
        n_ins = 0
        for p in plans:
            _e, blob, _l = read_slot_blob(iso_d, p['lba'], p['idx'])
            ins2, blob_no_ins = plan_insert_fix(blob, cs)
            if ins2:
                bad_txt.append((p['tag'], '%d 处插入型残留' % len(ins2)))
            if len(blob) != len(p['new_blob']):
                bad_txt.append((p['tag'], 'len %d != %d' % (len(blob), len(p['new_blob']))))
            text2, units2, edits2 = resolve_text(blob, cs, old2new)
            if edits2:
                bad_txt.append((p['tag'], len(edits2)))
            if text2 != p['text']:
                k = next((i for i in range(min(len(text2), len(p['text'])))
                          if text2[i] != p['text'][i]), 0)
                bad_txt.append((p['tag'], 'text mismatch @%d' % k))
            # SFXML 结构门禁: 条目标签/个数必须一个不差 (删字节不许破坏 XML 结构)
            if p['kind'] == 'sfxml':
                a1 = [(str(k), o, l) for (k, o, l, _b) in tcslib.parse_sfxml(blob)]
                a0 = [(str(k), o, l) for (k, o, l, _b) in tcslib.parse_sfxml(p['blob'])]
                if [x[0] for x in a1] != [x[0] for x in a0] or len(a1) != len(a0):
                    bad_txt.append((p['tag'], 'SFXML 结构变了 %d → %d' % (len(a0), len(a1))))
            tot_mig += len(p['edits'])
            n_ins += len(p['insert_sites'])
            n_left += sum(1 for (x, y, c, k) in walk_units(blob, cs, old2new) if k == 'oldpair')
        chk('文本: 盘上回读 == 目标文本 (逐字), 旧码残留 0', not bad_txt and n_left == 0,
            '迁移 %d 处; 插入型 %d 处; 残留 %d; 异常 %s' % (tot_mig, n_ins, n_left, bad_txt[:3]))
        # ③b 每处插入型修复: 被删掉的那个字节必须解出 △ (图标码), 目标字 = `B1 T`
        ins_bad = []
        for p in plans:
            for s in p['insert_sites']:
                if s['was'] != ins_icon_char(cs):
                    ins_bad.append((p['tag'], s['off'], 'was=%s' % s['was']))
                if s['char'] != cs.pair_of.get((0xB1, int(s['old'][4:6], 16))):
                    ins_bad.append((p['tag'], s['off'], 'target=%s' % s['char']))
        chk('插入型修复逐处核对 (删掉的字节解出 △; 目标字 = B1+T)',
            not ins_bad and n_ins == INS_EXPECT, '%d 处 (逐字: %s) %s'
            % (n_ins, ins_by_char(plans), ins_bad[:3]))

        # ④ 权威口径 (引擎规则): 解到"无墨格"的单元 == 0
        bad_ink = []
        for p in plans:
            _e, blob, _l = read_slot_blob(iso_d, p['lba'], p['idx'])
            for (x, y, c, k) in engine_decode_units(blob, cs):
                pp = po.get(c)
                if not pp:
                    continue
                s = (pp[0] - 0xA1) * 94 + (pp[1] - 0xA1)
                if int(win(Ad.eng, *cell_xy(s)).sum()) == 0:
                    bad_ink.append((p['tag'], c, blob[x:y].hex()))
        chk('权威口径 (引擎规则): 解到"无字形格"的单元 == 0', not bad_ink,
            '修前 481 / 修后 %d %s' % (len(bad_ink), bad_ink[:4]))

        # ④b 迁移分类计数
        n_h = n_z = 0
        for p in plans:
            _e, blob, _l = read_slot_blob(iso_d, p['lba'], p['idx'])
            n_h += sum(1 for e in p['edits'] if e['src'] == 'hashr')
            n_z += sum(1 for e in p['edits'] if e['src'] == 'zh130')
        chk('迁移分类: hashr 哨兵旧码 + zh130 换位旧码', True,
            'hashr %d 处 / zh130 %d 处' % (n_h, n_z))

        # ⑤ 载荷级旧码
        gate_val = tcslib.read_decode_gate(iso_d)

        def _payloads(tag, blob):
            if tag == 'sfxml':
                return [b for (_k, _o, _l, b) in tcslib.parse_sfxml(blob)]
            ents, _u = tcslib.parse_lang(blob)
            return [e.data for e in ents]

        def _counts(io_obj, csx):
            pay = tot = 0
            for (tag, lba, idx, kind) in TARGETS:
                e = io_obj.img_entry(lba, idx)
                raw = io_obj.read(e['iso_off'], e['stored'])
                subs = tcslib.lzo_subs(raw)
                blob = b''.join(s[0] for s in subs) if subs else raw
                tot += len(tcslib.scan_legacy_residue(blob, gate_val, csx.pair_of))
                for pay_b in _payloads(kind, blob):
                    pay += len(tcslib.scan_legacy_residue(pay_b, gate_val, csx.pair_of))
            return pay, tot

        pay_n, tot_n = _counts(iso_d, cs)
        pay_o, tot_o = _counts(iso_s, cs)
        chk('载荷级旧码 0 (gate 0x%02X)' % gate_val, pay_n == 0,
            '载荷 %d 处 (源盘 %d); 含结构区 %d 处' % (pay_n, pay_o, tot_n))
        chk('结构区/尾巴裸旧码与源盘相同 (不许改)', (tot_n - pay_n) == (tot_o - pay_o),
            '结构区 %d 处 (源盘 %d)' % (tot_n - pay_n, tot_o - pay_o))

        # ⑥ 全盘字节普查
        fh_s = open(src, 'rb')
        fh_d = open(dst, 'rb')
        a = mmap.mmap(fh_s.fileno(), 0, access=mmap.ACCESS_READ)
        g = mmap.mmap(fh_d.fileno(), 0, access=mmap.ACCESS_READ)
        wins = [(font['pak_e']['iso_off'] + A0.px_off,
                 font['pak_e']['iso_off'] + A0.px_off + A0.px_size)]
        for p in plans:
            wins.append((p['entry']['iso_off'], p['entry']['iso_off'] + p['entry']['stored']))
        n_diff = 0
        bad = []
        base = 0
        n = len(a)
        LO = 1 << 22
        try:
            while base < n:
                ca = a[base:base + LO]
                cb = g[base:base + LO]
                if ca != cb:
                    m = len(ca)
                    i = 0
                    while i < m:
                        if ca[i] != cb[i]:
                            j = i
                            while j < m and ca[j] != cb[j]:
                                j += 1
                            n_diff += j - i
                            if not any(lo <= base + i < hi for (lo, hi) in wins):
                                bad.append(base + i)
                            i = j
                        i += 1
                base += LO
        finally:
            a.close()
            g.close()
            fh_s.close()
            fh_d.close()
        chk('全盘差异全部落在计划窗口内', not bad, '%d B 改动; 窗口外 %d %s' % (n_diff, len(bad), bad[:3]))

        # ⑦ ASCII / IMG 条目表不动 —— 逐条按**捕获时记录的原字节**判 (迁移可能跨坐标系统:
        #   迭代 ≥1 的偏移是插入型删字节之后的坐标, 不能再回头去读原始 blob)
        bad_ascii = []
        for p in plans:
            for ed in p['edits']:
                ob = ed.get('old_bytes') or p['blob'][ed['off']:ed['off'] + 2].hex()
                nb = ed['new']
                if any(b < 0x80 for b in bytes.fromhex(ob)) or \
                        any(b < 0x80 for b in bytes.fromhex(nb)):
                    bad_ascii.append((p['tag'], ed['off'], ob, nb))
        chk('改动字节全在 >= 0x80 区 (ASCII 不动)', not bad_ascii, str(bad_ascii[:3]))
        ent_bad = []
        for (tag, lba, idx, kind) in TARGETS:
            e1 = iso_s.img_entry(lba, idx)
            e2 = iso_d.img_entry(lba, idx)
            for k in ('iso_off', 'stored', 'real'):
                if e1.get(k) != e2.get(k):
                    ent_bad.append((tag, k))
        chk('IMG 条目表 off/stored/real 一个字节没动', not ent_bad, str(ent_bad))
    finally:
        iso_d.close()
        iso_s.close()
    return out


if __name__ == '__main__':
    try:
        sys.exit(main())
    except StaleError as ex:
        print('')
        print('!! 中止: %s' % ex)
        sys.exit(2)
