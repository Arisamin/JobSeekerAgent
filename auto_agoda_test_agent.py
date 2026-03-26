from __future__ import annotations

import argparse
import html
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Ensure the terminal can handle Unicode (emoji, Hebrew, etc.) on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

import agent_engine as engine


class AutoAgodaTestAgent:
    def __init__(
        self,
        base_dir: Path,
        chat_id: int,
        job_match: str,
        run_scrape: bool,
        headless_scrape: bool,
        max_jobs: int,
        query: str,
        easy_apply_run_mode: str,
    ):
        self.base_dir = base_dir
        self.chat_id = chat_id
        self.job_match = (job_match or "agoda").strip().lower()
        self.run_scrape = run_scrape
        self.headless_scrape = headless_scrape
        self.max_jobs = max_jobs
        self.query = query
        mode = (easy_apply_run_mode or "testing").strip().lower()
        self.easy_apply_run_mode = mode if mode in {"normal", "testing"} else "testing"

        self.logger = engine.build_logger(base_dir)
        self.db = engine.ProcessedJobsDB(base_dir / "processed_jobs.db")
        self.session: Optional[engine.TelegramJobSession] = None
        self.messages: List[str] = []

    def _send_capture(self, text: str, parse_mode: str = "HTML") -> None:
        _ = parse_mode
        self.messages.append(text)

    def _render_plain(self, text: str) -> str:
        plain = html.unescape(text)
        plain = plain.replace("<b>", "").replace("</b>", "")
        plain = plain.replace("<i>", "").replace("</i>", "")
        plain = plain.replace("<code>", "").replace("</code>", "")
        plain = plain.replace("&amp;", "&")
        return plain

    def _print_new_messages(self, start_idx: int) -> None:
        for msg in self.messages[start_idx:]:
            text = "\n[BOT]\n" + self._render_plain(msg)
            # Guard against terminals that can't render all Unicode characters
            try:
                print(text)
            except UnicodeEncodeError:
                print(text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8", errors="replace"))

    def _run_scraper_if_needed(self) -> None:
        if not self.run_scrape:
            return

        print("\n[TEST] Running LinkedInJobAgent first (scrape + analyze)...")
        agent = engine.LinkedInJobAgent(
            base_dir=self.base_dir,
            max_jobs=self.max_jobs,
            headless=self.headless_scrape,
            query=self.query,
            user_data_dir=None,
            max_run_seconds=180,
            max_extract_seconds=60,
            per_card_seconds=8,
            keep_db_open=True,
        )
        agent.run()
        print("[TEST] Scraper stage complete.")

    def _make_session(self) -> None:
        self.session = engine.TelegramJobSession(
            bot_token="auto-test-token",
            chat_id=self.chat_id,
            db=self.db,
            new_jobs=[],
            query=self.query,
            logger=self.logger,
            easy_apply_run_mode=self.easy_apply_run_mode,
        )
        self.session._send = self._send_capture  # type: ignore[method-assign]

    def _current_job_matches(self, job: Optional[Dict]) -> bool:
        if not job:
            return False
        title = str(job.get("title") or "").lower()
        company = str(job.get("company") or "").lower()
        url = str(job.get("url") or "").lower()
        target = self.job_match
        return target in title or target in company or target in url

    def _default_answer_for(self, key: str) -> str:
        cv_path = self._resolve_existing_cv_path()
        defaults = {
            "cv_path": cv_path,
            "cover_letter_path": "none",
            "full_name": "Ariel Samin",
            "email": "ariel@example.com",
            "phone": "0500000000",
            "location": "Israel",
            "linkedin": "https://www.linkedin.com/in/ariel-samin",
            "github": "https://github.com/Arisamin",
            "website": "https://example.com",
            "experience_years": "10",
            "notice_period": "1 month",
            "salary_expectation": "30000",
            "motivation": "Strong fit for my backend experience.",
        }
        if key.startswith("custom__"):
            return "No"
        return defaults.get(key, "N/A")

    def _resolve_existing_cv_path(self) -> str:
        assert self.session is not None

        saved = (self.session._saved_profile.get("cv_path") or "").strip()
        if saved and Path(saved).exists():
            return saved

        candidates = [
            Path("C:/MyData/Ariel CV - 2026 [2].pdf"),
            Path("C:/MyData"),
            self.base_dir,
        ]

        explicit_file = candidates[0]
        if explicit_file.exists() and explicit_file.is_file():
            return str(explicit_file)

        for root in candidates[1:]:
            if not root.exists() or not root.is_dir():
                continue
            for pdf in root.rglob("*.pdf"):
                return str(pdf)

        return ""

    def _drive_flow_to_target_apply(self) -> Tuple[bool, str]:
        assert self.session is not None

        self.session.send_intro()
        self._print_new_messages(0)

        before = len(self.messages)
        self.session._handle_command("db")
        self._print_new_messages(before)

        for _ in range(500):
            if self._current_job_matches(self.session._current_job):
                job = self.session._current_job or {}
                print(
                    f"\n[TEST] Target job reached: {job.get('title', '?')} @ {job.get('company', '?')}"
                )
                before = len(self.messages)
                self.session._handle_command("apply")
                self._print_new_messages(before)
                return True, ""

            before = len(self.messages)
            keep_going = self.session._handle_command("next")
            self._print_new_messages(before)
            if not keep_going:
                return False, "Session ended unexpectedly while browsing jobs."

            if self.session._state == self.session.STATE_INTRO and self.session._current_job is None:
                return False, f"Reached end of DB jobs without finding target match '{self.job_match}'."

        return False, "Safety stop: exceeded max Next iterations while searching DB jobs."

    def _finish_apply_questions(self) -> Tuple[bool, str]:
        assert self.session is not None

        for _ in range(200):
            if self.session._state == self.session.STATE_APPLY_CONFIRM:
                return True, ""

            if self.session._state != self.session.STATE_APPLYING:
                return False, f"Unexpected state while answering questions: {self.session._state}"

            idx = self.session._apply_question_idx
            if idx >= len(self.session._apply_form_fields):
                before = len(self.messages)
                self.session._show_apply_summary()
                self._print_new_messages(before)
                continue

            field_key, _prompt = self.session._apply_form_fields[idx]
            answer = self._default_answer_for(field_key)
            if field_key == "cover_letter_path":
                answer = "none"

            before = len(self.messages)
            self.session._handle_command(answer)
            self._print_new_messages(before)

        return False, "Safety stop: exceeded max apply question iterations."

    def _extract_summary(self) -> Optional[str]:
        for msg in reversed(self.messages):
            if "Application Summary" in msg:
                return msg
        return None

    def run(self) -> int:
        try:
            self._run_scraper_if_needed()
            self._make_session()

            ok, reason = self._drive_flow_to_target_apply()
            if not ok:
                print(f"\n[TEST][FAIL] {reason}")
                return 1

            ok, reason = self._finish_apply_questions()
            if not ok:
                print(f"\n[TEST][FAIL] {reason}")
                return 1

            summary = self._extract_summary()
            if not summary:
                print("\n[TEST][FAIL] Could not find 'Application Summary' in captured messages.")
                return 1

            summary_path = self.base_dir / "Tests" / "Samples" / "auto_agoda_summary.txt"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(self._render_plain(summary), encoding="utf-8")

            print("\n[TEST][PASS] Captured application summary successfully.")
            print(f"[TEST] Summary saved to: {summary_path}")
            print("\n===== SUMMARY =====")
            print(self._render_plain(summary))
            print("===================")
            return 0
        finally:
            self.db.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automate the Agoda apply-flow test without manual Telegram interaction"
    )
    parser.add_argument(
        "--job-match",
        default="agoda",
        help="Substring to match target job by title/company/url (default: agoda)",
    )
    parser.add_argument(
        "--run-scrape",
        action="store_true",
        help="Run LinkedInJobAgent scrape stage before DB navigation",
    )
    parser.add_argument(
        "--headless-scrape",
        action="store_true",
        help="If --run-scrape is set, run scrape browser headless",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=5,
        help="Max jobs for scrape stage (used only with --run-scrape)",
    )
    parser.add_argument(
        "--chat-id",
        type=int,
        default=None,
        help="Telegram chat id whose saved profile should be reused (defaults to TELEGRAM_CHAT_ID env var)",
    )
    parser.add_argument(
        "--query",
        default="Senior C# Developer Israel",
        help="Search query for scrape stage (used only with --run-scrape)",
    )
    parser.add_argument(
        "--easy-apply-run-mode",
        choices=["normal", "testing"],
        default="testing",
        help="Easy Apply scan traversal mode for apply flow (default: testing)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent

    os.environ.setdefault("AGENT_DISABLE_JITTER", "1")

    chat_id_raw = args.chat_id if args.chat_id is not None else os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if chat_id_raw in ("", None):
        print("[TEST][FAIL] Missing chat id. Pass --chat-id or set TELEGRAM_CHAT_ID.")
        return 2
    try:
        chat_id = int(chat_id_raw)
    except Exception:
        print(f"[TEST][FAIL] Invalid chat id: {chat_id_raw!r}")
        return 2

    runner = AutoAgodaTestAgent(
        base_dir=base_dir,
        chat_id=chat_id,
        job_match=args.job_match,
        run_scrape=args.run_scrape,
        headless_scrape=args.headless_scrape,
        max_jobs=args.max_jobs,
        query=args.query,
        easy_apply_run_mode=args.easy_apply_run_mode,
    )
    return runner.run()


if __name__ == "__main__":
    raise SystemExit(main())
