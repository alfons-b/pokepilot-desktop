@echo off
REM Creates the virtual environment on first run, then starts PokePilot Desktop.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3 -m venv .venv || python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :error
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)
".venv\Scripts\python.exe" -m app
exit /b %errorlevel%
:error
echo Setup failed. See docs\INSTALLATION.md
pause
exit /b 1
