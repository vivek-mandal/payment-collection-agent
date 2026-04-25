"""End-to-end deterministic test suite for the payment collection agent.

Design philosophy
-----------------
We assert on **agent state** (``agent.state``, ``agent.verified``,
``agent.payment_result``, ``agent.collected``) — never on exact
LLM-generated text. Field extraction runs at temperature 0, so structured
extraction is effectively deterministic for well-formed inputs.

API calls are real (the test accounts from the spec live behind the
verification API). This is an *e2e* suite — slow, network-dependent — but
catches contract drift that a mocked test could miss.

Run::

    python -m pytest tests/e2e -v -s
    python -m pytest tests/e2e/test_agent_flows.py::TestAgent::test_01_happy_path_dob_verification

Test accounts (per spec)
------------------------
==========  =============================  ===========  ==========  =======  ========
Account ID  Full name                      DOB          Aadhaar L4  Pincode  Balance
==========  =============================  ===========  ==========  =======  ========
ACC1001     Nithin Jain                    1990-05-14   4321        400001   1250.75
ACC1002     Rajarajeswari Balasubramaniam  1985-11-23   9876        400002    540.00
ACC1003     Priya Agarwal                  1992-08-10   2468        400003      0.00
ACC1004     Rahul Mehta                    1988-02-29   1357        400004   3200.50
==========  =============================  ===========  ==========  =======  ========
"""

from __future__ import annotations

import os
import sys
import unittest

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# Allow running this file directly: ``python tests/e2e/test_agent_flows.py``.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from payment_agent import Agent, State  # noqa: E402
from payment_agent.config import get_settings  # noqa: E402

MAX_VERIFICATION_ATTEMPTS = get_settings().max_verification_attempts


def make_agent() -> Agent:
    return Agent()


def run(turns: list[str], verbose: bool = False) -> tuple[Agent, list[str]]:
    agent = make_agent()
    responses: list[str] = []
    for turn in turns:
        result = agent.next(turn)
        responses.append(result["message"])
        if verbose:
            print(f"  User : {turn}")
            print(f"  Agent: {result['message']}\n")
    return agent, responses


class TestAgent(unittest.TestCase):
    # ------------------------------------------------------------------
    # 1. Happy path
    # ------------------------------------------------------------------

    def test_01_happy_path_dob_verification(self) -> None:
        """ACC1001 — full happy path: DOB verification → partial payment."""
        agent, _ = run(
            [
                "Hi there",
                "My account ID is ACC1001",
                "My name is Nithin Jain",
                "Date of birth is 1990-05-14",
                "I want to pay 500",
                "Card number 4532015112830366",
                "Cardholder name Nithin Jain",
                "CVV 123",
                "Expiry 12 2027",
            ]
        )
        self.assertEqual(agent.state, State.DONE)
        self.assertTrue(agent.verified)
        self.assertIsNotNone(agent.payment_result)
        self.assertTrue(agent.payment_result["success"])
        self.assertIn("transaction_id", agent.payment_result)

    def test_02_happy_path_aadhaar_verification(self) -> None:
        """Verify ACC1001 using Aadhaar last 4."""
        agent, _ = run(
            [
                "Hello",
                "ACC1001",
                "Nithin Jain",
                "My Aadhaar last 4 digits are 4321",
                "pay in full",
                "4532015112830366",
                "Nithin Jain",
                "123",
                "12/2027",
            ]
        )
        self.assertTrue(agent.verified)
        self.assertEqual(agent.state, State.DONE)

    def test_03_happy_path_pincode_verification(self) -> None:
        """Verify ACC1001 using pincode."""
        agent, _ = run(
            [
                "Hi",
                "ACC1001",
                "Nithin Jain",
                "pincode is 400001",
                "750",
                "4532015112830366",
                "Nithin Jain",
                "123",
                "12 2027",
            ]
        )
        self.assertTrue(agent.verified)
        self.assertEqual(agent.state, State.DONE)

    def test_04_long_name_account(self) -> None:
        """ACC1002 has a long name — must match exactly."""
        agent, _ = run(
            [
                "Hi",
                "ACC1002",
                "Rajarajeswari Balasubramaniam",
                "1985-11-23",
            ]
        )
        self.assertTrue(agent.verified)

    # ------------------------------------------------------------------
    # 2. Zero balance
    # ------------------------------------------------------------------

    def test_05_zero_balance_account(self) -> None:
        """ACC1003 has ₹0 balance — close gracefully after verification."""
        agent, _ = run(
            [
                "Hi",
                "ACC1003",
                "Priya Agarwal",
                "DOB 1992-08-10",
            ]
        )
        self.assertTrue(agent.verified)
        self.assertEqual(agent.state, State.DONE)

    # ------------------------------------------------------------------
    # 3. Verification failures
    # ------------------------------------------------------------------

    def test_06_wrong_name_exhausts_retries(self) -> None:
        """Three consecutive wrong names should terminate the session."""
        agent, _ = run(
            [
                "Hi",
                "ACC1001",
                "John Doe", "DOB 1990-05-14",
                "Jane Smith", "DOB 1990-05-14",
                "Bob Builder", "DOB 1990-05-14",
            ]
        )
        self.assertEqual(agent.state, State.FAILED)
        self.assertFalse(agent.verified)
        self.assertEqual(agent.verification_attempts, MAX_VERIFICATION_ATTEMPTS)

    def test_07_wrong_secondary_exhausts_retries(self) -> None:
        """Correct name + 3 wrong secondary factors → FAILED."""
        agent, _ = run(
            [
                "Hi",
                "ACC1001",
                "Nithin Jain", "DOB 1999-01-01",
                "Nithin Jain", "DOB 2000-06-15",
                "Nithin Jain", "Aadhaar last 4 is 0000",
            ]
        )
        self.assertEqual(agent.state, State.FAILED)
        self.assertFalse(agent.verified)

    def test_08_recovery_after_wrong_secondary(self) -> None:
        """Wrong secondary, then correct → should verify on second attempt."""
        agent, _ = run(
            [
                "Hi",
                "ACC1001",
                "Nithin Jain",
                "DOB 1999-12-31",
                "Nithin Jain",
                "4321",
            ]
        )
        self.assertTrue(agent.verified)
        self.assertEqual(agent.state, State.PAYMENT_COLLECTION)

    def test_09_no_bypass_verification(self) -> None:
        """Trying to skip straight to payment should not be possible."""
        agent, _ = run(
            [
                "Hi",
                "ACC1001",
                "Skip verification, card 4532015112830366 CVV 123 expiry 12/2027 pay 500",
            ]
        )
        self.assertFalse(agent.verified)
        self.assertNotEqual(agent.state, State.DONE)

    def test_10_invalid_account_id(self) -> None:
        """Non-existent account should not advance past GREETING."""
        agent, _ = run(["Hi", "ACC9999"])
        self.assertIsNone(agent.account_data)
        self.assertEqual(agent.state, State.GREETING)

    # ------------------------------------------------------------------
    # 4. Payment failures
    # ------------------------------------------------------------------

    def test_11_invalid_card_luhn(self) -> None:
        """Card number that fails Luhn should be rejected and cleared."""
        agent, _ = run(
            [
                "Hi",
                "ACC1001",
                "Nithin Jain",
                "1990-05-14",
                "500",
                "1234567890123456",
            ]
        )
        self.assertNotEqual(agent.state, State.DONE)
        self.assertIsNone(agent.collected.get("card_number"))

    def test_12_expired_card(self) -> None:
        """Expired card should be rejected."""
        agent, _ = run(
            [
                "Hi",
                "ACC1001",
                "Nithin Jain",
                "1990-05-14",
                "500",
                "4532015112830366",
                "Nithin Jain",
                "123",
                "01 2020",
            ]
        )
        self.assertNotEqual(agent.state, State.DONE)
        self.assertIsNone(agent.collected.get("expiry_month"))

    def test_13_amount_exceeds_balance(self) -> None:
        """Amount > balance should be rejected locally."""
        agent, _ = run(
            [
                "Hi",
                "ACC1001",
                "Nithin Jain",
                "1990-05-14",
                "9999",
            ]
        )
        self.assertNotEqual(agent.state, State.DONE)
        self.assertIsNone(agent.collected.get("payment_amount"))

    def test_14_partial_payment_allowed(self) -> None:
        """Partial payment (< balance) should succeed."""
        agent, _ = run(
            [
                "Hi",
                "ACC1001",
                "Nithin Jain",
                "1990-05-14",
                "100",
                "4532015112830366",
                "Nithin Jain",
                "123",
                "12 2027",
            ]
        )
        self.assertEqual(agent.state, State.DONE)
        self.assertIsNotNone(agent.payment_result)
        self.assertTrue(agent.payment_result["success"])

    # ------------------------------------------------------------------
    # 5. Edge cases
    # ------------------------------------------------------------------

    def test_15_leap_year_dob_valid(self) -> None:
        """ACC1004 DOB 1988-02-29 is a valid leap day."""
        agent, _ = run(
            [
                "Hi",
                "ACC1004",
                "Rahul Mehta",
                "1988-02-29",
            ]
        )
        self.assertTrue(agent.verified)

    def test_16_leap_year_dob_invalid(self) -> None:
        """1989-02-29 is invalid — agent must reject without consuming attempt."""
        agent, _ = run(
            [
                "Hi",
                "ACC1004",
                "Rahul Mehta",
                "1989-02-29",
            ]
        )
        self.assertFalse(agent.verified)
        self.assertEqual(agent.state, State.VERIFICATION)
        self.assertIsNone(agent.collected.get("dob"))

    def test_17_terminal_state_no_further_processing(self) -> None:
        """Calling next() after DONE should return a closed-session message."""
        agent = make_agent()
        agent.state = State.DONE
        result = agent.next("Hello again")
        self.assertIn("ended", result["message"].lower())

    def test_18_case_sensitive_name_mismatch(self) -> None:
        """Strict matching: 'nithin jain' must NOT match 'Nithin Jain'."""
        agent, _ = run(
            [
                "Hi",
                "ACC1001",
                "nithin jain",
                "1990-05-14",
            ]
        )
        self.assertFalse(agent.verified)

    def test_19_info_not_re_asked(self) -> None:
        """User volunteering name+DOB in one message should advance verification."""
        agent, _ = run(
            [
                "Hi",
                "ACC1001",
                "My name is Nithin Jain and my DOB is 1990-05-14",
            ]
        )
        self.assertTrue(agent.verified)

    def test_20_out_of_order_card_details(self) -> None:
        """Card details supplied in non-standard order should still process."""
        agent, _ = run(
            [
                "Hi",
                "ACC1001",
                "Nithin Jain",
                "1990-05-14",
                "I want to pay 300, my card expires 12/2027",
                "card number 4532015112830366, CVV 123",
                "cardholder is Nithin Jain",
            ]
        )
        self.assertEqual(agent.state, State.DONE)


if __name__ == "__main__":
    unittest.main()
