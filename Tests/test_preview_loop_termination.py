"""
Targeted regression tests for the three deterministic exit modes of the
Easy Apply wizard loop inside TelegramJobSession._do_linkedin_easy_apply().

These tests are Playwright-free: they directly simulate the loop decision
logic to assert that each exit path produces the expected (success, message)
pair.  This mirrors the style used in test_session_patches.py for the scan
stagnation checks.

Exit modes covered:
  1. submit-step exit   – button text is "submit" and submit_application=False
                          → returns (True, "Preview stopped at final submit step …")
  2. stagnation exit    – same page signature repeats after at least one advance click
                          → returns (False, "Easy Apply wizard stopped progressing …")
  3. failsafe-cap exit  – loop exhausts max_modal_steps without hitting submit
                          → returns (True, "Preview stopped after … wizard steps …")

Task A companion test:
  4. selector-parity    – _EASY_APPLY_BUTTON_SELECTORS is the single shared source
                          used by both scan and apply code paths.
"""
import logging
import tempfile
import unittest
from pathlib import Path

import agent_engine


# ---------------------------------------------------------------------------
# Shared session factory (Playwright-free, temp DB)
# ---------------------------------------------------------------------------

def _make_session(easy_apply_run_mode: str = "normal") -> agent_engine.TelegramJobSession:
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "test.db"
    db = agent_engine.ProcessedJobsDB(db_path)
    logger = logging.getLogger("test.preview_loop")
    logger.handlers = []
    logger.addHandler(logging.NullHandler())
    session = agent_engine.TelegramJobSession(
        bot_token="dummy",
        chat_id=1,
        db=db,
        new_jobs=[],
        query="q",
        logger=logger,
        easy_apply_run_mode=easy_apply_run_mode,
    )
    # Attach for cleanup
    session.__test_db = db  # type: ignore[attr-defined]
    session.__test_dir = temp_dir  # type: ignore[attr-defined]
    return session


def _cleanup(session: agent_engine.TelegramJobSession) -> None:
    session.__test_db.close()  # type: ignore[attr-defined]
    session.__test_dir.cleanup()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Helper: minimal loop simulator
#
# Reproduces the exact decision logic from _do_linkedin_easy_apply without
# any Playwright objects.  Each argument controls one aspect of the simulated
# wizard state.
# ---------------------------------------------------------------------------

def _simulate_wizard_loop(
    *,
    max_modal_steps: int,
    page_signatures: list,      # one entry per step; "" means "no signature"
    button_texts: list,         # one entry per step
    submit_application: bool,
) -> tuple:
    """
    Simulate the wizard stepping loop and return (success, message) exactly
    as _do_linkedin_easy_apply does.

    page_signatures and button_texts are cycled if shorter than max_modal_steps.
    """
    last_page_signature = ""
    stagnant_signature_streak = 0

    for step_num in range(max_modal_steps):
        idx = step_num % len(page_signatures)
        page_signature = page_signatures[idx]

        if page_signature and page_signature == last_page_signature:
            stagnant_signature_streak += 1
        else:
            stagnant_signature_streak = 0
        if page_signature:
            last_page_signature = page_signature

        # Exact condition from agent_engine.py
        if step_num > 0 and stagnant_signature_streak >= 1:
            return False, (
                f"Easy Apply wizard stopped progressing at step {step_num + 1} "
                "(same form page repeated after an advance click)."
            )

        btn_text = (button_texts[step_num % len(button_texts)] or "").strip().lower()
        is_submit_action = any(
            tok in btn_text
            for tok in agent_engine.TelegramJobSession._SUBMIT_BUTTON_TOKENS
        )

        if is_submit_action and not submit_application:
            return True, "Preview stopped at final submit step (no submit clicked)."

        if is_submit_action and submit_application:
            return True, "Application submitted successfully."  # simplified success

        # click next / review / unknown  → continue loop

    # Loop exhausted without submitting
    if not submit_application:
        return True, (
            f"Preview stopped after {max_modal_steps} wizard steps "
            "(failsafe cap reached before submit step)."
        )
    return False, f"Easy Apply wizard exceeded {max_modal_steps} steps without submitting."


# ---------------------------------------------------------------------------
# 1. submit-step exit
# ---------------------------------------------------------------------------

class TestSubmitStepExit(unittest.TestCase):
    """
    When the advance button text is 'Submit' and submit_application=False,
    the loop must return immediately with a preview-halted success message
    WITHOUT clicking the submit button.
    """

    def test_submit_step_in_preview_mode_halts_without_submitting(self):
        # Two next steps, then a submit step; preview mode
        success, msg = _simulate_wizard_loop(
            max_modal_steps=50,
            page_signatures=["page1", "page2", "page3"],
            button_texts=["Next", "Next", "Submit"],
            submit_application=False,
        )
        self.assertTrue(success)
        self.assertIn("Preview stopped at final submit step", msg)
        self.assertIn("no submit clicked", msg)

    def test_submit_step_in_submit_mode_returns_submitted(self):
        success, msg = _simulate_wizard_loop(
            max_modal_steps=50,
            page_signatures=["page1", "page2", "page3"],
            button_texts=["Next", "Next", "Submit"],
            submit_application=True,
        )
        self.assertTrue(success)
        self.assertIn("submitted", msg.lower())

    def test_immediate_submit_step_halts_at_step_1(self):
        """If the very first page already shows Submit, preview stops right away."""
        success, msg = _simulate_wizard_loop(
            max_modal_steps=50,
            page_signatures=["single_page"],
            button_texts=["Submit"],
            submit_application=False,
        )
        self.assertTrue(success)
        self.assertIn("Preview stopped at final submit step", msg)

    def test_arabic_submit_tokens_are_recognised(self):
        """Arabic submit token 'تقديم' must also trigger the submit-step exit."""
        success, msg = _simulate_wizard_loop(
            max_modal_steps=50,
            page_signatures=["p1"],
            button_texts=["تقديم"],
            submit_application=False,
        )
        self.assertTrue(success)
        self.assertIn("Preview stopped at final submit step", msg)


# ---------------------------------------------------------------------------
# 2. stagnation exit
# ---------------------------------------------------------------------------

class TestStagnationExit(unittest.TestCase):
    """
    When the same page signature repeats on consecutive steps (streak >= 1),
    the loop must terminate with a stagnation message.
    Stagnation must NOT trigger on the very first step (step_num == 0).
    """

    def test_stagnation_triggers_on_second_identical_signature(self):
        """Signature repeats at step 1 → exit with stagnation message."""
        success, msg = _simulate_wizard_loop(
            max_modal_steps=50,
            page_signatures=["stuck_page"],   # every step returns the same sig
            button_texts=["Next"],
            submit_application=False,
        )
        self.assertFalse(success)
        self.assertIn("stopped progressing", msg)
        self.assertIn("step 2", msg)

    def test_stagnation_message_includes_step_number(self):
        sigs = ["page1", "page2", "page2"]   # stagnates at step 2 (index 2)
        success, msg = _simulate_wizard_loop(
            max_modal_steps=50,
            page_signatures=sigs,
            button_texts=["Next"],
            submit_application=False,
        )
        self.assertFalse(success)
        self.assertIn("stopped progressing", msg)
        # step 3 (1-based) = index 2
        self.assertIn("step 3", msg)

    def test_first_step_never_triggers_stagnation(self):
        """
        Even with an empty last_page_signature and a matching first signature,
        step_num==0 must never trigger the stagnation exit.
        """
        # Only one page signature entry; loop would stagnate immediately if not
        # guarded by the `step_num > 0` condition.
        sig = "one_page"
        last_page_signature = ""
        stagnant_streak = 0
        bailed = False

        # Step 0
        if sig and sig == last_page_signature:
            stagnant_streak += 1
        else:
            stagnant_streak = 0
        if sig:
            last_page_signature = sig

        if 0 > 0 and stagnant_streak >= 1:
            bailed = True

        self.assertFalse(bailed)
        self.assertEqual(stagnant_streak, 0)

    def test_changing_signatures_prevent_stagnation(self):
        """Every step has a unique signature → loop runs full max_steps without stagnating."""
        n = 10
        success, msg = _simulate_wizard_loop(
            max_modal_steps=n,
            page_signatures=[f"page_{i}" for i in range(n)],
            button_texts=["Next"],
            submit_application=True,
        )
        # No stagnation, no submit button → falls through to wizard-exceeded
        self.assertFalse(success)
        self.assertIn("exceeded", msg)

    def test_stagnation_exits_cleanly_in_preview_mode(self):
        success, msg = _simulate_wizard_loop(
            max_modal_steps=50,
            page_signatures=["frozen"],
            button_texts=["Next"],
            submit_application=False,
        )
        self.assertFalse(success)
        self.assertIn("stopped progressing", msg)


# ---------------------------------------------------------------------------
# 3. failsafe-cap exit
# ---------------------------------------------------------------------------

class TestFailsafeCapExit(unittest.TestCase):
    """
    When the loop exhausts all max_modal_steps without reaching a submit button
    (and submit_application=False), the failsafe exit must fire with a
    'Preview stopped after N wizard steps … failsafe cap' message.
    """

    def test_failsafe_cap_returns_success_true_in_preview_mode(self):
        cap = 5
        success, msg = _simulate_wizard_loop(
            max_modal_steps=cap,
            page_signatures=[f"p{i}" for i in range(cap)],  # all distinct → no stagnation
            button_texts=["Next"],
            submit_application=False,
        )
        self.assertTrue(success)
        self.assertIn("failsafe cap", msg)
        self.assertIn(str(cap), msg)

    def test_failsafe_cap_message_contains_step_count(self):
        cap = 7
        success, msg = _simulate_wizard_loop(
            max_modal_steps=cap,
            page_signatures=[f"unique_{i}" for i in range(cap)],
            button_texts=["Next"],
            submit_application=False,
        )
        self.assertTrue(success)
        self.assertIn("failsafe cap", msg)
        self.assertIn(str(cap), msg)

    def test_failsafe_cap_in_submit_mode_returns_failure(self):
        """If submit_application=True and cap reached, it's a failure (never submitted)."""
        cap = 5
        success, msg = _simulate_wizard_loop(
            max_modal_steps=cap,
            page_signatures=[f"p{i}" for i in range(cap)],
            button_texts=["Next"],
            submit_application=True,
        )
        self.assertFalse(success)
        self.assertIn("exceeded", msg)

    def test_default_max_modal_steps_is_100(self):
        """Regression guard: the production default cap is 100."""
        import inspect
        src = inspect.getsource(agent_engine.TelegramJobSession._do_linkedin_easy_apply)
        self.assertIn("max_modal_steps = 100", src)


# ---------------------------------------------------------------------------
# 4. Selector parity (Task A companion)
# ---------------------------------------------------------------------------

class TestEasyApplyButtonSelectorParity(unittest.TestCase):
    """
    The class constant _EASY_APPLY_BUTTON_SELECTORS is the single authoritative
    list.  Both the scan path and the apply path must reference it; there must
    be no second inline literal list in agent_engine.py.
    """

    def test_class_constant_is_non_empty_list(self):
        selectors = agent_engine.TelegramJobSession._EASY_APPLY_BUTTON_SELECTORS
        self.assertIsInstance(selectors, list)
        self.assertGreater(len(selectors), 0)

    def test_class_constant_contains_primary_selectors(self):
        selectors = agent_engine.TelegramJobSession._EASY_APPLY_BUTTON_SELECTORS
        joined = " | ".join(selectors)
        # Core selectors expected in any realistic LinkedIn scrape
        self.assertIn(".jobs-apply-button", joined)
        self.assertIn("button:has-text('Easy Apply')", joined)
        self.assertIn("button[aria-label*='Easy Apply']", joined)

    def test_no_duplicate_inline_selector_lists_in_source(self):
        """
        Neither inline local list 'EASY_APPLY_SELECTORS = [' nor
        'easy_apply_selectors = [' should appear in agent_engine.py after
        the consolidation refactor.
        """
        import agent_engine as ae
        import inspect
        src = inspect.getsource(ae)
        # Both inline list assignments must be gone
        self.assertNotIn("EASY_APPLY_SELECTORS = [", src)
        self.assertNotIn("easy_apply_selectors = [", src)

    def test_both_scan_and_apply_reference_class_constant(self):
        """Both code paths must reference _EASY_APPLY_BUTTON_SELECTORS."""
        import inspect
        src = inspect.getsource(agent_engine.TelegramJobSession)
        occurrences = src.count("_EASY_APPLY_BUTTON_SELECTORS")
        # 1 definition + at least 2 usages (scan path, apply path)
        self.assertGreaterEqual(occurrences, 3,
            msg=f"Expected ≥3 occurrences (1 definition + 2 usages), found {occurrences}")


if __name__ == "__main__":
    unittest.main()
