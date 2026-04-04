import html
import logging
import tempfile
import unittest
from pathlib import Path

import agent_engine


class TestMobileyeSavedHtmlSummary(unittest.TestCase):
    def _make_session(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)

        db_path = Path(temp_dir.name) / "test_processed_jobs.db"
        db = agent_engine.ProcessedJobsDB(db_path)
        self.addCleanup(db.close)

        logger = logging.getLogger("test.mobileye.saved.summary")
        logger.handlers = []
        logger.addHandler(logging.NullHandler())

        session = agent_engine.TelegramJobSession(
            bot_token="dummy",
            chat_id=1,
            db=db,
            new_jobs=[],
            query="q",
            logger=logger,
            easy_apply_run_mode="normal",
        )
        return session

    def _extract_scanned_fields_via_runtime_helpers(self, session, html_text):
        scanned = []
        seen = set()

        def _profile_key_for(label: str):
            label_lower = (label or "").lower()
            for pattern, key in session.LABEL_TO_PROFILE_KEY:
                if pattern.search(label_lower):
                    return key
            return None

        def _add(label: str, field_type: str, options=None):
            clean_label = agent_engine.normalize_form_label(label or "")
            if not clean_label:
                return
            clean_type = (field_type or "text").strip().lower()
            if clean_type not in {"text", "email", "tel", "textarea", "radio", "checkbox", "select", "file"}:
                clean_type = "text"
            pk = _profile_key_for(clean_label)
            key = pk if pk else session._custom_key_from_label(clean_label)
            marker = (key, clean_label.lower(), clean_type)
            if marker in seen:
                return
            seen.add(marker)
            scanned.append((key, clean_label, clean_type, options or []))

        for item in agent_engine.extract_standard_external_fields_from_html(html_text):
            if isinstance(item, dict):
                _add(item.get("label", ""), item.get("type", "text"), item.get("options", []))

        for item in agent_engine.extract_lever_additional_fields_from_html(html_text):
            if isinstance(item, dict):
                _add(item.get("label", ""), item.get("type", "text"), item.get("options", []))

        for raw in agent_engine.extract_lever_base_template_values_from_html(html_text):
            payload = agent_engine.parse_lever_base_template_value(raw)
            if not isinstance(payload, dict):
                continue
            title = agent_engine.normalize_form_label(payload.get("text", "") or "")
            for field in (payload.get("fields") or []):
                if not isinstance(field, dict):
                    continue
                field_type_raw = (field.get("type") or "").strip().lower()
                field_text = agent_engine.normalize_form_label(field.get("text", "") or "")
                label = agent_engine.choose_card_template_question_label(title, field_text)
                options = []
                for opt in (field.get("options") or []):
                    if isinstance(opt, dict):
                        txt = agent_engine.normalize_form_label(opt.get("text", "") or "")
                    else:
                        txt = agent_engine.normalize_form_label(str(opt or ""))
                    if txt:
                        options.append(txt)

                if field_type_raw in {"dropdown", "select", "multi_select"}:
                    ftype = "select"
                elif field_type_raw in {"radio"}:
                    ftype = "radio"
                elif field_type_raw in {"checkbox", "boolean"}:
                    ftype = "checkbox"
                elif field_type_raw in {"textarea"}:
                    ftype = "textarea"
                else:
                    # Commute question in this artifact is encoded as text with options; runtime prompt treats it as binary choice.
                    ftype = "radio" if len(options) >= 2 else "text"

                _add(label, ftype, options)

        return scanned

    def test_saved_html_scanner_summary_matches_expected_mobileye_questions(self):
        html_path = Path(__file__).resolve().parents[1] / "Selected HTMLs" / "Mobileye - Senior Software Engineer & Tech Lead [Application].html"
        self.assertTrue(html_path.exists(), f"Missing artifact: {html_path}")
        html_text = html_path.read_text(encoding="utf-8", errors="ignore")

        session = self._make_session()
        scanned = self._extract_scanned_fields_via_runtime_helpers(session, html_text)

        # Build options map exactly like runtime scanner does.
        session._apply_field_options = {k: list(opts) for k, _l, _t, opts in scanned if opts}

        # Ensure LinkedIn import button is not treated as askable question.
        labels = [label.lower() for _k, label, _t, _o in scanned]
        self.assertNotIn("linkedin profile", labels)

        required_labels = [
            "Resume / CV",
            "Full name",
            "Email",
            "Phone",
            "Current location",
            "LinkedIn URL",
            "GitHub URL",
            "Add a cover letter or anything else you want to share.",
            "Family member working at Mobileye",
            "What is your gender? (optional)",
            "The position is located in Jerusalem and requires on-site work four days per week. We offer shuttle services from the Tel Aviv, Shfela, and Sharon areas. Are you ok with commuting to Jerusalem?",
            "Yes, Mobileye can contact me about future job opportunities for up to 3 years",
        ]
        for label in required_labels:
            self.assertIn(label.lower(), labels)

        scanned_triplets = [(k, l, t) for k, l, t, _o in scanned]
        session._apply_form_fields = session._build_apply_form_fields(scanned_triplets)
        session._apply_field_labels = {k: l for k, l, _t, _o in scanned}

        # Fill representative values, using first option where predefined choices exist.
        answers = {}
        for key, label, _ftype, options in scanned:
            if options:
                answers[key] = options[0]
            elif key == "cv_path":
                answers[key] = r"C:\MyData\Ariel CV - 2026 [2].pdf"
            elif key == "full_name":
                answers[key] = "Ariel Samin"
            elif key == "email":
                answers[key] = "ariel@example.com"
            elif key == "phone":
                answers[key] = "050-1234567"
            elif key == "location":
                answers[key] = "Jerusalem, Israel"
            elif key == "linkedin":
                answers[key] = "https://www.linkedin.com/in/ariel-samin"
            elif key == "github":
                answers[key] = "https://github.com/ariel-samin"
            else:
                answers[key] = f"sample: {label}"

        session._apply_answers = answers
        session._apply_asked_field_keys = [k for k, _p in session._apply_form_fields]
        session._apply_scan_unverified = False
        session._current_job = {
            "title": "Senior Software Engineer & Tech Lead",
            "company": "Mobileye",
            "url": "https://www.linkedin.com/jobs/view/4366001366/",
        }

        sent_messages = []
        session._send = lambda message: sent_messages.append(message)

        self.assertTrue(session._show_apply_summary())
        self.assertGreater(len(sent_messages), 0)

        summary_html = sent_messages[-1]
        summary_text = html.unescape(summary_html)

        # Emit the same summary block for visual validation in test output.
        print("\n=== MOBILEYE SAVED-HTML SUMMARY (TEST OUTPUT) ===")
        print(summary_text)
        print("=== END SUMMARY ===\n")

        self.assertIn("Application Summary", summary_text)
        self.assertIn("Family member working at Mobileye", summary_text)
        self.assertIn("Add a cover letter or anything else you want to share.", summary_text)
        self.assertIn("Yes, Mobileye can contact me", summary_text)


if __name__ == "__main__":
    unittest.main()
