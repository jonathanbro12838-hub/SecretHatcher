@echo off
cd /d "%~dp0"
title Set update URL
echo This sets the link the app checks for new versions.
echo.
set /p GH_USER=Your GitHub username: 
set /p GH_REPO=Your GitHub repo name: 
python set_update_url.py "%GH_USER%" "%GH_REPO%"
echo.
pause
