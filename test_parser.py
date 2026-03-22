import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def contains_any(text: str, terms: List[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


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


def build_prompt(persona: str, context: str, job_description: str) -> str:
    return (
        "SYSTEM INSTRUCTIONS:\n"
        f"{persona.strip()}\n\n"
        "USER CONTEXT (Ariel Samin):\n"
        f"{context.strip()}\n\n"
        "JOB DESCRIPTION TO ANALYZE:\n"
        f"{job_description.strip()}"
    )


def analyze_job_description(job_text: str, requirements: Dict) -> Tuple[List[Tuple[str, str, str]], str, bool]:
    salary_floor = int(requirements.get("salary_min_ils", 25000))
    work_model_required = str(requirements.get("work_model", "Hybrid/Remote")).lower()

    normalized_jd = normalize_space(job_text)
    salary_values = find_salary_values_ils(normalized_jd)
    top_salary = max(salary_values) if salary_values else None

    tech_match = contains_any(normalized_jd, ["c#", "c sharp", ".net", "dotnet", "asp.net"])
    senior_match = contains_any(normalized_jd, ["senior", "staff", "lead", "principal"])
    israel_match = contains_any(
        normalized_jd,
        ["israel", "tel aviv", "haifa", "jerusalem", "rishon", "petah", "herzliya", "raanana"],
    )

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
        ("Role Seniority", "Role wording suggests senior-level scope.", "Yes" if senior_match else "No"),
        ("C#/.NET Core Fit", "JD includes C#/.NET indicators.", "Yes" if tech_match else "No"),
        ("Israel Location", "Location appears to be Israel-based.", "Yes" if israel_match else "Unknown"),
        ("Salary Floor (25K ILS)", salary_analysis, salary_result),
        ("BGU BSc Compatibility", bgu_analysis, bgu_result),
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
        match_bool = True
    elif not critical_fail and critical_unknown:
        recommendation = "REVIEW MANUALLY"
        match_bool = True
    else:
        recommendation = "DO NOT APPLY"
        match_bool = False

    return rows, recommendation, match_bool


def markdown_table(rows: List[Tuple[str, str, str]]) -> str:
    header = "| Metric | Analysis | Match? |"
    separator = "|---|---|---|"
    body = [f"| {metric} | {analysis} | {match} |" for metric, analysis, match in rows]
    return "\n".join([header, separator, *body])


def infer_expected(sample_file: Path) -> bool:
    name = sample_file.name.lower()
    if "positive" in name:
        return True
    if "negative" in name:
        return False
    raise ValueError("Cannot infer expected result from filename. Use --expect-match true|false.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline parser test for job-analysis logic")
    parser.add_argument(
        "sample_file",
        nargs="?",
        default="Tests/Samples/positive_match.txt",
        help="Path to local JD sample text file",
    )
    parser.add_argument(
        "--expect-match",
        choices=["true", "false", "auto"],
        default="auto",
        help="Expected match outcome for a TDD-style pass/fail check",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent

    context = load_text(base_dir / "MY_CONTEXT.md")
    persona = load_text(base_dir / "JOB_HUNTER_PERSONA.md")
    requirements = load_json(base_dir / "JOB_REQUIREMENTS.json")

    sample_file = Path(args.sample_file)
    if not sample_file.is_absolute():
        sample_file = base_dir / sample_file

    job_description = load_text(sample_file)

    prompt = build_prompt(persona, context, job_description)
    rows, recommendation, is_match = analyze_job_description(job_description, requirements)
    table = markdown_table(rows)

    print(f"--- RUNNING TEST ON: {sample_file} ---")
    print("\n=== EXECUTIVE SUMMARY ===")
    print(table)
    print(f"\nRecommendation: {recommendation}")
    print("Ariel, should I draft an application for this role? [Y/N]")
    print("=========================\n")

    print("[PROMPT PREVIEW]")
    prompt_preview = prompt[:1200] + ("..." if len(prompt) > 1200 else "")
    print(prompt_preview)

    if args.expect_match == "auto":
        expected = infer_expected(sample_file)
    else:
        expected = args.expect_match == "true"

    passed = expected == is_match
    print(f"\n[TDD CHECK] expected={expected} actual={is_match} -> {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
