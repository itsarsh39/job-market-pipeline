"""
fetch_jobs.py

Pulls job postings from the Adzuna API for a configured list of
countries and keywords, validates them, and upserts them into
jobs.db. Every run — success or failure — writes a row to run_log
per (country, keyword) so the pipeline's history is fully visible.

Usage:
    python fetch_jobs.py
"""

import os
import sqlite3
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from quality_checks import run_all_checks

load_dotenv()

DB_PATH = "jobs.db"
APP_ID = os.getenv("ADZUNA_APP_ID")
APP_KEY = os.getenv("ADZUNA_APP_KEY")

# --- Config: edit this list as you expand coverage ---
COUNTRIES = ["in", "us", "gb", "au", "ca", "sg"]
KEYWORDS = ["data analyst", "data engineer"]
RESULTS_PER_PAGE = 50
MAX_DAYS_OLD = 30

CURRENCY_BY_COUNTRY = {
    "in": "INR", "us": "USD", "gb": "GBP",
    "au": "AUD", "ca": "CAD", "sg": "SGD",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_page(country_code: str, keyword: str, page: int = 1) -> dict:
    """Single API call. Raises on HTTP errors so the caller can catch and log them."""
    url = f"https://api.adzuna.com/v1/api/jobs/{country_code}/search/{page}"
    params = {
        "app_id": APP_ID,
        "app_key": APP_KEY,
        "what": keyword,
        "results_per_page": RESULTS_PER_PAGE,
        "sort_by": "date",
        "max_days_old": MAX_DAYS_OLD,
        "content-type": "application/json",
    }
    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def parse_posting(raw: dict, country_code: str, keyword: str) -> dict:
    """Map a raw Adzuna posting into our flat row shape."""
    ts = now_iso()
    return {
        "posting_id": raw.get("id"),
        "country_code": country_code,
        "title": raw.get("title"),
        "company": (raw.get("company") or {}).get("display_name"),
        "location": (raw.get("location") or {}).get("display_name"),
        "category": (raw.get("category") or {}).get("label"),
        "contract_time": raw.get("contract_time"),
        "contract_type": raw.get("contract_type"),
        "salary_min": raw.get("salary_min"),
        "salary_max": raw.get("salary_max"),
        "salary_is_predicted": int(raw.get("salary_is_predicted", 0) or 0),
        "currency": CURRENCY_BY_COUNTRY.get(country_code, ""),
        "posted_date": raw.get("created"),
        "keyword_searched": keyword,
        "redirect_url": raw.get("redirect_url"),
        "first_seen_at": ts,
        "last_seen_at": ts,
    }


def upsert_postings(conn: sqlite3.Connection, postings: list) -> tuple:
    """
    Insert new postings or refresh last_seen_at on existing ones.
    Returns (rows_new, rows_updated).
    """
    cur = conn.cursor()
    rows_new, rows_updated = 0, 0
    ts = now_iso()

    for p in postings:
        cur.execute("SELECT posting_id FROM postings WHERE posting_id = ?", (p["posting_id"],))
        exists = cur.fetchone()

        if exists:
            cur.execute(
                """
                UPDATE postings
                SET last_seen_at = ?, is_active = 1,
                    salary_min = ?, salary_max = ?
                WHERE posting_id = ?
                """,
                (ts, p["salary_min"], p["salary_max"], p["posting_id"]),
            )
            rows_updated += 1
        else:
            cur.execute(
                """
                INSERT INTO postings (
                    posting_id, country_code, title, company, location,
                    category, contract_time, contract_type, salary_min,
                    salary_max, salary_is_predicted, currency, posted_date,
                    keyword_searched, redirect_url, first_seen_at, last_seen_at,
                    is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    p["posting_id"], p["country_code"], p["title"], p["company"],
                    p["location"], p["category"], p["contract_time"], p["contract_type"],
                    p["salary_min"], p["salary_max"], p["salary_is_predicted"],
                    p["currency"], p["posted_date"], p["keyword_searched"],
                    p["redirect_url"], p["first_seen_at"], p["last_seen_at"],
                ),
            )
            rows_new += 1

    conn.commit()
    return rows_new, rows_updated


def deactivate_missing(conn: sqlite3.Connection, country_code: str, keyword: str,
                        seen_ids: list) -> int:
    """
    Mark postings for this (country, keyword) as inactive if they weren't
    returned in this run's results — our "posting disappeared" signal.
    """
    cur = conn.cursor()
    if not seen_ids:
        placeholders = ""
        params = (country_code, keyword)
    else:
        placeholders = f"AND posting_id NOT IN ({','.join('?' for _ in seen_ids)})"
        params = (country_code, keyword, *seen_ids)

    cur.execute(
        f"""
        UPDATE postings
        SET is_active = 0
        WHERE country_code = ? AND keyword_searched = ? AND is_active = 1
        {placeholders}
        """,
        params,
    )
    conn.commit()
    return cur.rowcount


def log_run(conn: sqlite3.Connection, country_code: str, keyword: str, status: str,
            rows_fetched=0, rows_new=0, rows_updated=0, rows_deactivated=0,
            error_message=None) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO run_log (
            run_timestamp, country_code, keyword_searched, status,
            rows_fetched, rows_new, rows_updated, rows_deactivated, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (now_iso(), country_code, keyword, status, rows_fetched,
         rows_new, rows_updated, rows_deactivated, error_message),
    )
    conn.commit()


def run_for_country_keyword(conn: sqlite3.Connection, country_code: str, keyword: str) -> None:
    print(f"Fetching: country={country_code} keyword='{keyword}'")
    try:
        raw_response = fetch_page(country_code, keyword)
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else "unknown"
        if status_code == 429:
            msg = "Rate limited (HTTP 429) — skipping this country/keyword for this run"
        else:
            msg = f"HTTP error {status_code}: {e}"
        print(f"  FAILED: {msg}")
        log_run(conn, country_code, keyword, status="failed", error_message=msg)
        return
    except requests.exceptions.RequestException as e:
        msg = f"Request failed: {e}"
        print(f"  FAILED: {msg}")
        log_run(conn, country_code, keyword, status="failed", error_message=msg)
        return

    raw_postings = raw_response.get("results", [])
    parsed_postings = [parse_posting(r, country_code, keyword) for r in raw_postings]

    # --- Data quality checks ---
    issues = run_all_checks(raw_postings, parsed_postings)
    if issues:
        print(f"  Quality issues found ({len(issues)}):")
        for issue in issues[:10]:
            print(f"    - {issue}")

    # Schema drift is treated as fatal for this country/keyword —
    # better to halt than silently write malformed rows.
    schema_drift_issues = [i for i in issues if "Schema drift" in i]
    if schema_drift_issues:
        msg = f"Halted due to schema drift: {schema_drift_issues[:3]}"
        print(f"  FAILED: {msg}")
        log_run(conn, country_code, keyword, status="failed",
                rows_fetched=len(raw_postings), error_message=msg)
        return

    # Drop rows that failed the null check (unusable), keep the rest
    usable_postings = [
        p for p in parsed_postings
        if p.get("posting_id") and (p.get("title") or p.get("company") or p.get("location"))
    ]

    rows_new, rows_updated = upsert_postings(conn, usable_postings)
    seen_ids = [p["posting_id"] for p in usable_postings]
    rows_deactivated = deactivate_missing(conn, country_code, keyword, seen_ids)

    status = "partial" if issues else "success"
    log_run(
        conn, country_code, keyword, status=status,
        rows_fetched=len(raw_postings), rows_new=rows_new,
        rows_updated=rows_updated, rows_deactivated=rows_deactivated,
        error_message="; ".join(issues[:20]) if issues else None,
    )
    print(f"  Done: {rows_new} new, {rows_updated} updated, {rows_deactivated} deactivated")


def main():
    if not APP_ID or not APP_KEY:
        raise SystemExit(
            "Missing ADZUNA_APP_ID / ADZUNA_APP_KEY. "
            "Copy .env.example to .env and fill in your credentials."
        )

    conn = sqlite3.connect(DB_PATH)
    for country_code in COUNTRIES:
        for keyword in KEYWORDS:
            run_for_country_keyword(conn, country_code, keyword)
            time.sleep(1)  # small pause between calls, be polite to the API
    conn.close()
    print("All runs complete.")


if __name__ == "__main__":
    main()
