# Splitwise to YNAB Integration

 A Python script to integrate Splitwise with YNAB (You Need A Budget). The script retrieves the last 2 days of expenses from your Splitwise account, formats them to match YNAB's transaction format, and imports them into your YNAB budget.

## Features

- Retrieve recent Splitwise transactions from your account.
- Convert Splitwise transaction data into the format expected by YNAB.
- Import transactions directly into a specified YNAB budget and account.

## Configuration

1.  **Set Environment Variables**  
    You need to configure the following environment variables for the script to work:
    
    - `SPLITWISE_API_KEY`: Your Splitwise API key.
    - `SPLITWISE_USER_ID`: Your unique Splitwise user ID, this is used to select your net_balance out of a splitwise transaction,  
    - `YNAB_ACCESS_TOKEN`: Your YNAB API access token.
    - `YNAB_BUDGET_ID`: The ID of your YNAB budget.
    - `YNAB_ACCOUNT_ID`: The ID of the YNAB account where you want to import transactions.

    

