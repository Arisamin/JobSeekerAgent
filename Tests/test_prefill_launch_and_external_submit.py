import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import agent_engine


def _make_session():
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "test_processed_jobs.db"
    db = agent_engine.ProcessedJobsDB(db_path)

    logger = logging.getLogger("test.prefill.launch")
    logger.handlers = []
    logger.addHandler(logging.NullHandler())

    session = agent_engine.TelegramJobSession(
        bot_token="dummy",
        chat_id=1,
        db=db,
        new_jobs=[],
        query="q",
        logger=logger,
        easy_apply_run_mode="normal",
    )
    session._sent_messages = []
    session._send = lambda text, parse_mode="HTML": session._sent_messages.append(text)

    session._test_db = db
    session._test_dir = temp_dir
    return session


def _cleanup(session):
    session._test_db.close()
    session._test_dir.cleanup()


class TestPrefillLaunchLink(unittest.TestCase):
    def test_register_prefill_launch_creates_tokenized_url(self):
        session = _make_session()
        try:
            with patch.object(session, "_ensure_prefill_launch_server", return_value="http://127.0.0.1:8785"):
                url = session._register_prefill_launch(
                    job_url="https://www.linkedin.com/jobs/view/4366001366/",
                    answers={"full_name": "Abu Gabi"},
                    title="Senior Software Engineer & Tech Lead",
                    company="Mobileye",
                )

            self.assertIsNotNone(url)
            parsed = urlparse(url)
            self.assertEqual(parsed.path, "/launch-prefill")
            token = (parse_qs(parsed.query).get("token") or [""])[0]
            self.assertTrue(token)
            self.assertIn(token, session._prefill_launch_payloads)
            self.assertEqual(session._prefill_launch_payloads[token]["company"], "Mobileye")
        finally:
            _cleanup(session)

    def test_summary_includes_clickable_prefill_link(self):
        session = _make_session()
        try:
            session._current_job = {
                "id": 124,
                "title": "Senior Software Engineer & Tech Lead",
                "company": "Mobileye",
                "url": "https://www.linkedin.com/jobs/view/4366001366/",
            }
            session._apply_form_fields = [("full_name", "Full name")]
            session._apply_field_labels = {"full_name": "Full name"}
            session._apply_answers = {"full_name": "Abu Gabi"}
            session._apply_asked_field_keys = ["full_name"]

            with patch.object(session, "_register_prefill_launch", return_value="http://127.0.0.1:8785/launch-prefill?token=abc"):
                session._show_apply_summary()

            self.assertTrue(session._sent_messages)
            summary = session._sent_messages[-1]
            self.assertIn("Open prefilled browser form", summary)
            self.assertIn("launch-prefill?token=abc", summary)
        finally:
            _cleanup(session)


class TestExternalSubmitFallback(unittest.TestCase):
    def test_submit_external_uses_single_attempt_with_external_prefill_enabled(self):
        session = _make_session()
        try:
            session._current_job = {
                "id": 124,
                "title": "Senior Software Engineer & Tech Lead",
                "company": "Mobileye",
                "url": "https://www.linkedin.com/jobs/view/4366001366/",
            }
            session._apply_answers = {"full_name": "Abu Gabi", "email": "baba.guba@gmail.com"}

            with patch.object(
                session,
                "_do_linkedin_easy_apply",
                return_value=(
                    False,
                    "External application form was prefilled, but automatic submit could not be confirmed. Please review and submit manually on the external page.",
                ),
            ) as apply_mock:
                keep_running = session._cmd_submit_apply()

            self.assertTrue(keep_running)
            self.assertEqual(apply_mock.call_count, 1)
            call_kwargs = apply_mock.call_args.kwargs
            self.assertEqual(call_kwargs["submit_application"], True)
            self.assertEqual(call_kwargs["allow_external_prefill"], True)
            self.assertEqual(call_kwargs["force_headed"], False)

            sent = "\n".join(session._sent_messages)
            self.assertIn("submit was not confirmed", sent.lower())
            self.assertIn("status has <b>not</b> been changed", sent.lower())
        finally:
            _cleanup(session)


class TestApplyAnswerResolution(unittest.TestCase):
    def test_resolve_apply_answer_uses_machine_hints_for_location(self):
        session = _make_session()
        try:
            answer = session._resolve_apply_answer(
                "",
                {
                    "location": "Jerusalem, Israel",
                },
                hints=["candidate_location", "location"],
            )
            self.assertEqual(answer, "Jerusalem, Israel")
        finally:
            _cleanup(session)

    def test_resolve_apply_answer_uses_machine_hints_for_linkedin(self):
        session = _make_session()
        try:
            answer = session._resolve_apply_answer(
                "",
                {
                    "linkedin": "https://www.linkedin.com/in/example",
                },
                hints=["urls[LinkedIn]"],
            )
            self.assertEqual(answer, "https://www.linkedin.com/in/example")
        finally:
            _cleanup(session)


if __name__ == "__main__":
    unittest.main()
