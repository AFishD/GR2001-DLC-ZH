"""Win32 window discovery + capture helpers for PCSX2 smoke tests (ctypes only).

Deliverable of task-5 (runtime verification). No external deps besides Pillow,
which the bundled DSH Python already provides.

Usage (library):
    import wincap
    wins = wincap.list_windows(pid)
    main = wincap.pick_main_window(wins)
    img = wincap.capture_window(main.hwnd)   # PIL.Image (RGBA)
    stats = wincap.image_stats(img)
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass, field
from typing import List, Optional

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

# Make this process per-monitor DPI aware *before* touching any window geometry,
# otherwise GetWindowRect / screen grabs mix logical and physical pixels on
# scaled displays (this machine runs 3840x2160 @ 200%).
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
except Exception:
    pass

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.GetCurrentThreadId.restype = wt.DWORD

# ---------------------------------------------------------------------------
# prototypes
# ---------------------------------------------------------------------------
EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = [EnumWindowsProc, wt.LPARAM]
user32.EnumWindows.restype = wt.BOOL

user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD

user32.GetWindowTextW.argtypes = [wt.HWND, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wt.HWND, ctypes.c_wchar_p, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindowVisible.restype = wt.BOOL
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetWindowRect.restype = wt.BOOL
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetClientRect.restype = wt.BOOL

user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
user32.PrintWindow.restype = wt.BOOL

user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.restype = wt.BOOL

user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.SetForegroundWindow.restype = wt.BOOL
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.ShowWindow.restype = wt.BOOL
user32.GetForegroundWindow.restype = wt.HWND

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteObject.restype = wt.BOOL
gdi32.DeleteDC.argtypes = [wt.HDC]
gdi32.DeleteDC.restype = wt.BOOL
gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p,
                            ctypes.POINTER(BITMAPINFO), wt.UINT]
gdi32.GetDIBits.restype = ctypes.c_int

SW_RESTORE = 9
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200


@dataclass
class WindowInfo:
    hwnd: int
    pid: int
    title: str
    class_name: str
    visible: bool
    x: int
    y: int
    w: int
    h: int
    client_w: int = 0
    client_h: int = 0

    @property
    def area(self) -> int:
        return max(0, self.w) * max(0, self.h)

    def __str__(self) -> str:
        return (f"hwnd=0x{self.hwnd:X} title={self.title!r} class={self.class_name!r} "
                f"visible={self.visible} {self.w}x{self.h} @({self.x},{self.y})")


def list_windows(pid: int) -> List[WindowInfo]:
    """All top-level windows owned by the given process id."""
    result: List[WindowInfo] = []

    def _cb(hwnd, _lparam):
        win_pid = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
        if win_pid.value != pid:
            return True
        title_buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title_buf, 512)
        class_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buf, 256)
        rect = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        crect = wt.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(crect))
        result.append(WindowInfo(
            hwnd=int(hwnd),
            pid=pid,
            title=title_buf.value,
            class_name=class_buf.value,
            visible=bool(user32.IsWindowVisible(hwnd)),
            x=rect.left, y=rect.top,
            w=rect.right - rect.left, h=rect.bottom - rect.top,
            client_w=crect.right - crect.left,
            client_h=crect.bottom - crect.top,
        ))
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    return result


def pick_main_window(wins: List[WindowInfo], min_w: int = 200, min_h: int = 60) -> Optional[WindowInfo]:
    """Largest visible top-level window of the process (PCSX2 game/main window).

    Thresholds are deliberately loose: PCSX2's window can end up small (e.g. when
    it is created while another window owns the foreground), and for native F8
    screenshots all we need is a handle we can activate.
    """
    cands = [w for w in wins if w.visible and w.w >= min_w and w.h >= min_h]
    if not cands:
        cands = [w for w in wins if w.visible and w.w > 0 and w.h > 0]
    if not cands:
        return None
    titled = [w for w in cands if w.title.strip()]
    pool = titled or cands
    return max(pool, key=lambda w: w.area)


def capture_window(hwnd: int, mode: int = 2):
    """Capture a window via PrintWindow. mode=2 => PW_RENDERFULLCONTENT.

    Returns a PIL.Image (RGBA, top-down) or None.
    """
    from PIL import Image

    rect = wt.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None

    screen_dc = user32.GetDC(0)
    if not screen_dc:
        return None
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    if not mem_dc:
        user32.ReleaseDC(0, screen_dc)
        return None
    bmp = gdi32.CreateCompatibleBitmap(screen_dc, w, h)
    old = gdi32.SelectObject(mem_dc, bmp)

    ok = False
    try:
        for flags in (mode, 0):
            ok = bool(user32.PrintWindow(hwnd, mem_dc, flags))
            if ok:
                break

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB

        buf = ctypes.create_string_buffer(w * h * 4)
        got = gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
        if got == 0:
            return None
        img = Image.frombuffer("RGBA", (w, h), buf.raw, "raw", "BGRA", 0, 1).copy()
        return img
    finally:
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(0, screen_dc)


def image_stats(img) -> dict:
    """Cheap screenshot-validity stats: is the frame non-black / has content?"""
    import numpy as np

    arr = np.asarray(img.convert("RGB"), dtype=np.uint8)
    if arr.size == 0:
        return {"width": 0, "height": 0, "mean": 0.0, "std": 0.0,
                "unique_colors": 0, "nonblack_ratio": 0.0, "is_blank": True}
    luma = (0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2])
    # unique colors on a sparse grid (fast)
    sample = arr[::4, ::4].reshape(-1, 3)
    uniq = len({(int(r), int(g), int(b)) for r, g, b in sample})
    mean = float(luma.mean())
    std = float(luma.std())
    nonblack = float((luma > 16).mean())
    return {
        "width": int(arr.shape[1]),
        "height": int(arr.shape[0]),
        "mean": round(mean, 3),
        "std": round(std, 3),
        "unique_colors": int(uniq),
        "nonblack_ratio": round(nonblack, 4),
        "is_blank": bool(mean < 2.0 and uniq <= 2),
    }


# ---------------------------------------------------------------------------
# input injection (SendInput -- goes to whatever window is focused)
# ---------------------------------------------------------------------------
class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    # 32 bytes makes sizeof(INPUT) == 40 on x64, which is what SendInput expects
    _fields_ = [("ki", _KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
user32.SendInput.restype = wt.UINT
user32.keybd_event.argtypes = [wt.BYTE, wt.BYTE, wt.DWORD, ctypes.c_size_t]
user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.SetFocus.argtypes = [wt.HWND]
user32.SetFocus.restype = wt.HWND
kernel32.GetCurrentThreadId.restype = wt.DWORD

_WM_KEYUP = 0x0002
_KEYEVENTF_EXTENDEDKEY = 0x0001
# VKs that Windows treats as "extended" keys; without KEYEVENTF_EXTENDEDKEY some
# applications (Qt included) see the numpad variant / ignore the injected key.
_EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E,
                 0x5B, 0x5C, 0x6F, 0x90, 0x91}


def send_key(vk: int, up: bool = False) -> bool:
    flags = (_WM_KEYUP if up else 0)
    if vk in _EXTENDED_VKS:
        flags |= _KEYEVENTF_EXTENDEDKEY
    inp = _INPUT()
    inp.type = 1  # INPUT_KEYBOARD
    inp.u.ki = _KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags,
                           time=0, dwExtraInfo=0)
    return bool(user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT)))


def tap_key(hwnd: int | None, vk: int, hold_ms: int = 60) -> None:
    """Global key tap (SendInput). hwnd is ignored; the focused window receives it.
    Call force_focus(hwnd) first if the emulator window is not in the foreground."""
    import time
    send_key(vk, False)
    time.sleep(hold_ms / 1000.0)
    send_key(vk, True)


def post_key(hwnd: int, vk: int, keyup: bool = False) -> None:
    """Post WM_KEYDOWN/UP directly (works for some Qt widgets without focus)."""
    scan = user32.MapVirtualKeyW(vk, 0)
    lparam = 1 | (scan << 16)
    if keyup:
        lparam |= (1 << 30) | (1 << 31)
    user32.PostMessageW(hwnd, WM_KEYDOWN if not keyup else WM_KEYUP, vk, lparam)


def force_focus(hwnd: int) -> bool:
    """Best-effort foreground activation (needed for PCSX2 native screenshots /
    hotkeys, which only fire while the emulator window is active)."""
    import time
    user32.ShowWindow(hwnd, SW_RESTORE)
    time.sleep(0.05)
    fg = user32.GetForegroundWindow()
    my_tid = kernel32.GetCurrentThreadId()
    fg_pid = wt.DWORD(0)
    fg_tid = user32.GetWindowThreadProcessId(fg, ctypes.byref(fg_pid))
    pid = wt.DWORD(0)
    tgt_tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    ok = bool(user32.SetForegroundWindow(hwnd))
    if not ok:
        try:
            user32.AttachThreadInput(my_tid, fg_tid, True)
            user32.AttachThreadInput(my_tid, tgt_tid, True)
            ok = bool(user32.SetForegroundWindow(hwnd))
            user32.AttachThreadInput(my_tid, fg_tid, False)
            user32.AttachThreadInput(my_tid, tgt_tid, False)
        except Exception:
            pass
    if not ok:
        # classic foreground-lock bypass: tap ALT, retry
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 0x0002, 0)
        time.sleep(0.05)
        ok = bool(user32.SetForegroundWindow(hwnd))
    try:
        user32.SetFocus(hwnd)
    except Exception:
        pass
    return ok


def screen_capture_window(hwnd: int):
    """Grab the window's on-screen pixels from the desktop compositor (GDI
    BitBlt via PIL.ImageGrab). Works for D3D12 swapchains where PrintWindow
    returns mostly-black content, but the window must be visible/unoccluded."""
    from PIL import ImageGrab
    rect = wt.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    if rect.right <= rect.left or rect.bottom <= rect.top:
        return None
    return ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom),
                          all_screens=True)



def post_key_sequence(hwnd: int, chars: str, delay_ms: int = 120) -> None:
    """Type printable ASCII into a window via WM_CHAR (PCSX2 name entry)."""
    import time
    for ch in chars:
        user32.PostMessageW(hwnd, WM_CHAR, ord(ch), 1)
        time.sleep(delay_ms / 1000.0)


def click_window(hwnd: int, rel_x: Optional[int] = None, rel_y: Optional[int] = None) -> None:
    """Post a mouse click into the window (used to give the render widget focus)."""
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    x = w // 2 if rel_x is None else rel_x
    y = h // 2 if rel_y is None else rel_y
    lp = (y << 16) | (x & 0xFFFF)
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lp)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, 1, lp)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lp)


if __name__ == "__main__":
    import sys
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if not pid:
        print("usage: python wincap.py <pid>")
        sys.exit(2)
    wins = list_windows(pid)
    print(f"pid={pid} windows={len(wins)}")
    for w in wins:
        print(" ", w)
    main = pick_main_window(wins)
    if main:
        img = capture_window(main.hwnd)
        if img is not None:
            out = f"wincap_{pid}.png"
            img.save(out)
            print("saved", out, image_stats(img))
