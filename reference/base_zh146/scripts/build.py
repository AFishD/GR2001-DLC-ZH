#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""build.py —— GR PS2 汉化《幽灵行动》**唯一正式构筑入口**。

    python tools\final_fix\build.py                  # 英文原盘 -> work\builds\FINAL\GR_ZH146.iso
    python tools\final_fix\build.py --verify-only    # 只校验现成产物，不重建

设计
----
* **流程不在本文件里**：每一阶段（工具 / 参数 / 输入 / 期望 sha256）都写在 `fix_spec.json`。
  本文件只是一个"按表跑 + 每步核对指纹 + 按引用计数删中间盘"的执行器。
  要改汉化，改 `fix_spec.json` 或 `assets/`，**不要改这里**。
* 基底**只能**是 `third_party\orig\ps2\Tom Clancy's Ghost Recon (USA).iso`
  （外部只读原盘）+ K2 cdvd 转储；禁止拿上一版汉化盘当基底（否则链条不可复现）。
* **幂等**：同一份输入跑多少次都得到同一个 sha256；`--out` 已存在且指纹正确时直接返回。
* **断言**：输入指纹、每个阶段的输出指纹、成品身份、FF 闸门，任何一项不符立刻非零退出，
  绝不"带病继续"。
* 磁盘：同一时刻最多约 4 张盘（1.6 GB/张），中间盘在最后一位消费者用完后立刻删除。

阶段
----
    [ 1] base        英文原盘 ⊕ K2 转储            -> 2400 产品线基底
    [ 2] elf         卡死修复四件套 F4/F7/F7b/OOMFIX
    [ 3] glyph_edge  字库右缘采样修正
    [ 4] stale       旧码残留追赶
    [ 5] text2       文本层修正 #2
    [ 6] profile     著=0xFF 被 XML 词法器当 EOF 的修复
    [ 7] gate_ff     0xFF 闸门（不改盘，只判定）
    [ 8] glyphs61    61 个「有码无字」补画
    [ 9] chars139    +13 个实证生字
    [10] chars140    +9 个富文本生字
    [11] enrich      富文本表注入
    [12] chars141    +3 个真字形（…  ×  惧）
    [13] merge_text  合并文本层（正文/空行/标题/LANG）
    [14] ike142      特别收录正文折行 270->286 + 面板 290->306
    [15] ike143      折行再做 +8px（286->294，面板不动）
    [16] misnames    29/40 个任务名
    [17] m15         M15 -> 白刃（v3，居中）
    [18] final       合并两条任务名线 => 正式版
"""
from __future__ import print_function

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
SPEC_PATH = os.path.join(HERE, 'fix_spec.json')
TOOL_DIRS = [HERE, os.path.join(REPO, 'tools', 'lib'),
             os.path.join(REPO, 'tools', 'text_csv')]

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


# ---------------------------------------------------------------- fingerprints
def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(1 << 22)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def md5_of(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        while True:
            b = f.read(1 << 22)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_spec(path=SPEC_PATH):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def die(msg, code=1):
    print('\n[FAIL] ' + msg)
    sys.exit(code)


def banner(text):
    print('')
    print('=' * 96)
    print(text)
    print('=' * 96)


# ---------------------------------------------------------------- environment
def child_env():
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join(TOOL_DIRS)
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env


def run_tool(tool, args, quiet=False):
    path = os.path.join(HERE, tool)
    if not os.path.isfile(path):
        path = os.path.join(REPO, 'tools', 'text_csv', tool)
    if not os.path.isfile(path):
        die('缺少工具 %s' % tool)
    cmd = [sys.executable, path] + args
    t0 = time.time()
    p = subprocess.run(cmd, cwd=REPO, env=child_env(),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = p.stdout.decode('utf-8', 'replace')
    dt = time.time() - t0
    if not quiet:
        lines = [ln for ln in out.splitlines() if ln.strip()]
        for ln in lines[-12:]:
            print('    | ' + ln)
    if p.returncode != 0:
        print(out)
        die('%s 退出码 %d' % (tool, p.returncode))
    return dt


# ---------------------------------------------------------------- stage engine
def expand(token, ctx):
    """把 @xxx 占位符换成真实路径。"""
    if not isinstance(token, str) or not token.startswith('@'):
        return token
    if token.startswith('@repo/'):
        return os.path.join(REPO, token[len('@repo/'):].replace('/', os.sep))
    if token.startswith('@outdir/'):
        p = os.path.join(ctx['outdir'], token[len('@outdir/'):].replace('/', os.sep))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p
    key = token[1:]
    if key == 'out':
        return ctx['out']
    if key == 'outdir':
        return ctx['outdir']
    if key == 'in':
        return ctx['in']
    if key == 'repo':
        return REPO
    if key in ctx['paths']:
        return ctx['paths'][key]
    die('fix_spec.json 里的占位符 %s 没有对应产物' % token)


def consumers_after(stages, index):
    """index 之后（不含 index）还会被引用的 artifact 名字。"""
    need = set()
    for st in stages[index:]:
        for a in (st.get('args') or []):
            if isinstance(a, str) and a.startswith('@') and not a.startswith('@repo/'):
                need.add(a[1:])
    return need


def build(spec, opts):
    outdir = opts.outdir
    os.makedirs(outdir, exist_ok=True)
    ctx = {'paths': {}, 'outdir': outdir, 'out': '', 'in': ''}

    # ---------------------------------------------------------------- inputs
    banner('[0] 输入（只读；先核指纹）')
    inputs = {}
    for name, meta in spec['inputs'].items():
        p = meta['path'].replace('%LOCALAPPDATA%', os.environ.get('LOCALAPPDATA', ''))
        override = getattr(opts, name, '') or ''
        if override:
            p = override
        p = p if os.path.isabs(p) else os.path.join(REPO, p)
        if not os.path.exists(p):
            die('缺少「本地自备」输入 %s:\n    %s' % (name, p))
        sz = os.path.getsize(p)
        want = meta.get('sha256')
        print('  %-9s %s  (%d B)' % (name, os.path.basename(p), sz))
        if want:
            h = sha256_of(p)
            ok = (h == want)
            print('            sha256 %s  %s' % (h, 'OK' if ok else '<<< MISMATCH'))
            if not ok:
                die('%s 指纹不符：原盘 / 转储必须是声明的那一份' % name)
        inputs[name] = p
    ctx['paths'].update(inputs)

    # ---------------------------------------------------------------- seeds
    for seed in spec.get('seeds', []):
        src = os.path.join(REPO, seed['from'].replace('/', os.sep))
        if not os.path.isfile(src):
            die('缺少 seed 源 %s' % src)
        dst = os.path.join(outdir, seed['id'] + '_seed.json')
        shutil.copyfile(src, dst)
        h = sha256_of(dst)
        if seed.get('sha256') and h != seed['sha256']:
            die('seed %s 指纹不符: %s' % (seed['id'], h))
        print('  seed  %-9s %s  sha256 %s' % (seed['id'], os.path.basename(dst), h))
        ctx['paths'][seed['id']] = dst

    stages = spec['stages']
    produced = {}

    for index, stage in enumerate(stages):
        sid = stage['id']
        banner('[%2d/%d] %-10s -- %s' % (index + 1, len(stages), sid, stage['title']))

        ins = stage.get('in') or []
        if len(ins) > 1:
            die('阶段 %s 声明了多个 in；多输入请用显式 @<id> 占位符' % sid)
        src = ctx['paths'].get(ins[0]) if ins else None
        if ins and not src:
            die('阶段 %s 的输入 %s 不存在' % (sid, ins[0]))

        if stage.get('kind') == 'gate_ff':
            if not src:
                die('gate_ff 没有输入盘')
            print('  输入 %s' % os.path.basename(src))
            run_tool('verify.py', ['--ff-gate', '--iso', src])
            produced[sid] = src
            ctx['paths'][sid] = src
            continue

        out = os.path.join(outdir, '%02d_%s.iso' % (index + 1, sid))
        ctx['in'] = src or ''
        ctx['out'] = out
        args = [expand(a, ctx) for a in (stage.get('args') or [])]
        if src:
            print('  输入 %s' % os.path.basename(src))
        print('  输出 %s' % os.path.basename(out))
        dt = run_tool(stage['tool'], args)
        if not os.path.isfile(out):
            die('阶段 %s 没有产出 %s' % (sid, out))
        h = sha256_of(out)
        exp = stage.get('expect_sha256')
        print('  sha256 %s   %.1fs' % (h, dt))
        if exp:
            if h != exp:
                die('阶段 %s 指纹不符\n    期望 %s\n    实际 %s' % (sid, exp, h))
            print('  OK    == fix_spec.json')
        produced[sid] = out
        ctx['paths'][sid] = out

        # 引用计数回收：后面没人要、也没标 keep 的中间盘，立刻删
        if not opts.keep_intermediate:
            need = consumers_after(stages, index + 1)
            for name in list(ctx['paths']):
                if name in inputs or name.startswith('charset_work'):
                    continue
                if name == sid or name in need:
                    continue
                p = ctx['paths'].pop(name)
                if os.path.isfile(p) and os.path.abspath(p) != os.path.abspath(out):
                    print('  [gc]   %s (%d B)' % (os.path.basename(p), os.path.getsize(p)))
                    os.remove(p)

    final = produced[stages[-1]['id']]
    prod = spec['product']
    banner('成品')
    size = os.path.getsize(final)
    print('  file   %s' % final)
    print('  bytes  %d' % size)
    print('  sha256 %s' % sha256_of(final))
    print('  md5    %s' % md5_of(final))
    if size != prod['bytes']:
        die('成品大小不符: %d != %d' % (size, prod['bytes']))

    if not opts.no_copy:
        dest = opts.out or os.path.join(REPO, 'work', 'builds', 'GR_RELEASE', prod['file'])
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(dest):
            if sha256_of(dest) == prod['sha256'] and os.path.abspath(dest) != os.path.abspath(final):
                print('  已存在且指纹相同，保留旧件')
                os.remove(final)
                final = dest
            elif os.path.abspath(dest) != os.path.abspath(final):
                os.remove(dest)
        if os.path.abspath(final) != os.path.abspath(dest):
            shutil.move(final, dest)
            final = dest
        print('  发布 %s  (%d B)' % (dest, os.path.getsize(dest)))
        if sha256_of(dest) != prod['sha256']:
            die('发布后的盘指纹不符')

    if not opts.keep_intermediate:
        left = [f for f in os.listdir(outdir) if f.lower().endswith('.iso')]
        if left:
            print('  [gc]   %d 张中间盘' % len(left))
            for f in left:
                os.remove(os.path.join(outdir, f))
    print('\nBUILD OK  ->  %s' % final)
    return final


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description='GR PS2 汉化 唯一正式构筑入口')
    ap.add_argument('--out', default='', help='成品路径（默认 work/builds/FINAL/GR_ZH146.iso）')
    ap.add_argument('--outdir', default='', help='中间盘目录（默认 work/builds/FINAL/_stages）')
    ap.add_argument('--eng_iso', '--eng-iso', dest='eng_iso', default='', help='英文原盘')
    ap.add_argument('--k2_dump', '--k2-dump', dest='k2_dump', default='', help='K2 cdvd 转储')
    ap.add_argument('--font_ttf', '--font-ttf', dest='font_ttf', default='', help='字形 TTF')
    ap.add_argument('--keep-intermediate', action='store_true', help='保留每个阶段的盘')
    ap.add_argument('--no-copy', action='store_true', help='不复制到 work/builds/FINAL')
    ap.add_argument('--no-verify', action='store_true', help='出盘后不跑 verify.py')
    ap.add_argument('--verify-only', action='store_true', help='只校验现成成品')
    ap.add_argument('--force', action='store_true', help='成品已存在也重建')
    a = ap.parse_args(argv)

    spec = load_spec()
    prod = spec['product']

    if a.verify_only:
        target = a.out or os.path.join(REPO, 'work', 'builds', 'FINAL', prod['file'])
        if not os.path.isfile(target):
            die('成品不存在: %s' % target)
        run_tool('verify.py', ['--iso', target], quiet=False)
        return 0

    if not a.outdir:
        a.outdir = os.path.join(REPO, 'work', 'builds', 'FINAL', '_stages')

    default_out = a.out or os.path.join(REPO, 'work', 'builds', 'FINAL', prod['file'])
    if os.path.isfile(default_out) and not a.force:
        h = sha256_of(default_out)
        if h == prod['sha256']:
            banner('已是最新（幂等）')
            print('  %s' % default_out)
            print('  sha256 %s == fix_spec.json' % h)
            print('  （要强制重建请加 --force）')
            if not a.no_verify:
                run_tool('verify.py', ['--iso', default_out])
            return 0

    final = build(spec, a)
    if not a.no_verify:
        banner('自证 (verify.py)')
        run_tool('verify.py', ['--iso', final])
    return 0


if __name__ == '__main__':
    sys.exit(main())
