# Roblox Background Auto-Play (macOS)

Tool tự động nhận diện nút **Play** và bấm chơi lại **chạy ngầm 100%** trên macOS (không cần focus cửa sổ Roblox, không nhảy màn hình, không dùng giả lập), hỗ trợ **nhiều chế độ treo khác nhau** thông qua các file cấu hình trong thư mục `profiles/`.

Xem chi tiết kiến trúc và lộ trình phát triển tại [ARCHITECTURE.md](ARCHITECTURE.md).

## Yêu cầu quyền trên macOS

Mở **System Settings → Privacy & Security** và cấp 2 quyền sau cho **Terminal** (sau khi bật cần tắt và mở lại Terminal):
1. **Accessibility (Trợ năng)** — để gửi phím ngầm vào `RobloxPlayer`.
2. **Screen & System Audio Recording (Ghi màn hình)** — để chụp riêng cửa sổ Roblox khi bị tab khác che.

> **Lưu ý:** Có thể để các app khác (Chrome, VS Code...) đè lên cửa sổ Roblox thoải mái, nhưng **không bấm nút vàng thu nhỏ (Minimize)** cửa sổ Roblox và giữ nó trên cùng Desktop Space.

## Cách sử dụng

### 1. Xem danh sách chế độ treo hiện có
```bash
python3 autoplay.py --list-profiles
```

### 2. Chạy tự động theo chế độ (Profile)
```bash
# Chạy chế độ mặc định (profiles/default_play.json)
python3 autoplay.py

# Chạy một chế độ khác trong profiles/
python3 autoplay.py --profile <ten_profile>
```

### 3. Test nhanh trước khi treo máy
```bash
# Test chuỗi phím ngầm của profile
python3 autoplay.py --profile default_play --test-keys

# Test nhận diện nút Play khi cửa sổ bị che
python3 autoplay.py --profile default_play --check-once
```

## Cách thêm chế độ treo mới

1. Copy file `profiles/default_play.json` thành một file mới trong `profiles/` (ví dụ: `profiles/ranked.json`).
2. Đổi `id`, `name` và chỉnh mảng `sequence` theo đúng chuỗi phím UI Navigation của chế độ đó (hỗ trợ `wait:<giây>`, ví dụ `"wait:0.8"`).
3. Chạy ngay bằng:
   ```bash
   python3 autoplay.py --profile ranked
   ```

## Chạy Unit Test

```bash
python3 -m unittest discover -s tests -v
```
