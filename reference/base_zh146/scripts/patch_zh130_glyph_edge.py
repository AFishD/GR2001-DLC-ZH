# -*- coding: utf-8 -*-
r"""patch_zh130_glyph_edge.py — 修「字形采样矩形压到贴图右缘 (x + w == 1024)」导致的乱码 (GR_ZH130)。

## 现象 (用户实机点名)
  大写 **X**（名字输入键盘）、**约**、**金** 显示成乱码/稀疏。三者都不是"字库缺字"。

## 根因（两条采样路径，同一个物理原因）
  引擎把字形当**矩形**从 1024 宽的图集里采样。**采样矩形的右缘一旦正好等于贴图宽度
  (u1 == 1024)，引擎就取不到那块像素** —— 实拍表现为"斜纹方块/稀疏残字"。
  这条边界是**用户肉眼验证过的**，有两条独立实证：
    · round59（`docs/REPORT_edge_fix_zh109.md`）：「个」rect (1008,195,1024,211) = 斜纹方块，
      同批「这」(992,195,1008,211) 正常 ⇒ 只有 **u1 == 1024** 坏，u1 ≤ 1008 安全；
    · K2 轮（`docs/CAPACITY_2400.md` §12.6）：`T`=(1016,192,1024,208) 等 182 条 ASCII 记录
      里 u1=1024 的那批实拍"糊/缺横杠"，搬到 "货架 (u1 ≤ 1010)" 后 106 px 差异归零。

  本盘（64 列几何，`GR_FA2400_K2` 起的产物线）**两处同时踩线**：
    ① 对偶码网格：`x = 16*col`、`col = slot % 64` ⇒ **col 63 的格 = (1008..1023)**，
       右缘 1008+16 = **1024** ⇒ 36 个槽（29 个有字形 + 7 个空占位）全部落在取不到的带上；
       其中 **约 slot 639 / 金 slot 703** 正是用户点名的两个（`_REF` 表见 `--report`）。
    ② FT 记录表：**0x58 'X'** 的矩形 (1016,208,1024,224)（large/default/huge 三面同值）
       右缘 = 1024 ⇒ 键盘上那个 X 就是"偏稀疏"的来源（历史报告登记过、根因一直未定位）。

  为什么以前没被发现：64 列几何是 K2 轮引入的，而 K2/2400 的回归导航只到"主菜单 +
  记忆卡屏"，那些界面里一个 col-63 的字都没有（`心/该/给/引/候/总/约/金 …` 全在正文与
  任务名里）⇒ 1 帧粒度对照也照不出来。

## 修法（只动"映射 + 那 36 个格 + 1 条记录"，不动 ELF）
  A. 对偶路径：把 36 个 col-63 槽**整体换位**到"安全空格"（`cls == usable`、`col != 63`、
     格内 0 墨、位于保留段 1872..2344）—— 是**对偶槽位互换**（字符 A ↔ 占位字符 B）：
       · 有字形的字搬字形像素（逐 texel 原样），旧格清零；
       · 被换过来的占位字符本来就无字形（空模板）⇒ 旧格仍是空的 ⇒ 画面语义不变；
       · 码位变了 ⇒ 盘上**全部**文本按项目现成机器 `font_compact.plan_reencode()`
         （容器级登记表 + 全盘粗扫/细扫 + ELF 文本区）**逐字重编码**，长度不变（2B→2B）。
  B. FT 路径：把 **0x58 'X'** 的字形像素搬到货架空位 (352,627)-(360,643)（u1=360），
     三 face 的记录矩形同步改写；`pad`/`advance` 一个字节不动；旧矩形清零。
  C. charset JSON：只改这 72 个字符（36 对）的 `pair_of` 码位 + 追加一节
     `_glyph_edge_zh130` 元信息（文本级最小编辑，不整体重写）。

  ★ 为什么不是"改 64 列 / 改引擎"：`NCOL 64→63` 会让**全部** 2300 个槽的格位整体变位
    （等于重铺整张图集 + 搬 182 条记录），风险远大于 36 格换位；而换位只需重编码
    36 个**码位**，其余 2264 个码位一个字节不动（可用 `--dry-run` 核对）。

## 自证 (写盘前后, 全部硬断言)
  ① 图集三闸门: `w == 1024 ≤ 1024` · `px_size == w*h/2 + 16` · `(w*h/2) % 2048 == 0`
  ② 图集回读 == 目标图 (逐 texel, 引擎口径) + 48B GIF 包头逐字节不变
  ③ 搬运字形: 新格逐 texel == 旧格; 旧格 0 墨; 未参与的格 0 改动
  ④ FT 记录: 只有 0x58 三面变; 新矩形逐 texel == 旧矩形; 旧矩形 0 墨; 新 u1 == 360 ≤ 1008;
     ASCII 182 条记录逐条比对 (除 X 外逐字节/逐 texel == 源盘)
  ⑤ 文本逐字闭环: 每个被重写的容器 `新 charset 解(新字节)` == `旧 charset 解(旧字节)` 逐字相同
  ⑥ 载荷级旧码 0 (`tcslib.scan_legacy_residue`, gate 0xBA)
  ⑦ 全盘字节差异普查: 每一个变动字节必须落在**计划窗口**内 (图集容器 / 重写容器 / FONT.RES 槽)
  ⑧ charset: 恰好 72 条 `pair_of` 变化, `codes` 逐字节不变; 幂等 (对产物再跑 ⇒ 0 改动候选)

## 用法
  python tools/iso_build/patch_zh130_glyph_edge.py --iso <src.iso> --out <dst.iso> \
      [--charset <json>] [--report <json>] [--dry-run] [--no-charset-write]
"""
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, HERE)

import tcslib                                                       # noqa: E402

# ★ K2 几何 —— 必须在 import repack_font / font_compact **之前**覆写：
#   它们在模块级快照 `tcslib.NCOL`（`NCOL, CW, CH = tcslib.NCOL, ...`）。
tcslib.NCOL, tcslib.GRID_SKIP_ROWS, tcslib.GRID_Y0 = 64, 2, 3
tcslib.LEAD_HI = tcslib.PAIR_LEAD_HI = 0xBA

import dump_font as D                                               # noqa: E402
import repack_font as RF                                            # noqa: E402
import font_compact as FC                                           # noqa: E402

RF.NCOL = tcslib.NCOL

CH, CW = tcslib.CH, tcslib.CW
W_EXP, H_EXP = 1024, 644
SAFE_U1 = 1008                     # 经验安全上界（round59 / K2 §12.6 两次用户实拍标定）
X_CODE = 0x58                      # 'X'
ATLAS_REC = 'new_font_revised'
RESERVED_LO, RESERVED_HI = 1872, 2344      # 保留段（473 槽，设计上无字形）
TOOL = 'patch_zh130_glyph_edge'
ROUND = 'round-zh130-glyph-edge'

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:                                                    # noqa: BLE001
    pass


class EdgeError(Exception):
    """计划/门禁不过 —— 一律中止，不写产品盘。"""


# ═══════════════════════════ 小工具 ═══════════════════════════

def rel(p):
    try:
        r = os.path.relpath(p, REPO)
    except ValueError:
        return p.replace('\\', '/')
    return r.replace('\\', '/') if not r.startswith('..') else p.replace('\\', '/')


def sha256_file(p):
    return tcslib.sha256_file(p)


def sha256_b(b):
    return hashlib.sha256(b).hexdigest()


def yrow(r):
    return tcslib.GRID_Y0 + CH * (r + (tcslib.GRID_SKIP_ROWS if r >= tcslib.GRID_SKIP_ROW else 0))


def cell_xy(slot):
    """引擎格位（K2 几何）: x = 16*(slot % NCOL), y = yrow(slot // NCOL)。"""
    r, c = slot // tcslib.NCOL, slot % tcslib.NCOL
    return c * CW, yrow(r)


def face_tables(ft_blob):
    """展开态 FONT.RES → [(name, fld14, 记录表字节偏移, nrec)]（偏移供原地改写）。"""
    p = 0
    l0 = struct.unpack_from('<I', ft_blob, p)[0]
    p += 4 + l0
    nf = struct.unpack_from('<I', ft_blob, p)[0]
    p += 4
    out = []
    for _ in range(nf):
        l = struct.unpack_from('<I', ft_blob, p)[0]
        nm = ft_blob[p + 4:p + 4 + l].decode('latin-1')
        p += 4 + l
        fld = list(struct.unpack_from('<14I', ft_blob, p))
        p += 56
        nrec = fld[4] * fld[5]
        out.append((nm, fld, p, nrec))
        p += nrec * 10
    return out, p


def rec_at(blob, off):
    return struct.unpack_from('<BB4H', blob, off)


def put_rec(blob, off, b0, b1, u0, v0, u1, v1):
    struct.pack_into('<BB4H', blob, off, b0, b1, u0, v0, u1, v1)


def win(ink, x, y, w=CW, h=CH):
    out = np.zeros((h, w), dtype=bool)
    x0, x1 = max(0, x), min(ink.shape[1], x + w)
    y0, y1 = max(0, y), min(ink.shape[0], y + h)
    if x1 > x0 and y1 > y0:
        out[y0 - y:y1 - y, x0 - x:x1 - x] = ink[y0:y1, x0:x1]
    return out


# ═══════════════════════════ 装载 ═══════════════════════════

def load_all(iso_path):
    font = D.load_font(iso_path)
    ad = font['atlas']
    w, h, psm = ad['w'], ad['h'], ad['psm']
    if (w, h, psm) != (W_EXP, H_EXP, 0x14):
        raise EdgeError('图集不是 1024x644 PSMT4（本工具只认 K2 几何）: %s' % ((w, h, psm),))
    A = RF.Atlas(ad['pak'], ad['px_off'], ad['px_size'], w, h, psm)
    tabs, ft_end = face_tables(font['ft_blob'])
    if [t[0] for t in tabs] != ['large', 'default', 'huge']:
        raise EdgeError('face 顺序变了: %s' % ([t[0] for t in tabs],))
    return font, A, tabs, ft_end


def read_elf_geom(iso_path):
    iso = tcslib.Iso(iso_path)
    try:
        out = {}
        for name, va in (('NCOL', 0x4170AC), ('SKIP_ROWS', 0x4170E8), ('Y0', 0x4170F8),
                         ('V1', 0x4170FC)):
            off = tcslib.ELF_ISO_BASE + va - tcslib.ELF_VA_BASE
            out[name] = struct.unpack_from('<I', iso.mm, off)[0] & 0xFFFF
        out['gate'] = tcslib.read_decode_gate(iso)
        return out
    finally:
        iso.close()


# ═══════════════════════════ ① FT 记录: 'X' 右缘搬家 ═══════════════════════════

def plan_ft(font, ink, tabs, log):
    """把 0x58 'X' 的记录矩形从 (1016,208,1024,224) 搬到安全货架，并搬像素。

    返回 (changes, pixel_src, pixel_dst, new_recs) —— 只算不写。
    """
    idx = X_CODE - 0x20
    olds = []
    for (nm, fld, off, nrec) in tabs:
        if idx >= nrec:
            raise EdgeError('face %s 的 nrec=%d 装不下 0x%02X' % (nm, nrec, X_CODE))
        r = rec_at(font['ft_blob'], off + idx * 10)
        olds.append((nm, off + idx * 10, r))
    base = olds[1][2]                            # default face 为准
    if base[2:] != (1016, 208, 1024, 224):
        raise EdgeError('0x58 的矩形不是预期的 (1016,208,1024,224): %s'
                        % ([(o[0], o[2]) for o in olds],))
    if len({o[2][2:] for o in olds}) != 1:
        raise EdgeError('三 face 的 0x58 矩形不一致: %s' % ([(o[0], o[2]) for o in olds],))
    src = win(ink, 1016, 208, 8, 16)
    if not src.any():
        raise EdgeError('0x58 的旧矩形里没有墨 —— 盘不对?')

    # 落点: ASCII 货架 (y=627..643) 里 T(0x54) 之后的第一个 8x16 空格
    protect2 = np.zeros_like(ink)
    for (nm, fld, off, nrec) in tabs:
        for r in range(nrec):
            b0, b1, u0, v0, u1, v1 = rec_at(font['ft_blob'], off + r * 10)
            if u1 > u0 and v1 > v0:
                protect2[max(0, v0):min(H_EXP, v1), max(0, u0):min(W_EXP, u1)] = True
    tgt = None
    for x in range(0, W_EXP - 8 + 1, 8):
        if x + 8 + tcslib.GLYPH_TOL_X > W_EXP:
            break
        if protect2[627:643, x:x + 8].any():
            continue
        if ink[627:643, x:x + 8].any():
            continue
        if ink[627 - tcslib.GLYPH_TOL_Y:643 + tcslib.GLYPH_TOL_Y,
               x - tcslib.GLYPH_TOL_X:x + 8 + tcslib.GLYPH_TOL_X].any():
            continue
        tgt = (x, 627)
        break
    if tgt is None:
        raise EdgeError('货架上找不到 8x16 空格放 X')
    dst = win(ink, tgt[0], tgt[1], 8, 16)
    if dst.any():
        raise EdgeError('X 的落点 (x=%d) 不是空的' % tgt[0])
    log('  [FT] 0x58 X: rect (1016,208,1024,224) u1=1024 ✗ ⇒ 搬到 (%d,%d,%d,%d) u1=%d ✓'
        % (tgt[0], tgt[1], tgt[0] + 8, tgt[1] + 16, tgt[0] + 8))
    changes = [dict(face=nm, off=roff, code=X_CODE, old=list(r), new=None)
               for (nm, roff, r) in olds]
    return changes, (1016, 208), tgt, src


def apply_ft(blob, changes, tgt):
    for c in changes:
        b0, b1, _u0, _v0, _u1, _v1 = c['old']
        put_rec(blob, c['off'], b0, b1, tgt[0], tgt[1], tgt[0] + 8, tgt[1] + 16)
        c['new'] = list(rec_at(blob, c['off']))


# ═══════════════════════════ ② 对偶码: col-63 槽整体换位 ═══════════════════════════

def count_refs(iso_path, cs, cache=None, log=print):
    """**文本载荷口径**的字符引用计数 → (ui_refs, mis_refs)。

    ui  = `EN_STRINGS.RES@MENU/@GR` 的**条目载荷** + `EN_SPECIAL_FEATURE.XML` 解码文本；
    mis = `.MIS` 家族容器展开后的解码文本（背景噪声高，只作辅助判据）。

    ★ 为什么不用"裸字节 count": 容器**结构区**（长度前缀/属性/数值字段）里也会出现
      合法对偶码字节对，裸扫会把它们算成"引用"（实测把保留段 463 条里的 239 条误判成有引用）。
    """
    if cache and os.path.isfile(cache):
        with io.open(cache, encoding='utf-8') as fh:
            d = json.load(fh)
        if 'refs' in d:
            log('  [引用] 复用缓存 %s (UI %d 字符 / MIS %d 字符)'
                % (rel(cache), len(d['refs']), len(d.get('mis') or {})))
            return d['refs'], d.get('mis') or {}
    import collections
    ui = collections.Counter()
    mis = collections.Counter()
    iso = tcslib.Iso(iso_path)
    try:
        for (lba, idx, tag) in ((tcslib.MENU_LBA, tcslib.LANG_MENU_IDX, 'RES@MENU'),
                                (tcslib.GR_LBA, tcslib.LANG_GR_IDX, 'RES@GR')):
            e = iso.img_entry(lba, idx)
            raw = iso.read(e['iso_off'], e['stored'])
            subs = tcslib.lzo_subs(raw)
            blob = b''.join(s[0] for s in subs) if subs else raw
            ents, _used = tcslib.parse_lang(blob)
            for ent in ents:
                ui.update(cs.decode(ent.data)[0])
        e = iso.img_entry(tcslib.MENU_LBA, tcslib.XML_IDX)
        raw = iso.read(e['iso_off'], e['stored'])
        subs = tcslib.lzo_subs(raw)
        blob = b''.join(s[0] for s in subs) if subs else raw
        ui.update(cs.decode(blob)[0])
        for (tag, lba, idx, e2) in FC.enumerate_containers(iso):
            if not e2['name'].upper().endswith('.MIS'):
                continue
            s = FC.Slot(iso, tag, lba, idx)
            if s.blob:
                mis.update(cs.decode(s.blob)[0])
    finally:
        iso.close()
    d = dict(refs=dict(ui), mis=dict(mis),
             detail=dict(ui_chars=sum(ui.values()), mis_chars=sum(mis.values())))
    if cache:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with io.open(cache, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(d, fh, ensure_ascii=False, indent=1)
    log('  [引用] UI 载荷文本 %d 字符 / .MIS %d 字符 → 有引用的字符 UI %d / MIS %d'
        % (sum(ui.values()), sum(mis.values()), len(ui), len(mis)))
    return d['refs'], d['mis']


def plan_pairs(cs, ink, cells, cls, log, refs, mis):
    slot2ch = {}
    for ch, (b1, b2) in cs.enc_pair.items():
        slot2ch[tcslib.pair_slot(b1, b2)] = ch
    last = tcslib.NCOL - 1
    edge = [(s, slot2ch[s]) for s in sorted(slot2ch) if s % tcslib.NCOL == last]
    if len(edge) != 36:
        raise EdgeError('col-63 槽不是 36 个而是 %d 个 —— 这张盘的几何/码表不对' % len(edge))
    live, blank = [], []
    for (s, ch) in edge:
        x, y = cell_xy(s)
        (live if ink[y:y + CH, x:x + CW].any() else blank).append((s, ch))
    log('  [对偶] col-63: %d 槽 = 有字形 %d + 空占位 %d' % (len(edge), len(live), len(blank)))
    for (s, ch) in sorted(live):
        x, y = cell_xy(s)
        log('         %r slot=%-5d pair=%02X%02X cell=(%d,%d) ink=%d'
            % (ch, s, *cs.enc_pair[ch], x, y, int(ink[y:y + CH, x:x + CW].sum())))

    # 目标: 保留段里 PUA 占位 + "空 + usable + col != 63 + 0 墨 + **UI/MIS 双 0 引用**"
    #   ★ 0 引用是硬要求: 对家会被换到 col 63（引擎取不到的带），0 引用 ⇒ 永不采样 ⇒ 语义不变。
    cand = []
    for c in cells:
        s = c['slot']
        if c['col'] == last or s < RESERVED_LO or s > RESERVED_HI:
            continue
        if cls[s][0] != 'usable':
            continue
        if ink[c['y']:c['y'] + CH, c['x']:c['x'] + CW].any():
            continue
        ch = slot2ch.get(s)
        if ch is None or not (0xE000 <= ord(ch) <= 0xF8FF):
            continue
        if refs.get(ch, 0) != 0 or mis.get(ch, 0) != 0:
            continue
        cand.append(s)
    cand.sort()
    if len(cand) < len(edge):
        raise EdgeError('"PUA + 0 引用 + 空 + usable" 的安全空格只有 %d 个，不够 %d 个槽换位'
                        % (len(cand), len(edge)))
    targets = cand[:len(edge)]
    log('  [对偶] 对家候选 (PUA 占位 / UI+MIS 双 0 引用): %d 个 → 取前 %d 个 slot %d..%d'
        % (len(cand), len(targets), targets[0], targets[-1]))
    swap = {}
    for (s, ch), t in zip(edge, targets):
        swap[s] = t
        swap[t] = s
    if len(swap) != 2 * len(edge):
        raise EdgeError('换位表不是单射')
    moves = []
    for (s, ch), t in zip(edge, targets):
        moves.append(dict(char=ch, old_slot=s, new_slot=t,
                          old_code='%02X%02X' % cs.enc_pair[ch],
                          new_code='%02X%02X' % tcslib.pair_from_slot(t),
                          old_cell=list(cell_xy(s)), new_cell=list(cell_xy(t)),
                          partner=slot2ch[t],
                          partner_code_old='%02X%02X' % cs.enc_pair[slot2ch[t]],
                          partner_code_new='%02X%02X' % tcslib.pair_from_slot(s),
                          ink=int(ink[cell_xy(s)[1]:cell_xy(s)[1] + CH,
                                     cell_xy(s)[0]:cell_xy(s)[0] + CW].sum())))
    for m in moves:
        log('         %r %s→%s (slot %d→%d) 置换出 %r (%s→%s)'
            % (m['char'], m['old_code'], m['new_code'], m['old_slot'], m['new_slot'],
               m['partner'], m['partner_code_old'], m['partner_code_new']))
    return moves, swap, live, blank


def build_target(ink, moves, swap, ft_src, ft_dst, ft_pix):
    En = ink.copy()
    # ① FT: X 的像素搬到新家, 旧矩形清零
    En[ft_src[1]:ft_src[1] + 16, ft_src[0]:ft_src[0] + 8] = False
    En[ft_dst[1]:ft_dst[1] + 16, ft_dst[0]:ft_dst[0] + 8] = ft_pix
    # ② 对偶: 参与换位的格全部先清零, 再把有字形的搬到新格
    for s in swap:
        x, y = cell_xy(s)
        En[y:y + CH, x:x + CW] = False
    for m in moves:
        ox, oy = m['old_cell']
        nx, ny = m['new_cell']
        pix = ink[oy:oy + CH, ox:ox + CW]
        if pix.any():
            En[ny:ny + CH, nx:nx + CW] = pix
    return En


# ═══════════════════════════ ③ charset JSON (文本级最小编辑) ═══════════════════════════

def charset_text_patch(cs_path, pair_new, meta, log):
    """只改 `pair_of` 里变了的那些 `[lead, trail]`，再追加一节元信息；不整体重写 JSON。"""
    with io.open(cs_path, encoding='utf-8', newline='') as f:
        s = f.read()
    cs_obj = json.loads(s)
    old_pairs = {k: tuple(v) for k, v in cs_obj['pair_of'].items()}
    changed = [ch for ch in old_pairs if tuple(pair_new[ch]) != old_pairs[ch]]
    n_edit = 0
    for ch in changed:
        lead, trail = pair_new[ch]
        key = json.dumps(ch, ensure_ascii=False)          # 带引号, 与 json.dump 的键写法一致
        pat = re.compile(r'(\n  %s: \[\n   )(\d+)(,\n   )(\d+)(\n  \])' % re.escape(key))
        s2, n = pat.subn(lambda m: '%s%d%s%d%s' % (m.group(1), lead, m.group(3), trail,
                                                   m.group(5)), s, count=1)
        if n != 1:
            raise EdgeError('charset 文本级改写失败: %r (匹配 %d 次)' % (ch, n))
        s = s2
        n_edit += 1
    # 追加元信息 (幂等: 已有同名节就整体替换)
    meta_s = json.dumps(meta, ensure_ascii=False, indent=2).replace('\n', '\n    ')
    key = '_glyph_edge_zh130'
    if '"%s"' % key in s:
        s = re.sub(r',?\n  "%s": \{.*?\n  \}(?=,|\n\})' % key,
                   ',\n  "%s": %s' % (key, meta_s), s, count=1, flags=re.S)
    else:
        # 插到最后一个顶层键之前 (即 JSON 收尾 '}' 之前)
        idx = s.rstrip().rfind('}')
        head, tail = s[:idx].rstrip(), s[idx:]
        s = head + ',\n  "%s": %s\n' % (key, meta_s) + tail
    # 回读校验: 只有这 72 条 pair 变了, 其它字段逐字节等价
    back = json.loads(s)
    b_new = {k: tuple(v) for k, v in back['pair_of'].items()}
    if {k for k in b_new if b_new[k] != old_pairs.get(k)} != set(changed):
        raise EdgeError('charset 回读: 变动的 pair 条目集合与计划不符')
    if b_new != {k: tuple(v) for k, v in pair_new.items()}:
        raise EdgeError('charset 回读: pair_of 与目标不符')
    for k in ('codes', 'grid', 'mode'):
        if back.get(k) != cs_obj.get(k):
            raise EdgeError('charset 回读: %s 被动了' % k)
    log('  [charset] 文本级改写 %d 条 pair_of + 追加节 %s (%d B → %d B)'
        % (n_edit, key, len(open(cs_path, 'rb').read()), len(s.encode('utf-8'))))
    return s, changed


# ═══════════════════════════ 主流程 ═══════════════════════════

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--iso', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--charset', default=os.path.join(REPO, 'tools', 'final_fix', 'assets', 'charset',
                                        'charset_compiled_zh16.json'),
                    help='**源盘那一代**的 charset JSON (描述输入盘的码位)')
    ap.add_argument('--charset-out', default=None,
                    help='新版 charset 写到哪里 (缺省 = 原地写回 --charset, 并先存 .before_zh130 备份)')
    ap.add_argument('--report', default=None)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--no-charset-write', action='store_true')
    ap.add_argument('--skip-scan', action='store_true',
                    help='跳过全盘重编码扫描 (只改图集/记录; 供几何试跑用)')
    ap.add_argument('--refs-cache', default=os.path.join(REPO, 'work', 'builds', 'GR_GLYPHFIX',
                                                         'out', 'refs_payload.json'),
                    help='文本载荷口径的字符引用计数缓存 (两次跑复用, 省一遍全盘解码)')
    ap.add_argument('--exclude-container', action='append', default=[],
                    help='登记为"二进制巧合"的容器 (TAG#idx NAME 或裸文件名; 可多次)')
    a = ap.parse_args(argv)
    LOG = []

    def log(s=''):
        print(s, flush=True)
        LOG.append(s)

    t_iso = a.iso
    log('=' * 100)
    log('%s — 修“采样矩形压到贴图右缘 (x+w==1024)”的乱码' % TOOL)
    log('  输入 %s' % rel(t_iso))
    sha_in = sha256_file(t_iso)
    log('  sha256 %s' % sha_in)
    geom = read_elf_geom(t_iso)
    log('  ELF 几何: NCOL=%d SKIP_ROWS=%d Y0=%d V1=%d gate=0x%02X'
        % (geom['NCOL'], geom['SKIP_ROWS'], geom['Y0'], geom['V1'], geom['gate']))
    if (geom['NCOL'], geom['SKIP_ROWS'], geom['Y0']) != (64, 2, 3):
        raise EdgeError('ELF 几何不是 K2 (64/2/3): %s' % (geom,))

    font, A, tabs, ft_end = load_all(t_iso)
    w, h = A.w, A.h
    ink = A.eng.copy()
    with io.open(a.charset, encoding='utf-8') as fh:
        _csj = json.load(fh)
    if '_glyph_edge_zh130' in _csj:
        raise EdgeError('--charset %s **已经是打过本补丁的**码表 (含 _glyph_edge_zh130)。\n'
                        '   本工具需要"源盘那一代"的 charset —— 请用备份 '
                        '%s.before_zh130。' % (rel(a.charset), rel(a.charset)))
    cs = tcslib.Charset(a.charset)
    log('  charset %s : pair_of=%d codes=%d' % (rel(a.charset), len(cs.enc_pair),
                                                len(cs.codes)))

    # ---- ① FT 'X' ----
    ft_changes, ft_src, ft_dst, ft_pix = plan_ft(font, ink, tabs, log)
    ft_blob = bytearray(font['ft_blob'])
    apply_ft(ft_blob, ft_changes, ft_dst)
    # 记录改写后的保护掩码 (分类用最终态)
    faces_new = [(nm, fld, [rec_at(ft_blob, off + r * 10) for r in range(nrec)])
                 for (nm, fld, off, nrec) in tabs]
    protect, rects = RF.protect_mask(faces_new, w, h)

    # ---- ② 对偶 col-63 ----
    cells = RF.enumerate_cells(w, h)
    cls = RF.classify(cells, protect, w, h)
    refs, mis = count_refs(t_iso, cs, cache=a.refs_cache, log=log)
    moves, swap, live, blank = plan_pairs(cs, ink, cells, cls, log, refs, mis)

    # ---- ③ 目标图 ----
    En = build_target(ink, moves, swap, ft_src, ft_dst, ft_pix)
    # 写盘前自检
    prot_old = np.zeros_like(ink)
    for (nm, fld, off, nrec) in tabs:
        for r in range(nrec):
            b0, b1, u0, v0, u1, v1 = rec_at(font['ft_blob'], off + r * 10)
            if u1 > u0 and v1 > v0:
                prot_old[max(0, v0):min(h, v1), max(0, u0):min(w, u1)] = True
    for m in moves:
        ox, oy = m['old_cell']
        nx, ny = m['new_cell']
        if not np.array_equal(En[ny:ny + CH, nx:nx + CW], ink[oy:oy + CH, ox:ox + CW]):
            raise EdgeError('%r 的字形没有原样落到新格' % (m['char'],))
        if En[oy:oy + CH, ox:ox + CW].any():
            raise EdgeError('%r 的旧格没有清干净' % (m['char'],))
    if not np.array_equal(En[ft_dst[1]:ft_dst[1] + 16, ft_dst[0]:ft_dst[0] + 8], ft_pix):
        raise EdgeError('X 的字形没有原样落到新矩形')
    if En[ft_src[1]:ft_src[1] + 16, ft_src[0]:ft_src[0] + 8].any():
        raise EdgeError('X 的旧矩形没有清干净')
    n_px = int((En != ink).sum())
    log('  [图集] 计划改动 %d 像素 (墨量 %d → %d)' % (n_px, int(ink.sum()), int(En.sum())))

    # ---- ④ 码位 ----
    pair_new = dict(cs.enc_pair)
    for m in moves:
        pair_new[m['char']] = tcslib.pair_from_slot(m['new_slot'])
        pair_new[m['partner']] = tcslib.pair_from_slot(m['old_slot'])
    if len(set(pair_new.values())) != len(set(cs.enc_pair.values())):
        raise EdgeError('新码位不是单射 (有撞码)')
    for ch, (b1, b2) in pair_new.items():
        if not (tcslib.LEAD_LO <= b1 < tcslib.LEAD_HI):
            raise EdgeError('%r 的新 lead 0x%02X 越界' % (ch, b1))
        if b2 in (0xB1, 0xB5):
            raise EdgeError('%r 的新 trail 落在图标码 0xB1/0xB5' % (ch,))
    cs_new = FC.charset_view(cs, pair_new)
    cmap = FC.CodeMap(cs, cs_new)
    log('  [码位] 变化 pair 码位 %d 个 (36 对换位); codes(单字节) 0 改动'
        % len(cmap.changed_pairs))

    res = dict(cs=cs, cs_new=cs_new, cmap=cmap, atlas=A, target=En, font=font,
               charset_path=a.charset, code_changes=[], n_used=len(pair_new),
               pair_new=pair_new, migration=None,
               exclude_text_containers=set(a.exclude_container or []),
               exclude_reason=('压缩位图 (.BMZ) 的解压流偶然通过 texty() 判据；'
                               '它不参与文本渲染，且槽位重压超槽 ⇒ 显式登记为二进制巧合'))

    # ---- ⑤ 全盘重编码方案 ----
    re = None
    if a.skip_scan:
        re = dict(writes=[], units=[], scan={})
        log('  [重编码] --skip-scan ⇒ 跳过 (只试几何)')
    else:
        log('  [重编码] 用 font_compact.plan_reencode 规划全盘文本重编码 …')
        iso_o = tcslib.Iso(t_iso)
        try:
            re = FC.plan_reencode(iso_o, res, verbose=True)
        finally:
            iso_o.close()
        log('  [重编码] 要写回的容器 %d 个' % len(re['writes']))

    # ---- ⑥ 写盘 ----
    rep = dict(tool=TOOL, round=ROUND, src=rel(t_iso), src_sha256=sha_in,
               geometry=geom, charset=rel(a.charset), charset_sha256=sha256_file(a.charset),
               atlas=dict(w=w, h=h, psm=A.psm, px_size=A.px_size, nseg=len(A.segs),
                          pixels_changed=n_px, ink_before=int(ink.sum()),
                          ink_after=int(En.sum())),
               ft=[dict(face=c['face'], code='%02X' % c['code'], old=c['old'], new=c['new'])
                   for c in ft_changes],
               pair_moves=moves, n_pair_moves=len(moves),
               changed_pair_codes=len(cmap.changed_pairs),
               reencode=dict(writes=[dict(key='%s#%d' % (w_['lba'], w_['idx']) if 'lba' in w_
                                          else '?', 
                                          iso_off=w_['iso_off'], stored=w_.get('stored'),
                                          frame_bytes=w_.get('frame_bytes'),
                                          raw=bool(w_.get('raw')),
                                          detail=w_.get('detail'))
                                 for w_ in re['writes']]) if re else None)
    if a.dry_run:
        log('')
        log('[dry-run] 不写盘。计划如上。')
        if a.report:
            with io.open(a.report, 'w', encoding='utf-8', newline='\n') as fh:
                json.dump(rep, fh, ensure_ascii=False, indent=1)
            log('  报告 → %s' % rel(a.report))
        return 0

    # 真写: 先写盘, 再跑门禁; 门禁不过 ⇒ 删产物
    empty, _tot = A.empty_index()
    A.write_pixels(*np.where(En != A.eng), En[(En != A.eng)], empty)
    hdr_before = A.headers()
    for (doff, hb) in hdr_before:
        if bytes(A.cont[doff - tcslib.ATLAS_PREFIX_BYTES:doff]) != hb:
            raise EdgeError('48B 包头被改了 (doff=0x%X)' % doff)
    # FONT.RES 帧
    iso_src = tcslib.Iso(t_iso)
    try:
        ft_slot = FC.Slot(iso_src, 'MENU.IMG', tcslib.MENU_LBA, font['ft_idx'])
    finally:
        iso_src.close()
    ft_frame, n_rep, ft_len, ft_method = ft_slot.repack(bytes(ft_blob), 'FONT.RES')
    log('  [FONT.RES] 帧 %d B / 槽 %d B (方法 %s, 重压子流 %d)'
        % (ft_len, ft_slot.slot, ft_method, n_rep))
    if ft_len > ft_slot.slot:
        raise EdgeError('FONT.RES 帧超槽')

    if os.path.abspath(t_iso) == os.path.abspath(a.out):
        raise EdgeError('--out 不能等于 --iso')
    shutil.copyfile(t_iso, a.out)
    pak_e = font['pak_e']
    ft_e = font['ft_e']
    px_off = font['atlas']['px_off']
    px_size = font['atlas']['px_size']
    # 冲突检查: 重编码容器不得压到图集容器 / FONT.RES
    c_lo, c_hi = pak_e['iso_off'], pak_e['iso_off'] + pak_e['stored']
    f_lo, f_hi = ft_e['iso_off'], ft_e['iso_off'] + ft_e['stored']
    for w_ in re['writes']:
        lo, hi = w_['iso_off'], w_['iso_off'] + w_.get('stored', len(w_['frame']))
        if (lo < c_hi and c_lo < hi) or (lo < f_hi and f_lo < hi):
            raise EdgeError('重编码容器与图集/FONT.RES 槽重叠: 0x%X..0x%X' % (lo, hi))
    # ★ 图集像素容器在 COMMON.PAK **记录内部** ⇒ 必须写 pak_e.iso_off + px_off
    with open(a.out, 'r+b') as f:
        f.seek(pak_e['iso_off'] + px_off)
        f.write(bytes(A.cont))
        for w_ in re['writes']:
            if w_.get('raw'):
                f.seek(w_['iso_off'])
                f.write(w_['frame'])
            else:
                FC.Slot.write(f, w_['iso_off'], w_['stored'], w_['frame'])
        FC.Slot.write(f, ft_e['iso_off'], ft_e['stored'], ft_frame)
    if os.path.getsize(t_iso) != os.path.getsize(a.out):
        raise EdgeError('ISO 尺寸变了')
    sha_out = sha256_file(a.out)
    log('  [写盘] %s  %d B  sha256 %s' % (rel(a.out), os.path.getsize(a.out), sha_out))
    rep['out'] = rel(a.out)
    rep['out_sha256'] = sha_out

    # ---- ⑦ 门禁 (从盘上回读) ----
    try:
        gate = run_gates(a.out, t_iso, font, A, tabs, ft_changes, ft_src, ft_dst, ft_pix,
                         moves, En, cs, cs_new, cmap, re, ft_e, log)
    except EdgeError:
        log('  [!!] 门禁不过 ⇒ 删除产物 %s' % rel(a.out))
        try:
            os.remove(a.out)
        except OSError:
            pass
        raise
    rep['gates'] = gate
    if a.report:
        with io.open(a.report, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=1)
        log('  报告 → %s' % rel(a.report))
    if not a.no_charset_write and not a.skip_scan:
        meta = dict(note=('★ %s: 修“采样矩形右缘 == 贴图宽度 (1024) ⇒ 引擎取不到”的乱码。'
                          '36 个 col-63 槽 (含 约 slot639 / 金 slot703) 与占位字符换位, '
                          'X 的 FT 矩形搬到 (%d,%d)-(%d,%d); 盘上全部文本逐字重编码。'
                          % (ROUND, ft_dst[0], ft_dst[1], ft_dst[0] + 8, ft_dst[1] + 16)),
                    tool=TOOL, src_sha256=sha_in, out_sha256=sha_out,
                    atlas=dict(w=w, h=h, psm=A.psm, px_size=A.px_size, nseg=len(A.segs)),
                    ft_0x58=dict(old=[1016, 208, 1024, 224], new=[ft_dst[0], ft_dst[1],
                                                                 ft_dst[0] + 8, ft_dst[1] + 16]),
                    pair_moves=[dict(char=m['char'], old=m['old_code'], new=m['new_code'],
                                     old_slot=m['old_slot'], new_slot=m['new_slot'],
                                     old_cell=m['old_cell'], new_cell=m['new_cell'])
                                for m in moves],
                    changed_pair_codes=len(cmap.changed_pairs),
                    reencode_containers=len(re['writes']),
                    safe_u1=SAFE_U1, gate=geom['gate'])
        s_new, changed = charset_text_patch(a.charset, pair_new, meta, log)
        if changed:
            cs_out = a.charset_out or a.charset
            if os.path.abspath(cs_out) == os.path.abspath(a.charset):
                bak = a.charset + '.before_zh130'
                if not os.path.isfile(bak):
                    shutil.copyfile(a.charset, bak)
                    log('  [charset] 源码表备份 → %s' % rel(bak))
            with io.open(cs_out, 'w', encoding='utf-8', newline='\n') as fh:
                fh.write(s_new)
            rep['charset_out'] = rel(cs_out)
            log('  [charset] 已写回 %s' % rel(cs_out))
    log('')
    log('OK — %s' % rel(a.out))
    return 0


# ═══════════════════════════ 门禁 ═══════════════════════════

def run_gates(dst, src, font, A0, tabs, ft_changes, ft_src, ft_dst, ft_pix, moves, En,
              cs, cs_new, cmap, re, ft_e, log):
    out = []

    def chk(name, cond, detail):
        out.append(dict(check=name, ok=bool(cond), detail=detail))
        log('  [%s] %-44s %s' % ('门禁 ✓' if cond else '门禁 ✗', name, detail))
        if not cond:
            raise EdgeError('门禁不过: %s (%s)' % (name, detail))

    # ---- ① 三闸门 ----
    w, h, px = A0.w, A0.h, A0.px_size
    chk('图集闸门 w ≤ 1024', w <= 1024, 'w=%d' % w)
    chk('图集闸门 px_size == w*h/2+16', px == w * h // 2 + 16, '%d == %d' % (px, w * h // 2 + 16))
    chk('图集闸门 (w*h/2) %% 2048 == 0', (w * h // 2) % 2048 == 0, '%d %% 2048 == %d'
        % (w * h // 2, (w * h // 2) % 2048))
    # ---- ② 回读图集 ----
    font2, A2, tabs2, ft_end2 = load_all(dst)
    chk('图集回读 == 目标图 (逐 texel)', np.array_equal(A2.eng, En),
        '%d texel 与源盘不同 (计划值 %d)' % (int((A2.eng != A0.eng).sum()),
                                            int((En != A0.eng).sum())))
    chk('48B 包头逐字节不变',
        [bytes(A2.cont[d - 48:d]) for (_f, d, _n) in A2.segs] ==
        [hb for (_d, hb) in A0.headers()], '%d 段' % len(A2.segs))
    # ---- ③ 搬运 ----
    bad = []
    for m in moves:
        ox, oy = m['old_cell']
        nx, ny = m['new_cell']
        if not np.array_equal(A2.eng[ny:ny + CH, nx:nx + CW], A0.eng[oy:oy + CH, ox:ox + CW]):
            bad.append(m['char'])
        if A2.eng[oy:oy + CH, ox:ox + CW].any():
            bad.append('%s(旧格未清)' % m['char'])
    chk('搬运字形逐 texel 相等 + 旧格清零', not bad, '%d 个槽' % len(moves))
    # ---- ④ FT 记录 ----
    blob2 = bytearray(font2['ft_blob'])
    other_changed = []
    for (nm, fld, off, nrec) in tabs:
        (nm2, fld2, off2, nrec2) = [t for t in tabs2 if t[0] == nm][0]
        if (off, nrec) != (off2, nrec2):
            raise EdgeError('FACE 表结构变了')
        for r in range(nrec):
            if rec_at(font['ft_blob'], off + r * 10) != rec_at(bytes(blob2), off2 + r * 10):
                code = r + 0x20
                if code != X_CODE:
                    other_changed.append((nm, code, rec_at(font['ft_blob'], off + r * 10),
                                          rec_at(bytes(blob2), off2 + r * 10)))
    chk('FT 记录: 只有 0x58 三面变', not other_changed, '%d 条意外改动' % len(other_changed))
    x_news = []
    for (nm, fld, off, nrec) in tabs2:
        r = rec_at(bytes(blob2), off + (X_CODE - 0x20) * 10)
        x_news.append(r)
        if r[2:6] != (ft_dst[0], ft_dst[1], ft_dst[0] + 8, ft_dst[1] + 16):
            raise EdgeError('0x58 新矩形不对: %s' % (r,))
        if r[5] > SAFE_U1:
            raise EdgeError('0x58 新矩形 u1=%d > %d' % (r[5], SAFE_U1))
    chk('0x58 新矩形 u1 ≤ 1008 (三面一致)', len({x[2:6] for x in x_news}) == 1,
        str(x_news[0][2:6]))
    chk('0x58 新矩形逐 texel == 旧矩形',
        np.array_equal(A2.eng[ft_dst[1]:ft_dst[1] + 16, ft_dst[0]:ft_dst[0] + 8], ft_pix),
        'ink=%d' % int(ft_pix.sum()))
    chk('0x58 旧矩形已清零',
        not A2.eng[ft_src[1]:ft_src[1] + 16, ft_src[0]:ft_src[0] + 8].any(), '(1016,208,1024,224)')
    # ASCII 182 条
    n_ascii = same = 0
    for (nm, fld, off, nrec) in tabs:
        for r in range(nrec):
            b0, b1, u0, v0, u1, v1 = rec_at(font['ft_blob'], off + r * 10)
            if u1 <= u0 or v1 <= v0 or not (0x21 <= r + 0x20 <= 0x9C):
                continue
            n_ascii += 1
            r2 = rec_at(bytes(blob2), off + r * 10)
            a = win(A0.eng, u0, v0, u1 - u0, v1 - v0)
            b = win(A2.eng, r2[2], r2[3], r2[4] - r2[2], r2[5] - r2[3])
            if np.array_equal(a, b):
                same += 1
    chk('ASCII 0x21..0x9C 记录逐 texel 与源盘相同', same == n_ascii, '%d/%d' % (same, n_ascii))
    # ---- ⑤ 文本逐字闭环 ----
    iso_s = tcslib.Iso(src)
    iso_d = tcslib.Iso(dst)
    n_cont = n_ok = 0
    tot_chg = 0
    try:
        for w_ in re['writes']:
            n_cont += 1
            if w_.get('raw'):
                newb = iso_d.read(w_['iso_off'], w_['frame_bytes'])
                oldb = iso_s.read(w_['iso_off'], w_['frame_bytes'])
                t_old, _ = cs.decode(oldb)
                t_new, _ = cs_new.decode(newb)
            else:
                raw_new = iso_d.read(w_['iso_off'], w_['stored'])
                raw_old = iso_s.read(w_['iso_off'], w_['stored'])
                subs_n = tcslib.lzo_subs(raw_new)
                subs_o = tcslib.lzo_subs(raw_old)
                newb = b''.join(s[0] for s in subs_n) if subs_n else raw_new
                oldb = b''.join(s[0] for s in subs_o) if subs_o else raw_old
                t_old, _ = cs.decode(oldb)
                t_new, _ = cs_new.decode(newb)
            if t_old != t_new:
                raise EdgeError('容器 %d 重编码后文本不一致' % n_cont)
            n_ok += 1
            tot_chg += w_['detail'].get('changed_bytes', 0)
    finally:
        iso_s.close()
        iso_d.close()
    chk('重写容器: 新解 == 旧解 (逐字)', n_ok == n_cont, '%d/%d 容器, 改动 %d B'
        % (n_ok, n_cont, tot_chg))
    # ---- ⑥ 载荷级旧码 0 (项目口径: LANG 条目载荷 + SFXML <text> 正文) ----
    #   ★ 结构区/陈旧尾巴里那 7+7 处裸 0xB1..0xB9 是**基底既有**（CAPACITY_2400 §5/§10.4
    #     "不许改，单列登记"）⇒ 单独比较"与源盘相同"，不计入本判据。
    gate_val = tcslib.read_decode_gate(tcslib.Iso(dst))

    def _payloads(tag, blob):
        if tag == 'SFXML':
            return [b for (_k, _o, _l, b) in tcslib.parse_sfxml(blob)]
        ents, _u = tcslib.parse_lang(blob)
        return [e.data for e in ents]

    def _counts(iso_obj):
        pay = tot = 0
        for (lba, idx, tag) in ((tcslib.MENU_LBA, tcslib.LANG_MENU_IDX, 'RES@MENU'),
                                (tcslib.GR_LBA, tcslib.LANG_GR_IDX, 'RES@GR'),
                                (tcslib.MENU_LBA, tcslib.XML_IDX, 'SFXML')):
            e = iso_obj.img_entry(lba, idx)
            raw = iso_obj.read(e['iso_off'], e['stored'])
            subs = tcslib.lzo_subs(raw)
            blob = b''.join(s[0] for s in subs) if subs else raw
            pair_table = cs_new.pair_of if iso_obj is iso_new else cs.pair_of
            tot += len(tcslib.scan_legacy_residue(blob, gate_val, pair_table))
            for pay_b in _payloads(tag, blob):
                pay += len(tcslib.scan_legacy_residue(pay_b, gate_val, pair_table))
        return pay, tot

    iso_new = tcslib.Iso(dst)
    iso_old = tcslib.Iso(src)
    try:
        pay_new, tot_new = _counts(iso_new)
        iso_new.close()
        pay_old, tot_old = _counts(iso_old)
    finally:
        iso_old.close()
    chk('载荷级旧码 0 (gate 0x%02X)' % gate_val, pay_new == 0,
        '载荷 %d 处 (源盘 %d) / 含结构区 %d 处' % (pay_new, pay_old, tot_new))
    chk('结构区/尾巴裸旧码与源盘相同 (不许改)',
        (tot_new - pay_new) == (tot_old - pay_old),
        '结构区 %d 处 (源盘 %d)' % (tot_new - pay_new, tot_old - pay_old))
    # ---- ⑦ 全盘字节普查 ----
    win_ok, n_diff, bad_off = census(src, dst, font, A0, re, ft_e, log)
    chk('全盘差异全部落在计划窗口内', not bad_off, '%d B 改动; 窗口外 %d' % (n_diff, len(bad_off)))
    # ---- ⑧ charset 侧 ----
    chk('pair_of 变化 = 72 (36 对)', len(cmap.changed_pairs) == 72,
        str(len(cmap.changed_pairs)))
    return out


def census(src, dst, font, A0, re, ft_e, log):
    """逐字节差异普查: 每个变动字节必须落在 图集容器/FONT.RES 槽/重写容器 之内。"""
    import mmap
    f = open(src, 'rb')
    g = open(dst, 'rb')
    a = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    b = mmap.mmap(g.fileno(), 0, access=mmap.ACCESS_READ)
    n = len(a)
    if n != len(b):
        raise EdgeError('尺寸不同')
    LO = 1 << 22
    bad = []
    n_diff = 0
    try:
        for base in range(0, n, LO):
            ca = a[base:base + LO]
            cb = b[base:base + LO]
            if ca == cb:
                continue
            m = len(ca)
            i = 0
            while i < m:
                if ca[i] == cb[i]:
                    i += 1
                    continue
                j = i
                while j < m and ca[j] != cb[j]:
                    j += 1
                n_diff += j - i
                if not _in_windows(base + i, base + j, font, re, ft_e):
                    bad.append(base + i)
                i = j
    finally:
        a.close()
        b.close()
        f.close()
        g.close()
    log('  [普查] 变动字节 %d ; 落在窗口外 %d' % (n_diff, len(bad)))
    return (not bad), n_diff, bad


def _in_windows(lo, hi, font, re, ft_e):
    pak_e = font['pak_e']
    c_lo = pak_e['iso_off'] + font['atlas']['px_off']
    c_hi = c_lo + font['atlas']['px_size']
    wins = [(c_lo, c_hi),
            (ft_e['iso_off'], ft_e['iso_off'] + ft_e['stored'])]
    for w_ in re['writes']:
        wins.append((w_['iso_off'], w_['iso_off'] + max(w_.get('stored') or 0,
                                                       w_.get('frame_bytes') or 0)))
    return any(a <= lo and hi <= b for (a, b) in wins)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except EdgeError as e:
        print('!! %s' % e, file=sys.stderr)
        sys.exit(2)
