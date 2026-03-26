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


class _FakeLeaf:
    def __init__(self, visible: bool = True):
        self._visible = visible
        self.clicked = False

    def count(self):
        return 1

    @property
    def first(self):
        return self

    def is_visible(self, timeout=0):
        _ = timeout
        return self._visible

    def click(self, timeout=0):
        _ = timeout
        self.clicked = True


class _FakeRoot:
    def __init__(self, label_by_selector=None):
        self._labels = label_by_selector or {}

    def locator(self, selector):
        return self._labels.get(selector, _FakeLeaf(visible=False))


class _FakeRadioInput:
    def __init__(self, visible=True, radio_id="", checked=False, check_works=False, click_works=False):
        self._visible = visible
        self._id = radio_id
        self._checked = checked
        self._check_works = check_works
        self._click_works = click_works
        self._ancestor_label = _FakeLeaf(visible=False)

    def is_visible(self, timeout=0):
        _ = timeout
        return self._visible

    def is_checked(self, timeout=0):
        _ = timeout
        if self._checked:
            return True
        raise RuntimeError("not checked")

    def get_attribute(self, name, timeout=0):
        _ = timeout
        if name == "id":
            return self._id
        if name == "checked":
            return "checked" if self._checked else ""
        return ""

    def check(self, timeout=0):
        _ = timeout
        if not self._check_works:
            raise RuntimeError("check failed")
        self._checked = True

    def click(self, timeout=0):
        _ = timeout
        if not self._click_works:
            raise RuntimeError("click failed")
        self._checked = True

    def locator(self, selector):
        if selector == "xpath=ancestor::label[1]":
            return self._ancestor_label
        return _FakeLeaf(visible=False)


class _FakeGroup:
    def __init__(self, radios):
        self._radios = radios

    def count(self):
        return len(self._radios)

    def nth(self, idx):
        return self._radios[idx]


class TestExtractedRadioHelpers(unittest.TestCase):
    def _make_session(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db_path = Path(temp_dir.name) / "test_processed_jobs.db"
        db = agent_engine.ProcessedJobsDB(db_path)
        self.addCleanup(db.close)
        logger = logging.getLogger("test.radio.helpers")
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

    def test_scan_is_radio_selected_uses_checked_attr_fallback(self):
        session = self._make_session()
        radio = _FakeRadioInput(checked=False)
        self.assertFalse(session._scan_is_radio_selected(radio))

        checked_radio = _FakeRadioInput(checked=True)
        self.assertTrue(session._scan_is_radio_selected(checked_radio))

    def test_scan_try_select_radio_input_uses_label_for_fallback(self):
        session = self._make_session()
        radio = _FakeRadioInput(visible=False, radio_id="opt-1", checked=False, check_works=False, click_works=False)
        label = _FakeLeaf(visible=True)
        root = _FakeRoot({"label[for='opt-1']": label})

        selected = session._scan_try_select_radio_input(
            radio_input=radio,
            root=root,
            question_label="sample question",
            testing_mode=True,
        )
        self.assertTrue(selected)
        self.assertTrue(label.clicked)

    def test_scan_pick_visible_radio_indexes_includes_hidden_with_visible_label(self):
        session = self._make_session()
        visible_radio = _FakeRadioInput(visible=True, radio_id="r1")
        hidden_with_label = _FakeRadioInput(visible=False, radio_id="r2")
        hidden_no_label = _FakeRadioInput(visible=False, radio_id="r3")
        group = _FakeGroup([visible_radio, hidden_with_label, hidden_no_label])
        label_r2 = _FakeLeaf(visible=True)
        root = _FakeRoot({"label[for='r2']": label_r2})

        indexes = session._scan_pick_visible_radio_indexes(group=group, root=root)
        self.assertEqual(indexes, [0, 1])


if __name__ == "__main__":
    unittest.main()
