"""Detect Roblox UI Navigation highlight state on the bottom-right Sticker/Emote button."""

from __future__ import annotations

import numpy as np
from PIL import Image


def sticker_highlight_ratio(img: Image.Image) -> float:
    """
    Tính tỉ lệ pixel viền sáng trắng/xanh của khung UI Navigation ở góc dưới bên phải
    (vị trí nút Emote/Sticker nơi UI Navigation luôn bắt đầu khi bật trên màn hình Ban/Pick/Spectating).
    - Khi tắt (hoặc khung đang ở chỗ khác): ~1.9% - 2.5%
    - Khi bật và đang nằm ở nút Sticker   : ~10.8% - 13.1%
    """
    arr = np.asarray(img)
    if arr.ndim != 3 or arr.shape[2] < 3:
        return 0.0
    h, w = arr.shape[:2]
    if w < 200 or h < 200:
        return 0.0

    roi = arr[int(h * 0.88) : h, int(w * 0.92) : w]
    bright = (roi[:, :, 0] > 210) & (roi[:, :, 1] > 225) & (roi[:, :, 2] > 235)
    return float(bright.mean())


def is_sticker_highlighted(img: Image.Image, threshold: float = 0.06) -> bool:
    """Trả về True nếu khung UI Navigation đang bật và đứng tại nút Sticker góc dưới phải."""
    return sticker_highlight_ratio(img) >= threshold
