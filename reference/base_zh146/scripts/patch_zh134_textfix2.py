# -*- coding: utf-8 -*-
r"""patch_zh134_textfix2.py — GR_ZH134: 文本层第二修
（M249 错字 + 三处「插入型残留」补齐）

═══ A. M249 栏错字（用户报障 #1）═══
`MENU.IMG#283 EN_SPECIAL_FEATURE.XML` 的 `<text>#24`（条目名 `M249 班用机枪`）。
现状字节（可复现）: `... AD C6 AC BF B1 A4 A2 B6 AB A1 AB BE AD CB ...`
  ⇒ 引擎画 `M249 SAW（班用突眼借）`
目标字节: `... AD C6 AC BF B1 A4 A2 A4 C6 A1 AB BE AD CB ...`
  ⇒ 引擎画 `M249 SAW（班用自动武器）`（= 用户译文；英文原文 "Squad Assault Weapon"）
差异 = **2 字节**（body[15] B6→A4, body[16] AB→C6），**等长原位改写**。

═══ B. 三处「插入型残留」补齐 ═══
GR_ZH133 那轮的「插入型修复」规则 `B1 A1 T → B1 T` 只删了 1 个 0xA1，
但**部分站点的残留不止 1 字节**（历史迁移把 `。何` 碎片留在流里）。
逐处补齐后文本回到通顺译文（与英文原文逐句对照）。

═══ 纪律 ═══
· 只动 `MENU.IMG#283` 的文本层；**ELF 0 字节**、图集 0 字节、IMG 条目表 0 字节；
· 解压总长必须保持 116486（LZO 子流尺寸固定）⇒ 差额用 `</SpecialFeatures>` 之后的
  CRLF 尾巴（纯填充区）等量冲销 —— 与 GR_ZH133 那轮同一手法；
· 幂等：对产物再跑一次 = 0 改动。

用法:
  python tools/iso_build/patch_zh134_textfix2.py --iso <src> --out <dst> --report <json>
"""
import argparse
import io
import json
import mmap
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
except Exception:                                                     # noqa: BLE001
    pass

import tcslib                                                         # noqa: E402
import font_compact as FC                                             # noqa: E402
import patch_zh133_stale_hashr as P                                   # noqa: E402

TOOL = 'tools/iso_build/patch_zh134_textfix2.py'
ROUND = 'round-zh134'
CS = os.path.join(REPO, 'tools', 'final_fix', 'assets', 'charset', 'charset_compiled_zh16.json')
XML_IDX = tcslib.XML_IDX
MENU_LBA = tcslib.MENU_LBA
SLOT_BLOB = 116486
TAIL_BYTE = b'\r\n'


class FixError(Exception):
    pass


# ── 逐处编辑: (条目号, 体内偏移, 期望旧字节 hex, 新字节 hex, 说明) ──
EDITS = [
    (24, 15, 'B6AB', 'A4C6', 'M249: 突眼借→自动（自 A2A4 / 动 C6）'),
    (25, 66, 'A8B9FD', '', 'MG3: 删残留「。何」'),
    (30, 156, 'FD', '', 'Groza: 删残留「何」'),
    (33, 92, 'A8B9FD', '', '9A-91: 删残留「。何」'),
]


def rel(p):
    try:
        r = os.path.relpath(p, REPO)
    except ValueError:
        return p.replace('\\', '/')
    return r.replace('\\', '/') if not r.startswith('..') else p.replace('\\', '/')


def read_sfxml_blob(iso):
    e = iso.img_entry(MENU_LBA, XML_IDX)
    raw = iso.read(e['iso_off'], e['stored'])
    subs = tcslib.lzo_subs(raw)
    if not subs:
        raise FixError('SFXML 容器不是 LZO 子流帧')
    return e, b''.join(s[0] for s in subs), subs


def plan(blob, log=None):
    """返回 (new_blob, applied) —— 逐处断言上下文后**一次 splice** 改写（偏移全部按原 blob）。"""
    ents = {k: (off, ln, body) for (k, off, ln, body) in tcslib.parse_sfxml(blob)}
    applied = []
    edits = []
    for (tag, off, old_hex, new_hex, note) in EDITS:
        if tag not in ents:
            raise FixError('T%04d 不在容器里' % tag)
        boff = ents[tag][0]
        i = boff + off
        old = bytes.fromhex(old_hex)
        new = bytes.fromhex(new_hex)
        cur = bytes(blob[i:i + len(old)])
        if cur != old:
            raise FixError('T%04d@%d 上下文不符: 期望 %s, 实际 %s'
                           % (tag, off, old.hex().upper(), cur.hex().upper()))
        # 必须在 <text> 体内
        if not (boff <= i and i + len(old) <= boff + ents[tag][1]):
            raise FixError('T%04d@%d 越出 <text> 体' % (tag, off))
        edits.append((i, i + len(old), new))
        applied.append(dict(tag='T%04d' % tag, body_off=boff, off=off, abs_off=i,
                            old=old.hex().upper(), new=new.hex().upper(),
                            delta=len(new) - len(old), note=note))
        if log:
            log('  [编辑] %-6s 容器偏移 %-7d 体内 %-4d  %s -> %s  (%+d B)  %s'
                % ('T%04d' % tag, i, off, old.hex().upper(), new.hex().upper(),
                   len(new) - len(old), note))
    new_blob = tcslib.splice(blob, edits)
    # 逐条重新解析并断言 <text> 个数/键序不变
    a0 = [k for (k, _o, _l, _b) in tcslib.parse_sfxml(blob)]
    a1 = [k for (k, _o, _l, _b) in tcslib.parse_sfxml(new_blob)]
    if a0 != a1:
        raise FixError('SFXML 结构变了: %d -> %d' % (len(a0), len(a1)))
    return new_blob, applied


def close_tail(blob, target_len, log=None):
    """把 `</SpecialFeatures>` 之后的 CRLF 填充区调成使总长 == target_len。"""
    t = tcslib.xml_tail_start(blob)
    body, tail = blob[:t], blob[t:]
    if set(tail) - set(b'\r\n'):
        raise FixError('XML 尾巴不是纯 CRLF 填充区 (出现其它字节)')
    need = target_len - len(body)
    if need < 0:
        raise FixError('正文已超过目标总长 (%d > %d)' % (len(body), target_len))
    if need <= len(tail):
        new_tail = tail[:need]
    else:
        new_tail = tail + (TAIL_BYTE * ((need - len(tail)) // 2 + 2))[:need - len(tail)]
    if log:
        log('  [尾巴] tail %d -> %d (%+d), 总长 %d -> %d'
            % (len(tail), len(new_tail), len(new_tail) - len(tail),
               len(blob), len(body) + len(new_tail)))
    return body + new_tail


def sha256_file(p):
    return tcslib.sha256_file(p)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--iso', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--report', default=None)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    LOG = []

    def log(s=''):
        print(s, flush=True)
        LOG.append(s)

    src, dst = os.path.abspath(a.iso), os.path.abspath(a.out)
    if src == dst:
        raise FixError('--out 不能等于 --iso')
    log('=' * 96)
    log('%s  (%s)' % (TOOL, ROUND))
    log('  源盘   %s  sha256 %s' % (rel(src), sha256_file(src)))

    iso = tcslib.Iso(src)
    try:
        e, blob, subs = read_sfxml_blob(iso)
    finally:
        iso.close()
    log('  SFXML  %s#%d  stored=%d  解压 %d B  子流 %s'
        % (e['name'], XML_IDX, e['stored'], len(blob), [s[2] for s in subs]))
    if len(blob) != SLOT_BLOB:
        raise FixError('解压总长 %d != %d' % (len(blob), SLOT_BLOB))

    new_blob, applied = plan(blob, log)
    new_blob = close_tail(new_blob, SLOT_BLOB, log)
    if len(new_blob) != len(blob):
        raise FixError('总长变了')
    na = sum(x['delta'] for x in applied)
    log('  合计: %d 处编辑, 净 %+d B (由尾巴冲销)' % (len(applied), na))

    if a.dry_run:
        log('[dry-run] 不写盘')
        return 0

    # ── 复制 + 重压 + 写回 ──
    import shutil
    if os.path.exists(dst):
        os.remove(dst)
    shutil.copyfile(src, dst)
    iso_s = tcslib.Iso(src)
    try:
        slot = FC.Slot(iso_s, 'MENU.IMG#%d' % XML_IDX, MENU_LBA, XML_IDX)
        fr, n_rep, flen, method = slot.repack(new_blob, 'MENU.IMG#%d' % XML_IDX)
        log('  [重压] 帧 %d B / 槽 %d B (方法 %s, 重压子流 %d)' % (flen, slot.slot, method, n_rep))
        if flen > slot.slot:
            raise FixError('帧超槽')
    finally:
        iso_s.close()
    with open(dst, 'r+b') as f:
        FC.Slot.write(f, e['iso_off'], e['stored'], fr)
    if os.path.getsize(dst) != os.path.getsize(src):
        raise FixError('ISO 尺寸变了')
    sha_out = sha256_file(dst)
    log('  [写盘] %s  sha256 %s' % (rel(dst), sha_out))
    rep = dict(tool=TOOL, round=ROUND, src=rel(src), src_sha256=sha256_file(src),
               out=rel(dst), out_sha256=sha_out, edits=applied, net_delta=na)
    if a.report:
        with io.open(a.report, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=1)
    log('OK — %s' % rel(dst))
    return 0


if __name__ == '__main__':
    sys.exit(main())
