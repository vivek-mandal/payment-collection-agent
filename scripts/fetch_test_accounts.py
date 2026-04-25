"""Fetch live account data from the payment verification API and print a
summary table. Useful for confirming credentials before manual testing.

Usage:
    uv run python scripts/fetch_test_accounts.py
    uv run python scripts/fetch_test_accounts.py --json   # raw JSON output
"""

from __future__ import annotations

import argparse
import json
import sys

import requests

BASE_URL = "https://se-payment-verification-api.service.external.usea2.aws.prodigaltech.com"
ACCOUNT_IDS = ["ACC1001", "ACC1002", "ACC1003", "ACC1004"]
TIMEOUT = 10


def fetch_account(account_id: str) -> dict:
    resp = requests.post(
        f"{BASE_URL}/api/lookup-account",
        json={"account_id": account_id},
        timeout=TIMEOUT,
    )
    if resp.status_code == 200:
        return {"ok": True, "data": resp.json()}
    return {"ok": False, "account_id": account_id, "status": resp.status_code, "body": resp.text}


def print_table(accounts: list[dict]) -> None:
    cols = ["account_id", "full_name", "dob", "aadhaar_last4", "pincode", "balance"]
    widths = {c: max(len(c), *(len(str(a.get(c, ""))) for a in accounts)) for c in cols}

    header = "  ".join(c.ljust(widths[c]) for c in cols)
    sep = "  ".join("-" * widths[c] for c in cols)
    print("\n" + header)
    print(sep)
    for a in accounts:
        row = "  ".join(str(a.get(c, "ERROR")).ljust(widths[c]) for c in cols)
        print(row)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch test account data from the payment API")
    parser.add_argument("--json", action="store_true", help="Print raw JSON instead of table")
    args = parser.parse_args()

    print(f"Fetching {len(ACCOUNT_IDS)} accounts from {BASE_URL} ...\n")

    results = []
    errors = []

    for acc_id in ACCOUNT_IDS:
        result = fetch_account(acc_id)
        if result["ok"]:
            results.append(result["data"])
            print(f"  OK  {acc_id}")
        else:
            errors.append(result)
            print(f"  ERR {acc_id}  ->  HTTP {result['status']}: {result['body']}")

    print()

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        if results:
            print_table(results)

    if errors:
        print(f"WARNING: {len(errors)} account(s) failed to fetch.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
