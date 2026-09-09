@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
  echo Python не найден. Установите Python 3.11+ и отметьте "Add python.exe to PATH".
  pause
  exit /b 1
)
python -m pip install -r requirements.txt
python run.py
if errorlevel 1 pause
