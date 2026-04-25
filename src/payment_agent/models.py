"""Pydantic domain models.

These types are the boundary between modules. The extractor returns
:class:`ExtractedFields`; the FSM operates on :class:`ConversationState`;
the API client returns :class:`Account` and accepts :class:`CardDetails`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Account(BaseModel):
    """The shape of a successful ``/api/lookup-account`` response."""

    account_id: str
    full_name: str
    dob: str
    aadhaar_last4: str
    pincode: str
    balance: float

    model_config = ConfigDict(extra="ignore")


class CardDetails(BaseModel):
    """Card details for ``/api/process-payment``."""

    cardholder_name: str
    card_number: str
    cvv: str
    expiry_month: int = Field(ge=1, le=12)
    expiry_year: int = Field(ge=2000, le=2099)


class ExtractedFields(BaseModel):
    """Structured output from the extraction LLM call.

    Every field is optional — the extractor returns ``None`` for anything
    not explicitly present in the user's message.
    """

    account_id: str | None = None
    full_name: str | None = None
    dob: str | None = None
    aadhaar_last4: str | None = None
    pincode: str | None = None
    payment_amount: float | None = None
    pay_in_full: bool | None = None
    card_number: str | None = None
    cvv: str | None = None
    expiry_month: int | None = None
    expiry_year: int | None = None
    cardholder_name: str | None = None

    model_config = ConfigDict(extra="ignore")


class ConversationState(BaseModel):
    """All user-supplied data, accumulated across turns.

    The state machine reads and writes this; it never calls the LLM directly.
    """

    full_name: str | None = None
    dob: str | None = None
    aadhaar_last4: str | None = None
    pincode: str | None = None
    payment_amount: float | None = None
    card_number: str | None = None
    cvv: str | None = None
    expiry_month: int | None = None
    expiry_year: int | None = None
    cardholder_name: str | None = None

    def merge(self, fields: ExtractedFields) -> None:
        """Merge extracted fields into state.

        Rules:
        - Never overwrite a known value with None (extractor returning null
          means "not mentioned", not "user cleared it").
        - Identity fields (name, dob, aadhaar, pincode) ARE overwritten when
          the user provides a new value — they may be correcting a mistake.
        - Payment/card fields are sticky once set (user shouldn't re-enter
          card details just because they mentioned something else).
        """
        _sticky = {"payment_amount", "card_number", "cvv", "expiry_month",
                   "expiry_year", "cardholder_name"}

        for key, value in fields.model_dump(exclude_none=True).items():
            if not hasattr(self, key):
                continue
            normalized = self._normalize(key, value)
            if normalized is None:
                continue
            # For sticky fields, only set if not already known
            if key in _sticky and getattr(self, key) is not None:
                continue
            setattr(self, key, normalized)

    @staticmethod
    def _normalize(key: str, value: Any) -> Any:
        """Field-specific coercion — silently rejects bad shapes by returning None."""
        try:
            if key == "aadhaar_last4":
                cleaned = str(value).strip()
                return cleaned if cleaned.isdigit() and len(cleaned) == 4 else None
            if key == "pincode":
                return str(value).strip() or None
            if key == "payment_amount":
                return float(value)
            if key in ("expiry_month", "expiry_year"):
                return int(value)
            if key == "card_number":
                return str(value).replace(" ", "").replace("-", "")
            if key == "cvv":
                return str(value).strip()
            if key == "dob":
                return str(value).strip()
            if key in ("full_name", "cardholder_name"):
                return str(value).strip() or None
            return value
        except (TypeError, ValueError):
            return None

    def card_fields_present(self) -> list[str]:
        """Return human-readable names of card fields still missing."""
        missing: list[str] = []
        if not self.card_number:
            missing.append("card number")
        if not self.cardholder_name:
            missing.append("cardholder name (as it appears on the card)")
        if not self.cvv:
            missing.append("CVV")
        if not self.expiry_month or not self.expiry_year:
            missing.append("card expiry (month and year)")
        return missing

    def safe_summary(self) -> dict[str, Any]:
        """Render a redaction-safe snapshot for inclusion in LLM prompts."""
        out: dict[str, Any] = {}
        for key, value in self.model_dump(exclude_none=True).items():
            if key == "card_number":
                out[key] = f"****{str(value)[-4:]}"
            elif key == "cvv":
                out[key] = "***"
            else:
                out[key] = value
        return out

    def wipe_card_data(self) -> None:
        """Wipe sensitive card fields after a payment attempt completes."""
        self.card_number = None
        self.cvv = None
