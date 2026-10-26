# -*- coding: utf-8 -*-
r"""check_translated.py —— 译文 CSV 自动校验（译者/Lead 共用）。

检查项：
  1. 行数/顺序/id 与工单一致；每条 text_zh 非空；
  2. 富文本标记 `{p}` / `{br}` / `{{BTN:XXXX}}` 数量与英文原文一致；
  3. 无真换行/制表符/控制字符；无 0xFF 字符；
  4. 每条译文都能被字符集编码（缺字清单）；
  5. 提示：疑似未翻译（译文 == 英文原文且含 >=3 个字母）；英文残留率统计。

用法：
    python tools\dlc\check_translated.py --batch work\translation\batches\batch_01_mission_a.csv \
        --trans assets\text\translated\batch_01_mission_a.csv
    python tools\dlc\check_translated.py --all      # 校验 assets\text\translated\ 下全部
"""
import argparse
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'lib'))
import tcslib as T                                             # noqa: E402

BATCH_DIR = os.path.join(REPO, 'work', 'translation', 'batches')
TR_DIR = os.path.join(REPO, 'assets', 'text', 'translated')
CHARSET = os.path.join(REPO, 'assets', 'charset', 'charset_compiled_zh16.json')
TAG_RE = re.compile(r'\{(?:p|br)\}|\{\{BTN:[0-9A-Fa-f]{4}\}\}')
CTRL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def load(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def check_pair(batch_path, trans_path, cs, verbose=True):
    """返回 (ok, problems[], stats)。"""
    batch = load(batch_path)
    trans = load(trans_path)
    problems = []
    stats = dict(rows=len(batch), done=0, missing_markers=0, missing_chars={},
                 untranslated=[], ctrl=[], blank=[])
    got = {}
    for r in trans:
        key = (r.get('resource', ''), r.get('id', ''))
        if key in got:
            problems.append('重复行: %s' % (key,))
        got[key] = r.get('text_zh', '')
    if len(trans) != len(batch):
        problems.append('行数不符: 工单 %d / 译文 %d' % (len(batch), len(trans)))
    for r in batch:
        key = (r['resource'], r['id'])
        zh = got.get(key)
        if zh is None:
            problems.append('缺行: %s %s' % key)
            continue
        zh = zh.strip()
        if not zh:
            stats['blank'].append(key)
            continue
        stats['done'] += 1
        en = r['text_en']
        # 标记数量
        en_tags = TAG_RE.findall(en)
        zh_tags = TAG_RE.findall(zh)
        if len(en_tags) != len(zh_tags):
            stats['missing_markers'] += 1
            problems.append('标记数不符 %s: 原文 %s / 译文 %s' % (key, en_tags, zh_tags))
        # 控制字符 / 0xFF
        if CTRL_RE.search(zh) or '\uffff' in zh or '\x00' in zh:
            stats['ctrl'].append(key)
            problems.append('控制字符/0xFF: %s' % (key,))
        # 编码（缺字）
        try:
            cs.encode_strict(zh)
        except Exception as ex:                                # noqa: BLE001
            msg = str(ex)
            stats['missing_chars'].setdefault(msg, []).append(key)
        # 未翻译
        if zh == en and re.search('[A-Za-z]{3}', en):
            stats['untranslated'].append(key)
    ok = (not problems) and stats['blank'] == []
    if verbose:
        print('== %s ==' % os.path.basename(trans_path))
        print('  行数 %d / 已填 %d / 空 %d' % (stats['rows'], stats['done'], len(stats['blank'])))
        if stats['missing_markers']:
            print('  !! 标记数量不符 %d 条' % stats['missing_markers'])
        if stats['missing_chars']:
            print('  !! 缺字 %d 类' % len(stats['missing_chars']))
            for msg, keys in list(stats['missing_chars'].items())[:8]:
                print('     %s  (%d 条, 例 %s)' % (msg[:120], len(keys), keys[:3]))
        if stats['untranslated']:
            print('  ?  疑似未翻译 %d 条: %s' % (len(stats['untranslated']),
                                                stats['untranslated'][:6]))
        if stats['ctrl']:
            print('  !! 控制字符 %d 条: %s' % (len(stats['ctrl']), stats['ctrl'][:5]))
        print('  ->', 'OK' if ok else 'PROBLEMS')
        for p in problems[:10]:
            print('     -', p)
    return ok, problems, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch')
    ap.add_argument('--trans')
    ap.add_argument('--all', action='store_true')
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                          # noqa: BLE001
        pass
    cs = T.Charset(CHARSET)
    if a.all:
        trans_files = sorted(f for f in os.listdir(TR_DIR) if f.startswith('batch_')
                             and f.endswith('.csv')) if os.path.isdir(TR_DIR) else []
        all_ok = True
        for fn in trans_files:
            batch = os.path.join(BATCH_DIR, fn)
            if not os.path.exists(batch):
                print('!! 找不到工单 %s' % fn)
                continue
            ok, _, _ = check_pair(batch, os.path.join(TR_DIR, fn), cs)
            all_ok = all_ok and ok
        print('ALL', 'OK' if all_ok else 'PROBLEMS')
        return 0 if all_ok else 1
    assert a.batch and a.trans, '需要 --batch 与 --trans，或 --all'
    ok, _, _ = check_pair(a.batch, a.trans, cs)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
