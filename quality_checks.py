"""
quality_checks.py

Data-quality checks run against each batch of postings before they're
written to the database. Each function returns a list of issue strings
(empty list = no issues). Nothing here raises on its own — the caller
(fetch_jobs.py) decides whether an issue is fatal for that run.
"""

from typing import List, Dict, Any

# The keys we expect on every raw posting from the Adzuna API.
# If Adzuna adds/removes/renames fields, this is what catches it.
EXPECTED_KEYS = {
    "id", "title", "company", "location", "category",
    "created", "redirect_url", "salary_is_predicted",
}


def check_schema_drift(raw_posting: Dict[str, Any]) -> List[str]:
    """Compare a single raw posting's keys against what we expect."""
    issues = []
    actual_keys = set(raw_posting.keys())
    missing = EXPECTED_KEYS - actual_keys
    if missing:
        issues.append(f"Schema drift: missing expected fields {missing}")
    return issues


def check_nulls(posting: Dict[str, Any]) -> List[str]:
    """Flag postings missing critical fields needed to make the row useful."""
    issues = []
    if not posting.get("posting_id"):
        issues.append("Missing posting_id — cannot dedupe or store this row")
    if not posting.get("title") and not posting.get("company") and not posting.get("location"):
        issues.append("Missing title, company, AND location — posting not usable")
    return issues


def check_duplicates(postings: List[Dict[str, Any]]) -> List[str]:
    """Check for duplicate posting_ids within a single batch (pre-upsert)."""
    issues = []
    seen = set()
    dupes = set()
    for p in postings:
        pid = p.get("posting_id")
        if pid in seen:
            dupes.add(pid)
        seen.add(pid)
    if dupes:
        issues.append(f"Duplicate posting_id values within batch: {dupes}")
    return issues


def check_salary_sanity(posting: Dict[str, Any]) -> List[str]:
    """
    Flag suspicious salary values without discarding the row —
    salary data is inherently messy, so we log and keep, not drop.
    """
    issues = []
    smin, smax = posting.get("salary_min"), posting.get("salary_max")
    if smin is not None and smax is not None:
        if smin > smax:
            issues.append(f"salary_min ({smin}) > salary_max ({smax})")
    if smin is not None and smin < 0:
        issues.append(f"Negative salary_min: {smin}")
    return issues


def run_all_checks(raw_postings: List[Dict[str, Any]],
                    parsed_postings: List[Dict[str, Any]]) -> List[str]:
    """
    Run every check against a batch. Returns a flat list of all issues
    found, prefixed with which posting_id (if any) they relate to.
    """
    all_issues = []

    for raw in raw_postings:
        for issue in check_schema_drift(raw):
            all_issues.append(f"[{raw.get('id', 'unknown-id')}] {issue}")

    for posting in parsed_postings:
        pid = posting.get("posting_id", "unknown-id")
        for issue in check_nulls(posting):
            all_issues.append(f"[{pid}] {issue}")
        for issue in check_salary_sanity(posting):
            all_issues.append(f"[{pid}] {issue}")

    for issue in check_duplicates(parsed_postings):
        all_issues.append(issue)

    return all_issues
