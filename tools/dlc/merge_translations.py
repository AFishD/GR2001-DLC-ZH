# -*- coding: utf-8 -*-
r"""merge_translations.py —— 合并所有译文来源，产出「最终译文总表」。

来源优先级（高 → 低）：
  1. assets/text/translated/batch_*.csv   —— 本轮人工（AI）新译，按翻译规范与术语表
  2. work/analysis/text/translation_worklist.csv 的非空 text_zh —— 本体成品盘翻译记忆（TM）
  3. work/analysis/js19/js19_lang_decoded.csv —— 上一版 JS_ZH19 译文（LANG，未经校对，兜底）
  4. MIS：有 lang_ref 的字段由对应 LANG 译文自动回填

输出：
  work/translation/merged/translations_all.csv   columns: resource,id,text_zh,source
  work/translation/merged/merge_report.json      统计/冲突/缺口

用法：
    python tools\dlc\merge_translations.py
    python tools\dlc\merge_translations.py --strict   # 有缺口时退出码 1
"""
import argparse
import csv
import glob
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
WORK = os.path.join(REPO, 'work')
SRC_DIR = os.path.join(REPO, 'assets', 'text', 'source')
TR_DIR = os.path.join(REPO, 'assets', 'text', 'translated')
WORKLIST = os.path.join(WORK, 'analysis', 'text', 'translation_worklist.csv')
JS19 = os.path.join(WORK, 'analysis', 'js19', 'js19_lang_decoded.csv')
OUT_DIR = os.path.join(WORK, 'translation', 'merged')
OUT_CSV = os.path.join(OUT_DIR, 'translations_all.csv')
OUT_REPORT = os.path.join(OUT_DIR, 'merge_report.json')


def P(*a):
    print(' '.join(str(x) for x in a), flush=True)


def read_csv(path):
    with io.open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def norm_id(resource, key):
    k = (key or '').strip()
    up = k.upper()
    if up.startswith('LANG:'):
        return 'LANG', k[5:]
    if up.startswith('SFXML:'):
        return ('SFXML_TITLE' if k[6:len(k)].upper().startswith('A') else 'SFXML'), k[6:]
    if up.startswith('MIS:'):
        k = k[4:]
        # 两种写法归一：C01_X.MIS:Name / C01_X.MIS#Name
        if '#' not in k and ':' in k:
            fn, field = k.rsplit(':', 1)
            k = fn + '#' + field
        return 'MIS', k
    if up.startswith('ATR:'):
        return 'ATR', k[4:]
    if up.startswith('TXT:'):
        return 'STRINGS_TXT', k[4:]
    if up.startswith('EN_STRINGS.TXT#'):
        return 'STRINGS_TXT', k.split('#', 1)[1]
    if up in ('TXT', 'STRINGS_TXT'):
        return 'STRINGS_TXT', k
    return resource.strip().upper(), k


def fold_unencodable(text, cs):
    """把字符集里没有、但能 NFKD 拆出 ASCII 的拉丁变音字母降级为 ASCII（如 é→e、ô→o）。
    人名（制作人员名单）保留可读性；真正的汉字缺字保持原样（由字库补画流程解决）。"""
    import unicodedata
    out = []
    for ch in text:
        o = ord(ch)
        if o < 0x80 or ch in cs.enc_single or ch in cs.enc_pair:
            out.append(ch)
            continue
        base = ''.join(c for c in unicodedata.normalize('NFKD', ch)
                       if not unicodedata.combining(c))
        out.append(base if base and all(ord(c) < 0x80 for c in base) else ch)
    return ''.join(out)


def normalize_zh(text):
    """轻量术语/标点归一化（对所有来源统一执行；不碰 {p}/{br}/{{BTN:...}}）。"""
    t = text
    # 0xFF 禁忌：「著」在字符集里是单字节 0xFF（引擎 XML 词法器当 EOF）——必须换词/换字。
    # 本体成品盘的既有写法：显著→明显；其余含「著」的词也一律替换（最后兜底 著→着）。
    t = t.replace('显著', '明显').replace('著名', '知名').replace('著称', '闻名')
    t = t.replace('卓著', '卓越').replace('著作', '作品').replace('著', '着')
    # 术语统一（本体成品盘口径）
    t = t.replace('弹夹', '弹匣')
    t = t.replace('手雷', '手榴弹')
    # 英文日期 → 中文日期（含缩写月份）；例 March 20, 2010 → 2010年3月20日
    import re as _re
    _MON = {'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5,
            'june': 6, 'july': 7, 'august': 8, 'september': 9, 'october': 10,
            'november': 11, 'december': 12, 'jan': 1, 'feb': 2, 'mar': 3,
            'apr': 4, 'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'sept': 9,
            'oct': 10, 'nov': 11, 'dec': 12}
    def _date(m):
        mon = _MON.get(m.group(1).lower().rstrip('.'))
        return '%s年%d月%d日' % (m.group(3), mon, int(m.group(2))) if mon else m.group(0)
    t = _re.sub(r'(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(\d{1,2}),\s+(\d{4})', _date, t, flags=_re.I)
    # 标点：英文省略号/破折号 → 中文
    t = t.replace('...', '……')
    t = t.replace('--', '——')
    # 连续空格压缩（{p} 附近不处理）
    while '  ' in t:
        t = t.replace('  ', ' ')
    return t.strip()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--strict', action='store_true')
    a = ap.parse_args(argv)
    os.makedirs(OUT_DIR, exist_ok=True)

    # ── 读取所有来源 ──
    fresh = {}
    for fn in sorted(glob.glob(os.path.join(TR_DIR, 'batch_*.csv'))):
        rows = read_csv(fn)
        n = 0
        for r in rows:
            res, key = norm_id(r.get('resource', ''), r.get('id', ''))
            zh = (r.get('text_zh') or '').strip()
            if zh:
                fresh[(res, key)] = zh
                n += 1
        P('  fresh %-32s %3d 条' % (os.path.basename(fn), n))

    tm = {}
    for r in read_csv(WORKLIST):
        if (r.get('text_zh') or '').strip():
            res, key = norm_id(r['resource'], r['id'])
            tm[(res, key)] = r['text_zh'].strip()
    P('  TM(worklist) %d 条' % len(tm))

    js19 = {}
    if os.path.exists(JS19):
        for r in read_csv(JS19):
            zh = (r.get('text_zh_js19') or '').strip()
            en = (r.get('text_en') or '').strip()
            conf = (r.get('confidence') or '').strip()
            if not zh or zh == en:
                continue
            key = 'G%03d.I%03d' % (int(r['g']) + 1, int(r['i']))
            js19[('LANG', key)] = zh
        P('  JS19 译文 %d 条' % len(js19))

    # ── 需要翻译的 id 全集（来自 text_source.json；keep=True 的按规范保留英文，不替换）──
    source = json.load(io.open(os.path.join(SRC_DIR, 'text_source.json'),
                               encoding='utf-8'))
    needed, keep = [], set()
    for it in source['items']:
        res = it.get('resource', it.get('kind', ''))
        key = it.get('id') or it.get('key')
        if not key:
            continue
        k = norm_id(res, key)
        if it.get('keep'):
            keep.add(k)
            continue
        if not (it.get('text_en') or '').strip():
            keep.add(k)          # 原文为空：不需要翻译（注入时保持空）
            continue
        needed.append(k)
    P('  source items %d 条（translatable %d / keep %d）'
      % (len(source['items']), len(needed), len(keep)))

    # ── 合并 ──
    _T = __import__('sys'); _T.path.insert(0, os.path.join(REPO, 'tools', 'text_csv'))
    import tcslib as _tc
    _cs = _tc.Charset(os.path.join(REPO, 'assets', 'charset', 'charset_compiled_zh16.json'))
    merged, conflicts = {}, []
    stats = dict(fresh=0, tm=0, js19=0, auto_mis=0, missing=0)
    for (res, key) in needed:
        cand = []
        if (res, key) in fresh:
            cand.append(('fresh', fresh[(res, key)]))
        if (res, key) in tm:
            cand.append(('tm', tm[(res, key)]))
        if (res, key) in js19:
            cand.append(('js19', js19[(res, key)]))
        if cand:
            src, zh = cand[0]
            zh = fold_unencodable(normalize_zh(zh), _cs)
            merged[(res, key)] = (zh, src)
            stats[src] += 1
            if len(cand) > 1 and cand[0][1] != cand[1][1]:
                conflicts.append(dict(resource=res, id=key, chosen=cand[0][0],
                                      other=cand[1][0],
                                      chosen_text=zh[:60],
                                      other_text=cand[1][1][:60]))
        else:
            stats['missing'] += 1

    # ── MIS 自动回填（lang_ref → LANG 已合并译文）──
    mis_rows = read_csv(os.path.join(SRC_DIR, 'mis_source.csv'))
    mis_keys = set()
    for r in source['items']:
        res = r.get('resource', r.get('kind', ''))
        if str(res).upper() in ('MIS', 'MISSION'):
            mis_keys.add(norm_id('MIS', r.get('id') or r.get('key')))
    for r in mis_rows:
        key = r['key']
        res_key = norm_id('MIS', key)
        if res_key in merged:
            continue
        ref = (r.get('lang_ref') or '').strip()
        if ref and ('LANG', ref) in merged:
            merged[res_key] = (merged[('LANG', ref)][0], 'auto_mis')
            stats['auto_mis'] += 1
    # ── MIS 二次回填：按归一化英文与 LANG 原文匹配（MIS BriefingText 常是 LANG 简报的拷贝）──
    import re as _re
    def _norm_en(x):
        x = _re.sub(r'\s+', ' ', x or '').strip().lower()
        return (x.replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
                 .replace('\u2013', '-').replace('\u2014', '-'))
    src_en = {}
    lang_norm = {}
    for it in source['items']:
        k = norm_id(it.get('resource', it.get('kind', '')), it.get('id') or it.get('key'))
        src_en[k] = it.get('text_en') or ''
        if it.get('kind') == 'lang' and (it.get('text_en') or '').strip():
            lang_norm.setdefault(_norm_en(it['text_en']), k[1])
    import difflib
    for k in list(mis_keys):
        if k in merged or not src_en.get(k, '').strip():
            continue
        n = _norm_en(src_en[k])
        hit = lang_norm.get(n)
        if not hit:
            best = difflib.get_close_matches(n, list(lang_norm.keys()), n=1, cutoff=0.88)
            hit = lang_norm.get(best[0]) if best else None
        if hit and ('LANG', hit) in merged:
            merged[k] = (merged[('LANG', hit)][0], 'auto_mis_text')
    # ── 手工译名（极少数无 LANG 对应的短条目；见 docs/TRANSLATION_GUIDE.md 术语表）──
    MANUAL = {
        ('MIS', 'C03_HIGH_SIERRA.MIS#RecommendedGameTypes'): '16 至 36',
        ('MIS', 'C04_SWAMP_AIRFIELD.MIS#RecommendedGameTypes'): '16 至 36',
        ('MIS', 'G01_VOLCANO.MIS#Name'): 'G01 - 火山',
        ('MIS', 'G01_VOLCANO.MIS#MapName'): 'G01 火山',
        ('MIS', 'U04_MURDER.MIS#Name'): 'U04 - 谋杀',
        ('MIS', 'U04_MURDER.MIS#MapName'): 'U04 谋杀',
        ('STRINGS_TXT', 'EN_STRINGS.TXT#WPN_EXTRAAMMO'): '追加弹药',
        ('STRINGS_TXT', 'EN_STRINGS.TXT#ITM_CLAYMORE'): '定向雷',
        ('STRINGS_TXT', 'EN_STRINGS.TXT#ITM_BOMB'): '爆破装药',
        ('STRINGS_TXT', 'EN_STRINGS.TXT#No Restrictions'): '无限制',
        ('STRINGS_TXT', 'EN_STRINGS.TXT#Pistols Only'): '仅手枪',
        ('STRINGS_TXT', 'EN_STRINGS.TXT#Primary Weapons Only'): '仅主武器',
        ('STRINGS_TXT', 'EN_STRINGS.TXT#Standard Kits'): '标准装备',
        ('STRINGS_TXT', 'EN_STRINGS.TXT#Originals Only'): '仅原版',
    }
    for k, zh in MANUAL.items():
        if k in needed and k not in merged:
            merged[k] = (fold_unencodable(normalize_zh(zh), _cs), 'manual')
    # ── ATR 人名：按规范保留英文（写回原英文字节，等于不变）──
    for k in needed:
        if k[0] == 'ATR' and k not in merged:
            merged[k] = (src_en.get(k, ''), 'keep_en')

    # ── 无条件覆盖：TM 里残留英文、但界面实际可见的条目 ──
    OVERRIDE = {
        ('LANG', 'G058.I275'): '英语', ('LANG', 'G058.I276'): '法语',
        ('LANG', 'G058.I277'): '德语', ('LANG', 'G058.I278'): '意大利语',
        ('LANG', 'G058.I279'): '西班牙语', ('LANG', 'G058.I298'): '英语',
        ('LANG', 'G059.I027'): '英语', ('LANG', 'G059.I028'): '法语',
        ('LANG', 'G059.I029'): '德语', ('LANG', 'G059.I030'): '意大利语',
        ('LANG', 'G059.I031'): '西班牙语',
        ('LANG', 'G065.I008'): '模组',
        # 制作名单 G062 的职位标题（人名/公司名保留英文，见 b08 报告）
        ('LANG', 'G062.I006'): '<title>制作人',
        ('LANG', 'G062.I010'): '<title>数据管理员',
        ('LANG', 'G062.I028'): '<title>首席程序员',
        ('LANG', 'G062.I030'): '<title>程序员',
        ('LANG', 'G062.I046'): '<title>首席游戏设计师',
        ('LANG', 'G062.I074'): '<title>对白编辑',
        ('LANG', 'G062.I080'): '<title>制作经理',
        ('LANG', 'G062.I082'): '<title>制作人',
        ('LANG', 'G062.I084'): '<title>配音演员',
        ('LANG', 'G062.I126'): '<title>制作经理',
        ('LANG', 'G062.I151'): '<title>动画师',
        ('LANG', 'G062.I167'): '<title>首席测试员',
        ('LANG', 'G062.I169'): '<title>测试员',
        ('LANG', 'G062.I199'): '<title>首席测试员',
        ('LANG', 'G062.I202'): '<title>测试员',
        ('LANG', 'G062.I232'): '<title>国际制作总监',
        ('LANG', 'G062.I255'): '<title>美国市场部',
        ('LANG', 'G062.I260'): '<title>品牌经理',
        ('LANG', 'G062.I266'): '<title>市场组经理',
        ('LANG', 'G062.I292'): '<title>配音演员',
        ('LANG', 'G062.I307'): '<title>配音演员',
        ('LANG', 'G062.I334'): '<title>配音演员',
        # ATR 兵种显示名（其余 ATR 是人名，保留英文）
        ('ATR', 'MP_PLT1_ASL.ATR#ActorName'): '突击兵',
        ('ATR', 'MP_PLT1_HVYWEP.ATR#ActorName'): '支援兵',
        ('ATR', 'MP_PLT1_SNIP.ATR#ActorName'): '狙击手',
        ('ATR', '_G_DESERT_ASL.ATR#ActorName'): '突击兵',
        ('ATR', '_G_DESERT_HVYWEP.ATR#ActorName'): '支援兵',
        ('ATR', '_G_DESERT_SNIP.ATR#ActorName'): '狙击手',
        # 兵种显示名（多人模式选择界面）
        ('LANG', 'G058.I939'): '爆破',
        ('LANG', 'G058.I940'): '爆破兵',
        ('LANG', 'G058.I941'): '步枪手',
        ('LANG', 'G058.I942'): '狙击手',
        ('LANG', 'G058.I943'): '支援兵',
        # 训练任务 TAC01 简报（TM 里残留英文，界面可见）
        ('LANG', 'G048.I008'):
            '欢迎参加你的第一次战术演练。本次任务的目标是歼灭敌军。{p}'
            '该区域有敌军巡逻队。查看指挥地图可以看到，情报部门已经为你和你的小队'
            '标出了一些便于交火的射击位置。{p}另外，我们强烈建议你采用司令部预先'
            '选定的队员与武器配置，这是完成任务的最佳方案。{p}试用小队中各种不同'
            '的枪械，体会它们的操作方式。你也可以使用固定的重机枪。',
    }
    for k, zh in OVERRIDE.items():
        if k in needed:
            merged[k] = (fold_unencodable(normalize_zh(zh), _cs), 'manual_override')

    # 重新统计缺口
    missing = [('%s:%s' % k) for k in needed if k not in merged]
    stats['missing'] = len(missing)

    # ── 写出 ──
    with io.open(OUT_CSV, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['resource', 'id', 'text_zh', 'source'])
        for (res, key), (zh, src) in sorted(merged.items()):
            w.writerow([res, key, zh, src])

    report = dict(items=len(needed), merged=len(merged), stats=stats,
                  conflicts=len(conflicts), conflict_sample=conflicts[:20],
                  missing=missing[:200], missing_total=len(missing),
                  sources=dict(fresh_dir=os.path.relpath(TR_DIR, REPO),
                               tm=os.path.relpath(WORKLIST, REPO),
                               js19=os.path.relpath(JS19, REPO)))
    json.dump(report, io.open(OUT_REPORT, 'w', encoding='utf-8', newline='\n'),
              ensure_ascii=False, indent=1)
    P('')
    P('合并结果：%d / %d 条' % (len(merged), len(needed)))
    P('  来源: fresh=%d tm=%d js19=%d auto_mis=%d'
      % (stats['fresh'], stats['tm'], stats['js19'], stats['auto_mis']))
    P('  冲突（与下一优先级不同）= %d（见 report.conflict_sample）' % len(conflicts))
    P('  缺口 = %d %s' % (len(missing), missing[:10]))
    P('  输出: %s' % os.path.relpath(OUT_CSV, REPO))
    if a.strict and missing:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
