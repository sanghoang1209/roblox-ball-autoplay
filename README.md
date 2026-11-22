# Roblox Background Auto-Play (macOS)

Tool tự động nhận diện nút **Play** và bấm chơi lại **chạy ngầm 100%** trên macOS (không cần focus cửa sổ Roblox, không nhảy màn hình, không dùng giả lập).

## Yêu cầu quyền trên macOS

Mở **System Settings → Privacy & Security** và cấp 2 quyền sau cho **Terminal** (sau khi bật cần tắt và mở lại Terminal):
1. **Accessibility (Trợ năng)** — để gửi phím ngầm vào `RobloxPlayer`.
2. **Screen & System Audio Recording (Ghi màn hình)** — để chụp riêng cửa sổ Roblox khi bị tab khác che.

> **Lưu ý:** Có thể để các app khác (Chrome, VS Code...) đè lên cửa sổ Roblox thoải mái, nhưng **không bấm nút vàng thu nhỏ (Minimize)** cửa sổ Roblox và giữ nó trên cùng Desktop Space.

## Cách test trước khi treo máy

1. **Test chuỗi phím ngầm (`\` → `Down` ×3 → `Right` → `Enter` → chờ 0.8s → `Down` → `Enter` → chờ 0.3s → `\`):**
   ```bash
   python3 autoplay.py --test-keys
   ```
   *(Trong 4 giây đếm ngược, bấm sang cửa sổ khác và quan sát xem Roblox có tự bấm Play, xác nhận cửa sổ thứ 2, rồi tắt khung UI Navigation không. Nếu cửa sổ thứ 2 hiện hơi chậm, tăng `--popup-delay 1.2`.)*

2. **Test nhận diện nút Play khi cửa sổ bị che:**
   ```bash
   python3 autoplay.py --check-once
   ```

## Chạy tự động

```bash
python3 autoplay.py
```

### Tùy chọn hữu ích
- `--popup-delay 0.8`: Số giây chờ cửa sổ thứ 2 hiện lên sau khi bấm Play (mặc định `0.8`).
- `--interval 3`: Chu kỳ quét (giây), mặc định `3.0`.
- `--cooldown 12`: Thời gian nghỉ sau khi bấm Play (giây), mặc định `12.0`.
- `--step-delay 0.22`: Độ trễ giữa mỗi phím mũi tên (giây), mặc định `0.22`.
- `--afk-interval 480`: Tự bấm nhẹ `Space` chống kick AFK 20 phút (mặc định `480` giây = 8 phút). Dùng `--no-anti-afk` để tắt.
- `--dry-run`: Chạy quét thử nhưng không bấm phím.
