import logging
import os
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

    def test_parse_args_accepts_reset_db(self):
        with patch.object(sys, "argv", ["agent_engine.py", "--reset-db"]):
            args = agent_engine.parse_args()
        self.assertTrue(args.reset_db)


class TestDbResetHelper(unittest.TestCase):
    def test_reset_processed_jobs_db_removes_db_and_sidecars(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        base = Path(temp_dir.name)
        for name in ["processed_jobs.db", "processed_jobs.db-wal", "processed_jobs.db-shm"]:
            (base / name).write_text("x", encoding="utf-8")

        agent_engine.reset_processed_jobs_db(base)

        self.assertFalse((base / "processed_jobs.db").exists())
        self.assertFalse((base / "processed_jobs.db-wal").exists())
        self.assertFalse((base / "processed_jobs.db-shm").exists())


class TestReportActionsServerLatestReport(unittest.TestCase):
    def test_latest_report_prefers_filename_timestamp_over_mtime(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        base = Path(temp_dir.name)
        reports = base / "Reports"
        reports.mkdir(parents=True, exist_ok=True)

        older = reports / "run_report_20260408_113529.html"
        newer = reports / "run_report_20260411_000610.html"
        older.write_text("older", encoding="utf-8")
        newer.write_text("newer", encoding="utf-8")

        # Simulate accidental touch of an older report file.
        os.utime(older, None)

        server = agent_engine.ReportActionsServer(base_dir=base, open_browser=False)
        selected = server._latest_report_path()

        self.assertIsNotNone(selected)
        self.assertEqual(selected.name, "run_report_20260411_000610.html")


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


class _FakeLocatorItem:
    def __init__(self, text: str = "", visible: bool = True):
        self._text = text
        self._visible = visible

    def is_visible(self, timeout: int = 0):
        return self._visible

    def inner_text(self, timeout: int = 0):
        return self._text


class _FakeLocator:
    def __init__(self, items):
        self._items = list(items)

    def count(self):
        return len(self._items)

    def nth(self, idx: int):
        return self._items[idx]


class _FakePageForApplyMode:
    def __init__(self, mapping):
        self._mapping = mapping
        self.context = None

    def locator(self, selector: str):
        return _FakeLocator(self._mapping.get(selector, []))


class _FakeProbeContext:
    def __init__(self, probe_page):
        self._probe_page = probe_page

    def new_page(self):
        return self._probe_page


class _FakeProbePage(_FakePageForApplyMode):
    def set_default_timeout(self, timeout: int):
        return None

    def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 0):
        return None

    def wait_for_timeout(self, ms: int):
        return None

    def close(self):
        return None


class TestApplyModeDetection(unittest.TestCase):
    def _make_agent(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        base = Path(temp_dir.name)
        agent = agent_engine.LinkedInJobAgent(
            base_dir=base,
            max_jobs=1,
            headless=True,
            query="test",
            user_data_dir=None,
            max_run_seconds=60,
            max_extract_seconds=30,
            per_card_seconds=10,
        )
        self.addCleanup(agent.db.close)
        for handler in list(agent.logger.handlers):
            self.addCleanup(handler.close)
        return agent

    def test_detect_apply_mode_ignores_non_top_card_easy_apply_text(self):
        agent = self._make_agent()
        page = _FakePageForApplyMode(
            {
                "a:has-text('Easy Apply')": [_FakeLocatorItem("Easy Apply", True)],
            }
        )
        mode = agent._detect_apply_mode(page)
        self.assertEqual(mode, agent_engine.ProcessedJobsDB.APPLY_MODE_UNKNOWN)

    def test_detect_apply_mode_marks_easy_apply_when_top_card_easy_visible(self):
        agent = self._make_agent()
        page = _FakePageForApplyMode(
            {
                "[data-control-name*='jobdetails_topcard_inapply'] button": [_FakeLocatorItem("Easy Apply", True)],
            }
        )
        mode = agent._detect_apply_mode(page)
        self.assertEqual(mode, agent_engine.ProcessedJobsDB.APPLY_MODE_EASY)

    def test_detect_apply_mode_marks_external_when_top_card_apply_visible(self):
        agent = self._make_agent()
        page = _FakePageForApplyMode(
            {
                ".jobs-details-top-card__job-actions button:has-text('Apply')": [_FakeLocatorItem("Apply", True)],
            }
        )
        mode = agent._detect_apply_mode(page)
        self.assertEqual(mode, agent_engine.ProcessedJobsDB.APPLY_MODE_EXTERNAL)

    def test_detect_apply_mode_for_job_url_prefers_probe_page_mode(self):
        agent = self._make_agent()

        # Active page appears to contain generic Easy Apply artifacts.
        active_page = _FakePageForApplyMode(
            {
                "[data-control-name*='jobdetails_topcard_inapply'] button": [_FakeLocatorItem("Easy Apply", True)],
            }
        )

        # Probe page for the specific URL has no visible apply controls.
        probe_page = _FakeProbePage({})
        active_page.context = _FakeProbeContext(probe_page)

        mode = agent._detect_apply_mode_for_job_url(active_page, "https://www.linkedin.com/jobs/view/4374291012/")
        self.assertEqual(mode, agent_engine.ProcessedJobsDB.APPLY_MODE_UNKNOWN)


class TestAdaptiveJitter(unittest.TestCase):
    def _make_agent(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        base = Path(temp_dir.name)
        agent = agent_engine.LinkedInJobAgent(
            base_dir=base,
            max_jobs=5,
            headless=True,
            query="test",
            user_data_dir=None,
            max_run_seconds=60,
            max_extract_seconds=30,
            per_card_seconds=10,
        )
        self.addCleanup(agent.db.close)
        for handler in list(agent.logger.handlers):
            self.addCleanup(handler.close)
        return agent

    def test_jitter_respects_max_delay_budget(self):
        agent = self._make_agent()
        with patch("agent_engine.random.uniform", return_value=0.35), patch("agent_engine.time.sleep") as sleep_mock:
            agent.jitter("x", max_delay=0.5)
        sleep_mock.assert_called_once()
        self.assertLessEqual(float(sleep_mock.call_args[0][0]), 0.5)

    def test_jitter_disable_flag_uses_short_delay(self):
        agent = self._make_agent()
        with patch.dict(os.environ, {"AGENT_DISABLE_JITTER": "1"}, clear=False), patch("agent_engine.time.sleep") as sleep_mock:
            agent.jitter("x", max_delay=0.8)
        sleep_mock.assert_called_once_with(0.2)


if __name__ == "__main__":
    unittest.main()
