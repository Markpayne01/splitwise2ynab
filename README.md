# Splitwise to YNAB Integration

 A Python script to integrate Splitwise with YNAB (You Need A Budget). The script retrieves recent expenses from your Splitwise account, formats them to match YNAB's transaction format, and imports them into your YNAB budget.

## Features

- Retrieve recent Splitwise transactions from your account.
- Convert Splitwise transaction data into the format expected by YNAB.
- Import transactions directly into a specified YNAB budget and account.
- Create Splitwise expenses from flagged YNAB transactions in any on-budget account.

## Configuration

1.  **Set Environment Variables**  
    You need to configure the following environment variables for the script to work:
    
    - `SPLITWISE_API_KEY`: Your Splitwise API key.
    - `YNAB_ACCESS_TOKEN`: Your YNAB API access token.
    - `YNAB_BUDGET_ID`: The ID of your YNAB budget.
    - `YNAB_ACCOUNT_ID`: The ID of the YNAB account where you want to import transactions.
    - `SPLITWISE_DEFAULT_PERSON_NAME`: The Splitwise friend name to use for new 50:50 expenses created from flagged YNAB transactions.
    - `YNAB_SPLITWISE_FLAG_COLOR`: YNAB flag color that triggers Splitwise creation (default: `yellow`).
    - `YNAB_SPLITWISE_SYNCED_FLAG_COLOR`: Optional flag color to set after successful sync (for example `blue`). If unset, the trigger flag is cleared.
    - `YNAB_SPLITWISE_LOOKBACK_DAYS`: Only process flagged YNAB transactions within this many recent days (default: `7`).
    - `YNAB_SPLITWISE_DRY_RUN`: If `true`, print what would be created without creating Splitwise expenses or clearing YNAB flags.

## YNAB Flag -> Splitwise behavior

- When an outflow transaction in any on-budget, open YNAB account is flagged with `YNAB_SPLITWISE_FLAG_COLOR`, the script creates a Splitwise expense.
- The expense is split 50:50 between your Splitwise user and `SPLITWISE_DEFAULT_PERSON_NAME`.
- Only transactions within `YNAB_SPLITWISE_LOOKBACK_DAYS` are considered.
- After successful sync, the script sets `YNAB_SPLITWISE_SYNCED_FLAG_COLOR` if configured; otherwise it clears the YNAB flag.
- After that, normal Splitwise -> YNAB import behavior continues unchanged.

Recommended first run:

```bash
export YNAB_SPLITWISE_DRY_RUN=true
python3 sync.py
```

## Audit helper

Use `audit_sync.py` to audit the original Splitwise -> YNAB sync mapping and report:
- missing in YNAB
- different fields (amount/date/memo)

Example:

```bash
python3 audit_sync.py --days 30 --show 50 --list-transactions
```

Useful options:
- `--account-id <YNAB_ACCOUNT_ID>`: override account to audit.
- `--max-splitwise 1000`: limit Splitwise expenses fetched.
- `--days 30`: set lookback window.

## YNAB flag usage helper

Use `list_ynab_flags.py` to see which flag colors are already in use and which known colors are currently unused.

Examples:

```bash
python3 list_ynab_flags.py
python3 list_ynab_flags.py --days 365 --show-samples 5
python3 list_ynab_flags.py --on-budget-only
```

    
