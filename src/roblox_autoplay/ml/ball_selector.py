"""Ball ranking lookup, fuzzy matching, fast compiled macOS Vision OCR, and screen parser."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

DEFAULT_RANKINGS_PATH = Path(__file__).resolve().parents[3] / "config" / "ball_rankings.json"
_OCR_CACHE_DIR = Path.home() / ".cache" / "roblox_autoplay"

_SWIFT_OCR_SCRIPT = r"""
import Foundation
import Vision
import AppKit

let args = CommandLine.arguments
guard args.count >= 2 else { exit(1) }
let path = args[1]
guard let img = NSImage(contentsOfFile: path),
      let cgImg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    exit(2)
}

var results: [[String: Any]] = []
let request = VNRecognizeTextRequest { req, _ in
    guard let obs = req.results as? [VNRecognizedTextObservation] else { return }
    for item in obs {
        if let top = item.topCandidates(1).first {
            let box = item.boundingBox
            results.append([
                "text": top.string,
                "cx": box.origin.x + box.size.width / 2.0,
                "cy": 1.0 - (box.origin.y + box.size.height / 2.0),
                "confidence": top.confidence
            ])
        }
    }
}
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false

let handler = VNImageRequestHandler(cgImage: cgImg, options: [:])
try? handler.perform([request])

if let data = try? JSONSerialization.data(withJSONObject: results),
   let out = String(data: data, encoding: .utf8) {
    print(out)
}
"""


@dataclass(frozen=True)
class BallEntry:
    name: str
    tier: str
    score: int
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class BallChoice:
    slot_index: int
    raw_text: str
    matched_ball: BallEntry | None
    score: int


@dataclass(frozen=True)
class OcrToken:
    text: str
    cx: float
    cy: float
    confidence: float


@dataclass(frozen=True)
class BallScreenDetection:
    detected: bool
    phase: str  # "BAN", "PICK", "PREVIEW", or "NONE"
    header_text: str
    slots: list[BallChoice]
    best_choice: BallChoice | None


def _normalize(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in text)
    parts = [p for p in cleaned.split() if p != "ball"]
    return " ".join(parts).strip()


class BallSelector:
    """Chọn trái banh có điểm xếp hạng cao nhất từ bảng tier list."""

    def __init__(self, entries: list[BallEntry]) -> None:
        self.entries = entries
        self._lookup: dict[str, BallEntry] = {}
        for entry in entries:
            self._lookup[_normalize(entry.name)] = entry
            for alias in entry.aliases:
                self._lookup[_normalize(alias)] = entry

    @classmethod
    def from_file(cls, path: Path = DEFAULT_RANKINGS_PATH) -> "BallSelector":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        entries = [
            BallEntry(
                name=str(item["name"]),
                tier=str(item.get("tier", "C")),
                score=int(item.get("score", 30)),
                aliases=tuple(str(a) for a in item.get("aliases", [])),
            )
            for item in data.get("balls", [])
        ]
        return cls(entries)

    def match_ball(self, raw_text: str) -> BallEntry | None:
        norm = _normalize(raw_text)
        if not norm:
            return None
        if norm in self._lookup:
            return self._lookup[norm]

        keys = list(self._lookup.keys())
        candidates = difflib.get_close_matches(norm, keys, n=1, cutoff=0.72)
        if candidates:
            return self._lookup[candidates[0]]

        words = norm.split()
        if len(words) > 1:
            shorter = " ".join(words[:-1])
            candidates = difflib.get_close_matches(shorter, keys, n=1, cutoff=0.72)
            if candidates:
                return self._lookup[candidates[0]]
        return None

    def pick_best(self, slot_texts: list[str]) -> BallChoice | None:
        """Nhận danh sách tên bóng ở các ô lựa chọn và trả về ô có điểm cao nhất."""
        if not slot_texts:
            return None

        best: BallChoice | None = None
        for idx, raw in enumerate(slot_texts):
            entry = self.match_ball(raw)
            score = entry.score if entry is not None else 0
            choice = BallChoice(slot_index=idx, raw_text=raw, matched_ball=entry, score=score)
            if best is None or choice.score > best.score:
                best = choice
        return best


def _ensure_ocr_binary() -> Path | None:
    """Biên dịch sẵn helper Swift OCR 1 lần bằng swiftc -O để mỗi lần OCR chỉ mất ~0.15s."""
    digest = hashlib.sha256(_SWIFT_OCR_SCRIPT.encode("utf-8")).hexdigest()[:12]
    bin_path = _OCR_CACHE_DIR / f"macos_ocr_{digest}"
    if bin_path.is_file() and os.access(bin_path, os.X_OK):
        return bin_path

    try:
        _OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        src_path = _OCR_CACHE_DIR / f"macos_ocr_{digest}.swift"
        src_path.write_text(_SWIFT_OCR_SCRIPT, encoding="utf-8")
        res = subprocess.run(
            ["/usr/bin/swiftc", "-O", str(src_path), "-o", str(bin_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if res.returncode == 0 and bin_path.is_file():
            return bin_path
    except Exception:  # noqa: BLE001
        pass
    return None


def ocr_image_macos(image_path: str | Path) -> list[OcrToken]:
    """Đọc chữ & tọa độ chuẩn hóa (cx, cy trong [0, 1]) từ ảnh bằng Apple Vision OCR."""
    binary = _ensure_ocr_binary()
    cmd = (
        [str(binary), str(image_path)]
        if binary is not None
        else ["/usr/bin/swift", "-e", _SWIFT_OCR_SCRIPT, str(image_path)]
    )
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if res.returncode != 0 or not res.stdout.strip():
        return []
    raw_items = json.loads(res.stdout)
    return [
        OcrToken(
            text=str(item["text"]),
            cx=float(item["cx"]),
            cy=float(item["cy"]),
            confidence=float(item.get("confidence", 0.0)),
        )
        for item in raw_items
    ]


def ocr_pil_image(img: Image.Image) -> list[OcrToken]:
    """Chạy OCR trên một ảnh PIL.Image (dùng file tạm và xóa ngay lập tức)."""
    fd, tmp_path = tempfile.mkstemp(prefix="roblox_ocr_", suffix=".png")
    os.close(fd)
    try:
        img.save(tmp_path)
        return ocr_image_macos(tmp_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def parse_ball_selection_screen(
    tokens: list[OcrToken],
    selector: BallSelector,
) -> BallScreenDetection:
    """
    Phân tích kết quả OCR màn hình Ban / Pick bóng trong Ball VS Ball Ranked:
    - Pha BAN ("BAN OPPONENT'S BALL"):
        3 thẻ đối thủ ở hàng trên (cy in [0.30, 0.43]):
          Slot 0 (trái): cx < 0.36
          Slot 1 (giữa): 0.36 <= cx < 0.56
          Slot 2 (phải): cx >= 0.56
        -> Chọn bóng mạnh nhất của đối thủ để BAN.
    - Pha PICK ("PICK YOUR BALL"):
        2 thẻ của người chơi ở hàng dưới (cy in [0.50, 0.62]):
          Slot 0 (trái): cx < 0.45
          Slot 1 (phải): cx >= 0.45
        -> Chọn bóng mạnh nhất của bạn để PICK.
    - Pha PREVIEW ("CHECK BOTH SIDES"):
        Chỉ xem trước 3s, không bấm gì.
    """
    header_parts = [
        t.text.strip()
        for t in tokens
        if 0.22 <= t.cx <= 0.72 and 0.08 <= t.cy <= 0.22 and len(t.text.strip()) >= 3
    ]
    header_text = " ".join(header_parts)
    header_upper = header_text.upper()

    if "CHECK BOTH SIDES" in header_upper:
        return BallScreenDetection(
            detected=False,
            phase="PREVIEW",
            header_text=header_text,
            slots=[],
            best_choice=None,
        )

    # Kiểm tra pha BAN OPPONENT'S BALL (3 ô đối thủ ở cy ~ 0.36)
    if "BAN" in header_upper:
        slot_raw = ["", "", ""]
        slot_matched: list[BallEntry | None] = [None, None, None]
        for tok in tokens:
            if not (0.30 <= tok.cy <= 0.43 and 0.14 <= tok.cx <= 0.78):
                continue
            if tok.cx < 0.36:
                idx = 0
            elif tok.cx < 0.56:
                idx = 1
            else:
                idx = 2
            entry = selector.match_ball(tok.text)
            if entry is not None or not slot_raw[idx]:
                slot_raw[idx] = tok.text.strip()
                slot_matched[idx] = entry

        slots = [
            BallChoice(
                slot_index=i,
                raw_text=slot_raw[i],
                matched_ball=slot_matched[i],
                score=slot_matched[i].score if slot_matched[i] is not None else 0,
            )
            for i in range(3)
        ]
        non_empty = [s for s in slots if s.raw_text]
        if len(non_empty) >= 2:
            best = max(non_empty, key=lambda c: c.score)
            return BallScreenDetection(
                detected=True,
                phase="BAN",
                header_text=header_text,
                slots=slots,
                best_choice=best,
            )

    # Kiểm tra pha PICK YOUR BALL (2 ô của người chơi ở cy ~ 0.55)
    if "PICK" in header_upper or "CHOOSE" in header_upper:
        slot_raw = ["", ""]
        slot_matched = [None, None]
        for tok in tokens:
            if not (0.49 <= tok.cy <= 0.62 and 0.22 <= tok.cx <= 0.72):
                continue
            idx = 0 if tok.cx < 0.45 else 1
            entry = selector.match_ball(tok.text)
            if entry is not None or not slot_raw[idx]:
                slot_raw[idx] = tok.text.strip()
                slot_matched[idx] = entry

        slots = [
            BallChoice(
                slot_index=i,
                raw_text=slot_raw[i],
                matched_ball=slot_matched[i],
                score=slot_matched[i].score if slot_matched[i] is not None else 0,
            )
            for i in range(2)
        ]
        non_empty = [s for s in slots if s.raw_text]
        if len(non_empty) >= 2:
            best = max(non_empty, key=lambda c: c.score)
            return BallScreenDetection(
                detected=True,
                phase="PICK",
                header_text=header_text,
                slots=slots,
                best_choice=best,
            )

    return BallScreenDetection(
        detected=False,
        phase="NONE",
        header_text=header_text,
        slots=[],
        best_choice=None,
    )
