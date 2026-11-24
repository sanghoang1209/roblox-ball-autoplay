"""Main AutoPlayEngine with clean callbacks so both CLI and GUI/Menu Bar can drive it."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from roblox_autoplay.core.anti_afk import AntiAfkTracker
from roblox_autoplay.core.macos_input import run_key_sequence, send_bg_key
from roblox_autoplay.core.macos_window import (
    capture_window,
    find_roblox_pid,
    find_roblox_window_id,
)
from roblox_autoplay.core.profile_loader import Profile
from roblox_autoplay.ml.ball_selector import (
    BallSelector,
    ocr_pil_image,
    parse_ball_selection_screen,
)
from roblox_autoplay.vision.play_button import DetectionResult, detect_play_button
from roblox_autoplay.vision.ui_nav import is_sticker_highlighted

DEFAULT_LOG_FILE = Path(__file__).resolve().parents[3] / "data" / "logs" / "autoplay.log"


def _append_log_file(line: str, log_file: Path = DEFAULT_LOG_FILE) -> None:
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def default_logger(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    _append_log_file(line)


class AutoPlayEngine:
    """
    Vòng lặp chạy ngầm tách biệt khỏi CLI/UI.
    Phase 3 (Menu Bar / GUI App) có thể gọi `run()` trong background thread và dừng bằng `stop()`.
    """

    def __init__(
        self,
        profile: Profile,
        dry_run: bool = False,
        on_log: Callable[[str], None] | None = None,
        on_play_count: Callable[[int], None] | None = None,
        on_state_change: Callable[[str], None] | None = None,
    ) -> None:
        self.profile = profile
        self.dry_run = dry_run
        self._user_log = on_log
        self._on_play_count = on_play_count
        self._on_state_change = on_state_change

        self._stop_event = threading.Event()
        self.play_count = 0
        self.state = "IDLE"
        self._ball_selector: BallSelector | None = None
        if self.profile.ball_selection.enabled and self.profile.ball_selection.strategy == "ranking_ocr":
            rankings_path = self.profile.ball_selection.rankings_path
            if rankings_path:
                self._ball_selector = BallSelector.from_file(Path(rankings_path))
            else:
                self._ball_selector = BallSelector.from_file()

    def _log(self, msg: str) -> None:
        if self._user_log is not None:
            ts = datetime.now().strftime("%H:%M:%S")
            _append_log_file(f"[{ts}] {msg}")
            self._user_log(msg)
        else:
            default_logger(msg)

    def _ensure_ui_nav_at_sticker(self, pid: int, wid: int, current_img: object) -> bool:
        """
        Đảm bảo UI Navigation đang BẬT và đứng đúng tại nút Sticker góc dưới phải
        trước khi gửi phím mũi tên. Tự sửa nếu bị ngược trạng thái bật/tắt ('\\').
        """
        if is_sticker_highlighted(current_img):
            self._log("🧭 UI Navigation đã bật sẵn ở nút Sticker — không cần bấm '\\' mở đầu.")
            return True

        for attempt in range(1, 3):
            send_bg_key(pid, "backslash")
            time.sleep(0.40)
            try:
                check_img = capture_window(wid)
            except RuntimeError:
                return True
            if is_sticker_highlighted(check_img):
                return True
            if attempt == 1:
                self._log("🔄 Chưa thấy khung ở nút Sticker (có thể UI Nav vừa tắt), bấm '\\' lại lần 2...")

        self._log("⚠️  Không xác nhận được khung UI Nav ở nút Sticker, vẫn thử tiếp tục chuỗi phím.")
        return False

    def _turn_off_ui_nav_if_on_sticker(self, pid: int, wid: int) -> None:
        """Sau khi bấm Confirm, chỉ bấm '\\' tắt UI Navigation nếu nó vẫn đang bật ở nút Sticker."""
        time.sleep(0.45)
        try:
            after_img = capture_window(wid)
        except RuntimeError:
            return
        if is_sticker_highlighted(after_img):
            self._log("🧭 UI Navigation vẫn còn bật ở nút Sticker -> bấm '\\' để tắt gọn.")
            send_bg_key(pid, "backslash")

    @staticmethod
    def _strip_outer_backslashes(sequence: list[str]) -> list[str]:
        """Bỏ '\\' đầu/cuối (và wait ngay trước '\\' cuối) vì engine đã tự quản lý trạng thái '\\'."""
        seq = list(sequence)
        if seq and seq[0] == "backslash":
            seq = seq[1:]
        if seq and seq[-1] == "backslash":
            seq = seq[:-1]
            while seq and seq[-1].startswith("wait:"):
                seq = seq[:-1]
        return seq

    def _try_ban_or_pick_ball(
        self,
        pid: int,
        wid: int,
        last_ban_ts: float,
        last_pick_ts: float,
    ) -> tuple[float, float]:
        """Kiểm tra màn hình BAN / PICK qua OCR và tự gửi chuỗi UI Navigation tương ứng."""
        if self._ball_selector is None:
            return last_ban_ts, last_pick_ts

        now = time.time()
        cfg = self.profile.ball_selection
        can_ban = (now - last_ban_ts) >= cfg.ban_cooldown_sec
        can_pick = (now - last_pick_ts) >= cfg.pick_cooldown_sec
        if not can_ban and not can_pick:
            return last_ban_ts, last_pick_ts

        try:
            img = capture_window(wid)
        except RuntimeError:
            return last_ban_ts, last_pick_ts

        tokens = ocr_pil_image(img)
        ball_res = parse_ball_selection_screen(tokens, self._ball_selector)
        if not ball_res.detected or ball_res.best_choice is None:
            return last_ban_ts, last_pick_ts

        best = ball_res.best_choice
        slots_summary = ", ".join(
            f"[{s.slot_index}] {s.raw_text or '?'}({s.score})" for s in ball_res.slots
        )

        if ball_res.phase == "BAN":
            if not can_ban:
                return last_ban_ts, last_pick_ts
            self._log(
                f"🚫 Pha BAN đối thủ: {slots_summary} "
                f"-> Cấm ô {best.slot_index} ({best.raw_text}, điểm {best.score})"
            )
            seq = cfg.ban_slot_sequences.get(str(best.slot_index))
            if not seq:
                self._log(f"⚠️  Chưa cấu hình ban_slot_sequences cho ô {best.slot_index}.")
                return time.time(), last_pick_ts
            if not self.dry_run:
                self._ensure_ui_nav_at_sticker(pid, wid, img)
                core_seq = self._strip_outer_backslashes(seq)
                run_key_sequence(
                    pid,
                    core_seq,
                    step_delay=max(0.28, self.profile.timing.step_delay_sec),
                    on_log=self._log,
                )
                self._turn_off_ui_nav_if_on_sticker(pid, wid)
            return time.time(), last_pick_ts

        if ball_res.phase == "PICK":
            if not can_pick:
                return last_ban_ts, last_pick_ts
            self._log(
                f"⚽ Pha PICK bóng: {slots_summary} "
                f"-> Chọn ô {best.slot_index} ({best.raw_text}, điểm {best.score})"
            )
            seq = cfg.pick_slot_sequences.get(str(best.slot_index))
            if not seq:
                self._log(f"⚠️  Chưa cấu hình pick_slot_sequences cho ô {best.slot_index}.")
                return last_ban_ts, time.time()
            if not self.dry_run:
                self._ensure_ui_nav_at_sticker(pid, wid, img)
                core_seq = self._strip_outer_backslashes(seq)
                run_key_sequence(
                    pid,
                    core_seq,
                    step_delay=max(0.28, self.profile.timing.step_delay_sec),
                    on_log=self._log,
                )
                self._turn_off_ui_nav_if_on_sticker(pid, wid)
            return last_ban_ts, time.time()

        return last_ban_ts, last_pick_ts

    def _set_state(self, new_state: str) -> None:
        if new_state != self.state:
            self.state = new_state
            if self._on_state_change:
                self._on_state_change(new_state)

    def stop(self) -> None:
        self._stop_event.set()

    def _sleep(self, seconds: float) -> None:
        self._stop_event.wait(timeout=max(0.0, seconds))

    def detect_with_triggers(
        self, window_id: int, save_debug: str = ""
    ) -> tuple[DetectionResult, list[str], str]:
        """Kiểm tra detector chính và tất cả extra_triggers trên cùng 1 ảnh chụp."""
        img = capture_window(window_id)
        if save_debug:
            img.save(save_debug)
            self._log(f"💾 Đã lưu ảnh chụp kiểm tra tại: {save_debug}")

        primary_res = detect_play_button(img, self.profile.detector)
        if primary_res.found:
            return primary_res, self.profile.sequence, "primary"

        for trigger in self.profile.extra_triggers:
            alt_res = detect_play_button(img, trigger.detector)
            if alt_res.found:
                seq = trigger.sequence if trigger.sequence is not None else self.profile.sequence
                return alt_res, seq, trigger.name

        return primary_res, self.profile.sequence, "primary"

    def detect_once(self, window_id: int, save_debug: str = "") -> DetectionResult:
        res, _, _ = self.detect_with_triggers(window_id, save_debug=save_debug)
        return res

    def run(self) -> None:
        """Chạy vòng lặp quét & tự động bấm cho đến khi `stop()` hoặc Ctrl+C."""
        self._stop_event.clear()
        timing = self.profile.timing
        afk_tracker = AntiAfkTracker(self.profile.anti_afk)

        pid: int | None = None
        wid: int | None = None
        last_play_ts = 0.0
        last_ban_ts = 0.0
        last_pick_ts = 0.0
        consecutive_hits = 0

        is_timer_mode = self.profile.detector.type == "timer"

        self._log(f"🧩 Profile: {self.profile.name} ({self.profile.id})")
        if self._ball_selector is not None:
            self._log("⚽ Tự động Ban & Pick bóng (OCR + Ranking): BẬT")
        if is_timer_mode:
            self._log(
                f"⏱️  Chế độ Timer (chạy xuyên Fullscreen, không chụp màn hình) | "
                f"Chu kỳ: mỗi {int(timing.cooldown_sec)}s | "
                f"Chuỗi phím: {' -> '.join(self.profile.sequence)}"
            )
        else:
            self._log(
                f"🚀 Bắt đầu chạy ngầm! Quét mỗi {timing.scan_interval_sec}s | "
                f"Cooldown: {int(timing.cooldown_sec)}s | "
                f"Chuỗi phím: {' -> '.join(self.profile.sequence)}"
            )
        if self.profile.anti_afk.enabled:
            self._log(
                f"🛡️  Chống AFK bật (tự bấm '{self.profile.anti_afk.key}' "
                f"mỗi ~{int(self.profile.anti_afk.interval_sec)}s)"
            )
        if self.dry_run:
            self._log("🧪 Đang ở chế độ DRY-RUN (không gửi phím bấm).")
        self._log("   Nhấn Ctrl+C để dừng.")

        try:
            if is_timer_mode:
                self._log("👉 Bắt đầu gửi chuỗi đầu tiên sau 3 giây...")
                self._sleep(3.0)

            while not self._stop_event.is_set():
                now = time.time()
                cur_pid = find_roblox_pid()

                if cur_pid is None:
                    self._set_state("WAITING_ROBLOX")
                    if pid is not None:
                        self._log("⏳ RobloxPlayer đã đóng... đang chờ mở lại.")
                    else:
                        self._log("⏳ Chưa thấy RobloxPlayer... đang chờ mở game.")
                    pid = None
                    wid = None
                    self._sleep(5.0)
                    continue

                if is_timer_mode:
                    if cur_pid != pid:
                        pid = cur_pid
                        self._log(f"✅ Kết nối RobloxPlayer (PID: {pid}) [Timer mode]")

                    if last_play_ts > 0.0 and (now - last_play_ts) < timing.cooldown_sec:
                        self._set_state("COOLDOWN")
                        if not self.dry_run and afk_tracker.is_due():
                            self._log(f"🛡️  Gửi phím '{self.profile.anti_afk.key}' ngầm chống AFK...")
                            send_bg_key(pid, self.profile.anti_afk.key)
                            afk_tracker.mark_triggered()
                        remaining = timing.cooldown_sec - (now - last_play_ts)
                        self._sleep(min(timing.scan_interval_sec, remaining))
                        continue

                    self._set_state("PLAYING_SEQUENCE")
                    self.play_count += 1
                    if self._on_play_count:
                        self._on_play_count(self.play_count)

                    self._log(f"⏱️  Đến chu kỳ Timer (#{self.play_count})")
                    if not self.dry_run:
                        run_key_sequence(
                            pid,
                            self.profile.sequence,
                            step_delay=timing.step_delay_sec,
                            on_log=self._log,
                        )
                    last_play_ts = time.time()
                    afk_tracker.mark_activity(last_play_ts)
                    self._log(f"⏸️  Hẹn lần bấm tiếp theo sau {int(timing.cooldown_sec)}s...")
                    self._set_state("COOLDOWN")
                    continue

                win_info = find_roblox_window_id(cur_pid)
                if win_info is None:
                    self._set_state("WAITING_WINDOW")
                    self._log("⚠️  Chưa tìm thấy cửa sổ chính của Roblox (đảm bảo không bị Minimize).")
                    self._sleep(3.0)
                    continue
                new_wid, (ww, wh) = win_info
                if cur_pid != pid or new_wid != wid:
                    pid = cur_pid
                    wid = new_wid
                    self._log(f"✅ Kết nối RobloxPlayer (PID: {pid}, WindowID: {wid}, Size: {ww}x{wh})")
                    self._set_state("SCANNING")

                # Trong thời gian cooldown sau khi bấm Play:
                # - Nếu tắt Ban/Pick tự động -> bỏ qua chụp màn hình cho nhẹ máy
                # - Nếu bật Ban/Pick tự động -> vẫn quét OCR mỗi ~1.5s để tự Ban & Pick giữa các round
                if last_play_ts > 0.0 and (now - last_play_ts) < timing.cooldown_sec:
                    self._set_state("COOLDOWN")
                    if self._ball_selector is not None:
                        last_ban_ts, last_pick_ts = self._try_ban_or_pick_ball(
                            pid, wid, last_ban_ts, last_pick_ts
                        )
                    if not self.dry_run and afk_tracker.is_due():
                        self._log(f"🛡️  Gửi phím '{self.profile.anti_afk.key}' ngầm chống AFK...")
                        send_bg_key(pid, self.profile.anti_afk.key)
                        afk_tracker.mark_triggered()
                    remaining = timing.cooldown_sec - (now - last_play_ts)
                    step_sleep = 1.5 if self._ball_selector is not None else timing.scan_interval_sec
                    self._sleep(min(step_sleep, remaining))
                    continue

                if self._ball_selector is not None:
                    last_ban_ts, last_pick_ts = self._try_ban_or_pick_ball(
                        pid, wid, last_ban_ts, last_pick_ts
                    )

                try:
                    res, matched_seq, trigger_name = self.detect_with_triggers(wid)
                except RuntimeError as exc:
                    self._log(f"⚠️  {exc}")
                    win_info = find_roblox_window_id(pid)
                    if win_info:
                        wid, _ = win_info
                    self._sleep(timing.scan_interval_sec)
                    continue

                if res.found:
                    consecutive_hits += 1
                    if consecutive_hits >= 2 or timing.scan_interval_sec >= 3.0:
                        self._set_state("PLAYING_SEQUENCE")
                        self.play_count += 1
                        if self._on_play_count:
                            self._on_play_count(self.play_count)

                        tag = f" ({trigger_name})" if trigger_name != "primary" else ""
                        self._log(
                            f"🎯 Phát hiện nút Play{tag} (#{self.play_count}) "
                            f"[green={res.green_ratio:.0%}, white={res.white_ratio:.1%}]"
                        )
                        if not self.dry_run:
                            seq_to_run = list(matched_seq)
                            try:
                                pre_img = capture_window(wid)
                                if seq_to_run and seq_to_run[0] == "backslash" and is_sticker_highlighted(pre_img):
                                    self._log("🧭 UI Navigation đã bật sẵn ở nút Sticker — bỏ qua '\\' mở đầu.")
                                    seq_to_run = seq_to_run[1:]
                            except RuntimeError:
                                pass
                            run_key_sequence(
                                pid,
                                seq_to_run,
                                step_delay=timing.step_delay_sec,
                                on_log=self._log,
                            )
                        last_play_ts = time.time()
                        afk_tracker.mark_activity(last_play_ts)
                        consecutive_hits = 0
                        self._log(f"⏸️  Nghỉ cooldown {int(timing.cooldown_sec)}s trước khi quét lại...")
                        self._set_state("COOLDOWN")
                else:
                    consecutive_hits = 0
                    self._set_state("SCANNING")

                if not self.dry_run and afk_tracker.is_due():
                    self._log(f"🛡️  Gửi phím '{self.profile.anti_afk.key}' ngầm chống AFK...")
                    send_bg_key(pid, self.profile.anti_afk.key)
                    afk_tracker.mark_triggered()

                self._sleep(timing.scan_interval_sec)

        except KeyboardInterrupt:
            pass
        finally:
            self._set_state("STOPPED")
            self._log(f"👋 Đã dừng tool. Tổng số lần bấm Play: {self.play_count}")
