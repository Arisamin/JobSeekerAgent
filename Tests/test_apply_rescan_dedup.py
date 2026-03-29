import logging
import tempfile
import unittest
from pathlib import Path

import agent_engine


class TestApplyRescanDedup(unittest.TestCase):
    def _make_session(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)

        db_path = Path(temp_dir.name) / "test_processed_jobs.db"
        db = agent_engine.ProcessedJobsDB(db_path)
        self.addCleanup(db.close)

        logger = logging.getLogger("test.apply.rescan.dedup")
        logger.handlers = []
        logger.addHandler(logging.NullHandler())

        return agent_engine.TelegramJobSession(
            bot_token="dummy",
            chat_id=1,
            db=db,
            new_jobs=[],
            query="q",
            logger=logger,
            easy_apply_run_mode="normal",
        )

    def test_canonicalize_apply_label_strips_prefix_and_duplicate_halves(self):
        session = self._make_session()
        raw = (
            "Q17: Are you presently employed by any company within the Booking Holdings group? "
            "Are you presently employed by any company within the Booking Holdings group? مطلوب"
        )
        canonical = session._canonicalize_apply_label(raw)
        self.assertEqual(
            canonical,
            "Are you presently employed by any company within the Booking Holdings group?",
        )

    def test_rescan_dedup_keeps_existing_keys_and_answers(self):
        session = self._make_session()
        session._current_job = {
            "title": "Back End Staff Software Engineer",
            "company": "Agoda",
            "url": "https://www.linkedin.com/jobs/view/4299764895/",
        }

        scanned_initial = [
            (
                "agoda_booking_holdings_group_employment",
                "Are you presently employed by any company within the Booking Holdings group?",
                "radio",
            ),
            (
                "agoda_relationship",
                "Do you as a candidate have a personal relationship with a current Agoda employee?",
                "radio",
            ),
        ]

        session._apply_field_options = {
            "agoda_booking_holdings_group_employment": ["Yes", "No"],
            "agoda_relationship": ["Yes", "No"],
        }
        session._apply_form_fields = session._build_apply_form_fields(scanned_initial)
        session._apply_answers = {
            "agoda_booking_holdings_group_employment": "yes",
            "agoda_relationship": "no",
        }
        session._apply_asked_field_keys = [
            "agoda_booking_holdings_group_employment",
            "agoda_relationship",
        ]

        def fake_rescan(_job_url, seed_answers=None):
            _ = seed_answers
            return [
                (
                    "custom__bookings__a1b2",
                    "Are you presently employed by any company within the Booking Holdings group? "
                    "Are you presently employed by any company within the Booking Holdings group? مطلوب",
                    "radio",
                ),
                (
                    "custom__relationship__c3d4",
                    "Do you as a candidate have a personal relationship with a current Agoda employee? مطلوب",
                    "radio",
                ),
            ]

        session._scan_easy_apply_fields = fake_rescan  # type: ignore[method-assign]

        expanded = session._maybe_expand_apply_fields_via_rescan(session._current_job["url"])

        self.assertFalse(expanded)
        self.assertIn("agoda_booking_holdings_group_employment", session._apply_answers)
        self.assertIn("agoda_relationship", session._apply_answers)
        self.assertNotIn("custom__bookings__a1b2", dict(session._apply_form_fields))

    def test_rescan_replaces_prompt_to_include_latest_options(self):
        session = self._make_session()
        session._current_job = {
            "title": "Back End Staff Software Engineer",
            "company": "Agoda",
            "url": "https://www.linkedin.com/jobs/view/4299764895/",
        }

        scanned_initial = [
            (
                "agoda_booking_holdings_group_employment",
                "Are you presently employed by any company within the Booking Holdings group?",
                "radio",
            ),
        ]
        session._apply_form_fields = session._build_apply_form_fields(scanned_initial)
        # Simulate older prompt without options.
        session._apply_form_fields = [
            (
                "agoda_booking_holdings_group_employment",
                "❓ Are you presently employed by any company within the Booking Holdings group? (type your answer):",
            )
        ]

        def fake_rescan(_job_url, seed_answers=None):
            _ = seed_answers
            return [
                (
                    "custom__bookings__x1",
                    "Are you presently employed by any company within the Booking Holdings group?",
                    "radio",
                ),
            ]

        session._scan_easy_apply_fields = fake_rescan  # type: ignore[method-assign]
        session._apply_answers = {"agoda_booking_holdings_group_employment": "yes"}
        session._send = lambda text, parse_mode="HTML": None

        _ = session._maybe_expand_apply_fields_via_rescan(session._current_job["url"])

        prompts = [prompt for _key, prompt in session._apply_form_fields]
        joined = "\n".join(prompts)
        self.assertIn("Options:", joined)
        self.assertIn("1) Yes", joined)
        self.assertIn("2) No", joined)


if __name__ == "__main__":
    unittest.main()
