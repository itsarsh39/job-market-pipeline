"""
test_api.py

Helper script to verify Adzuna credentials with a single real API call
and test response schema against quality_checks.py before running full ingestion.
"""

import os
import sys
import requests
from dotenv import load_dotenv

from quality_checks import run_all_checks, EXPECTED_KEYS

load_dotenv()

APP_ID = os.getenv("ADZUNA_APP_ID")
APP_KEY = os.getenv("ADZUNA_APP_KEY")

if not APP_ID or not APP_KEY:
    print("ERROR: Missing ADZUNA_APP_ID or ADZUNA_APP_KEY in .env file.")
    print("Please set ADZUNA_APP_ID and ADZUNA_APP_KEY in .env before running.")
    sys.exit(1)

url = "https://api.adzuna.com/v1/api/jobs/in/search/1"
params = {
    "app_id": APP_ID,
    "app_key": APP_KEY,
    "what": "data analyst",
    "results_per_page": 5,
    "content-type": "application/json",
}

print(f"Testing Adzuna API credentials with a single call to {url}...")
try:
    response = requests.get(url, params=params, timeout=15)
    print(f"HTTP Status Code: {response.status_code}")
    response.raise_for_status()
    data = response.json()
    results = data.get("results", [])
    total_count = data.get("count", "unknown")
    print(f"Success! Total jobs available for 'data analyst' in 'in': {total_count}")
    print(f"Fetched {len(results)} sample postings.")

    if results:
        sample = results[0]
        actual_keys = set(sample.keys())
        print(f"\nKeys in sample posting:\n  {sorted(list(actual_keys))}")
        missing_keys = EXPECTED_KEYS - actual_keys
        extra_keys = actual_keys - EXPECTED_KEYS
        print(f"\nSchema comparison against EXPECTED_KEYS:")
        print(f"  Expected: {sorted(list(EXPECTED_KEYS))}")
        print(f"  Missing:  {sorted(list(missing_keys)) if missing_keys else 'None (All present!)'}")
        print(f"  Extra:    {sorted(list(extra_keys)) if extra_keys else 'None'}")

        # Run quality checks
        from fetch_jobs import parse_posting
        parsed_sample = [parse_posting(r, "in", "data analyst") for r in results]
        issues = run_all_checks(results, parsed_sample)
        print(f"\nQuality checks run on {len(results)} postings:")
        if issues:
            for issue in issues[:10]:
                print(f"  - {issue}")
        else:
            print("  No issues found! Clean batch.")

except requests.exceptions.HTTPError as e:
    status_code = e.response.status_code if e.response is not None else "unknown"
    if status_code in (401, 403):
        print(f"Authentication Failed (HTTP {status_code}): Invalid ADZUNA_APP_ID or ADZUNA_APP_KEY.")
    elif status_code == 429:
        print(f"Rate Limit Exceeded (HTTP 429).")
    else:
        print(f"HTTP error {status_code}: {e}")
    sys.exit(1)
except requests.exceptions.RequestException as e:
    print(f"Network / Connection error: {e}")
    sys.exit(1)
