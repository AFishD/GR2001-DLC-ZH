# -*- coding: utf-8 -*-
"""nav_squad.py —— 从开机走到「小队设置 / 队员信息 / 武器信息」并逐界面截图。

复用 nav_briefing.py 的实测路径先到战役 C01「简介」页，然后继续：
    简介页 --Cross--> 小队设置 --Cross--> 自动分配/名册 --Dpad上--> 选中队员
    --Circle--> 队员信息 --R1--> 选装备 --Circle--> 武器信息
每一步都做「画面变化判定 + 稳定帧判定」，每个界面保存 2~3 张 2100x1106 PNG。

本机按键绑定（写死在 run_smoke.write_clean_ini 的 [Pad1] 里，脚本会把该节写进
run.json 作为证据；运行时再用「按一下看画面变化」实测校准，见 run.json['key_evidence']）：
    Cross=space  Circle=s  Triangle=w  Square=a
    Up=t  Down=g  Left=f  Right=h
    L1=q  R1=e  L2=1  R2=2  Start=return  Select=tab

用法：
    python tools\\emu\\nav_squad.py --iso work\\builds\\FINAL\\GR_JS_ZH_v23_candidate.iso \
        --out work\\analysis\\emu\\squad_v23 [--diag]

    --diag  额外保存每一步的逐帧观察图、并在最后逐个试按方向键/其它键做映射标定
"""
import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import wincap  # noqa: E402
import run_smoke as RS  # noqa: E402

user32 = ctypes.WinDLL('user32', use_last_error=True)
EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

THUMB = (160, 120)
SIG_TOP = 0.16            # 比较模板时去掉左上角 OSD 区域


def children(hwnd):
    out = []

    def cb(h, _lp):
        out.append(h)
        return True

    user32.EnumChildWindows(hwnd, EnumChildProc(cb), 0)
    return out


def biggest_child(hwnd):
    best, best_area = None, 0
    for h in children(hwnd):
        r = wintypes.RECT()
        if not user32.GetClientRect(h, ctypes.byref(r)):
            continue
        a = (r.right - r.left) * (r.bottom - r.top)
        if a > best_area:
            best, best_area = h, a
    return best, best_area


def content_box(img):
    """动态找游戏画面列范围（窗口右侧可能是纯黑竖条）。"""
    g = np.asarray(img.convert('L'), dtype=np.float32)
    col = g.mean(axis=0)
    xs = np.where(col > 4.0)[0]
    w, h = img.size
    if len(xs) == 0:
        return (0, 0, w, h)
    x0, x1 = int(xs[0]), int(xs[-1]) + 1
    if not (1.10 < (x1 - x0) / float(h) < 2.10):
        return (0, 0, w, h)
    return (x0, 0, x1, h)


def crop_content(img):
    """裁掉窗口右侧的黑色竖条，只留游戏画面。"""
    return img.crop(content_box(img))


def thumb(img):
    c = crop_content(img)
    w, h = c.size
    return np.asarray(c.crop((0, int(SIG_TOP * h), w, h)).convert('L').resize(THUMB),
                      dtype=np.float32)


def imgdiff(a, b):
    """0..255 灰度缩略图的平均绝对差。"""
    return float(np.abs(a - b).mean())


def bigdiff(a, b):
    """整帧（去掉 OSD 区）的差分，用于检测高亮/文字变化。"""
    return imgdiff(thumb(a), thumb(b))


def yellow_count(img):
    a = np.asarray(img.convert('RGB'), dtype=np.int16)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    return int(((r > 170) & (g > 140) & (b < 110)).sum())


def highlight_bands(img, ymin=0.12):
    """金色高亮横条（菜单选中行/标题条）。返回 [(yc_norm, y0, y1, width_px), ...]。

    实测配色：选中行底色约 (157,121,31)，比边框暗；所以阈值放宽到 r>135。
    左上角 RTSS OSD 的橙字也会成条，用 ymin=0.12 排除。
    """
    a = np.asarray(img.convert('RGB'), dtype=np.int16)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    m = (r > 135) & (g > 100) & (b < 90) & ((r - b) > 60)
    h = m.shape[0]
    rowcnt = m.sum(axis=1)
    rows = np.where(rowcnt > 80)[0]
    if len(rows) == 0:
        return []
    groups = []
    s = prev = rows[0]
    for y in rows[1:]:
        if y - prev <= 8:
            prev = y
            continue
        groups.append((s, prev))
        s = prev = y
    groups.append((s, prev))
    out = []
    for y0, y1 in groups:
        if y1 - y0 + 1 < 18:
            continue
        yc = (y0 + y1) / 2.0 / h
        if yc < ymin:
            continue
        cols = np.where(m[y0:y1 + 1].any(axis=0))[0]
        out.append((round(yc, 4), int(y0), int(y1), int(cols[-1] - cols[0] + 1)))
    return out


def top_band(img):
    """最可能的菜单选中行：取最宽的金色横条。"""
    bands = highlight_bands(img)
    if not bands:
        return None
    return max(bands, key=lambda b: b[3])


def bar_y_norm(img):
    a = np.asarray(img.convert('RGB'), dtype=np.int16)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    m = (r > 170) & (g > 140) & (b < 110)
    h, w = m.shape
    sub = m[int(h * 0.15):int(h * 0.95), int(w * 0.18):int(w * 0.62)]
    ys, xs = np.nonzero(sub)
    if len(ys) < 300:
        return None
    return float(ys.mean()) / (h * 0.8)


def patch_ini_osd(ini_path):
    """write_clean_ini 没写 OsdShowHardwareInfo 等新键，默认是开的，会盖住左上角
    中文文字；这里显式全部关掉。"""
    txt = ini_path.read_text(encoding='ascii', errors='replace')
    extra = ('OsdShowHardwareInfo = false\n'
             'OsdShowFrameTimes = false\n'
             'OsdShowGPU = false\n'
             'OsdShowGPUStats = false\n'
             'OsdShowVPS = false\n'
             'OsdShowVersion = false\n'
             'OsdShowSettings = false\n'
             'OsdShowInputs = false\n')
    if 'OsdShowHardwareInfo' not in txt:
        txt = txt.replace('[EmuCore/GS]\n', '[EmuCore/GS]\n' + extra, 1)
        ini_path.write_text(txt, encoding='ascii', errors='replace')
    return ini_path


def _fmt4(v):
    return 'None' if v is None else '%.4f' % v


class Runner(object):
    def __init__(self, args):
        self.args = args
        self.iso = Path(args.iso).resolve()
        self.out = Path(args.out).resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.runtime = Path(args.runtime).resolve()
        self.method = args.input
        self.hold = 0.07
        self.t0 = time.time()
        self.proc = None
        self.mw = None
        self.rw = None
        self.frames = 0
        self.steps = []
        self.key_evidence = {}
        self.logf = open(str(self.out / 'run.log'), 'w', encoding='utf-8')
        self.ini_text = ''

    # ---------------------------------------------------------------- logging
    def log(self, msg):
        line = '[%7.1f] %s' % (time.time() - self.t0, msg)
        try:
            print(line, flush=True)
        except Exception:
            print(line.encode('ascii', 'replace').decode('ascii'), flush=True)
        self.logf.write(line + '\n')
        self.logf.flush()

    # ------------------------------------------------------------------- boot
    def start(self):
        # 先杀掉可能残留的 pcsx2
        try:
            subprocess.run(['taskkill', '/IM', 'pcsx2-qt.exe', '/F', '/T'],
                           capture_output=True, timeout=20)
        except Exception:
            pass
        prov = RS.provision_runtime(self.runtime, Path(RS.DEFAULT_SOURCE_PCSX2),
                                    Path(RS.DEFAULT_BIOS_DIR / RS.DEFAULT_BIOS),
                                    force=False)
        memcard = ''
        mc = REPO / 'reference' / 'Mcd001.ps2'
        if mc.exists():
            dst = self.runtime / 'memcards' / 'Mcd001.ps2'
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(mc, dst)
            memcard = 'Mcd001.ps2'
        ini = RS.write_clean_ini(self.runtime, renderer='dx12',
                                 bios_name=Path(prov['bios']).name,
                                 framelimit=True, memcard=memcard, texfilter=-1)
        patch_ini_osd(Path(ini))
        self.ini_text = Path(ini).read_text(encoding='ascii', errors='replace')
        if '[Pad1]' in self.ini_text:
            self.log('PAD1 ' + ' | '.join(
                ln.strip() for ln in self.ini_text.split('[Pad1]')[1].split('[Hotkeys]')[0].splitlines()
                if ln.strip()))

        log_path = self.out / 'emulog.txt'
        if log_path.exists():
            log_path.unlink()
        exe = self.runtime / 'pcsx2-qt.exe'
        cmd = [str(exe), '-batch', '-fastboot', '-logfile', str(log_path), '--', str(self.iso)]
        self.console = open(self.out / 'console.txt', 'wb')
        self.proc = subprocess.Popen(cmd, cwd=str(self.runtime),
                                     stdout=self.console, stderr=subprocess.STDOUT,
                                     env=dict(os.environ))
        self.log('boot pid=%d iso=%s out=%s' % (self.proc.pid, self.iso.name, self.out))

    def stop(self):
        try:
            if self.proc and self.proc.poll() is None:
                subprocess.run(['taskkill', '/PID', str(self.proc.pid), '/T', '/F'],
                               capture_output=True, timeout=30)
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        except Exception:
            pass
        try:
            self.console.close()
        except Exception:
            pass

    # ---------------------------------------------------------------- capture
    def windows(self):
        if self.mw is None:
            for _ in range(120):
                if self.proc.poll() is not None:
                    return None, None
                w = wincap.pick_main_window(wincap.list_windows(self.proc.pid))
                if w:
                    self.mw = w
                    break
                time.sleep(0.5)
        if self.mw is not None and self.rw is None:
            ch, a = biggest_child(self.mw.hwnd)
            if ch and a > 10000:
                self.rw = ch
        return self.mw, self.rw

    def grab(self):
        self.windows()
        if self.mw is None:
            return None
        for attempt in range(4):
            img = wincap.capture_window(self.rw or self.mw.hwnd, mode=2)
            if img is not None:
                return img.convert('RGB')
            # 窗口可能被重建（分辨率切换/崩溃），重新枚举
            if attempt == 1:
                self.mw = None
                self.rw = None
                self.windows()
                if self.mw is None:
                    return None
            time.sleep(0.3)
        return None

    def save(self, img, name):
        p = self.out / (name + '.png')
        img.save(str(p))
        self.frames += 1
        return p

    # ------------------------------------------------------------------ press
    def press(self, key, method=None, hold=None):
        self.windows()
        if self.mw is None:
            return False
        method = method or self.method
        hold = self.hold if hold is None else hold
        vk = RS.KEY_VK[key]
        if method in ('post', 'postchild'):
            hwnd = self.mw.hwnd
            if method == 'postchild' and self.rw:
                hwnd = self.rw
            wincap.post_key(hwnd, vk, keyup=False)
            time.sleep(hold)
            wincap.post_key(hwnd, vk, keyup=True)
        else:
            wincap.force_focus(self.mw.hwnd)
            time.sleep(0.05)
            wincap.tap_key(self.mw.hwnd, vk, int(hold * 1000))
        return True

    def keycal(self):
        """标定：在单人游戏子菜单上测「按键按住多久 = 移动几行」。

        实测本作菜单是逐帧采样：按 70ms（30fps 下 2~3 帧）会一次跳 2 行，
        直接影响队员选择/武器列表，所以要把 1 行对应的按住时间量出来。
        """
        self.start()
        try:
            self.boot_to_mainmenu()
            self.press('space', method='post')
            time.sleep(3.0)
            img = self.grab()
            self.save(img, 'kc_00_spmenu')
            self.log('KC base band=%s yellow=%d'
                     % ((top_band(img) or [None])[0], yellow_count(img)))
            results = []
            for hold in (0.010, 0.020, 0.030, 0.040, 0.055, 0.070, 0.100):
                # 先回到第 0 行
                for _ in range(6):
                    b = top_band(self.grab())
                    if b is None or b[0] < 0.26:
                        break
                    self.press('t', hold=0.07)
                    time.sleep(0.9)
                b0 = top_band(self.grab())
                y0 = b0[0] if b0 else None
                self.press('g', hold=hold)
                time.sleep(1.0)
                b1 = top_band(self.grab())
                y1 = b1[0] if b1 else None
                step = None if (y0 is None or y1 is None) else round((y1 - y0) / 0.0625, 2)
                self.log('KC hold=%3.0fms band %s -> %s rows=%s' % (hold * 1000, _fmt4(y0), _fmt4(y1), step))
                results.append({'hold_ms': hold * 1000, 'band_before': y0,
                                'band_after': y1, 'rows': step})
            (self.out / 'keycal.json').write_text(
                json.dumps({'note': 'rows = 每次按 Down 移动的行数（1 行≈0.0625 yc）',
                            'results': results}, ensure_ascii=False, indent=2),
                encoding='utf-8')
            self.log('KC done')
        finally:
            self.stop()

    def kc_step(self, key, method, tag, wait=1.6):
        before = self.grab()
        bb = top_band(before)
        b = bb[0] if bb else None
        y0 = yellow_count(before)
        self.press(key, method=method)
        time.sleep(wait)
        after = self.grab()
        ab = top_band(after)
        a = ab[0] if ab else None
        y1 = yellow_count(after)
        d = bigdiff(before, after)
        moved = b is not None and a is not None and abs(a - b) > 0.02
        name = 'kc_%s_%s' % (tag, method)
        self.save(after, name)
        self.log('KC %-5s %-9s band %s -> %s moved=%s diff=%5.2f yellow %d -> %d'
                 % (key, method, _fmt4(b), _fmt4(a), moved, d, y0, y1))
        return {'key': key, 'method': method, 'band_before': b, 'band_after': a,
                'moved': moved, 'diff': round(d, 2), 'yellow_before': y0,
                'yellow_after': y1, 'file': name + '.png'}

    def boot_to_mainmenu(self):
        ref = thumb(Image.open(REPO / 'work' / 'analysis' / 'emu' / 'refs' / 'mainmenu.png'))
        last_key = 0.0
        t_start = time.time()
        while time.time() - t_start < 400:
            img = self.grab()
            if img is None:
                time.sleep(0.8)
                continue
            t = time.time() - t_start
            d = imgdiff(thumb(img), ref)
            y = yellow_count(img)
            if d < 10.0 and y > 3000:
                self.save(img, 'step_00_mainmenu')
                self.log('STATE mainmenu d=%.2f yellow=%d' % (d, y))
                return img
            if t - last_key >= 1.2:
                self.press('space' if int(t / 1.2) % 2 == 0 else 'return')
                last_key = t
            time.sleep(0.6)
        raise RuntimeError('main menu not reached')

    def wait_change(self, before, timeout=6.0, th=2.0, interval=0.45):
        t_start = time.time()
        frames = []
        changed = False
        while time.time() - t_start < timeout:
            time.sleep(interval)
            img = self.grab()
            if img is None:
                continue
            d = bigdiff(before, img)
            frames.append((time.time() - t_start, img, d))
            if d >= th:
                changed = True
                break
        return changed, frames

    def settle(self, max_wait=9.0, quiet=1.2, hold_after=0.0):
        prev = self.grab()
        t_start = time.time()
        last_change = time.time()
        if prev is None:
            return None
        while time.time() - t_start < max_wait:
            time.sleep(0.5)
            img = self.grab()
            if img is None:
                continue
            if bigdiff(prev, img) > 0.9:
                last_change = time.time()
            prev = img
            if time.time() - last_change >= quiet and time.time() - t_start >= 1.0:
                break
        return prev

    def capture_group(self, tag, n=3, gap=0.9):
        """稳定帧：连续抓 n 帧，检查互相差异，存 {tag}_1..n 与 {tag}.png。"""
        imgs = []
        for _ in range(n):
            img = self.grab()
            if img is not None:
                imgs.append(img)
            time.sleep(gap)
        if not imgs:
            self.log('CAPTURE %s FAILED (no frame)' % tag)
            return []
        spread = max([bigdiff(imgs[0], im) for im in imgs] or [0.0])
        names = []
        for i, im in enumerate(imgs, 1):
            p = self.save(im, '%s_%d' % (tag, i))
            names.append(p.name)
        p = self.save(imgs[-1], tag)
        names.append(p.name)
        self.log('CAPTURE %s n=%d spread=%.2f yellow=%d files=%s size=%dx%d' % (
            tag, len(imgs), spread, yellow_count(imgs[-1]), ','.join(names),
            imgs[-1].size[0], imgs[-1].size[1]))
        self.steps.append({'tag': tag, 'files': names, 'spread': round(spread, 2),
                           'yellow': yellow_count(imgs[-1]),
                           'size': list(imgs[-1].size)})
        self.save_hint(imgs[-1], tag)
        return names

    def save_hint(self, img, tag):
        c = crop_content(img)
        w, h = c.size
        band = c.crop((0, int(h * 0.80), w, int(h * 0.985)))
        band.save(str(self.out / ('hint_%s.png' % tag)))
        self.log('HINT %s -> hint_%s.png' % (tag, tag))

    def key_test(self, key, tag, at, seconds=2.2, nframes=3, save_frames=True):
        """按一下 key，观察画面是否变化；记录到 key_evidence。"""
        before = self.grab()
        if before is None:
            return 0.0
        if save_frames and self.args.diag:
            self.save(before, 'k_%s_00_before' % tag)
        self.press(key)
        t_start = time.time()
        peak = 0.0
        frames = []
        while time.time() - t_start < seconds:
            time.sleep(0.55)
            img = self.grab()
            if img is None:
                continue
            d = bigdiff(before, img)
            peak = max(peak, d)
            frames.append(img)
            if save_frames and self.args.diag:
                self.save(img, 'k_%s_t%02d_d%03d' % (tag, int((time.time() - t_start) * 10),
                                                     min(999, int(d * 10))))
        changed = peak >= 2.0
        self.key_evidence.setdefault(key, []).append(
            {'where': at, 'tag': tag, 'peak_diff': round(peak, 2), 'changed': changed})
        self.log('KEYTEST %-2s at %-12s peak=%5.2f changed=%s' % (key, at, peak, changed))
        if not changed and self.method != 'sendinput' and at != 'brief':
            self.log('  !! key had no effect -> retry with sendinput')
            self.method = 'sendinput'
            time.sleep(0.4)
            return self.key_test(key, tag + '_si', at, seconds, nframes, save_frames)
        return peak

    # --------------------------------------------------------------- navigate
    def boot_to_brief(self):
        self.boot_to_mainmenu()
        # Cross → 单人游戏子菜单
        self.press('space')
        time.sleep(3.2)
        # 单人菜单：高亮行不一定默认在「战役」，用金色高亮条位置双向闭环到第 3 行
        # 实测 yc：0=训练 0.237 / 1=战术演习 0.299 / 2=战役 0.362 / 3=快速任务 0.424
        TARGET = 0.362
        for _ in range(14):
            img = self.grab()
            band = top_band(img)
            cur = band[0] if band else None
            self.log('  sp_menu band=%s yellow=%d hold=%.0fms method=%s'
                     % (cur, yellow_count(img), self.hold * 1000, self.method))
            if cur is None:
                break
            if abs(cur - TARGET) <= 0.02:
                break
            if cur < TARGET - 0.02:
                self.press('g')
                self.log('  -> Down(g)')
            else:
                self.press('t')
                self.log('  -> Up(t)')
            time.sleep(1.3)
            band2 = top_band(self.grab())
            cur2 = band2[0] if band2 else None
            if cur2 is not None and cur is not None:
                step = abs(cur2 - cur)
                if step > 0.09:          # 超过 1.5 行 ⇒ 按太久，缩短按住时间
                    self.hold = max(0.012, self.hold * 0.55)
                    self.log('  !! step=%.3f too big -> hold=%.0fms' % (step, self.hold * 1000))
                elif step < 0.005:
                    self.hold = min(0.12, self.hold * 1.6)
                    self.log('  !! no move -> hold=%.0fms' % (self.hold * 1000))
        img = self.grab()
        self.save(img, 'step_01_sp_menu')
        self.log('STATE sp_menu band=%s yellow=%d'
                 % ((top_band(img) or [None])[0], yellow_count(img)))
        # 战役画廊
        self.press('space')
        time.sleep(3.5)
        self.save(self.grab(), 'step_02_campaign_gallery')
        # 任务列表
        self.press('space')
        time.sleep(4.0)
        self.save(self.grab(), 'step_03_mission_list')
        # C01 → FMV → 简介页（实测简介页可能只停留 0.5~1s 就被下一屏顶掉，
        # 所以检测到「任务目标」金色标题条就立即存图，不做长时间稳定等待）
        self.press('space')
        t_start = time.time()
        img = None
        bands = []
        while time.time() - t_start < 60:
            cand = self.grab()
            if cand is None:
                time.sleep(0.3)
                continue
            if self.args.diag and time.time() - t_start < 10:
                self.save(cand, 'step_04_c01_t%02d' % int((time.time() - t_start) * 2))
            bands = highlight_bands(cand)
            if any(0.45 < b[0] < 0.85 for b in bands):
                img = cand
                break
            time.sleep(0.3)
        if img is None:
            self.save(self.grab(), 'step_04_c01_timeout')
            raise RuntimeError('brief page not reached')
        self.log('STATE brief t=%.1fs bands=%s' % (time.time() - t_start,
                                                   [b[0] for b in bands]))
        return img

    # -------------------------------------------------------------------- run
    def advance(self, key, tag, timeout=6.0, tries=2):
        """按一个键并等待画面变化；没反应就换 sendinput 重试，并记录证据。"""
        for i in range(tries + 1):
            before = self.grab()
            if before is None:
                self.log('ADV %s: no frame' % tag)
                return False
            b0 = [b[0] for b in highlight_bands(before)]
            self.press(key)
            t0 = time.time()
            changed = False
            peak = 0.0
            while time.time() - t0 < timeout:
                time.sleep(0.5)
                img = self.grab()
                if img is None:
                    continue
                d = bigdiff(before, img)
                peak = max(peak, d)
                if d >= 2.0:
                    changed = True
                    break
            after = self.grab()
            b1 = [b[0] for b in highlight_bands(after)] if after is not None else []
            self.log('ADV %-14s key=%-5s try=%d changed=%s peak=%5.2f band %s -> %s'
                     % (tag, key, i, changed, peak, b0, b1))
            self.key_evidence.setdefault(key, []).append(
                {'where': tag, 'peak_diff': round(peak, 2), 'changed': changed})
            if changed:
                return True
            if self.method != 'sendinput' and os.environ.get('GRJS_EMU_NO_SENDINPUT') != '1':
                self.method = 'sendinput'
                self.log('  !! no change -> switch to sendinput and retry')
                time.sleep(0.5)
        return False

    def wait_for_band(self, lo, hi, timeout=15.0):
        """等待屏幕上出现指定纵向位置的金色高亮条（用来认界面的关键控件）。"""
        t0 = time.time()
        last = None
        while time.time() - t0 < timeout:
            img = self.grab()
            if img is not None:
                last = img
                b = top_band(img)
                if b and lo <= b[0] <= hi:
                    return img
            time.sleep(0.4)
        return last

    def run(self):
        self.start()
        try:
            brief = self.boot_to_brief()
            self.save(brief, 'brief_1')
            time.sleep(0.25)
            b2 = self.grab() or brief
            self.save(b2, 'brief_2')
            self.save(b2, 'brief')
            self.save_hint(b2, 'brief')
            self.steps.append({'tag': 'brief', 'files': ['brief_1.png', 'brief_2.png', 'brief.png'],
                               'spread': 0.0, 'yellow': yellow_count(b2),
                               'size': list(b2.size)})
            self.log('CAPTURE brief n=2 yellow=%d size=%dx%d'
                     % (yellow_count(b2), b2.size[0], b2.size[1]))
            if self.args.sweep:
                for key in ('e', 'q'):
                    before = self.grab()
                    self.press(key)
                    time.sleep(1.0)
                    after = self.grab()
                    d = bigdiff(before, after)
                    self.save(after, 'sweep_brief_%s_d%03d' % (key, int(d * 10)))
                    self.log('SWEEP brief %-3s diff=%5.2f' % (key, d))

            # 简介页会自己推进到「小队设置」（实测 ~0.5s，被缓存的 Cross 顶掉）；
            # 10s 没动就主动按一次 Cross。
            before = self.grab()
            changed, _ = self.wait_change(before, timeout=10)
            if not changed:
                self.log('brief did not advance by itself -> press Cross')
                self.advance('space', 'cross_brief', 8)
            # 小队设置：左上「自动分配」金色按钮带 yc≈0.18
            img = self.wait_for_band(0.15, 0.21, 15)
            self.settle()
            self.capture_group('squad_setup', 3, 0.9)

            # ---- Cross → 自动分配（名册填充，右下出现职业）
            self.advance('space', 'cross_auto', 8)
            self.settle()
            self.capture_group('squad_auto', 3, 0.9)

            # ---- Dpad 上 → 选中队员
            self.key_test('t', 'up_squad', 'squad_auto', seconds=2.2)
            self.capture_group('member_selected', 2, 0.8)

            # ---- Circle → 队员信息（角色说明 / 兵种说明）
            self.advance('s', 'circle_member', 8)
            self.settle()
            self.capture_group('member_info', 3, 0.9)
            # 说明面板比可视区高，试试 Dpad 下能否滚动出后半段
            for i in range(3):
                self.press('g')
                time.sleep(1.0)
                img = self.grab()
                if img is not None:
                    self.save(img, 'member_info_scroll%d' % (i + 1))
            self.log('SCROLL member_info x3')

            # ---- Triangle 返回名册，再 R1 切到「选择队员武器」
            self.advance('w', 'triangle_back', 8)
            self.settle()
            self.capture_group('roster_back', 2, 0.8)
            # ---- R1：实测在名册上没有任何反应（peak<1.0，L1 同样），
            #      这里保留证据帧，文件名标明「不是武器界面」，避免误用。
            for key, tag in (('e', 'r1_weapon'),):
                self.advance(key, tag, 5, tries=1)
            self.settle()
            self.capture_group('weapon_select_UNREACHED_roster', 2, 0.9)
            self.advance('s', 'circle_weapon', 8)
            self.settle()
            self.capture_group('weapon_info_UNREACHED_char_desc', 3, 0.9)
            (self.out / 'WEAPON_SCREEN_NOT_REACHED.txt').write_text(
                'v23: 在小队名册（选中队员）状态下实测 R1(e)/L1(q)/Square(a)/L2(1)/R2(2)/Right(h) '
                '均无画面变化，未能进入独立「选择队员武器/武器说明」界面。\n'
                'weapon_select_UNREACHED_roster.png = 按 R1 后的名册（与之前相同）。\n'
                'weapon_info_UNREACHED_char_desc.png = 再按 Circle 打开的画面，实际是「角色说明」。\n',
                encoding='utf-8')

            # ---- 额外映射标定（不影响上面的截图）
            self.key_test('w', 'triangle_weapon', 'weapon_info', seconds=3.0)
            self.settle()
            self.key_test('g', 'down_after', 'after_triangle', seconds=2.0)
            self.key_test('f', 'left_after', 'after_triangle', seconds=2.0)
            self.key_test('h', 'right_after', 'after_triangle', seconds=2.0)
            self.key_test('a', 'square_after', 'after_triangle', seconds=2.0)
            self.key_test('1', 'l2_after', 'after_triangle', seconds=1.8)
            self.key_test('2', 'r2_after', 'after_triangle', seconds=1.8)
            self.key_test('tab', 'select_after', 'after_triangle', seconds=1.8)
            self.key_test('return', 'start_after', 'after_triangle', seconds=1.8)

            if self.args.sweep:
                # 在小队名册上逐个试按键，看看「选择队员武器」到底绑在哪个键
                self.key_test('w', 'back_to_roster', 'sweep', seconds=2.5)
                self.settle()
                for key in ('a', 'e', 'q', '1', '2', 'f', 'h', 'g', 't', 'space', 's'):
                    before = self.grab()
                    self.press(key)
                    time.sleep(1.2)
                    after = self.grab()
                    d = bigdiff(before, after)
                    self.save(after, 'sweep_%s_d%03d' % (key, int(d * 10)))
                    self.log('SWEEP roster %-5s diff=%5.2f' % (key, d))

            # 交付要求的固定名：hint_bar.png（取「选中队员」那一屏，含 ◯ 信息）
            src = self.out / 'hint_member_selected.png'
            if not src.exists():
                src = self.out / 'hint_squad_auto.png'
            if src.exists():
                shutil.copyfile(str(src), str(self.out / 'hint_bar.png'))
                self.log('HINT %s -> hint_bar.png' % src.name)
            self.log('DONE frames=%d' % self.frames)
        finally:
            self.write_json()
            self.stop()

    def write_json(self):
        data = {
            'iso': str(self.iso),
            'out': str(self.out),
            'duration_s': round(time.time() - self.t0, 1),
            'frames': self.frames,
            'size': None,
            'pad1_ini': self.ini_text.split('[Pad1]')[1].split('[Hotkeys]')[0].strip()
            if '[Pad1]' in self.ini_text else '',
            'key_evidence': self.key_evidence,
            'steps': self.steps,
        }
        (self.out / 'run.json').write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                           encoding='utf-8')


def main(argv=None):
    ap = argparse.ArgumentParser(description='导航到小队设置/队员信息/武器信息并截图')
    ap.add_argument('--iso', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--runtime', default=str(REPO / 'work' / 'emu_runtime'))
    ap.add_argument('--mode', choices=('flow', 'keycal'), default='flow')
    ap.add_argument('--input', choices=('post', 'postchild', 'sendinput'), default='post',
                    help='按键注入方式；flow 会自动从 post 回退到 sendinput')
    ap.add_argument('--diag', action='store_true', help='保存逐帧观察图 + 完整按键标定')
    ap.add_argument('--sweep', action='store_true', help='额外逐键试探（找武器界面按键）')
    args = ap.parse_args(argv)
    r = Runner(args)
    if args.mode == 'keycal':
        r.keycal()
    else:
        r.run()
    print('OUT', r.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
