#!/bin/zsh
cd "$(dirname "$0")/.." || exit 1
make ui-stop
sleep 1.2
osascript -e 'tell application "Terminal" to close (first window whose busy is false)' >/dev/null 2>&1 || true
