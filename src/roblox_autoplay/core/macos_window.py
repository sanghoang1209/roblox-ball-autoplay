"""macOS process lookup, CGWindowID discovery, and background window capture."""

from __future__ import annotations

import ctypes
import os
import subprocess
import tempfile

from PIL import Image

_cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
_cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


_cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
_cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p

_cg.CGRectMakeWithDictionaryRepresentation.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(_CGRect),
]
_cg.CGRectMakeWithDictionaryRepresentation.restype = ctypes.c_bool

_cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
_cf.CFArrayGetCount.restype = ctypes.c_long

_cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
_cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p

_cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_cf.CFDictionaryGetValue.restype = ctypes.c_void_p

_cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
_cf.CFStringCreateWithCString.restype = ctypes.c_void_p

_cf.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
_cf.CFNumberGetValue.restype = ctypes.c_bool

_cf.CFRelease.argtypes = [ctypes.c_void_p]
_cf.CFRelease.restype = None

_K_CF_STRING_ENCODING_UTF8 = 0x08000100
_K_CF_NUMBER_SINT32_TYPE = 3
_K_CG_WINDOW_LIST_OPTION_ALL = 0


def find_roblox_pid() -> int | None:
    """Tìm PID của tiến trình RobloxPlayer đang chạy."""
    for cmd in (["pgrep", "-x", "RobloxPlayer"], ["pgrep", "-f", "RobloxPlayer"]):
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            return int(res.stdout.strip().splitlines()[0])
    return None


def _cfstr(text: str) -> int:
    return _cf.CFStringCreateWithCString(None, text.encode("utf-8"), _K_CF_STRING_ENCODING_UTF8)


def _cf_dict_int(cf_dict: int, key_ref: int) -> int | None:
    val = _cf.CFDictionaryGetValue(cf_dict, key_ref)
    if not val:
        return None
    out = ctypes.c_int32(0)
    if _cf.CFNumberGetValue(val, _K_CF_NUMBER_SINT32_TYPE, ctypes.byref(out)):
        return out.value
    return None


def find_roblox_window_id(pid: int) -> tuple[int, tuple[int, int]] | None:
    """Tìm CGWindowID và kích thước (w, h) của cửa sổ game chính thuộc RobloxPlayer."""
    k_pid = _cfstr("kCGWindowOwnerPID")
    k_num = _cfstr("kCGWindowNumber")
    k_layer = _cfstr("kCGWindowLayer")
    k_bounds = _cfstr("kCGWindowBounds")

    window_list = _cg.CGWindowListCopyWindowInfo(_K_CG_WINDOW_LIST_OPTION_ALL, 0)
    if not window_list:
        for k in (k_pid, k_num, k_layer, k_bounds):
            _cf.CFRelease(k)
        return None

    best_wid: int | None = None
    best_area = 0.0
    best_size = (0, 0)

    try:
        count = _cf.CFArrayGetCount(window_list)
        for i in range(count):
            entry = _cf.CFArrayGetValueAtIndex(window_list, i)
            if _cf_dict_int(entry, k_pid) != pid:
                continue
            if _cf_dict_int(entry, k_layer) != 0:
                continue

            bounds_dict = _cf.CFDictionaryGetValue(entry, k_bounds)
            rect = _CGRect()
            if not bounds_dict or not _cg.CGRectMakeWithDictionaryRepresentation(
                bounds_dict, ctypes.byref(rect)
            ):
                continue

            w, h = rect.size.width, rect.size.height
            if w < 200 or h < 200:
                continue

            area = w * h
            if area > best_area:
                wid = _cf_dict_int(entry, k_num)
                if wid is not None:
                    best_area = area
                    best_wid = wid
                    best_size = (int(w), int(h))
    finally:
        _cf.CFRelease(window_list)
        for k in (k_pid, k_num, k_layer, k_bounds):
            _cf.CFRelease(k)

    if best_wid is None:
        return None
    return best_wid, best_size


def capture_window(window_id: int) -> Image.Image:
    """Chụp riêng cửa sổ Roblox ngay cả khi bị cửa sổ khác che (không được Minimize)."""
    fd, tmp_path = tempfile.mkstemp(prefix="roblox_cap_", suffix=".png")
    os.close(fd)
    try:
        res = subprocess.run(
            ["/usr/sbin/screencapture", "-l", str(window_id), "-x", "-o", tmp_path],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0 or not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            err = res.stderr.strip() or "Không chụp được cửa sổ Roblox"
            raise RuntimeError(
                f"{err}. Hãy kiểm tra quyền Screen Recording và đảm bảo Roblox KHÔNG bị thu nhỏ (Minimize)."
            )
        with Image.open(tmp_path) as img:
            return img.convert("RGB")
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
