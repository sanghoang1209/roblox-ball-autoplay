"""Send background keyboard events directly to a target PID via CoreGraphics."""

from __future__ import annotations

import ctypes
import random
import time
from typing import Callable

_cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
_cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")

_cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
_cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p

_cg.CGEventPostToPid.argtypes = [ctypes.c_int32, ctypes.c_void_p]
_cg.CGEventPostToPid.restype = None

_cf.CFRelease.argtypes = [ctypes.c_void_p]
_cf.CFRelease.restype = None

# macOS Virtual Keycodes (<HIToolbox/Events.h>)
KEYCODES: dict[str, int] = {
    "backslash": 42,  # \ (bật/tắt UI Navigation trong Roblox)
    "down": 125,
    "up": 126,
    "left": 123,
    "right": 124,
    "enter": 36,      # Return
    "space": 49,
    "escape": 53,
    "tab": 48,
    "w": 13,
    "a": 0,
    "s": 1,
    "d": 2,
    "e": 14,
    "r": 15,
    "1": 18,
    "2": 19,
    "3": 20,
    "4": 21,
}


def validate_sequence_tokens(sequence: list[str]) -> None:
    """Validate danh sách bước phím / wait:<giây>."""
    if not sequence:
        raise ValueError("Chuỗi phím 'sequence' không được rỗng.")
    for token in sequence:
        t = token.strip().lower()
        if t.startswith("wait:"):
            raw_val = t.split(":", 1)[1]
            try:
                sec = float(raw_val)
            except ValueError as exc:
                raise ValueError(f"Giá trị wait không hợp lệ: '{token}' (ví dụ đúng: wait:0.8)") from exc
            if sec < 0:
                raise ValueError(f"Thời gian wait không được âm: '{token}'")
        elif t not in KEYCODES:
            supported = ", ".join(sorted(KEYCODES))
            raise ValueError(f"Phím không hợp lệ: '{token}'. Hỗ trợ: {supported}, wait:<giây>")


def send_bg_key(pid: int, key_name: str, hold_sec: float | None = None) -> None:
    """Gửi một lần nhấn phím ngầm (key down -> hold -> key up) trực tiếp vào PID."""
    key = key_name.strip().lower()
    if key not in KEYCODES:
        raise ValueError(f"Phím không được hỗ trợ: '{key_name}'")

    keycode = KEYCODES[key]
    if hold_sec is None:
        hold_sec = random.uniform(0.055, 0.095)

    down = _cg.CGEventCreateKeyboardEvent(None, keycode, True)
    up = _cg.CGEventCreateKeyboardEvent(None, keycode, False)
    if not down or not up:
        raise RuntimeError("Không tạo được CGEvent (hãy kiểm tra quyền Accessibility).")
    try:
        _cg.CGEventPostToPid(pid, down)
        time.sleep(hold_sec)
        _cg.CGEventPostToPid(pid, up)
    finally:
        _cf.CFRelease(down)
        _cf.CFRelease(up)


def run_key_sequence(
    pid: int,
    sequence: list[str],
    step_delay: float = 0.22,
    on_log: Callable[[str], None] | None = None,
) -> None:
    """Chạy lần lượt chuỗi phím và các bước wait:<giây> vào tiến trình đích."""
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
