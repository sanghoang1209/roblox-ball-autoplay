"""macOS permission checks (Accessibility & Screen Recording)."""

from __future__ import annotations

import ctypes
import sys

if sys.platform == "darwin":
    _cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    _app_services = ctypes.CDLL(
        "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
    )

    _cg.CGPreflightScreenCaptureAccess.argtypes = []
    _cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool

    _app_services.AXIsProcessTrusted.argtypes = []
    _app_services.AXIsProcessTrusted.restype = ctypes.c_bool
else:
    _cg = None
    _app_services = None


def has_accessibility_permission() -> bool:
    if _app_services is None:
        return True
    return bool(_app_services.AXIsProcessTrusted())


def has_screen_recording_permission() -> bool:
    if _cg is None:
        return True
    return bool(_cg.CGPreflightScreenCaptureAccess())


def check_permissions(need_screen: bool = True) -> tuple[bool, list[str]]:
    """Kiểm tra quyền macOS và trả về (ok, danh_sách_cảnh_báo)."""
    warnings: list[str] = []
    if not has_accessibility_permission():
        warnings.append(
            "⚠️  Terminal/App chưa có quyền Accessibility (Trợ năng)!\n"
            "   -> System Settings -> Privacy & Security -> Accessibility -> Bật cho Terminal/App."
        )

    if need_screen and not has_screen_recording_permission():
        warnings.append(
            "⚠️  Terminal/App chưa có quyền Screen Recording (Ghi màn hình)!\n"
            "   -> System Settings -> Privacy & Security -> Screen & System Audio Recording -> Bật cho Terminal/App.\n"
            "   (Sau khi bật cần tắt và mở lại Terminal/App để macOS áp dụng quyền.)"
        )

    return len(warnings) == 0, warnings
