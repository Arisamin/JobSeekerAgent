"""
Unit tests for Easy Apply scan modal-open helpers.
Covers the login-redirect detection logic that guards _scan_easy_apply_fields.
"""
import unittest

from agent_engine import is_linkedin_login_page


class TestIsLinkedInLoginPage(unittest.TestCase):
    def test_login_url_detected(self):
        self.assertTrue(is_linkedin_login_page("https://www.linkedin.com/login"))

    def test_checkpoint_url_detected(self):
        self.assertTrue(is_linkedin_login_page("https://www.linkedin.com/checkpoint/lg/login-submit"))

    def test_uas_login_detected(self):
        self.assertTrue(is_linkedin_login_page("https://www.linkedin.com/uas/login"))

    def test_authwall_detected(self):
        self.assertTrue(is_linkedin_login_page("https://www.linkedin.com/authwall?trk=foo"))

    def test_normal_job_url_not_login(self):
        self.assertFalse(is_linkedin_login_page("https://www.linkedin.com/jobs/view/4299764895/"))

    def test_empty_url_not_login(self):
        self.assertFalse(is_linkedin_login_page(""))


if __name__ == "__main__":
    unittest.main()
