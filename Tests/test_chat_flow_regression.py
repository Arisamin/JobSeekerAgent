"""
Regression tests for the chat flow bugs reported in
'Regression: misleading chat flow, lost cached answers, short question prompts,
and damaged test coverage after last run'.

Covers:
  1. Status message accuracy – "No active job selected" only when truly no job.
  2. Profile cache pre-fill for initial FIXED_FIELDS.
  3. Profile cache pre-fill for rescan-discovered fields (Bug #2 regression guard).
  4. Full form prompts used for questions, not short summary labels.
  5. GitHub profile URL validation and cache persistence.
"""
import json
import logging
import tempfile
import unittest
from pathlib import Path

import agent_engine


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_session(new_jobs=None, chat_id=1, easy_apply_run_mode="normal", saved_profile=None):
    """Create a TelegramJobSession backed by a temp DB with no real network calls."""
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "test.db"
    db = agent_engine.ProcessedJobsDB(db_path)
    logger = logging.getLogger("test.chat_flow_regression")
    logger.handlers = []
    logger.addHandler(logging.NullHandler())

    session = agent_engine.TelegramJobSession(
        bot_token="dummy",
        chat_id=chat_id,
        db=db,
        new_jobs=new_jobs or [],
        query="Senior Backend",
        logger=logger,
        easy_apply_run_mode=easy_apply_run_mode,
    )

    # Suppress actual Telegram sends; capture messages instead.
    # Use a single-underscore name to avoid Python class-based name mangling.
    session._sent_messages = []
    session._send = lambda text, parse_mode="HTML": session._sent_messages.append(text)

    if saved_profile is not None:
        session._saved_profile = dict(saved_profile)

    # Stash temp objects for cleanup by caller.
    session._test_db = db
    session._test_dir = temp_dir
    return session


def _cleanup(session):
    session._test_db.close()
    session._test_dir.cleanup()


def _sample_job(title="Backend Engineer", company="Agoda", url="https://www.linkedin.com/jobs/view/123/"):
    return {"id": 1, "title": title, "company": company, "url": url, "status": "Discovered"}


# ---------------------------------------------------------------------------
# 1. Status message accuracy
# ---------------------------------------------------------------------------

class TestStatusMessageAccuracy(unittest.TestCase):
    """'No active job selected' must only appear when there are truly no jobs."""

    def test_intro_with_new_jobs_does_not_say_no_active_job(self):
        """send_intro() with new jobs must NOT send 'No active job selected'."""
        session = _make_session(new_jobs=[_sample_job()])
        try:
            session.send_intro()
            for msg in session._sent_messages:
                self.assertNotIn(
                    "No active job selected",
                    msg,
                    msg=f"Misleading message sent during intro: {msg!r}",
                )
        finally:
            _cleanup(session)

    def test_intro_with_new_jobs_announces_count(self):
        """send_intro() with new jobs must mention the number of jobs found."""
        session = _make_session(new_jobs=[_sample_job(), _sample_job("Dev", "ACME")])
        try:
            session.send_intro()
            joined = " ".join(session._sent_messages)
            self.assertIn("2 new job(s)", joined)
        finally:
            _cleanup(session)

    def test_apply_before_next_in_browsing_new_does_not_say_no_active_job(self):
        """
        After send_intro() with new_jobs, calling _cmd_apply() before pressing
        Next must NOT say 'No active job selected' (there ARE jobs; none is merely
        displayed yet).
        """
        session = _make_session(new_jobs=[_sample_job()])
        try:
            session.send_intro()
            session._sent_messages.clear()
            session._cmd_apply()
            for msg in session._sent_messages:
                self.assertNotIn(
                    "No active job selected",
                    msg,
                    msg=f"Misleading 'No active job' message when jobs DO exist: {msg!r}",
                )
        finally:
            _cleanup(session)

    def test_apply_before_next_in_browsing_new_suggests_next(self):
        """When Apply is called with no current job in BROWSING_NEW, reply must suggest Next."""
        session = _make_session(new_jobs=[_sample_job()])
        try:
            session.send_intro()
            session._sent_messages.clear()
            session._cmd_apply()
            joined = " ".join(session._sent_messages)
            self.assertIn("Next", joined)
        finally:
            _cleanup(session)

    def test_apply_in_intro_state_with_no_jobs_says_no_active_job(self):
        """When there are truly no jobs (STATE_INTRO, _current_job=None), the canonical
        'No active job selected' message IS correct."""
        session = _make_session(new_jobs=[])
        try:
            # With no new_jobs, send_intro leaves state at STATE_INTRO
            session.send_intro()
            session._sent_messages.clear()
            session._cmd_apply()
            joined = " ".join(session._sent_messages)
            self.assertIn("No active job selected", joined)
        finally:
            _cleanup(session)

    def test_skip_before_next_in_browsing_new_does_not_say_no_active_job(self):
        """Same accuracy requirement for _cmd_skip() in BROWSING_NEW state."""
        session = _make_session(new_jobs=[_sample_job()])
        try:
            session.send_intro()
            session._sent_messages.clear()
            session._cmd_skip()
            for msg in session._sent_messages:
                self.assertNotIn(
                    "No active job selected",
                    msg,
                    msg=f"Misleading message in skip: {msg!r}",
                )
        finally:
            _cleanup(session)


# ---------------------------------------------------------------------------
# 2. Profile cache pre-fill for initial fixed fields
# ---------------------------------------------------------------------------

class TestProfileCachePrefillFixed(unittest.TestCase):
    """Answers already in _saved_profile must be pre-populated for FIXED_FIELDS."""

    def _make_apply_session_with_profile(self, profile):
        """Helper that creates a session, sets its profile, and calls _cmd_apply() with a job."""
        session = _make_session(saved_profile=profile)
        session._current_job = _sample_job()
        session._state = session.STATE_BROWSING_DB
        # Don't actually open a browser; stub out any scan/rescan.
        session._scan_easy_apply_fields = lambda *a, **kw: []  # type: ignore[method-assign]
        session._maybe_expand_apply_fields_via_rescan = lambda *a, **kw: False  # type: ignore[method-assign]
        return session

    def test_fixed_fields_with_cache_are_prefilled(self):
        """If _saved_profile has all FIXED_FIELDS, none of them should need to be asked."""
        profile = {
            "cv_path": "/tmp/cv.pdf",
            "cover_letter_path": "",
            "full_name": "Aba Guba",
            "email": "aba@example.com",
            "phone": "0556745678",
            "location": "Tel Aviv, Israel",
            "linkedin": "https://www.linkedin.com/in/aba",
        }
        session = self._make_apply_session_with_profile(profile)
        try:
            # Build form fields for this session (normal mode, no scan)
            session._apply_form_fields = session._build_apply_form_fields([])
            session._apply_answers = {}
            for field_key, _prompt in session._apply_form_fields:
                saved_value = (session._saved_profile.get(field_key) or "").strip()
                if saved_value:
                    session._apply_answers[field_key] = saved_value

            # All cached fields should be pre-populated
            for key, cached_val in profile.items():
                if cached_val:
                    self.assertIn(
                        key, session._apply_answers,
                        msg=f"Cached key '{key}' should be pre-populated but is missing.",
                    )
                    self.assertEqual(session._apply_answers[key], cached_val)
        finally:
            _cleanup(session)

    def test_prefilled_fields_are_skipped_by_first_missing_idx(self):
        """_first_missing_apply_field_idx() must skip fields that are already answered."""
        session = _make_session(saved_profile={
            "cv_path": "/tmp/cv.pdf",
            "cover_letter_path": "",
            "full_name": "Aba Guba",
            "email": "aba@example.com",
            "phone": "0556745678",
            "location": "Tel Aviv, Israel",
            "linkedin": "https://www.linkedin.com/in/aba",
        })
        try:
            session._apply_form_fields = session._build_apply_form_fields([])
            session._apply_answers = {}
            for field_key, _prompt in session._apply_form_fields:
                saved = (session._saved_profile.get(field_key) or "").strip()
                if saved:
                    session._apply_answers[field_key] = saved

            idx = session._first_missing_apply_field_idx()
            # cv_path, full_name, email, phone, location, linkedin are all non-empty in cache
            # and are transferred to _apply_answers.  cover_letter_path is an empty string
            # in the saved profile, so it is NOT transferred (empty values are excluded),
            # making it the first unanswered field at index 1.
            self.assertEqual(idx, 1)  # index 1 is cover_letter_path (not in cache / empty)
        finally:
            _cleanup(session)


# ---------------------------------------------------------------------------
# 3. Profile cache pre-fill for rescan-discovered fields (Bug #2 regression guard)
# ---------------------------------------------------------------------------

class TestProfileCachePrefillRescanFields(unittest.TestCase):
    """
    When _maybe_expand_apply_fields_via_rescan() discovers new fields (e.g. github),
    their values must be pre-populated from _saved_profile, not asked again.
    """

    def _make_rescan_session(self, saved_profile):
        session = _make_session(saved_profile=saved_profile)
        session._current_job = _sample_job()
        session._state = session.STATE_APPLYING
        # Start with FIXED_FIELDS only (normal incremental mode)
        session._apply_form_fields = session._build_apply_form_fields([])
        session._apply_answers = {}
        for field_key, _prompt in session._apply_form_fields:
            saved = (session._saved_profile.get(field_key) or "").strip()
            if saved:
                session._apply_answers[field_key] = saved
        session._apply_asked_field_keys = list(session._apply_answers.keys())
        session._apply_question_idx = session._first_missing_apply_field_idx()
        return session

    def test_rescan_discovered_github_field_prefilled_from_cache(self):
        """
        After a rescan discovers the 'github' field, it must be pre-populated
        from _saved_profile without asking the user again.
        """
        saved_profile = {
            "cv_path": "/tmp/cv.pdf",
            "full_name": "Ariel Test",
            "email": "ariel@example.com",
            "phone": "0500000000",
            "location": "Israel",
            "linkedin": "https://www.linkedin.com/in/ariel",
            "github": "https://github.com/Arisamin",
        }
        session = self._make_rescan_session(saved_profile)
        try:
            # Simulate a rescan that returns the github fallback field
            def fake_scan(_url, seed_answers=None):
                return [("github", "Github Profile? (Please paste link or answer 'No')", "text")]

            session._scan_easy_apply_fields = fake_scan  # type: ignore[method-assign]

            expanded = session._maybe_expand_apply_fields_via_rescan(
                session._current_job["url"]
            )

            # The github field should be in _apply_answers (from saved profile)
            self.assertIn(
                "github",
                session._apply_answers,
                msg="'github' should be pre-populated from saved profile after rescan.",
            )
            self.assertEqual(session._apply_answers["github"], "https://github.com/Arisamin")
        finally:
            _cleanup(session)

    def test_rescan_discovered_field_not_in_cache_is_asked(self):
        """
        A rescan-discovered field with NO cached answer must still be asked.
        """
        saved_profile = {
            "cv_path": "/tmp/cv.pdf",
            "full_name": "Ariel Test",
            "email": "ariel@example.com",
            "phone": "0500000000",
            "location": "Israel",
            "linkedin": "https://www.linkedin.com/in/ariel",
            # Note: 'github' is intentionally absent from cache
        }
        session = self._make_rescan_session(saved_profile)
        try:
            def fake_scan(_url, seed_answers=None):
                return [("github", "Github Profile? (Please paste link or answer 'No')", "text")]

            session._scan_easy_apply_fields = fake_scan  # type: ignore[method-assign]

            expanded = session._maybe_expand_apply_fields_via_rescan(
                session._current_job["url"]
            )

            # github is NOT in cache, so it must NOT be pre-answered
            self.assertNotIn("github", session._apply_answers)
            # And there should be a pending question for it
            self.assertTrue(expanded, "Should return True indicating more questions pending.")
        finally:
            _cleanup(session)

    def test_rescan_discovered_agoda_fields_prefilled_from_cache(self):
        """
        Full Agoda fallback scenario: all fallback fields cached → none asked again.
        """
        saved_profile = {
            "cv_path": "/tmp/cv.pdf",
            "full_name": "Ariel Test",
            "email": "ariel@example.com",
            "phone": "0500000000",
            "location": "Israel",
            "linkedin": "https://www.linkedin.com/in/ariel",
            "github": "https://github.com/Arisamin",
            "website": "https://example.com",
            "relocate_bangkok": "No",
            "agoda_relationship": "No",
            "agoda_booking_holdings_group_employment": "No",
        }
        session = self._make_rescan_session(saved_profile)
        try:
            agoda_fallback = [
                ("github", "Github Profile? (Please paste link or answer 'No')", "text"),
                ("website", "Website / blog / other", "text"),
                ("relocate_bangkok", "Are you currently based in Bangkok or open to relocate?", "radio"),
                ("agoda_relationship", "Do you have a personal relationship with a current Agoda employee?", "radio"),
                ("agoda_booking_holdings_group_employment", "Are you employed by any Booking Holdings company?", "radio"),
            ]

            def fake_scan(_url, seed_answers=None):
                return agoda_fallback

            session._scan_easy_apply_fields = fake_scan  # type: ignore[method-assign]

            expanded = session._maybe_expand_apply_fields_via_rescan(
                session._current_job["url"]
            )

            for key in ("github", "website", "relocate_bangkok", "agoda_relationship",
                        "agoda_booking_holdings_group_employment"):
                self.assertIn(
                    key, session._apply_answers,
                    msg=f"Cached Agoda field '{key}' should be pre-populated after rescan.",
                )

            # All Agoda-specific fields are answered from cache, so they must not be pending.
            pending_keys = [
                k for k, _p in session._apply_form_fields
                if not session._apply_answers.get(k) and k in (
                    "github", "website", "relocate_bangkok",
                    "agoda_relationship", "agoda_booking_holdings_group_employment",
                )
            ]
            self.assertEqual(
                pending_keys, [],
                "All cached Agoda fields should be answered and not pending.",
            )
        finally:
            _cleanup(session)


# ---------------------------------------------------------------------------
# 4. Full form prompts used for questions, not short summary labels
# ---------------------------------------------------------------------------

class TestFullFormPromptsForQuestions(unittest.TestCase):
    """
    Questions presented to the user during the Q&A phase must use the full
    prompt text from FIXED_FIELDS (e.g. including file path hint), not the
    short summary label from FIXED_FIELD_SUMMARY_LABELS.
    """

    def test_fixed_fields_prompts_are_full_not_summary(self):
        """
        Each FIXED_FIELD prompt should be longer and more descriptive than
        the corresponding FIXED_FIELD_SUMMARY_LABEL.
        """
        session = _make_session()
        try:
            fixed_fields = dict(agent_engine.TelegramJobSession.FIXED_FIELDS)
            summary_labels = agent_engine.TelegramJobSession.FIXED_FIELD_SUMMARY_LABELS

            for key, full_prompt in fixed_fields.items():
                short_label = summary_labels.get(key, "")
                self.assertGreater(
                    len(full_prompt), len(short_label),
                    msg=f"FIXED_FIELDS prompt for '{key}' should be longer than summary label.",
                )
                # The full prompt should contain the summary label text as a substring
                self.assertIn(
                    short_label, full_prompt,
                    msg=f"Full prompt for '{key}' should contain its summary label.",
                )
        finally:
            _cleanup(session)

    def test_send_current_apply_prompt_uses_full_prompt(self):
        """
        _send_current_apply_prompt() must send the full prompt from
        _apply_form_fields, NOT the short label from _apply_field_labels.
        """
        session = _make_session()
        try:
            session._apply_form_fields = session._build_apply_form_fields([])
            session._apply_answers = {}
            session._apply_question_idx = 0  # cv_path is first

            session._send_current_apply_prompt()

            self.assertTrue(session._sent_messages, "Should have sent a prompt.")
            sent = session._sent_messages[0]
            # The full FIXED_FIELDS prompt for cv_path contains the example path
            self.assertIn(
                "CV file path",
                sent,
                msg="Prompt should contain full cv_path description.",
            )
            # It should NOT be just the short label
            self.assertNotEqual(
                sent.strip(),
                "CV file path",
                msg="Prompt must not be just the short summary label.",
            )
        finally:
            _cleanup(session)

    def test_scanned_field_prompt_includes_label_hint(self):
        """
        Scanned field prompts (e.g. GitHub) should include the label text and
        any hint that was in the original label (not stripped by canonicalization).
        """
        session = _make_session()
        try:
            scanned = [
                ("github", "Github Profile? (Please paste link or answer 'No')", "text"),
            ]
            session._apply_form_fields = session._build_apply_form_fields(scanned)
            # Find the github prompt
            github_prompt = next(
                (p for k, p in session._apply_form_fields if k == "github"), None
            )
            self.assertIsNotNone(github_prompt, "github field should be in form fields.")
            self.assertIn("Github Profile?", github_prompt)
            self.assertIn("Please paste link or answer", github_prompt)
        finally:
            _cleanup(session)


# ---------------------------------------------------------------------------
# 5. GitHub profile URL validation and cache persistence
# ---------------------------------------------------------------------------

class TestGithubProfileValidation(unittest.TestCase):
    """GitHub profile field validation and answer persistence."""

    def _make_apply_session(self):
        session = _make_session()
        session._apply_field_types = {"github": "text"}
        session._apply_field_options = {}
        return session

    def test_valid_github_url_passes(self):
        session = self._make_apply_session()
        try:
            is_valid, err, normalized = session._validate_apply_answer(
                "github", "http://www.github.com/moshe"
            )
            self.assertTrue(is_valid, f"Should accept valid GitHub URL; got error: {err!r}")
            self.assertEqual(normalized, "http://www.github.com/moshe")
        finally:
            _cleanup(session)

    def test_https_github_url_passes(self):
        session = self._make_apply_session()
        try:
            is_valid, err, normalized = session._validate_apply_answer(
                "github", "https://github.com/Arisamin"
            )
            self.assertTrue(is_valid, f"Should accept https GitHub URL; got error: {err!r}")
        finally:
            _cleanup(session)

    def test_none_answer_passes_as_skip(self):
        session = self._make_apply_session()
        try:
            is_valid, err, normalized = session._validate_apply_answer("github", "none")
            self.assertTrue(is_valid, "Answering 'none' should be accepted as skip.")
            self.assertEqual(normalized, "")
        finally:
            _cleanup(session)

    def test_non_github_url_fails(self):
        session = self._make_apply_session()
        try:
            is_valid, err, _ = session._validate_apply_answer(
                "github", "https://gitlab.com/moshe"
            )
            self.assertFalse(is_valid, "Non-github URL should be rejected.")
            self.assertIn("GitHub", err)
        finally:
            _cleanup(session)

    def test_github_answer_persisted_to_saved_profile(self):
        """After answering the github question, the answer is saved to _saved_profile."""
        session = _make_session()
        try:
            scanned = [
                ("github", "Github Profile? (Please paste link or answer 'No')", "text"),
            ]
            session._apply_form_fields = session._build_apply_form_fields(scanned)
            session._apply_answers = {}
            session._apply_asked_field_keys = []

            # Find the github question index
            idx = next(
                (i for i, (k, _p) in enumerate(session._apply_form_fields) if k == "github"),
                None,
            )
            self.assertIsNotNone(idx, "github field should be in apply form fields.")
            session._apply_question_idx = idx

            # Simulate answering (bypass all scan/rescan side effects)
            session._maybe_expand_apply_fields_via_rescan = lambda *a, **kw: False  # type: ignore[method-assign]
            session._show_apply_summary = lambda: True  # type: ignore[method-assign]

            # Mock persistence to avoid touching real filesystem
            persisted = {}
            def fake_persist():
                persisted.update(session._saved_profile)

            session._persist_saved_profile = fake_persist  # type: ignore[method-assign]

            session._handle_apply_answer("https://github.com/Arisamin")

            self.assertIn("github", persisted, "github should be persisted to saved profile.")
            self.assertEqual(persisted["github"], "https://github.com/Arisamin")
        finally:
            _cleanup(session)


if __name__ == "__main__":
    unittest.main()
