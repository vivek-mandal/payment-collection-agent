# Test Accounts — Live Data from API

Fetched directly from the payment verification API.
Use these for manual testing and to verify agent behaviour.

> **Keep this file private — do not commit to a public repo.**

---

| Field          | ACC1001         | ACC1002                        | ACC1003        | ACC1004       |
|----------------|-----------------|--------------------------------|----------------|---------------|
| **Full Name**  | Nithin Jain     | Rajarajeswari Balasubramaniam  | Priya Agarwal  | Rahul Mehta   |
| **DOB**        | 1990-05-14      | 1985-11-23                     | 1992-08-10     | 1988-02-29 ⚠️ |
| **Aadhaar L4** | 4321            | 9876                           | 2468           | 1357          |
| **Pincode**    | 400001          | 400002                         | 400003         | 400004        |
| **Balance**    | ₹1,250.75       | ₹540.00                        | ₹0.00 ⚠️       | ₹3,200.50     |

⚠️ **ACC1003** — zero balance, session closes after verification with no payment step.
⚠️ **ACC1004** — DOB `1988-02-29` is a real leap year date. `1989-02-29` is invalid and must be rejected by the agent without consuming a verification attempt.

---

## Quick test card

Works against all accounts (passes Luhn, not expired):

| Field           | Value              |
|-----------------|--------------------|
| Card Number     | 4532015112830366   |
| CVV             | 123                |
| Expiry          | 12/2027            |
| Cardholder Name | (any name)         |

---

## Verification rules (reminder)

- Name must match **exactly** — case-sensitive. `nithin jain` ≠ `Nithin Jain`.
- Plus **at least one** of: DOB / Aadhaar last 4 / Pincode.
- Max **3 attempts** before session is locked.
- Invalid date format (e.g. `1989-02-29`) does **not** count as an attempt.
