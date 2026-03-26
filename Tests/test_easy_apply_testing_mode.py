import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import auto_agoda_test_agent as agoda_runner
import agent_engine


class TestEasyApplyModeParsing(unittest.TestCase):
    def test_agent_engine_parse_args_defaults_to_normal(self):
        with patch.object(sys, "argv", ["agent_engine.py"]):
            args = agent_engine.parse_args()
        self.assertEqual(args.easy_apply_run_mode, "normal")

    def test_agent_engine_parse_args_accepts_testing(self):
        with patch.object(sys, "argv", ["agent_engine.py", "--easy-apply-run-mode", "testing"]):
            args = agent_engine.parse_args()
        self.assertEqual(args.easy_apply_run_mode, "testing")

    def test_auto_agoda_parse_args_defaults_to_testing(self):
        with patch.object(sys, "argv", ["auto_agoda_test_agent.py"]):
            args = agoda_runner.parse_args()
        self.assertEqual(args.easy_apply_run_mode, "testing")

    def test_auto_agoda_parse_args_accepts_normal(self):
        with patch.object(sys, "argv", ["auto_agoda_test_agent.py", "--easy-apply-run-mode", "normal"]):
            args = agoda_runner.parse_args()
        self.assertEqual(args.easy_apply_run_mode, "normal")


class TestTelegramSessionEasyApplyMode(unittest.TestCase):
    def _make_session(self, easy_apply_run_mode: str):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)

        db_path = Path(temp_dir.name) / "test_processed_jobs.db"
        db = agent_engine.ProcessedJobsDB(db_path)
        self.addCleanup(db.close)

        logger = logging.getLogger(f"test.easyapply.{easy_apply_run_mode}")
        logger.handlers = []
        logger.addHandler(logging.NullHandler())

        return agent_engine.TelegramJobSession(
            bot_token="dummy",
            chat_id=1,
            db=db,
            new_jobs=[],
            query="q",
            logger=logger,
            easy_apply_run_mode=easy_apply_run_mode,
        )

    def test_session_mode_accepts_testing(self):
        session = self._make_session("testing")
        self.assertEqual(session._easy_apply_run_mode, "testing")

    def test_session_mode_fallbacks_to_normal_for_invalid(self):
        session = self._make_session("invalid-mode")
        self.assertEqual(session._easy_apply_run_mode, "normal")


class TestApplyFieldPromptTypes(unittest.TestCase):
    def _make_session(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)

        db_path = Path(temp_dir.name) / "test_processed_jobs.db"
        db = agent_engine.ProcessedJobsDB(db_path)
        self.addCleanup(db.close)

        logger = logging.getLogger("test.prompt.types")
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

    def test_build_apply_form_fields_maps_prompts_by_type(self):
        session = self._make_session()
        scanned = [
            ("custom__radio_q", "Do you agree?", "radio"),
            ("custom__select_q", "Choose your stack", "select"),
            ("custom__text_q", "Tell us about yourself", "text"),
            ("custom__checkbox_q", "Accept terms", "checkbox"),
        ]

        fields = session._build_apply_form_fields(scanned)
        prompts_by_key = {key: prompt for key, prompt in fields}

        self.assertEqual(prompts_by_key["custom__radio_q"], "❓ Do you agree? (type your answer):")
        self.assertEqual(prompts_by_key["custom__select_q"], "🔽 Choose your stack (type your choice):")
        self.assertEqual(prompts_by_key["custom__text_q"], "✏️ Tell us about yourself:")
        self.assertEqual(prompts_by_key["custom__checkbox_q"], "❓ Accept terms (type your answer):")


if __name__ == "__main__":
    unittest.main()
