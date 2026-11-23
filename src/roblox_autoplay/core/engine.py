"""Main AutoPlayEngine with clean callbacks so both CLI and GUI/Menu Bar can drive it."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Callable

from roblox_autoplay.core.anti_afk import AntiAfkTracker
from roblox_autoplay.core.macos_input import run_key_sequence, send_bg_key
from roblox_autoplay.core.macos_window import (
    capture_window,
    find_roblox_pid,
    find_roblox_window_id,
)
from roblox_autoplay.core.profile_loader import Profile
from roblox_autoplay.vision.play_button import DetectionResult, detect_play_button


def default_logger(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


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
        self._log = on_log or default_logger
        self._on_play_count = on_play_count
        self._on_state_change = on_state_change

        self._stop_event = threading.Event()
        self.play_count = 0
        self.state = "IDLE"

    def _set_state(self, new_state: str) -> None:
        if new_state != self.state:
            self.state = new_state
            if self._on_state_change:
                self._on_state_change(new_state)

    def stop(self) -> None:
        self._stop_event.set()

    def _sleep(self, seconds: float) -> None:
        self._stop_event.wait(timeout=max(0.0, seconds))

    def detect_once(self, window_id: int, save_debug: str = "") -> DetectionResult:
        img = capture_window(window_id)
        if save_debug:
            img.save(save_debug)
            self._log(f"💾 Đã lưu ảnh chụp kiểm tra tại: {save_debug}")
        return detect_play_button(img, self.profile.detector)

    def run(self) -> None:
        """Chạy vòng lặp quét & tự động bấm cho đến khi `stop()` hoặc Ctrl+C."""
        self._stop_event.clear()
        timing = self.profile.timing
        afk_tracker = AntiAfkTracker(self.profile.anti_afk)

        pid: int | None = None
        wid: int | None = None
        last_play_ts = 0.0
        consecutive_hits = 0

        self._log(f"🧩 Profile: {self.profile.name} ({self.profile.id})")
        self._log(
            f"🚀 Bắt đầu chạy ngầm! Quét mỗi {timing.scan_interval_sec}s | "
            f"Chuỗi phím: {' -> '.join(self.profile.sequence)}"
        )
        if self.profile.anti_afk.enabled:
            self._log(
                f"🛡️  Chống AFK bật (tự bấm '{self.profile.anti_afk.key}' "
                f"mỗi ~{int(self.profile.anti_afk.interval_sec)}s)"
            )
        if self.dry_run:
            self._log("🧪 Đang ở chế độ DRY-RUN (chỉ nhận diện, không bấm phím).")
        self._log("   Nhấn Ctrl+C để dừng.")

        try:
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

                if cur_pid != pid or wid is None:
                    win_info = find_roblox_window_id(cur_pid)
                    if win_info is None:
                        self._set_state("WAITING_WINDOW")
                        self._log("⚠️  Chưa tìm thấy cửa sổ chính của Roblox (đảm bảo không bị Minimize).")
                        self._sleep(3.0)
                        continue
                    pid = cur_pid
                    wid, (ww, wh) = win_info
                    self._log(f"✅ Kết nối RobloxPlayer (PID: {pid}, WindowID: {wid}, Size: {ww}x{wh})")
                    self._set_state("SCANNING")

                # Trong thời gian cooldown sau khi bấm Play, bỏ qua chụp màn hình để tiết kiệm tài nguyên
                if last_play_ts > 0.0 and (now - last_play_ts) < timing.cooldown_sec:
                    self._set_state("COOLDOWN")
                    if not self.dry_run and afk_tracker.is_due():
                        self._log(f"🛡️  Gửi phím '{self.profile.anti_afk.key}' ngầm chống AFK...")
                        send_bg_key(pid, self.profile.anti_afk.key)
                        afk_tracker.mark_triggered()
                    remaining = timing.cooldown_sec - (now - last_play_ts)
                    self._sleep(min(timing.scan_interval_sec, remaining))
                    continue

                try:
                    res = self.detect_once(wid)
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

                        self._log(
                            f"🎯 Phát hiện nút Play (#{self.play_count}) "
                            f"[green={res.green_ratio:.0%}, white={res.white_ratio:.1%}]"
                        )
                        if not self.dry_run:
                            run_key_sequence(
                                pid,
                                self.profile.sequence,
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
