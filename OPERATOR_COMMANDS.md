# OPERATOR COMMANDS (? HELP STYLE)

Day-to-day runbook in command-help format.

## NAME
Job Seeker Agent operator commands.

## SYNOPSIS

Report mode (single run):

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Report_Mode.bat
```

Search/Telegram mode (launcher defaults):

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Agent_Search_Mode.bat [options]
```

Chat-only Telegram mode (no search upfront):

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Agent_Chat_Only.bat [options]
```

Advanced direct run (bypass launcher defaults):

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\.venv\Scripts\python.exe .\agent_engine.py [options]
```

## QUICK BOTTOM LINE (HEADED APPLY DEBUG)

Copy-paste this when you want to apply while seeing the browser in action:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\.venv\Scripts\python.exe .\agent_engine.py --telegram-notify --easy-apply-run-mode headed --result-filter-mode easy_apply_do_not_apply_only --easy-apply-only --max-jobs 1
```

Why this is the right command:
- No `--headless`, so browser is visible.
- `--easy-apply-run-mode headed` keeps apply flow headed-friendly.
- Uses your existing filter mode and easy-apply-only discovery intent.

Important:
- `Start_Agent_Search_Mode.bat` hardcodes `--headless`, so do not use that launcher for headed debugging.

## RUN MODES TABLE

| Run Mode | Command Entry Point | Purpose | Main Options | Notes |
|---|---|---|---|---|
| Searching | `.\Start_Agent_Search_Mode.bat [options]` | Discover new jobs, analyze, then operate via Telegram | `--max-jobs`, `--reset-db`, `--headless`, `--easy-apply-only`, `--result-filter-mode`, `--query` | Launcher always appends `--telegram-notify --max-jobs 5 --easy-apply-run-mode search --headless` before your extra options |
| Report | `.\Start_Report_Mode.bat` | One-shot report generation/update | Usually none for launcher path | Stops after report cycle |
| Chat-only (no search upfront) | `.\Start_Agent_Chat_Only.bat [options]` | Launch Telegram session immediately using existing DB only | `--max-jobs`, `--headless`, `--easy-apply-run-mode` | Uses new `--telegram-chat-only` path (no scan run) |
| Apply-only workflow (legacy direct form) | `.\.venv\Scripts\python.exe .\agent_engine.py --telegram-chat-only [options]` | Launch Telegram session and apply from existing DB jobs only | `--easy-apply-run-mode`, optional `--headless` | Preferred over `--telegram-notify --max-jobs 0` when you want zero upfront scan |

## OPTION SCOPE TABLE

| Option | Affects Searching | Affects Report | Affects Apply-only (`--max-jobs 0`) | Meaning |
|---|---|---|---|---|
| `--max-jobs N` | Yes | Indirect | Yes | Target number of newly added jobs; `0` means no new search intake |
| `--telegram-chat-only` | No (bypasses scan) | No | Yes | Starts Telegram session immediately without running a search first |
| `--reset-db` | Yes | Usually no | Usually no | Clears processed jobs DB before run |
| `--query "..."` | Yes | Sometimes | Usually no | Search keywords for LinkedIn extraction |
| `--easy-apply-only` | Yes | Sometimes | No practical effect | Discovery filter: keep Easy Apply jobs only |
| `--result-filter-mode all` | Yes | Yes | No practical effect | No post-analysis filtering |
| `--result-filter-mode easy_apply_do_not_apply_only` | Yes | Yes | No practical effect | Keep only Easy Apply + `DO NOT APPLY` in run results |
| `--result-filter-mode easy_apply_match` | Yes | Yes | No practical effect | Keep only Easy Apply + match-level recommendations |
| `--easy-apply-run-mode search` | Yes | No practical effect | Yes | Apply-flow traversal style (incremental rescan behavior) |
| `--easy-apply-run-mode headed` | Yes | No practical effect | Yes | Apply-flow traversal style with headed-friendly behavior |
| `--headless` | Yes | Yes | Yes | Browser hidden when applied to direct python run |
| `--report-host` | No practical effect | Yes | Yes | Bind address for report HTTP endpoints used by report UI and Telegram report download link |
| `--report-port` | No practical effect | Yes | Yes | Port for report HTTP endpoints |
| `--report-public-base-url` | No practical effect | No practical effect | Yes | Public URL prefix returned to Telegram for report download links |

## COPY-PASTE EXAMPLES BY MODE

Searching (default launcher behavior):

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Agent_Search_Mode.bat
```

Searching with explicit filters:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Agent_Search_Mode.bat --easy-apply-only --result-filter-mode easy_apply_match --max-jobs 5 --headless
```

Report mode:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Report_Mode.bat
```

Apply-only workflow (no new search, headed apply behavior):

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Agent_Chat_Only.bat --easy-apply-run-mode headed
```

Chat-only on remote server with downloadable report links:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\.venv\Scripts\python.exe .\agent_engine.py --telegram-chat-only --headless --report-host 0.0.0.0 --report-port 8765 --report-public-base-url "https://YOUR_PUBLIC_HOST:8765"
```

In Telegram, send:
- `Report`
- `Download report`

## DB RESET

Safe reset (remove DB + sidecars):

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
Remove-Item .\processed_jobs.db, .\processed_jobs.db-wal, .\processed_jobs.db-shm -ErrorAction SilentlyContinue
```

Verify reset:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
Test-Path .\processed_jobs.db, .\processed_jobs.db-wal, .\processed_jobs.db-shm
```

Expected output:
- `False False False`

Optional backup before reset:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
Copy-Item .\processed_jobs.db (".\processed_jobs.backup_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".db") -ErrorAction SilentlyContinue
```
