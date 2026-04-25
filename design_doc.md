# Design Document — Payment Collection AI Agent

## Architecture Overview

The agent uses a **hybrid LLM + deterministic state machine** pattern.

```
user_input
    │
    ▼
┌──────────────────────────────────────────────────┐
│  agent.next(user_input)                          │
│                                                  │
│  Phase 1 ─ LLM Extraction (temperature=0)        │
│    Extract structured fields from raw text:      │
│    account_id, full_name, dob, card_number, …    │
│                          │                       │
│  Phase 2 ─ State Merge                           │
│    Update `collected` dict (never overwrite      │
│    existing value with None)                     │
│                          │                       │
│  Phase 3 ─ State Machine  ◄──── DETERMINISTIC    │
│    ┌──────────┐  account  ┌────────────┐         │
│    │ GREETING │ ─lookup──►│VERIFICATION│         │
│    └──────────┘           └────────────┘         │
│                                │ verify          │
│                           ┌────▼──────────┐      │
│                           │PAYMENT_        │      │
│                           │COLLECTION     │      │
│                           └────┬──────────┘      │
│                      payment   │  API             │
│                           ┌────▼──┐  ┌────────┐  │
│                           │ DONE  │  │ FAILED │  │
│                           └───────┘  └────────┘  │
│                          │                       │
│  Phase 4 ─ LLM Response                          │
│    Generate natural language reply given         │
│    current state + business_context string       │
└──────────────────────────────────────────────────┘
    │
    ▼
{"message": str}
```

**Two LLM calls per turn.** The first (extraction) is small, focused, and runs
at temperature=0 for determinism. The second (response generation) runs at
temperature=0.3 for natural, varied language.

All **business logic** — verification pass/fail, retry counting, card validation,
API call timing — is implemented in Python and is completely LLM-independent.

---

## Key Design Decisions

### 1. LLM-driven extraction, Python-driven logic

**Decision:** The LLM only does two things — extract structured data and
generate responses. It never makes pass/fail decisions.

**Rationale:** Verification must be strict (spec requirement). Any LLM involvement
in the pass/fail decision introduces non-determinism and potential for prompt
injection attacks. Python `==` comparison is unambiguous and auditable.

**Tradeoff:** Two LLM calls per turn adds ~500ms latency. Acceptable for a
payment flow where users expect deliberate pacing.

### 2. State machine with explicit states

**Decision:** Five named states (GREETING, VERIFICATION, PAYMENT_COLLECTION,
DONE, FAILED). Transitions are one-way and triggered by explicit conditions.

**Rationale:** Makes the agent's flow predictable, testable, and auditable.
Prevents the LLM from "deciding" to skip steps or loop back unexpectedly.

**Tradeoff:** Less flexible than a fully LLM-driven agent, but correct by
construction for the required flow.

### 3. Verification: strict name + one secondary factor

**Decision:** Implemented exactly per spec — exact string comparison for
full_name, and at least one exact match from {dob, aadhaar_last4, pincode}.
No fuzzy matching, no case folding.

**Rationale:** The spec is unambiguous on this. Strict matching prevents social
engineering (e.g. "Nithin Jain " with trailing space would fail, which is correct
because the user should type their name correctly).

**Edge case handled:** Invalid date formats (e.g. 1989-02-29) are caught by
`validate_date()` before comparison, the field is cleared, and the attempt is
NOT counted. This prevents a user from being penalised for a format error.

### 4. Retry counting

**Decision:** 3 attempts max. An "attempt" is counted only when we have name +
secondary factor and the combination fails. A snapshot of the last-checked data
prevents the same failed data from being re-checked and double-counted.

**What happens on exhaustion:** State transitions to FAILED (terminal).
User is directed to contact support. Session cannot continue.

### 5. Partial payments

**Decision:** Ask the user how much they want to pay, show the balance, default
to full balance if they say "pay in full." Accept any amount from ₹0.01 to
the full balance.

**Rationale:** The spec says "partial payments are allowed." Not offering partial
payment would be a worse user experience. The LLM handles "pay in full" by
extracting the numeric balance from context.

### 6. Card data handling

**Decision:** Card number and CVV are wiped from `self.collected` immediately
after the payment API call (success or failure). They are never logged or
stored in conversation history beyond the single API call.

**Rationale:** Minimum necessary retention principle. The evaluator will inspect
agent state, and we should not have raw card data sitting in memory.

### 7. Local validation before API call

**Decision:** Run Luhn check, CVV length check, expiry check, and amount check
locally before calling `process-payment`.

**Rationale:** Reduces unnecessary API calls, gives faster user feedback, and
provides clearer error messages. The API also validates, so this is defence in
depth — both layers must pass.

### 8. `business_context` string pattern

**Decision:** Phase 3 (state machine) produces a plain English context string
describing exactly what happened and what the LLM should say. Phase 4 (LLM)
only has to execute on that instruction.

**Rationale:** Separates what to say from how to say it. The LLM cannot
contradict the state machine — if the context says "verification passed," the
LLM must say verification passed. This is more reliable than prompting the LLM
to "figure out what to do."

---

## Evaluation Design

Tests assert on agent **internal state** (`agent.state`, `agent.verified`,
`agent.payment_result`, `agent.collected`), not on LLM-generated text.

This makes tests deterministic:
- Verification outcomes are pure Python comparisons.
- API responses are deterministic for fixed inputs (test accounts).
- Extraction uses temperature=0, making LLM field extraction stable.

20 test cases cover happy paths, all failure modes, edge cases (leap year,
case sensitivity, out-of-order input, zero balance).

---

## Tradeoffs Accepted

| Tradeoff | Accepted Because |
|----------|-----------------|
| 2 LLM calls/turn | Clean separation of extraction vs. response; latency acceptable for payment UX |
| No fuzzy name matching | Spec requires strict matching; fuzzy matching is a security risk |
| Conversation history capped at 12 turns | Payment flows are short; avoids token bloat |
| No multi-session state | Spec requires fresh agent per session |
| LLM response not parsed | Response is for display only; no structured data extracted from it |

---

## What I Would Improve With More Time

1. **Rate limiting and session locking** — prevent brute-force verification by
   adding exponential backoff between attempts and IP-level throttling.

2. **Streaming responses** — stream the LLM response token-by-token for a
   better chat UX.

3. **Audit logging** — structured logs (JSON) for every state transition and API
   call, with timestamps and session IDs, without logging raw card data.

4. **PCI-DSS compliance** — in a real system, card data should be collected via
   a tokenisation iframe (e.g. Stripe Elements) and never pass through our
   server. The current design collects it in chat as a demo.

5. **LLM fallback** — if the primary Azure deployment is unavailable, fall back
   to a secondary endpoint or a rule-based extraction path.

6. **Conversation memory** — if a user drops mid-flow, allow session resumption
   with re-verification (rather than starting over).

7. **UI** — the CLI is functional but a web UI (React + WebSocket) would be a
   better demo vehicle and easier for evaluators to test interactively.
