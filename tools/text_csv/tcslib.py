# -*- coding: utf-8 -*-
r"""tcslib.py — CSV 文本工具链公共库 (round29)

职责:
  · ISO / IMG 条目读取 (只读 mmap, 不重建 ISO)
  · LZO 子流解压 / 重压 (复用 tools/hanliu/tools 的 lzo1x)
  · 专有变长字符集的「引擎口径」解码 + 编码 (charset_compiled_zh16.json)
  · 两类容器解析:
      LANG   : MENU.IMG#25 == GR.IMG#902 语言表 (ngroups + {count}+{len}{data}{u16 attr})
      SFXML  : MENU.IMG#283 EN_SPECIAL_FEATURE.XML (<text>…</text> 正文)
  · RSTextComponent::DoWordWrap 折行模型 (口径见 docs/REPORT_wrap_and_title.md)
  · 换行约定: {br} <-> 单个换行符 ; {p} <-> 空行 (连续 2 个换行符) ;
    {WRAP} <-> **人工断点** (round36: 注入时写成 {br}; dump 绝不自动插)

本模块被 dump_text_csv.py / inject_text_csv.py 共用。
"""
import csv
import glob
import io
import json
import mmap
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))

from lz77_decode import lzo1x_decompress                       # noqa: E402
from lzo1x_c import compress as lzo_compress                   # noqa: E402

# ─────────────────────────────── 常量 ───────────────────────────────
SEC = 2048
TAB_OFF, TAB_STEP = 0x830, 48
MENU_LBA, GR_LBA = 776286, 19175
LANG_MENU_IDX, LANG_GR_IDX = 25, 902
XML_IDX = 283
_CHARSET_CANDIDATES = [
    os.path.join(REPO, 'tools', 'final_fix', 'assets', 'charset',
                 'charset_compiled_zh16.json'),
    os.path.join(REPO, 'tools', 'font_pipeline', 'data', 'charset_compiled_zh16.json'),
]
CHARSET = next((_c for _c in _CHARSET_CANDIDATES if os.path.isfile(_c)),
               _CHARSET_CANDIDATES[0])

# ★ round40 (GR_ZH93 方案 C): 四处 ELF gate `sltiu ...,0xAE` 已改成 `0xB1`
#   ⇒ 引擎的 DBCS lead 区间 = [0xA1, 0xB1)，即 0xA1..0xB0（新增 lead 0xAE/0xAF/0xB0 共 282 码位）。
#   0xB1 是上限：
#     · 0xB1/0xB5 = 引擎**真正认的**两个文本手柄图标码 (round42 定性, 见 icon_table.py);
#     · 0xE7/0xF1 = Latin-1 的 ç / ñ (round42 定性, round43 已**正式进字符集**) ——
#       它们过去被当图标写成 {{BTN:E0E7}}/{{BTN:E0F1}}, 那种写法现在仍是**历史别名**
#       (见 BTN_LATIN1_ALIAS), 但引擎画的从来都是字母。
#   这四个字节都必须留在 lead 之外。
#   证据: tools/iso_build/patch_zh93_planc.py + docs/REPORT_plan_c_zh93.md;
#   全 ELF `sltiu imm=0xAE` 扫描确认 lead 立即数只有这 4 处。
#   ★ 只有这两个常量随上界变; 其余口径 (atlas_cell_xy / _check_record / …) 未动。
#   ★★ round82「零缺字成品盘」: 上界 0xB1 → **0xB5**（ELF 4 处 `sltiu …,0xB1` 同步改成 0xB5,
#      见 work/tools/zx_patch_font.py）⇒ lead 区间 [0xA1, 0xB5), 对偶空间 20×94 = 1880。
#      连带结果（由本文件 selfcheck_charset 强制把关）: 0xB2/键、0xB3/练、0xB4/用 不再是单字节码,
#      已迁进对偶空间; 0xB1/△ 也改对偶（否则会被当成 lead 吞掉后一个字节）。
#      docs/REPORT_zero_missing_glyph_build2.md 有完整改动清单。
LEAD_LO, LEAD_HI = 0xA1, 0xBA          # 引擎 DBCS lead 区间 [0xA1, 0xBA) —— 2026-10-15 闸门 0xB5→0xBA
PAIR_LEAD_LO, PAIR_LEAD_HI = 0xA1, 0xBA  # 允许写出的 pair lead (引擎只认这段)
W_CJK, W_ASCII, W_SPACE, TRACK = 16, 8, 3, 1
FP = W_SPACE + TRACK                   # 4 = 每 token 与每个字面空格各收一次
TAG_RE = re.compile(r'\{(?:br|p)\}')
CJK_RE = re.compile(r'[\u4e00-\u9fff]')

# ═════════ 手柄按键图标占位符: 私有区字符 ↔ ASCII 标记 {{BTN:XXXX}} (round33) ═════════
#   语言表里有一类**字符表未映射的控制字节**。
#   ★ round42/43 订正: 现役盘里真正属于这一类的只有 **0xB1 / 0xB5** (引擎认的两个图标码);
#     当年一并写进标记的 0xE7 / 0xF1 其实是拉丁字母 ç / ñ, round43 已进字符集 ⇒
#     新 dump 直接输出字母, 老 CSV 的 `{{BTN:E0E7}}`/`{{BTN:E0F1}}` 作为**历史别名**继续接受
#     (见下面的 BTN_LATIN1_ALIAS)。
#   引擎直接拿 0xB1/0xB5 去画手柄按键图标, **不吃字库** (见 GlyphCache.check_text)。
#
#   round32 之前: dump 把它们回落成私有区字符 U+E0XX。问题是 **Excel 没有任何 PUA 字形**,
#   打开 CSV 只看到方框/空白 ⇒ 用户根本看不见、也没法安全编辑 (用户报障原文:
#   「excel 缺少字库 无法显示各个手柄按键占位符」)。
#
#   round33 起: CSV 里一律写成 **ASCII 可见标记 `{{BTN:XXXX}}`**:
#       U+E0B1  ↔  "{{BTN:E0B1}}"      (XXXX = 原码位的 4 位大写十六进制)
#   标记是纯 ASCII、无空格、无换行、双花括号成对 ⇒ 在 Excel 里复制/粘贴/查找都不会被打散,
#   也**绝不会**被引擎的 {br}/{p} 换行标记误认。
#
#   ★ 语义 (round42 已逆向出来, 见 icon_table.py): 0xB1 = △ 三角键, 0xB5 = ✕ 叉键;
#     引擎的文本图标码**只有这两个**。标记本身仍只写码位 (XXXX), 不写键名。
BTN_FMT = '{{BTN:%04X}}'                        # 码位(int) -> 标记 (dump 输出统一大写)
BTN_RE = re.compile(r'\{\{BTN:([0-9A-Fa-f]{4})\}\}', re.I)  # 合法标记 (大小写不敏感)
BTN_PREFIX_RE = re.compile(r'\{\{?\s*BTN\s*:', re.I)       # 「像标记的开头」—— 专供人话报错
BTN_LO, BTN_HI = 0xE080, 0xE0FF                 # 合法占位码位区间 = decode 唯一可能产出的区间
BTN_CHUNK = 28                                  # 报错时最多展示的原文片段长度

# ═════════ ★ round43: Latin-1 的 ç / ñ 正式进字符集 (0xE7 / 0xF1) ═════════
#   round42 定性 (双重证据): 0xE7 **不是**手柄图标, 是拉丁小写 ç; 0xF1 是 ñ。
#     · 出现处: 语言菜单 LANG:G059.I028 "Français" / LANG:G059.I031 "Español";
#     · FT 记录 idx=199 / idx=209 在图集上确有 ç / ñ 的字形 (实机画的就是这两个字母)。
#   round43 起: 这两个字节正式进 charset JSON 的 `codes` ⇒
#     · decode(0xE7) 直接产出 **'ç'** (不再回落成私有区 U+E0E7) ⇒ CSV 里看得见、可编辑;
#     · 工具链 (GlyphCache 字库预检 / dump_font 的 kind='latin1') 一律按**普通字母**处理;
#     · icon_table.is_icon(0xE7/0xF1) 恒为 **False** (它们从来就不是图标码)。
#
#   ★ 向后兼容 (硬要求, round33 的兼容线不能被本轮破坏):
#     用户表里既有的 `{{BTN:E0E7}}` / `{{BTN:E0F1}}` 标记**仍须被接受**, 且必须与
#     直接写 `ç` / `ñ` **注入出同一份盘** (两种写法都编码成同一个字节)。
#     实现三处:
#       ① btn_code_ok()           —— 这两个字节显式放行 (它们是"历史别名", 不是普通汉字);
#       ② normalize_latin1_alias() —— U+E0E7/U+E0F1 → ç/ñ, 供 encode_strict 做对称自检;
#       ③ encode() 的占位分支不变 —— U+E0E7 照旧写成 0xE7 (老 CSV 一个字都不用改)。
BTN_LATIN1_ALIAS = (0xE7, 0xF1)                 # 历史别名: 曾写成 {{BTN:…}} 的拉丁字母字节
LATIN1_ALIAS_CHARS = {0xE7: 'ç', 0xF1: 'ñ'}     # 字节 → 真正的字符 (单一事实来源)


def is_btn_mark(s):
    """s 是不是一个**完整合法**的按键标记 (如 '{{BTN:E0B1}}')? 大小写不敏感。"""
    return bool(BTN_RE.fullmatch(s))


def pua_to_marks(text):
    """私有区占位字符 U+E080..U+E0FF → ``{{BTN:E0XX}}`` (dump 出 CSV 时用)。

    ★ 只转 U+E080..U+E0FF —— 这正是 Charset.decode 唯一会产出的占位区间
      (低于 0x80 的字节走 ASCII, 已映射字节走 codes/pair_of)。
      U+E000..U+E07F 属于**不该出现**的越界回落, 故意不转: 由 dump 的
      「CSV 不许含 PUA」硬断言拦下, 而不是悄悄变成非法标记。
    """
    if not any(BTN_LO <= ord(c) <= BTN_HI for c in text):
        return text                                     # 快速路径: 99% 的条目走这里
    return ''.join(BTN_FMT % ord(c) if BTN_LO <= ord(c) <= BTN_HI else c for c in text)


def mark_positions(text):
    """给报告用: 返回文本里所有合法标记的 [(位置, 标记)]"""
    return [(m.start(), m.group(0)) for m in BTN_RE.finditer(text)]


# ═════════ ★ round42: 图标码**查询接口** (格式零变化, 只补"这个码是什么键") ═════════
#   背景 (逆向结论, 详见 tools/text_csv/icon_table.py 与 docs/REPORT_icon_codes.md):
#     · 引擎的**文本图标码只有 2 个**: 0xB1(△) 与 0xB5(✕)。
#       它们不是"某张表里的一项", 而是 DrawString v1 (0x219A70, 全 ELF 唯一带字符循环的
#       绘制入口) 里**写死的两个 if** ⇒ 码的个数上限就是 2, 不存在"没找到的更多图标码"。
#     · 0xE7/0xF1 **不是图标**, 是 Latin-1 的 ç / ñ (语言菜单里的 Français / Español)。
#     · 玩家在按钮提示栏看到的其它手柄图标 (△○✕□ / 左右键 …) 由 UI 的**快捷键**系统
#       (`kShortcutDefaultTC` @0x2BEFE0) 按**动作索引**绘制, 与文本字节无关。
#
#   ★ 这些函数**不改变**任何既有行为: `{{BTN:XXXX}}` 的格式、区间、编解码、
#     预检口径全部原样 (round33 的兼容性硬要求)。它们只回答"这个码是什么"。
#   ★ 实现放在独立模块 `icon_table.py` (不 import 本模块 ⇒ 无循环依赖),
#     这里做**惰性导入**包装, 这样单独 import tcslib 的老脚本一行都不用改。
_ICON_TABLE = None


def _icon_table():
    global _ICON_TABLE
    if _ICON_TABLE is None:
        import icon_table                                       # noqa: PLC0415
        _ICON_TABLE = icon_table
    return _ICON_TABLE


def icon_info(x):
    """``0xB1`` / ``U+E0B1`` / ``'{{BTN:E0B1}}'`` → 图标记录 dict; 不是图标码 → None。

    记录字段: ``byte / pua / key('triangle'|'cross') / name('△ 三角键') / uv / verified / note``
    """
    return _icon_table().icon_info(x)


def icon_key(x):
    """码 → 英文键名 (``'triangle'`` / ``'cross'``); 不是图标码 → None。"""
    return _icon_table().icon_key(x)


def icon_name(x):
    """码 → 人话键名 (``'△ 三角键'`` / ``'✕ 叉键'``); 不是图标码 → None。"""
    return _icon_table().icon_name(x)


def all_icons():
    """引擎认的**全部**文本图标码记录 (只有 2 个: 0xB1 / 0xB5)。"""
    return _icon_table().all_icons()


def engine_icon_bytes():
    """引擎认的文本图标码字节元组 = ``(0xB1, 0xB5)``。"""
    return _icon_table().engine_icon_bytes()


def candidate_icon_bytes(charset=None):
    """★ 修掉的"缺漏"口径: 枚举 ``0xB1..0xFF`` 里**没被字符集占用**的全部字节。

    旧口径 = 「文本里出现过未映射字节才算图标」⇒ 引擎认、但当前译文没用的码看不见。
    新口径 = **枚举字节空间** (不依赖任何文本)。
    ``charset`` 不传 ⇒ 只按区间返回 (不做字符集过滤)。
    """
    return _icon_table().candidate_bytes(charset)


def describe_icon_byte(b, charset=None):
    """给 dump/报告用的一行人话: 这个字节是图标 / 拉丁字母 / 汉字 / 空着。"""
    return _icon_table().describe(b, charset)


def icon_summary_lines(charset=None):
    """给 dump/报告用的多行人话结论 (dump_font 与本模块共用同一口径)。"""
    return _icon_table().summary_lines(charset)


# 资源定义
RES = {
    'LANG': dict(
        kind='lang',
        # 同一份表的两份拷贝 (历史轮次要求同步写)
        copies=[('MENU.IMG', MENU_LBA, LANG_MENU_IDX, 'EN_STRINGS.RES@MENU'),
                ('GR.IMG', GR_LBA, LANG_GR_IDX, 'EN_STRINGS.RES@GR')],
    ),
    'SFXML': dict(
        kind='sfxml',
        copies=[('MENU.IMG', MENU_LBA, XML_IDX, 'EN_SPECIAL_FEATURE.XML')],
    ),
}

# 折行档: 只有经过实机标定的档位才默认插入「软换行」
#   source=calibrated  → 有 EE RAM / 实绘逐行证据
#   source=measured    → 由本次 round29 简报屏 drawlog 反解
#   source=unknown     → 未标定, 默认不插软换行 (--wrapw 可强制)
WRAP_PROFILES = {
    'SFXML':     dict(wrap_w=270, source='calibrated',
                      evidence='docs/REPORT_wrap_and_title.md (EE RAM frame 11030: comp[0x40]=270)'),
    'LANG':      dict(wrap_w=0, source='unknown',
                      evidence='语言表被多种组件消费, 宽度各不同; 见 work/archive/cmp/r29_csv/wrap_fit.md'),
}
PROFILE_FILE = os.path.join(HERE, 'wrap_profiles.json')


def load_wrap_profiles():
    """外部可选覆盖: tools/text_csv/wrap_profiles.json"""
    p = dict((k, dict(v)) for k, v in WRAP_PROFILES.items())
    if os.path.isfile(PROFILE_FILE):
        try:
            ext = json.load(open(PROFILE_FILE, encoding='utf-8'))
            for k, v in ext.items():
                p.setdefault(k, {})
                p[k].update(v)
        except Exception as e:                                  # noqa: BLE001
            print('[warn] wrap_profiles.json 解析失败: %s' % e)
    return p


# ───────────────────────────── ISO / IMG ─────────────────────────────

class Iso:
    """只读 ISO (mmap)"""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.f = open(path, 'rb')
        self.size = os.path.getsize(path)
        self.mm = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ)

    def read(self, off, n):
        return bytes(self.mm[off:off + n])

    def img_name(self, lba, idx):
        base = lba * SEC
        noff = struct.unpack_from('<I', self.mm, base + 0x10)[0]
        nend = struct.unpack_from('<I', self.mm, base + 4)[0]
        names = [x.decode('latin-1') for x in
                 bytes(self.mm[base + noff:base + nend]).split(b'\x00') if x]
        return names[idx] if idx < len(names) else '?%d' % idx

    def img_entry(self, lba, idx):
        """返回 dict(base, stored, real, off, name, iso_off)"""
        base = lba * SEC
        r = struct.unpack_from('<12I', self.mm, base + TAB_OFF + TAB_STEP * idx)
        return dict(base=base, stored=r[6], real=r[7], off=r[8],
                    name=self.img_name(lba, idx), iso_off=base + r[8])

    def close(self):
        self.mm.close()
        self.f.close()


def sha256_file(path, buf=1 << 22):
    import hashlib
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# ───────────────────────────── LZO 子流 ─────────────────────────────

def lzo_subs(raw):
    """顺序解析 {u32 comp_len}{u32 real_len}{comp} 子流表, 直到解不出为止。
    返回 [(dec_bytes, comp_len, real_len, hdr_off)]"""
    subs, p = [], 0
    while p + 8 <= len(raw):
        L, S = struct.unpack_from('<II', raw, p)
        if L == 0 or p + 8 + L > len(raw):
            break
        try:
            dd, err, _ = lzo1x_decompress(raw[p + 8:p + 8 + L], out_size=S)
        except Exception:                                       # noqa: BLE001
            break
        if err is not None or len(dd) != S:
            break
        subs.append((bytes(dd), L, S, p))
        p += 8 + L
    return subs


def lzo_pack(chunks):
    """把若干解压块按同样顺序重压成帧字节"""
    out = bytearray()
    for c, S in chunks:
        cc = lzo_compress(c, level=7, use_m1=True, use_m4=True)
        back, err, _ = lzo1x_decompress(cc, out_size=S)
        assert err is None and back == c, '子流回环失败 (real=%d)' % S
        out += struct.pack('<II', len(cc), S) + cc
    return bytes(out)


# ───────────────────────────── 字符集 ─────────────────────────────

class Charset:
    """charset_compiled_zh16.json:
         codes   = {char: byte}        单字节码
         pair_of = {char: [b1, b2]}    双字节 pair
    """

    def __init__(self, path=CHARSET):
        c = json.load(open(path, encoding='utf-8'))
        self.enc_single = {ch: int(v) for ch, v in c['codes'].items()}       # char -> byte
        self.enc_pair = {ch: tuple(v) for ch, v in c['pair_of'].items()}     # char -> (b1,b2)
        self.codes = {v: ch for ch, v in self.enc_single.items()}            # byte -> char
        self.pair_of = {v: ch for ch, v in self.enc_pair.items()}            # (b1,b2) -> char

    # ---- 解码: 严格按引擎 (ELF 四处 sltiu lead,0xAE) ----
    #   未映射字节 (按键图标 0xB1~0xB5 等) 回落到私有区 U+E0xx, 保证 encode(decode(b)) == b
    PUA_BASE = 0xE000

    def decode(self, b):
        """返回 (text, byte_off_of_char[])

        ★ 这里**保持私有区写法** (U+E0XX), 不直接产出标记 —— 原因有二:
          ① 折行模型 strlen 按「一个占位 = 一个 16px 宽的字」算, 换成 12 字符的 ASCII
             标记会把宽度算成 100+px, 整份软换行全错位;
          ② 字节级忠实: decode/encode 是引擎口径的一对互逆函数, CSV 只是它的一个视图。
        会话层 (CSV) 的写法转换由 pua_to_marks / marks_to_pua 负责。
        """
        out, mp, i, n = [], [], 0, len(b)
        while i < n:
            v = b[i]
            if v < 0x80:
                out.append(chr(v)); mp.append(i); i += 1
            elif LEAD_LO <= v < LEAD_HI and i + 1 < n and (v, b[i + 1]) in self.pair_of:
                out.append(self.pair_of[(v, b[i + 1])]); mp.append(i); i += 2
            elif v in self.codes:
                out.append(self.codes[v]); mp.append(i); i += 1
            else:
                out.append(chr(self.PUA_BASE + v)); mp.append(i); i += 1
        return ''.join(out), mp

    @staticmethod
    def is_placeholder(s):
        """s 是「手柄按键图标占位符」吗? (round33: 新旧两种写法都认)

          · 单个私有区占位字符 ``U+E080..U+E0FF``  → True   (旧 CSV / 引擎字节的直接回落)
          · 完整标记字符串 ``{{BTN:XXXX}}``        → True   (新 CSV 写法, 大小写不敏感)

        ★ 区间从原来的 U+E000..U+E0FF 收紧成 U+E080..U+E0FF: decode 只可能产出 ≥U+E080,
          而 U+E000..U+E07F 会被 encode 写成 0x00..0x7F 裸控制字节、且再 decode 回来是
          ASCII 而非占位 ⇒ 本来就破坏了 encode/decode 的互逆性, 现在直接按「字符集里没有」拒绝。
        """
        if len(s) == 1:
            return BTN_LO <= ord(s) <= BTN_HI
        return is_btn_mark(s)

    # ---- 私有区占位 ↔ {{BTN:XXXX}} 标记 (round33) ----

    def btn_code_ok(self, code):
        """码位 code (int) 能不能当按键图标占位? 返回 None = 可以, 否则人话原因。"""
        if not (BTN_LO <= code <= BTN_HI):
            return ('码位 U+%04X 不在可用区间 U+%04X..U+%04X 内 (XXXX 是*原码位*, 不是字节值)'
                    % (code, BTN_LO, BTN_HI))
        b = code - self.PUA_BASE
        if b in BTN_LATIN1_ALIAS:
            # ★ round43 向后兼容: U+E0E7 / U+E0F1 是**历史别名** —— 当年把 ç / ñ 误当图标
            #   时写下的标记。它们现在在字符集里 (是拉丁字母), 但老 CSV **必须照旧能注入**,
            #   所以这里放行; 归一化成真字母由 normalize_latin1_alias() 负责。
            return None
        if b in self.codes:
            return ('码位 U+%04X 就是字节 0x%02X, 而它在本盘字符表里是正常汉字「%s」'
                    ' —— 不是按键图标占位' % (code, b, self.codes[b]))
        if LEAD_LO <= b < LEAD_HI:
            # ★ round40 (方案 C 上界同步): 0xA1..0xB0 现在是引擎的 DBCS lead 区间。
            #   把这些字节当图标写出去, 引擎会把它读成对偶首字节 (吞掉后一个字 + 画错字)。
            return ('码位 U+%04X 就是字节 0x%02X, 而 0x%02X..0x%02X 是引擎的对偶 lead 区间'
                    ' (lead≥0x%02X 才能当图标字节)' % (code, b, LEAD_LO, LEAD_HI - 1, LEAD_HI))
        return None

    def scan_marks(self, text):
        """扫描 ``{{BTN:XXXX}}`` 标记。返回 ``(替换成私有区后的文本, [问题...])``。

        问题项 = ``(位置, 原文片段, 人话原因)``。**不抛异常** —— 供「一次性列出全部
        问题」的预检用; 真正要写入时走 marks_to_pua (遇到第一个问题就抛)。

        认这些写法错误 (全部**拒绝**, 绝不静默当普通文本):
          · ``{{BTN:ZZZZ}}``      非十六进制
          · ``{{BTN:E0B1``        缺右边 ``}}``
          · ``{{BTN:E0B1}``       只写了一个右花括号
          · ``{BTN:E0B1}``        只写了一个左花括号
          · ``{{BTN:1234}}``      码位未知 (不在 U+E080..U+E0FF)
          · ``{{BTN:E0AF}}``      该码位落在引擎的对偶 lead 区间 0xA1..0xB0 (会吞掉后一个字)
          · 孤立的 ``}}``         标记前半截被删掉了
        """
        out, probs, i, n = [], [], 0, len(text)
        while i < n:
            ch = text[i]
            if ch == '{':
                m = BTN_RE.match(text, i)
                if m:
                    code = int(m.group(1), 16)
                    bad = self.btn_code_ok(code)
                    if bad:
                        probs.append((i, m.group(0), bad))
                    else:
                        out.append(chr(code))
                    i = m.end()
                    continue
                lm = BTN_PREFIX_RE.match(text, i)
                if lm or text.startswith('{{', i):
                    end = text.find('}}', i)
                    if 0 <= end - i <= BTN_CHUNK:
                        adv = end + 2
                        frag = text[i:adv]          # 正好是「像标记的那一段」, 不加噪
                    else:
                        adv = max(i + 1, lm.end() if lm else i + 2)
                        frag = text[i:i + BTN_CHUNK]
                    probs.append((i, frag, self._btn_syntax_reason(text, i)))
                    i = adv
                    continue
                out.append(ch); i += 1
                continue
            if ch == '}' and text.startswith('}}', i):
                probs.append((i, text[i:i + 6],
                              '这里是**孤立的 }}** —— 按键标记的前半截被删掉了'))
                i += 2
                continue
            out.append(ch); i += 1
        return ''.join(out), probs

    def marks_to_pua(self, text):
        """``{{BTN:XXXX}}`` → 私有区占位字符 U+E0XX (decode 的逆运算)。

        非法标记一律抛 ``BtnMarkError`` (含人话说明), **绝不静默当普通文本写进盘**
        —— 否则游戏里会真的显示出 "{{BTN:..." 这串 ASCII 字符。
        """
        if '{' not in text and '}' not in text:
            return text                                     # 快速路径
        out, probs = self.scan_marks(text)
        if probs:
            pos, frag, why = probs[0]
            raise BtnMarkError(
                '按键标记写法错误 @ 第 %d 个字符: %r\n'
                '  问题: %s\n'
                '  正确写法: {{BTN:XXXX}} —— 双花括号 + 大写 BTN + 冒号 + 4 位十六进制, '
                '例如 {{BTN:E0B1}}\n'
                '  最稳做法: **直接从 note 列复制**现成的标记, 不要手打。'
                % (pos + 1, frag, why))
        return out

    @staticmethod
    def _btn_syntax_reason(text, i):
        """给一个「像标记但写错了」的位置, 说人话指出错在哪。"""
        if not text.startswith('{{', i):
            return ('花括号只写了**一个** —— 按键标记两边都必须写**两个**花括号 '
                    '(是 {{ 和 }}, 不是单个 { })')
        tail = text[i:i + BTN_CHUNK]
        if '}}' not in tail:
            return '标记没写完 —— **缺少右边的两个花括号 }}**'
        if tail[2:3].isspace():
            return '{{ 后面必须**紧跟** BTN, 中间不能有空格'
        core = tail[2:]
        if core[:3].upper() != 'BTN':
            return ('{{ 后面必须是 BTN (三个字母) —— 你写的是 %r'
                    % core.split('}}')[0])
        rest = core[3:]
        if not rest.startswith(':'):
            return 'BTN 后面**漏了冒号 :** (正确写法是 BTN:XXXX)'
        body = rest[1:].split('}}')[0]
        if body != body.strip():
            return '花括号/冒号两边**不能有空格** (你写的是 %r)' % body
        return ('冒号后面必须是**4 位十六进制数字** 0-9 A-F '
                '(你写的是 %r, 共 %d 个字符; 常见错因: 少写/多写一位, 或用了非十六进制字母)'
                % (body, len(body)))

    def encode(self, text, bad='raise'):
        """按「按键标记 / 私有区占位 → 单字节码 → 双字节 pair」编码。

        入参的 ``{{BTN:XXXX}}`` 标记会先还原成私有区占位字符 (非法标记直接抛
        BtnMarkError); 也可以直接喂私有区字符 (老 CSV) —— 两条路等价。
        返回 (bytes, [(char_idx, nbytes, reason|None)])"""
        text = self.marks_to_pua(text)
        out = bytearray()
        issues = []
        for i, ch in enumerate(text):
            o = ord(ch)
            if o < 0x80:
                out.append(o); issues.append((i, 1, None))
            elif self.is_placeholder(ch):
                out.append(o - self.PUA_BASE); issues.append((i, 1, None))
            elif ch in self.enc_single:
                out.append(self.enc_single[ch]); issues.append((i, 1, None))
            elif ch in self.enc_pair:
                b1, b2 = self.enc_pair[ch]
                if not (PAIR_LEAD_LO <= b1 < PAIR_LEAD_HI):
                    # ★ 引擎 DBCS 判据 = sltiu lead,0xAE (ELF 四处实测) ⇒ lead>=0xAE
                    #   的 pair 会被引擎读成两个单字节 → 严禁写出 (字表里有 0xAE/0xAF/0xB0
                    #   开头的死 pair, 是表里的历史残留, 不能当编码用)
                    issues.append((i, 0, '字 %r 只有不可用双字节码 (lead=0x%02X, '
                                         '引擎只认 0xA1..0xAD)' % (ch, b1)))
                    continue
                out += bytes((b1, b2)); issues.append((i, 2, None))
            else:
                issues.append((i, 0, 'charset 无此字: %r(U+%04X)' % (ch, o)))
                if bad == 'raise':
                    continue                                   # 收集全部问题后统一报错
                out.append(0x20)
        return bytes(out), issues

    @staticmethod
    def normalize_latin1_alias(text):
        """★ round43: 把**历史别名占位** U+E0E7 / U+E0F1 归一化成真正的字母 ``ç`` / ``ñ``。

        为什么必须有这一步: 这两个码位现在在字符集里 (是**拉丁字母**, 不是图标) ⇒
        老 CSV 的 ``{{BTN:E0E7}}`` 与新的 ``ç`` **编码成同一个字节** (0xE7),
        因此它们也必须有同一个「解码回读」结果, 否则 encode_strict 的对称自检
        (decode(encode(t)) == t) 会把合法的老 CSV 判成死。

        ★ 只动这两个码位; 其余任何私有区占位一律原样 (它们是引擎直接画图标的控制字节)。
        """
        if '\ue0e7' in text or '\ue0f1' in text:
            for b, ch in LATIN1_ALIAS_CHARS.items():
                text = text.replace(chr(Charset.PUA_BASE + b), ch)
        return text

    def encode_strict(self, text):
        # ★ round36 不变式: 人工断点标记 {WRAP} **绝不允许**出现在要写盘的文本里
        #   (它是"这里要断行"的指令; 走 cell_to_bytes_text 时已展开成真换行)。
        #   万一哪条路径漏了, 这里直接拦下 —— 绝不把 "{WRAP" 这串 ASCII 写进游戏文本。
        if WRAP_RE.search(text):
            raise WrapMarkError(
                '要写入的文本里出现了人工断点标记 %s —— 这是工具链缺陷 (它不该走到编码器)。\n'
                '   正确路径: CSV 单元格 → tcslib.cell_to_bytes_text() (会把 %s 展开成真换行)。'
                % (WRAP_MARK, WRAP_MARK))
        # ★ 先统一成私有区写法: {{BTN:E0B1}} 与 U+E0B1 是同一件事的两种写法,
        #   老 CSV (私有区) 与新 CSV (标记) 都必须照旧能注入 (向后兼容硬要求)。
        #   ★ round43: 再把 ç/ñ 的历史别名 (U+E0E7/U+E0F1) 归一化成真字母 ——
        #   两种写法编码成的字节完全相同, 归一化只为让下面的对称自检成立。
        text = self.normalize_latin1_alias(self.marks_to_pua(text))
        b, issues = self.encode(text)
        errs = [x for x in issues if x[2]]
        if errs:
            raise CharsetError('; '.join('%s' % x[2] for x in errs[:6]) +
                               (' 等 %d 处' % len(errs) if len(errs) > 6 else ''))
        # ★ 编解码对称自检: 解回来的文本必须与输入完全相同, 否则一定会写出错字
        back, _ = self.decode(b)
        if back != text:
            k = next((i for i in range(min(len(back), len(text))) if back[i] != text[i]),
                     min(len(back), len(text)))
            raise CharsetError('编码/解码不对称 @%d: 输入 %r → 回读 %r (周围: %r / %r)'
                               % (k, text[max(0, k - 3):k + 3],
                                  back[max(0, k - 3):k + 3],
                                  text[max(0, k - 12):k + 12], back[max(0, k - 12):k + 12]))
        return b

    def text_safe(self, b):
        """decode 后再 encode, 逐字节回环? 返回 (text, ok)"""
        t, _ = self.decode(b)
        try:
            return t, self.encode_strict(t) == b
        except CharsetError:
            return t, False


class CharsetError(ValueError):
    pass


class BtnMarkError(CharsetError):
    """CSV 里的 ``{{BTN:XXXX}}`` 标记写错了 (语法错 / 码位非法)。

    ★ 继承 CharsetError ⇒ 任何「凡 CharsetError 就跳过」的上游逻辑都不会漏掉它;
      但 inject_text_csv.py 会**先**单独接住它, 给「哪个标记、怎么写才对」的人话报错,
      而不是笼统的「这个字字符表里没有」。
    ★ 它**不可被 --force 绕过**: 写错的标记没有任何字节序列能表示, 只能改 CSV。
    """
    pass


# ══════════════════ 字库覆盖预检 (round30, FontGuard) ══════════════════
#   注入前必须回答两个**互相独立**的问题:
#     ① 这个字**能编码**吗? —— 单字节码 / 可用对偶码 (charset JSON)
#     ② 盘上**真有字形**吗? —— FT 记录表 (MENU.IMG#4 FONT.RES) + 图集
#                                 (MENU.IMG#3 COMMON.PAK 的 new_font_revised)
#   只查 ① 会漏掉"JSON 有、盘上没字形"; 只查 ② 会漏掉"图集有墨但不是这个字"。
#
#   ★ 盘上实测口径 (GR_ZH93, 见 docs/REPORT_charset_guard.md + REPORT_dump_font_capacity.md):
#     · 单字节码 0xAF..0xFE 走 **FT 记录表**: idx = code - 0x20 (< nrec=224),
#       字形就在记录矩形 (u0,v0)-(u1,v1) 附近 —— 实测 +4/+2 偏置, 故取 ±4/±2 邻域;
#       `0xB7` 是单字节「小」的**合法码位**, 绝不是对偶 lead (历史事故: 曾毁 382 个「小」)。
#     · 对偶 pair 走 **引擎格位公式** (round41 修正, 见 atlas_cell_xy_engine_view):
#       slot = (b1-0xA1)*94 + (b2-0xA1); row = slot/NCOL, col = slot%NCOL;
#       ★ K2 (现役): NCOL=64 ⇒ x = 16*col, y = yrow(row), **无相位/无回绕**;
#       (62 列旧盘才需要 x = 16*((col + PHI[row]) % 64), 那套已随 FA2400 废弃)。
#       ⚠ 历史写法 x = 4+16*col **不是引擎格** (与真格 1504/1504 个 slot 都不同) ——
#       旧版预检之所以没误报, 是因为历史补丁在图集里为 legacy 位置**额外留了副本**。
#       索引恒 ≥0xE0 ≥ nrec ⇒ 永远不走记录表, 所以**不能**用记录表判断 pair 的字形。
#     · ASCII (<0x80) 也走记录表 (idx = code-0x20 < 224), 记录在 EN 带 (y=395/420/452/482),
#       不在 CJK 网格行上 ⇒ 不做相位校正。
#     · 引擎对**单字节码**的宽度查表 (0x416F40 cave) 与 UV (0x21ADE0) 同用记录表 ⇒
#       记录矩形有没有墨, 直接决定这个字画不画得出来。
FONT_FACE_DEFAULT = 1                   # face 顺序 = ['large','default','huge']; 引擎用 default
FT_NREC_FIELD = 4 * 5                   # fld[4]×fld[5] = 32×7 = 224
ATLAS_X0, ATLAS_Y0 = 4, 2               # ★ **legacy 口径** 的绘制原点 (x=4+16*col), 与引擎格无关
                                        #   (PROGRESS §10: 16px/PSMT4 采样 = rec.u+4); 新代码不要用。
                                        #   K2 的引擎格 x 恒为 16*col (无 +4 偏置), 见 atlas_cell_xy_engine_view。
GLYPH_DU, GLYPH_DV = 4, 2               # 记录矩形 → 图集采样窗 的实测偏置
GLYPH_TOL_X, GLYPH_TOL_Y = 4, 2         # 邻域容差 (实测单字节码最大偏置)
EN_BAND = (448, 480)                    # ASCII/符号带 y 区间 (现役盘实测)
# CJK 网格 —— ★ **以盘上 ELF 立即数为准** (2026-10-20 fix/font 订正; 见 docs/FONT_CURRENT_STATE.md)
#   现役 K2 几何 = 64 列 / Y0=3 / SKIP_ROWS=2 / SKIP_ROW=12 / CW=CH=16, 4bpp 1024×644。
#   三个立即数 (只读, 可用 verify_font_state.py 复核):
#     · NCOL      VA 0x4170AC  imm = 0x40 (64)      ISO 偏移 0x3AA92C
#     · SKIP_ROWS VA 0x4170E8  imm = 2               ISO 偏移 0x3AA968
#     · Y0        VA 0x4170F8  imm = 3               ISO 偏移 0x3AA978
#   ⚠ 旧值 62 / Y0=2 / SKIP_ROWS=3 是 FA2400 之前的配方 (那一版图集是 1024×512)。
#     在现役盘上用旧值跑任何审计都会**整体错行** (实测: 同一张盘 K2 口径 xor==0 命中
#     1,874/1,937、旧口径 0/1,937、平均 xor 92.55) ⇒ 旧值已彻底废弃。
NCOL, CW, CH = 64, 16, 16
GRID_Y0, GRID_SKIP_ROW, GRID_SKIP_ROWS = 3, 12, 2

# ═════════ 引擎格位公式 (round41 起; round45 订正行 19..24; ★ 2026-10-20 K2 收口) ═════════
#   引擎 (ELF cctc cave 0x417050 反汇编) 算的是 U0 = 16*col、V0 = yrow(row) —— **无相位**。
#   ⚠ **62 列时代的历史说明 (下面是给旧盘看的, K2 已不适用)**: 图集数据曾被各轮"行移位/重铺"过
#   ⇒ 图集(flat)里字形实际所在列 = (col + PHI[row]) mod 64 (图集一行 64 格, 旧引擎一行 62 格 ⇒ 回绕)。
#
#   ★★ **K2 几何 (现役, NCOL=64) 起 PHI 恒为空表**: 引擎一行 64 格 == 图集一行 64 格 ⇒
#      **没有回绕、没有行相位**; 写入侧一律走 `Atlas.write_pixels()` (按 GIF 封包定位),
#      不再存在"flat 容器坐标"这回事。`atlas_cell_xy_engine()` 与
#      `atlas_cell_xy_engine_view()` 在 K2 上**逐 slot 完全相同** (见 verify_font_state.py)。
#      ⇒ 旧的 62 列相位表 (6/12/18/24/30/36/42) 若保留，会让 dump 的 `cell_flat_*` 列
#        指到**别的格**, 并在图集 README 里假报"这些行的字形不在引擎采样格上"。
#
#   ---- 以下为 62 列时代的取证记录 (留档, 不删) ----
#
#   ★ round45 订正 (实机 A/B 闭环 + TTF 逐格辨认 + 记录码交叉验证, 见 docs/REPORT_glyph_align.md):
#     容器是 **GIF 封包流**: 每段 48B 包头 ⇒ flat 列 = 引擎列 + 6×(段号+1) ⇒
#       **PHI[row] 的真值 = 6×(段号+1) mod 64** (与"行相位"无关)。
#     行 0..18 恰好一直等于这个值 (所以历史实证全对得上); 行 19..24 原来是 2/2/2/2/2/0,
#     **是错的** ⇒ 那些字形落在同排别的列 ⇒ 游戏里显示成别的字。round45 已把盘上字形搬到
#     正确格, 并把本表订正为真值 (36/36/42×4)。搬运后 flat 格 == 引擎采样格, 两者重合。
#
#   证据:
#     · 实机 A/B (探针盘, temp/r45): 在引擎格 (16*col, yrow) 涂实心块 ⇒ 该字真的变成方块
#       (药 = 对偶码, 位 row11col26; 有/更 = 单字节记录码) ⇒ 引擎采样格就是 (16*col, yrow);
#     · 方正像素16 TTF 模板逐格辨认: 行 19 col 0..33 = 单字节码 0xDB..0xFE 的字形 (err=0),
#       行 19..23 的对偶字形则**偏 (col−6×(段号+1)) mod 64 格**;
#     · 1297 字抽样在行 0..18 上 785 个 0 误差 (PHI = 段错位);
#     · 回绕列的字形在图集里低 1 行 (实测 8/8), 故 y 要 +1。
# ★★ K2 (64 列) 的相位表 = **纯容器几何** (与"行移位/重铺"无关):
#   容器仍是 GIF 封包流, 每段前面有 48B 包头 ⇒ 段内数据在**裸容器**里相对引擎图整体右移
#   96 texel = **6 格** / 段。所以 PHI[r] = 6 × (段号+1) mod 64, 段号 = yrow(r) // 64。
#   本表由 `_k2_phi_table()` **按公式生成**(不写死), 随几何常量自动跟着变。
#   ⇒ `atlas_cell_xy_engine(slot)` = 该字在**裸容器**里的列 (flat 口径),
#      `atlas_cell_xy_engine_view(slot)` = 引擎采样格; 两者的差恒等于 `atlas_flat_x_shift()`。
#   ⇒ `dump_font.grid_row_alignment()` (= PHI − flat_shift/16) 对 K2 **恒为 0**
#      (= "写入侧 flat 格与引擎采样格是同一个物理字形"), 不会再假报"字形不在采样格上"。
#   ⚠ 62 列时代那张**拟合**表 {行0..3:6, 4..7:12, 8..11:18, 12:24, 13..16:30, 17..18:36,
#     19..20:36, 21..24:42} 已废弃 (它对 K2 的行 14 起就对不上了); 留档见上面的 round45 记录。
ATLAS_SEG_ROWS_FOR_PHI = 64          # == 下面 ATLAS_SEG_ROWS (每段 64 行); 这里先给个本地别名


def _k2_phi_table():
    """K2 的 flat/引擎列相位表: PHI[r] = 6 × (yrow(r)//64 + 1) mod NCOL。"""
    out = {}
    # 槽位数 = (lead 上界−下界) × 94 (trail 区间 0xA1..0xFE); 2,350 个槽 ⇒ 最后一行 = 36。
    # (PAIR_STRIDE / pair_capacity() 定义在本文件后面, 这里用等价算式, 避免前向引用。)
    last_row = ((LEAD_HI - LEAD_LO) * 94 - 1) // NCOL
    for r in range(last_row + 1):
        y = GRID_Y0 + CH * (r + (GRID_SKIP_ROWS if r >= GRID_SKIP_ROW else 0))
        out[r] = (6 * (y // ATLAS_SEG_ROWS_FOR_PHI + 1)) % NCOL
    return out


ATLAS_PHI = _k2_phi_table()
#   ★ 与**记录码采样窗**冲突的引擎格 (对偶码不可占用):
#     round45 实测 (见 docs/REPORT_glyph_align.md) 曾列出 51 格: 行 19 col 0..33 / 行 24
#     col 0..5,12 「整格被单字节记录码占用」, 行 21/22 col 5..8 与行 23 col 8/9
#     「一角被手柄图标码的记录矩形压着」; round45 把 38 个冲突的对偶字改派到干净槽。
#     ★ **round67 订正: 这 51 条标注现已在现役盘上**全部过期**。** 起因是 round55 把那批
#     单字节记录搬到了 y=195/211 带 ⇒ 记录矩形早已不在这些格上。逐格实测 (GR_ZH111,
#     `work/builds/GR_ZH98/temp/r67/r1_verify.py`, 本表 51 格全查):
#       · 51/51 格 **零墨** (格内 texel==0 的个数 = 0);
#       · 51/51 格 **不被任何 FT 记录矩形覆盖** (3 个 face × 544 条非空记录全画一遍求交 = 0 px);
#       · ⇒ 「仍成立」0 条, 「过期」51 条。
#     ⇒ 本表**清空**。判"某格能不能给对偶码用"一律**按实际像素/记录矩形现算**
#       (`font_cell_map.py` 的「空白但被记录压」统计、`dump_font.py` 的 `_live_rects`、
#        `patch_zh113_expand_font.py` 的硬断言① 都是这么做的) —— 静态标注表会随盘漂移,
#        这正是它过期 3 轮才被发现的原因。
#     (清空的直接收益: 容量口径从"按过期标注 278 格"回到真值 329 格; 见
#      docs/REPORT_probe_lead_limit.md §5.3 与 docs/REPORT_expand_font_329.md)
ATLAS_ENGINE_SINGLE_CELLS = {}
# 图集一行多少格。★ 旧注释写死 "64, 引擎一行 62 ⇒ 回绕"; K2 起 **NCOL == GRID_MOD == 64**
# ⇒ 不改写成派生量就会在 NCOL 再变时静默错位, 故这里直接派生 (不再写死 64)。
GRID_MOD = NCOL
#   62 列时代: 回绕列的字形低 1 行 ⇒ 它最后一行落进**下一行 cell 的第 0 行** (1 行渗漏)。
#   判"这个格子有没有字形"时必须把这 1 行剔掉, 否则渗漏会被误当成字形 (见 _check_grid)。
#   K2 (64 列) 无回绕 ⇒ 本值只在 62 列老盘上有意义; 现役盘恒为 0 行渗漏。
GRID_BLEED_ROWS = 1
PAIR_TRAIL_LO, PAIR_TRAIL_HI = 0xA1, 0xFE   # trail 区间 (94 个)
PAIR_STRIDE = PAIR_TRAIL_HI - PAIR_TRAIL_LO + 1              # 94


def pair_slot(b1, b2):
    """对偶码 (lead, trail) → 槽位号 slot。"""
    return (b1 - LEAD_LO) * PAIR_STRIDE + (b2 - PAIR_TRAIL_LO)


def pair_from_slot(slot):
    """槽位号 slot → 对偶码 (lead, trail)。"""
    return LEAD_LO + slot // PAIR_STRIDE, PAIR_TRAIL_LO + slot % PAIR_STRIDE


def pair_capacity():
    """合法对偶空间 = (lead 上界 - lead 下界) × 94。★ 不写死数字: 随 LEAD_HI 变。"""
    return (LEAD_HI - LEAD_LO) * PAIR_STRIDE


def atlas_row_phase(row):
    """行相位 PHI: 图集里该行字形相对 16*col 的列偏移 (拟合表; 表外行按 0 = 反汇编原值)。"""
    return ATLAS_PHI.get(row, 0)


def parse_ft_faces(ft, body_off=28):
    """解析展开态 FONT.RES。返回 (head_end, [(name, fld14, [rec6])]).

    布局: {u32 20}{20B}{u32 nfaces} 其后每面 {u32 nameLen}{name}{14×u32}{nrec×10B}
    rec6 = (b0, b1, u0, v0, u1, v1); nrec = fld[4]*fld[5]
    """
    p = body_off
    n = struct.unpack_from('<I', ft, 24)[0]
    faces = []
    for _f in range(n):
        l = struct.unpack_from('<I', ft, p)[0]
        p += 4
        nm = ft[p:p + l].decode('latin-1')
        p += l
        fld = list(struct.unpack_from('<14I', ft, p))
        p += 56
        nrec = fld[4] * fld[5]
        recs = [struct.unpack_from('<BB4H', ft, p + 10 * r) for r in range(nrec)]
        p += nrec * 10
        faces.append((nm, fld, recs))
    return p, faces


def parse_pak_records(pak):
    """解析 COMMON.PAK 记录链。返回 [(name, psm, w, h, clut_size, px_size, px_off)].

    格式: {u32 type}{u32 nameLen}{name}{u32 psm}{u32 w}{u32 h}{u32 clut}{clut}{u32 px}{px}
    结束哨兵 type=0x63。★ 只有 4 个 u32 参数 (历史文档记的 "8×u32 hdr" 是误读)。
    """
    out, p = [], 0
    while p + 8 <= len(pak):
        ty, nl = struct.unpack_from('<II', pak, p)
        if ty == 0x63 or nl > 64:
            break
        nm = pak[p + 8:p + 8 + nl].decode('latin-1')
        q = p + 8 + nl
        psm, w, h, clut = struct.unpack_from('<4I', pak, q)
        px = struct.unpack_from('<I', pak, q + 16 + clut)[0]
        out.append((nm, psm, w, h, clut, px, q + 20 + clut))
        p = q + 20 + clut + px
    return out


def atlas_cell_xy_engine(slot):
    """★ 引擎真实格位 (round45 起为唯一权威口径): slot → (x, y) 图集格左上角。

        row, col = slot // NCOL, slot % NCOL          # K2: NCOL=64
        p        = col + PHI[row]                     # K2: PHI 为空 ⇒ p == col
        x        = 16 * (p % GRID_MOD)                # 62 列旧盘: 图集一行 64 格 ⇒ 回绕
        y        = yrow(row) + (1 if p >= GRID_MOD else 0)   # 回绕列低 1 行 (仅 62 列旧盘)

    ★ **K2 起本函数 = 同一字形在"裸容器"里的坐标**: PHI 由 `_k2_phi_table()` 按容器几何生成
      (`6×(段号+1) mod 64`)，所以 `atlas_cell_xy_engine(slot) == atlas_flat_pos(*engine_view(slot))`
      对**全部 2,350 个 slot** 成立；`grid_row_alignment()` 恒为 0（不再假报"字形不在采样格上"）。
      **引擎真正采样**的位置请用 `atlas_cell_xy_engine_view()`。60 余字的历史取证见上面的注释块。

    ★ **round45 订正(62 列旧盘)**: PHI[row] 的真值 = ``6×(段号+1) mod 64`` (= 每段 48B 包头造成的
      flat/引擎错位)。行 0..18 一直等于它 ⇒ 历史实证全对得上; 行 19..24 原来是错的
      (2/2/2/2/2/0) ⇒ 那些字形落在**同排别的列**。GR_ZH94 起盘上字形已按真值重排。

    ⚠ 例外 (曾经与单字节记录码共用的格, 见 ``ATLAS_ENGINE_SINGLE_CELLS``): round45 曾标注
      行 19 col 0..33、行 24 col 0..5/12 归 FT 记录表 (单字节码 0xDB..0xFE 等) 所有; 但那批
      记录 round55 已搬走, **round67 逐格实测 51 条标注全部过期** ⇒ 该表已清空, 现在一律按
      实际像素 + 记录矩形现算 (见本文件 ``ATLAS_ENGINE_SINGLE_CELLS`` 处的说明)。
    """
    row, col = slot // NCOL, slot % NCOL
    p = col + atlas_row_phase(row)
    y = GRID_Y0 + CH * (row + (GRID_SKIP_ROWS if row >= GRID_SKIP_ROW else 0))
    return CW * (p % GRID_MOD), y + (1 if p >= GRID_MOD else 0)


def atlas_cell_xy(slot):
    """⚠ **legacy 口径, 不是引擎格** —— 保留原名只为兼容历史的写盘/自检脚本。

        x = 4 + 16*col,  y = y0 + 16*(row + 3*[row>=12])

    (= ``tools/font_pipeline/font_usage.py::slot_cell`` 那张配方单, 它自带逐位一致性自检;
    也 = 历史补丁往图集里写"预检副本"的位置。) 新代码请一律用 ``atlas_cell_xy_engine()``。
    """
    r, c = slot // NCOL, slot % NCOL
    y = GRID_Y0 + CH * (r + (GRID_SKIP_ROWS if r >= GRID_SKIP_ROW else 0))
    return ATLAS_X0 + CW * c, y


atlas_cell_xy_legacy = atlas_cell_xy       # 显式别名: 让人一眼看出这是历史口径


# ═════════ ★ round44 查实: 像素容器 = **GIF 封包流**, 不是裸图 ═════════
#   证据 (全部可复现, 见 docs/REPORT_atlas_artifact.md):
#     · 现役盘 COMMON.PAK `new_font_revised` 的像素容器开头 48B = 一个合法的 GIF 包头:
#         [PT NLOOP=1 EOP=0 PACKED NREG=1 REGS={0xE}][A+D qword = TRXPOS (SSAY=0)][IMAGE NLOOP=2048 EOP=1]
#       之后每 0x8000 字节再来一组, 共 8 段 —— 与 tools/font_pipeline/make_pak.py 生成的字节**逐字节相同**;
#       原版 EN 盘则是 [1 个 GIFTAG NLOOP=0x4000 EOP=1 FLG=2][0x40000 像素] 单包。
#     · 硬件把这些包头当 **DMA 命令**吃掉 ⇒ 它们**永远不是像素**。
#     · 写入侧 (patch_zh64/65/68/93 …) 一律按 `segs[k] + (ay - SEG_Y[k]) * 512` 定位,
#       即 **引擎看到的行 = 段内行** (payload); 「整个容器当 1024x512 裸图逐行读」是**旧 dump 的错口径**
#       (它把包头画成像素, 并把每段内容右移 96*(段号+1) texel = 6 格/段)。
#     · 判据 (不需要 TTF): 盘上自己的 ASCII FT 记录矩形 (u0,v0,u1,v1) 在两种读法里数墨 ——
#       引擎口径 94/94 有墨 / 裸图口径 61/94, 且 33 条**只有引擎口径有墨**、反向 0 条。
#   ⇒ 引擎真正看到的图集 = 按封包把每段数据放到 TRXPOS 指定的行。
ATLAS_SEG_ROWS = 64              # 现役容器: 每段 64 行 (末段 63 行 + 半行)
ATLAS_PREFIX_BYTES = 48          # 每段前缀 = [PT 16B][A+D TRXPOS 16B][IMAGE tag 16B]
ATLAS_ORIG_TAG_BYTES = 16        # 原版容器 = [1 个 GIFTAG 16B] 之后就是像素


def atlas_container_segments(blob, stride):
    """把像素容器按 GIF 封包语法切开 (只读, 不猜)。返回 ``[(首行号, 数据偏移, 字节数)]``。

    · 原版单包: 第 1 个包就是 IMAGE (FLG=2) ⇒ 首行 = 0;
    · 现役 8 段: 每段前面有 ``PT(NREG=1)`` + ``A+D`` (TRXPOS, 低 u32=SSAX 高 u32=SSAY) ⇒ 首行 = SSAY。
    解析不出已知形态 ⇒ 返回 ``None`` (调用方退回"整块当裸图", 那是**旧口径**, 会把包头画成像素)。
    """
    segs, o, trx = [], 0, None
    while o + 16 <= len(blob):
        w0, w1 = struct.unpack_from('<II', blob, o)
        nloop, eop, flg = w0 & 0x7FFF, (w0 >> 15) & 1, (w1 >> 26) & 3
        nreg = (((w1 >> 28) - 1) & 0xF) + 1
        if flg in (0, 1):                                  # PACKED: PT (A+D)
            if nloop == 0:
                break                                      # 尾部 no-op tag
            if nloop == 1 and nreg == 1:
                trx = struct.unpack_from('<I', blob, o + 20)[0]
                o += 16 + nloop * 16 * nreg
                continue
            return None
        ln = nloop * 16                                    # FLG=2: IMAGE
        segs.append((0 if trx is None else trx, o + 16, ln))
        o += 16 + ln
        if eop and nloop == 0:
            break
    return segs or None


def atlas_flat_x_shift(y):
    """「整块当裸图」视图相对引擎视图的水平错位 (texel): 每过一段 (64 行) 多错 96 (=6 格)。

    实测 (work/builds/GR_ZH93/temp/r44/s4_copies.py §A): 段内恒定, 逐行差异 0。
    **内容映射** (引擎口径像素 → flat 容器里的位置, 带行进位):
        ``x2 = x + atlas_flat_x_shift(y)``; ``x2 >= 宽`` 时 ``x2 -= 宽``, ``y += 1``。
    实现见 ``atlas_flat_pos()``。这是**容器几何**关系 (只与"每段 48B 包头"有关)。

    ⚠ **K2 起已去掉"最多 8 段"的截断**: 现役容器是 **11 段** (10×64 行 + 末段 2 行 + 半行),
      旧式 `min(y//64, 7)` 是 1024×512 / 8 段时代的产物, 会让 y ≥ 512 的错位算少。
      去掉之后, 本函数与 `ATLAS_PHI` (= 6×(段号+1) mod 64) 在**全部 2,350 个槽**上一致:
      `atlas_cell_xy_engine(slot) == atlas_flat_pos(*atlas_cell_xy_engine_view(slot))`。
      仍然只服务"裸容器对照"这一类度量: **读写盘一律走 `Atlas.write_pixels()`** (按封包定位)。
    """
    return 96 * (y // ATLAS_SEG_ROWS + 1)


def atlas_flat_pos(x, y, w=1024):
    """引擎口径像素 (x, y) → 「整块当裸图」视图里的位置 (x2, y2)。带行进位, 见上一条。"""
    x2 = x + atlas_flat_x_shift(y)
    if x2 >= w:
        x2 -= w
        y += 1
    return x2, y


def atlas_cell_xy_engine_view(slot):
    """★ **引擎采样坐标** (图集 = 引擎真正看到的像素): ``x = 16*col``, ``y = yrow(row)``, **无相位**。

    round45 起它与 ``atlas_cell_xy_engine()`` **指向同一格** (后者是同一个物理位置在 flat 口径里的
    坐标, PHI 已订正为真值), 换算关系:
      ``flat_x = (本函数 x + atlas_flat_x_shift(y)) % 图集宽`` (带行进位)。

    证据:
      · ELF cctc cave (hook 0x21ADE0 → 0x417050) 汇编: ``t4=slot; row=t4/62; col=t4%62;
        U0 = 16*col; if row>=12: row+=3; V0 = 2+16*row`` —— **没有任何行相位表**;
      · **实机 A/B 探针 (round45)**: 按本函数算出的引擎格涂实心块 ⇒ 该字真的变方块
        (对偶字 药 = row11col26; 单字节记录码 有/更) ⇒ 采样格就是 (16*col, yrow);
      · 盘上自己的 ASCII FT 记录矩形在"引擎口径"里 94/94 有墨 (裸图口径只 61/94);
      · TTF(方正像素16) 模板在引擎口径图集上对 grid 行 0..18 逐像素 0 误差命中 x = 16*col。
    """
    row, col = slot // NCOL, slot % NCOL
    return CW * col, GRID_Y0 + CH * (row + (GRID_SKIP_ROWS if row >= GRID_SKIP_ROW else 0))


class GlyphCache:
    """字库覆盖检查器 (只读)。

    用法::
        g = GlyphCache(charset, iso)     # iso=None ⇒ 只查字符集映射, 跳过字形检查
        g.encodable(ch)      -> bool     # 单字节码或可用对偶码
        g.has_glyph(ch)      -> bool     # 盘上确有字形 (FT 记录 / 图集格)
        g.glyph_reason(ch)   -> str|None # None=有字形; 否则是**人话**原因
        g.check_text(text)   -> [问题 dict]

    性能: 图集行 nibble 缓存 (bytes.translate) + 每字结果缓存 ⇒ 全量 2261 条 ~1 s。
    """

    def __init__(self, charset, iso=None, verbose=False):
        self.cs = charset
        self.iso = iso
        self.verbose = verbose
        self.recs = None
        self.rec_nrec = 0
        self.atlas = None               # (pak, px_off, w, h)
        self.segs = None                # ★ round45: 像素容器的 GIF 封包分段表 (引擎图口径)
        self._nib = {}                  # y -> nibble 表 (byte -> 该行 2 texel)
        self._cell_ink = {}             # (x, y) -> 该 16x16 格墨量 (None=越界)
        self._gc = {}                   # char -> (ok, reason)
        self._note = []
        if iso is not None:
            self._load_font()

    # ---------- 装载 ----------
    def _load_font(self):
        try:
            ft_e = None
            pak_e = None
            for i in range(24):
                e = self.iso.img_entry(MENU_LBA, i)
                if e['name'] == 'FONT.RES':
                    ft_e = e
                elif e['name'] == 'COMMON.PAK':
                    pak_e = e
                if ft_e and pak_e:
                    break
            if ft_e is None or pak_e is None:
                self._note.append('MENU.IMG 里找不到 FONT.RES / COMMON.PAK ⇒ 跳过字形检查')
                return
            blob = b''.join(s[0] for s in
                            lzo_subs(self.iso.read(ft_e['iso_off'], ft_e['stored'])))
            _he, faces = parse_ft_faces(blob)
            if len(faces) <= FONT_FACE_DEFAULT:
                self._note.append('FONT.RES 只有 %d 个 face ⇒ 跳过字形检查' % len(faces))
                return
            self.recs = faces[FONT_FACE_DEFAULT][2]
            self.rec_nrec = len(self.recs)
            self.face_name = faces[FONT_FACE_DEFAULT][0]
            pak = self.iso.read(pak_e['iso_off'], pak_e['stored'])
            for (nm, psm, w, h, clut, px, off) in parse_pak_records(pak):
                if nm == 'new_font_revised':
                    self.atlas = (pak, off, w, h)
                    # ★ round45: 容器 = GIF 封包流 ⇒ 记下分段表, 之后按**引擎图**取行
                    try:
                        self.segs = atlas_container_segments(pak[off:off + px], w // 2)
                    except Exception:                               # noqa: BLE001
                        self.segs = None
                    break
            if self.atlas is None:
                self._note.append('COMMON.PAK 里找不到 new_font_revised ⇒ 跳过字形检查')
        except Exception as ex:                                     # noqa: BLE001
            self._note.append('字库装载失败 (%s) ⇒ 跳过字形检查' % ex)
            self.recs = None
            self.atlas = None

    @property
    def font_ok(self):
        return bool(self.recs) and self.atlas is not None

    def notes(self):
        return list(self._note)

    # ---------- 图集采样 ----------
    #   性能关键: 每行只做一次 bytes.translate (C 速度), 之后逐 texel 只查表。
    #   PSMT4 每字节 2 texel: 偶数 x = 低 nibble, 奇数 x = 高 nibble。
    _LONIB = bytes(i & 0xF for i in range(256))
    _HINIB = bytes((i >> 4) & 0xF for i in range(256))

    def _nibbles(self, y):
        """返回该行「低 nibble 表」与「高 nibble 表」; 越界返回 (None, None)。

        ★ round45 起按**引擎图**取行 —— 容器是 GIF 封包流 (每段 48B 包头 + 64 行数据),
          引擎看到的是"每段放回 TRXPOS 指定的行"的图; 旧版按「整块当裸图」取行,
          对单字节/ASCII 的 FT 记录矩形 (u0,v0) 会读到**别的像素**(错位 6 格/段),
          于是把 脆/膛/若/著 这类本该有字形的字误报成缺字 (round45 实测)。
        认不出封包分段时退回旧的"裸图行"读法 (行为与旧版一致)。
        """
        t = self._nib.get(y)
        if t is None:
            pak, off, w, h = self.atlas
            row = None
            if 0 <= y < h:
                if self.segs:
                    k = y // ATLAS_SEG_ROWS
                    if k < len(self.segs):
                        first_row, doff, nbytes = self.segs[k]
                        rel = (y - first_row) * (w // 2)
                        if 0 <= rel and rel + w // 2 <= nbytes:
                            row = pak[off + doff + rel:off + doff + rel + w // 2]
                else:
                    row = pak[off + y * (w // 2):off + y * (w // 2) + (w // 2)]
            if row is not None and len(row) == w // 2:
                t = (row.translate(self._LONIB), row.translate(self._HINIB))
            if t is None:
                t = (None, None)
            self._nib[y] = t
        return t

    def _tex(self, x, y):
        lo, hi = self._nibbles(y)
        if lo is None or x < 0 or x >= self.atlas[2]:
            return 1
        return lo[x >> 1] if (x & 1) == 0 else hi[x >> 1]

    def _ink(self, x0, y0, x1, y1):
        """矩形内墨 (texel==0) 数量; 越界部分按空算。"""
        if not self.font_ok:
            return 0
        w, h = self.atlas[2], self.atlas[3]
        n = 0
        for y in range(max(0, y0), min(h, y1)):
            lo, hi = self._nibbles(y)
            if lo is None:
                continue
            for x in range(max(0, x0), min(w, x1)):
                if (lo[x >> 1] if (x & 1) == 0 else hi[x >> 1]) == 0:
                    n += 1
        return n

    def cell_ink(self, x, y):
        """CJK 格墨量 (缓存)。越界返回 -1。"""
        k = (x, y)
        v = self._cell_ink.get(k)
        if v is None:
            if y + CH > self.atlas[3] or y < 0:
                v = -1
            else:
                v = self._ink(x, y, x + CW, y + CH)
            self._cell_ink[k] = v
        return v

    # ---------- 字符集侧 ----------
    def encodable(self, s):
        """能否编码: ASCII / 私有区占位 / {{BTN:XXXX}} 标记 / 单字节码 / lead 合法的对偶码。"""
        if len(s) != 1:
            return self.cs.is_placeholder(s)        # 完整标记 ⇒ 一定能编码
        o = ord(s)
        if o < 0x80 or self.cs.is_placeholder(s):
            return True
        if s in self.cs.enc_single:
            return True
        p = self.cs.enc_pair.get(s)
        return bool(p) and PAIR_LEAD_LO <= p[0] < PAIR_LEAD_HI

    def pair_lead_bad(self, ch):
        """该字在 JSON 里有对偶码, 但 lead≥0xAE (引擎只认 0xA1..0xAD) ⇒ 写出去是乱码。"""
        p = self.cs.enc_pair.get(ch)
        return bool(p) and not (PAIR_LEAD_LO <= p[0] < PAIR_LEAD_HI)

    # ---------- 字形侧 ----------
    def has_glyph(self, ch):
        return self.glyph_reason(ch) is None

    def glyph_reason(self, ch):
        """返回 None (有字形) 或人话原因字符串。结果缓存 (每字只查一次图集)。"""
        if len(ch) != 1:                            # {{BTN:XXXX}} 整体: 不吃字库
            return None if self.cs.is_placeholder(ch) else '不是一个字符'
        if ch in self._gc:
            return self._gc[ch]
        r = self._check_glyph(ch)
        self._gc[ch] = r
        return r

    def _check_glyph(self, ch):
        o = ord(ch)
        if o < 0x80:
            return self._check_record(o)
        if self.cs.is_placeholder(ch):
            return None                     # 按键图标: 引擎直接给 UV, 不吃字库
        if ch in self.cs.enc_single:
            return self._check_record(self.cs.enc_single[ch])
        p = self.cs.enc_pair.get(ch)
        if p:
            return self._check_grid(p)
        return '不在字符集里'

    def _check_record(self, code):
        """单字节/ASCII: 查 FT 记录表 (idx = code-0x20) 的矩形及其邻域。"""
        if not self.font_ok:
            return None                     # 没装到字库 ⇒ 不阻断
        idx = code - 0x20
        if idx < 0 or idx >= self.rec_nrec:
            return ('码位 0x%02X 超出 FT 记录表 (idx=%d ≥ %d)'
                    % (code, idx, self.rec_nrec))
        _b0, _b1, u0, v0, u1, v1 = self.recs[idx]
        if u1 <= u0 or v1 <= v0:
            return 'FT 记录 0x%02X 的矩形退化 (%d,%d,%d,%d)' % (code, u0, v0, u1, v1)
        if self._ink(u0, v0, u1, v1):
            return None
        if self._ink(u0 + GLYPH_DU, v0 + GLYPH_DV, u1 + GLYPH_DU, v1 + GLYPH_DV):
            return None
        if self._ink(u0 - GLYPH_TOL_X, v0 - GLYPH_TOL_Y,
                     u1 + GLYPH_TOL_X, v1 + GLYPH_TOL_Y):
            return None
        return ('FT 记录 0x%02X 的矩形 (%d,%d,%d,%d) 及邻域在图集里是空的'
                % (code, u0, v0, u1, v1))

    def _check_grid(self, pair):
        """对偶码: 按**引擎格位公式** (round45 起 = 引擎图里的 (16*col, yrow)) 查图集。

        ★ 判据 = 「引擎格里、**第 1..15 行**有墨」而不是「整格有墨」 —— 只在前 1 行有墨的格子
          不是真字形 (那是渗漏/残留)。GR_ZH94 起盘上字形已对齐, 1319/1319 在第 1..15 行都有墨。
        ★ round67: 判据 = **实际像素** (下面 `cell_ink` / `_ink`)。round45 那条"有些格归单字节
          记录码所有"的静态例外已在本轮被逐格实测证伪 ⇒ `ATLAS_ENGINE_SINGLE_CELLS` 清空。
        """
        if not self.font_ok:
            return None
        slot = pair_slot(*pair)
        row, col = slot // NCOL, slot % NCOL
        # ★ round67: `ATLAS_ENGINE_SINGLE_CELLS` 已清空 (51 条标注全被实测证伪, 见常量区注释)
        #   ⇒ 这个分支现在恒不成立, 保留只为兼容"万一将来又出现真的占格冲突"。真正生效的
        #   判据是下面按**实际像素**查引擎格。
        if ATLAS_ENGINE_SINGLE_CELLS.get((row, col)):
            return ('引擎格 slot=%d (row=%d col=%d) 与**记录码采样窗**冲突 (%s) '
                    '⇒ 这个对偶码做不出字形, 必须换码位 (见 docs/REPORT_glyph_align.md)'
                    % (slot, row, col, ATLAS_ENGINE_SINGLE_CELLS[(row, col)]))
        x, y = atlas_cell_xy_engine_view(slot)
        n = self.cell_ink(x, y)
        if n < 0:
            return ('引擎格 slot=%d (row=%d) 超出图集下沿 y=%d'
                    % (slot, slot // NCOL, y))
        if self._ink(x, y + GRID_BLEED_ROWS, x + CW, y + CH):
            return None
        return ('引擎格 slot=%d (row=%d col=%d) 的格 (%d,%d) 在图集里是空的 '
                '(整格墨=%d; 去掉第 0 行后 0 ⇒ 那点墨不是字形)'
                % (slot, slot // NCOL, slot % NCOL, x, y, n))

    def glyph_basis(self, ch):
        """该字的字形判定**依据**哪条路径 (给 dump/报告用):

        'ft_record'   = FT 记录表 (ASCII <0x80 与单字节码 0xAF..0xFE)
        'atlas_cell'  = 引擎格位公式 (对偶码, 查图集 16x16 格)
        'engine_icon' = 不吃字库 (按键图标占位 {{BTN:XXXX}}/私有区)
        'none'        = 不在字符集里
        """
        if len(ch) != 1:
            return 'engine_icon' if self.cs.is_placeholder(ch) else 'none'
        o = ord(ch)
        if o < 0x80 or ch in self.cs.enc_single:
            return 'ft_record'
        if self.cs.is_placeholder(ch):
            return 'engine_icon'
        return 'atlas_cell' if ch in self.cs.enc_pair else 'none'

    def glyph_cell(self, ch):
        """引擎**实际采样窗**左上角 (x, y) —— 与 has_glyph 的判定同一口径 (引擎图坐标)。

        · 对偶码  : 引擎格 = atlas_cell_xy_engine_view(slot) = (16*col, yrow(row))
        · 单字节码: FT 记录矩形 (u0,v0) 原值 (引擎直接用它当采样窗, **无相位**;
                    实机 A/B 已证: 记录矩形在哪, 字就在哪)
        · ASCII   : 同上 (ASCII 记录在 EN 带 v0=452/482/395)
        返回 (x, y) 或 None (没有字形路径)。
        """
        if len(ch) != 1:
            return None
        o = ord(ch)
        code = o if o < 0x80 else self.cs.enc_single.get(ch)
        if code is not None:
            idx = code - 0x20
            if not (0 <= idx < self.rec_nrec):
                return None
            _b0, _b1, u0, v0 = self.recs[idx][:4]
            return u0, v0                        # 记录矩形 = 引擎采样窗 (无相位)
        p = self.cs.enc_pair.get(ch)
        return atlas_cell_xy_engine_view(pair_slot(*p)) if p else None

    def glyph_locator(self, ch):
        """给报告用: 该字的字形在哪 (FT 记录矩形 / 引擎格 / 无)。"""
        if not self.font_ok:
            return 'n/a'
        o = ord(ch)
        if o < 0x80 or ch in self.cs.enc_single:
            code = o if o < 0x80 else self.cs.enc_single[ch]
            idx = code - 0x20
            if 0 <= idx < self.rec_nrec:
                r = self.recs[idx]
                return 'FT rec[%d]=(%d,%d,%d,%d)' % (idx, r[2], r[3], r[4], r[5])
            return 'FT rec 越界 (idx=%d)' % idx
        p = self.cs.enc_pair.get(ch)
        if p:
            slot = pair_slot(*p)
            x, y = atlas_cell_xy_engine_view(slot)
            return '引擎格 slot=%d cell=(%d,%d)' % (slot, x, y)
        return '无'

    # ---------- 文本检查 ----------
    def check_text(self, text):
        """逐字符检查。返回问题列表 (同一字符只报一次)。

        每项: dict(kind, char, cp, reason, locator)
          kind = 'not_in_charset' | 'dead_pair' | 'no_glyph'

        ★ round33: ``{{BTN:XXXX}}`` 手柄按键标记**整体剔除后**才逐字符检查 ——
          这些标记是引擎直接给 UV 画图标, **不吃字库**, 所以绝不能因为它们报缺字。
          (旧写法: 私有区字符 U+E0XX 走下面的 is_placeholder 分支, 同样跳过。)
        ★ round35: ``{WRAP}`` 建议断点标记**同样整体剔除** —— 它注入时就被丢弃,
          根本不会写盘, 也不该被报缺字 (组成它的都是 ASCII)。
        """
        scan = WRAP_RE.sub('', BTN_RE.sub('', text))     # 工具标记: 整体跳过, 不查字库
        seen, out = set(), []
        for ch in scan:
            if ch in seen or ch == '\n':
                continue
            seen.add(ch)
            o = ord(ch)
            if o < 0x20:
                continue                # 控制字符 (不该出现, 由上游 CSV 检查管)
            if o < 0x80:
                # ★ ASCII: 引擎一律按单字节画, 与 charset JSON 无关 ⇒ 编码永远没问题。
                #   ⚠ 字形检查对 ASCII 只能「告警」, 不能判死: 实测现役盘正文大量使用小写
                #   (a-z, 5648 处) 且实机清晰可读 (例: 帮助/背景页的 "Tom Clancy" 小写正常显示),
                #   而本检查只覆盖 FT 的 default face —— 小写字形在别的 face 里。
                #   ⇒ 记为 ascii_no_glyph (告警), 由 inject 端按「不阻断」处理。
                if self.glyph_reason(ch):
                    out.append(dict(kind='ascii_no_glyph', char=ch, cp=o,
                                    reason=(self.glyph_reason(ch) +
                                            ' —— ASCII 仅告警: 引擎的 ASCII 单字节路径在其它 face 里有字形,'
                                            ' 现役盘实机可读'),
                                    locator=self.glyph_locator(ch)))
                continue
            if self.cs.is_placeholder(ch):
                continue                # 按键图标: 引擎直接给 UV, 不吃字库
            if ch in self.cs.enc_single:
                if self.glyph_reason(ch):
                    out.append(dict(kind='no_glyph', char=ch, cp=o,
                                    reason=self.glyph_reason(ch),
                                    locator=self.glyph_locator(ch)))
                continue
            if self.pair_lead_bad(ch):
                p = self.cs.enc_pair[ch]
                out.append(dict(kind='dead_pair', char=ch, cp=o,
                                reason=('只有不可用双字节码 %02X%02X (lead≥0xAE, '
                                        '引擎只认 0xA1..0xAD) ⇒ 写出去会变乱码'
                                        % (p[0], p[1])),
                                locator=self.glyph_locator(ch)))
                continue
            if ch in self.cs.enc_pair:
                if self.glyph_reason(ch):
                    out.append(dict(kind='no_glyph', char=ch, cp=o,
                                    reason=self.glyph_reason(ch),
                                    locator=self.glyph_locator(ch)))
                continue
            out.append(dict(kind='not_in_charset', char=ch, cp=o,
                            reason='字符集 (charset JSON) 里没有这个字',
                            locator=self.glyph_locator(ch)))
        return out

    # ---------- 反向检查 ----------
    def en_only_ascii(self, text):
        """反向检查: 文本里出现「本盘字符集 (JSON) 没声明、但英文原盘有」的 ASCII。

        ★ ASCII (<0x80) 引擎一律按单字节画, 与 charset JSON 无关 ⇒ 没声明也能编码;
          真正决定显示与否的是"现役图集里还有没有字形"。
        ★ round33: ``{{BTN:XXXX}}`` 标记先整体剔除 —— 组成标记的 { B T N : 0-9 }
          全是 ASCII, 不剔的话报告里会凭空多出 8 个「本盘字符集没有的字符」噪音。
        ★ round35: ``{WRAP}`` 建议断点标记同样剔除 (它注入时就被丢弃, 不是正文)。
        返回 [(char, cp, in_atlas)]; in_atlas = 现役图集里是否仍有字形。
        """
        out = []
        for ch in sorted(set(WRAP_RE.sub('', BTN_RE.sub('', text)))):
            o = ord(ch)
            if o >= 0x80 or o < 0x20 or ch == '\n':
                continue
            if ch in self.cs.enc_single:
                continue                     # 字符集里已声明 (本盘常用字/数字等)
            out.append((ch, o, not self.glyph_reason(ch)))
        return out

    def atlas_note(self):
        if not self.font_ok:
            return '未装载'
        pak, off, w, h = self.atlas
        return ('%dx%d @COMMON.PAK+0x%X; FT %s face, %d 条记录'
                % (w, h, off, getattr(self, 'face_name', '?'), self.rec_nrec))


# ─────────────────── 解码口径自检 (round29 关键坑) ───────────────────
#   ★ 本工程采用**单字节码优先**口径, 依据:
#     · ELF 四处 `sltiu reg, lead, 0xAE` ⇒ 只有 0xA1..0xAD 才是双字节 lead;
#     · 0xAF 是单字节「的」、0xB0 是单字节「你」(字表 codes 实测);
#     · 对偶优先 (tools/diag/res_text_dump.py 的 dec()) 会把 `AF A1 BD`(的 方) 拆成
#       `AF A1`=弗 + `BD`=开, 把 `B0 AF`(你 的) 拆成「蔡」等 → 整份 dump 系统性错字。
#   本工具链一律用 Charset.decode (上表口径), 并在 dump 时做锚点断言。
ANCHORS_LANG = [('G058.I192', 'A组'), ('G058.I193', 'B组'), ('G058.I194', 'C组'),
                ('G058.I195', '命令'), ('G058.I797', '正在读取记忆卡')]
ANCHORS_XML = [('T0010', '定向反步兵地雷')]


def selfcheck_charset(cs):
    """字符集口径自检。返回 (ok, 明细行列表)"""
    out, ok = [], True

    def chk(cond, msg):
        nonlocal ok
        ok = ok and bool(cond)
        out.append('%s %s' % ('[ok]' if cond else '[!!]', msg))
    # ★ round46 起「的/你」的具体码位**不再钉死**: 字库紧凑重排 (tools/iso_build/repack_font.py)
    #   每轮构筑都会按"当前槽位升序"重新机器分配全部对偶码 ⇒ A8BA/A8BB 只是 round40 那一轮的
    #   落点, 钉死它会让每一次重排都自检失败 (实测: 重排后 dump_text_csv 直接拒绝出表)。
    #   保留真正的不变量: **必须是对偶码 + lead 在引擎可读区间 + 编解码自洽** (round40 的本意
    #   "0xAF/0xB0 不再是单字节码" 由下面第 3 条单独把关, 与码位取值无关)。
    for _ch in ('的', '你'):
        _p = cs.enc_pair.get(_ch)
        _rt = bool(_p) and cs.encode_strict(_ch) == bytes(_p) \
            and cs.decode(bytes(_p))[0] == _ch
        chk(bool(_p) and PAIR_LEAD_LO <= _p[0] < PAIR_LEAD_HI and _ch not in cs.enc_single
            and _rt,
            '对偶码 %s = %s (必须是**对偶码**, lead 在 0x%02X..0x%02X, 且「编码↔解码」逐字节自洽; '
            '★ 具体码位由字库紧凑重排机器分配, 不再钉死 A8BA/A8BB)'
            % (_ch, _p, PAIR_LEAD_LO, PAIR_LEAD_HI - 1))
    chk(0xAF not in cs.codes and 0xB0 not in cs.codes,
        '字节 0xAF/0xB0 不再是单字节码 (已是 lead): %r / %r'
        % (cs.codes.get(0xAF), cs.codes.get(0xB0)))
    # lead 区间里绝不允许存在单字节码 (否则编码器会写出 1 字节的 lead)
    _bad_lead_single = sorted(c for c in cs.codes if LEAD_LO <= c < LEAD_HI)
    chk(not _bad_lead_single,
        'lead 区间 [0x%02X,0x%02X) 内的单字节码: %s'
        % (LEAD_LO, LEAD_HI, ['0x%02X' % c for c in _bad_lead_single] or '无'))
    # ── ★ round50: 「编码↔解码」的**通用不变量** (取代写死的 "AF A1 BD" 断言) ──
    #   round49 的坑: 这里原本钉死 `(0xAF, 0xA1)` 必须是合法对偶码, 再断言 `AF A1 BD` 的拆法。
    #   但字库紧凑重排 (round46 起每轮构筑默认开, tools/iso_build/repack_font.py) 会按
    #   "当前槽位升序" **机器重新分配全部对偶码** ⇒ 任何一个具体码位随时会变, 钉死它 =
    #   每次重排自检都失败 (实测: 重排后 dump_text_csv.py 直接拒绝出表, round49 因此只能关掉重排)。
    #   换成下面这几条**与人无关**的不变量后, 重排 / 回收死字 / 扩字都不会误报。
    _rt_bad = []
    for _ch, _b in sorted(cs.enc_single.items(), key=lambda kv: kv[1]):
        try:
            _e = cs.encode_strict(_ch)
            _d = cs.decode(_e)[0]
        except Exception:                                        # noqa: BLE001
            _rt_bad.append(_ch)
            continue
        if _e != bytes([_b]) or _d != _ch:
            _rt_bad.append(_ch)
    _n_rt_pair = 0
    for _ch, _p in sorted(cs.enc_pair.items(), key=lambda kv: pair_slot(*kv[1])):
        if not (PAIR_LEAD_LO <= _p[0] < PAIR_LEAD_HI):
            continue                    # 死 pair 由下面那条单独把关 (它本来就编不出去)
        _n_rt_pair += 1
        try:
            _e = cs.encode_strict(_ch)
            _d = cs.decode(_e)[0]
        except Exception:                                        # noqa: BLE001
            _rt_bad.append(_ch)
            continue
        if _e != bytes(_p) or _d != _ch:
            _rt_bad.append(_ch)
    chk(not _rt_bad,
        '全部在用码位「编码→解码」逐字节自洽: 单字节 %d 个 + 对偶 %d 个 ⇒ 不自洽 %d 个 %s '
        '(★ 不钉死任何具体码位)'
        % (len(cs.enc_single), _n_rt_pair, len(_rt_bad), ''.join(_rt_bad[:8]) or '无'))
    # 单字节码不得与**任何对偶 lead** 撞车 (撞了编码器就会写出 1 字节的"半个对偶码")
    _leads_used = set(p[0] for p in cs.enc_pair.values())
    _clash = sorted(c for c in cs.codes if c in _leads_used)
    chk(not _clash, '单字节码与对偶 lead 撞车: %s (期望 0 个)'
        % (['0x%02X' % c for c in _clash] or '无'))
    # **动态锚点**: 从本盘**实际在用**的对偶码里挑若干条做「对偶优先」断言 —— 不写死某个码。
    #   判据 = 「对偶码 + 单字节码」拼起来必须按 2+1 拆 (不能拆成 1+2 或 1+1+1)。
    #   (= 旧那条 `AF A1 BD → 对偶(0xAF,0xA1) + 0xBD` 的通用版; 旧版只是在 round40 那一轮
    #    恰好成立的实例。) 取槽位最小/最大的各 1 个对偶 + 最小/最大的各 1 个单字节。
    _ok_pairs = [(pair_slot(*p), ch, p) for ch, p in cs.enc_pair.items()
                 if PAIR_LEAD_LO <= p[0] < PAIR_LEAD_HI]
    _ok_pairs.sort(key=lambda t: (t[0], ord(t[1])))
    _sing = sorted((b, ch) for ch, b in cs.enc_single.items())
    if _ok_pairs and _sing:
        _cases = [(_ok_pairs[0][1], _ok_pairs[0][2], _sing[0]),
                  (_ok_pairs[-1][1], _ok_pairs[-1][2], _sing[-1])]
        for (_pc, _pp, (_sb, _sc)) in _cases:
            _seq = bytes(_pp) + bytes([_sb])
            _t, _mp = cs.decode(_seq)
            chk(_t == _pc + _sc and _mp == [0, 2],
                '对偶优先: %r(%s) + %r(%02X) = [%s] 解码 %r (期望 %r, 字节边界 %s)'
                % (_pc, bytes(_pp).hex(' '), _sc, _sb, _seq.hex(' '), _t, _pc + _sc, _mp))
    else:
        chk(False, 'charset 里对偶码 %d 个 / 单字节码 %d 个 —— 至少各要有一个才能做解码自检'
            % (len(_ok_pairs), len(_sing)))
    bad = [ch for ch, (b1, _b2) in cs.enc_pair.items()
           if not (PAIR_LEAD_LO <= b1 < PAIR_LEAD_HI)]
    chk(not bad, '字表里 lead 越界的死 pair: %s (期望 0 个)'
        % (''.join(bad[:8]) or '无'))
    # ── round33: 按键标记 ↔ 私有区占位 的往返自检 ──
    #   ★ round82: gate 抬到 0xB5 后, 0xB1 落进 lead 区间 [0xA1,0xB5) ⇒ 它**不再**能当图标码
    #     (写出去会被引擎当对偶首字节吞掉后一个字) ⇒ 对这类字节改为断言"被正确拒绝"。
    for byte in (0xB1, 0xB5, 0xE7, 0xF1):
        pua = chr(0xE000 + byte)
        m = BTN_FMT % (0xE000 + byte)
        if LEAD_LO <= byte < LEAD_HI:
            chk(cs.btn_code_ok(0xE000 + byte) is not None,
                '字节 0x%02X 落在 lead 区间 [0x%02X,0x%02X) ⇒ 已不是可用图标码, 应被拒绝 ✓'
                % (byte, LEAD_LO, LEAD_HI))
            continue
        chk(cs.is_placeholder(pua), 'is_placeholder(%r)=True (私有区旧写法)' % pua)
        chk(cs.is_placeholder(m), 'is_placeholder(%r)=True (标记新写法)' % m)
        chk(cs.marks_to_pua(m) == pua, '%s → %r' % (m, pua))
        chk(pua_to_marks(pua) == m, '%r → %s' % (pua, m))
        chk(cs.encode_strict(m) == bytes([byte]),
            '%s 编码为字节 0x%02X' % (m, byte))
        chk(cs.encode_strict(pua) == bytes([byte]),
            '旧写法 %r 编码为同一字节 0x%02X (向后兼容)' % (pua, byte))
    _ok_icon = next((b for b in (0xB1, 0xB5) if not (LEAD_LO <= b < LEAD_HI)), None)
    if _ok_icon is not None:
        chk(cs.marks_to_pua(BTN_FMT % (0xE000 + _ok_icon)) == chr(0xE000 + _ok_icon),
            '标记大小写不敏感 (%s)' % (BTN_FMT % (0xE000 + _ok_icon)).lower())
    for wrong in ('{{BTN:ZZZZ}}', '{{BTN:E0B1', '{{BTN:E0B1}', '{BTN:E0B1}',
                  '{{BTN:1234}}', '{{BTN:E0AF}}', '{{BTN:E0B1 }}'):
        try:
            cs.marks_to_pua(wrong)
            ok_ = False
        except BtnMarkError:
            ok_ = True
        chk(ok_, '非法标记 %-16r 被拒绝 (BtnMarkError)' % wrong)
    return ok, out


# ─────────────────── 换行/建议断点 互逆自检 (round35) ───────────────────

def selfcheck_newlines(cs):
    """「进(dump) ↔ 出(inject)」换行/断点口径自检。返回 ``(ok, 明细行列表)``。

    round36 的硬要求:
      · 盘上 1 个 ``{br}`` ⇒ CSV 里**恰好 1 个**换行 (不多出空行);
      · 盘上 1 个 ``{p}``  ⇒ CSV 里**恰好 1 个空行** (连续 2 个换行);
      · 人工写的 ``{WRAP}`` (大小写不限) ⇒ 注入时**一个真换行** ⇒ 盘上 ``{br}``;
      · dump **绝不自动插** ``{WRAP}`` (因此"没改动的条目一个字都不动");
      · 写错 ``{WRAP`` / ``{WRP}`` / 位置非法 (行首/行尾/紧邻换行或另一个断点) 一律拦下。
    """
    out, ok = [], True

    def chk(cond, msg):
        nonlocal ok
        ok = ok and bool(cond)
        out.append('%s %s' % ('[ok]' if cond else '[!!]', msg))

    # ── 1) 单字节级映射: 进出必须一一对应 ──
    chk(text_to_cell('A{br}B') == 'A\nB', 'text_to_cell(A{br}B) = %r (期望 A\\nB)'
        % text_to_cell('A{br}B'))
    chk(text_to_cell('A{p}B') == 'A\n\nB', 'text_to_cell(A{p}B) = %r (期望 A\\n\\nB)'
        % text_to_cell('A{p}B'))
    chk(text_to_cell('A{br}B{p}C') == 'A\nB\n\nC',
        'text_to_cell(A{br}B{p}C) = %r (期望 A\\nB\\n\\nC)' % text_to_cell('A{br}B{p}C'))
    chk(cell_to_bytes_text('A\nB', cs) == cs.encode_strict('A{br}B'),
        '1 个换行 → {br} (cell_to_bytes_text)')
    chk(cell_to_bytes_text('A\n\nB', cs) == cs.encode_strict('A{p}B'),
        '空行 (2 个换行) → {p} (cell_to_bytes_text)')
    # 渲染端 (wrap_w>0) 绝不能多出空行 —— round34 的 bug 就在这
    chk(render_cell('A{br}B', 270)[0] == 'A\nB',
        'render_cell(A{br}B, 270) = %r (期望 A\\nB —— 不得多出空行)'
        % render_cell('A{br}B', 270)[0])
    chk(render_cell('A{p}B', 270)[0] == 'A\n\nB',
        'render_cell(A{p}B, 270) = %r (期望 A\\n\\nB)' % render_cell('A{p}B', 270)[0])
    chk(render_cell('A{br}B', 270)[0] == text_to_cell('A{br}B'),
        'render_cell == text_to_cell (dump 单元格口径只有一个)')
    chk(render_cell('A{br}B', 270)[1] == 0,
        'render_cell 的"自动断点数"恒为 0 —— round36 起 dump **绝不**自动插 {WRAP}')

    # ── 2) 人工断点 {WRAP} ⇒ 真换行 ({br}); 写法/位置错了就拦 ──
    chk(cell_to_bytes_text('A%sB' % WRAP_MARK, cs) == cs.encode_strict('A{br}B'),
        '%s 人工断点 → 真换行 A{br}B' % WRAP_MARK)
    chk(cell_to_bytes_text('A{wrap}B', cs) == cs.encode_strict('A{br}B'),
        '小写 {wrap} 同样生效 (大小写不敏感)')
    chk(cell_to_bytes_text('A{Warp}B', cs) == cell_to_bytes_text('A%sB' % WRAP_MARK, cs),
        '{Warp} 与 {WRAP} 逐字节等价')
    chk(cell_to_bytes_text('A%sB' % WRAP_MARK, cs) != cell_to_bytes_text('AB', cs),
        '人工断点确实产生了字节 (不再是"整段丢弃")')
    chk(b'WRAP' not in cell_to_bytes_text('A%sB' % WRAP_MARK, cs),
        '盘上绝不会出现 "WRAP" 这串 ASCII 字样')
    chk(expand_wrap_marks('A%sB' % WRAP_MARK) == ('A\nB', 1),
        'expand_wrap_marks(A%sB) = %r' % (WRAP_MARK, expand_wrap_marks(
            'A%sB' % WRAP_MARK)))
    chk(count_wrap_marks('A%sB{wrap}C' % WRAP_MARK) == 2, '大小写混写的标记计数 = 2')
    for wrong in ('{WRAP', '{ WRAP }', '{WRAPP}', '{Wrap }', '士 {WRAP兵可获得',
                  '{WRAP兵可获得此勋章：', '{ W R A P }', '{WRP}'):
        try:
            expand_wrap_marks(wrong)
            good = False
        except WrapMarkError:
            good = True
        chk(good, '写错的断点标记 %-12r 被拒绝 (WrapMarkError)' % wrong)
    for badpos, why in (('{WRAP}A', '行首'), ('A{WRAP}', '行尾'),
                        ('A{WRAP}{WRAP}B', '两个标记紧挨'),
                        ('A\n{WRAP}B', '前一个字符是换行'),
                        ('A{WRAP}\nB', '后一个字符是换行'),
                        ('A\n\n{WRAP}B', '紧跟在空行之后')):
        try:
            expand_wrap_marks(badpos)
            good = False
        except WrapPlacementError:
            good = True
        chk(good, '位置非法的断点 %-16r 被拒绝 (WrapPlacementError: %s)' % (badpos, why))
    try:
        cs.encode_strict('A%sB' % WRAP_MARK)
        good = False
    except WrapMarkError:
        good = True
    chk(good, '编码器不变式: 带 %s 的文本进不了字节流 (WrapMarkError)' % WRAP_MARK)

    # ── 3) 严格互逆 + 逐字符保真 (样本只在**字符集里能编码**时使用) ──
    cand = [
        '第一段 中文 {br}第二段',
        '第一段{p}第二段{p}第三段',
        '没有标记的一段中文，引擎自己会按宽度折行。',
        '短{br}',
        '{p}开头就是空行',
        '尾随空格   {br}后面',
        '半个字 宽 的 混合 ASCII words here',
        '在幽灵行动中，符合以下条件的士 兵可获得此勋章，这是一段够长的中文长文本，'
        '用来验证折行提示的逐字符保真与互逆。',
    ]
    samples, dropped = [], []
    for s in cand:
        try:
            cs.encode_strict(s)
            samples.append(s)
        except CharsetError:
            dropped.append(s)
    chk(len(samples) >= 4, '换行样本可用 %d 个 (字符集里能编码的; 跳过 %d 个含生僻字的)'
        % (len(samples), len(dropped)))
    for w in (270, 0):
        bad = []
        for s in samples:
            cell, _ns, _nh = render_cell(s, w)
            if cell_to_bytes_text(cell, cs) != cs.encode_strict(s):
                bad.append(s)
        chk(not bad, 'wrap_w=%d: dump 单元格 → cell_to_bytes_text 逐字节回到原文 (%d 个样本)'
            % (w, len(samples)))
    # 人工断点: 落在用户写的位置上, 且不产生多余字节
    for (cell, want) in (('A%sB' % WRAP_MARK, 'A{br}B'),
                         ('A%sB%sC' % (WRAP_MARK, WRAP_MARK), 'A{br}B{br}C'),
                         ('A{wrap}B{Warp}C', 'A{br}B{br}C')):
        got = cs.decode(cell_to_bytes_text(cell, cs))[0]
        chk(got == want, '人工断点: %r → 盘上 %r (期望 %r)' % (cell, got, want))
        chk(len(cell_to_bytes_text(cell, cs)) ==
            len(cs.encode_strict(want)), '人工断点不产生多余字节 (%r)' % cell)

    # ── 4) 折行提示 (只读列 wrap_hint / wrap_preview) 的口径 ──
    def _enc1(ch):
        try:
            cs.encode_strict(ch)
            return True
        except CharsetError:
            return False

    seg = ''.join(c for c in cand[-1] if _enc1(c))
    if len(seg) < 40:                       # 字符集太窄时退回纯 ASCII 样本
        seg = ('a long ascii sample text that must wrap at 270 px because it is long enough '
               'to overflow the line width for sure')
    cell, marks, preview = wrap_hint_cell(seg, 270)
    chk(cell == text_to_cell(seg), 'wrap_hint_cell 的单元格 == text_to_cell (不含任何标记)')
    chk(count_wrap_marks(cell) == 0, 'dump 端单元格里 {WRAP} 个数 = 0 (绝不自动插标记) ✓')
    chk(len(marks) > 0, '该样本确实算出了折行点 (%d 个: %s)'
        % (len(marks), ','.join(str(p) for p in marks[:8])))
    spans = wrap_seg_spans(seg, 270)
    chk(marks == [b for (_a, b) in spans[:-1] if b > _a],
        '折行点位置 = wrap_seg_spans 的行边界 (%d 个)' % len(marks))
    chk(preview.count('|') == len(marks) and '|' not in cell,
        '折行预览里的 | 个数 == 折行点数, 且单元格本身不含 |')
    chk(preview.replace('|', '') == cell, '折行预览去掉 | 后与单元格逐字符相同')
    chk(all(cell[p - 1:p] and p > 0 for p in marks) and max(marks) < len(cell),
        '折行点位置都在单元格范围内 (1-based, "第 p 个字符之后")')
    chk(wrap_hint_cell(seg, 0)[1] == [] and wrap_hint_cell(seg, 0)[2] == '',
        'wrap_w=0 ⇒ 折行提示为空 (未标定宽度就不猜)')
    # 区间表与 wrap_seg 必须一致 (行数 + 行内容; 按折行模型的"折叠连续空格"口径比)
    lines = wrap_seg(seg, 270)
    same = (len(spans) == len(lines) and
            all(norm_ws(seg[a:b]) == norm_ws(ln) for (a, b), ln in zip(spans, lines)))
    contig = all(spans[i][1] == spans[i + 1][0] for i in range(len(spans) - 1)) \
        and spans[0][0] == 0 and spans[-1][1] == len(seg)
    chk(same and contig, 'wrap_seg_spans 与 wrap_seg 一致且区间连续 (行数 %d/%d)'
        % (len(spans), len(lines)))
    return ok, out


def selfcheck_anchors(cs, blob_lang=None, blob_xml=None):
    """容器正文锚点断言 (人眼可读的一致性证据)"""
    out, ok = [], True
    if blob_lang is not None:
        ents, _ = parse_lang(blob_lang)
        idx = {('G%03d.I%03d' % (e.g + 1, e.i)): e for e in ents}
        for loc, want in ANCHORS_LANG:
            e = idx.get(loc)
            got = cs.decode(e.data)[0] if e else None
            c = bool(got) and want in got
            ok = ok and c
            out.append('%s LANG %s = %r (期望含 %r)' % ('[ok]' if c else '[!!]', loc, got, want))
    if blob_xml is not None:
        idx = {'T%04d' % k: b for (k, _o, _l, b) in parse_sfxml(blob_xml)}
        for loc, want in ANCHORS_XML:
            b = idx.get(loc)
            got = cs.decode(b)[0] if b else None
            c = bool(got) and want in got
            ok = ok and c
            out.append('%s SFXML %s = %r… (期望含 %r)'
                       % ('[ok]' if c else '[!!]', loc, (got or '')[:24], want))
    return ok, out


# ═════════════════ 人工断点标记 {WRAP} (round36 语义变更) ═════════════════
#   ★ 用户要求原话: 「我希望主动控制断点, 只在内容里添加 {WRAP} 控制断点。」
#
#   round36 起 `{WRAP}` 的语义 = **人工断点指令** (不再是"引擎折行提示"):
#       · 只由**人**写在 `text_edited` 里 —— dump 端**绝不自动插入** (见 dump_text_csv.py);
#       · 注入时在该位置产生一个**真换行** ⇒ 盘上写出 `{br}` (人工确认的硬换行);
#       · 大小写不限 (`{WRAP}` / `{Warp}` / `{wrap}` 都认), dump 输出统一大写 `{WRAP}`。
#
#   为什么必须把「人工断点」与「引擎自动折行」分开 (round35 的教训):
#       round35 及更早的 dump 把**引擎算出来的自动折行点**也写成 `{WRAP}`
#       (现役盘 1548 个), 于是「我在这里断行」与「引擎碰巧在这里折行」长得一模一样:
#         · 注入端只能整段丢弃 ⇒ 用户写的断点**永远不生效** (用户本轮报障的根因);
#         · 若改成当真换行, 那 1548 个自动提示又会被一次性固化成硬换行。
#   ⇒ round36 的解法是"**源头分开**": dump 再也不写 `{WRAP}` ⇒ CSV 里出现的 `{WRAP}`
#       只可能是人写的, 一律当断点; 「引擎现在会在哪折行」只写进**只读列**
#       `wrap_hint` / `wrap_preview` (见 dump_text_csv.py, 注入器完全不看这两列)。
#
#   ★ 写法: **两种拼写都认, 大小写不限** —— `{WRAP}` 与 `{Warp}`(= `{WARP}`)。
#       用户原话里写的是 `{Warp}`, 而工具链历史文档里写的是 `{WRAP}` ——
#       这两串**不是**大小写关系 (`Warp` = W,a,r,p; `WRAP` = W,R,A,P), 所以正则里两种都列;
#       总计 2^4 = 16 种大小写组合全部接受。dump/报错信息统一写成 `{WRAP}`。
#   ★ 写错就拦 (WrapMarkError, 退出码 1, `--force` 不能绕过):
#       `{WRAP` / `{WRP}` / `{WRAPP}` / `{ WRAP }` / `{WAP}` …
#   ★ 位置非法就拦 (WrapPlacementError, 退出码 1):
#       **行首 / 行尾 / 紧邻另一个断点标记 或 紧邻换行** —— 这些位置会写出**连续标记**
#       (`{br}{br}`, 引擎画成空行), 而「1 换行 = {br} / 空行 = {p}」无法无损表示它
#       (dump 的往返自检会因此拒绝写 CSV) ⇒ 必须在注入前拦下。
#       想空一行: 在 CSV 里敲**一个空行** (连续 2 个回车) ⇒ 盘上写成 1 个 `{p}`。
WRAP_MARK = '{WRAP}'
WRAP_SPELLINGS = ('WRAP', 'WARP')                # 两种拼写 (各自大小写不限)
WRAP_RE = re.compile(r'\{(?:WRAP|WARP)\}', re.I)  # 合法标记 (两种拼写 + 大小写不敏感)
WRAP_CHUNK = 16                                  # 报错时最多展示的原文片段长度
#   「像 WRAP/WARP 的写法错误」白名单 (去空白+转大写后判定; 命中 = 拒绝注入)
WRAP_TYPOS = ('WR', 'WRA', 'WA', 'WAR', 'WRP', 'WAP', 'RAP', 'WARP', 'RWAP', 'WRAP')


def _wrap_lookalike(u):
    """u = 花括号里的内容 (已去空白 + 转大写), 或 (缺右花括号时) '{' 之后最多 16 个字符。
    「像不像想写 {WRAP}/{Warp} 但写错了」的判定 —— 只看**开头**这一段:

      · 前 8 个字符里出现 ``WRAP`` 或 ``WARP`` → 是 (WRAP / WARP / WRAPP / WARPP / XWRAP…)
      · 前 2~4 个字符是常见残缺写法            → 是 (WR / WRA / WA / WAR / WRP / WAP / RAP …)
      · 整体很短(≤6) 且是两种拼写之一的前缀     → 是 (WR / WRA / WA / WAR)

    ★ 现役盘实测: 正文里**没有任何**裸花括号 (唯一的 { 都来自 {br}/{p}/{{BTN:...}}/断点标记),
      所以这里的误报面是 0 —— 宁可对疑似写法错误报错, 也不许它被当成普通文字写进盘。
    """
    if not u:
        return False
    head = u[:8]
    if any(w in head for w in WRAP_SPELLINGS):
        return True
    if u[:4] in WRAP_TYPOS or u[:2] in WRAP_TYPOS[:2] or u[:2] == 'WA':
        return True
    return len(u) <= 6 and len(u) >= 2 and any(w.startswith(u) for w in WRAP_SPELLINGS)


def count_wrap_marks(text):
    """文本里有几个合法的断点标记 (``{WRAP}`` / ``{Warp}``, 大小写不限)。"""
    return len(WRAP_RE.findall(text or ''))


def wrap_hits(text):
    """文本里所有合法断点标记的位置: ``[(start, end)]`` (两种拼写 + 大小写不限)。"""
    return [(m.start(), m.end()) for m in WRAP_RE.finditer(text or '')]


def scan_wrap_marks(text):
    """扫描 ``{WRAP}`` 标记的**写法**错误 (不管位置; 位置见 scan_wrap_placement)。

    返回 ``(去掉合法标记后的文本, [问题...])``; 问题项 = ``(位置, 原文片段, 人话原因)``。
    **不抛异常** —— 供「一次性列出全部问题」的预检用; 真正要写盘时走 expand_wrap_marks。
    """
    out, probs, i, n = [], [], 0, len(text)
    while i < n:
        if text[i] != '{':
            out.append(text[i]); i += 1
            continue
        m = WRAP_RE.match(text, i)
        if m:
            i = m.end()                          # 合法标记: 交给 expand_wrap_marks 变真换行
            continue
        end = text.find('}', i + 1)
        if 0 <= end - i <= WRAP_CHUNK + 1:       # {..} 离得很近 ⇒ 整段作为嫌疑片段
            frag, adv = text[i:end + 1], end + 1
        else:                                    # 没有右花括号 (漏写/删了)
            frag, adv = text[i:i + WRAP_CHUNK], i + 1
        core = re.sub(r'\s+', '', frag[1:].rstrip('}')).upper()
        if _wrap_lookalike(core):
            probs.append((i, frag, _wrap_syntax_reason(frag)))
            i = adv
            continue
        out.append(text[i]); i += 1
    return ''.join(out), probs


def _wrap_syntax_reason(frag):
    """给一个「像 {WRAP}/{Warp} 但写错了」的片段, 说人话指出错在哪。"""
    core = frag[1:]
    closed = core.endswith('}')
    if closed:
        core = core[:-1]
    u = re.sub(r'\s+', '', core).upper()
    if not closed:
        return ('断点标记**没写完** —— 缺少右边的花括号 } (正确写法: %s, 也接受 {Warp})'
                % WRAP_MARK)
    if u in WRAP_SPELLINGS:
        return ('标记的**花括号里面/旁边不能有空格** (正确写法: %s, 也接受 {Warp})'
                % WRAP_MARK)
    return ('这不是合法的断点标记 —— 只有两种拼写: %s 与 {Warp} (各自大小写不限), '
            '你写的是 %r; 它既不会被当成断点、也不会被当成普通文字写进盘。'
            % (WRAP_MARK, frag))


class WrapMarkError(CharsetError):
    """CSV 里的 ``{WRAP}`` 断点标记**写法**错了 (语法错)。

    ★ 继承 CharsetError ⇒ 任何「凡 CharsetError 就跳过」的上游逻辑都不会漏掉它;
      但 inject_text_csv.py 会**先**单独接住它, 给「哪个标记、怎么写才对」的人话报错。
    ★ **不可被 --force 绕过**: 写错的标记不是断点, 也不该变成正文。
    """


class WrapPlacementError(CharsetError):
    """``{WRAP}`` 断点标记的位置非法 (行首 / 行尾 / 紧邻换行或另一个断点)。

    ★ 这些位置会写出**连续标记** (``{br}{br}``), 而 CSV 的「1 换行 = {br} / 空行 = {p}」
      无法无损表示它 (dump 的往返自检会因此拒绝写 CSV) ⇒ 注入前必须拦下。
    ★ 同样**不可被 --force 绕过** —— 放行只会写出一份"再 dump 就报错"的盘。
    """


def scan_wrap_placement(text):
    """扫描 ``{WRAP}`` 的**位置**问题 (不抛异常, 供一次性列出全部问题)。

    返回 ``[(位置, 原文片段, 人话原因)]``。判据 (都会在盘上产生**连续换行标记**):
      · 标记在文本**最开头** ⇒ 盘上以空行开头;
      · 标记在文本**最末尾** ⇒ 盘上以空行结尾;
      · 标记**紧邻另一个** ``{WRAP}`` ⇒ ``{br}{br}``;
      · 标记**紧邻一个换行** (前或后) ⇒ ``{br}{br}``。
    """
    text = text or ''
    hits = wrap_hits(text)
    if not hits:
        return []
    n, probs = len(text), []
    for (a, b) in hits:
        frag = text[max(0, a - 8):min(n, b + 8)]
        if a == 0:
            probs.append((a, frag, '断点标记在**文本最开头** —— 盘上会多出一个空行开头; '
                                   '确要空行请直接在开头敲回车, 否则把它挪到两个字之间'))
        elif b == n:
            probs.append((a, frag, '断点标记在**文本最末尾** —— 盘上会多出一个空行结尾; '
                                   '确要空行请直接在末尾敲回车, 否则把它挪到两个字之间'))
        elif text[a - 1] == '\n':
            probs.append((a, frag, '断点标记**紧跟在换行后面** —— 会写出连续换行 {br}{br} '
                                   '(引擎画成空行), 而 CSV 只能无损表示 1 个换行'
                                   ' ⇒ 请删掉其中一个; 想空一行请在 CSV 里敲**一个空行**'))
        elif text[b] == '\n':
            probs.append((a, frag, '断点标记**后面紧跟着换行** —— 会写出连续换行 {br}{br} '
                                   '(引擎画成空行), 而 CSV 只能无损表示 1 个换行'
                                   ' ⇒ 请删掉其中一个; 想空一行请在 CSV 里敲**一个空行**'))
    for (a1, b1), (a2, _b2) in zip(hits, hits[1:]):
        if a2 == b1:
            probs.append((a2, text[max(0, a1 - 8):min(n, b1 + 14)],
                          '**两个断点标记紧挨着** —— 会写出连续换行 {br}{br} (引擎画成空行), '
                          '而 CSV 只能无损表示 1 个换行 ⇒ 请删掉其中一个; '
                          '想空一行请在 CSV 里敲**一个空行** (连续 2 个回车)'))
    return probs


def expand_wrap_marks(text):
    """``{WRAP}`` / ``{Warp}`` 断点标记 → **一个真换行**。返回 ``(新文本, 断点个数)``。

    ★ 两种拼写 + 大小写不限; 写法错误 (``WrapMarkError``) 与位置非法
      (``WrapPlacementError``) 一律抛异常, 绝不静默当普通文本写进盘
      —— 否则游戏里会真的显示出 "{WRAP" 这串 ASCII。
    """
    if '{' not in (text or ''):
        return text, 0
    _clean, probs = scan_wrap_marks(text)               # ① 写法错误: 先拦
    if probs:
        pos, frag, why = probs[0]
        raise WrapMarkError(
            '断点标记写错了 @ 第 %d 个字符: %r\n'
            '  问题: %s\n'
            '  正确写法: %s 或 {Warp} —— 花括号 + WRAP/WARP (大小写不限)\n'
            '  它是什么意思: **人工断点** —— 注入时在这里写出一个真换行 (盘上 {br})。\n'
            '  怎么办: ① 按上面的正确写法改写; 或 ② 把这个位置**空着**, 想断行就敲回车。'
            % (pos + 1, frag, why, WRAP_MARK))
    bad = scan_wrap_placement(text)                     # ② 位置非法: 再拦
    if bad:
        prob = bad[0]
        more = ('\n  (这一条里还有 %d 处同类问题)' % (len(bad) - 1)) if len(bad) > 1 else ''
        raise WrapPlacementError(
            '断点标记的位置不对 @ 第 %d 个字符: %r\n'
            '  问题: %s%s\n'
            '  为什么必须拦: 这些位置会写出**连续换行标记** {br}{br} (引擎画成空行), '
            '而 CSV 的「1 换行 = {br} / 空行 = {p}」无法无损表示它'
            '(再 dump 回来时往返自检会拒绝写 CSV)。\n'
            '  怎么办: ① 把标记挪到**两个字之间**(前后都不是换行、也不是另一个标记); '
            '或 ② 想空一行 ⇒ 在那个位置敲**一个空行**(连续 2 个回车, 盘上写成 1 个 {p})。'
            % (prob[0] + 1, prob[1], prob[2], more))
    return WRAP_RE.sub('\n', text), len(WRAP_RE.findall(text))


def wrap_break_positions(cell):
    """``text_edited`` 里每个 ``{WRAP}`` 断点落在**去掉标记后的第几个字符之后**。

    返回 ``[p1, p2, ...]`` (0-based: ``p`` = 断点前面的字符数) —— 与盘上 ``{br}`` 的位置
    一一对应 (见 tag_break_positions), 供注入器做「人工断点落点核对」。
    """
    return [len(WRAP_RE.sub('', cell[:a])) for (a, _b) in wrap_hits(cell)]


def tag_break_positions(text):
    """引擎正文里 ``{br}``/``{p}`` 的位置: ``[(kind, p)]``。

    ``p`` = 该标记**前面**的可见字符数 (标记本身不计数) ⇒ 与 wrap_break_positions 同口径,
    可以直接比对「人写的 {WRAP} 到底落在了哪里」。
    """
    out, i, n, plain = [], 0, len(text or ''), 0
    while i < n:
        if text.startswith('{br}', i):
            out.append(('br', plain)); i += 4; continue
        if text.startswith('{p}', i):
            out.append(('p', plain)); i += 3; continue
        plain += 1; i += 1
    return out


def cells_to_marked(cells):
    """给报告用: 把若干单元格里的私有区占位换成标记写法 (只影响显示)"""
    return [pua_to_marks(c) for c in cells]


# ───────────────────────── 换行约定 (CSV <-> 字节) ─────────────────────────
#   ★ round36 起「进(dump)/出(inject)」**严格互逆**, 且「人工断点」与「引擎自动折行」分开:
#
#     盘上引擎字节            CSV 单元格                注入回盘
#     ─────────────────────  ─────────────────────────  ────────────────────────────
#     {br}                   1 个换行                   1 个换行         → {br}
#     {p}                    1 个空行 (连续 2 个换行)   ≥2 个连续换行    → 1 个 {p}
#     (无标记, 引擎自动折行) **不写任何标记**           —— (只读列 wrap_hint 里给提示)
#     人工写的 {WRAP}        {WRAP} (大小写不限)       → {br}  ★ 这就是"人工控制断点"
#
#   ⇒ 人工在 CSV 里敲 1 个回车, 盘上就恰好多 1 个 {br}; 敲 1 个空行, 盘上就是 1 个 {p};
#     在想断行的地方写一个 {WRAP}, 盘上同样恰好多 1 个 {br} —— 三种写法都只影响那一个位置。
#   ★ dump **绝不**自动插 {WRAP} ⇒ 「没改动的条目一个字都不动」(往返零字节差异)。

def text_to_cell(text):
    """引擎正文 → CSV 单元格 (**不含**任何断点标记)。

    映射: ``{p}`` → 空行, ``{br}`` → 换行 (顺序敏感: 先 {p});
          私有区占位 U+E0XX → ``{{BTN:E0XX}}`` 标记 (round33, Excel 能显示)。

    ★ 顺序: 先换标记再换换行都行 —— 标记里不含 {br}/{p}, 换行标记里不含 PUA。
    ★ round36 起这里是 dump 的**唯一**单元格口径: 「引擎会在哪自动折行」不再塞进单元格,
      只写进只读列 wrap_hint / wrap_preview (见 wrap_hint_cell)。
    ★ 前提: 盘上**不出现连续标记** (如 ``{br}{br}``/``{p}{p}``) —— 否则
      「1 换行 = {br} / 空行 = {p}」无法互逆 (现役盘 2261 条实测 0 处; dump 会自检)。
    """
    t = pua_to_marks(text)
    t = t.replace('{p}', '\n\n')
    return t.replace('{br}', '\n')


def cell_to_bytes_text(cell, charset, stats=None):
    """CSV 单元格文本 → 引擎字节 (text_to_cell 的逆)。

    规则 (与 dump 端严格互逆, 见 FORMAT.md §3):
      · ``{WRAP}`` **人工断点** (大小写不限) → **一个真换行** ⇒ 盘上 ``{br}``;
        位置非法 (行首/行尾/紧邻换行或另一个断点) 抛 ``WrapPlacementError``;
      · 1 个换行 → ``{br}``; 连续 ≥2 个换行 (空行) → 折叠成 1 个 ``{p}``;
      · ``{{BTN:XXXX}}`` → 原控制字节。

    ★ 向后兼容: 单元格里若仍是**原始私有区字符** U+E0XX (round32 及更早的 CSV),
      照旧能注入; 两种写法编码结果逐字节相同。
    ★ 写错的标记 (``{{BTN:...`` / ``{WRAP`` 等) 由 expand_wrap_marks / encode_strict 抛
      WrapMarkError / BtnMarkError ⇒ 调用方必须拒绝注入 (绝不静默当普通文本写进去)。
    ★ stats (可选 dict): 填上 n_wrap(人工断点个数) / n_br / n_p / max_run, 供报告与告警。
    """
    s = cell.replace('\r\n', '\n').replace('\r', '\n')
    s, n_wrap = expand_wrap_marks(s)                # ★ 人工断点 → 真换行 (round36)
    out, i, n = [], 0, len(s)
    n_br = n_p = max_run = 0
    while i < n:
        if s[i] == '\n':
            j = i
            while j < n and s[j] == '\n':
                j += 1
            run = j - i
            max_run = max(max_run, run)
            if run >= 2:
                out.append('{p}'); n_p += 1
            else:
                out.append('{br}'); n_br += 1
            i = j
        else:
            out.append(s[i]); i += 1
    if stats is not None:
        stats.update(n_wrap=n_wrap, n_wrap_breaks=n_wrap, n_br=n_br, n_p=n_p, max_run=max_run)
    return charset.encode_strict(''.join(out))


# ───────────────────────────── 折行模型 ─────────────────────────────

def strlen(s):
    return 0 if not s else sum(W_ASCII if ord(c) < 0x80 else W_CJK for c in s) + (len(s) - 1) * TRACK


def norm_ws(s):
    """把连续空白折叠成一个空格并去掉首尾 (折行模型的"看词"口径)。

    ★ 折行模型 `wrap_seg` 是按单个空格切词的 ⇒ 它眼里的行文本**折叠了连续空格**;
      而 CSV 单元格保留原文的**每一个空格**(逐字节保真)。
      两者的差异只影响"比较", 不影响写盘 —— 见 FORMAT.md §9。
    """
    return ' '.join((s or '').split())


def segments(text):
    """按 {br}/{p} 切段, 返回 [(start,end,seg)]"""
    segs, pos = [], 0
    for m in TAG_RE.finditer(text):
        segs.append((pos, m.start(), text[pos:m.start()]))
        pos = m.end()
    segs.append((pos, len(text), text[pos:]))
    return segs


def wrap_seg(seg, wrap_w):
    """忠实还原 RSTextComponent::DoWordWrap @0x21CC10, 返回渲染行列表。"""
    toks = [t for t in seg.split(' ') if t]
    if not toks:
        return [seg] if seg else []
    lines, cur, s1, first = [], '', wrap_w, True
    for ti, tk in enumerate(toks):
        tw = strlen(tk)
        if wrap_w < tw:                                        # 逐字硬断兜底
            for ch in tk:
                c = (W_ASCII if ord(ch) < 0x80 else W_CJK) + TRACK
                s1 -= c
                if s1 < 0:
                    lines.append(cur); cur, s1 = ch, wrap_w - c
                else:
                    cur += ch
            first = False
        else:
            s3 = tw + (0 if first else FP)
            s1 -= s3
            s1 -= TRACK
            if s1 < 0:
                lines.append(cur); cur, s1 = tk, wrap_w - s3 + FP
            else:
                cur += tk
            first = False
        if ti + 1 < len(toks):
            s1 -= FP
            cur += ' '
    if cur:
        lines.append(cur)
    return lines


def wrap_seg_spans(seg, wrap_w):
    """RSTextComponent::DoWordWrap 的**字符区间**版 (round35)。

    返回 ``[(start, end)]`` —— 与 ``wrap_seg(seg, wrap_w)`` 的行**一一对应**, 且
      · 区间首尾相接: start[0]=0, start[k+1]=end[k], end[-1]=len(seg);
      · ``seg[start:end]`` 就是该行的原文 (含模型放在行尾的那个空格)。
    ⇒ 在这些边界插一个**零宽标记**就能既显示断点、又逐字符保真 (去掉标记即还原原文)。

    空行 (模型偶尔会吐出的空行 —— 例如 wrap_w 恰好等于首个 token 宽度时) 用 (p, p) 表示,
    调用方不为它插标记。

    ★ 与 wrap_seg 的一致性由 dump 的往返自检逐段断言 (见 dump_text_csv.assert_csv_roundtrip)。
    """
    toks = [(m.start(), m.end()) for m in re.finditer(r'[^ ]+', seg)]
    if not toks:
        return [(0, len(seg))] if seg else []
    spans, cur, s1, first = [], None, wrap_w, True
    for ti, (ts, te) in enumerate(toks):
        tk = seg[ts:te]
        tw = strlen(tk)
        if wrap_w < tw:                                        # 逐字硬断兜底
            for ci in range(te - ts):
                ch = seg[ts + ci]
                c = (W_ASCII if ord(ch) < 0x80 else W_CJK) + TRACK
                s1 -= c
                if s1 < 0:
                    spans.append((cur if cur is not None else ts + ci, ts + ci))
                    cur, s1 = ts + ci, wrap_w - c
                elif cur is None:
                    cur = ts + ci
            first = False
        else:
            s3 = tw + (0 if first else FP)
            s1 -= s3
            s1 -= TRACK
            if s1 < 0:
                spans.append((cur if cur is not None else ts, ts))
                cur, s1 = ts, wrap_w - s3 + FP
            elif cur is None:
                cur = ts
            first = False
        if ti + 1 < len(toks):
            s1 -= FP
    spans.append((cur if cur is not None else len(seg), len(seg)))
    return spans


def wrap_hint_cell(text, wrap_w):
    """引擎正文 → ``(CSV 单元格, 折行点位置表, 折行预览)`` —— **只读提示, 不插任何标记**。

    ★ round36 起 dump **不再**往单元格里塞 ``{WRAP}`` (那会与人工断点混淆, round35 的病灶),
      「引擎现在会在哪自动折行」只写成两个**只读列**:
        · 位置表: 1-based 字符位置, 相对**单元格文本**(含其中的换行), 表示
                  "第 p 个字符之后引擎会换到下一行"; 形如 ``14,33,50``; 不折行 ⇒ 空;
        · 预览  : 单元格文本在同样位置插 ``|``, 一眼就能看出引擎现在断在哪。

    返回 ``(cell, [p...], preview)``。``wrap_w <= 0`` ⇒ 位置表为空、预览为空串
    (未标定宽度的资源不猜折行点)。折行模型口径 = RSTextComponent::DoWordWrap (见 wrap_seg)。
    """
    cell_parts, marks, pos, n_cell = [], [], 0, 0

    def add_seg(seg):
        """把一段正文 (两个 {br}/{p} 之间) 追加进单元格, 并记录该段内的折行点。"""
        nonlocal n_cell
        if not seg:
            return
        base, cseg = n_cell, pua_to_marks(seg)
        if wrap_w > 0:
            spans = wrap_seg_spans(seg, wrap_w)
            for (a, b) in spans[:-1]:
                if b > a:                       # 空行 (b==a) 不产生断点
                    marks.append(base + len(pua_to_marks(seg[:b])))
        cell_parts.append(cseg)
        n_cell += len(cseg)

    for m in TAG_RE.finditer(text):
        add_seg(text[pos:m.start()])
        rep = '\n\n' if m.group(0) == '{p}' else '\n'
        cell_parts.append(rep)
        n_cell += len(rep)
        pos = m.end()
    add_seg(text[pos:])
    s = ''.join(cell_parts)
    if not marks:
        return s, [], ''
    prev, out = 0, []
    for p in marks:
        out.append(s[prev:p]); out.append('|'); prev = p
    out.append(s[prev:])
    return s, marks, ''.join(out)


def render_cell(text, wrap_w=0, strip_tail=False):
    """★ round36 起本函数**不再插任何标记** (= text_to_cell), 返回 ``(cell, 0, 硬标记数)``。

    历史: round35 及更早它会把折行模型的断点写成 ``{WRAP}`` 塞进单元格 —— 而 round36 起
    ``{WRAP}`` 是**人工断点** (注入时变真换行) ⇒ 再自动插标记就等于"替用户把引擎折行固化",
    这正是本轮要修的病灶。故保留函数名 (向后兼容调用方), 但**一律不插标记**, 需要看折行点
    请用 :func:`wrap_hint_cell` (只读提示)。

    ``wrap_w`` / ``strip_tail`` 保留在签名里但被忽略 (旧调用方传了也不会出事)。
    """
    cell = text_to_cell(text)
    return cell, 0, len(TAG_RE.findall(text))


def wrap_render(text, wrap_w=0, strip_tail=False):
    """render_cell 的旧名 (round36 起同样**不插标记**; 参数被忽略)。"""
    return render_cell(text, wrap_w, strip_tail)


def wrap_line_count(text, wrap_w):
    n = 0
    for _a, _b, s in segments(text):
        n += len(wrap_seg(s, wrap_w))
    return n


# ─────────────────────── 容器: LANG 语言表 ───────────────────────

class LangEntry:
    __slots__ = ('g', 'i', 'data_off', 'length', 'attr_off', 'data')

    def __init__(self, g, i, data_off, length, attr_off, data):
        self.g, self.i = g, i
        self.data_off, self.length, self.attr_off, self.data = data_off, length, attr_off, data


def parse_lang(blob):
    """解析语言表。返回 (entries, used_end)。

    真实布局 (与 tools/diag/res_text_dump.py / patch_zh63 的既有口径一致, 实证:
    G58.I797 = 读卡提示串):
        {u32 ngroups}
        组 1:                       {u32 count} {u32 len}{data}{u16 attr} × count
        组 k (k>=2): {u32 0(分隔)}   {u32 count} {u32 len}{data}{u16 attr} × count
    本盘: ngroups=66, 条目合计 2232, 有效区结束 @68615。
    """
    ng = struct.unpack_from('<I', blob, 0)[0]
    p = 4
    ents = []
    for g in range(ng):
        if g:
            p += 4                       # 组间分隔 u32 (实测恒 0)
        cnt = struct.unpack_from('<I', blob, p)[0]
        p += 4
        for i in range(cnt):
            ln = struct.unpack_from('<I', blob, p)[0]
            p += 4
            data = bytes(blob[p:p + ln])
            p += ln
            attr_off = p
            p += 2
            ents.append(LangEntry(g, i, p - ln - 2, ln, attr_off, data))
    return ents, p


def lang_entry_span(blob, e):
    """整条记录的字节区间 [start, end) = 4B len + data + 2B attr"""
    return e.data_off - 4, e.attr_off + 2


# ─────────────────────── 容器: SFXML ───────────────────────

TEXT_RE = re.compile(rb'<text>([^<]*)</text>')


def parse_sfxml(xml):
    """返回 [(idx(1-based), body_off, body_len, body)]"""
    out = []
    for k, m in enumerate(TEXT_RE.finditer(xml), start=1):
        out.append((k, m.start(1), m.end(1) - m.start(1), bytes(m.group(1))))
    return out


def xml_tail_start(xml):
    """</SpecialFeatures> 之后 (有效内容结束) 的偏移"""
    m = xml.find(b'</SpecialFeatures>')
    return (m + len(b'</SpecialFeatures>')) if m >= 0 else (xml.rfind(b'>') + 1)


# ───────────────────────── 通用: 编辑应用 ─────────────────────────

def splice(blob, edits):
    """edits = [(start, end, newbytes)] (区间不重叠, 可乱序); 返回新 bytes"""
    if not edits:
        return blob
    edits = sorted(edits, key=lambda x: x[0])
    out, pos = bytearray(), 0
    for a, b, nb in edits:
        assert a >= pos, '编辑区间重叠: %d < %d' % (a, pos)
        out += blob[pos:a] + nb
        pos = b
    out += blob[pos:]
    return bytes(out)


# ═══════════════════ 英文基线盘 → CSV 的 text_en 列 (round34) ═══════════════════
#   `text_en` 是**只读参考列**: 供人工校对时对照英文原文。它**不参与注入**
#   (inject_text_csv.py 读表后立刻把这一列丢掉, 见该脚本 load_table_inputs → drop_ignored_cols)。
#
#   为什么要单独写一套解码: 英文基线盘 (USA SLUS-206.13) 用的是**它自己的字库**,
#   和现役中文盘的 charset JSON 不是一回事。实测英文盘正文里 >=0x80 的字节
#   **全部符合 Windows-1252** 语义 (逐条上下文取证, 见 docs/REPORT_en_column.md §2):
#       0x85 → '…'   0x92 → '’'   0xA0 → 空格   0xAE → '®'   0xBE → '¾'
#       0xE7 → 'ç'   0xE9 → 'é'   0xF1 → 'ñ'
#   例: 'you[92]ll' → you’ll / 'PlayStation[AE]2' → PlayStation®2 /
#       'a layer of [BE] of a pound' → ¾ 磅 (中文盘同条译作「约 340 克」, 340g = ¾ lb ✓) /
#       'Fran[E7]ais' → Français。
#
#   ★ 两个字节是**手柄按键图标占位** (引擎直接画图标, 不吃字库), 与中文盘同一套:
#       0xB1 0xB5 → {{BTN:E0B1}} {{BTN:E0B5}}   (英文原文自己写着
#       "Use the [B5] button to add a waypoint, and press the [B1] button to remove it.")
#
#   ★ 未列出的任何字节 (>=0x80 / C0 / DEL) 一律**拒绝 dump**并指名道姓 ——
#     宁可让工具报错, 也不许把不可见字符塞进给用户看的 CSV (与 round33 的 PUA 硬门槛同一思路)。
EN_ISO_DEFAULT = os.path.join(REPO, 'work', 'builds', 'GR_EN_ORIG', 'GR_EN_ORIG.iso')

#   字节 -> 显示字符 (Windows-1252 口径, 只列实测出现过的; 值是**可见**字符)
EN_CP1252 = {
    0x85: '\u2026',      # …  HORIZONTAL ELLIPSIS
    0x92: '\u2019',      # ’  RIGHT SINGLE QUOTATION MARK
    0xA0: ' ',           #    NO-BREAK SPACE  ← 故意降级成普通空格: CSV 里不留不可见字符
    0xAE: '\u00ae',      # ®  REGISTERED SIGN
    0xBE: '\u00be',      # ¾  VULGAR FRACTION THREE QUARTERS
    0xE7: '\u00e7',      # ç
    0xE9: '\u00e9',      # é
    0xF1: '\u00f1',      # ñ
}
#   图标占位字节 -> 与中文盘一致的 {{BTN:XXXX}} 标记 (XXXX = 0xE000 + 字节值)
EN_ICON_BYTES = (0xB1, 0xB5)


class EnDecodeError(ValueError):
    """英文基线盘出现本工具没见过的字节 —— 拒绝 dump, 请人工取证后再加进 EN_CP1252。"""


def decode_en(data, where='?'):
    """英文基线盘正文 → (可读文本, 统计 dict)。

    统计: dict(bytes={字节: 次数}, icons={字节: 次数}, mapped={字节: 次数},
               ascii_ctl=[])
    """
    out, st = [], dict(bytes={}, icons={}, mapped={}, ascii_ctl=[])
    for pos, b in enumerate(data):
        if b < 0x80:
            if b < 0x20 or b == 0x7F:
                st['ascii_ctl'].append((pos, b))
                raise EnDecodeError(
                    '英文盘 %s 第 %d 个字节是 ASCII 控制字符 0x%02X —— 本工具不知道它该怎么显示。\n'
                    '   怎么办: 请人工确认它的含义, 再决定 (报错而不是猜)。' % (where, pos + 1, b))
            out.append(chr(b))
            continue
        st['bytes'][b] = st['bytes'].get(b, 0) + 1
        if b in EN_ICON_BYTES:
            st['icons'][b] = st['icons'].get(b, 0) + 1
            out.append(BTN_FMT % (0xE000 + b))
            continue
        ch = EN_CP1252.get(b)
        if ch is None:
            raise EnDecodeError(
                '英文盘 %s 第 %d 个字节是 0x%02X —— 本工具**没见过**这个字节, 不猜它的含义。\n'
                '   上下文: %r\n'
                '   怎么办: 请人工确认这是哪个字符 (英文盘的高位字节实测符合 Windows-1252), '
                '然后加进 tcslib.EN_CP1252 (或 EN_ICON_BYTES, 若它是图标占位)。'
                % (where, pos + 1, b, data[max(0, pos - 24):pos + 24]))
        st['mapped'][b] = st['mapped'].get(b, 0) + 1
        out.append(ch)
    return ''.join(out), st


def en_read_tables(iso, verify_copies=True):
    """从**英文基线盘**读出两张表, 返回 (lang, sfxml, info)。

    lang  : {'LANG:G058.I195': '英文原文(已转 {{BTN:XXXX}} / 已是 CSV 单元格写法)'}
    sfxml : {'SFXML:T0010': '...'}
    对齐键与 dump 出来的 `id` 完全一致 (LANG 用 G组号.I条目号; SFXML 用条目序 T%04d)。
    只读**第一份拷贝** (与中文盘 dump 的主拷贝一致: EN_STRINGS.RES@MENU);
    info['copies_differ'] 会列出两份拷贝内容不同的条目 (英文基线盘实测有 12 条;
    实测中文译文是从**第一份拷贝**翻的 —— 见 docs/REPORT_en_column.md §3)。
    """
    info = dict(iso=iso.path, lang=dict(entries=0, nonempty=0, empty_ids=[], bytes=0,
                                        bytes_hist={}, icons={}, mapped={}),
                sfxml=dict(entries=0, nonempty=0, empty_ids=[], bytes=0,
                           bytes_hist={}, icons={}, mapped={}),
                copies_differ=[], entry_bytes={})

    # ── LANG: 只有第一份拷贝参与 text_en ──
    ent_by_copy, all_by_copy = [], []
    for ci, (img, lba, idx, tag) in enumerate(RES['LANG']['copies']):
        e = iso.img_entry(lba, idx)
        blob = b''.join(s[0] for s in lzo_subs(iso.read(e['iso_off'], e['stored'])))
        ents = parse_lang(blob)[0]
        all_by_copy.append(dict((('LANG:G%03d.I%03d' % (x.g + 1, x.i)), x) for x in ents))
        ent_by_copy.append(dict((k, v) for k, v in all_by_copy[-1].items() if v.length))
    lang = {}
    for rid in sorted(ent_by_copy[0]):
        x = ent_by_copy[0][rid]
        t, st = decode_en(x.data, 'LANG %s' % rid)
        lang[rid] = text_to_cell(t)
        info['lang']['nonempty'] += 1
        info['lang']['bytes'] += x.length
        for d, k in ((st['bytes'], 'bytes_hist'), (st['icons'], 'icons'), (st['mapped'], 'mapped')):
            for b, n in d.items():
                info['lang'][k][b] = info['lang'][k].get(b, 0) + n
        if st['bytes']:
            info['entry_bytes'][rid] = dict(st['bytes'])
    info['lang']['empty_ids'] = sorted(k for k, v in all_by_copy[0].items() if not v.length)
    if verify_copies:
        all_ids = set()
        for c in ent_by_copy:
            all_ids |= set(c)
        for rid in sorted(all_ids):
            a = ent_by_copy[0].get(rid)
            da = a.data if a is not None else None
            if any((c[rid].data if rid in c else None) != da for c in ent_by_copy[1:]):
                info['copies_differ'].append(rid)

    # ── SFXML ──
    c0 = RES['SFXML']['copies'][0]
    e = iso.img_entry(c0[1], c0[2])
    blob = b''.join(s[0] for s in lzo_subs(iso.read(e['iso_off'], e['stored'])))
    items = parse_sfxml(blob)
    sfxml = {}
    for (k, off, ln, body) in items:
        rid = 'SFXML:T%04d' % k
        info['sfxml']['entries'] += 1
        if not ln:
            info['sfxml']['empty_ids'].append(rid)
            continue
        t, st = decode_en(body, 'SFXML %s' % rid)
        sfxml[rid] = text_to_cell(t)
        info['sfxml']['nonempty'] += 1
        info['sfxml']['bytes'] += ln
        for d, kk in ((st['bytes'], 'bytes_hist'), (st['icons'], 'icons'), (st['mapped'], 'mapped')):
            for b, n in d.items():
                info['sfxml'][kk][b] = info['sfxml'][kk].get(b, 0) + n
        if st['bytes']:
            info['entry_bytes'][rid] = dict(st['bytes'])
    info['lang']['entries'] = len(all_by_copy[0])
    return lang, sfxml, info


def fmt_en_hist(hist, mapped_dict=None):
    """人话打印 '0x92×14→’ 0xAE×27→®' 这类字节分布。"""
    return ' '.join('%02X×%d%s' % (b, n, ('→' + EN_CP1252[b]) if (mapped_dict and b in EN_CP1252)
                                   else ('→{{BTN:%04X}}' % (0xE000 + b) if b in EN_ICON_BYTES else ''))
                    for b, n in sorted(hist.items()))


# ══════════════ 多表布局: 按 kind 拆成多张 CSV (round37, 用户要求) ══════════════
#   用户原话: 「修改一下脚本 改成按照 kind 进行分类 输出多个表格。」
#
#   为什么要拆:
#     · 一张大表 2261 行里混着三类完全不同的东西 —— 可写 {WRAP} 的长段 (58) /
#       语言表长段 (255) / 按钮·条目名·提示 (1948); 在 Excel 里翻找费劲, 而且最容易
#       出现「改了一张、另一张忘了改」的歧义。
#     · 拆开之后每张表**表头与列完全不变** (16 列), 只是行按 kind 分开 ⇒ 工具口径零变化。
#
#   布局 (都在版本文件夹内):
#     text/<版本>_text_long.csv         kind=long          ★ 可写 {WRAP} 控制断点的长段
#     text/<版本>_text_long_nowrap.csv  kind=long_nowrap   语言表长段 (简报等, 宽度未标定)
#     text/<版本>_text_short.csv        kind=short         按钮 / 条目名 / 短提示
#     text/<版本>_text_locked.csv       kind=locked        不可编辑 (字节回环不稳定; 通常 0 条)
#     text/<版本>_text.txt              合并的**一份**轻量快照 (id<TAB>正文; 便于 git diff)
#     text/<版本>_text.meta.json        每张表的条数 / kind 列表 / 总条数 / sha256
#   ★ **不再**产出合并的大 CSV —— 免得"改了一张、另一张没改"。
#   ★ 某一类 kind 一条都没有时**照样产出只有表头的空表** (别让人以为漏了)。
#   ★ 注入: `--csv` 可给多次, 也可以直接给**目录** (自动读目录下所有 *_text_*.csv);
#           多张表**按 id 合并**; 同一个 id 出现在两张表且 text_edited 不同 ⇒ 报错 (歧义)。
FMT_TABLES = 'text-csv/4'                        # round37: 多表布局 (每张表仍是 16 列)
TABLE_KIND_ORDER = ('long', 'long_nowrap', 'short', 'locked')
ALWAYS_KINDS = ('long', 'long_nowrap', 'short')  # 主表: 即使 0 条也产出空表
TABLE_GLOB = '*_text_*.csv'
_TABLE_RE = re.compile(r'^(?P<base>.+_text)_(?P<kind>[A-Za-z][A-Za-z0-9_]*)$')
_OLD_MERGED_RE = re.compile(r'^.*_text\.csv$', re.I)


def esc_text(s):
    """正文 → 单行转义形式 (TXT 快照 / 跨版本对比的唯一口径; 可逆)。"""
    return (s.replace('\\', '\\\\').replace('\r', '\\r')
             .replace('\n', '\\n').replace('\t', '\\t'))


def csv_stem(path):
    """路径去掉 .csv 后缀。"""
    p = str(path)
    return p[:-4] if p.lower().endswith('.csv') else p


def split_table_name(path):
    """表文件名 → ``(base, kind)``。

    ``…/GR_ZH92_text_long.csv`` → ``(…/GR_ZH92_text, 'long')``
    ``…/GR_ZH92_text.csv``      → ``(…/GR_ZH92_text, None)``      (老的大表)
    """
    stem = csv_stem(path)
    m = _TABLE_RE.match(stem)
    return (m.group('base'), m.group('kind')) if m else (stem, None)


def is_table_csv(path):
    """是不是一张「按 kind 分出来的表」 (``*_text_<kind>.csv``)。"""
    return bool(_TABLE_RE.match(csv_stem(path)))


def table_base(path):
    """一张表所属的**表集基准路径** (多表 + meta + txt 共用这个名字)。"""
    return split_table_name(path)[0]


def table_meta_paths(path):
    """一张表可能对应的 meta.json (顺序: 表集基准 → 自身)。"""
    out = [table_base(path) + '.meta.json']
    own = csv_stem(path) + '.meta.json'
    if own not in out:
        out.append(own)
    return out


def table_txt_path(path):
    """一张表对应的**合并 TXT 快照**路径 (多表共一份)。"""
    return table_base(path) + '.txt'


def kind_order(kinds):
    """把一组 kind 排成给人看的顺序 (已知的按 TABLE_KIND_ORDER, 其余按字母)。"""
    ks = set(k for k in kinds if k)
    out = [k for k in TABLE_KIND_ORDER if k in ks]
    out += sorted(k for k in ks if k not in TABLE_KIND_ORDER)
    return out


def table_path_for(out_base, kind):
    """dump 输出的一张表路径: ``<out_base>_<kind>.csv`` (out_base 可带 .csv)。"""
    return '%s_%s.csv' % (csv_stem(out_base), kind)


# ───────────────────────── 读表 / 找表 ─────────────────────────

def read_table_rows(path):
    """读一张文本表 → ``(rows, cols)``。

    与 inject_text_csv.py 的读表口径**完全同一份实现** (UTF-8 BOM / 容忍 CR / 忽略空行);
    行是 ``{列名: 值}`` 的 dict, **保持文件里的行序**。
    """
    with io.open(path, 'r', encoding='utf-8-sig', newline='') as f:
        rd = csv.reader(f)
        cols, rows = None, []
        for rec in rd:
            if cols is None:
                cols = [c.strip() for c in rec]
                continue
            if not rec or all(not c.strip() for c in rec):
                continue
            r = {}
            for i, c in enumerate(cols):
                v = rec[i] if i < len(rec) else ''
                if v and '\r' in v:
                    v = v.replace('\r\n', '\n').replace('\r', '\n')
                r[c] = v
            rows.append(r)
    return rows, (cols or [])


def expand_csv_inputs(specs, glob_pat=TABLE_GLOB):
    """把 ``--csv`` 的若干参数展开成**有序去重**的 CSV 路径列表。

    每个参数可以是:
      · **目录** → 读该目录下所有 ``*_text_*.csv`` (多表; 按文件名排序 ⇒ 顺序确定);
      · **文件** → 直接用 (不校验命名 ⇒ 老的大表也照旧能注入);
      · 其它     → 记 error (交给调用方报人话并退出)。

    返回 ``(paths, notes)``; notes = ``[dict(level, code, path, msg)]``:
      ``merged-table`` 给的是老的大表 / ``dir-empty`` 目录里没有多表 /
      ``dir-extra`` 目录里还留着老的大表 / ``dir-skipped`` 名字不像多表 /
      ``missing`` 路径不存在 / ``duplicate`` 同一个文件给了多次。
    """
    paths, notes, seen = [], [], set()

    def add(p):
        ap = os.path.abspath(p)
        if ap in seen:
            notes.append(dict(level='info', code='duplicate', path=ap,
                              msg='同一个文件给了多次, 只读一次: %s' % os.path.basename(ap)))
            return
        seen.add(ap)
        paths.append(ap)

    for spec in specs:
        s = str(spec).strip().strip('"')
        if not s:
            continue
        if os.path.isdir(s):
            found = sorted(glob.glob(os.path.join(s, glob_pat)))
            tbl = [p for p in found if is_table_csv(p)]
            for p in [x for x in found if not is_table_csv(x)]:
                notes.append(dict(level='warn', code='dir-skipped', path=os.path.abspath(p),
                                  msg=('文件名不像多表, 已跳过: %s (多表命名是 '
                                       '<版本>_text_<kind>.csv)' % os.path.basename(p))))
            big = [os.path.join(s, f) for f in sorted(os.listdir(s))
                   if _OLD_MERGED_RE.match(f)]
            if not tbl:
                notes.append(dict(level='error', code='dir-empty', path=os.path.abspath(s),
                                  msg=('目录里没有多表文件 (%s): %s%s'
                                       % (glob_pat, s,
                                          ('；目录里只有老格式的大表: %s'
                                           % ', '.join(os.path.basename(x) for x in big[:4]))
                                          if big else ''))))
                continue
            if big:
                notes.append(dict(level='info', code='dir-extra', path=os.path.abspath(big[0]),
                                  msg=('目录里还留着老格式的大表 (**未读入**, 多表布局下它是多余的, '
                                       '可以删掉): %s' % os.path.basename(big[0]))))
            for p in tbl:
                add(p)
            continue
        if os.path.isfile(s):
            add(s)
            if is_view_csv(s):
                notes.append(dict(level='error', code='view-only-table', path=os.path.abspath(s),
                                  msg=('这是 dump_containers.py 产出的 **view-only 表** '
                                       '(只能看/校对, 不能注入): %s' % os.path.basename(s))))
            elif not is_table_csv(s):
                notes.append(dict(level='warn', code='merged-table', path=os.path.abspath(s),
                                  msg=('这是一张**合并的大表**, 不是按 kind 拆的多表: %s'
                                       % os.path.basename(s))))
            continue
        notes.append(dict(level='error', code='missing', path=os.path.abspath(s),
                          msg='找不到: %s' % s))
    return paths, notes


def merge_table_rows(tables):
    """多张表 → 一份合并行表 (按 ``id`` 合并)。

    ``tables`` = ``[(path, rows)]``; 返回 ``(merged_rows, report)``。

    合并口径 (round37):
      · **按 id 合并**, 保持第一次出现的顺序 (LANG 在前, 与老的大表一致);
      · 同一个 id 出现在两张表里:
          - ``text_edited`` **不同** ⇒ 记进 ``report['conflicts']``
            (调用方必须报错退出 —— 这就是"改了一张、另一张没改"的歧义);
          - 相同 ⇒ 去重放行, 记进 ``report['duplicates']``;
      · 其它列 (text_zh / kind / offset …) 不一致只记 ``report['soft']`` (以第一张表为准)。
    """
    merged, by_id = [], {}
    duplicates, conflicts, soft, per_file = [], [], [], []
    for (path, rows) in tables:
        per_file.append(dict(path=os.path.abspath(path),
                             kind=(split_table_name(path)[1] or ''),
                             rows=len(rows)))
        for r in rows:
            rid = (r.get('id') or '').strip()
            if not rid:
                continue
            prev = by_id.get(rid)
            if prev is None:
                by_id[rid] = (path, r)
                merged.append(r)
                continue
            ppath, pr = prev
            a, b = pr.get('text_edited'), r.get('text_edited')
            if a != b:
                conflicts.append(dict(id=rid, path_a=os.path.abspath(ppath), edited_a=a,
                                      path_b=os.path.abspath(path), edited_b=b))
                continue
            duplicates.append(dict(id=rid, path_a=os.path.abspath(ppath),
                                   path_b=os.path.abspath(path)))
            for col in ('text_zh', 'resource', 'kind', 'entry_index', 'offset', 'len_bytes'):
                if (pr.get(col) or '') != (r.get(col) or ''):
                    soft.append(dict(id=rid, column=col, path_a=os.path.abspath(ppath),
                                     a=pr.get(col), path_b=os.path.abspath(path), b=r.get(col)))
                    break
    report = dict(files=per_file, rows_in=sum(f['rows'] for f in per_file),
                  merged=len(merged), duplicates=duplicates, conflicts=conflicts, soft=soft)
    return merged, report


def write_txt_snapshot(path, items):
    """把（多张表合并后的）文本写成**一份** TXT 快照: 每行 ``id<TAB>转义正文``。

    ★ 视图口径: ``{WRAP}`` 人工断点**渲染成真换行** (再转义成 ``\\n``) ⇒ TXT 里看到的
      就是**盘上的换行**（round36 及更早是"把 {WRAP} 删掉", 那会让视图凭空少掉换行）。
    ``items`` = ``[(id, text)]`` (顺序即写出顺序)。
    返回 ``(行数, 字符数, 中文字数)``。
    """
    n = n_chars = n_cjk = 0
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        for (rid, text) in items:
            t = WRAP_RE.sub('\n', text or '')
            f.write('%s\t%s\n' % (rid, esc_text(t)))
            n += 1
            n_chars += len(t)
            n_cjk += sum(1 for c in t if '\u4e00' <= c <= '\u9fff')
    return n, n_chars, n_cjk


def row_for_txt(r):
    """一行表记录 → TXT 快照用的正文 (与 make_build / diff 同一口径: text_edited 优先)。"""
    t = r.get('text_edited')
    if t is None or t == '':
        t = r.get('text_zh') or ''
    return t


# ═════════ ★ round39: view-only 表的识别与拒绝 (安全红线) ═════════
#   dump_containers.py 产出的「全容器文本普查」表是**只能看/校对**的:
#   那些容器的格式没被逆向, 逐字节往返做不到 ⇒ 写回盘上会毁盘。
#   两道防线:
#     ① 命名空间隔离: view 表叫 ``<版本>_view_<类别>.csv``, 与注入器自动扫描的
#        ``*_text_*.csv`` **互相排斥** ⇒ ``--csv <目录>`` 天然扫不到它们;
#     ② 表内自述: 表头带 ``injectable`` 列且值恒为 ``no`` ⇒ 就算有人**改名**
#        或**显式**把 view 表喂给注入器, 注入器也必须报错退出、一个字都不写盘。
VIEW_MARK = '_view_'
VIEW_REJECT_EXIT = 1                      # 与 EXIT_STRUCT 同一码: 结构性错误


def is_view_csv(path):
    """路径名像不像 dump_containers.py 产出的 view-only 表 (``*_view_*.csv``)。"""
    return VIEW_MARK in os.path.basename(str(path))


def view_rows(rows):
    """行表里有多少行自述 ``injectable = no`` (= view-only 表的内容)。"""
    n = 0
    for r in rows:
        v = (r.get('injectable') or '').strip().lower()
        if v in ('no', 'false', '0', '否'):
            n += 1
    return n


def table_set_summary(tables):
    """给 meta.json / build_info.json 用: 每张表的路径 / kind / 条数 / 字节数 / sha256。

    ``tables`` = ``[(path, rows)]``。
    """
    files = []
    for (path, rows) in tables:
        _base, kind = split_table_name(path)
        p = os.path.abspath(path)
        files.append(dict(path=p.replace('\\', '/'), name=os.path.basename(p),
                          kind=kind or '', rows=len(rows), bytes=os.path.getsize(p),
                          sha256=sha256_file(p)))
    return dict(files=files,
                kinds=kind_order([f['kind'] for f in files]),
                tables=len(files), rows_total=sum(f['rows'] for f in files))
# -*- coding: utf-8 -*-
# ═══════════════════════════════════════════════════════════════════════════════
# ★ 旧单字节码 / 解码闸门 自检 (task: textmig; 见 docs/TEXT_MIGRATION_0xBA.md)
# ═══════════════════════════════════════════════════════════════════════════════
#  背景 (已确诊的 bug): 引擎的 DBCS 判据是 ELF 里一条无符号区间比较
#      `0xA1 <= byte < GATE`   (4 站点 sltiu: 0x416EE8 / 0x417160 / 0x41751C / 0x5656A4)
#  闸门从 0xB1 抬到 0xBA 以后, `0xB1..0xB9` 这些**原本是单字节字**的字节变成对偶前导:
#  文本里每个遗留的裸字节都会吃掉后一个字节 ⇒ 乱码 + 可能内存损坏 (用户实机崩溃)。
#
#  ⇒ 回写工具链**必须**在写盘前自检: "本盘闸门之下的 `0xB1..gate-1` 裸字节 = 0 处"。
#    本段提供的 API **默认被 inject_text_csv.py 调用** (闸门从目标盘的 ELF 实测读出,
#    所以对 gate=0xB1 的老盘是**零行为变化** —— 窗口为空)。
LEGACY_GATE_LO = 0xB1           # 历史上第一个"曾是单字节码"的字节 (= 第一代闸门)
LEGACY_GATE_LO_OLD = 0xA1       # 老 lead 区间下界 (不参与本自检)
ELF_GATE_SITES = (0x416EE8, 0x417160, 0x41751C, 0x5656A4)     # VA
ELF_ISO_BASE, ELF_VA_BASE = 0x93880, 0x100000                  # VA - 0x6C780 = ISO off
GATE_PAIRS_FILE = os.path.join(HERE, 'gate_pairs.json')         # 闸门对偶码登记表 (见下)


class LegacyCodeError(CharsetError):
    """文本里还有"旧闸门之下的裸单字节码" —— 抬过闸门的盘上会吞字/乱码, 拒绝写盘。"""


def read_decode_gate(iso):
    """从盘上 ELF 的 4 个站点读出**本盘的解码闸门** (立即数)。

    4 处必须一致 (它们是同一个谓词的 4 个副本); 不一致 ⇒ 抛异常 (盘已坏或读到别的盘)。
    """
    vals = []
    for va in ELF_GATE_SITES:
        off = ELF_ISO_BASE + va - ELF_VA_BASE
        vals.append(struct.unpack_from('<I', iso.mm, off)[0] & 0xFFFF)
    if len(set(vals)) != 1:
        raise LegacyCodeError('本盘 ELF 的 4 个 gate 站点立即数不一致: %s '
                              '(盘已损坏或不是预期版本)' % [hex(v) for v in vals])
    return vals[0]


def load_gate_pairs(path=None):
    """读**闸门对偶码登记表** ``tools/text_csv/gate_pairs.json`` → ``{(b1,b2): 字}``。

    为什么需要它: 迁移会用到一些"引擎已可寻址、但 charset JSON 还没来得及登记"的对偶码
    (例: GR_TXMIG 借了 slot 2345..2349 给 按/时/小/击/✕)。charset 是**几何路的受保护路径**,
    本工具链不写它 ⇒ 用一个**独立的登记表**让自检与编码先跑起来。
    登记表内容必须由 charset 所有者最终并入 charset JSON (两边不一致时以 charset 为准)。
    文件不存在 ⇒ 返回空表 (对 gate=0xB1 的老盘毫无影响)。
    """
    p = path or GATE_PAIRS_FILE
    if not p or not os.path.isfile(p):
        return {}
    try:
        j = json.load(open(p, encoding='utf-8'))
    except Exception as e:                                          # noqa: BLE001
        print('[warn] %s 解析失败: %s (忽略)' % (p, e))
        return {}
    out = {}
    for ch, pr in (j.get('pairs') or {}).items():
        out[(int(pr[0]), int(pr[1]))] = ch
    return out


def legacy_window(gate):
    """本自检关心的字节窗口 = ``[0xB1, gate)`` (闸门 ≤ 0xB1 ⇒ 空窗口 = 零行为变化)。"""
    return range(LEGACY_GATE_LO, max(LEGACY_GATE_LO, gate))


def charset_gate_warnings(cs, gate, extra_pairs_ch=None):
    """charset ``codes`` 里落在 ``[0xA1, gate)`` 的字 —— 它们**不能**再按单字节码写出去。

    这是一个"表级"预警 (不阻断): 这些字以后必须走对偶码, charset 所有者应把它们从
    ``codes`` 移进 ``pair_of``。``extra_pairs_ch`` = ``{字: (b1,b2)}`` (gate_pairs 登记表):
    一起报才不会与"其实编得出"矛盾。
    """
    out = []
    ex = extra_pairs_ch or {}
    for ch, b in cs.enc_single.items():
        if LEAD_LO <= b < gate:
            pr = cs.enc_pair.get(ch) or ex.get(ch)
            src = ('charset.pair_of' if cs.enc_pair.get(ch) else
                   ('gate_pairs.json' if ex.get(ch) else None))
            out.append((ch, b, tuple(pr) if pr else None, src))
    return out


def scan_legacy_residue(data, gate, pair_table):
    """按**本盘闸门**走一遍, 找 ``[0xB1, gate)`` 里"不是合法对偶 lead"的裸字节。

    pair_table = ``{(b1,b2): 字}`` (charset.pair_of ∪ gate_pairs)。
    → ``[(偏移, 字节, trail|None, 该字节在 charset.codes 里对应的字|None)]``
    """
    out, i, n = [], 0, len(data)
    while i < n:
        b = data[i]
        if b < 0x80:
            i += 1
            continue
        if LEAD_LO <= b < LEGACY_GATE_LO:        # 老 lead 区间: 历史行为, 不归本自检管
            i += 2 if i + 1 < n else 1
            continue
        if LEGACY_GATE_LO <= b < gate:           # ★ 检查窗口
            t = data[i + 1] if i + 1 < n else None
            if t is not None and (b, t) in pair_table:
                i += 2
                continue
            out.append((i, b, t))
            i += 1
            continue
        i += 1
    return out


def assert_no_legacy_residue(data, tag, gate, pair_table, codes=None, where='载荷'):
    """★ 硬自检: 该区段里不许有"旧闸门之下的裸单字节码"。有 ⇒ 抛 LegacyCodeError。"""
    hits = scan_legacy_residue(data, gate, pair_table)
    if not hits:
        return 0
    by = {}
    for (_o, b, _t) in hits:
        by[b] = by.get(b, 0) + 1
    (o0, b0, t0) = hits[0]
    ch = (codes or {}).get(b0)
    raise LegacyCodeError(
        '!! %s 的%s里还有 **%d 处遗留的旧单字节码** —— 本盘 ELF 闸门 = 0x%02X,\n'
        '   而 `0xB1..0x%02X` 在这个闸门下已经是**对偶前导**: 裸字节会吃掉后一个字节,\n'
        '   整串重配对 ⇒ 界面乱码、并可能内存损坏 (实机崩溃)。拒绝写盘。\n'
        '   逐码: %s\n'
        '   首例 @0x%X: 0x%02X%s%s\n'
        '   怎么办: ① 先在**源盘**上跑全量迁移\n'
        '              python work/tools/migrate_legacy.py <源盘.iso> <产物.iso> --reserve-slots\n'
        '            (它会把 0xB1..gate-1 改写成对应字的对偶码, 并把 ELF 闸门一起抬到位);\n'
        '           ② 若迁移借用的对偶码还没进 charset JSON, 把它们登记到\n'
        '              tools/text_csv/gate_pairs.json (自检与编码都会读它)。'
        % (tag, where, len(hits), gate, gate - 1,
           ' '.join('0x%02X%s:%d' % (k, ('(%s)' % codes[k]) if codes and k in codes else '', v)
                    for k, v in sorted(by.items())),
           o0, b0, ('%02X' % t0) if t0 is not None else '(区段末尾, 无 trail)',
           (' = 字 %r 的旧单字节码' % ch) if ch else ''))


def legacy_selfcheck_container(c, blob, gate, extra_pairs=None, verbose=True):
    """对**一个容器的新 blob** 做闸门自检 (正文载荷 + SFXML 标题属性)。

    与写盘口径一致: LANG 只查条目 payload, SFXML 查 `<text>` 正文 + `name=` 属性
    (结构区是数字字段, 引擎不当文本读)。
    → dict(n=残留处数, pairs=检出的合法对偶 lead 计数, warnings=charset 表级预警)
    """
    pair_table = dict(c.cs.pair_of)
    pair_table.update(extra_pairs or {})
    ch_pairs = {ch: tuple(p) for ch, p in c.cs.enc_pair.items()}
    ch_pairs.update({ch: tuple(p) for p, ch in (extra_pairs or {}).items()})
    n = 0
    for (loc, pay) in c.iter_payloads(blob):
        n += assert_no_legacy_residue(pay, '%s %s' % (c.tag, loc), gate, pair_table,
                                      c.cs.codes, where='条目载荷')
    for (loc, val) in c.iter_attrs(blob):
        n += assert_no_legacy_residue(val, '%s %s' % (c.tag, loc), gate, pair_table,
                                      c.cs.codes, where='标题属性')
    leads = {}
    for (loc, pay) in c.iter_payloads(blob):
        i, m = 0, len(pay)
        while i < m:
            b = pay[i]
            if b < 0x80:
                i += 1
            elif LEAD_LO <= b < gate:
                if i + 1 < m and (b, pay[i + 1]) in pair_table:
                    leads[b] = leads.get(b, 0) + 1
                    i += 2
                else:
                    i += 2 if LEGACY_GATE_LO <= b else 1
            else:
                i += 1
    if verbose and leads:
        print('   [gate] %s: 合法对偶 lead 计数 %s'
              % (c.tag, ' '.join('0x%02X:%d' % (k, v) for k, v in sorted(leads.items()))))
    return dict(n=n, pairs=leads, warnings=charset_gate_warnings(c.cs, gate, ch_pairs))
