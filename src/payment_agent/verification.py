"""Identity verification logic.

Per spec:
  * Full name must match **exactly** (case-sensitive after .strip()).
  * At least one of DOB / Aadhaar last 4 / pincode must additionally match.
  * No fuzzy matching anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

from payment_agent.models import Account, ConversationState
from payment_agent.validators import validate_date


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of a single verification attempt."""

    passed: bool
    name_matched: bool
    secondary_matched: bool
    invalid_dob_reason: str | None = None  # set if DOB present but not parseable


def _name_matches(provided: str, on_file: str) -> bool:
    return provided.strip() == on_file.strip()


def attempt_verification(state: ConversationState, account: Account) -> VerificationResult:
    """Evaluate whether the data in ``state`` verifies against ``account``.

    The caller is responsible for retry counting and state transitions; this
    function simply reports what it found. If the user supplied a DOB whose
    *format* is invalid, ``invalid_dob_reason`` is populated and the caller
    should treat this as a re-prompt rather than a failed attempt.
    """
    name_matched = bool(state.full_name) and _name_matches(state.full_name, account.full_name)

    invalid_dob_reason: str | None = None
    secondary_matched = False

    if state.dob:
        dob_valid, dob_err = validate_date(state.dob)
        if not dob_valid:
            invalid_dob_reason = dob_err
        elif state.dob == account.dob:
            secondary_matched = True

    if not secondary_matched and state.aadhaar_last4:
        if str(state.aadhaar_last4) == str(account.aadhaar_last4):
            secondary_matched = True

    if not secondary_matched and state.pincode:
        if str(state.pincode) == str(account.pincode):
            secondary_matched = True

    return VerificationResult(
        passed=name_matched and secondary_matched,
        name_matched=name_matched,
        secondary_matched=secondary_matched,
        invalid_dob_reason=invalid_dob_reason,
    )
