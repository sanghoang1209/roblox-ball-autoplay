"""Anti-AFK tracker to prevent Roblox 20-minute inactivity kicks."""

from __future__ import annotations

import random
import time

from roblox_autoplay.core.profile_loader import AntiAfkConfig


class AntiAfkTracker:
    def __init__(self, config: AntiAfkConfig, now: float | None = None) -> None:
        self.config = config
        self._last_action_ts = time.time() if now is None else now

    def mark_activity(self, now: float | None = None) -> None:
        self._last_action_ts = time.time() if now is None else now

    def is_due(self, now: float | None = None) -> bool:
        if not self.config.enabled:
            return False
        current = time.time() if now is None else now
        return (current - self._last_action_ts) >= self.config.interval_sec

    def mark_triggered(self, now: float | None = None, jitter_sec: float = 30.0) -> None:
        current = time.time() if now is None else now
        offset = random.uniform(-jitter_sec, jitter_sec) if jitter_sec > 0 else 0.0
        self._last_action_ts = current + offset
