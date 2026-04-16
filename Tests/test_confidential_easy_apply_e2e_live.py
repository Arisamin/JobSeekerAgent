import html
import logging
import os
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import agent_engine


class TestConfidentialEasyApplyE2ELive(unittest.TestCase):
    JOB_URL = "https://www.linkedin.com/jobs/view/4400959935/"
    # Ordered, approved, hard-coded contract for user-provided/selected/checked inputs.
    # Tuple format: (label, field_type, predefined_answer, predefined_options)
    EXPECTED_USER_DECISION_FIELDS = [
        ("Email address", "email", "ariel.samin@gmail.com", []),
        ("Phone country code", "select", "Israel (+972)", ["Israel (+972)"]),
        ("Mobile phone number", "tel", "050123456789", []),
        (
            "How many years of work experience do you have with Distributed Systems?",
            "number",
            "2",
            [],
        ),
        (
            "How many years of work experience do you have with Cloud Infrastructure?",
            "number",
            "2",
            [],
        ),
        ("Resume", "file", "my CV.pdf", []),
        (
            "Follow Confidential to stay up to date with their page.",
            "checkbox",
            "unchecked",
            ["unchecked", "checked"],
        ),
    ]

    def _make_session(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)

        db_path = Path(temp_dir.name) / "test_processed_jobs.db"
        db = agent_engine.ProcessedJobsDB(db_path)
        self.addCleanup(db.close)

        logger = logging.getLogger("test.confidential.easyapply.e2e.live")
        logger.handlers = []
        logger.addHandler(logging.NullHandler())

        session = agent_engine.TelegramJobSession(
            bot_token="dummy",
            chat_id=1,
            db=db,
            new_jobs=[],
            query="q",
            logger=logger,
            easy_apply_run_mode="search",
        )
        return session

    def _normalize_label(self, label: str) -> str:
        normalized = agent_engine.normalize_form_label(label or "")
        normalized = re.sub(r"\s+", " ", normalized).strip().lower()
        normalized = normalized.rstrip(".")

        # LinkedIn review blocks can duplicate visible/hidden text into a single
        # extracted label (e.g. "email address email address"). Collapse that form
        # so equality checks do not create false misses.
        parts = normalized.split()
        if len(parts) >= 2 and len(parts) % 2 == 0:
            half = len(parts) // 2
            if parts[:half] == parts[half:]:
                normalized = " ".join(parts[:half])

        return normalized

    def _label_match_candidates(self, label: str) -> set:
        base = self._normalize_label(label)
        candidates = {base}
        if not base:
            return candidates

        # Add punctuation-stripped and compact variants for robust matching.
        compact = re.sub(r"[\W_]+", " ", base).strip()
        if compact:
            candidates.add(compact)

        # If trailing parenthetical exists, include version without it.
        no_paren = re.sub(r"\s*\([^)]*\)\s*$", "", base).strip()
        if no_paren:
            candidates.add(no_paren)

        return {c for c in candidates if c}

    def _write_discovery_report(
        self,
        discovered: list,
        found_rows: list,
        missed_rows: list,
    ) -> Path:
        report_dir = Path(__file__).resolve().parents[1] / "Reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = report_dir / f"confidential_easy_apply_discovery_report_{stamp}.md"

        lines = []
        lines.append("# Confidential Easy Apply Discovery Report")
        lines.append(f"- Generated: {datetime.now().isoformat()}")
        lines.append(f"- Job URL: {self.JOB_URL}")
        lines.append("")
        lines.append("## Expected User-Provided/Chosen/Checked Fields (Hard-Coded)")
        for idx, (label, ftype, answer, options) in enumerate(self.EXPECTED_USER_DECISION_FIELDS, 1):
            options_text = ", ".join(options) if options else "(none)"
            lines.append(f"{idx}. text={label} | type={ftype} | predefined_answer={answer} | predefined_options={options_text}")

        lines.append("")
        lines.append("## Agent Discovered Fields")
        if discovered:
            for idx, (_key, label, ftype) in enumerate(discovered, 1):
                lines.append(f"{idx}. text={label} | type={ftype}")
        else:
            lines.append("(none)")

        lines.append("")
        lines.append("## Found Expected Fields")
        if found_rows:
            for row in found_rows:
                lines.append(
                    f"- expected #{row['index']} text={row['expected_label']} | expected_type={row['expected_type']} | discovered_type={row['discovered_type']}"
                )
        else:
            lines.append("(none)")

        lines.append("")
        lines.append("## Missed Expected Fields")
        if missed_rows:
            for row in missed_rows:
                lines.append(
                    f"- expected #{row['index']} text={row['expected_label']} | expected_type={row['expected_type']} | predefined_answer={row['predefined_answer']}"
                )
        else:
            lines.append("(none)")

        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report_path

    def test_live_scan_matches_hardcoded_expected_user_decision_fields(self):
        if os.environ.get("RUN_CONFIDENTIAL_LINKEDIN_E2E", "0") != "1":
            self.skipTest(
                "Set RUN_CONFIDENTIAL_LINKEDIN_E2E=1 to run live LinkedIn scan parity test for job 4400959935."
            )

        session = self._make_session()
        scanned = session._scan_easy_apply_fields(self.JOB_URL)

        discovered_by_label = {}
        for _key, label, ftype in scanned:
            for candidate in self._label_match_candidates(label):
                if candidate in discovered_by_label:
                    continue
                discovered_by_label[candidate] = {
                    "label": label,
                    "type": (ftype or "").strip().lower(),
                }

        found_rows = []
        missed_rows = []
        for idx, (expected_label, expected_type, predefined_answer, _options) in enumerate(
            self.EXPECTED_USER_DECISION_FIELDS,
            1,
        ):
            hit = None
            for candidate in self._label_match_candidates(expected_label):
                hit = discovered_by_label.get(candidate)
                if hit:
                    break
            if hit:
                found_rows.append(
                    {
                        "index": idx,
                        "expected_label": expected_label,
                        "expected_type": expected_type,
                        "discovered_type": hit["type"],
                    }
                )
            else:
                missed_rows.append(
                    {
                        "index": idx,
                        "expected_label": expected_label,
                        "expected_type": expected_type,
                        "predefined_answer": predefined_answer,
                    }
                )

        report_path = self._write_discovery_report(
            discovered=scanned,
            found_rows=found_rows,
            missed_rows=missed_rows,
        )

        self.assertGreater(len(scanned), 0, "Live scan returned zero fields")
        self.assertEqual(
            [],
            missed_rows,
            f"Missed expected user decision fields. See report: {report_path}",
        )

        # Also verify summary contract for this run: all scraped fields must appear exactly once.
        session._apply_form_fields = session._build_apply_form_fields(scanned, include_fixed_fields=False)
        session._apply_answers = {
            key: "2" for key, _prompt in session._apply_form_fields
        }
        session._apply_asked_field_keys = []
        session._current_job = {
            "title": "Senior Software Engineer",
            "company": "Confidential",
            "url": self.JOB_URL,
        }

        sent_messages = []
        session._send = lambda message: sent_messages.append(message)
        self.assertTrue(session._show_apply_summary())
        self.assertTrue(sent_messages)

        summary = sent_messages[-1]
        self.assertEqual(
            summary.count("• Q"),
            len(session._apply_form_fields),
            "Summary must include every scraped field exactly once.",
        )


if __name__ == "__main__":
    unittest.main()
