# Sample Conversations

> All transcripts below are illustrative. Exact wording will vary turn-to-turn (the responder runs at temperature 0.3); state transitions are deterministic.

---

## 1. Successful end-to-end payment (DOB verification)

```
Agent : Hello! Welcome to our payment service. Please share your account ID
        to get started.

User  : ACC1001

Agent : Thank you. I've found your account. To verify your identity, could you
        please provide your full name as registered with us, along with one of:
        date of birth (YYYY-MM-DD), last 4 digits of Aadhaar, or pincode?

User  : Nithin Jain, DOB 1990-05-14

Agent : Your identity has been verified. Your outstanding balance is ₹1,250.75.
        How much would you like to pay today? You may pay any amount up to
        ₹1,250.75, or say "pay in full".

User  : 500

Agent : Please share your card details: card number, cardholder name, CVV,
        and expiry month and year.

User  : Card 4532015112830366, Nithin Jain, CVV 123, expiry 12/2027

Agent : Processing your payment of ₹500.00...

        ✅ Payment successful.
        Transaction ID: txn_1762510325322_l1fl4oy
        Amount paid: ₹500.00

        Thank you, Nithin. Is there anything else I can help you with?
```

---

## 2. Verification failure — retries exhausted

```
Agent : Hello! Please share your account ID to get started.

User  : ACC1001
Agent : Account found. Please provide your full name and one of: DOB, Aadhaar
        last 4, or pincode.

User  : John Smith, DOB 1990-05-14
Agent : The information you provided does not match our records. You have 2
        attempts remaining. Please re-check and try again.

User  : John Smith, Aadhaar 4321
Agent : Verification unsuccessful. You have 1 attempt remaining.

User  : John Smith, pincode 400001
Agent : I'm sorry, we were unable to verify your identity after 3 attempts.
        For security reasons, this session has been closed. Please contact
        our customer support team for further assistance.
```

State after this conversation: `agent.state == FAILED`, `agent.verified == False`.

---

## 3. Payment failure — invalid card, then retry succeeds

```
[after successful verification]

Agent : Your outstanding balance is ₹1,250.75. How much would you like to pay?
User  : 500
Agent : Please provide your card number, cardholder name, CVV, and expiry date.
User  : 1234567890123456, Nithin Jain, 123, 12/2027
Agent : The card number you provided appears to be invalid (failed security
        check). Please re-enter your card number.
User  : 4532015112830366
Agent : ✅ Payment of ₹500.00 processed.
        Transaction ID: txn_...
```

---

## 4. Edge case — leap year (ACC1004)

```
Agent : Please provide your full name and a verification factor.
User  : Rahul Mehta, DOB 1989-02-29

Agent : The date you provided is not valid — 1989 was not a leap year, so
        February 29 doesn't exist that year. Could you re-enter your date of
        birth in YYYY-MM-DD format?

User  : 1988-02-29

Agent : Identity verified. Your outstanding balance is ₹3,200.50...
```

The invalid date does **not** consume a verification attempt — the agent treats it as a format error.

---

## 5. Zero-balance account (ACC1003)

```
User  : ACC1003
Agent : Account found. Please verify your identity.
User  : Priya Agarwal, DOB 1992-08-10
Agent : Identity verified. Your outstanding balance is ₹0.00 — there is
        nothing owed on this account. Have a great day!
```

State after this conversation: `agent.state == DONE`, no payment needed.
