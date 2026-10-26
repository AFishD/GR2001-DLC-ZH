# -*- coding: utf-8 -*-
r"""js19_atlas_introspect.py — JS19 图集几何自证：打印 cell 位图 + 行/列边界检测。

用法:
  python tools/recovery/js19_atlas_introspect.py cells      # 按 elf-analyst 公式打印前 24 格
  python tools/recovery/js19_atlas_introspect.py rowprof    # 每行 ink 与 cell 宽度剖面
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'font'))
import dlclib as L            # noqa: E402
import fontlib as F           # noqa: E402

JS = os.path.join(REPO, 'work', 'analysis', 'js19')
P_PAK = os.path.join(JS, 'payloads', '00009_COMMON.PAK.bin')

# elf-analyst 从 JS19 cave 反汇编得到的几何（VA 见 docs）
NCOL, CW, CH = 62, 8, 16
Y0, X0 = 2, 2
SKIP_ROW, SKIP_ROWS = 12, 3
PAIR_BASE = 224


def atlas_tex():
    pak = open(P_PAK, 'rb').read()
    recs = L.parse_pak_records(pak)
    r = [x for x in recs if x['name'] == 'new_font_revised'][0]
    cont = pak[r['px_off']:r['px_off'] + r['px']]
    tex, empty, pk, segs = F.atlas_engine_image(cont, 512, 512, 19)
    return tex == 0


def cell_xy(slot):
    row, col = slot // NCOL, slot % NCOL
    y = Y0 + CH * (row + (SKIP_ROWS if row >= SKIP_ROW else 0))
    x = X0 + CW * col
    return row, col, x, y


def cell_ink(ink, slot):
    row, col, x, y = cell_xy(slot)
    return ink[y:y + CH, x:x + CW]


def cmd_cells():
    ink = atlas_tex()
    for slot in range(0, 32):
        row, col, x, y = cell_xy(slot)
        c = cell_ink(ink, slot)
        print('slot %3d row %2d col %2d (x=%3d,y=%3d) ink=%3d' % (slot, row, col, x, y, int(c.sum())))
        for yy in range(CH):
            print('   ' + ''.join('#' if c[yy, xx] else '.' for xx in range(CW)))
        if slot >= 7:
            break


def cmd_rowprof():
    ink = atlas_tex()
    print('=== 每 grid 行：y、各格 ink 统计、非空格数 ===')
    for row in range(0, 30):
        y = Y0 + CH * (row + (SKIP_ROWS if row >= SKIP_ROW else 0))
        if y + CH > 512:
            print('row %2d y=%3d 超出图集' % (row, y))
            continue
        counts = [int(ink[y:y + CH, X0 + CW * c:X0 + CW * (c + 1)].sum()) for c in range(NCOL)]
        print('row %2d y=%3d ink=%4d nonempty=%2d  min/max=%3d/%3d  counts[:12]=%s'
              % (row, y, sum(counts), sum(1 for v in counts if v), min(counts), max(counts), counts[:12]))
    # 按整数列检测：整幅图 x 方向 ink 投影
    print('\n=== x 方向 ink 投影（每 1 px）===')
    cols = ink.sum(0)
    print(' '.join('%d' % v for v in cols))


if __name__ == '__main__':
    globals()['cmd_' + (sys.argv[1] if len(sys.argv) > 1 else 'cells')]()
