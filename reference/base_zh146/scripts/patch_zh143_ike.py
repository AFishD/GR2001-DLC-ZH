# -*- coding: utf-8 -*-
r"""patch_zh143_ike.py — GR_ZH143 的数据改动：NTSC_IKE.RES 里
SPECIAL_FEATURES_GR_PS2 屏 **只有 1 个字段**：

    TEXT 组件宽度  286 -> 294   (+8px；GR_ZH142 是 270 -> 286)

同屏面板底图 pda-lcd-02.rsb 的 306.0 **不动**：
  · 286 时最宽墨迹 281 ⇒ 右缘 316，面板右缘 330 ⇒ 余 14px；
  · 294 时最宽墨迹 290 ⇒ 右缘 325 < 330 ⇒ **仍余 5px**，且 < 右侧武器预览左缘 ~338。
  见 work\builds\GR_WRAP8\out\wrap8_pixel_budget.json。

为什么只改 1 个字段（而不是像 142 那样 2 个）：面板已经按 +16px 加宽到 306，
再 +8px 的墨迹增量被这 14px 余量吃掉了 ⇒ 面板不动，ELF 0 字节，Game CRC 不变。

★ 本工具**参数化** --w（默认 294）。286+5=291..296 的折行输出逐条完全相同
  （见 out\wrap8_widths.txt），所以 --w 291 与 --w 294 渲染等价；
  仅当 --w 294 时才校验 EXP_DST（成品身份）。

做法：
  解 LZO 帧 -> 改 1 个 u32 -> 只重压**含该字段的子流**（#9）
  -> 其余 19 个子流的压缩字节原样保留 -> 把 MENU.IMG 条目表 #282 的 `stored` 改成新帧长。

用法:
  python patch_zh143_ike.py --src work\builds\GR_RELEASE\GR_ZH142.iso \
      --dst work\builds\GR_RELEASE\GR_ZH143.iso [--w 294] [--report out.json]
"""
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _repo_root(start):
    """往上找带 tools\text_csv\tcslib.py 的目录 ⇒ 同一份文件放在
    work\builds\GR_WRAP8\tools\ 与 tools\final_fix\ 下都能跑。"""
    d = start
    for _ in range(8):
        if os.path.isfile(os.path.join(d, 'tools', 'text_csv', 'tcslib.py')):
            return d
        d = os.path.dirname(d)
    raise SystemExit('repo root not found above %s' % start)


REPO = _repo_root(HERE)
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import tcslib as T  # noqa: E402

IKE_IDX = 282
W_OFF = 0x27AC8                  # 解压 blob 里的 TEXT w 字段 (u32)
PANEL_W_OFF = 0x27A95            # 面板目标宽 (float) —— 本盘**不动**
TEXT_TAG = 0x27AB8
SCREEN = b'SPECIAL_FEATURES_GR_PS2'
W_FROM = 286                     # GR_ZH142 的成品值
PW_FROM = 306.0                  # GR_ZH142 的面板值 (本盘保持)
EXP_SRC = '28e4bc915774c9605eaa6071252cea1009bb6d3214a0273f7de950d176c4cd64'
EXP_STORED_OLD = 38333
EXP_DST_294 = None               # 首次构建后回填 (见 out\patch_zh143.json)


def sha256(p):
    return T.sha256_file(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--dst', required=True)
    ap.add_argument('--w', type=int, default=294)
    ap.add_argument('--report', default=None)
    a = ap.parse_args()

    h_src = sha256(a.src)
    if h_src != EXP_SRC:
        raise SystemExit('src sha256 %s != expected GR_ZH142 %s' % (h_src, EXP_SRC))
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
    assert (x, y, w, h) == (35, 173, 286, 190), (x, y, w, h)
    assert struct.unpack_from('<I', blob, W_OFF)[0] == W_FROM
    img_tag = blob.rfind(b'pda-lcd-02.rsb', 0, TEXT_TAG)
    img_base = img_tag + 14
    px, py, pw, ph = struct.unpack_from('<4f', blob, img_base + 0x14)
    assert (px, py, pw, ph) == (25.0, 160.0, PW_FROM, 210.0), (px, py, pw, ph)
    assert img_base + 0x1C == PANEL_W_OFF
    slack = nxt['off'] - (e['off'] + e['stored'])
    print('[ike] #%d %s stored=%d real=%d subs=%d blob=%d ; next #%d off=0x%X slack=%d'
          % (IKE_IDX, e['name'], e['stored'], e['real'], len(subs), len(blob),
             IKE_IDX + 1, nxt['off'], slack))
    print('[rec] TEXT @0x%X  x=%d y=%d w=%d h=%d  (w @0x%X) -> %d'
          % (TEXT_TAG, x, y, w, h, W_OFF, a.w))
    print('[rec] panel image @0x%X  (%.1f,%.1f,%.1f,%.1f)  ** 不动 **'
          % (img_tag, px, py, pw, ph))

    base, sub_i = 0, None
    for i, s in enumerate(subs):
        if base <= W_OFF < base + len(s[0]):
            sub_i, sub_off = i, W_OFF - base
            break
        base += len(s[0])
    assert sub_i is not None
    dec = bytearray(subs[sub_i][0])
    struct.pack_into('<I', dec, sub_off, a.w)
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
    assert len(frame) <= e['stored'] + slack
    frame = bytes(frame)

    subs2 = T.lzo_subs(frame)
    blob2 = b''.join(s[0] for s in subs2)
    assert len(blob2) == len(blob)
    diff = [i for i in range(len(blob)) if blob[i] != blob2[i]]
    allowed = set(range(W_OFF, W_OFF + 4)) | set(range(PANEL_W_OFF, PANEL_W_OFF + 4))
    assert diff and all(i in allowed for i in diff), diff
    assert struct.unpack_from('<I', blob2, W_OFF)[0] == a.w
    assert struct.unpack_from('<f', blob2, PANEL_W_OFF)[0] == PW_FROM
    print('[check] decompressed blob differs only inside the width fields: %s'
          % ['0x%X' % i for i in diff])

    if os.path.exists(a.dst):
        os.remove(a.dst)
    import shutil
    shutil.copyfile(a.src, a.dst)
    tab = T.MENU_LBA * T.SEC + T.TAB_OFF + T.TAB_STEP * IKE_IDX + 24
    with open(a.dst, 'r+b') as f:
        f.seek(tab)
        f.write(struct.pack('<I', len(frame)))
        f.seek(e['iso_off'])
        f.write(frame)
        f.flush()
        os.fsync(f.fileno())
    h_dst = sha256(a.dst)
    print('[write] %s  sha256 %s' % (a.dst, h_dst))
    if a.w == 294 and EXP_DST_294:
        assert h_dst == EXP_DST_294, 'dst sha256 %s != %s' % (h_dst, EXP_DST_294)
        print('[check] dst sha256 == GR_ZH143 (declared)')
    if a.report:
        import json
        json.dump(dict(src=a.src, dst=a.dst, src_sha256=h_src, dst_sha256=h_dst,
                       ike_idx=IKE_IDX, stored_from=EXP_STORED_OLD, stored_to=len(frame),
                       frame=len(frame), sub=sub_i, sub_off=sub_off,
                       w_off=W_OFF, w_from=W_FROM, w_to=a.w,
                       rect=[x, y, a.w, h],
                       panel_name='pda-lcd-02.rsb', panel_off=PANEL_W_OFF,
                       panel_from=PW_FROM, panel_to=PW_FROM, panel_touched=False,
                       panel_rect=[px, py, pw, ph],
                       entry_table_off=tab, container_iso_off=e['iso_off'],
                       blob_diff=diff),
                  open(a.report, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('-> %s' % a.report)


main()
