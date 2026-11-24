# Quy Tắc Quản Lý Git & Commit

Tài liệu này quy định cách chia và đặt tên commit cho dự án `roblox-ball-autoplay` để dễ theo dõi lịch sử thay đổi, tìm lỗi và quay lại phiên bản cũ khi cần.

---

## 1. Cấu trúc Commit Message

Dùng chuẩn **Conventional Commits**:

```text
<type>(<scope>): <mô tả ngắn bằng tiếng Anh hoặc tiếng Việt không dấu>
```

*(Có thể bỏ `(<scope>)` nếu thay đổi mang tính toàn dự án như `docs:` hoặc `chore:`.)*

### Các `type` sử dụng
| Type | Ý nghĩa |
| :--- | :--- |
| `feat` | Thêm tính năng mới hoặc thêm chế độ treo (profile) mới |
| `fix` | Sửa lỗi (nhận diện sai nút, bấm hụt phím, lệch trạng thái UI Nav...) |
| `refactor` | Tái cấu trúc code nhưng không đổi hành vi bên ngoài |
| `perf` | Tối ưu hiệu năng / tài nguyên (CPU, RAM, tốc độ OCR, giảm chụp màn hình...) |
| `test` | Thêm hoặc cập nhật unit test |
| `docs` | Cập nhật tài liệu (`README.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md`, `docs/assets/`) |
| `chore` | Cấu hình công cụ, `pyproject.toml`, `requirements.txt`, `Makefile`, `.gitignore`, dọn file |

### Các `scope` theo từng module của dự án
| Scope | Thư mục / file tương ứng | Ví dụ commit |
| :--- | :--- | :--- |
| `profiles` | `profiles/` | `feat(profiles): add ranked mode profile` |
| `vision` | `src/roblox_autoplay/vision/` | `fix(vision): adjust play button green threshold` |
| `core` | `src/roblox_autoplay/core/` | `feat(core): add Windows Win32 backend and dispatcher` |
| `cli` | `src/roblox_autoplay/cli.py`, `autoplay.py` | `feat(cli): add --test-ball-ocr option` |
| `ui` | `src/roblox_autoplay/ui/`, `app.py` | `feat(ui): add translucent avatar background and split layout` |
| `ml` | `src/roblox_autoplay/ml/`, `config/ball_rankings.json` | `feat(ml): add Windows WinRT OCR backend for Ban/Pick` |

---

## 2. Nguyên tắc chia Commit

1. **1 commit = 1 mục đích duy nhất:**
   - Không gộp việc **chỉnh chuỗi phím / cooldown trong `profiles/`** chung với việc **sửa logic code trong `src/`**.
   - Tách riêng commit **dọn dẹp / cấu hình (`chore`)** khỏi commit **tính năng (`feat` / `refactor`)**.
   - Tách riêng commit **test (`test`)** khi thêm bộ test mới.
2. **Không commit dữ liệu nặng hoặc file tạm:**
   - Các thư mục `data/`, `models/`, `__pycache__/`, ảnh `debug_*.png` đã được loại trừ trong `.gitignore`.
3. **Chạy test trước khi commit code trong `src/`, `config/` hoặc `profiles/`:**
   ```bash
   # macOS (nhanh)
   make test

   # Hoặc chạy trực tiếp trên cả macOS & Windows
   python3 -m unittest discover -s tests -v
   ```

---

## 3. Các lệnh Git hữu ích khi cần tra cứu lại

```bash
# Xem lịch sử ngắn gọn toàn dự án
git log --oneline -n 20

# Xem riêng lịch sử chỉnh sửa chuỗi phím / cooldown của 1 chế độ
git log --oneline -- profiles/ranked.json

# Lọc toàn bộ commit liên quan đến nhận diện hình ảnh (vision) hoặc Ban/Pick (ml)
git log --oneline --grep="(vision)"
git log --oneline --grep="(ml)"

# Xem chi tiết thay đổi của 1 commit cụ thể
git show <commit_hash>
```
