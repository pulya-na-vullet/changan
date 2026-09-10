@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Changan Hub
cd /d "%~dp0"

if not exist logs mkdir logs
echo %DATE% %TIME% run.bat start>> logs\start.log

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
  echo Python 3.10+ not found. Install from python.org and tick "Add python.exe to PATH".
  echo Do not use the Microsoft Store stub.
  echo %DATE% %TIME% no python>> logs\start.log
  pause
  exit /b 1
)

set "VPY=%CD%\.venv\Scripts\python.exe"
set "VPW=%CD%\.venv\Scripts\pythonw.exe"

if exist "%VPY%" (
  "%VPY%" -c "import cryptography" >nul 2>&1
  if not errorlevel 1 (
    echo .venv already ready, skipping pip.
    echo %DATE% %TIME% venv ok skip ensure_env>> logs\start.log
    goto :launch
  )
)

echo Checking .venv (only if cryptography is missing^)...
%PY% ensure_env.py
if errorlevel 1 (
  echo.
  echo Failed. Log: logs\start.log
  echo Delete the folder .venv on the flash drive and run run.bat again.
  pause
  exit /b 1
)

:launch
if not exist "%VPY%" (
  echo Missing %VPY%
  pause
  exit /b 1
)

echo Starting Hub...
echo %DATE% %TIME% launching app.py>> logs\start.log
if exist "%VPW%" (
  start "Changan Hub" /D "%CD%" "%VPW%" app.py
) else (
  "%VPY%" app.py
  if errorlevel 1 (
    echo Hub exited with an error. See logs\hub.log and logs\start.log
    pause
  )
)
exit /b 0
