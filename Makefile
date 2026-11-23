PYTHON ?= python3
PROFILE ?= default_play

.PHONY: help ui ui-plain run ranked timer profiles check test-keys test clean

help: ## Hiển thị danh sách lệnh nhanh
	@echo "🎮 Roblox Ball Autoplay — Lệnh nhanh (Makefile)"
	@echo ""
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  make %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "💡 Mẹo: Có thể đổi profile bằng biến PROFILE, ví dụ: make run PROFILE=timer_fullscreen"

ui: ## Mở giao diện Web UI (tự chống Sleep & khóa màn hình)
	caffeinate -di $(PYTHON) app.py

ui-plain: ## Mở giao diện Web UI (không kèm caffeinate)
	$(PYTHON) app.py

run: ## Chạy treo máy theo PROFILE (mặc định: default_play, chống Sleep/Lock)
	caffeinate -di $(PYTHON) autoplay.py --profile $(PROFILE)

ranked: ## Chạy nhanh chế độ Ranked (Play Again, cooldown 3 phút)
	caffeinate -di $(PYTHON) autoplay.py --profile ranked

timer: ## Chạy nhanh chế độ Timer xuyên Fullscreen (chống Sleep)
	caffeinate -i $(PYTHON) autoplay.py --profile timer_fullscreen

profiles: ## Liệt kê toàn bộ chế độ treo trong profiles/
	$(PYTHON) autoplay.py --list-profiles

check: ## Kiểm tra nhanh nhận diện nút Play (1 lần)
	$(PYTHON) autoplay.py --profile $(PROFILE) --check-once

test-keys: ## Test gửi chuỗi phím ngầm (đếm ngược 4 giây)
	$(PYTHON) autoplay.py --profile $(PROFILE) --test-keys

test: ## Chạy toàn bộ unit tests
	$(PYTHON) -m unittest discover -s tests -v

clean: ## Dọn file tạm (__pycache__, debug_*.png)
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	rm -f debug_*.png
