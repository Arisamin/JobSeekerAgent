import argparse
import html
import hashlib
import importlib
import json
import logging
import os
import random
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def ensure_logs_dir(base_dir: Path) -> Path:
    logs_dir = base_dir / "Logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def build_logger(base_dir: Path) -> logging.Logger:
    logs_dir = ensure_logs_dir(base_dir)
    log_filename = logs_dir / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logger = logging.getLogger("linkedin_job_agent")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s <step_%(step)s> %(message)s")
    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    stream_handler = logging.StreamHandler(sys.stdout)
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def find_salary_values_ils(job_text: str) -> List[int]:
    text = job_text.lower()
    values: List[int] = []

    numeric_patterns = [
        r"(\d{2,3}[\.,\s]?\d{3})\s*(?:ils|nis|₪|shekels?)",
        r"(?:ils|nis|₪)\s*(\d{2,3}[\.,\s]?\d{3})",
    ]

    for pattern in numeric_patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            cleaned = re.sub(r"[^\d]", "", match)
            if cleaned:
                values.append(int(cleaned))

    for match in re.findall(r"(\d{2,3})\s*k\b", text):
        values.append(int(match) * 1000)

    return sorted(set(v for v in values if 5000 <= v <= 200000))


def contains_any(text: str, terms: List[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def analyze_job_description(
    job_text: str,
    requirements: Dict,
    context_text: str,
    persona_text: str,
    title: str,
    company: str,
    assume_israel_location: bool = True,
) -> Tuple[List[Tuple[str, str, str]], str]:
    salary_floor = int(requirements.get("salary_min_ils", 25000))
    tech_stack = requirements.get("tech_stack", ["C#", ".NET"])
    work_model_required = str(requirements.get("work_model", "Hybrid/Remote")).lower()

    normalized_jd = normalize_space(job_text)
    salary_values = find_salary_values_ils(normalized_jd)
    top_salary = max(salary_values) if salary_values else None

    tech_match = contains_any(normalized_jd, ["c#", "c sharp", ".net", "dotnet", "asp.net"])
    senior_match = contains_any(normalized_jd, ["senior", "staff", "lead", "principal"])
    israel_from_text = contains_any(
        normalized_jd,
        ["israel", "tel aviv", "haifa", "jerusalem", "rishon", "petah", "herzliya", "raanana"],
    )
    israel_match = israel_from_text or assume_israel_location

    if "hybrid" in work_model_required or "remote" in work_model_required:
        work_model_match = contains_any(normalized_jd, ["hybrid", "remote", "office", "onsite", "on-site"])
    else:
        work_model_match = True

    degree_required_match = contains_any(normalized_jd, ["bachelor", "b.sc", "bsc", "computer science", "cs degree"])
    bgu_explicit_match = contains_any(normalized_jd, ["ben-gurion", "ben gurion", "bgu"])

    if top_salary is None:
        salary_result = "Unknown"
        salary_analysis = f"No explicit salary found; cannot confirm {salary_floor:,} ILS floor."
    elif top_salary >= salary_floor:
        salary_result = "Yes"
        salary_analysis = f"Found salary indicator around {top_salary:,} ILS, meeting floor {salary_floor:,}."
    else:
        salary_result = "No"
        salary_analysis = f"Highest extracted salary {top_salary:,} ILS is below floor {salary_floor:,}."

    bgu_result = "Yes" if (bgu_explicit_match or degree_required_match) else "No"
    bgu_analysis = (
        "BGU appears explicitly in JD."
        if bgu_explicit_match
        else "Bachelor's/CS degree requested; BGU BSc aligns with requirement."
        if degree_required_match
        else "No degree signal detected to map BGU BSc credential."
    )

    rows = [
        (
            "Role",
            f"{title or 'Unknown title'} at {company or 'Unknown company'}.",
            "Yes" if senior_match else "No",
        ),
        (
            "C#/.NET Core Fit",
            f"JD mentions stack terms: {', '.join(tech_stack)}.",
            "Yes" if tech_match else "No",
        ),
        (
            "Israel Location",
            "Location text indicates Israel-based role."
            if israel_from_text
            else "No explicit location in JD; accepted via search filter location=Israel (IL)."
            if assume_israel_location
            else "Location signal not found in JD.",
            "Yes" if israel_match else "Unknown",
        ),
        (
            "Salary Floor (25K ILS)",
            salary_analysis,
            salary_result,
        ),
        (
            "BGU BSc Compatibility",
            bgu_analysis,
            bgu_result,
        ),
        (
            "Work Model",
            f"Expected model: {requirements.get('work_model', 'Hybrid/Remote')}",
            "Yes" if work_model_match else "No",
        ),
    ]

    critical_fail = any(r[2] == "No" for r in rows if r[0] in {"C#/.NET Core Fit", "Work Model"})
    critical_unknown = False

    if not critical_fail and not critical_unknown:
        recommendation = "STRONG MATCH"
    elif not critical_fail and critical_unknown:
        recommendation = "REVIEW MANUALLY"
    else:
        recommendation = "DO NOT APPLY"

    _ = context_text
    _ = persona_text
    return rows, recommendation


def markdown_table(rows: List[Tuple[str, str, str]]) -> str:
    header = "| Metric | Analysis | Match? |"
    separator = "|---|---|---|"
    body = [f"| {metric} | {analysis} | {match} |" for metric, analysis, match in rows]
    return "\n".join([header, separator, *body])


def build_test_prompt(persona: str, context: str, job_description: str) -> str:
    return (
        "SYSTEM INSTRUCTIONS:\n"
        f"{persona.strip()}\n\n"
        "USER CONTEXT (Ariel Samin):\n"
        f"{context.strip()}\n\n"
        "JOB DESCRIPTION TO ANALYZE:\n"
        f"{job_description.strip()}"
    )


@dataclass
class JobRecord:
    job_key: str
    title: str
    company: str
    location: str
    url: str
    description: str


class ProcessedJobsDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_key TEXT NOT NULL UNIQUE,
                title TEXT,
                company TEXT,
                url TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def seen(self, job_key: str) -> bool:
        cursor = self.conn.execute("SELECT 1 FROM processed_jobs WHERE job_key = ? LIMIT 1", (job_key,))
        return cursor.fetchone() is not None

    def add(self, job: JobRecord) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO processed_jobs (job_key, title, company, url, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job.job_key, job.title, job.company, job.url, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


class LinkedInJobAgent:
    def __init__(
        self,
        base_dir: Path,
        max_jobs: int,
        headless: bool,
        query: str,
        user_data_dir: Optional[str],
        max_run_seconds: int,
        max_extract_seconds: int,
        per_card_seconds: int,
    ):
        self.base_dir = base_dir
        self.max_jobs = max(5, min(max_jobs, 10))
        self.headless = headless
        self.query = query
        self.user_data_dir = user_data_dir
        self.max_run_seconds = max(30, max_run_seconds)
        self.max_extract_seconds = max(15, max_extract_seconds)
        self.per_card_seconds = max(5, per_card_seconds)
        self.logger = build_logger(base_dir)
        self.db = ProcessedJobsDB(base_dir / "processed_jobs.db")
        self.context_text = ""
        self.persona_text = ""
        self.requirements: Dict = {}
        self.report_entries: List[Dict[str, Any]] = []
        self.report_output_path: Optional[Path] = None

    def log_step(self, step: str, message: str) -> None:
        self.logger.info(message, extra={"step": step})

    def jitter(self, step: str) -> None:
        if os.getenv("AGENT_DISABLE_JITTER", "0") == "1":
            delay = 0.2
        else:
            delay = random.uniform(5, 15)
        self.log_step(step, f"Jitter wait {delay:.1f}s")
        time.sleep(delay)

    def initialize(self) -> None:
        self.log_step("1.0", "Initializing local brain files and database")
        self.context_text = load_text(self.base_dir / "MY_CONTEXT.md")
        self.persona_text = load_text(self.base_dir / "JOB_HUNTER_PERSONA.md")
        self.requirements = load_json(self.base_dir / "JOB_REQUIREMENTS.json")
        self.log_step("1.1", "Loaded MY_CONTEXT.md, JOB_HUNTER_PERSONA.md, JOB_REQUIREMENTS.json")

    def build_search_url(self) -> str:
        from urllib.parse import quote_plus

        return (
            "https://www.linkedin.com/jobs/search/"
            f"?keywords={quote_plus(self.query)}"
            f"&location={quote_plus('Israel (IL)')}"
            "&geoId=101620260"
            "&f_TPR=r86400"
        )

    def _has_auth_wall(self, page: Any) -> bool:
        auth_selectors = [
            "a[href*='signup']",
            "a[href*='login']",
            "button:has-text('Sign in')",
            "text=/join linkedin/i",
            "text=/sign in to see/i",
        ]
        for selector in auth_selectors:
            try:
                if page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
        return False

    def _first_non_empty_text(self, page: Any, selectors: List[str], timeout: int = 1500) -> str:
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.count() < 1:
                    continue
                text = normalize_space(locator.inner_text(timeout=timeout))
                if text:
                    return text
            except Exception:
                continue
        return ""

    def _first_non_empty_text_in_card(self, card: Any, selectors: List[str], timeout: int = 1000) -> str:
        for selector in selectors:
            try:
                locator = card.locator(selector).first
                if locator.count() < 1:
                    continue
                text = normalize_space(locator.inner_text(timeout=timeout))
                if text:
                    return text
            except Exception:
                continue
        return ""

    def _expand_job_description(self, page: Any) -> None:
        expand_selectors = [
            "button:has-text('Show more')",
            "button:has-text('See more')",
            "button[aria-label*='more']",
        ]
        for selector in expand_selectors:
            try:
                button = page.locator(selector).first
                if button.count() > 0 and button.is_visible():
                    button.click(timeout=2000)
                    return
            except Exception:
                continue

    def _get_cards_locator(self, page: Any) -> Any:
        selectors = [
            "ul.jobs-search__results-list li",
            "li.scaffold-layout__list-item",
            "li:has(a.base-card__full-link)",
            "div.job-search-card",
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector)
                if locator.count() > 0:
                    return locator
            except Exception:
                continue
        return None

    def _capture_page_diagnostics(self, page: Any, reason: str) -> None:
        try:
            diagnostics_dir = self.base_dir / "Logs" / "Diagnostics"
            diagnostics_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            screenshot_path = diagnostics_dir / f"diag_{stamp}.png"
            html_path = diagnostics_dir / f"diag_{stamp}.html"
            meta_path = diagnostics_dir / f"diag_{stamp}.txt"

            page.screenshot(path=str(screenshot_path), full_page=True)
            html_path.write_text(page.content(), encoding="utf-8")

            selector_candidates = [
                "ul.jobs-search__results-list li",
                "li.scaffold-layout__list-item",
                "li:has(a.base-card__full-link)",
                "div.job-search-card",
                "a.base-card__full-link",
                "a[href*='/jobs/view/']",
                "button:has-text('Sign in')",
                "a[href*='signup']",
                "a[href*='login']",
            ]

            lines = [
                f"reason={reason}",
                f"url={page.url}",
                f"title={page.title()}",
                f"screenshot={screenshot_path}",
                f"html={html_path}",
                "selector_counts:",
            ]
            for selector in selector_candidates:
                try:
                    count = page.locator(selector).count()
                except Exception:
                    count = -1
                lines.append(f"  {selector} -> {count}")

            meta_path.write_text("\n".join(lines), encoding="utf-8")
            self.log_step("3.9", f"Diagnostics captured: {meta_path}")
        except Exception as exc:
            self.log_step("3.9", f"Failed to capture diagnostics: {exc}")

    def _write_html_report(self) -> Path:
        reports_dir = self.base_dir / "Reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = reports_dir / f"run_report_{stamp}.html"

        strong_count = sum(1 for entry in self.report_entries if entry["recommendation"] == "STRONG MATCH")
        review_count = sum(1 for entry in self.report_entries if entry["recommendation"] == "REVIEW MANUALLY")
        reject_count = sum(1 for entry in self.report_entries if entry["recommendation"] == "DO NOT APPLY")

        cards_html: List[str] = []
        for index, entry in enumerate(self.report_entries, start=1):
            rows_html = "".join(
                f"<tr><td>{html.escape(metric)}</td><td>{html.escape(analysis)}</td><td>{html.escape(match)}</td></tr>"
                for metric, analysis, match in entry["rows"]
            )
            cards_html.append(
                "".join(
                    [
                        "<section class='job-card'>",
                        f"<h2>{index}. {html.escape(entry['title'])}</h2>",
                        f"<p><strong>Company:</strong> {html.escape(entry['company'])}</p>",
                        f"<p><strong>Location:</strong> {html.escape(entry['location'] or 'N/A')}</p>",
                        f"<p><strong>URL:</strong> <a href='{html.escape(entry['url'])}' target='_blank'>{html.escape(entry['url'])}</a></p>",
                        f"<p><strong>Recommendation:</strong> <span class='badge'>{html.escape(entry['recommendation'])}</span></p>",
                        "<table><thead><tr><th>Metric</th><th>Analysis</th><th>Match?</th></tr></thead>",
                        f"<tbody>{rows_html}</tbody></table>",
                        "<p class='approval'>Ariel, should I draft an application for this role? [Y/N]</p>",
                        "</section>",
                    ]
                )
            )

        body_content = "".join(cards_html) if cards_html else "<p>No jobs were extracted in this run.</p>"

        html_report = "".join(
            [
                "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
                "<meta name='viewport' content='width=device-width, initial-scale=1'>",
                "<title>LinkedIn Job Agent Report</title>",
                "<style>",
                "body{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#0f172a;color:#e2e8f0}",
                "h1,h2{margin:0 0 10px}",
                ".meta{margin:0 0 16px;color:#94a3b8}",
                ".summary{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0 20px}",
                ".pill{background:#1e293b;border:1px solid #334155;border-radius:8px;padding:8px 12px}",
                ".job-card{background:#111827;border:1px solid #334155;border-radius:10px;padding:16px;margin-bottom:16px}",
                "table{width:100%;border-collapse:collapse;margin-top:10px}",
                "th,td{border:1px solid #334155;padding:8px;vertical-align:top}",
                "th{background:#1f2937}",
                "a{color:#93c5fd}",
                ".badge{background:#1d4ed8;color:#fff;border-radius:6px;padding:2px 8px}",
                ".approval{margin-top:12px;font-weight:600}",
                "</style></head><body>",
                "<h1>Autonomous LinkedIn Job Agent Report</h1>",
                f"<p class='meta'><strong>Generated:</strong> {html.escape(datetime.now().isoformat())} | <strong>Query:</strong> {html.escape(self.query)}</p>",
                "<div class='summary'>",
                f"<div class='pill'>Total Extracted: <strong>{len(self.report_entries)}</strong></div>",
                f"<div class='pill'>STRONG MATCH: <strong>{strong_count}</strong></div>",
                f"<div class='pill'>REVIEW MANUALLY: <strong>{review_count}</strong></div>",
                f"<div class='pill'>DO NOT APPLY: <strong>{reject_count}</strong></div>",
                "</div>",
                body_content,
                "</body></html>",
            ]
        )

        report_path.write_text(html_report, encoding="utf-8")
        return report_path

    def extract_job_cards(self, page: Any) -> List[JobRecord]:
        sync_api = importlib.import_module("playwright.sync_api")
        playwright_timeout_error = getattr(sync_api, "TimeoutError", Exception)
        extract_deadline = time.monotonic() + self.max_extract_seconds

        self.log_step("3.0", "Extracting first job cards and full descriptions")
        if self._has_auth_wall(page):
            self.log_step("3.0", "Auth wall detected; extraction quality may be limited")
            self._capture_page_diagnostics(page, "auth_wall_detected")
            self.log_step("3.8", "Stopping extraction early. Re-run non-headless with authenticated profile.")
            return []

        cards_locator = self._get_cards_locator(page)

        if cards_locator is None:
            self._capture_page_diagnostics(page, "no_cards_locator")
            self.log_step("3.8", "No job cards found; possible auth wall or changed LinkedIn DOM")
            return []

        total = min(cards_locator.count(), self.max_jobs)
        jobs: List[JobRecord] = []

        for index in range(total):
            if time.monotonic() >= extract_deadline:
                self.log_step("3.8", f"Extraction deadline reached ({self.max_extract_seconds}s); stopping scan")
                break

            self.log_step("3.1", f"Opening job card {index + 1}/{total}")
            card_deadline = time.monotonic() + self.per_card_seconds
            try:
                cards_locator = self._get_cards_locator(page)
                if cards_locator is None or cards_locator.count() <= index:
                    self.log_step("3.5", f"Card list changed before index {index + 1}; stopping early")
                    break

                card = cards_locator.nth(index)

                try:
                    card.scroll_into_view_if_needed(timeout=2500)
                except Exception:
                    pass

                clickable = card.locator("a.base-card__full-link, a.job-card-container__link, a").first
                if clickable.count() > 0:
                    clickable.click(timeout=3500)
                else:
                    card.click(timeout=3500)
                self.jitter("3.2")

                if time.monotonic() >= card_deadline:
                    self.log_step("3.5", f"Per-card deadline reached on card {index + 1}; continuing")
                    continue

                self._expand_job_description(page)
                page.wait_for_timeout(250)

                card_title = self._first_non_empty_text_in_card(
                    card,
                    [
                        "a.job-card-list__title",
                        "div.artdeco-entity-lockup__title span",
                        "h3.base-search-card__title",
                        "strong",
                        "h3",
                    ],
                    timeout=1000,
                )
                card_company = self._first_non_empty_text_in_card(
                    card,
                    [
                        "a.job-card-container__company-name",
                        "div.artdeco-entity-lockup__subtitle span",
                        "div.artdeco-entity-lockup__subtitle",
                        "span.job-card-container__primary-description",
                        "h4.base-search-card__subtitle",
                        "a.hidden-nested-link",
                        "h4",
                    ],
                    timeout=1000,
                )

                title = self._first_non_empty_text(
                    page,
                    ["h1.top-card-layout__title", "h2.jobs-unified-top-card__job-title", "h2.t-24"],
                    timeout=1500,
                )
                company = self._first_non_empty_text(
                    page,
                    [
                        "div.job-details-jobs-unified-top-card__company-name a",
                        "div.jobs-unified-top-card__company-name a",
                        "a.jobs-unified-top-card__company-name",
                        "div.job-details-jobs-unified-top-card__company-name",
                        "span.jobs-unified-top-card__company-name",
                        "a.topcard__org-name-link",
                        "span.topcard__flavor",
                    ],
                    timeout=1500,
                )
                location = self._first_non_empty_text(
                    page,
                    [
                        "div.jobs-unified-top-card__subtitle-primary-grouping span",
                        "span.jobs-unified-top-card__bullet",
                        "div.jobs-unified-top-card__primary-description-container span",
                        "span.topcard__flavor--bullet",
                    ],
                    timeout=1500,
                )
                description = self._first_non_empty_text(
                    page,
                    [
                        "div.jobs-description__content",
                        "div.jobs-box__html-content",
                        "div.show-more-less-html__markup",
                        "section.show-more-less-html",
                    ],
                    timeout=2000,
                )

                if not description:
                    self.log_step("3.5", f"No description content for card {index + 1}; continuing")
                    continue

                job_url = page.url
                try:
                    href = clickable.get_attribute("href", timeout=1500) if clickable.count() > 0 else None
                    if href:
                        if href.startswith("/"):
                            href = f"https://www.linkedin.com{href}"
                        job_url = href
                except Exception:
                    pass

                if not title:
                    title = card_title
                if not company:
                    company = card_company

                if not title:
                    title = "Unknown title"
                if not company:
                    company = "Unknown company"

                key_source = f"{title}|{company}|{job_url}"
                job_key = hashlib.sha256(key_source.encode("utf-8")).hexdigest()

                if self.db.seen(job_key):
                    self.log_step("3.3", f"Skipping already-processed job: {title} @ {company}")
                    continue

                job = JobRecord(
                    job_key=job_key,
                    title=title,
                    company=company,
                    location=location,
                    url=job_url,
                    description=description,
                )
                self.db.add(job)
                jobs.append(job)
                self.log_step("3.4", f"Captured new job: {title} @ {company}")

                if time.monotonic() >= card_deadline:
                    self.log_step("3.5", f"Per-card deadline reached after capture for card {index + 1}")
            except playwright_timeout_error:
                self.log_step("3.5", f"Timeout extracting card {index + 1}; continuing")
            except Exception as exc:
                self.log_step("3.6", f"Extraction error on card {index + 1}: {exc}")

        self.log_step("3.7", f"Extracted {len(jobs)} new jobs")
        return jobs

    def report_job(self, job: JobRecord) -> None:
        self.log_step("4.0", f"Analyzing role: {job.title} @ {job.company}")
        prompt = build_test_prompt(self.persona_text, self.context_text, job.description)
        rows, recommendation = analyze_job_description(
            job_text=job.description,
            requirements=self.requirements,
            context_text=self.context_text,
            persona_text=self.persona_text,
            title=job.title,
            company=job.company,
        )
        table = markdown_table(rows)

        report_block = (
            "\n=== EXECUTIVE SUMMARY ===\n"
            f"Role: {job.title}\n"
            f"Company: {job.company}\n"
            f"Location: {job.location}\n"
            f"URL: {job.url}\n\n"
            f"{table}\n\n"
            f"Recommendation: {recommendation}\n"
            "Ariel, should I draft an application for this role? [Y/N]\n"
            "=========================\n"
        )

        self.log_step("4.1", "Executive summary generated")
        print(report_block)
        self.logger.info(report_block, extra={"step": "4.2"})

        prompt_preview = prompt[:800] + ("..." if len(prompt) > 800 else "")
        self.logger.info(f"Prompt preview:\n{prompt_preview}", extra={"step": "4.3"})
        self.report_entries.append(
            {
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "url": job.url,
                "recommendation": recommendation,
                "rows": rows,
            }
        )

    def run(self) -> None:
        sync_api = importlib.import_module("playwright.sync_api")
        sync_playwright = getattr(sync_api, "sync_playwright")
        target_closed_error = getattr(sync_api, "TargetClosedError", Exception)
        run_deadline = time.monotonic() + self.max_run_seconds

        self.initialize()
        self.log_step("2.0", "Launching persistent Playwright context")

        user_data_dir = self.user_data_dir
        if not user_data_dir:
            local_app_data = os.environ.get("LOCALAPPDATA")
            if not local_app_data:
                raise RuntimeError("LOCALAPPDATA is not set; pass --user-data-dir manually.")
            user_data_dir = os.path.join(local_app_data, "Google", "Chrome", "User Data")

        fallback_user_data_dir = str(self.base_dir / ".playwright_profile")

        with sync_playwright() as playwright:
            try:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    channel="chrome",
                    headless=self.headless,
                    viewport={"width": 1440, "height": 900},
                )
            except target_closed_error as exc:
                self.log_step("2.0", f"Primary profile launch failed: {exc}")
                self.log_step("2.0", f"Retrying with local profile: {fallback_user_data_dir}")
                os.makedirs(fallback_user_data_dir, exist_ok=True)
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=fallback_user_data_dir,
                    channel="chrome",
                    headless=self.headless,
                    viewport={"width": 1440, "height": 900},
                )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(min(5000, self.per_card_seconds * 1000))
                search_url = self.build_search_url()
                self.log_step("2.1", f"Navigating to LinkedIn search: {search_url}")
                page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                self.jitter("2.2")

                if time.monotonic() >= run_deadline:
                    self.log_step("5.0", f"Run deadline reached ({self.max_run_seconds}s) before extraction")
                    return

                jobs = self.extract_job_cards(page)
                if not jobs:
                    self.log_step("5.0", "No new jobs discovered in this run")
                for job in jobs:
                    if time.monotonic() >= run_deadline:
                        self.log_step("5.0", f"Run deadline reached ({self.max_run_seconds}s); stopping reports")
                        break
                    self.report_job(job)
                    self.jitter("4.4")
                self.report_output_path = self._write_html_report()
                self.log_step("6.0", f"HTML report generated: {self.report_output_path}")
            finally:
                if self.report_output_path is None:
                    try:
                        self.report_output_path = self._write_html_report()
                        self.log_step("6.0", f"HTML report generated: {self.report_output_path}")
                    except Exception as exc:
                        self.log_step("6.1", f"Failed to generate HTML report: {exc}")
                self.log_step("5.1", "Closing browser context")
                context.close()
                self.db.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autonomous LinkedIn Job Agent")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--max-jobs", type=int, default=8, help="How many jobs to inspect (5-10)")
    parser.add_argument(
        "--query",
        type=str,
        default="Senior C# Developer Israel",
        help="LinkedIn search keywords",
    )
    parser.add_argument(
        "--user-data-dir",
        type=str,
        default=None,
        help="Path to Chrome user data dir for persistent login",
    )
    parser.add_argument(
        "--max-run-seconds",
        type=int,
        default=180,
        help="Hard deadline for full run; agent exits cleanly when reached",
    )
    parser.add_argument(
        "--max-extract-seconds",
        type=int,
        default=90,
        help="Hard deadline for extraction phase",
    )
    parser.add_argument(
        "--per-card-seconds",
        type=int,
        default=12,
        help="Per-card budget to avoid stalls on dynamic DOM",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    agent = LinkedInJobAgent(
        base_dir=Path(__file__).resolve().parent,
        max_jobs=args.max_jobs,
        headless=args.headless,
        query=args.query,
        user_data_dir=args.user_data_dir,
        max_run_seconds=args.max_run_seconds,
        max_extract_seconds=args.max_extract_seconds,
        per_card_seconds=args.per_card_seconds,
    )
    agent.run()


if __name__ == "__main__":
    main()