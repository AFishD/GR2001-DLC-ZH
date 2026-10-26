# -*- coding: utf-8 -*-
r"""repack_font.py — **字库紧凑重排** (round46): 把在用字形压到最前面, 未使用区域全部置零。

## 这个工具解决什么

盘上的汉字字形躺在图集 (COMMON.PAK `new_font_revised`) 的 16x16 格子里。
1504 个对偶槽 (slot) 里, **不是每个格子都能用**:

  · 有些格整格归**单字节记录码**所有 (FT 记录矩形就压在那);
  · 有些格被**手柄图标码**的小矩形压着一角 (滚动箭头 △/✕);
  · 有些格被别的 face 的 FT 记录矩形盖住。

而历史各轮往里写字形时, 槽位是"哪有空就塞哪", 于是:

  · 真正的空白可用格被冲得七零八落 (GR_ZH94: 未占用 185 格, 其中格是白的只有 42 格);
  · 一堆"退役"字形残留在没人用的格子里 (看着白, 其实有墨 ⇒ 不能用)。

本工具每轮构筑**自动**做一件事: 把**当前在用的全部字形**按**确定性顺序**紧凑重排到
最前面的可用格上, 其余可用格一律清零 ⇒

  · 重排后"格是白的、可以直接写新字"的位置 = **可用格总数 − 在用字数** (这就是真正的上限);
  · 未使用区域的残留墨被清掉 (顺带治"某字被别的图案污染"这类问题);
  · 幂等: 同一张盘跑第二次 = **0 改动**, 不写盘、不改 charset、产物 sha256 不变。

## 引擎口径 (round45 定稿, 全部走 tcslib, 不重新逆向)

  · 对偶码采样窗: `slot=(lead-0xA1)*94+(trail-0xA1); row=slot//62; col=slot%62;
    x=16*col; y=2+16*(row+3*[row>=12])`  ← **无相位** (`tcslib.atlas_cell_xy_engine_view`);
  · 像素容器是 **GIF 封包流** (现役 8 段 × [PT 16B][A+D TRXPOS 16B][IMAGE tag 16B] + 数据),
    读写一律走 `tcslib.atlas_container_segments()` 算出的**数据区字节偏移**,
    **绝不按裸图偏移**、**绝不碰 48B 包头**;
  · 单字节/ASCII 走 `FONT.RES` 的 FT 记录矩形 ⇒ 这些矩形覆盖的像素**一个都不能动**。

## 用法

  # 只算不写 (看现在能压出多少空位)
  python tools/iso_build/repack_font.py --iso work/builds/GR_ZH94/GR_ZH94.iso --dry-run

  # 真重排: 出新盘 + 改 charset + 另出"强制重编码"文本表
  python tools/iso_build/repack_font.py --iso <src.iso> --out-iso <dst.iso> \
      --text-src work/builds/GR_ZH94/text --reencode-out <out>/temp/font_repack/reencode \
      --report <out>/temp/font_repack/repack_report.json

  # 幂等复核 (对已重排过的盘再跑): 应报"无需重排", 且**不产出任何文件**
  python tools/iso_build/repack_font.py --iso <dst.iso> --out-iso <tmp.iso> --dry-run

★ 被 make_build.py 当作构筑的一等步骤自动调用 (文本注入**之前**), 见 `--no-font-repack`。

## ⚠ 人工单跑的前提：charset JSON 必须与这张盘**同一版本**

重排按 `charset` 给的"当前槽位"去图集里取字形。如果 charset 是别的版本的映射
（比如手工换过、或某次构筑半途失败没回滚），取到的就是**别的格子的像素** ⇒ 会把整盘字写乱。
`plan()` 里有一道"大面积取空就拒绝"的粗探针，但**两版图集都很满时它看不出来** ——
所以人工单跑时请务必确认 charset 与盘同版本（构筑器每次都会把重排前的 charset
备份到 `<版本>/temp/font_repack/charset_before.json`）。
在构筑管线里这件事是自动保证的：charset 与盘同进同退，注入失败会**回滚 charset**。
`charset['_font_repack']['iso_sha256']` 记着"这份 charset 是给哪张盘写的"，可用于排查。
"""
import argparse
import csv
import hashlib
import io
import json
import os
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

NCOL, CW, CH = tcslib.NCOL, tcslib.CW, tcslib.CH
ROUND = 'round46'
TOOL_VERSION = 'r46.2'
# 确定性顺序: 先按**当前槽位**升序 (= 图集行主序, 保持相邻字相邻), 再按字符码点
ORDER_KEY = 'current_slot_asc'

# ═══════════════ 几何: ★ 以**盘上 ELF 立即数**为准 (2026-10-20 fix/font 订正) ═══════════════
#   ⚠ 历史缺陷: 上面那行是 **import 时**的快照。旧 tcslib 里是 62 列 / Y0=2 / SKIP=3 的
#     FA2400 配方 ⇒ 本模块算出的格位**全是错的**, 而调用方(构筑器)看不出来 (格位错了只会
#     把字形搬到别的格)。现在两道保险:
#       ① tcslib 的常量已订正为 K2 (64/3/2), 所以 import 快照本身是对的;
#       ② 真正用到格位之前一律走 `sync_geometry_from_iso()`: 它**从盘上 ELF 立即数重读**
#          (VA 0x4170AC / 0x4170E8 / 0x4170F8), 与当前值不符就**以盘为准**进程内覆写 + 打日志,
#          最后断言模块级 NCOL/CW/CH 与盘一致 —— 以后几何再变, 这里不会再静默错位。
ELF_GRID_IMM = (('NCOL', 0x4170AC), ('SKIP_ROWS', 0x4170E8), ('Y0', 0x4170F8))


def read_elf_grid(iso_path):
    """只读: 从盘上 ELF 立即数读 (NCOL, SKIP_ROWS, Y0)。几何的唯一真源。"""
    iso = tcslib.Iso(iso_path)
    try:
        out = {}
        for name, va in ELF_GRID_IMM:
            off = tcslib.ELF_ISO_BASE + va - tcslib.ELF_VA_BASE
            out[name] = struct.unpack_from('<I', iso.mm, off)[0] & 0xFFFF
        return out
    finally:
        iso.close()


def sync_geometry_from_iso(iso_path, verbose=True):
    """把模块级 NCOL/CW/CH 与 tcslib 的网格常量同步到**盘上 ELF 立即数**。

    返回 dict(NCOL, SKIP_ROWS, Y0, source)。盘与 tcslib 不一致时以**盘**为准 (并大声打印),
    最后 `assert` 三者一致 —— 宁可直接失败, 也不要按错的格位搬字。
    """
    global NCOL, CW, CH
    g = read_elf_grid(iso_path)
    cur = (tcslib.NCOL, tcslib.GRID_Y0, tcslib.GRID_SKIP_ROWS)
    want = (g['NCOL'], g['Y0'], g['SKIP_ROWS'])
    if cur != want:
        if verbose:
            print('  [geom] ★ 盘上 ELF 立即数 = NCOL=%d Y0=%d SKIP_ROWS=%d, 而 tcslib 是 '
                  'NCOL=%d Y0=%d SKIP_ROWS=%d ⇒ **以盘为准**进程内覆写 (不改源文件)'
                  % (want + cur), flush=True)
        tcslib.NCOL, tcslib.GRID_Y0, tcslib.GRID_SKIP_ROWS = want
    NCOL, CW, CH = tcslib.NCOL, tcslib.CW, tcslib.CH
    assert (NCOL, CW, CH) == (g['NCOL'], tcslib.CW, tcslib.CH), \
        'repack_font: NCOL=%r 与盘上 ELF 立即数 %r 不一致' % (NCOL, g['NCOL'])
    assert (tcslib.GRID_Y0, tcslib.GRID_SKIP_ROWS) == (g['Y0'], g['SKIP_ROWS']), \
        'repack_font: yrow 常量与盘上 ELF 不一致 (Y0=%r, SKIP_ROWS=%r)' \
        % (tcslib.GRID_Y0, tcslib.GRID_SKIP_ROWS)
    if verbose:
        print('  [geom] NCOL=%d CW=%d CH=%d Y0=%d SKIP_ROW=%d SKIP_ROWS=%d (ELF 0x4170AC/E8/F8 实测)'
              % (NCOL, CW, CH, tcslib.GRID_Y0, tcslib.GRID_SKIP_ROW, tcslib.GRID_SKIP_ROWS), flush=True)
    return dict(g, source='ELF imm 0x4170AC/0x4170E8/0x4170F8',
                yrow='y(r)=%d+%d*(r+%d*[r>=%d])' % (tcslib.GRID_Y0, CH, tcslib.GRID_SKIP_ROWS,
                                                    tcslib.GRID_SKIP_ROW))


def rel(p):
    try:
        r = os.path.relpath(p, REPO)
    except ValueError:
        return p.replace('\\', '/')
    return r.replace('\\', '/') if not r.startswith('..') else p.replace('\\', '/')


def sha256_b(b):
    return hashlib.sha256(b).hexdigest()


def _load_charset_json(path):
    """只读读一次 charset JSON (取 `_font_repack` 元信息用; 读失败就当没有)。"""
    try:
        return json.load(io.open(path, encoding='utf-8'))
    except Exception:                                                # noqa: BLE001
        return {}


def yrow(r):
    """网格行 → 引擎 y (与 tcslib.atlas_cell_xy_engine_view 同一算式)。"""
    return tcslib.GRID_Y0 + CH * (r + (tcslib.GRID_SKIP_ROWS if r >= tcslib.GRID_SKIP_ROW else 0))


# ═══════════════════════ 图集容器 (GIF 封包流) 读写 ═══════════════════════

class Atlas:
    """`new_font_revised` 的像素容器: 引擎图 ↔ 容器字节 (带 GIF 包头偏移)。

    · `self.cont`  = 容器**原始字节** (含 8×48B 包头; 写盘时整块回写)
    · `self.segs`  = `tcslib.atlas_container_segments()` 的结果 [(首行, 数据偏移, 字节数)]
    · `self.eng`   = 引擎真正看到的图 (H×W bool, True=墨)
    """

    def __init__(self, pak_bytes, px_off, px_size, w, h, psm):
        self.w, self.h, self.psm = w, h, psm
        self.px_off, self.px_size = px_off, px_size
        self.cont = bytearray(pak_bytes[px_off:px_off + px_size])
        self.stride = w // 2 if psm == 0x14 else w
        self.segs = tcslib.atlas_container_segments(bytes(self.cont), self.stride)
        if not self.segs:
            raise SystemExit('!! 认不出像素容器的 GIF 封包分段 —— 拒绝按裸图偏移读写')
        self.nseg = len(self.segs)
        self.eng = self.decode()

    # ---- 解码: 按封包把每段数据放回 TRXPOS 指定的行 ----
    def decode(self):
        img = np.zeros((self.h, self.w), dtype=bool)
        for (first_row, doff, nbytes) in self.segs:
            nrow = min(nbytes // self.stride, self.h - first_row)
            if nrow <= 0:
                continue
            a = np.frombuffer(bytes(self.cont[doff:doff + nrow * self.stride]),
                              dtype=np.uint8).reshape(nrow, self.stride)
            img[first_row:first_row + nrow, 0::2] = (a & 0x0F) == 0
            img[first_row:first_row + nrow, 1::2] = (a >> 4) == 0
        return img

    def locate(self, y):
        """引擎行 y 落在哪个段: 返回 (first_row, doff, nbytes) 或 None。"""
        best = None
        for (fr, doff, nbytes) in self.segs:
            if fr <= y < fr + nbytes // self.stride and (best is None or fr > best[0]):
                best = (fr, doff, nbytes)
        return best

    def empty_index(self):
        """「空」用的调色板索引 = 容器里出现最多的非 0 nibble (= 背景色)。"""
        nb = np.frombuffer(bytes(self.cont), dtype=np.uint8)
        tot = np.bincount(nb & 0x0F, minlength=16) + np.bincount(nb >> 4, minlength=16)
        tot[0] = 0
        v = int(np.argmax(tot))
        if not (1 <= v <= 15):
            raise SystemExit('!! 图集调色板索引异常: 空色 = %d' % v)
        return v, tot

    def write_pixels(self, ys, xs, ink, empty):
        """把引擎图像素批量写回容器 (只写**数据区**, 绝不碰 48B 包头)。"""
        ys = np.asarray(ys, dtype=np.int64)
        xs = np.asarray(xs, dtype=np.int64)
        ink = np.asarray(ink, dtype=bool)
        arr = np.frombuffer(self.cont, dtype=np.uint8)          # bytearray ⇒ 可写视图
        n = 0
        for (fr, doff, nbytes) in self.segs:
            nrow = nbytes // self.stride
            sel = (ys >= fr) & (ys < fr + nrow)
            if not sel.any():
                continue
            yy, xx = ys[sel], xs[sel]
            offs = doff + (yy - fr) * self.stride + xx // 2
            if offs.min() < doff or offs.max() >= doff + nbytes:
                raise SystemExit('!! 像素算出的偏移越出该段数据区 —— 封包换算错了')
            vals = np.where(ink[sel], 0, empty).astype(np.uint8)
            hi = (xx & 1) == 1
            if hi.any():
                o = offs[hi]
                arr[o] = (arr[o] & 0x0F) | (vals[hi] << 4)
            lo = ~hi
            if lo.any():
                o = offs[lo]
                arr[o] = (arr[o] & 0xF0) | vals[lo]
            n += int(sel.sum())
        if n != len(ys):
            raise SystemExit('!! 有 %d 个像素不属于任何段的数据区' % (len(ys) - n))
        return n

    def headers(self):
        """全部段头的字节 (供"包头没被动过"的核对)。"""
        out = []
        for (_fr, doff, _nb) in self.segs:
            out.append((doff, bytes(self.cont[doff - tcslib.ATLAS_PREFIX_BYTES:doff])))
        return out


# ═══════════════════════ 可用格枚举 ═══════════════════════

def enumerate_cells(w, h):
    """全部 1504 个对偶槽 → dict(slot, row, col, x, y)。"""
    out = []
    for s in range(tcslib.pair_capacity()):
        r, c = s // NCOL, s % NCOL
        x, y = tcslib.atlas_cell_xy_engine_view(s)
        out.append(dict(slot=s, row=r, col=c, x=x, y=y))
    return out


def protect_mask(faces, w, h):
    """全部 face 的 **FT 记录矩形** (单字节码 / 手柄图标码的采样窗) 打成一个像素掩码。

    ★ 三个 face 全部保护 —— round45 的教训: 只护 `default` 会擦掉图标码的小矩形,
      实机表现为"武器详情页上下滚动箭头变暗"。宁可少 44 个格, 也不动别人的采样窗。
    """
    m = np.zeros((h, w), dtype=bool)
    rects = []
    for (fname, _fld, rs) in faces:
        for idx, r in enumerate(rs):
            _b0, _b1, u0, v0, u1, v1 = r
            if u1 <= u0 or v1 <= v0:
                continue
            x0, x1 = max(0, u0), min(w, u1)
            y0, y1 = max(0, v0), min(h, v1)
            if x0 >= x1 or y0 >= y1:
                continue
            m[y0:y1, x0:x1] = True
            rects.append(dict(face=fname, code=idx + 0x20, u0=u0, v0=v0, u1=u1, v1=v1))
    return m, rects


def classify(cells, protect, w, h):
    """每个槽 → ('usable' | 'oob' | 'record_cell' | 'ft_rect', 人话原因)。"""
    cls = {}
    for c in cells:
        s, r, col, x, y = c['slot'], c['row'], c['col'], c['x'], c['y']
        if x + CW > w or y + CH > h:
            cls[s] = ('oob', '引擎格越出图集 (%d,%d)' % (x, y))
            continue
        note = tcslib.ATLAS_ENGINE_SINGLE_CELLS.get((r, col))
        if note:
            cls[s] = ('record_cell', note)
            continue
        if protect[y:y + CH, x:x + CW].any():
            cls[s] = ('ft_rect', '被 FT 记录矩形压着 (单字节码/图标码的采样窗)')
            continue
        cls[s] = ('usable', '')
    return cls


def char_order(cs):
    """**确定性顺序**: 按当前槽位升序 (图集行主序), 同槽按码点。"""
    items = []
    dead = {}
    for ch, (b1, b2) in cs.enc_pair.items():
        if tcslib.PAIR_LEAD_LO <= b1 < tcslib.PAIR_LEAD_HI:
            items.append((tcslib.pair_slot(b1, b2), ch))
        else:
            dead[ch] = (b1, b2)
    items.sort(key=lambda t: (t[0], ord(t[1])))
    return items, dead


# ════════ "charset 指到的槽位是空的" 三分类 (★ 2026-10-20 fix/font 修的字库步骤中止缺陷) ════════
#   旧门禁把"在用字、但 charset 指的槽位在图集里是空的"整块判成 **"charset JSON 与盘对不上"**,
#   超过 2% 就 raise ⇒ 现役盘上**必然中止** (实测 `CompactError: 420/2300` / repack 侧 SystemExit)。
#   那 420 其实是三类完全不同的东西, 只有第三类才是真故障:
#
#     ① `pua`             359 个 —— PUA 码位 (U+E000..U+F8FF) 的**占位键**: charset 刻意留的坑,
#                          无字符、无字形、永远空。它空着**完全正常** ⇒ **豁免**。
#     ② `registered_missing` 61 个 —— charset 元数据 `_expand_cap2400.real_chars` 里
#                          {槽位: [字, 频次]} **明明白白登记过**的真汉字 (如 1872=鼠), 只是
#                          像素从没画上去 (本轮 GR_ZH138 已把这 61 格补齐)。
#                          ⇒ 它是"**已登记的缺字形**"这个已知缺陷本身, 不是"charset 版本不对";
#                             仍然**逐字计入 `missing_glyph_before`** 并打印, 一个都没被抹掉,
#                             只是不再让它把整条字库步骤打死。
#     ③ `unexplained`      —— 既不是 PUA、也没在元数据登记 ⇒ **这才是真故障**(换错 charset /
#                          盘被改过) ⇒ **无条件中止** (比原来的 2% 阈值严格: 1 个就停)。
#
#   ★ 为什么不能"只豁免 PUA": 只豁免 359 的话剩 61/2300 = 2.65% > 2% ⇒ ZH137 仍然中止,
#     与"修好生成链"直接矛盾。所以把 ② 单列成**具名已知缺陷**(而不是把它算成版本冲突)。
PUA_LO, PUA_HI = 0xE000, 0xF8FF
REGISTERED_MISSING_BLOCK = '_expand_cap2400'


def registered_missing_slots(charset_json=None, cs=None):
    """charset 元数据里"**已登记槽位、真汉字、尚未画**"的表 → {slot: char}。

    只读元数据 (`_expand_cap2400.real_chars`), 不看像素; 给了 `cs` 时再与 `pair_of` **交叉核对**
    (槽位上的字必须与当前映射一致) —— 这样"元数据陈旧/换了 charset"不会把错版放过去。
    """
    rc = ((charset_json or {}).get(REGISTERED_MISSING_BLOCK) or {}).get('real_chars') or {}
    out = {}
    for k, v in rc.items():
        try:
            slot = int(k)
            ch = v[0] if isinstance(v, (list, tuple)) else str(v)
        except (TypeError, ValueError, IndexError):
            continue
        if isinstance(ch, str) and len(ch) == 1:
            out[slot] = ch
    if cs is not None:
        slot2ch = dict((tcslib.pair_slot(b1, b2), ch)
                       for ch, (b1, b2) in cs.enc_pair.items())
        out = dict((s, ch) for s, ch in out.items() if slot2ch.get(s) == ch)
    return out


def classify_blank_slots(pairs, charset_json=None, cs=None):
    """把 [(slot, char)] 形式的空槽清单分成 pua / registered_missing / unexplained 三类。"""
    reg = registered_missing_slots(charset_json, cs)
    out = dict(pua=[], registered_missing=[], unexplained=[])
    for slot, ch in pairs:
        if PUA_LO <= ord(ch) <= PUA_HI:
            out['pua'].append((slot, ch))
        elif reg.get(slot) == ch:
            out['registered_missing'].append((slot, ch))
        else:
            out['unexplained'].append((slot, ch))
    return out


def report_blank_slots(bl, n_items, tag='[!!]'):
    """打印三分类 (人话), 返回 (可继续?, 一行摘要)。"""
    n_pua = len(bl['pua'])
    n_reg = len(bl['registered_missing'])
    n_bad = len(bl['unexplained'])
    if not (n_pua or n_reg or n_bad):
        return True, '0 个在用字的槽位是空的 (charset 与盘完全对得上)'
    print('  %s 有 %d/%d 个在用字的"当前槽位"在图集里是空的 —— 分三类:'
          % (tag, n_pua + n_reg + n_bad, n_items), flush=True)
    print('        · PUA 占位 %d 个  (豁免: 刻意留白, 无字符/无字形)' % n_pua, flush=True)
    print('        · 已登记未绘制 %d 个  (不是版本问题; 仍计入缺字形): %s'
          % (n_reg, ''.join(c for _s, c in bl['registered_missing'][:30])), flush=True)
    print('        · **来源不明 %d 个**  (这才是"charset 与盘对不上"): %s'
          % (n_bad, ''.join(c for _s, c in bl['unexplained'][:30])), flush=True)
    return (n_bad == 0), ('PUA %d 豁免 / 已登记缺字形 %d / 来源不明 %d' % (n_pua, n_reg, n_bad))


# ═══════════════════════ 主流程 ═══════════════════════

def plan(iso_path, charset_path=None, verbose=True):
    """只读地算出重排方案 (不写任何文件)。返回 summary dict (含 target 引擎图)。"""
    t0 = time.time()
    charset_path = charset_path or tcslib.CHARSET
    # ★ 先对盘: 模块级 NCOL/CW/CH 一律以**盘上 ELF 立即数**为准 (不再信 import 时的快照)
    geom = sync_geometry_from_iso(iso_path, verbose=verbose)
    font = dump_font.load_font(iso_path)
    atlas_meta, faces = font['atlas'], font['faces']
    w, h, psm = atlas_meta['w'], atlas_meta['h'], atlas_meta['psm']
    A = Atlas(atlas_meta['pak'], atlas_meta['px_off'], atlas_meta['px_size'], w, h, psm)
    cs = tcslib.Charset(charset_path)

    # ---- ★ "charset 与这张盘对不对得上" 的第一道（便宜）检查 ----
    #   charset 的 `_font_repack.iso_sha256` 记着"上次重排把这份 charset 写给了哪张盘"。
    #   正常构筑里下一轮的**基底就是上一轮的产物** ⇒ sha 天然相等, 不打印任何东西;
    #   只有"基底被本轮的 --patch 改过"或"charset 被换成了别的版本"时才会不一致。
    iso_sha = tcslib.sha256_file(iso_path)
    rec_sha = ((_load_charset_json(charset_path).get('_font_repack') or {})
               .get('iso_sha256'))
    if rec_sha and rec_sha != iso_sha and verbose:
        print('  [note] charset 记录的"上次写入的盘"是 %s…, 本次输入盘是 %s… —— 两者不同。'
              % (rec_sha[:12], iso_sha[:12]))
        print('         正常构筑里这表示"基底被本轮的 --patch 改过"(没问题);')
        print('         若是**人工单跑**, 请确认这份 charset 与这张盘是**同一版本**'
              ' (见本文件顶部 ⚠ —— 用错版本会把整盘字写乱)。')

    protect, rects = protect_mask(faces, w, h)
    cells = enumerate_cells(w, h)
    cls = classify(cells, protect, w, h)
    usable = [c['slot'] for c in cells if cls[c['slot']][0] == 'usable']
    counts = {}
    for c in cells:
        k = cls[c['slot']][0]
        counts[k] = counts.get(k, 0) + 1

    # 禁用格 ⊆ 记录矩形? (口径自洽性: 禁用格必须真的是"别人的采样窗")
    forb_not_prot = [s for s in cls if cls[s][0] == 'record_cell'
                     and not protect[cells[s]['y']:cells[s]['y'] + CH,
                                    cells[s]['x']:cells[s]['x'] + CW].any()]

    items, dead = char_order(cs)
    dup = {}
    for s, ch in items:
        dup.setdefault(s, []).append(ch)
    dup_slots = dict((s, v) for s, v in dup.items() if len(v) > 1)

    used_slots = [s for s, _ch in items]
    on_bad = [(s, ch, cls[s][0]) for s, ch in items if cls[s][0] != 'usable']
    old_img = A.eng
    # ---- ★ 一致性把关: charset JSON 与这张盘对不对得上? ----
    #   重排按 **charset 给的当前槽位** 去图集里取字形 ⇒ 若 charset 是"另一版"的映射
    #   (例如有人手工换了 charset、或某次构筑半途失败没回滚), 取到的就是**别的格子的像素**。
    #   ★ 2026-10-20 起: 判据换成 `classify_blank_slots()` 的三分类 + **零容忍**
    #     (PUA 占位豁免 / 已登记缺字形单列 / 其余 1 个就中止), 见本文件上方那段说明。
    #   ⚠ 已知局限仍然存在: 两版图集都很满时, 取到"别人的字形"是**看不出来**的 —— 所以真正的
    #     保障是 ① 构筑管线里 charset 与盘同进同退 (make_build 在失败时回滚 charset),
    #     ② 人工单跑本工具时**必须用与这张盘同一版本**的 charset。
    _js = _load_charset_json(charset_path)
    blank_pairs = [(s, ch) for s, ch in items
                   if not old_img[cells[s]['y']:cells[s]['y'] + CH,
                                  cells[s]['x']:cells[s]['x'] + CW].any()]
    bl = classify_blank_slots(blank_pairs, _js, cs)
    ok_blank, blank_line = report_blank_slots(bl, len(items))
    if not ok_blank:
        raise SystemExit(
            '!! 拒绝重排: %d/%d 个在用字在 charset 指的槽位上是空的, 且**既不是 PUA 占位、'
            '也没在 charset 元数据里登记** —— **charset JSON 与这张盘对不上** '
            '(多半是 charset 被换成了别的版本)。\n'
            '   出处: %s\n'
            '   重排会按 charset 的槽位去图集取字形, 对不上就会把整盘字写乱。\n'
            '   怎么办: 把 charset JSON 换回**与这张盘同一版本**的那份再跑 '
            '(构筑时构筑器会自动备份到 <版本>/temp/font_repack/charset_before.json)。'
            % (len(bl['unexplained']), len(items),
               ''.join(ch for _s, ch in bl['unexplained'][:20])))
    if len(usable) < len(items):
        raise SystemExit('!! 可用格不够: 可用 %d < 在用字形 %d —— 无法紧凑重排'
                         % (len(usable), len(items)))

    # ---- 分配: 第 i 个字 → 第 i 个可用格 (可用格按 slot 升序 = 行主序) ----
    move = {}                                   # char -> new_slot
    for i, (_s, ch) in enumerate(items):
        move[ch] = usable[i]

    old_img = A.eng                               # (已在上面一致性检查前取好)
    new_slots = set(move.values())
    assert len(new_slots) == len(move), '新槽位有重复 —— 分配不是单射'

    # ---- 构造目标引擎图 ----
    En = old_img.copy()
    um = np.zeros((h, w), dtype=bool)                    # 全部可用格 = 清零区
    for c in cells:
        if cls[c['slot']][0] == 'usable':
            um[c['y']:c['y'] + CH, c['x']:c['x'] + CW] = True
    En[um] = False                                       # ★ 未使用区域置零
    moved = kept = 0
    for s, ch in items:
        ns = move[ch]
        ox, oy = cells[s]['x'], cells[s]['y']
        nx, ny = cells[ns]['x'], cells[ns]['y']
        En[ny:ny + CH, nx:nx + CW] = old_img[oy:oy + CH, ox:ox + CW]
        if ns == s:
            kept += 1
        else:
            moved += 1
    En[protect] = old_img[protect]                       # ★ 别人的采样窗最终说了算

    # ---- 自检 (在 plan 阶段就做完, 写盘前就能拦) ----
    diff = En != old_img
    bad_prot = int((En[protect] != old_img[protect]).sum())
    if bad_prot:
        raise SystemExit('!! 自检失败: FT 记录矩形被改了 %d 个像素' % bad_prot)
    glyph_ok = 0
    for s, ch in items:
        ns = move[ch]
        ox, oy = cells[s]['x'], cells[s]['y']
        nx, ny = cells[ns]['x'], cells[ns]['y']
        if np.array_equal(En[ny:ny + CH, nx:nx + CW], old_img[oy:oy + CH, ox:ox + CW]):
            glyph_ok += 1
    if glyph_ok != len(items):
        raise SystemExit('!! 自检失败: 只有 %d/%d 个字形的像素原样落到新格' % (glyph_ok, len(items)))

    # ---- code 变更 ----
    code_changes = []
    for s, ch in items:
        ns = move[ch]
        if ns == s:
            continue
        lead, trail = tcslib.pair_from_slot(ns)
        code_changes.append(dict(char=ch, old_slot=s, new_slot=ns,
                                 old_code='%02X%02X' % cs.enc_pair[ch],
                                 new_code='%02X%02X' % (lead, trail),
                                 old_cell=[cells[s]['x'], cells[s]['y']],
                                 new_cell=[cells[ns]['x'], cells[ns]['y']],
                                 ink=int(old_img[cells[s]['y']:cells[s]['y'] + CH,
                                                  cells[s]['x']:cells[s]['x'] + CW].sum())))
    bad_new = [x for x in code_changes
               if cls[x['new_slot']][0] != 'usable'
               or tcslib.ATLAS_ENGINE_SINGLE_CELLS.get((x['new_slot'] // NCOL, x['new_slot'] % NCOL))]
    if bad_new:
        raise SystemExit('!! 自检失败: %d 个字被分配到禁用/被压的格' % len(bad_new))

    ink0 = int(old_img.sum())
    ink1 = int(En.sum())
    empty_val, hist = A.empty_index()
    changed = bool(diff.any()) or bool(code_changes)
    n_px = int(diff.sum())

    # ---- 重排前"格是白的、可直接用"的口径 ----
    #   ★ 只在**可用格**里数 (才与"重排后能放多少新字"同一个口径):
    #     空着的槽 185 个, 其中 51 个是记录码/图标占死的格、44 个被 FT 记录矩形压着 ——
    #     这些**永远不能用**, 不能算进"可直接用的空位"。
    used_set = set(used_slots)
    free_usable_now = [s for s in usable if s not in used_set]
    blank_now = sum(1 for s in free_usable_now
                    if not old_img[cells[s]['y']:cells[s]['y'] + CH,
                                   cells[s]['x']:cells[s]['x'] + CW].any())
    dirty_now = len(free_usable_now) - blank_now
    free_slots_now = tcslib.pair_capacity() - len(used_set)
    free_after = len(usable) - len(items)
    blank_after = sum(1 for s in usable if s not in new_slots)

    summ = dict(
        tool='tools/iso_build/repack_font.py', tool_version=TOOL_VERSION, round=ROUND,
        iso=rel(iso_path), iso_sha256=tcslib.sha256_file(iso_path),
        charset=rel(charset_path), order_key=ORDER_KEY,
        geom_from_elf=geom,
        changed=changed, pixels_changed=n_px, empty_index=empty_val,
        atlas=dict(w=w, h=h, psm=psm, px_off=atlas_meta['px_off'], px_size=atlas_meta['px_size'],
                   segments=len(A.segs), ink_before=ink0, ink_after=ink1,
                   ink_delta=ink1 - ink0),
        cells=dict(total=len(cells), usable=len(usable), oob=counts.get('oob', 0),
                   record_cell=counts.get('record_cell', 0), ft_rect=counts.get('ft_rect', 0),
                   forbidden_total=counts.get('record_cell', 0) + counts.get('ft_rect', 0),
                   forbidden_not_in_ft_rect=len(forb_not_prot),
                   ft_records=len(rects)),
        glyphs=dict(used=len(items), moved=moved, kept=kept, dead_pairs=len(dead),
                    dead_chars=''.join(sorted(dead)), dup_slots=len(dup_slots),
                    on_bad_cell_before=len(on_bad),
                    # ★ 2026-10-20: `missing_glyph_before` 只数**真缺字形**(已登记未绘制),
                    #   PUA 占位单列成 `pua_placeholder_before` (它们是**故意空**的, 不是缺字)。
                    missing_glyph_before=len(bl['registered_missing']),
                    pua_placeholder_before=len(bl['pua']),
                    blank_slots_before=len(blank_pairs),
                    blank_classification=blank_line,
                    missing_glyph_chars=''.join(ch for _s, ch in bl['registered_missing'])),
        capacity=dict(
            pair_slots=tcslib.pair_capacity(),
            usable_cells=len(usable), used=len(items),
            free_slots_before=free_slots_now,
            free_usable_before=len(free_usable_now),
            blank_usable_before=blank_now, dirty_usable_before=dirty_now,
            remaining_capacity=free_after, blank_usable_after=blank_after,
            freed=blank_after - blank_now,
            blocked_by_record_cells=counts.get('record_cell', 0),
            blocked_by_ft_rects=counts.get('ft_rect', 0),
            note=('可用格 = 1504 − 单字节/图标记录码占死的格 − 被 FT 记录矩形压着的格; '
                  '重排后还能再放多少新字 = 可用格 − 在用字形')),
        code_changes=len(code_changes),
        code_changes_full=code_changes,
        on_bad_cell_before_detail=[dict(slot=s, char=ch, kind=k, row=s // NCOL, col=s % NCOL)
                                   for s, ch, k in on_bad],
        ft_rects_on_grid=[r for r in rects
                          if any(yrow(rr) < r['v1'] and r['v0'] < yrow(rr) + CH
                                 for rr in range(25))],
        seconds=round(time.time() - t0, 1),
    )
    # ---- 交叉核对: 用工程自己的 dump_font.capacity_report 再算一遍 (口径不同, 如实并列) ----
    try:
        _iso = tcslib.Iso(iso_path)
        cache = tcslib.GlyphCache(cs, _iso)
        capr = dump_font.capacity_report(cs, cache, faces, int(old_img.sum()), w, h)
        _iso.close()
        summ['cross_check_dump_font'] = dict(
            vacuum_usable=capr['pair']['vacuum_usable'],
            strict_window_free=capr['pair']['strict_window_free'],
            note=('dump_font 口径: vacuum = 空槽里引擎格一个墨点都没有的 —— **含"虽然空、'
                  '但被记录码/图标占死、永远不能用"的格** ⇒ 比本工具的"可用格−在用"宽松; '
                  'strict_window_free 再要求与全部活字形采样窗零交叠 ⇒ 比本工具更保守。'
                  '三个数口径不同, 如实并列, 不互相掩盖。'
                  '(round46 已订正 dump_font 里"数墨用 flat 列 + 取行用引擎图"的坐标混用)'),
        )
    except Exception as e:                                       # noqa: BLE001
        summ['cross_check_dump_font'] = dict(error='%s: %s' % (type(e).__name__, e))
    # 给人看的一句话
    if changed:
        summ['one_line'] = ('重排后还能再放 **%d** 个新字 (重排前"格是白的、又真能用"的只有 %d 个); '
                            '本轮搬运 %d 个字, 清干净 %d 个可用格。'
                            % (free_after, blank_now, moved, len(usable) - len(new_slots)))
    else:
        summ['one_line'] = ('字库已经是紧凑的: 无需重排 (0 改动); 还能再放 **%d** 个新字。'
                            % free_after)
    return dict(summary=summ, atlas=A, cells=cells, cls=cls, items=items, move=move,
                target=En, protect=protect, faces=faces, font=font, cs=cs, usable=usable,
                code_changes=code_changes)


# ═══════════════════════ charset JSON ═══════════════════════

def update_charset(charset_path, code_changes, summ):
    """按新分配改 `pair_of`, 并写一节 `_font_repack` 说明。返回改动条数。"""
    js = json.load(io.open(charset_path, encoding='utf-8'))
    for x in code_changes:
        ch = x['char']
        if ch not in js['pair_of']:
            raise SystemExit('!! charset JSON 里没有 %r 的 pair_of' % ch)
        lead, trail = tcslib.pair_from_slot(x['new_slot'])
        if not (tcslib.PAIR_LEAD_LO <= lead < tcslib.PAIR_LEAD_HI):
            raise SystemExit('!! %r 的新 lead 0x%02X 越出引擎可读区间' % (ch, lead))
        js['pair_of'][ch] = [lead, trail]
    prev = js.get('_font_repack') or {}
    js['_font_repack'] = dict(
        note=('round46 起: 构筑管线每轮自动把在用字形**紧凑重排**到最前面的可用格, '
              '未使用区域清零; 顺序 = %s。可用格 = 1504 − 单字节/图标记录码占死的格 − '
              '被 FT 记录矩形 (单字节/ASCII 采样窗) 压着的格。' % ORDER_KEY),
        tool='tools/iso_build/repack_font.py', tool_version=TOOL_VERSION,
        last_applied=time.strftime('%Y-%m-%d %H:%M:%S'),
        first_applied=prev.get('first_applied') or time.strftime('%Y-%m-%d %H:%M:%S'),
        usable_cells=summ['cells']['usable'], used=summ['glyphs']['used'],
        remaining_capacity=summ['capacity']['remaining_capacity'],
        blocked=dict(record_cells=summ['cells']['record_cell'],
                     ft_rect_cells=summ['cells']['ft_rect']),
        moved_last=summ['glyphs']['moved'], codes_changed_last=summ['code_changes'],
        atlas_pixel_sha256=summ['atlas_pixel_sha256'],
        # ★ 记下"这份 charset 是给哪张盘写的" —— 人工排查 "charset 与盘对不上" 时用得上。
        iso_sha256=summ.get('iso_sha256_after') or summ.get('iso_sha256'),
        order=('决策顺序: 按"当前槽位"升序 (= 图集行主序) 逐字搬到第 i 个可用格; '
               '因为槽位号本身就是行主序, 重排后顺序不变 ⇒ 再跑一次是 0 改动'),
        forbidden_cells=dict(('%d,%d' % k, v)
                             for k, v in sorted(tcslib.ATLAS_ENGINE_SINGLE_CELLS.items())),
    )
    io.open(charset_path, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(js, ensure_ascii=False, indent=1) + '\n')
    return len(code_changes)


# ═══════════════════════ 强制重编码文本表 ═══════════════════════

def make_reencode_tables(src, dst, verbose=True):
    """把注入用的表 (文件或目录) 拷成「强制重编码」副本: **只清 `text_zh` 列**, 其余照抄。

    为什么必须这样: 注入器对 `text_edited == text_zh`(没人工改过)的行**原样不动**
    (设计如此: "dump 后不改动 ⇒ 产物与基底 sha256 相同")。重排改了"字节↔字符"映射,
    盘上所有旧编码的文本都必须**整体重编码**一次 —— 清掉 text_zh 这一列, 注入器就认为
    每一行都"被人工改过", 于是用**新** charset 把用户译文重新编码写盘。
    用户译文 (`text_edited`) **一个字都不动**。

    返回 dict(files=[...], rows=..., edited_nonempty=...) 或抛异常。
    """
    paths, notes = tcslib.expand_csv_inputs([src])
    errs = [n for n in notes if n['level'] == 'error']
    if errs or not paths:
        raise SystemExit('!! 重编码: 找不到可读的文本表 (%s): %s'
                         % (src, '; '.join(n['msg'] for n in errs) or '空目录'))
    os.makedirs(dst, exist_ok=True)
    files, tot, edited = [], 0, 0
    for p in paths:
        with io.open(p, 'r', encoding='utf-8-sig', newline='') as fh:
            recs = list(csv.reader(fh))
        if not recs:
            continue
        cols = [c.strip() for c in recs[0]]
        if 'text_zh' not in cols or 'text_edited' not in cols:
            raise SystemExit('!! 重编码: %s 缺 text_zh / text_edited 列: %s' % (p, cols))
        iz, ie = cols.index('text_zh'), cols.index('text_edited')
        out_recs = [recs[0]]
        for r in recs[1:]:
            if not r or all(not c.strip() for c in r):
                continue
            r = list(r) + [''] * (len(cols) - len(r))
            tot += 1
            if (r[ie] or '').strip():
                edited += 1
            r[iz] = ''                                   # ★ 只改这一列
            out_recs.append(r)
        op = os.path.join(dst, os.path.basename(p))
        with io.open(op, 'w', encoding='utf-8', newline='') as fh:
            csv.writer(fh, lineterminator='\n').writerows(out_recs)
        files.append(dict(src=rel(p), dst=rel(op), rows=len(out_recs) - 1,
                          sha256=tcslib.sha256_file(op)))
        if verbose:
            print('  [reencode] %-40s %4d 行 (译文非空 %d) → %s'
                  % (os.path.basename(p), len(out_recs) - 1,
                     sum(1 for r in out_recs[1:] if (r[ie] or '').strip()), rel(op)))
    # 非 CSV 的伴随文件 (meta.json / txt) 一并拷过去, 免得注入器找不到
    if os.path.isdir(src):
        for fn in sorted(os.listdir(src)):
            fp = os.path.join(src, fn)
            if os.path.isfile(fp) and not fn.lower().endswith('.csv'):
                shutil.copyfile(fp, os.path.join(dst, fn))
    man = dict(src=rel(src), dst=rel(dst), files=files, rows=tot, edited_nonempty=edited,
               why='只清 text_zh 列 (强制整表重编码); text_edited 逐字节来自用户表',
               generated=time.strftime('%Y-%m-%d %H:%M:%S'))
    io.open(os.path.join(dst, '_reencode_manifest.json'), 'w', encoding='utf-8',
            newline='\n').write(json.dumps(man, ensure_ascii=False, indent=1) + '\n')
    if verbose:
        print('  [reencode] 合计 %d 行 (译文非空 %d) → %s' % (tot, edited, rel(dst)))
    return man


# ═══════════════════════ 执行 (写盘) ═══════════════════════

def apply(src_iso, out_iso, res, charset_path=None, do_charset=True, verbose=True):
    """把方案落到盘上 + 同步 charset; 返回回读校验结果。"""
    # ★ 写盘前再对一次盘上的 ELF 立即数 (方案是 plan() 算的; 这里防"plan 之后换了盘")
    sync_geometry_from_iso(src_iso, verbose=verbose)
    A = res['atlas']
    summ = res['summary']
    pak_e = res['font']['pak_e']
    px_off = A.px_off
    empty = summ['empty_index']
    ys, xs = np.where(res['target'] != A.eng)
    ink = res['target'][ys, xs]
    hdr_before = A.headers()
    A.write_pixels(ys, xs, ink, empty)

    # 包头逐字节没动
    for (doff, hb) in hdr_before:
        if bytes(A.cont[doff - tcslib.ATLAS_PREFIX_BYTES:doff]) != hb:
            raise SystemExit('!! 有 48B 包头被改了 (doff=0x%X)' % doff)

    if os.path.abspath(src_iso) != os.path.abspath(out_iso):
        shutil.copyfile(src_iso, out_iso)
    with open(out_iso, 'r+b') as f:
        f.seek(pak_e['iso_off'] + px_off)
        f.write(bytes(A.cont))
    if os.path.getsize(src_iso) != os.path.getsize(out_iso):
        raise SystemExit('!! ISO 尺寸变了')

    # ---- 回读校验 ----
    with open(out_iso, 'rb') as f:
        f.seek(pak_e['iso_off'])
        pak2 = f.read(pak_e['stored'])
    if bytes(pak2[:px_off]) != bytes(res['font']['atlas']['pak'][:px_off]) or \
       bytes(pak2[px_off + A.px_size:]) != bytes(res['font']['atlas']['pak'][px_off + A.px_size:]):
        raise SystemExit('!! 回读: COMMON.PAK 里像素容器以外的字节被改动了')
    A2 = Atlas(pak2, px_off, A.px_size, A.w, A.h, A.psm)
    if not np.array_equal(A2.eng, res['target']):
        d = int((A2.eng != res['target']).sum())
        raise SystemExit('!! 回读: 盘上解出的引擎图与目标图差 %d 个像素' % d)
    # 每个字的字形必须原样落在新格上
    cells = res['cells']
    bad = 0
    for s, ch in res['items']:
        ns = res['move'][ch]
        ox, oy = cells[s]['x'], cells[s]['y']
        nx, ny = cells[ns]['x'], cells[ns]['y']
        if not np.array_equal(A2.eng[ny:ny + CH, nx:nx + CW],
                              res['atlas'].eng[oy:oy + CH, ox:ox + CW]):
            bad += 1
    if bad:
        raise SystemExit('!! 回读: %d 个字形的像素搬运不正确' % bad)

    summ['atlas_pixel_sha256'] = sha256_b(
        np.packbits(res['target'].reshape(-1)).tobytes())
    # ★ 记录**产出盘**的 sha (不是输入盘的): 下一轮构筑的基底就是它 ⇒ 天然对得上。
    summ['iso_sha256_after'] = tcslib.sha256_file(out_iso)
    if verbose:
        print('  [pack] 回写 %d 像素 (空色=索引 %d); 包头逐字节未动 ✓; 回读引擎图一致 ✓'
              % (len(ys), empty))

    if do_charset:
        charset_path = charset_path or tcslib.CHARSET
        n = update_charset(charset_path, res['code_changes'], summ)
        cs2 = tcslib.Charset(charset_path)
        # charset 自检: 每个字都能编码成新槽位的字节, 且新槽位可用
        for x in res['code_changes']:
            ch = x['char']
            want = bytes(tcslib.pair_from_slot(x['new_slot']))
            if cs2.encode_strict(ch) != want:
                raise SystemExit('!! charset 自检失败: %r 编码 %s ≠ 期望 %s'
                                 % (ch, cs2.encode_strict(ch).hex(), want.hex()))
            r, c = x['new_slot'] // NCOL, x['new_slot'] % NCOL
            if tcslib.ATLAS_ENGINE_SINGLE_CELLS.get((r, c)):
                raise SystemExit('!! charset 自检失败: %r 落在禁用格 (%d,%d)' % (ch, r, c))
        if verbose:
            print('  [json] charset 已更新 %d 个码位, 自检 ✓ (%s)' % (n, rel(charset_path)))
    return summ


def stamp_charset(version, iso_sha, charset_path=None):
    """把"这份 charset 配的是哪张盘"记进 charset JSON 的 `_font_repack` 段。

    ★ 目的: 让"charset 与盘对不对得上"**可查**。人工单跑本工具时, 如果手里拿的是
      别的版本的 charset, `plan()` 会据此打一条提醒 (见文件顶部 ⚠)。
    只在**构筑成功后**调, 失败时不写 (失败走 rollback)。任何异常都吞掉 —— 这只是一个
    旁证字段, 不该让已经产出的盘变成"构筑失败"。
    """
    charset_path = charset_path or tcslib.CHARSET
    try:
        js = json.load(io.open(charset_path, encoding='utf-8'))
        fr = js.get('_font_repack')
        if not isinstance(fr, dict):
            fr = dict(note='round46 起: 构筑管线每轮自动紧凑重排字库 (repack_font.py)')
            js['_font_repack'] = fr
        fr['iso_sha256'] = iso_sha
        fr['iso_version'] = version
        fr['stamped'] = time.strftime('%Y-%m-%d %H:%M:%S')
        io.open(charset_path, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(js, ensure_ascii=False, indent=1) + '\n')
        return True
    except Exception as e:                                           # noqa: BLE001
        print('[font-repack] ⚠ charset 打戳失败 (不影响构筑): %s' % e)
        return False


def verify_no_change_sha(iso_path, res):
    """幂等复核: 盘上现状 == 方案目标, 且没有任何 code 变更。"""
    A = res['atlas']
    same_px = np.array_equal(A.eng, res['target'])
    return dict(pixels_identical=same_px, code_changes=len(res['code_changes']),
                iso_sha256=tcslib.sha256_file(iso_path))


# ═══════════════════════ CLI ═══════════════════════

def print_report(summ, verbose=True):
    c, g, cap = summ['cells'], summ['glyphs'], summ['capacity']
    print('')
    print('─' * 78)
    print('字库紧凑重排 — %s' % ('**有改动**' if summ['changed'] else '无需重排 (0 改动)'))
    print('─' * 78)
    print('  图集        : %dx%d psm=0x%02X, %d 段 GIF 封包, 墨点 %d → %d'
          % (summ['atlas']['w'], summ['atlas']['h'], summ['atlas']['psm'],
             summ['atlas']['segments'], summ['atlas']['ink_before'], summ['atlas']['ink_after']))
    print('  对偶容量    : %d 槽 (空着的 %d)' % (cap['pair_slots'], cap['free_slots_before']))
    print('    其中**可用**: %d   (= 容量 − 记录码/图标占死 %d − 被 FT 记录矩形压着 %d)'
          % (c['usable'], c['record_cell'], c['ft_rect']))
    print('  在用字形    : %d  (搬运 %d, 原地不动 %d)'
          % (g['used'], g['moved'], g['kept']))
    print('  ★ 剩余容量  : **%d** 个新字 (重排前"格是白的、又真能用"的只有 %d 个; '
          '另有 %d 个可用格被旧字形残墨糊着)' % (cap['remaining_capacity'],
                                                cap['blank_usable_before'],
                                                cap['dirty_usable_before']))
    print('    重排后空出的 %d 格里, %d 个是本次清干净的'
          % (cap['remaining_capacity'], cap['freed']))
    print('  码位变更    : %d 个字 (charset 已同步; 文本需整体重编码)'
          % summ['code_changes'])
    print('  像素改动    : %d (清零区 %d 格)' % (summ['pixels_changed'],
                                                c['usable'] - g['used']))
    if g['dead_pairs']:
        print('  死 pair     : %d %s (lead 越界, 引擎读不了; 未搬动)' % (g['dead_pairs'], g['dead_chars']))
    if g['on_bad_cell_before']:
        print('  ★ 重排前坐在"不可用格"上的字: %d 个 %s'
              % (g['on_bad_cell_before'],
                 ' '.join('%s(row%d col%d,%s)' % (d['char'], d['row'], d['col'], d['kind'])
                          for d in summ['on_bad_cell_before_detail'][:12])))
    print('  耗时        : %.1fs' % summ['seconds'])
    print('─' * 78)
    print('  一句话: %s' % summ['one_line'].replace('**', ''))
    print('─' * 78)


def main():
    ap = argparse.ArgumentParser(description='字库紧凑重排 (round46)')
    ap.add_argument('--iso', required=True, help='源盘 (只读; 本工具绝不改它, 除非 --in-place)')
    ap.add_argument('--out-iso', default=None, help='重排后的盘 (有改动时必须给)')
    ap.add_argument('--charset', default=None, help='charset JSON (默认 tcslib.CHARSET)')
    ap.add_argument('--no-charset', action='store_true', help='不写 charset JSON (调试)')
    ap.add_argument('--dry-run', action='store_true', help='只算不写 (不出盘/不改 JSON)')
    ap.add_argument('--in-place', action='store_true',
                    help='直接改 --iso 自己 (构筑管线内部用; 人工请用 --out-iso)')
    ap.add_argument('--text-src', default=None,
                    help='生成"强制重编码"文本表的来源 (表文件或 text/ 目录)')
    ap.add_argument('--reencode-out', default=None, help='重编码表输出目录')
    ap.add_argument('--report', default=None, help='把方案 summary 写成 JSON')
    ap.add_argument('--moves-out', default=None, help='把逐字搬运明细写成 JSON')
    ap.add_argument('--json', action='store_true', help='终端只打一行 JSON 摘要')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()

    res = plan(a.iso, a.charset)
    summ = res['summary']

    if not summ['changed']:
        if not a.quiet and not a.json:
            print_report(summ)
        # ---- 幂等: 0 改动 ⇒ 不产出任何文件, 产物 sha256 不变 ----
        if a.out_iso and os.path.abspath(a.out_iso) != os.path.abspath(a.iso):
            print('  [幂等] 无需重排 ⇒ **不产出 %s** (产物就是输入盘本身, sha256 不变)'
                  % rel(a.out_iso))
        summ['wrote_iso'] = None
        summ['iso_sha256_after'] = summ['iso_sha256']
    else:
        if a.dry_run:
            if not a.quiet:
                print_report(summ)
            print('  [dry ] 有改动, 但 --dry-run ⇒ 不写盘 (给 --out-iso 才会产出)')
            summ['wrote_iso'] = None
        else:
            if a.in_place:
                out = a.iso
            else:
                if not a.out_iso:
                    raise SystemExit('!! 有改动但没有 --out-iso (或加 --in-place / --dry-run)')
                out = a.out_iso
            summ = apply(a.iso, out, res, charset_path=a.charset,
                         do_charset=not a.no_charset, verbose=not a.quiet)
            summ['wrote_iso'] = rel(out)
            summ['iso_sha256_after'] = tcslib.sha256_file(out)
            if not a.quiet and not a.json:
                print_report(summ)
                print('  [out ] → %s  sha256 %s…' % (rel(out), summ['iso_sha256_after'][:16]))

    if a.text_src and a.reencode_out:
        if summ['changed'] and not a.dry_run:
            print('[reencode] 生成"强制重编码"文本表 (只清 text_zh 列; text_edited 一字不动):')
            summ['reencode'] = make_reencode_tables(a.text_src, a.reencode_out)
        else:
            print('[reencode] %s ⇒ 不生成 (重排 0 改动时不需要重编码)'
                  % ('dry-run' if a.dry_run else '无需重排'))

    if a.report:
        os.makedirs(os.path.dirname(os.path.abspath(a.report)), exist_ok=True)
        io.open(a.report, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(summ, ensure_ascii=False, indent=1) + '\n')
        print('[rep ] → %s' % rel(a.report))
    if a.moves_out:
        os.makedirs(os.path.dirname(os.path.abspath(a.moves_out)), exist_ok=True)
        io.open(a.moves_out, 'w', encoding='utf-8', newline='\n').write(json.dumps(dict(
            order_key=ORDER_KEY, moved=summ['glyphs']['moved'], kept=summ['glyphs']['kept'],
            changes=res['code_changes'],
            layout=[dict(slot=s, char=ch, x=res['cells'][res['move'][ch]]['x'],
                         y=res['cells'][res['move'][ch]]['y']) for s, ch in res['items']],
        ), ensure_ascii=False, indent=1) + '\n')
        print('[rep ] → %s (逐字搬运明细)' % rel(a.moves_out))
    if a.json:
        print(json.dumps(dict(changed=summ['changed'], moved=summ['glyphs']['moved'],
                              usable=summ['cells']['usable'], used=summ['glyphs']['used'],
                              remaining_capacity=summ['capacity']['remaining_capacity'],
                              blank_usable_before=summ['capacity']['blank_usable_before'],
                              code_changes=summ['code_changes'],
                              pixels_changed=summ['pixels_changed'],
                              iso_sha256=summ.get('iso_sha256_after') or summ['iso_sha256'],
                              wrote_iso=summ.get('wrote_iso')),
                         ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
