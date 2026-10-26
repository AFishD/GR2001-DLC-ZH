# -*- coding: utf-8 -*-
r"""split_translation.py —— 把翻译工作清单切成可并行处理的批次（第二版）。

输入：work/analysis/text/translation_worklist.csv（TM 预填后的工单）
      assets/text/source/mis_source.csv（MIS 的 lang_ref：有 ref 的由 LANG 自动回填）
输出：work/translation/batches/batch_<name>.csv（翻译员填 text_zh）

划分原则：每批 ~8-16K 英文字符，按资源/组语义成块（便于术语一致）。
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
SRC = os.path.join(REPO, 'work', 'analysis', 'text', 'translation_worklist.csv')
MIS_SRC = os.path.join(REPO, 'assets', 'text', 'source', 'mis_source.csv')
OUT = os.path.join(REPO, 'work', 'translation', 'batches')

GROUP_NOTE = {
    1: '多人模式·胜负提示', 2: '多人模式·胜负提示', 3: '多人模式·Mouse Hunt 规则',
    4: '多人模式·胜负提示', 5: '多人模式·胜负提示', 6: '多人模式·比分提示',
    7: '多人模式·胜负提示', 8: '多人模式·King of the Hill 提示', 9: '多人模式·胜负提示',
    10: '多人模式·Hostage 提示', 11: '多人模式·基地攻防提示',
    12: '训练场教程（武器/装备/操作）', 13: '训练场教程', 14: '训练场教程',
    15: '训练场教程', 16: '训练场教程', 17: '训练场教程', 18: '训练场教程',
    19: '战役简报·C01 Plantation', 20: '战役简报·C02 Military Camp',
    21: '战役简报·C03 High Sierra', 22: '战役简报·C04 Swamp Airfield',
    23: '战役简报·C05 Bridges', 24: '战役简报·C06 Polling Center',
    25: '战役简报·C07 Beach Resort', 26: '战役简报·C08 Mountain Stronghold',
    27: '战役简报·J01', 28: '战役简报·J02', 29: '战役简报·J03', 30: '战役简报·J04',
    31: '战役简报·J05', 32: '战役简报·J06', 33: '战役简报·J07',
    34: '多人地图·MP01 River', 35: '多人地图·MP02 Night Battle', 36: '多人地图·MP03 Train Wreck',
    37: '多人地图·MP04 Valley', 38: '多人地图·MP05 Docks', 39: '任务事件提示（目标完成/失败）',
    40: '合作地图·CP01 Hunting Lodge', 41: '合作地图·CP02 Island', 42: '合作地图·CP03 Prison',
    43: '合作地图·CP04 Island Village', 44: '合作地图·CP05 Market', 45: '多人模式规则·Defend',
    46: '多人模式规则·Firefight', 47: '多人模式规则/提示', 48: '多人模式提示',
    49: '多人模式·任务完成提示', 50: '多人模式·任务失败提示', 51: '多人模式·目标提示',
    52: '多人模式·基地防守提示', 53: '多人地图·DP01 Stronghold', 54: '多人地图·DP02 Farm Day',
    55: '多人地图·DP03 Creekbed', 56: '多人地图·DP04 Wilderness', 57: '多人地图·DP05 Ravine',
    58: '通用 UI 文案/按钮/提示/专家档案/军械说明（逐条看原文判断）',
    59: '存档/回放界面', 60: '主菜单内部标记', 61: '控制设置项',
    62: '制作人员名单（人名保留英文，职位名译中文）', 63: '文件名（保留）',
    64: '特别收录截图文件名（保留）', 65: '选项菜单', 66: '军衔', 67: '音频文件名（保留）',
}
RES_NOTE = {
    'MIS': '任务文件字段（Name/MapName/Location/Date/Time/Briefing…）',
    'SFXML': '特别收录正文（博物馆/武器介绍/专家档案等长文；含 {p}/{br} 标记）',
    'SFXML_TITLE': '特别收录标题/分类名',
    'ATR': '角色名/兵种显示名',
    'STRINGS_TXT': '武器/道具 token 的显示名',
}


def group_of(r):
    return int(r['id'].split('.')[0][1:]) if r['resource'] == 'LANG' else None


def note_of(r):
    if r['resource'] == 'LANG':
        return GROUP_NOTE.get(group_of(r), '')
    return RES_NOTE.get(r['resource'], '')


def chunks_by_chars(rows, target=15000):
    """按英文字符预算把条目切块（保持原顺序）。"""
    out, cur, n = [], [], 0
    for r in rows:
        cur.append(r)
        n += len(r['text_en'])
        if n >= target:
            out.append(cur)
            cur, n = [], 0
    if cur:
        out.append(cur)
    return out


def main():
    rows = list(csv.DictReader(open(SRC, encoding='utf-8-sig')))
    todo = [r for r in rows if r['status'] == 'todo']
    os.makedirs(OUT, exist_ok=True)

    def lang_rows(groups):
        return [r for r in todo if r['resource'] == 'LANG' and group_of(r) in groups]

    def res_rows(res):
        return [r for r in todo if r['resource'] == res]

    # MIS：有 lang_ref 的由 LANG 自动回填，只把无 ref 的交给译者
    mis_all = list(csv.DictReader(open(MIS_SRC, encoding='utf-8-sig')))
    mis_no_ref = {r['key'] for r in mis_all if not r.get('lang_ref')}
    mis_rows = [r for r in todo if r['resource'] == 'MIS'
                and r['id'].replace('MIS:', '') in mis_no_ref]

    g58 = lang_rows({58})
    g58.sort(key=lambda r: int(r['id'].split('.I')[1]))
    g58_chunks = chunks_by_chars(g58, 15000)

    ui_rows = (lang_rows(set(range(1, 12)) | set(range(12, 19)) | set(range(34, 39))
                         | set(range(40, 45)) | set(range(45, 53)) | set(range(53, 58))
                         | {59, 60, 61, 63, 64, 65, 66, 67}))
    credits_rows = lang_rows({62}) + res_rows('ATR') + res_rows('STRINGS_TXT')

    batches = {}
    batches['01_mission_a'] = lang_rows(set(range(19, 26)))
    batches['02_mission_b'] = lang_rows(set(range(26, 34))) + lang_rows({39}) + mis_rows
    for i, ch in enumerate(g58_chunks):
        batches['%02d_g58_%s' % (3 + i, 'abcde'[i])] = ch
    base = 3 + len(g58_chunks)
    batches['%02d_sfxml' % base] = res_rows('SFXML') + res_rows('SFXML_TITLE')
    batches['%02d_ui' % (base + 1)] = ui_rows
    batches['%02d_credits' % (base + 2)] = credits_rows

    total = 0
    for name, items in batches.items():
        path = os.path.join(OUT, 'batch_%s.csv' % name)
        with open(path, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f)
            w.writerow(['resource', 'id', 'text_en', 'text_zh', 'context'])
            for r in items:
                w.writerow([r['resource'], r['id'], r['text_en'], '', note_of(r)])
        chars = sum(len(r['text_en']) for r in items)
        total += len(items)
        print('%-22s %4d 条  %7d 英文字符' % (name, len(items), chars))
    print('合计 %d 条（todo %d 条；MIS 自动回填 %d 条）'
          % (total, len(todo), sum(1 for r in todo if r['resource'] == 'MIS') - len(mis_rows)))
    assigned = set(id(r) for items in batches.values() for r in items)
    miss = [r for r in todo if id(r) not in assigned
            and not (r['resource'] == 'MIS' and r['id'].replace('MIS:', '') in mis_no_ref)]
    miss = [r for r in miss if not (r['resource'] == 'MIS')]
    if miss:
        print('!! 未分配 %d 条: %s' % (len(miss), [(m['resource'], m['id']) for m in miss[:8]]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
