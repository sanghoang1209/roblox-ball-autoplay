#!/bin/zsh
cd "$(dirname "$0")/.." || exit 1

if [ -f data/ui.pid ] && kill -0 "$(cat data/ui.pid)" 2>/dev/null; then
  echo "ℹ️  Web UI đã đang chạy ngầm — mở lại giao diện..."
  open "http://127.0.0.1:8765"
else
  make ui-bg
fi

sleep 1.2
osascript -e 'tell application "Terminal" to close (first window whose busy is false)' >/dev/null 2>&1 || true
