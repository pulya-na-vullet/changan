@echo off
setlocal EnableExtensions
title Changan Hub
cd /d "%~dp0"

echo Changan Hub
echo.

set "PY="
where py >nul 2>&1 && (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  where python >nul 2>&1 && (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY=python"
  )
)
if not defined PY (
  echo Python 3.10+ не найден. Установите с python.org и отметьте "Add python.exe to PATH".
  echo Не используйте заглушку Microsoft Store.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Первый запуск: создаю окружение на флешке. Не закрывайте окно.
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Не удалось создать .venv
    pause
    exit /b 1
  )
)

set "VPY=.venv\Scripts\python.exe"
if not exist "%VPY%" (
  echo Нет %VPY%
  pause
  exit /b 1
)

"%VPY%" -c "import cryptography" >nul 2>&1
if errorlevel 1 (
  echo Ставлю зависимости ^(один раз, не каждый запуск^)...
  "%VPY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo pip не смог поставить cryptography. Проверьте интернет.
    pause
    exit /b 1
  )
)

echo Открываю Hub...
if exist "%CD%\.venv\Scripts\pythonw.exe" (
  start "Changan Hub" /D "%CD%" "%CD%\.venv\Scripts\pythonw.exe" app.py
) else (
  "%VPY%" app.py
  if errorlevel 1 pause
)
exit /b 0
