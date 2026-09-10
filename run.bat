@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Keep this file ASCII-only. Do not add "chcp 65001": UTF-8 code page
REM makes cmd.exe skip the first character of later lines
REM ("cd /d" becomes "/d", "echo" becomes "ho").

set "HUB_LOG=%~dp0logs\start.log"
if not exist "%~dp0logs" mkdir "%~dp0logs" >nul 2>&1
echo [%date% %time%] run.bat start>> "%HUB_LOG%"

if exist "%~dp0hub.lock" goto :launch
if exist "%~dp0logs\hub.lock" goto :launch

if exist "%~dp0.venv\Scripts\python.exe" goto :launch

where python >nul 2>&1
if errorlevel 1 (
  echo Python not found. Install Python 3 from python.org and tick "Add python.exe to PATH".
  echo Then double-click run.bat again, or run: python app.py
  pause
  exit /b 1
)

echo Creating .venv ...
python -m venv .venv
if errorlevel 1 (
  echo venv create failed. Launching with system Python.
  goto :launch
)

echo [%date% %time%] pip install>> "%HUB_LOG%"
".venv\Scripts\python.exe" -m pip install --upgrade pip --trusted-host pypi.org --trusted-host files.pythonhosted.org >> "%HUB_LOG%" 2>&1
".venv\Scripts\python.exe" -m pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org >> "%HUB_LOG%" 2>&1

:launch
if exist "%~dp0.venv\Scripts\pythonw.exe" (
  start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py"
  goto :ok
)
if exist "%~dp0.venv\Scripts\python.exe" (
  start "" "%~dp0.venv\Scripts\python.exe" "%~dp0app.py"
  goto :ok
)
where pythonw >nul 2>&1
if not errorlevel 1 (
  start "" pythonw "%~dp0app.py"
  goto :ok
)
where python >nul 2>&1
if not errorlevel 1 (
  start "" python "%~dp0app.py"
  goto :ok
)

echo Python not found. Install Python 3 and tick "Add python.exe to PATH".
pause
exit /b 1

:ok
echo [%date% %time%] launched>> "%HUB_LOG%"
exit /b 0
