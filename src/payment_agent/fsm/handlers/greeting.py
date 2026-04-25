"""GREETING-state handler."""

from __future__ import annotations

import logging

from payment_agent.api_client import PaymentAPIClient
from payment_agent.exceptions import AccountNotFoundError, APIError
from payment_agent.fsm.machine import BusinessOutcome, Session
from payment_agent.fsm.states import State

log = logging.getLogger(__name__)


def handle(session: Session, api: PaymentAPIClient) -> BusinessOutcome:
    if not session.account_id:
        return BusinessOutcome(
            code="GREETING_NEED_ACCOUNT_ID",
            instruction="Greet the user and ask for their account ID.",
        )

    try:
        account = api.lookup_account(session.account_id)
    except AccountNotFoundError:
        bad_id = session.account_id
        session.account_id = None
        return BusinessOutcome(
            code="ACCOUNT_NOT_FOUND",
            instruction=(
                "No account exists for the ID provided. Politely inform the user "
                "and ask them to double-check their account ID."
            ),
            metadata={"attempted_id": bad_id},
        )
    except APIError as exc:
        log.error("greeting api error: %s", exc)
        session.account_id = None
        return BusinessOutcome(
            code="SYSTEM_ERROR",
            instruction=(
                "Could not reach the account service. Apologise and ask the user "
                "to try again in a moment."
            ),
        )

    session.account_data = account
    session.state = State.VERIFICATION
    return BusinessOutcome(
        code="ACCOUNT_FOUND",
        instruction=(
            "Account found. Ask for the user's full name AND at least one of: "
            "date of birth (YYYY-MM-DD), last 4 Aadhaar digits, or pincode. "
            "Do NOT reveal account data or balance yet."
        ),
    )
