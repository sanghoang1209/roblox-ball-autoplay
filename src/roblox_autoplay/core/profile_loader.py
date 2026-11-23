"""Load and validate JSON mode profiles from the profiles/ directory."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from roblox_autoplay.core.macos_input import KEYCODES, validate_sequence_tokens

DEFAULT_PROFILES_DIR = Path(__file__).resolve().parents[3] / "profiles"


@dataclass
class DetectorConfig:
    type: str = "green_play_button"
    roi: tuple[float, float, float, float] = (0.30, 0.84, 0.70, 0.995)
    min_green_ratio: float = 0.60
    min_white_ratio: float = 0.015
    max_white_ratio: float = 0.30


@dataclass
class TimingConfig:
    scan_interval_sec: float = 3.0
    cooldown_sec: float = 180.0
    step_delay_sec: float = 0.22


@dataclass
class AntiAfkConfig:
    enabled: bool = True
    interval_sec: float = 480.0
    key: str = "space"


@dataclass
class BallSelectionConfig:
    enabled: bool = False
    strategy: str = "fixed"
    model_path: str | None = None


@dataclass
class Profile:
    id: str
    name: str
    sequence: list[str]
    description: str = ""
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    anti_afk: AntiAfkConfig = field(default_factory=AntiAfkConfig)
    ball_selection: BallSelectionConfig = field(default_factory=BallSelectionConfig)
    source_path: Path | None = None


def _validate_roi(raw_roi: list[float]) -> tuple[float, float, float, float]:
    if not isinstance(raw_roi, list) or len(raw_roi) != 4:
        raise ValueError("detector.roi phải là mảng 4 số [x0, y0, x1, y1].")
    x0, y0, x1, y1 = (float(v) for v in raw_roi)
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        raise ValueError(f"detector.roi không hợp lệ: {raw_roi} (phải nằm trong [0, 1] và x0<x1, y0<y1).")
    return (x0, y0, x1, y1)


def parse_profile_dict(data: dict, source_path: Path | None = None) -> Profile:
    """Parse & validate một dict JSON thành đối tượng Profile."""
    profile_id = str(data.get("id", "")).strip()
    name = str(data.get("name", "")).strip()
    if not profile_id:
        raise ValueError("Profile thiếu trường 'id'.")
    if not name:
        raise ValueError(f"Profile '{profile_id}' thiếu trường 'name'.")

    raw_seq = data.get("sequence")
    if not isinstance(raw_seq, list):
        raise ValueError(f"Profile '{profile_id}' thiếu mảng 'sequence'.")
    sequence = [str(tok).strip().lower() for tok in raw_seq if str(tok).strip()]
    validate_sequence_tokens(sequence)

    det_raw = data.get("detector", {})
    detector = DetectorConfig(
        type=str(det_raw.get("type", "green_play_button")),
        roi=_validate_roi(det_raw.get("roi", [0.30, 0.84, 0.70, 0.995])),
        min_green_ratio=float(det_raw.get("min_green_ratio", 0.60)),
        min_white_ratio=float(det_raw.get("min_white_ratio", 0.015)),
        max_white_ratio=float(det_raw.get("max_white_ratio", 0.30)),
    )

    time_raw = data.get("timing", {})
    timing = TimingConfig(
        scan_interval_sec=max(0.2, float(time_raw.get("scan_interval_sec", 3.0))),
        cooldown_sec=max(0.0, float(time_raw.get("cooldown_sec", 180.0))),
        step_delay_sec=max(0.05, float(time_raw.get("step_delay_sec", 0.22))),
    )

    afk_raw = data.get("anti_afk", {})
    afk_key = str(afk_raw.get("key", "space")).strip().lower()
    if afk_key not in KEYCODES:
        raise ValueError(f"Profile '{profile_id}': anti_afk.key không hợp lệ ('{afk_key}').")
    anti_afk = AntiAfkConfig(
        enabled=bool(afk_raw.get("enabled", True)),
        interval_sec=max(10.0, float(afk_raw.get("interval_sec", 480.0))),
        key=afk_key,
    )

    ball_raw = data.get("ball_selection", {})
    ball_selection = BallSelectionConfig(
        enabled=bool(ball_raw.get("enabled", False)),
        strategy=str(ball_raw.get("strategy", "fixed")),
        model_path=ball_raw.get("model_path"),
    )

    return Profile(
        id=profile_id,
        name=name,
        description=str(data.get("description", "")),
        sequence=sequence,
        detector=detector,
        timing=timing,
        anti_afk=anti_afk,
        ball_selection=ball_selection,
        source_path=source_path,
    )


def load_profile_file(path: Path) -> Profile:
    """Đọc 1 file JSON profile cụ thể."""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return parse_profile_dict(data, source_path=path)


def list_profiles(profiles_dir: Path = DEFAULT_PROFILES_DIR) -> list[Profile]:
    """Liệt kê tất cả các profile hợp lệ trong thư mục profiles/ (bỏ qua schema.json)."""
    if not profiles_dir.exists():
        return []
    profiles: list[Profile] = []
    for path in sorted(profiles_dir.glob("*.json")):
        if path.name == "schema.json":
            continue
        profiles.append(load_profile_file(path))
    return profiles


def resolve_profile(name_or_path: str, profiles_dir: Path = DEFAULT_PROFILES_DIR) -> Profile:
    """Tìm profile theo đường dẫn file hoặc theo id / tên file trong profiles/."""
    candidate = Path(name_or_path)
    if candidate.is_file():
        return load_profile_file(candidate)

    by_filename = profiles_dir / (
        name_or_path if name_or_path.endswith(".json") else f"{name_or_path}.json"
    )
    if by_filename.is_file():
        return load_profile_file(by_filename)

    for prof in list_profiles(profiles_dir):
        if prof.id == name_or_path:
            return prof

    available = [p.id for p in list_profiles(profiles_dir)]
    raise FileNotFoundError(
        f"Không tìm thấy profile '{name_or_path}'. Các profile hiện có: {', '.join(available) or '(trống)'}"
    )
