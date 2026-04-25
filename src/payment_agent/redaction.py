"""PII / PCI redaction helpers.

Used at two boundaries:
  1. Before any user / assistant turn is appended to ``conversation_history``.
  2. Inside the structlog processor chain, so logs never carry raw PAN or CVV.

We intentionally keep the patterns conservative: we'd rather over-redact a
benign 13–19-digit string than leak a card number into a log.
"""

from __future__ import annotations

import re

# Sequences of 13-19 digits, optionally separated by single spaces or dashes.
_CARD_RE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")

# CVV mentioned with a label like "cvv 123" / "cvc: 4321".
_CVV_LABELED_RE = re.compile(
    r"(?P<label>\b(?:cvv|cvc|cv2|security\s*code)\b\W*)(?P<digits>\d{3,4})\b",
    re.IGNORECASE,
)


def mask_card_number(text: str) -> str:
    """Replace card-number-shaped substrings with ``****<last4>``."""

    def _replace(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19:
            return f"****{digits[-4:]}"
        return match.group(0)

    return _CARD_RE.sub(_replace, text)


def mask_cvv(text: str) -> str:
    """Replace labelled CVV digits with ``***``."""
    return _CVV_LABELED_RE.sub(lambda m: f"{m.group('label')}***", text)


def redact(text: str) -> str:
    """Apply all redaction rules. Idempotent."""
    if not text:
        return text
    return mask_cvv(mask_card_number(text))
