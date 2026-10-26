# -*- coding: utf-8 -*-
r"""js19_blob_probe.py — 对比 JS19 与英文原盘的 LANG blob 尺寸/子流结构（注入接口参考）。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
import dlclib as L            # noqa: E402

JS = os.path.join(REPO, 'work', 'analysis', 'js19')
DLC_ISO = os.path.join(REPO, 'third_party', 'orig', 'ps2',
                       "[PS2] Tom Clancy's Ghost Recon - Jungle Storm (U).iso")


def main():
    with L.Iso(DLC_ISO) as iso:
        ents = L.img_entries(iso)
        e = ents[576]
        pl = L.entry_payload(iso, e)
        enblob = pl['blob']
        en_sub = pl['subs']
        print('EN entry stored=%d real=%d subs=%d rlen=%s'
              % (e['stored'], e['real'], len(en_sub), [x[2] for x in en_sub]))
    raw = open(os.path.join(JS, 'payloads', '00576_EN_STRINGS.RES.bin'), 'rb').read()
    js_sub = L.lzo_subs(raw)
    jsblob = b''.join(s[0] for s in js_sub)
    print('JS entry stored=%d subs=%d rlen=%s'
          % (len(raw), len(js_sub), [x[2] for x in js_sub]))
    en_ents, en_used = L.parse_lang(enblob)
    js_ents, js_used = L.parse_lang(jsblob)
    print('EN blob=%d used_end=%d tail=%d tail_all_zero=%s'
          % (len(enblob), en_used, len(enblob) - en_used,
             all(b == 0 for b in enblob[en_used:])))
    print('JS blob=%d used_end=%d tail=%d tail_all_zero=%s'
          % (len(jsblob), js_used, len(jsblob) - js_used,
             all(b == 0 for b in jsblob[js_used:])))
    print('EN entries=%d JS entries=%d' % (len(en_ents), len(js_ents)))
    # 各子流压缩率
    print('EN 子流: %s' % [(x[1], x[2]) for x in en_sub])
    print('JS 子流: %s' % [(x[1], x[2]) for x in js_sub])


if __name__ == '__main__':
    main()
