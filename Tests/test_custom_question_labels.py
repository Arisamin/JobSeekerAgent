import logging
import tempfile
import unittest
from pathlib import Path

import agent_engine


class TestCustomQuestionLabels(unittest.TestCase):
    def _make_session(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)

        db_path = Path(temp_dir.name) / "test_processed_jobs.db"
        db = agent_engine.ProcessedJobsDB(db_path)
        self.addCleanup(db.close)

        logger = logging.getLogger("test.custom.question.labels")
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

    def test_custom_key_generation_is_collision_resistant(self):
        session = self._make_session()
        label_a = (
            "Are you presently employed by any company within the Booking Holdings group, "
            "including but not limited to Kayak, OpenTable, Booking.com, Rental Cars?"
        )
        label_b = (
            "Are you presently employed by any company within the Booking Holdings group, "
            "including but not limited to Priceline, Momondo, CheapFlights, or Getaroom?"
        )

        key_a = session._custom_key_from_label(label_a)
        key_b = session._custom_key_from_label(label_b)

        self.assertTrue(key_a.startswith("custom__"))
        self.assertTrue(key_b.startswith("custom__"))
        self.assertNotEqual(key_a, key_b)

    def test_apply_summary_uses_full_scanned_label(self):
        session = self._make_session()
        long_label = (
            "Are you presently employed by any company within the Booking Holdings group"
        )
        field_key = session._custom_key_from_label(long_label)

        session._current_job = {
            "title": "Software Engineer",
            "company": "ExampleCo",
            "url": "https://example.com/job",
        }
        session._apply_form_fields = [
            (field_key, "❓ Q1: Are you presently employed by any company within (type your answer):"),
        ]
        session._apply_field_labels = {field_key: long_label}
        session._apply_answers = {field_key: "No"}
        session._apply_asked_field_keys = [field_key]

        sent_messages = []
        session._send = lambda text, parse_mode="HTML": sent_messages.append(text)

        keep_going = session._show_apply_summary()

        self.assertTrue(keep_going)
        self.assertTrue(any(long_label in message for message in sent_messages))


if __name__ == "__main__":
    unittest.main()
