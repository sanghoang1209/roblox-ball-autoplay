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
    cooldown_sec: float = 120.0
    step_delay_sec: float = 0.22


@dataclass
class AntiAfkConfig:
    enabled: bool = False
    interval_sec: float = 480.0
    key: str = "space"


@dataclass
class BallSelectionConfig:
    enabled: bool = False
    strategy: str = "fixed"
    model_path: str | None = None
    rankings_path: str | None = None
    ban_cooldown_sec: float = 28.0
    pick_cooldown_sec: float = 22.0
    ban_slot_sequences: dict[str, list[str]] = field(default_factory=dict)
    pick_slot_sequences: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class TriggerRule:
    name: str
    detector: DetectorConfig
    sequence: list[str] | None = None


@dataclass
class Profile:
    id: str
    name: str
    sequence: list[str]
    description: str = ""
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    extra_triggers: list[TriggerRule] = field(default_factory=list)
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
    det_type = str(det_raw.get("type", "green_play_button")).strip().lower()
    if det_type not in ("green_play_button", "timer"):
        raise ValueError(f"Profile '{profile_id}': detector.type không hợp lệ ('{det_type}').")
    detector = DetectorConfig(
        type=det_type,
        roi=_validate_roi(det_raw.get("roi", [0.30, 0.84, 0.70, 0.995])),
        min_green_ratio=float(det_raw.get("min_green_ratio", 0.60)),
        min_white_ratio=float(det_raw.get("min_white_ratio", 0.015)),
        max_white_ratio=float(det_raw.get("max_white_ratio", 0.30)),
    )

    time_raw = data.get("timing", {})
    timing = TimingConfig(
        scan_interval_sec=max(0.2, float(time_raw.get("scan_interval_sec", 3.0))),
        cooldown_sec=max(0.0, float(time_raw.get("cooldown_sec", 120.0))),
        step_delay_sec=max(0.05, float(time_raw.get("step_delay_sec", 0.22))),
    )

    afk_raw = data.get("anti_afk", {})
    afk_key = str(afk_raw.get("key", "space")).strip().lower()
    if afk_key not in KEYCODES:
        raise ValueError(f"Profile '{profile_id}': anti_afk.key không hợp lệ ('{afk_key}').")
    anti_afk = AntiAfkConfig(
        enabled=bool(afk_raw.get("enabled", False)),
        interval_sec=max(10.0, float(afk_raw.get("interval_sec", 480.0))),
        key=afk_key,
    )

    def _parse_slot_map(raw_map: object, field_name: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        if isinstance(raw_map, dict):
            for slot_key, raw_slot_seq in raw_map.items():
                if not isinstance(raw_slot_seq, list):
                    raise ValueError(
                        f"Profile '{profile_id}': ball_selection.{field_name}['{slot_key}'] phải là mảng."
                    )
                norm_seq = [str(tok).strip().lower() for tok in raw_slot_seq if str(tok).strip()]
                validate_sequence_tokens(norm_seq)
                out[str(slot_key)] = norm_seq
        return out

    ball_raw = data.get("ball_selection", {})
    ban_slot_sequences = _parse_slot_map(ball_raw.get("ban_slot_sequences", {}), "ban_slot_sequences")
    pick_slot_sequences = _parse_slot_map(
        ball_raw.get("pick_slot_sequences", ball_raw.get("slot_sequences", {})),
        "pick_slot_sequences",
    )

    ball_selection = BallSelectionConfig(
        enabled=bool(ball_raw.get("enabled", False)),
        strategy=str(ball_raw.get("strategy", "fixed")),
        model_path=ball_raw.get("model_path"),
        rankings_path=ball_raw.get("rankings_path"),
        ban_cooldown_sec=max(5.0, float(ball_raw.get("ban_cooldown_sec", 28.0))),
        pick_cooldown_sec=max(5.0, float(ball_raw.get("pick_cooldown_sec", 22.0))),
        ban_slot_sequences=ban_slot_sequences,
        pick_slot_sequences=pick_slot_sequences,
    )

    extra_triggers: list[TriggerRule] = []
    for idx, trig_raw in enumerate(data.get("extra_triggers", [])):
        t_name = str(trig_raw.get("name", f"trigger_{idx + 1}")).strip()
        t_det_raw = trig_raw.get("detector", {})
        t_det_type = str(t_det_raw.get("type", "green_play_button")).strip().lower()
        if t_det_type not in ("green_play_button",):
            raise ValueError(f"Profile '{profile_id}': extra_triggers[{idx}].detector.type không hợp lệ.")
        t_det = DetectorConfig(
            type=t_det_type,
            roi=_validate_roi(t_det_raw.get("roi", [0.30, 0.84, 0.70, 0.995])),
            min_green_ratio=float(t_det_raw.get("min_green_ratio", 0.55)),
            min_white_ratio=float(t_det_raw.get("min_white_ratio", 0.008)),
            max_white_ratio=float(t_det_raw.get("max_white_ratio", 0.30)),
        )
        t_seq_raw = trig_raw.get("sequence")
        t_seq: list[str] | None = None
        if t_seq_raw is not None:
            if not isinstance(t_seq_raw, list):
                raise ValueError(f"Profile '{profile_id}': extra_triggers[{idx}].sequence phải là mảng.")
            t_seq = [str(tok).strip().lower() for tok in t_seq_raw if str(tok).strip()]
            validate_sequence_tokens(t_seq)
        extra_triggers.append(TriggerRule(name=t_name, detector=t_det, sequence=t_seq))

    return Profile(
        id=profile_id,
        name=name,
        description=str(data.get("description", "")),
        sequence=sequence,
        detector=detector,
        extra_triggers=extra_triggers,
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


def profile_to_dict(profile: Profile) -> dict:
    """Chuyển đối tượng Profile về dict chuẩn JSON."""
    result = {
        "id": profile.id,
        "name": profile.name,
        "description": profile.description,
        "detector": {
            "type": profile.detector.type,
            "roi": list(profile.detector.roi),
            "min_green_ratio": profile.detector.min_green_ratio,
            "min_white_ratio": profile.detector.min_white_ratio,
            "max_white_ratio": profile.detector.max_white_ratio,
        },
        "timing": {
            "scan_interval_sec": profile.timing.scan_interval_sec,
            "cooldown_sec": profile.timing.cooldown_sec,
            "step_delay_sec": profile.timing.step_delay_sec,
        },
        "sequence": list(profile.sequence),
        "anti_afk": {
            "enabled": profile.anti_afk.enabled,
            "interval_sec": profile.anti_afk.interval_sec,
            "key": profile.anti_afk.key,
        },
        "ball_selection": {
            "enabled": profile.ball_selection.enabled,
            "strategy": profile.ball_selection.strategy,
            "model_path": profile.ball_selection.model_path,
            "rankings_path": profile.ball_selection.rankings_path,
            "ban_cooldown_sec": profile.ball_selection.ban_cooldown_sec,
            "pick_cooldown_sec": profile.ball_selection.pick_cooldown_sec,
            "ban_slot_sequences": {k: list(v) for k, v in profile.ball_selection.ban_slot_sequences.items()},
            "pick_slot_sequences": {k: list(v) for k, v in profile.ball_selection.pick_slot_sequences.items()},
        },
    }
    if profile.extra_triggers:
        result["extra_triggers"] = [
            {
                "name": t.name,
                "detector": {
                    "type": t.detector.type,
                    "roi": list(t.detector.roi),
                    "min_green_ratio": t.detector.min_green_ratio,
                    "min_white_ratio": t.detector.min_white_ratio,
                    "max_white_ratio": t.detector.max_white_ratio,
                },
                "sequence": list(t.sequence) if t.sequence is not None else None,
            }
            for t in profile.extra_triggers
        ]
    return result


def save_profile_file(profile: Profile, profiles_dir: Path = DEFAULT_PROFILES_DIR) -> Path:
    """Validate và lưu Profile ra file JSON trong thư mục profiles/."""
    data = profile_to_dict(profile)
    # Re-validate trước khi ghi file
    parse_profile_dict(data)
    target = profile.source_path or (profiles_dir / f"{profile.id}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return target
