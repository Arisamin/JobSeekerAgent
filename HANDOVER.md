# Project Handover

## 1. Project Goal

`Job Seeker Agent` automates a LinkedIn job-application workflow with a Telegram-driven interface.

Primary goals:
- Discover and browse jobs from DB/new scrape results.
- Drive application flow through Telegram state machine (`Next`, `Apply`, `Skip`, `Done`, `db`, `Cancel`).
- Scan LinkedIn Easy Apply forms and ask only required questions.
- Build a trustworthy pre-submit summary of all captured answers.
- Support preview mode that fills the real LinkedIn modal and halts before submit for visual verification.

Secondary goals:
- Keep job status DB consistent (`Discovered`, `Applied`, `Skipped`).
- Provide robust test harnesses and deterministic regression checks.

## 2. Development Methodology (User-Mandated)

The user explicitly requires strict engineering discipline:

- TDD-oriented flow:
  1. Reproduce/define behavior with tests.
  2. Implement/fix.
  3. Re-run tests immediately.
- Unit tests must pass before end-to-end runs.
- Do not claim progress without test evidence.
- Keep flowcharts and docs aligned with logic changes.
- Use the Telegram tester flow for realistic behavior validation.
- Avoid blind reruns; explain failure cause and the exact delta change.

Operational checklist source:
- `SKILL_CHECKLIST.md`

Flowcharts that must be updated when logic changes:
- `FLOWCHART_STATE_MACHINE.md`
- `FLOWCHART_SKIPPED_MAINTENANCE.md`
- `FLOWCHART_USER_DB_UPDATE.md`

## 3. Test Strategy and Commands

### 3.1 Unit tests (must run first)

Preferred commands:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.venv\Scripts\python.exe Tests\_timeout_runner.py Tests\
```

Or targeted:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.venv\Scripts\python.exe Tests\_timeout_runner.py Tests\test_session_patches.py
```

Current relevant suite often used during Easy Apply work:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.venv\Scripts\python.exe -m pytest \
  Tests/test_session_patches.py \
  Tests/test_apply_rescan_dedup.py \
  Tests/test_easy_apply_testing_mode.py \
  Tests/test_custom_question_labels.py \
  Tests/test_agoda_fallback_questions.py -q
```

### 3.2 End-to-end Telegram-driven test

Use Agoda automation runner:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\run_auto_agoda_test.ps1 -NoScrape -PreviewBeforeSubmit
```

Artifacts:
- `Tests/Samples/auto_agoda_summary.txt`
- `Tests/Samples/auto_agoda_chat_transcript.txt`
- Runtime logs in `Logs/`

## 4. Codebase Structure and Roles

### Core runtime
- `agent_engine.py`
  - Main state machine, Telegram I/O, LinkedIn automation, apply scan/fill/submit logic.
- `auto_agoda_test_agent.py`
  - Deterministic tester agent that simulates Telegram interaction and answers prompts.
- `run_auto_agoda_test.ps1`
  - One-command e2e regression runner.

### Data and config
- `processed_jobs.db`
  - Primary job/status database.
- `telegram_profile.json`
  - Persisted profile + saved answers.
- `JOB_REQUIREMENTS.json`, `JOB_HUNTER_PERSONA.md`, `MY_CONTEXT.md`
  - Search/profile context.

### Design docs
- `FLOWCHART_STATE_MACHINE.md`
- `FLOWCHART_SKIPPED_MAINTENANCE.md`
- `FLOWCHART_USER_DB_UPDATE.md`
- `USER_DB_UPDATE_GUIDE.md`

### Diagnostics
- `Logs/`
- `Reports/`
- `scan_debug_screenshot.png`
- `diag_*.py` helpers

### Tests
- `Tests/` with timeout wrapper and targeted regression tests.

## 5. Architecture Summary

### 5.1 Telegram state machine
`TelegramJobSession` orchestrates:
- Intro/report
- DB browsing
- Apply initiation
- Q/A collection
- Summary confirmation (`Preview` or `Submit`)

### 5.2 Easy Apply scanning and prompt generation
- `_scan_easy_apply_fields(...)` scans modal fields and infers types/options.
- `_build_apply_form_fields(...)` creates ordered prompts from fixed + custom fields.
- Keys for custom questions use collision-resistant format:
  - `custom__<slug>__<hash10>`

### 5.3 Summary and verification
- `_show_apply_summary()` renders deduped Q/A list.
- `_apply_scan_unverified` flag adds warning if scan confidence is low.

### 5.4 Preview/submit execution
- `_do_linkedin_easy_apply(...)` performs browser actions.
- `submit_application=False` enters preview path (halt before submit).
- Browser snapshot support captures visible field labels/values for cross-check.

## 6. What Changed Recently

Key implemented improvements:
- Added Easy Apply selector support for Agoda button text spans in both scan and apply paths.
- Added browser snapshot reporting during preview.
- Added scan-unverified warning in summary.
- Gated Agoda synthetic fallback questions behind env var:
  - `AGENT_ENABLE_AGODA_FALLBACK=1` (enabled in test runner, off by default for production).
- Improved label canonicalization and dedup handling.
- Added/updated regression tests around prompt handling, fallback behavior, and rescan dedup.
- Reworked preview loop to avoid relying on a small hard step cap as normal flow; added progress/stagnation signal and high failsafe cap.

## 7. Open Issues and Friction Encountered

1. LinkedIn DOM volatility
- Selectors can become stale quickly; scan and apply had duplicated selector lists, which caused regressions when only one list was updated.

2. Scan vs. apply drift risk
- There are multiple paths with similar logic. Changes must be mirrored or refactored into shared helpers.

3. Long Agoda wizard behavior
- Agoda modal can have many `Next` pages; low caps falsely terminate before true submit page.

4. Browser/profile instability
- `launch_persistent_context` against primary profile intermittently fails with context closed/exited errors and falls back to `.playwright_profile`.

5. Data quality in saved profile
- `telegram_profile.json` may accumulate noisy or undesirable custom answers from test sessions; this can skew future prompts/fills.

6. Process discipline gaps observed during session
- At least one patch was reported before rerunning tests; user explicitly flagged this as methodology violation.

## 8. Immediate Next Steps (Priority Order)

1. Run one clean live validation with current code
- Command:
  ```powershell
  .\run_auto_agoda_test.ps1 -NoScrape -PreviewBeforeSubmit
  ```
- Confirm end condition is one of:
  - `Preview stopped at final submit step (no submit clicked).`
  - `Easy Apply wizard stopped progressing ...`
- Capture outcome from latest `Logs/run_*.log` and Telegram outputs.

2. Consolidate duplicated selector constants
- Move Easy Apply selector list into one shared class constant/helper used by both scan and apply.

3. Add targeted tests for preview loop termination
- Mock wizard sequence to assert:
  - submit-step exit
  - stagnation exit
  - failsafe-cap exit

4. Sanitize persisted profile test pollution
- Prune invalid/offensive/noise custom fields in `telegram_profile.json` before production runs.

5. Keep docs synchronized
- If behavior changed, update relevant flowcharts and README sections immediately.

## 9. Suggested Handover Workflow for Next Agent

1. Read in order:
- `README.md`
- `SKILL_CHECKLIST.md`
- `HANDOVER.md`
- `FLOWCHART_STATE_MACHINE.md`

2. Reproduce baseline:
- Run unit tests (timeout runner or focused pytest set).
- Run Agoda tester in preview mode.

3. Inspect latest logs/artifacts:
- `Logs/run_*.log`
- `Tests/Samples/auto_agoda_summary.txt`
- `Tests/Samples/auto_agoda_chat_transcript.txt`

4. Only then implement deltas.

## 10. Notes for Reliability

- Treat preview/browser snapshot as source of truth when scan confidence is low.
- Keep all user-facing claims grounded in test output or log lines.
- Prefer small, test-backed edits over broad refactors during active debugging.
