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

    def test_section_heading_label_detection_helper(self):
        self.assertTrue(agent_engine.is_section_heading_label("SUBMIT YOUR APPLICATION"))
        self.assertTrue(agent_engine.is_section_heading_label("Links"))
        self.assertTrue(agent_engine.is_section_heading_label("Privacy policy"))
        self.assertFalse(agent_engine.is_section_heading_label("LinkedIn profile URL"))

    def test_linkedin_share_disclaimer_fragment_is_not_a_question_label(self):
        self.assertTrue(agent_engine.is_disclaimer_label("shared. Learn more"))
        self.assertTrue(agent_engine.is_linkedin_share_disclaimer_label("shared. Learn more"))

    def test_extract_question_label_prefers_linkedin_profile_over_share_disclaimer_fragment(self):
        block = """
        LinkedIn profile
        Your full LinkedIn profile will be
        shared. Learn more
        """
        label = agent_engine.extract_question_label_from_block_text(block)
        self.assertEqual(label, "LinkedIn profile")

    def test_linkedin_profile_share_blurb_is_disclaimer_label(self):
        self.assertTrue(agent_engine.is_disclaimer_label("Your full LinkedIn profile will be shared."))

    def test_disclaimer_and_option_lines_do_not_override_real_question(self):
        block = """
        This question is asked for the purpose of ensuring inclusivity and diversity. Your response is optional and will not affect the evaluation of your application
        Gender
        Male
        Female
        Non-binary
        Prefer not to say
        No, position isn't relevant for me
        """
        label = agent_engine.extract_question_label_from_block_text(block)
        self.assertEqual(label, "Gender")

    def test_section_heading_does_not_override_specific_field_label(self):
        block = """
        LINKS
        LinkedIn profile URL
        """
        label = agent_engine.extract_question_label_from_block_text(block)
        self.assertEqual(label, "LinkedIn profile URL")

    def test_checkbox_questions_default_to_yes_no_prompt_options(self):
        session = self._make_session()
        fields = session._build_apply_form_fields([
            ("custom__privacy_ack", "I agree to the privacy policy", "checkbox"),
        ])
        prompt = dict(fields)["custom__privacy_ack"]
        self.assertIn("Options:", prompt)
        self.assertIn("1) Yes", prompt)
        self.assertIn("2) No", prompt)

    def test_binary_radio_question_gets_yes_no_options(self):
        session = self._make_session()
        fields = session._build_apply_form_fields([
            (
                "custom__commute",
                "The position is located in Jerusalem and requires on-site work four days per week. Are you ok with commuting to Jerusalem?",
                "radio",
            ),
        ])
        prompt = dict(fields)["custom__commute"]
        self.assertIn("Options:", prompt)
        self.assertIn("1) Yes", prompt)
        self.assertIn("2) No", prompt)

    def test_family_member_question_not_suppressed_as_option_line(self):
        block = """
        ADDITIONAL INFORMATION
        Do you have any family member working at Mobileye?
        I don't have any family member working at Mobileye
        I have a family member working at Mobileye
        """
        label = agent_engine.extract_question_label_from_block_text(block)
        self.assertEqual(label, "Do you have any family member working at Mobileye?")

    def test_choose_card_template_question_label_prefers_concise_card_title_for_long_blurb(self):
        label = agent_engine.choose_card_template_question_label(
            card_title="Family member working at Mobileye",
            field_text=(
                "We kindly request that you make us aware if a family member of yours is currently employed by "
                "Mobileye. Due to potential issues that can arise such as conflict of interest, favoritism, "
                "personal conflicts etc., having this information will enable us to be considerate."
            ),
        )
        self.assertEqual(label, "Family member working at Mobileye")

    def test_choose_card_template_question_label_prefers_title_over_disclaimer(self):
        label = agent_engine.choose_card_template_question_label(
            card_title="What is your gender? (optional)",
            field_text=(
                "This question is asked for the purpose of ensuring inclusivity and diversity. "
                "Your response is optional and will not affect the evaluation of your application"
            ),
        )
        self.assertEqual(label, "What is your gender? (optional)")

    def test_scan_path_disambiguates_generic_custom_keys(self):
        src = inspect.getsource(agent_engine.TelegramJobSession._scan_easy_apply_fields)
        self.assertIn("def _disambiguate_generic_key", src)
        self.assertIn("is_generic_choice_label", src)
        self.assertIn("_disambiguate_generic_key(key, label", src)

    def test_scan_path_includes_hidden_required_card_selects(self):
        src = inspect.getsource(agent_engine.TelegramJobSession._scan_easy_apply_fields)
        self.assertIn("include_hidden_select", src)
        self.assertIn("cards[", src)
        self.assertIn("including hidden required select", src)

    def test_scan_path_extracts_modal_scope_html_via_locator_inner_html(self):
        src = inspect.getsource(agent_engine.TelegramJobSession._scan_easy_apply_fields)
        self.assertIn("def _extract_root_html", src)
        self.assertIn("inner_html", src)
        self.assertIn("_extract_root_html(root_obj=root, page_obj=page)", src)

    def test_scan_path_parses_hidden_card_templates(self):
        src = inspect.getsource(agent_engine.TelegramJobSession._scan_easy_apply_fields)
        self.assertIn("baseTemplate", src)
        self.assertIn("choose_card_template_question_label", src)
        self.assertIn("parse_lever_base_template_value", src)

    def test_external_scan_uses_multipass_reveal_with_prefill(self):
        src = inspect.getsource(agent_engine.TelegramJobSession._scan_easy_apply_fields)
        self.assertIn("for _pass in range(4)", src)
        self.assertIn("_prefill_required_for_scan(root, scope=None)", src)
        self.assertIn("_scroll_root_once(root)", src)

    def test_scan_prefill_prefers_synthetic_values_without_seed_answers(self):
        src = inspect.getsource(agent_engine.TelegramJobSession._scan_easy_apply_fields)
        self.assertIn("has_seed_answers = bool(seed_answers_map)", src)
        self.assertIn("if has_seed_answers:", src)
        self.assertIn("fill = _random_testing_value(label, ftype)", src)
        self.assertIn("Scan prefill override: replacing existing value", src)
        self.assertIn("if cur and _looks_scan_valid(cur, label, ftype):", src)

    def test_scan_path_force_fills_required_controls_when_stagnant(self):
        src = inspect.getsource(agent_engine.TelegramJobSession._scan_easy_apply_fields)
        self.assertIn("def _force_fill_required_controls_for_stagnation", src)
        self.assertIn("stale page detected; force-filled", src)
        self.assertIn("_force_fill_required_controls_for_stagnation(scan_page, scope=modal_scope)", src)

    def test_scan_path_uses_synthetic_file_fallback_for_required_uploads(self):
        src = inspect.getsource(agent_engine.TelegramJobSession._scan_easy_apply_fields)
        self.assertIn("def _ensure_synthetic_scan_file", src)
        self.assertIn("Scan prefill file: using synthetic", src)
        self.assertIn("scan_resume.pdf", src)
        self.assertIn("input[type='file'][required]", src)

    def test_scan_path_includes_hidden_cover_letter_file_inputs(self):
        src = inspect.getsource(agent_engine.TelegramJobSession._scan_easy_apply_fields)
        self.assertIn('include_hidden_file = True', src)
        self.assertIn('if fi_disabled:', src)
        self.assertIn('is_cover_slot = "cover" in hint_blob', src)
        self.assertIn('_add("cover_letter_path", label or "Cover letter", "file")', src)

    def test_scan_path_reuses_apply_step_filler_for_custom_widgets(self):
        src = inspect.getsource(agent_engine.TelegramJobSession._scan_easy_apply_fields)
        self.assertIn("self._fill_easy_apply_modal(page, bootstrap_answers, synthetic_cv)", src)
        self.assertIn("bootstrap_answers", src)

    def test_scan_select_prefill_skips_select_an_option_placeholder(self):
        src = inspect.getsource(agent_engine.TelegramJobSession._scan_easy_apply_fields)
        self.assertIn("select an option", src)
        self.assertIn("text.startswith(\"select \")", src)

    def test_scan_aborts_when_easy_apply_modal_not_detected_after_retry(self):
        src = inspect.getsource(agent_engine.TelegramJobSession._scan_easy_apply_fields)
        self.assertIn("Easy Apply modal did not appear after retry; aborting scan", src)
        self.assertIn("return []", src)
        self.assertIn("retry_selectors", src)

    def test_scan_canonicalizes_resume_and_follow_labels(self):
        src = inspect.getsource(agent_engine.TelegramJobSession._scan_easy_apply_fields)
        self.assertIn("display_label = \"Resume\"", src)
        self.assertIn("Follow Confidential to stay up to date with their page.", src)

    def test_scan_dedupes_on_canonical_label_not_label_type_pair(self):
        src = inspect.getsource(agent_engine.TelegramJobSession._scan_easy_apply_fields)
        self.assertIn("signature = canonical_label.lower()", src)
        self.assertIn("signature_to_index", src)
        self.assertIn("discovered[existing_index] = (existing_field_key, existing_label, chosen_type)", src)

    def test_submit_flow_uses_single_submission_audit_logger(self):
        submit_src = inspect.getsource(agent_engine.TelegramJobSession._cmd_submit_apply)
        do_apply_src = inspect.getsource(agent_engine.TelegramJobSession._do_linkedin_easy_apply)
        external_src = inspect.getsource(agent_engine.TelegramJobSession._submit_external_application_form)

        self.assertIn("force_headed=False", submit_src)
        self.assertIn("_log_submission_payload_once", do_apply_src)
        self.assertIn("_log_submission_payload_once", external_src)

    def test_submit_flow_handles_hidden_resume_inputs_and_logs_filename(self):
        fill_src = inspect.getsource(agent_engine.TelegramJobSession._fill_easy_apply_modal)

        self.assertIn("if not fi_visible and not (is_doc_slot or fi_required):", fill_src)
        self.assertIn("is_resume_slot", fill_src)
        self.assertIn("Easy Apply: uploaded CV file", fill_src)

    def test_submission_snapshot_includes_resume_document_cards(self):
        snap_src = inspect.getsource(agent_engine.TelegramJobSession._capture_visible_modal_field_snapshot)

        self.assertIn("jobs-document-card__filename", snap_src)
        self.assertIn("ui-attachment__filename", snap_src)
        self.assertIn("snapshot.append((label, filename_text))", snap_src)

    def test_saved_mobileye_html_contains_parseable_family_member_card_template(self):
        html_path = Path(__file__).resolve().parents[1] / "Selected HTMLs" / "Mobileye - Senior Software Engineer & Tech Lead [Application].html"
        self.assertTrue(html_path.exists(), f"Missing artifact: {html_path}")

        html_text = html_path.read_text(encoding="utf-8", errors="ignore")
        values = agent_engine.extract_lever_base_template_values_from_html(html_text)
        self.assertGreater(len(values), 0)

        payloads = [agent_engine.parse_lever_base_template_value(v) for v in values]
        payloads = [p for p in payloads if isinstance(p, dict)]
        self.assertGreater(len(payloads), 0)

        family_payload = None
        for payload in payloads:
            title = (payload.get("text") or "").lower()
            if "family member" in title and "mobileye" in title:
                family_payload = payload
                break

        self.assertIsNotNone(family_payload, "Family member card template not found in saved HTML")

        fields = family_payload.get("fields") or []
        self.assertGreater(len(fields), 0)
        options = []
        for field in fields:
            if isinstance(field, dict):
                for opt in (field.get("options") or []):
                    if isinstance(opt, dict):
                        text = (opt.get("text") or "").strip()
                        if text:
                            options.append(text)
        joined = " | ".join(options).lower()
        self.assertIn("don't have any family member", joined)
        self.assertIn("have a family member", joined)

    def test_saved_mobileye_html_contains_additional_information_textarea(self):
        html_path = Path(__file__).resolve().parents[1] / "Selected HTMLs" / "Mobileye - Senior Software Engineer & Tech Lead [Application].html"
        html_text = html_path.read_text(encoding="utf-8", errors="ignore")

        extracted = agent_engine.extract_lever_additional_fields_from_html(html_text)
        labels = [str(item.get("label", "")) for item in extracted if isinstance(item, dict)]
        types = [str(item.get("type", "")) for item in extracted if isinstance(item, dict)]

        joined_labels = " | ".join(labels).lower()
        self.assertIn("cover letter", joined_labels)
        self.assertIn("text", " | ".join(types).lower())

    def test_saved_mobileye_html_contains_marketing_consent_checkbox(self):
        html_path = Path(__file__).resolve().parents[1] / "Selected HTMLs" / "Mobileye - Senior Software Engineer & Tech Lead [Application].html"
        html_text = html_path.read_text(encoding="utf-8", errors="ignore")

        extracted = agent_engine.extract_lever_additional_fields_from_html(html_text)
        consent = [item for item in extracted if isinstance(item, dict) and str(item.get("type", "")).lower() == "checkbox"]
        self.assertGreater(len(consent), 0)

        label_blob = " | ".join(str(item.get("label", "")) for item in consent).lower()
        self.assertIn("mobileye can contact me", label_blob)

    def test_build_fields_keeps_mobileye_family_member_variants_separate(self):
        session = self._make_session()
        session._apply_field_options = {
            "custom__family_long": [
                "I don't have any family member working at Mobileye",
                "I have a family member working at Mobileye",
            ],
            "custom__family_short": [
                "I don't have any family member working at Mobileye",
                "I have a family member working at Mobileye",
            ],
        }
        scanned = [
            (
                "custom__family_long",
                "We kindly request that you make us aware if a family member of yours is currently employed by Mobileye.",
                "radio",
            ),
            ("custom__family_short", "Family member working at Mobileye", "radio"),
        ]
        fields = session._build_apply_form_fields(scanned)
        custom_keys = [key for key, _ in fields if key.startswith("custom__")]
        self.assertEqual(custom_keys, ["custom__family_long", "custom__family_short"])

    def test_build_fields_keeps_marketing_consent_privacy_suffix_variant_separate(self):
        session = self._make_session()
        session._apply_field_options = {
            "custom__consent_a": ["Yes", "No"],
            "custom__consent_b": ["Yes", "No"],
        }
        scanned = [
            (
                "custom__consent_a",
                "Yes, Mobileye can contact me about future job opportunities for up to 3 years Privacy policy",
                "checkbox",
            ),
            (
                "custom__consent_b",
                "Yes, Mobileye can contact me about future job opportunities for up to 3 years",
                "checkbox",
            ),
        ]
        fields = session._build_apply_form_fields(scanned)
        custom_keys = [key for key, _ in fields if key.startswith("custom__")]
        self.assertEqual(custom_keys, ["custom__consent_a", "custom__consent_b"])

    def test_build_fields_skips_linkedin_share_disclaimer_text_question(self):
        session = self._make_session()
        scanned = [
            ("custom__linkedin_blurb", "Your full LinkedIn profile will be", "text"),
            ("custom__linkedin_action", "LinkedIn profile", "action"),
        ]
        session._apply_field_options = {
            "custom__linkedin_action": ["Share", "Skip"],
        }
        fields = session._build_apply_form_fields(scanned)
        keys = [key for key, _ in fields]
        self.assertNotIn("custom__linkedin_blurb", keys)
        self.assertIn("custom__linkedin_action", keys)


if __name__ == "__main__":
    unittest.main()
