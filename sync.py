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
TIMEZONE = pytz.timezone("UTC")  # Set to your timezone if needed

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
    - days_ago: Number of days in the past for the 'dated_after' filter (default is 2 days).
    """
    headers = {
        'Authorization': f'Bearer {SPLITWISE_API_KEY}',
        'Content-Type': 'application/json'
    }
    date_threshold = (datetime.now() - timedelta(days=days_ago)).date().isoformat()

    params = {
        'limit': limit,  # Set the number of transactions to retrieve
        'dated_after': date_threshold  # Set the date filter for transactions

    }
    
    response = requests.get(f"{SPLITWISE_API_URL}/get_expenses", headers=headers, params=params)
    
    if response.status_code == 200:
        data = response.json()
        return data['expenses']
    else:
        print(f"Failed to fetch transactions from Splitwise: {response.status_code}")
        return []

def format_for_ynab(transaction,user_id):
    """
    Format Splitwise transaction data for YNAB based on the net_balance for the specific user.
    """
    # Find the user data for the specific USER_ID
    amount = None
    for user in transaction['users']:
        if user['user']['id'] == user_id: 
            amount = user['net_balance']

    # YNAB expects milliunits, so convert net_balance to milliunits
    amount = int(float(amount) * 1000)
    description = transaction['description']
    date_str = transaction['date']
    date = datetime.fromisoformat(date_str).astimezone(TIMEZONE).date().isoformat()

    return {
        "account_id": YNAB_ACCOUNT_ID,
        "import_id": transaction['id'],
        "date": date,
        "amount": amount,
        "payee_name": description,
        "memo": f"Imported from Splitwise: {description}",
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
        print(f"{len(batch)} transactions imported successfully.")
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
