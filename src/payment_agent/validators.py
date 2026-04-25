"""Pure validation functions.

No side effects, no I/O, no LLM. Every public function returns
``(is_valid, error_message)`` so the caller can surface a precise reason.
"""

from __future__ import annotations

import datetime


def luhn_check(card_number: str) -> bool:
    """Return True if ``card_number`` passes the Luhn algorithm."""
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


def validate_card_number(card_number: str) -> tuple[bool, str]:
    """Reject anything that isn't a Luhn-valid 13–19-digit string."""
    cleaned = card_number.replace(" ", "").replace("-", "")

    if not cleaned.isdigit():
        return False, "Card number must contain only digits."
    if not (13 <= len(cleaned) <= 19):
        return False, f"Card number must be 13–19 digits (got {len(cleaned)})."
    if not luhn_check(cleaned):
        return False, "Card number is invalid (failed Luhn check)."
    return True, ""


def validate_cvv(cvv: str, card_number: str = "") -> tuple[bool, str]:
    """Amex (BIN starts 34/37) requires 4 digits; everyone else requires 3."""
    if not cvv.isdigit():
        return False, "CVV must contain only digits."

    cleaned_card = card_number.replace(" ", "").replace("-", "")
    is_amex = cleaned_card.startswith(("34", "37"))
    expected_len = 4 if is_amex else 3

    if len(cvv) != expected_len:
        return False, f"CVV must be {expected_len} digits for this card type (got {len(cvv)})."
    return True, ""


def validate_expiry(month: int, year: int) -> tuple[bool, str]:
    """A card is valid through the last day of its expiry month."""
    if not (1 <= month <= 12):
        return False, "Expiry month must be between 1 and 12."
    if not (2000 <= year <= 2099):
        return False, f"Expiry year '{year}' is not valid."

    if month == 12:
        last_day = datetime.date(year, 12, 31)
    else:
        last_day = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

    if last_day < datetime.date.today():
        return False, f"Card expired on {last_day.strftime('%m/%Y')}."
    return True, ""


def validate_amount(amount: float, balance: float) -> tuple[bool, str]:
    """Amount must be > 0, ≤ balance, and have at most 2 decimal places."""
    if amount <= 0:
        return False, "Payment amount must be greater than ₹0."

    amount_cents = amount * 100
    if abs(amount_cents - round(amount_cents)) > 1e-9:
        return False, "Amount can have at most 2 decimal places."

    if amount > balance + 1e-9:
        return False, f"Amount ₹{amount:.2f} exceeds outstanding balance of ₹{balance:.2f}."
    return True, ""


def validate_date(date_str: str) -> tuple[bool, str]:
    """Validate a YYYY-MM-DD date including leap-year correctness."""
    if not isinstance(date_str, str):
        return False, "Date must be a string in YYYY-MM-DD format."

    parts = date_str.strip().split("-")
    if len(parts) != 3:
        return False, "Date must be in YYYY-MM-DD format (e.g. 1990-05-14)."

    try:
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        datetime.date(year, month, day)
    except ValueError as exc:
        return False, f"Invalid date: {exc}."
    return True, ""
