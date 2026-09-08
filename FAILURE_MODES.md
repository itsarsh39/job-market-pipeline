# Failure Modes and Resilience Guide

This document specifies the failure modes, error handling strategies, data-quality safeguards, and recovery procedures for the **Self-Refreshing Job-Market Analytics Pipeline**.

---

## 1. Summary Failure Matrix

| Failure Mode | Root Cause / Trigger | Pipeline Behavior & Mitigation | Impact on `jobs.db` | Observability / Detection |
| :--- | :--- | :--- | :--- | :--- |
| **API Outage / Network Timeout** | Adzuna downtime, DNS failure, HTTP 5xx, or network timeout (> 20s) | Caught via `requests.exceptions.RequestException`. Run is aborted for that batch. | **Zero data loss**. Existing rows remain untouched; no partial commits. | `run_log.status = 'failed'` with full error string; dashboard staleness warning triggered (> 36h). |
| **Rate Limit Exceeded (HTTP 429)** | Exceeded daily/hourly free tier quota (~a few hundred calls/day) | Specific HTTP 429 handler catches error, skips current `(country, keyword)` pair politely without crashing whole script. | Previous data preserved. No new rows added for rate-limited country. | `run_log.status = 'failed'`, `error_message = 'Rate limited (HTTP 429)...'`. |
| **Schema Drift** | Adzuna removes or renames expected fields (e.g. `id`, `created`, `salary_is_predicted`) | `check_schema_drift()` flags missing keys against `EXPECTED_KEYS`. Execution halts immediately for that batch. | Prevents silent data corruption or malformed schema in `postings`. | `run_log.status = 'failed'`, `error_message = 'Halted due to schema drift: [...]'`. |
| **Missed Scheduled Run** | GitHub Actions outage, cron delay, or repository runner queuing | Pipeline is stateless and idempotent. Next scheduled or manual run catches up using `max_days_old=30`. | Data remains at last known state until next run. | Visible timestamp gap in `run_log.run_timestamp`. |
| **Unusable / Corrupt Rows (Nulls)** | Job scraping artifacts lacking `posting_id` or completely missing `title`, `company`, and `location` | `check_nulls()` flags unusable records. Filter drops them before database upsert while keeping valid records. | Dropped rows are discarded; only clean records enter `postings`. | `run_log.status = 'partial'`, issue listed in `error_message`. |
| **Salary Data Inconsistencies** | Employer typos, `salary_min > salary_max`, or negative values | `check_salary_sanity()` logs issues. Postings are retained rather than discarded to preserve market presence signal. | Row is inserted/updated; salary is kept as-is or sanitized for analytics. | `run_log.status = 'partial'`, issue noted in `error_message`. |
| **Duplicate Records within Batch** | Search query matching overlapping postings across keywords or pages | Natural primary key `posting_id` with `check_duplicates()` verification. Upsert updates `last_seen_at` without duplication. | Exactly one row per `posting_id`. | `rows_updated` incremented instead of duplicate insertion. |
| **Posting Removal / Expiration** | Job listing filled, removed, or expired upstream on job board | `deactivate_missing()` performs soft deletion: sets `is_active = 0` for postings not returned in the latest run. | Historical record preserved for trend analysis; active view excludes them. | `run_log.rows_deactivated` tracks volume of expired jobs. |

---

## 2. Detailed Scenario Analysis

### 2.1 API Outages and Network Timeouts
- **Mechanism**: The API request in `fetch_page()` is configured with an explicit `timeout=20` to prevent hanging jobs:
  ```python
  response = requests.get(url, params=params, timeout=20)
  response.raise_for_status()
  ```
- **Error Handling**: `fetch_jobs.py` wraps calls in `try...except (requests.exceptions.HTTPError, requests.exceptions.RequestException)`.
- **Database Safety**: Database commits occur per batch only after successful parsing and validation. An API failure triggers a write to `run_log` with `status='failed'` and leaves `postings` in its previous consistent state.

### 2.2 Schema Drift Protection
- **Why It Matters**: Upstream API changes are the most common source of silent data pipeline degradation. If an API provider renames `id` to `job_id` or removes `created`, downstream queries crash days later.
- **Enforcement**: `quality_checks.py` defines `EXPECTED_KEYS`:
  ```python
  EXPECTED_KEYS = {
      "id", "title", "company", "location", "category",
      "created", "redirect_url", "salary_is_predicted",
  }
  ```
- **Action**: Any missing field from `EXPECTED_KEYS` is treated as fatal schema drift. Ingestion for that country/keyword is immediately stopped, preventing partial or corrupt data from being committed.

### 2.3 Rate Limiting (HTTP 429)
- **API Constraints**: Adzuna's free tier provides a daily call budget.
- **Pipeline Etiquette**:
  - `fetch_jobs.py` inserts a polite `time.sleep(1)` between consecutive calls.
  - The default scope is constrained to 6 countries (`in`, `us`, `gb`, `au`, `ca`, `sg`) × 2 keywords = 12 requests per run.
  - If HTTP 429 occurs, it is trapped specifically, logged with clear diagnostic messaging, and execution gracefully continues to other tasks without crash traces.

### 2.4 Idempotence and Run Resumption
- **Primary Key Deduplication**: `posting_id` serves as the primary key.
- **Upsert Logic**:
  - New postings receive both `first_seen_at` and `last_seen_at` timestamps with `is_active = 1`.
  - Existing postings have their `last_seen_at` refreshed, `is_active` set to `1`, and latest salary ranges updated.
  - If a pipeline run fails midway or runs twice in the same hour, the database remains completely consistent without duplicate rows.

### 2.5 Job Expiration (Soft Deletes)
- Postings are never physically deleted (`DELETE FROM postings`) because historical data is required to calculate market metrics like average job duration, hiring surges, and category volume over time.
- The pipeline tracks vanished listings using:
  ```sql
  UPDATE postings
  SET is_active = 0
  WHERE country_code = ? AND keyword_searched = ? AND is_active = 1
    AND posting_id NOT IN (...)
  ```
- When a job is no longer returned by the API within that search criteria, it transitions to `is_active = 0`.

---

## 3. Operational Recovery Procedures

### If a run fails due to invalid credentials (HTTP 401/403)
1. Verify credentials locally using `test_api.py`.
2. Update GitHub Repository Secrets:
   - Navigate to **Settings → Secrets and variables → Actions**.
   - Update `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`.
3. Trigger the workflow manually via **Actions → Refresh Job Data → Run workflow**.

### If schema drift is reported
1. Review the error message logged in `run_log` or GitHub Actions console.
2. Run `test_api.py` locally to inspect the new raw payload shape.
3. Update `quality_checks.py` (`EXPECTED_KEYS`) and `fetch_jobs.py` (`parse_posting`) to support the updated upstream schema.
4. Run `fetch_jobs.py` locally to verify before pushing to GitHub.
