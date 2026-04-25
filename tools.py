"""
tools.py — API wrappers for the payment collection agent.
Handles all external HTTP calls with proper error handling.
"""

import requests
from typing import Optional

BASE_URL = "https://se-payment-verification-api.service.external.usea2.aws.prodigaltech.com/openapi"
TIMEOUT_SECONDS = 10


def lookup_account(account_id: str) -> dict:
    """
    Look up an account by ID.

    Returns:
        {
            "success": True,
            "data": { account fields ... }
        }
        OR
        {
            "success": False,
            "error_code": "account_not_found" | "api_error" | "timeout" | "network_error",
            "detail": optional str
        }
    """
    try:
        resp = requests.post(
            f"{BASE_URL}/api/lookup-account",
            json={"account_id": account_id},
            timeout=TIMEOUT_SECONDS,
        )

        if resp.status_code == 200:
            return {"success": True, "data": resp.json()}

        if resp.status_code == 404:
            return {"success": False, "error_code": "account_not_found"}

        # Unexpected status code
        return {
            "success": False,
            "error_code": "api_error",
            "detail": f"HTTP {resp.status_code}",
        }

    except requests.exceptions.Timeout:
        return {"success": False, "error_code": "timeout"}
    except requests.exceptions.ConnectionError as e:
        return {"success": False, "error_code": "network_error", "detail": str(e)}
    except Exception as e:
        return {"success": False, "error_code": "unexpected_error", "detail": str(e)}


def process_payment(account_id: str, amount: float, card: dict) -> dict:
    """
    Process a card payment against an account.

    card dict must contain:
        cardholder_name, card_number, cvv, expiry_month, expiry_year

    Returns:
        {
            "success": True,
            "transaction_id": "txn_..."
        }
        OR
        {
            "success": False,
            "error_code": str   # see API Error Codes in spec
        }
    """
    payload = {
        "account_id": account_id,
        "amount": round(float(amount), 2),
        "payment_method": {
            "type": "card",
            "card": {
                "cardholder_name": card["cardholder_name"],
                "card_number": card["card_number"],
                "cvv": card["cvv"],
                "expiry_month": int(card["expiry_month"]),
                "expiry_year": int(card["expiry_year"]),
            },
        },
    }

    try:
        resp = requests.post(
            f"{BASE_URL}/api/process-payment",
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )

        data = resp.json()

        if resp.status_code == 200 and data.get("success"):
            return {"success": True, "transaction_id": data["transaction_id"]}

        # 422 or other failure
        return {
            "success": False,
            "error_code": data.get("error_code", "unknown_error"),
        }

    except requests.exceptions.Timeout:
        return {"success": False, "error_code": "timeout"}
    except requests.exceptions.ConnectionError as e:
        return {"success": False, "error_code": "network_error", "detail": str(e)}
    except Exception as e:
        return {"success": False, "error_code": "unexpected_error", "detail": str(e)}
