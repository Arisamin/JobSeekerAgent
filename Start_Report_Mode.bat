@echo off
setlocal
cd /d "%~dp0"

set "AGENT_DISABLE_JITTER=1"

echo Starting Job Seeker Report Mode...
echo This will scan once, then open the latest report update page automatically.
echo.

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "agent_engine.py" --report-mode --headless --max-jobs 5
) else (
  python "agent_engine.py" --report-mode --headless --max-jobs 5
)

echo.
echo Report Mode stopped. You can close this window.
pause
