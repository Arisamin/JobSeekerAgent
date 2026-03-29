import logging
import tempfile
import unittest
from pathlib import Path

import agent_engine


class TestAgodaFallbackQuestions(unittest.TestCase):
    def _make_session(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)

        db_path = Path(temp_dir.name) / "test_processed_jobs.db"
        db = agent_engine.ProcessedJobsDB(db_path)
        self.addCleanup(db.close)

        logger = logging.getLogger("test.agoda.fallback")
        logger.handlers = []
        logger.addHandler(logging.NullHandler())

        return agent_engine.TelegramJobSession(
            bot_token="dummy",
            chat_id=1,
            db=db,
            new_jobs=[],
            query="q",
            logger=logger,
            easy_apply_run_mode="testing",
        )

    def test_injects_fallback_when_agoda_scan_has_only_fixed_fields(self):
        session = self._make_session()
        fixed_only = [
            ("cv_path", "Resume / CV", "file"),
            ("full_name", "Full name", "text"),
            ("email", "Email", "email"),
        ]

        merged = session._inject_agoda_fallback_fields_if_needed(
            scanned=fixed_only,
            title="Back End Staff Software Engineer",
            company="Agoda",
            job_url="https://www.linkedin.com/jobs/view/4299764895/",
        )

        keys = [k for k, _label, _ftype in merged]
        self.assertIn("agoda_booking_holdings_group_employment", keys)
        self.assertIn("agoda_relationship", keys)
        self.assertIn("relocate_bangkok", keys)

    def test_does_not_inject_when_custom_fields_already_present(self):
        session = self._make_session()
        scanned = [
            ("cv_path", "Resume / CV", "file"),
            ("custom__x__123", "Custom question", "radio"),
        ]

        merged = session._inject_agoda_fallback_fields_if_needed(
            scanned=scanned,
            title="Back End Staff Software Engineer",
            company="Agoda",
            job_url="https://www.linkedin.com/jobs/view/4299764895/",
        )

        self.assertEqual(merged, scanned)


if __name__ == "__main__":
    unittest.main()
