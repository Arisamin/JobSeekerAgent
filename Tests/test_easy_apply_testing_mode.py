import logging
import json
import os
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

    def test_agent_engine_parse_args_accepts_headed(self):
        with patch.object(sys, "argv", ["agent_engine.py", "--easy-apply-run-mode", "headed"]):
            args = agent_engine.parse_args()
        self.assertEqual(args.easy_apply_run_mode, "headed")

    def test_agent_engine_parse_args_maps_legacy_testing_alias_to_headed(self):
        with patch.object(sys, "argv", ["agent_engine.py", "--easy-apply-run-mode", "testing"]):
            args = agent_engine.parse_args()
        self.assertEqual(args.easy_apply_run_mode, "headed")

    def test_auto_agoda_parse_args_defaults_to_headed(self):
        with patch.object(sys, "argv", ["auto_agoda_test_agent.py"]):
            args = agoda_runner.parse_args()
        self.assertEqual(args.easy_apply_run_mode, "headed")

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

    def test_session_mode_accepts_headed(self):
        session = self._make_session("headed")
        self.assertEqual(session._easy_apply_run_mode, "headed")

    def test_session_mode_maps_legacy_testing_alias_to_headed(self):
        session = self._make_session("testing")
        self.assertEqual(session._easy_apply_run_mode, "headed")

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

    def test_validate_apply_answer_accepts_cv_existing_template_option(self):
        session = self._make_session()
        session._apply_field_types = {"cv_path": "select"}
        session._apply_field_options = {"cv_path": ["Ariel CV - 2026.pdf", "Ariel CV - 2025.pdf"]}

        is_valid, _, normalized = session._validate_apply_answer("cv_path", "1")
        self.assertTrue(is_valid)
        self.assertEqual(normalized, "Ariel CV - 2026.pdf")

    def test_validate_apply_answer_rejects_unknown_cv_existing_template_option(self):
        session = self._make_session()
        session._apply_field_types = {"cv_path": "select"}
        session._apply_field_options = {"cv_path": ["Ariel CV - 2026.pdf", "Ariel CV - 2025.pdf"]}

        is_valid, _, normalized = session._validate_apply_answer("cv_path", "CV not listed")
        self.assertFalse(is_valid)
        self.assertEqual(normalized, "")

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
        self.assertEqual(
            "select",
            session._normalize_scanned_field_type(
                field_key="cv_path",
                label="Resume / CV",
                field_type="select",
            ),
        )

    def test_build_apply_form_fields_cv_path_select_uses_option_protocol(self):
        session = self._make_session()
        session._apply_field_options = {
            "cv_path": ["Ariel CV - 2026.pdf", "Ariel CV - 2025.pdf"],
        }

        fields = session._build_apply_form_fields(
            [("cv_path", "Resume / CV", "select")],
            include_fixed_fields=False,
        )
        prompt = dict(fields)["cv_path"]

        self.assertIn("🔽 Resume / CV", prompt)
        self.assertIn("1) Ariel CV - 2026.pdf", prompt)
        self.assertNotIn("file path", prompt.lower())

    def test_build_apply_form_fields_cv_path_uses_local_file_fallback_options(self):
        session = self._make_session()

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        cv1 = Path(temp_dir.name) / "Ariel CV - 2026 [2].pdf"
        cv2 = Path(temp_dir.name) / "Ariel CV - 2025 [1].pdf"
        cv1.write_text("x", encoding="utf-8")
        cv2.write_text("x", encoding="utf-8")

        session._saved_profile = {"cv_path": str(cv1)}
        session._apply_field_options = {}

        fields = session._build_apply_form_fields(
            [("cv_path", "Upload resume", "file")],
            include_fixed_fields=False,
        )
        prompt = dict(fields)["cv_path"]

        self.assertEqual("select", session._apply_field_types.get("cv_path"))
        cv_options = session._apply_field_options.get("cv_path", [])
        self.assertGreaterEqual(len(cv_options), 2)
        self.assertIn(str(cv1.resolve()), cv_options)
        self.assertIn(str(cv2.resolve()), cv_options)
        self.assertIn("🔽 Upload resume", prompt)
        self.assertIn("Ariel CV - 2026 [2].pdf", prompt)

    def test_canonicalize_apply_label_collapses_short_duplicate_halves(self):
        session = self._make_session()
        self.assertEqual(
            "Phone country code",
            session._canonicalize_apply_label("Phone country code Phone country code"),
        )

    def test_canonicalize_apply_label_normalizes_machine_date_range_labels(self):
        session = self._make_session()
        self.assertEqual("From year", session._canonicalize_apply_label("Year of From"))
        self.assertEqual("To month", session._canonicalize_apply_label("Month of To"))

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

    def test_build_fields_reuses_options_for_duplicate_canonical_label(self):
        session = self._make_session()
        long_key = "custom__phone_country_long"
        short_key = "custom__phone_country_short"
        session._apply_field_options = {
            long_key: ["Israel (+972)", "United States (+1)"],
        }

        fields = session._build_apply_form_fields(
            [
                (long_key, "Phone country code Phone country code", "select"),
                (short_key, "Phone country code", "select"),
            ],
            include_fixed_fields=False,
        )
        prompts_by_key = {key: prompt for key, prompt in fields}

        self.assertIn("1) Israel (+972)", prompts_by_key[short_key])
        self.assertIn("2) United States (+1)", prompts_by_key[short_key])
        self.assertEqual(
            ["Israel (+972)", "United States (+1)"],
            session._apply_field_options.get(short_key),
        )

    def test_prune_invalid_prefill_for_duplicate_phone_country_label(self):
        session = self._make_session()
        session._persist_saved_profile = lambda: None
        long_key = "custom__phone_country_long"
        short_key = "custom__phone_country_short"
        session._apply_field_options = {
            long_key: ["Israel (+972)", "United States (+1)"],
        }
        session._apply_form_fields = session._build_apply_form_fields(
            [
                (long_key, "Phone country code Phone country code", "select"),
                (short_key, "Phone country code", "select"),
            ],
            include_fixed_fields=False,
        )
        session._apply_answers = {short_key: "Isr"}
        session._saved_profile = {short_key: "Isr"}

        invalid_labels = session._prune_invalid_prefilled_option_answers()

        self.assertIn("Phone country code", invalid_labels)
        self.assertNotIn(short_key, session._apply_answers)
        self.assertNotIn(short_key, session._saved_profile)

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

    def test_cmd_apply_forces_cv_reask_each_run_when_multiple_resume_options_exist(self):
        session = self._make_session()
        sent_messages = []
        session._send = lambda text, parse_mode="HTML": sent_messages.append(text)
        session._current_job = {
            "id": 70,
            "title": "VMware engineer",
            "company": "Bynet",
            "url": "https://www.linkedin.com/jobs/view/4412741120/",
        }
        session._saved_profile = {
            "cv_path": "Ariel CV - 2026 [2].pdf",
        }

        def _scan(_url):
            session._apply_field_options = {
                "cv_path": ["Ariel CV - 2026 [2].pdf", "Ariel CV - 2025 [1].pdf"],
            }
            return [
                ("cv_path", "Upload resume", "select"),
                ("email", "Email", "email"),
            ]

        session._scan_easy_apply_fields = _scan

        self.assertTrue(session._cmd_apply())
        self.assertNotIn("cv_path", session._apply_answers)
        self.assertEqual(0, session._apply_question_idx)
        self.assertTrue(any("Multiple existing resume choices" in msg for msg in sent_messages))

    def test_cmd_apply_keeps_prefilled_cv_when_only_one_resume_option_exists(self):
        session = self._make_session()
        session._send = lambda _text, parse_mode="HTML": None
        session._current_job = {
            "id": 71,
            "title": "VMware engineer",
            "company": "Bynet",
            "url": "https://www.linkedin.com/jobs/view/4412741120/",
        }
        session._saved_profile = {
            "cv_path": "Ariel CV - 2026 [2].pdf",
        }

        def _scan(_url):
            session._apply_field_options = {
                "cv_path": ["Ariel CV - 2026 [2].pdf"],
            }
            return [
                ("cv_path", "Upload resume", "select"),
                ("email", "Email", "email"),
            ]

        session._scan_easy_apply_fields = _scan

        self.assertTrue(session._cmd_apply())
        self.assertEqual("Ariel CV - 2026 [2].pdf", session._apply_answers.get("cv_path"))

    def test_cmd_apply_forces_cv_reask_with_local_cv_fallback_options(self):
        session = self._make_session()
        sent_messages = []
        session._send = lambda text, parse_mode="HTML": sent_messages.append(text)

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        cv1 = Path(temp_dir.name) / "Ariel CV - 2026 [2].pdf"
        cv2 = Path(temp_dir.name) / "Ariel CV - 2026 [3].pdf"
        cv1.write_text("x", encoding="utf-8")
        cv2.write_text("x", encoding="utf-8")

        session._current_job = {
            "id": 72,
            "title": "Software Engineer",
            "company": "IO River",
            "url": "https://www.linkedin.com/jobs/view/4412557695/",
        }
        session._saved_profile = {
            "cv_path": str(cv1),
        }

        session._scan_easy_apply_fields = lambda _url: [
            ("phone", "Phone", "tel"),
            ("email", "Email", "email"),
            ("cv_path", "Upload resume", "file"),
        ]

        self.assertTrue(session._cmd_apply())
        self.assertNotIn("cv_path", session._apply_answers)
        self.assertTrue(any("Multiple existing resume choices" in msg for msg in sent_messages))

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

    def test_option_resolution_requires_number_even_when_filter_has_single_match(self):
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

        self.assertIsNone(session._apply_answers.get("custom__country"))
        self.assertIn("Only a numbered reply finalizes", sent_messages[-1])

        session._handle_apply_answer("1")
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
                "Tel Aviv, Israel",
                "Bangkok, Thailand",
                "Bangalore, India",
            ]
        }
        session._apply_answers = {}
        session._apply_question_idx = 0

        session._send_current_apply_prompt()
        session._handle_apply_answer("Bang")

        self.assertIn("1) Bangkok, Thailand", sent_messages[-1])
        self.assertIn("2) Bangalore, India", sent_messages[-1])
        session._handle_apply_answer("2")

        self.assertEqual(session._apply_answers.get("custom__location"), "Bangalore, India")
        self.assertEqual(session._apply_question_idx, 1)

    def test_location_select_uses_option_protocol(self):
        session = self._make_session()
        sent_messages = []
        session._send = lambda text, parse_mode="HTML": sent_messages.append(text)
        session._persist_saved_profile = lambda: None

        session._state = session.STATE_APPLYING
        session._current_job = {"id": 1, "title": "Role", "company": "Comp", "url": "https://www.linkedin.com/jobs/view/1/"}
        session._apply_form_fields = [
            ("location", "🔽 Location (city):"),
            ("full_name", "✍️ Full name:"),
        ]
        session._apply_field_types = {"location": "select", "full_name": "text"}
        session._apply_field_options = {
            "location": [
                "Tel Aviv",
                "Jerusalem",
                "Haifa",
            ]
        }
        session._apply_answers = {}
        session._apply_question_idx = 0

        session._send_current_apply_prompt()
        session._handle_apply_answer("Aviv")

        self.assertIsNone(session._apply_answers.get("location"))
        self.assertIn("Only a numbered reply finalizes", sent_messages[-1])

        session._handle_apply_answer("1")
        self.assertEqual(session._apply_answers.get("location"), "Tel Aviv")
        self.assertEqual(session._apply_question_idx, 1)

    def test_location_city_rejects_partial_value_without_dropdown_options(self):
        session = self._make_session()
        sent_messages = []
        session._send = lambda text, parse_mode="HTML": sent_messages.append(text)
        session._persist_saved_profile = lambda: None

        session._state = session.STATE_APPLYING
        session._current_job = {"id": 1, "title": "Role", "company": "Comp", "url": "https://www.linkedin.com/jobs/view/1/"}
        session._apply_form_fields = [
            ("location", "✏️ Location (city):"),
            ("full_name", "✍️ Full name:"),
        ]
        session._apply_field_labels = {
            "location": "Location (city)",
            "full_name": "Full name",
        }
        session._apply_field_types = {"location": "text", "full_name": "text"}
        session._apply_field_options = {}
        session._apply_answers = {}
        session._apply_question_idx = 0

        session._handle_apply_answer("Aviv")

        self.assertNotIn("location", session._apply_answers)
        self.assertEqual(session._apply_question_idx, 0)
        self.assertIn("Location (city) looks incomplete", sent_messages[-2])

        session._handle_apply_answer("Tel Aviv")
        self.assertEqual(session._apply_answers.get("location"), "Tel Aviv")
        self.assertEqual(session._apply_question_idx, 1)

    def test_apply_summary_always_includes_cv_context(self):
        session = self._make_session()
        sent_messages = []
        session._send = lambda text, parse_mode="HTML": sent_messages.append(text)
        session._register_prefill_launch = lambda **_kwargs: ""  # type: ignore[method-assign]

        session._current_job = {
            "id": 1,
            "title": "Role",
            "company": "Comp",
            "url": "https://www.linkedin.com/jobs/view/1/",
        }
        session._apply_form_fields = [
            ("location", "✏️ Location (city):"),
            ("email", "✏️ Email:"),
        ]
        session._apply_field_labels = {
            "location": "Location (city)",
            "email": "Email address",
        }
        session._apply_field_types = {
            "location": "text",
            "email": "email",
        }
        session._apply_field_options = {}
        session._apply_answers = {
            "location": "Tel Aviv",
            "email": "ariel@example.com",
        }
        session._saved_profile = {
            "cv_path": r"C:\MyData\Ariel CV - 2026 [2].pdf",
        }

        self.assertTrue(session._show_apply_summary())
        summary_text = sent_messages[-1]

        self.assertIn("CV candidate for upload", summary_text)
        self.assertIn(r"C:\MyData\Ariel CV - 2026 [2].pdf", summary_text)

    def test_cover_letter_none_counts_as_answered_not_missing(self):
        session = self._make_session()
        sent_messages = []
        session._send = lambda text, parse_mode="HTML": sent_messages.append(text)
        session._persist_saved_profile = lambda: None

        session._state = session.STATE_APPLYING
        session._current_job = {"id": 1, "title": "Role", "company": "Comp", "url": "https://www.linkedin.com/jobs/view/1/"}
        session._apply_form_fields = [
            ("cover_letter_path", "📝 Cover letter file path"),
            ("full_name", "✍️ Full name:"),
        ]
        session._apply_field_types = {"cover_letter_path": "file", "full_name": "text"}
        session._apply_field_options = {}
        session._apply_answers = {}
        session._apply_question_idx = 0
        session._maybe_expand_apply_fields_via_rescan = lambda *_a, **_k: False  # type: ignore[method-assign]

        session._handle_apply_answer("none")

        self.assertIn("cover_letter_path", session._apply_answers)
        self.assertEqual(session._apply_answers.get("cover_letter_path"), "")
        self.assertEqual(session._apply_question_idx, 1)

    def test_rescan_keeps_explicit_blank_answers_and_drops_stale_unanswered_fields(self):
        session = self._make_session()
        session._easy_apply_run_mode = "search"
        session._current_job = {
            "id": 8,
            "title": "Role",
            "company": "Comp",
            "url": "https://www.linkedin.com/jobs/view/1/",
        }

        session._apply_form_fields = [
            ("cover_letter_path", "cover"),
            ("custom__how_did_you_hear", "hear"),
            ("email", "email"),
        ]
        session._apply_field_labels = {
            "cover_letter_path": "Cover letter file path",
            "custom__how_did_you_hear": "How did you hear about us?",
            "email": "Email address",
        }
        session._apply_field_types = {
            "cover_letter_path": "file",
            "custom__how_did_you_hear": "text",
            "email": "email",
        }
        session._apply_field_options = {}
        session._apply_answers = {
            "cover_letter_path": "",
            "email": "ariel.samin@gmail.com",
        }
        session._apply_asked_field_keys = ["cover_letter_path", "custom__how_did_you_hear", "email"]
        session._apply_question_idx = 0

        session._scan_easy_apply_fields = lambda _url, seed_answers=None: [
            ("email", "Email address", "email"),
        ]

        _ = session._maybe_expand_apply_fields_via_rescan(session._current_job["url"])

        keys = [k for k, _ in session._apply_form_fields]
        self.assertIn("cover_letter_path", keys)
        self.assertNotIn("custom__how_did_you_hear", keys)
        self.assertIn("cover_letter_path", session._apply_answers)
        self.assertEqual(session._apply_answers.get("cover_letter_path"), "")

    def test_rescan_does_not_announce_required_questions_when_new_fields_prefilled(self):
        session = self._make_session()
        sent_messages = []
        session._send = lambda text, parse_mode="HTML": sent_messages.append(text)
        session._easy_apply_run_mode = "search"
        session._current_job = {
            "id": 9,
            "title": "Role",
            "company": "Comp",
            "url": "https://www.linkedin.com/jobs/view/1/",
        }

        session._apply_form_fields = [
            ("location", "location"),
        ]
        session._apply_field_labels = {
            "location": "Location (city)",
        }
        session._apply_field_types = {
            "location": "text",
        }
        session._apply_field_options = {}
        session._apply_answers = {
            "location": "Tel Aviv",
        }
        session._saved_profile = {
            "cv_path": r"C:\__nonexistent__\Ariel CV - 2026 [2].pdf",
            "cover_letter_path": r"C:\__nonexistent__\Ariel CV - 2026 [2].pdf",
            "custom__linkedin_profile__4661a6e4c0": "http://linkedin.com",
            "custom__how_did_you_hear_about_jfrog__7a1302ea68": "friend",
            "custom__follow_jfrog_to_stay_up_to_date_with_their_p__b52e1896f4": "No",
        }
        session._apply_asked_field_keys = ["location"]
        session._apply_question_idx = 1

        session._scan_easy_apply_fields = lambda _url, seed_answers=None: [
            ("location", "Location (city)", "text"),
            ("cv_path", "Resume", "file"),
            ("cover_letter_path", "Cover letter", "file"),
            ("custom__linkedin_profile__4661a6e4c0", "LinkedIn Profile", "text"),
            ("custom__how_did_you_hear_about_jfrog__7a1302ea68", "How did you hear about JFrog?", "text"),
            ("custom__follow_jfrog_to_stay_up_to_date_with_their_p__b52e1896f4", "Follow JFrog to stay up to date with their page.", "checkbox"),
        ]

        expanded = session._maybe_expand_apply_fields_via_rescan(session._current_job["url"])

        self.assertFalse(expanded)
        self.assertNotIn("I found more required questions", "\n".join(sent_messages))

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

    def test_prune_invalid_prefilled_answers_reasks_incomplete_city(self):
        session = self._make_session()
        session._persist_saved_profile = lambda: None
        session._apply_form_fields = [("location", "prompt")]
        session._apply_field_labels = {"location": "Location (city)"}
        session._apply_field_types = {"location": "text"}
        session._apply_field_options = {}
        session._apply_answers = {"location": "Aviv"}
        session._saved_profile = {"location": "Aviv"}

        invalid_labels = session._prune_invalid_prefilled_answers()

        self.assertIn("Location (city)", invalid_labels)
        self.assertNotIn("location", session._apply_answers)
        self.assertNotIn("location", session._saved_profile)

    def test_prune_invalid_prefilled_answers_keeps_valid_city(self):
        session = self._make_session()
        session._persist_saved_profile = lambda: None
        session._apply_form_fields = [("location", "prompt")]
        session._apply_field_labels = {"location": "Location (city)"}
        session._apply_field_types = {"location": "text"}
        session._apply_field_options = {}
        session._apply_answers = {"location": "Tel Aviv"}
        session._saved_profile = {"location": "Tel Aviv"}

        invalid_labels = session._prune_invalid_prefilled_answers()

        self.assertEqual([], invalid_labels)
        self.assertEqual("Tel Aviv", session._apply_answers.get("location"))
        self.assertEqual("Tel Aviv", session._saved_profile.get("location"))

    def test_load_profile_consolidates_phone_country_code_alias_keys(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        profile_path = Path(temp_dir.name) / "profile.json"
        profile_path.write_text(
            json.dumps(
                {
                    "chat_profiles": {
                        "1": {
                            "custom__phone_country_code_phone_country_code__e2d23d73d6__dup2": "Israel (+972)",
                            "custom__phone_country_code__42a596e1fa__dup2": "Israel (+972)",
                            "custom__phone_country_code_phone_country_code__e2d23d73d6": "Azerbaijan (+994)",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        with patch.dict(os.environ, {"AGENT_PROFILE_PATH": str(profile_path)}):
            session = self._make_session()

        canonical_key = "phone_country_code"
        self.assertEqual("Israel (+972)", session._saved_profile.get(canonical_key))

        profile_keys = list(session._saved_profile.keys())
        extra_aliases = [
            key
            for key in profile_keys
            if key.startswith("custom__phone_country_code") and key != canonical_key
        ]
        self.assertEqual([], extra_aliases)

        persisted = json.loads(profile_path.read_text(encoding="utf-8"))
        persisted_profile = persisted["chat_profiles"]["1"]
        self.assertEqual("Israel (+972)", persisted_profile.get(canonical_key))
        persisted_aliases = [
            key
            for key in persisted_profile.keys()
            if key.startswith("custom__phone_country_code") and key != canonical_key
        ]
        self.assertEqual([], persisted_aliases)

    def test_profile_key_for_phone_country_code_uses_stable_key(self):
        session = self._make_session()
        session._saved_profile = {"phone_country_code": "Israel (+972)"}
        scanned = [
            ("phone_country_code", "Phone country code Phone country code", "select"),
        ]

        form_fields = session._build_apply_form_fields(scanned, include_fixed_fields=False)
        field_keys = [key for key, _prompt in form_fields]

        self.assertIn("phone_country_code", field_keys)

        prefilled = {}
        for field_key, _prompt in form_fields:
            saved_value = (session._saved_profile.get(field_key) or "").strip()
            if saved_value:
                prefilled[field_key] = saved_value
        self.assertEqual(prefilled.get("phone_country_code"), "Israel (+972)")

    def test_submission_payload_log_emits_once_per_application(self):
        session = self._make_session()
        session._current_job = {
            "title": "Role",
            "company": "Comp",
            "url": "https://www.linkedin.com/jobs/view/1/",
        }
        session._apply_form_fields = [
            ("email", "prompt"),
        ]
        session._apply_field_labels = {
            "email": "Email address",
        }
        session._submission_audit_logged = False

        class _AuditLogger:
            def __init__(self):
                self.info_lines = []
                self.error_lines = []

            def info(self, msg, *args):
                self.info_lines.append(msg % args if args else msg)

            def error(self, msg, *args):
                self.error_lines.append(msg % args if args else msg)

            def warning(self, msg, *args):
                _ = (msg, args)

        audit_logger = _AuditLogger()
        session.logger = audit_logger

        answers = {"email": "ariel.samin@gmail.com"}
        session._log_submission_payload_once("linkedin_easy_apply", answers, page=None)
        session._log_submission_payload_once("external_apply", answers, page=None)

        submission_logs = [line for line in audit_logger.info_lines if "SUBMISSION_PAYLOAD" in line]
        self.assertEqual(1, len(submission_logs))
        self.assertTrue(any("SUBMISSION_PAYLOAD_DUPLICATE" in line for line in audit_logger.error_lines))


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
