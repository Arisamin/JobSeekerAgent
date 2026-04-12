@echo off
setlocal

REM ---------------------------------------------------------------------------
REM Start_Agent_Search_Mode.bat
REM
REM Default behavior:
REM   - Starts agent_engine.py with Telegram notifications enabled
REM   - Uses --easy-apply-run-mode search
REM   - Uses --max-jobs 5
REM   - Uses --headless (no visible browser window)
REM
REM Copy-paste commands (PowerShell, from repo root):
REM   1) Default run:
REM      .\Start_Agent_Search_Mode.bat
REM
REM   2) Search mode + more jobs:
REM      .\Start_Agent_Search_Mode.bat --max-jobs 8

REM   2b) Force fresh run (reset DB before scan):
REM      .\Start_Agent_Search_Mode.bat --max-jobs 5 --headless --reset-db

REM   2c) Easy Apply only discovery mode:
REM      .\Start_Agent_Search_Mode.bat --easy-apply-only
REM
REM   3) Testing traversal mode:
REM      .\Start_Agent_Search_Mode.bat --easy-apply-run-mode testing
REM
REM   4) Override query:
REM      .\Start_Agent_Search_Mode.bat --query "Senior C# Developer Israel"
REM
REM   5) Pass Telegram token/chat ID on command line for this run only:
REM      .\Start_Agent_Search_Mode.bat --telegram-bot-token "<token>" --telegram-chat-id 123456789
REM
REM   6) Headless browser run (default in this launcher):
REM      .\Start_Agent_Search_Mode.bat
REM
REM Note:
REM   Any arguments passed to this .bat are appended via %%* to python command.
REM ---------------------------------------------------------------------------

cd /d "%~dp0"

set "EXISTING_AGENT_PIDS="
for /f "delims=" %%A in ('powershell -NoProfile -Command "$p=Get-CimInstance Win32_Process ^| Where-Object { $_.Name -match '^python(\.exe)?$' -and $_.CommandLine -match 'agent_engine\.py' } ^| Select-Object -ExpandProperty ProcessId; if($p){($p -join ',')}" ^| findstr /r "^[0-9][0-9,]*$"') do set "EXISTING_AGENT_PIDS=%%A"

if defined EXISTING_AGENT_PIDS (
    echo [ERROR] Existing agent_engine.py process detected: %EXISTING_AGENT_PIDS%
    echo Close old agent sessions first to avoid duplicate Telegram pollers and unexpected browser launches.
    echo.
    echo PowerShell command to stop old agent processes:
    echo   $procs = Get-CimInstance Win32_Process ^| Where-Object { $_.Name -match 'python' -and $_.CommandLine -match 'agent_engine.py' }; $procs ^| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    pause
    exit /b 1
)

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

echo Starting Job Seeker Agent in search mode...
echo.

set "BASELINE_AGENT_PIDS="
for /f "delims=" %%A in ('powershell -NoProfile -Command "$p=Get-CimInstance Win32_Process ^| Where-Object { $_.Name -match '^python(\.exe)?$' -and $_.CommandLine -match 'agent_engine\.py' } ^| Select-Object -ExpandProperty ProcessId; if($p){($p -join ',')}" ^| findstr /r "^[0-9][0-9,]*$"') do set "BASELINE_AGENT_PIDS=%%A"

".venv\Scripts\python.exe" "agent_engine.py" --telegram-notify --max-jobs 5 --easy-apply-run-mode search --headless %*
set EXIT_CODE=%ERRORLEVEL%

powershell -NoProfile -Command "$baseline=@(); if('%BASELINE_AGENT_PIDS%' -ne ''){$baseline='%BASELINE_AGENT_PIDS%'.Split(',') ^| ForEach-Object {[int]$_}}; $b=@{}; $baseline ^| ForEach-Object { $b[$_] = $true }; $current=Get-CimInstance Win32_Process ^| Where-Object { $_.Name -match '^python(\.exe)?$' -and $_.CommandLine -match 'agent_engine\.py' } ^| Select-Object -ExpandProperty ProcessId; $new=@($current ^| Where-Object { -not $b.ContainsKey($_) }); if($new.Count -gt 0){ $new ^| ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }; Write-Host ('[RUNNER] Cleanup: stopped launched agent_engine.py PIDs: ' + ($new -join ', ')) } else { Write-Host '[RUNNER] Cleanup: no newly launched agent_engine.py process to stop.' }"

echo.
echo Agent exited with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
