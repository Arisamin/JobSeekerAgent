import unittest
from pathlib import Path

import agent_engine


class TestLinkedInReviewFieldExtraction(unittest.TestCase):
    def _load_confidential_review_html(self) -> str:
        html_path = (
            Path(__file__).resolve().parents[1]
            / "Selected HTMLs"
            / "Senior Software Engineer _ Confidential _ LinkedIn.html"
        )
        self.assertTrue(html_path.exists(), f"Missing artifact: {html_path}")
        return html_path.read_text(encoding="utf-8", errors="ignore")

    def test_extracts_required_review_rows_resume_and_follow_checkbox(self):
        html_text = self._load_confidential_review_html()
        extracted = agent_engine.extract_linkedin_review_fields_from_html(html_text)

        labels = {str(item.get("label", "")).strip().lower() for item in extracted}

        self.assertIn("email address", labels)
        self.assertIn("phone country code", labels)
        self.assertIn("mobile phone number", labels)
        self.assertIn(
            "how many years of work experience do you have with distributed systems?",
            labels,
        )
        self.assertIn(
            "how many years of work experience do you have with cloud infrastructure?",
            labels,
        )
        self.assertIn("resume", labels)
        self.assertIn("follow confidential to stay up to date with their page.", labels)

    def test_extracts_expected_field_types_for_summary_specific_items(self):
        html_text = self._load_confidential_review_html()
        extracted = agent_engine.extract_linkedin_review_fields_from_html(html_text)

        by_label = {
            str(item.get("label", "")).strip().lower(): str(item.get("type", "")).strip().lower()
            for item in extracted
        }

        self.assertEqual("file", by_label.get("resume"))
        self.assertEqual(
            "checkbox",
            by_label.get("follow confidential to stay up to date with their page."),
        )
        self.assertEqual("number", by_label.get("how many years of work experience do you have with cloud infrastructure?"))


if __name__ == "__main__":
    unittest.main()
