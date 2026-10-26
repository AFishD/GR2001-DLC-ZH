# -*- coding: utf-8 -*-
r"""verify.py —— 汉化 ISO 的硬断言自证（唯一校验入口）。

用法：
    python tools\dlc\verify.py --iso work\builds\JS_ZH_final.iso --stage all
    python tools\dlc\verify.py --iso <盘> --stage font
    python tools\dlc\verify.py --iso <盘>                 # 只跑通用结构断言

断言分组：
  A 身份/ISO 结构：尺寸、卷标、PVD volume_space、根目录 GR.IMG 长度 == 头 +0x0、条目数/名字
  B 条目完整性：全 3,111 条可解析（raw 或 LZO 全解）、条目表非内容字段与英文原盘一致
  C 字库：COMMON.PAK 10 记录、new_font_revised psm/w/h/clut/px、图集容器 sha == seed、
          FONT.RES 3 face × 224 记录 + 522B 尾部、ASCII FT 记录与资料片原盘一致
  D 文本：LANG 2,971 条 / 67 组、(g,i) 序列不变、每条可编码/解码、无 0xFF；
          SFXML 98 个 <text>；MIS 文件数不变且 XML 可解析
  E ELF：sha256 / PCSX2 Game CRC 与期望一致（打了补丁的 stage）
  F 回归：与 fix_spec.json 记录的 sha256 一致
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'font'))

import dlclib as L                                             # noqa: E402
import tcslib as T                                             # noqa: E402

SPEC_PATH = os.path.join(HERE, 'fix_spec.json')
SEED_DIR = os.path.join(REPO, 'third_party', 'ref', 'zh_font_seed')
CHARSET = os.path.join(REPO, 'assets', 'charset', 'charset_compiled_zh16.json')
ELF_NAME = 'SLUS_208.20'
GR_LBA = L.GR_LBA
TAB_OFF, TAB_STEP = L.TAB_OFF, L.TAB_STEP

# 各阶段允许被替换的条目名（其余条目必须与英文原盘逐字节相同）
REPLACED_BY_STAGE = {
    'font': {'COMMON.PAK', 'FONT.RES'},
    'text': {'COMMON.PAK', 'FONT.RES', 'EN_STRINGS.RES', 'EN_SPECIAL_FEATURE.XML'},
    'elf': {'COMMON.PAK', 'FONT.RES'},
    'all': {'COMMON.PAK', 'FONT.RES', 'EN_STRINGS.RES', 'EN_SPECIAL_FEATURE.XML'},
}

_results = []


def chk(cond, msg):
    _results.append((bool(cond), msg))
    return bool(cond)


def P(*a):
    print(' '.join(str(x) for x in a), flush=True)


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(path):
    return L.sha256_file(path)


def xor_crc32(data):
    c = 0
    for (w,) in struct.iter_unpack('<I', data[:len(data) // 4 * 4]):
        c ^= w
    return c & 0xFFFFFFFF


def load_seed_meta():
    p = os.path.join(SEED_DIR, 'meta.json')
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else None


def load_spec():
    return json.load(open(SPEC_PATH, encoding='utf-8')) if os.path.exists(SPEC_PATH) else None


# ───────────────────────── A. ISO / IMG 结构 ─────────────────────────
def verify_structure(iso, orig):
    pvd = iso.pvd()
    chk(pvd['volume_id'] == 'SLUS_20820', 'A1 卷标 = SLUS_20820（实际 %s）' % pvd['volume_id'])
    chk(pvd['volume_space'] * L.SEC == iso.size,
        'A2 PVD volume_space %d 扇区 × 2048 == ISO 尺寸 %d' % (pvd['volume_space'], iso.size))
    gr = iso.find_root('GR.IMG')
    chk(gr is not None, 'A3 根目录有 GR.IMG')
    ents = L.img_entries(iso)
    chk(len(ents) == L.ENTRY_COUNT, 'A4 GR.IMG 条目数 = %d（实际 %d）' % (L.ENTRY_COUNT, len(ents)))
    hdr_size = struct.unpack_from('<I', iso.mm, GR_LBA * L.SEC)[0]
    chk(hdr_size == gr['size'], 'A5 头 +0x0 (%d) == 根目录 GR.IMG 长度 (%d)' % (hdr_size, gr['size']))
    chk(gr['lba'] == GR_LBA, 'A6 GR.IMG LBA = %d' % GR_LBA)
    # 名字表与条目名（与英文原盘一致）
    oents = L.img_entries(orig)
    chk([e['name'] for e in ents] == [e['name'] for e in oents],
        'A7 3,111 个条目名与英文原盘逐条一致')
    # 条目表非内容字段（[0][1][4][5][9][10][11]）与英文原盘一致
    bad = []
    for a, b in zip(ents, oents):
        for k in (0, 1, 4, 5, 9, 10, 11):
            if a['raw'][k] != b['raw'][k]:
                bad.append((a['idx'], a['name'], k, a['raw'][k], b['raw'][k]))
    chk(not bad, 'A8 条目表 [0][1][4][5][9][10][11] 与英文原盘一致（%d 处不同）' % len(bad))
    return ents, oents


# ───────────────────────── B. 条目完整性 ─────────────────────────
def verify_entries(iso, ents, oents, stage):
    replaced = REPLACED_BY_STAGE.get(stage, set())
    bad_parse, changed, unexpected = [], [], []
    for e, oe in zip(ents, oents):
        packed = iso.read(e['iso_off'], e['stored'])
        if e['stored'] == e['real']:
            ok = len(packed) == e['real']
        else:
            subs = L.lzo_subs(packed)
            ok = (sum(s[2] for s in subs) == e['real']) and len(subs) > 0
        if not ok:
            bad_parse.append((e['idx'], e['name']))
        old = orig_read(orig_iso, oe)
        if packed != old:
            changed.append((e['idx'], e['name']))
            nm = e['name'].upper()
            allowed = (nm in replaced or nm.endswith('.MIS') or nm.endswith('.ATR')
                       or nm == 'EN_STRINGS.TXT')
            if not allowed:
                unexpected.append((e['idx'], e['name']))
    chk(not bad_parse, 'B1 全 3,111 条载荷可解析（raw %d / LZO %d；坏 %d）'
        % (sum(1 for e in ents if e['stored'] == e['real']),
           sum(1 for e in ents if e['stored'] != e['real']), len(bad_parse)))
    P('     changed payloads: %d %s%s' % (
        len(changed), [c[1] for c in changed[:8]],
        ' ...' if len(changed) > 8 else ''))
    chk(not unexpected, 'B2 除声明可替换资源外没有意外改动的条目（%d 个意外: %s）'
        % (len(unexpected), unexpected[:5]))
    return dict(changed=[c[1] for c in changed])


_orig_iso = None
orig_iso = None


def orig_read(iso, e):
    return iso.read(e['iso_off'], e['stored'])


# ───────────────────────── C. 字库 ─────────────────────────
def verify_font(iso, ents, seed, stage):
    meta = seed
    e_pak = L.img_find(ents, 'COMMON.PAK')
    pak, pay = e_pak, L.entry_payload(iso, e_pak)
    chk(pay['kind'] == 'raw', 'C1 COMMON.PAK 为 raw 载荷')
    recs = L.parse_pak_records(pay['blob'])
    names = [r['name'] for r in recs]
    oiso = L.Iso(L.DEFAULT_ISO)
    o_pay = L.entry_payload(oiso, L.img_find(L.img_entries(oiso), 'COMMON.PAK'))
    orecs = L.parse_pak_records(o_pay['blob'])
    orig_pak_blob = o_pay['blob']
    oiso.close()
    onames = [r['name'] for r in orecs]
    chk(names == onames, 'C2 COMMON.PAK 记录名/顺序不变（%d 条）' % len(onames))
    rec = [r for r in recs if r['name'] == 'new_font_revised'][0]
    orec = [r for r in orecs if r['name'] == 'new_font_revised'][0]
    chk(len(recs) == len(orecs), 'C3 记录数 %d == 原盘 %d' % (len(recs), len(orecs)))
    if meta:
        at = meta['atlas']
        chk(rec['psm'] == at['psm'] and rec['w'] == at['w'] and rec['h'] == at['h'],
            'C4 new_font_revised psm/w/h = %d/%d/%d' % (rec['psm'], rec['w'], rec['h']))
        chk(rec['clut'] == 80, 'C5 new_font_revised CLUT 长度 = 80（native 形状；实际 %d）' % rec['clut'])
        chk(rec['px'] == at['px'], 'C6 new_font_revised px = %d（实际 %d）' % (at['px'], rec['px']))
        cont = pay['blob'][rec['px_off']:rec['px_off'] + rec['px']]
        try:
            import expand_charset as EC
            _seed_cont = open(os.path.join(SEED_DIR, 'COMMON_PAK.MENU3.zh.bin'), 'rb').read()
            import fontlib as _F
            _seeds = _F.load_seed() if hasattr(_F, 'load_seed') else None
        except Exception:                                      # noqa: BLE001
            _seeds = None
        try:
            import build_font as _BF
            _sf = _BF.load_seed()
            _expect_cont, _einfo = EC.expand_container(_sf['container'])
            chk(sha256(cont) == sha256(_expect_cont),
                'C7 图集容器 == seed + 字符集扩充补画（%s，新增 %d 字）'
                % (sha256(cont)[:16], _einfo.get('assignments', 0)))
        except Exception as ex:                                # noqa: BLE001
            chk(False, 'C7 图集容器无法复算: %r' % (ex,))
        # 其它记录字节不变
        bad = []
        for r, orc in zip(recs, orecs):
            if r['name'] == 'new_font_revised':
                continue
            if pay['blob'][r['hdr_off']:r['rec_end']] != orig_pak_blob[orc['hdr_off']:orc['rec_end']]:
                bad.append(r['name'])
        chk(not bad, 'C8 COMMON.PAK 其它 9 条记录字节不变（%d 个变化: %s）' % (len(bad), bad[:3]))
    # FONT.RES
    e_ft = L.img_find(ents, 'FONT.RES')
    ftpay = L.entry_payload(iso, e_ft)
    blob = ftpay['blob']
    end, faces = T.parse_ft_faces(blob)
    chk(len(faces) == 3 and [len(f[2]) for f in faces] == [224, 224, 224],
        'C9 FONT.RES 3 face × 224 条记录（实际 %s）' % [len(f[2]) for f in faces])
    chk(len(blob) - end == 522, 'C10 FONT.RES 尾部 %d B == 522' % (len(blob) - end))
    # ASCII FT 记录必须全部落在 1024×644 图集采样范围内
    oob = [(nm, r) for (nm, fld, recs) in faces for r in recs
           if r[4] > 1024 or r[5] > 644]
    chk(not oob, 'C11 FT 记录采样矩形全部在 1024×644 内（越界 %d 条）' % len(oob))
    # 与 fontlib 的确定性合并结果逐字节比对
    try:
        import fontlib as F
        oiso = L.Iso(L.DEFAULT_ISO)
        oents2 = L.img_entries(oiso)
        o_ft = L.entry_payload(oiso, L.img_find(oents2, 'FONT.RES'))
        oiso.close()
        seed_ft = open(os.path.join(SEED_DIR, 'FONT_RES.MENU4.zh.bin'), 'rb').read()
        expect = F.ft_merge_for_dlc(seed_ft, o_ft['blob'])
        chk(blob == expect, 'C12 FONT.RES == fontlib.ft_merge_for_dlc(seed, DLC)（sha %s）'
            % sha256(blob)[:16])
    except Exception as ex:                                    # noqa: BLE001
        chk(False, 'C12 FONT.RES 合并结果无法复算: %r' % (ex,))
    # A‴ 度量恢复（v8）：face fld[1] == EN 原盘、style f5=1.0 且 f6 == EN 原盘
    try:
        import struct as _st
        import fontlib as F2
        _info = F2.ft_parse(blob)
        _f1 = [f['fld'][1] for f in _info['faces']]
        _dlc_info = F2.ft_parse(o_ft['blob'])
        _exp_f1 = [f['fld'][1] for f in _dlc_info['faces']]
        _q = _info['parsed_end']
        _ns = _st.unpack_from('<I', blob, _q)[0]
        _q += 4
        _bad = []
        for _i in range(_ns):
            _nl = _st.unpack_from('<I', blob, _q)[0]
            _q += 4 + _nl + 4 * 4 + 1
            _f5, _f6 = _st.unpack_from('<2f', blob, _q)
            if abs(_f5 - 1.0) > 1e-6 or abs(_f6 - 1.0) > 1e-6:
                _bad.append((_i, _f5, _f6))
            _q += 8
        chk(_f1 == _exp_f1 and not _bad,
            'C14 FONT.RES 度量 = EN 行盒口径：fld[1]=%s（EN %s）、style f5/f6=1.0（越界=%s）'
            % (_f1, _exp_f1, _bad[:3]))
    except Exception as ex:                                    # noqa: BLE001
        chk(False, 'C14 FONT.RES 度量恢复无法复算: %r' % (ex,))
    chk(len(ftpay['packed']) <= e_ft['stored'] + 1,
        'C13 FONT.RES 载荷可解析（stored %d / real %d）'
        % (len(ftpay['packed']), e_ft['real']))


# ───────────────────────── D. 文本 ─────────────────────────
TEXT_TAG_RE = re.compile(rb'\{(?:p|br)\}')


def verify_text(iso, ents, stage, strict=True):
    cs = T.Charset(CHARSET)
    e_lang = L.img_find(ents, 'EN_STRINGS.RES')
    lang = L.entry_payload(iso, e_lang)
    oiso = L.Iso(L.DEFAULT_ISO)
    oents = L.img_entries(oiso)
    olang = L.entry_payload(oiso, L.img_find(oents, 'EN_STRINGS.RES'))
    ents_l = L.parse_lang(lang['blob'])[0]
    ents_o = L.parse_lang(olang['blob'])[0]
    chk(len(ents_l) == len(ents_o) == 2971, 'D1 LANG 条目数 = 2,971（实际 %d）' % len(ents_l))
    chk([(e.g, e.i) for e in ents_l] == [(e.g, e.i) for e in ents_o],
        'D2 LANG (g,i) 序列与英文原盘逐条一致')
    chk(max(e.g for e in ents_l) + 1 == 67, 'D3 LANG 组数 = 67')
    bad_enc, has_ff = [], []
    changed = 0
    for e, oe in zip(ents_l, ents_o):
        data = e.data
        if data != oe.data:
            changed += 1
        if b'\xff' in data:
            has_ff.append((e.g, e.i))
        try:
            txt, _ = cs.decode(data)
            cs.encode_strict(txt)
        except Exception:                                      # noqa: BLE001
            bad_enc.append((e.g, e.i))
    chk(not has_ff, 'D4 LANG 文本字节零 0xFF（%d 条命中）' % len(has_ff))
    chk(not bad_enc, 'D5 LANG 每条都能用字符集编码/解码（%d 条失败）' % len(bad_enc))
    P('     LANG changed entries: %d / %d' % (changed, len(ents_l)))
    # SFXML
    e_sf = L.img_find(ents, 'EN_SPECIAL_FEATURE.XML')
    sf = L.entry_payload(iso, e_sf)['blob']
    texts = T.parse_sfxml(sf)
    chk(len(texts) == 98, 'D6 SFXML <text> 数量 = 98（实际 %d）' % len(texts))
    chk(b'</SpecialFeatures>' in sf, 'D7 SFXML 结构完整（有结束标签）')
    ff = [k for (k, off, ln, body) in texts if b'\xff' in body]
    chk(not ff, 'D8 SFXML 正文零 0xFF（%d 条命中）' % len(ff))
    # MIS
    mis = [e for e in ents if e['name'].upper().endswith('.MIS')]
    mis_o = [e for e in oents if e['name'].upper().endswith('.MIS')]
    chk([e['name'] for e in mis] == [e['name'] for e in mis_o],
        'D9 MIS 文件清单不变（%d 个）' % len(mis))
    bad_mis = []
    for e in mis:
        try:
            blob = L.entry_payload(iso, e)['blob']
        except Exception:                                      # noqa: BLE001
            bad_mis.append(e['name'])
            continue
        if b'</MissionFile>' not in blob:
            bad_mis.append(e['name'] + '(无 MissionFile)')
    chk(not bad_mis, 'D10 全部 MIS 可解析且含 </MissionFile>（%d 坏: %s）' % (len(bad_mis), bad_mis[:3]))
    # 说明：ATR / STRINGS_TXT 等按 text stage 是否改动另行报告
    rep = dict(lang_entries=len(ents_l), lang_changed=changed,
               sfxml_texts=len(texts), mis_files=len(mis))
    return rep


# ───────────────────────── E. ELF ─────────────────────────
def verify_elf(iso, spec, stage):
    elf = iso.elf()
    sha = sha256(elf)
    crc = xor_crc32(elf)
    P('     ELF sha256 %s ; Game CRC %08X' % (sha, crc))
    ok = True
    eobj = os.path.join(HERE, 'elf_patches.json')
    if stage in ('elf', 'all') and os.path.exists(eobj):
        obj = json.load(open(eobj, encoding='utf-8'))
        exp_sha = obj.get('expect_elf_sha256')
        exp_crc = obj.get('expect_crc32')
        if exp_sha:
            ok &= chk(sha == exp_sha, 'E1 ELF sha256 == 期望 %s' % exp_sha[:16])
        if exp_crc:
            ok &= chk(('%08X' % crc) == exp_crc.upper(), 'E2 Game CRC == 期望 %s' % exp_crc)
        bad = []
        for patch in obj.get('patches', []):
            off = patch['file_off']
            new = bytes.fromhex(patch['new'])
            if bytes(elf[off:off + len(new)]) != new:
                bad.append(off)
        ok &= chk(not bad, 'E3 全部 %d 处补丁在盘上（%d 处不符）'
                  % (len(obj.get('patches', [])), len(bad)))
    else:
        oiso = L.Iso(L.DEFAULT_ISO)
        oelf = oiso.elf()
        oiso.close()
        ok &= chk(sha == sha256(oelf), 'E1 ELF 与原盘一致（未打补丁阶段）')
    return ok


# ───────────────────────── 主入口 ─────────────────────────
def verify_icon_protection(iso, stage):
    """I* 图标占位/哨兵槽保护：字符集不占用 + 图集哨兵格与 seed 一致。"""
    sys.path.insert(0, os.path.join(REPO, 'tools', 'font'))
    import atlas_guard as AG
    ok, bad, _risk = AG.check_charset()
    chk(ok, 'I1 字符集不占用图标哨兵槽（50 格）')
    try:
        ok2, bad2 = AG.check_atlas_vs_seed(iso.path)
        chk(ok2 is True, 'I2 图集图标哨兵格像素 == seed（%r）' % (bad2,))
    except Exception as ex:                                      # noqa: BLE001
        chk(False, 'I2 图标哨兵格校验异常: %r' % (ex,))


def verify_iso(path, stage='all', verbose=True):
    global orig_iso
    ok_all = True
    if verbose:
        P('=' * 96)
        P('校验 %s（stage=%s）' % (path, stage))
    if not os.path.exists(path):
        P('!! 文件不存在')
        return False
    global _results
    _results = []
    iso = L.Iso(path)
    orig = L.Iso(L.DEFAULT_ISO)
    orig_iso = orig
    seed = load_seed_meta()
    spec = load_spec()
    try:
        ents, oents = verify_structure(iso, orig)
        rep = verify_entries(iso, ents, oents, stage)
        if stage in ('font', 'text', 'elf', 'all'):
            try:
                verify_font(iso, ents, seed, stage)
            except Exception as ex:                            # noqa: BLE001
                chk(False, 'C* 字库校验异常: %r' % (ex,))
        if stage in ('text', 'all'):
            try:
                verify_text(iso, ents, stage)
            except Exception as ex:                            # noqa: BLE001
                chk(False, 'D* 文本校验异常: %r' % (ex,))
        verify_elf(iso, spec, stage)
        try:
            verify_icon_protection(iso, stage)
        except Exception as ex:  # noqa: BLE001
            chk(False, 'I* 图标保护校验异常: %r' % (ex,))
    finally:
        iso.close()
        orig.close()
    # F 回归：与 fix_spec 的 sha256
    if spec and stage in spec.get('stages', {}):
        exp = spec['stages'][stage]['sha256']
        h = sha_file(path)
        chk(h == exp, 'F1 ISO sha256 == fix_spec 阶段 %s（%s）' % (stage, exp[:16]))
    n_ok = sum(1 for ok, _ in _results if ok)
    if verbose:
        for ok, msg in _results:
            if not ok:
                P('  FAIL  ' + msg)
        P('-' * 96)
        P('断言 %d/%d 通过' % (n_ok, len(_results)))
    ok_all = all(ok for ok, _ in _results)
    return ok_all


def main(argv):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                          # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description='汉化 ISO 硬断言自证')
    ap.add_argument('--iso', default=os.path.join(REPO, 'work', 'builds', 'JS_ZH_final.iso'))
    ap.add_argument('--stage', default='all',
                    choices=['font', 'text', 'elf', 'all'])
    a = ap.parse_args(argv)
    ok = verify_iso(a.iso, a.stage)
    P('VERIFY', 'OK' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
