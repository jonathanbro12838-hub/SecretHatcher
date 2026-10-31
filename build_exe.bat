@echo off
cd /d "%~dp0"
title Building Secret Hatch Notifer+.exe
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10-3.12 from python.org first and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
if not exist webhooks.txt (
  echo.
  echo NOTE: webhooks.txt was not found, so this exe will NOT be able to send alerts.
  echo Create webhooks.txt next to this file with two lines:
  echo     main=YOUR_MAIN_WEBHOOK_LINK
  echo     test=YOUR_TEST_WEBHOOK_LINK
  echo.
)
echo Installing build tools and requirements (may take a few minutes)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
python make_secrets.py
echo.
echo Building "Secret Hatch Notifer+.exe" (5-10 minutes, the file will be large)...
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "Secret Hatch Notifer+" ^
  --icon icon.ico --add-data "icon.ico;." --add-data "icon.png;." --add-data "alert.wav;." ^
  --collect-all customtkinter --collect-all rapidocr_onnxruntime --collect-all onnxruntime ^
  --hidden-import win32ui --hidden-import cv2 --hidden-import win32timezone --hidden-import hw_secrets ^
  hatch_watcher.py
echo.
if exist "dist\Secret Hatch Notifer+.exe" (
  echo Done! Your app is: %~dp0dist\Secret Hatch Notifer+.exe
  echo If the old icon still shows, copy the exe to a new folder - Windows caches icons.
  explorer dist
) else (
  echo Build failed. Scroll up to see the error.
)
pause
