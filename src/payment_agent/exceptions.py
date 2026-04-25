"""Exception taxonomy for the payment agent.

Using typed exceptions instead of magic strings lets each FSM handler signal
its outcome unambiguously and keeps the responder decoupled from the
business-logic layer.
"""

from __future__ import annotations


class PaymentAgentError(Exception):
    """Base for all payment-agent errors."""


class APIError(PaymentAgentError):
    """Raised when the upstream payment API returns an unexpected response."""


class APITimeoutError(APIError):
    """Network operation timed out (retryable)."""


class APINetworkError(APIError):
    """Connection-level failure (retryable)."""


class AccountNotFoundError(APIError):
    """Account lookup returned 404."""

    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        super().__init__(f"Account '{account_id}' not found")


class PaymentDeclinedError(APIError):
    """Payment API returned a structured decline.

    Attributes:
        error_code: One of the known API error codes
            (``invalid_card``, ``invalid_cvv``, ``invalid_expiry``,
            ``insufficient_balance``, ``invalid_amount``, ``account_not_found``).
    """

    def __init__(self, error_code: str, message: str | None = None) -> None:
        self.error_code = error_code
        super().__init__(message or f"Payment declined: {error_code}")


class VerificationError(PaymentAgentError):
    """Internal signal that verification cannot proceed (e.g. malformed input)."""
