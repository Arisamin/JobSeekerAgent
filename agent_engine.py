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
import subprocess
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class StepFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "step"):
            record.step = "-"
        return super().format(record)


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

    formatter = StepFormatter("%(asctime)s <step_%(step)s> %(message)s")
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


def format_display_datetime(value: Optional[str]) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return raw


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
        self.lock_path = db_path.parent / ".db_lock"
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_key TEXT NOT NULL UNIQUE,
                title TEXT,
                company TEXT,
                url TEXT,
                status TEXT DEFAULT 'Discovered',
                created_at TEXT NOT NULL,
                last_updated TEXT NOT NULL
            )
            """
        )
        self.conn.commit()
        # Migrate existing records if needed (add new columns)
        try:
            self.conn.execute("ALTER TABLE processed_jobs ADD COLUMN status TEXT DEFAULT 'Discovered'")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            self.conn.execute("ALTER TABLE processed_jobs ADD COLUMN last_updated TEXT")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists

    def seen(self, job_key: str) -> bool:
        cursor = self.conn.execute("SELECT 1 FROM processed_jobs WHERE job_key = ? LIMIT 1", (job_key,))
        return cursor.fetchone() is not None

    def add(self, job: JobRecord) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO processed_jobs (job_key, title, company, url, status, created_at, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (job.job_key, job.title, job.company, job.url, "Discovered", datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def get_all_jobs(self) -> List[Dict]:
        """Retrieve all jobs from the database."""
        cursor = self.conn.execute("SELECT id, job_key, title, company, url, status, created_at, last_updated FROM processed_jobs ORDER BY created_at DESC")
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_jobs_by_status(self, statuses: List[str]) -> List[Dict]:
        if not statuses:
            return []
        placeholders = ",".join("?" for _ in statuses)
        cursor = self.conn.execute(
            f"SELECT id, job_key, title, company, url, status, created_at, last_updated FROM processed_jobs WHERE status IN ({placeholders}) ORDER BY last_updated DESC",
            tuple(statuses),
        )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def update_job_status(self, job_id: int, new_status: str) -> None:
        """Update the status of a job."""
        if new_status not in ["Discovered", "Applied", "InProcess", "RejectedMe", "RejectedByMe", "Accepted", "Skipped", "Closed"]:
            raise ValueError(f"Invalid status: {new_status}")
        self.conn.execute(
            "UPDATE processed_jobs SET status = ?, last_updated = ? WHERE id = ?",
            (new_status, datetime.now(timezone.utc).isoformat(), job_id),
        )
        self.conn.commit()

    def acquire_lock(self, timeout: int = 10) -> bool:
        """Acquire an exclusive lock on the database (prevents concurrent access)."""
        import time
        start = time.time()
        while time.time() - start < timeout:
            try:
                with open(self.lock_path, "x") as f:
                    f.write(str(os.getpid()))
                return True
            except FileExistsError:
                time.sleep(0.5)
        return False

    def release_lock(self) -> None:
        """Release the database lock."""
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass

    def close(self) -> None:
        self.conn.close()


class UserDBUpdateMode:
    """Interactive mode for users to update job status in the database."""

    STATUSES = ["Discovered", "Applied", "InProcess", "RejectedMe", "RejectedByMe", "Accepted", "Skipped", "Closed"]

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.db = ProcessedJobsDB(base_dir / "processed_jobs.db")
        self.logger = build_logger(base_dir)

    def run(self) -> None:
        """Run the interactive UI form."""
        if not self.db.acquire_lock():
            print("❌ Error: Another instance of the agent is running. Please stop it first.")
            return

        try:
            print("\n" + "="*60)
            print("   JOB STATUS UPDATE MODE")
            print("="*60 + "\n")

            while True:
                all_jobs = self.db.get_all_jobs()
                jobs = [
                    job
                    for job in all_jobs
                    if job.get("title") != "Unknown title" and job.get("company") != "Unknown company"
                ]

                if not all_jobs:
                    print("⚠️  No jobs in the database yet.\n")
                    break

                hidden_count = len(all_jobs) - len(jobs)
                if not jobs:
                    print("⚠️  Only placeholder records found (Unknown title/company).\n")
                    break

                print(f"📋 Found {len(jobs)} job(s) in database:\n")
                if hidden_count > 0:
                    print(f"ℹ️  Hidden {hidden_count} placeholder row(s) with Unknown title/company.\n")
                for idx, job in enumerate(jobs, 1):
                    status_marker = "✓" if job['status'] == 'Accepted' else "✗" if job['status'] == 'RejectedMe' else "→"
                    print(f"  [{idx}] {status_marker} {job['title']} @ {job['company']} [{job['status']}]")

                print("\n  [0] Done / Exit\n")

                try:
                    choice = input("Select job number to update (0 to exit): ").strip()
                    if choice == "0":
                        break
                    job_idx = int(choice) - 1
                    if not (0 <= job_idx < len(jobs)):
                        print("❌ Invalid selection. Try again.\n")
                        continue
                except ValueError:
                    print("❌ Invalid input. Please enter a number.\n")
                    continue

                selected_job = jobs[job_idx]
                self._update_job_status(selected_job)
                print()

        finally:
            self.db.release_lock()
            self.db.close()
            print("✅ Done. Locked released.\n")

    def _update_job_status(self, job: Dict) -> None:
        """UI form to update a single job's status."""
        print("\n" + "-"*60)
        print(f"Job: {job['title']}")
        print(f"Company: {job['company']}")
        print(f"URL: {job['url']}")
        print(f"Current Status: {job['status']}")
        print(f"Created: {job['created_at']}")
        print(f"Last Updated: {job['last_updated']}")
        print("-"*60 + "\n")

        print("Select new status:\n")
        for idx, status in enumerate(self.STATUSES, 1):
            mark = "✓" if status == job['status'] else " "
            print(f"  [{idx}] {status} {mark}")
        print()

        try:
            choice = input("Enter new status number: ").strip()
            status_idx = int(choice) - 1
            if not (0 <= status_idx < len(self.STATUSES)):
                print("❌ Invalid selection.\n")
                return
        except ValueError:
            print("❌ Invalid input.\n")
            return

        new_status = self.STATUSES[status_idx]

        try:
            self.db.update_job_status(job['id'], new_status)
            print(f"\n✅ Status updated to: {new_status}")
            self.logger.info(f"Job status updated: {job['title']} @ {job['company']} -> {new_status}")
        except Exception as e:
            print(f"❌ Error updating status: {e}\n")


class UserDBUpdateGUI:
    """Windows desktop UI for updating job statuses (dropdowns + buttons)."""

    STATUSES = UserDBUpdateMode.STATUSES

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.db = ProcessedJobsDB(base_dir / "processed_jobs.db")
        self.logger = build_logger(base_dir)
        self._jobs_by_id: Dict[int, Dict[str, Any]] = {}

    def run(self) -> None:
        if not self.db.acquire_lock():
            print("❌ Error: Another instance of the agent is running. Please stop it first.")
            return

        try:
            import tkinter as tk
            from tkinter import messagebox, ttk
        except Exception as exc:
            self.db.release_lock()
            self.db.close()
            print(f"❌ Failed to launch GUI mode ({exc}). Falling back to console mode.")
            UserDBUpdateMode(self.base_dir).run()
            return

        self.tk = tk
        self.ttk = ttk
        self.messagebox = messagebox
        self.root = tk.Tk()
        self.root.title("Job Seeker Agent - DB Update")
        self.root.geometry("1100x650")
        self.root.minsize(980, 560)

        self._build_layout()
        self._load_jobs()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _build_layout(self) -> None:
        root = self.root
        ttk = self.ttk

        container = ttk.Frame(root, padding=10)
        container.pack(fill="both", expand=True)

        title = ttk.Label(container, text="Job Status Update", font=("Segoe UI", 14, "bold"))
        title.pack(anchor="w", pady=(0, 8))

        self.info_var = self.tk.StringVar(value="Loading jobs...")
        info_label = ttk.Label(container, textvariable=self.info_var)
        info_label.pack(anchor="w", pady=(0, 8))

        tree_wrap = ttk.Frame(container)
        tree_wrap.pack(fill="both", expand=True)

        columns = ("id", "title", "company", "status", "last_updated")
        self.tree = ttk.Treeview(tree_wrap, columns=columns, show="headings", height=14)
        self.tree.heading("id", text="ID")
        self.tree.heading("title", text="Title")
        self.tree.heading("company", text="Company")
        self.tree.heading("status", text="Status")
        self.tree.heading("last_updated", text="Last Updated")
        self.tree.column("id", width=70, anchor="center", stretch=False)
        self.tree.column("title", width=380, anchor="w")
        self.tree.column("company", width=200, anchor="w")
        self.tree.column("status", width=120, anchor="center", stretch=False)
        self.tree.column("last_updated", width=250, anchor="w")

        y_scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y_scroll.set)

        self.tree.pack(side="left", fill="both", expand=True)
        y_scroll.pack(side="right", fill="y")

        details_frame = ttk.LabelFrame(container, text="Selected Job", padding=10)
        details_frame.pack(fill="x", pady=(10, 8))

        self.selected_id_var = self.tk.StringVar(value="")
        self.selected_title_var = self.tk.StringVar(value="")
        self.selected_company_var = self.tk.StringVar(value="")
        self.selected_url_var = self.tk.StringVar(value="")
        self.current_status_var = self.tk.StringVar(value="")

        ttk.Label(details_frame, text="ID:").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Label(details_frame, textvariable=self.selected_id_var).grid(row=0, column=1, sticky="w", pady=2)
        ttk.Label(details_frame, text="Current Status:").grid(row=0, column=2, sticky="e", padx=(12, 6), pady=2)
        ttk.Label(details_frame, textvariable=self.current_status_var).grid(row=0, column=3, sticky="w", pady=2)

        ttk.Label(details_frame, text="Title:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Label(details_frame, textvariable=self.selected_title_var).grid(row=1, column=1, columnspan=3, sticky="w", pady=2)

        ttk.Label(details_frame, text="Company:").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Label(details_frame, textvariable=self.selected_company_var).grid(row=2, column=1, columnspan=3, sticky="w", pady=2)

        ttk.Label(details_frame, text="URL:").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Entry(details_frame, textvariable=self.selected_url_var, state="readonly", width=110).grid(
            row=3, column=1, columnspan=3, sticky="we", pady=2
        )

        controls = ttk.Frame(container)
        controls.pack(fill="x", pady=(4, 0))

        ttk.Label(controls, text="Filter Status:").pack(side="left", padx=(0, 8))
        self.filter_status_values = ["All", *self.STATUSES]
        self.filter_status_var = self.tk.StringVar(value="All")
        self.filter_combo = ttk.Combobox(
            controls,
            textvariable=self.filter_status_var,
            values=self.filter_status_values,
            state="readonly",
            width=16,
        )
        self.filter_combo.pack(side="left", padx=(0, 12))
        self.filter_combo.bind("<<ComboboxSelected>>", self._on_filter_changed)

        ttk.Label(controls, text="New Status:").pack(side="left", padx=(0, 8))
        self.new_status_var = self.tk.StringVar(value=self.STATUSES[0])
        self.status_combo = ttk.Combobox(
            controls,
            textvariable=self.new_status_var,
            values=self.STATUSES,
            state="readonly",
            width=20,
        )
        self.status_combo.pack(side="left")

        ttk.Button(controls, text="Apply Status", command=self._apply_status, width=16).pack(side="left", padx=(10, 6))
        ttk.Button(controls, text="Refresh", command=self._load_jobs, width=12).pack(side="left", padx=6)
        ttk.Button(controls, text="Close", command=self._on_close, width=12).pack(side="right")

        self.tree.bind("<<TreeviewSelect>>", self._on_select)

    def _filtered_jobs(self) -> List[Dict[str, Any]]:
        jobs = self.db.get_all_jobs()
        visible_jobs = [
            job
            for job in jobs
            if job.get("title") != "Unknown title" and job.get("company") != "Unknown company"
        ]

        selected_status = self.filter_status_var.get().strip()
        if selected_status and selected_status != "All":
            visible_jobs = [job for job in visible_jobs if job.get("status") == selected_status]

        return visible_jobs

    def _on_filter_changed(self, _event: Any) -> None:
        self._load_jobs()

    def _load_jobs(self) -> None:
        selected_item = self.tree.selection()
        previously_selected_id = None
        if selected_item:
            values = self.tree.item(selected_item[0], "values")
            if values:
                previously_selected_id = int(values[0])

        for item in self.tree.get_children():
            self.tree.delete(item)

        jobs = self._filtered_jobs()
        self._jobs_by_id = {int(job["id"]): job for job in jobs}

        for job in jobs:
            self.tree.insert(
                "",
                "end",
                values=(
                    job["id"],
                    job["title"],
                    job["company"],
                    job["status"],
                    job["last_updated"],
                ),
            )

        current_filter = self.filter_status_var.get().strip() or "All"
        self.info_var.set(
            f"Loaded {len(jobs)} job(s). Filter: {current_filter}. Select a row, choose status, then click Apply Status."
        )

        if not jobs:
            self._clear_selection_details()
            return

        target_item = None
        if previously_selected_id is not None:
            for item in self.tree.get_children():
                values = self.tree.item(item, "values")
                if values and int(values[0]) == previously_selected_id:
                    target_item = item
                    break
        if target_item is None:
            target_item = self.tree.get_children()[0]

        self.tree.selection_set(target_item)
        self.tree.focus(target_item)
        self._on_select(None)

    def _clear_selection_details(self) -> None:
        self.selected_id_var.set("")
        self.selected_title_var.set("")
        self.selected_company_var.set("")
        self.selected_url_var.set("")
        self.current_status_var.set("")

    def _on_select(self, _event: Any) -> None:
        selected = self.tree.selection()
        if not selected:
            self._clear_selection_details()
            return

        values = self.tree.item(selected[0], "values")
        if not values:
            self._clear_selection_details()
            return

        job_id = int(values[0])
        job = self._jobs_by_id.get(job_id)
        if not job:
            self._clear_selection_details()
            return

        self.selected_id_var.set(str(job["id"]))
        self.selected_title_var.set(job["title"])
        self.selected_company_var.set(job["company"])
        self.selected_url_var.set(job["url"])
        self.current_status_var.set(job["status"])
        self.new_status_var.set(job["status"])

    def _apply_status(self) -> None:
        selected = self.tree.selection()
        if not selected:
            self.messagebox.showwarning("No Selection", "Please select a job first.")
            return

        values = self.tree.item(selected[0], "values")
        job_id = int(values[0])
        new_status = self.new_status_var.get().strip()

        if new_status not in self.STATUSES:
            self.messagebox.showerror("Invalid Status", "Please choose a valid status from the dropdown.")
            return

        job = self._jobs_by_id.get(job_id)
        if not job:
            self.messagebox.showerror("Missing Job", "Selected job was not found. Please refresh.")
            return

        try:
            self.db.update_job_status(job_id, new_status)
            self.logger.info(f"Job status updated: {job['title']} @ {job['company']} -> {new_status}")
            self._load_jobs()
            self.info_var.set(f"Updated: {job['title']} @ {job['company']} -> {new_status}")
        except Exception as exc:
            self.messagebox.showerror("Update Failed", f"Failed to update status: {exc}")

    def _on_close(self) -> None:
        try:
            self.db.release_lock()
            self.db.close()
        finally:
            self.root.destroy()


class ReportActionsServer:
    """Serve latest report and accept status updates from report HTML."""

    def __init__(self, base_dir: Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True):
        self.base_dir = base_dir
        self.host = host
        self.port = port
        self.open_browser = open_browser

    def _latest_report_path(self) -> Optional[Path]:
        reports_dir = self.base_dir / "Reports"
        if not reports_dir.exists():
            return None
        report_files = sorted(reports_dir.glob("run_report_*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
        return report_files[0] if report_files else None

    def _apply_updates(self, updates: List[Dict[str, Any]]) -> Tuple[bool, str, int]:
        db = ProcessedJobsDB(self.base_dir / "processed_jobs.db")
        if not db.acquire_lock(timeout=3):
            db.close()
            return False, "Database is locked by another process.", 0

        try:
            allowed = set(UserDBUpdateMode.STATUSES)
            updated_count = 0
            for update in updates:
                job_id = int(update.get("id"))
                new_status = str(update.get("status", "")).strip()
                if new_status not in allowed:
                    return False, f"Invalid status: {new_status}", updated_count
                db.update_job_status(job_id, new_status)
                updated_count += 1
        except Exception as exc:
            return False, str(exc), 0
        finally:
            db.release_lock()
            db.close()

        return True, "OK", updated_count

    def _launch_user_update_mode(self) -> None:
        cmd = [sys.executable, str(self.base_dir / "agent_engine.py"), "--user-db-update"]
        subprocess.Popen(cmd, cwd=str(self.base_dir))

    @staticmethod
    def _json_bytes(payload: Dict[str, Any]) -> bytes:
        return json.dumps(payload).encode("utf-8")

    def run(self) -> None:
        report_path = self._latest_report_path()
        if report_path is None:
            print("❌ No report found. Run agent first to generate one.")
            return

        server_context = self

        class Handler(BaseHTTPRequestHandler):
            def _send_bytes(self, status_code: int, content_type: str, data: bytes) -> None:
                self.send_response(status_code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                if self.path not in {"/", "/report"}:
                    self._send_bytes(404, "text/plain; charset=utf-8", b"Not found")
                    return
                try:
                    data = report_path.read_bytes()
                    self._send_bytes(200, "text/html; charset=utf-8", data)
                except Exception as exc:
                    self._send_bytes(500, "text/plain; charset=utf-8", str(exc).encode("utf-8"))

            def do_POST(self) -> None:
                if self.path != "/apply-status-updates":
                    self._send_bytes(404, "application/json; charset=utf-8", ReportActionsServer._json_bytes({"ok": False, "error": "Not found"}))
                    return

                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                    payload_raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
                    payload = json.loads(payload_raw.decode("utf-8"))
                    updates = payload.get("updates", [])
                    if not isinstance(updates, list):
                        self._send_bytes(400, "application/json; charset=utf-8", ReportActionsServer._json_bytes({"ok": False, "error": "updates must be a list"}))
                        return

                    ok, message, updated_count = server_context._apply_updates(updates)
                    if not ok:
                        self._send_bytes(409, "application/json; charset=utf-8", ReportActionsServer._json_bytes({"ok": False, "error": message, "updated_count": updated_count}))
                        return

                    launched = False
                    if updated_count > 0:
                        server_context._launch_user_update_mode()
                        launched = True

                    self._send_bytes(
                        200,
                        "application/json; charset=utf-8",
                        ReportActionsServer._json_bytes({"ok": True, "updated_count": updated_count, "launched": launched}),
                    )
                except Exception as exc:
                    self._send_bytes(500, "application/json; charset=utf-8", ReportActionsServer._json_bytes({"ok": False, "error": str(exc)}))

            def log_message(self, format: str, *args: Any) -> None:
                return

        selected_port = self.port
        httpd = None
        for candidate_port in range(self.port, self.port + 15):
            try:
                httpd = ThreadingHTTPServer((self.host, candidate_port), Handler)
                selected_port = candidate_port
                break
            except OSError:
                continue

        if httpd is None:
            print(f"❌ Could not start report server on ports {self.port}-{self.port + 14}")
            return

        url = f"http://{self.host}:{selected_port}/"
        print(f"✅ Serving latest report: {report_path.name}")
        print(f"🌐 Open: {url}")
        if self.open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()


def run_easy_mode(args: argparse.Namespace, base_dir: Path) -> None:
    print("\n🚀 Easy mode starting: scan jobs, then open update page...\n")

    agent = LinkedInJobAgent(
        base_dir=base_dir,
        max_jobs=args.max_jobs,
        headless=args.headless,
        query=args.query,
        user_data_dir=args.user_data_dir,
        max_run_seconds=args.max_run_seconds,
        max_extract_seconds=args.max_extract_seconds,
        per_card_seconds=args.per_card_seconds,
    )
    try:
        agent.run()
    except Exception as exc:
        print(f"⚠️ Scan ended with warning: {exc}")
        print("⚠️ Continuing to open latest report for status updates...")

    print("\n✅ Scan finished. Opening update page in your browser...\n")
    server = ReportActionsServer(
        base_dir=base_dir,
        host=args.report_host,
        port=args.report_port,
        open_browser=not args.no_open_browser,
    )
    server.run()


class SkippedJobsMaintenanceTask:
    """Scheduled task: verify skipped job URLs and mark closed jobs as Closed."""

    def __init__(self, base_dir: Path, headless: bool = True):
        self.base_dir = base_dir
        self.headless = headless
        self.db = ProcessedJobsDB(base_dir / "processed_jobs.db")
        self.logger = build_logger(base_dir)

    def _looks_closed(self, title: str, body: str, url: str) -> bool:
        lowered_title = (title or "").lower()
        lowered_body = (body or "").lower()
        lowered_url = (url or "").lower()

        dead_markers = [
            "page not found",
            "we can't seem to find this page",
            "this job is no longer available",
            "job is no longer available",
            "no longer accepting applications",
            "this job has expired",
            "job has expired",
            "position has been filled",
            "404",
        ]

        if any(marker in lowered_title for marker in dead_markers):
            return True
        if any(marker in lowered_body for marker in dead_markers):
            return True
        if "/404" in lowered_url:
            return True
        return False

    def run(self) -> None:
        if not self.db.acquire_lock():
            print("❌ Error: Another instance of the agent is running. Please stop it first.")
            return

        self.logger.info("Starting skipped-jobs maintenance task", extra={"step": "M.0"})

        try:
            skipped_jobs = self.db.get_jobs_by_status(["Skipped"])
            if not skipped_jobs:
                self.logger.info("No skipped jobs to verify", extra={"step": "M.1"})
                print("ℹ️ No skipped jobs to verify.")
                return

            sync_api = importlib.import_module("playwright.sync_api")
            sync_playwright = getattr(sync_api, "sync_playwright")

            closed_count = 0
            kept_count = 0

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self.headless)
                page = browser.new_page()
                page.set_default_timeout(30000)

                for job in skipped_jobs:
                    job_title = job.get("title") or "Unknown title"
                    job_company = job.get("company") or "Unknown company"
                    job_url = job.get("url") or ""
                    self.logger.info(
                        f"Checking skipped job URL: {job_title} @ {job_company}",
                        extra={"step": "M.2"},
                    )

                    is_closed = False
                    try:
                        response = page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_timeout(1000)
                        title = page.title()
                        body = page.content()

                        if response and response.status in {404, 410}:
                            is_closed = True
                        elif self._looks_closed(title=title, body=body, url=page.url):
                            is_closed = True
                    except Exception as exc:
                        self.logger.info(
                            f"Skipped job URL check failed (keeping Skipped): {job_title} @ {job_company} ({exc})",
                            extra={"step": "M.3"},
                        )

                    if is_closed:
                        self.db.update_job_status(job["id"], "Closed")
                        closed_count += 1
                        self.logger.info(
                            f"Marked Closed: {job_title} @ {job_company}",
                            extra={"step": "M.4"},
                        )
                    else:
                        kept_count += 1

                browser.close()

            summary = f"Skipped maintenance complete. Closed={closed_count}, StillSkipped={kept_count}"
            self.logger.info(summary, extra={"step": "M.5"})
            print(f"✅ {summary}")
        finally:
            self.db.release_lock()
            self.db.close()


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
        keep_db_open: bool = False,
    ):
        self.base_dir = base_dir
        self.max_jobs = max(5, min(max_jobs, 10))
        self.headless = headless
        self.query = query
        self.user_data_dir = user_data_dir
        self.max_run_seconds = max(30, max_run_seconds)
        self.max_extract_seconds = max(15, max_extract_seconds)
        self.per_card_seconds = max(5, per_card_seconds)
        self.keep_db_open = keep_db_open
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

    @staticmethod
    def _canonicalize_job_url(url: str) -> str:
        cleaned = (url or "").strip()
        if not cleaned:
            return ""
        cleaned = cleaned.split("?", 1)[0]
        cleaned = cleaned.split("#", 1)[0]
        view_match = re.search(r"linkedin\.com/jobs/view/(\d+)", cleaned)
        if view_match:
            return f"https://www.linkedin.com/jobs/view/{view_match.group(1)}/"
        return cleaned

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

        run_results_content = "".join(cards_html) if cards_html else "<p>No jobs were extracted in this run.</p>"

        db_jobs = self.db.get_all_jobs()
        db_rows: List[str] = []
        for job in db_jobs:
            status_options = "".join(
                [
                    f"<option value='{html.escape(status)}'{' selected' if status == job['status'] else ''}>{html.escape(status)}</option>"
                    for status in UserDBUpdateMode.STATUSES
                ]
            )
            db_rows.append(
                "".join(
                    [
                        "<tr>",
                        f"<td>{job['id']}</td>",
                        f"<td>{html.escape(job['title'] or 'N/A')}</td>",
                        f"<td>{html.escape(job['company'] or 'N/A')}</td>",
                        f"<td><a href='{html.escape(job['url'] or '')}' target='_blank'>{html.escape(job['url'] or '')}</a></td>",
                        (
                            "<td>"
                            f"<select class='status-select' data-job-id='{job['id']}'>"
                            f"{status_options}"
                            "</select>"
                            "</td>"
                        ),
                        f"<td>{html.escape(format_display_datetime(job.get('last_updated')))}</td>",
                        "</tr>",
                    ]
                )
            )

        db_jobs_section = (
            "".join(
                [
                    "<div class='toolbar'>",
                    "<button id='update-agent-btn' class='primary'>Update Agent</button>",
                    "<span id='apply-status-msg' class='muted'>Update Agent sends selected statuses to DB and opens DB update mode.</span>",
                    "</div>",
                    "<table><thead><tr><th>ID</th><th>Title</th><th>Company</th><th>URL</th><th>Status</th><th>Last Updated</th></tr></thead>",
                    f"<tbody>{''.join(db_rows)}</tbody></table>",
                ]
            )
            if db_rows
            else "<p>No jobs found in DB.</p>"
        )

        html_report = "".join(
            [
                "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
                "<meta name='viewport' content='width=device-width, initial-scale=1'>",
                "<title>LinkedIn Job Agent Report</title>",
                "<style>",
                "body{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#0f172a;color:#e2e8f0}",
                "h1,h2{margin:0 0 10px}",
                "h3{margin:0 0 8px}",
                ".meta{margin:0 0 16px;color:#94a3b8}",
                ".summary{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0 20px}",
                ".pill{background:#1e293b;border:1px solid #334155;border-radius:8px;padding:8px 12px}",
                ".job-card{background:#111827;border:1px solid #334155;border-radius:10px;padding:16px;margin-bottom:16px}",
                ".section{background:#111827;border:1px solid #334155;border-radius:10px;margin:14px 0;overflow:hidden}",
                "details>summary{cursor:pointer;padding:14px 16px;background:#1f2937;font-weight:700;user-select:none}",
                ".section-body{padding:14px 16px}",
                "table{width:100%;border-collapse:collapse;margin-top:10px}",
                "th,td{border:1px solid #334155;padding:8px;vertical-align:top}",
                "th{background:#1f2937}",
                "a{color:#93c5fd}",
                ".badge{background:#1d4ed8;color:#fff;border-radius:6px;padding:2px 8px}",
                ".approval{margin-top:12px;font-weight:600}",
                ".toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:10px}",
                "button.primary{background:#2563eb;color:#fff;border:1px solid #1d4ed8;border-radius:6px;padding:8px 14px;cursor:pointer}",
                "button.primary:hover{background:#1d4ed8}",
                "select.status-select{width:100%;min-width:140px;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:4px;padding:4px}",
                ".muted{color:#94a3b8}",
                ".params-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}",
                ".param{background:#0b1220;border:1px solid #263244;border-radius:8px;padding:8px 10px}",
                "</style></head><body>",
                "<h1>Autonomous LinkedIn Job Agent Report</h1>",
                f"<p class='meta'><strong>Generated:</strong> {html.escape(datetime.now().strftime('%Y-%m-%d %H:%M'))} | <strong>Query:</strong> {html.escape(self.query)}</p>",
                "<details class='section'>",
                "<summary>A) Current run results and search parameters used</summary>",
                "<div class='section-body'>",
                "<div class='summary'>",
                f"<div class='pill'>Total Extracted: <strong>{len(self.report_entries)}</strong></div>",
                f"<div class='pill'>STRONG MATCH: <strong>{strong_count}</strong></div>",
                f"<div class='pill'>REVIEW MANUALLY: <strong>{review_count}</strong></div>",
                f"<div class='pill'>DO NOT APPLY: <strong>{reject_count}</strong></div>",
                "</div>",
                "<h3>Search Parameters</h3>",
                "<div class='params-grid'>",
                f"<div class='param'><strong>Query</strong><br>{html.escape(self.query)}</div>",
                f"<div class='param'><strong>Headless</strong><br>{html.escape(str(self.headless))}</div>",
                f"<div class='param'><strong>Max Jobs</strong><br>{self.max_jobs}</div>",
                f"<div class='param'><strong>Max Run Seconds</strong><br>{self.max_run_seconds}</div>",
                f"<div class='param'><strong>Max Extract Seconds</strong><br>{self.max_extract_seconds}</div>",
                f"<div class='param'><strong>Per Card Seconds</strong><br>{self.per_card_seconds}</div>",
                "</div>",
                "<h3 style='margin-top:14px'>Run Jobs</h3>",
                run_results_content,
                "</div></details>",
                "<details class='section'>",
                "<summary>B) Jobs in DB</summary>",
                f"<div class='section-body'>{db_jobs_section}</div>",
                "</details>",
                "<script>",
                "async function applyStatusUpdates(){",
                "  const msg = document.getElementById('apply-status-msg');",
                "  const btn = document.getElementById('update-agent-btn');",
                "  if (window.location.protocol === 'file:') {",
                "    msg.textContent = 'Update failed: report opened as local file. Run: python agent_engine.py --serve-latest-report';",
                "    return;",
                "  }",
                "  const selects = Array.from(document.querySelectorAll('.status-select'));",
                "  const updates = selects.map(s => ({id: Number(s.dataset.jobId), status: s.value}));",
                "  btn.disabled = true;",
                "  msg.textContent = 'Updating agent...';",
                "  try {",
                "    const res = await fetch('/apply-status-updates', {",
                "      method: 'POST',",
                "      headers: {'Content-Type': 'application/json'},",
                "      body: JSON.stringify({updates})",
                "    });",
                "    const data = await res.json();",
                "    if (!res.ok || !data.ok) { throw new Error(data.error || 'Apply failed'); }",
                "    msg.textContent = `Updated ${data.updated_count} row(s). DB update UI launched.`;",
                "  } catch (err) {",
                "    const details = (err && err.message) ? err.message : 'Unknown error';",
                "    msg.textContent = `Update failed: ${details}. Ensure server is running: python agent_engine.py --serve-latest-report`;",
                "  } finally {",
                "    btn.disabled = false;",
                "  }",
                "}",
                "document.getElementById('update-agent-btn')?.addEventListener('click', applyStatusUpdates);",
                "</script>",
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

                if title == "Unknown title" or company == "Unknown company":
                    self.log_step("3.5", f"Skipping low-quality card {index + 1}: missing title/company")
                    continue

                job_url = self._canonicalize_job_url(job_url)
                if not job_url:
                    self.log_step("3.5", f"Skipping card {index + 1}: missing job URL")
                    continue

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
                # Wait for page to fully load (job cards to render)
                self.log_step("2.2", "Waiting 10 seconds for page to fully load job cards")
                time.sleep(10)

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
                try:
                    context.close()
                except Exception as exc:
                    self.log_step("5.1", f"Browser context close warning: {exc}")
                if not self.keep_db_open:
                    self.db.close()



# ---------------------------------------------------------------------------
# Telegram Interactive Session
# ---------------------------------------------------------------------------

JERUSALEM_TZ_NAME = "Asia/Jerusalem"


def _now_jerusalem() -> datetime:
    try:
        import pytz  # type: ignore
        tz = pytz.timezone(JERUSALEM_TZ_NAME)
        return datetime.now(tz)
    except Exception:
        return datetime.now()


def _fmt_jlm(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


class TelegramJobSession:
    """
    Interactive Telegram bot session for reviewing and acting on new job results.

    States
    ------
    INTRO          – intro message sent, waiting for first command
    BROWSING_NEW   – iterating through new (this-run) jobs one by one
    BROWSING_DB    – iterating through all DB jobs one by one
    APPLYING       – "Apply" flow in progress for a specific job
    DONE           – session terminated

    Commands (case-insensitive)
    ---------------------------
    next    – send next pending job; leave current at Discovered
    apply   – mark current job Applied (and terminate any in-progress apply)
    skip    – mark current job Skipped
    done    – terminate session (process exits)
    db      – switch to DB-browse mode; send jobs one by one
    cancel  – if an apply is in progress, cancel it; otherwise no-op with help text
    """

    VALID_STATUSES = ["Discovered", "Applied", "InProcess", "RejectedMe", "RejectedByMe", "Accepted", "Skipped", "Closed"]

    # State constants
    STATE_INTRO = "INTRO"
    STATE_BROWSING_NEW = "BROWSING_NEW"
    STATE_BROWSING_DB = "BROWSING_DB"
    STATE_APPLYING = "APPLYING"
    STATE_DONE = "DONE"

    def __init__(
        self,
        bot_token: str,
        chat_id: int,
        db: "ProcessedJobsDB",
        new_jobs: List[Dict],
        query: str,
        logger: logging.Logger,
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.db = db
        self.new_jobs: List[Dict] = new_jobs        # jobs found in this run
        self.query = query
        self.logger = logger

        self._state: str = self.STATE_INTRO
        self._new_job_idx: int = 0                  # cursor into new_jobs
        self._db_jobs: List[Dict] = []              # populated when entering DB-browse mode
        self._db_job_idx: int = 0                   # cursor into _db_jobs
        self._current_job: Optional[Dict] = None    # job under review / being applied
        self._apply_in_progress_job_id: Optional[int] = None  # DB id of job being applied

    # ------------------------------------------------------------------
    # Low-level Telegram send helpers
    # ------------------------------------------------------------------

    def _send(self, text: str, parse_mode: str = "HTML") -> None:
        """Send a message via the Bot API (blocking HTTP)."""
        import urllib.request
        import urllib.parse
        payload = json.dumps({
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }).encode("utf-8")
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                pass
        except Exception as exc:
            self.logger.warning(f"Telegram send failed: {exc}")

    def _send_document(self, filename: str, content: bytes, caption: str = "") -> None:
        """Send a file (e.g. HTML) via the Bot API using multipart/form-data."""
        import urllib.request
        import uuid
        boundary = uuid.uuid4().hex
        CRLF = b"\r\n"

        def part_field(name: str, value: str) -> bytes:
            return (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")

        body = (
            part_field("chat_id", str(self.chat_id))
            + (part_field("caption", caption) if caption else b"")
            + (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
                f"Content-Type: text/html\r\n\r\n"
            ).encode("utf-8")
            + content
            + CRLF
            + f"--{boundary}--\r\n".encode("utf-8")
        )
        url = f"https://api.telegram.org/bot{self.bot_token}/sendDocument"
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                pass
        except Exception as exc:
            self.logger.warning(f"Telegram sendDocument failed: {exc}")

    def _get_updates(self, offset: int, timeout: int = 20) -> List[Dict]:
        """Long-poll for new messages."""
        import urllib.request
        url = (
            f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
            f"?offset={offset}&timeout={timeout}&allowed_updates=%5B%22message%22%5D"
        )
        try:
            with urllib.request.urlopen(url, timeout=timeout + 5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("result", [])
        except Exception as exc:
            self.logger.warning(f"Telegram getUpdates failed: {exc}")
            return []

    # ------------------------------------------------------------------
    # Job card helpers
    # ------------------------------------------------------------------

    def _job_card_text(self, job: Dict, index: int, total: int) -> str:
        title   = html.escape(job.get("title") or "Unknown")
        company = html.escape(job.get("company") or "Unknown")
        url     = job.get("url") or ""
        status  = html.escape(job.get("status") or "Discovered")
        jid     = job.get("id", "?")
        return (
            f"<b>Job {index}/{total}</b>  |  ID: <code>{jid}</code>\n"
            f"<b>{title}</b>\n"
            f"🏢 {company}\n"
            f"📌 Status: {status}\n"
            f'🔗 <a href="{url}">{url}</a>\n\n'
            "Reply: <b>Next</b> | <b>Apply</b> | <b>Skip</b> | <b>Done</b>"
        )

    def _db_card_text(self, job: Dict, index: int, total: int) -> str:
        title   = html.escape(job.get("title") or "Unknown")
        company = html.escape(job.get("company") or "Unknown")
        url     = job.get("url") or ""
        status  = html.escape(job.get("status") or "")
        jid     = job.get("id", "?")
        return (
            f"<b>[DB] Job {index}/{total}</b>  |  ID: <code>{jid}</code>\n"
            f"<b>{title}</b>\n"
            f"🏢 {company}\n"
            f"📌 Status: {status}\n"
            f'🔗 <a href="{url}">{url}</a>\n\n'
            "Reply: <b>Next</b> | <b>Apply</b> | <b>Skip</b> | <b>Done</b>"
        )

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    def _handle_command(self, raw: str) -> bool:
        """
        Process a single user message.  Returns True if session should
        continue, False if it should terminate (Done).
        """
        cmd = raw.strip().lower()

        # --- In-progress apply guard -----------------------------------------
        if self._apply_in_progress_job_id is not None:
            if cmd == "cancel":
                return self._cmd_cancel_apply()
            # Any unrecognised message while apply is in progress
            jid = self._apply_in_progress_job_id
            self._send(
                f"⚠️ Job application for job ID <code>{jid}</code> is still in progress.\n"
                "Reply <b>Cancel</b> to abort it."
            )
            return True

        # --- Global commands -------------------------------------------------
        if cmd == "done":
            return self._cmd_done()
        if cmd == "db":
            return self._cmd_db()
        if cmd == "cancel":
            self._send("ℹ️ No application is currently in progress.")
            return True

        # --- Browsing context ------------------------------------------------
        current_list   = self.new_jobs if self._state == self.STATE_BROWSING_NEW else self._db_jobs
        current_idx    = self._new_job_idx if self._state == self.STATE_BROWSING_NEW else self._db_job_idx
        in_browse_mode = self._state in (self.STATE_BROWSING_NEW, self.STATE_BROWSING_DB)

        if cmd == "next":
            return self._cmd_next()
        if cmd == "apply":
            return self._cmd_apply()
        if cmd == "skip":
            return self._cmd_skip()

        # Unrecognised
        self._send(
            "❓ Unknown command.\n"
            "Available: <b>Next</b> | <b>Apply</b> | <b>Skip</b> | <b>Done</b> | <b>db</b> | <b>Cancel</b>"
        )
        return True

    # --- individual command handlers -----------------------------------------

    def _cmd_done(self) -> bool:
        self._send("✅ Session complete. See you next run! 👋")
        self._state = self.STATE_DONE
        return False  # terminate

    def _cmd_db(self) -> bool:
        self._db_jobs = [
            j for j in self.db.get_all_jobs()
            if j.get("title") != "Unknown title" and j.get("company") != "Unknown company"
        ]
        if not self._db_jobs:
            self._send("📭 No jobs in the database yet.")
            return True
        self._db_job_idx = 0
        self._state = self.STATE_BROWSING_DB
        self._current_job = self._db_jobs[0]
        total = len(self._db_jobs)
        self._send(self._db_card_text(self._current_job, 1, total))
        return True

    def _cmd_next(self) -> bool:
        # Leave current job at its current status (Discovered stays Discovered)
        if self._state == self.STATE_BROWSING_NEW:
            self._new_job_idx += 1
            if self._new_job_idx >= len(self.new_jobs):
                self._send("✅ No more new jobs from this run.\nReply <b>db</b> to browse all DB jobs, or <b>Done</b> to finish.")
                self._state = self.STATE_INTRO
                self._current_job = None
                return True
            self._current_job = self.new_jobs[self._new_job_idx]
            total = len(self.new_jobs)
            self._send(self._job_card_text(self._current_job, self._new_job_idx + 1, total))
            return True

        if self._state == self.STATE_BROWSING_DB:
            self._db_job_idx += 1
            if self._db_job_idx >= len(self._db_jobs):
                self._send("✅ No more jobs in the database.\nReply <b>Done</b> to finish.")
                self._state = self.STATE_INTRO
                self._current_job = None
                return True
            self._current_job = self._db_jobs[self._db_job_idx]
            total = len(self._db_jobs)
            self._send(self._db_card_text(self._current_job, self._db_job_idx + 1, total))
            return True

        # INTRO state – treat as "start browsing new jobs"
        self._send("💡 Tip: Reply <b>Next</b> again to start browsing new jobs, or <b>db</b> to browse all DB jobs.")
        return True

    def _cmd_apply(self) -> bool:
        if self._current_job is None:
            self._send("⚠️ No active job selected. Reply <b>Next</b> to get the first job.")
            return True
        job_id = self._current_job.get("id")
        title  = self._current_job.get("title", "?")
        company = self._current_job.get("company", "?")
        try:
            self.db.update_job_status(job_id, "Applied")
            self.logger.info(f"Telegram: Applied -> {title} @ {company} (id={job_id})")
        except Exception as exc:
            self._send(f"❌ DB update failed: {html.escape(str(exc))}")
            return True
        self._send(
            f"✅ Marked <b>{html.escape(title)}</b> @ <b>{html.escape(company)}</b> as <b>Applied</b>.\n\n"
            "Reply <b>Next</b> to continue | <b>Done</b> to finish | <b>db</b> to browse DB"
        )
        # Advance cursor so next "Next" shows the following job
        if self._state == self.STATE_BROWSING_NEW:
            self._new_job_idx += 1
            self._current_job = self.new_jobs[self._new_job_idx] if self._new_job_idx < len(self.new_jobs) else None
        elif self._state == self.STATE_BROWSING_DB:
            self._db_job_idx += 1
            self._current_job = self._db_jobs[self._db_job_idx] if self._db_job_idx < len(self._db_jobs) else None
        return True

    def _cmd_skip(self) -> bool:
        if self._current_job is None:
            self._send("⚠️ No active job selected. Reply <b>Next</b> to get the first job.")
            return True
        job_id  = self._current_job.get("id")
        title   = self._current_job.get("title", "?")
        company = self._current_job.get("company", "?")
        try:
            self.db.update_job_status(job_id, "Skipped")
            self.logger.info(f"Telegram: Skipped -> {title} @ {company} (id={job_id})")
        except Exception as exc:
            self._send(f"❌ DB update failed: {html.escape(str(exc))}")
            return True
        self._send(
            f"⏭️ Skipped <b>{html.escape(title)}</b> @ <b>{html.escape(company)}</b>.\n\n"
            "Reply <b>Next</b> | <b>Done</b> | <b>db</b>"
        )
        if self._state == self.STATE_BROWSING_NEW:
            self._new_job_idx += 1
            self._current_job = self.new_jobs[self._new_job_idx] if self._new_job_idx < len(self.new_jobs) else None
        elif self._state == self.STATE_BROWSING_DB:
            self._db_job_idx += 1
            self._current_job = self._db_jobs[self._db_job_idx] if self._db_job_idx < len(self._db_jobs) else None
        return True

    def _cmd_cancel_apply(self) -> bool:
        jid = self._apply_in_progress_job_id
        self._apply_in_progress_job_id = None
        self._state = self.STATE_BROWSING_NEW if self.new_jobs else self.STATE_INTRO
        self._send(
            f"🚫 Application for job ID <code>{jid}</code> cancelled.\n\n"
            "Reply <b>Next</b> | <b>Done</b> | <b>db</b>"
        )
        return True

    # ------------------------------------------------------------------
    # Intro message
    # ------------------------------------------------------------------

    def send_intro(self) -> None:
        count = len(self.new_jobs)
        now_str = _fmt_jlm(_now_jerusalem())

        if count == 0:
            body = (
                f"👋 <b>Job Agent Report</b> — {now_str}\n\n"
                f"🔍 Query: <i>{html.escape(self.query)}</i>\n\n"
                "📭 No new jobs found in this run.\n\n"
                "Reply <b>db</b> to browse all DB jobs | <b>Done</b> to finish"
            )
        else:
            companies = sorted({j.get("company", "?") for j in self.new_jobs if j.get("company")})
            companies_str = ", ".join(html.escape(c) for c in companies)
            body = (
                f"👋 <b>Job Agent Report</b> — {now_str}\n\n"
                f"🔍 Query: <i>{html.escape(self.query)}</i>\n"
                f"📋 <b>{count} new job(s)</b> found:\n"
                f"🏢 {companies_str}\n\n"
                "Commands:\n"
                "  <b>Next</b>  – review first job\n"
                "  <b>db</b>    – browse all DB jobs\n"
                "  <b>Done</b>  – finish for today"
            )
        self._send(body)
        self._state = self.STATE_INTRO
        if self.new_jobs:
            self._state = self.STATE_BROWSING_NEW
            # Pre-load first job so the user can reply Apply/Skip without Next
            self._current_job = self.new_jobs[0]
            self._send(self._job_card_text(self._current_job, 1, count))

    # ------------------------------------------------------------------
    # Main event loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Block until the session ends (user says Done or process is interrupted)."""
        self.send_intro()

        if self._state == self.STATE_DONE:
            return

        offset = 0
        self.logger.info("Telegram session started, entering poll loop")

        while True:
            updates = self._get_updates(offset=offset, timeout=20)
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message", {})
                # Only accept messages from our chat
                if str(message.get("chat", {}).get("id", "")) != str(self.chat_id):
                    continue
                text = (message.get("text") or "").strip()
                if not text:
                    continue
                self.logger.info(f"Telegram message received: {text!r}")
                keep_going = self._handle_command(text)
                if not keep_going:
                    self.logger.info("Telegram session ended by user (Done)")
                    return


# ---------------------------------------------------------------------------
# Telegram notify entry point – called after LinkedInJobAgent.run()
# ---------------------------------------------------------------------------

def run_telegram_notify(
    new_jobs: List[Dict],
    db: "ProcessedJobsDB",
    query: str,
    logger: logging.Logger,
    bot_token: Optional[str] = None,
    chat_id: Optional[int] = None,
) -> None:
    """
    Start an interactive Telegram session.  Reads BOT_TOKEN and CHAT_ID from
    environment variables if not provided.
    """
    token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    cid_raw = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token:
        logger.error("Telegram notify: TELEGRAM_BOT_TOKEN not set. Skipping.")
        print("❌ TELEGRAM_BOT_TOKEN not set. Set it as an environment variable.")
        return
    if not cid_raw:
        logger.error("Telegram notify: TELEGRAM_CHAT_ID not set. Skipping.")
        print("❌ TELEGRAM_CHAT_ID not set. Set it as an environment variable.")
        return

    try:
        cid = int(cid_raw)
    except ValueError:
        logger.error(f"Telegram notify: TELEGRAM_CHAT_ID is not a valid integer: {cid_raw!r}")
        print(f"❌ TELEGRAM_CHAT_ID must be a numeric chat ID, got: {cid_raw!r}")
        return

    session = TelegramJobSession(
        bot_token=token,
        chat_id=cid,
        db=db,
        new_jobs=new_jobs,
        query=query,
        logger=logger,
    )
    session.run()


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
    parser.add_argument(
        "--user-db-update",
        action="store_true",
        help="Run Windows GUI mode to update job status in the database",
    )
    parser.add_argument(
        "--user-db-update-cli",
        action="store_true",
        help="Run console (text) mode to update job status in the database",
    )
    parser.add_argument(
        "--run-skipped-maintenance",
        action="store_true",
        help="Run scheduled task to verify skipped jobs by URL and mark closed jobs",
    )
    parser.add_argument(
        "--serve-latest-report",
        action="store_true",
        help="Serve latest HTML report with status-apply endpoint",
    )
    parser.add_argument(
        "--report-host",
        type=str,
        default="127.0.0.1",
        help="Host for report server",
    )
    parser.add_argument(
        "--report-port",
        type=int,
        default=8765,
        help="Port for report server",
    )
    parser.add_argument(
        "--no-open-browser",
        action="store_true",
        help="Do not auto-open browser when serving report",
    )
    parser.add_argument(
        "--easy-mode",
        action="store_true",
        help="One-step mode: run scan once, then open report update page",
    )
    parser.add_argument(
        "--telegram-notify",
        action="store_true",
        help=(
            "After scanning, start an interactive Telegram session. "
            "Requires env vars TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
        ),
    )
    parser.add_argument(
        "--telegram-bot-token",
        type=str,
        default=None,
        help="Telegram bot token (overrides TELEGRAM_BOT_TOKEN env var)",
    )
    parser.add_argument(
        "--telegram-chat-id",
        type=int,
        default=None,
        help="Telegram chat ID (overrides TELEGRAM_CHAT_ID env var)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent

    if args.easy_mode:
        run_easy_mode(args=args, base_dir=base_dir)
        return

    if args.run_skipped_maintenance:
        maintenance = SkippedJobsMaintenanceTask(
            base_dir=base_dir,
            headless=True,
        )
        maintenance.run()
        return

    if args.serve_latest_report:
        server = ReportActionsServer(
            base_dir=base_dir,
            host=args.report_host,
            port=args.report_port,
            open_browser=not args.no_open_browser,
        )
        server.run()
        return

    if args.user_db_update:
        updater_gui = UserDBUpdateGUI(base_dir=base_dir)
        updater_gui.run()
        return

    if args.user_db_update_cli:
        updater = UserDBUpdateMode(base_dir=base_dir)
        updater.run()
        return

    agent = LinkedInJobAgent(
        base_dir=base_dir,
        max_jobs=args.max_jobs,
        headless=args.headless,
        query=args.query,
        user_data_dir=args.user_data_dir,
        max_run_seconds=args.max_run_seconds,
        max_extract_seconds=args.max_extract_seconds,
        per_card_seconds=args.per_card_seconds,
        keep_db_open=args.telegram_notify,
    )
    agent.run()

    if args.telegram_notify:
        # Build new-job list from DB records whose URLs match this run's report
        reported_urls = {e["url"] for e in (agent.report_entries or [])}
        all_db = agent.db.get_all_jobs()
        new_job_dicts = [j for j in all_db if j.get("url") in reported_urls]
        try:
            run_telegram_notify(
                new_jobs=new_job_dicts,
                db=agent.db,
                query=args.query,
                logger=agent.logger,
                bot_token=args.telegram_bot_token,
                chat_id=args.telegram_chat_id,
            )
        finally:
            agent.db.close()


if __name__ == "__main__":
    main()