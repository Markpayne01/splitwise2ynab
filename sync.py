import os
import requests
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import pytz


# API credentials
SPLITWISE_API_KEY = os.getenv('SPLITWISE_API_KEY')
YNAB_ACCESS_TOKEN = os.getenv('YNAB_ACCESS_TOKEN')
YNAB_BUDGET_ID = os.getenv('YNAB_BUDGET_ID') 
YNAB_ACCOUNT_ID = os.getenv('YNAB_ACCOUNT_ID') 
SPLITWISE_DEFAULT_PERSON_NAME = os.getenv('SPLITWISE_DEFAULT_PERSON_NAME')
YNAB_SPLITWISE_FLAG_COLOR = os.getenv('YNAB_SPLITWISE_FLAG_COLOR', 'yellow').strip().lower()
YNAB_SPLITWISE_DRY_RUN = os.getenv('YNAB_SPLITWISE_DRY_RUN', 'false').strip().lower() in ('1', 'true', 'yes')

# API endpoints
SPLITWISE_API_URL = 'https://secure.splitwise.com/api/v3.0'
YNAB_BASE_API_URL = f'https://api.ynab.com/v1/budgets/{YNAB_BUDGET_ID}'
YNAB_TRANSACTIONS_API_URL = f'{YNAB_BASE_API_URL}/transactions'
YNAB_ACCOUNTS_API_URL = f'{YNAB_BASE_API_URL}/accounts'

# Timezone settings
TIMEZONE = pytz.timezone("UTC") 


def env_int(name, default):
    value = os.getenv(name, str(default))
    try:
        return int(value)
    except (TypeError, ValueError):
        print(f"Invalid integer for {name}={value!r}; using default {default}.")
        return default


YNAB_SPLITWISE_LOOKBACK_DAYS = env_int('YNAB_SPLITWISE_LOOKBACK_DAYS', 7)

def splitwise_headers():
    return {
        'Authorization': f'Bearer {SPLITWISE_API_KEY}',
        'Content-Type': 'application/json'
    }


def ynab_headers():
    return {
        "Authorization": f"Bearer {YNAB_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }


def get_current_splitwise_user_id():
    headers = {
        'Authorization': f'Bearer {SPLITWISE_API_KEY}',
        'Content-Type': 'application/json'
    }  

    response = requests.get(f"{SPLITWISE_API_URL}/get_current_user", headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        return data['user']['id']
    else:
        print(f"Failed to fetch user id from Splitwise: {response.status_code}")
        return None

def get_splitwise_transactions(limit=10, days_ago=2):
    """
    Retrieve transactions from Splitwise with a limit and filter for transactions dated after a specific date.
    
    Parameters:
    - limit: Number of transactions to retrieve.
    - days_ago: Number of days in the past for the 'updated_after' filter (default is 2 days).
    """
    headers = splitwise_headers()
    date_threshold = (datetime.now(TIMEZONE) - timedelta(days=days_ago)).date().isoformat()

    params = {
        'limit': limit,  # Set the number of transactions to retrieve
        'updated_after': date_threshold  # Set the date filter for transactions

    }
    
    response = requests.get(f"{SPLITWISE_API_URL}/get_expenses", headers=headers, params=params)
    
    if response.status_code == 200:
        data = response.json()
        return data['expenses']
    else:
        print(f"Failed to fetch transactions from Splitwise: {response.status_code}")
        return []


def get_splitwise_friends():
    response = requests.get(f"{SPLITWISE_API_URL}/get_friends", headers=splitwise_headers())
    if response.status_code != 200:
        print(f"Failed to fetch friends from Splitwise: {response.status_code} {response.text}")
        return []

    return response.json().get("friends", [])


def resolve_splitwise_friend_id_by_name(friend_name):
    if not friend_name:
        print("SPLITWISE_DEFAULT_PERSON_NAME is not set; skipping YNAB->Splitwise sync.")
        return None

    target = friend_name.strip().casefold()
    matches = []

    for friend in get_splitwise_friends():
        first = (friend.get("first_name") or "").strip()
        last = (friend.get("last_name") or "").strip()
        full = " ".join(x for x in [first, last] if x).strip()

        candidates = {first.casefold(), full.casefold()}
        if target in candidates:
            matches.append(friend)

    if not matches:
        print(f"No Splitwise friend found matching '{friend_name}'.")
        return None

    if len(matches) > 1:
        names = []
        for match in matches:
            first = (match.get("first_name") or "").strip()
            last = (match.get("last_name") or "").strip()
            names.append(" ".join(x for x in [first, last] if x).strip() or str(match.get("id")))
        print(
            f"Ambiguous Splitwise friend name '{friend_name}'. "
            f"Matches: {', '.join(names)}. Please use a unique name."
        )
        return None

    return matches[0].get("id")


def get_ynab_accounts():
    response = requests.get(YNAB_ACCOUNTS_API_URL, headers=ynab_headers())
    if response.status_code != 200:
        print(f"Failed to fetch accounts from YNAB: {response.status_code} {response.text}")
        return []
    return response.json().get("data", {}).get("accounts", [])


def parse_ynab_date(date_value):
    if not date_value:
        return None
    try:
        return datetime.strptime(date_value, "%Y-%m-%d").date()
    except ValueError:
        return None


def get_flagged_ynab_transactions(flag_color, lookback_days):
    on_budget_account_ids = {
        account.get("id")
        for account in get_ynab_accounts()
        if account.get("on_budget") and not account.get("closed")
    }

    if not on_budget_account_ids:
        return []

    response = requests.get(YNAB_TRANSACTIONS_API_URL, headers=ynab_headers())
    if response.status_code != 200:
        print(f"Failed to fetch transactions from YNAB: {response.status_code} {response.text}")
        return []

    transactions = response.json().get("data", {}).get("transactions", [])
    cutoff_date = (datetime.now(TIMEZONE) - timedelta(days=lookback_days)).date()
    filtered = []
    for tx in transactions:
        if tx.get("deleted"):
            continue
        if tx.get("account_id") not in on_budget_account_ids:
            continue
        if (tx.get("flag_color") or "").lower() != flag_color:
            continue
        # Skip split subtransactions and account transfers.
        if tx.get("parent_transaction_id") or tx.get("transfer_account_id"):
            continue
        # Only outflow transactions should become Splitwise expenses.
        if (tx.get("amount") or 0) >= 0:
            continue
        tx_date = parse_ynab_date(tx.get("date"))
        if tx_date is None:
            continue
        if tx_date < cutoff_date:
            continue
        filtered.append(tx)

    return filtered


def decimal_to_string(value):
    return f"{value.quantize(Decimal('0.01')):.2f}"


def milliunits_to_decimal_abs(milliunits):
    return (Decimal(abs(milliunits)) / Decimal(1000)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def build_splitwise_expense_payload(ynab_transaction, splitwise_user_id, friend_user_id):
    cost = milliunits_to_decimal_abs(ynab_transaction.get("amount", 0))
    friend_owed = (cost / Decimal(2)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    user_owed = (cost - friend_owed).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    description = (
        ynab_transaction.get("payee_name")
        or ynab_transaction.get("memo")
        or f"YNAB transaction {ynab_transaction.get('date')}"
    )
    details = f"Created by splitwise2ynab from YNAB transaction {ynab_transaction.get('id')}"
    tx_date = f"{ynab_transaction.get('date')}T00:00:00Z"

    return {
        "cost": decimal_to_string(cost),
        "description": description,
        "details": details,
        "date": tx_date,
        "group_id": 0,
        "users__0__user_id": splitwise_user_id,
        "users__0__paid_share": decimal_to_string(cost),
        "users__0__owed_share": decimal_to_string(user_owed),
        "users__1__user_id": friend_user_id,
        "users__1__paid_share": "0.00",
        "users__1__owed_share": decimal_to_string(friend_owed),
    }


def create_splitwise_expense(payload):
    response = requests.post(f"{SPLITWISE_API_URL}/create_expense", headers=splitwise_headers(), json=payload)
    if response.status_code != 200:
        print(f"Failed to create expense in Splitwise: {response.status_code} {response.text}")
        return None

    data = response.json()
    if data.get("errors"):
        print(f"Splitwise returned errors while creating expense: {data.get('errors')}")
        return None

    expenses = data.get("expenses") or []
    if not expenses:
        print("Splitwise create_expense returned no expense object.")
        return None

    return expenses[0].get("id")


def clear_ynab_flag(transaction_id):
    patch_url = f"{YNAB_TRANSACTIONS_API_URL}/{transaction_id}"
    payload = {"transaction": {"flag_color": None}}
    response = requests.patch(patch_url, headers=ynab_headers(), json=payload)
    if response.status_code != 200:
        print(f"Failed to clear flag in YNAB for transaction {transaction_id}: {response.status_code} {response.text}")
        return False
    return True


def sync_ynab_flagged_transactions_to_splitwise():
    if YNAB_SPLITWISE_LOOKBACK_DAYS < 0:
        print("YNAB_SPLITWISE_LOOKBACK_DAYS must be >= 0; skipping YNAB->Splitwise sync.")
        return

    splitwise_user_id = get_current_splitwise_user_id()
    if splitwise_user_id is None:
        return

    friend_id = resolve_splitwise_friend_id_by_name(SPLITWISE_DEFAULT_PERSON_NAME)
    if friend_id is None:
        return

    flagged_transactions = get_flagged_ynab_transactions(
        YNAB_SPLITWISE_FLAG_COLOR,
        YNAB_SPLITWISE_LOOKBACK_DAYS
    )
    if not flagged_transactions:
        print(
            f"No on-budget YNAB transactions found with flag '{YNAB_SPLITWISE_FLAG_COLOR}' "
            f"in the last {YNAB_SPLITWISE_LOOKBACK_DAYS} day(s)."
        )
        return

    created_count = 0
    dry_run_count = 0
    for tx in flagged_transactions:
        payload = build_splitwise_expense_payload(tx, splitwise_user_id, friend_id)
        if YNAB_SPLITWISE_DRY_RUN:
            dry_run_count += 1
            print(
                f"[DRY RUN] Would create Splitwise expense from YNAB transaction {tx.get('id')} "
                f"dated {tx.get('date')} with cost {payload.get('cost')}"
            )
            continue

        expense_id = create_splitwise_expense(payload)
        if expense_id is None:
            continue

        if clear_ynab_flag(tx.get("id")):
            created_count += 1
            print(
                f"Created Splitwise expense {expense_id} from YNAB transaction {tx.get('id')} "
                f"and cleared the YNAB flag."
            )

    if YNAB_SPLITWISE_DRY_RUN:
        print(f"YNAB->Splitwise dry run complete. Would create {dry_run_count} expense(s).")
    else:
        print(f"YNAB->Splitwise sync complete. Created {created_count} expense(s).")

def format_for_ynab(transaction, user_id):
    """
    Format Splitwise transaction data for YNAB based on the net_balance for the specific user.
    Payee is the counterparty (who you owe / who owes you). Memo includes 'paid by' and brief context.
    """

    # Find the net balance of the logged in user for this transaction.
    amount = None
    for u in transaction["users"]:
        if u["user"]["id"] == user_id:
            amount = u["net_balance"]
            break

    # Identify counterparties
    others = []
    for u in transaction["users"]:
        if u["user"]["id"] == user_id:
            continue
        first = u["user"].get("first_name", "")
        last = u["user"].get("last_name", "")
        name = " ".join(x for x in [first, last] if x).strip()
        others.append(name or str(u["user"]["id"]))

    if len(others) == 1:
        payee_name = f"{others[0]} (Splitwise)"
    elif len(others) > 1:
        payee_name = "Multiple people (Splitwise)"
    else:
        payee_name = "Splitwise"

    # Determine payer(s): anyone with paid_share > 0
    payers = []
    for u in transaction["users"]:
        try:
            if float(u.get("paid_share", "0") or "0") > 0:
                first = u["user"].get("first_name", "")
                last = u["user"].get("last_name", "")
                name = " ".join(x for x in [first, last] if x).strip()
                payers.append(name or str(u["user"]["id"]))
        except (TypeError, ValueError):
            continue

    paid_by_text = ", ".join(payers) if payers else "unknown"

    # Keep description as the human label in memo, plus payer context
    memo = f"Splitwise: {transaction['description']} | paid by {paid_by_text}"

    return {
        "account_id": YNAB_ACCOUNT_ID,
        "import_id": transaction["id"],
        "date": transaction["date"],
        "amount": int(float(amount) * 1000),
        "payee_name": payee_name,
        "memo": memo,
        "cleared": "cleared",
        "approved": False
    }

def post_transactions_to_ynab(batch):
    headers = ynab_headers()
    payload = {
        "transactions": batch
    }

    if not batch:
        print("No Splitwise transactions to import into YNAB.")
        return

    response = requests.post(YNAB_TRANSACTIONS_API_URL, headers=headers, json=payload)

    if response.status_code == 201:
        print(f"{len(batch)} transactions imported successfully. {response.status_code} {response.text}")
    else:
        print(f"Failed to import: {response.status_code} {response.text}")

def import_transactions():
    sync_ynab_flagged_transactions_to_splitwise()

    transactions = get_splitwise_transactions()
    userid = get_current_splitwise_user_id()
    if userid is None:
        print("Cannot import Splitwise transactions because current Splitwise user id could not be fetched.")
        return

    print(f"Transactions from Splitwise {transactions}")
    ynab_transactions = [format_for_ynab(transaction,userid) for transaction in transactions]
    print(f"Transactions for ynab {ynab_transactions}")

    post_transactions_to_ynab(ynab_transactions)

if __name__ == "__main__":
    import_transactions()
