"""Windows Win32 process lookup, HWND discovery, background PrintWindow capture, and anti-sleep."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import subprocess
import sys

from PIL import Image

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    _user32 = ctypes.windll.user32
    _gdi32 = ctypes.windll.gdi32
    _kernel32 = ctypes.windll.kernel32
    # Bật DPI awareness để GetWindowRect & PrintWindow khớp đúng pixel thật trên màn hình scale 125%-200%
    try:
        _user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wt.DWORD),
            ("biWidth", wt.LONG),
            ("biHeight", wt.LONG),
            ("biPlanes", wt.WORD),
            ("biBitCount", wt.WORD),
            ("biCompression", wt.DWORD),
            ("biSizeImage", wt.DWORD),
            ("biXPelsPerMeter", wt.LONG),
            ("biYPelsPerMeter", wt.LONG),
            ("biClrUsed", wt.DWORD),
            ("biClrImportant", wt.DWORD),
        ]

    class _BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]

    _ENUM_WINDOWS_PROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

_PW_RENDERFULLCONTENT = 0x00000002
_BI_RGB = 0
_DIB_RGB_COLORS = 0
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002


def set_windows_keep_awake(enabled: bool) -> None:
    """Chống Windows tự ngủ / tắt màn hình trong lúc tool đang chạy (tương đương caffeinate -di)."""
    if not _IS_WINDOWS:
        return
    flags = _ES_CONTINUOUS | (_ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED if enabled else 0)
    try:
        _kernel32.SetThreadExecutionState(flags)
    except Exception:  # noqa: BLE001
        pass


def find_roblox_pid() -> int | None:
    """Tìm PID của tiến trình RobloxPlayerBeta.exe trên Windows."""
    if not _IS_WINDOWS:
        return None
    for exe in ("RobloxPlayerBeta.exe", "RobloxPlayer.exe"):
        try:
            res = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {exe}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for line in res.stdout.splitlines():
                line = line.strip()
                if not line or "No tasks" in line or not line.startswith('"'):
                    continue
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 2 and parts[1].isdigit():
                    return int(parts[1])
        except Exception:  # noqa: BLE001
            continue
    return None


def find_roblox_window_id(pid: int) -> tuple[int, tuple[int, int]] | None:
    """Tìm HWND và kích thước (w, h) của cửa sổ game chính thuộc Roblox trên Windows."""
    if not _IS_WINDOWS:
        return None

    best_hwnd: int | None = None
    best_area = 0
    best_size = (0, 0)

    def _callback(hwnd: int, _lparam: int) -> bool:
        nonlocal best_hwnd, best_area, best_size
        if not _user32.IsWindowVisible(hwnd):
            return True

        win_pid = wt.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
        if win_pid.value != pid:
            return True

        rect = wt.RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True

        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w < 200 or h < 200:
            return True

        area = w * h
        if area > best_area:
            best_area = area
            best_hwnd = int(hwnd)
            best_size = (int(w), int(h))
        return True

    cb = _ENUM_WINDOWS_PROC(_callback)
    _user32.EnumWindows(cb, 0)

    if best_hwnd is None:
        return None
    return best_hwnd, best_size


def capture_window(hwnd: int) -> Image.Image:
    """
    Chụp riêng cửa sổ Roblox trên Windows bằng PrintWindow(PW_RENDERFULLCONTENT)
    ngay cả khi bị cửa sổ khác che (miễn không bấm Minimize).
    """
    if not _IS_WINDOWS:
        raise RuntimeError("win_window.capture_window chỉ chạy trên Windows.")

    if _user32.IsIconic(hwnd):
        raise RuntimeError("Cửa sổ Roblox đang bị thu nhỏ (Minimize). Hãy mở lại cửa sổ Roblox.")

    rect = wt.RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("Không lấy được kích thước cửa sổ Roblox.")

    w = rect.right - rect.left
    h = rect.bottom - rect.top
    if w <= 0 or h <= 0:
        raise RuntimeError(f"Kích thước cửa sổ Roblox không hợp lệ ({w}x{h}).")

    hwnd_dc = _user32.GetWindowDC(hwnd)
    if not hwnd_dc:
        raise RuntimeError("Không lấy được WindowDC của Roblox.")

    mem_dc = _gdi32.CreateCompatibleDC(hwnd_dc)
    bitmap = _gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    old_obj = _gdi32.SelectObject(mem_dc, bitmap)

    try:
        ok = _user32.PrintWindow(hwnd, mem_dc, _PW_RENDERFULLCONTENT)
        if not ok:
            ok = _user32.PrintWindow(hwnd, mem_dc, 0)
        if not ok:
            raise RuntimeError("PrintWindow không chụp được cửa sổ Roblox.")

        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # Top-down DIB
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = _BI_RGB

        buf = ctypes.create_string_buffer(w * h * 4)
        lines = _gdi32.GetDIBits(mem_dc, bitmap, 0, h, buf, ctypes.byref(bmi), _DIB_RGB_COLORS)
        if lines == 0:
            raise RuntimeError("GetDIBits thất bại khi đọc pixel cửa sổ Roblox.")

        return Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1).copy()
    finally:
        _gdi32.SelectObject(mem_dc, old_obj)
        _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(mem_dc)
        _user32.ReleaseDC(hwnd, hwnd_dc)
