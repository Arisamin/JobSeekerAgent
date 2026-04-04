import inspect
import logging
import tempfile
import unittest
from pathlib import Path

import agent_engine


class TestMobileyeGapRootCauses(unittest.TestCase):
    def _make_session(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)

        db_path = Path(temp_dir.name) / "test_processed_jobs.db"
        db = agent_engine.ProcessedJobsDB(db_path)
        self.addCleanup(db.close)

        logger = logging.getLogger("test.mobileye.root.causes")
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

    def test_placeholder_only_block_no_longer_becomes_question_label(self):
        block = """
        Select...
        I don't have any family member working at Mobileye
        I have a family member working at Mobileye
        Male
        Female
        Non-binary
        Prefer not to say
        """
        # Regression: option-only blocks should not produce a fake question label.
        label = agent_engine.extract_question_label_from_block_text(block)
        self.assertEqual(label, "")

    def test_external_flow_no_longer_references_unbound_step_variable(self):
        src = inspect.getsource(agent_engine.TelegramJobSession._scan_easy_apply_fields)
        self.assertIn("easy_apply_step = -1", src)
        self.assertIn("scan_flow_type == \"easy_apply\"", src)
        self.assertIn("easy_apply_step == max_steps - 1", src)
        self.assertNotIn("if len(discovered) > 0 and _step == max_steps - 1", src)

    def test_generic_label_detection_helper(self):
        self.assertTrue(agent_engine.is_generic_choice_label("Select..."))
        self.assertTrue(agent_engine.is_generic_choice_label("choose"))
        self.assertFalse(agent_engine.is_generic_choice_label("Gender"))

    def test_scan_path_disambiguates_generic_custom_keys(self):
        src = inspect.getsource(agent_engine.TelegramJobSession._scan_easy_apply_fields)
        self.assertIn("def _disambiguate_generic_key", src)
        self.assertIn("is_generic_choice_label", src)
        self.assertIn("_disambiguate_generic_key(key, label", src)


if __name__ == "__main__":
    unittest.main()
