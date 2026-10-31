@echo off
cd /d "%~dp0"
title Building Secret Hatch Notifer+.exe
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10-3.12 from python.org first and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
echo Installing build tools and requirements (may take a few minutes)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
echo.
echo Building "Secret Hatch Notifer+.exe" (5-10 minutes, the file will be large)...
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "Secret Hatch Notifer+" ^
  --icon icon.ico --add-data "icon.ico;." --add-data "alert.wav;." ^
  --collect-all customtkinter --collect-all rapidocr_onnxruntime --collect-all onnxruntime ^
  --hidden-import win32ui --hidden-import cv2 --hidden-import win32timezone ^
  hatch_watcher.py
echo.
if exist "dist\Secret Hatch Notifer+.exe" (
  echo Done! Your app is: %~dp0dist\Secret Hatch Notifer+.exe
  echo Send people just that one file. They do NOT need Python.
  echo If the old icon still shows, restart Explorer or copy the exe to a new folder - Windows caches icons.
  explorer dist
) else (
  echo Build failed. Scroll up to see the error.
)
pause
