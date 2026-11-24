#!/usr/bin/env python3
"""
UI Explorer & Step-by-Step Navigation Recorder
----------------------------------------------
Hai chế độ chạy từ Terminal (đã có quyền Accessibility & Screen Recording):

1. watch: Tự động chụp lại toàn bộ các màn hình trong 1 trận Ranked (CHECK BOTH SIDES -> BAN -> PICK -> RESULT)
          kèm OCR text mỗi khung hình để AI phân tích chính xác luồng chơi.
   Ví dụ: python3 scripts/ui_explorer.py watch --duration 45 --interval 1.0

2. nav:   Gửi từng phím UI Navigation một, sau mỗi phím chụp 1 ảnh lưu vào data/explore/
          để thấy chính xác khung viền chọn UI nhảy tới nút nào sau từng phím.
   Ví dụ: python3 scripts/ui_explorer.py nav --keys backslash,down,right,right,down,left,backslash
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from roblox_autoplay.core.macos_input import send_bg_key, validate_sequence_tokens  # noqa: E402
from roblox_autoplay.core.macos_window import (  # noqa: E402
    capture_window,
    find_roblox_pid,
    find_roblox_window_id,
)
from roblox_autoplay.core.permissions import check_permissions  # noqa: E402
from roblox_autoplay.ml.ball_selector import ocr_image_macos  # noqa: E402


def _make_session_dir(prefix: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = ROOT / "data" / "explore" / f"{prefix}_{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _require_roblox() -> tuple[int, int]:
    ok, warnings = check_permissions(need_screen=True)
    if not ok:
        for w in warnings:
            print(w)
        sys.exit(1)

    pid = find_roblox_pid()
    if pid is None:
        print("❌ Không tìm thấy RobloxPlayer đang chạy.")
        sys.exit(1)

    win_info = find_roblox_window_id(pid)
    if win_info is None:
        print("❌ Không tìm thấy cửa sổ chính của RobloxPlayer (không được Minimize/Fullscreen Space khác).")
        sys.exit(1)

    wid, (ww, wh) = win_info
    print(f"✅ Kết nối RobloxPlayer (PID={pid}, WindowID={wid}, Size={ww}x{wh})")
    return pid, wid


def run_watch(duration: float, interval: float, with_ocr: bool) -> None:
    _, wid = _require_roblox()
    out_dir = _make_session_dir("watch")
    print(f"📸 Bắt đầu ghi lại màn hình mỗi {interval}s trong {duration}s -> {out_dir}")
    print("   (Nhấn Ctrl+C bất cứ lúc nào để dừng sớm.)\n")

    records: list[dict] = []
    start = time.time()
    idx = 0
    try:
        while (time.time() - start) < duration:
            t_rel = round(time.time() - start, 2)
            img = capture_window(wid)
            fname = f"{idx:03d}_t{t_rel:05.1f}s.jpg"
            fpath = out_dir / fname
            # Resize nhẹ nếu ảnh Retina quá lớn để lưu nhanh & đọc nhanh
            if img.width > 1280:
                ratio = 1280 / img.width
                img = img.resize((1280, int(img.height * ratio)))
            img.save(fpath, quality=85)

            ocr_texts: list[dict] = []
            if with_ocr:
                tokens = ocr_image_macos(fpath)
                ocr_texts = [
                    {"text": t.text, "cx": round(t.cx, 3), "cy": round(t.cy, 3)}
                    for t in tokens
                ]
            header_preview = " | ".join(t["text"] for t in ocr_texts[:5])
            print(f"  [{idx:03d}] +{t_rel:4.1f}s -> {fname} | OCR: {header_preview}", flush=True)
            records.append({"index": idx, "t_sec": t_rel, "file": fname, "ocr": ocr_texts})
            idx += 1
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n⏹️  Đã dừng ghi sớm theo yêu cầu.")

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n🎉 Đã lưu {len(records)} ảnh + OCR summary tại:\n   {out_dir}")


def run_nav(keys: list[str], delay: float, countdown: int) -> None:
    validate_sequence_tokens(keys)
    pid, wid = _require_roblox()
    out_dir = _make_session_dir("nav")

    print(f"🧭 Sẽ test từng phím UI Navigation: {' -> '.join(keys)}")
    print(f"   Ảnh từng bước sẽ lưu tại: {out_dir}")
    for i in range(countdown, 0, -1):
        print(f"   Bắt đầu sau {i}s...", flush=True)
        time.sleep(1)

    records: list[dict] = []

    def snap(step_idx: int, label: str) -> None:
        img = capture_window(wid)
        fname = f"{step_idx:02d}_{label}.jpg"
        fpath = out_dir / fname
        if img.width > 1280:
            ratio = 1280 / img.width
            img = img.resize((1280, int(img.height * ratio)))
        img.save(fpath, quality=88)
        records.append({"step": step_idx, "action": label, "file": fname})
        print(f"  📸 Bước {step_idx:02d} ({label}) -> {fname}", flush=True)

    snap(0, "before")
    for idx, token in enumerate(keys, start=1):
        if token.startswith("wait:"):
            sec = float(token.split(":", 1)[1])
            print(f"  ⏳ Nghỉ {sec}s...", flush=True)
            time.sleep(sec)
            snap(idx, f"wait_{sec}s")
            continue

        send_bg_key(pid, token)
        time.sleep(delay)
        snap(idx, token)

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n🎉 Xong! Đã lưu {len(records)} ảnh từng bước tại:\n   {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chụp ảnh & dò từng bước UI Navigation Roblox")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_watch = sub.add_parser("watch", help="Chụp liên tục các màn hình trong 1 round (Check -> Ban -> Pick)")
    p_watch.add_argument("--duration", type=float, default=35.0, help="Tổng thời gian ghi (giây, mặc định 35)")
    p_watch.add_argument("--interval", type=float, default=1.0, help="Khoảng cách mỗi lần chụp (giây, mặc định 1.0)")
    p_watch.add_argument("--no-ocr", action="store_true", help="Tắt OCR trong lúc ghi cho nhanh hơn")

    p_nav = sub.add_parser("nav", help="Gửi từng phím UI Navigation và chụp ảnh sau mỗi phím")
    p_nav.add_argument(
        "--keys",
        type=str,
        default="backslash,down,right,right,down,left,left,backslash",
        help="Chuỗi phím cần test cách nhau bằng dấu phẩy",
    )
    p_nav.add_argument("--delay", type=float, default=0.45, help="Chờ sau mỗi phím trước khi chụp (giây)")
    p_nav.add_argument("--countdown", type=int, default=3, help="Đếm ngược trước khi bắt đầu (giây)")

    args = parser.parse_args()
    if args.cmd == "watch":
        run_watch(duration=args.duration, interval=args.interval, with_ocr=not args.no_ocr)
    elif args.cmd == "nav":
        keys = [k.strip().lower() for k in args.keys.split(",") if k.strip()]
        run_nav(keys=keys, delay=args.delay, countdown=args.countdown)


if __name__ == "__main__":
    main()
