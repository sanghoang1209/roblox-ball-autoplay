"""Localhost Web UI server & controller for Roblox Background Auto-Play."""

from __future__ import annotations

import argparse
import json
import mimetypes
import socket
import threading
import time
import webbrowser
from collections import deque
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from roblox_autoplay.core.engine import AutoPlayEngine
from roblox_autoplay.core.macos_input import run_key_sequence, validate_sequence_tokens
from roblox_autoplay.core.macos_window import find_roblox_pid, find_roblox_window_id
from roblox_autoplay.core.permissions import check_permissions
from roblox_autoplay.core.profile_loader import (
    DEFAULT_PROFILES_DIR,
    list_profiles,
    profile_to_dict,
    resolve_profile,
    save_profile_file,
)

UI_DIR = Path(__file__).resolve().parent
STATIC_DIR = UI_DIR / "static"
ASSETS_DIR = UI_DIR / "assets"


class AppController:
    """Quản lý vòng đời AutoPlayEngine trên background thread cho giao diện Web UI."""

    def __init__(self, profiles_dir: Path = DEFAULT_PROFILES_DIR) -> None:
        self.profiles_dir = profiles_dir
        self._lock = threading.Lock()
        self._engine: AutoPlayEngine | None = None
        self._thread: threading.Thread | None = None
        self._active_profile_id: str | None = None
        self._state = "STOPPED"
        self._play_count = 0
        self._logs: deque[str] = deque(maxlen=150)

    def append_log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        with self._lock:
            self._logs.append(line)

    def clear_logs(self) -> None:
        with self._lock:
            self._logs.clear()

    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
            return {
                "running": running,
                "state": self._state if running else "STOPPED",
                "active_profile_id": self._active_profile_id,
                "play_count": self._play_count,
                "roblox_running": find_roblox_pid() is not None,
                "logs": list(self._logs),
            }

    def start(self, profile_id: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.is_running():
            return {"ok": False, "error": "Tool đang chạy rồi. Hãy dừng trước khi chuyển chế độ."}

        profile = resolve_profile(profile_id, self.profiles_dir)
        if overrides:
            self._apply_overrides(profile, overrides)

        need_screen = profile.detector.type != "timer"
        ok, warnings = check_permissions(need_screen=need_screen)
        if not ok:
            msg = "\n".join(warnings)
            self.append_log(msg)
            return {"ok": False, "error": msg}

        def on_state(new_state: str) -> None:
            with self._lock:
                self._state = new_state

        def on_count(count: int) -> None:
            with self._lock:
                self._play_count = count

        engine = AutoPlayEngine(
            profile=profile,
            on_log=self.append_log,
            on_play_count=on_count,
            on_state_change=on_state,
        )

        with self._lock:
            self._engine = engine
            self._active_profile_id = profile.id
            self._play_count = 0
            self._state = "STARTING"
            self._thread = threading.Thread(target=engine.run, daemon=True)
            self._thread.start()

        return {"ok": True, "profile_id": profile.id}

    def stop(self) -> dict[str, Any]:
        with self._lock:
            engine = self._engine
        if engine is not None:
            engine.stop()
            return {"ok": True}
        return {"ok": True, "message": "Tool đang không chạy."}

    def test_keys(self, profile_id: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        profile = resolve_profile(profile_id, self.profiles_dir)
        if overrides:
            self._apply_overrides(profile, overrides)

        ok, warnings = check_permissions(need_screen=False)
        if not ok:
            msg = "\n".join(warnings)
            self.append_log(msg)
            return {"ok": False, "error": msg}

        pid = find_roblox_pid()
        if pid is None:
            msg = "❌ Không tìm thấy RobloxPlayer đang chạy. Hãy mở game Roblox trước."
            self.append_log(msg)
            return {"ok": False, "error": msg}

        def _worker() -> None:
            self.append_log(f"🧪 Test phím ({profile.id}): đếm ngược 4 giây, hãy giữ Roblox ở nền...")
            for i in range(4, 0, -1):
                self.append_log(f"   Gửi phím sau {i}s...")
                time.sleep(1)
            run_key_sequence(
                pid,
                profile.sequence,
                step_delay=profile.timing.step_delay_sec,
                on_log=self.append_log,
            )
            self.append_log("🎉 Đã gửi xong chuỗi phím test!")

        threading.Thread(target=_worker, daemon=True).start()
        return {"ok": True}

    def check_once(self, profile_id: str) -> dict[str, Any]:
        profile = resolve_profile(profile_id, self.profiles_dir)
        if profile.detector.type == "timer":
            msg = "ℹ️  Chế độ Timer không chụp màn hình — hoạt động xuyên Fullscreen."
            self.append_log(msg)
            return {"ok": True, "found": None, "message": msg}

        ok, warnings = check_permissions(need_screen=True)
        if not ok:
            msg = "\n".join(warnings)
            self.append_log(msg)
            return {"ok": False, "error": msg}

        pid = find_roblox_pid()
        if pid is None:
            msg = "❌ Không tìm thấy RobloxPlayer đang chạy."
            self.append_log(msg)
            return {"ok": False, "error": msg}

        win_info = find_roblox_window_id(pid)
        if win_info is None:
            msg = "❌ Không tìm thấy cửa sổ chính của RobloxPlayer."
            self.append_log(msg)
            return {"ok": False, "error": msg}

        wid, (ww, wh) = win_info
        engine = AutoPlayEngine(profile=profile, on_log=self.append_log)
        try:
            res = engine.detect_once(wid)
        except RuntimeError as exc:
            msg = f"⚠️  {exc}"
            self.append_log(msg)
            return {"ok": False, "error": msg}

        status = "✅ THẤY NÚT PLAY" if res.found else "❌ KHÔNG THẤY"
        summary = (
            f"{status} (Window {ww}x{wh}) | {res.reason} | "
            f"green={res.green_ratio:.1%}, white={res.white_ratio:.1%}"
        )
        self.append_log(summary)
        return {"ok": True, "found": res.found, "message": summary}

    def save_profile_updates(self, profile_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        profile = resolve_profile(profile_id, self.profiles_dir)
        self._apply_overrides(profile, updates)
        saved_path = save_profile_file(profile, self.profiles_dir)
        self.append_log(f"💾 Đã lưu cấu hình vào {saved_path.name}")
        return {"ok": True, "profile": profile_to_dict(profile)}

    @staticmethod
    def _apply_overrides(profile: Any, data: dict[str, Any]) -> None:
        if "cooldown_sec" in data:
            profile.timing.cooldown_sec = max(0.0, float(data["cooldown_sec"]))
        if "scan_interval_sec" in data:
            profile.timing.scan_interval_sec = max(0.5, float(data["scan_interval_sec"]))
        if "step_delay_sec" in data:
            profile.timing.step_delay_sec = max(0.05, float(data["step_delay_sec"]))
        if "anti_afk_enabled" in data:
            profile.anti_afk.enabled = bool(data["anti_afk_enabled"])
        if "anti_afk_interval_sec" in data:
            profile.anti_afk.interval_sec = max(10.0, float(data["anti_afk_interval_sec"]))
        if "sequence" in data:
            raw_seq = data["sequence"]
            if isinstance(raw_seq, str):
                tokens = [t.strip().lower() for t in raw_seq.replace("->", ",").split(",") if t.strip()]
            elif isinstance(raw_seq, list):
                tokens = [str(t).strip().lower() for t in raw_seq if str(t).strip()]
            else:
                raise ValueError("Trường 'sequence' không hợp lệ.")
            validate_sequence_tokens(tokens)
            profile.sequence = tokens


def _make_handler(controller: AppController) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return  # Giữ terminal sạch sẽ

        def _send_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path) -> None:
            if not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type, _ = mimetypes.guess_type(str(path))
            data = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/" or path == "/index.html":
                self._send_file(STATIC_DIR / "index.html")
                return
            if path.startswith("/assets/"):
                rel = Path(path.removeprefix("/assets/")).name
                self._send_file(ASSETS_DIR / rel)
                return
            if path == "/api/profiles":
                profiles = [profile_to_dict(p) for p in list_profiles(controller.profiles_dir)]
                self._send_json({"profiles": profiles})
                return
            if path == "/api/status":
                self._send_json(controller.get_status())
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            try:
                body = self._read_json_body()
                if path == "/api/start":
                    res = controller.start(body["profile_id"], body.get("overrides"))
                    self._send_json(res, HTTPStatus.OK if res.get("ok") else HTTPStatus.BAD_REQUEST)
                    return
                if path == "/api/stop":
                    self._send_json(controller.stop())
                    return
                if path == "/api/test-keys":
                    res = controller.test_keys(body["profile_id"], body.get("overrides"))
                    self._send_json(res, HTTPStatus.OK if res.get("ok") else HTTPStatus.BAD_REQUEST)
                    return
                if path == "/api/check-once":
                    res = controller.check_once(body["profile_id"])
                    self._send_json(res, HTTPStatus.OK if res.get("ok") else HTTPStatus.BAD_REQUEST)
                    return
                if path == "/api/save-profile":
                    res = controller.save_profile_updates(body["profile_id"], body.get("updates", {}))
                    self._send_json(res)
                    return
                if path == "/api/clear-logs":
                    controller.clear_logs()
                    self._send_json({"ok": True})
                    return
                self.send_error(HTTPStatus.NOT_FOUND)
            except (KeyError, ValueError, FileNotFoundError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    return Handler


def _pick_port(preferred: int = 8765) -> int:
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return int(s.getsockname()[1])
            except OSError:
                continue
    return preferred


def run_ui(port: int = 8765, open_browser: bool = True) -> None:
    chosen_port = _pick_port(port)
    controller = AppController()
    server = ThreadingHTTPServer(("127.0.0.1", chosen_port), _make_handler(controller))
    url = f"http://127.0.0.1:{chosen_port}"
    print(f"🎮 Roblox Ball Autoplay UI đang chạy tại: {url}")
    print("   Nhấn Ctrl+C trong Terminal để tắt hẳn ứng dụng.", flush=True)

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Đang dừng engine và tắt UI...")
        controller.stop()
        server.shutdown()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Giao diện điều khiển Roblox Ball Autoplay")
    parser.add_argument("--port", type=int, default=8765, help="Cổng localhost (mặc định: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Không tự mở trình duyệt")
    args = parser.parse_args(argv)
    run_ui(port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
