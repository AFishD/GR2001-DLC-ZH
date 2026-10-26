# -*- coding: utf-8 -*-
r"""glyph_geometry.py — **字形几何体检** (round50): 每个在用字形的"墨迹包围盒 / 触边 / 丢行"结构化判据。

## 为什么需要它 (round50 的教训)

round46 的"错字检测"是**容差窗**口径: `tcslib.GlyphCache._check_record` 只要
「记录矩形 / 矩形+(4,2) / 矩形±(4,2)」三处**任一有墨**就算"画得出来"。
实测代价: 6 个**完全空白**的字被这圈 ±4/±2 的邻域墨"蒙"过去, 成了漏网之鱼。

round50 又发现第二种漏网: **字形整体少最后一行**(GR_ZH97 上 叶奋姚娜孙宁宇 7 个字)。
它既不空、也不越界、容差窗也照样"有墨" ⇒ 老判据永远发现不了。

## 本模块的判据 (全部**结构性**, 不含容差窗)

对每一个"引擎会采样"的 16×16 窗 (对偶格 / FT 记录矩形 / 图标码记录矩形), 都在
**引擎图** (`view='engine'`) 里量:

  ① `empty`      窗内一个墨点都没有                        → **错误**
  ② `sparse`     墨点 < SPARSE_MIN (默认 4)                → **警告**
  ③ `ink_out`    墨越出窗 (窗内触边 **且** 窗外紧邻行/列也有墨) → **错误**
  ④ `touch_*`    墨贴到窗的左/右/上/下边界                 → **提示** (模板能证清白就降级)
  ⑤ `tpl_lost`   **与 TTF 模板逐像素比对**: 模板有墨的整行在盘上**全空** → **错误**
                 (这就是 孙/宁/宇 那一类: 上 15 行逐像素吻合, 第 16 行整行不见了)
  ⑥ `tpl_miss`   模板比对的差异像素数 (紧阈值: 0 才算过)     → 超过 TPL_TOL → **警告**
  ⑦ `tpl_extra`  盘上有墨、模板没有 (渗漏/残墨)             → 超过 TPL_TOL → **警告**

模板来源 = `third_party/fonts/方正像素16.ttf` 的 16px em 窗 (`a[8:24, 8:24] < 128`),
与 `tools/font_pipeline/gen_font16.py::render16()` **同一配方** ⇒ 盘上字形本就该等于它。

## 与 dump_font 的关系

`dump_font.py` 在构筑时**自动调用**本模块, 把结果放进 `<版本>_font_summary.json` 的
`glyph_geometry` 段 ⇒ **以后每次 dump 都会自动发现**这类问题, 不用等人肉看 PNG。

独立跑 (出 `truncation_report.json` / `.md`):

    python tools/iso_build/scan_glyph_geometry.py --iso <盘> --out <目录> [--prefix X]

★ 本模块**只读**盘; 只往调用方给的目录写报告。
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))

import numpy as np                                       # noqa: E402
import tcslib                                            # noqa: E402

TOOL = 'tools/iso_build/glyph_geometry.py'
TOOL_VERSION = 'r50.1'
ROUND = 'round50'

CW = CH = tcslib.CW
NCOL = tcslib.NCOL
TTF = os.path.join(REPO, 'third_party', 'fonts', '方正像素16.ttf')
FACE_DEFAULT_NAME = 'default'     # = faces[1][0]; 现役盘引擎真正用的那一面 (tcslib.FONT_FACE_DEFAULT)

SPARSE_MIN = 4        # 墨点少于这个数 = 极稀 (几乎看不见)
TPL_TOL = 0           # 模板逐像素比对的容忍差异 (0 = 紧阈值; 见自检说明)
BLEED_ROWS = 1        # 窗外"紧邻"的行数 (判 ink_out 用)

# 分级 (报告里按这个顺序排)
LV_E, LV_W, LV_I = 'error', 'warn', 'info'
_LV_ORDER = {LV_E: 0, LV_W: 1, LV_I: 2}

# 每条判据的人话
RULE_TEXT = {
    'empty': '窗内一个墨点都没有 (这个字画出来是空白)',
    'sparse': '墨点极少 (几乎看不见)',
    'ink_out': '窗内触边 **且** 窗外紧邻还有"无主墨" (不属于任何采样窗) = 被窗外沿切掉/溢出',
    'tpl_lost_rows': '★与 16px 模板逐像素比对: 模板有墨的整行在盘上**全空** (丢行 = 被截断)',
    'row_shift': '★与模板比对: 字形整体**错位**了若干行 (错位把最下/最上的行推出了采样窗)',
    'tpl_miss': '与模板比对有差异像素 (盘上比模板**少**墨)',
    'tpl_extra': '与模板比对有差异像素 (盘上比模板**多**墨 = 渗漏/残墨)',
    'touch_left': '墨贴到窗的左边界',
    'touch_right': '墨贴到窗的右边界',
    'touch_top': '墨贴到窗的上边界',
    'touch_bottom': '墨贴到窗的下边界 (像素字库里这是正常的, 仅作提示)',
}


def rel(p):
    try:
        r = os.path.relpath(p, REPO)
    except ValueError:
        return p.replace('\\', '/')
    return r.replace('\\', '/') if not r.startswith('..') else p.replace('\\', '/')


# ═══════════════════════════ TTF 模板 ═══════════════════════════
#   配方与 tools/font_pipeline/gen_font16.py::render16() **完全一致**:
#     draw origin (8,8) → 取 canvas[8:24, 8:24] → 阈值 128。
#   ★ FALLBACK16 (® µ 蹚) 在方正像素16 里没有墨 ⇒ 盘上那三个字来自 13px 老图集块,
#     模板为空时**跳过**模板比对 (只做几何判据), 并在 tick 里如实标注。

class Templates(object):
    def __init__(self, ttf_path=None):
        self.path = ttf_path or TTF
        self.ok = os.path.isfile(self.path)
        self._fnt = None
        self._cache = {}
        self.no_ink = []            # 模板里没墨 (字体缺字) 的字
        if self.ok:
            from PIL import ImageFont
            self._fnt = ImageFont.truetype(self.path, 16)

    def get(self, ch):
        if not self.ok:
            return None
        if ch in self._cache:
            return self._cache[ch]
        from PIL import Image, ImageDraw
        img = Image.new('L', (32, 32), 255)
        ImageDraw.Draw(img).text((8, 8), ch, font=self._fnt, fill=0)
        win = np.asarray(img)[8:24, 8:24] < 128
        if not win.any():
            self.no_ink.append(ch)
            win = None
        self._cache[ch] = win
        return win


# ═══════════════════════════ 单个窗的体检 ═══════════════════════════

def _outside_ink(ink, cover, x, y, h, w, side):
    """窗外紧邻一圈里, 是否有**不属于任何别的采样窗**的墨 (真正的"溢出到没人管的地方")。

    ★ 为什么必须看 cover: 引擎采样窗是**紧挨着铺满**图集的 (col 与 col+1 相邻、
      行与行之间也是下一行的字形) ⇒ 单看"窗外有墨"会 100% 假报 (实测 GR_ZH98 假报 1019 个)。
      只有窗外那一像素**不被任何采样窗覆盖**时, "墨越界"才是真的越界。
    """
    hits = []
    if side in ('bottom', 'top'):
        yy = y + CH if side == 'bottom' else y - 1
        if not (0 <= yy < h):
            return False
        seg = ink[yy, max(0, x):min(w, x + CW)]
        cov = cover[yy, max(0, x):min(w, x + CW)]
        hits = seg & ~cov
    else:
        xx = x + CW if side == 'right' else x - 1
        if not (0 <= xx < w):
            return False
        seg = ink[max(0, y):min(h, y + CH), xx]
        cov = cover[max(0, y):min(h, y + CH), xx]
        hits = seg & ~cov
    return bool(hits.any())


def measure(ink, x, y, ch=None, tpls=None, h=None, w=None, cover=None):
    """量一个 16×16 采样窗 (引擎图坐标)。返回 dict(可 JSON 化)。

    ink   = 二维 bool (True=墨), 引擎图。x/y = 窗左上角, 允许越界 (越界部分按空算)。
    cover = "这个像素属于某个采样窗吗" 的 bool 掩码 (判 ink_out 用; None ⇒ 不判越窗)
    """
    h = ink.shape[0] if h is None else h
    w = ink.shape[1] if w is None else w
    pad = BLEED_ROWS
    y0, y1 = max(0, y), min(h, y + CH)
    x0, x1 = max(0, x), min(w, x + CW)
    win = np.zeros((CH, CW), bool)
    if y1 > y0 and x1 > x0:
        win[y0 - y:y1 - y, x0 - x:x1 - x] = ink[y0:y1, x0:x1]
    n = int(win.sum())
    out = dict(ink_px=n, bbox=None, flags=[], level=LV_I, missing_rows=[])
    ys, xs = np.where(win)
    if n:
        out['bbox'] = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
        out['fill_rows'] = int(len(set(ys.tolist())))
    else:
        out['fill_rows'] = 0

    if n == 0:
        out['flags'].append('empty')
    elif n < SPARSE_MIN:
        out['flags'].append('sparse')

    if n:
        if win[:, 0].any():
            out['flags'].append('touch_left')
        if win[:, CW - 1].any():
            out['flags'].append('touch_right')
        if win[0].any():
            out['flags'].append('touch_top')
        if win[CH - 1].any():
            out['flags'].append('touch_bottom')
        # 越窗 = 窗内触边 **且** 窗外紧邻的那一圈里有墨, 而那个像素**不属于任何别的采样窗**
        if cover is not None:
            for (edge, side) in ((win[CH - 1].any(), 'bottom'), (win[0].any(), 'top'),
                                 (win[:, CW - 1].any(), 'right'), (win[:, 0].any(), 'left')):
                if edge and _outside_ink(ink, cover, x, y, h, w, side):
                    out['flags'].append('ink_out')
                    break

    # ---- 模板逐像素比对 (紧阈值) + 行错位估计 ----
    if tpls is not None and ch is not None and len(ch) == 1:
        t = tpls.get(ch)
        out['tpl'] = 'none'
        if t is not None:
            out['tpl'] = 'compared'
            tpl_ink = int(t.sum())
            out['tpl_ink_px'] = tpl_ink
            miss = int((t & ~win).sum())          # 模板有墨、盘上没有
            extra = int((win & ~t).sum())         # 盘上有墨、模板没有
            out['tpl_miss'] = miss
            out['tpl_extra'] = extra
            # ★ 行错位 dy: 盘上第 r 行 == 模板第 r-dy 行 ⇒ dy>0 = 字形整体**低**了 dy 行
            dy, score = _row_shift(win, t)
            out['row_shift'] = dy
            out['row_shift_score'] = score
            if dy:
                out['flags'].append('row_shift')
                if 'tpl_miss' not in out['flags']:
                    out['flags'].append('tpl_miss')
            # 该错位下, 模板里那些**永远看不到**的行 (被推出采样窗)
            if dy:
                out['rows_pushed_out'] = [r for r in range(CH)
                                          if t[r].any() and not (0 <= r - dy < CH)]
            if miss > TPL_TOL and 'tpl_miss' not in out['flags']:
                out['flags'].append('tpl_miss')
            if extra > TPL_TOL:
                out['flags'].append('tpl_extra')
            # ★ 丢行: 模板某一行有墨, 盘上那一行**整行空**
            lost = [r for r in range(CH) if t[r].any() and not win[r].any()]
            if lost:
                out['missing_rows'] = lost
                out['flags'].append('tpl_lost_rows')
    return out


def _row_shift(win, t, maxd=3):
    """盘上窗 vs 模板的**行错位**。返回 (dy, 命中率)。

    dy > 0 ⇒ 盘上第 r 行 ≈ 模板第 r-dy 行 ⇒ 字形整体比模板**低** dy 行
              (最下的 dy 行被推出 16 行采样窗 ⇒ 看不见 = 截断)。
    dy < 0 ⇒ 字形整体**高** dy 行 (最上的 |dy| 行被推出)。
    """
    best, best_score = 0, -1.0
    for dy in range(-maxd, maxd + 1):
        inter = union = 0
        for r in range(CH):
            rr = r - dy
            if 0 <= rr < CH:
                inter += int((win[r] & t[rr]).sum())
                union += int((win[r] | t[rr]).sum())
        if union == 0:
            continue
        sc = float(inter) / union
        if sc > best_score + 1e-9:
            best_score, best = sc, dy
    return best, round(max(best_score, 0.0), 3)


def _level(flags):
    if 'empty' in flags or 'ink_out' in flags or 'tpl_lost_rows' in flags:
        return LV_E
    if 'row_shift' in flags or 'sparse' in flags or 'tpl_miss' in flags or 'tpl_extra' in flags:
        # tpl_miss/extra 只有超过容差才会进 flags (见 measure)
        return LV_W
    return LV_I


# ═══════════════════════════ 全盘体检 ═══════════════════════════

def _empty_record_reason(face_name, face_idx, code, cs):
    """FT 记录矩形为空 ⇒ 这**正常吗**? 返回 (level, 人话原因)。

    ★ 实测 GR_ZH98 有 38 条空记录, 全部有正当理由 (不是坏字形):
        · 0x20 空格 —— 本来就该是空的;
        · 0x7F 未分配 —— 引擎不会去画;
        · 0xA1..0xAD 是**对偶 lead** —— 它们不是单字节码, 记录位是占位;
        · 0xB1/0xB5 —— 引擎认的**文本图标码** (DrawString v1 里写死), 走另一张贴图, 不吃字库;
        · 0xAE 之类 —— 见 charset 的 codes (有映射却没墨 ⇒ 才该报警)。
      只有「default face + 可打印 ASCII / charset 里真有映射的单字节码」为空, 才算 **错误**。
    """
    if code == 0x20:
        return LV_I, '空格记录 —— 本来就该是空的'
    if code == 0x7F:
        return LV_I, '0x7F 未分配记录 —— 引擎不会去画'
    if tcslib.PAIR_LEAD_LO <= code < tcslib.PAIR_LEAD_HI:
        return LV_I, ('0x%02X 是**对偶 lead** (不是单字节码) —— 记录位只是占位' % code)
    try:
        import icon_table
        if icon_table.is_icon(code):
            return LV_I, ('0x%02X 是引擎认的**文本图标码** (%s) —— 走硬编码 UV 的另一张贴图, '
                          '不吃字库' % (code, icon_table.icon_name(code)))
    except Exception:                                                # noqa: BLE001
        pass
    if face_idx != tcslib.FONT_FACE_DEFAULT:
        return LV_I, ('该空记录在 `%s` face 里 —— 现役盘引擎用的是 `%s` face (#%d), 这一面不参与显示'
                      % (face_name, FACE_DEFAULT_NAME, tcslib.FONT_FACE_DEFAULT))
    if cs is not None and code in cs.codes:
        return LV_E, ('default face 里 0x%02X 是 charset 映射的单字节码 (%r), 但记录矩形是空的 '
                      '⇒ 这个字画出来是空白' % (code, cs.codes[code]))
    if 0x21 <= code <= 0x7E:
        return LV_E, ('default face 里可打印 ASCII 0x%02X (%r) 的记录矩形是空的 '
                      '⇒ 这个字符画出来是空白' % (code, chr(code)))
    return LV_I, '没有映射的空记录 —— 引擎不会去画它'


def analyze(gray, atlas, faces, cs, iso_path=None, iso_sha256=None, ttf_path=None,
            verbose=False, strict_template=True):
    """扫描**全部引擎采样窗** ⇒ 结构化体检结果 (可直接塞进 summary.json)。

    · gray   = `dump_font.atlas_gray(font['atlas'], view='engine')` 的字节 (0=墨)
    · atlas  = `font['atlas']` (需要 w/h)
    · faces  = `font['faces']`  (FT 记录表)
    · cs     = `tcslib.Charset`
    """
    w, h = atlas['w'], atlas['h']
    ink = (np.frombuffer(gray, np.uint8).reshape(h, w) == 0)
    tpls = Templates(ttf_path) if strict_template else None
    rows = []

    # ── 采样窗覆盖掩码: 哪些像素"有主" (判越窗的唯一正确参照) ──
    cover = np.zeros((h, w), bool)
    for (_b1, _b2) in cs.enc_pair.values():
        if not (tcslib.PAIR_LEAD_LO <= _b1 < tcslib.PAIR_LEAD_HI):
            continue
        _x, _y = tcslib.atlas_cell_xy_engine_view(tcslib.pair_slot(_b1, _b2))
        cover[max(0, _y):min(h, _y + CH), max(0, _x):min(w, _x + CW)] = True
    for (_nm, _fld, recs) in faces:
        for (_b0, _b1, u0, v0, u1, v1) in recs:
            if u1 > u0 and v1 > v0:
                cover[max(0, v0):min(h, v1), max(0, u0):min(w, u1)] = True

    # ── ① 对偶格 (charset 里 lead 合法的全部在用字) ──
    n_pair = 0
    for ch, (b1, b2) in sorted(cs.enc_pair.items(), key=lambda kv: tcslib.pair_slot(*kv[1])):
        if not (tcslib.PAIR_LEAD_LO <= b1 < tcslib.PAIR_LEAD_HI):
            continue
        n_pair += 1
        slot = tcslib.pair_slot(b1, b2)
        x, y = tcslib.atlas_cell_xy_engine_view(slot)
        m = measure(ink, x, y, ch, tpls, h, w, cover)
        m.update(kind='pair', char=ch, code='%02X%02X' % (b1, b2), slot=slot,
                 row=slot // NCOL, col=slot % NCOL, cell=[x, y])
        m['level'] = _level(m['flags'])
        rows.append(m)

    # ── ② FT 记录矩形 (三个 face 全部 544 条非空) ──
    n_ft = 0
    for fi, (nm, _fld, recs) in enumerate(faces):
        for idx, (b0, b1, u0, v0, u1, v1) in enumerate(recs):
            if u1 <= u0 or v1 <= v0:
                continue
            n_ft += 1
            code = idx + 0x20
            rw, rh = u1 - u0, v1 - v0
            sub = np.zeros((CH, CW), bool)
            yy0, yy1 = max(0, v0), min(h, v1)
            xx0, xx1 = max(0, u0), min(w, u1)
            if yy1 > yy0 and xx1 > xx0:
                sub[yy0 - v0:yy1 - v0, xx0 - u0:xx1 - u0] = ink[yy0:yy1, xx0:xx1]
            n = int(sub.sum())
            rec = dict(kind='ft_record', face=fi, face_name=nm, code='%02X' % code,
                       index=idx, rect=[u0, v0, u1, v1], size=[rw, rh],
                       cell=[u0, v0], ink_px=n, fill_rows=int(len(set(np.where(sub)[0].tolist()))),
                       flags=[], level=LV_I, bbox=None, missing_rows=[])
            ys2, xs2 = np.where(sub)
            if n:
                rec['bbox'] = [int(xs2.min()), int(ys2.min()), int(xs2.max()), int(ys2.max())]
            if n == 0:
                lv_, why = _empty_record_reason(nm, fi, code, cs)
                rec['level'] = lv_
                rec['empty_reason'] = why
                if lv_ != LV_I:
                    rec['flags'].append('empty')
            elif n < SPARSE_MIN and rw * rh >= CW:
                rec['flags'].append('sparse')
            if n:
                if sub[:, 0].any():
                    rec['flags'].append('touch_left')
                if sub[:, CW - 1].any():
                    rec['flags'].append('touch_right')
                if sub[0].any():
                    rec['flags'].append('touch_top')
                if sub[CH - 1].any():
                    rec['flags'].append('touch_bottom')
            # ★ 只对**default face 的整格 ASCII 记录**做 16px 模板比对
            #   (其他 face / 非 16×16 记录是另一套设计, 与 16px 模板无关)
            if nm == FACE_DEFAULT_NAME and rw >= CW and rh >= CH and 0x20 <= code < 0x80:
                m2 = measure(ink, u0, v0, chr(code), tpls, h, w, cover)
                for k in ('tpl', 'tpl_ink_px', 'tpl_miss', 'tpl_extra', 'missing_rows'):
                    if k in m2:
                        rec[k] = m2[k]
                for f in m2['flags']:
                    if f not in rec['flags']:
                        rec['flags'].append(f)
            rec['note'] = ('非 16×16 的记录矩形 (%dx%d) —— 几何判据按矩形自身算, 不做 16px 模板比对'
                           % (rw, rh)) if (rw < CW or rh < CH) else ''
            if rec['level'] != LV_E:
                rec['level'] = _level(rec['flags'])
            rows.append(rec)


    # ── ③ 图标码 (0xB1/0xB5): 引擎硬编码 UV, 不吃字库; 它们在 FT 记录表里仍占一格 ──
    icons = []
    try:
        import icon_table
        for r in icon_table.all_icons():
            icons.append(dict(byte='%02X' % r['byte'], mark=tcslib.BTN_FMT % r['pua'],
                              name=r['name'], key=r['key'], uv=list(r['uv']),
                              note='引擎按硬编码 UV 画图标 (另一张贴图), **不吃字库**; '
                                   '它在 FT 记录表里的那一格只是"占位", 不参与字库几何判据'))
    except Exception as e:                                       # noqa: BLE001
        icons.append(dict(error=str(e)))

    # ── 汇总 ──
    lv = {}
    for r in rows:
        lv[r['level']] = lv.get(r['level'], 0) + 1
    flag_cnt = {}
    for r in rows:
        for f in r['flags']:
            flag_cnt[f] = flag_cnt.get(f, 0) + 1
    bad = [r for r in rows if r['level'] in (LV_E, LV_W)]
    bad.sort(key=lambda r: (_LV_ORDER[r['level']], r['kind'], r.get('row', -1), r.get('col', -1)))
    # "有正当理由的空记录"单列一张表 (省得每次都要重新论证它们没问题)
    by_design = [dict(face=r.get('face_name'), code=r['code'], rect=r['rect'],
                      reason=r.get('empty_reason', ''))
                 for r in rows if r['kind'] == 'ft_record' and r['ink_px'] == 0
                 and r['level'] == LV_I]
    # ★ 截断专项清单: 模板有墨的整行在盘上全空 (round50 新判据; 老判据看不见这一类)
    trunc = [r for r in rows if 'tpl_lost_rows' in r['flags']]
    doc = dict(
        tool=TOOL, tool_version=TOOL_VERSION, round=ROUND,
        iso=rel(iso_path) if iso_path else None,
        iso_sha256=iso_sha256,
        atlas=dict(width=w, height=h, ink_texels=int(ink.sum())),
        geometry=dict(window='%dx%d' % (CW, CH), ncol=NCOL,
                      window_formula='对偶码: (16*col, 2+16*(row+3*[row>=12])) —— 引擎采样窗, '
                                     '无相位; FT 记录: 记录矩形原值',
                      template=rel(tpls.path) if tpls and tpls.ok else None,
                      template_recipe='PIL truetype 16px, draw origin (8,8), 窗 = canvas[8:24,8:24], '
                                      '阈值 128 (= gen_font16.render16 同一配方)',
                      tpl_tol=TPL_TOL, sparse_min=SPARSE_MIN,
                      rules=RULE_TEXT),
        counts=dict(pair_windows=n_pair, ft_record_windows=n_ft, icon_codes=len(icons),
                    windows_total=len(rows), by_level=lv, by_flag=flag_cnt,
                    empty_ft_by_design=len(by_design)),
        findings=bad,
        findings_total=len(bad),
        truncated=trunc,
        empty_ft_by_design=by_design,
        template_missing=[c for c in sorted(set(tpls.no_ink))] if tpls else [],
        verdict=dict(truncated=flag_cnt.get('tpl_lost_rows', 0),
                     empty=flag_cnt.get('empty', 0),
                     overflow=flag_cnt.get('ink_out', 0),
                     sparse=flag_cnt.get('sparse', 0),
                     errors=lv.get(LV_E, 0), warnings=lv.get(LV_W, 0)),
    )
    doc['verdict']['ok'] = (doc['verdict']['errors'] == 0)
    doc['one_line'] = (
        '引擎采样窗 %d 个 (对偶 %d + FT 记录 %d): 错误 %d / 警告 %d —— '
        '**截断(丢行) %d**, 空白 %d, 越窗 %d, 极稀 %d'
        % (len(rows), n_pair, n_ft, lv.get(LV_E, 0), lv.get(LV_W, 0),
           flag_cnt.get('tpl_lost_rows', 0), flag_cnt.get('empty', 0),
           flag_cnt.get('ink_out', 0), flag_cnt.get('sparse', 0)))
    if verbose:
        print('[geom] %s' % doc['one_line'])
        for r in bad[:40]:
            print('[geom]   %s %s' % ('[!!]' if r['level'] == LV_E else '[warn]',
                                      _finding_line(r)))
    return doc


def _finding_line(r):
    if r['kind'] == 'pair':
        who = '%s (码 %s slot=%d row=%d col=%d 格=%s)' % (
            r['char'], r['code'], r['slot'], r['row'], r['col'], r['cell'])
    else:
        who = 'FT[%s] 码 %s 矩形=%s (%dx%d)' % (r.get('face_name'), r['code'], r['rect'],
                                                r['size'][0], r['size'][1])
    why = '; '.join(RULE_TEXT.get(f, f) for f in r['flags'])
    extra = ''
    if r.get('row_shift'):
        extra += ' 行错位=%+d行 (命中率 %.3f)' % (r['row_shift'], r.get('row_shift_score', 0))
    if r.get('rows_pushed_out'):
        extra += ' 被推出窗外的模板行=%s' % (r['rows_pushed_out'],)
    if r.get('missing_rows'):
        extra += ' 盘上整行空白=%s' % (r['missing_rows'],)
    if r.get('tpl_miss') is not None:
        extra += ' 模板差: 少 %d / 多 %d' % (r.get('tpl_miss', 0), r.get('tpl_extra', 0))
    return '%s —— %s%s' % (who, why, extra)


# ═══════════════════════════ 报告 ═══════════════════════════

def markdown(doc):
    L = []
    A = L.append
    V = doc['verdict']
    A('# 字形几何体检报告 (truncation_report)')
    A('')
    A('> 工具 `%s` (%s) · 盘 `%s`' % (doc['tool'], doc['tool_version'], doc['iso']))
    A('> sha256 `%s`' % (doc['iso_sha256'] or '?'))
    A('> 窗口: %s; 模板 `%s`' % (doc['geometry']['window'], doc['geometry']['template']))
    A('')
    A('## 一句话结论')
    A('')
    A('- **%s**' % doc['one_line'])
    A('- 判据 = **结构性**的: 墨必须在窗内、与 16px 模板逐像素比对 (紧阈值 %d),'
      % doc['geometry']['tpl_tol'])
    A('  并把「空白 / 极稀 / 触边 / 越窗 / 丢行」分成不同告警级别'
      ' —— **不再用 ±4/±2 容差窗**"蒙"过空白字。')
    A('')
    A('## 统计')
    A('')
    A('| 项 | 数量 |')
    A('|---|---|')
    A('| 体检窗总数 | %d |' % doc['counts']['windows_total'])
    A('| 　对偶格 | %d |' % doc['counts']['pair_windows'])
    A('| 　FT 记录矩形 | %d |' % doc['counts']['ft_record_windows'])
    A('| 错误 (error) | **%d** |' % V['errors'])
    A('| 警告 (warn) | %d |' % V['warnings'])
    A('| 　**截断 (模板有墨的整行不见了)** | **%d** |' % V['truncated'])
    A('| 　空白 | %d |' % V['empty'])
    A('| 　越出采样窗 | %d |' % V['overflow'])
    A('| 　极稀 | %d |' % V['sparse'])
    A('')
    by_flag = doc['counts']['by_flag']
    if by_flag:
        A('按判据计数: ' + ', '.join('`%s` %d' % kv for kv in sorted(by_flag.items())))
        A('')
    if not doc['findings']:
        A('## 逐字清单')
        A('')
        A('**没有任何"错误/警告"级别的发现** —— 全部 %d 个采样窗都通过。'
          % doc['counts']['windows_total'])
        A('')
    else:
        A('## 逐字清单 (%d 条, 错误在前)' % doc['findings_total'])
        A('')
        A('| 级别 | 对象 | 墨点 | 包围盒 | 判据 |')
        A('|---|---|---|---|---|')
        for r in doc['findings']:
            if r['kind'] == 'pair':
                who = '%s 码%s slot=%d (r%d c%d)' % (r['char'], r['code'], r['slot'],
                                                     r['row'], r['col'])
            else:
                who = 'FT %s 码%s' % (r.get('face_name'), r['code'])
            A('| %s | %s | %d | %s | %s |'
              % ('!!' if r['level'] == LV_E else 'warn', who, r['ink_px'],
                 r['bbox'], '; '.join(RULE_TEXT.get(f, f) for f in r['flags'])))
        A('')
    if doc['template_missing']:
        A('## 模板缺字的字 (方正像素16 里没有墨 ⇒ 只做几何判据, 不比模板)')
        A('')
        A('`%s`' % ''.join(doc['template_missing']))
        A('')
    A('## 截断专项清单 (模板有墨的整行在盘上全空)')
    A('')
    if not doc['truncated']:
        A('- **0 个** —— 没有字形被采样窗切掉底行。')
    else:
        for r in doc['truncated']:
            A('- %s' % _finding_line(r))
    A('')
    A('## "空记录"为什么不算坏 (有正当理由的 %d 条)' % len(doc['empty_ft_by_design']))
    A('')
    if doc['empty_ft_by_design']:
        A('| face | 码 | 矩形 | 理由 |')
        A('|---|---|---|---|')
        for r in doc['empty_ft_by_design']:
            A('| %s | %s | %s | %s |' % (r['face'], r['code'], r['rect'], r['reason']))
    else:
        A('- 无')
    A('')
    A('## 判据明细')
    A('')
    for k in sorted(RULE_TEXT):
        A('- `%s` — %s' % (k, RULE_TEXT[k]))
    A('')
    A('---')
    A('')
    A('★ 本报告由 `%s` 生成; `dump_font.py` 每轮构筑都会把同一份结果写进 '
      '`<版本>_font_summary.json` 的 `glyph_geometry` 段。' % doc['tool'])
    return '\n'.join(L) + '\n'


def write_reports(doc, out_dir, prefix=''):
    os.makedirs(out_dir, exist_ok=True)
    pj = os.path.join(out_dir, (prefix + '_' if prefix else '') + 'truncation_report.json')
    pm = os.path.join(out_dir, (prefix + '_' if prefix else '') + 'truncation_report.md')
    with io.open(pj, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    with io.open(pm, 'w', encoding='utf-8', newline='\n') as f:
        f.write(markdown(doc))
    return pj, pm
