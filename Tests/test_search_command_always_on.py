import logging
import tempfile
import unittest
from pathlib import Path

import agent_engine


def _make_session(new_jobs=None):
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "test.db"
    db = agent_engine.ProcessedJobsDB(db_path)
    logger = logging.getLogger("test.search_command_always_on")
    logger.handlers = []
    logger.addHandler(logging.NullHandler())

    session = agent_engine.TelegramJobSession(
        bot_token="dummy",
        chat_id=1,
        db=db,
        new_jobs=new_jobs or [],
        query="Senior Backend",
        logger=logger,
        easy_apply_run_mode="search",
    )

    session._sent_messages = []
    session._send = lambda text, parse_mode="HTML": session._sent_messages.append(text)
    session._test_db = db
    session._test_dir = temp_dir
    return session


def _cleanup(session):
    session._test_db.close()
    session._test_dir.cleanup()


class TestKillCommandBehavior(unittest.TestCase):
    def test_kill_requires_confirmation_then_stops(self):
        session = _make_session()
        try:
            keep_going = session._handle_command("kill")
            self.assertTrue(keep_going)
            self.assertTrue(session._kill_confirmation_pending)

            keep_going = session._handle_command("kill now")
            self.assertFalse(keep_going)
            self.assertFalse(session._kill_confirmation_pending)

            joined = "\n".join(session._sent_messages)
            self.assertIn("Kill requested", joined)
            self.assertIn("Kill confirmed", joined)
        finally:
            _cleanup(session)

    def test_kill_cancel_keeps_session_alive(self):
        session = _make_session()
        try:
            self.assertTrue(session._handle_command("kill"))
            self.assertTrue(session._kill_confirmation_pending)

            keep_going = session._handle_command("cancel")
            self.assertTrue(keep_going)
            self.assertFalse(session._kill_confirmation_pending)

            joined = "\n".join(session._sent_messages)
            self.assertIn("Kill cancelled", joined)
        finally:
            _cleanup(session)

    def test_done_alias_routes_to_kill_confirmation(self):
        session = _make_session()
        try:
            keep_going = session._handle_command("done")
            self.assertTrue(keep_going)
            self.assertTrue(session._kill_confirmation_pending)
            joined = "\n".join(session._sent_messages)
            self.assertIn("renamed to", joined)
        finally:
            _cleanup(session)


class TestInteractiveSearchWizard(unittest.TestCase):
    def test_search_wizard_collects_params_and_runs(self):
        session = _make_session()
        try:
            called = {"run": 0}

            def _fake_run_search_request():
                called["run"] += 1
                return True

            session._run_search_request = _fake_run_search_request

            self.assertTrue(session._handle_command("search"))
            self.assertEqual(session._state, session.STATE_SEARCH_WIZARD)

            self.assertTrue(session._handle_command("Senior C# Developer Israel"))
            self.assertTrue(session._handle_command("12"))
            self.assertTrue(session._handle_command("easy"))
            self.assertTrue(session._handle_command("no"))
            self.assertTrue(session._handle_command("yes"))
            self.assertTrue(session._handle_command("run"))

            self.assertEqual(called["run"], 1)
            self.assertEqual(session._search_wizard_payload.get("query"), "Senior C# Developer Israel")
            self.assertEqual(session._search_wizard_payload.get("max_jobs"), 12)
            self.assertEqual(session._search_wizard_payload.get("easy_apply_only"), True)
            self.assertEqual(session._search_wizard_payload.get("reset_db"), False)
            self.assertEqual(session._search_wizard_payload.get("headless"), True)
        finally:
            _cleanup(session)

    def test_search_command_while_apply_in_progress_aborts_apply(self):
        session = _make_session()
        try:
            session._apply_in_progress_job_id = 123
            session._state = session.STATE_APPLYING
            self.assertTrue(session._handle_command("search"))
            self.assertIsNone(session._apply_in_progress_job_id)
            self.assertEqual(session._state, session.STATE_SEARCH_WIZARD)
        finally:
            _cleanup(session)
