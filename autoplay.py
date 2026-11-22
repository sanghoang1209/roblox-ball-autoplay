#!/usr/bin/env python3
"""
Roblox Background Auto-Play (macOS)
-----------------------------------
Chạy ngầm 100% trên macOS (không cần focus cửa sổ Roblox, không nhảy màn hình):
- Chụp ảnh riêng cửa sổ RobloxPlayer bằng `screencapture -l <window_id>`
- Nhận diện nút "Play" màu xanh lá ở giữa phía dưới màn hình (không phụ thuộc kích thước cửa sổ)
- Gửi chuỗi phím UI Navigation trực tiếp vào PID của Roblox qua `CGEventPostToPid`
- Tích hợp chống AFK (tự bấm nhẹ Space định kỳ để không bị Roblox kick sau 20 phút)
"""

from __future__ import annotations

import argparse
import ctypes
import os
import random
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from PIL import Image

# =============================================================================
# macOS Native Frameworks (CoreGraphics / CoreFoundation / ApplicationServices)
# =============================================================================

cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
app_services = ctypes.CDLL(
    "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
)


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class CGRect(ctypes.Structure):
    _fields_ = [("origin", CGPoint), ("size", CGSize)]


cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p

cg.CGEventPostToPid.argtypes = [ctypes.c_int32, ctypes.c_void_p]
cg.CGEventPostToPid.restype = None

cg.CGPreflightScreenCaptureAccess.argtypes = []
cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool

cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p

cg.CGRectMakeWithDictionaryRepresentation.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(CGRect),
]
cg.CGRectMakeWithDictionaryRepresentation.restype = ctypes.c_bool

cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
cf.CFArrayGetCount.restype = ctypes.c_long

cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p

cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
cf.CFDictionaryGetValue.restype = ctypes.c_void_p

cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
cf.CFStringCreateWithCString.restype = ctypes.c_void_p

cf.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
cf.CFNumberGetValue.restype = ctypes.c_bool

cf.CFRelease.argtypes = [ctypes.c_void_p]
cf.CFRelease.restype = None

app_services.AXIsProcessTrusted.argtypes = []
app_services.AXIsProcessTrusted.restype = ctypes.c_bool

K_CF_STRING_ENCODING_UTF8 = 0x08000100
K_CF_NUMBER_SINT32_TYPE = 3
K_CG_WINDOW_LIST_OPTION_ALL = 0

# macOS Virtual Keycodes (<HIToolbox/Events.h>)
KEYCODES: dict[str, int] = {
    "backslash": 42,  # \ (bật/tắt UI Navigation trong Roblox)
    "down": 125,
    "up": 126,
    "left": 123,
    "right": 124,
    "enter": 36,      # Return
    "space": 49,
}

# Chuỗi phím mặc định để bấm nút Play:
# 1. \ -> Down x3 -> Right -> Enter (bấm nút Play)
# 2. Chờ cửa sổ thứ 2 hiện lên -> Down -> Enter (xác nhận vào trận)
# 3. Chờ nhẹ -> \ (tắt UI Navigation để lần sau không bị bật/tắt ngược nhau)
def build_default_sequence(popup_delay: float = 0.8) -> list[str]:
    return [
        "backslash",
        "down",
        "down",
        "down",
        "right",
        "enter",
        f"wait:{popup_delay}",
        "down",
        "enter",
        "wait:0.3",
        "backslash",
    ]


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# =============================================================================
# Process & Window Utilities
# =============================================================================


def find_roblox_pid() -> int | None:
    for cmd in (["pgrep", "-x", "RobloxPlayer"], ["pgrep", "-f", "RobloxPlayer"]):
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            return int(res.stdout.strip().splitlines()[0])
    return None


def _cfstr(text: str) -> int:
    return cf.CFStringCreateWithCString(None, text.encode("utf-8"), K_CF_STRING_ENCODING_UTF8)


def _cf_dict_int(cf_dict: int, key_ref: int) -> int | None:
    val = cf.CFDictionaryGetValue(cf_dict, key_ref)
    if not val:
        return None
    out = ctypes.c_int32(0)
    if cf.CFNumberGetValue(val, K_CF_NUMBER_SINT32_TYPE, ctypes.byref(out)):
        return out.value
    return None


def find_roblox_window_id(pid: int) -> tuple[int, tuple[int, int]] | None:
    """Tìm CGWindowID của cửa sổ game chính thuộc RobloxPlayer."""
    k_pid = _cfstr("kCGWindowOwnerPID")
    k_num = _cfstr("kCGWindowNumber")
    k_layer = _cfstr("kCGWindowLayer")
    k_bounds = _cfstr("kCGWindowBounds")

    window_list = cg.CGWindowListCopyWindowInfo(K_CG_WINDOW_LIST_OPTION_ALL, 0)
    if not window_list:
        for k in (k_pid, k_num, k_layer, k_bounds):
            cf.CFRelease(k)
        return None

    best_wid: int | None = None
    best_area = 0.0
    best_size = (0, 0)

    try:
        count = cf.CFArrayGetCount(window_list)
        for i in range(count):
            entry = cf.CFArrayGetValueAtIndex(window_list, i)
            owner_pid = _cf_dict_int(entry, k_pid)
            if owner_pid != pid:
                continue

            layer = _cf_dict_int(entry, k_layer)
            if layer != 0:
                continue

            bounds_dict = cf.CFDictionaryGetValue(entry, k_bounds)
            rect = CGRect()
            if not bounds_dict or not cg.CGRectMakeWithDictionaryRepresentation(
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
        cf.CFRelease(window_list)
        for k in (k_pid, k_num, k_layer, k_bounds):
            cf.CFRelease(k)

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


# =============================================================================
# Background Keyboard Sender
# =============================================================================


def send_bg_key(pid: int, key_name: str, hold_sec: float | None = None) -> None:
    keycode = KEYCODES[key_name]
    if hold_sec is None:
        hold_sec = random.uniform(0.055, 0.095)

    down = cg.CGEventCreateKeyboardEvent(None, keycode, True)
    up = cg.CGEventCreateKeyboardEvent(None, keycode, False)
    if not down or not up:
        raise RuntimeError("Không tạo được CGEvent (hãy kiểm tra quyền Accessibility).")
    try:
        cg.CGEventPostToPid(pid, down)
        time.sleep(hold_sec)
        cg.CGEventPostToPid(pid, up)
    finally:
        cf.CFRelease(down)
        cf.CFRelease(up)


def press_play_sequence(
    pid: int,
    sequence: list[str],
    step_delay: float = 0.22,
) -> None:
    log(f"▶️  Gửi chuỗi phím ngầm: {' -> '.join(sequence)}")
    for idx, token in enumerate(sequence):
        if token.startswith("wait:"):
            wait_sec = float(token.split(":", 1)[1])
            time.sleep(max(0.0, wait_sec))
            continue

        send_bg_key(pid, token)
        # Chỉ nghỉ step_delay nếu bước kế tiếp là một phím bấm (không phải wait:)
        if idx < len(sequence) - 1 and not sequence[idx + 1].startswith("wait:"):
            jitter = random.uniform(-0.04, 0.06)
            time.sleep(max(0.08, step_delay + jitter))


# =============================================================================
# Play Button Detector (Color + Shape + Relative Position)
# =============================================================================


@dataclass
class DetectionResult:
    found: bool
    reason: str
    green_ratio: float = 0.0
    white_ratio: float = 0.0
    aspect_ratio: float = 0.0
    rel_bbox: tuple[float, float, float, float] | None = None


def detect_play_button(img: Image.Image) -> DetectionResult:
    """
    Nhận diện nút 'Play' màu xanh lá sáng ở giữa phía dưới màn hình.
    Hoạt động tốt ở mọi kích thước cửa sổ Roblox và cả màn hình Retina.
    """
    arr = np.asarray(img)
    if arr.ndim != 3 or arr.shape[2] < 3:
        return DetectionResult(False, "Ảnh chụp không hợp lệ")

    h, w = arr.shape[:2]
    if w < 200 or h < 200:
        return DetectionResult(False, f"Kích thước cửa sổ quá nhỏ ({w}x{h})")

    # Vùng tìm kiếm (ROI): giữa phía dưới màn hình
    rx0, rx1 = int(w * 0.30), int(w * 0.70)
    ry0, ry1 = int(h * 0.84), int(h * 0.995)
    roi = arr[ry0:ry1, rx0:rx1]

    r = roi[:, :, 0].astype(np.int16)
    g = roi[:, :, 1].astype(np.int16)
    b = roi[:, :, 2].astype(np.int16)

    # Màu xanh lá đặc trưng của nút Play (median RGB ~ 102, 200, 1)
    green_mask = (
        (g >= 155)
        & ((g - b) >= 95)
        & ((g - r) >= 35)
        & (r >= 40)
        & (r <= 175)
        & (b <= 75)
    )

    # Lọc các hàng & cột có mật độ xanh đủ lớn để tránh nhiễu pixel lẻ
    row_density = green_mask.mean(axis=1)
    col_density = green_mask.mean(axis=0)
    active_rows = np.where(row_density >= 0.20)[0]
    active_cols = np.where(col_density >= 0.15)[0]

    if len(active_rows) < 6 or len(active_cols) < 20:
        return DetectionResult(False, "Không thấy khối màu xanh nút Play ở đáy màn hình")

    by0, by1 = int(active_rows[0]), int(active_rows[-1]) + 1
    bx0, bx1 = int(active_cols[0]), int(active_cols[-1]) + 1

    bw = bx1 - bx0
    bh = by1 - by0
    rel_w = bw / w
    rel_h = bh / h
    aspect = bw / max(1, bh)

    abs_x0, abs_x1 = rx0 + bx0, rx0 + bx1
    abs_y0, abs_y1 = ry0 + by0, ry0 + by1
    center_x_rel = ((abs_x0 + abs_x1) / 2.0) / w
    rel_bbox = (abs_x0 / w, abs_y0 / h, abs_x1 / w, abs_y1 / h)

    # Kiểm tra hình học của nút Play
    if not (0.08 <= rel_w <= 0.40 and 0.025 <= rel_h <= 0.15):
        return DetectionResult(
            False,
            f"Kích thước khối xanh không khớp ({rel_w:.2f}x{rel_h:.2f})",
            aspect_ratio=aspect,
            rel_bbox=rel_bbox,
        )

    if not (2.0 <= aspect <= 9.0):
        return DetectionResult(
            False,
            f"Tỉ lệ khung nút không khớp (w/h={aspect:.2f})",
            aspect_ratio=aspect,
            rel_bbox=rel_bbox,
        )

    if not (0.40 <= center_x_rel <= 0.60):
        return DetectionResult(
            False,
            f"Vị trí ngang không nằm giữa (center_x={center_x_rel:.2f})",
            aspect_ratio=aspect,
            rel_bbox=rel_bbox,
        )

    # Kiểm tra độ phủ màu xanh và chữ trắng "Play" bên trong nút
    btn_green = green_mask[by0:by1, bx0:bx1]
    btn_rgb = roi[by0:by1, bx0:bx1]
    btn_white = (btn_rgb[:, :, 0] > 210) & (btn_rgb[:, :, 1] > 210) & (btn_rgb[:, :, 2] > 210)

    green_ratio = float(btn_green.mean())
    white_ratio = float(btn_white.mean())

    if green_ratio < 0.60:
        return DetectionResult(
            False,
            f"Độ phủ xanh quá thấp ({green_ratio:.1%})",
            green_ratio=green_ratio,
            white_ratio=white_ratio,
            aspect_ratio=aspect,
            rel_bbox=rel_bbox,
        )

    if not (0.015 <= white_ratio <= 0.30):
        return DetectionResult(
            False,
            f"Không khớp chữ trắng 'Play' bên trong ({white_ratio:.1%})",
            green_ratio=green_ratio,
            white_ratio=white_ratio,
            aspect_ratio=aspect,
            rel_bbox=rel_bbox,
        )

    return DetectionResult(
        True,
        "Phát hiện nút Play!",
        green_ratio=green_ratio,
        white_ratio=white_ratio,
        aspect_ratio=aspect,
        rel_bbox=rel_bbox,
    )


# =============================================================================
# Permissions & Main Loop
# =============================================================================


def check_permissions(need_screen: bool = True) -> bool:
    ok = True
    if not app_services.AXIsProcessTrusted():
        print("⚠️  Terminal chưa có quyền Accessibility (Trợ năng)!")
        print("   -> System Settings -> Privacy & Security -> Accessibility -> Bật cho Terminal.")
        ok = False

    if need_screen and not cg.CGPreflightScreenCaptureAccess():
        print("⚠️  Terminal chưa có quyền Screen Recording (Ghi màn hình)!")
        print("   -> System Settings -> Privacy & Security -> Screen & System Audio Recording -> Bật cho Terminal.")
        print("   (Sau khi bật cần tắt và mở lại Terminal để macOS áp dụng quyền.)")
        ok = False

    return ok


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Roblox Background Auto-Play cho macOS")
    parser.add_argument(
        "--interval",
        type=float,
        default=3.0,
        help="Số giây giữa mỗi lần quét cửa sổ Roblox (mặc định: 3.0)",
    )
    parser.add_argument(
        "--cooldown",
        type=float,
        default=12.0,
        help="Số giây nghỉ sau khi bấm Play để chờ vào trận (mặc định: 12.0)",
    )
    parser.add_argument(
        "--step-delay",
        type=float,
        default=0.22,
        help="Độ trễ giữa các phím UI Navigation tính bằng giây (mặc định: 0.22)",
    )
    parser.add_argument(
        "--popup-delay",
        type=float,
        default=0.8,
        help="Số giây chờ cửa sổ thứ 2 hiện lên sau khi bấm Play (mặc định: 0.8)",
    )
    parser.add_argument(
        "--sequence",
        type=str,
        default="",
        help="Tùy chỉnh chuỗi phím cách nhau bằng dấu phẩy (hỗ trợ wait:<giây>)",
    )
    parser.add_argument(
        "--afk-interval",
        type=float,
        default=480.0,
        help="Chu kỳ bấm Space chống AFK tính bằng giây (mặc định: 480 = 8 phút)",
    )
    parser.add_argument(
        "--no-anti-afk",
        action="store_true",
        help="Tắt tính năng tự bấm Space chống kick AFK 20 phút",
    )
    parser.add_argument(
        "--check-once",
        action="store_true",
        help="Chụp cửa sổ Roblox 1 lần và in kết quả nhận diện nút Play rồi thoát",
    )
    parser.add_argument(
        "--save-debug",
        type=str,
        default="",
        help="Lưu ảnh chụp cửa sổ Roblox ra file (dùng kèm --check-once để kiểm tra)",
    )
    parser.add_argument(
        "--test-keys",
        action="store_true",
        help="Đếm ngược 4 giây rồi gửi thử chuỗi phím Play vào Roblox đang chạy ngầm",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ quét và báo khi thấy nút Play, KHÔNG gửi phím bấm",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.sequence.strip():
        sequence = [k.strip().lower() for k in args.sequence.split(",") if k.strip()]
    else:
        sequence = build_default_sequence(args.popup_delay)

    for token in sequence:
        if token.startswith("wait:"):
            try:
                float(token.split(":", 1)[1])
            except ValueError:
                print(f"❌ Giá trị wait không hợp lệ: '{token}' (ví dụ đúng: wait:0.8)")
                sys.exit(1)
        elif token not in KEYCODES:
            print(f"❌ Phím không hợp lệ: '{token}'. Các phím hỗ trợ: {', '.join(KEYCODES)}, wait:<giây>")
            sys.exit(1)

    need_screen = not args.test_keys
    if not check_permissions(need_screen=need_screen):
        sys.exit(1)

    pid = find_roblox_pid()
    if pid is None:
        print("❌ Không tìm thấy RobloxPlayer đang chạy. Hãy mở game Roblox trước.")
        sys.exit(1)

    if args.test_keys:
        log(f"✅ Tìm thấy RobloxPlayer (PID: {pid})")
        log("👉 Hãy bấm sang cửa sổ khác để test chạy ngầm...")
        for i in range(4, 0, -1):
            log(f"   Gửi phím sau {i} giây...")
            time.sleep(1)
        press_play_sequence(pid, sequence, step_delay=args.step_delay)
        log("🎉 Đã gửi xong chuỗi phím test!")
        return

    win_info = find_roblox_window_id(pid)
    if win_info is None:
        print("❌ Không tìm thấy cửa sổ chính của RobloxPlayer (đảm bảo cửa sổ chưa bị Minimize).")
        sys.exit(1)

    wid, (ww, wh) = win_info
    log(f"✅ Tìm thấy RobloxPlayer (PID: {pid}, WindowID: {wid}, Size: {ww}x{wh})")

    if args.check_once:
        img = capture_window(wid)
        if args.save_debug:
            img.save(args.save_debug)
            log(f"💾 Đã lưu ảnh chụp kiểm tra tại: {args.save_debug}")
        res = detect_play_button(img)
        status = "✅ THẤY NÚT PLAY" if res.found else "❌ KHÔNG THẤY"
        log(
            f"{status} | {res.reason} | green={res.green_ratio:.1%}, "
            f"white={res.white_ratio:.1%}, aspect={res.aspect_ratio:.2f}, bbox={res.rel_bbox}"
        )
        return

    log(f"🚀 Bắt đầu chạy ngầm! Quét mỗi {args.interval}s | Chuỗi phím: {' -> '.join(sequence)}")
    if not args.no_anti_afk:
        log(f"🛡️  Chống AFK bật (tự bấm Space mỗi ~{int(args.afk_interval)}s)")
    if args.dry_run:
        log("🧪 Đang ở chế độ DRY-RUN (chỉ nhận diện, không bấm phím).")
    log("   Nhấn Ctrl+C để dừng.")

    last_play_ts = 0.0
    last_action_ts = time.time()
    play_count = 0
    consecutive_hits = 0

    try:
        while True:
            now = time.time()

            # Kiểm tra lại PID/Window nếu Roblox bị mở lại
            cur_pid = find_roblox_pid()
            if cur_pid is None:
                log("⏳ Không thấy RobloxPlayer... đang chờ mở lại.")
                time.sleep(5)
                continue
            if cur_pid != pid:
                pid = cur_pid
                win_info = find_roblox_window_id(pid)
                if win_info is None:
                    time.sleep(3)
                    continue
                wid, _ = win_info
                log(f"🔄 Đã kết nối lại RobloxPlayer (PID: {pid}, WindowID: {wid})")

            try:
                img = capture_window(wid)
            except RuntimeError as exc:
                log(f"⚠️  {exc}")
                # Thử lấy lại WindowID phòng trường hợp cửa sổ thay đổi
                win_info = find_roblox_window_id(pid)
                if win_info:
                    wid, _ = win_info
                time.sleep(args.interval)
                continue

            res = detect_play_button(img)

            if res.found:
                consecutive_hits += 1
                # Yêu cầu thấy 2 lần liên tiếp (hoặc lần đầu nếu interval >= 3s) để tránh nháy khung hình
                ready_by_cooldown = (now - last_play_ts) >= args.cooldown
                if ready_by_cooldown and (consecutive_hits >= 2 or args.interval >= 3.0):
                    play_count += 1
                    log(
                        f"🎯 Phát hiện nút Play (#{play_count}) "
                        f"[green={res.green_ratio:.0%}, white={res.white_ratio:.1%}]"
                    )
                    if not args.dry_run:
                        press_play_sequence(
                            pid,
                            sequence,
                            step_delay=args.step_delay,
                        )
                    last_play_ts = time.time()
                    last_action_ts = last_play_ts
                    consecutive_hits = 0
            else:
                consecutive_hits = 0

            # Chống AFK 20 phút khi đang trong trận dài
            if not args.no_anti_afk and not args.dry_run:
                if (time.time() - last_action_ts) >= args.afk_interval:
                    log("🛡️  Gửi phím Space ngầm chống AFK...")
                    send_bg_key(pid, "space")
                    last_action_ts = time.time() + random.uniform(-30, 30)

            time.sleep(args.interval)

    except KeyboardInterrupt:
        log(f"\n👋 Đã dừng tool. Tổng số lần bấm Play: {play_count}")


if __name__ == "__main__":
    main()
