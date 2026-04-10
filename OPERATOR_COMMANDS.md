# Operator Commands

Copy-paste commands for day-to-day operation.

## 1) Run report mode

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Report_Mode.bat
```

What it does:
- Runs one report-mode cycle.
- Generates/updates report artifacts in `Reports`.
- Stops after the run.

Expected behavior:
- Console prints: `Starting Job Seeker Report Mode...`
- Then: `Report Mode stopped. You can close this window.`

## 2) Run normal flow mode

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Agent_Normal_Mode.bat
```

Force a fresh run (clear DB first inside agent startup):

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Agent_Normal_Mode.bat --max-jobs 5 --headless --reset-db
```

What it does:
- Starts the regular Telegram-driven flow.
- Uses `--easy-apply-run-mode normal`, `--max-jobs 5`, and `--headless` (from launcher defaults).

Expected behavior:
- Console prints: `Starting Job Seeker Agent in normal mode...`
- Telegram session should start and accept commands like `Next`, `Apply`, `Preview`, `Submit`.
- Normal mode does **not** auto-open a report page in browser.

If your browser keeps showing an old report (for example `Generated: 2026-04-08 ...`):
- You are likely viewing a previously opened local HTML tab, not the live latest-report server.
- Run report mode, then use the server URL it prints (for example `http://127.0.0.1:8765/`).
- Avoid opening report files directly from disk when you want the latest auto-selected report.

Optional examples:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Agent_Normal_Mode.bat --max-jobs 8
```

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Agent_Normal_Mode.bat --query "Senior C# Developer Israel"
```

## 3) Clear jobs DB

Safe reset command (removes DB and SQLite sidecar files):

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
Remove-Item .\processed_jobs.db, .\processed_jobs.db-wal, .\processed_jobs.db-shm -ErrorAction SilentlyContinue
```

Verification (recommended):

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
Test-Path .\processed_jobs.db, .\processed_jobs.db-wal, .\processed_jobs.db-shm
```

Expected verification output:
- `False False False`

Optional backup before clear:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
Copy-Item .\processed_jobs.db (".\processed_jobs.backup_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".db") -ErrorAction SilentlyContinue
```

Expected behavior after clearing:
- On next run, a fresh DB is created automatically.
- All prior job statuses/history in `processed_jobs.db` are reset.
