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

## 2) Run search flow mode

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Agent_Search_Mode.bat
```

Force a fresh run (clear DB first inside agent startup):

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Agent_Search_Mode.bat --max-jobs 5 --headless --reset-db
```

What it does:
- Starts the regular Telegram-driven flow.
- Uses `--easy-apply-run-mode search`, `--max-jobs 5`, and `--headless` (from launcher defaults).
- `--max-jobs` is a target count of new DB additions for this run, not a cap on scanned cards.

Expected behavior:
- Console prints: `Starting Job Seeker Agent in search mode...`
- Telegram session should start and accept commands like `Next`, `Apply`, `Preview`, `Submit`.
- Search mode does **not** auto-open a report page in browser.

Easy Apply-only discovery mode:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Agent_Search_Mode.bat --easy-apply-only
```

Result-filter modes (post-analysis run filtering):

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Agent_Search_Mode.bat --result-filter-mode easy_apply_do_not_apply_only
```

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Agent_Search_Mode.bat --result-filter-mode easy_apply_match
```

What these new params do:
- `--result-filter-mode all` (default): no post-analysis filtering.
- `--result-filter-mode easy_apply_do_not_apply_only`: keeps only `Easy Apply` jobs with recommendation `DO NOT APPLY` in run results.
- `--result-filter-mode easy_apply_match`: keeps only `Easy Apply` jobs with match-level recommendations (for example `MATCH` / `STRONG MATCH`) in run results.

Important behavior:
- Both `easy_apply_do_not_apply_only` and `easy_apply_match` force Easy Apply discovery filtering automatically (equivalent to Easy Apply-only discovery intent for that run).
- Filtering is applied after recommendation analysis, so DB metadata is still refreshed for analyzed jobs.
- Report search parameters now include `Result Filter Mode` so operator can verify active mode.

Important note:
- `--easy-apply-run-mode search` controls apply-flow scanning behavior only.
- It does not filter discovered jobs to Easy Apply.
- Use `--easy-apply-only` for discovery filtering.
- Extraction now keeps scanning result cards until target is reached or result feed is exhausted.

Expected behavior in Easy Apply-only mode:
- LinkedIn search URL includes `f_AL=true` (Easy Apply filter) before scanning cards.
- If per-job probe is inconclusive (`Unknown`), the run trusts the filtered search feed and treats the card as Easy Apply.
- Jobs without confirmed Easy Apply are filtered out during discovery.
- Only jobs classified as `Easy Apply` are added as newly discovered jobs.

If your browser keeps showing an old report (for example `Generated: 2026-04-08 ...`):
- You are likely viewing a previously opened local HTML tab, not the live latest-report server.
- Run report mode, then use the server URL it prints (for example `http://127.0.0.1:8765/`).
- Avoid opening report files directly from disk when you want the latest auto-selected report.

Optional examples:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Agent_Search_Mode.bat --max-jobs 8
```

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Agent_Search_Mode.bat --query "Senior C# Developer Israel"
```

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\Start_Agent_Search_Mode.bat --easy-apply-only --result-filter-mode easy_apply_match --max-jobs 5 --headless
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
