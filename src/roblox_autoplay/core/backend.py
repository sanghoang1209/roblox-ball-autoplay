"""Cross-platform backend dispatcher (macOS CoreGraphics + Windows Win32)."""

from __future__ import annotations

import sys
from typing import Callable

from PIL import Image

from roblox_autoplay.core.macos_input import KEYCODES, validate_sequence_tokens

if sys.platform == "win32":
    from roblox_autoplay.core import win_input as _input_mod
    from roblox_autoplay.core import win_window as _win_mod

    def check_permissions(need_screen: bool = True) -> tuple[bool, list[str]]:
        return True, []

    def set_keep_awake(enabled: bool) -> None:
        _win_mod.set_windows_keep_awake(enabled)

elif sys.platform == "darwin":
    from roblox_autoplay.core import macos_input as _input_mod
    from roblox_autoplay.core import macos_window as _win_mod
    from roblox_autoplay.core.permissions import check_permissions

    def set_keep_awake(enabled: bool) -> None:
        return  # macOS sử dụng caffeinate qua Makefile hoặc lệnh terminal

else:
    _input_mod = None
    _win_mod = None

    def check_permissions(need_screen: bool = True) -> tuple[bool, list[str]]:
        return False, [f"Hệ điều hành '{sys.platform}' chưa được hỗ trợ (hỗ trợ macOS & Windows)."]

    def set_keep_awake(enabled: bool) -> None:
        return


def find_roblox_pid() -> int | None:
    if _win_mod is None:
        return None
    return _win_mod.find_roblox_pid()


def find_roblox_window_id(pid: int) -> tuple[int, tuple[int, int]] | None:
    if _win_mod is None:
        return None
    return _win_mod.find_roblox_window_id(pid)


def capture_window(window_id: int) -> Image.Image:
    if _win_mod is None:
        raise RuntimeError(f"Hệ điều hành '{sys.platform}' chưa hỗ trợ chụp cửa sổ.")
    return _win_mod.capture_window(window_id)


def send_bg_key(pid: int, key_name: str, hold_sec: float | None = None) -> None:
    if _input_mod is None:
        raise RuntimeError(f"Hệ điều hành '{sys.platform}' chưa hỗ trợ gửi phím ngầm.")
    _input_mod.send_bg_key(pid, key_name, hold_sec=hold_sec)


def run_key_sequence(
    pid: int,
    sequence: list[str],
    step_delay: float = 0.22,
    on_log: Callable[[str], None] | None = None,
) -> None:
    import random
    import time

    normalized = [t.strip().lower() for t in sequence if t.strip()]
    validate_sequence_tokens(normalized)

    if on_log:
        on_log(f"▶️  Gửi chuỗi phím ngầm: {' -> '.join(normalized)}")

    for idx, token in enumerate(normalized):
        if token.startswith("wait:"):
            wait_sec = float(token.split(":", 1)[1])
            time.sleep(max(0.0, wait_sec))
            continue

        send_bg_key(pid, token)
        if idx < len(normalized) - 1 and not normalized[idx + 1].startswith("wait:"):
            jitter = random.uniform(-0.04, 0.06)
            time.sleep(max(0.08, step_delay + jitter))


__all__ = [
    "KEYCODES",
    "capture_window",
    "check_permissions",
    "find_roblox_pid",
    "find_roblox_window_id",
    "run_key_sequence",
    "send_bg_key",
    "set_keep_awake",
    "validate_sequence_tokens",
]
