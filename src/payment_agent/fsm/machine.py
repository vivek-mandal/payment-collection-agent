"""State-machine dispatcher.

Holds the mutable session state and routes each turn to the correct
per-state handler.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from payment_agent.api_client import PaymentAPIClient
from payment_agent.config import Settings, get_settings
from payment_agent.fsm.states import State
from payment_agent.models import Account, ConversationState


@dataclass
class BusinessOutcome:
    """Result of one FSM step.

    code        — stable machine-readable identifier
    instruction — plain-English guidance for the response generator
    metadata    — optional structured data (balance, transaction_id, ...)
    """

    code: str
    instruction: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Session:
    """All mutable per-conversation state."""

    state: State = State.GREETING
    account_id: str | None = None
    account_data: Account | None = None
    verified: bool = False
    verification_attempts: int = 0
    last_verification_snapshot: tuple[str | None, ...] | None = None
    collected: ConversationState = field(default_factory=ConversationState)
    payment_result: dict[str, Any] | None = None


class StateMachine:
    """Deterministic dispatcher — no LLM calls, no side effects outside of API."""

    def __init__(self, api: PaymentAPIClient, settings: Settings | None = None) -> None:
        self._api = api
        self._cfg = settings or get_settings()
        self.session = Session()

    @property
    def state(self) -> State:
        return self.session.state

    def is_terminal(self) -> bool:
        return self.session.state in (State.DONE, State.FAILED)

    def advance(self) -> BusinessOutcome:
        from payment_agent.fsm.handlers import greeting, payment, verification

        if self.session.state == State.GREETING:
            return greeting.handle(self.session, self._api)
        if self.session.state == State.VERIFICATION:
            return verification.handle(self.session, self._cfg)
        if self.session.state == State.PAYMENT_COLLECTION:
            return payment.handle(self.session, self._api)

        return BusinessOutcome(
            code="TERMINAL",
            instruction="Session is closed. Inform the user politely.",
        )
