"""
init_db.py

Creates the SQLite database and tables for the job-market pipeline.
Safe to run multiple times — uses CREATE TABLE IF NOT EXISTS, so it
will never wipe existing data.

Usage:
    python init_db.py
"""

import sqlite3

DB_PATH = "jobs.db"

CREATE_POSTINGS_TABLE = """
CREATE TABLE IF NOT EXISTS postings (
    posting_id          TEXT PRIMARY KEY,
    country_code        TEXT NOT NULL,
    title                TEXT,
    company              TEXT,
    location             TEXT,
    category             TEXT,
    contract_time        TEXT,   -- full_time / part_time
    contract_type        TEXT,   -- permanent / contract
    salary_min           REAL,
    salary_max           REAL,
    salary_is_predicted  INTEGER,
    currency             TEXT,
    posted_date          TEXT,
    keyword_searched     TEXT,
    redirect_url         TEXT,
    first_seen_at        TEXT NOT NULL,
    last_seen_at         TEXT NOT NULL,
    is_active            INTEGER NOT NULL DEFAULT 1
);
"""

CREATE_RUN_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS run_log (
    run_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_timestamp     TEXT NOT NULL,
    country_code      TEXT NOT NULL,
    keyword_searched  TEXT,
    status            TEXT NOT NULL,   -- success / failed / partial
    rows_fetched      INTEGER DEFAULT 0,
    rows_new          INTEGER DEFAULT 0,
    rows_updated      INTEGER DEFAULT 0,
    rows_deactivated  INTEGER DEFAULT 0,
    error_message     TEXT
);
"""

# Helpful indexes for the dashboard's queries
CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_postings_country ON postings(country_code);",
    "CREATE INDEX IF NOT EXISTS idx_postings_active ON postings(is_active);",
    "CREATE INDEX IF NOT EXISTS idx_postings_date ON postings(posted_date);",
    "CREATE INDEX IF NOT EXISTS idx_runlog_timestamp ON run_log(run_timestamp);",
]

# SQL Analytical Views for reporting & data modeling
CREATE_VIEWS = [
    """
    CREATE VIEW IF NOT EXISTS vw_country_summary AS
    SELECT 
        country_code,
        keyword_searched,
        COUNT(*) AS total_postings,
        SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active_postings,
        AVG(salary_min) AS avg_salary_min,
        AVG(salary_max) AS avg_salary_max,
        COUNT(CASE WHEN salary_min IS NOT NULL THEN 1 END) AS postings_with_salary
    FROM postings
    GROUP BY country_code, keyword_searched;
    """,
    """
    CREATE VIEW IF NOT EXISTS vw_pipeline_health_summary AS
    SELECT 
        country_code,
        keyword_searched,
        COUNT(run_id) AS total_runs,
        SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_runs,
        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_runs,
        SUM(rows_fetched) AS total_rows_fetched,
        SUM(rows_new) AS total_rows_new,
        SUM(rows_updated) AS total_rows_updated,
        SUM(rows_deactivated) AS total_rows_deactivated
    FROM run_log
    GROUP BY country_code, keyword_searched;
    """
]


def init_db(db_path: str = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(CREATE_POSTINGS_TABLE)
    cur.execute(CREATE_RUN_LOG_TABLE)
    for stmt in CREATE_INDEXES:
        cur.execute(stmt)
    for stmt in CREATE_VIEWS:
        cur.execute(stmt)
    conn.commit()
    conn.close()
    print(f"Database ready at {db_path}")


if __name__ == "__main__":
    init_db()

