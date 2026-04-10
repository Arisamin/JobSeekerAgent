# Easy Apply Automation Roadmap

Goal: add an autonomous mode that applies automatically only to LinkedIn Easy Apply jobs when all required answers are known and confidence is high.

## Product principle

- Easy Apply is the primary path.
- External apply remains secondary/fallback.
- Never auto-submit when confidence is below threshold.

## Proposed new mode

Mode name:
- `--easy-apply-auto-mode guarded`

Behavior:
1. Scan job list and prioritize Easy Apply entries.
2. For each Easy Apply job, run form scan.
3. Build required field list for all wizard steps (including rescan expansion).
4. Compute answer coverage.
5. Auto-submit only if eligibility checks pass.
6. Otherwise route to manual review queue with explicit missing fields.

## Eligibility checks before auto-submit

A job is eligible only if all are true:
- Apply mode is Easy Apply.
- Required fields are fully covered by profile/custom answers.
- CV path exists and is readable.
- If cover letter upload is required, cover letter path exists.
- No unknown required custom question remains unanswered.
- No scan-unverified warning for required fields.
- No anti-automation blocker detected (captcha/challenge/login gate).

## Confidence score and policy

Compute:
- coverage = answered_required / total_required
- confidence = weighted score from:
  - coverage,
  - label quality,
  - option match certainty,
  - scan stability across rescan.

Policy:
- auto-submit only if coverage = 1.0 and confidence >= 0.90
- preview-only if 0.75 <= confidence < 0.90
- manual queue if confidence < 0.75

## Required implementation steps

## Step 1: Add eligibility evaluator

Add helper:
- `_evaluate_easy_apply_auto_eligibility(job_url, answers, scanned_fields) -> dict`

Output fields:
- `eligible` (bool)
- `coverage` (float)
- `confidence` (float)
- `missing_required` (list)
- `blocking_reasons` (list)

## Step 2: Add auto mode orchestrator

Add command path:
- `AUTO_APPLY_EASY` (or CLI-only headless batch mode)

Flow:
1. collect candidate jobs
2. filter/sort Easy Apply first
3. evaluate eligibility
4. submit eligible jobs
5. report per-job result to Telegram/log/report

## Step 3: Add dry-run mode first

Before enabling true submit, ship:
- `--easy-apply-auto-mode dry-run`

Dry-run output should include:
- eligible count
- blocked count
- per-job reason for ineligibility
- predicted action (submit / preview / manual)

## Step 4: Add guarded submit mode

Then enable:
- `--easy-apply-auto-mode guarded`

Guardrails:
- max auto submits per run (e.g., 3)
- kill-switch env var (e.g., `AGENT_DISABLE_AUTO_SUBMIT=1`)
- stop on first unexpected modal/navigation error

## Step 5: Add report visibility

In run report add columns:
- `Auto Eligibility`
- `Coverage`
- `Confidence`
- `Auto Action`
- `Block Reason`

## Test plan (must exist before enabling guarded mode)

1. Unit tests:
- eligibility evaluator scoring
- missing required field detection
- confidence threshold branching

2. Integration tests:
- simulated Easy Apply full coverage -> auto submit path
- partial coverage -> manual queue path
- scan-unverified -> blocked path

3. Safety tests:
- kill-switch prevents submit
- max-submit limit enforced
- DB status transitions only on confirmed success

## Recommended rollout

1. Week 1: implement evaluator + dry-run reports only.
2. Week 2: run dry-run on real sessions and tune thresholds.
3. Week 3: enable guarded mode for a very small subset (max 1-2 submits).
4. Week 4: increase submit cap only after stable logs and zero false submits.
