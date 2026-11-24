@echo off
setlocal
title Roblox Ball Autoplay (Windows)

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY_CMD=py -3"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PY_CMD=python"
    ) else (
        echo [LOI] Khong tim thay Python 3. Hay cai Python 3.10+ tu https://www.python.org/downloads/
        echo       (Nho tich chon "Add Python to PATH" khi cai dat.)
        pause
        exit /b 1
    )
)

echo [1/2] Dang kiem tra & cai dat thu vien tu requirements.txt...
%PY_CMD% -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo [LOI] Khong cai duoc thu vien trong requirements.txt.
    pause
    exit /b 1
)

echo [2/2] Dang mo giao dien Roblox Ball Autoplay...
%PY_CMD% app.py
pause
