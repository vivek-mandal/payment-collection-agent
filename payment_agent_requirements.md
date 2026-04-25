# Payment Collection AI Agent — Full Requirements Breakdown

---

## 🎯 Core Objective

Build a **conversational AI agent** that handles an end-to-end payment collection flow via chat, exposing a strict Python interface for automated evaluation.

---

## 📋 Conversation Flow (Ordered Steps)

The agent must follow this sequence — **steps cannot be skipped even if the user volunteers info early**:

1. Greet the user → ask for **Account ID**
2. **Look up account** via API using that ID
3. **Collect identity info** → verify the user
4. **Share outstanding balance** (only after verification passes)
5. **Collect card payment details**
6. **Process payment** via API
7. **Communicate outcome** — success (with transaction ID) or failure (with reason)
8. **Recap and close** the conversation

---

## 🔐 Verification Requirements

### Logic
- User is verified if:
  - ✅ **Full name matches exactly** — AND —
  - ✅ **At least one** of the following also matches:
    - Date of Birth (format: `YYYY-MM-DD`)
    - Last 4 digits of Aadhaar
    - Pincode

### Rules

| Rule | Detail |
|------|--------|
| Matching strictness | Strict — no fuzzy matching, no case-insensitive workarounds for names |
| Gate on payment | Do NOT proceed to any payment step until verification passes |
| Partial inputs | Handle gracefully — guide the user to provide what's missing |
| Retries | Allow reasonable retries but enforce a **sensible retry limit** (you decide the number) |
| Retry exhaustion | Decide what happens when limit is hit — document your decision |
| Data exposure | Do NOT expose DOB, Aadhaar, pincode to the user at any point |

---

## 🌐 API Reference

### Base URL
```
https://se-payment-verification-api.service.external.usea2.aws.prodigaltech.com/openapi/
```

---

### `POST /api/lookup-account`

**Request:**
```json
{ "account_id": "ACC1001" }
```

**Success Response (200):**
```json
{
  "account_id": "ACC1001",
  "full_name": "Nithin Jain",
  "dob": "1990-05-14",
  "aadhaar_last4": "4321",
  "pincode": "400001",
  "balance": 1250.75
}
```

**Failure Response (404):**
```json
{ "error_code": "account_not_found", "message": "..." }
```

---

### `POST /api/process-payment`

**Request:**
```json
{
  "account_id": "ACC1001",
  "amount": 500.00,
  "payment_method": {
    "type": "card",
    "card": {
      "cardholder_name": "Nithin Jain",
      "card_number": "4532015112830366",
      "cvv": "123",
      "expiry_month": 12,
      "expiry_year": 2027
    }
  }
}
```

**Success (200):**
```json
{ "success": true, "transaction_id": "txn_..." }
```

**Failure (422):**
```json
{ "success": false, "error_code": "insufficient_balance" }
```

---

### All API Error Codes to Handle

| Error Code | Description |
|---|---|
| `account_not_found` | Account ID does not exist |
| `invalid_amount` | Zero, negative, or more than 2 decimal places |
| `insufficient_balance` | Amount exceeds outstanding balance |
| `invalid_card` | Fails Luhn check, masked, or wrong length |
| `invalid_cvv` | Wrong length (3 digits standard, 4 for Amex) |
| `invalid_expiry` | Invalid or expired card |

### Important API Caveats
- `cardholder_name` is **not validated** against account name by the API
- API validates card format, CVV, expiry, balance — **not identity**
- **Balance does NOT persist** across requests after payment — this is by design
- Partial payments (amount < balance) are allowed

---

## 🧪 Test Accounts

| Account ID | Full Name | DOB | Aadhaar Last 4 | Pincode | Balance |
|---|---|---|---|---|---|
| ACC1001 | Nithin Jain | 1990-05-14 | 4321 | 400001 | ₹1,250.75 |
| ACC1002 | Rajarajeswari Balasubramaniam | 1985-11-23 | 9876 | 400002 | ₹540.00 |
| ACC1003 | Priya Agarwal | 1992-08-10 | 2468 | 400003 | ₹0.00 |
| ACC1004 | Rahul Mehta | 1988-02-29 | 1357 | 400004 | ₹3,200.50 |

> ⚠️ **ACC1004 edge case:** DOB `1988-02-29` is a leap year date — your agent must handle date validation edge cases (is it valid? what if user provides a nearby wrong date?).

---

## ⚙️ Technical Requirements

### 1. Context Management
- Maintain **full conversation state** across all turns
- Do **not re-ask** for information already provided
- Handle **out-of-order information** (e.g., user provides name before being asked)

### 2. Tool Calling
- Decide the **right moment** to call each API (not too early, not too late)
- Construct **correct, validated payloads** before any API call
- Handle **all response types**: success, known error codes, and unexpected failures

### 3. Verification Logic
- Implement entirely **in-agent** (no separate verification API)
- Reject incorrect attempts clearly and **count retries**
- Define and enforce a **retry limit** — document what happens on exhaustion

### 4. Payment Handling
- Collect all required card fields: number, CVV, expiry month, expiry year, cardholder name
- Support **partial payments** (amount ≤ balance)
- Interpret all API error codes and **communicate them clearly** to the user
- Do **not store or log raw card data** beyond what's needed for the API call

### 5. Failure Handling
- Every API failure → clear, **actionable user message**
- Distinguish **user-fixable** errors (invalid card) vs **terminal** failures
- For retryable errors → guide to retry; for terminal errors → close gracefully

---

## 🐍 Mandatory Python Interface

```python
class Agent:
    def next(self, user_input: str) -> dict:
        """
        Process one turn of the conversation.

        Args:
            user_input: The user's message as a plain string.

        Returns:
            {
                "message": str  # The agent's response to display to the user
            }
        """
```

### Interface Rules
- All conversation state maintained **internally** between calls
- Each `next()` call = exactly **one turn**
- Must behave **consistently and deterministically** across repeated runs
- No external setup required between turns — no manual state resets

### Sample Usage
```python
agent = Agent()
agent.next("Hi")
# → { "message": "Hello! Please share your account ID to get started." }

agent.next("My account ID is ACC1001")
# → { "message": "Got it. Could you please confirm your full name?" }

agent.next("Nithin Jain")
# → { "message": "Thanks. Could you verify your date of birth or Aadhaar last 4?" }

agent.next("DOB is 1990-05-14")
# → { "message": "Identity verified. Your outstanding balance is ₹1,250.75..." }
```

---

## 📦 Deliverables Checklist

### 1. Working Code
- [ ] `agent.py` — Agent class with exact interface
- [ ] Supporting modules (tools, validators, etc.)
- [ ] `requirements.txt`
- [ ] `README.md` with setup and run instructions
- [ ] *(Optional but recommended)* CLI/script for interactive testing

### 2. Sample Conversations (in README or separate file)
- [ ] Successful end-to-end payment
- [ ] Verification failure (retries exhausted)
- [ ] Payment failure (invalid card / expired card)
- [ ] One edge case of your choice

### 3. Design Document (1–2 pages)
- [ ] Architecture overview
- [ ] Key decisions and rationale (LLM-driven vs rule-based, etc.)
- [ ] Tradeoffs accepted
- [ ] What you'd improve with more time

### 4. Evaluation Approach
- [ ] Test cases: happy path, verification failure, payment failure, edge cases
- [ ] Definition of correctness for each step
- [ ] Automated evaluation script (if built)
- [ ] Observations: where does the agent struggle?

---

## 📊 Evaluation Criteria

| Dimension | What They Look For |
|---|---|
| **System Thinking** | Clear state machine? Edge cases anticipated? |
| **Context Handling** | State tracked correctly? No re-asking questions? |
| **Verification Logic** | Strict matching? Retries and failure modes handled? |
| **Tool Usage** | APIs called at right time with correct payloads? Errors handled? |
| **Failure Handling** | Errors communicated clearly? Graceful recovery or closure? |
| **Code Quality** | Readable, modular, and maintainable code? |
| **Evaluation Design** | Meaningful test cases? Thoughtful evaluation approach? |

---

## 🚫 Hard Rules — Non-Negotiable

1. ❌ Do NOT proceed to payment without successful verification
2. ❌ Do NOT expose DOB, Aadhaar, or pincode to the user
3. ❌ Do NOT skip steps even if user volunteers info early
4. ✅ Validate all inputs before calling any API
5. ✅ Verification must be strict — no fuzzy matching
6. ✅ Handle incorrect/partial inputs gracefully with clear guidance

---

## 💡 Key Design Decisions Left to You (Document These)

- How many **retry attempts** before locking out verification?
- What to do when retries are **exhausted** (lock, escalate, exit)?
- **LLM-driven vs rule-based** verification logic?
- How to handle **leap year date validation** (ACC1004)?
- How to handle **zero-balance accounts** (ACC1003)?
- What counts as a **terminal vs retryable** failure?
