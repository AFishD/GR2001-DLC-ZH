# -*- coding: utf-8 -*-
r"""iso_img_scan.py —— GR.IMG 容器全量结构分析（《幽灵行动：丛林风暴》PS2 / SLUS-20820）。

用途（默认全只读）：
  1) ISO 内 GR.IMG 的 12×u32 容器头字段语义（逐项用盘上数据自证）；
  2) 3111 条目表 12×u32 每字段语义（名字偏移链 / 名字排序链 / 压缩标志 / stored / real /
     off / 哈希桶链表），以及名字区 / 哈希表 / 条目间 slack / 文件尾空间；
  3) 逐条展开 payload（含「clen==rlen ⇒ 原样块」的 LZO 混合帧规则），统计可打印 ASCII 串；
  4) 产出机器可读清单 assets/manifests/gr_img_index.json 与 work/ 下明细。

用法：
  python tools/analysis/iso_img_scan.py                 # 全量扫描 + 写清单
  python tools/analysis/iso_img_scan.py --quick         # 只做容器结构（不展开载荷）
  python tools/analysis/iso_img_scan.py --limit 50      # 只处理前 N 条（调试）
  python tools/analysis/iso_img_scan.py --header        # 只打印容器头/条目表结构
  python tools/analysis/iso_img_scan.py --help

证据口径（本文档数字全部由本脚本现场计算）：
  * 容器头 +0x00 = 容器总字节数（== ISO9660 root dir 登记的 GR.IMG;1 大小）
  * +0x04 = 名字区结束偏移；+0x08 = 扇区大小 2048；+0x0C = 条目表结束偏移(=+0x830+N*48)
  * +0x10 = 名字区起始；+0x14 = 载荷区起始(== 第一条目 off)；+0x18 = 1 / +0x1C..+0x2C 见报告
  * +0x20 = 哈希桶表起始(4096×u32，0xFFFFFFFF=空，值=条目号+1)
  * 条目 u32[0]=名字偏移 u32[1]=名字排序链 next(条目号+1, 0=尾)
    u32[4]=压缩标志 u32[5]=1 u32[6]=stored u32[7]=real u32[8]=条目内偏移
    u32[9]/u32[10]=同名资源跨容器/跨版本恒定的名字键（算法未定，见报告）
    u32[11]=哈希桶链 next(条目号+1, 0=尾)
  * LZO 条目 = 顺序子流 {u32 clen}{u32 rlen}{payload}；clen==rlen 时该块为**原样未压缩块**
    （本盘 355 个此类块；缺失该规则会把 107 条误判为「不可解」）。
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
import dlclib  # noqa: E402

SEC = 2048
PRINT_RE = re.compile(rb'[\x20-\x7e]{4,}')

# 扩展名 → 资源类别（「实证」= 已解析/已看清结构；「推测」= 按命名与同类类比）
EXT_CLASS = {
    # ---- 文本 / XML 类（实证：payload 以 '<XxxFile>' 开头，见 --payloads 输出）----
    'ATR': ('text_xml', 'ActorFile XML：角色(AI)定义，含 <ActorName> 等显示名'),
    'MIS': ('text_xml', 'MissionFile XML：任务定义/简报/目标，含 NameId→LANG 引用'),
    'GTF': ('text_xml', 'GameTypeFile XML：多人模式定义，含 Name/Comment 与 NameId/CommentId'),
    'GUN': ('text_xml', 'GunFile XML：武器定义，含 NameToken(→EN_STRINGS.TXT)'),
    'KIT': ('text_xml', 'KitFile XML：装备包定义（纯文件引用）'),
    'TOE': ('text_xml', 'TOEFile XML：编制表'),
    'PRJ': ('text_xml', 'ProjectileFile XML：弹道/抛射物定义'),
    'VCL': ('text_xml', 'VehicleFile XML：载具定义'),
    'ITM': ('text_xml', 'HandHeldItemFile XML：手持道具定义'),
    'ENV': ('text_xml', 'EnvironmentFile XML：环境定义'),
    'CSF': ('text_xml', 'CampaignStateFile XML：战役存档模板'),
    'PSF': ('text_xml', 'ProfileStateFile XML：存档模板'),
    'KIL': ('text_xml', 'KitRestriction XML：装备限制表'),
    'XML': ('text_xml', '通用 XML：CAMPAIGN/OPTIONS/UNLOCKED_*/SPECIAL_FEATURE 等'),
    'LNG': ('binary', '局部化采样表?（LZO 多子流二进制；未解析，推测与语音/字幕相关）'),
    'RES': ('lang_or_bin', '语言表 LANG(*_STRINGS.RES)；FONT/IKE/NTSC_IKE 为二进制资源'),
    'TXT': ('text_dev', '开发期 token→英文键值表（*_STRINGS.TXT；可能被引擎读取用于物品名）'),
    'DIR': ('text_dev', '目录清单（路径列表）'),
    'LST': ('text_dev', '编号清单（语音 wav 列表等）'),
    'LOG': ('text_dev', '日志'),
    'WRD': ('text_dev', '语音识别词表（非显示文本）'),
    'XBS': ('text_dev', '声音事件/文件名清单'),
    'BAT': ('text_dev', '构建脚本（PC 开发残留）'),
    # ---- 图像 / 图集 ----
    'PAK': ('image_atlas', '纹理图集包（记录=PS2 GS 图像: psm/w/h/clut/px；含字库图集）'),
    'RSB': ('image', '贴图包（Red Storm Bitmap；自带内部压缩，stored==real）'),
    'ICO': ('image', '内存卡图标（PS2 图标数据）'),
    'BMB': ('image', '贴图（推测）'),
    'BMZ': ('image', '压缩贴图（推测：LZO 混合帧 + 贴图数据）'),
    # ---- 3D 模型 / 动画 ----
    'POB': ('model', '模型包（BeginPOB 头）'),
    'QOB': ('model', '模型包（BeginModel 头）'),
    'POZ': ('model', '压缩模型（推测）'),
    'QOZ': ('model', '压缩模型（推测）'),
    'CHR': ('model', '角色模型（推测）'),
    'ANM': ('model', '动画（BeginANM 头）'),
    'VCL': ('model', '载具定义（XML，见上）'),
    'SCN': ('model', '场景/几何包（ANIB 头）'),
    'MOL': ('model', '地图对象布局（LZO 多子流）'),
    'MAZ': ('model', '地图区域/网格（推测）'),
    'POL': ('model', '多边形/门户数据（推测）'),
    'SHT': ('model', '光照贴图数据（RoomData 头）'),
    'AOL': ('model', '对象列表（Version 头）'),
    'CHZ': ('model', '压缩角色数据（推测）'),
    'CHA': ('model', '角色数据（推测）'),
    'XBG': ('model', '模型引用表（含 .qob/.pob 文件名）'),
    # ---- 音频 / 视频 ----
    'SB': ('audio', '音频采样包（sound bank）'),
    'SH': ('audio', '音频头/索引'),
    'SS': ('audio', '音频流（大体积）'),
    'WAV': ('audio', 'RIFF WAVE'),
    'AUD': ('audio', 'RIFF DMAP 音频路径'),
    'THC': ('audio', '音频库头（推测）'),
    'MPG': ('video', '视频'),
    'PSS': ('video', 'PS2 PSS 视频流'),
    'TM': ('video', 'PS2 TM 视频/过场流（推测）'),
    # ---- 其它 ----
    'SAV': ('save', '存档模板'),
    'CSF_BIN': ('save', '战役存档二进制'),
    'PSF_BIN': ('save', '档案存档二进制'),
    'IDC': ('data', '整数/索引表（推测）'),
    'CTX': ('data', '上下文/通用数据（推测）'),
    'GCD': ('data', 'GC 数据块（推测）'),
    'BAT': ('text_dev', '构建脚本'),
}

# 已知「玩家可见文本」资源名（实证或本体工程结论继承）
PLAYER_VISIBLE = {
    'EN_STRINGS.RES': 'LANG 语言表（UI/任务/教程/多人模式全部文本）',
    'EN_STRINGS.TXT': 'token→英文键值表（武器/道具/Kit 名；本体工程判定为玩家可见）',
    'EN_SPECIAL_FEATURE.XML': 'SFXML 专家档案/画廊文字',
    'IKE.RES': '菜单布局（无数值文本；布局宽度影响折行）',
    'NTSC_IKE.RES': '菜单布局（NTSC 版）',
}
TEXT_EXTS = ('MIS', 'ATR', 'GTF', 'XML', 'KIL')


def P(*a):
    print(' '.join(str(x) for x in a), flush=True)


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def ext_of(name):
    return name.rsplit('.', 1)[-1].upper() if '.' in name else '(NONE)'


# ───────────────────────── 载荷展开（含 raw 块规则） ─────────────────────────
def expand_frames(packed, real_hint=None):
    """顺序展开 {u32 clen}{u32 rlen}{payload} 帧。

    · clen == rlen：payload 为**原样未压缩块**（本盘大量 BMZ/CHZ/MIS/ICO 的末块如此）
    · clen <  rlen：LZO1X 压缩块
    · 返回 (blob, streams, tail_bytes)；streams 每项 dict(off,clen,rlen,raw)
    """
    blob = bytearray()
    streams = []
    p = 0
    n = len(packed)
    while p + 8 <= n:
        L, S = struct.unpack_from('<II', packed, p)
        if L == S and 0 < L and p + 8 + L <= n:
            data = packed[p + 8:p + 8 + L]
            streams.append(dict(off=p, clen=L, rlen=S, raw=True))
        elif 0 < L < S and p + 8 + L <= n:
            try:
                data, err, _ = dlclib.lzo1x_decompress(packed[p + 8:p + 8 + L], out_size=S)
            except Exception:  # noqa: BLE001
                break
            if err is not None or len(data) != S:
                break
            streams.append(dict(off=p, clen=L, rlen=S, raw=False))
        else:
            break
        blob += data
        p += 8 + L
    return bytes(blob), streams, n - p


def entry_payload2(iso, e):
    """返回 dict(kind,packed,blob,streams,tail)；不抛异常，status 说明可解性。"""
    packed = iso.read(e['iso_off'], e['stored'])
    if e['stored'] == e['real']:
        return dict(kind='raw', packed=packed, blob=packed, streams=[], tail=0,
                    status='raw', nraw=0)
    blob, streams, tail = expand_frames(packed)
    nraw = sum(1 for s in streams if s['raw'])
    if len(blob) == e['real']:
        status = 'ok'
    elif len(blob) == 0 and not streams:
        status = 'frame_error'
    else:
        status = 'len_mismatch(%d!=%d)' % (len(blob), e['real'])
    return dict(kind='lzo', packed=packed, blob=blob, streams=streams, tail=tail,
                status=status, nraw=nraw)


# ───────────────────────── 容器结构分析 ─────────────────────────
def analyze_header(iso, ents):
    base = dlclib.GR_LBA * SEC
    mm = iso.mm
    h = list(struct.unpack_from('<12I', mm, base))
    root = iso.find_root('GR.IMG')
    names_region = bytes(mm[base + h[4]:base + h[1]])
    names = [x.decode('latin-1') for x in names_region.split(b'\x00') if x]
    # 名字偏移链自证
    off = 0
    name_off_ok = True
    for e in ents:
        if e['raw'][0] != off:
            name_off_ok = False
            break
        off += len(e['name']) + 1
    # 哈希桶表
    ht_off = h[8]
    ht = struct.unpack_from('<4096I', mm, base + ht_off)
    empty = sum(1 for v in ht if v == 0xFFFFFFFF)
    roots = 4096 - empty
    bucket = {}
    chains = []
    order_ok = True
    for b, v in enumerate(ht):
        if v == 0xFFFFFFFF:
            continue
        cur = v - 1
        chain = []
        seen = set()
        while True:
            if cur in seen or not (0 <= cur < len(ents)):
                order_ok = False
                break
            seen.add(cur)
            chain.append(cur)
            bucket[cur] = b
            nxt = ents[cur]['raw'][11]
            if nxt == 0:
                break
            cur = nxt - 1
        chains.append(chain)
    # ★ 桶号与条目 u32[10] 的关系（本盘 3111/3111 完全吻合）：
    #   u32[10] = (hi6 << 16) | lo16，其中 hi6 = u32[10]>>16（6 bit）、lo6 = u32[10]&0x3F；
    #   桶号 = (hi6 << 6) | lo6  ⇒ 即 u32[10] 里藏着一个 12-bit 名字哈希，桶表按它取模。
    bucket_fn_ok = sum(1 for i in range(len(ents))
                       if ((((ents[i]['raw'][10] >> 16) << 6)
                            | (ents[i]['raw'][10] & 0x3F)) & 0xFFF) == bucket[i])
    # 名字排序链
    head = None
    referenced = set()
    for e in ents:
        v = e['raw'][1]
        if v:
            referenced.add(v - 1)
    heads = [i for i in range(len(ents)) if i not in referenced]
    sorted_order = []
    sorted_ok = True
    if len(heads) == 1:
        head = heads[0]
        cur = head
        seen = set()
        while True:
            if cur in seen:
                sorted_ok = False
                break
            seen.add(cur)
            sorted_order.append(cur)
            nxt = ents[cur]['raw'][1]
            if nxt == 0:
                break
            cur = nxt - 1
    names_sorted = [ents[i]['name'] for i in sorted_order]
    names_match = (sorted_order and
                   names_sorted == sorted(names_sorted, key=lambda s: s.encode('latin-1')))
    # 间距 / slack
    by_off = sorted(ents, key=lambda e: e['off'])
    slack = {}
    overlap = []
    for k, e in enumerate(by_off):
        nxt = by_off[k + 1]['off'] if k + 1 < len(by_off) else h[0]
        s = nxt - (e['off'] + e['stored'])
        slack[e['idx']] = s
        if s < 0:
            overlap.append((e['idx'], e['name'], s))
    tail = h[0] - max(e['off'] + e['stored'] for e in ents)
    # 容器头字段交叉验证
    checks = {
        '+0x00 size == ISO9660 GR.IMG;1 size': h[0] == root['size'],
        '+0x04 names_end == names_start + 名字区长度': h[1] == h[4] + len(names_region),
        '+0x08 == 2048（扇区大小）': h[2] == SEC,
        '+0x0C tbl_end == 0x830 + 3111*48': h[3] == dlclib.TAB_OFF + dlclib.TAB_STEP * len(ents),
        '+0x10 names_start == tbl_end + 2400 + 16384（中间 2400B 零填充 + 16KB 哈希表）': h[4] == h[3] + 2400 + 16384,
        '+0x14 data_start == min(off)': h[5] == min(e['off'] for e in ents),
        '+0x18 == 1': h[6] == 1,
        '+0x1C == 0': h[7] == 0,
        '+0x20 hash_off + 16384 == names_start': h[8] + 16384 == h[4],
        '+0x24..+0x2C == 0': h[9] == h[10] == h[11] == 0,
        '名字偏移链 u32[0] 连续覆盖名字区': name_off_ok,
        '名字排序链 u32[1] 恰好 1 个头、覆盖全部条目、顺序==名字字节序升序': bool(sorted_order) and sorted_ok and names_match,
        '哈希桶表 4096 槽、链覆盖全部条目、无环无重': (order_ok and len(bucket) == len(ents)
                                                and sum(len(c) for c in chains) == len(ents)),
        '哈希桶号 == ((u32[10]>>16)<<6)|(u32[10]&0x3F)：12-bit 名字哈希': bucket_fn_ok == len(ents),
    }
    info = dict(
        raw=h,
        fields={
            '+0x00': dict(val=h[0], name='container_size',
                          note='容器总字节数；与 ISO9660 root dir 登记大小相等'),
            '+0x04': dict(val=h[1], name='names_end', note='名字区结束偏移'),
            '+0x08': dict(val=h[2], name='sector_size', note='扇区大小 2048'),
            '+0x0C': dict(val=h[3], name='entry_table_end',
                          note='0x830 + N*48；其后 2400 B 全零填充'),
            '+0x10': dict(val=h[4], name='names_start', note='名字区起始偏移'),
            '+0x14': dict(val=h[5], name='data_start', note='载荷区起点 == min(off)'),
            '+0x18': dict(val=h[6], name='version?', note='本盘=1；与本体同值（推测：格式版本）'),
            '+0x1C': dict(val=h[7], name='reserved', note='0'),
            '+0x20': dict(val=h[8], name='hash_table_off',
                          note='4096×u32 哈希桶表；0xFFFFFFFF=空；值=条目号+1'),
            '+0x24': dict(val=h[9], name='reserved', note='0'),
            '+0x28': dict(val=h[10], name='reserved', note='0'),
            '+0x2C': dict(val=h[11], name='reserved', note='0'),
        },
        checks=checks,
        names_region_len=len(names_region),
        n_names=len(names),
        hash_table=dict(off=ht_off, off_abs=base + ht_off, slots=4096, empty=empty,
                        used=roots, covered=len(bucket), max_chain=max(len(c) for c in chains),
                        avg_chain=round(len(ents) / roots, 3),
                        bucket_fn='bucket = ((u32[10]>>16)<<6) | (u32[10]&0x3F)',
                        bucket_fn_matches=bucket_fn_ok),
        sorted_list=dict(field=1, head=head, head_name=ents[head]['name'] if head is not None else None,
                         tail=sorted_order[-1] if sorted_order else None,
                         tail_name=ents[sorted_order[-1]]['name'] if sorted_order else None,
                         covered=len(sorted_order), matches_byte_sorted=names_match),
        gaps=dict(tbl_end_to_hash=h[8] - h[3],
                  names_end_to_data=h[5] - h[1],
                  tail_bytes=tail,
                  tail_note='容器末尾空闲（0 填充）'),
        slack=dict(zero=sum(1 for v in slack.values() if v == 0),
                   lt_2048=sum(1 for v in slack.values() if 0 < v < 2048),
                   ge_2048=sum(1 for v in slack.values() if v >= 2048),
                   total=sum(slack.values()),
                   max=max(slack.values()) if slack else 0,
                   overlaps=overlap),
    )
    return info, slack


def analyze_entry_fields(ents):
    """条目 12×u32 字段语义统计（用盘上值自证）。"""
    n = len(ents)
    raws = [e['raw'] for e in ents]
    f04 = Counter(r[4] for r in raws)
    consist = Counter()
    for e in ents:
        r, eq = e['raw'], e['stored'] == e['real']
        consist[(r[4], 'eq' if eq else ('gt' if r[6] > r[7] else 'lt'))] += 1
    empty = [e for e in ents if e['stored'] == 0 and e['real'] == 0]
    gt = [e for e in ents if e['stored'] > e['real']]
    return dict(
        f04_dist=dict(f04),
        f04_vs_stored_real=dict(('%d/%s' % k, v) for k, v in consist.items()),
        f05_all_one=all(r[5] == 1 for r in raws),
        f02_f03_all_zero=all(r[2] == 0 and r[3] == 0 for r in raws),
        zero_len_entries=len(empty),
        stored_gt_real=[dict(idx=e['idx'], name=e['name'], stored=e['stored'],
                             real=e['real'], f04=e['raw'][4]) for e in gt],
        f09_distinct=len(set(r[9] for r in raws)),
        f10_distinct=len(set(r[10] for r in raws)),
        f09f10_pairs_distinct=len(set((r[9], r[10]) for r in raws)),
    )


# ───────────────────────── 文本普查 ─────────────────────────
def text_census(blob):
    runs = 0
    total = 0
    best = []
    for m in PRINT_RE.finditer(blob):
        s = m.group(0)
        runs += 1
        total += len(s)
        if len(best) < 5:
            best.append(s.decode('latin-1'))
        elif len(s) > min(len(x) for x in best):
            best[best.index(min(best, key=len))] = s.decode('latin-1')
    return runs, total, best


def xml_text_stats(blob):
    """轻量 XML 文本量统计：去标签后的文本字节（含属性值）。"""
    try:
        txt = blob.decode('latin-1')
    except Exception:  # noqa: BLE001
        return None
    body = re.sub(r'<[^>]*>', ' ', txt)
    text = re.sub(r'\s+', ' ', body).strip()
    return dict(xml_ok=True, text_bytes=len(text), text_chars=len(text))


def structured_text(iso, ents, payloads):
    """对已知文本类资源做结构化统计。"""
    out = {}
    byname = {e['name'].upper(): e for e in ents}
    # LANG
    for e in ents:
        ext = ext_of(e['name'])
        if ext == 'RES' and e['name'].upper().endswith('_STRINGS.RES'):
            p = payloads[e['idx']]
            try:
                lang, used = dlclib.parse_lang(p['blob'])
                groups = defaultdict(list)
                for x in lang:
                    groups[x.g].append(x)
                out[e['name']] = dict(parser='parse_lang', groups=len(groups),
                                      entries=len(lang),
                                      text_bytes=sum(len(x.data) for x in lang),
                                      used_end=used, blob_len=len(p['blob']),
                                      tail=len(p['blob']) - used,
                                      group_sizes={str(k): len(v) for k, v in sorted(groups.items())})
            except Exception as ex:  # noqa: BLE001
                out[e['name']] = dict(parser='parse_lang', error=str(ex))
    # SFXML
    for e in ents:
        if 'SPECIAL_FEATURE.XML' in e['name'].upper():
            p = payloads[e['idx']]
            try:
                texts = dlclib.parse_sfxml(p['blob'])
                nonempty = [t for t in texts if t[3]]
                out[e['name']] = dict(parser='parse_sfxml', text_tags=len(texts),
                                     nonempty=len(nonempty),
                                     text_bytes=sum(t[2] for t in nonempty),
                                     total_text_bytes=sum(t[2] for t in texts))
            except Exception as ex:  # noqa: BLE001
                out[e['name']] = dict(parser='parse_sfxml', error=str(ex))
    # XML / MIS / ATR / GTF 等
    for e in ents:
        ext = ext_of(e['name'])
        if ext not in TEXT_EXTS and ext not in ('GUN', 'KIT', 'TOE', 'PRJ', 'VCL', 'ITM',
                                                'ENV', 'CSF', 'PSF'):
            continue
        p = payloads[e['idx']]
        st = xml_text_stats(p['blob'])
        if st is None:
            continue
        st['real'] = e['real']
        if e['name'] in out:                 # SFXML 已由 parse_sfxml 解析：保留其统计并补充 XML 口径
            out[e['name']].update(st)
        else:
            out[e['name']] = st
    return out


def ext_summary(ents, rows, text_stats):
    agg = defaultdict(lambda: dict(n=0, stored=0, real=0, lzo=0, raw=0, lzo_ok=0,
                                   text_runs=0, text_bytes=0, text_entries=0))
    for e in ents:
        ext = ext_of(e['name'])
        a = agg[ext]
        a['n'] += 1
        a['stored'] += e['stored']
        a['real'] += e['real']
        r = rows[e['idx']]
        if r['kind'] == 'raw':
            a['raw'] += 1
        else:
            a['lzo'] += 1
            if r['status'] == 'ok':
                a['lzo_ok'] += 1
        a['text_runs'] += r['text_runs']
        a['text_bytes'] += r['text_bytes']
        if r['text_bytes'] >= 256:
            a['text_entries'] += 1
    for ext, a in agg.items():
        cls = EXT_CLASS.get(ext, ('binary', ''))[0]
        a['class'] = cls
    return dict(sorted(agg.items(), key=lambda kv: -kv[1]['n']))


# ───────────────────────── 主流程 ─────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description='GR.IMG (SLUS-20820) 容器/条目/文本全量分析（只读）')
    ap.add_argument('--iso', default=dlclib.DEFAULT_ISO, help='英文原盘 ISO 路径（只读）')
    ap.add_argument('--quick', action='store_true', help='只分析容器结构，不展开载荷')
    ap.add_argument('--header', action='store_true', help='只打印容器头/条目表结构')
    ap.add_argument('--limit', type=int, default=0, help='只处理前 N 条（调试用）')
    ap.add_argument('--manifest', default=os.path.join(REPO, 'assets', 'manifests', 'gr_img_index.json'),
                    help='机器可读清单输出路径')
    ap.add_argument('--workdir', default=os.path.join(REPO, 'work', 'analysis', 'iso'),
                    help='明细中间产物目录')
    args = ap.parse_args()

    os.makedirs(args.workdir, exist_ok=True)
    iso = dlclib.Iso(args.iso)
    ents = dlclib.img_entries(iso)
    if args.limit:
        ents = ents[:args.limit]
    P('[cfg] ISO = %s (%d B)' % (iso.path, iso.size))
    P('[cfg] GR.IMG @ LBA %d, 条目 %d' % (dlclib.GR_LBA, len(ents)))

    P('\n=== 1) 容器头字段与结构自证 ===')
    hdr, slack = analyze_header(iso, ents)
    for off, f in hdr['fields'].items():
        P('  %-6s = %-12d %-16s %s' % (off, f['val'], f['name'], f['note']))
    for k, v in hdr['checks'].items():
        P('  [%s] %s' % ('OK ' if v else 'FAIL', k))
    P('  哈希表: %d 槽 / 已用 %d / 链覆盖 %d 条 / 最长链 %d / 平均链 %.3f / 桶号公式吻合 %d/%d'
      % (hdr['hash_table']['slots'], hdr['hash_table']['used'], hdr['hash_table']['covered'],
         hdr['hash_table']['max_chain'], hdr['hash_table']['avg_chain'],
         hdr['hash_table']['bucket_fn_matches'], len(ents)))
    P('  名字排序链: head=#%s %s / tail=#%s %s / 覆盖 %d 条 / 顺序==名字升序: %s'
      % (hdr['sorted_list']['head'], hdr['sorted_list']['head_name'],
         hdr['sorted_list']['tail'], hdr['sorted_list']['tail_name'],
         hdr['sorted_list']['covered'], hdr['sorted_list']['matches_byte_sorted']))
    P('  间隙: 条目表末→哈希表 %d B; 名字末→载荷区 %d B; 容器尾空闲 %d B'
      % (hdr['gaps']['tbl_end_to_hash'], hdr['gaps']['names_end_to_data'], hdr['gaps']['tail_bytes']))
    P('  条目间 slack: =0 %d 条, 1..2047 %d 条, >=2048 %d 条, 合计 %d B, max %d B, 负值(重叠) %d 条'
      % (hdr['slack']['zero'], hdr['slack']['lt_2048'], hdr['slack']['ge_2048'],
         hdr['slack']['total'], hdr['slack']['max'], len(hdr['slack']['overlaps'])))

    P('\n=== 2) 条目表 12×u32 字段语义统计 ===')
    fields = analyze_entry_fields(ents)
    P('  u32[4] 压缩标志分布: %s' % fields['f04_dist'])
    P('  u32[4] × stored/real 关系: %s' % fields['f04_vs_stored_real'])
    P('  u32[2]==u32[3]==0: %s ; u32[5] 全为 1: %s'
      % (fields['f02_f03_all_zero'], fields['f05_all_one']))
    P('  零长条目(stored==real==0): %d' % fields['zero_len_entries'])
    P('  stored>real 异常: %d 条 %s' % (len(fields['stored_gt_real']),
                                        [(x['name'], x['stored'], x['real']) for x in fields['stored_gt_real']]))
    P('  u32[9] distinct=%d, u32[10] distinct=%d, (u32[9],u32[10]) distinct=%d'
      % (fields['f09_distinct'], fields['f10_distinct'], fields['f09f10_pairs_distinct']))

    if args.header:
        iso.close()
        return 0

    # 名字重复 / 大小写重复
    dup = [k for k, v in Counter(e['name'] for e in ents).items() if v > 1]
    dup_ci = [k for k, v in Counter(e['name'].upper() for e in ents).items() if v > 1]
    P('  重名: %d 个; 忽略大小写重名: %d 个' % (len(dup), len(dup_ci)))

    rows = {}
    if args.quick:
        for e in ents:
            rows[e['idx']] = dict(kind='raw' if e['stored'] == e['real'] else 'lzo',
                                  status='skipped', text_runs=0, text_bytes=0,
                                  text_ratio=0.0, nsub=0, nraw=0, frame_bytes=0,
                                  intra_slack=0, packed_len=e['stored'], blob_len=0,
                                  sha='', samples=[])
        payloads = {}
    else:
        P('\n=== 3) 全量载荷展开 + 可打印 ASCII 串普查（%d 条）===' % len(ents))
        payloads = {}
        bad = []
        n_raw_blocks = 0
        for k, e in enumerate(ents):
            p = entry_payload2(iso, e)
            payloads[e['idx']] = p
            n_raw_blocks += p['nraw']
            runs, total, samples = text_census(p['blob'])
            frame_bytes = sum(8 + s['clen'] for s in p['streams'])
            intra = (e['stored'] - frame_bytes) if p['kind'] == 'lzo' else 0
            rows[e['idx']] = dict(
                kind=p['kind'], status=p['status'],
                nsub=len(p['streams']), nraw=p['nraw'],
                packed_len=len(p['packed']), blob_len=len(p['blob']),
                frame_bytes=frame_bytes,
                intra_slack=intra,
                text_runs=runs, text_bytes=total,
                text_ratio=round(total / max(1, len(p['blob'])), 4),
                sha=sha256(p['blob']), samples=samples[:3])
            if p['status'] not in ('raw', 'ok'):
                bad.append((e['idx'], e['name'], p['status']))
            if (k + 1) % 400 == 0:
                P('  ... %d/%d' % (k + 1, len(ents)))
        P('  展开完成：raw %d / LZO %d；LZO 不可解 %d 条；LZO 内原样块 %d 个'
          % (sum(1 for r in rows.values() if r['kind'] == 'raw'),
             sum(1 for r in rows.values() if r['kind'] == 'lzo'),
             len(bad), n_raw_blocks))
        if bad:
            for b in bad[:20]:
                P('    !! #%d %s %s' % b)

    # 结构化文本统计（text-engineer 上游口径）
    text_stats = structured_text(iso, ents, payloads) if payloads else {}
    ext = ext_summary(ents, rows, text_stats)

    if not args.quick:
        # 写 work 明细
        txt_path = os.path.join(args.workdir, 'gr_img_entries.tsv')
        with open(txt_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write('idx\tname\text\tclass\tkind\tstatus\tnsub\tnraw\tstored\treal\toff\t'
                    'frame_bytes\tintra_slack\tslack_to_next\ttext_runs\ttext_bytes\ttext_ratio\tsha256\tplayers\n')
            for e in ents:
                r = rows[e['idx']]
                cls = EXT_CLASS.get(ext_of(e['name']), ('binary', ''))[0]
                pv = '1' if e['name'] in PLAYER_VISIBLE else ''
                f.write('%d\t%s\t%s\t%s\t%s\t%s\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%.4f\t%s\t%s\n'
                        % (e['idx'], e['name'], ext_of(e['name']), cls, r['kind'], r['status'],
                           r['nsub'], r['nraw'], e['stored'], e['real'], e['off'],
                           r['frame_bytes'], r['intra_slack'], slack.get(e['idx'], 0),
                           r['text_runs'], r['text_bytes'], r['text_ratio'], r['sha'], pv))
        P('  写入 %s' % txt_path)
        # 文本样本
        samp_path = os.path.join(args.workdir, 'text_samples.tsv')
        with open(samp_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write('idx\tname\text\ttext_runs\ttext_bytes\ttext_ratio\tsamples\n')
            for e in ents:
                r = rows[e['idx']]
                if r['text_bytes'] < 256:
                    continue
                ss = ' | '.join(s.replace('\t', ' ').replace('\r', '\\r').replace('\n', '\\n')
                                for s in r['samples'])
                f.write('%d\t%s\t%s\t%d\t%d\t%.4f\t%s\n'
                        % (e['idx'], e['name'], ext_of(e['name']), r['text_runs'],
                           r['text_bytes'], r['text_ratio'], ss))
        P('  写入 %s' % samp_path)
        # 按文本量排序的普查清单（按资源排序）
        sort_path = os.path.join(args.workdir, 'text_census_by_resource.tsv')
        with open(sort_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write('rank\tidx\tname\text\tclass\tis_text\ttext_runs\ttext_bytes\ttext_ratio\tblob_len\n')
            order = sorted(ents, key=lambda e: -rows[e['idx']]['text_bytes'])
            for rk, e in enumerate(order, 1):
                r = rows[e['idx']]
                cls = EXT_CLASS.get(ext_of(e['name']), ('binary', ''))[0]
                is_text = '1' if (cls.startswith('text') or cls == 'lang_or_bin'
                                  or e['name'] in PLAYER_VISIBLE) else ''
                f.write('%d\t%d\t%s\t%s\t%s\t%s\t%d\t%d\t%.4f\t%d\n'
                        % (rk, e['idx'], e['name'], ext_of(e['name']), cls, is_text,
                           r['text_runs'], r['text_bytes'], r['text_ratio'], r['blob_len']))
        P('  写入 %s' % sort_path)
        # 每个文本类资源的结构化统计
        tstat_path = os.path.join(args.workdir, 'text_resource_stats.json')
        with open(tstat_path, 'w', encoding='utf-8') as f:
            json.dump(text_stats, f, ensure_ascii=False, indent=1)
        P('  写入 %s' % tstat_path)

    # 清单
    manifest = dict(
        schema='gr_img_index/1',
        generated_by='tools/analysis/iso_img_scan.py',
        source=dict(iso=os.path.basename(iso.path), iso_bytes=iso.size,
                    iso_sha256=dlclib.ISO_SHA256,
                    lba=dlclib.GR_LBA, img_bytes=hdr['raw'][0]),
        header=hdr,
        entry_fields={
            'u32[0]': 'name_off（相对 names_start 的偏移；按条目顺序累计，无对齐填充）',
            'u32[1]': 'name_sort_next（1-based 条目号；0=链表尾；按名字字节升序遍历的 next 链）',
            'u32[2]': '0（保留）',
            'u32[3]': '0（保留）',
            'u32[4]': 'compressed（1=LZO 帧流，0=原样载荷）',
            'u32[5]': '1（常量，含义未定；推测=格式版本/ref 标志）',
            'u32[6]': 'stored（盘上占用字节数，含帧头与尾部 padded 字节）',
            'u32[7]': 'real（展开后负载字节数 = Σ rlen）',
            'u32[8]': 'off（相对容器头 0 的载荷偏移；载荷区起点=data_start）',
            'u32[9]': 'name_key（同名资源跨 GR/MENU/本体/资料片恒定；32bit，全表 2405 个不同值（有碰撞）；'
                      '算法未解，推测=完整名字哈希/构建期资源ID；汉化不改名 ⇒ 无需重算）',
            'u32[10]': 'bucket_hash（= (hi6<<16)|lo16，hi6=u32[10]>>16 为 6 bit、lo6=u32[10]&0x3F 为 6 bit；'
                       '哈希桶号 = (hi6<<6)|lo6，本盘 3111/3111 完全吻合 ⇒ 内藏 12-bit 名字哈希）',
            'u32[11]': 'hash_chain_next（1-based 条目号；0=链尾；哈希桶表 @+0x20 的冲突链）',
        },
        entry_field_evidence=fields,
        summary=dict(
            n_entries=len(ents),
            n_raw=sum(1 for r in rows.values() if r['kind'] == 'raw'),
            n_lzo=sum(1 for r in rows.values() if r['kind'] == 'lzo'),
            n_lzo_ok=sum(1 for r in rows.values() if r['status'] == 'ok'),
            n_lzo_bad=sum(1 for r in rows.values() if r['status'] not in ('raw', 'ok')),
            n_stream_raw_blocks=sum(r['nraw'] for r in rows.values()),
            sum_stored=sum(e['stored'] for e in ents),
            sum_real=sum(e['real'] for e in ents),
            data_end=max(e['off'] + e['stored'] for e in ents),
            container_size=hdr['raw'][0],
            tail_free_bytes=hdr['raw'][0] - max(e['off'] + e['stored'] for e in ents),
            slack_total=hdr['slack']['total'],
            dup_names=dup, dup_names_ci=dup_ci,
            ext=ext,
        ),
        player_visible_resources=PLAYER_VISIBLE,
        text_resources=text_stats,
        entries=[],
    )
    for e in ents:
        r = rows[e['idx']]
        cls, note = EXT_CLASS.get(ext_of(e['name']), ('binary', ''))
        is_text = bool(cls.startswith('text') or cls == 'lang_or_bin'
                       or e['name'] in PLAYER_VISIBLE)
        manifest['entries'].append(dict(
            i=e['idx'], name=e['name'], ext=ext_of(e['name']), res_class=cls,
            kind=r['kind'], status=r['status'],
            nsub=r['nsub'], nraw=r['nraw'],
            stored=e['stored'], real=e['real'], off=e['off'],
            frame_bytes=r['frame_bytes'], intra_slack=r['intra_slack'],
            text_runs=r['text_runs'], text_bytes=r['text_bytes'], text_ratio=r['text_ratio'],
            sha256=r['sha'],
            is_text=is_text,
            player_visible=e['name'] in PLAYER_VISIBLE,
        ))
    os.makedirs(os.path.dirname(args.manifest), exist_ok=True)
    with open(args.manifest, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    P('\n[out] 清单 %s (%.1f KB)' % (args.manifest, os.path.getsize(args.manifest) / 1024))

    # 汇总表
    P('\n=== 4) 扩展名 / 类别汇总（按条目数降序）===')
    P('  %-8s %5s %4s %4s %7s %12s %10s %10s %8s' %
      ('ext', 'n', 'raw', 'lzo', 'lzoBAD', 'stored', 'real', 'text_bytes', 'textEntries'))
    for k, a in ext.items():
        P('  %-8s %5d %4d %4d %7d %12d %10d %10d %8d'
          % (k, a['n'], a['raw'], a['lzo'], a['lzo'] - a['lzo_ok'],
             a['stored'], a['real'], a['text_bytes'], a['text_entries']))
    P('\n[ok] 完成')
    iso.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
