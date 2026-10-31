@echo off
cd /d "%~dp0"
title Secret Hatch Notifer+
echo Installing what the app needs (first run only, may take a few minutes)...
python -m pip install -r requirements.txt
python make_secrets.py
echo.
echo Starting Secret Hatch Notifer+...
python hatch_watcher.py
pause
