# Payment Collection AI Agent

A production-ready conversational agent that handles end-to-end payment collection:
account lookup → identity verification → card payment processing.

---

## Quick Start

### 1. Clone and install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set environment variables

Create a `.env` file in the project root:

```env
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key-here
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
```

Or export them directly:

```bash
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
export AZURE_OPENAI_API_KEY="your-key"
export AZURE_OPENAI_DEPLOYMENT_NAME="gpt-4o"
```

### 3. Run interactively

```bash
python cli.py
```

### 4. Run evaluation suite

```bash
python eval.py        # all 20 tests
python eval.py -v     # verbose output
```

---

## File Structure

```
payment_agent/
├── agent.py          # Agent class — the required interface
├── tools.py          # API wrappers (lookup_account, process_payment)
├── validators.py     # Deterministic validators (Luhn, CVV, expiry, date, amount)
├── cli.py            # Interactive terminal interface
├── eval.py           # Deterministic evaluation suite (20 test cases)
├── requirements.txt
├── README.md
└── design_doc.md
```

---

## Agent Interface

```python
from agent import Agent

agent = Agent()
result = agent.next("Hello")          # → {"message": str}
result = agent.next("My ID is ACC1001")
result = agent.next("Nithin Jain")
# ... and so on
```

State is maintained internally across all `.next()` calls.

---

## Sample Conversations

### ✅ Successful end-to-end payment

```
Agent : Hello! Welcome to our payment service. Please share your account ID to get started.

User  : ACC1001

Agent : Thank you. I've found your account. To verify your identity, could you please
        provide your full name as registered with us?

User  : Nithin Jain

Agent : Got it. Could you please confirm your date of birth (YYYY-MM-DD),
        the last 4 digits of your Aadhaar, or your pincode?

User  : DOB is 1990-05-14

Agent : Your identity has been verified. Your outstanding balance is ₹1,250.75.
        How much would you like to pay today? You may pay any amount up to ₹1,250.75,
        or say "pay in full" to clear the entire balance.

User  : 500

Agent : Please share your card details: card number, cardholder name, CVV,
        and expiry month and year.

User  : Card number 4532015112830366, name Nithin Jain, CVV 123, expiry 12/2027

Agent : Thank you. Processing your payment of ₹500.00…

        ✅ Payment successful!
        Transaction ID: txn_1762510325322_l1fl4oy
        Amount paid: ₹500.00

        Thank you, Nithin. Is there anything else I can help you with?
```

---

### ❌ Verification failure — retries exhausted

```
Agent : Hello! Please share your account ID to get started.
User  : ACC1001
Agent : Account found. Please provide your full name.

User  : John Smith
Agent : The name provided does not match our records. Please check and re-enter your
        full name exactly as registered. You have 2 attempts remaining.

User  : John Smith
Agent : Verification unsuccessful. You have 1 attempt remaining. Please try again
        with the correct name.

User  : John Smith
Agent : I'm sorry, but we were unable to verify your identity after 3 attempts.
        For security reasons, this session has been closed.
        Please contact our customer support team for further assistance.
```

---

### 💳 Payment failure — invalid card

```
[After verification...]
Agent : Your outstanding balance is ₹1,250.75. How much would you like to pay?
User  : 500
Agent : Please provide your card number, cardholder name, CVV, and expiry date.
User  : Card 1234567890123456, name Nithin Jain, CVV 123, expiry 12/2027
Agent : The card number you entered appears to be invalid (failed security check).
        Please double-check and re-enter your card number.
User  : 4532015112830366
Agent : ✅ Payment of ₹500.00 processed. Transaction ID: txn_...
```

---

### 🔄 Edge case — leap year (ACC1004)

```
Agent : Please provide your identity details.
User  : Rahul Mehta
Agent : Thank you. Date of birth, Aadhaar last 4, or pincode?

User  : 1989-02-29
Agent : The date of birth you entered is not valid — 1989 is not a leap year, so
        February 29 does not exist in that year. Please re-enter your date of birth
        in YYYY-MM-DD format.

User  : 1988-02-29
Agent : Identity verified. Your outstanding balance is ₹3,200.50...
```

---

## Test Accounts

| Account | Name | DOB | Aadhaar Last 4 | Pincode | Balance |
|---------|------|-----|----------------|---------|---------|
| ACC1001 | Nithin Jain | 1990-05-14 | 4321 | 400001 | ₹1,250.75 |
| ACC1002 | Rajarajeswari Balasubramaniam | 1985-11-23 | 9876 | 400002 | ₹540.00 |
| ACC1003 | Priya Agarwal | 1992-08-10 | 2468 | 400003 | ₹0.00 |
| ACC1004 | Rahul Mehta | 1988-02-29 | 1357 | 400004 | ₹3,200.50 |

---

## Evaluation

20 deterministic test cases covering:

| Category | Tests |
|----------|-------|
| Happy path (DOB / Aadhaar / Pincode verification) | 3 |
| Long name account | 1 |
| Zero balance | 1 |
| Verification failures (wrong name / secondary / retries) | 5 |
| Payment failures (Luhn / expired / over-balance) | 3 |
| Partial payment | 1 |
| Edge cases (leap year, case sensitivity, out-of-order input) | 5 |

Tests assert on `agent.state`, `agent.verified`, and `agent.payment_result` —
not on LLM-generated text — making them deterministic across runs.
