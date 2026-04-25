"""Conversation state enum."""

from __future__ import annotations

from enum import Enum


class State(str, Enum):
    """High-level conversation phases.

    Inheriting from ``str`` makes ``state.value`` JSON-serializable for
    free, which is convenient for logs and prompt templating.
    """

    GREETING = "greeting"
    VERIFICATION = "verification"
    PAYMENT_COLLECTION = "payment_collection"
    DONE = "done"
    FAILED = "failed"
