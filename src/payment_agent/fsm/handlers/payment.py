"""PAYMENT_COLLECTION-state handler."""

from __future__ import annotations

import logging

from payment_agent.api_client import PaymentAPIClient
from payment_agent.exceptions import APIError, PaymentDeclinedError
from payment_agent.fsm.machine import BusinessOutcome, Session
from payment_agent.fsm.states import State
from payment_agent.models import CardDetails, ConversationState
from payment_agent.validators import (
    validate_amount,
    validate_card_number,
    validate_cvv,
    validate_expiry,
)

log = logging.getLogger(__name__)

_USER_FIXABLE: dict[str, str] = {
    "invalid_card":          "The card number is invalid. Please re-enter the card number.",
    "invalid_cvv":           "The CVV is incorrect. Please re-enter the CVV.",
    "invalid_expiry":        "The card expiry is invalid or expired. Please re-enter the expiry date.",
    "insufficient_balance":  "The amount exceeds the account balance.",
    "invalid_amount":        "The payment amount is invalid (must be positive, ≤ 2 decimal places).",
}


def handle(session: Session, api: PaymentAPIClient) -> BusinessOutcome:
    if session.account_data is None:
        session.state = State.GREETING
        return BusinessOutcome(code="STATE_INCONSISTENT", instruction="Restart by asking for the account ID.")

    balance = session.account_data.balance
    c = session.collected

    if c.payment_amount is None:
        return BusinessOutcome(
            code="PAYMENT_NEED_AMOUNT",
            instruction=(
                f"The outstanding balance is EXACTLY ₹{balance:.2f} — state this exact figure. "
                f"Ask how much the user wants to pay (any amount up to ₹{balance:.2f}, "
                "or 'pay in full' to pay the entire balance)."
            ),
        )

    # Eagerly validate individual fields as soon as they arrive so we give
    # the user immediate feedback and clear invalid values before asking for
    # the remaining missing fields (including amount > balance).
    early_errors = _early_validate(c, balance=balance)
    if early_errors:
        return BusinessOutcome(
            code="VALIDATION_ERRORS",
            instruction=f"Invalid details — {'; '.join(early_errors)}. Ask the user to correct them.",
            metadata={"errors": early_errors},
        )

    missing = c.card_fields_present()
    if missing:
        return BusinessOutcome(
            code="PAYMENT_NEED_CARD_FIELDS",
            instruction=(
                f"Amount set to ₹{float(c.payment_amount):.2f}. "
                f"Still need: {', '.join(missing)}. Do NOT re-ask for already collected fields."
            ),
        )

    return _validate_and_charge(session, api)


def _early_validate(c: ConversationState, *, balance: float = 0.0) -> list[str]:
    """Validate whichever fields are already present, clear invalid ones, and
    return a list of error messages. Called before checking for completeness."""
    errors: list[str] = []

    if c.payment_amount is not None:
        ok, err = validate_amount(float(c.payment_amount), balance)
        if not ok:
            errors.append(f"Amount: {err}")
            c.payment_amount = None

    if c.card_number is not None:
        ok, err = validate_card_number(str(c.card_number))
        if not ok:
            errors.append(f"Card number: {err}")
            c.card_number = None

    if c.cvv is not None:
        ok, err = validate_cvv(str(c.cvv), str(c.card_number) if c.card_number else "")
        if not ok:
            errors.append(f"CVV: {err}")
            c.cvv = None

    if c.expiry_month is not None and c.expiry_year is not None:
        ok, err = validate_expiry(int(c.expiry_month), int(c.expiry_year))
        if not ok:
            errors.append(f"Expiry: {err}")
            c.expiry_month = None
            c.expiry_year = None

    return errors


def _validate_and_charge(session: Session, api: PaymentAPIClient) -> BusinessOutcome:
    c = session.collected
    balance = session.account_data.balance  # type: ignore[union-attr]
    errors: list[str] = []

    amount = float(c.payment_amount)  # type: ignore[arg-type]
    ok, err = validate_amount(amount, balance)
    if not ok:
        errors.append(f"Amount: {err}")
        c.payment_amount = None

    card_number = str(c.card_number)
    ok, err = validate_card_number(card_number)
    if not ok:
        errors.append(f"Card number: {err}")
        c.card_number = None

    cvv = str(c.cvv)
    ok, err = validate_cvv(cvv, card_number if c.card_number else "")
    if not ok:
        errors.append(f"CVV: {err}")
        c.cvv = None

    ok, err = validate_expiry(int(c.expiry_month), int(c.expiry_year))  # type: ignore[arg-type]
    if not ok:
        errors.append(f"Expiry: {err}")
        c.expiry_month = None
        c.expiry_year = None

    if errors:
        return BusinessOutcome(
            code="VALIDATION_ERRORS",
            instruction=f"Invalid details — {'; '.join(errors)}. Ask the user to correct them.",
            metadata={"errors": errors},
        )

    card = CardDetails(
        cardholder_name=c.cardholder_name,  # type: ignore[arg-type]
        card_number=card_number,
        cvv=cvv,
        expiry_month=int(c.expiry_month),  # type: ignore[arg-type]
        expiry_year=int(c.expiry_year),    # type: ignore[arg-type]
    )

    try:
        txn_id = api.process_payment(
            account_id=session.account_id,  # type: ignore[arg-type]
            amount=amount,
            card=card,
        )
    except PaymentDeclinedError as exc:
        c.wipe_card_data()
        if exc.error_code in _USER_FIXABLE:
            _clear_declined_field(session, exc.error_code)
            msg = _USER_FIXABLE[exc.error_code]
            if exc.error_code == "insufficient_balance":
                msg += f" Outstanding balance: ₹{balance:.2f}."
            return BusinessOutcome(
                code="PAYMENT_FAILED_RETRYABLE",
                instruction=f"{msg} Ask the user to correct it and try again.",
                metadata={"error_code": exc.error_code},
            )
        session.state = State.FAILED
        return BusinessOutcome(
            code="PAYMENT_FAILED_TERMINAL",
            instruction=f"Payment failed unexpectedly ({exc.error_code}). Apologise and direct user to support.",
            metadata={"error_code": exc.error_code},
        )
    except APIError as exc:
        log.error("payment api error: %s", exc)
        c.wipe_card_data()
        session.state = State.FAILED
        return BusinessOutcome(
            code="PAYMENT_FAILED_TERMINAL",
            instruction="System error during payment. Apologise and direct user to support.",
        )

    c.wipe_card_data()
    session.state = State.DONE
    session.payment_result = {"success": True, "transaction_id": txn_id}
    return BusinessOutcome(
        code="PAYMENT_SUCCESS",
        instruction=(
            f"Payment of ₹{amount:.2f} succeeded. Transaction ID: {txn_id}. "
            "Congratulate the user, share the full transaction ID, and close gracefully."
        ),
        metadata={"transaction_id": txn_id, "amount": amount},
    )


def _clear_declined_field(session: Session, error_code: str) -> None:
    c = session.collected
    if error_code == "invalid_card":
        c.card_number = None
    elif error_code == "invalid_cvv":
        c.cvv = None
    elif error_code == "invalid_expiry":
        c.expiry_month = None
        c.expiry_year = None
    elif error_code in ("insufficient_balance", "invalid_amount"):
        c.payment_amount = None
