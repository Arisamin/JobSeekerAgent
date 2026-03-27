# Skill Checklist (Mandatory per Code-Change Iteration)

This checklist is the required development methodology for this repository.

## Core Rule

- Do not hallucinate in answers, analysis, or implementation details.

## Iteration Gate (run before and during every change)

0. Maintain and review this checklist before every code-change iteration.
1. Every new logic must have a unit test guarding it.
2. After successful compilation and before any manual test, run unit tests.
3. Unit tests must run with a hard timeout guard (use `Tests/_timeout_runner.py` or equivalent).
4. If timeout is reached, capture diagnostics (faulthandler/trace logs), identify the blocking path, patch, and re-run before manual testing.
5. Every logic change must be reflected in the appropriate flowchart(s), and flowcharts must be reviewed for alignment.

## Practical Sequence (per iteration)

1. Define the logic change scope.
2. Add or update unit test(s) first (or alongside the change).
3. Implement the logic change.
4. Compile / syntax-check.
5. Run unit tests via timeout wrapper (default: `Tests/_timeout_runner.py Tests/`).
6. Run manual test only after tests pass.
7. Update relevant flowchart markdown file(s):
   - `FLOWCHART_STATE_MACHINE.md`
   - `FLOWCHART_SKIPPED_MAINTENANCE.md`
   - `FLOWCHART_USER_DB_UPDATE.md`
8. Re-check checklist before starting the next iteration.

## Iteration Sign-off (copy into PR/commit notes)

- [ ] Checklist reviewed before change
- [ ] Unit test added/updated for new logic
- [ ] Compile/syntax check passed
- [ ] Unit tests passed before manual test
- [ ] Unit tests executed with timeout guard
- [ ] Relevant flowchart(s) updated and reviewed
- [ ] No hallucinated claims in summary/output
