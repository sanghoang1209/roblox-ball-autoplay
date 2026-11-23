"""Resolution-independent detector for the green 'Play' button."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from roblox_autoplay.core.profile_loader import DetectorConfig


@dataclass
class DetectionResult:
    found: bool
    reason: str
    green_ratio: float = 0.0
    white_ratio: float = 0.0
    aspect_ratio: float = 0.0
    rel_bbox: tuple[float, float, float, float] | None = None


def detect_play_button(
    img: Image.Image,
    config: DetectorConfig | None = None,
) -> DetectionResult:
    """
    Nhận diện nút 'Play' màu xanh lá sáng ở vùng đáy giữa màn hình.
    Hoạt động tốt ở mọi kích thước cửa sổ Roblox và màn hình Retina.
    """
    cfg = config or DetectorConfig()
    arr = np.asarray(img)
    if arr.ndim != 3 or arr.shape[2] < 3:
        return DetectionResult(False, "Ảnh chụp không hợp lệ")

    h, w = arr.shape[:2]
    if w < 200 or h < 200:
        return DetectionResult(False, f"Kích thước cửa sổ quá nhỏ ({w}x{h})")

    rx0_f, ry0_f, rx1_f, ry1_f = cfg.roi
    rx0, rx1 = int(w * rx0_f), int(w * rx1_f)
    ry0, ry1 = int(h * ry0_f), int(h * ry1_f)
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

    btn_green = green_mask[by0:by1, bx0:bx1]
    btn_rgb = roi[by0:by1, bx0:bx1]
    btn_white = (btn_rgb[:, :, 0] > 210) & (btn_rgb[:, :, 1] > 210) & (btn_rgb[:, :, 2] > 210)

    green_ratio = float(btn_green.mean())
    white_ratio = float(btn_white.mean())

    if green_ratio < cfg.min_green_ratio:
        return DetectionResult(
            False,
            f"Độ phủ xanh quá thấp ({green_ratio:.1%})",
            green_ratio=green_ratio,
            white_ratio=white_ratio,
            aspect_ratio=aspect,
            rel_bbox=rel_bbox,
        )

    if not (cfg.min_white_ratio <= white_ratio <= cfg.max_white_ratio):
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
