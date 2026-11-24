"""CLI entrypoint for Roblox Background Auto-Play."""

from __future__ import annotations

import argparse
import sys
import time

from roblox_autoplay.core.backend import (
    capture_window,
    check_permissions,
    find_roblox_pid,
    find_roblox_window_id,
    run_key_sequence,
    validate_sequence_tokens,
)
from roblox_autoplay.core.engine import AutoPlayEngine, default_logger
from roblox_autoplay.core.profile_loader import list_profiles, resolve_profile
from roblox_autoplay.ml.ball_selector import (
    BallSelector,
    ocr_pil_image,
    parse_ball_selection_screen,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Roblox Background Auto-Play cho macOS")
    parser.add_argument(
        "-p",
        "--profile",
        type=str,
        default="default_play",
        help="ID hoặc đường dẫn file JSON profile trong thư mục profiles/ (mặc định: default_play)",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="Liệt kê toàn bộ chế độ treo hiện có trong profiles/ rồi thoát",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Ghi đè số giây giữa mỗi lần quét cửa sổ Roblox",
    )
    parser.add_argument(
        "--cooldown",
        type=float,
        default=None,
        help="Ghi đè số giây nghỉ sau khi bấm Play",
    )
    parser.add_argument(
        "--step-delay",
        type=float,
        default=None,
        help="Ghi đè độ trễ giữa các phím UI Navigation (giây)",
    )
    parser.add_argument(
        "--sequence",
        type=str,
        default="",
        help="Ghi đè chuỗi phím cách nhau bằng dấu phẩy (hỗ trợ wait:<giây>)",
    )
    parser.add_argument(
        "--afk-interval",
        type=float,
        default=None,
        help="Ghi đè chu kỳ bấm chống AFK (giây)",
    )
    parser.add_argument(
        "--no-anti-afk",
        action="store_true",
        help="Tắt tính năng chống kick AFK 20 phút",
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
        help="Lưu ảnh chụp cửa sổ Roblox ra file (dùng kèm --check-once)",
    )
    parser.add_argument(
        "--test-keys",
        action="store_true",
        help="Đếm ngược 4 giây rồi gửi thử chuỗi phím của profile vào Roblox đang chạy ngầm",
    )
    parser.add_argument(
        "--test-ball-ocr",
        action="store_true",
        help="Chụp cửa sổ Roblox 1 lần, chạy OCR đọc 3 ô bóng và gợi ý ô điểm cao nhất",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ quét và báo khi thấy nút Play, KHÔNG gửi phím bấm",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_profiles:
        profiles = list_profiles()
        if not profiles:
            print("Chưa có profile nào trong thư mục profiles/.")
            return
        print("📋 Các chế độ treo hiện có:")
        for prof in profiles:
            print(f"  - {prof.id}: {prof.name}")
            if prof.description:
                print(f"      Mô tả : {prof.description}")
            print(f"      Phím  : {' -> '.join(prof.sequence)}")
        return

    try:
        profile = resolve_profile(args.profile)
    except (FileNotFoundError, ValueError) as exc:
        print(f"❌ Lỗi profile: {exc}")
        sys.exit(1)

    # Áp dụng các cờ ghi đè từ CLI nếu người dùng truyền vào
    if args.interval is not None:
        profile.timing.scan_interval_sec = max(0.2, args.interval)
    if args.cooldown is not None:
        profile.timing.cooldown_sec = max(0.0, args.cooldown)
    if args.step_delay is not None:
        profile.timing.step_delay_sec = max(0.05, args.step_delay)
    if args.afk_interval is not None:
        profile.anti_afk.interval_sec = max(10.0, args.afk_interval)
    if args.no_anti_afk:
        profile.anti_afk.enabled = False
    if args.sequence.strip():
        custom_seq = [t.strip().lower() for t in args.sequence.split(",") if t.strip()]
        try:
            validate_sequence_tokens(custom_seq)
        except ValueError as exc:
            print(f"❌ {exc}")
            sys.exit(1)
        profile.sequence = custom_seq

    need_screen = (not args.test_keys) and (profile.detector.type != "timer")
    ok, warnings = check_permissions(need_screen=need_screen)
    if not ok:
        for warn in warnings:
            print(warn)
        sys.exit(1)

    if args.test_keys:
        pid = find_roblox_pid()
        if pid is None:
            print("❌ Không tìm thấy RobloxPlayer đang chạy. Hãy mở game Roblox trước.")
            sys.exit(1)
        default_logger(f"✅ Tìm thấy RobloxPlayer (PID: {pid}) | Profile: {profile.id}")
        default_logger("👉 Hãy bấm sang cửa sổ khác để test chạy ngầm...")
        for i in range(4, 0, -1):
            default_logger(f"   Gửi phím sau {i} giây...")
            time.sleep(1)
        run_key_sequence(
            pid,
            profile.sequence,
            step_delay=profile.timing.step_delay_sec,
            on_log=default_logger,
        )
        default_logger("🎉 Đã gửi xong chuỗi phím test!")
        return

    if args.test_ball_ocr:
        pid = find_roblox_pid()
        if pid is None:
            print("❌ Không tìm thấy RobloxPlayer đang chạy. Hãy mở game Roblox trước.")
            sys.exit(1)
        win_info = find_roblox_window_id(pid)
        if win_info is None:
            print("❌ Không tìm thấy cửa sổ chính của RobloxPlayer.")
            sys.exit(1)
        wid, (ww, wh) = win_info
        default_logger(f"✅ Đang chụp & OCR cửa sổ Roblox ({ww}x{wh})...")
        img = capture_window(wid)
        selector = BallSelector.from_file()
        tokens = ocr_pil_image(img)
        ball_res = parse_ball_selection_screen(tokens, selector)
        if not ball_res.detected:
            default_logger(
                f"❌ Chưa thấy pha BAN/PICK (phase={ball_res.phase}, header={ball_res.header_text!r})."
            )
            return
        default_logger(f"✅ Pha: {ball_res.phase} | Header: {ball_res.header_text!r}")
        for s in ball_res.slots:
            tier = s.matched_ball.tier if s.matched_ball else "?"
            name = s.matched_ball.name if s.matched_ball else "Không rõ"
            default_logger(f"   Ô {s.slot_index}: {s.raw_text!r} -> {name} (Tier {tier}, điểm {s.score})")
        if ball_res.best_choice:
            action = "CẤM (BAN)" if ball_res.phase == "BAN" else "CHỌN (PICK)"
            default_logger(
                f"🏆 Quyết định {action}: Ô {ball_res.best_choice.slot_index} "
                f"({ball_res.best_choice.raw_text}, điểm {ball_res.best_choice.score})"
            )
        return

    engine = AutoPlayEngine(profile=profile, dry_run=args.dry_run)

    if args.check_once:
        if profile.detector.type == "timer":
            default_logger(
                f"ℹ️  Profile '{profile.id}' đang dùng chế độ Timer (không chụp màn hình). "
                "Hãy dùng --test-keys để test gửi phím."
            )
            return
        pid = find_roblox_pid()
        if pid is None:
            print("❌ Không tìm thấy RobloxPlayer đang chạy. Hãy mở game Roblox trước.")
            sys.exit(1)
        win_info = find_roblox_window_id(pid)
        if win_info is None:
            print("❌ Không tìm thấy cửa sổ chính của RobloxPlayer (đảm bảo không bị Minimize).")
            sys.exit(1)
        wid, (ww, wh) = win_info
        default_logger(f"✅ Tìm thấy RobloxPlayer (PID: {pid}, WindowID: {wid}, Size: {ww}x{wh})")
        res = engine.detect_once(wid, save_debug=args.save_debug)
        status = "✅ THẤY NÚT PLAY" if res.found else "❌ KHÔNG THẤY"
        default_logger(
            f"{status} | {res.reason} | green={res.green_ratio:.1%}, "
            f"white={res.white_ratio:.1%}, aspect={res.aspect_ratio:.2f}, bbox={res.rel_bbox}"
        )
        return

    engine.run()


if __name__ == "__main__":
    main()
