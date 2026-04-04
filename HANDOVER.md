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

### NON-NEGOTIABLE RULES:

**These rules are MANDATORY. Violations will result in immediate task termination and restart.**

1. **NEVER claim code is ready without test evidence**
   - ❌ WRONG: "I've updated the selector constants"
   - ✓ CORRECT: "I've updated selector constants. Running tests now..."
   - ✓ CORRECT: "Changes made. Test output: [paste actual output]"

2. **NEVER submit a patch before running tests**
   - If you propose code changes, your IMMEDIATE next action MUST be:
     ```
     Running: python Tests\_timeout_runner.py Tests/test_session_patches.py
     ```
   - Show the actual test output, not a description of it

3. **NEVER say 'the tests should pass now' or 'this should work'**
   - ❌ WRONG: "The tests should pass now"
   - ✓ CORRECT: "Running tests..." [then show actual output]
   - Claims without evidence are false confirmations

4. **When a test fails, you MUST explain:**
   - **Root cause** (not speculation or guesses)
   - **Exact line/file** causing the failure
   - **Specific change** that will fix it (one targeted change, not "try this")
   - **Re-run proof** after the fix (show green tests)

5. **Update documentation BEFORE changing code**
   - If logic changes, update flowcharts FIRST, then implement
   - Code follows documentation, not the other way around

6. **Before proposing ANY code change, state:**
   - Which file(s) will change
   - Which test(s) will verify the change
   - The exact command I should run to verify
   - What "success" looks like (specific output to expect)

7. **After I run tests and paste results:**
   - Parse the output for PASS/FAIL
   - If FAIL: Quote the exact error line
   - If FAIL: Explain root cause from the error
   - If FAIL: Propose ONE specific fix
   - If PASS: Confirm which requirement is now satisfied

### If you violate these rules:
The user will stop you immediately, point out the violation, and restart the task from the beginning.

### Standard TDD-oriented flow:
1. Reproduce/define behavior with tests
2. Implement/fix
3. Re-run tests immediately and show output
4. Only then claim task is complete

### Operational checklist source:
- `SKILL_CHECKLIST.md`

### Flowcharts that must be updated when logic changes:
- `FLOWCHART_STATE_MACHINE.md`
- `FLOWCHART_SKIPPED_MAINTENANCE.md`
- `FLOWCHART_USER_DB_UPDATE.md`

## 3. Model Selection Requirements

**This project requires specific AI model capabilities to work correctly.**

### Minimum Requirements:
- **Context window:** 160K tokens minimum (200K+ strongly recommended)
  - Need to hold: entire codebase, flowcharts, test files, logs, conversation history
  - Insufficient context causes flowchart drift, selector duplication, and false confirmations
- **Multi-step reasoning capability** for TDD workflows
- **Deterministic behavior** (same model across sessions, NO auto-switching)

### Recommended Models (in priority order):

**TIER 1 - Best Choice:**
- **GPT-5.3-Codex** (400K context, 1x cost)
  - ✓ Can hold ENTIRE project without dropping context
  - ✓ Code-specialized variant
  - ✓ Prevents flowchart drift and selector duplication issues
- **GPT-5.4** (400K context, 1x cost)
  - ✓ Same capacity as 5.3-Codex
  - ✓ Newer generation

**TIER 2 - Acceptable if TIER 1 unavailable:**
- **GPT-5.2-Codex** (400K context, 1x cost)
- **Claude Opus 4.6** (192K context, 3x cost) - Expensive but high quality

**TIER 3 - Marginal (use only if others unavailable):**
- **Claude Sonnet 4.6** (160K context, 1x cost)
  - ⚠️ Minimum acceptable context size
  - ⚠️ May drop context under heavy discussion
- **GPT-5.1** (192K context, 1x cost)

### DO NOT USE:
- ❌ **Auto/Dynamic model selection** - Causes inconsistent behavior across sessions
- ❌ **GPT-4.1 or older** (128K or less) - Context too small for this project
- ❌ **GPT-4o** (68K) - Way too small, will cause amnesia and drift
- ❌ **Fast/cheap variants** (Haiku, Flash, mini) - Optimized for speed over verification
- ❌ **Gemini Flash** - "Flash" means speed over accuracy

### Why Context Size Matters:

**Insufficient context causes these exact issues:**
1. **Flowchart drift** - Flowchart evicted from context during implementation
2. **Selector duplication** - Can't see both selector lists simultaneously
3. **False confirmations** - Requirements already evicted when you ask "does this match?"
4. **Repeating mistakes** - Error logs and previous attempts dropped from context
5. **Inconsistent behavior** - Different context = different understanding each session

### Model Selection Checklist:
```
Before starting work:
1. ✓ Select a TIER 1 model manually (disable Auto mode)
2. ✓ Verify context window is 200K+ tokens
3. ✓ Lock selection for entire session (don't switch mid-task)
4. ✓ Upload ALL key documents in first message to maximize context usage
```

## 4. Test Strategy and Commands

### 4.1 Unit tests (must run first)

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

### 4.2 End-to-end Telegram-driven test

Use Agoda automation runner:

```powershell
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.\run_auto_agoda_test.ps1 -NoScrape -PreviewBeforeSubmit
```

Artifacts:
- `Tests/Samples/auto_agoda_summary.txt`
- `Tests/Samples/auto_agoda_chat_transcript.txt`
- Runtime logs in `Logs/`

## 5. Codebase Structure and Roles

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

## 6. Architecture Summary

### 6.1 Telegram state machine
`TelegramJobSession` orchestrates:
- Intro/report
- DB browsing
- Apply initiation
- Q/A collection
- Summary confirmation (`Preview` or `Submit`)

### 6.2 Easy Apply scanning and prompt generation
- `_scan_easy_apply_fields(...)` scans modal fields and infers types/options.
- `_build_apply_form_fields(...)` creates ordered prompts from fixed + custom fields.
- Keys for custom questions use collision-resistant format:
  - `custom__<slug>__<hash10>`

### 6.3 Summary and verification
- `_show_apply_summary()` renders deduped Q/A list.
- `_apply_scan_unverified` flag adds warning if scan confidence is low.

### 6.4 Preview/submit execution
- `_do_linkedin_easy_apply(...)` performs browser actions.
- `submit_application=False` enters preview path (halt before submit).
- Browser snapshot support captures visible field labels/values for cross-check.

## 7. What Changed Recently

Key implemented improvements:
- Added Easy Apply selector support for Agoda button text spans in both scan and apply paths.
- Added browser snapshot reporting during preview.
- Added scan-unverified warning in summary.
- Gated Agoda synthetic fallback questions behind env var:
  - `AGENT_ENABLE_AGODA_FALLBACK=1` (enabled in test runner, off by default for production).
- Improved label canonicalization and dedup handling.
- Added/updated regression tests around prompt handling, fallback behavior, and rescan dedup.
- Reworked preview loop to avoid relying on a small hard step cap as normal flow; added progress/stagnation signal and high failsafe cap.

## 8. Open Issues and Friction Encountered

### 8.1 LinkedIn DOM volatility
- Selectors can become stale quickly; scan and apply had duplicated selector lists, which caused regressions when only one list was updated.
- **Root cause:** Insufficient context window caused AI to see only one selector list at a time.

### 8.2 Scan vs. apply drift risk
- There are multiple paths with similar logic. Changes must be mirrored or refactored into shared helpers.
- **Root cause:** AI couldn't cross-reference both code paths simultaneously due to context limitations.

### 8.3 Long Agoda wizard behavior
- Agoda modal can have many `Next` pages; low caps falsely terminate before true submit page.

### 8.4 Browser/profile instability
- `launch_persistent_context` against primary profile intermittently fails with context closed/exited errors and falls back to `.playwright_profile`.

### 8.5 Data quality in saved profile
- `telegram_profile.json` may accumulate noisy or undesirable custom answers from test sessions; this can skew future prompts/fills.

### 8.6 Process discipline gaps observed during session
- **CRITICAL:** At least one patch was reported before rerunning tests.
- This is a **methodology violation** (see Section 2, Rule 2).
- **Root causes identified:**
  - Auto model selection caused inconsistent AI behavior across sessions
  - Insufficient context window (68K-160K models) caused flowchart drift and false confirmations
  - Vague prompts that didn't enforce test-first discipline

## 9. Immediate Next Steps (DO IN ORDER - GATED PROGRESSION)

### Step 1: Validate Current State (MANDATORY FIRST - DO NOT SKIP)

**Goal:** Prove baseline works before ANY changes

**Prerequisites:**
- Select GPT-5.3-Codex or GPT-5.4 (400K context) manually
- Disable Auto mode
- Upload all key documents to maximize context

**Commands to run:**
```powershell
# Must pass - all unit tests green:
Set-Location "c:\MyData\Git\AI Projects\Job Seeker Agent"
.venv\Scripts\python.exe Tests\_timeout_runner.py Tests/

# Must complete with expected exit:
.\run_auto_agoda_test.ps1 -NoScrape -PreviewBeforeSubmit
```

**Success criteria (ALL must be true):**
- ✓ All unit tests pass (green output)
- ✓ Agoda test exits with one of:
  - "Preview stopped at final submit step (no submit clicked)."
  - "Easy Apply wizard stopped progressing..."
- ✓ No crashes, timeouts, or unexpected errors
- ✓ Latest `Logs/run_*.log` shows clean execution

**Evidence required:**
- Paste full test output
- Quote exit message from Agoda test
- Confirm log file location and key lines

**GATE:** Do NOT proceed to Step 2 until this works and evidence is provided.

---

### Step 2: Consolidate Selector Duplication

**Goal:** Fix drift risk between scan and apply selector lists

**Why this is Step 2:**
- Step 1 proves baseline works
- This fix prevents future regressions
- Changes are isolated and testable

**Task:**
1. Move Easy Apply selector list into one shared class constant/helper
2. Update both `_scan_easy_apply_fields` and `_do_linkedin_easy_apply` to use shared source
3. Add unit test that verifies selectors are identical in both paths

**Validation:**
```powershell
# Must pass after changes:
.venv\Scripts\python.exe Tests\_timeout_runner.py Tests/
.\run_auto_agoda_test.ps1 -NoScrape -PreviewBeforeSubmit
```

**GATE:** Do NOT proceed to Step 3 until tests pass and you show output.

---

### Step 3: Add Preview Loop Termination Tests

**Goal:** Ensure preview mode exits correctly under all scenarios

**Task:**
- Mock wizard sequence to assert:
  - submit-step exit (normal path)
  - stagnation exit (stuck on same page)
  - failsafe-cap exit (safety limit reached)

**Validation:**
```powershell
# New test file must pass:
.venv\Scripts\python.exe Tests\_timeout_runner.py Tests/test_preview_termination.py
```

**GATE:** Do NOT proceed to Step 4 until new tests exist and pass.

---

### Step 4: Sanitize Persisted Profile

**Goal:** Remove test pollution from `telegram_profile.json`

**Task:**
- Prune invalid/offensive/noise custom fields
- Backup original file first
- Verify cleaned profile doesn't break existing tests

**Validation:**
```powershell
# Must still pass with cleaned profile:
.\run_auto_agoda_test.ps1 -NoScrape -PreviewBeforeSubmit
```

**GATE:** Do NOT proceed to Step 5 until validation passes.

---

### Step 5: Synchronize Documentation

**Goal:** Keep docs aligned with code changes

**Task:**
- If behavior changed in Steps 2-4, update relevant flowcharts
- Update README sections if workflow changed
- Ensure SKILL_CHECKLIST reflects new tests added in Step 3

**Validation:**
- Manual review: Do flowcharts match current code behavior?
- Git diff: Are doc updates committed alongside code changes?

---

## 10. Red Flags That Mean STOP

**If any of these happen during work, STOP immediately and do NOT continue:**

### 🚩 Methodology Violations:

1. **You modify code without running tests**
   - STOP. Run tests first, show output, then proceed.

2. **You say "tests should pass now" or "this should work" without re-running**
   - STOP. These are false confirmations. Show actual test output.

3. **You claim something works based on "reading the code"**
   - STOP. Code doesn't prove behavior - tests do.

4. **You propose a patch and don't immediately follow with test execution**
   - STOP. Rule 2 violation. Run tests before claiming task complete.

### 🚩 Context/Understanding Issues:

5. **You can't quote from HANDOVER.md or flowcharts mid-conversation**
   - STOP. Documents were evicted from context. Re-upload and start over.

6. **You make assumptions about LinkedIn DOM without checking logs**
   - STOP. Check `scan_debug_screenshot.png` and actual selector hits in logs.

7. **You suggest changes to both scan and apply paths but only modify one**
   - STOP. This causes drift (Section 8.2). With 400K context you should see both simultaneously.

### 🚩 Documentation Drift:

8. **You update a flowchart AFTER changing code**
   - STOP. Flowchart should change FIRST, then code follows (Rule 5).

9. **You can't explain how your change aligns with existing flowcharts**
   - STOP. Re-read flowcharts, understand current design, then propose changes.

### 🚩 Process Shortcuts:

10. **You say "I'll run tests after we finish this feature"**
    - STOP. TDD means tests DURING implementation, not after.

11. **You suggest skipping Step 1 baseline validation**
    - STOP. Baseline validation is mandatory. Never skip.

12. **You claim to have run tests but don't paste output**
    - STOP. Claims without evidence are false confirmations.

---

## 11. Suggested Handover Workflow for Next Agent

### Phase 1: Comprehension (Do NOT Code Yet)

1. **Read in order:**
   - `README.md`
   - `SKILL_CHECKLIST.md`
   - `HANDOVER.md` (this file)
   - `FLOWCHART_STATE_MACHINE.md`

2. **Prove comprehension by answering:**
   - What does this project do? (in your own words)
   - What are the 5 non-negotiable methodology rules?
   - What commands would you run to verify baseline health?
   - What is the minimum required context window and why?

3. **Wait for user confirmation** before proceeding to Phase 2.

---

### Phase 2: Baseline Validation (Still No Code Changes)

1. **Select correct model:**
   - Manually choose GPT-5.3-Codex or GPT-5.4 (400K context)
   - Disable Auto mode
   - Confirm selection to user

2. **Upload context documents:**
   - All flowcharts
   - HANDOVER.md and SKILL_CHECKLIST.md
   - Key source files (agent_engine.py, test files)

3. **Run baseline tests:**
   ```powershell
   # Unit tests:
   .venv\Scripts\python.exe Tests\_timeout_runner.py Tests/
   
   # E2E test:
   .\run_auto_agoda_test.ps1 -NoScrape -PreviewBeforeSubmit
   ```

4. **Report results with evidence:**
   - Paste test output
   - Quote exit messages
   - Identify log file location

5. **Inspect latest logs/artifacts:**
   - `Logs/run_*.log`
   - `Tests/Samples/auto_agoda_summary.txt`
   - `Tests/Samples/auto_agoda_chat_transcript.txt`

6. **Wait for user confirmation** that baseline is healthy before Phase 3.

---

### Phase 3: Implement Deltas (Only After Phases 1-2 Complete)

1. **Work through Section 9 (Next Steps) in order**
2. **Respect gates** - don't skip steps
3. **Show test evidence** after each change
4. **Update docs alongside code** (not after)

---

## 12. How To Work With Me (User Expectations)

### When you propose changes:

1. **Explain WHY** (what problem does this solve?)
2. **Show the DIFF** (what exactly changes?)
3. **Identify RISKS** (what could this break?)
4. **Prove it WORKS** (show test output, not claims)

### When tests fail:

1. **Quote the exact error message** (don't paraphrase)
2. **Identify the failing line/file** (be specific)
3. **Explain root cause** (not guesses - use logs/evidence)
4. **Propose ONE targeted fix** (not "let's try X, Y, and Z")
5. **Re-run and show green** (close the loop)

### When you're uncertain:

1. **SAY SO explicitly** ("I'm not certain about X because...")
2. **List what you'd need to know** (which log? which test?)
3. **Propose how to find out** (don't guess, verify)
4. **Wait for my input** (don't assume)

### When working with large context:

1. **Verify documents are still in context** mid-conversation
2. **Quote from flowcharts/docs** to prove you can still see them
3. **Cross-reference multiple files** (scan vs apply selectors, code vs flowchart)
4. **If context feels dropped**, ask to re-upload key documents

### What I will NOT accept:

- ❌ "Should work now" without proof
- ❌ "Probably caused by X" without evidence
- ❌ "Let's try Y" without explaining why
- ❌ Code changes before baseline validation
- ❌ Claims of test success without pasted output
- ❌ Modifications to one code path when both need updating
- ❌ Flowchart updates AFTER code changes

---

## 13. Notes for Reliability

- Treat preview/browser snapshot as source of truth when scan confidence is low.
- Keep all user-facing claims grounded in test output or log lines.
- Prefer small, test-backed edits over broad refactors during active debugging.
- With 400K context, you can and should see: flowcharts, code, tests, and logs simultaneously.
- If you can't quote a flowchart or doc mid-conversation, it was evicted - re-upload immediately.
- False confirmations are often context amnesia, not dishonesty - verify docs are in context before answering.

---

## 14. Model Selection Validation Checklist

**Before starting any work session, verify:**

```
□ Model selected: GPT-5.3-Codex or GPT-5.4 (400K context minimum)
□ Auto mode: DISABLED
□ Documents uploaded in first message:
  □ HANDOVER.md
  □ SKILL_CHECKLIST.md
  □ FLOWCHART_STATE_MACHINE.md
  □ FLOWCHART_SKIPPED_MAINTENANCE.md
  □ FLOWCHART_USER_DB_UPDATE.md
  □ agent_engine.py (or key sections)
  
□ Context verification test passed:
  - Ask mid-conversation: "Quote the 5 methodology rules from HANDOVER.md"
  - If you can quote them → context is holding
  - If you can't → context evicted, re-upload and restart

□ Baseline validation complete (Section 9, Step 1):
  □ Unit tests passed
  □ E2E test completed successfully
  □ Evidence provided to user
```

**If any checkbox is unchecked, STOP and complete it before proceeding with work.**

