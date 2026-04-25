"""Public Agent class — thin orchestrator over the FSM, extractor, responder.

Per-turn lifecycle:
    1. Redact + log user input
    2. FieldExtractor  → ExtractedFields   (LLM #1, temp=0, JSON)
    3. Merge into ConversationState
    4. StateMachine.advance()              (deterministic; may call API)
    5. ResponseGenerator.render()          (LLM #2, temp=0.3, plain text)
    6. Return {"message": str}
"""

from __future__ import annotations

import logging
from typing import Any

from openai import AzureOpenAI, OpenAI

from payment_agent.api_client import PaymentAPIClient
from payment_agent.config import Settings, get_settings
from payment_agent.fsm.machine import StateMachine
from payment_agent.fsm.states import State
from payment_agent.llm import FieldExtractor, ResponseGenerator, build_llm_client
from payment_agent.models import ExtractedFields
from payment_agent.redaction import redact

log = logging.getLogger(__name__)


class Agent:
    """Conversational payment-collection agent.

    Usage::

        agent = Agent()
        result = agent.next("user message")  # → {"message": str}

    All state is held internally. No setup between turns.
    """

    def __init__(
        self,
        *,
        llm: AzureOpenAI | OpenAI | None = None,
        api: PaymentAPIClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._cfg = settings or get_settings()
        _llm = llm or build_llm_client(self._cfg)
        self._api = api or PaymentAPIClient(self._cfg)
        self._extractor = FieldExtractor(_llm, self._cfg)
        self._responder = ResponseGenerator(_llm, self._cfg)
        self._fsm = StateMachine(self._api, self._cfg)
        self._history: list[dict[str, str]] = []

    # ------------------------------------------------------------------
    # Public interface (per spec)
    # ------------------------------------------------------------------

    def next(self, user_input: str) -> dict[str, str]:
        if self._fsm.is_terminal():
            return {
                "message": (
                    "This session has ended. Please start a new conversation "
                    "if you need further assistance."
                )
            }

        redacted = redact(user_input)
        self._history.append({"role": "user", "content": redacted})
        log.info("[%s] user: %s", self._fsm.state.value, redacted)

        last_agent_msg = next(
            (m["content"] for m in reversed(self._history) if m["role"] == "assistant"),
            None,
        )
        extracted = self._extractor.extract(
            user_input,
            state=self._fsm.state.value,
            last_agent_message=last_agent_msg,
        )
        self._merge_extracted(extracted)

        outcome = self._fsm.advance()
        log.info("[%s] outcome: %s", self._fsm.state.value, outcome.code)

        message = self._responder.render(
            state=self._fsm.state.value,
            account_id=self._fsm.session.account_id,
            verified=self._fsm.session.verified,
            attempts_used=self._fsm.session.verification_attempts,
            collected=self._fsm.session.collected,
            outcome=outcome.instruction,
            history=self._history,
        )

        self._history.append({"role": "assistant", "content": redact(message)})
        return {"message": message}

    # ------------------------------------------------------------------
    # Read-only views used by tests
    # ------------------------------------------------------------------

    @property
    def state(self) -> State:
        return self._fsm.state

    @state.setter
    def state(self, value: State) -> None:
        """Fast-forward state — for tests only."""
        self._fsm.session.state = value

    @property
    def verified(self) -> bool:
        return self._fsm.session.verified

    @property
    def verification_attempts(self) -> int:
        return self._fsm.session.verification_attempts

    @property
    def account_id(self) -> str | None:
        return self._fsm.session.account_id

    @property
    def account_data(self) -> dict[str, Any] | None:
        acct = self._fsm.session.account_data
        return acct.model_dump() if acct else None

    @property
    def collected(self) -> dict[str, Any]:
        return self._fsm.session.collected.model_dump()

    @property
    def payment_result(self) -> dict[str, Any] | None:
        return self._fsm.session.payment_result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _merge_extracted(self, extracted: ExtractedFields) -> None:
        if extracted.account_id and not self._fsm.session.account_id:
            self._fsm.session.account_id = str(extracted.account_id).strip()

        # Resolve "pay in full" → balance amount
        if (
            extracted.pay_in_full
            and self._fsm.session.account_data is not None
            and self._fsm.session.collected.payment_amount is None
        ):
            extracted.payment_amount = self._fsm.session.account_data.balance

        self._fsm.session.collected.merge(extracted)
