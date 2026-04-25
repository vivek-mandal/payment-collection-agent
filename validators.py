"""
validators.py — Pure Python validation logic.
No LLM, no API calls. All checks are deterministic.
"""

import datetime
from typing import Tuple


# ---------------------------------------------------------------------------
# Card Number
# ---------------------------------------------------------------------------

def luhn_check(card_number: str) -> bool:
    """Return True if card_number passes the Luhn algorithm."""
    digits = [int(d) for d in card_number if d.isdigit()]
    if not (13 <= len(digits) <= 19):
        return False
    total = 0
    for i, digit in enumerate(reversed(digits)):
        if i % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def validate_card_number(card_number: str) -> Tuple[bool, str]:
    """
    Returns (is_valid, error_message).
    Strips spaces and dashes before checking.
    """
    cleaned = card_number.replace(" ", "").replace("-", "")

    if not cleaned.isdigit():
        return False, "Card number must contain only digits."

    if not (13 <= len(cleaned) <= 19):
        return False, f"Card number must be 13–19 digits (got {len(cleaned)})."

    if not luhn_check(cleaned):
        return False, "Card number is invalid (failed Luhn check)."

    return True, ""


# ---------------------------------------------------------------------------
# CVV
# ---------------------------------------------------------------------------

def validate_cvv(cvv: str, card_number: str = "") -> Tuple[bool, str]:
    """
    Returns (is_valid, error_message).
    Amex (starts 34/37) requires 4 digits; all others require 3.
    """
    if not cvv.isdigit():
        return False, "CVV must contain only digits."

    cleaned_card = card_number.replace(" ", "").replace("-", "")
    is_amex = cleaned_card.startswith(("34", "37"))
    expected_len = 4 if is_amex else 3

    if len(cvv) != expected_len:
        return False, f"CVV must be {expected_len} digits for this card type (got {len(cvv)})."

    return True, ""


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------

def validate_expiry(month: int, year: int) -> Tuple[bool, str]:
    """
    Returns (is_valid, error_message).
    Card is valid through the last day of the expiry month.
    """
    if not (1 <= month <= 12):
        return False, "Expiry month must be between 1 and 12."

    if not (2000 <= year <= 2099):
        return False, f"Expiry year '{year}' is not valid."

    # Last day of expiry month
    if month == 12:
        last_day = datetime.date(year, 12, 31)
    else:
        last_day = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

    if last_day < datetime.date.today():
        return False, f"Card expired on {last_day.strftime('%m/%Y')}."

    return True, ""


# ---------------------------------------------------------------------------
# Amount
# ---------------------------------------------------------------------------

def validate_amount(amount: float, balance: float) -> Tuple[bool, str]:
    """
    Returns (is_valid, error_message).
    Amount must be > 0, ≤ balance, and have at most 2 decimal places.
    """
    if amount <= 0:
        return False, "Payment amount must be greater than ₹0."

    # Check max 2 decimal places: multiply by 100 and check for remainder
    amount_cents = amount * 100
    if abs(amount_cents - round(amount_cents)) > 1e-9:
        return False, "Amount can have at most 2 decimal places."

    if amount > balance + 1e-9:  # tiny epsilon for float safety
        return False, f"Amount ₹{amount:.2f} exceeds outstanding balance of ₹{balance:.2f}."

    return True, ""


# ---------------------------------------------------------------------------
# Date
# ---------------------------------------------------------------------------

def validate_date(date_str: str) -> Tuple[bool, str]:
    """
    Validate a YYYY-MM-DD date string, including leap year correctness.
    Returns (is_valid, error_message).
    """
    if not isinstance(date_str, str):
        return False, "Date must be a string in YYYY-MM-DD format."

    parts = date_str.strip().split("-")
    if len(parts) != 3:
        return False, "Date must be in YYYY-MM-DD format (e.g. 1990-05-14)."

    try:
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        datetime.date(year, month, day)  # raises ValueError for invalid dates
        return True, ""
    except ValueError as exc:
        return False, f"Invalid date: {exc}."
