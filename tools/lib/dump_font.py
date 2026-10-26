# -*- coding: utf-8 -*-
r"""dump_font.py — 「字库 dump」: 把一张盘上的字库导成**一眼能看**的四件套 (只读)

用途: 每轮构筑完成后, 让人**不用跑模拟器**就能回答四个问题:
  ① 这一版的字形长什么样?               → `<版本>_font_atlas.png`
  ② 每个码位画在哪儿、有没有墨?          → `<版本>_font_ft.csv`
  ③ 本盘字符集里有哪些字、缺哪些字形?    → `<版本>_font_charset.csv`
  ④ 字库还能装多少字? 缺字形有哪几个?    → `<版本>_font_summary.json`

用法 (单跑; 构筑时由 make_build.py 自动调用, 默认开):
  python tools/iso_build/dump_font.py --iso work/builds/GR_ZH91/GR_ZH91.iso \
                                     --out work/builds/GR_ZH91/font --prefix GR_ZH91

  --scale N     PNG 放大倍数 (默认 2; 最近邻, 只为肉眼看)
  --no-png      只出 CSV/JSON, 不出 PNG (省几秒)
  --grid        主图叠**引擎格 16×16 网格线** (淡红) + FT 记录矩形 (淡蓝) + 已用格角标
  --labels      --grid 之上再加 列号/行号 + 每个已用格里的 slot 编号 (输出 RGB PNG)
  --only-sampled 另出 `<版本>_font_atlas_sampled.png`: 只拼**引擎会采样的格**
                (62 列 × 用到的网格行 + 底部记录带), 彻底避开"从不采样"的边角
  --flat-view   ★ 只作对照: 用旧口径 (整个容器当裸图) 渲染 —— 会看到 48B 包头被画成像素、
                每 64 行一次"撕裂"、每段右移 6 格。**那不是游戏里看到的样子**。

★ 只读: 只 mmap 读 ISO, **绝不写盘上的任何字节**。
★ 可复现: 输出里**不含时间戳**, **同一个输出目录**下对同一 ISO dump 两次, 四个文件的 sha256
  完全相同。(`summary.json` 里记了各文件的**输出路径** ⇒ 换一个输出目录写, 它的 sha256 会变;
  另外三个内容文件 (PNG / ft.csv / charset.csv) 与目录无关, 始终逐字节相同。)
★ 全部口径复用 tools/text_csv/tcslib.py 的现成实现 (字表解析 / PAK 解析 / 引擎格位公式 /
  字形存在性检查), 本脚本**不重新逆向**任何格式:

  字表 FT   : MENU.IMG #4 `FONT.RES` (槽 @0xB9120, 存 4421 B → LZO 展开 5942 B)
              face 描述 = 14×u32; 记录 10 B `{u8 f0}{u8 f1=advance}{u16 u0}{u16 v0}{u16 u1}{u16 v1}`
              nrec = fld[4]×fld[5] (现役: 224/224/96)
  图集      : MENU.IMG #3 `COMMON.PAK` 内 `new_font_revised`, 1024×512 PSMT4 (4bpp)
              **texel 0 = 墨, 非 0 = 空** (PSMT4 每字节 2 texel: 偶 x 低 nibble)
              ★ round44 查实: 这段"像素区"其实是 **GIF 封包流** (8 段, 每段 48B 包头 =
                [PT][A+D TRXPOS][IMAGE tag]); 硬件把包头当 DMA 命令吃掉 ⇒ 它们不是像素。
                默认 PNG = **引擎口径** (按封包把每段数据放回 TRXPOS 指定的行);
                旧口径 (整块当裸图) 只作对照, 用 `--flat-view` 出。
                原版 EN 盘是 PSMT8/8bpp/512×512 + 单包 (16B GIFTAG), 现在也按 psm 正确读。
                详见 docs/REPORT_atlas_artifact.md。
  网格      : NCOL=62 CW=CH=16 Y0=2 SKIP_ROW=12 SKIP_ROWS=3 (对偶码走引擎格位公式)

★ **引擎格位公式 (round41 修正; 旧版这里是错的)**:
    slot      = (lead-0xA1)*94 + (trail-0xA1)
    row, col  = slot // 62, slot % 62
    p         = col + PHI[row]
    x         = 16 * (p % 64)                      ← 图集一行 64 格 ⇒ 会回绕
    y         = yrow(row) + (1 if p >= 64 else 0)   ← 回绕列的字形低 1 行 (实测)
    PHI = 行0-3:6 行4-7:12 行8-11:18 行12:24 行13-16:30 行17-18:36 行19-23:2 行24:0
  实证: 1297 字模板比对本式 785 个 0 误差, 无相位式 0/1297; 本盘 1319/1319 个对偶字的
  引擎格都有墨; 回绕列 8/8 抽样字模板 0 误差命中在 y+1 (见 tcslib 常量区注释 +
  docs/REPORT_dump_font_capacity.md §格位公式证据)。
  ⇒ CSV 的 `cell_x/cell_y` 一律是**引擎真实口径** (round51 订正: 对偶码走
    `tcslib.atlas_cell_xy_engine_view`, 即引擎采样坐标、无相位);
    flat 口径 (= 引擎坐标 + 每段 6 格, 越界回绕并带行进位) 另存 `cell_flat_x/cell_flat_y` (仅对偶码有值);
    旧口径 (x = 4+16*col) 另存 `cell_legacy_x/cell_legacy_y` 供对照。

  ASCII/单字节: 走 FT 记录表 (idx = code-0x20), 引擎采样窗 = 记录矩形做相位校正后的位置
              ((u0 + 16*PHI[row(v0)]) % 宽, v0+1); 记录不在网格行上 (EN 带) 时 = 原值。

产出 (写进 --out 目录):
  <prefix>_font_atlas.png     图集可视化 (0=墨→黑, 非 0=空→白; 默认 2 倍最近邻放大)
  <prefix>_font_ft.csv        FT 记录表, 列:
                               face,face_name,index,code,advance,u0,v0,u1,v1,slot_x,slot_y,ink_px,has_ink
                               · face/face_name = face 序号与名 (large/default/huge)
                               · index          = 记录序号 (0..nrec-1)
                               · code           = 该记录对应的码位 = index + 0x20
                               · advance        = 记录第 2 字节 (字宽, 现役 = 8)
                               · u0,v0,u1,v1    = 记录矩形 (u 水平 / v 垂直)
                               · slot_x,slot_y  = 引擎实际采样处 (u0+4, v0+2 实测偏置)
                               · ink_px         = 记录矩形内的墨点数
                               · has_ink        = 该码位在图集里**画得出来**吗 (矩形/+4+2/±邻域三处任一有墨)
  <prefix>_font_charset.csv   字符集清单, 列:
                               char,unicode,kind,bytes_hex,slot,cell_x,cell_y,
                               cell_legacy_x,cell_legacy_y,has_glyph,glyph_basis,note
                               · kind = ascii (0x20..0x7E) / single (单字节码) /
                                        pair (对偶码) / icon (未映射控制字节 → 引擎画按键图标)
                               · slot = 槽位号 (只对 pair 有意义)
                               · **cell_x/cell_y = 引擎实际采样窗左上角** (权威口径):
                                   pair  = 引擎格位公式 (PHI + 64 回绕, 回绕列 y 低 1 行)
                                   ascii/single = FT 记录矩形做行相位校正后的采样点
                                   icon  = 空 (不吃字库)
                               · cell_legacy_x/cell_legacy_y = **旧 dump 的 cell_x/cell_y**
                                   (pair = tcslib.atlas_cell_xy 的 4+16*col; ascii/single = 记录
                                    矩形原值); 留一列只为和改版前逐行对照, 别拿它当引擎位置。
                               · has_glyph    = 盘上真有字形吗 (判定口径见 glyph_basis 列)
                               · glyph_basis  = 判定依据: ft_record (FT 记录表) /
                                                atlas_cell (引擎格查图集) / engine_icon (不吃字库)
  <prefix>_font_summary.json  统计: **容量/用量** / face 数 / 记录数 / 字符数 / 有字形数 /
                               缺字形数 / 图集尺寸与哈希 / 各文件 sha256

退出码: 0 = 成功; 2 = 参数/装载错误 (盘不对、找不到 FONT.RES / COMMON.PAK)。
"""
import argparse
import csv
import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))

import tcslib                                                   # noqa: E402
import icon_table                                               # noqa: E402  (round42)
import glyph_geometry                                           # noqa: E402  (round50)

try:                                        # 中文输出在重定向/管道下也要可读
    sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:                                                    # noqa: BLE001
    pass

MENU_LBA = tcslib.MENU_LBA
FT_NAME, PAK_NAME, ATLAS_REC = 'FONT.RES', 'COMMON.PAK', 'new_font_revised'
SEARCH_N = 24                       # 字表/图集都在 MENU.IMG 前 24 个条目里 (实测 #4 / #3)

# 单字节码带: 引擎的单字节码位实测落在 0xAF..0xFE (现役 76 个)。
# 这一段里**没有映射**的字节 = 引擎直接拿去画按键图标/特殊符号 (不吃字库)。
SINGLE_BAND = (0xAF, 0xFE)


# ═══════════════════════════ 小工具 ═══════════════════════════

def rel(p):
    """仓库内相对路径 (正斜杠), 写进 json 给人看。"""
    try:
        r = os.path.relpath(p, REPO)
    except ValueError:
        return p.replace('\\', '/')
    return r.replace('\\', '/') if not r.startswith('..') else p.replace('\\', '/')


def sha256_file(p):
    return tcslib.sha256_file(p)


def sha256_bytes(b):
    import hashlib
    return hashlib.sha256(b).hexdigest()


def _find_entries(iso):
    """定位 MENU.IMG 里的 FONT.RES / COMMON.PAK, 返回 (ft_e, ft_idx, pak_e, pak_idx)。"""
    ft = pak = None
    ft_i = pak_i = -1
    for i in range(SEARCH_N):
        e = iso.img_entry(MENU_LBA, i)
        if ft is None and e['name'] == FT_NAME:
            ft, ft_i = e, i
        elif pak is None and e['name'] == PAK_NAME:
            pak, pak_i = e, i
        if ft and pak:
            break
    return ft, ft_i, pak, pak_i


# ═══════════════════════════ 装载字库 ═══════════════════════════

def load_font(iso_path):
    """只读装载字库: 字表 faces + 图集像素 (字形检查用的 GlyphCache 由 dump_font() 另建)。"""
    iso = tcslib.Iso(iso_path)
    ft_e, ft_i, pak_e, pak_i = _find_entries(iso)
    if ft_e is None or pak_e is None:
        raise SystemExit('!! MENU.IMG 前 %d 个条目里找不到 %s / %s (这张盘不是本工程的盘?)'
                         % (SEARCH_N, FT_NAME, PAK_NAME))
    # ① 字表: 存的是 LZO 帧 ⇒ 先按 tcslib 的子流口径展开, 再解析 face
    ft_slot = iso.read(ft_e['iso_off'], ft_e['stored'])
    ft_blob = b''.join(s[0] for s in tcslib.lzo_subs(ft_slot))
    if not ft_blob:
        raise SystemExit('!! FONT.RES 子流解压失败 (LZO 帧不对)')
    _head_end, faces = tcslib.parse_ft_faces(ft_blob)
    # ② 图集: COMMON.PAK 记录链里找 new_font_revised
    pak = iso.read(pak_e['iso_off'], pak_e['stored'])
    atlas = None
    for (nm, psm, w, h, clut, px, off) in tcslib.parse_pak_records(pak):
        if nm == ATLAS_REC:
            atlas = dict(name=nm, psm=psm, w=w, h=h, clut=clut, px_size=px,
                         px_off=off, pak=pak)
            break
    iso.close()
    if atlas is None:
        raise SystemExit('!! COMMON.PAK 里找不到 %s' % ATLAS_REC)
    return dict(ft_e=ft_e, ft_idx=ft_i, ft_slot=ft_slot, ft_blob=ft_blob,
                faces=faces, pak_e=pak_e, pak_idx=pak_i, atlas=atlas)


# ═══════════════════════════ 图集 → PNG ═══════════════════════════
#
#   ★ round44 查实: 像素容器**不是裸图**, 而是 **GIF 封包流** (见 tcslib 常量区注释 + 
#     docs/REPORT_atlas_artifact.md):
#       现役盘 : 8 段, 每段 [PT 16B][A+D TRXPOS 16B][IMAGE tag 16B][数据]  (make_pak.py 产物)
#       原版盘 : [GIFTAG 16B][0x40000 像素]  单包
#     硬件把包头当 **DMA 命令**吃掉 ⇒ 包头字节**永远不是像素**。
#     旧口径 (整个容器当 1024x512 裸图逐行读) 会把 48B 包头画成"最左上角一行断续的像素",
#     并把每一段的内容整体右移 96×(段号+1) texel (= 6 格/段) ⇒ 用户看到的"每隔 4 行撕裂纹样"
#     (= 每 64 像素行 = 每 4 个字形行一段)。
#
#   PSMT4 = 4bpp: 每字节 2 个 texel, 偶 x = 低 nibble, 奇 x = 高 nibble (与 tcslib 同口径)。
#   PSMT8 (原版 EN 盘) = 每字节 1 texel; 墨 = 索引 < INK8_THRESHOLD (抗锯齿字体的浅色墨也算)。
#   这里用 bytes.translate (C 速度) 逐行做两次查表, 再按 x 交错 ⇒ 1 MB 图集 ~0.3 s。
_LONIB = bytes(i & 0xF for i in range(256))
_HINIB = bytes((i >> 4) & 0xF for i in range(256))
_INK = bytes(0 if i == 0 else 255 for i in range(256))       # texel 0 = 墨 → 黑(0)
INK8_THRESHOLD = 24                     # 8bpp 原版字库: 墨 = 调色板索引 < 24 (patch_zh64 的 INK_THR 同值)
_INK8 = bytes(0 if i < INK8_THRESHOLD else 255 for i in range(256))

# 叠加层配色 (只在 --grid/--labels/--only-sampled 时用, 默认 PNG 仍是 1bit 黑白)
GRID_LINE = (255, 214, 214)             # 引擎格线 (淡红)
GRID_LINE_ROW = (255, 160, 160)         # 网格行边界 (稍深)
GRID_REC = (170, 215, 255)              # FT 记录矩形 (淡蓝; ASCII/单字节的采样窗)
GRID_MARK = (40, 130, 255)              # 已用格角标


def container_blob(atlas):
    """COMMON.PAK 里这一段像素容器的原始字节 (含 GIF 包头)。"""
    return atlas['pak'][atlas['px_off']: atlas['px_off'] + atlas['px_size']]


def pixels_engine_order(atlas):
    """像素容器 → **引擎看到的那张图**的字节流 (每行 stride 字节) + 诊断 dict。

    做法: 按 GIF 封包把每段数据搬到 TRXPOS 指定的行 (= 写入侧 patch_zh64/65/93 的同一张映射)。
    解析不出已知封包形态 ⇒ 退回"整块当裸图"(旧口径), 并在 diag 里标出来 (不崩)。
    """
    psm, w, h = atlas['psm'], atlas['w'], atlas['h']
    stride = w // 2 if psm == 0x14 else w
    blob = container_blob(atlas)
    diag = dict(container_bytes=len(blob), row_bytes=stride,
                container='gif-packets', segments=[])
    segs = tcslib.atlas_container_segments(blob, stride)
    if not segs:
        diag['container'] = 'unparsed-raw (退回旧口径: 整个容器当裸图)'
        return blob[:stride * h].ljust(stride * h, b'\x00'), diag
    fill = 0x11 if psm == 0x14 else 0x1F
    out = bytearray(bytes([fill]) * (stride * h))
    for (row, off, ln) in segs:
        nr, rem = ln // stride, ln % stride
        diag['segments'].append(dict(first_row=row, data_off=off, bytes=ln, rows=nr, tail=rem))
        for r in range(nr):
            if row + r >= h:
                break
            out[(row + r) * stride: (row + r + 1) * stride] = \
                blob[off + r * stride: off + (r + 1) * stride]
        if rem and row + nr < h:
            d = (row + nr) * stride
            out[d:d + rem] = blob[off + nr * stride: off + nr * stride + rem]
    return bytes(out), diag


def decode_pixels(raw, w, h, psm):
    """裸像素字节流 → 灰度 bytes (0=墨/黑, 255=空/白), 长度 w*h。"""
    if psm == 0x14:                                       # PSMT4 4bpp: 偶 x = 低 nibble
        stride = w // 2
        buf = bytearray(w * h)
        for y in range(h):
            row = raw[y * stride: (y + 1) * stride]
            if len(row) != stride:
                row = row + b'\x00' * (stride - len(row))
            base = y * w
            buf[base: base + w: 2] = row.translate(_LONIB).translate(_INK)
            buf[base + 1: base + w: 2] = row.translate(_HINIB).translate(_INK)
        return bytes(buf)
    if psm in (0x13, 0x1B):                               # PSMT8 8bpp: 1 texel/byte
        return raw[:w * h].ljust(w * h, b'\x1F').translate(_INK8)
    # 未知 psm: 按 4bpp 读 (历史行为), 由调用方在 summary 里标注
    return decode_pixels(raw, w, h, 0x14)


def atlas_gray(atlas, view='engine'):
    """图集像素 → 灰度 bytes (0=墨/黑, 255=空/白), 长度 w*h。

    view='engine' (默认, round44 起): **引擎真正看到的图集** —— 按 GIF 封包把每段数据放到
        TRXPOS 指定的行。行 0/1 是干净的空白, 没有"虚线行", 也不会有 6 格/段的错位。
    view='flat'  : 旧口径 (整个容器当 1024x512 裸图逐行读) —— **只作对照**:
        它把 48B 包头画成最左上角那一行断续像素, 并把每段内容右移 96×(段号+1) texel。
        (旧 dump 的 PNG / CSV 的 cell_x 都是这个视图里的坐标。)
    """
    w, h, psm = atlas['w'], atlas['h'], atlas['psm']
    if view == 'engine':
        raw, _diag = pixels_engine_order(atlas)
    else:
        stride = w // 2 if psm == 0x14 else w
        raw = container_blob(atlas)[:stride * h].ljust(stride * h, b'\x00')
    return decode_pixels(raw, w, h, psm)


def _grid_rows(h):
    """全部网格行的 y (含 SKIP_ROWS), 截到图集内。"""
    return [tcslib.GRID_Y0 + tcslib.CH * (r + (tcslib.GRID_SKIP_ROWS if r >= tcslib.GRID_SKIP_ROW else 0))
            for r in range(64) if tcslib.GRID_Y0 + tcslib.CH * (
                r + (tcslib.GRID_SKIP_ROWS if r >= tcslib.GRID_SKIP_ROW else 0)) + tcslib.CH <= h]


def engine_cells(cs):
    """引擎采样格清单: [(slot, x, y, 说明)] —— 对偶格 (无相位) + 单字节记录矩形由调用方另加。"""
    out = []
    for ch, (b1, b2) in sorted(cs.enc_pair.items(), key=lambda kv: tcslib.pair_slot(*kv[1])):
        slot = tcslib.pair_slot(b1, b2)
        if not (tcslib.PAIR_LEAD_LO <= b1 < tcslib.PAIR_LEAD_HI):
            continue
        x, y = tcslib.atlas_cell_xy_engine_view(slot)
        out.append((slot, x, y, ch))
    return out


def write_atlas_png(gray, atlas, path, scale=2, grid=False, labels=False, cells=None):
    """把二值化灰度图写成 PNG (最近邻放大 scale 倍)。

    默认 (grid=False, labels=False) 输出 1bit 黑白 (与历史产物同观感, 文件小)。
    开 --grid / --labels 时输出 RGB, 叠加:
      · 引擎格 16x16 网格线 (淡红; 网格行边界稍深) —— 坐标 = tcslib.atlas_cell_xy_engine_view
      · FT 记录矩形 (淡蓝; ASCII/单字节码的采样窗)
      · 已用格左上角角标 (蓝)
      · labels=True 时再加 列号/行号 + 每个已用格里的 slot 编号
    """
    from PIL import Image, ImageDraw
    w, h = atlas['w'], atlas['h']
    if not (grid or labels):
        im = Image.frombytes('L', (w, h), gray).convert('1', dither=Image.Dither.NONE)
        if scale > 1:
            im = im.resize((w * scale, h * scale), Image.NEAREST)
        im.save(path, optimize=True)
        return w, h
    im = Image.frombytes('L', (w, h), gray).convert('RGB')
    if scale > 1:
        im = im.resize((w * scale, h * scale), Image.NEAREST)
    d = ImageDraw.Draw(im)
    for y in _grid_rows(h):                                     # 网格行边界
        col = GRID_LINE_ROW if y in (tcslib.GRID_Y0, ) or (y - tcslib.GRID_Y0) % (tcslib.CH * 4) == 0 \
            else GRID_LINE
        d.line([0, y * scale, im.size[0], y * scale], fill=col)
        d.line([0, (y + tcslib.CH) * scale, im.size[0], (y + tcslib.CH) * scale], fill=col)
    for c in range(0, w // tcslib.CW + 1):                      # 列边界 (每 16px = 一格)
        d.line([c * tcslib.CW * scale, 0, c * tcslib.CW * scale, im.size[1]], fill=GRID_LINE)
    for (_slot, x, y, _ch) in (cells or []):                    # 已用格角标
        d.line([x * scale, y * scale, (x + 3) * scale, y * scale], fill=GRID_MARK)
        d.line([x * scale, y * scale, x * scale, (y + 3) * scale], fill=GRID_MARK)
    if labels:
        from PIL import ImageFont
        f = ImageFont.load_default()
        for c in range(0, w // tcslib.CW):
            d.text((c * tcslib.CW * scale + 1, 1), '%d' % c, fill=GRID_MARK, font=f)
        for ri, y in enumerate(_grid_rows(h)):
            d.text((1, y * scale + 1), 'r%d' % ri, fill=GRID_MARK, font=f)
        if scale * tcslib.CW >= 30:
            for (slot, x, y, _ch) in (cells or []):
                d.text((x * scale + 1, y * scale + scale * tcslib.CH // 2), str(slot),
                       fill=GRID_MARK, font=f)
    im.save(path, optimize=True)
    return w, h


def write_sampled_png(gray, atlas, cs, faces, path, scale=2, labels=True):
    """只拼**引擎会采样到的格**的紧凑图 (彻底避开"从不采样"的边角/包头/回绕副本)。

    版面: 左边一列行号 + 上面一行列号 (labels) + 主体 = NCOL(62) 列 × 用到的网格行,
          每个 16x16 格**按引擎口径原样摘取** (tcslib.atlas_cell_xy_engine_view);
          最下面再贴一条 **记录带** (ASCII/单字节码的 FT 记录矩形, 引擎直接按记录采样)。
    返回 (图宽, 图高, 用到的网格行数)。
    """
    from PIL import Image, ImageDraw, ImageFont
    w, h = atlas['w'], atlas['h']
    src = Image.frombytes('L', (w, h), gray)
    rows = _grid_rows(h)
    y_to_row = {y: i for i, y in enumerate(rows)}
    used_rows = sorted(set(tcslib.pair_slot(*p) // tcslib.NCOL for p in cs.enc_pair.values()))
    used_rows = [r for r in used_rows if r < len(rows)]
    sheet_row = {r: i for i, r in enumerate(used_rows)}
    margin = 22 if labels else 0
    sw = tcslib.NCOL * tcslib.CW
    sh = len(used_rows) * tcslib.CH
    # 记录带: v0 不在任何网格行上的记录 (= EN 带/图标带之类, 引擎按记录矩形采样)
    band = []
    for (_nm, _fld, recs) in faces:
        for (_b0, _b1, u0, v0, u1, v1) in recs:
            if u1 <= u0 or v1 <= v0 or v0 in rows:
                continue
            band.append((u0, v0, u1, v1))
    band = sorted(set(band), key=lambda r: (r[1], r[0]))
    bh = (max((r[3] - r[1]) for r in band) if band else 0)
    im = Image.new('RGB', (sw * scale + margin, sh * scale + (bh * scale + 6 if band else 0) + margin),
                   (255, 255, 255))
    for i, r in enumerate(used_rows):
        for c in range(tcslib.NCOL):
            x, y = tcslib.CW * c, rows[r]
            blk = src.crop((x, y, x + tcslib.CW, y + tcslib.CH)).convert('RGB')
            if scale > 1:
                blk = blk.resize((tcslib.CW * scale, tcslib.CH * scale), Image.NEAREST)
            im.paste(blk, (margin + c * tcslib.CW * scale, margin + i * tcslib.CH * scale))
    d = ImageDraw.Draw(im)
    for i in range(len(used_rows) + 1):
        d.line([margin, margin + i * tcslib.CH * scale, margin + sw * scale,
                margin + i * tcslib.CH * scale], fill=GRID_LINE)
    for c in range(tcslib.NCOL + 1):
        d.line([margin + c * tcslib.CW * scale, margin, margin + c * tcslib.CW * scale,
                margin + sh * scale], fill=GRID_LINE)
    for (_slot, x, y, _ch) in engine_cells(cs):                # 已用格角标 (按行号定位)
        r = y_to_row.get(y)
        if r is None or r not in sheet_row:
            continue
        i = sheet_row[r]
        c = x // tcslib.CW
        d.line([margin + c * tcslib.CW * scale, margin + i * tcslib.CH * scale,
                margin + (c * tcslib.CW + 3) * scale, margin + i * tcslib.CH * scale], fill=GRID_MARK)
        d.line([margin + c * tcslib.CW * scale, margin + i * tcslib.CH * scale,
                margin + c * tcslib.CW * scale, margin + (i * tcslib.CH + 3) * scale], fill=GRID_MARK)
    if band:
        by = margin + sh * scale + 3
        for (u0, v0, u1, v1) in band:
            blk = src.crop((u0, v0, min(u1, w), min(v1, h))).convert('RGB')
            bw = min(u1, w) - u0
            if scale > 1:
                blk = blk.resize((bw * scale, (min(v1, h) - v0) * scale), Image.NEAREST)
            im.paste(blk, (margin + u0 * scale, by))
        d.line([margin, by - 2, im.size[0], by - 2], fill=GRID_REC)
    if labels:
        f = ImageFont.load_default()
        for c in range(0, tcslib.NCOL, 1):
            d.text((margin + c * tcslib.CW * scale + 1, 2), '%d' % c, fill=GRID_MARK, font=f)
        for i, r in enumerate(used_rows):
            d.text((2, margin + i * tcslib.CH * scale + 1), 'r%d' % r, fill=GRID_MARK, font=f)
    im.save(path, optimize=True)
    return im.size[0], im.size[1], len(used_rows)


# ═══════════════════════════ FT 记录表 → CSV ═══════════════════════════

def _face_recs(g, recs):
    """把 GlyphCache 的「记录表」临时换成某个 face (复用它的判墨口径, 不重写逻辑)。"""
    saved = (g.recs, g.rec_nrec)
    g.recs, g.rec_nrec = recs, len(recs)
    return saved


def ft_rows(cache, faces):
    """遍历**所有 face** 的记录 ⇒ CSV 行列表。has_ink 复用 GlyphCache._check_record。"""
    ok = cache.font_ok
    out = []
    for fi, (name, fld, recs) in enumerate(faces):
        saved = _face_recs(cache, recs)
        try:
            for idx, (b0, b1, u0, v0, u1, v1) in enumerate(recs):
                code = idx + 0x20
                if ok:
                    has_ink = cache._check_record(code) is None      # 矩形 / +4+2 / ±邻域
                    ink = cache._ink(u0, v0, u1, v1) if u1 > u0 and v1 > v0 else 0
                else:
                    has_ink, ink = '', ''
                out.append(dict(face=fi, face_name=name, index=idx, code=code,
                                advance=b1, u0=u0, v0=v0, u1=u1, v1=v1,
                                slot_x=u0 + tcslib.GLYPH_DU, slot_y=v0 + tcslib.GLYPH_DV,
                                ink_px=ink, has_ink=('' if has_ink == '' else int(bool(has_ink)))))
        finally:
            cache.recs, cache.rec_nrec = saved
    return out


# ═══════════════════════════ 字符集 → CSV ═══════════════════════════

FT_COLS = ['face', 'face_name', 'index', 'code', 'advance',
           'u0', 'v0', 'u1', 'v1', 'slot_x', 'slot_y', 'ink_px', 'has_ink']
CS_COLS = ['char', 'unicode', 'kind', 'bytes_hex', 'slot',
           'cell_x', 'cell_y', 'cell_flat_x', 'cell_flat_y', 'cell_legacy_x', 'cell_legacy_y',
           'has_glyph', 'glyph_basis', 'note']


def icon_bytes(cs):
    """本盘「未映射字节」= 字符表里没有映射、也不是对偶 lead 的高位字节。

    ★ round42 修正口径 (**修掉"图标识别"的缺漏**):
      旧口径只扫 `SINGLE_BAND = 0xAF..0xFE` —— 下界 0xAF 是按"历史单字节码带"挑的,
      既漏掉 0xB1 以下可能空出来的字节, 也把**不是图标**的字节 (0xE7/0xF1 = ç/ñ)
      一并当成"手柄图标"。现在改为:

        候选 = `icon_table.candidate_bytes(cs)`          ← 0xB1..0xFF 里**没被字符集占用**的
               ∪ 旧 SINGLE_BAND 里的未映射字节 (向后兼容, 1 个都不少)

      并把「引擎真正认的文本图标码」(只有 0xB1/0xB5, 见 icon_table) 排在前面、
      标出来; 其余候选如实标注是"拉丁字母 / 空字节", **不再一律叫图标**。

    ★ 关键事实: 引擎的文本图标码是 DrawString v1 里**写死的两个 if** ⇒ 个数上限就是 2。
      「空出来的字节」**不等于**「新的图标码」—— 写别的字节只会走字形路径 (画不出图标)。
    """
    old = [b for b in range(SINGLE_BAND[0], SINGLE_BAND[1] + 1)
           if b not in cs.codes and b not in set(v[0] for v in cs.enc_pair.values())]
    cand = list(icon_table.candidate_bytes(cs))
    # 引擎认的图标码排最前 (升序), 其余按字节升序
    out = [b for b in icon_table.engine_icon_bytes() if b in cand]
    out += [b for b in cand if b not in out]
    out += [b for b in old if b not in out]
    return sorted(set(out), key=lambda b: (0 if icon_table.is_icon(b) else 1, b))


def charset_rows(cs, cache):
    """字符集全清单 (ascii / single / pair / icon), 排序固定 ⇒ 可复现。

    ★ 私有区占位字符 (按键图标) 一律按工程约定写成 ``{{BTN:XXXX}}`` 标记 ——
      CSV 里**不允许**出现私有区字符 (Excel 显示不出来, 见 toolbox 的硬门槛)。
    ★ cell_x/cell_y = **引擎真实采样窗左上角** (pair 走引擎格位公式; 单字节/ASCII 走
      FT 记录矩形 + 行相位校正); cell_legacy_* = 旧 dump 的老口径, 只供对照。
    """
    ok = cache.font_ok
    nrec = cache.rec_nrec
    rows = []

    def glyph(ch):
        """has_glyph (真/假) + 人话 note 尾巴。没装载字库时返回 ('', 说明)。

        ★ round52: **空格单独处理** —— 引擎对 0x20 不画任何像素, 它本来就不需要字形。
        此前 has_glyph 靠"记录矩形 ± 邻域有墨"判定, 而邻域里的**碎片残墨**会让它误报有字形;
        GR_ZH102 把那些碎片清掉后, 空格就被误报成"缺字形" ⇒ 这里显式短路。
        """
        if not ok:
            return '', '字库未装载, 跳过字形检查'
        if ch == ' ':
            return 1, '空格: 引擎不画像素, 不需要字形 (has_glyph 恒为真; round52)'
        r = cache.glyph_reason(ch)
        return int(r is None), ('' if r is None else r)

    def basis(ch):
        """判定依据 ('ft_record' / 'atlas_cell' / 'engine_icon'); 字库没装载时给 n/a。"""
        return cache.glyph_basis(ch) if ok else 'n/a'

    def rec_cells(ch, code):
        """单字节/ASCII 的 (引擎采样点, 旧口径记录矩形) —— 记录 idx = code-0x20。"""
        cell = cache.glyph_cell(ch)
        x, y = cell if cell else ('', '')
        idx = code - 0x20
        legacy = cache.recs[idx][2:4] if (ok and 0 <= idx < nrec) else ('', '')
        return x, y, legacy[0], legacy[1]

    def engine_note(ch, code):
        """单字节码的行相位人话 (说明 cell_x/cell_y 为什么不是记录矩形原值)。"""
        if not (ok and 0 <= code - 0x20 < nrec):
            return ''
        u0, v0 = cache.recs[code - 0x20][2:4]
        cell = cache.glyph_cell(ch)
        if not cell or cell == (u0, v0):
            return '引擎采样 = FT 记录矩形原值 (该行不参与相位校正: EN 带/非网格行)'
        return ('引擎采样 = 记录(%d,%d) + 行相位 %d×16 ⇒ (%d,%d); '
                'legacy 两列 = 记录矩形原值' % (u0, v0, (cell[0] - u0) // 16, cell[0], cell[1]))

    # ① ASCII 0x20..0x7E —— 引擎按单字节画, 与 charset JSON 无关, 走 FT 记录表
    for b in range(0x20, 0x7F):
        ch = chr(b)
        hg, why = glyph(ch)
        note = []
        idx = b - 0x20
        if ok:
            if 0 <= idx < nrec:
                r = cache.recs[idx]
                note.append('FT rec[%d]=(%d,%d,%d,%d)' % (idx, r[2], r[3], r[4], r[5]))
            else:
                note.append('FT rec 越界 (idx=%d ≥ %d)' % (idx, nrec))
        if why:
            note.append(why + ' (ASCII 只告警: 小写字形在别的 face, 现役盘实机可读)')
        cx, cy, lx, ly = rec_cells(ch, b)
        note.append(engine_note(ch, b) or 'FT 记录表')
        rows.append(dict(char=ch, unicode='U+%04X' % b, kind='ascii',
                         bytes_hex='%02X' % b, slot='',
                         cell_x=cx, cell_y=cy, cell_legacy_x=lx, cell_legacy_y=ly,
                         has_glyph=hg, glyph_basis=basis(ch), note='; '.join(n for n in note if n)))

    # ② 单字节码 (含汉字 的/你 等)
    #    ★ round43: 其中 ç(0xE7) / ñ(0xF1) 是**拉丁字母**, 单独归成 kind='latin1'
    #      (它们过去是"未映射字节", 归在 ④ 的 icon 段里; 现在进了 charset 的 codes,
    #       ④ 段自然不再包含它们 ⇒ 在这里按 latin1 归类, 保持 kind 统计仍是 latin1=2)。
    for ch, b in sorted(cs.enc_single.items(), key=lambda kv: kv[1]):
        hg, why = glyph(ch)
        latin1 = icon_table.is_known_not_icon(b)
        idx = b - 0x20
        note = []
        if ok and 0 <= idx < nrec:
            r = cache.recs[idx]
            note.append('单字节码 0x%02X → FT rec[%d]=(%d,%d,%d,%d)' % (b, idx, r[2], r[3], r[4], r[5]))
        elif ok:
            note.append('单字节码 0x%02X 超出 FT 记录表 (idx=%d)' % (b, idx))
        note.append(engine_note(ch, b) or 'FT 记录表')
        if latin1:
            info2 = icon_table.NOT_ICON_CODES[b]
            note.append('⚠ **不是手柄图标**: 0x%02X 是 Latin-1 的 %s (%s) —— round42 定性、'
                        'round43 起它就在 charset 的 codes 里, 引擎按**普通字母**画 (走字形路径); '
                        '老 CSV 的 %s 标记是**历史别名**, 注入器仍接受, 且与本行这个字母'
                        '写出的字节完全相同'
                        % (b, info2['latin1'], info2['name'],
                           tcslib.BTN_FMT % (tcslib.Charset.PUA_BASE + b)))
        if why:
            note.append(why)
        cx, cy, lx, ly = rec_cells(ch, b)
        rows.append(dict(char=ch, unicode='U+%04X' % ord(ch),
                         kind=('latin1' if latin1 else 'single'),
                         bytes_hex='%02X' % b, slot='',
                         cell_x=cx, cell_y=cy, cell_legacy_x=lx, cell_legacy_y=ly,
                         has_glyph=hg, glyph_basis=basis(ch), note='; '.join(n for n in note if n)))

    # ③ 对偶码 (走**引擎格位公式**; lead≥上界的是「死 pair」, 引擎读不了 —— 照列, 但 note 标出来)
    for ch, (b1, b2) in sorted(cs.enc_pair.items(), key=lambda kv: tcslib.pair_slot(*kv[1])):
        slot = tcslib.pair_slot(b1, b2)
        row, col = slot // tcslib.NCOL, slot % tcslib.NCOL
        ph = tcslib.atlas_row_phase(row)
        fx, fy = tcslib.atlas_cell_xy_engine(slot)      # flat 口径 (= 引擎坐标 + 每段 6 格)
        x, y = tcslib.atlas_cell_xy_engine_view(slot)   # ★ 引擎采样坐标 (无相位)
        lx, ly = tcslib.atlas_cell_xy(slot)
        hg, why = glyph(ch)
        note = ['引擎格 slot=%d (row=%d, col=%d, 行相位 PHI=%d%s)'
                % (slot, row, col, ph, ', x 回绕 ⇒ y 低 1 行' if col + ph >= tcslib.GRID_MOD else ''),
                'legacy 两列 = 旧口径 (4+16×col, 非引擎位置)']
        if not (tcslib.PAIR_LEAD_LO <= b1 < tcslib.PAIR_LEAD_HI):
            note.append('★死 pair: lead=0x%02X ≥ 0x%02X, 引擎读成两个单字节 ⇒ 写出去是乱码 '
                        '(编码器已拒绝写出)' % (b1, tcslib.PAIR_LEAD_HI))
        if why:
            note.append(why)
        rows.append(dict(char=ch, unicode='U+%04X' % ord(ch), kind='pair',
                         bytes_hex='%02X%02X' % (b1, b2), slot=slot,
                         cell_x=x, cell_y=y, cell_flat_x=fx, cell_flat_y=fy,
                         cell_legacy_x=lx, cell_legacy_y=ly,
                         has_glyph=hg, glyph_basis=basis(ch), note='; '.join(note)))

    # ④ 未映射字节: 引擎认的**文本图标码** (只有 0xB1/0xB5) + 其余空字节 (如实标注)
    for b in icon_bytes(cs):
        ch = chr(tcslib.Charset.PUA_BASE + b)
        mark = tcslib.BTN_FMT % (tcslib.Charset.PUA_BASE + b)
        info = icon_table.icon_info(b)
        if info:
            note = ('★引擎认的**文本图标码** = %s (%s); UV 硬编码于 DrawString v1 %s; '
                    '引擎直接画图标, **不吃字库**; %s'
                    % (info['name'], info['key'], info['elf_evidence'], info['note']))
            kind, glyph, basis = 'icon', 1, 'engine_icon'
        elif icon_table.is_known_not_icon(b):
            info2 = icon_table.NOT_ICON_CODES[b]
            note = ('⚠ **不是图标**: 0x%02X 是 Latin-1 的 %s (%s); %s; '
                    '引擎按普通字形画 ⇒ 该字节**不能**当手柄图标码用'
                    % (b, info2['latin1'], info2['name'], info2['evidence']))
            kind, glyph, basis = 'latin1', 1, 'ft_record'
        else:
            note = ('空字节 0x%02X —— 本盘字符表里没有映射, 也**不是**引擎认的图标码; '
                    '★「空出来的字节」≠「新的图标码」: 引擎只认 0xB1(△)/0xB5(✕) 两个值 '
                    '(DrawString v1 写死), 写别的字节只会走字形路径 ⇒ 画不出图标'
                    % b)
            kind, glyph, basis = 'unmapped', '', 'none'
        rows.append(dict(char=mark, unicode='U+%04X' % (tcslib.Charset.PUA_BASE + b),
                         kind=kind, bytes_hex='%02X' % b, slot='',
                         cell_x='', cell_y='', cell_legacy_x='', cell_legacy_y='',
                         has_glyph=glyph, glyph_basis=basis, note=note))
    return rows


# ═══════════════════════════ 容量 / 用量 ═══════════════════════════

def _live_rects(cs, faces, atlas_w):
    """全部**活字形采样窗** (对偶格 ∪ 三个 face 的 FT 记录窗) —— 给「严格干净」判据用。

    与 tools/iso_build/patch_zh93_planc.py 的 LIVE 同口径: 写新字形时, 16x16 的写入框
    必须与这些窗**零交叠** (交叠了就是污染别人的采样窗)。
    """
    rects = []
    for (_b1, _b2) in cs.enc_pair.values():
        # ★ round46: 与 capacity_report 的"数墨"同一口径 —— 活字形采样窗 = **引擎格**
        x, y = tcslib.atlas_cell_xy_engine_view(tcslib.pair_slot(_b1, _b2))
        rects.append((x, y, x + tcslib.CW, y + tcslib.CH))
    for (_nm, _fld, recs) in faces:
        for (_b0, _b1, u0, v0, u1, v1) in recs:
            if u1 <= u0 or v1 <= v0:
                continue
            rects.append((u0, v0, u1, v1))
            rects.append((u0 + tcslib.GLYPH_DU, v0 + tcslib.GLYPH_DV,
                          u1 + tcslib.GLYPH_DU, v1 + tcslib.GLYPH_DV))
            for row in range(64):
                y = tcslib.GRID_Y0 + tcslib.CH * (row + (tcslib.GRID_SKIP_ROWS
                                                         if row >= tcslib.GRID_SKIP_ROW else 0))
                if y == v0:
                    x = (u0 + tcslib.CW * tcslib.atlas_row_phase(row)) % atlas_w
                    rects.append((x, y + 1, x + tcslib.CW, y + 1 + tcslib.CH))
                    break
    return rects


def capacity_report(cs, cache, faces, atlas_ink, atlas_w, atlas_h):
    """字库「容量 / 已用 / 还能加多少」—— ★ 全部**按当前 charset 动态算**, 不写死任何数字。

    口径全部来自 tcslib 的常量 (LEAD_LO/LEAD_HI/PAIR_TRAIL_*/pair_capacity/引擎格位公式),
    ⇒ lead 上界变了 (历史 0xAE → 现在 0xB1)、charset 扩了字, 这里都会自动跟着变。
    """
    cap = tcslib.pair_capacity()
    lead_lo, lead_hi = tcslib.LEAD_LO, tcslib.LEAD_HI

    used_in, used_out = {}, {}
    for ch, (b1, b2) in cs.enc_pair.items():
        if lead_lo <= b1 < lead_hi and tcslib.PAIR_TRAIL_LO <= b2 <= tcslib.PAIR_TRAIL_HI:
            used_in.setdefault(tcslib.pair_slot(b1, b2), ch)
        else:
            used_out[ch] = (b1, b2)
    free = [s for s in range(cap) if s not in used_in]

    # 「引擎格真的空」= 该 slot 的引擎格里一个墨点都没有 ⇒ 新字直接写进去即可
    # (字库没装载时没法看图集 ⇒ 一律算"需回收", 并靠 font_loaded=False 标明这层含义)
    # ★ round46 订正: 这里必须用 **引擎采样格** `atlas_cell_xy_engine_view` (x = 16*col, 无相位)。
    #   原来用 `atlas_cell_xy_engine` (x = 16*((col+PHI[row])%64), 那是**flat 容器口径**的列),
    #   而 `cache.cell_ink()` 从 round45 起按**引擎图**取行 ⇒ 两者混用会去读**别的格子的墨**,
    #   "现在就能直接放新字的有几个" 这个数就不可信 (实测 GR_ZH94 旧口径 34 / 订正后 42;
    #   重排后旧口径会给出远低于真值的数)。CSV 的 cell_x/cell_y 列语义**不变**
    #   (仍是 atlas_cell_xy_engine, 见 _grid_selfcheck), 这里只订正"数墨"用的坐标。
    vacuum, recycle = [], []
    rows_vac = {}
    for s in free:
        x, y = tcslib.atlas_cell_xy_engine_view(s)
        n = cache.cell_ink(x, y) if cache.font_ok else -1
        row = s // tcslib.NCOL
        if n == 0:
            vacuum.append(s)
            rows_vac[row] = rows_vac.get(row, 0) + 1
        else:
            recycle.append(s)

    # 更严格口径: 引擎格空 **且** 与全部活字形采样窗零交叠 (planc 写新字时用的判据)
    live = _live_rects(cs, faces, atlas_w) if cache.font_ok else []
    strict = []
    for s in vacuum:
        x, y = tcslib.atlas_cell_xy_engine_view(s)
        if not any(x < rx1 and rx0 < x + tcslib.CW and y < ry1 and ry0 < y + tcslib.CH
                   for (rx0, ry0, rx1, ry1) in live):
            strict.append(s)

    # 单字节码: 0x80..0xFF 里既没映射、也不是任何对偶 lead 的字节 = 引擎拿去画图标
    used_single = sorted(cs.codes)
    pair_leads = set(b1 for (b1, _b2) in cs.enc_pair.values())
    spare = sorted(set(range(0x80, 0x100)) - set(cs.codes) - pair_leads)
    icons = [b for b in spare if SINGLE_BAND[0] <= b <= SINGLE_BAND[1]]
    # ★ round43: 单字节码里区分「汉字」与「拉丁字母 (ç/ñ)」—— 两者都在 codes 里, 但报告要分开说
    latin1_bytes = [b for b in used_single if icon_table.is_known_not_icon(b)]

    n_charset = len(set(cs.enc_single) | set(cs.enc_pair))
    tot_texels = atlas_w * atlas_h
    return dict(
        pair=dict(capacity=cap, used=len(used_in), free=len(free),
                  font_loaded=bool(cache.font_ok),
                  lead_range='0x%02X..0x%02X' % (lead_lo, lead_hi - 1), leads=lead_hi - lead_lo,
                  trail_range='0x%02X..0x%02X' % (tcslib.PAIR_TRAIL_LO, tcslib.PAIR_TRAIL_HI),
                  trails=tcslib.PAIR_STRIDE,
                  formula='slot=(lead-0xA1)*94+(trail-0xA1); 容量=(lead 上界-lead 下界)×94',
                  vacuum_usable=len(vacuum), need_recycle=len(recycle),
                  vacuum_rows=dict(sorted(rows_vac.items())),
                  vacuum_slots=vacuum,
                  strict_window_free=len(strict),
                  strict_window_free_slots=strict,
                  used_dead=len(used_out), dead_chars=''.join(sorted(used_out))),
        single=dict(used=len(cs.enc_single), used_bytes=['%02X' % b for b in used_single],
                    used_hanzi=len(cs.enc_single) - len(latin1_bytes),
                    used_latin1=len(latin1_bytes),
                    latin1_bytes=['%02X' % b for b in latin1_bytes],
                    latin1_chars=[cs.codes[b] for b in latin1_bytes],
                    spare_bytes=['%02X' % b for b in spare],
                    spare_is_icon_bytes=['%02X' % b for b in icons],
                    really_usable=len([b for b in spare if b not in icons]),
                    note='0x80..0xFF 里「没映射 + 不是任何对偶 lead」的字节 = 本盘**空着**的字节。'
                         '★ round42 修正: 空着 ≠ 图标码 —— 引擎认的文本图标码只有 '
                         '0xB1(△)/0xB5(✕) 两个 (DrawString v1 写死), '
                         '其余空字节写出去只会走字形路径。'
                         '★ round43: ç(0xE7)/ñ(0xF1) 已进 charset 的 codes ⇒ 它们是**拉丁字母**'
                         '单字节码, 不再算"未映射字节"; used 里汉字 %d + 拉丁字母 %d。'
                         '详见 summary.json 的 icons 一节'
                         % (len(cs.enc_single) - len(latin1_bytes), len(latin1_bytes))),
        charset=dict(unique_chars=n_charset, single=len(cs.enc_single), pair=len(cs.enc_pair),
                     single_hanzi=len(cs.enc_single) - len(latin1_bytes),
                     single_latin1=len(latin1_bytes),
                     pair_plus_single=len(cs.enc_single) + len(cs.enc_pair),
                     ascii_rows=95, icon_rows=len(icons),
                     latin1_rows=len(latin1_bytes),
                     dump_total=95 + len(icons) + len(cs.enc_single) + len(cs.enc_pair),
                     note='charset 口径 = JSON 里真有的字 (单字节+对偶, 去重); '
                          'dump 口径 = 再加 ASCII 95 个 + 按键图标行 (latin1 行在单字节码里, '
                          '不重复计)'),
        atlas=dict(width=atlas_w, height=atlas_h, texels=tot_texels,
                   ink_texels=atlas_ink,
                   ink_ratio=round(100.0 * atlas_ink / tot_texels, 2),
                   pair_cell_ratio=round(100.0 * len(used_in) / cap, 2),
                   note='ink_ratio = 墨 texel 占全图集; pair_cell_ratio = 已被对偶字占用的'
                        '引擎格 / 总格数'),
        verdict=dict(new_chars_fit_now=len(vacuum),
                     new_chars_fit_strict=len(strict),
                     new_chars_fit_after_recycle=len(free),
                     single_codes_left=len([b for b in spare if b not in icons])),
        dynamic='★ 以上全部按**当前 charset + 当前 tcslib 常量**动态算: lead 上界变 (0xAE→0xB1)、'
                'charset 扩字, 数字都会自动跟着变; 没有任何写死的 1504/1319。')


def _grid_selfcheck(out_dir, prefix, n_slots):
    """自查: 把**刚写出的 CSV** 读回来, 对**全部 n_slots 个 slot** 逐个复核引擎格位公式。

    ① CSV 里出现过的 slot: cell_x/cell_y 必须逐位等于 tcslib.atlas_cell_xy_engine_view(slot)
       (round51 订正: CSV 的 cell_x/cell_y 现在是**引擎采样坐标**; flat 口径另存 cell_flat_x/cell_flat_y);
    ② 全部 n_slots 个 slot (含没被占用、CSV 里没有的): 公式必须给出图集内的合法格, 不重不漏;
    ③ CSV 里不许出现容量范围外的 slot。
    """
    p = os.path.join(out_dir, prefix + '_font_charset.csv')
    got, dup, oor = {}, [], []
    with io.open(p, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            if r['kind'] != 'pair' or not r['slot']:
                continue
            s = int(r['slot'])
            if s in got:
                dup.append(s)
            if not (0 <= s < n_slots):
                oor.append(s)
            got[s] = (int(r['cell_x']), int(r['cell_y']))
    bad, seen_cell, not_in_csv = [], set(), 0
    for s in range(n_slots):
        x, y = tcslib.atlas_cell_xy_engine_view(s)
        seen_cell.add((x, y))
        if s in got:
            if got[s] != (x, y):
                bad.append((s, got[s], x, y))
        else:
            not_in_csv += 1
    return dict(checker='tcslib.atlas_cell_xy_engine_view (引擎采样坐标, 无相位; flat 口径另存 cell_flat_*)',
                slots_capacity=n_slots, slots_compared=n_slots,
                slots_in_csv=len(got), slots_not_in_csv=not_in_csv,
                distinct_cells=len(seen_cell), duplicate_slots=len(dup),
                out_of_range=len(oor), mismatched=len(bad), examples=bad[:5],
                ok=(not bad and not dup and not oor and len(got) <= n_slots))


# ═══════════════════════════ 落盘 ═══════════════════════════

def _write_csv(path, cols, rows):
    with io.open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, lineterminator='\r\n')          # 工程约定: UTF-8 BOM + CRLF (Excel 友好)
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, '') for c in cols])


def _file_info(path):
    return dict(path=rel(path), bytes=os.path.getsize(path), sha256=sha256_file(path))


def grid_row_alignment():
    """每行「写入侧(flat 口径)格」与「引擎采样格」的差 (单位=格, 0 = 同一个物理位置)。

    = (PHI[row] - flat_x_shift(yrow(row))/16) mod 64。
    非 0 ⇒ 这一行的字形**不在引擎会采样的格上**(引擎会画成同排别的字) —— round44 查实:
    grid 行 0..18 = 0 (历史实证全对得上); 行 19..24 ≠ 0 (新扩的 lead 空间)。
    """
    out = {}
    last_row = (tcslib.pair_capacity() - 1) // tcslib.NCOL      # 只有这些行可能落到槽位
    for row in range(0, last_row + 1):
        y = tcslib.GRID_Y0 + tcslib.CH * (row + (tcslib.GRID_SKIP_ROWS if row >= tcslib.GRID_SKIP_ROW else 0))
        if y + tcslib.CH > 512:
            break
        out[row] = (tcslib.atlas_row_phase(row) - tcslib.atlas_flat_x_shift(y) // tcslib.CW) % 64
    return out


def _atlas_readme(prefix, atlas, seg_diag, view, cells, has_sampled, bad_rows=None):
    """PNG 旁边的人话说明 (给非程序员看)。bad_rows = 字形不在引擎采样格上的网格行号。"""
    w, h = atlas['w'], atlas['h']
    segs = seg_diag.get('segments') or []
    L = []
    A = L.append
    A('=' * 74)
    A('%s 字库图集 —— 看图须知 (由 tools/iso_build/dump_font.py 自动生成, 可随 dump 一起复制)' % prefix)
    A('=' * 74)
    A('')
    A('一、这张图是什么')
    A('  %s_font_atlas.png = 本盘字库贴图 (%dx%d, psm=0x%02X)。黑 = 有笔画(墨), 白 = 空。'
      % (prefix, w, h, atlas['psm']))
    A('')
    A('二、图上"最左上角那一行断续的像素"是什么? (round44 查实)')
    A('  不是字形, 也不是"原版数据" —— 那是贴图数据流里的 **DMA 包头**。')
    A('  游戏把贴图交给 PS2 显卡时, 数据是一串 "GIF 封包": 每 64 行数据前面有 48 字节包头')
    A('  (告诉显卡这段数据放到显存哪一行)。显卡把这些字节当**命令**吃掉, 它们**永远不是像素**。')
    A('  旧版 dump 把整块数据当普通图片逐行读, 于是:')
    A('    · 第 0 行那 88~96 个墨点 = 第 1 段的那 48 字节包头;')
    A('    · 第 64/128/192/… 像素行再来一次 ⇒ 看起来"每隔 4 个字形行出现一次撕裂纹样";')
    A('    · 每一段的内容还被整体右移了 6 格 (96 像素)。')
    A('  ⇒ **是 dump 工具的读法错了; 盘上的数据是好的, 游戏内也看不到任何异常。**')
    A('')
    A('三、现在这张图是什么口径')
    if view == 'engine':
        A('  默认就是 **引擎真正看到的图**: 已按封包把每段数据放回正确的行,')
        A('  所以第 0/1 行是干净的空白, 没有虚线, 也没有 6 格错位。')
    else:
        A('  ★ 本次是用 --flat-view 生成的**旧口径对照图** (整块当裸图): 会看到包头被画成像素、')
        A('    每 64 行一次"撕裂"、每段右移 6 格。**这不是游戏里看到的样子**, 只作查错对照。')
    A('  想看另一种口径: %s --flat-view 重跑。' % ('去掉' if view == 'flat' else '加上'))
    A('')
    A('四、哪些像素引擎永远不采样 (游戏内不可见)')
    A('  · 第 0、1 行 (字形网格从第 2 行开始);')
    A('  · 每个网格行最右侧那几格的"回绕副本"位置, 以及图集最底部没有网格行的区域;')
    A('  · 本盘 %d 段 × %d 字节的包头 (引擎口径图里已剔除)。'
      % (len(segs) or 1, tcslib.ATLAS_PREFIX_BYTES))
    if has_sampled:
        A('  本次已另出 %s_font_atlas_sampled.png: 只拼**引擎会采样的格**' % prefix)
        A('  (62 列 × 用到的网格行) + 底部一条记录带(ASCII/单字节码), 彻底避开上述区域。')
    else:
        A('  想彻底避开这些区域: 加 --only-sampled 重跑, 会另出一张 *_font_atlas_sampled.png。')
    A('')
    A('五、ASCII 字母/数字在哪')
    A('  它们不在 16x16 网格里, 而是由 FONT.RES 的"记录矩形"直接采样 ⇒ 在图集下部那条带里。')
    A('  每个码位的矩形见 %s_font_ft.csv; 字符与码位的对应见 %s_font_charset.csv。'
      % (prefix, prefix))
    A('')
    A('六、可复现性')
    A('  同一张盘 dump 两次, 本目录所有文件逐字节相同 (产物不含时间戳); 各文件 sha256 见 summary.json。')
    A('')
    A('七、已知限制 (如实说明, 别当成工具 bug)')
    A('  · 本盘容器共 %d 段 (每段 %s 字节包头): %s'
      % (len(segs) or 1, tcslib.ATLAS_PREFIX_BYTES,
         ', '.join('行%d起' % s['first_row'] for s in segs[:8]) if segs else '单包 (原版形态)'))
    A('  · CSV 的 cell_x/cell_y 仍是**旧 flat 口径**的坐标 (= 引擎坐标 + 6 格/段), 本轮**没有改**,')
    A('    以免影响下游工具; 换算与每行的对齐表见 summary.json 的 atlas_artifact 一节。')
    if bad_rows:
        A('  · ⚠ 本盘网格行 %s 的字形目前**不在引擎采样格上**(偏 22~42 格): 这些槽位在游戏里'
          % '/'.join(str(r) for r in bad_rows))
        A('    会显示成**同一排里另一个字**的字形。这是盘上数据的放置问题 (历史遗留),')
        A('    **不是 dump 工具的问题, 也不是本轮改动引入的**; 需要一次实机 A/B 才能定论,')
        A('    详见 docs/REPORT_atlas_artifact.md 第 4 节 (含影响面: 涉及槽位/字符数).')
    else:
        A('  · 本盘没有"字形不在引擎采样格上"的网格行 ⇒ 图集放置与引擎采样一一对应。')
    A('')
    A('八、一句话')
    A('  以后看图就看这张 *_font_atlas.png (引擎口径); 看到"左上角一行小点/每 4 行撕裂"')
    A('  只可能是有人用 --flat-view 或老版本工具生成的图。')
    A('')
    return '\n'.join(L)


def dump_font(iso_path, out_dir, prefix, scale=2, want_png=True, iso_sha=None, verbose=True,
              view='engine', grid=False, labels=False, only_sampled=False):
    """把字库 dump 到 out_dir/<prefix>_font_*; 返回写进 build_info.json 的摘要 dict。

    view='engine' (默认) / 'flat'  —— 见 atlas_gray() 的说明 (engine = 引擎真正看到的像素)。
    grid/labels      —— 主图叠加引擎格线 / 行列号+slot 号 (输出 RGB PNG)。
    only_sampled     —— 另出一张 `_font_atlas_sampled.png`: 只拼引擎会采样的格 (+ 记录带)。
    """
    t0 = time.time()
    iso_path = os.path.abspath(iso_path)
    if not os.path.isfile(iso_path):
        raise SystemExit('!! 找不到 ISO: %s' % iso_path)
    os.makedirs(out_dir, exist_ok=True)

    font = load_font(iso_path)
    cs = tcslib.Charset()
    # ★ 字形检查一律用 tcslib 的现成检查器 (GlyphCache): 它按盘上实测口径
    #   (FT 记录表 + 网格公式 + 邻域容差) 判定「这个字画得出来吗」, 本脚本不重写这套逻辑。
    cache_iso = tcslib.Iso(iso_path)
    try:
        cache = tcslib.GlyphCache(cs, cache_iso)
        notes = list(cache.notes())
        if not cache.font_ok:
            notes.append('字库未装载 ⇒ has_glyph/has_ink 留空 (CSV 结构照出)')

        # ① 图集像素 → 二值化灰度 (墨=0/空=255) + 墨点数统计; PNG 只是它的一个视图
        gray = atlas_gray(font['atlas'], view=view)
        _raw_engine, seg_diag = pixels_engine_order(font['atlas'])
        atlas_ink = gray.count(0)
        cells = engine_cells(cs)
        png_p = os.path.join(out_dir, prefix + '_font_atlas.png')
        if want_png:
            write_atlas_png(gray, font['atlas'], png_p, scale=scale,
                            grid=(grid or labels), labels=labels, cells=cells)
        sampled_p = os.path.join(out_dir, prefix + '_font_atlas_sampled.png')
        sampled_info = None
        if want_png and only_sampled:
            sw_, sh_, nr_ = write_sampled_png(gray, font['atlas'], cs, font['faces'],
                                              sampled_p, scale=scale, labels=True)
            sampled_info = dict(path=rel(sampled_p), width=sw_, height=sh_,
                                grid_rows=nr_, scale=scale,
                                note='只拼引擎会采样的格 (对偶格 + 记录带), 不含包头/边角/回绕副本')

        # ② FT 记录表
        frows = ft_rows(cache, font['faces'])
        ft_p = os.path.join(out_dir, prefix + '_font_ft.csv')
        _write_csv(ft_p, FT_COLS, frows)

        # ③ 字符集清单
        crows = charset_rows(cs, cache)
        cs_p = os.path.join(out_dir, prefix + '_font_charset.csv')
        _write_csv(cs_p, CS_COLS, crows)
    finally:
        cache_iso.close()

    # ③b ★ round50: 字形几何体检 (截断/空白/越窗/错位) —— 结构化判据, 不用 ±4/±2 容差窗。
    #     结果进 summary.json 的 `glyph_geometry` 段 + 同目录 truncation_report.{json,md}
    #     ⇒ 以后**每次 dump 都会自动发现**这类问题, 不用靠人肉看 PNG。
    geom = None
    try:
        geom = glyph_geometry.analyze(gray, font['atlas'], font['faces'], cs,
                                      iso_path=iso_path, iso_sha256=iso_sha,
                                      verbose=False)
        _gj, _gm = glyph_geometry.write_reports(geom, out_dir, prefix)
        geom['report_json'] = rel(_gj)
        geom['report_md'] = rel(_gm)
        if geom['verdict']['errors']:
            notes.append('!! 字形几何体检有 %d 个**错误**: %s'
                         % (geom['verdict']['errors'], geom['one_line']))
        for r in geom['findings']:
            if r['level'] == glyph_geometry.LV_E:
                notes.append('!! 字形几何: %s' % glyph_geometry._finding_line(r))
    except Exception as _ex:                                     # noqa: BLE001
        notes.append('字形几何体检未跑成 (%s) —— 不影响其余产物' % _ex)

    # ④ 汇总
    atlas = font['atlas']
    nrec_total = sum(len(f[2]) for f in font['faces'])
    assert len(frows) == nrec_total, 'FT 行数 %d != 记录数 %d' % (len(frows), nrec_total)
    by_kind = {}
    for r in crows:
        by_kind[r['kind']] = by_kind.get(r['kind'], 0) + 1
    n_glyph = sum(1 for r in crows if r['has_glyph'] == 1)
    n_missing = sum(1 for r in crows if r['has_glyph'] == 0)
    missing = [r['char'] for r in crows if r['has_glyph'] == 0]
    n_ft_ink = sum(1 for r in frows if r['has_ink'] == 1)
    n_ft_no = sum(1 for r in frows if r['has_ink'] == 0)
    px_used = atlas['w'] * atlas['h'] // 2            # 图集像素平面实际用的字节 (4bpp)
    px = atlas['pak'][atlas['px_off']: atlas['px_off'] + px_used]
    files = dict(ft_csv=_file_info(ft_p), charset_csv=_file_info(cs_p))
    if want_png:
        files['atlas_png'] = _file_info(png_p)
        if sampled_info:
            files['atlas_sampled_png'] = _file_info(sampled_p)
    # 图例/说明: PNG 旁边放一份人话 (非程序员也看得懂); summary.json 里同时有结构化版本
    readme_p = os.path.join(out_dir, prefix + '_font_atlas_README.txt')
    _drift = grid_row_alignment()
    _used_rows = set(tcslib.pair_slot(*p) // tcslib.NCOL for p in cs.enc_pair.values())
    _bad_rows = [r for r, d in sorted(_drift.items()) if d and r in _used_rows]
    readme_txt = _atlas_readme(prefix, atlas, seg_diag, view, cells,
                               bool(only_sampled and want_png), _bad_rows)
    with io.open(readme_p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(readme_txt)
    files['atlas_readme'] = _file_info(readme_p)

    # ⑤ 容量 / 用量 (按当前 charset 动态算) + 引擎格位自查
    capr = capacity_report(cs, cache, font['faces'], atlas_ink, atlas['w'], atlas['h'])
    selfchk = _grid_selfcheck(out_dir, prefix, capr['pair']['capacity'])
    if not selfchk['ok']:
        notes.append('!! 引擎格位自查未通过: %d 个 slot 的 cell_x/cell_y 与 '
                     'tcslib.atlas_cell_xy_engine 不一致 (CSV 里的 slot 数 %d / 容量 %d)'
                     % (selfchk['mismatched'], selfchk['slots_in_csv'], selfchk['slots_capacity']))
    n_pair_ok = sum(1 for r in crows if r['kind'] == 'pair' and r['has_glyph'] == 1)
    if cache.font_ok and n_pair_ok != capr['pair']['used']:
        notes.append('!! 对偶字字形覆盖不全: 有字形 %d / 已用 %d'
                     % (n_pair_ok, capr['pair']['used']))

    summ = dict(
        tool='tools/iso_build/dump_font.py',
        reproducible='本文件及三个 CSV/PNG/README 都不含时间戳: 同一 ISO dump 两次, sha256 完全相同',
        how_to_read=dict(
            atlas_png='字库图集 (默认=**引擎口径**, 见 atlas_artifact): 黑=有墨(字形), 白=空; '
                      '默认 2 倍最近邻放大; --grid 叠引擎格线, --labels 再加行列号/slot 号',
            atlas_readme='同一目录的 *_font_atlas_README.txt: 上面这些事的人话版 (给非程序员看)',
            atlas_sampled_png='--only-sampled 时另出: 只拼引擎会采样的格, 没有包头/边角/回绕副本',
            ft_csv='码位 → 图集位置 的记录表 (ASCII/单字节走这张表); has_ink=0 表示这个码位画不出来',
            charset_csv='本盘能打出的字符清单 (ascii/single/pair/icon); '
                        'cell_x/cell_y = **旧 flat 口径**的采样窗左上角 (见 atlas_artifact); '
                        'has_glyph=0 = 缺字形, 会画成空白',
            summary_json='本文件: 上面几样的统计、**字库容量/用量**、图集结构与 sha256'),
        capacity=capr,
        grid_selfcheck=selfchk,
        # ★ round50: 字形几何体检 (结构性判据; 见 tools/iso_build/glyph_geometry.py)
        glyph_geometry=geom,
        atlas_artifact=dict(
            one_line='像素容器是 **GIF 封包流** (DMA 命令 + 数据), 不是裸图; 旧 dump 把 48B 包头'
                     '当像素画 ⇒ 图上"最左上角一行断续像素"与"每 64 行(每 4 个字形行)一次撕裂"'
                     '**全是读法问题**, 盘上数据与游戏内都正常。',
            container=seg_diag,
            prefix_bytes=tcslib.ATLAS_PREFIX_BYTES,
            view=view,
            grid=bool(grid or labels), labels=bool(labels),
            sampled_png=sampled_info,
            flat_vs_engine='flat(旧口径) 视图 = 引擎视图**右移 96×(段号+1) texel** (每段 6 格, 带行进位);'
                           ' 实测逐行差异 0 (temp/r44/s4_copies.py §A)',
            y0_artifacts='旧口径图第 0 行的 88~96 个墨点 = 第 1 段 48 字节包头'
                         ' (PT tag + TRXPOS A+D + IMAGE tag), 逐字节可复现 (make_pak.py 同款)',
            engine_sampling='引擎采样 = 网格格 (x=16*col, y=yrow(row), **无相位**) + FT 记录矩形;'
                            ' 第 0/1 行、每行右侧回绕格、末段之后都不被采样',
            never_sampled_pixels='第 0/1 行 + 每行右侧回绕副本区 + 图集底部无网格行区 + 8×48B 包头',
            grid_row_alignment=grid_row_alignment(),
            grid_rows_misplaced=_bad_rows,
            grid_row_alignment_note='每行 (写入侧 flat 格 - 引擎采样格) 的差(格); 0 = 同一个物理位置。'
                                    '行 0..18 = 0 (历史实证因此全对得上); 行 19..24 ≠ 0 ⇒ '
                                    '那些槽位的字形不在引擎采样格上 (详见 docs/REPORT_atlas_artifact.md §4)',
            csv_cell_xy_note='CSV 的 cell_x/cell_y 本轮**未改** (仍是写入侧/旧 dump 的口径); '
                             '换算到引擎坐标: engine_x = (cell_x - 96*(y//64+1)) % 图集宽 '
                             '(带行进位), engine_y = cell_y; 反向: flat_x = engine_x + 96*(y//64+1)',
            evidence=['tcslib.atlas_container_segments: 包头逐字节 = make_pak.py 产物',
                      '盘上自己的 ASCII FT 记录矩形: 引擎口径 94/94 有墨 / 旧口径 61/94, '
                      '33 条只有引擎口径有墨、反向 0 条',
                      'TTF(方正像素16) 模板: 引擎口径图 grid 行 0..18 逐像素 0 误差命中 x=16*col',
                      'ELF cctc cave (hook 0x21ADE0 → 0x417050) 汇编: U0 = 16*col, 无相位表',
                      'docs/REPORT_atlas_artifact.md (本轮完整报告)']),
        source_iso=rel(iso_path),
        source_iso_sha256=iso_sha or sha256_file(iso_path),
        font_res=dict(index=font['ft_idx'], name=FT_NAME,
                      container_offset=font['ft_e']['off'],
                      iso_offset=font['ft_e']['iso_off'], stored=font['ft_e']['stored'],
                      expanded=len(font['ft_blob']),
                      slot_sha256=sha256_bytes(font['ft_slot']),
                      expanded_sha256=sha256_bytes(font['ft_blob'])),
        atlas=dict(index=font['pak_idx'], name=PAK_NAME, record=atlas['name'],
                   container_offset=font['pak_e']['off'],
                   psm=atlas['psm'], width=atlas['w'], height=atlas['h'],
                   px_offset_in_pak=atlas['px_off'], px_size_declared=atlas['px_size'],
                   pixel_bytes_used=px_used, pixel_sha256=sha256_bytes(px),
                   ink_texels=atlas_ink, total_texels=atlas['w'] * atlas['h']),
        faces=[dict(index=i, name=f[0], records=len(f[2]),
                    nrec_field=(f[1][4] * f[1][5]), fields=list(f[1]))
               for i, f in enumerate(font['faces'])],
        counts=dict(faces=len(font['faces']), ft_records=nrec_total,
                    ft_records_with_ink=n_ft_ink, ft_records_without_ink=n_ft_no,
                    charset_rows=len(crows), by_kind=by_kind,
                    has_glyph=n_glyph, missing_glyph=n_missing),
        # ★ round42: 手柄图标码总表 (含**未被任何文本使用**的码) —— 不再只看"文本里出现过的"
        icons=dict(
            tool='tools/text_csv/icon_table.py',
            engine_icon_codes=[
                dict(byte='%02X' % r['byte'], mark=tcslib.BTN_FMT % r['pua'],
                     key=r['key'], name=r['name'], uv=list(r['uv']),
                     verified=r['verified'], elf=r['elf_evidence'], note=r['note'])
                for r in icon_table.all_icons()],
            engine_icon_count=len(icon_table.all_icons()),
            engine_icon_bytes=['%02X' % b for b in icon_table.engine_icon_bytes()],
            not_icon_codes=[
                dict(byte='%02X' % b, mark=tcslib.BTN_FMT % r['pua'],
                     latin1=r['latin1'], name=r['name'], evidence=r['evidence'])
                for b, r in sorted(icon_table.NOT_ICON_CODES.items())],
            candidate_bytes=['%02X' % b for b in icon_bytes(cs)],
            candidate_count=len(icon_bytes(cs)),
            usage_in_text={},          # 由调用方按需填 (本脚本只列全集)
            shortcut_system=dict(func=icon_table.SHORTCUT_SYSTEM['func'],
                                 va='0x%08X' % icon_table.SHORTCUT_SYSTEM['va'],
                                 indices=list(icon_table.SHORTCUT_SYSTEM['indices']),
                                 texture=icon_table.SHORTCUT_SYSTEM['texture'],
                                 note=icon_table.SHORTCUT_SYSTEM['note']),
            evidence='ELF SLUS_206.13: DrawString v1 @0x219A70 是全 ELF 唯一带字符循环的'
                     '绘制入口, 它对字符值只有 3 个特判 (0x20 空格 / 0xB5 / 0xB1); '
                     '图标 UV 硬编码在 0x219C4C..0x219C8C; 图标走独立的 '
                     'UISpriteModel(this+76, 纹理 pda_counterparts.rsb), 不吃字库',
            how_to_read='engine_icon_codes = 引擎真正认的**文本图标码**(只有 2 个); '
                        'candidate_bytes = 本盘 0xB1..0xFF 里没被字符集占用的字节'
                        '(**只是"空着"**, 不等于图标码); '
                        'not_icon_codes = 未映射但**不是图标**的字节 (Latin-1 字母); '
                        'shortcut_system = 玩家在按钮提示栏看到的其它手柄图标 (UI 侧, 与文本码无关)'),
        glyph_face_checked=dict(
            face=tcslib.FONT_FACE_DEFAULT,
            name=(font['faces'][tcslib.FONT_FACE_DEFAULT][0]
                  if len(font['faces']) > tcslib.FONT_FACE_DEFAULT else '?'),
            note='单字节/ASCII 的字形判定由 tcslib.GlyphCache 按该 face 的记录表做 '
                 '(现役盘实测引擎用的就是这个 face)'),
        grid=dict(ncol=tcslib.NCOL, cw=tcslib.CW, ch=tcslib.CH, y0=tcslib.GRID_Y0,
                  skip_row=tcslib.GRID_SKIP_ROW, skip_rows=tcslib.GRID_SKIP_ROWS,
                  mod=tcslib.GRID_MOD, phi=tcslib.ATLAS_PHI,
                  formula='slot=(b1-0xA1)*94+(b2-0xA1); row=slot//ncol; col=slot%ncol; '
                          'p=col+PHI[row]; x=16*(p%64); y=2+16*(row+3*[row>=12])+(1 if p>=64 else 0)',
                  legacy_formula='x=4+16*col (旧口径, 见 tcslib.atlas_cell_xy; 不是引擎位置)',
                  checker='tcslib.atlas_cell_xy_engine_view(slot)',
                  evidence='1297 字模板比对: 本式 785 个 0 误差 / 无相位 0 个; '
                           '本盘 1319/1319 对偶字引擎格有墨; 回绕列 8/8 抽样命中 y+1; '
                           'row 24 相位实测 = 0 (该行 6 个字形模板 0 误差在 (u0,434))'),
        missing_glyph_chars=missing[:200],
        missing_glyph_truncated=(len(missing) > 200),
        png=dict(scale=scale, width=(atlas['w'] * scale if want_png else None),
                 height=(atlas['h'] * scale if want_png else None),
                 ink_pixels=atlas_ink, view=view, grid=bool(grid or labels), labels=bool(labels),
                 legend='黑 = 墨, 白 = 空; 最近邻放大; 默认 = 引擎口径 (按 GIF 封包还原); '
                        '--grid/--labels 时叠引擎格线 (淡红) / FT 记录矩形 (淡蓝) / 已用格角标 (蓝)'),
        files=files,
        notes=notes)
    summ_p = os.path.join(out_dir, prefix + '_font_summary.json')
    with io.open(summ_p, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(summ, f, ensure_ascii=False, indent=1)
    files['summary_json'] = _file_info(summ_p)
    summ['files'] = files                     # summary.json 的 sha256 由 build_info.json 记

    if verbose:
        print('[font] 字表 %s #%d @0x%X: 存 %d B → 展开 %d B, %d 个 face'
              % (FT_NAME, font['ft_idx'], font['ft_e']['iso_off'], font['ft_e']['stored'],
                 len(font['ft_blob']), len(font['faces'])))
        print('[font] 图集 %s #%d %s: %d×%d psm=0x%02X, 墨 %d/%d texel (%.2f%%)'
              % (PAK_NAME, font['pak_idx'], atlas['name'], atlas['w'], atlas['h'],
                 atlas['psm'], atlas_ink or 0, atlas['w'] * atlas['h'],
                 100.0 * (atlas_ink or 0) / (atlas['w'] * atlas['h'])))
        print('[font] 记录 %d 条 (有墨 %d / 无墨 %d) → %s'
              % (nrec_total, n_ft_ink, n_ft_no, rel(ft_p)))
        print('[font] 字符 %d 个 (%s) — 有字形 %d / 缺字形 %d → %s'
              % (len(crows), ' '.join('%s %d' % kv for kv in sorted(by_kind.items())),
                 n_glyph, n_missing, rel(cs_p)))
        # ── ★ round42: 手柄图标码总表 (含未被文本使用的码) ──
        print('[font] ┌─ 手柄图标码 (全集, 不依赖"文本里出现过没有") ──────────────')
        for r in icon_table.all_icons():
            print('[font] │ %s = 字节 0x%02X = %s (%s)%s'
                  % (tcslib.BTN_FMT % r['pua'], r['byte'], r['name'], r['key'],
                     '  实机/图集已验证' if r['verified'] else '  **未验证**'))
        print('[font] │ 引擎认的文本图标码共 %d 个 —— 它们是 DrawString v1 里写死的两个 if,'
              % len(icon_table.all_icons()))
        print('[font] │   所以**不存在**"没找到的更多图标码"; 空出来的字节也不会自动变成图标')
        cands = icon_bytes(cs)
        print('[font] │ 本盘 0xB1..0xFF 里没被字符集占用的字节 %d 个: %s'
              % (len(cands), ' '.join('%02X' % b for b in cands)))
        for b in cands:
            print('[font] │   0x%02X  %s' % (b, icon_table.describe(b, cs)))
        print('[font] │ 玩家在按钮提示栏看到的其它手柄图标 (△○✕□/左右键…) 来自 UI 快捷键系统')
        print('[font] │   %s @0x%08X (按**动作索引**取 UV, 与文本字节无关; 纹理 %s)'
              % (icon_table.SHORTCUT_SYSTEM['func'], icon_table.SHORTCUT_SYSTEM['va'],
                 icon_table.SHORTCUT_SYSTEM['texture'].split(' (')[0]))
        print('[font] └──────────────────────────────────────────────────────────')
        # ── 容量 / 用量: 先说人话结论, 再给细节 ──
        P, S, C, A = capr['pair'], capr['single'], capr['charset'], capr['atlas']
        print('[font] ┌─ 字库还能装多少字 ─────────────────────────────────────────')
        print('[font] │ 汉字 (对偶码): 总容量 %d 个 = %d 个 lead(0x%s) × %d 个 trail(0x%s)'
              % (P['capacity'], P['leads'], P['lead_range'][2:4] + '..' + P['lead_range'][-2:],
                 P['trails'], P['trail_range'][2:4] + '..' + P['trail_range'][-2:]))
        print('[font] │   已经用了 %d 个 ⇒ 还空着 %d 个位子' % (P['used'], P['free']))
        print('[font] │   ★ 其中**现在就能直接放新字**的只有 %d 个 (图集上那格是白的)'
              % P['vacuum_usable'])
        print('[font] │   ★ 另外 %d 个位子的格子上压着旧字形, 得先把旧字回收/重排才能用'
              % P['need_recycle'])
        print('[font] │   (最严格口径: 连"别人的采样窗"都不碰的干净格子 = %d 个; '
              '实在不够时上限 = 全部空位 %d 个)' % (P['strict_window_free'], P['free']))
        print('[font] │ 单字节码: 已经用了 %d 个' % S['used'])
        if S['spare_bytes']:
            print('[font] │   0x80..0xFF 里只剩 %d 个没主的字节: %s'
                  % (len(S['spare_bytes']), ' '.join(S['spare_bytes'])))
            print('[font] │   这 %d 个是**空字节** (其中 %d 个是手柄图标码 0xB1/0xB5, '
                  '译文里的 {{BTN:E0XX}} 要用, 动不得) '
                  '⇒ ★真正能用的单字节码 = %d 个'
                  % (len(S['spare_is_icon_bytes']), len(icon_table.engine_icon_bytes()),
                     S['really_usable']))
        else:
            print('[font] │   0x80..0xFF 已经一个空字节都不剩 ⇒ ★真正能用的单字节码 = 0 个')
        print('[font] │ 汉字总数: %d 个 (单字节 %d + 对偶 %d)  ← 这是「字符集」口径'
              % (C['unique_chars'], C['single'], C['pair']))
        print('[font] │ dump 口径 %d 个 = 上面 %d + ASCII %d + 未映射字节 %d'
              % (C['dump_total'], C['unique_chars'], C['ascii_rows'], C['icon_rows']))
        print('[font] │ 图集占用: 墨 %d / %d texel = %.2f%%; 对偶格占用 %d/%d = %.2f%%'
              % (A['ink_texels'], A['texels'], A['ink_ratio'],
                 P['used'], P['capacity'], A['pair_cell_ratio']))
        print('[font] └─ 以上数字全部按本盘 charset 现算 (不是写死的) ───────────────')
        if want_png:
            print('[font] 图集图 %d×%d (%d 倍, %s 口径%s) %.0f KB → %s'
                  % (atlas['w'] * scale, atlas['h'] * scale, scale, view,
                     '+格线' if (grid or labels) else '', os.path.getsize(png_p) / 1024, rel(png_p)))
            if sampled_info:
                print('[font] 紧凑图(只含引擎采样格) %d×%d → %s'
                      % (sampled_info['width'], sampled_info['height'], rel(sampled_p)))
            print('[font] 看图须知 → %s' % rel(readme_p))
        print('[font] 汇总 → %s (%.1fs)' % (rel(summ_p), time.time() - t0))
        print('[font] 自查: 引擎格位公式 %s (把刚写的 CSV 读回来, %d/%d 个 slot 逐个对 %s; '
              '不一致 %d 个; 对偶字有字形 %d/%d)'
              % ('OK ✓' if selfchk['ok'] else '**不一致** ✗',
                 selfchk['slots_compared'], selfchk['slots_capacity'], selfchk['checker'],
                 selfchk['mismatched'], n_pair_ok, capr['pair']['used']))
        print('[font] 图集容器: %s; %d 段%s'
              % (seg_diag['container'],
                 len(seg_diag.get('segments') or []),
                 '' if view == 'engine' else '  ⚠ 本次是 --flat-view 旧口径 (含包头/错位)'))
        # ── ★ round50: 字形几何体检 (结构性) ──
        if geom:
            GV = geom['verdict']
            print('[font] ┌─ 字形几何体检 (结构性判据: 墨在窗内 + 与 16px 模板逐像素比对) ──')
            print('[font] │ %s' % geom['one_line'])
            print('[font] │ ★ 截断(模板有墨的整行在盘上全空) = %d 个%s'
                  % (GV['truncated'], '' if not GV['truncated'] else '  ← 需要处理'))
            print('[font] │ 错误 %d / 警告 %d (报告 %s)'
                  % (GV['errors'], GV['warnings'], geom.get('report_md', '-')))
            print('[font] └──────────────────────────────────────────────────────────')
        for n in notes:
            print('[font][warn] %s' % n)
        # ★ 可复现性自检 (同一次运行里重算一遍 sha256, 只是确认写完没被改动)
        for k in ('atlas_png', 'atlas_sampled_png', 'atlas_readme', 'ft_csv', 'charset_csv',
                  'summary_json'):
            if k in files:
                assert sha256_file(os.path.join(REPO, files[k]['path'])) == files[k]['sha256'], k
    return summ


def main():
    ap = argparse.ArgumentParser(description='字库 dump (只读): 图集 PNG + FT 记录表 + 字符集清单 + 汇总')
    ap.add_argument('--iso', required=True, help='要 dump 的 ISO (只读)')
    ap.add_argument('--out', required=True, help='输出目录 (构筑时 = work/builds/<版本>/font)')
    ap.add_argument('--prefix', default=None,
                    help='产物文件名前缀 (默认 = ISO 文件名去掉 .iso)')
    ap.add_argument('--scale', type=int, default=2, help='PNG 放大倍数 (默认 2)')
    ap.add_argument('--no-png', action='store_true', help='不出 PNG (省几秒)')
    ap.add_argument('--iso-sha', default=None, help='已知的 ISO sha256 (省一次全盘哈希)')
    ap.add_argument('--grid', action='store_true',
                    help='主图叠加**引擎格的 16×16 网格线** (淡红) + FT 记录矩形 (淡蓝) + 已用格角标')
    ap.add_argument('--labels', action='store_true', help='--grid 之上再加 列号/行号 + 每个已用格的 slot 号')
    ap.add_argument('--only-sampled', action='store_true',
                    help='另出一张 <prefix>_font_atlas_sampled.png: 只拼**引擎会采样的格**'
                         '(62 列 × 用到的网格行 + 记录带), 彻底避开包头/边角/回绕副本')
    ap.add_argument('--flat-view', action='store_true',
                    help='★ 仅供对照: 用**旧口径**渲染图集 (整个容器当裸图 ⇒ 会把 48B 包头画成像素、'
                         '每段右移 6 格)。默认是引擎口径 (按 GIF 封包还原)')
    a = ap.parse_args()
    prefix = a.prefix or os.path.splitext(os.path.basename(a.iso))[0]
    summ = dump_font(a.iso, a.out, prefix, scale=max(1, a.scale),
                     want_png=not a.no_png, iso_sha=a.iso_sha,
                     view=('flat' if a.flat_view else 'engine'),
                     grid=a.grid, labels=a.labels, only_sampled=a.only_sampled)
    print('[font] 产物: %s' % ', '.join(sorted(summ['files'])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
