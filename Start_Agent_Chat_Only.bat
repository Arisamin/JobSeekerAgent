@echo off
setlocal

REM ---------------------------------------------------------------------------
REM Start_Agent_Chat_Only.bat
REM
REM Purpose:
REM   - Start Telegram interactive agent session with NO upfront search/scan.
REM   - Uses existing DB contents only.
REM
REM Default behavior:
REM   - Runs agent_engine.py with --telegram-chat-only
REM   - Uses --headless
REM   - Uses --max-jobs 5 as default for future in-chat Search wizard runs
REM
REM Copy-paste commands (PowerShell, from repo root):
REM   1) Default chat-only run:
REM      .\Start_Agent_Chat_Only.bat
REM
REM   2) Override default future search max-jobs:
REM      .\Start_Agent_Chat_Only.bat --max-jobs 8
REM
REM   3) Pass Telegram token/chat ID for this run only:
REM      .\Start_Agent_Chat_Only.bat --telegram-bot-token "<token>" --telegram-chat-id 123456789
REM
REM   4) Remote server mode with downloadable report links:
REM      .\Start_Agent_Chat_Only.bat --report-host 0.0.0.0 --report-port 8765 --report-public-base-url "https://YOUR_PUBLIC_HOST:8765"
REM
REM Note:
REM   Any arguments passed to this .bat are appended via %%* to python command.
REM ---------------------------------------------------------------------------

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Python virtual environment not found at .venv\Scripts\python.exe
    echo Create it first, then install dependencies.
    pause
    exit /b 1
)

for /f "delims=" %%A in ('powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('TELEGRAM_BOT_TOKEN','User')"') do set "TELEGRAM_BOT_TOKEN=%%A"
for /f "delims=" %%A in ('powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('TELEGRAM_CHAT_ID','User')"') do set "TELEGRAM_CHAT_ID=%%A"

if "%TELEGRAM_BOT_TOKEN%"=="" (
    echo [ERROR] TELEGRAM_BOT_TOKEN is empty in User environment variables.
    pause
    exit /b 1
)

if "%TELEGRAM_CHAT_ID%"=="" (
    echo [ERROR] TELEGRAM_CHAT_ID is empty in User environment variables.
    pause
    exit /b 1
)

echo Starting Job Seeker Agent in chat-only mode (no search)...
echo.

".venv\Scripts\python.exe" "agent_engine.py" --telegram-chat-only --max-jobs 5 --headless %*
set EXIT_CODE=%ERRORLEVEL%

echo.
echo Agent exited with code %EXIT_CODE%.
exit /b %EXIT_CODE%
