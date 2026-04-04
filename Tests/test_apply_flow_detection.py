import unittest
import inspect

import agent_engine


class TestApplyFlowDetection(unittest.TestCase):
    def test_has_generic_apply_fallback_selectors(self):
        selectors = agent_engine.TelegramJobSession._GENERAL_APPLY_BUTTON_SELECTORS
        self.assertTrue(any("Apply with LinkedIn" in s for s in selectors))
        self.assertTrue(any("Apply on company site" in s for s in selectors))
        self.assertTrue(any("button:has-text('Apply')" == s for s in selectors))

    def test_detects_popup_external_apply(self):
        flow = agent_engine.TelegramJobSession._classify_apply_flow_transition(
            pre_click_url="https://www.linkedin.com/jobs/view/123/",
            post_click_url="https://www.linkedin.com/jobs/view/123/",
            pre_page_count=1,
            post_page_count=2,
        )
        self.assertEqual(flow, "external_popup")

    def test_detects_same_tab_external_domain(self):
        flow = agent_engine.TelegramJobSession._classify_apply_flow_transition(
            pre_click_url="https://www.linkedin.com/jobs/view/123/",
            post_click_url="https://jobs.lever.co/mobileye/apply",
            pre_page_count=1,
            post_page_count=1,
        )
        self.assertEqual(flow, "external_same_tab")

    def test_detects_same_tab_non_job_linkedin_page(self):
        flow = agent_engine.TelegramJobSession._classify_apply_flow_transition(
            pre_click_url="https://www.linkedin.com/jobs/view/123/",
            post_click_url="https://www.linkedin.com/redir/redirect?url=https%3A%2F%2Fjobs.example.com",
            pre_page_count=1,
            post_page_count=1,
        )
        self.assertEqual(flow, "external_same_tab")

    def test_detects_linkedin_internal_jobs_navigation(self):
        flow = agent_engine.TelegramJobSession._classify_apply_flow_transition(
            pre_click_url="https://www.linkedin.com/jobs/view/4366001366/",
            post_click_url="https://www.linkedin.com/jobs/collections/similar-jobs/?currentJobId=4377246354&referenceJobId=4366001366",
            pre_page_count=1,
            post_page_count=1,
        )
        self.assertEqual(flow, "linkedin_internal_navigation")

    def test_keeps_easy_apply_when_staying_on_job_page(self):
        flow = agent_engine.TelegramJobSession._classify_apply_flow_transition(
            pre_click_url="https://www.linkedin.com/jobs/view/123/",
            post_click_url="https://www.linkedin.com/jobs/view/123/",
            pre_page_count=1,
            post_page_count=1,
        )
        self.assertEqual(flow, "easy_apply")

    def test_scan_path_uses_flow_classifier(self):
        src = inspect.getsource(agent_engine.TelegramJobSession._scan_easy_apply_fields)
        self.assertIn("_classify_apply_flow_transition", src)
        self.assertIn("scan_flow_type", src)
        self.assertIn("_GENERAL_APPLY_BUTTON_SELECTORS", src)
        self.assertIn("generic Apply", src)

    def test_submit_path_uses_flow_classifier(self):
        src = inspect.getsource(agent_engine.TelegramJobSession._do_linkedin_easy_apply)
        self.assertIn("_classify_apply_flow_transition", src)
        self.assertIn("external application flow", src)
        self.assertIn("_GENERAL_APPLY_BUTTON_SELECTORS", src)
        self.assertIn("clicked generic Apply fallback entry", src)


if __name__ == "__main__":
    unittest.main()
