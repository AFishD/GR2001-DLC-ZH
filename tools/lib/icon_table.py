# -*- coding: utf-8 -*-
r"""icon_table.py — ★ 手柄按键图标码总表 (round42)

本模块回答一个问题: **引擎的文本里到底有几个「手柄图标码」, 每个是什么键。**

═══════════════════════════════════════════════════════════════════════════
一、结论 (逆向 + 实机双重证据)
═══════════════════════════════════════════════════════════════════════════

  **引擎的「文本图标码」只有 2 个: `0xB1` 与 `0xB5`。**
  它们不是"某个表里的某一项", 而是 **DrawString v1 里写死的两个 if** ——
  引擎里**不存在**更大的"文本图标码表", 所以码的个数**不可能**超过 2。

  | 盘上字节 | CSV 标记        | 是哪个键 | 证据 |
  |---|---|---|---|
  | `0xB1` | `{{BTN:E0B1}}` | △ 三角键 | ELF 0x219C70/0x219C80 硬编码 UV (25,198)-(45,218) → 图标图集里那个格子是绿色三角 |
  | `0xB5` | `{{BTN:E0B5}}` | ✕ 叉键   | ELF 0x219C4C/0x219C5C 硬编码 UV (1,198)-(21,218)  → 图标图集里那个格子是蓝红叉 |

  其余高位字节**都不是图标**:
    · `0xE7` / `0xF1` = Latin-1 的 **ç / ñ** 两个**普通字母**
      (它们出现在语言选择菜单的 `Français` / `Español` 里, 吃字库、走正常字形路径);
    · 本站其余 `0x80..0xFF` 的字节**全被中文字符集占用** (108 个单字节码 + 16 个对偶 lead),
      引擎对它们一律按"汉字"画 ⇒ 它们**不可能是**图标码。

═══════════════════════════════════════════════════════════════════════════
二、ELF 证据 (SLUS_206.13, 全部地址为虚拟地址)
═══════════════════════════════════════════════════════════════════════════

  ① `RSFontMgr::DrawString` v1 @0x219A70 (912 B) 是**全 ELF 唯一带字符循环的绘制入口**
     (符号表: `DrawString__9RSFontMgrFPCcffRC7RSColorP6RSFontPCiPCii`;
      另两个 DrawString v2/v3 只是坐标换算 + 委托 v1)。
     它的取字符循环里对**字符值**只有 3 个特判:

       0x219BE8  addiu $v1, $zero, 32      ; c == 0x20 (空格) → 另行处理
       0x219C08  addiu $v1, $zero, -75     ; c == 0xB5  ┐ 图标路径
       0x219C0C  beq   $a1, $v1, 0x219C44  ;             │
       0x219C14  addiu $v1, $zero, -79     ; c == 0xB1  │
       0x219C18  beq   $a1, $v1, 0x219C40  ;             ┘
       0x219C30  jal   ComputeCharTextureCoords (0x21ADE0)   ; ← 其余字符一律走字形路径

     同一函数里同样的比较共 **6 处** (0x219C08/0x219C10/0x219C94/0x219CAC/0x219D24/0x219D38),
     全部只涉及 `0xB5` / `0xB1` 两个值 —— **没有第三个**。
     (全 ELF 穷举 `addiu rt,$zero,imm` 且 imm∈0xFF80..0xFFFF 的结果里,
      落在字体/文本链 0x219xxx~0x21Axxx 的也只有这两组。)

  ② 图标的 UV 是**写死的常量** (不是查表):

       0x219C4C  lui $v1, 0x3F80 → 1.0     ┐
       0x219C54  lui $v1, 0x4346 → 198.0   │  0xB5 → (u 1..21,  v 198..218)
       0x219C5C  lui $v1, 0x41A8 → 21.0    │
       0x219C64  lui $v1, 0x435A → 218.0   ┘
       0x219C70  lui $v1, 0x41C8 → 25.0    ┐
       0x219C78  lui $v1, 0x4346 → 198.0   │  0xB1 → (u 25..45, v 198..218)
       0x219C80  lui $v1, 0x4234 → 45.0    │
       0x219C88  lui $v1, 0x435A → 218.0   ┘

  ③ 图标**不吃字库**: `RSFontMgr` 里有**两个** UISpriteModel
     (实现在 `RSFontMgr::ReadResourceFile` @0x219380 尾部):

       0x2197B8..0x2197C8   model[+40] 初始化 (容量 = 108)   ← 文字
       0x2197CC..0x2197DC   model[+76] 初始化 (容量 = **2**) ← 图标
       0x2197E8..0x2197F8   SetTexture(model[+40], GetTexture(字体资源))
       0x219800/0x21980C   lui $v0,0x0058 ; addiu $a1,$v0,-31152  ⇒ a1 = 0x578650
       0x21981C..0x219828   SetTexture(model[+76], GetTexture("pda_counterparts.rsb"))

     ⇒ 图标走的是**另一张纹理** (`pda_counterparts.rsb`, GR.IMG #861 / MENU.IMG#3 COMMON.PAK
       里也有同名 256x256 记录), 所以字库覆盖预检**不该**、也**不会**管它。

  ④ `AddOneWord` @0x219F50 的第 6 个参数 `bool` 就是"这是图标吗":
     `t0 != 0` ⇒ 走 model[+76] (0x21A078 分支), `t0 == 0` ⇒ 走 model[+40]。
     DrawString v1 只在 0xB5/0xB1 那两个分支里给它传 1 (0x219D78 `addiu $t0,$zero,1`)。

═══════════════════════════════════════════════════════════════════════════
三、玩家在界面上看到的**其它**手柄图标 (△○✕□ / L1R1 / 十字键 …) 从哪来?
═══════════════════════════════════════════════════════════════════════════

  它们**不是文本码**, 而是 UI 的「快捷键提示」系统画的, 按**动作索引**取 UV:

     `kShortcutDefaultTC(unsigned int index, int)` @0x2BEFE0 (RSVector4 返回)
       = 一张 switch 表: index 0..6 / 23..31 各自对应一组 UV 常量,
         例如  26 → (0,178)-(20,198)   27 → (85,178)-(120,198)
               29 → (21,178)-(41,198) 30 → (42,178)-(62,198) 31 → (63,178)-(83,198)
     这些是**动作/按钮 ID**, 与文本字节**没有**任何映射关系 ⇒
       · dump 文本永远看不到它们;
       · 也不能用 `{{BTN:xxxx}}` 去调它们。

  ⇒ 用户看到的「四个面键 + 至少一个左右键」= 这套 shortcut 图标 (或其图集),
    **不是**文本图标码。文本图标码确实只有 2 个。

═══════════════════════════════════════════════════════════════════════════
四、已知限制 (诚实挂账)
═══════════════════════════════════════════════════════════════════════════

  1. `0xB1`/`0xB5` → △/✕ 的对应关系来自"引擎 UV ↔ 图标图集内容"的比对,
     并已由实机截图复核 (见 docs/REPORT_icon_codes.md §实机判定)。
  2. shortcut 图标那张表的 **index → 动作名** 映射没有逆向 (需要动作表/UI 侧取证),
     本模块只如实登记"存在这张表、它是 UI 侧、与文本码无关"。
  3. 若**将来**把某个图标字节从字符集里释放出来 (不再当汉字), 它**也不会**自动变成图标 ——
     引擎只认 0xB1/0xB5 这两个值, 别的字节一律走字形路径。**这一点必须记住**:
     「空出来的字节」≠「新的图标码」。
"""
import re

# ═════════════════════════ 常量 ═════════════════════════

PUA_BASE = 0xE000                       # 私有区回落基址 (与 tcslib.Charset.PUA_BASE 一致)
BTN_PUA_LO, BTN_PUA_HI = 0xE080, 0xE0FF  # 合法标记码位区间 (与 tcslib.BTN_LO/BTN_HI 一致)
MARK_FMT = '{{BTN:%04X}}'               # 标记格式 (round33 起固定, **不变**)
MARK_RE = re.compile(r'\{\{BTN:([0-9A-Fa-f]{4})\}\}', re.I)
BYTE_LO, BYTE_HI = 0xB1, 0xFF           # 「可能被当图标」的字节区间下界 = 0xB1
#   ★ 为什么下界是 0xB1 而不是 0x80:
#     0xA1..0xB0 是引擎的 DBCS **lead 区间** (ELF 四处 `sltiu …,0xB1` 实测),
#     图标码写在那里会被当成对偶首字节吞掉后一个字。0x80..0xA0 在本盘是单字节汉字。

# 文本图标码 (引擎写死的两个) -------------------------------------------------
ICON_CODES = {
    0xB1: dict(
        byte=0xB1, pua=0xE0B1, key='triangle', name='△ 三角键', short='△',
        uv=(25, 198, 45, 218),
        elf_evidence='DrawString v1 @0x219C70/0x219C80: UV=(25,198)-(45,218)',
        verified=True,
        in_game='GR_ZH96_icon 实机 f26200: 正文 "1={{BTN:E0B1}}图" 处画出**绿色三角键帽**',
        note='语言表里用它做「返回/退出」类提示; 图标图集那一格是绿色三角'),
    0xB5: dict(
        byte=0xB5, pua=0xE0B5, key='cross', name='✕ 叉键', short='✕',
        uv=(1, 198, 21, 218),
        elf_evidence='DrawString v1 @0x219C4C/0x219C5C: UV=(1,198)-(21,218)',
        verified=True,
        in_game='GR_ZH96_icon 实机 f26200: 正文 "2={{BTN:E0B5}}图" 处画出**蓝/粉叉键帽**',
        note='英文原文 "Use the [0xB5] button to add a waypoint" ⇒ 确认/接受类; '
             '图标图集那一格是蓝红叉'),
}

# **不是**图标的字节 (round33 一度被当成图标; round42 定性; round43 已进字符集) ------
NOT_ICON_CODES = {
    0xE7: dict(byte=0xE7, pua=0xE0E7, key='latin-1 c-cedilla', name='ç (拉丁小写 c 带软音符)',
               latin1='ç', charset_char='ç', in_charset=True, kind='latin1', evidence='出现于 LANG:G059.I028 "Français"; '
                                     'FT 记录 idx=199 在图集上有 ç 的字形; '
                                     '实机 f26200 画出的是小写字母 ç (不是图标)'),
    0xF1: dict(byte=0xF1, pua=0xE0F1, key='latin-1 n-tilde', name='ñ (拉丁小写 n 带波浪号)',
               latin1='ñ', charset_char='ñ', in_charset=True, kind='latin1', evidence='出现于 LANG:G059.I031 "Español"; '
                                    'FT 记录 idx=209 在图集上有 ñ 的字形; '
                                    '实机 f26200 画出的是小写字母 ñ (不是图标)'),
}
#   ★ round43: 这两个字节**已经在 charset JSON 的 `codes` 里** (kind = latin1) ⇒
#     · is_icon() 对它们恒为 **False** (它们从来就不是图标码, 只是当年被误写成 {{BTN:…}});
#     · candidate_bytes() 不再把它们算成"空字节" (已被字符集占用);
#     · 老 CSV 的 `{{BTN:E0E7}}` / `{{BTN:E0F1}}` 仍被注入器接受 (tcslib 的历史别名路径),
#       与直接写 ç / ñ **注入出同一份盘**。
LATIN1_ALIAS_BYTES = tuple(sorted(NOT_ICON_CODES))      # (0xE7, 0xF1) —— 与 tcslib 同一口径

# UI 侧「快捷键图标」系统 (与文本码无关, 只作登记) ----------------------------
SHORTCUT_SYSTEM = dict(
    func='kShortcutDefaultTC(unsigned int index, int)',
    va=0x2BEFE0,
    indices=(0, 1, 2, 3, 4, 5, 6, 23, 24, 25, 26, 27, 28, 29, 30, 31),
    texture='pda_counterparts.rsb (GR.IMG #861; MENU.IMG#3 COMMON.PAK 内另有同名 256x256 记录)',
    note=('玩家在按钮提示栏/快捷键栏看到的手柄图标 (含 △○✕□ 与左右方向) 由这套系统按'
          '**动作索引**绘制, 与文本字节没有映射关系 ⇒ 文本 dump 里看不到, '
          '也不能用 {{BTN:xxxx}} 调它。'),
)

ENGINE_ICON_BYTES = tuple(sorted(ICON_CODES))          # (0xB1, 0xB5)
MARK_RE_BYTES = tuple(0xE000 + b for b in ENGINE_ICON_BYTES)


# ═════════════════════════ 查询接口 ═════════════════════════

def code_of(x):
    """把 `0xB1` / `U+E0B1` / `'{{BTN:E0B1}}'` / `'\ue0b1'` / `'B1'` 统一成**私有区码位** int。

    认不出来返回 None (不抛异常 —— 这是查询接口, 不是校验接口)。
    """
    if isinstance(x, int):
        if 0 <= x <= 0xFF:
            return PUA_BASE + x
        if BTN_PUA_LO <= x <= BTN_PUA_HI:
            return x
        return None
    if isinstance(x, str):
        m = MARK_RE.fullmatch(x)
        if m:
            return int(m.group(1), 16)
        if len(x) == 1:
            return ord(x) if BTN_PUA_LO <= ord(x) <= BTN_PUA_HI else None
        try:
            v = int(x, 16)
        except ValueError:
            return None
        return (PUA_BASE + v) if v <= 0xFF else (v if BTN_PUA_LO <= v <= BTN_PUA_HI else None)
    return None


BTN_PUA_LO, BTN_PUA_HI = 0xE080, 0xE0FF        # 与 tcslib.BTN_LO/BTN_HI 一致 (见文件头常量区)


def byte_of(x):
    """同 :func:`code_of`, 但返回**字节值** (0x00..0xFF)。"""
    c = code_of(x)
    return None if c is None else c - PUA_BASE


def is_icon(x):
    """这个码位/字节是不是**引擎认的文本图标码** (只有 0xB1/0xB5)。"""
    b = byte_of(x)
    return b in ICON_CODES


def is_known_not_icon(x):
    """是不是「未映射字节, 但**不是**图标」的那两个 (0xE7/0xF1 = ç/ñ)。"""
    b = byte_of(x)
    return b in NOT_ICON_CODES


def icon_info(x):
    """码 → 图标记录 dict (含 key/name/uv/verified/note); 不是图标码返回 None。"""
    b = byte_of(x)
    return ICON_CODES.get(b)


def icon_key(x):
    """码 → 英文键名 ('triangle' / 'cross'); 不是图标码返回 None。"""
    r = icon_info(x)
    return r['key'] if r else None


def icon_name(x):
    """码 → 人话键名 ('△ 三角键' / '✕ 叉键'); 不是图标码返回 None。"""
    r = icon_info(x)
    return r['name'] if r else None


def all_icons():
    """全部**引擎认的**文本图标码 (按字节升序) 的记录列表。"""
    return [ICON_CODES[b] for b in sorted(ICON_CODES)]


def engine_icon_bytes():
    """引擎认的文本图标码字节元组 = (0xB1, 0xB5)。"""
    return ENGINE_ICON_BYTES


# ═════════════════════════ 候选枚举 (工具链的"全集"口径) ═════════════════════════

def candidate_bytes(charset=None, lo=BYTE_LO, hi=BYTE_HI):
    """`BYTE_LO..BYTE_HI` 里**没被字符集占用**的字节 = 候选图标字节 (完整枚举)。

    ★ 这就是 round42 修掉的"缺漏": 以前的判据是「文本里出现过未映射字节才算图标」,
      于是"引擎认、但当前译文没用到"的码完全看不见。现在改为**枚举字节空间**:

        candidate = [lo..hi] - 单字节码 - 对偶 lead

      · charset = tcslib.Charset() (不传就只按区间返回, 不做字符集过滤);
      · 返回**字节**列表 (升序)。
    """
    bs = list(range(lo, hi + 1))
    if charset is None:
        return bs
    codes = set(getattr(charset, 'codes', {}) or {})
    leads = set(b1 for (b1, _b2) in (getattr(charset, 'enc_pair', {}) or {}).values())
    return [b for b in bs if b not in codes and b not in leads]


def describe(b, charset=None):
    """给人看的一行: 这个字节是什么 (图标 / 拉丁字母 / 汉字 / 空着)。"""
    r = ICON_CODES.get(b)
    if r:
        return '★图标码 0x%02X = %s (%s)%s' % (
            b, r['name'], r['key'], '' if r['verified'] else ' [未实机验证]')
    r = NOT_ICON_CODES.get(b)
    if r:
        return ('不是图标 0x%02X = %s (%s); ★ round43 起它已在字符集里 (kind=%s, 单字节码) '
                '⇒ 引擎按**普通字母**画, 用不着 {{BTN:…}} 标记'
                % (b, r['name'], r['evidence'], r.get('kind', 'latin1')))
    if charset is not None:
        ch = (getattr(charset, 'codes', {}) or {}).get(b)
        if ch:
            zh = '汉字' if '\u4e00' <= ch <= '\u9fff' else '拉丁字母'
            return '%s 0x%02X = 「%s」(被字符集占用 ⇒ 不可能是图标)' % (zh, b, ch)
        leads = set(b1 for (b1, _b2) in (getattr(charset, 'enc_pair', {}) or {}).values())
        if b in leads:
            return '对偶 lead 0x%02X (落在引擎 lead 区间 ⇒ 不能当图标码)' % b
    return '空字节 0x%02X (引擎不认它当图标 ⇒ 写了会走字形路径)' % b


def summary_lines(charset=None):
    """给 dump/报告用的多行人话结论 (与 dump_font / REPORT 共用同一口径)。"""
    out = []
    out.append('引擎认的**文本图标码** = %d 个: %s'
               % (len(ICON_CODES),
                  '  '.join('%s=0x%02X(%s)' % (MARK_FMT % (PUA_BASE + b), b,
                                               ICON_CODES[b]['name'])
                            for b in sorted(ICON_CODES))))
    out.append('  ★ 它们不是"表里的一项", 而是 DrawString v1 里写死的两个 if ⇒ '
               '码的个数上限就是 2, 不存在"没找到的更多图标码"。')
    if charset is not None:
        cands = candidate_bytes(charset)
        out.append('本盘 %02X..%02X 里**没被字符集占用**的字节 %d 个: %s'
                   % (BYTE_LO, BYTE_HI, len(cands),
                      ' '.join('%02X' % b for b in cands) or '无'))
        for b in cands:
            out.append('  %s' % describe(b, charset))
    if NOT_ICON_CODES:
        out.append('曾误当图标、其实是**拉丁字母**的字节 (round43 起已在字符集里, 是普通字母): %s'
                   % '  '.join('0x%02X=%s' % (b, NOT_ICON_CODES[b]['latin1'])
                               for b in sorted(NOT_ICON_CODES)))
    out.append('玩家看到的其它手柄图标 (△○✕□/左右键…) 来自 UI 快捷键系统 %s'
               % SHORTCUT_SYSTEM['func'])
    return out


# ═════════════════════════ 自检 ═════════════════════════

def selfcheck(charset=None):
    """本模块的自检 (不需要 ISO; charset 可选, 传了就顺带验候选口径)。

    返回 ``(ok, 明细行列表)`` —— 与 tcslib 的 selfcheck_* 同一形状, 便于 dump 打印。
    """
    out, ok = [], True

    def chk(cond, msg):
        nonlocal ok
        ok = ok and bool(cond)
        out.append('%s %s' % ('[ok]' if cond else '[!!]', msg))

    chk(len(ICON_CODES) == 2 and set(ICON_CODES) == {0xB1, 0xB5},
        '引擎认的文本图标码 = 0xB1/0xB5 共 2 个 (DrawString v1 写死的两个 if)')
    chk(all(ICON_CODES[b]['verified'] for b in ICON_CODES),
        '两个码都有实机/图集证据 (verified=True)')
    for b in range(0x80, 0x100):
        if is_icon(b) != (b in ICON_CODES):
            ok = False
            out.append('[!!] is_icon(0x%02X) 与表不一致' % b)
    chk(ok, '0x80..0xFF 穷举: is_icon() 为真的只有表里那两个')
    for x, want in ((0xB1, 0xE0B1), ('{{BTN:E0B1}}', 0xE0B1), ('\ue0b5', 0xE0B5),
                    ('E0B5', 0xE0B5), (0xB5, 0xE0B5)):
        chk(code_of(x) == want, 'code_of(%r) = U+%04X' % (x, want))
    chk(code_of('abc') is None, "code_of('abc') = None (不抛异常)")
    chk(code_of('{{BTN:1234}}') == 0x1234 and icon_info('{{BTN:1234}}') is None,
        '语法合法但不是图标码的 {{BTN:1234}} ⇒ icon_info=None (格式合法 ≠ 引擎认得)')
    chk(NOT_ICON_CODES.get(0xE7, {}).get('latin1') == 'ç'
        and NOT_ICON_CODES.get(0xF1, {}).get('latin1') == 'ñ',
        '0xE7/0xF1 如实登记为 Latin-1 的 ç / ñ (**不是**图标)')
    # ★ round43 硬要求: 这两个字节**必须** is_icon()=False (它们已在 latin1 类里, 是普通字母)
    for b, ch in ((0xE7, 'ç'), (0xF1, 'ñ')):
        chk(is_icon(b) is False, 'is_icon(0x%02X) = False —— %s 是拉丁字母, 不是图标码' % (b, ch))
        chk(is_known_not_icon(b) is True,
            'is_known_not_icon(0x%02X) = True —— 它登记在 latin1 类里' % b)
        chk(NOT_ICON_CODES[b].get('in_charset') is True
            and NOT_ICON_CODES[b].get('charset_char') == ch,
            '0x%02X 登记为「已在字符集里」(round43: codes[%r] = 0x%02X)' % (b, ch, b))
        chk(all(not is_icon(x) for x in (b, 0xE000 + b, '{{BTN:%04X}}' % (0xE000 + b))),
            'is_icon() 对 %r / %r / %r 三种写法都是 False'
            % (b, 0xE000 + b, '{{BTN:%04X}}' % (0xE000 + b)))
    if charset is not None:
        # 与字符集交叉验证: 这两个字节现在**已被字符集占用** ⇒ 天然不可能是"空字节/图标码"
        for b, ch in ((0xE7, 'ç'), (0xF1, 'ñ')):
            chk((getattr(charset, 'codes', {}) or {}).get(b) == ch,
                'charset.codes[0x%02X] = %r (charset JSON 里确实有它)' % (b, ch))
    chk(MARK_FMT == '{{BTN:%04X}}' and BTN_PUA_LO == 0xE080 and BTN_PUA_HI == 0xE0FF,
        '标记格式与区间与 round33 完全一致 (格式零变化)')
    if charset is not None:
        cands = candidate_bytes(charset)
        chk(set(ENGINE_ICON_BYTES) <= set(cands),
            '候选枚举包含全部引擎图标码 (%s ⊆ %s)'
            % (' '.join('%02X' % b for b in ENGINE_ICON_BYTES),
               ' '.join('%02X' % b for b in cands)))
        chk(len(cands) == len(set(cands)), '候选枚举无重复')
        for b in cands:
            chk(describe(b, charset) != '', 'describe(0x%02X) 有人话输出' % b)
    return ok, out


if __name__ == '__main__':
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                            # noqa: BLE001
        pass
    cs = None
    try:                                    # 有 tcslib 就顺带验「本盘候选枚举」
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import tcslib                                            # noqa: PLC0415
        cs = tcslib.Charset()
    except Exception as e:                                       # noqa: BLE001
        print('[note] 没有加载 charset (只跑静态自检): %s' % e)
    o, lines = selfcheck(cs)
    for ln in lines:
        print(ln)
    print()
    for ln in summary_lines(cs):
        print(ln)
    print()
    print('icon_table 自检: %s' % ('全部通过 ✓' if o else '**有失败** ✗'))
    sys.exit(0 if o else 1)

