"""
agent.py — Production-ready payment collection AI agent.

Architecture: Hybrid LLM + deterministic state machine.
  - LLM (GPT-4o on Azure): extracts structured data from natural language,
    generates conversational responses.
  - Python state machine: drives flow, runs verification, calls APIs,
    enforces all business rules — no LLM involvement in pass/fail decisions.

State flow:
    GREETING → VERIFICATION → PAYMENT_COLLECTION → DONE
                                                  → FAILED (terminal)
"""

import json
import os
from enum import Enum
from typing import Optional

from openai import AzureOpenAI

from tools import lookup_account, process_payment
from validators import (
    luhn_check,
    validate_amount,
    validate_card_number,
    validate_cvv,
    validate_date,
    validate_expiry,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_VERIFICATION_ATTEMPTS = 3

# Fields we never show the user (pulled from account data for internal comparison only)
PRIVATE_ACCOUNT_FIELDS = {"dob", "aadhaar_last4", "pincode"}


# ---------------------------------------------------------------------------
# State enum
# ---------------------------------------------------------------------------

class State(Enum):
    GREETING = "greeting"
    VERIFICATION = "verification"
    PAYMENT_COLLECTION = "payment_collection"
    DONE = "done"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class Agent:
    """
    Conversational payment collection agent.

    Public interface:
        agent = Agent()
        result = agent.next("user message")   # → {"message": str}
    """

    def __init__(self):
        self.client = AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version="2024-05-01-preview",
        )
        self.deployment: str = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")
        self._reset_state()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def next(self, user_input: str) -> dict:
        """
        Process one turn of the conversation.

        Args:
            user_input: The user's raw message string.

        Returns:
            {"message": str}
        """
        # Terminal: do not process anything further
        if self.state in (State.DONE, State.FAILED):
            return {
                "message": (
                    "This session has ended. "
                    "Please start a new conversation if you need further assistance."
                )
            }

        # Record user turn
        self.conversation_history.append({"role": "user", "content": user_input})

        # Phase 1 — Extract structured data from user's message (LLM, temp=0)
        extracted = self._extract_data(user_input)

        # Phase 2 — Merge extracted data into collected state
        self._update_collected(extracted)

        # Phase 3 — Run state machine: API calls, verification, validation
        business_context = self._run_state_machine()

        # Phase 4 — Generate natural language response (LLM)
        message = self._generate_response(business_context)

        # Record assistant turn
        self.conversation_history.append({"role": "assistant", "content": message})

        return {"message": message}

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def _reset_state(self):
        self.state: State = State.GREETING
        self.account_id: Optional[str] = None
        self.account_data: Optional[dict] = None       # PRIVATE — never send to user

        self.verified: bool = False
        self.verification_attempts: int = 0
        self._last_verification_snapshot: Optional[dict] = None  # prevents double-counting

        # Accumulated user-provided data
        self.collected: dict = {
            "full_name": None,
            "dob": None,
            "aadhaar_last4": None,
            "pincode": None,
            "payment_amount": None,
            "card_number": None,
            "cvv": None,
            "expiry_month": None,
            "expiry_year": None,
            "cardholder_name": None,
        }

        self.payment_result: Optional[dict] = None
        self.conversation_history: list = []

    # ------------------------------------------------------------------
    # Phase 1 — LLM extraction
    # ------------------------------------------------------------------

    def _extract_data(self, user_input: str) -> dict:
        """
        One focused LLM call: extract structured fields from the user's message.
        Returns a dict; any field not found in the message is None.
        """
        system = (
            "You are a data extraction assistant. "
            "Extract the following fields from the user's message and return ONLY valid JSON. "
            "Use null for any field not explicitly present — do NOT infer or guess.\n\n"
            "{\n"
            '  "account_id":      null,  // Account identifier, e.g. "ACC1001"\n'
            '  "full_name":       null,  // Full name exactly as stated\n'
            '  "dob":             null,  // Date of birth — normalize to YYYY-MM-DD\n'
            '  "aadhaar_last4":   null,  // Last 4 digits of Aadhaar (string, exactly 4 digits)\n'
            '  "pincode":         null,  // 6-digit postal code (string)\n'
            '  "payment_amount":  null,  // Numeric rupee amount (float)\n'
            '  "card_number":     null,  // Card digits, strip spaces/dashes\n'
            '  "cvv":             null,  // CVV digits (string)\n'
            '  "expiry_month":    null,  // Expiry month as integer 1–12\n'
            '  "expiry_year":     null,  // Expiry year as 4-digit integer\n'
            '  "cardholder_name": null   // Name as it appears on the card\n'
            "}"
        )

        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_input},
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=400,
            )
            return json.loads(response.choices[0].message.content)
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Phase 2 — Merge into collected state
    # ------------------------------------------------------------------

    def _update_collected(self, extracted: dict):
        """Merge extracted data. Never overwrite an existing value with None."""
        # Account ID lives outside collected
        if extracted.get("account_id") and not self.account_id:
            self.account_id = str(extracted["account_id"]).strip()

        for key in self.collected:
            value = extracted.get(key)
            if value is None:
                continue

            # Type coercions for safety
            if key == "aadhaar_last4":
                value = str(value).strip().zfill(4)[:4]  # keep as 4-char string
            elif key == "pincode":
                value = str(value).strip()
            elif key == "payment_amount":
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue
            elif key in ("expiry_month", "expiry_year"):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            elif key == "card_number":
                value = str(value).replace(" ", "").replace("-", "")
            elif key == "cvv":
                value = str(value).strip()

            self.collected[key] = value

    # ------------------------------------------------------------------
    # Phase 3 — State machine
    # ------------------------------------------------------------------

    def _run_state_machine(self) -> str:
        """
        Execute business logic for the current state.
        May transition state, call APIs, run verification.
        Returns a context string describing what happened — used by _generate_response.
        """
        if self.state == State.GREETING:
            return self._sm_greeting()

        if self.state == State.VERIFICATION:
            return self._sm_verification()

        if self.state == State.PAYMENT_COLLECTION:
            return self._sm_payment_collection()

        return "Session is in terminal state."

    # --- GREETING ---

    def _sm_greeting(self) -> str:
        if not self.account_id:
            return "ACTION: Greet the user and ask for their account ID."

        # Account ID just arrived — look it up immediately
        result = lookup_account(self.account_id)

        if result["success"]:
            self.account_data = result["data"]
            self.state = State.VERIFICATION
            return (
                f"ACCOUNT_FOUND: Account '{self.account_id}' exists. "
                "Transition to identity verification. "
                "Ask for the user's full name AND at least one of: "
                "date of birth (YYYY-MM-DD), last 4 digits of Aadhaar, or pincode. "
                "Do NOT reveal any account data or the balance yet."
            )

        if result["error_code"] == "account_not_found":
            self.account_id = None  # let user retry
            return (
                "ACCOUNT_NOT_FOUND: No account found for that ID. "
                "Politely inform the user and ask them to double-check their account ID."
            )

        # Network/API error
        self.account_id = None
        return (
            f"SYSTEM_ERROR: Could not reach account service "
            f"({result.get('error_code', 'unknown')}). "
            "Apologise and ask the user to try again in a moment."
        )

    # --- VERIFICATION ---

    def _sm_verification(self) -> str:
        has_name = bool(self.collected["full_name"])
        has_secondary = any(
            self.collected[k] for k in ("dob", "aadhaar_last4", "pincode")
        )

        # Tell LLM what's still missing so it can ask correctly
        if not has_name:
            return (
                "VERIFICATION_PENDING: Need the user's full name. "
                "Ask for it. Remind them we also need one of: DOB, Aadhaar last 4, or pincode."
            )

        if not has_secondary:
            name_provided = self.collected["full_name"]
            return (
                f"VERIFICATION_PENDING: Full name '{name_provided}' received. "
                "Now ask for one of: date of birth (YYYY-MM-DD), "
                "last 4 Aadhaar digits, or pincode."
            )

        # We have name + secondary — attempt verification, but only if
        # the data has changed since the last attempt (avoid re-triggering same check)
        snapshot = {
            "full_name": self.collected["full_name"],
            "dob": self.collected["dob"],
            "aadhaar_last4": self.collected["aadhaar_last4"],
            "pincode": self.collected["pincode"],
        }

        if snapshot == self._last_verification_snapshot:
            remaining = MAX_VERIFICATION_ATTEMPTS - self.verification_attempts
            return (
                "SAME_DATA: User is repeating information that already failed. "
                f"{remaining} attempt(s) remaining. "
                "Gently ask them to provide different or corrected information."
            )

        self._last_verification_snapshot = snapshot.copy()

        # --- Name check (strict, case-sensitive) ---
        name_matches = self.collected["full_name"] == self.account_data["full_name"]

        if not name_matches:
            self.verification_attempts += 1
            if self.verification_attempts >= MAX_VERIFICATION_ATTEMPTS:
                self.state = State.FAILED
                return (
                    "VERIFICATION_FAILED_TERMINAL: Name does not match after maximum attempts. "
                    "Inform the user verification has failed and the session is closed. "
                    "Advise them to contact customer support. Do NOT reveal the correct name."
                )
            remaining = MAX_VERIFICATION_ATTEMPTS - self.verification_attempts
            return (
                f"VERIFICATION_FAILED: The name provided does not match our records. "
                f"{remaining} attempt(s) remaining. "
                "Ask the user to re-enter their full name exactly as registered. "
                "Do NOT reveal the correct name."
            )

        # --- Secondary factor check ---
        secondary_passed = False
        failed_factors = []

        if self.collected["dob"]:
            dob_valid, dob_err = validate_date(self.collected["dob"])
            if not dob_valid:
                # Invalid date format/value — inform user, don't count as verification attempt
                # Clear invalid DOB so user retries
                self.collected["dob"] = None
                return (
                    f"INVALID_DATE_FORMAT: The date of birth provided is not valid ({dob_err}). "
                    "Ask the user to re-enter it in YYYY-MM-DD format."
                )
            if self.collected["dob"] == self.account_data["dob"]:
                secondary_passed = True
            else:
                failed_factors.append("date of birth")

        if self.collected["aadhaar_last4"]:
            if str(self.collected["aadhaar_last4"]) == str(self.account_data["aadhaar_last4"]):
                secondary_passed = True
            else:
                failed_factors.append("Aadhaar last 4")

        if self.collected["pincode"]:
            if str(self.collected["pincode"]) == str(self.account_data["pincode"]):
                secondary_passed = True
            else:
                failed_factors.append("pincode")

        if secondary_passed:
            self.verified = True
            self.state = State.PAYMENT_COLLECTION
            balance = self.account_data["balance"]

            if balance == 0:
                # Zero balance edge case — jump straight to done
                self.state = State.DONE
                return (
                    "VERIFICATION_SUCCESS_ZERO_BALANCE: Identity verified. "
                    f"Outstanding balance is ₹0.00 — nothing is owed. "
                    "Inform the user and close the conversation gracefully."
                )

            return (
                f"VERIFICATION_SUCCESS: Identity verified. "
                f"Reveal outstanding balance: ₹{balance:.2f}. "
                f"Ask how much they would like to pay today "
                f"(any amount from ₹0.01 up to ₹{balance:.2f}; "
                f"they may say 'pay in full' to pay the entire balance). "
                "Then begin collecting card details."
            )

        # Secondary factor(s) provided but none matched
        self.verification_attempts += 1
        if self.verification_attempts >= MAX_VERIFICATION_ATTEMPTS:
            self.state = State.FAILED
            return (
                "VERIFICATION_FAILED_TERMINAL: Secondary verification failed after maximum attempts. "
                "Inform user the session is closed. Advise contacting customer support. "
                "Do NOT reveal the correct values."
            )

        remaining = MAX_VERIFICATION_ATTEMPTS - self.verification_attempts
        return (
            f"VERIFICATION_FAILED: Name matches but secondary factor did not match. "
            f"{remaining} attempt(s) remaining. "
            "Ask user to try a different secondary factor (DOB / Aadhaar last 4 / pincode). "
            "Do NOT reveal the correct values."
        )

    # --- PAYMENT COLLECTION ---

    def _sm_payment_collection(self) -> str:
        balance = self.account_data["balance"]

        # Resolve 'pay in full' shorthand
        if self.collected["payment_amount"] is None:
            return (
                f"PAYMENT_COLLECTION: Balance is ₹{balance:.2f}. "
                "Ask the user how much they want to pay today. "
                "They may say 'pay in full' to pay the complete balance."
            )

        # Handle "pay in full" — set amount to balance
        # (The LLM should extract the numeric value; if user said 'pay in full',
        # the extraction call may have returned None. We handle that above.
        # But in case it returned the balance directly, continue.)

        # Check what card details are still missing
        missing = []
        if not self.collected["card_number"]:
            missing.append("card number")
        if not self.collected["cardholder_name"]:
            missing.append("cardholder name (as it appears on the card)")
        if not self.collected["cvv"]:
            missing.append("CVV")
        if not self.collected["expiry_month"] or not self.collected["expiry_year"]:
            missing.append("card expiry (month and year)")

        if missing:
            already_have = [
                k for k in ("card_number", "cardholder_name", "cvv")
                if self.collected[k]
            ]
            if self.collected["expiry_month"] and self.collected["expiry_year"]:
                already_have.append("expiry")

            return (
                f"PAYMENT_COLLECTION: Amount set to ₹{float(self.collected['payment_amount']):.2f}. "
                f"Still need: {', '.join(missing)}. "
                "Do NOT re-ask for already collected fields."
            )

        # All fields present — validate then process
        return self._validate_and_process()

    def _validate_and_process(self) -> str:
        """Run local validation, then call the payment API."""
        balance = self.account_data["balance"]
        errors = []

        # Validate amount
        amount = float(self.collected["payment_amount"])
        valid, err = validate_amount(amount, balance)
        if not valid:
            errors.append(f"Amount: {err}")
            self.collected["payment_amount"] = None

        # Validate card number
        card_number = str(self.collected["card_number"])
        valid, err = validate_card_number(card_number)
        if not valid:
            errors.append(f"Card number: {err}")
            self.collected["card_number"] = None

        # Validate CVV (only if card number still present for Amex detection)
        cvv = str(self.collected["cvv"])
        valid, err = validate_cvv(cvv, card_number if self.collected["card_number"] else "")
        if not valid:
            errors.append(f"CVV: {err}")
            self.collected["cvv"] = None

        # Validate expiry
        valid, err = validate_expiry(
            int(self.collected["expiry_month"]),
            int(self.collected["expiry_year"]),
        )
        if not valid:
            errors.append(f"Expiry: {err}")
            self.collected["expiry_month"] = None
            self.collected["expiry_year"] = None

        if errors:
            return (
                f"VALIDATION_ERRORS: The following details are invalid — "
                f"{'; '.join(errors)}. Ask the user to correct them."
            )

        # --- All valid — call the payment API ---
        card = {
            "cardholder_name": self.collected["cardholder_name"],
            "card_number": card_number,
            "cvv": cvv,
            "expiry_month": int(self.collected["expiry_month"]),
            "expiry_year": int(self.collected["expiry_year"]),
        }

        result = process_payment(self.account_id, amount, card)

        # Wipe sensitive fields immediately after the call
        self.collected["card_number"] = None
        self.collected["cvv"] = None

        if result["success"]:
            self.state = State.DONE
            self.payment_result = result
            return (
                f"PAYMENT_SUCCESS: Payment of ₹{amount:.2f} processed successfully. "
                f"Transaction ID: {result['transaction_id']}. "
                "Congratulate the user, share the transaction ID, and close the conversation."
            )

        # --- API error codes ---
        error_code = result.get("error_code", "unknown")
        user_fixable_messages = {
            "invalid_card": "The card number is invalid. Please re-enter the card number.",
            "invalid_cvv": "The CVV is incorrect. Please re-enter the CVV.",
            "invalid_expiry": "The card expiry is invalid or the card has expired. Please check the expiry date.",
            "insufficient_balance": f"The amount exceeds the account balance of ₹{balance:.2f}.",
            "invalid_amount": "The payment amount is invalid (must be positive with up to 2 decimal places).",
        }

        if error_code in user_fixable_messages:
            # Reset the relevant field so user re-enters it
            if error_code == "invalid_card":
                self.collected["card_number"] = None
            elif error_code == "invalid_cvv":
                self.collected["cvv"] = None
            elif error_code == "invalid_expiry":
                self.collected["expiry_month"] = None
                self.collected["expiry_year"] = None
            elif error_code in ("insufficient_balance", "invalid_amount"):
                self.collected["payment_amount"] = None

            return (
                f"PAYMENT_FAILED_RETRYABLE: {user_fixable_messages[error_code]} "
                "Ask the user to correct it and try again."
            )

        # Terminal / unexpected API failure
        self.state = State.FAILED
        return (
            f"PAYMENT_FAILED_TERMINAL: Payment failed due to an unexpected error ({error_code}). "
            "Apologise and advise the user to contact customer support."
        )

    # ------------------------------------------------------------------
    # Phase 4 — Response generation
    # ------------------------------------------------------------------

    def _generate_response(self, business_context: str) -> str:
        """Generate a natural language response using the LLM."""

        # Build a privacy-safe summary of collected data for the prompt
        collected_display = {}
        for key, val in self.collected.items():
            if val is None:
                continue
            if key == "card_number":
                collected_display[key] = f"****{str(val)[-4:]}" if val else None
            elif key == "cvv":
                collected_display[key] = "***"  # never echo CVV
            else:
                collected_display[key] = val

        system = f"""You are a professional, empathetic payment collection agent for a financial services company.
Your job is to guide users through identity verification and then collect a card payment.

## Session State
- State: {self.state.value}
- Account ID: {self.account_id or "not yet provided"}
- Verified: {self.verified}
- Verification attempts used: {self.verification_attempts} / {MAX_VERIFICATION_ATTEMPTS}
- Information collected from user: {json.dumps(collected_display, indent=2)}

## Business Logic Result (follow these instructions exactly to craft your reply):
{business_context}

## Standing Rules
1. NEVER reveal account data to the user — specifically: date of birth, Aadhaar digits, pincode.
2. Do NOT re-ask for information that is already listed in "Information collected from user".
3. Be concise and professional — one clear request per message where possible.
4. If verification has passed, you may reference the balance.
5. If payment succeeded, always include the full transaction ID in your message.
6. If the session has FAILED, close gracefully and direct the user to customer support.
7. Do not include any JSON, tags, or meta-commentary in your reply — plain conversational text only.
"""

        # Include last 12 turns for context (enough for full payment flow)
        messages = [{"role": "system", "content": system}]
        messages.extend(self.conversation_history[-12:])

        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=messages,
                temperature=0.3,
                max_tokens=350,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            return (
                "I'm having trouble processing your request right now. "
                "Please try again in a moment."
            )
