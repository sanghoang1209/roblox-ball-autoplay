PYTHON ?= python3
PROFILE ?= default_play
KEYS ?= backslash,left,up,left,left,right,enter,down,backslash

.PHONY: help ui ui-bg ui-stop ui-plain run ranked timer profiles check test-keys explore-watch explore-nav test clean

help: ## Hiển thị danh sách lệnh nhanh
	@echo "🎮 Roblox Ball Autoplay — Lệnh nhanh (Makefile)"
	@echo ""
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  make %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "💡 Mẹo: Có thể đổi profile bằng biến PROFILE, ví dụ: make run PROFILE=timer_fullscreen"

ui: ## Mở giao diện Web UI (tự chống Sleep & khóa màn hình)
	caffeinate -di $(PYTHON) app.py

ui-bg: ## Chạy Web UI ngầm độc lập (tắt Terminal / VS Code vẫn chạy)
	@mkdir -p data/logs
	@if [ -f data/ui.pid ] && kill -0 $$(cat data/ui.pid) 2>/dev/null; then \
		echo "ℹ️  Web UI đã chạy ngầm sẵn (PID: $$(cat data/ui.pid)) -> http://127.0.0.1:8765"; \
	else \
		nohup caffeinate -di $(PYTHON) app.py > data/logs/ui_server.log 2>&1 < /dev/null & \
		echo $$! > data/ui.pid; \
		sleep 0.6; \
		echo "✅ Đã chạy Web UI ngầm (PID: $$(cat data/ui.pid)) -> http://127.0.0.1:8765"; \
		echo "   (Tắt Terminal/VS Code vẫn chạy bình thường. Gõ 'make ui-stop' khi muốn tắt hẳn.)"; \
	fi

ui-stop: ## Tắt hẳn Web UI đang chạy ngầm
	@if [ -f data/ui.pid ]; then \
		PID=$$(cat data/ui.pid); \
		pkill -P $$PID 2>/dev/null || true; \
		kill $$PID 2>/dev/null || true; \
		rm -f data/ui.pid; \
		echo "🛑 Đã tắt Web UI chạy ngầm (PID: $$PID)."; \
	else \
		pkill -f "$(PYTHON) app.py" 2>/dev/null && echo "🛑 Đã tắt tiến trình Web UI." || echo "ℹ️  Không có Web UI nào đang chạy ngầm."; \
	fi

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

explore-watch: ## Ghi lại toàn bộ màn hình 1 round (Check -> Ban -> Pick) + OCR
	$(PYTHON) scripts/ui_explorer.py watch --duration 35 --interval 1.0

explore-nav: ## Dò từng bước UI Navigation và chụp ảnh sau mỗi phím
	$(PYTHON) scripts/ui_explorer.py nav --keys "$(KEYS)" --delay 0.45 --countdown 2

test: ## Chạy toàn bộ unit tests
	$(PYTHON) -m unittest discover -s tests -v

clean: ## Dọn file tạm (__pycache__, debug_*.png)
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	rm -f debug_*.png
