import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent_engine


class TestReportModeParsing(unittest.TestCase):
    def test_parse_args_accepts_report_mode(self):
        with patch.object(sys, "argv", ["agent_engine.py", "--report-mode"]):
            args = agent_engine.parse_args()
        self.assertTrue(args.report_mode)

    def test_parse_args_rejects_legacy_easy_mode(self):
        with patch.object(sys, "argv", ["agent_engine.py", "--easy-mode"]):
            with self.assertRaises(SystemExit):
                agent_engine.parse_args()


class TestJobMetadataPersistence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_processed_jobs.db"
        self.db = agent_engine.ProcessedJobsDB(self.db_path)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_add_persists_apply_mode_and_recommendation_defaults(self):
        job = agent_engine.JobRecord(
            job_key="k1",
            title="Backend Engineer",
            company="Acme",
            location="Tel Aviv",
            url="https://www.linkedin.com/jobs/view/1/",
            description="desc",
            apply_mode="External Apply",
        )
        self.db.add(job)

        jobs = self.db.get_all_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["apply_mode"], "External Apply")
        self.assertEqual(jobs[0]["recommendation"], "Unknown")

    def test_upsert_metadata_updates_existing_row(self):
        job = agent_engine.JobRecord(
            job_key="k2",
            title="Platform Engineer",
            company="Beta",
            location="Jerusalem",
            url="https://www.linkedin.com/jobs/view/2/",
            description="desc",
            apply_mode="Unknown",
        )
        self.db.add(job)
        self.db.upsert_job_metadata(job_key="k2", recommendation="STRONG MATCH", apply_mode="Easy Apply")

        jobs = self.db.get_all_jobs()
        self.assertEqual(jobs[0]["recommendation"], "STRONG MATCH")
        self.assertEqual(jobs[0]["apply_mode"], "Easy Apply")


class TestTelegramApplyModeDisplay(unittest.TestCase):
    def _make_session(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)

        db_path = Path(temp_dir.name) / "test_processed_jobs.db"
        db = agent_engine.ProcessedJobsDB(db_path)
        self.addCleanup(db.close)

        logger = logging.getLogger("test.telegram.apply.mode")
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

    def test_job_card_includes_easy_apply_mode_icon_and_text(self):
        session = self._make_session()
        text = session._job_card_text(
            {
                "id": 1,
                "title": "Backend Engineer",
                "company": "Acme",
                "url": "https://www.linkedin.com/jobs/view/1/",
                "status": "Discovered",
                "apply_mode": "Easy Apply",
            },
            index=1,
            total=3,
        )
        self.assertIn("Apply Mode:", text)
        self.assertIn("Easy Apply", text)
        self.assertIn("⚡", text)

    def test_db_card_includes_external_apply_mode_icon_and_text(self):
        session = self._make_session()
        text = session._db_card_text(
            {
                "id": 2,
                "title": "Platform Engineer",
                "company": "Beta",
                "url": "https://www.linkedin.com/jobs/view/2/",
                "status": "Discovered",
                "apply_mode": "External Apply",
            },
            index=1,
            total=1,
        )
        self.assertIn("Apply Mode:", text)
        self.assertIn("External Apply", text)
        self.assertIn("🌐", text)


class TestReportHtmlSectionsMetadata(unittest.TestCase):
    def test_write_html_report_shows_apply_mode_and_recommendation_in_sections(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        base = Path(temp_dir.name)

        db = agent_engine.ProcessedJobsDB(base / "processed_jobs.db")
        self.addCleanup(db.close)

        job = agent_engine.JobRecord(
            job_key="k3",
            title="Data Engineer",
            company="Gamma",
            location="Haifa",
            url="https://www.linkedin.com/jobs/view/3/",
            description="desc",
            apply_mode="External Apply",
        )
        db.add(job)
        db.upsert_job_metadata(job_key="k3", recommendation="REVIEW MANUALLY", apply_mode="External Apply")

        agent = agent_engine.LinkedInJobAgent(
            base_dir=base,
            max_jobs=5,
            headless=True,
            query="test query",
            user_data_dir=None,
            max_run_seconds=60,
            max_extract_seconds=30,
            per_card_seconds=10,
        )
        self.addCleanup(agent.db.close)
        for handler in list(agent.logger.handlers):
            self.addCleanup(handler.close)

        agent.report_entries = [
            {
                "title": "Data Engineer",
                "company": "Gamma",
                "location": "Haifa",
                "url": "https://www.linkedin.com/jobs/view/3/",
                "recommendation": "REVIEW MANUALLY",
                "apply_mode": "External Apply",
                "rows": [("Role", "Good", "Yes")],
            }
        ]

        report_path = agent._write_html_report()
        html_text = report_path.read_text(encoding="utf-8")

        self.assertIn("A) Current run results", html_text)
        self.assertIn("<th>Apply Mode</th>", html_text)
        self.assertIn("<th>Recommendation</th>", html_text)
        self.assertIn("Apply Mode", html_text)
        self.assertIn("External Apply", html_text)
        self.assertIn("B) Jobs in DB", html_text)
        self.assertIn("Recommendation", html_text)


if __name__ == "__main__":
    unittest.main()
