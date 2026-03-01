import argparse
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import requests


YNAB_ACCESS_TOKEN = os.getenv("YNAB_ACCESS_TOKEN")
YNAB_BUDGET_ID = os.getenv("YNAB_BUDGET_ID")

KNOWN_FLAG_COLORS = ["red", "orange", "yellow", "green", "blue", "purple"]


def ynab_headers():
    return {
        "Authorization": f"Bearer {YNAB_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def require_env():
    missing = []
    if not YNAB_ACCESS_TOKEN:
        missing.append("YNAB_ACCESS_TOKEN")
    if not YNAB_BUDGET_ID:
        missing.append("YNAB_BUDGET_ID")
    if missing:
        raise SystemExit(f"Missing required env vars: {', '.join(missing)}")


def get_accounts():
    url = f"https://api.ynab.com/v1/budgets/{YNAB_BUDGET_ID}/accounts"
    response = requests.get(url, headers=ynab_headers(), timeout=30)
    response.raise_for_status()
    return response.json().get("data", {}).get("accounts", [])


def get_transactions(since_date=None):
    url = f"https://api.ynab.com/v1/budgets/{YNAB_BUDGET_ID}/transactions"
    params = {}
    if since_date:
        params["since_date"] = since_date
    response = requests.get(url, headers=ynab_headers(), params=params, timeout=60)
    response.raise_for_status()
    return response.json().get("data", {}).get("transactions", [])


def normalize_flag_color(value):
    if not value:
        return None
    return str(value).strip().lower()


def build_since_date(days):
    if days is None:
        return None
    if days < 0:
        raise SystemExit("--days must be >= 0")
    return (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()


def print_section(title):
    print(f"\n{title}")
    print("-" * len(title))


def main():
    parser = argparse.ArgumentParser(
        description="List YNAB flag usage to help identify an unused flag color."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Optional: only include transactions from last N days. If omitted, uses all history.",
    )
    parser.add_argument(
        "--on-budget-only",
        action="store_true",
        help="Optional: only include on-budget accounts.",
    )
    parser.add_argument(
        "--show-samples",
        type=int,
        default=3,
        help="Show up to this many sample transactions per used flag (default: 3).",
    )
    args = parser.parse_args()

    require_env()

    since_date = build_since_date(args.days)
    accounts = get_accounts()
    account_name_by_id = {a.get("id"): a.get("name") or a.get("id") for a in accounts}

    if args.on_budget_only:
        allowed_account_ids = {a.get("id") for a in accounts if a.get("on_budget")}
        scope_text = "on-budget accounts (open + closed)"
    else:
        allowed_account_ids = {a.get("id") for a in accounts}
        scope_text = "all accounts (on-budget + off-budget, open + closed)"

    transactions = get_transactions(since_date=since_date)

    flag_counts = Counter()
    sample_by_flag = defaultdict(list)
    considered = 0
    unflagged_count = 0

    for tx in transactions:
        if tx.get("deleted"):
            continue
        if tx.get("account_id") not in allowed_account_ids:
            continue

        considered += 1
        color = normalize_flag_color(tx.get("flag_color"))
        if not color:
            unflagged_count += 1
            continue

        flag_counts[color] += 1
        if len(sample_by_flag[color]) < args.show_samples:
            sample_by_flag[color].append(
                {
                    "date": tx.get("date"),
                    "amount_milliunits": tx.get("amount"),
                    "payee_name": tx.get("payee_name"),
                    "account": account_name_by_id.get(tx.get("account_id"), tx.get("account_id")),
                    "transaction_id": tx.get("id"),
                }
            )

    used_known_colors = [c for c in KNOWN_FLAG_COLORS if flag_counts.get(c, 0) > 0]
    unused_known_colors = [c for c in KNOWN_FLAG_COLORS if flag_counts.get(c, 0) == 0]
    unknown_colors = sorted([c for c in flag_counts.keys() if c not in KNOWN_FLAG_COLORS])

    print(f"Scope: {scope_text}")
    if since_date:
        print(f"Since: {since_date}")
    else:
        print("Since: all history")
    print(f"Transactions considered: {considered}")
    print(f"Unflagged transactions: {unflagged_count}")

    print_section("Flagged transactions")
    flagged_rows = []
    for color in sorted(flag_counts.keys()):
        for sample in sample_by_flag[color]:
            flagged_rows.append({**sample, "flag_color": color})

    # Rebuild full flagged list so this section is not limited by --show-samples.
    for tx in transactions:
        if tx.get("deleted"):
            continue
        if tx.get("account_id") not in allowed_account_ids:
            continue
        color = normalize_flag_color(tx.get("flag_color"))
        if not color:
            continue
        flagged_rows.append(
            {
                "date": tx.get("date"),
                "flag_color": color,
                "amount_milliunits": tx.get("amount"),
                "payee_name": tx.get("payee_name"),
                "account": account_name_by_id.get(tx.get("account_id"), tx.get("account_id")),
                "transaction_id": tx.get("id"),
            }
        )

    # Remove duplicates introduced by sample bootstrap and sort by date desc.
    deduped = {}
    for row in flagged_rows:
        deduped[row["transaction_id"]] = row
    flagged_rows = sorted(
        deduped.values(),
        key=lambda r: (r.get("date") or "", r.get("transaction_id") or ""),
        reverse=True,
    )

    if not flagged_rows:
        print("No flagged transactions found in this scope.")
    else:
        for row in flagged_rows:
            print(f"- {row}")

    print_section("Flag usage counts")
    if not flag_counts:
        print("No flagged transactions found in this scope.")
    else:
        for color, count in sorted(flag_counts.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"- {color}: {count}")

    print_section("Known colors in use")
    if used_known_colors:
        for color in used_known_colors:
            print(f"- {color}")
    else:
        print("- none")

    print_section("Known colors unused")
    if unused_known_colors:
        for color in unused_known_colors:
            print(f"- {color}")
    else:
        print("- none")

    if unknown_colors:
        print_section("Unexpected flag values")
        for color in unknown_colors:
            print(f"- {color}: {flag_counts[color]}")

    if args.show_samples > 0 and flag_counts:
        print_section("Sample transactions by flag")
        for color in sorted(flag_counts.keys()):
            print(f"{color}:")
            for sample in sample_by_flag[color]:
                print(f"- {sample}")


if __name__ == "__main__":
    main()
