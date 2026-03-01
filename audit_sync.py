import argparse
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import requests


SPLITWISE_API_KEY = os.getenv("SPLITWISE_API_KEY")
YNAB_ACCESS_TOKEN = os.getenv("YNAB_ACCESS_TOKEN")
YNAB_BUDGET_ID = os.getenv("YNAB_BUDGET_ID")
YNAB_ACCOUNT_ID = os.getenv("YNAB_ACCOUNT_ID")
SPLITWISE_API_URL = "https://secure.splitwise.com/api/v3.0"


def splitwise_headers():
    return {
        "Authorization": f"Bearer {SPLITWISE_API_KEY}",
        "Content-Type": "application/json",
    }


def ynab_headers():
    return {
        "Authorization": f"Bearer {YNAB_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def require_env():
    required = {
        "SPLITWISE_API_KEY": SPLITWISE_API_KEY,
        "YNAB_ACCESS_TOKEN": YNAB_ACCESS_TOKEN,
        "YNAB_BUDGET_ID": YNAB_BUDGET_ID,
        "YNAB_ACCOUNT_ID": YNAB_ACCOUNT_ID,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise SystemExit(f"Missing required env vars: {', '.join(missing)}")


def get_current_splitwise_user_id():
    response = requests.get(f"{SPLITWISE_API_URL}/get_current_user", headers=splitwise_headers(), timeout=30)
    response.raise_for_status()
    return response.json()["user"]["id"]


def get_splitwise_expenses(updated_after, max_records):
    expenses = []
    limit = 100
    offset = 0

    while len(expenses) < max_records:
        params = {
            "updated_after": updated_after,
            "limit": min(limit, max_records - len(expenses)),
            "offset": offset,
        }
        response = requests.get(
            f"{SPLITWISE_API_URL}/get_expenses",
            headers=splitwise_headers(),
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        page = response.json().get("expenses", [])
        if not page:
            break

        expenses.extend(page)
        if len(page) < params["limit"]:
            break
        offset += len(page)

    return expenses


def is_splitwise_deleted(expense):
    # Splitwise marks deleted expenses with a non-null deleted_at timestamp.
    return bool(expense.get("deleted_at"))


def get_ynab_account_transactions(account_id, since_date):
    url = f"https://api.ynab.com/v1/budgets/{YNAB_BUDGET_ID}/accounts/{account_id}/transactions"
    response = requests.get(url, headers=ynab_headers(), params={"since_date": since_date}, timeout=30)
    response.raise_for_status()
    return response.json().get("data", {}).get("transactions", [])


def expense_user_map(expense):
    users = expense.get("users") or []
    return {u.get("user", {}).get("id"): u for u in users}


def to_milliunits(value):
    decimal_value = Decimal(str(value))
    return int((decimal_value * Decimal(1000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def expected_ynab_from_splitwise(expense, splitwise_user_id):
    users = expense_user_map(expense)
    current_user = users.get(splitwise_user_id) or {}
    amount = to_milliunits(current_user.get("net_balance", "0"))

    payers = []
    others = []
    for participant in expense.get("users") or []:
        user = participant.get("user", {})
        user_id = user.get("id")
        name = " ".join(
            x for x in [user.get("first_name", "").strip(), user.get("last_name", "").strip()] if x
        ).strip() or str(user_id)

        if user_id != splitwise_user_id:
            others.append(name)

        try:
            if float(participant.get("paid_share", "0") or "0") > 0:
                payers.append(name)
        except (TypeError, ValueError):
            pass

    if len(others) == 1:
        payee = f"{others[0]} (Splitwise)"
    elif len(others) > 1:
        payee = "Multiple people (Splitwise)"
    else:
        payee = "Splitwise"

    paid_by_text = ", ".join(payers) if payers else "unknown"
    memo = f"Splitwise: {expense.get('description', '')} | paid by {paid_by_text}"

    return {
        "id": str(expense.get("id")),
        "date": (expense.get("date") or "")[:10],
        "amount": amount,
        "payee_name": payee,
        "memo": memo,
    }


def compare(splitwise_expenses, ynab_transactions, splitwise_user_id):
    expected_by_id = {}
    active_splitwise_expenses = [expense for expense in splitwise_expenses if not is_splitwise_deleted(expense)]

    for expense in active_splitwise_expenses:
        expected = expected_ynab_from_splitwise(expense, splitwise_user_id)
        expected_by_id[expected["id"]] = expected

    ynab_by_import_id = {}
    for tx in ynab_transactions:
        if tx.get("deleted"):
            continue

        import_id = (tx.get("import_id") or "").strip()
        if import_id:
            ynab_by_import_id[import_id] = tx

    missing_in_ynab = []
    different = []

    for splitwise_id, expected in expected_by_id.items():
        tx = ynab_by_import_id.get(splitwise_id)
        if not tx:
            missing_in_ynab.append(expected)
            continue

        differences = {}
        if tx.get("amount") != expected["amount"]:
            differences["amount"] = {
                "splitwise_expected": expected["amount"],
                "ynab_actual": tx.get("amount"),
            }
        if tx.get("date") != expected["date"]:
            differences["date"] = {
                "splitwise_expected": expected["date"],
                "ynab_actual": tx.get("date"),
            }

        actual_memo = tx.get("memo") or ""
        if actual_memo != expected["memo"]:
            differences["memo"] = {
                "splitwise_expected": expected["memo"],
                "ynab_actual": actual_memo,
            }

        if differences:
            different.append(
                {
                    "splitwise_id": splitwise_id,
                    "ynab_transaction_id": tx.get("id"),
                    "differences": differences,
                }
            )

    return {
        "splitwise_count": len(active_splitwise_expenses),
        "ynab_count": len([t for t in ynab_transactions if not t.get("deleted")]),
        "missing_in_ynab": missing_in_ynab,
        "different": different,
    }


def print_list(title, items, limit):
    print(f"\n{title}: {len(items)}")
    for item in items[:limit]:
        print(f"- {item}")
    if len(items) > limit:
        print(f"... {len(items) - limit} more")


def normalize_splitwise(expense, splitwise_user_id):
    expected = expected_ynab_from_splitwise(expense, splitwise_user_id)
    return {
        "splitwise_id": expected["id"],
        "date": expected["date"],
        "amount_milliunits": expected["amount"],
        "description": expense.get("description"),
    }


def normalize_ynab(tx):
    return {
        "ynab_transaction_id": tx.get("id"),
        "import_id": tx.get("import_id"),
        "date": tx.get("date"),
        "amount_milliunits": tx.get("amount"),
        "payee_name": tx.get("payee_name"),
        "memo": tx.get("memo"),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Audit original Splitwise->YNAB sync expectations for missing/different records."
    )
    parser.add_argument("--days", type=int, default=30, help="Look back this many days (default: 30)")
    parser.add_argument(
        "--max-splitwise",
        type=int,
        default=1000,
        help="Max Splitwise expenses to fetch within the date window (default: 1000)",
    )
    parser.add_argument(
        "--account-id",
        default=YNAB_ACCOUNT_ID,
        help="YNAB account id to audit (default: YNAB_ACCOUNT_ID env var)",
    )
    parser.add_argument(
        "--show",
        type=int,
        default=20,
        help="How many rows to print per section (default: 20)",
    )
    parser.add_argument(
        "--list-transactions",
        action="store_true",
        help="Also print normalized Splitwise and YNAB transaction lists.",
    )
    args = parser.parse_args()

    require_env()
    if not args.account_id:
        raise SystemExit("No YNAB account id supplied. Set YNAB_ACCOUNT_ID or use --account-id.")

    updated_after = (datetime.now(timezone.utc) - timedelta(days=args.days)).date().isoformat()
    print(f"Auditing since {updated_after} UTC")
    print(f"YNAB account: {args.account_id}")

    splitwise_user_id = get_current_splitwise_user_id()
    splitwise_expenses = get_splitwise_expenses(updated_after=updated_after, max_records=args.max_splitwise)
    ynab_transactions = get_ynab_account_transactions(account_id=args.account_id, since_date=updated_after)

    results = compare(splitwise_expenses, ynab_transactions, splitwise_user_id)

    print(f"\nSplitwise expenses fetched: {results['splitwise_count']}")
    print(f"YNAB transactions fetched: {results['ynab_count']}")

    if args.list_transactions:
        splitwise_list = [
            normalize_splitwise(expense, splitwise_user_id)
            for expense in splitwise_expenses
            if not is_splitwise_deleted(expense)
        ]
        ynab_list = [
            normalize_ynab(tx)
            for tx in ynab_transactions
            if not tx.get("deleted")
        ]
        print_list("Splitwise transactions (normalized)", splitwise_list, args.show)
        print_list("YNAB transactions (normalized)", ynab_list, args.show)

    print_list("Missing in YNAB (exists in Splitwise)", results["missing_in_ynab"], args.show)
    print_list("Different fields", results["different"], args.show)


if __name__ == "__main__":
    main()
