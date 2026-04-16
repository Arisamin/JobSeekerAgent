import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import auto_agoda_test_agent as agoda_runner
import agent_engine


class TestEasyApplyModeParsing(unittest.TestCase):
    def test_agent_engine_parse_args_defaults_to_search(self):
        with patch.object(sys, "argv", ["agent_engine.py"]):
            args = agent_engine.parse_args()
        self.assertEqual(args.easy_apply_run_mode, "search")

    def test_agent_engine_parse_args_accepts_testing(self):
        with patch.object(sys, "argv", ["agent_engine.py", "--easy-apply-run-mode", "testing"]):
            args = agent_engine.parse_args()
        self.assertEqual(args.easy_apply_run_mode, "testing")

    def test_auto_agoda_parse_args_defaults_to_testing(self):
        with patch.object(sys, "argv", ["auto_agoda_test_agent.py"]):
            args = agoda_runner.parse_args()
        self.assertEqual(args.easy_apply_run_mode, "testing")

    def test_auto_agoda_parse_args_accepts_search(self):
        with patch.object(sys, "argv", ["auto_agoda_test_agent.py", "--easy-apply-run-mode", "search"]):
            args = agoda_runner.parse_args()
        self.assertEqual(args.easy_apply_run_mode, "search")


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

    def test_session_mode_fallbacks_to_search_for_invalid(self):
        session = self._make_session("invalid-mode")
        self.assertEqual(session._easy_apply_run_mode, "search")


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

        self.assertIn("❓ Do you agree? (type your answer):", prompts_by_key["custom__radio_q"])
        self.assertIn("Options:", prompts_by_key["custom__radio_q"])
        self.assertIn("1) Yes", prompts_by_key["custom__radio_q"])
        self.assertIn("2) No", prompts_by_key["custom__radio_q"])
        self.assertEqual(prompts_by_key["custom__select_q"], "🔽 Choose your stack (type your choice):")
        self.assertEqual(prompts_by_key["custom__text_q"], "✏️ Tell us about yourself:")
        self.assertIn("❓ Accept terms (type your answer):", prompts_by_key["custom__checkbox_q"])
        self.assertIn("Options:", prompts_by_key["custom__checkbox_q"])
        self.assertIn("1) Yes", prompts_by_key["custom__checkbox_q"])
        self.assertIn("2) No", prompts_by_key["custom__checkbox_q"])

    def test_build_apply_form_fields_includes_predefined_options(self):
        session = self._make_session()
        session._apply_field_options = {
            "custom__radio_q": ["Yes", "No"],
            "custom__select_q": ["Backend", "Platform", "Data"],
        }
        scanned = [
            ("custom__radio_q", "Do you agree?", "radio"),
            ("custom__select_q", "Choose your stack", "select"),
        ]

        fields = session._build_apply_form_fields(scanned)
        prompts_by_key = {key: prompt for key, prompt in fields}

        self.assertIn("Options:", prompts_by_key["custom__radio_q"])
        self.assertIn("1) Yes", prompts_by_key["custom__radio_q"])
        self.assertIn("2) No", prompts_by_key["custom__radio_q"])
        self.assertIn("Reply with an option number, the full option text, or a filter substring", prompts_by_key["custom__radio_q"])

        self.assertIn("1) Backend", prompts_by_key["custom__select_q"])
        self.assertIn("3) Data", prompts_by_key["custom__select_q"])

    def test_build_apply_form_fields_marks_arabic_questions(self):
        session = self._make_session()
        scanned = [
            ("custom__arabic_q", "هل أنت مستعد للانتقال؟", "radio"),
        ]

        fields = session._build_apply_form_fields(scanned)
        prompts_by_key = {key: prompt for key, prompt in fields}
        self.assertIn("هل أنت مستعد للانتقال؟", prompts_by_key["custom__arabic_q"])
        self.assertIn("Arabic label detected", prompts_by_key["custom__arabic_q"])

    def test_validate_apply_answer_accepts_option_number(self):
        session = self._make_session()
        session._apply_field_types = {"custom__radio_q": "radio"}
        session._apply_field_options = {"custom__radio_q": ["Yes", "No"]}

        is_valid, _, normalized = session._validate_apply_answer("custom__radio_q", "2")
        self.assertTrue(is_valid)
        self.assertEqual(normalized, "No")

    def test_normalize_scanned_field_type_corrects_common_misclassifications(self):
        session = self._make_session()

        self.assertEqual(
            "email",
            session._normalize_scanned_field_type(
                field_key="email",
                label="Email address Email address",
                field_type="select",
            ),
        )
        self.assertEqual(
            "tel",
            session._normalize_scanned_field_type(
                field_key="phone",
                label="Mobile phone number",
                field_type="text",
            ),
        )
        self.assertEqual(
            "select",
            session._normalize_scanned_field_type(
                field_key="phone",
                label="Phone country code Phone country code",
                field_type="text",
            ),
        )
        self.assertEqual(
            "checkbox",
            session._normalize_scanned_field_type(
                field_key="custom__follow",
                label="Follow Confidential to stay up to date with their page.",
                field_type="text",
            ),
        )

    def test_build_apply_form_fields_truncates_displayed_options_for_large_select(self):
        session = self._make_session()
        many_options = [f"Country {i}" for i in range(1, 60)]
        session._apply_field_options = {"custom__country": many_options}
        fields = session._build_apply_form_fields([
            ("custom__country", "In which country are you currently based?", "select"),
        ])
        prompts_by_key = {key: prompt for key, prompt in fields}
        prompt = prompts_by_key["custom__country"]

        self.assertIn("1) Country 1", prompt)
        self.assertIn("20) Country 20", prompt)
        self.assertNotIn("21) Country 21", prompt)
        self.assertIn("more option(s) not shown", prompt)

    def test_validate_apply_answer_rejects_unknown_free_text_for_select(self):
        session = self._make_session()
        session._apply_field_types = {"custom__country": "select"}
        session._apply_field_options = {"custom__country": ["Afghanistan", "Albania", "Algeria"]}

        is_valid, _, normalized = session._validate_apply_answer("custom__country", "Thailand")
        self.assertFalse(is_valid)
        self.assertEqual(normalized, "")

    def test_build_apply_form_fields_scan_only_omits_fixed_fields(self):
        session = self._make_session()
        scanned = [
            ("custom__english", "What is your level of proficiency in English?", "select"),
            ("phone", "Phone number", "tel"),
        ]

        fields = session._build_apply_form_fields(scanned, include_fixed_fields=False)
        keys = [k for k, _ in fields]

        self.assertIn("custom__english", keys)
        self.assertIn("phone", keys)
        self.assertNotIn("full_name", keys)
        self.assertNotIn("location", keys)

    def test_cmd_apply_uses_only_scanned_fields_when_scan_is_partial(self):
        session = self._make_session()
        session._current_job = {
            "id": 7,
            "title": "Senior Backend Engineer",
            "company": "Confidential",
            "url": "https://www.linkedin.com/jobs/view/4400959935/",
        }
        session._scan_easy_apply_fields = lambda _url: [
            ("phone", "Mobile phone number", "tel"),
            ("email", "Email address", "email"),
            (
                "custom__how_many_years_of_work_experience_do_you_have_with_cloud_infrastructure",
                "How many years of work experience do you have with Cloud Infrastructure?",
                "number",
            ),
        ]

        self.assertTrue(session._cmd_apply())

        keys = [k for k, _ in session._apply_form_fields]
        self.assertNotIn("cv_path", keys)
        self.assertNotIn("full_name", keys)
        self.assertIn("email", keys)
        self.assertIn("phone", keys)
        self.assertNotIn("location", keys)
        self.assertNotIn("linkedin", keys)
        self.assertTrue(any(k.startswith("custom__") for k in keys))

    def test_rescan_keeps_only_scanned_fields_and_appends_new_discovered_keys(self):
        session = self._make_session()
        session._easy_apply_run_mode = "search"
        session._current_job = {
            "id": 8,
            "title": "Senior Backend Engineer",
            "company": "Confidential",
            "url": "https://www.linkedin.com/jobs/view/4400959935/",
        }

        session._apply_form_fields = session._build_apply_form_fields([
            ("phone", "Mobile phone number", "tel"),
            ("email", "Email address", "email"),
        ], include_fixed_fields=False)
        session._apply_answers = {}
        session._apply_asked_field_keys = []
        session._apply_question_idx = 0

        session._scan_easy_apply_fields = lambda _url, seed_answers=None: [
            ("phone", "Mobile phone number", "tel"),
            ("email", "Email address", "email"),
            (
                "custom__how_many_years_of_work_experience_do_you_have_with_distributed_systems",
                "How many years of work experience do you have with Distributed Systems?",
                "number",
            ),
        ]

        expanded = session._maybe_expand_apply_fields_via_rescan(session._current_job["url"])

        self.assertTrue(expanded)
        keys = [k for k, _ in session._apply_form_fields]
        self.assertNotIn("cv_path", keys)
        self.assertNotIn("full_name", keys)
        self.assertNotIn("location", keys)
        self.assertNotIn("linkedin", keys)
        self.assertIn("phone", keys)
        self.assertIn("email", keys)
        self.assertTrue(any(k.startswith("custom__") for k in keys))

    def test_resolve_apply_answer_prefers_custom_skill_specific_experience_key(self):
        session = self._make_session()
        label = "How many years of work experience do you have with Cloud Infrastructure?"
        custom_key = session._custom_key_from_label(label)
        answers = {
            "experience_years": "5",
            custom_key: "8",
        }

        resolved = session._resolve_apply_answer(label, answers)
        self.assertEqual(resolved, "8")

    def test_option_resolution_accepts_exact_match_without_confirm(self):
        session = self._make_session()
        sent_messages = []
        session._send = lambda text, parse_mode="HTML": sent_messages.append(text)
        session._persist_saved_profile = lambda: None

        session._state = session.STATE_APPLYING
        session._current_job = {"id": 1, "title": "Role", "company": "Comp", "url": "https://www.linkedin.com/jobs/view/1/"}
        session._apply_form_fields = [
            ("custom__country", "🔽 Country:"),
            ("full_name", "✍️ Full name:"),
        ]
        session._apply_field_types = {"custom__country": "select", "full_name": "text"}
        session._apply_field_options = {"custom__country": ["Afghanistan", "Albania", "Algeria"]}
        session._apply_answers = {}
        session._apply_question_idx = 0

        session._send_current_apply_prompt()
        session._handle_apply_answer("Albania")

        self.assertEqual(session._apply_answers.get("custom__country"), "Albania")
        self.assertEqual(session._apply_question_idx, 1)

    def test_option_resolution_allows_number_selection_from_match_sublist(self):
        session = self._make_session()
        sent_messages = []
        session._send = lambda text, parse_mode="HTML": sent_messages.append(text)
        session._persist_saved_profile = lambda: None

        session._state = session.STATE_APPLYING
        session._current_job = {"id": 1, "title": "Role", "company": "Comp", "url": "https://www.linkedin.com/jobs/view/1/"}
        session._apply_form_fields = [
            ("custom__location", "🔽 Location:"),
            ("full_name", "✍️ Full name:"),
        ]
        session._apply_field_types = {"custom__location": "select", "full_name": "text"}
        session._apply_field_options = {
            "custom__location": [
                "Bangkok, Thailand",
                "Bangalore, India",
                "Tel Aviv, Israel",
            ]
        }
        session._apply_answers = {}
        session._apply_question_idx = 0

        session._send_current_apply_prompt()
        session._handle_apply_answer("Bang")

        self.assertEqual(session._option_resolution_state.get("phase"), "await_pick")
        session._handle_apply_answer("2")

        self.assertEqual(session._apply_answers.get("custom__location"), "Bangalore, India")
        self.assertEqual(session._apply_question_idx, 1)

    def test_prune_invalid_prefilled_option_answers_removes_stale_value(self):
        session = self._make_session()
        session._persist_saved_profile = lambda: None
        session._apply_form_fields = [("custom__country", "prompt")]
        session._apply_field_labels = {"custom__country": "In which country are you currently based?"}
        session._apply_field_types = {"custom__country": "select"}
        session._apply_field_options = {"custom__country": ["Israel", "Thailand", "United States"]}
        session._apply_answers = {"custom__country": "Mars"}
        session._saved_profile = {"custom__country": "Mars"}

        invalid_labels = session._prune_invalid_prefilled_option_answers()

        self.assertIn("In which country are you currently based?", invalid_labels)
        self.assertNotIn("custom__country", session._apply_answers)
        self.assertNotIn("custom__country", session._saved_profile)


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
