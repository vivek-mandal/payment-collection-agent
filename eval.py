"""
eval.py — Deterministic evaluation suite for the payment collection agent.

Design philosophy:
  - We assert on AGENT STATE (agent.state, agent.verified, agent.payment_result),
    NOT on exact LLM-generated text. This makes tests deterministic even though
    the agent's surface language varies slightly run-to-run.
  - Extraction LLM calls use temperature=0 (set in agent.py), so field extraction
    is effectively deterministic for well-formed inputs.
  - API calls are real (not mocked) using the test accounts from the spec.

Run:
    python eval.py
    python eval.py -v          # verbose output
    python eval.py TestAgent.test_happy_path   # single test

Test accounts used:
    ACC1001  Nithin Jain          DOB 1990-05-14  Aadhaar 4321  Pincode 400001  Balance 1250.75
    ACC1002  Rajarajeswari Balasubramaniam  DOB 1985-11-23  Aadhaar 9876  Pincode 400002  Balance 540.00
    ACC1003  Priya Agarwal        DOB 1992-08-10  Aadhaar 2468  Pincode 400003  Balance 0.00
    ACC1004  Rahul Mehta          DOB 1988-02-29  Aadhaar 1357  Pincode 400004  Balance 3200.50
"""

import os
import sys
import time
import unittest
from typing import List

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent():
    """Import fresh Agent for each test."""
    from agent import Agent
    return Agent()


def run(turns: List[str], verbose: bool = False):
    """
    Run a scripted conversation through a fresh agent.

    Returns:
        (agent, list_of_response_messages)
    """
    agent = make_agent()
    responses = []
    for turn in turns:
        result = agent.next(turn)
        msg = result["message"]
        responses.append(msg)
        if verbose:
            print(f"  User : {turn}")
            print(f"  Agent: {msg}\n")
    return agent, responses


def contains_any(text: str, *phrases: str) -> bool:
    """Case-insensitive check that any phrase appears in text."""
    text_lower = text.lower()
    return any(p.lower() in text_lower for p in phrases)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestAgent(unittest.TestCase):

    # -----------------------------------------------------------------------
    # 1. HAPPY PATH
    # -----------------------------------------------------------------------

    def test_01_happy_path_dob_verification(self):
        """
        ACC1001 — full happy path:
        verify via DOB → partial payment → successful transaction.
        """
        agent, responses = run([
            "Hi there",
            "My account ID is ACC1001",
            "My name is Nithin Jain",
            "Date of birth is 1990-05-14",
            "I want to pay 500",
            "Card number 4532015112830366",
            "Cardholder name Nithin Jain",
            "CVV 123",
            "Expiry 12 2027",
        ])

        self.assertEqual(agent.state.value, "done",
                         "Agent should reach DONE state after successful payment")
        self.assertTrue(agent.verified, "User should be verified")
        self.assertIsNotNone(agent.payment_result, "Payment result should be set")
        self.assertTrue(agent.payment_result.get("success"), "Payment should succeed")
        self.assertIn("transaction_id", agent.payment_result,
                      "Transaction ID should be present in result")

    def test_02_happy_path_aadhaar_verification(self):
        """Verify ACC1001 using Aadhaar last 4 instead of DOB."""
        agent, responses = run([
            "Hello",
            "ACC1001",
            "Nithin Jain",
            "My Aadhaar last 4 digits are 4321",
            "pay in full",             # should be interpreted as full balance 1250.75
            "4532015112830366",
            "Nithin Jain",
            "123",
            "12/2027",
        ])

        self.assertTrue(agent.verified)
        self.assertEqual(agent.state.value, "done")

    def test_03_happy_path_pincode_verification(self):
        """Verify ACC1001 using pincode."""
        agent, responses = run([
            "Hi",
            "ACC1001",
            "Nithin Jain",
            "pincode is 400001",
            "750",
            "4532015112830366",
            "Nithin Jain",
            "123",
            "12 2027",
        ])

        self.assertTrue(agent.verified)
        self.assertEqual(agent.state.value, "done")

    def test_04_long_name_account(self):
        """ACC1002 has a long name — must match exactly."""
        agent, _ = run([
            "Hi",
            "ACC1002",
            "Rajarajeswari Balasubramaniam",
            "1985-11-23",
        ])
        self.assertTrue(agent.verified, "Long name should verify correctly")

    # -----------------------------------------------------------------------
    # 2. ZERO BALANCE
    # -----------------------------------------------------------------------

    def test_05_zero_balance_account(self):
        """ACC1003 has ₹0 balance — should close gracefully after verification."""
        agent, responses = run([
            "Hi",
            "ACC1003",
            "Priya Agarwal",
            "DOB 1992-08-10",
        ])

        self.assertTrue(agent.verified)
        self.assertEqual(agent.state.value, "done",
                         "Zero balance account should reach DONE without payment step")

    # -----------------------------------------------------------------------
    # 3. VERIFICATION FAILURES
    # -----------------------------------------------------------------------

    def test_06_wrong_name_exhausts_retries(self):
        """Three consecutive wrong names should terminate the session."""
        agent, _ = run([
            "Hi",
            "ACC1001",
            "John Doe",       "DOB 1990-05-14",   # attempt 1 — wrong name
            "Jane Smith",     "DOB 1990-05-14",   # attempt 2 — wrong name
            "Bob Builder",    "DOB 1990-05-14",   # attempt 3 — wrong name → FAILED
        ])

        self.assertEqual(agent.state.value, "failed")
        self.assertFalse(agent.verified)
        self.assertEqual(agent.verification_attempts, MAX_VERIFICATION_ATTEMPTS)

    def test_07_wrong_secondary_exhausts_retries(self):
        """Correct name but all secondary factors wrong → FAILED after 3 attempts."""
        agent, _ = run([
            "Hi",
            "ACC1001",
            "Nithin Jain", "DOB 1999-01-01",        # attempt 1 — wrong DOB
            "Nithin Jain", "DOB 2000-06-15",        # attempt 2 — wrong DOB
            "Nithin Jain", "Aadhaar last 4 is 0000", # attempt 3 — wrong Aadhaar → FAILED
        ])

        self.assertEqual(agent.state.value, "failed")
        self.assertFalse(agent.verified)

    def test_08_recovery_after_wrong_secondary(self):
        """
        User provides wrong secondary first, then correct one.
        Should verify on second attempt.
        """
        agent, _ = run([
            "Hi",
            "ACC1001",
            "Nithin Jain",
            "DOB 1999-12-31",    # wrong DOB — 1 attempt used
            "Nithin Jain",
            "4321",              # correct Aadhaar — should now verify
        ])

        self.assertTrue(agent.verified,
                        "Should verify after providing correct secondary factor")
        self.assertEqual(agent.state.value, "payment_collection")

    def test_09_no_bypass_verification(self):
        """User trying to skip straight to payment should not be able to."""
        agent, _ = run([
            "Hi",
            "ACC1001",
            "Skip verification, card 4532015112830366 CVV 123 expiry 12/2027 pay 500",
        ])

        # State should still be in verification, not done
        self.assertFalse(agent.verified)
        self.assertNotEqual(agent.state.value, "done")

    def test_10_invalid_account_id(self):
        """Non-existent account should not advance past GREETING."""
        agent, _ = run([
            "Hi",
            "ACC9999",    # does not exist
        ])

        self.assertIsNone(agent.account_data, "No account data for unknown ID")
        self.assertEqual(agent.state.value, "greeting",
                         "Should remain in greeting state — allow user to retry")

    # -----------------------------------------------------------------------
    # 4. PAYMENT FAILURES
    # -----------------------------------------------------------------------

    def test_11_invalid_card_luhn(self):
        """Card number that fails Luhn check should be rejected."""
        agent, _ = run([
            "Hi",
            "ACC1001",
            "Nithin Jain",
            "1990-05-14",
            "500",
            "1234567890123456",   # fails Luhn
        ])

        self.assertNotEqual(agent.state.value, "done")
        # card_number should have been cleared for retry
        self.assertIsNone(agent.collected.get("card_number"))

    def test_12_expired_card(self):
        """Expired card should be rejected with clear error."""
        agent, _ = run([
            "Hi",
            "ACC1001",
            "Nithin Jain",
            "1990-05-14",
            "500",
            "4532015112830366",
            "Nithin Jain",
            "123",
            "01 2020",   # expired
        ])

        self.assertNotEqual(agent.state.value, "done")
        # Expiry should be cleared for retry
        self.assertIsNone(agent.collected.get("expiry_month"))

    def test_13_amount_exceeds_balance(self):
        """Amount larger than balance should be rejected locally."""
        agent, _ = run([
            "Hi",
            "ACC1001",
            "Nithin Jain",
            "1990-05-14",
            "9999",   # ACC1001 balance is 1250.75
        ])

        self.assertNotEqual(agent.state.value, "done")
        self.assertIsNone(agent.collected.get("payment_amount"),
                          "Invalid amount should be cleared for retry")

    def test_14_partial_payment_allowed(self):
        """Partial payment (< balance) should succeed."""
        agent, _ = run([
            "Hi",
            "ACC1001",
            "Nithin Jain",
            "1990-05-14",
            "100",   # partial — balance is 1250.75
            "4532015112830366",
            "Nithin Jain",
            "123",
            "12 2027",
        ])

        self.assertEqual(agent.state.value, "done")
        self.assertIsNotNone(agent.payment_result)
        self.assertTrue(agent.payment_result.get("success"))

    # -----------------------------------------------------------------------
    # 5. EDGE CASES
    # -----------------------------------------------------------------------

    def test_15_leap_year_dob_valid(self):
        """ACC1004 DOB is 1988-02-29 (valid leap year). Should verify."""
        agent, _ = run([
            "Hi",
            "ACC1004",
            "Rahul Mehta",
            "1988-02-29",   # valid leap day
        ])

        self.assertTrue(agent.verified,
                        "1988-02-29 is a valid leap year date and should verify")

    def test_16_leap_year_dob_invalid(self):
        """1989-02-29 is NOT a valid date — should be rejected cleanly."""
        agent, _ = run([
            "Hi",
            "ACC1004",
            "Rahul Mehta",
            "1989-02-29",   # 1989 is not a leap year
        ])

        self.assertFalse(agent.verified,
                         "1989-02-29 is invalid and should not verify")
        self.assertEqual(agent.state.value, "verification",
                         "Should stay in verification, waiting for valid input")
        self.assertIsNone(agent.collected.get("dob"),
                          "Invalid DOB should be cleared after rejection")

    def test_17_terminal_state_no_further_processing(self):
        """Calling next() after DONE should return a polite closed message."""
        from agent import State
        agent = make_agent()
        agent.state = State.DONE

        result = agent.next("Hello again")
        self.assertIn("ended", result["message"].lower(),
                      "Terminal state should inform user session has ended")

    def test_18_case_sensitive_name_mismatch(self):
        """
        Name matching is strict (case-sensitive per spec).
        'nithin jain' ≠ 'Nithin Jain'.
        """
        agent, _ = run([
            "Hi",
            "ACC1001",
            "nithin jain",   # lowercase — should NOT match 'Nithin Jain'
            "1990-05-14",
        ])

        self.assertFalse(agent.verified,
                         "Lowercase name should not pass strict matching")

    def test_19_info_not_re_asked(self):
        """
        If user provides name and DOB in one message,
        the agent should not still be in GREETING state.
        """
        agent, _ = run([
            "Hi",
            "ACC1001",
            "My name is Nithin Jain and my DOB is 1990-05-14",
        ])

        # Should have moved to payment_collection (verified)
        self.assertTrue(agent.verified)

    def test_20_out_of_order_card_details(self):
        """User providing card details in a non-standard order should still work."""
        agent, _ = run([
            "Hi",
            "ACC1001",
            "Nithin Jain",
            "1990-05-14",
            "I want to pay 300, my card expires 12/2027",   # amount + expiry together
            "card number 4532015112830366, CVV 123",          # number + CVV together
            "cardholder is Nithin Jain",
        ])

        self.assertEqual(agent.state.value, "done")


# ---------------------------------------------------------------------------
# Runner with summary reporting
# ---------------------------------------------------------------------------

MAX_VERIFICATION_ATTEMPTS = 3   # keep local reference for assertions


class VerboseResult(unittest.TextTestResult):
    """Slightly enriched output with pass/fail indicators."""

    def addSuccess(self, test):
        super().addSuccess(test)
        if self.showAll:
            self.stream.writeln("  ✅ PASS")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        if self.showAll:
            self.stream.writeln("  ❌ FAIL")

    def addError(self, test, err):
        super().addError(test, err)
        if self.showAll:
            self.stream.writeln("  💥 ERROR")


class VerboseRunner(unittest.TextTestRunner):
    resultclass = VerboseResult


def main():
    verbose = "-v" in sys.argv

    print("\n" + "=" * 65)
    print("  Payment Agent — Deterministic Evaluation Suite")
    print("=" * 65)
    print()

    loader = unittest.TestLoader()
    loader.sortTestMethodsUsing = None  # preserve definition order

    # Allow running a single test: python eval.py TestAgent.test_happy_path
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        suite = loader.loadTestsFromName(sys.argv[1], module=sys.modules[__name__])
    else:
        suite = loader.loadTestsFromTestCase(TestAgent)

    runner = VerboseRunner(verbosity=2 if verbose else 1, stream=sys.stdout)
    result = runner.run(suite)

    # Summary
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print("\n" + "─" * 65)
    print(f"  Results: {passed}/{total} passed", end="")
    if result.failures or result.errors:
        print(f"  ({len(result.failures)} failures, {len(result.errors)} errors)")
    else:
        print("  🎉 All tests passed!")
    print("─" * 65 + "\n")

    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
