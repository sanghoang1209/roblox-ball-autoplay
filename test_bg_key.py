import ctypes
import subprocess
import sys
import time

# Load macOS native frameworks (zero external dependencies)
cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
app_services = ctypes.CDLL(
    "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
)

# Function signatures
cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p

cg.CGEventPostToPid.argtypes = [ctypes.c_int32, ctypes.c_void_p]
cg.CGEventPostToPid.restype = None

cf.CFRelease.argtypes = [ctypes.c_void_p]
cf.CFRelease.restype = None

app_services.AXIsProcessTrusted.argtypes = []
app_services.AXIsProcessTrusted.restype = ctypes.c_bool

# macOS virtual keycodes
KEY_SPACE = 49      # Space (nhảy trong game)
KEY_BACKSLASH = 42  # \ (bật/tắt UI Navigation trong Roblox)


def find_roblox_pid() -> int | None:
    for pattern in (["pgrep", "-x", "RobloxPlayer"], ["pgrep", "-f", "RobloxPlayer"]):
        res = subprocess.run(pattern, capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            return int(res.stdout.strip().splitlines()[0])
    return None


def send_bg_key(pid: int, keycode: int, hold_sec: float = 0.08) -> None:
    down = cg.CGEventCreateKeyboardEvent(None, keycode, True)
    up = cg.CGEventCreateKeyboardEvent(None, keycode, False)
    if not down or not up:
        raise RuntimeError("Không tạo được CGEvent (hãy kiểm tra quyền Accessibility).")
    try:
        cg.CGEventPostToPid(pid, down)
        time.sleep(hold_sec)
        cg.CGEventPostToPid(pid, up)
    finally:
        cf.CFRelease(down)
        cf.CFRelease(up)


def main() -> None:
    if not app_services.AXIsProcessTrusted():
        print("⚠️  Terminal chưa có quyền Accessibility (Trợ năng)!")
        print("   Hãy vào: System Settings -> Privacy & Security -> Accessibility")
        print("   Bật quyền cho Terminal (hoặc app bạn đang chạy lệnh này), rồi chạy lại.")
        sys.exit(1)

    pid = find_roblox_pid()
    if pid is None:
        print("❌ Không tìm thấy RobloxPlayer đang chạy.")
        print("   Hãy mở game Roblox trước rồi chạy lại script này.")
        sys.exit(1)

    print(f"✅ Tìm thấy RobloxPlayer (PID: {pid})")
    print("👉 Bây giờ hãy bấm sang cửa sổ KHÁC (vd: Chrome/Finder) để Roblox mất focus,")
    print("   nhưng vẫn để lộ cửa sổ Roblox bên cạnh để bạn nhìn xem nó có phản ứng không.")

    for i in range(5, 0, -1):
        print(f"   Bắt đầu test sau {i} giây...", flush=True)
        time.sleep(1)

    print("\n[Test 1/2] Gửi phím SPACE (nhảy) 3 lần vào Roblox đang chạy ngầm...")
    for n in range(1, 4):
        send_bg_key(pid, KEY_SPACE)
        print(f"   Đã gửi Space lần {n}")
        time.sleep(1.2)

    print("\n[Test 2/2] Gửi phím '\\' (bật UI Navigation) vào Roblox đang chạy ngầm...")
    send_bg_key(pid, KEY_BACKSLASH)
    print("   Đã gửi phím '\\'")

    print("\n🎉 Xong! Hãy kiểm tra xem lúc bạn đang ở cửa sổ khác:")
    print("   1. Nhân vật trong Roblox có tự NHẢY không?")
    print("   2. Hoặc khung xanh/trắng UI Navigation có hiện lên trên nút trong Roblox không?")


if __name__ == "__main__":
    main()
