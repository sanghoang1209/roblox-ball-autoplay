"""Send background keyboard events to a Roblox HWND on Windows via Win32 PostMessageW."""

from __future__ import annotations

import ctypes
import random
import sys
import time

from roblox_autoplay.core.win_window import find_roblox_window_id

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    _user32 = ctypes.windll.user32

_WM_KEYDOWN = 0x0100
_WM_KEYUP = 0x0101
_MAPVK_VK_TO_VSC = 0

# Windows Virtual-Key Codes (VK_*)
WIN_VK_CODES: dict[str, int] = {
    "backslash": 0xDC,  # VK_OEM_5 (\)
    "left": 0x25,       # VK_LEFT
    "up": 0x26,         # VK_UP
    "right": 0x27,      # VK_RIGHT
    "down": 0x28,       # VK_DOWN
    "enter": 0x0D,      # VK_RETURN
    "space": 0x20,      # VK_SPACE
    "escape": 0x1B,     # VK_ESCAPE
    "tab": 0x09,        # VK_TAB
    "w": 0x57,
    "a": 0x41,
    "s": 0x53,
    "d": 0x44,
    "e": 0x45,
    "r": 0x52,
    "1": 0x31,
    "2": 0x32,
    "3": 0x33,
    "4": 0x34,
}

_EXTENDED_KEYS = {"left", "up", "right", "down"}


def build_key_lparam(scan_code: int, is_keyup: bool = False, extended: bool = False) -> int:
    """Tạo lParam chuẩn Win32 cho WM_KEYDOWN / WM_KEYUP."""
    lparam = 1 | ((scan_code & 0xFF) << 16)
    if extended:
        lparam |= 1 << 24
    if is_keyup:
        lparam |= (1 << 30) | (1 << 31)
    return lparam


def send_bg_key(pid: int, key_name: str, hold_sec: float | None = None) -> None:
    """Gửi phím ngầm trực tiếp vào cửa sổ Roblox trên Windows bằng PostMessageW."""
    if not _IS_WINDOWS:
        raise RuntimeError("win_input.send_bg_key chỉ chạy trên Windows.")

    key = key_name.strip().lower()
    if key not in WIN_VK_CODES:
        raise ValueError(f"Phím không được hỗ trợ trên Windows: '{key_name}'")

    win_info = find_roblox_window_id(pid)
    if win_info is None:
        raise RuntimeError("Không tìm thấy cửa sổ Roblox để gửi phím trên Windows.")
    hwnd, _ = win_info

    vk = WIN_VK_CODES[key]
    scan = int(_user32.MapVirtualKeyW(vk, _MAPVK_VK_TO_VSC))
    extended = key in _EXTENDED_KEYS
    down_lp = build_key_lparam(scan, is_keyup=False, extended=extended)
    up_lp = build_key_lparam(scan, is_keyup=True, extended=extended)

    if hold_sec is None:
        hold_sec = random.uniform(0.055, 0.095)

    _user32.PostMessageW(hwnd, _WM_KEYDOWN, vk, down_lp)
    time.sleep(hold_sec)
    _user32.PostMessageW(hwnd, _WM_KEYUP, vk, up_lp)
