# Job Seeker Agent

## Handover

Comprehensive project handover document:
- `HANDOVER.md`

## Development methodology (mandatory)

Before every code-change iteration, follow `SKILL_CHECKLIST.md`.

- Checklist file: `SKILL_CHECKLIST.md`
- Flowcharts to keep aligned with logic changes:
	- `FLOWCHART_STATE_MACHINE.md`
	- `FLOWCHART_SKIPPED_MAINTENANCE.md`
	- `FLOWCHART_USER_DB_UPDATE.md`

## Testing

Run unit tests through the timeout wrapper so hangs fail fast and print diagnostics.

### Full suite

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.venv\Scripts\python.exe Tests\_timeout_runner.py Tests\
```

### Specific test file

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.venv\Scripts\python.exe Tests\_timeout_runner.py Tests\test_session_patches.py
```

### Optional timeout overrides

```powershell
$env:PYTEST_HARD_TIMEOUT="180"
$env:PYTEST_FAULTHANDLER_TIMEOUT="30"
.venv\Scripts\python.exe Tests\_timeout_runner.py Tests\
```

### VS Code tasks

- `tests: timeout (all)`
- `tests: timeout (session patches)`

### When timeout is reached

- `pytest` prints faulthandler diagnostics after `PYTEST_FAULTHANDLER_TIMEOUT` seconds.
- The wrapper then enforces the hard timeout (`PYTEST_HARD_TIMEOUT`), terminates the test process, and exits with code `124`.

## Auto Agoda test (no manual Telegram steps)

Run one command to:
1. scrape/analyze jobs,
2. browse DB jobs automatically,
3. open Apply on Agoda,
4. answer cover letter with `none`,
5. open LinkedIn Easy Apply, fill fields from tester answers, and stop on final review (no submit),
6. print and save the application summary.

### Quick run (recommended)

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\run_auto_agoda_test.ps1
```

By default, this run sends `Preview` after summary: LinkedIn opens, fields are filled, and the flow pauses on the final submit page. Close the browser window after reviewing to let the runner finish.

### Useful options

```powershell
# Headed scrape (visible browser)
.\run_auto_agoda_test.ps1 -Headed

# Skip scrape, only run DB/apply automation
.\run_auto_agoda_test.ps1 -NoScrape

# Mirror tester ↔ job-seeker chat into Telegram
.\run_auto_agoda_test.ps1 -NoScrape -MirrorToTelegram

# Opt out of preview mode and keep old summary-only completion
.\run_auto_agoda_test.ps1 -NoScrape -NoPreviewBeforeSubmit

# Force legacy conservative scan behavior
.\run_auto_agoda_test.ps1 -EasyApplyRunMode normal

# Target a different company/job substring
.\run_auto_agoda_test.ps1 -JobMatch "semperis"
```

### Output

- Console prints `[TEST][PASS]`/`[TEST][FAIL]`
- Summary file path: `Tests/Samples/auto_agoda_summary.txt`
- Full simulated chat transcript path: `Tests/Samples/auto_agoda_chat_transcript.txt`
