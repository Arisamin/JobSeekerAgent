# Project Handover

## 0. Session Working Rules (User-Specific)

These rules are required for this repo going forward:

1. After making changes, the agent must always provide:
  - exact next steps for the user,
  - what to test,
  - and expected behavior/results.
2. The agent must never initiate `git commit` or `git push` on its own.
  - Commits/pushes are done only when the user explicitly asks.
3. The agent must update `CHAT_LOG.txt` on every interaction.
  - Keep newest entry pair at top.
  - Keep `[Copilot]` section above corresponding `[User]` section for each pair.
  - Keep entries concise but sufficient for restart continuity (requests, regressions, fixes, current status, next steps/open issues).

## 1. Project Goal

`Job Seeker Agent` automates a LinkedIn job-application workflow with a Telegram-driven interface.

Primary goals:
- Discover and browse jobs from DB/new scrape results.
- Drive application flow through Telegram state machine (`Next`, `Apply`, `Skip`, `Done`, `db`, `Cancel`).
- Prioritize LinkedIn Easy Apply jobs/flows as the top automation path.
- Scan LinkedIn Easy Apply forms first, then external apply forms as fallback, and ask only relevant required questions that don't have corresponding cached answers.
- Build a trustworthy pre-submit summary of captured answers.
- Support preview mode that fills the real apply flow and halts before submit for visual verification.

Secondary goals:
- Keep job status DB consistent (`Discovered`, `Applied`, `Skipped`, etc.).
- Maintain robust, repeatable regression checks with artifact-backed tests.

Current status snapshot:
- Mobileye summary external apply form behavior is now correct for the validated saved HTML contract.
- Recent regressions around duplicate questions and LinkedIn AWLI disclaimer pseudo-questions were fixed and covered by tests.

## 2. Development Methodology (User-Mandated)

The user explicitly requires strict engineering discipline.

### NON-NEGOTIABLE RULES

1. Never claim code is ready without test evidence.
2. Never submit/finalize a patch before running tests.
3. Never use speculative confirmation language ("should work", "should pass now").
4. On failures, provide root cause, exact file/line context, one targeted fix, and re-run proof.
5. Keep docs aligned with behavior; update handover/test expectations when logic meaningfully changes.
6. Before changes, state target files, verifying tests, exact commands, and success criteria.
7. After user-provided test output, parse pass/fail explicitly and respond with evidence-backed next action.

Standard flow:
1. Reproduce/define behavior with tests.
2. Implement/fix.
3. Re-run tests immediately and show output.
4. Only then mark complete.

Operational checklist source:
- `SKILL_CHECKLIST.md`

Flowcharts for behavior changes:
- `FLOWCHART_STATE_MACHINE.md`
- `FLOWCHART_SKIPPED_MAINTENANCE.md`
- `FLOWCHART_USER_DB_UPDATE.md`

## 3. Model Selection Requirements

Use a large-context, deterministic coding model for this repo.

Minimum requirements:
- Context window: 160K minimum (200K+ strongly recommended).
- Strong multi-step reasoning for TDD and log-driven debugging.
- Fixed model selection for the session (avoid Auto switching).

Recommended:
- `GPT-5.3-Codex` (preferred)
- `GPT-5.4`

Avoid:
- Auto model switching.
- Small/fast models that lose context in long debugging sessions.

Why it matters here:
- This project repeatedly requires cross-referencing logs, tests, scan/apply code paths, and saved HTML artifacts in one pass.

## 4. Test Strategy and Commands

### 4.1 Unit and regression tests

Full suite:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.venv\Scripts\python.exe -m pytest Tests -q
```

Focused Mobileye regressions:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.venv\Scripts\python.exe -m pytest \
  Tests/test_mobileye_gap_root_causes.py \
  Tests/test_mobileye_saved_html_summary.py -q
```

Saved-HTML inventory + summary printout:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.venv\Scripts\python.exe -m pytest \
  Tests/test_mobileye_saved_html_summary.py::TestMobileyeSavedHtmlSummary::test_saved_html_scanner_summary_matches_expected_mobileye_questions \
  -s -q
```

Timeout runner (repo standard):

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.venv\Scripts\python.exe Tests\_timeout_runner.py Tests\
```

### 4.2 End-to-end Telegram-driven test

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\run_auto_agoda_test.ps1 -NoScrape -PreviewBeforeSubmit
```

Artifacts:
- `Tests/Samples/auto_agoda_summary.txt`
- `Tests/Samples/auto_agoda_chat_transcript.txt`
- `Logs/run_*.log`

## 5. Codebase Structure and Roles

Core runtime:
- `agent_engine.py`: Telegram state machine, scan/build/summary logic, Playwright apply paths.
- `auto_agoda_test_agent.py`: deterministic automation for test flow.
- `run_auto_agoda_test.ps1`: one-command e2e runner.

Data/config:
- `processed_jobs.db`
- `telegram_profile.json`
- `JOB_REQUIREMENTS.json`
- `JOB_HUNTER_PERSONA.md`
- `MY_CONTEXT.md`

Design docs:
- `FLOWCHART_STATE_MACHINE.md`
- `FLOWCHART_SKIPPED_MAINTENANCE.md`
- `FLOWCHART_USER_DB_UPDATE.md`
- `USER_DB_UPDATE_GUIDE.md`

Diagnostics:
- `Logs/`
- `Reports/`
- `diag_*.py`
- `scan_debug_screenshot.png`

Tests:
- `Tests/` (scan, dedupe, preview termination, chat flow, saved HTML contracts)

## 6. Architecture Summary

### 6.1 Telegram state machine
`TelegramJobSession` handles:
- Intro/report
- New/DB browsing
- Apply Q/A collection
- Summary confirmation (`Preview`/`Submit`)

### 6.2 Scan and prompt generation
- `_scan_easy_apply_fields(...)`: discovers fields/types/options.
- `_build_apply_form_fields(...)`: composes fixed + scanned prompts.
- Custom question keys use stable hashed format: `custom__<slug>__<hash10>`.

### 6.3 Summary and verification
- `_show_apply_summary()` renders deduped answers.
- `_apply_scan_unverified` warns when scan confidence is low.

### 6.4 Preview/submit execution
- `_do_linkedin_easy_apply(...)` fills modal/wizard.
- `submit_application=False` = preview stop before submit.

## 7. What Changed Recently

Recent validated changes:
- Strengthened semantic dedupe for equivalent question variants (build + rescan + summary).
- Fixed Mobileye saved-HTML contract behavior:
  - LinkedIn share control represented as explicit `action` question.
  - Additional information textarea and marketing consent extracted.
  - Cover-letter file path no longer forced as always-fixed when not present in form.
- Suppressed AWLI disclaimer pseudo-questions (e.g. `Your full LinkedIn profile will be`, `shared. Learn more`).
- Added/updated regressions:
  - `Tests/test_mobileye_saved_html_summary.py`
  - `Tests/test_mobileye_gap_root_causes.py`
  - `Tests/test_chat_flow_regression.py`
- Added printed numbered inventories in saved-HTML test output:
  - expected question set
  - discovered (runtime logic) question set

Recent commits on active branch:
- `0d50492` - Mobileye saved-HTML contract updates (LinkedIn action + cover-letter dedupe)
- `5412686` - AWLI disclaimer pseudo-question suppression

## 8. Open Issues and Friction Encountered

1. LinkedIn/Lever DOM volatility remains a general risk.
2. Live runtime can still surface site-specific noise if new widget text appears; artifact tests should be extended when new patterns are observed.
3. `telegram_profile.json` can accumulate stale custom answers from exploratory runs and may influence prompts if not cleaned.

No current blocker on the validated Mobileye summary contract.

## 9. Immediate Next Steps (Ordered)

### Step 1: Baseline validation (mandatory)
Run and share outputs:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.venv\Scripts\python.exe -m pytest Tests -q
```

Optional live check if user requests runtime confirmation:
- Run one Mobileye apply flow in preview path.
- Confirm summary contains only expected LinkedIn items:
  - `LinkedIn profile URL`
  - `LinkedIn profile` (`Share`/`Skip`)
- Confirm no AWLI disclaimer pseudo-question appears.

### Step 2: Keep saved-HTML contract current
If Mobileye form HTML changes:
- Update expected set in `Tests/test_mobileye_saved_html_summary.py`.
- Preserve strict equality assertion (label + type + options).
- Re-run focused + full tests.

### Step 3: Expand artifact-driven contracts for additional employers
- Add similar saved-HTML contract tests for other volatile external forms.

## 10. Red Flags That Mean STOP

Stop and correct immediately if any occur:
- Claiming fixes without test output.
- Shipping changes after only partial/path-specific testing.
- Updating only scan or only apply when behavior depends on both.
- Accepting new pseudo-questions without adding suppression tests.
- Editing production profile data (`telegram_profile.json`) as part of code fixes.

## 11. Suggested Handover Workflow for Next Agent

### Phase 1: Understand current state
Read:
1. `HANDOVER.md`
2. `CHAT_LOG.txt`
3. `SKILL_CHECKLIST.md`
4. `FLOWCHART_STATE_MACHINE.md`
5. `Tests/test_mobileye_saved_html_summary.py`
6. `Tests/test_mobileye_gap_root_causes.py`

### Phase 2: Prove baseline health
- Run full tests.
- Run focused Mobileye tests.
- If needed, run saved-HTML test with `-s` and inspect inventories/summary output.

### Phase 3: Implement deltas only with regression guardrails
- Add/adjust test first.
- Patch minimally.
- Re-run focused then full suite.

## 12. How To Work With Me (User Expectations)

- Explain why a change is needed.
- Point to exact file(s)/function(s).
- Show test evidence after changes.
- For regressions from chat transcripts, map transcript symptom to exact code path and add a dedicated test.

User-preferred style for this repo:
- Artifact-grounded validation over assumptions.
- Clear pass/fail evidence in chat.
- Avoid vague confidence language.

## 13. Notes for Reliability

- Treat saved HTML contracts as source of truth for extraction behavior.
- Keep summary dedupe semantics aligned with scan dedupe semantics.
- Prefer adding small suppression heuristics plus regression tests for new UI text noise.
- Keep local runtime artifacts and profile noise out of commits unless explicitly requested.

## 14. Session Bootstrap Checklist

Before starting a new debugging session:

- Select `GPT-5.3-Codex` (or equivalent large-context model).
- Disable Auto model switching.
- Run baseline tests and share output.
- If task is Mobileye-specific, run:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.venv\Scripts\python.exe -m pytest \
  Tests/test_mobileye_gap_root_causes.py \
  Tests/test_mobileye_saved_html_summary.py -q
```

- If extraction behavior is under discussion, run the saved-HTML test with `-s` and share the two numbered inventories plus summary block.
