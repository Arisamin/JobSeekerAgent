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


def normalize_form_label(value: str) -> str:
    label = normalize_space(value)
    label = re.sub(r"\s*\(required\)\s*", " ", label, flags=re.IGNORECASE)
    label = label.replace("*", " ")
    label = re.sub(r"^[\-•·\s]+", "", label)
    return normalize_space(label)


def extract_question_label_from_block_text(block_text: str) -> str:
    lines = [normalize_form_label(line) for line in (block_text or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    for line in lines:
        if "?" in line:
            return line

    noise_values = {
        "yes",
        "no",
        "y",
        "n",
        "none",
        "n/a",
        "na",
        "prefer not to say",
        "select",
        "choose",
        "next",
        "review",
        "submit",
    }
    for line in lines:
        lowered = line.lower()
        if lowered not in noise_values:
            return line

    return lines[0]


def is_linkedin_login_page(url: str) -> bool:
    """Return True if the URL indicates LinkedIn redirected us to a login wall."""
    if not url:
        return False
    markers = ("/login", "/checkpoint/lg/", "/uas/login", "/authwall")
    return any(m in url for m in markers)


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
    INTRO           – intro message sent, waiting for first command
    BROWSING_NEW    – iterating through new (this-run) jobs one by one
    BROWSING_DB     – iterating through all DB jobs one by one
    APPLYING        – Q&A form in progress (collecting answers for a job)
    APPLY_CONFIRM   – summary shown, waiting for Submit or Cancel
    DONE            – session terminated

    Commands (case-insensitive)
    ---------------------------
    next            – send next pending job; leave current at Discovered
    next <name>     – jump to next job whose title/company/url contains <name>
    apply   – start application Q&A flow (collects data, then shows summary)
    submit  – (after summary) fill & submit LinkedIn Easy Apply form; mark Applied only on success
    preview – (after summary) fill LinkedIn Easy Apply form and stop before Submit for visual review
    skip    – mark current job Skipped
    done    – terminate session (process exits)
    db      – switch to DB-browse mode; send jobs one by one
    cancel  – abort an in-progress apply form or confirmation at any step
    cancel  – if an apply is in progress, cancel it; otherwise no-op with help text
    """

    VALID_STATUSES = ["Discovered", "Applied", "InProcess", "RejectedMe", "RejectedByMe", "Accepted", "Skipped", "Closed"]

    # State constants
    STATE_INTRO = "INTRO"
    STATE_BROWSING_NEW = "BROWSING_NEW"
    STATE_BROWSING_DB = "BROWSING_DB"
    STATE_APPLYING = "APPLYING"
    STATE_APPLY_CONFIRM = "APPLY_CONFIRM"  # waiting for Submit/Cancel after summary
    STATE_DONE = "DONE"

    # ── Always-asked fixed fields (files + contact identity) ─────────────────
    # These are asked regardless of what the form contains because we need them
    # for every submission.  They are stored in the saved profile so repeat
    # applications skip them automatically.
    FIXED_FIELDS: List[Tuple[str, str]] = [
        ("cv_path",           "📎 CV file path (full path to your PDF CV, e.g. C:\\Users\\you\\CV.pdf):"),
        ("cover_letter_path", "📝 Cover letter file path (full path, or reply 'none' if not available):"),
        ("full_name",         "✍️ Full name:"),
        ("email",             "📧 Email:"),
        ("phone",             "📱 Phone number:"),
        ("location",          "📍 Current location (City, Country):"),
        ("linkedin",          "🔗 LinkedIn profile URL:"),
    ]

    # ── Mapping: LinkedIn label text patterns → profile key ──────────────────
    # Used during form scanning to recognise a field and match it to a saved
    # profile value.  If a scanned label matches nothing here it becomes an
    # "unknown" field and is asked verbatim from the user.
    LABEL_TO_PROFILE_KEY: List[Tuple[Any, str]] = []  # populated after class body

    PROFILE_FILENAME = "telegram_profile.json"

    def __init__(
        self,
        bot_token: str,
        chat_id: int,
        db: "ProcessedJobsDB",
        new_jobs: List[Dict],
        query: str,
        logger: logging.Logger,
        easy_apply_run_mode: str = "normal",
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
        self._apply_answers: Dict[str, str] = {}
        self._apply_asked_field_keys: List[str] = []
        self._apply_question_idx: int = 0
        self._apply_form_fields: List[Tuple[str, str]] = []  # built dynamically per job
        self._apply_field_options: Dict[str, List[str]] = {}
        self._apply_field_types: Dict[str, str] = {}
        self._return_state_after_apply: str = self.STATE_INTRO
        self._profile_path: Path = self.db.db_path.parent / self.PROFILE_FILENAME
        self._saved_profile: Dict[str, str] = self._load_saved_profile()
        mode = (easy_apply_run_mode or "normal").strip().lower()
        self._easy_apply_run_mode = mode if mode in {"normal", "testing"} else "normal"

    # ------------------------------------------------------------------
    # Low-level Telegram send helpers
    # ------------------------------------------------------------------

    def _send(self, text: str, parse_mode: str = "HTML") -> None:
        """Send a message via the Bot API (blocking HTTP) with safe fallback."""
        import urllib.request
        import urllib.error

        def _to_plain(v: str) -> str:
            plain = html.unescape(v or "")
            plain = re.sub(r"<br\s*/?>", "\n", plain, flags=re.IGNORECASE)
            plain = re.sub(r"</p\s*>", "\n", plain, flags=re.IGNORECASE)
            plain = re.sub(r"<[^>]+>", "", plain)
            return plain

        def _chunk_text(v: str, limit: int = 3500) -> List[str]:
            content = (v or "").strip()
            if not content:
                return [""]
            chunks: List[str] = []
            remaining = content
            while len(remaining) > limit:
                cut = remaining.rfind("\n", 0, limit)
                if cut < 200:
                    cut = remaining.rfind(" ", 0, limit)
                if cut < 200:
                    cut = limit
                chunks.append(remaining[:cut].strip())
                remaining = remaining[cut:].strip()
            if remaining:
                chunks.append(remaining)
            return chunks or [""]

        def _send_once(message_text: str, mode: Optional[str]) -> Optional[str]:
            payload_obj: Dict[str, Any] = {
                "chat_id": self.chat_id,
                "text": message_text,
                "disable_web_page_preview": True,
            }
            if mode:
                payload_obj["parse_mode"] = mode
            payload = json.dumps(payload_obj).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                try:
                    return resp.read().decode("utf-8", errors="replace")
                except Exception:
                    return None

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        for chunk in _chunk_text(text):
            try:
                _send_once(chunk, parse_mode)
                continue
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    body = ""
                self.logger.warning(
                    f"Telegram send failed: HTTP {getattr(exc, 'code', '?')} {exc}; body={body[:800]}"
                )

                try:
                    _send_once(_to_plain(chunk), None)
                    self.logger.info("Telegram send fallback succeeded with plain text mode")
                    continue
                except Exception as plain_exc:
                    self.logger.warning(f"Telegram plain-text fallback failed: {plain_exc}")
            except Exception as exc:
                self.logger.warning(f"Telegram send failed: {exc}")

    def _send_document(self, filename: str, content: bytes, caption: str = "") -> None:
        """Send a file via the Bot API using multipart/form-data."""
        import urllib.request
        import mimetypes
        import uuid
        boundary = uuid.uuid4().hex
        CRLF = b"\r\n"

        def part_field(name: str, value: str) -> bytes:
            return (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")

        guessed_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        body = (
            part_field("chat_id", str(self.chat_id))
            + (part_field("caption", caption) if caption else b"")
            + (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
                f"Content-Type: {guessed_type}\r\n\r\n"
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

    def _send_photo(self, filename: str, content: bytes, caption: str = "") -> None:
        """Send an image via Telegram Bot API sendPhoto."""
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
                f'Content-Disposition: form-data; name="photo"; filename="{filename}"\r\n'
                f"Content-Type: image/png\r\n\r\n"
            ).encode("utf-8")
            + content
            + CRLF
            + f"--{boundary}--\r\n".encode("utf-8")
        )
        url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30):
                pass
        except Exception as exc:
            self.logger.warning(f"Telegram sendPhoto failed: {exc}")

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

    def _load_saved_profile(self) -> Dict[str, str]:
        """Load persisted profile answers for this chat, if available."""
        try:
            if not self._profile_path.exists():
                return {}
            root = json.loads(self._profile_path.read_text(encoding="utf-8"))
            chat_profiles = root.get("chat_profiles", {}) if isinstance(root, dict) else {}
            profile = chat_profiles.get(str(self.chat_id), {})
            if isinstance(profile, dict):
                return {str(k): str(v) for k, v in profile.items() if v is not None}
        except Exception as exc:
            self.logger.warning(f"Failed to load saved Telegram profile: {exc}")
        return {}

    def _persist_saved_profile(self) -> None:
        """Persist current profile answers for this chat."""
        try:
            root: Dict[str, Any] = {}
            if self._profile_path.exists():
                try:
                    loaded = json.loads(self._profile_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        root = loaded
                except Exception:
                    root = {}

            chat_profiles = root.get("chat_profiles")
            if not isinstance(chat_profiles, dict):
                chat_profiles = {}
            chat_profiles[str(self.chat_id)] = self._saved_profile
            root["chat_profiles"] = chat_profiles
            self._profile_path.write_text(json.dumps(root, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self.logger.warning(f"Failed to persist Telegram profile: {exc}")

    def _scan_is_radio_selected(self, radio_input: Any) -> bool:
        try:
            return radio_input.is_checked(timeout=200)
        except Exception:
            try:
                checked_attr = (radio_input.get_attribute("checked", timeout=200) or "").strip().lower()
                return checked_attr in {"checked", "true", "1"}
            except Exception:
                return False

    def _scan_try_select_radio_input(
        self,
        radio_input: Any,
        root: Any,
        question_label: str = "",
        testing_mode: bool = False,
    ) -> bool:
        try:
            radio_input.check(timeout=700)
            if testing_mode:
                self.logger.info(
                    f"Scan prefill radio: selected via check()"
                    f"{f' | question={question_label!r}' if question_label else ''}"
                )
            return True
        except Exception:
            pass
        try:
            radio_input.click(timeout=700)
            if testing_mode:
                self.logger.info(
                    f"Scan prefill radio: selected via direct click()"
                    f"{f' | question={question_label!r}' if question_label else ''}"
                )
            return True
        except Exception:
            pass
        try:
            radio_id = (radio_input.get_attribute("id", timeout=200) or "").strip()
            if radio_id:
                lbl = root.locator(f"label[for='{radio_id}']").first
                if lbl.count() > 0 and lbl.is_visible(timeout=200):
                    lbl.click(timeout=700)
                    if testing_mode:
                        self.logger.info(
                            f"Scan prefill radio: selected via label[for] fallback"
                            f"{f' | question={question_label!r}' if question_label else ''}"
                        )
                    return True
        except Exception:
            pass
        try:
            wrapper = radio_input.locator("xpath=ancestor::label[1]").first
            if wrapper.count() > 0 and wrapper.is_visible(timeout=200):
                wrapper.click(timeout=700)
                if testing_mode:
                    self.logger.info(
                        f"Scan prefill radio: selected via ancestor<label> fallback"
                        f"{f' | question={question_label!r}' if question_label else ''}"
                    )
                return True
        except Exception:
            pass
        if testing_mode:
            self.logger.info(
                f"Scan prefill radio: failed to select any option"
                f"{f' | question={question_label!r}' if question_label else ''}"
            )
        return False

    def _scan_pick_visible_radio_indexes(self, group: Any, root: Any) -> List[int]:
        choices: List[int] = []
        for idx in range(group.count()):
            try:
                candidate = group.nth(idx)
                if candidate.is_visible(timeout=150):
                    choices.append(idx)
                    continue
                rid = (candidate.get_attribute("id", timeout=150) or "").strip()
                if rid:
                    rl = root.locator(f"label[for='{rid}']").first
                    if rl.count() > 0 and rl.is_visible(timeout=150):
                        choices.append(idx)
            except Exception:
                continue
        return choices

    # ------------------------------------------------------------------
    # Dynamic form-field discovery
    # ------------------------------------------------------------------

    def _scan_easy_apply_fields(
        self,
        job_url: str,
        seed_answers: Optional[Dict[str, str]] = None,
    ) -> List[Tuple[str, str, str]]:
        """
        Open the Easy Apply modal for *job_url* (without submitting), walk every
        wizard step, and return a list of discovered fields:

            [(field_key, label_text, field_type), ...]

        field_type is one of: 'text', 'email', 'tel', 'textarea', 'radio',
        'checkbox', 'select', 'file', 'unknown'.
        field_key is either a known profile key (matched via LABEL_TO_PROFILE_KEY)
        or a sanitised slug of the label text prefixed with 'custom__'.

        Returns an empty list on any failure (caller falls back gracefully).
        """
        import os as _os
        try:
            sync_api = importlib.import_module("playwright.sync_api")
            sync_playwright = getattr(sync_api, "sync_playwright")
            target_closed_error = getattr(sync_api, "TargetClosedError", Exception)
        except ImportError:
            return []

        local_app_data = _os.environ.get("LOCALAPPDATA", "")
        primary_profile = _os.path.join(local_app_data, "Google", "Chrome", "User Data") if local_app_data else ""
        fallback_profile = str(Path(__file__).parent / ".playwright_profile")

        testing_mode = self._easy_apply_run_mode in {"testing", "normal"}
        easy_apply_headless = self._easy_apply_run_mode == "normal"
        seed_answers_map = {k: (v or "") for k, v in (seed_answers or {}).items()}
        discovered: List[Tuple[str, str, str]] = []
        discovered_options: Dict[str, List[str]] = {}
        seen_keys: set = set()

        def _random_digits(length: int) -> str:
            return "".join(random.choice("0123456789") for _ in range(length))

        def _random_testing_value(label_text: str, field_type: str) -> str:
            label_lower = (label_text or "").lower()
            ftype = (field_type or "text").lower()
            token = random.randint(100, 999)

            if "email" in label_lower or ftype == "email":
                return f"test{token}@example.com"
            if "phone" in label_lower or "mobile" in label_lower or ftype == "tel":
                return f"05{_random_digits(8)}"
            if "linkedin" in label_lower:
                return f"https://www.linkedin.com/in/test-user-{token}"
            if "github" in label_lower:
                return f"https://github.com/test-user-{token}"
            if "website" in label_lower or "portfolio" in label_lower or ftype == "url":
                return f"https://example.com/profile-{token}"
            if "salary" in label_lower or "compensation" in label_lower:
                return str(random.randint(20000, 90000))
            if "notice" in label_lower or "availability" in label_lower:
                return random.choice(["Immediate", "2 weeks", "1 month"])
            if "experience" in label_lower and ("year" in label_lower or ftype == "number"):
                return str(random.randint(2, 15))
            if "first" in label_lower and "name" in label_lower:
                return random.choice(["Ariel", "Dana", "Noam", "Lior"])
            if "last" in label_lower and "name" in label_lower:
                return random.choice(["Samin", "Levi", "Cohen", "Bar"])
            if "name" in label_lower:
                return random.choice(["Ariel Samin", "Dana Levi", "Noam Cohen"])
            if "city" in label_lower or "location" in label_lower:
                return random.choice(["Tel Aviv", "Jerusalem", "Haifa", "Bangkok"])
            if ftype == "number":
                return str(random.randint(1, 999))
            if ftype == "date":
                return "2026-12-01"
            if ftype == "textarea":
                return f"Automated testing answer {token}"
            return f"test-{token}"

        def _label_for(page: Any, inp: Any) -> str:
            """Best-effort label text for a form element."""
            for attr in ("aria-label",):
                try:
                    v = inp.get_attribute(attr, timeout=400)
                    if v and v.strip():
                        return normalize_form_label(v)
                except Exception:
                    pass
            try:
                inp_id = inp.get_attribute("id", timeout=400) or ""
                if inp_id:
                    lbl = page.locator(f"label[for='{inp_id}']").first
                    if lbl.count() > 0:
                        t = lbl.inner_text(timeout=400)
                        if t and t.strip():
                            return normalize_form_label(t)
            except Exception:
                pass
            try:
                t = inp.get_attribute("placeholder", timeout=400)
                if t and t.strip():
                    return normalize_form_label(t)
            except Exception:
                pass
            # Walk up to the nearest fieldset/div and grab its first text node
            try:
                ctx_text = (
                    inp.locator("xpath=ancestor::*[self::fieldset or self::div][1]")
                    .inner_text(timeout=400)
                    .strip()
                )
                if ctx_text:
                    return extract_question_label_from_block_text(ctx_text)
            except Exception:
                pass
            return ""

        def _profile_key_for(label: str) -> Optional[str]:
            label_lower = label.lower()
            for pattern, key in self.LABEL_TO_PROFILE_KEY:
                if pattern.search(label_lower):
                    return key
            return None

        def _slug(text: str) -> str:
            """Sanitise label text into a safe dict key."""
            return re.sub(r"[^a-z0-9_]", "_", text.lower().strip())[:60]

        def _answer_for_label(label: str) -> str:
            normalized = normalize_form_label(label or "")
            if not normalized:
                return ""
            profile_key = _profile_key_for(normalized)
            if profile_key:
                seeded = (seed_answers_map.get(profile_key) or "").strip()
                if seeded:
                    return seeded
                saved = (self._saved_profile.get(profile_key) or "").strip()
                if saved:
                    return saved
            custom_key = f"custom__{_slug(normalized)}"
            seeded_custom = (seed_answers_map.get(custom_key) or "").strip()
            if seeded_custom:
                return seeded_custom
            return ""

        def _merge_options(key: str, options: List[str]) -> None:
            if not options:
                return
            bucket = discovered_options.setdefault(key, [])
            for option in options:
                normalized = normalize_form_label(option or "")
                if not normalized:
                    continue
                lowered = normalized.lower()
                if lowered in {"select", "choose", "اختر", "--", "n/a", "na"}:
                    continue
                if any(existing.lower() == lowered for existing in bucket):
                    continue
                bucket.append(normalized)
                if len(bucket) >= 8:
                    break

        def _add(key: str, label: str, ftype: str, options: Optional[List[str]] = None) -> None:
            _merge_options(key, options or [])
            if key in seen_keys:
                return
            seen_keys.add(key)
            discovered.append((key, label, ftype))

        def _is_advance_action(btn_text: str, btn_aria: str) -> bool:
            text = (btn_text or "").strip().lower()
            aria = (btn_aria or "").strip().lower()
            haystack = f"{text} {aria}"
            advance_tokens = [
                "next", "continue", "review",
                "التالي", "الاستمرار", "مراجعة",
            ]
            return any(token in haystack for token in advance_tokens)

        def _is_submit_action(btn_text: str, btn_aria: str) -> bool:
            text = (btn_text or "").strip().lower()
            aria = (btn_aria or "").strip().lower()
            haystack = f"{text} {aria}"
            submit_tokens = ["submit", "ارسال", "إرسال", "تقديم"]
            return any(token in haystack for token in submit_tokens)

        def _scan_step(page: Any, scope: Optional[Any] = None) -> None:
            root = scope if scope is not None else page
            # File inputs
            for fi in root.locator("input[type='file']").all():
                try:
                    if not fi.is_visible(timeout=400):
                        continue
                    label = _label_for(page, fi)
                    ll = label.lower()
                    if "cover" in ll:
                        _add("cover_letter_path", label or "Cover letter", "file")
                    else:
                        _add("cv_path", label or "Resume / CV", "file")
                except Exception:
                    pass

            # Text / email / tel / textarea inputs
            sel = (
                "input[type='text'], input[type='email'], input[type='tel'], input[type='url'], "
                "input[type='number'], input[type='date'], input:not([type]), textarea"
            )
            for inp in root.locator(sel).all():
                try:
                    if not inp.is_visible(timeout=400):
                        continue
                    label = _label_for(page, inp)
                    if not label:
                        continue
                    try:
                        ftype = inp.get_attribute("type", timeout=400) or "text"
                    except Exception:
                        ftype = "text"
                    if inp.evaluate("el => el.tagName").lower() == "textarea":
                        ftype = "textarea"
                    pk = _profile_key_for(label)
                    key = pk if pk else f"custom__{_slug(label)}"
                    _add(key, label, ftype)
                except Exception:
                    pass

            # ARIA textboxes used by custom widgets
            for tb in root.locator("[role='textbox']").all():
                try:
                    if not tb.is_visible(timeout=300):
                        continue
                    label = _label_for(page, tb)
                    if not label:
                        continue
                    pk = _profile_key_for(label)
                    key = pk if pk else f"custom__{_slug(label)}"
                    _add(key, label, "text")
                except Exception:
                    continue

            # Select dropdowns
            for sel_el in root.locator("select").all():
                try:
                    if not sel_el.is_visible(timeout=400):
                        continue
                    label = _label_for(page, sel_el)
                    if not label:
                        continue
                    pk = _profile_key_for(label)
                    key = pk if pk else f"custom__{_slug(label)}"
                    options: List[str] = []
                    try:
                        for opt in sel_el.locator("option").all():
                            txt = normalize_form_label(opt.inner_text(timeout=200))
                            if txt:
                                options.append(txt)
                    except Exception:
                        pass
                    _add(key, label, "select", options=options)
                except Exception:
                    pass

            # Custom combobox dropdowns
            for cb in root.locator("[role='combobox']").all():
                try:
                    if not cb.is_visible(timeout=300):
                        continue
                    label = _label_for(page, cb)
                    if not label:
                        continue
                    pk = _profile_key_for(label)
                    key = pk if pk else f"custom__{_slug(label)}"
                    _add(key, label, "select")
                except Exception:
                    continue

            # Radio/checkbox groups — grab question from fieldset legend
            for fieldset in root.locator("fieldset").all():
                try:
                    if not fieldset.is_visible(timeout=400):
                        continue
                    legend = ""
                    try:
                        legend = normalize_form_label(fieldset.locator("legend").first.inner_text(timeout=400))
                    except Exception:
                        pass
                    if not legend:
                        try:
                            legend = extract_question_label_from_block_text(fieldset.inner_text(timeout=400))
                        except Exception:
                            pass
                    if not legend:
                        continue
                    # Determine type from first input inside
                    first_inp = fieldset.locator("input").first
                    ftype = "radio"
                    try:
                        ftype = first_inp.get_attribute("type", timeout=400) or "radio"
                    except Exception:
                        pass
                    pk = _profile_key_for(legend)
                    key = pk if pk else f"custom__{_slug(legend)}"
                    option_labels: List[str] = []
                    try:
                        for lbl in fieldset.locator("label").all():
                            txt = normalize_form_label(lbl.inner_text(timeout=200))
                            if txt and txt.lower() != legend.lower():
                                option_labels.append(txt)
                    except Exception:
                        pass
                    _add(key, legend, ftype, options=option_labels)
                except Exception:
                    pass

            # Radio groups not wrapped in fieldset (common in custom UIs)
            handled_radio_names: set = set()
            for radio in root.locator("input[type='radio']").all():
                try:
                    if not radio.is_visible(timeout=300):
                        continue
                    name = (radio.get_attribute("name", timeout=300) or "").strip()
                    if not name or name in handled_radio_names:
                        continue
                    handled_radio_names.add(name)

                    group = root.locator(f"input[type='radio'][name='{name}']")
                    if group.count() == 0:
                        continue

                    first = group.first
                    label = ""
                    try:
                        container_text = first.locator(
                            "xpath=ancestor::*[@role='radiogroup' or self::fieldset or contains(@class, 'fb-dash-form-element') or contains(@class, 'jobs-easy-apply-form-section__grouping')][1]"
                        ).inner_text(timeout=400)
                        label = extract_question_label_from_block_text(container_text)
                    except Exception:
                        pass

                    if not label:
                        label = _label_for(page, first)
                    if not label:
                        continue

                    pk = _profile_key_for(label)
                    key = pk if pk else f"custom__{_slug(label)}"
                    option_labels: List[str] = []
                    try:
                        for idx in range(min(group.count(), 8)):
                            radio_i = group.nth(idx)
                            rid = (radio_i.get_attribute("id", timeout=200) or "").strip()
                            if rid:
                                lbl = page.locator(f"label[for='{rid}']").first
                                if lbl.count() > 0:
                                    txt = normalize_form_label(lbl.inner_text(timeout=200))
                                    if txt:
                                        option_labels.append(txt)
                    except Exception:
                        pass
                    _add(key, label, "radio", options=option_labels)
                except Exception:
                    continue

            # ARIA radio groups (custom LinkedIn controls)
            for rg in root.locator("[role='radiogroup']").all():
                try:
                    if not rg.is_visible(timeout=300):
                        continue
                    label = ""
                    try:
                        label = extract_question_label_from_block_text(rg.inner_text(timeout=400))
                    except Exception:
                        pass
                    if not label:
                        continue
                    pk = _profile_key_for(label)
                    key = pk if pk else f"custom__{_slug(label)}"
                    option_labels: List[str] = []
                    try:
                        lines = [normalize_form_label(line) for line in rg.inner_text(timeout=300).splitlines()]
                        lines = [line for line in lines if line]
                        if len(lines) > 1:
                            option_labels = lines[1:]
                    except Exception:
                        pass
                    _add(key, label, "radio", options=option_labels)
                except Exception:
                    continue

            # Standalone checkboxes (common consent/custom questions)
            for chk in root.locator("input[type='checkbox']").all():
                try:
                    if not chk.is_visible(timeout=300):
                        continue
                    label = _label_for(page, chk)
                    if not label:
                        continue
                    pk = _profile_key_for(label)
                    key = pk if pk else f"custom__{_slug(label)}"
                    _add(key, label, "checkbox")
                except Exception:
                    continue

        def _current_page_signature(page: Any, scope: Optional[Any] = None) -> str:
            root = scope if scope is not None else page
            labels: List[str] = []

            def _push(label: str) -> None:
                normalized = normalize_form_label(label or "")
                if normalized:
                    labels.append(normalized.lower())

            try:
                controls = root.locator(
                    "input, textarea, select, [role='textbox'], [role='combobox']"
                )
                for idx in range(min(controls.count(), 40)):
                    try:
                        control = controls.nth(idx)
                        if not control.is_visible(timeout=150):
                            continue
                        _push(_label_for(page, control))
                    except Exception:
                        continue
            except Exception:
                pass

            try:
                fieldsets = root.locator("fieldset")
                for idx in range(min(fieldsets.count(), 12)):
                    try:
                        fieldset = fieldsets.nth(idx)
                        if not fieldset.is_visible(timeout=150):
                            continue
                        legend = ""
                        try:
                            legend = normalize_form_label(fieldset.locator("legend").first.inner_text(timeout=200))
                        except Exception:
                            legend = ""
                        if not legend:
                            try:
                                legend = extract_question_label_from_block_text(fieldset.inner_text(timeout=200))
                            except Exception:
                                legend = ""
                        _push(legend)
                    except Exception:
                        continue
            except Exception:
                pass

            try:
                radio_groups = root.locator("[role='radiogroup']")
                for idx in range(min(radio_groups.count(), 12)):
                    try:
                        radio_group = radio_groups.nth(idx)
                        if not radio_group.is_visible(timeout=150):
                            continue
                        _push(extract_question_label_from_block_text(radio_group.inner_text(timeout=200)))
                    except Exception:
                        continue
            except Exception:
                pass

            deduped_labels = list(dict.fromkeys(label for label in labels if label))
            if deduped_labels:
                return " | ".join(deduped_labels)[:500]

            try:
                fallback_text = (root.inner_text(timeout=300) or "").strip().lower()
                return re.sub(r"\s+", " ", fallback_text)[:500]
            except Exception:
                return ""

        def _prefill_required_for_scan(page: Any, scope: Optional[Any] = None) -> None:
            """
            Best-effort prefill so scanner can pass required step validation and
            discover later wizard pages. Uses harmless placeholder values and
            never reaches Submit (loop breaks before submit click).
            """
            root = scope if scope is not None else page
            # Fill empty text-like controls
            text_like = (
                "input[type='text'], input[type='email'], input[type='tel'], input[type='url'], "
                "input[type='number'], input[type='date'], input:not([type]), textarea"
            )
            for inp in root.locator(text_like).all():
                try:
                    if not inp.is_visible(timeout=300):
                        continue
                    cur = (inp.input_value(timeout=300) or "").strip()
                    if cur:
                        continue
                    label = _label_for(page, inp).lower()
                    ftype = (inp.get_attribute("type", timeout=300) or "text").strip().lower()
                    if inp.evaluate("el => el.tagName").lower() == "textarea":
                        ftype = "textarea"

                    if testing_mode:
                        fill = _random_testing_value(label, ftype)
                    else:
                        fill = (_answer_for_label(label) or "").strip()
                        if not fill:
                            fill = "test"
                            if "email" in label:
                                fill = "test@example.com"
                            elif "phone" in label or "mobile" in label:
                                fill = "0500000000"
                            elif "linkedin" in label:
                                fill = self._saved_profile.get("linkedin") or "https://www.linkedin.com/in/test"
                            elif "github" in label:
                                fill = self._saved_profile.get("github") or "No"
                            elif "website" in label or "blog" in label:
                                fill = self._saved_profile.get("website") or "No"
                            elif "year" in label and "experience" in label:
                                fill = self._saved_profile.get("experience_years") or "5"
                            elif "salary" in label or "compensation" in label:
                                fill = self._saved_profile.get("salary_expectation") or "30000"
                            elif "notice" in label or "availability" in label:
                                fill = self._saved_profile.get("notice_period") or "1 month"
                            elif "first" in label and "name" in label:
                                fill = (self._saved_profile.get("full_name") or "Test User").split()[0]
                            elif "last" in label and "name" in label:
                                full = (self._saved_profile.get("full_name") or "Test User").split()
                                fill = full[-1] if len(full) > 1 else full[0]
                            elif "name" in label:
                                fill = self._saved_profile.get("full_name") or "Test User"
                            elif "location" in label or "city" in label:
                                fill = self._saved_profile.get("location") or "Tel Aviv"
                    inp.fill(fill, timeout=1000)
                except Exception:
                    continue

            # Fill ARIA textboxes (for custom LinkedIn controls)
            for tb in root.locator("[role='textbox']").all():
                try:
                    if not tb.is_visible(timeout=300):
                        continue
                    current_text = (tb.inner_text(timeout=300) or "").strip()
                    if current_text:
                        continue
                    label = _label_for(page, tb)
                    if testing_mode:
                        fill = _random_testing_value(label, "text")
                    else:
                        fill = _answer_for_label(label) or "test"
                    tb.click(timeout=800)
                    page.keyboard.type(fill, delay=15)
                except Exception:
                    continue

            # Select first non-empty option for required selects
            for sel_el in root.locator("select").all():
                try:
                    if not sel_el.is_visible(timeout=300):
                        continue
                    options = sel_el.locator("option").all()
                    candidates: List[str] = []
                    desired_answer = (_answer_for_label(_label_for(page, sel_el)) or "").strip().lower()
                    for opt in options:
                        try:
                            value = (opt.get_attribute("value", timeout=300) or "").strip()
                            text = (opt.inner_text(timeout=300) or "").strip().lower()
                            if not value:
                                continue
                            if text in {"select", "choose", "please select"}:
                                continue
                            candidates.append(value)
                        except Exception:
                            continue
                    picked = False
                    if desired_answer:
                        for opt in options:
                            try:
                                value = (opt.get_attribute("value", timeout=300) or "").strip()
                                text = (opt.inner_text(timeout=300) or "").strip().lower()
                                if not value:
                                    continue
                                if desired_answer in text or desired_answer == value.lower():
                                    sel_el.select_option(value=value)
                                    picked = True
                                    break
                            except Exception:
                                continue
                    if not picked and candidates:
                        try:
                            value_to_pick = random.choice(candidates) if testing_mode else candidates[0]
                            sel_el.select_option(value=value_to_pick)
                            picked = True
                        except Exception:
                            pass
                    if not picked and options:
                        try:
                            fallback_value = (options[-1].get_attribute("value", timeout=300) or "").strip()
                            if fallback_value:
                                sel_el.select_option(value=fallback_value)
                        except Exception:
                            pass
                except Exception:
                    continue

            # Fill custom combobox dropdowns (common LinkedIn component)
            for cb in root.locator("[role='combobox']").all():
                try:
                    if not cb.is_visible(timeout=300):
                        continue
                    current_text = (cb.inner_text(timeout=300) or "").strip().lower()
                    if current_text and current_text not in {"select", "choose", "בחר", "اختر"}:
                        continue
                    try:
                        cb.click(timeout=1000)
                    except Exception:
                        continue
                    page.wait_for_timeout(250)
                    options = page.locator("[role='option']")
                    if options.count() == 0:
                        continue
                    picked = False
                    candidate_indexes: List[int] = []
                    for idx in range(min(options.count(), 12)):
                        try:
                            opt = options.nth(idx)
                            if not opt.is_visible(timeout=200):
                                continue
                            text = (opt.inner_text(timeout=300) or "").strip().lower()
                            if not text or text in {"select", "choose", "בחר", "اختر"}:
                                continue
                            candidate_indexes.append(idx)
                        except Exception:
                            continue

                    if candidate_indexes:
                        try:
                            picked_idx = random.choice(candidate_indexes) if testing_mode else candidate_indexes[0]
                            options.nth(picked_idx).click(timeout=1000)
                            picked = True
                        except Exception:
                            pass

                    if not picked:
                        try:
                            page.keyboard.press("Escape")
                        except Exception:
                            pass
                except Exception:
                    continue

            # For each radio group, select first visible option if none selected
            for fieldset in root.locator("fieldset").all():
                try:
                    radios = fieldset.locator("input[type='radio']")
                    if radios.count() == 0:
                        continue
                    already_selected = False
                    for idx in range(radios.count()):
                        try:
                            r = radios.nth(idx)
                            if self._scan_is_radio_selected(r):
                                already_selected = True
                                break
                        except Exception:
                            continue
                    if already_selected:
                        continue
                    choices: List[int] = []
                    for idx in range(radios.count()):
                        try:
                            r = radios.nth(idx)
                            if r.is_visible(timeout=200):
                                choices.append(idx)
                                continue
                            rid = (r.get_attribute("id", timeout=200) or "").strip()
                            if rid:
                                rl = root.locator(f"label[for='{rid}']").first
                                if rl.count() > 0 and rl.is_visible(timeout=200):
                                    choices.append(idx)
                        except Exception:
                            continue
                    if choices:
                        pick_idx = random.choice(choices) if testing_mode else choices[0]
                        try:
                            r = radios.nth(pick_idx)
                            self._scan_try_select_radio_input(
                                radio_input=r,
                                root=root,
                                question_label=_label_for(page, r),
                                testing_mode=testing_mode,
                            )
                        except Exception:
                            pass
                except Exception:
                    continue

            # Standalone radio groups by name (outside fieldset)
            radio_names: set = set()
            for radio in root.locator("input[type='radio']").all():
                try:
                    name = (radio.get_attribute("name", timeout=200) or "").strip()
                    if not name or name in radio_names:
                        continue
                    radio_names.add(name)
                    group = root.locator(f"input[type='radio'][name='{name}']")
                    choices = self._scan_pick_visible_radio_indexes(group=group, root=root)
                    if not choices:
                        continue
                    pick_idx = random.choice(choices) if testing_mode else choices[0]
                    target = group.nth(pick_idx)
                    if not self._scan_is_radio_selected(target):
                        self._scan_try_select_radio_input(
                            radio_input=target,
                            root=root,
                            question_label=_label_for(page, target),
                            testing_mode=testing_mode,
                        )
                except Exception:
                    continue

            # ARIA radio groups (custom controls with role='radio')
            for rg in root.locator("[role='radiogroup']").all():
                try:
                    if not rg.is_visible(timeout=200):
                        continue
                    options = rg.locator("[role='radio']")
                    if options.count() == 0:
                        continue
                    already_selected = False
                    for idx in range(options.count()):
                        try:
                            aria_checked = (options.nth(idx).get_attribute("aria-checked", timeout=150) or "").strip().lower()
                            if aria_checked == "true":
                                already_selected = True
                                break
                        except Exception:
                            continue
                    if already_selected:
                        continue
                    visible_choices = []
                    for idx in range(options.count()):
                        try:
                            if options.nth(idx).is_visible(timeout=150):
                                visible_choices.append(idx)
                        except Exception:
                            continue
                    if not visible_choices:
                        continue
                    pick_idx = random.choice(visible_choices) if testing_mode else visible_choices[0]
                    try:
                        options.nth(pick_idx).click(timeout=800)
                        if testing_mode:
                            rg_label = extract_question_label_from_block_text(rg.inner_text(timeout=200))
                            self.logger.info(
                                f"Scan prefill radio: selected ARIA role='radio' option"
                                f"{f' | question={rg_label!r}' if rg_label else ''}"
                            )
                    except Exception:
                        pass
                except Exception:
                    continue

            # Check required/visible checkboxes in testing mode to unblock Next
            if testing_mode:
                for chk in root.locator("input[type='checkbox']").all():
                    try:
                        if not chk.is_visible(timeout=150):
                            continue
                        if chk.is_checked(timeout=150):
                            continue
                        try:
                            chk.check(timeout=700)
                        except Exception:
                            chk.click(timeout=700)
                    except Exception:
                        continue

        try:
            with sync_playwright() as pw:
                try:
                    ctx = pw.chromium.launch_persistent_context(
                        user_data_dir=primary_profile,
                        channel="chrome",
                        headless=easy_apply_headless,
                        no_viewport=True,
                        args=["--start-maximized"],
                        slow_mo=100,
                        locale="en-US",
                        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
                    )
                except (target_closed_error, Exception) as exc:
                    self.logger.warning(f"Scan: primary profile failed ({exc}), using fallback")
                    _os.makedirs(fallback_profile, exist_ok=True)
                    ctx = pw.chromium.launch_persistent_context(
                        user_data_dir=fallback_profile,
                        channel="chrome",
                        headless=easy_apply_headless,
                        no_viewport=True,
                        args=["--start-maximized"],
                        slow_mo=100,
                        locale="en-US",
                        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
                    )
                try:
                    page = ctx.pages[0] if ctx.pages else ctx.new_page()
                    page.set_default_timeout(20000)
                    try:
                        page.bring_to_front()
                    except Exception:
                        pass

                    page.goto(job_url, wait_until="domcontentloaded", timeout=30000)

                    # Wait for network to settle so dynamic elements render
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass  # networkidle timeout is not fatal

                    # Login-wall guard: if LinkedIn redirected us, bail early
                    current_url = page.url
                    if is_linkedin_login_page(current_url):
                        self.logger.warning(f"Scan: LinkedIn login wall detected ({current_url}), skipping scan")
                        return []

                    page.wait_for_timeout(3000)

                    # Probe for any Easy Apply element (up to 8 s) before the retry loop
                    EASY_APPLY_SELECTORS = [
                        ".jobs-apply-button",
                        "a.jobs-apply-button",
                        "button.jobs-apply-button",
                        "[data-control-name*='jobdetails_topcard_inapply']",
                        "[data-control-name*='jobdetails_topcard_inapply'] button",
                        ".jobs-apply-button--top-card",
                        ".jobs-s-apply [role='button']",
                        "button:has-text('Easy Apply')",
                        "button[aria-label*='Easy Apply']",
                        ".jobs-s-apply button",
                        "[role='button']:has-text('Easy Apply')",
                        "a:has-text('Easy Apply')",
                        "span:has-text('Easy Apply')",
                    ]
                    _combined_selector = ", ".join(EASY_APPLY_SELECTORS)
                    try:
                        page.wait_for_selector(_combined_selector, timeout=8000)
                        self.logger.info("Scan: Easy Apply element detected in DOM")
                    except Exception:
                        self.logger.warning("Scan: wait_for_selector timed out – button may not be present")

                    clicked = False
                    for _attempt in range(3):
                        if _attempt > 0:
                            page.wait_for_timeout(1500)
                        for sel in EASY_APPLY_SELECTORS:
                            try:
                                btn = page.locator(sel).first
                                if btn.count() > 0 and btn.is_visible(timeout=3000):
                                    btn.click(timeout=5000)
                                    clicked = True
                                    self.logger.info(
                                        f"Scan: clicked Easy Apply via {sel!r} "
                                        f"(attempt {_attempt + 1})"
                                    )
                                    break
                            except Exception:
                                continue
                        if clicked:
                            break

                    if not clicked:
                        # Save a screenshot so we can diagnose what the page shows
                        _shot_path = str(Path(__file__).parent / "scan_debug_screenshot.png")
                        try:
                            page.screenshot(path=_shot_path, full_page=False)
                            self.logger.info(f"Scan: debug screenshot saved → {_shot_path}")
                        except Exception as _se:
                            self.logger.debug(f"Scan: screenshot failed: {_se}")
                        self.logger.info(
                            "Scan: Easy Apply button not found after 3 attempts – "
                            f"page url: {page.url}"
                        )
                        return []

                    # Wait for the Easy Apply modal to appear
                    try:
                        page.wait_for_selector(
                            ".artdeco-modal, .jobs-easy-apply-modal",
                            timeout=8000
                        )
                        self.logger.info("Scan: Easy Apply modal opened")
                    except Exception:
                        # Modal selector not found; give a flat extra wait before scanning
                        self.logger.warning("Scan: modal selector not detected, proceeding with flat wait")
                        page.wait_for_timeout(2000)

                    # Resolve modal container for scoped operations
                    modal_scope = None
                    for _modal_sel in [".artdeco-modal", ".jobs-easy-apply-modal"]:
                        try:
                            _m = page.locator(_modal_sel).first
                            if _m.count() > 0 and _m.is_visible(timeout=500):
                                modal_scope = _m
                                self.logger.info(f"Scan: modal scope resolved via {_modal_sel!r}")
                                break
                        except Exception:
                            pass
                    if modal_scope is None:
                        self.logger.warning("Scan: modal scope not resolved, falling back to full page")

                    # Walk wizard steps (scan only – never submit)
                    max_steps = 20
                    last_page_signature = ""
                    stagnant_signature_streak = 0
                    for _step in range(max_steps):
                        page.wait_for_timeout(800)
                        before = len(discovered)
                        _scan_step(page, scope=modal_scope)
                        _prefill_required_for_scan(page, scope=modal_scope)
                        new_fields = len(discovered) - before
                        self.logger.info(f"Scan step {_step}: +{new_fields} new field(s), total={len(discovered)}")

                        page_signature = _current_page_signature(page, scope=modal_scope)

                        if page_signature and page_signature == last_page_signature:
                            stagnant_signature_streak += 1
                        else:
                            stagnant_signature_streak = 0
                        if page_signature:
                            last_page_signature = page_signature

                        if new_fields == 0 and stagnant_signature_streak >= 1:
                            self.logger.info(
                                f"Scan step {_step}: visible form content unchanged after advance; stopping wizard walk"
                            )
                            break

                        # Find advance button (language-agnostic) — scoped to modal
                        advance = None
                        advance_root = modal_scope if modal_scope is not None else page
                        for sel in [
                            ".artdeco-modal button.artdeco-button--primary",
                            ".jobs-easy-apply-modal button.artdeco-button--primary",
                            "button.artdeco-button--primary",
                            "button[aria-label*='Continue to next step']",
                            "button[aria-label*='Next']",
                            "button[aria-label*='next']",
                            "button[aria-label*='Review']",
                            "button[aria-label*='review']",
                            "button[aria-label*='التالي']",
                            "button[aria-label*='الاستمرار']",
                            "button[aria-label*='الخطوة التالية']",
                            "button[aria-label*='مراجعة']",
                            "button:has-text('Next')",
                            "button:has-text('Continue')",
                            "button:has-text('Review')",
                        ]:
                            try:
                                b = advance_root.locator(sel).last
                                if b.count() > 0 and b.is_visible(timeout=1000) and b.is_enabled(timeout=1000):
                                    advance = b
                                    break
                            except Exception:
                                continue

                        if advance is None:
                            # Robust fallback: inspect visible modal buttons directly.
                            blocked_primary = None
                            try:
                                modal_buttons = advance_root.locator("button")
                                for idx in range(modal_buttons.count()):
                                    try:
                                        b = modal_buttons.nth(idx)
                                        if not b.is_visible(timeout=300):
                                            continue
                                        cls = (b.get_attribute("class", timeout=300) or "").lower()
                                        if "artdeco-button--primary" not in cls:
                                            continue
                                        if "dismiss" in cls:
                                            continue
                                        if b.is_enabled(timeout=300):
                                            advance = b
                                            break
                                        blocked_primary = b
                                    except Exception:
                                        continue
                            except Exception:
                                pass

                            if advance is None and blocked_primary is not None:
                                try:
                                    _prefill_required_for_scan(page, scope=modal_scope)
                                    page.wait_for_timeout(500)
                                    if blocked_primary.is_enabled(timeout=500):
                                        advance = blocked_primary
                                except Exception:
                                    pass

                        if advance is None:
                            # Fallback: pick any visible primary modal action button,
                            # then retry prefill in case required custom controls are still empty.
                            for sel in [
                                "button.artdeco-button--primary",
                            ]:
                                try:
                                    cand = advance_root.locator(sel).last
                                    if cand.count() > 0 and cand.is_visible(timeout=500):
                                        if cand.is_enabled(timeout=500):
                                            advance = cand
                                            break
                                        _prefill_required_for_scan(page, scope=modal_scope)
                                        page.wait_for_timeout(500)
                                        if cand.is_enabled(timeout=500):
                                            advance = cand
                                            break
                                except Exception:
                                    continue

                        if advance is None:
                            try:
                                visible_candidates = advance_root.locator(
                                    "button:has(span.artdeco-button__text)"
                                ).filter(has_text=re.compile(r"next|continue|review|التالي|الاستمرار|مراجعة", re.IGNORECASE))
                                self.logger.info(
                                    f"Scan step {_step}: no enabled advance button found; "
                                    f"visible candidates={visible_candidates.count()}"
                                )
                            except Exception:
                                pass
                            try:
                                dbg_buttons = advance_root.locator("button")
                                dbg_count = dbg_buttons.count()
                                self.logger.info(f"Scan step {_step}: debug button count={dbg_count}")
                                for i in range(min(dbg_count, 8)):
                                    try:
                                        b = dbg_buttons.nth(i)
                                        t = (b.inner_text(timeout=200) or "").strip()
                                        a = (b.get_attribute("aria-label", timeout=200) or "").strip()
                                        c = (b.get_attribute("class", timeout=200) or "").strip()
                                        v = b.is_visible(timeout=200)
                                        e = b.is_enabled(timeout=200)
                                        self.logger.info(
                                            f"Scan step {_step}: btn[{i}] visible={v} enabled={e} text={t!r} aria={a!r} class={c!r}"
                                        )
                                    except Exception:
                                        continue
                            except Exception:
                                pass
                            self.logger.info(f"Scan step {_step}: no advance button found, stopping wizard walk")
                            break
                        btn_text = (advance.inner_text(timeout=2000) or "").strip().lower()
                        try:
                            btn_aria = (advance.get_attribute("aria-label", timeout=1000) or "").strip().lower()
                        except Exception:
                            btn_aria = ""
                        self.logger.info(f"Scan step {_step}: advance button text={btn_text!r}")
                        self.logger.info(f"Scan step {_step}: advance button aria={btn_aria!r}")
                        # Stop before Submit – we don't want to actually submit
                        if _is_submit_action(btn_text, btn_aria):
                            break
                        if not _is_advance_action(btn_text, btn_aria):
                            self.logger.info(f"Scan step {_step}: action is not an advance action, stopping")
                            break
                        advance.click(timeout=5000)
                        page.wait_for_timeout(1200)

                    if len(discovered) > 0 and _step == max_steps - 1:
                        self.logger.info(
                            f"Scan: reached max_steps={max_steps}; traversal stopped with {len(discovered)} discovered fields"
                        )

                    # Close modal / dismiss
                    for dismiss_sel in [
                        "button[aria-label*='Dismiss']",
                        "button[aria-label*='Close']",
                        "button[aria-label*='إغلاق']",
                        "button[aria-label*='رفض']",
                        ".artdeco-modal__dismiss",
                    ]:
                        try:
                            d = page.locator(dismiss_sel).first
                            if d.count() > 0 and d.is_visible(timeout=1000):
                                d.click(timeout=3000)
                                break
                        except Exception:
                            continue

                finally:
                    try:
                        ctx.close()
                    except Exception:
                        pass
        except Exception as exc:
            self.logger.warning(f"Easy Apply scan failed: {exc}")

        self._apply_field_options = discovered_options
        self.logger.info(f"Easy Apply scan: found {len(discovered)} field(s): {[k for k,_,_ in discovered]}")
        return discovered

    # ------------------------------------------------------------------
    # Per-job apply field list builder
    # ------------------------------------------------------------------

    def _build_apply_form_fields(self, scanned: List[Tuple[str, str, str]]) -> List[Tuple[str, str]]:
        """
        Merge scan results with FIXED_FIELDS to build the per-job
        _apply_form_fields list as (key, telegram_prompt) tuples.

        Logic:
        - Always start with FIXED_FIELDS (cv, cover letter, identity).
        - Append any extra fields found in the scan that are NOT already in
          FIXED_FIELDS, preserving scan order.
        - Unknown custom__ fields get a verbatim question prompt.
        """
        result: List[Tuple[str, str]] = list(self.FIXED_FIELDS)
        self._apply_field_types = {
            "cv_path": "file",
            "cover_letter_path": "file",
            "full_name": "text",
            "email": "email",
            "phone": "tel",
            "location": "text",
            "linkedin": "url",
        }
        fixed_keys = {k for k, _ in self.FIXED_FIELDS}

        def _contains_arabic(text: str) -> bool:
            return bool(re.search(r"[\u0600-\u06FF]", text or ""))

        for key, label, ftype in scanned:
            if key in fixed_keys:
                continue  # already covered
            self._apply_field_types[key] = ftype
            # Build a prompt from the label and field type
            options = self._apply_field_options.get(key, [])
            options_block = ""
            if options and ftype in {"radio", "checkbox", "select"}:
                options_lines = [f"   {index + 1}) {html.escape(opt)}" for index, opt in enumerate(options[:8])]
                options_block = "\nOptions:\n" + "\n".join(options_lines) + "\nReply with option number or text."
            arabic_note = "\n🌐 Arabic question detected; answering in English is okay." if _contains_arabic(label) else ""
            if ftype in {"radio", "checkbox"}:
                prompt = f"❓ {label} (type your answer):{options_block}{arabic_note}"
            elif ftype == "select":
                prompt = f"🔽 {label} (type your choice):{options_block}{arabic_note}"
            elif ftype == "file":
                continue  # file inputs are handled by FIXED_FIELDS
            else:
                prompt = f"✏️ {label}:{arabic_note}"
            result.append((key, prompt))
            fixed_keys.add(key)

        return result

    def _first_missing_apply_field_idx(self) -> int:
        for index, (field_key, _prompt) in enumerate(self._apply_form_fields):
            if not self._apply_answers.get(field_key):
                return index
        return len(self._apply_form_fields)

    def _send_current_apply_prompt(self) -> None:
        if self._apply_question_idx >= len(self._apply_form_fields):
            return
        key, prompt = self._apply_form_fields[self._apply_question_idx]
        if key not in self._apply_asked_field_keys:
            self._apply_asked_field_keys.append(key)
        self._send(prompt)

    def _validate_apply_answer(self, field_key: str, raw_answer: str) -> Tuple[bool, str, str]:
        """Validate one Q&A answer. Returns (is_valid, error_message, normalized_answer)."""
        answer = raw_answer.strip().strip('"').strip("'")
        if not answer:
            return False, "⚠️ Empty answer. Please provide a value.", ""

        ftype = self._apply_field_types.get(field_key, "")
        options = self._apply_field_options.get(field_key, [])
        if options and ftype in {"radio", "checkbox", "select"}:
            if answer.isdigit():
                idx = int(answer) - 1
                if 0 <= idx < len(options):
                    return True, "", options[idx]
                return False, f"⚠️ Invalid option number. Choose 1-{len(options)}.", ""

            lowered = answer.lower()
            for option in options:
                if lowered == option.lower():
                    return True, "", option

            return False, (
                "⚠️ Please answer with one of the listed options (or its number)."
            ), ""

        if field_key == "cv_path":
            candidate = Path(answer)
            if not candidate.exists() or not candidate.is_file():
                return False, "⚠️ CV file path not found. Please send a valid existing file path.", ""
            return True, "", str(candidate)

        if field_key == "cover_letter_path":
            lowered = answer.lower().strip()
            if lowered in {"none", "skip", "n/a", "na"}:
                return True, "", ""
            candidate = Path(answer)
            if not candidate.exists() or not candidate.is_file():
                return False, "⚠️ Cover letter file path not found. Send a valid path, or reply 'none'.", ""
            return True, "", str(candidate)

        if field_key == "full_name":
            if len(answer) < 3 or len(answer.split()) < 2:
                return False, "⚠️ Please provide first and last name.", ""
            return True, "", answer

        if field_key == "email":
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", answer):
                return False, "⚠️ Invalid email format. Example: name@example.com", ""
            return True, "", answer

        if field_key == "phone":
            digits = re.sub(r"\D", "", answer)
            if len(digits) < 7 or len(digits) > 15:
                return False, "⚠️ Invalid phone number. Please send a valid phone number.", ""
            return True, "", answer

        if field_key == "location":
            if len(answer) < 2:
                return False, "⚠️ Location looks too short. Please send City, Country.", ""
            return True, "", answer

        if field_key == "linkedin":
            lowered = answer.lower()
            if "linkedin.com/" not in lowered:
                return False, "⚠️ Please send a valid LinkedIn URL.", ""
            return True, "", answer

        if field_key == "github":
            lowered = answer.lower().strip()
            if lowered in {"none", "skip", "n/a", "na"}:
                return True, "", ""
            if "github.com/" not in lowered:
                return False, "⚠️ Please send a valid GitHub URL, or reply 'none'.", ""
            return True, "", answer

        if field_key == "website":
            lowered = answer.lower().strip()
            if lowered in {"none", "skip", "n/a", "na"}:
                return True, "", ""
            if not re.match(r"^https?://", lowered):
                return False, "⚠️ Website URL should start with http:// or https://, or reply 'none'.", ""
            return True, "", answer

        if field_key in {"relocate_bangkok", "agoda_relationship"}:
            lowered = answer.lower().strip()
            yes_values = {"yes", "y", "true", "1"}
            no_values = {"no", "n", "false", "0"}
            if lowered in yes_values:
                return True, "", "yes"
            if lowered in no_values:
                return True, "", "no"
            return False, "⚠️ Please answer with yes or no.", ""

        if field_key == "experience_years":
            match = re.search(r"\d{1,3}", answer)
            if not match:
                return False, "⚠️ Invalid experience. Please provide years as a number (e.g. 10).", ""
            years = int(match.group(0))
            if years < 0 or years > 60:
                return False, "⚠️ Experience years must be between 0 and 60.", ""
            return True, "", str(years)

        if field_key == "notice_period":
            if len(answer) < 2:
                return False, "⚠️ Please provide notice period / availability.", ""
            return True, "", answer

        if field_key == "salary_expectation":
            if len(answer) < 2:
                return False, "⚠️ Please provide salary expectation.", ""
            return True, "", answer

        if field_key == "motivation":
            if len(answer) < 8:
                return False, "⚠️ Motivation text is too short. Please provide 1-2 meaningful lines.", ""
            return True, "", answer

        return True, "", answer

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
        command_text = raw.strip()
        cmd = command_text.lower()
        cmd_name, cmd_arg = (cmd.split(maxsplit=1) + [""])[:2] if cmd else ("", "")
        abort_aliases = {"cancel", "quit", "abort", "stop", "give up", "giveup"}

        # --- In-progress apply guard -----------------------------------------
        if self._apply_in_progress_job_id is not None:
            if cmd in abort_aliases:
                return self._cmd_cancel_apply()

            # Waiting for Submit/Cancel confirmation after summary
            if self._state == self.STATE_APPLY_CONFIRM:
                if cmd == "submit":
                    return self._cmd_submit_apply()
                if cmd in {"preview", "review"}:
                    return self._cmd_preview_apply()
                jid = self._apply_in_progress_job_id
                self._send(
                    "⚠️ Review the summary above and reply <b>Preview</b> to open/fill and stop before submit, "
                    "<b>Submit</b> to apply now, or <b>Cancel</b> to abort."
                )
                return True

            # Still in Q&A phase — block navigation commands
            if cmd_name in {"next", "apply", "skip", "db", "done", "submit", "preview", "review"}:
                jid = self._apply_in_progress_job_id
                self._send(
                    f"⚠️ Job application for job ID <code>{jid}</code> is still in progress.\n"
                    "Reply with the current question answer, or <b>Cancel</b>/<b>Quit</b> to abort."
                )
                return True

            return self._handle_apply_answer(raw.strip())

        # --- Global commands -------------------------------------------------
        if cmd_name == "done":
            return self._cmd_done()
        if cmd_name == "db":
            return self._cmd_db()
        if cmd in {"reset profile", "resetprofile"}:
            self._saved_profile = {}
            self._persist_saved_profile()
            self._send("🧹 Saved profile was cleared. Future Apply flows will ask all fields again.")
            return True
        if cmd in abort_aliases:
            self._send("ℹ️ No application is currently in progress.")
            return True

        # --- Browsing context ------------------------------------------------
        current_list   = self.new_jobs if self._state == self.STATE_BROWSING_NEW else self._db_jobs
        current_idx    = self._new_job_idx if self._state == self.STATE_BROWSING_NEW else self._db_job_idx
        in_browse_mode = self._state in (self.STATE_BROWSING_NEW, self.STATE_BROWSING_DB)

        if cmd_name == "next":
            return self._cmd_next(cmd_arg)
        if cmd_name == "apply":
            return self._cmd_apply()
        if cmd_name == "skip":
            return self._cmd_skip()

        # Unrecognised
        self._send(
            "❓ Unknown command.\n"
            "Available: <b>Next</b> | <b>Next &lt;name&gt;</b> | <b>Apply</b> | <b>Skip</b> | <b>Done</b> | <b>db</b> | <b>Cancel</b>/<b>Quit</b>"
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

    def _job_matches_name(self, job: Dict, name_query: str) -> bool:
        if not name_query:
            return True
        query = name_query.strip().lower()
        if not query:
            return True
        title = str(job.get("title") or "").lower()
        company = str(job.get("company") or "").lower()
        url = str(job.get("url") or "").lower()
        return query in title or query in company or query in url

    def _cmd_next(self, name_query: str = "") -> bool:
        # Leave current job at its current status (Discovered stays Discovered)
        filter_name = (name_query or "").strip()

        if self._state == self.STATE_BROWSING_NEW:
            next_idx = self._new_job_idx + 1
            while next_idx < len(self.new_jobs) and not self._job_matches_name(self.new_jobs[next_idx], filter_name):
                next_idx += 1
            self._new_job_idx = next_idx
            if self._new_job_idx >= len(self.new_jobs):
                if filter_name:
                    self._send(
                        f"🔎 No more new jobs matched <b>{html.escape(filter_name)}</b>.\n"
                        "Reply <b>db</b> to browse all DB jobs, or <b>Done</b> to finish."
                    )
                    return True
                self._send("✅ No more new jobs from this run.\nReply <b>db</b> to browse all DB jobs, or <b>Done</b> to finish.")
                self._state = self.STATE_INTRO
                self._current_job = None
                return True
            self._current_job = self.new_jobs[self._new_job_idx]
            total = len(self.new_jobs)
            self._send(self._job_card_text(self._current_job, self._new_job_idx + 1, total))
            return True

        if self._state == self.STATE_BROWSING_DB:
            next_idx = self._db_job_idx + 1
            while next_idx < len(self._db_jobs) and not self._job_matches_name(self._db_jobs[next_idx], filter_name):
                next_idx += 1
            self._db_job_idx = next_idx
            if self._db_job_idx >= len(self._db_jobs):
                if filter_name:
                    self._send(f"🔎 No more DB jobs matched <b>{html.escape(filter_name)}</b>.\nReply <b>Done</b> to finish.")
                    return True
                self._send("✅ No more jobs in the database.\nReply <b>Done</b> to finish.")
                self._state = self.STATE_INTRO
                self._current_job = None
                return True
            self._current_job = self._db_jobs[self._db_job_idx]
            total = len(self._db_jobs)
            self._send(self._db_card_text(self._current_job, self._db_job_idx + 1, total))
            return True

        # INTRO state – support direct filtered search in new jobs then DB jobs
        if filter_name:
            if self.new_jobs:
                start_new_idx = self._new_job_idx if self._state == self.STATE_BROWSING_NEW else 0
                for idx in range(start_new_idx, len(self.new_jobs)):
                    if self._job_matches_name(self.new_jobs[idx], filter_name):
                        self._state = self.STATE_BROWSING_NEW
                        self._new_job_idx = idx
                        self._current_job = self.new_jobs[idx]
                        self._send(self._job_card_text(self._current_job, idx + 1, len(self.new_jobs)))
                        return True

            db_jobs = [
                j for j in self.db.get_all_jobs()
                if j.get("title") != "Unknown title" and j.get("company") != "Unknown company"
            ]
            for idx, job in enumerate(db_jobs):
                if self._job_matches_name(job, filter_name):
                    self._db_jobs = db_jobs
                    self._db_job_idx = idx
                    self._state = self.STATE_BROWSING_DB
                    self._current_job = job
                    self._send(self._db_card_text(job, idx + 1, len(db_jobs)))
                    return True

            self._send(
                f"🔎 Couldn't find any job matching <b>{html.escape(filter_name)}</b> in new jobs or DB.\n"
                "Reply <b>Next</b> to browse new jobs, or <b>db</b> for full DB browsing."
            )
            return True

        self._send("💡 Tip: Reply <b>Next</b> to browse new jobs, <b>Next &lt;name&gt;</b> to filter, or <b>db</b> to browse all DB jobs.")
        return True

    def _cmd_apply(self) -> bool:
        if self._current_job is None:
            self._send("⚠️ No active job selected. Reply <b>Next</b> to get the first job.")
            return True

        title   = self._current_job.get("title", "?")
        company = self._current_job.get("company", "?")
        job_url = self._current_job.get("url", "")

        # ── Scan the actual form before asking anything ───────────────────────
        scan_mode_note = (
            "This runs headless in <b>normal</b> mode. "
            if self._easy_apply_run_mode == "normal"
            else f"This opens a browser briefly in <b>{html.escape(self._easy_apply_run_mode)}</b> mode. "
        )
        self._send(
            f"🔍 Scanning the Easy Apply form for <b>{html.escape(title)}</b> @ <b>{html.escape(company)}</b>…\n"
            f"{scan_mode_note}"
            "I'll ask only the questions the form actually needs."
        )
        try:
            scanned = self._scan_easy_apply_fields(job_url)
        except Exception as exc:
            self.logger.warning(f"Scan raised unexpectedly: {exc}")
            scanned = []

        # Fallback: if scan fails for known Agoda flow, inject known required
        # additional questions so summary and Q&A still match the real form.
        if not scanned:
            company_l = (company or "").lower()
            title_l = (title or "").lower()
            url_l = (job_url or "").lower()
            if "agoda" in company_l or "agoda" in title_l or "agoda" in url_l:
                scanned = [
                    ("github", "Github Profile? (Please paste link or answer 'No')", "text"),
                    ("website", "Website / blog / other", "text"),
                    ("relocate_bangkok", "Are you currently based in Bangkok or open to relocate to Bangkok?", "radio"),
                    ("agoda_relationship", "Do you as a candidate have a personal relationship with a current Agoda employee?", "radio"),
                ]
                self.logger.info("Scan fallback: injected Agoda additional questions")

        self._apply_form_fields = self._build_apply_form_fields(scanned)
        n_extra = len(self._apply_form_fields) - len(self.FIXED_FIELDS)
        if scanned:
            extra_labels = [label for key, label, _ in scanned if key not in {k for k, _ in self.FIXED_FIELDS}]
            if extra_labels:
                self._send(
                    f"✅ Form scanned. Found <b>{n_extra}</b> job-specific question(s):\n"
                    + "\n".join(f"  • {html.escape(l)}" for l in extra_labels)
                )
            else:
                self._send("✅ Form scanned. No extra questions beyond the standard fields.")
        else:
            self._send("⚠️ Could not scan the form (job may not use Easy Apply, or login needed). "
                       "I'll ask standard fields only.")

        # ── Initialise apply state ────────────────────────────────────────────
        self._return_state_after_apply = self._state
        self._state = self.STATE_APPLYING
        self._apply_answers = {
            field_key: self._saved_profile.get(field_key, "")
            for field_key, _prompt in self._apply_form_fields
            if self._saved_profile.get(field_key)
        }
        self._apply_asked_field_keys = []
        self._apply_question_idx = self._first_missing_apply_field_idx()
        self._apply_in_progress_job_id = self._current_job.get("id")

        loaded_count = len(self._apply_answers)
        self._send(
            f"🧾 Starting application form for <b>{html.escape(title)}</b> @ <b>{html.escape(company)}</b>.\n"
            "Reply with each answer. Use <b>Cancel</b> or <b>Quit</b> anytime to abort."
        )
        if loaded_count > 0:
            self._send(
                f"💾 Loaded <b>{loaded_count}</b> saved profile field(s), so I'll ask only missing details.\n"
                "Reply <b>reset profile</b> anytime (outside apply flow) to clear saved values."
            )

        if self._apply_question_idx >= len(self._apply_form_fields):
            if self._maybe_expand_apply_fields_via_rescan(job_url):
                self._send_current_apply_prompt()
                return True
            return self._show_apply_summary()

        self._send_current_apply_prompt()
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
        self._apply_answers = {}
        self._apply_asked_field_keys = []
        self._apply_question_idx = 0
        self._apply_form_fields = []
        self._state = self._return_state_after_apply
        self._send(
            f"🚫 Application for job ID <code>{jid}</code> cancelled.\n\n"
            "Reply <b>Next</b> | <b>Done</b> | <b>db</b>"
        )
        return True

    def _handle_apply_answer(self, answer: str) -> bool:
        if not answer:
            self._send("⚠️ Empty answer. Please send a value or <b>Cancel</b>.")
            return True

        if self._apply_question_idx >= len(self._apply_form_fields):
            return self._show_apply_summary()

        key, _prompt = self._apply_form_fields[self._apply_question_idx]
        is_valid, error_message, normalized_answer = self._validate_apply_answer(key, answer)
        if not is_valid:
            self._send(error_message)
            self._send_current_apply_prompt()
            return True

        self._apply_answers[key] = normalized_answer
        # Only persist non-custom fields to saved profile
        if not key.startswith("custom__"):
            self._saved_profile[key] = normalized_answer
            self._persist_saved_profile()
        self._apply_question_idx += 1

        while self._apply_question_idx < len(self._apply_form_fields):
            next_key, _next_prompt = self._apply_form_fields[self._apply_question_idx]
            if self._apply_answers.get(next_key):
                self._apply_question_idx += 1
                continue
            break

        if self._apply_question_idx < len(self._apply_form_fields):
            self._send_current_apply_prompt()
            return True

        current_job_url = (self._current_job or {}).get("url", "")
        if self._maybe_expand_apply_fields_via_rescan(current_job_url):
            self._send_current_apply_prompt()
            return True

        return self._show_apply_summary()

    def _maybe_expand_apply_fields_via_rescan(self, job_url: str) -> bool:
        """
        In normal mode, re-scan the wizard using answers collected so far.
        If new fields are discovered, append them and continue Q&A.
        """
        if self._easy_apply_run_mode != "normal":
            return False
        if not job_url:
            return False

        existing_keys = [field_key for field_key, _prompt in self._apply_form_fields]
        existing_set = set(existing_keys)

        try:
            rescanned = self._scan_easy_apply_fields(job_url, seed_answers=dict(self._apply_answers))
        except Exception as exc:
            self.logger.warning(f"Iterative scan raised unexpectedly: {exc}")
            return False

        if not rescanned:
            return False

        merged_fields = self._build_apply_form_fields(rescanned)
        merged_keys = [field_key for field_key, _prompt in merged_fields]
        new_keys = [key for key in merged_keys if key not in existing_set]
        if not new_keys:
            return False

        self._apply_form_fields = merged_fields
        self._apply_question_idx = self._first_missing_apply_field_idx()

        new_labels: List[str] = []
        for field_key, label, _ftype in rescanned:
            if field_key in new_keys:
                new_labels.append(label)
        if new_labels:
            self._send(
                "🔁 Thanks — your answers unlocked additional form page(s).\n"
                "I found more required questions:\n"
                + "\n".join(f"  • {html.escape(label)}" for label in new_labels)
            )
        else:
            self._send("🔁 Thanks — your answers unlocked additional form page(s).")

        return self._apply_question_idx < len(self._apply_form_fields)

    def _show_apply_summary(self) -> bool:
        """All Q&A answers collected. Show summary and ask user to Submit or Cancel."""
        job = self._current_job or {}
        title = job.get("title", "?")
        company = job.get("company", "?")
        url = job.get("url", "")

        submission_lines: List[str] = []
        for field_key, prompt in self._apply_form_fields:
            value = (self._apply_answers.get(field_key) or "").strip()
            include_empty_for_asked = (field_key in self._apply_asked_field_keys)
            if not value and not include_empty_for_asked:
                continue

            # Build a clean display label from the prompt
            label = prompt.split(" ", 1)[1].rstrip(":") if " " in prompt else prompt.rstrip(":")
            label = label.split(" (", 1)[0].strip()
            display_value = value or "(not provided)"
            submission_lines.append(f"• <b>{html.escape(label)}</b>: {html.escape(display_value)}")

        submission_section = "\n🧾 <b>Data that will be submitted in this application:</b>\n"
        if submission_lines:
            submission_section += "\n".join(submission_lines)
        else:
            submission_section += "• <i>No values are currently available for submission.</i>"

        self._send(
            f"📋 <b>Application Summary</b>\n"
            f"Role: <b>{html.escape(title)}</b> @ <b>{html.escape(company)}</b>\n"
            f"🔗 {html.escape(url)}\n\n"
            + submission_section
            + "\n\n"
            "Reply <b>Preview</b> to fill and stop on the final review page (no submit), "
            "or <b>Submit</b> to fill &amp; submit the form on LinkedIn, "
            "or <b>Cancel</b> to abort."
        )
        self._state = self.STATE_APPLY_CONFIRM
        return True

    def _cmd_preview_apply(self) -> bool:
        """User requested preview mode: fill form and stop on final review step without submitting."""
        job = self._current_job or {}
        title = job.get("title", "?")
        company = job.get("company", "?")
        job_url = job.get("url", "")
        answers = self._apply_answers

        self._send(
            f"👀 Opening LinkedIn and filling the application for <b>{html.escape(title)}</b> @ <b>{html.escape(company)}</b>.\n"
            "I will stop at the final submit page without submitting."
        )
        self.logger.info(f"Telegram: Starting LinkedIn Easy Apply preview for {title} @ {company}")

        success, message = self._do_linkedin_easy_apply(
            job_url,
            answers,
            submit_application=False,
        )
        if success:
            self._send(
                "✅ <b>Preview ready.</b> The form is filled and paused before submit for your visual review.\n"
                f"{html.escape(message)}\n\n"
                "Status remains unchanged. Reply <b>Submit</b> to perform a real submission, or <b>Cancel</b> to abort."
            )
            return True

        self._send(
            f"❌ <b>Preview failed.</b>\n"
            f"{html.escape(message)}\n\n"
            "Reply <b>Preview</b> to retry, <b>Submit</b> to try direct submit, or <b>Cancel</b>."
        )
        return True

    def _cmd_submit_apply(self) -> bool:
        """User confirmed Submit. Run Playwright to fill and submit the LinkedIn Easy Apply form."""
        job = self._current_job or {}
        job_id = job.get("id")
        title = job.get("title", "?")
        company = job.get("company", "?")
        job_url = job.get("url", "")
        answers = self._apply_answers

        self._send(f"⏳ Opening LinkedIn and submitting your application for <b>{html.escape(title)}</b>…")
        self.logger.info(f"Telegram: Starting LinkedIn Easy Apply for job {job_id} ({title} @ {company})")

        success, message = self._do_linkedin_easy_apply(job_url, answers, submit_application=True)

        if success:
            try:
                self.db.update_job_status(job_id, "Applied")
                self.logger.info(f"Telegram: Applied -> {title} @ {company} (id={job_id})")
            except Exception as exc:
                self._send(f"⚠️ Submission succeeded but DB update failed: {html.escape(str(exc))}")
            self._send(
                f"✅ <b>Application submitted successfully!</b>\n"
                f"Role: <b>{html.escape(title)}</b> @ <b>{html.escape(company)}</b>\n"
                f"Status set to <b>Applied</b>.\n\n"
                "Reply <b>Next</b> to continue | <b>Done</b> to finish | <b>db</b> to browse DB"
            )
        else:
            self._send(
                f"❌ <b>Submission failed.</b>\n"
                f"{html.escape(message)}\n\n"
                "Status has <b>not</b> been changed. You can try again or apply manually.\n"
                "Reply <b>Cancel</b> to abort this application | <b>Submit</b> to retry."
            )
            # Stay in APPLY_CONFIRM so user can retry or cancel
            return True

        # Reset apply state
        self._apply_in_progress_job_id = None
        self._apply_question_idx = 0
        self._apply_answers = {}
        self._apply_asked_field_keys = []
        self._apply_form_fields = []
        self._state = self._return_state_after_apply
        return True

    def _do_linkedin_easy_apply(
        self,
        job_url: str,
        answers: Dict[str, str],
        submit_application: bool = True,
    ) -> Tuple[bool, str]:
        """
        Open the LinkedIn job page, click Easy Apply, and fill out the modal form
        using the collected answers.

        If submit_application=True, click submit and mark success on completion.
        If submit_application=False, stop on final review page without clicking submit.

        Returns (success: bool, message: str).
        """
        import os as _os
        try:
            sync_api = importlib.import_module("playwright.sync_api")
            sync_playwright = getattr(sync_api, "sync_playwright")
            target_closed_error = getattr(sync_api, "TargetClosedError", Exception)
        except ImportError as exc:
            return False, f"Playwright not available: {exc}"

        # Resolve Chrome profile (same logic as LinkedInJobAgent.run)
        local_app_data = _os.environ.get("LOCALAPPDATA", "")
        primary_profile = _os.path.join(local_app_data, "Google", "Chrome", "User Data") if local_app_data else ""
        fallback_profile = str(Path(__file__).parent / ".playwright_profile")
        easy_apply_headless = self._easy_apply_run_mode == "normal"

        cv_path = answers.get("cv_path", "").strip()

        try:
            with sync_playwright() as pw:
                # Try primary profile first, fall back to local
                try:
                    ctx = pw.chromium.launch_persistent_context(
                        user_data_dir=primary_profile,
                        channel="chrome",
                        headless=easy_apply_headless,
                        no_viewport=True,
                        args=["--start-maximized"],
                        slow_mo=150,
                        locale="en-US",
                        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
                    )
                except (target_closed_error, Exception) as exc:
                    self.logger.warning(f"LinkedIn Easy Apply: primary profile failed ({exc}), using fallback")
                    _os.makedirs(fallback_profile, exist_ok=True)
                    ctx = pw.chromium.launch_persistent_context(
                        user_data_dir=fallback_profile,
                        channel="chrome",
                        headless=easy_apply_headless,
                        no_viewport=True,
                        args=["--start-maximized"],
                        slow_mo=150,
                        locale="en-US",
                        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
                    )

                try:
                    page = ctx.pages[0] if ctx.pages else ctx.new_page()
                    page.set_default_timeout(20000)
                    try:
                        page.bring_to_front()
                    except Exception:
                        pass

                    # ── Step 1: Navigate to job page ──────────────────────────────
                    self.logger.info(f"Easy Apply: navigating to {job_url}")
                    page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(2000)

                    # ── Step 2: Click Easy Apply button ───────────────────────────
                    easy_apply_selectors = [
                        ".jobs-apply-button",
                        "a.jobs-apply-button",
                        "button.jobs-apply-button",
                        "[data-control-name*='jobdetails_topcard_inapply']",
                        "[data-control-name*='jobdetails_topcard_inapply'] button",
                        ".jobs-apply-button--top-card",
                        ".jobs-s-apply [role='button']",
                        "button:has-text('Easy Apply')",
                        "button[aria-label*='Easy Apply']",
                        ".jobs-s-apply button",
                        "[role='button']:has-text('Easy Apply')",
                        "a:has-text('Easy Apply')",
                        "span:has-text('Easy Apply')",
                    ]
                    try:
                        page.wait_for_selector(", ".join(easy_apply_selectors), timeout=8000)
                        self.logger.info("Easy Apply: apply element detected in DOM")
                    except Exception:
                        self.logger.warning("Easy Apply: wait_for_selector timed out for apply button")

                    clicked = False
                    for attempt in range(3):
                        if attempt > 0:
                            page.wait_for_timeout(1500)
                        for sel in easy_apply_selectors:
                            try:
                                btn = page.locator(sel).first
                                if btn.count() > 0 and btn.is_visible(timeout=3000):
                                    btn.click(timeout=5000)
                                    clicked = True
                                    self.logger.info(
                                        f"Easy Apply: clicked Easy Apply button via {sel!r} "
                                        f"(attempt {attempt + 1})"
                                    )
                                    break
                            except Exception:
                                continue
                        if clicked:
                            break

                    if not clicked:
                        # Check if it's an external application
                        ext_btn = page.locator("button:has-text('Apply'), a:has-text('Apply on company site')").first
                        if ext_btn.count() > 0:
                            return False, (
                                "This job uses an external application page (not LinkedIn Easy Apply). "
                                "Please apply manually via the job URL."
                            )
                        return False, "Could not find the Easy Apply button. The page may have changed or you may need to log in."

                    page.wait_for_timeout(2000)  # modal animation

                    # ── Step 3: Fill the modal form ───────────────────────────────
                    # The Easy Apply modal is a multi-step wizard. We iterate pages.
                    max_modal_steps = 20
                    for step_num in range(max_modal_steps):
                        self.logger.info(f"Easy Apply: filling modal step {step_num + 1}")
                        page.wait_for_timeout(1000)

                        # Fill text inputs that are visible and empty
                        self._fill_easy_apply_modal(page, answers, cv_path)

                        # Look for Next / Review / Submit button
                        next_btn = self._find_modal_advance_button(page)
                        if next_btn is None:
                            return False, f"Lost the Easy Apply modal at step {step_num + 1}."

                        btn_text = (next_btn.inner_text(timeout=3000) or "").strip().lower()
                        self.logger.info(f"Easy Apply: modal button text = {btn_text!r}")

                        is_submit_action = any(tok in btn_text for tok in ["submit", "تقديم", "إرسال", "ارسال"])

                        if is_submit_action and not submit_application:
                            self.logger.info("Easy Apply: reached submit step in preview mode; not clicking submit")
                            return True, "Preview stopped at final submit step (no submit clicked)."

                        if is_submit_action and submit_application:
                            next_btn.click(timeout=10000)
                            self.logger.info("Easy Apply: clicked Submit button")
                            page.wait_for_timeout(3000)
                            # Check for success indicators
                            success_indicators = [
                                "text=/application submitted/i",
                                "text=/your application was sent/i",
                                "text=/successfully applied/i",
                                ".artdeco-modal:has-text('application submitted')",
                                "h3:has-text('Application submitted')",
                            ]
                            submitted = False
                            for ind in success_indicators:
                                try:
                                    if page.locator(ind).count() > 0:
                                        submitted = True
                                        break
                                except Exception:
                                    pass
                            if submitted:
                                self.logger.info("Easy Apply: submission confirmed")
                                return True, "Application submitted successfully."
                            # If no explicit confirmation, treat as success (LinkedIn sometimes
                            # closes the modal without a visible banner)
                            self.logger.info("Easy Apply: modal closed after Submit – treating as success")
                            return True, "Application submitted (modal closed after Submit)."

                        elif "next" in btn_text or "review" in btn_text or "continue" in btn_text or "التالي" in btn_text or "مراجعة" in btn_text or "الاستمرار" in btn_text:
                            next_btn.click(timeout=5000)
                        else:
                            # Unknown button — click it and hope for the best
                            next_btn.click(timeout=5000)

                    if not submit_application:
                        return True, (
                            f"Preview stopped after {max_modal_steps} wizard steps "
                            "(submit step not reached automatically)."
                        )

                    return False, f"Easy Apply wizard exceeded {max_modal_steps} steps without submitting."

                finally:
                    try:
                        ctx.close()
                    except Exception:
                        pass

        except Exception as exc:
            self.logger.error(f"Easy Apply unexpected error: {exc}")
            return False, f"Unexpected error during submission: {exc}"

    def _fill_easy_apply_modal(self, page: Any, answers: Dict[str, str], cv_path: str) -> None:
        """Fill visible fields in the current Easy Apply modal step using dynamic label matching."""
        try:
            cover_letter_path = (answers.get("cover_letter_path") or "").strip()

            def _get_label(inp: Any) -> str:
                try:
                    aria = inp.get_attribute("aria-label", timeout=400) or ""
                    if aria.strip():
                        return aria.strip()
                except Exception:
                    pass
                try:
                    inp_id = inp.get_attribute("id", timeout=400) or ""
                    if inp_id:
                        lbl = page.locator(f"label[for='{inp_id}']").first
                        if lbl.count() > 0:
                            text = lbl.inner_text(timeout=400) or ""
                            if text.strip():
                                return text.strip()
                except Exception:
                    pass
                try:
                    placeholder = inp.get_attribute("placeholder", timeout=400) or ""
                    if placeholder.strip():
                        return placeholder.strip()
                except Exception:
                    pass
                return ""

            def _custom_key_from_label(label: str) -> str:
                return f"custom__{re.sub(r'[^a-z0-9_]', '_', label.lower().strip())[:60]}"

            def _answer_for_label(label: str) -> str:
                lowered = label.lower()
                for pattern, key in self.LABEL_TO_PROFILE_KEY:
                    if pattern.search(lowered):
                        return answers.get(key, "")
                return answers.get(_custom_key_from_label(label), "")

            for fi in page.locator("input[type='file']").all():
                try:
                    if not fi.is_visible(timeout=1000):
                        continue
                    label_context = ""
                    try:
                        label_context = (
                            fi.locator("xpath=ancestor::*[self::div or self::section][1]").inner_text(timeout=500) or ""
                        ).lower()
                    except Exception:
                        pass

                    if "cover" in label_context and cover_letter_path and Path(cover_letter_path).exists():
                        fi.set_input_files(cover_letter_path)
                        self.logger.info("Easy Apply: uploaded cover letter")
                        page.wait_for_timeout(500)
                        continue

                    if ("resume" in label_context or "cv" in label_context) and cv_path and Path(cv_path).exists():
                        fi.set_input_files(cv_path)
                        self.logger.info("Easy Apply: uploaded CV")
                        page.wait_for_timeout(500)
                        continue

                    current_files = ""
                    try:
                        current_files = fi.input_value(timeout=500) or ""
                    except Exception:
                        pass

                    if not current_files and cv_path and Path(cv_path).exists():
                        fi.set_input_files(cv_path)
                        self.logger.info("Easy Apply: uploaded CV (fallback)")
                        page.wait_for_timeout(500)
                        cv_path = ""
                    elif not current_files and cover_letter_path and Path(cover_letter_path).exists():
                        fi.set_input_files(cover_letter_path)
                        self.logger.info("Easy Apply: uploaded cover letter (fallback)")
                        page.wait_for_timeout(500)
                        cover_letter_path = ""
                except Exception:
                    continue

            text_like_selector = "input[type='text'], input[type='email'], input[type='tel'], input[type='url'], input[type='number'], textarea"
            for inp in page.locator(text_like_selector).all():
                try:
                    if not inp.is_visible(timeout=500):
                        continue
                    current_val = inp.input_value(timeout=500)
                    if current_val:
                        continue

                    label_text = _get_label(inp)
                    if not label_text:
                        continue

                    fill_value = _answer_for_label(label_text)
                    label_lower = label_text.lower()
                    full_name = answers.get("full_name", "")
                    if full_name:
                        if "first" in label_lower:
                            parts = full_name.split()
                            fill_value = parts[0] if parts else full_name
                        elif "last" in label_lower:
                            parts = full_name.split()
                            fill_value = parts[-1] if len(parts) > 1 else full_name

                    if fill_value:
                        inp.fill(fill_value, timeout=3000)
                        self.logger.info(f"Easy Apply: filled '{label_text}'")
                except Exception:
                    continue

            for sel_el in page.locator("select").all():
                try:
                    if not sel_el.is_visible(timeout=500):
                        continue
                    label_text = _get_label(sel_el)
                    if not label_text:
                        continue
                    desired = (_answer_for_label(label_text) or "").strip()
                    if not desired:
                        continue

                    selected = False
                    for option in sel_el.locator("option").all():
                        try:
                            opt_value = (option.get_attribute("value", timeout=400) or "").strip()
                            opt_text = (option.inner_text(timeout=400) or "").strip()
                            if desired.lower() in opt_text.lower() or desired.lower() == opt_value.lower():
                                if opt_value:
                                    sel_el.select_option(value=opt_value)
                                else:
                                    sel_el.select_option(label=opt_text)
                                selected = True
                                break
                        except Exception:
                            continue
                    if not selected:
                        try:
                            sel_el.select_option(label=desired)
                            selected = True
                        except Exception:
                            pass
                    if selected:
                        self.logger.info(f"Easy Apply: selected option for '{label_text}'")
                except Exception:
                    continue

            for fieldset in page.locator("fieldset").all():
                try:
                    if not fieldset.is_visible(timeout=500):
                        continue
                    legend = ""
                    try:
                        legend = (fieldset.locator("legend").first.inner_text(timeout=400) or "").strip()
                    except Exception:
                        pass
                    if not legend:
                        continue

                    desired = (_answer_for_label(legend) or "").strip().lower()
                    if not desired:
                        continue

                    for control in fieldset.locator("input[type='radio'], input[type='checkbox']").all():
                        try:
                            control_id = control.get_attribute("id", timeout=400) or ""
                            option_label = ""
                            if control_id:
                                option = page.locator(f"label[for='{control_id}']").first
                                if option.count() > 0:
                                    option_label = (option.inner_text(timeout=400) or "").strip().lower()
                            option_value = (control.get_attribute("value", timeout=400) or "").strip().lower()
                            if desired in option_label or desired == option_value:
                                try:
                                    control.check(timeout=2000)
                                except Exception:
                                    control.click(timeout=2000)
                                self.logger.info(f"Easy Apply: selected '{desired}' for '{legend}'")
                                break
                        except Exception:
                            continue
                except Exception:
                    continue
        except Exception as exc:
            self.logger.warning(f"Easy Apply fill step error: {exc}")

    def _find_modal_advance_button(self, page: Any) -> Any:
        """Find the primary action button in the Easy Apply modal (Next/Review/Submit)."""
        selectors = [
            "button[aria-label*='Submit application']",
            "button[aria-label*='submit']",
            "button:has-text('Submit application')",
            "button:has-text('Submit')",
            "button[aria-label*='Review']",
            "button:has-text('Review')",
            "button[aria-label*='Continue to next step']",
            "button:has-text('Next')",
            "button:has-text('Continue')",
            ".artdeco-modal button.artdeco-button--primary",
            ".jobs-easy-apply-modal button.artdeco-button--primary",
        ]
        for sel in selectors:
            try:
                btn = page.locator(sel).last  # last primary button in modal
                if btn.count() > 0 and btn.is_visible(timeout=1500) and btn.is_enabled(timeout=1500):
                    return btn
            except Exception:
                continue
        return None

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
            # Do not pre-send the first job card; wait for explicit Next so
            # user can choose db/done first.
            self._new_job_idx = -1
            self._current_job = None

    # ------------------------------------------------------------------
    # Main event loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Block until the session ends (user says Done or process is interrupted)."""
        self.send_intro()

        if self._state == self.STATE_DONE:
            return

        offset = 0
        bootstrap_updates = self._get_updates(offset=offset, timeout=0)
        if bootstrap_updates:
            offset = bootstrap_updates[-1]["update_id"] + 1
            self.logger.info(f"Telegram poll bootstrap: skipped {len(bootstrap_updates)} stale update(s)")
        self.logger.info("Telegram session started, entering poll loop")

        interrupt_count = 0
        interrupt_window_started = 0.0
        while True:
            try:
                updates = self._get_updates(offset=offset, timeout=20)
                interrupt_count = 0
                interrupt_window_started = 0.0
            except KeyboardInterrupt:
                now_ts = time.time()
                if interrupt_window_started and (now_ts - interrupt_window_started) <= 3.0:
                    interrupt_count += 1
                else:
                    interrupt_window_started = now_ts
                    interrupt_count = 1

                if interrupt_count >= 2:
                    self.logger.info("Telegram session interrupted twice; shutting down")
                    return

                self.logger.warning(
                    "Telegram poll interrupted once; continuing (press Ctrl+C again within 3s to stop)"
                )
                time.sleep(1)
                continue

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


# ── Populate TelegramJobSession.LABEL_TO_PROFILE_KEY after class is defined ──
# Maps compiled regex patterns of LinkedIn field labels → saved profile keys.
# Order matters: first match wins.
TelegramJobSession.LABEL_TO_PROFILE_KEY = [
    (re.compile(r"first.?name",                 re.I), "full_name"),
    (re.compile(r"last.?name",                  re.I), "full_name"),
    (re.compile(r"full.?name|your name",        re.I), "full_name"),
    (re.compile(r"email",                       re.I), "email"),
    (re.compile(r"phone|mobile",                re.I), "phone"),
    (re.compile(r"city|location|address",       re.I), "location"),
    (re.compile(r"linkedin",                    re.I), "linkedin"),
    (re.compile(r"github",                      re.I), "github"),
    (re.compile(r"website|portfolio|personal.?site", re.I), "website"),
    (re.compile(r"year.*experience|experience.*year|years of exp", re.I), "experience_years"),
    (re.compile(r"notice|availability|when can you start|start date", re.I), "notice_period"),
    (re.compile(r"salary|compensation|expected.*pay|pay.*expect", re.I), "salary_expectation"),
    (re.compile(r"cover.?letter|motivation|why.*apply|why.*interest", re.I), "motivation"),
]


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
    easy_apply_run_mode: str = "normal",
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
        easy_apply_run_mode=easy_apply_run_mode,
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
    parser.add_argument(
        "--easy-apply-run-mode",
        type=str,
        choices=["normal", "testing"],
        default="normal",
        help="Easy Apply scan traversal mode: normal or testing",
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
                easy_apply_run_mode=args.easy_apply_run_mode,
            )
        finally:
            agent.db.close()


if __name__ == "__main__":
    main()