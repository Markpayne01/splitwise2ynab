import os
import requests
import json
from datetime import datetime, timedelta
import pytz


# API credentials
SPLITWISE_API_KEY = os.getenv('SPLITWISE_API_KEY')
YNAB_ACCESS_TOKEN = os.getenv('YNAB_ACCESS_TOKEN')
YNAB_BUDGET_ID = os.getenv('YNAB_BUDGET_ID') 
YNAB_ACCOUNT_ID = os.getenv('YNAB_ACCOUNT_ID') 

# API endpoints
SPLITWISE_API_URL = 'https://secure.splitwise.com/api/v3.0'
YNAB_API_URL = f'https://api.youneedabudget.com/v1/budgets/{YNAB_BUDGET_ID}/transactions'

# Timezone settings
TIMEZONE = pytz.timezone("UTC") 

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
        return []

def get_splitwise_transactions(limit=10, days_ago=2):
    """
    Retrieve transactions from Splitwise with a limit and filter for transactions dated after a specific date.
    
    Parameters:
    - limit: Number of transactions to retrieve.
    - days_ago: Number of days in the past for the 'updated_after' filter (default is 2 days).
    """
    headers = {
        'Authorization': f'Bearer {SPLITWISE_API_KEY}',
        'Content-Type': 'application/json'
    }
    date_threshold = (datetime.now() - timedelta(days=days_ago)).date().isoformat()

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
    headers = {
        "Authorization": f"Bearer {YNAB_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "transactions": batch
    }

    response = requests.post(YNAB_API_URL, headers=headers, json=payload)

    if response.status_code == 201:
        print(f"{len(batch)} transactions imported successfully. {response.status_code} {response.text}")
    else:
        print(f"Failed to import: {response.status_code} {response.text}")

def import_transactions():
    transactions = get_splitwise_transactions()
    userid = get_current_splitwise_user_id()
    print(f"Transactions from Splitwise {transactions}")
    ynab_transactions = [format_for_ynab(transaction,userid) for transaction in transactions]
    print(f"Transactions for ynab {ynab_transactions}")

    post_transactions_to_ynab(ynab_transactions)

if __name__ == "__main__":
    import_transactions()
