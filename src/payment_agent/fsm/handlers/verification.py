"""VERIFICATION-state handler."""

from __future__ import annotations

import logging

from payment_agent.config import Settings
from payment_agent.fsm.machine import BusinessOutcome, Session
from payment_agent.fsm.states import State
from payment_agent.verification import attempt_verification

log = logging.getLogger(__name__)


def _snapshot(session: Session) -> tuple[str | None, ...]:
    c = session.collected
    return (c.full_name, c.dob, c.aadhaar_last4, c.pincode)


def handle(session: Session, settings: Settings) -> BusinessOutcome:
    if session.account_data is None:
        session.state = State.GREETING
        return BusinessOutcome(
            code="STATE_INCONSISTENT",
            instruction="Restart by asking for the account ID.",
        )

    has_name = bool(session.collected.full_name)
    has_secondary = any(
        getattr(session.collected, k) for k in ("dob", "aadhaar_last4", "pincode")
    )

    if not has_name:
        return BusinessOutcome(
            code="VERIFICATION_NEED_NAME",
            instruction=(
                "Ask for the user's full name and one of: date of birth (YYYY-MM-DD), "
                "Aadhaar last 4, or pincode."
            ),
        )

    if not has_secondary:
        return BusinessOutcome(
            code="VERIFICATION_NEED_SECONDARY",
            instruction=(
                f"Full name '{session.collected.full_name}' received. "
                "Now ask for one of: DOB (YYYY-MM-DD), Aadhaar last 4, or pincode."
            ),
        )

    snap = _snapshot(session)
    if snap == session.last_verification_snapshot:
        remaining = settings.max_verification_attempts - session.verification_attempts
        return BusinessOutcome(
            code="VERIFICATION_REPEAT_DATA",
            instruction=(
                f"User repeated the same data that already failed. "
                f"Ask them to provide corrected information. {remaining} attempt(s) remaining."
            ),
        )
    session.last_verification_snapshot = snap

    result = attempt_verification(session.collected, session.account_data)

    # Malformed date — clear it and re-prompt without burning an attempt.
    # Also clear the name so the user can re-submit everything cleanly.
    if result.invalid_dob_reason:
        session.collected.dob = None
        session.collected.full_name = None
        return BusinessOutcome(
            code="INVALID_DATE_FORMAT",
            instruction=(
                f"DOB is invalid ({result.invalid_dob_reason}). "
                "Ask the user to re-enter their full name and a valid date of birth "
                "in YYYY-MM-DD format (or Aadhaar last 4 / pincode instead)."
            ),
        )

    if result.passed:
        session.verified = True
        balance = session.account_data.balance

        if balance == 0:
            session.state = State.DONE
            return BusinessOutcome(
                code="VERIFICATION_SUCCESS_ZERO_BALANCE",
                instruction=(
                    "Identity verified. Balance is ₹0.00 — nothing owed. "
                    "Inform the user and close gracefully."
                ),
            )

        session.state = State.PAYMENT_COLLECTION
        return BusinessOutcome(
            code="VERIFICATION_SUCCESS",
            instruction=(
                f"Identity verified. The outstanding balance is EXACTLY ₹{balance:.2f} "
                f"— you MUST state this exact figure to the user, do not round or change it. "
                f"Ask how much they want to pay today (any amount from ₹0.01 up to ₹{balance:.2f}, "
                "or they may say 'pay in full' to pay the entire balance)."
            ),
            metadata={"balance": balance},
        )

    # Failed — consume an attempt, then clear the collected fields so the user
    # can submit fresh values next turn (merge() won't overwrite non-None values).
    session.verification_attempts += 1
    _clear_verification_fields(session, name_failed=not result.name_matched)

    if session.verification_attempts >= settings.max_verification_attempts:
        session.state = State.FAILED
        return BusinessOutcome(
            code="VERIFICATION_FAILED_TERMINAL",
            instruction=(
                "Max verification attempts reached. Tell the user the session is closed "
                "for security reasons and to contact customer support. "
                "Do NOT reveal which field was wrong or its correct value."
            ),
        )

    remaining = settings.max_verification_attempts - session.verification_attempts

    if not result.name_matched:
        return BusinessOutcome(
            code="VERIFICATION_FAILED_NAME",
            instruction=(
                f"Name does not match. {remaining} attempt(s) remaining. "
                "Ask user to re-enter their full name exactly as registered. "
                "Do NOT reveal the correct name."
            ),
        )

    return BusinessOutcome(
        code="VERIFICATION_FAILED_SECONDARY",
        instruction=(
            f"Name matched but secondary factor did not. {remaining} attempt(s) remaining. "
            "Ask user to try a different secondary factor (DOB / Aadhaar last 4 / pincode). "
            "Do NOT reveal correct values."
        ),
    )


def _clear_verification_fields(session: Session, *, name_failed: bool) -> None:
    """Clear collected identity fields after a failed attempt so the user
    can re-enter them. Always clear secondary factors. Clear name only if
    it was the name that failed (so a correct name isn't thrown away when
    only the secondary factor was wrong)."""
    session.collected.dob = None
    session.collected.aadhaar_last4 = None
    session.collected.pincode = None
    if name_failed:
        session.collected.full_name = None
