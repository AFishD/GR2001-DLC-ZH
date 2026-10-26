# -*- coding: utf-8 -*-
r"""patch_zh142_ike.py — GR_ZH142 的数据改动：NTSC_IKE.RES 里
SPECIAL_FEATURES_GR_PS2 屏的两个字段：
  1) TEXT 组件宽度 270 -> 286（折行宽度 +16px = 一个全角字）；
  2) 同屏面板底图 pda-lcd-02.rsb 目标宽 290.0 -> 306.0（右边框随文字右移 16px，
     使 286 宽度下的墨迹仍在面板内；见 out\pixel_budget_final.json）。

背景（指令级/数据级证据见 docs/REPORT_WRAP_ATLAS.md §A）：
  * 折行宽度 wrapW = comp[0x40] - comp[0xB4]，comp[0xB4]=0，comp[0x40]=组件宽；
  * 组件宽 270 来自 MENU.IMG#282 NTSC_IKE.RES 的 IKE 布局记录：
      TEXT @blob 0x27AB8  x=35 y=173 w=270 h=190，紧随其后的是屏名
      "SPECIAL_FEATURES_GR_PS2"（= 特别收录 → 武器/奖章 内页）；
  * 面板底图在同一屏的 image 对象 pda-lcd-02.rsb：rect=(25,160,290,210)；
  * 所以这是**纯数据**改动：ELF 0 字节、Game CRC 不变。

做法：
  解 LZO 帧 -> 改 1 个 u32 + 1 个 float（各只动 1 个非零字节）-> 只重压**含这两个字段的子流**
  （#9）-> 其余 19 个子流的压缩字节原样保留 -> 新帧 38,333 B 比原槽 38,284 B 多 49 B
  -> 把 MENU.IMG 条目表 #282 的 `stored` 改成 38,333
  （下一条目 #283 在 0x3782000，中间有 789,092 B 空隙，所以**没有任何偏移搬家**）。

用法:
  python patch_zh142_ike.py --src work\builds\GR_RELEASE\GR_ZH141.iso \
      --dst work\builds\GR_RELEASE\GR_ZH142.iso [--report out.json]
"""
import argparse
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import tcslib as T  # noqa: E402

IKE_IDX = 282
W_OFF = 0x27AC8                  # 解压 blob 里的 TEXT w 字段 (u32)
PANEL_W_OFF = 0x27A95            # 同一屏的 image 对象 (pda-lcd-02.rsb) 目标宽 (float, 1 字节对齐)
TEXT_TAG = 0x27AB8
SCREEN = b'SPECIAL_FEATURES_GR_PS2'
W_FROM, W_TO = 270, 286
PW_FROM, PW_TO = 290.0, 306.0
EXP_SRC = '23b3f95187b8fa68d540c6dc358ad06bc922da9e71a9b2d6361f2b2240ac9357'
EXP_DST = '28e4bc915774c9605eaa6071252cea1009bb6d3214a0273f7de950d176c4cd64'
EXP_STORED_OLD, EXP_STORED_NEW = 38284, 38333


def sha256(p):
    return T.sha256_file(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--dst', required=True)
    ap.add_argument('--report', default=None)
    a = ap.parse_args()

    h_src = sha256(a.src)
    if h_src != EXP_SRC:
        raise SystemExit('src sha256 %s != expected GR_ZH141 %s' % (h_src, EXP_SRC))
    iso = T.Iso(a.src)
    e = iso.img_entry(T.MENU_LBA, IKE_IDX)
    raw = iso.read(e['iso_off'], e['stored'])
    subs = T.lzo_subs(raw)
    blob = b''.join(s[0] for s in subs)
    nxt = iso.img_entry(T.MENU_LBA, IKE_IDX + 1)
    iso.close()
    assert e['stored'] == EXP_STORED_OLD, e['stored']
    assert blob[TEXT_TAG:TEXT_TAG + 5] == b'TEXT\x00'
    assert blob[TEXT_TAG + 0x80:TEXT_TAG + 0x80 + 23] == SCREEN
    x, y, w, h = struct.unpack_from('<4I', blob, TEXT_TAG + 8)
    assert (x, y, w, h) == (35, 173, 270, 190), (x, y, w, h)
    assert struct.unpack_from('<I', blob, W_OFF)[0] == W_FROM
    # 同一屏的面板底图对象: TEXT 前一条 image 记录 (pda-lcd-02.rsb) 的目标矩形
    img_tag = blob.rfind(b'pda-lcd-02.rsb', 0, TEXT_TAG)
    assert img_tag > 0
    img_base = img_tag + 14                     # IKE 记录里名字后**不**做 4 字节对齐
    px, py, pw, ph = struct.unpack_from('<4f', blob, img_base + 0x14)
    assert (px, py, pw, ph) == (25.0, 160.0, 290.0, 210.0), (px, py, pw, ph)
    assert img_base + 0x1C == PANEL_W_OFF
    assert struct.unpack_from('<f', blob, PANEL_W_OFF)[0] == PW_FROM
    slack = nxt['off'] - (e['off'] + e['stored'])
    print('[ike] #%d %s stored=%d real=%d subs=%d blob=%d ; next #%d off=0x%X slack=%d'
          % (IKE_IDX, e['name'], e['stored'], e['real'], len(subs), len(blob),
             IKE_IDX + 1, nxt['off'], slack))
    print('[rec] TEXT @0x%X  x=%d y=%d w=%d h=%d  (w @0x%X)' % (TEXT_TAG, x, y, w, h, W_OFF))
    print('[rec] panel image @0x%X  (%.1f,%.1f,%.1f,%.1f)  (w @0x%X)'
          % (img_tag, px, py, pw, ph, PANEL_W_OFF))

    # 定位子流
    base, sub_i = 0, None
    for i, s in enumerate(subs):
        if base <= W_OFF < base + len(s[0]):
            sub_i, sub_off = i, W_OFF - base
            break
        base += len(s[0])
    assert sub_i is not None
    dec = bytearray(subs[sub_i][0])
    struct.pack_into('<I', dec, sub_off, W_TO)
    # 面板底图宽 (float) —— 与 TEXT 同一条子流时只重压一次
    base2, sub_p = 0, None
    for i, s in enumerate(subs):
        if base2 <= PANEL_W_OFF < base2 + len(s[0]):
            sub_p, sub_p_off = i, PANEL_W_OFF - base2
            break
        base2 += len(s[0])
    assert sub_p is not None
    if sub_p == sub_i:
        struct.pack_into('<f', dec, sub_p_off, PW_TO)
    new_dec = bytes(dec)
    cb = T.lzo_compress(new_dec, level=7, use_m1=True, use_m4=True)
    back, err, _ = T.lzo1x_decompress(cb, out_size=len(new_dec))
    assert err is None and back == new_dec
    print('[lzo] sub #%d (real=%d): %d -> %d B (level 7)'
          % (sub_i, subs[sub_i][2], subs[sub_i][1], len(cb)))

    frame = bytearray()
    for i, (d, clen, real, hdr) in enumerate(subs):
        frame += (struct.pack('<II', len(cb), real) + cb) if i == sub_i \
            else raw[hdr:hdr + 8 + clen]
    print('[frame] %d B (slot %d, %+d)' % (len(frame), e['stored'], len(frame) - e['stored']))
    if EXP_STORED_NEW:
        assert len(frame) == EXP_STORED_NEW, len(frame)
    assert len(frame) <= e['stored'] + slack
    frame = bytes(frame)

    subs2 = T.lzo_subs(frame)
    blob2 = b''.join(s[0] for s in subs2)
    assert len(blob2) == len(blob)
    diff = [i for i in range(len(blob)) if blob[i] != blob2[i]]
    allowed = set(range(W_OFF, W_OFF + 4)) | set(range(PANEL_W_OFF, PANEL_W_OFF + 4))
    assert diff and all(i in allowed for i in diff), diff
    assert struct.unpack_from('<I', blob2, W_OFF)[0] == W_TO
    assert struct.unpack_from('<f', blob2, PANEL_W_OFF)[0] == PW_TO
    for i in range(len(blob)):
        if i not in (W_OFF, W_OFF + 1, W_OFF + 2, W_OFF + 3,
                     PANEL_W_OFF, PANEL_W_OFF + 1, PANEL_W_OFF + 2, PANEL_W_OFF + 3):
            assert blob[i] == blob2[i], i
    print('[check] decompressed blob differs only inside the two fields: %s'
          % ['0x%X' % i for i in diff])

    if os.path.exists(a.dst):
        os.remove(a.dst)
    import shutil
    shutil.copyfile(a.src, a.dst)
    tab = T.MENU_LBA * T.SEC + T.TAB_OFF + T.TAB_STEP * IKE_IDX + 24
    with open(a.dst, 'r+b') as f:
        f.seek(tab)
        f.write(struct.pack('<I', EXP_STORED_NEW))
        f.seek(e['iso_off'])
        f.write(frame)
        f.flush()
        os.fsync(f.fileno())
    h_dst = sha256(a.dst)
    print('[write] %s  sha256 %s' % (a.dst, h_dst))
    if os.path.basename(a.src) == 'GR_ZH141.iso' and EXP_DST != 'TBD':
        assert h_dst == EXP_DST, 'dst sha256 %s != %s' % (h_dst, EXP_DST)
        print('[check] dst sha256 == GR_ZH142 (declared)')
    if a.report:
        json.dump(dict(src=a.src, dst=a.dst, src_sha256=h_src, dst_sha256=h_dst,
                       ike_idx=IKE_IDX, stored_from=EXP_STORED_OLD, stored_to=EXP_STORED_NEW,
                       frame=len(frame), sub=sub_i, sub_off=sub_off,
                       w_off=W_OFF, rect=[x, y, W_TO, h],
                       panel_name='pda-lcd-02.rsb', panel_off=PANEL_W_OFF,
                       panel_from=PW_FROM, panel_to=PW_TO,
                       panel_rect=[px, py, PW_TO, ph],
                       entry_table_off=tab, container_iso_off=e['iso_off'],
                       blob_diff=diff),
                  open(a.report, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('-> %s' % a.report)


main()
