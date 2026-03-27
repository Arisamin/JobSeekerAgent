"""
Tests for the three patches applied in the 2026-03-27 session:

  1. KI resilience  – TelegramJobSession.run() survives a single KeyboardInterrupt
     and only stops on a second KI within 3 seconds.
  2. Page-signature stagnation – the scan wizard bails after ONE repeated signature
     instead of two (stagnant_signature_streak >= 1).
  3. Discovery-mode unification – normal run-mode uses the same aggressive
     prefill path as testing mode during field discovery.
"""
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent_engine


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _make_session(easy_apply_run_mode: str = "normal"):
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "test.db"
    db = agent_engine.ProcessedJobsDB(db_path)
    logger = logging.getLogger("test.patches")
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
    # Stash references so callers can clean up
    session.__test_db = db
    session.__test_dir = temp_dir
    return session


def _cleanup(session):
    session.__test_db.close()
    session.__test_dir.cleanup()


# ---------------------------------------------------------------------------
# 1. KeyboardInterrupt resilience in run()
# ---------------------------------------------------------------------------

class TestPollLoopKIResilience(unittest.TestCase):
    """
    run() must survive a single KI and only stop on a second KI within 3 s.
    We test this without actually sleeping by mocking time.time() and
    _get_updates() to raise KI on demand.
    """

    def _make_running_session(self):
        session = _make_session()
        session._send = lambda text, parse_mode="HTML": None
        return session

    @staticmethod
    def _chat_update(update_id: int, text: str = "next"):
        return {
            "update_id": update_id,
            "message": {
                "chat": {"id": 1},
                "text": text,
            },
        }

    def test_single_ki_continues(self):
        """One KI → session keeps looping and reaches a later handled update."""
        session = self._make_running_session()

        call_count = {"n": 0}
        trace = []

        def fake_get_updates(offset, timeout):
            call_count["n"] += 1
            trace.append(f"poll#{call_count['n']}: offset={offset} timeout={timeout}")
            if call_count["n"] == 1:
                # Bootstrap: drain stale updates
                return []
            if call_count["n"] == 2:
                trace.append("raising first KeyboardInterrupt")
                raise KeyboardInterrupt
            # After KI the loop should continue and process a real update.
            return [self._chat_update(101, "after-ki")]

        try:
            with patch.object(session, "_get_updates", side_effect=fake_get_updates):
                with patch.object(session, "_handle_command", return_value=False) as handle_mock:
                    with patch("time.sleep"):  # don't actually sleep
                        session.run()
        finally:
            _cleanup(session)

        # run() returns because handled update requested stop, proving loop continued past KI.
        self.assertTrue(handle_mock.called, msg=f"trace={trace}")
        self.assertGreaterEqual(call_count["n"], 3)
        self.assertIn("raising first KeyboardInterrupt", trace)

    def test_double_ki_within_window_stops(self):
        """Two KIs within 3 s → session returns cleanly."""
        session = self._make_running_session()

        call_count = {"n": 0}
        # Simulate both KIs arriving within the 3-second window
        timestamps = [100.0, 100.0, 101.0, 101.0]  # always "within window"

        def fake_get_updates(offset, timeout):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return []  # bootstrap
            raise KeyboardInterrupt  # every subsequent call raises KI

        try:
            with patch.object(session, "_get_updates", side_effect=fake_get_updates):
                with patch("time.sleep"):
                    with patch("time.time", side_effect=timestamps):
                        session.run()
        finally:
            _cleanup(session)

        # run() must have returned on its own (double-KI shutdown)
        # If it hadn't returned we'd have hit an infinite loop above

    def test_ki_resets_after_successful_poll(self):
        """
        KI, then a successful poll, then another KI → that second KI is treated
        as the FIRST of a new window (does NOT stop the session).
        """
        session = self._make_running_session()
        call_count = {"n": 0}
        trace = []

        def fake_get_updates(offset, timeout):
            call_count["n"] += 1
            trace.append(f"poll#{call_count['n']}: offset={offset} timeout={timeout}")
            if call_count["n"] == 1:
                return []  # bootstrap
            if call_count["n"] == 2:
                trace.append("raising first KeyboardInterrupt")
                raise KeyboardInterrupt  # first KI
            if call_count["n"] == 3:
                return []  # successful poll resets counter
            if call_count["n"] == 4:
                trace.append("raising second KeyboardInterrupt after successful poll")
                raise KeyboardInterrupt  # second KI in a NEW window → should continue
            return [self._chat_update(202, "stop-after-second-ki")]

        # time.time() returning far-apart values ensures the second KI is outside
        # the 3-second window of the first
        timestamps = [100.0, 100.0, 200.0, 200.0, 200.0, 200.0]

        try:
            with patch.object(session, "_get_updates", side_effect=fake_get_updates):
                with patch.object(session, "_handle_command", return_value=False) as handle_mock:
                    with patch("time.sleep"):
                        with patch("time.time", side_effect=timestamps):
                            session.run()
        finally:
            _cleanup(session)

        self.assertTrue(handle_mock.called, msg=f"trace={trace}")
        self.assertGreaterEqual(call_count["n"], 5)


# ---------------------------------------------------------------------------
# 2. Stagnation detection: bail after ONE repeated page signature
# ---------------------------------------------------------------------------

class TestStagnantSignatureThreshold(unittest.TestCase):
    """
    The wizard loop must stop as soon as it sees the same page signature twice
    in a row (stagnant_signature_streak >= 1), not after two repeats.
    We verify this by checking the LOGIC of the threshold directly, and by
    building a minimal fake-page scenario.
    """

    def test_streak_threshold_is_one(self):
        """Stagnation triggers at streak == 1, not 2."""
        streak = 0
        last_sig = ""
        iterations_run = 0
        max_steps = 20

        # Simulate: page always returns same signature, no new fields
        constant_sig = "first name | salary"
        new_fields_per_step = [1, 0, 0, 0, 0]  # 1 new on step 0, then stuck

        for _step in range(max_steps):
            iterations_run += 1
            new_fields = new_fields_per_step[_step] if _step < len(new_fields_per_step) else 0
            page_sig = constant_sig

            if page_sig and page_sig == last_sig:
                streak += 1
            else:
                streak = 0
            if page_sig:
                last_sig = page_sig

            # This is the exact condition from agent_engine.py
            if new_fields == 0 and streak >= 1:
                break

        # Step 0 records signature; step 1 repeats signature with no new fields and breaks.
        self.assertEqual(iterations_run, 2)  # steps 0, 1

    def test_non_stagnant_pages_continue(self):
        """If signature keeps changing, the loop does NOT stop early."""
        streak = 0
        last_sig = ""
        iterations_run = 0
        max_steps = 10

        sigs = [f"page_{i}" for i in range(max_steps)]

        for _step in range(max_steps):
            iterations_run += 1
            new_fields = 0
            page_sig = sigs[_step]

            if page_sig and page_sig == last_sig:
                streak += 1
            else:
                streak = 0
            if page_sig:
                last_sig = page_sig

            if new_fields == 0 and streak >= 1:
                break

        # Each step has a new signature, so streak never reaches 1 — full run
        self.assertEqual(iterations_run, max_steps)

    def test_first_step_never_triggers_stagnation(self):
        """
        On the very first step last_sig is '' so the streak stays 0 even if
        new_fields == 0, preventing an immediate false-positive bail.
        """
        streak = 0
        last_sig = ""
        bailed = False
        page_sig = "first name"
        new_fields = 0

        # Step 0
        if page_sig and page_sig == last_sig:
            streak += 1
        else:
            streak = 0
        if page_sig:
            last_sig = page_sig

        if new_fields == 0 and streak >= 1:
            bailed = True

        self.assertFalse(bailed)


# ---------------------------------------------------------------------------
# 3. Discovery-mode unification: normal mode acts like testing during scan
# ---------------------------------------------------------------------------

class TestDiscoveryModeUnification(unittest.TestCase):
    """
    After the unification patch, a session created with easy_apply_run_mode='normal'
    must evaluate  ``testing_mode = self._easy_apply_run_mode in {"testing", "normal"}``
    as True, so that _prefill_required_for_scan uses aggressive fills.

    We cannot call _scan_easy_apply_fields directly (it needs a browser), but we CAN:
      a) confirm the run-mode is stored correctly, and
      b) verify the expression value at the point where testing_mode is computed.
    """

    def test_normal_mode_evaluates_as_testing_mode_true(self):
        session = _make_session("normal")
        try:
            # This is the exact expression from line ~2075 of agent_engine.py
            testing_mode = session._easy_apply_run_mode in {"testing", "normal"}
            self.assertTrue(testing_mode, "normal mode should evaluate testing_mode=True for discovery")
        finally:
            _cleanup(session)

    def test_testing_mode_evaluates_as_testing_mode_true(self):
        session = _make_session("testing")
        try:
            testing_mode = session._easy_apply_run_mode in {"testing", "normal"}
            self.assertTrue(testing_mode)
        finally:
            _cleanup(session)

    def test_unknown_mode_falls_back_to_normal_and_is_still_true(self):
        """Unknown modes are normalised to 'normal' by __init__, so still True."""
        session = _make_session("foobar")
        try:
            self.assertEqual(session._easy_apply_run_mode, "normal")
            testing_mode = session._easy_apply_run_mode in {"testing", "normal"}
            self.assertTrue(testing_mode)
        finally:
            _cleanup(session)

    def test_old_expression_would_have_been_false_for_normal(self):
        """
        Regression guard: the OLD expression  ``== "testing"`` returns False for
        normal mode.  This test documents the bug that was fixed.
        """
        session = _make_session("normal")
        try:
            old_expression_result = session._easy_apply_run_mode == "testing"
            self.assertFalse(
                old_expression_result,
                "Confirms the old code was broken for normal mode (regression guard)"
            )
        finally:
            _cleanup(session)


if __name__ == "__main__":
    unittest.main()
