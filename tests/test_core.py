"""Unit tests for profile loading, Play button detection, and Anti-AFK tracker."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from roblox_autoplay.core.anti_afk import AntiAfkTracker  # noqa: E402
from roblox_autoplay.core.profile_loader import (  # noqa: E402
    AntiAfkConfig,
    list_profiles,
    parse_profile_dict,
    resolve_profile,
)
from roblox_autoplay.ml.ball_selector import (  # noqa: E402
    BallSelector,
    OcrToken,
    parse_ball_selection_screen,
)
from roblox_autoplay.vision.play_button import detect_play_button  # noqa: E402
from roblox_autoplay.vision.ui_nav import is_sticker_highlighted  # noqa: E402


def _make_synthetic_lobby(width: int = 1024, height: int = 665, with_button: bool = True) -> Image.Image:
    img = Image.new("RGB", (width, height), (35, 55, 85))
    if with_button:
        draw = ImageDraw.Draw(img)
        x0, x1 = int(width * 0.41), int(width * 0.59)
        y0, y1 = int(height * 0.905), int(height * 0.962)
        draw.rectangle([x0, y0, x1, y1], fill=(102, 200, 1))
        # Vẽ chữ giả lập màu trắng ở giữa nút (~5-10% diện tích nút)
        tx0, tx1 = int(width * 0.475), int(width * 0.525)
        ty0, ty1 = int(height * 0.922), int(height * 0.946)
        draw.rectangle([tx0, ty0, tx1, ty1], fill=(255, 255, 255))
    return img


class TestProfileLoader(unittest.TestCase):
    def test_list_and_resolve_default_profile(self) -> None:
        profiles = list_profiles()
        self.assertGreaterEqual(len(profiles), 2)
        prof = resolve_profile("default_play")
        self.assertEqual(prof.id, "default_play")
        self.assertGreater(prof.timing.cooldown_sec, 0)
        self.assertEqual(prof.sequence[0], "backslash")
        self.assertEqual(prof.sequence[-1], "backslash")
        self.assertIn("wait:0.8", prof.sequence)

    def test_resolve_timer_fullscreen_profile(self) -> None:
        prof = resolve_profile("timer_fullscreen")
        self.assertEqual(prof.id, "timer_fullscreen")
        self.assertEqual(prof.detector.type, "timer")
        self.assertEqual(prof.timing.cooldown_sec, 120.0)

    def test_resolve_ranked_profile(self) -> None:
        prof = resolve_profile("ranked")
        self.assertEqual(prof.id, "ranked")
        self.assertEqual(prof.detector.type, "green_play_button")
        self.assertEqual(prof.timing.cooldown_sec, 180.0)
        self.assertEqual(prof.sequence.count("down"), 9)
        self.assertEqual(prof.sequence[0], "backslash")
        self.assertEqual(prof.sequence[-1], "backslash")
        self.assertEqual(len(prof.extra_triggers), 1)
        self.assertEqual(
            prof.extra_triggers[0].sequence,
            ["backslash", "left", "enter", "wait:0.3", "backslash"],
        )

    def test_invalid_key_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_profile_dict({"id": "bad", "name": "Bad", "sequence": ["not_a_key"]})

    def test_invalid_wait_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_profile_dict({"id": "bad", "name": "Bad", "sequence": ["wait:abc"]})

    def test_invalid_roi_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_profile_dict(
                {
                    "id": "bad_roi",
                    "name": "Bad ROI",
                    "sequence": ["space"],
                    "detector": {"roi": [0.8, 0.5, 0.2, 0.9]},
                }
            )


class TestPlayButtonDetector(unittest.TestCase):
    def test_detects_synthetic_button(self) -> None:
        img = _make_synthetic_lobby(1024, 665, with_button=True)
        res = detect_play_button(img)
        self.assertTrue(res.found, msg=res.reason)
        self.assertGreaterEqual(res.green_ratio, 0.60)

    def test_detects_resized_with_titlebar(self) -> None:
        small = _make_synthetic_lobby(640, 420, with_button=True)
        with_bar = Image.new("RGB", (640, 448), (40, 40, 40))
        with_bar.paste(small, (0, 28))
        res = detect_play_button(with_bar)
        self.assertTrue(res.found, msg=res.reason)

    def test_negative_without_button(self) -> None:
        img = _make_synthetic_lobby(1024, 665, with_button=False)
        res = detect_play_button(img)
        self.assertFalse(res.found)

    def test_negative_solid_green_floor(self) -> None:
        img = _make_synthetic_lobby(1024, 665, with_button=False)
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 560, 1024, 665], fill=(102, 200, 10))
        res = detect_play_button(img)
        self.assertFalse(res.found)

    def test_sticker_highlight_detection(self) -> None:
        dark = Image.new("RGB", (1024, 665), (20, 25, 35))
        self.assertFalse(is_sticker_highlighted(dark))
        highlighted = dark.copy()
        draw = ImageDraw.Draw(highlighted)
        draw.rectangle([955, 600, 1018, 660], outline=(245, 250, 255), width=6)
        self.assertTrue(is_sticker_highlighted(highlighted))


class TestAntiAfkTracker(unittest.TestCase):
    def test_due_and_reset(self) -> None:
        tracker = AntiAfkTracker(AntiAfkConfig(enabled=True, interval_sec=100.0), now=1000.0)
        self.assertFalse(tracker.is_due(now=1050.0))
        self.assertTrue(tracker.is_due(now=1100.0))
        tracker.mark_activity(now=1100.0)
        self.assertFalse(tracker.is_due(now=1150.0))

    def test_disabled(self) -> None:
        tracker = AntiAfkTracker(AntiAfkConfig(enabled=False, interval_sec=10.0), now=0.0)
        self.assertFalse(tracker.is_due(now=9999.0))


class TestBallSelector(unittest.TestCase):
    def test_picks_highest_tier_ball(self) -> None:
        selector = BallSelector.from_file()
        choice = selector.pick_best(["Cactus Ball", "Laser Ball", "Chess"])
        self.assertIsNotNone(choice)
        assert choice is not None
        self.assertEqual(choice.slot_index, 1)
        self.assertEqual(choice.matched_ball.name, "Laser")
        self.assertEqual(choice.matched_ball.tier, "S")

    def test_fuzzy_matches_ocr_typo(self) -> None:
        selector = BallSelector.from_file()
        match = selector.match_ball("Vamplre Bal")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.name, "Vampire")

    def test_parse_ban_and_pick_screens(self) -> None:
        selector = BallSelector.from_file()

        # 1. CHECK BOTH SIDES (preview -> should not trigger)
        preview_tokens = [
            OcrToken("CHECK BOTH SIDES", 0.455, 0.141, 1.0),
            OcrToken("WDC", 0.286, 0.676, 1.0),
            OcrToken("Glass Ball", 0.455, 0.677, 1.0),
            OcrToken("Dice Ball", 0.623, 0.676, 1.0),
        ]
        prev = parse_ball_selection_screen(preview_tokens, selector)
        self.assertFalse(prev.detected)
        self.assertEqual(prev.phase, "PREVIEW")

        # 2. BAN OPPONENT'S BALL (3 opponent cards -> ban Electric over Pi & Big Spike)
        ban_tokens = [
            OcrToken("BAN OPPONENT'S BALL", 0.456, 0.143, 1.0),
            OcrToken("Pi Ball", 0.259, 0.360, 1.0),
            OcrToken("Electric Ball", 0.456, 0.359, 1.0),
            OcrToken("Big Spike Ball", 0.654, 0.360, 1.0),
        ]
        ban = parse_ball_selection_screen(ban_tokens, selector)
        self.assertTrue(ban.detected)
        self.assertEqual(ban.phase, "BAN")
        assert ban.best_choice is not None
        self.assertEqual(ban.best_choice.slot_index, 1)
        self.assertEqual(ban.best_choice.matched_ball.name, "Electric")

        # 3. PICK YOUR BALL (2 player cards -> pick Laser over WDC)
        pick_tokens = [
            OcrToken("PICK YOUR BALL", 0.455, 0.147, 1.0),
            OcrToken("Laser Ball", 0.356, 0.550, 1.0),
            OcrToken("WDC", 0.553, 0.548, 1.0),
        ]
        pick = parse_ball_selection_screen(pick_tokens, selector)
        self.assertTrue(pick.detected)
        self.assertEqual(pick.phase, "PICK")
        assert pick.best_choice is not None
        self.assertEqual(pick.best_choice.slot_index, 0)
        self.assertEqual(pick.best_choice.matched_ball.name, "Laser")


if __name__ == "__main__":
    unittest.main()
