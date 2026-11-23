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
    """
    Tìm CGWindowID và kích thước (w, h) của cửa sổ game chính thuộc RobloxPlayer.
    Ưu tiên cửa sổ đang hiển thị (kCGWindowIsOnscreen == 1) và loại trừ cửa sổ ẩn 500x500 của Roblox.
    """
    k_pid = _cfstr("kCGWindowOwnerPID")
    k_num = _cfstr("kCGWindowNumber")
    k_layer = _cfstr("kCGWindowLayer")
    k_bounds = _cfstr("kCGWindowBounds")
    k_onscreen = _cfstr("kCGWindowIsOnscreen")

    window_list = _cg.CGWindowListCopyWindowInfo(_K_CG_WINDOW_LIST_OPTION_ALL, 0)
    if not window_list:
        for k in (k_pid, k_num, k_layer, k_bounds, k_onscreen):
            _cf.CFRelease(k)
        return None

    best_wid: int | None = None
    best_rank: tuple[int, int, float] = (-1, -1, 0.0)
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

            wid = _cf_dict_int(entry, k_num)
            if wid is None:
                continue

            is_onscreen = 1 if _cf_dict_int(entry, k_onscreen) == 1 else 0
            # Roblox tạo 1 cửa sổ ẩn cố định 500x500 (onscreen=None) -> hạ ưu tiên tối đa
            is_not_dummy = 0 if (not is_onscreen and int(w) == 500 and int(h) == 500) else 1
            rank = (is_onscreen, is_not_dummy, w * h)

            if rank > best_rank:
                best_rank = rank
                best_wid = wid
                best_size = (int(w), int(h))
    finally:
        _cf.CFRelease(window_list)
        for k in (k_pid, k_num, k_layer, k_bounds, k_onscreen):
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
                f"{err}. Hãy kiểm tra quyền Screen Recording, đảm bảo Roblox KHÔNG bị Minimize "
                f"và KHÔNG bật Fullscreen sang Desktop Space khác."
            )
        with Image.open(tmp_path) as img:
            return img.convert("RGB")
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
