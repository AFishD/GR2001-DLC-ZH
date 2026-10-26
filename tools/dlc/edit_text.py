# -*- coding: utf-8 -*-
"""文本表「dump → 改 → 反向写回」工具（对齐原版工程 text_csv 工作流）。

用法（在仓库根目录）：

    # ① dump 出可编辑的对照表（含空列 text_edited；已有的编辑不会丢）
    python tools/dlc/edit_text.py prepare

    # ② 用 Excel 打开 work/analysis/text/tables/*_bilingual.csv，只改 text_edited 列：
    #    · 想手动控制断行，在文本里写 {WRAP}（大小写不限，{Warp} 也认）→ 盘上写引擎换行 {br}
    #    · {{BTN:E0B1}} / {{BTN:E0B5}} 是手柄图标标记，别改
    #    · 正文单元格不能有真换行（需要换行用 {WRAP}/{p}/{br} 标记）

    # ③ 按表写回（从英文原盘完整重建 ISO，字体/ELF 补丁照旧叠加）
    python tools/dlc/edit_text.py inject --out work/builds/EDIT.iso --verify

    # 只校验不写盘 / 看合并结果
    python tools/dlc/edit_text.py inject --dry-run

说明：
· prepare 先调用 build.py --stage dump-text 重新 dump（默认最新 merged 译文表），
  再给每张表追加 text_edited 列（已存在则保留原内容，不覆盖你的编辑）。
· inject 读全部表：text_edited 非空 ⇒ 用编辑后文本，否则用 text_zh，合并成完整译文表，
  再调用 build.py --stage all（GRJS_TRANS=合并表）从英文原盘完整重建。
· {WRAP} 语义（对齐本体工程 round36）：人工断点 → 盘上写 {br}；
  不能出现在开头/结尾，也不能与另一个断点相邻（会产生空行）。
"""
import csv
import json
import os
import re
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))

DEFAULT_TABLES = os.path.join(REPO, 'work', 'analysis', 'text', 'tables')
MERGED_DIR = os.path.join(REPO, 'work', 'translation', 'merged')

# 表名 → resource（与 build.py dump 表一致）
TABLE_RES = {
    'lang_bilingual.csv': 'LANG',
    'sfxml_text_bilingual.csv': 'SFXML',
    'sfxml_titles_bilingual.csv': 'SFXML_TITLE',
    'mis_bilingual.csv': 'MIS',
    'atr_bilingual.csv': 'ATR',
    'strings_txt_bilingual.csv': 'STRINGS_TXT',
}

WRAP_RE = re.compile(r'\{wrap\}', re.I)
WRAP_BAD_RE = re.compile(r'\{w(?:r?a?p?|arp)[^}]*\}', re.I)


def P(msg):
    print(msg, flush=True)


def textlib():
    import textlib as T
    return T


def unesc(cell):
    T = textlib()
    try:
        return T.unesc_cell(cell)
    except ValueError:
        return cell


def esc(text):
    T = textlib()
    return T.esc_cell(text)


# ═════════════════════════ 准备：dump + 追加 text_edited 列 ═════════════════════════
def tables(directory):
    out = []
    for name, res in TABLE_RES.items():
        p = os.path.join(directory, name)
        if os.path.exists(p):
            out.append((p, res))
    return out


def add_edited_column(path):
    """给一张表追加 text_edited 列（已有则不动）。返回是否改动。"""
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    if not rows:
        return False
    header = rows[0]
    if 'text_edited' in header:
        return False
    if 'text_zh' not in header:
        return False
    idx = header.index('text_zh') + 1
    header2 = header[:idx] + ['text_edited'] + header[idx:]
    out = [header2]
    for r in rows[1:]:
        if len(r) < len(header):
            r = r + [''] * (len(header) - len(r))
        out.append(r[:idx] + [''] + r[idx:])
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        csv.writer(f, lineterminator='\r\n').writerows(out)
    return True


def _snapshot_edits(directory):
    """dump 会重写整张表 ⇒ 先按 (文件名, key) 记住 text_edited，dump 后再回填。"""
    snap = {}
    for path, _res in tables(directory):
        try:
            with open(path, 'r', encoding='utf-8-sig', newline='') as f:
                for row in csv.DictReader(f):
                    key = (row.get('key') or '').strip()
                    ed = row.get('text_edited') or ''
                    if key and ed.strip():
                        snap[(os.path.basename(path), key)] = ed
        except OSError:
            continue
    return snap


def _restore_edits(directory, snap):
    n = 0
    if not snap:
        return 0
    for path, _res in tables(directory):
        name = os.path.basename(path)
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            rows = list(csv.reader(f))
        if not rows or 'text_edited' not in rows[0]:
            continue
        i_key = rows[0].index('key')
        i_ed = rows[0].index('text_edited')
        changed = False
        for r in rows[1:]:
            if len(r) <= max(i_key, i_ed):
                continue
            v = snap.get((name, r[i_key]))
            if v and not (r[i_ed] or '').strip():
                r[i_ed] = v
                changed = True
                n += 1
        if changed:
            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                csv.writer(f, lineterminator='\r\n').writerows(rows)
    return n


def cmd_prepare(args):
    out_dir = args.tables or DEFAULT_TABLES
    trans = args.trans
    old_edits = _snapshot_edits(out_dir) if os.path.isdir(out_dir) else {}
    if not trans:
        for cand in ('translations_v21.csv', 'translations_v20.csv', 'translations_all.csv'):
            p = os.path.join(MERGED_DIR, cand)
            if os.path.exists(p):
                trans = p
                break
    os.makedirs(out_dir, exist_ok=True)
    P('=' * 84)
    P('① 重新 dump 文本表 → %s' % out_dir)
    P('   译文表: %s' % trans)
    env = dict(os.environ)
    if trans:
        env['GRJS_TRANS'] = trans
    cmd = [sys.executable, os.path.join(REPO, 'tools', 'dlc', 'build.py'),
           '--stage', 'dump-text', '--out-dir', out_dir]
    r = subprocess.run(cmd, cwd=REPO, env=env)
    if r.returncode != 0:
        P('!! dump 失败（exit %d）' % r.returncode)
        return 1
    P('② 给各表追加 text_edited 列（已有编辑会保留）')
    n = 0
    for path, _res in tables(out_dir):
        if add_edited_column(path):
            n += 1
            P('   + %s' % os.path.basename(path))
    P('   共 %d 张表追加了 text_edited 列' % n)
    if old_edits:
        k = _restore_edits(out_dir, old_edits)
        P('   已回填原有编辑 %d 条（dump 前保存的 text_edited）' % k)
    P('= 准备完成。用 Excel 打开上表，只改 text_edited 列；断行写 {WRAP}。')
    return 0


# ═════════════════════════ 校验 + 合并 ═════════════════════════
def check_wrap(text):
    """校验 {WRAP} 位置；返回错误字符串或 None。"""
    bad = None
    for m in WRAP_BAD_RE.finditer(text):
        if not WRAP_RE.fullmatch(m.group(0)):
            bad = m.group(0)
            break
    if bad:
        return '断点标记写法不对：%r（应为 {WRAP}）' % bad
    if not WRAP_RE.search(text):
        return None
    core = WRAP_RE.sub('{br}', text).strip()
    if core.startswith('{br}') or core.endswith('{br}'):
        return '{WRAP} 不能放在文本开头或结尾（会产生空行）'
    if '{br}{br}' in core:
        return '两个 {WRAP} 紧挨着（会产生空行），请删掉一个'
    if '{br}{p}' in core or '{p}{br}' in core:
        return '{WRAP} 不能与 {p} 相邻'
    return None


def normalize_text(text, where=''):
    """真换行 → {p}/{br}；{WRAP} → {br}。返回 (text, err)。"""
    T = textlib()
    raw = unesc(text)
    if '\r' in raw or '\n' in raw:
        raw = T.normalize_newlines(raw)
    err = check_wrap(raw)
    if err:
        return raw, err
    return WRAP_RE.sub('{br}', raw), None


def read_edited(directory, files=None):
    """读全部表 → (all_items, edited_items, errors)。

    all_items    : [(resource, key, text, is_edited)] —— 完整重建用（未编辑用 text_zh）
    edited_items : 只有用户改过的行（报告/往返自检用）
    """
    items = []
    all_items = []
    paths = []
    if files:
        for f in files:
            p = f if os.path.isabs(f) else os.path.join(REPO, f)
            if os.path.isdir(p):
                paths.extend(tables(p))
            else:
                paths.append((p, TABLE_RES.get(os.path.basename(p).lower())))
    else:
        paths = tables(directory)
    errors = []
    for path, res in paths:
        if not os.path.exists(path):
            continue
        if not res:
            errors.append((os.path.basename(path), '不在可识别表清单里（跳过）'))
            continue
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            rd = csv.DictReader(f)
            for row in rd:
                key = (row.get('key') or row.get('id') or '').strip()
                if not key:
                    continue
                edited = row.get('text_edited') or ''
                zh = row.get('text_zh') or ''
                if not edited.strip():
                    if zh.strip():
                        all_items.append((res, key, zh, False))
                    continue
                text, err = normalize_text(edited, key)
                if err:
                    errors.append((key, err))
                    continue
                items.append((res, key, text, os.path.basename(path)))
                all_items.append((res, key, text, True))
    return all_items, items, errors


def write_merged(all_items, out_csv):
    """完整合并表（text_edited 优先，否则 text_zh）→ 供 build.py 全量重建。"""
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    merged = {}
    for res, key, text, is_edited in all_items:
        merged[(res, key)] = (text, is_edited)
    with open(out_csv, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, lineterminator='\r\n')
        w.writerow(['resource', 'id', 'text_zh', 'source'])
        for (res, key), (text, is_edited) in merged.items():
            w.writerow([res, key, esc(text), 'edit' if is_edited else 'dump'])
    return out_csv


# ═════════════════════════ 注入 ═════════════════════════
def cmd_inject(args):
    tables_dir = args.tables or DEFAULT_TABLES
    all_items, items, errors = read_edited(tables_dir, args.csv)
    P('=' * 84)
    P('文本表反向写回')
    P('  表目录: %s' % tables_dir)
    P('  参与重建条目: %d（其中有编辑 %d 条）' % (len(all_items), len(items)))
    if errors:
        P('!! 校验失败 %d 条（不会写盘）：' % len(errors))
        for key, msg in errors[:20]:
            P('   - %s: %s' % (key, msg))
        return 1
    if not all_items:
        P('没有找到任何可注入文本。先跑 prepare 再改 text_edited。')
        return 1
    by_res = {}
    for res, _k, _t, _f in items:
        by_res[res] = by_res.get(res, 0) + 1
    P('  编辑按资源: %s' % json.dumps(by_res, ensure_ascii=False))
    merged = args.merged or os.path.join(MERGED_DIR, 'translations_edited.csv')
    write_merged(all_items, merged)
    P('  合并译文表: %s' % merged)
    if args.dry_run:
        P('  (dry-run：不写盘)')
        return 0
    out = args.out or os.path.join(REPO, 'work', 'builds', 'GR_JS_ZH_edited.iso')
    P('  从英文原盘重建 ISO → %s' % out)
    env = dict(os.environ)
    env['GRJS_TRANS'] = merged
    env['GRJS_NO_SPEC_CHECK'] = '1'     # 文本编辑盘与 fix_spec 的 FINAL sha 必然不同
    cmd = [sys.executable, os.path.join(REPO, 'tools', 'dlc', 'build.py'),
           '--stage', 'all', '--out', out, '--force', '--no-verify']
    r = subprocess.run(cmd, cwd=REPO, env=env)
    if r.returncode != 0:
        P('!! 构筑失败（exit %d）' % r.returncode)
        return r.returncode
    P('= 写回完成：%s' % out)
    if args.verify:
        return verify_roundtrip(out, items, merged)
    return 0


def verify_roundtrip(iso, items, merged):
    """把写回后的盘重新 dump 到临时目录，核对编辑条目是否落盘。"""
    import glob
    P('  往返自检：重新 dump 校对…')
    tmp = os.path.join(REPO, 'work', 'analysis', 'text', '_roundtrip')
    os.makedirs(tmp, exist_ok=True)
    for f in glob.glob(os.path.join(tmp, '*.csv')):
        os.remove(f)
    env = dict(os.environ)
    env['GRJS_DUMP_ISO'] = iso
    env['GRJS_TRANS'] = merged
    env['GRJS_NO_SPEC_CHECK'] = '1'
    r = subprocess.run([sys.executable, os.path.join(REPO, 'tools', 'dlc', 'build.py'),
                        '--stage', 'dump-text', '--out-dir', tmp], cwd=REPO, env=env)
    if r.returncode != 0:
        P('  !! 重新 dump 失败')
        return r.returncode
    got = {}
    for path, res in tables(tmp):
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                k = (row.get('key') or '').strip()
                if k:
                    got[(res, k)] = row.get('text_zh') or ''
    bad, ok = [], 0
    for res, key, text, _fn in items:
        want = text.strip()
        have = got.get((res, key))
        if have is None:
            bad.append((key, 'dump 里找不到'))
            continue
        if have.strip() == want:
            ok += 1
        else:
            bad.append((key, '不一致: 盘上 %r / 期望 %r' % (have[:50], want[:50])))
    if bad:
        P('!! 往返自检失败 %d 条：' % len(bad))
        for k, m in bad[:15]:
            P('   - %s: %s' % (k, m))
        return 1
    P('  往返自检通过：%d 条全部落盘 ✓' % ok)
    return 0


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description='文本表 dump→编辑→写回（支持 {WRAP} 人工断行）')
    sub = ap.add_subparsers(dest='cmd')

    p1 = sub.add_parser('prepare', help='重新 dump 并在各表追加 text_edited 列')
    p1.add_argument('--tables', help='表目录（默认 work/analysis/text/tables）')
    p1.add_argument('--trans', help='合并译文表 CSV（默认最新 merged）')

    p2 = sub.add_parser('inject', help='按编辑后的表写回 ISO')
    p2.add_argument('--tables', help='表目录（默认 work/analysis/text/tables）')
    p2.add_argument('--csv', nargs='*', help='只读这些表（不给=整个表目录）')
    p2.add_argument('--merged', help='合并译文表输出路径')
    p2.add_argument('--out', help='输出 ISO（默认 work/builds/GR_JS_ZH_edited.iso）')
    p2.add_argument('--dry-run', action='store_true', help='只校验/合并不写盘')
    p2.add_argument('--verify', action='store_true', help='写入后重新 dump 做往返自检')

    args = ap.parse_args(argv)
    if args.cmd == 'prepare':
        return cmd_prepare(args)
    if args.cmd == 'inject':
        return cmd_inject(args)
    ap.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
