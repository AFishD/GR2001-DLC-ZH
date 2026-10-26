#!/usr/bin/env python3
"""run_smoke.py -- reproducible PCSX2 runtime smoke test for the Ghost Recon
Jungle Storm (SLUS-20820) localization project.

What it does
------------
1. Provisions a *clean portable* PCSX2 runtime under work/analysis/emu/runtime
   (copied from the locally installed PCSX2, e.g. %LOCALAPPDATA%\\PCSX2) so the
   user's own PCSX2 config / memory cards / logs are never touched.
2. Writes a deterministic clean PCSX2.ini (D3D12 or SW renderer, file logging on,
   keyboard pad bindings for scripted navigation, empty memory cards).
3. Boots the given ISO, lets it run for N seconds, captures the PCSX2 window at
   scheduled times through the Win32 PrintWindow API (headless-friendly, works
   without bringing the window to the foreground).
4. Classifies success from three independent signals:
      a) emulog shows the disc was booted (SYSTEM.CNF / disc serial / game name),
      b) a PCSX2 window existed and was capturable,
      c) at least one captured frame is not a blank/black image.
   Writes summary.json + screenshots + emulog into the output dir.

This tool is intentionally *offline-verification grade* (boot + render smoke,
A/B screenshot evidence). Frame-exact deterministic replay lives in the
instrumented pcsx2-gsrunner build (see docs/ANALYSIS_RUNTIME.md).

Examples
--------
    python tools\\emu\\run_smoke.py --tag baseline_en ^
        --iso "third_party\\orig\\ps2\\[PS2] Tom Clancy's Ghost Recon - Jungle Storm (U).iso" ^
        --seconds 60 --capture-at 15,30,45,60 ^
        --out work\\analysis\\emu\\baseline

    # A/B: same recipe on the Chinese build, then compare with tools\\emu\\compare_smoke.py
    python tools\\emu\\run_smoke.py --tag zh --iso work\\builds\\JS_ZH19\\JS_ZH19.iso ...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent.parent  # tools/emu -> tools -> workspace

# Default local assets (all gitignored / read-only third_party area)
DEFAULT_SOURCE_PCSX2 = Path(os.environ.get("LOCALAPPDATA", r"C:\Users\%USERNAME%\AppData\Local")) / "PCSX2"
DEFAULT_RUNTIME = WORKSPACE / "work" / "analysis" / "emu" / "runtime" / "pcsx2-qt"
BASE_PROJECT_EMU = Path(r"C:\Users\84363\Desktop\Ghost_Recon_2001_Locolization\third_party\emu")
DEFAULT_BIOS_DIR = BASE_PROJECT_EMU / "run" / "bios"
DEFAULT_BIOS = "SCPH-70012_BIOS_V12_USA_200.bin"
DEFAULT_ISO = WORKSPACE / "third_party" / "orig" / "ps2" / "[PS2] Tom Clancy's Ghost Recon - Jungle Storm (U).iso"

# Renderer ids in PCSX2 2.8: Auto=-1, DX11=3, Null=11, OGL=12, SW=13, VK=14, DX12=15
RENDERER_ID = {"auto": -1, "dx11": 3, "sw": 13, "vulkan": 14, "dx12": 15}

KEY_VK = {
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    # 字母替代方向键：Qt 可能把 Arrow 当 UI 导航吞掉，游戏菜单/OSK 用字母映射更可靠
    "t": 0x54, "g": 0x47, "f": 0x46, "h": 0x48,
    "return": 0x0D, "space": 0x20, "tab": 0x09, "escape": 0x1B,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f8": 0x77,
    "a": 0x41, "s": 0x53, "w": 0x57, "q": 0x51, "e": 0x45,
    "1": 0x31, "2": 0x32,
}


# ---------------------------------------------------------------------------
# runtime provisioning
# ---------------------------------------------------------------------------
def sha256_prefix(path: Path, nbytes: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(nbytes))
    return h.hexdigest()[:16]


def copy_tree_filtered(src: Path, dst: Path, skip_names: set[str] | None = None) -> None:
    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if skip_names and item.name in skip_names:
            continue
        target = dst / item.name
        if item.is_dir():
            copy_tree_filtered(item, target, skip_names=skip_names)
        else:
            shutil.copy2(item, target)


def provision_runtime(runtime: Path, source: Path, bios_file: Path | None,
                      force: bool = False) -> dict:
    """Create a clean portable PCSX2 runtime dir (idempotent)."""
    exe = runtime / "pcsx2-qt.exe"
    info: dict = {"runtime": str(runtime), "source": str(source), "provisioned": False}

    if exe.exists() and not force:
        info["provisioned"] = "cached"
    else:
        if not (source / "pcsx2-qt.exe").exists():
            raise FileNotFoundError(f"PCSX2 install not found: {source / 'pcsx2-qt.exe'}")
        runtime.mkdir(parents=True, exist_ok=True)
        # root binaries / configs; ReShade proxy dll and updater are deliberately skipped
        skip = {"d3d11.dll", "unins000.exe", "updater.exe", "ReShade.ini",
                "ReShade2.ini", "ReShade3.ini", "ReShade4.ini", "ReShade.log",
                "ReShade_pcsx2-qt.log"}
        for item in source.iterdir():
            if item.is_file() and item.name not in skip:
                if item.suffix.lower() in {".exe", ".dll", ".ini", ".txt", ".conf"} or item.name == "qt.conf":
                    shutil.copy2(item, runtime / item.name)
        for sub in ("resources", "QtPlugins", "D3D12", "platforms", "imageformats",
                    "iconengines", "styles", "tls", "generic", "networkinformation"):
            # translations are optional for English UI; copy if cheap
            if (source / sub).is_dir() and sub != "translations":
                copy_tree_filtered(source / sub, runtime / sub)
        info["provisioned"] = True

    # directories the emulator expects
    for sub in ("bios", "inis", "logs", "memcards", "snaps", "sstates", "cache",
                "cheats", "cheats_ni", "cheats_ws", "covers", "gamesettings",
                "inputprofiles", "patches", "textures", "videos", "utils", "cdvd-dump"):
        (runtime / sub).mkdir(parents=True, exist_ok=True)

    # portable markers => data root == runtime dir, user config untouched
    if not (runtime / "portable.txt").exists():
        (runtime / "portable.txt").write_text("", encoding="utf-8")
    if not (runtime / "portable.ini").exists():
        (runtime / "portable.ini").write_text("RunWizard=0\n", encoding="utf-8")

    # BIOS: prefer the base project's known-good USA v12 BIOS
    bios_dir = runtime / "bios"
    bios_name = DEFAULT_BIOS
    if bios_file and Path(bios_file).exists():
        shutil.copy2(bios_file, bios_dir / Path(bios_file).name)
        bios_name = Path(bios_file).name
    else:
        candidates = list(bios_dir.glob("*.bin")) + list(bios_dir.glob("*.BIN"))
        if candidates:
            bios_name = candidates[0].name
    info["bios"] = str(bios_dir / bios_name)
    info["exe"] = str(exe)
    info["exe_size"] = exe.stat().st_size if exe.exists() else 0
    info["exe_sha256_head"] = sha256_prefix(exe) if exe.exists() else ""
    return info


def write_clean_ini(runtime: Path, renderer: str = "dx12", bios_name: str = DEFAULT_BIOS,
                    framelimit: bool = True, memcard: str = "", texfilter: int = -1) -> Path:
    ini = f"""[UI]
SettingsVersion = 1
ConfirmShutdown = false
Theme = darkfusionblue
ShowToolbar = true
LockToolbar = true
ShowStatusBar = true
VerboseStatusBar = false
GameListGridView = true
HideMouseCursor = true
PauseOnFocusLoss = false

[Filenames]
BIOS = {bios_name}

[Folders]
Bios = bios
Snapshots = snaps
Savestates = sstates
MemoryCards = memcards
Logs = logs
Cheats = cheats
CheatsWS = cheats_ws
Cache = cache
Textures = textures
Covers = covers
Patches = patches

[EmuCore]
EnablePatches = true
EnableCheats = false
CdvdDumpBlocks = false
CDVDVerboseReads = false
HostFs = false
EnablePINE = false
EnableWideScreenPatches = false
EnableNoInterlacingPatches = false
BackupSavestate = false
McdFolderAutoManage = false

[MemoryCards]
Slot1_Enable = {'true' if memcard else 'false'}
Slot1_Filename = {memcard or 'Mcd001.ps2'}
Slot2_Enable = false
Slot2_Filename = Mcd002.ps2

[EmuCore/GS]
Renderer = {RENDERER_ID.get(renderer, 15)}
{('filter = %d' % texfilter) if texfilter >= 0 else ''}
UpscaleMultiplier = 1
VsyncEnable = 0
FrameLimitEnable = {'true' if framelimit else 'false'}
FramerateNTSC = 59.940000
FrameratePAL = 50.000000
AspectRatio = 4:3
FMVAspectRatioSwitch = Off
OsdShowMessages = false
OsdShowSpeed = false
OsdShowFPS = false
OsdShowCPU = false
OsdShowResolution = false
OsdShowGSStats = false
OsdShowIndicators = false
IntegerScaling = false
ScreenshotFormat = 0
ScreenshotQuality = 10

[Logging]
EnableFileLogging = true
EnableVerbose = true
EnableSystemConsole = false
EnableTimestamps = true

[Hotkeys]
Screenshot = Keyboard/F8
TogglePause = Keyboard/P
ToggleFrameLimit = Keyboard/F4
SaveStateToSlot = Keyboard/F1
LoadStateFromSlot = Keyboard/F3
GSDumpSingleFrame = Keyboard/Shift & Keyboard/F8
GSDumpMultiFrame = Keyboard/Control & Keyboard/Shift & Keyboard/F8

[InputSources]
SDL = false
XInput = false

[Pad1]
Type = DualShock2
Up = Keyboard/T
Down = Keyboard/G
Left = Keyboard/F
Right = Keyboard/H
LUp = Keyboard/T
LDown = Keyboard/G
LLeft = Keyboard/F
LRight = Keyboard/H
Select = Keyboard/Tab
Start = Keyboard/Return
L1 = Keyboard/Q
R1 = Keyboard/E
L2 = Keyboard/1
R2 = Keyboard/2
Triangle = Keyboard/W
Circle = Keyboard/S
Cross = Keyboard/Space
Square = Keyboard/A
"""
    path = runtime / "inis" / "PCSX2.ini"
    path.write_text(ini, encoding="ascii")
    return path


# ---------------------------------------------------------------------------
# smoke run
# ---------------------------------------------------------------------------
def existing_pcsx2_processes() -> list[str]:
    out = []
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32")
        # fall back to tasklist (always available, cheap)
        r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                           text=True, timeout=20)
        for line in r.stdout.splitlines():
            if "pcsx2" in line.lower():
                out.append(line.strip())
    except Exception:
        pass
    return out


def parse_emulog(log_path: Path) -> dict:
    info = {"exists": False, "size": 0, "version": None, "serial": None,
            "game_name": None, "crc": None, "boot_lines": [], "errors": []}
    if not log_path.exists():
        return info
    info["exists"] = True
    info["size"] = log_path.stat().st_size
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return info
    m = re.search(r"PCSX2 v?([0-9][0-9A-Za-z.\-]*)", text)
    if m:
        info["version"] = m.group(1)
    m = re.search(r"Disc changed to .*?\.\n.*?Name:\s*(.+?)\n.*?Serial:\s*(SLUS-\d+)\n.*?Version:\s*([0-9.]+)\n.*?CRC:\s*([0-9A-Fa-f]+)",
                  text, re.S)
    if m:
        info["game_name"] = m.group(1).strip()
        info["serial"] = m.group(2)
        info["crc"] = m.group(4).upper()
    else:
        m = re.search(r"Serial:\s*(SLUS-\d+)", text)
        if m:
            info["serial"] = m.group(1)
        m = re.search(r"Name:\s*(.+)", text)
        if m:
            info["game_name"] = m.group(1).strip()
        m = re.search(r"CRC:\s*([0-9A-Fa-f]{8})", text)
        if m:
            info["crc"] = m.group(1).upper()
    for pat in ("SYSTEM.CNF", "Boot success", "VM subsystems initialized",
                "Add .* play time", "GameDB:"):
        for line in text.splitlines():
            if re.search(pat, line):
                info["boot_lines"].append(line.strip())
                break
    for pat in ("TLB Miss", "Trap exception", "Jump to unmapped", "ReportErrorAsync",
                "RecLut", "recLUT", "GPU crashed", "Failed to create"):
        n = len(re.findall(pat, text))
        if n:
            info["errors"].append({"pattern": pat, "count": n})
    return info


def run(args) -> int:
    import wincap

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    iso = Path(args.iso)
    if not iso.exists():
        print(f"ERROR: ISO not found: {iso}", file=sys.stderr)
        return 2

    # 1) runtime -----------------------------------------------------------------
    source = Path(args.source_pcsx2)
    runtime = Path(args.runtime)
    bios_file = Path(args.bios) if args.bios else None
    prov = provision_runtime(runtime, source, bios_file, force=args.force_provision)
    memcard = ""
    if args.memcard:
        src_card = Path(args.memcard)
        if not src_card.exists():
            print(f"ERROR: memory card not found: {src_card}", file=sys.stderr)
            return 2
        dst = runtime / "memcards" / "Mcd001.ps2"
        dst.parent.mkdir(parents=True, exist_ok=True)
        import shutil as _sh
        _sh.copy2(src_card, dst)
        memcard = "Mcd001.ps2"
    ini = write_clean_ini(runtime, renderer=args.renderer,
                          bios_name=Path(prov["bios"]).name,
                          framelimit=not args.unlimited, memcard=memcard,
                          texfilter=args.texfilter)
    exe = runtime / "pcsx2-qt.exe"

    # 2) environment snapshot ----------------------------------------------------
    others = existing_pcsx2_processes()
    summary: dict = {
        "schema": "gr-js-smoke/1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "iso": {"path": str(iso), "size": iso.stat().st_size,
                "sha256_head": sha256_prefix(iso)},
        "runtime": prov,
        "clean_ini": str(ini),
        "renderer": args.renderer,
        "seconds": args.seconds,
        "capture_at": args.capture_at,
        "other_pcsx2_processes_at_start": others,
        "captures": [],
        "emulog": str(out_dir / "emulog.txt"),
        "console_log": str(out_dir / "console.txt"),
        "inputs": [],
    }

    # 3) launch ------------------------------------------------------------------
    log_path = out_dir / "emulog.txt"
    if log_path.exists():
        log_path.unlink()
    cmd = [str(exe), "-batch", "-fastboot", "-logfile", str(log_path)]
    if args.nogui:
        cmd.insert(1, "-nogui")
    if args.statefile:
        cmd += ["-statefile", str(Path(args.statefile).resolve())]
    cmd += ["--", str(iso)]

    env = dict(os.environ)
    env["PCSX2_NOCONSOLE"] = "0"
    console_path = out_dir / "console.txt"
    console_f = open(console_path, "wb")
    start = time.time()
    proc = subprocess.Popen(cmd, cwd=str(runtime), stdout=console_f,
                            stderr=subprocess.STDOUT, env=env)
    summary["command"] = cmd
    summary["pid"] = proc.pid
    print(f"[smoke] pid={proc.pid} renderer={args.renderer} seconds={args.seconds}")
    print(f"[smoke] runtime={runtime}")
    print(f"[smoke] iso={iso}")

    captures: list[dict] = []
    windows_seen: dict[str, dict] = {}
    boot_first_frame_t = None
    end_t = start + float(args.seconds)
    pending = sorted(float(x) for x in args.capture_at)
    input_queue = sorted(args.press or [], key=lambda x: x[0])
    killed = False
    snap_dir = runtime / "snaps"
    snap_dir.mkdir(parents=True, exist_ok=True)
    for old in snap_dir.glob("*.png"):
        try:
            old.unlink()
        except OSError:
            pass
    prefix = f"{args.tag}_" if args.tag else ""

    def native_screenshot(tag: str) -> dict | None:
        """Trigger PCSX2's own F8 screenshot (clean emulated framebuffer, no UI/OSD).

        Requires briefly activating the emulator window; the previous foreground
        window is restored afterwards.
        """
        wins = wincap.list_windows(proc.pid)
        main = wincap.pick_main_window(wins)
        if main is None:
            return None
        fg_before = wincap.user32.GetForegroundWindow()
        before = {p.name for p in snap_dir.glob("*.png")}
        wincap.force_focus(main.hwnd)
        time.sleep(float(args.focus_delay))
        wincap.click_window(main.hwnd)
        time.sleep(0.15)
        wincap.tap_key(main.hwnd, 0x77, 45)  # F8 = Screenshot hotkey
        new_file = None
        deadline = time.time() + 5.0
        while time.time() < deadline:
            time.sleep(0.15)
            cand = sorted(p for p in snap_dir.glob("*.png") if p.name not in before)
            if cand:
                new_file = cand[-1]
                break
        if fg_before and fg_before != main.hwnd:
            try:
                wincap.user32.SetForegroundWindow(fg_before)
            except Exception:
                pass
        if new_file is None:
            return None
        dst = out_dir / f"{prefix}native_{tag}.png"
        try:
            shutil.copy2(new_file, dst)
        except OSError:
            return None
        from PIL import Image
        try:
            img = Image.open(dst)
        except Exception:
            return None
        stats = wincap.image_stats(img)
        stats.update({"kind": "native", "tag": tag, "t": round(time.time() - start, 2),
                      "path": str(dst), "window": {"hwnd": f"0x{main.hwnd:X}",
                                                   "title": main.title, "w": main.w, "h": main.h}})
        return stats

    def window_screenshot(tag: str) -> dict | None:
        wins = wincap.list_windows(proc.pid)
        for w in wins:
            windows_seen[f"0x{w.hwnd:X}"] = {"title": w.title, "class": w.class_name,
                                             "visible": w.visible, "w": w.w, "h": w.h}
        main = wincap.pick_main_window(wins)
        if main is None:
            return None
        img = wincap.capture_window(main.hwnd)
        if img is None:
            return None
        png = out_dir / f"{prefix}window_{tag}.png"
        img.save(png)
        stats = wincap.image_stats(img)
        stats.update({"kind": "window", "tag": tag, "t": round(time.time() - start, 2),
                      "window": {"hwnd": f"0x{main.hwnd:X}", "title": main.title,
                                 "w": main.w, "h": main.h},
                      "path": str(png)})
        return stats

    def do_capture(tag: str) -> None:
        nonlocal boot_first_frame_t
        wstats = window_screenshot(tag)
        if wstats:
            captures.append(wstats)
            if not wstats["is_blank"] and boot_first_frame_t is None:
                boot_first_frame_t = wstats["t"]
            print(f"[smoke] window {tag} t={wstats['t']}s {wstats['width']}x{wstats['height']} "
                  f"mean={wstats['mean']} colors={wstats['unique_colors']} blank={wstats['is_blank']}")
        if args.native:
            nstats = native_screenshot(tag)
            if nstats:
                captures.append(nstats)
                if not nstats["is_blank"] and boot_first_frame_t is None:
                    boot_first_frame_t = nstats["t"]
                print(f"[smoke] native {tag} t={nstats['t']}s {nstats['width']}x{nstats['height']} "
                      f"mean={nstats['mean']} colors={nstats['unique_colors']} blank={nstats['is_blank']}")
            else:
                print(f"[smoke] native {tag}: no screenshot produced")

    try:
        while time.time() < end_t:
            time.sleep(0.5)
            if proc.poll() is not None:
                print(f"[smoke] PCSX2 exited early rc={proc.returncode}")
                break
            now = time.time()
            while pending and now - start >= pending[0]:
                tag = f"{int(pending[0]):03d}s"
                pending.pop(0)
                do_capture(tag)
            while input_queue and now - start >= input_queue[0][0]:
                _, keys = input_queue.pop(0)
                wins = wincap.list_windows(proc.pid)
                main = wincap.pick_main_window(wins)
                if main is None:
                    continue
                fg_before = wincap.user32.GetForegroundWindow()
                wincap.force_focus(main.hwnd)
                time.sleep(0.2)
                wincap.click_window(main.hwnd)
                time.sleep(0.15)
                for k in keys.split("+"):
                    vk = KEY_VK.get(k.strip().lower())
                    if vk is None:
                        print(f"[smoke] unknown key {k!r}")
                        continue
                    wincap.tap_key(main.hwnd, vk, hold_ms=args.key_hold)
                    time.sleep(args.key_gap / 1000.0)
                if fg_before and fg_before != main.hwnd:
                    try:
                        wincap.user32.SetForegroundWindow(fg_before)
                    except Exception:
                        pass
                summary["inputs"].append({"t": round(time.time() - start, 2), "keys": keys})
                print(f"[smoke] input t={round(time.time() - start, 1)}s keys={keys}")
            if args.live_seconds and (now - start) > args.live_seconds:
                break
        if proc.poll() is None and not args.keep:
            do_capture("final")
    finally:
        # 4) stop + reap ---------------------------------------------------------
        if proc.poll() is None and not args.keep:
            killed = True
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=30)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        console_f.close()

    # 5) verdict ------------------------------------------------------------------
    time.sleep(0.5)
    emu = parse_emulog(log_path)
    native_ok = any((not c["is_blank"]) and c.get("kind") == "native" for c in captures)
    window_render_ok = any((not c["is_blank"]) and c.get("kind") == "window" for c in captures)
    render_ok = native_ok or window_render_ok
    window_ok = any(c.get("kind") == "window" for c in captures) or bool(windows_seen)
    boot_ok = bool(emu["serial"] or emu["boot_lines"]) and emu["exists"]
    success = bool(boot_ok and window_ok and render_ok and not args.keep)
    summary.update({
        "duration_actual_s": round(time.time() - start, 2),
        "killed_by_tool": killed,
        "process_returncode": proc.returncode,
        "windows_seen": windows_seen,
        "first_nonblank_frame_t": boot_first_frame_t,
        "emulog_info": emu,
        "captures": captures,
        "verdict": {
            "boot_ok": boot_ok,
            "window_ok": window_ok,
            "native_screenshot_ok": native_ok,
            "render_ok": render_ok,
            "success": success,
        },
    })
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    (out_dir / "RUN_LOG.txt").write_text(
        f"iso={iso}\nruntime={runtime}\nrenderer={args.renderer}\n"
        f"seconds={args.seconds}\ncaptures={len(captures)}\n"
        f"serial={emu['serial']} game={emu['game_name']} crc={emu['crc']}\n"
        f"version={emu['version']}\nboot_ok={boot_ok} window_ok={window_ok} "
        f"render_ok={render_ok} SUCCESS={success}\n",
        encoding="utf-8")

    print(f"[smoke] serial={emu['serial']} game={emu['game_name']} crc={emu['crc']}")
    print(f"[smoke] captures={len(captures)} boot_ok={boot_ok} window_ok={window_ok} "
          f"render_ok={render_ok} => SUCCESS={success}")
    print(f"[smoke] summary: {out_dir / 'summary.json'}")
    return 0 if success else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iso", default=str(DEFAULT_ISO), help="PS2 ISO to boot")
    ap.add_argument("--seconds", type=float, default=60.0, help="wall-clock run time")
    ap.add_argument("--capture-at", default="15,30,45,60",
                    help="comma separated wall-clock seconds to capture at")
    ap.add_argument("--press", action="append", default=[],
                    metavar="SEC:KEY[+KEY2]",
                    help="activate the emulator window and tap keyboard keys at "
                         "wall-clock SEC, e.g. --press 25:return --press 40:down+down+space")
    ap.add_argument("--keys", default="",
                    help="comma separated shorthand for --press, e.g. \"95:return,105:space\"")
    ap.add_argument("--texfilter", type=int, default=-1,
                    help="GS texture filtering override: -1=auto/PS2(default), 0=Nearest, 1=Forced(bilinear), 3=ForcedButSprite")
    ap.add_argument("--memcard", default="",
                    help="copy a PS2 memory card (.ps2) into the clean runtime slot 1 and enable it")
    ap.add_argument("--statefile", default="",
                    help="pass a PCSX2 .p2s savestate to -statefile (deterministic A/B)")
    ap.add_argument("--key-hold", type=int, default=60,
                    help="key hold duration in ms (default 60; menus need >=120 to register reliably)")
    ap.add_argument("--key-gap", type=int, default=180,
                    help="gap between consecutive keys in a combo, ms (default 180)")
    ap.add_argument("--native", dest="native", action="store_true", default=True,
                    help="also grab clean emulated framebuffers through PCSX2's F8 "
                         "screenshot hotkey (default: on)")
    ap.add_argument("--no-native", dest="native", action="store_false",
                    help="disable native screenshots (window capture only, no focus steal)")
    ap.add_argument("--focus-delay", type=float, default=0.35,
                    help="seconds to wait after activating the emulator window")
    ap.add_argument("--out", default=str(WORKSPACE / "work" / "analysis" / "emu" / "baseline"),
                    help="output directory")
    ap.add_argument("--tag", default="", help="tag prefix for screenshot file names")
    ap.add_argument("--runtime", default=str(DEFAULT_RUNTIME))
    ap.add_argument("--source-pcsx2", default=str(DEFAULT_SOURCE_PCSX2),
                    help="installed PCSX2 dir to provision the clean runtime from")
    ap.add_argument("--bios", default=str(DEFAULT_BIOS_DIR / DEFAULT_BIOS),
                    help="BIOS file to copy into the clean runtime")
    ap.add_argument("--renderer", default="dx12", choices=sorted(RENDERER_ID))
    ap.add_argument("--unlimited", action="store_true", help="disable frame limiter")
    ap.add_argument("--nogui", action="store_true",
                    help="hide PCSX2 main window (screenshots will fall back to none)")
    ap.add_argument("--force-provision", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep emulator running (debug)")
    ap.add_argument("--live-seconds", type=float, default=0)
    args = ap.parse_args(argv)

    # parse capture list / press list
    args.capture_at = [float(x) for x in str(args.capture_at).replace(";", ",").split(",") if x.strip()]
    args.capture_at = [x for x in args.capture_at if x <= args.seconds]
    press_specs = list(args.press)
    if args.keys:
        press_specs += [s.strip() for s in args.keys.split(",") if s.strip()]
    parsed_press = []
    for spec in press_specs:
        sec_s, _, keys = spec.partition(":")
        try:
            parsed_press.append((float(sec_s), keys))
        except ValueError:
            raise SystemExit(f"bad --press spec: {spec!r}")
    args.press = parsed_press

    return run(args)


if __name__ == "__main__":
    sys.exit(main())
