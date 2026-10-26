# -*- coding: utf-8 -*-
r"""iso_tools.py — ISO9660 读取 / 安全重建 / IMG 条目扩容  库

本模块是本项目 ISO 层操作的基础库，供 make_build.py 与各补丁脚本调用。

★ 核心教训（已实机验证）
  从零构造 ISO **会失败**（RB01/RB02 两轮实验均卡在 LBA 18582），
  因为会丢失:
    · LBA 0..11    PS2 保护/授权区
    · LBA 32..37 / 48..53 / 64..65  Sony 系统数据
    · LBA 256..260 路径表（PS2 cdvd 驱动必需）
    · PVD 的 pub_id/app_id/copyright/created 等字段
  ⇒ **必须以原盘为底，只改必要部分**（RB03 验证通过）。

接口:
  IsoImage.read(path)                    解析 ISO（文件树 / LBA / 大小）
  safe_rebuild(src, dst, replace, layout) 在原盘副本上重建
  img_entry(d, lba, name)               读 IMG 内某条目的 12×u32 记录
  img_expand(d, lba, total, name, newsz) 把某条目移到 IMG 末尾并扩槽
"""
import os
import struct
import sys

SEC = 2048
TAB_OFF, TAB_STEP = 0x830, 48


# ---------------------------------------------------------------- ISO9660 读取

class IsoImage:
    """极简 ISO9660 解析器（本盘结构简单：根目录 + 一个子目录）"""

    def __init__(self, path):
        self.path = path
        self.data = open(path, 'rb').read()
        self.files = []
        self._parse()

    def _parse(self):
        d = self.data
        pvd = 16 * SEC
        assert d[pvd + 1:pvd + 6] == b'CD001', 'not an ISO9660 image'
        self.vol_size = struct.unpack_from('<I', d, pvd + 80)[0]
        self.root_lba = struct.unpack_from('<I', d, pvd + 158)[0]
        self.root_size = struct.unpack_from('<I', d, pvd + 166)[0]
        self.path_lba = struct.unpack_from('<I', d, pvd + 140)[0]
        self.path_size = struct.unpack_from('<I', d, pvd + 132)[0]
        self.files = []
        self._walk(self.root_lba, self.root_size, '')

    def _read_dir(self, lba, size):
        out = []
        data = self.data[lba * SEC: lba * SEC + size]
        i = 0
        while i < len(data):
            L = data[i]
            if L == 0:
                i = (i // SEC + 1) * SEC
                if i >= len(data):
                    break
                continue
            if i + L > len(data) or L < 34:
                break
            rec = data[i:i + L]
            ext = struct.unpack_from('<I', rec, 2)[0]
            sz = struct.unpack_from('<I', rec, 10)[0]
            out.append((rec[33:33 + rec[32]], ext, sz, rec[25]))
            i += L
        return out

    def _walk(self, lba, size, prefix):
        for nm, ext, sz, fl in self._read_dir(lba, size):
            if nm in (b'\x00', b'\x01'):
                continue
            name = nm.decode('latin-1')
            is_dir = bool(fl & 2)
            p = (prefix + '/' + name) if prefix else name
            self.files.append({'path': p, 'name': name, 'lba': ext,
                               'size': sz, 'is_dir': is_dir})
            if is_dir:
                self._walk(ext, sz, p)

    def read_file(self, path):
        for f in self.files:
            if f['path'] == path and not f['is_dir']:
                return self.data[f['lba'] * SEC: f['lba'] * SEC + f['size']]
        raise KeyError(path)

    def report(self):
        out = ['ISO %s  (卷 %d 扇区, 根目录 LBA %d)'
               % (os.path.basename(self.path), self.vol_size, self.root_lba)]
        for f in sorted(self.files, key=lambda x: x['lba']):
            out.append('  %s %-28s LBA=%-8d size=%d'
                       % ('DIR ' if f['is_dir'] else 'FILE', f['path'], f['lba'], f['size']))
        return '\n'.join(out)


# ------------------------------------------------------------------ 安全重建

def safe_rebuild(src_iso, dst_iso, replace=None, layout=None, verbose=True):
    """在原盘副本上重建 ISO

    replace: {path: bytes}   替换文件内容（可改变大小）
    layout : {path: lba}     指定新 LBA（None = 保留原 LBA）

    ★ 保留 LBA 0..255 的系统区、路径表、PVD 全部字段；
      只更新目录记录里的 LBA/大小 与 PVD 的 vol_space。
    """
    data = bytearray(open(src_iso, 'rb').read())
    img = IsoImage(src_iso)
    files = [f for f in img.files if not f['is_dir']]

    pvd = 16 * SEC
    root_lba = img.root_lba
    root_sz = img.root_size

    newlba = {}
    newsz = {}
    for f in files:
        newlba[f['path']] = (layout or {}).get(f['path'], f['lba'])
        newsz[f['path']] = len(replace[f['path']]) if (replace and f['path'] in replace) \
            else f['size']

    # 先确保容器够大
    end = len(data)
    for f in files:
        need = newlba[f['path']] * SEC + newsz[f['path']]
        if need > end:
            data.extend(b'\x00' * (need - end))
            end = need

    # 写内容（先读原内容再写，避免自覆盖）
    blobs = {}
    for f in files:
        blobs[f['path']] = (replace[f['path']] if (replace and f['path'] in replace)
                            else bytes(data[f['lba'] * SEC: f['lba'] * SEC + f['size']]))
    for f in files:
        o = newlba[f['path']] * SEC
        data[o:o + len(blobs[f['path']])] = blobs[f['path']]

    # 更新目录记录
    dirs = [(f['path'], f['lba'], f['size']) for f in img.files if f['is_dir']]
    _patch_dir(data, root_lba, root_sz, img, newlba, newsz, prefix='')
    for dp, dl, ds in dirs:
        _patch_dir(data, dl, ds, img, newlba, newsz, prefix=dp + '/')

    # PVD vol_space
    vs = (len(data) + SEC - 1) // SEC
    struct.pack_into('<I', data, pvd + 80, vs)
    struct.pack_into('>I', data, pvd + 84, vs)
    if len(data) % SEC:
        data.extend(b'\x00' * (SEC - len(data) % SEC))

    with open(dst_iso, 'wb') as fp:
        fp.write(bytes(data))
    if verbose:
        print('[iso] 重建 %s → %s (卷 %d 扇区)' % (os.path.basename(src_iso),
                                                  os.path.basename(dst_iso), vs))
    return newlba


def _patch_dir(data, lba, size, img, newlba, newsz, prefix):
    o = lba * SEC
    i = 0
    while i < size:
        L = data[o + i]
        if L == 0:
            i = (i // SEC + 1) * SEC
            if i >= size:
                break
            continue
        if L < 34:
            break
        rec = o + i
        nlen = data[rec + 32]
        nm = bytes(data[rec + 33:rec + 33 + nlen])
        if nm not in (b'\x00', b'\x01'):
            path = prefix + nm.decode('latin-1')
            if path in newlba:
                nl, ns = newlba[path], newsz[path]
                struct.pack_into('<I', data, rec + 2, nl)
                struct.pack_into('>I', data, rec + 6, nl)
                struct.pack_into('<I', data, rec + 10, ns)
                struct.pack_into('>I', data, rec + 14, ns)
        i += L


# ------------------------------------------------------- IMG 内条目操作

def img_names(d, lba):
    base = lba * SEC
    noff = struct.unpack_from('<I', d, base + 0x10)[0]
    nend = struct.unpack_from('<I', d, base + 4)[0]
    return [x.decode('latin-1') for x in d[base + noff:base + nend].split(b'\x00') if x]


def img_entry(d, lba, name):
    """返回 (idx, [12×u32])"""
    base = lba * SEC
    names = img_names(d, lba)
    i = names.index(name)
    return i, list(struct.unpack_from('<12I', d, base + TAB_OFF + TAB_STEP * i))


def img_expand(d, lba, img_total, name, new_stored, verbose=True):
    """把一个 IMG 条目搬到 IMG 末尾并扩槽

    ★ 只改该条目自己的 off/stored，其它条目完全不动。
    返回新 off。
    """
    base = lba * SEC
    names = img_names(d, lba)
    ents = [list(struct.unpack_from('<12I', d, base + TAB_OFF + TAB_STEP * i))
            for i in range(len(names))]
    fi = names.index(name)
    e = ents[fi]
    old_off, old_stored = e[8], e[6]
    assert new_stored >= old_stored, '缩槽不支持'

    end = max((x[8] + x[6]) for x in ents if x[8])
    new_off = ((end + SEC - 1) // SEC) * SEC
    assert new_off + new_stored <= img_total, '%s 空间不足' % name

    blob = bytes(d[base + old_off: base + old_off + old_stored])
    d[base + new_off: base + new_off + new_stored] = blob + b'\x00' * (new_stored - len(blob))

    to = base + TAB_OFF + TAB_STEP * fi
    struct.pack_into('<I', d, to + 4 * 8, new_off)
    struct.pack_into('<I', d, to + 4 * 6, new_stored)
    if verbose:
        print('[img] %s(0x%X) %s: off %d → %d, stored %d → %d'
              % (os.path.basename(d_lba_hint(lba)), lba, name, old_off, new_off,
                 old_stored, new_stored))
    return new_off


def d_lba_hint(lba):
    return {776286: 'MENU.IMG', 19175: 'GR.IMG'}.get(lba, 'IMG@%d' % lba)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    img = IsoImage(sys.argv[1] if len(sys.argv) > 1
                   else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     '..', '..', 'work/builds/GR_ZH87/GR_ZH87.iso'))
    print(img.report())
