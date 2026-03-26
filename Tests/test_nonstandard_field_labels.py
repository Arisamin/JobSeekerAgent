import unittest

from agent_engine import extract_question_label_from_block_text, normalize_form_label


class TestNonStandardFieldLabels(unittest.TestCase):
    def test_extracts_question_line_from_block_text(self):
        block = """
        Are you currently based in Bangkok or open to relocate to Bangkok? *
        Yes
        No
        """
        self.assertEqual(
            extract_question_label_from_block_text(block),
            "Are you currently based in Bangkok or open to relocate to Bangkok?",
        )

    def test_normalize_form_label_removes_required_marker(self):
        self.assertEqual(
            normalize_form_label("  Do you have a personal relationship? (required) *  "),
            "Do you have a personal relationship?",
        )

    def test_extracts_first_meaningful_line_when_no_question_mark(self):
        block = """
        Select language
        Choose
        """
        self.assertEqual(
            extract_question_label_from_block_text(block),
            "Select language",
        )


if __name__ == "__main__":
    unittest.main()
