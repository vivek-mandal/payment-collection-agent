# Payment Collection Agent — Design Document

## 1. Goal

A conversational agent that walks a user through:

1. Account lookup (by ID)
2. Identity verification (full name + at least one of DOB / Aadhaar last-4 / pincode)
3. Disclosure of outstanding balance
4. Card details collection
5. Payment processing
6. Outcome communication and graceful close

The agent must expose the strict interface:

```python
class Agent:
    def next(self, user_input: str) -> dict: ...
```

with all conversation state held internally between calls.

---

## 2. High-level architecture

```
            ┌──────────────────────────────────────────────────┐
            │                     Agent                        │
            │  (turn orchestrator — exposes .next(user_input)) │
            └─────────────────────────┬────────────────────────┘
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        ▼                             ▼                             ▼
┌────────────────┐          ┌──────────────────┐         ┌──────────────────┐
│  Extractor     │          │  StateMachine    │         │   Responder      │
│  (LLM,         │          │  (deterministic) │         │   (LLM,          │
│   temp=0,      │          │                  │         │    temp=0.3)     │
│   JSON schema) │          │  GREETING        │         │                  │
└────────┬───────┘          │  VERIFICATION    │         └────────▲─────────┘
         │ ExtractedFields  │  PAYMENT         │                  │
         ▼                  │  DONE / FAILED   │  BusinessOutcome │
   ┌──────────────┐         │                  │──────────────────┘
   │ CollectedData│◄────────┤  + Validators    │
   │ (state)      │         │  + Verification  │
   └──────────────┘         │  + APIClient     │
                            └──────────┬───────┘
                                       │ HTTP
                                       ▼
                       ┌────────────────────────────────┐
                       │   PaymentAPIClient             │
                       │  - retries (tenacity)          │
                       │  - idempotency keys on payment │
                       │  - typed exceptions            │
                       └────────────────────────────────┘
```

### Why this split

| Concern | Owner | Why |
|---|---|---|
| Pass/fail decisions | State machine + validators | Deterministic, auditable, unit-testable |
| Natural-language understanding | LLM extractor | Free text → structured fields |
| Tone and phrasing | LLM responder | Variability is fine here |
| HTTP, retries, idempotency | API client | Single point of network resilience |
| Prompts | `prompts/*.txt` | Versionable, reviewable, swappable |

The LLM **never** decides whether the user is verified or whether a payment goes through. Those decisions live in pure Python.

---

## 3. Per-turn lifecycle

```
agent.next(user_input)
   │
   ├─ append to redacted history
   │
   ├─ Extractor.extract(user_input)        ── LLM call #1 (temp=0, JSON output)
   │     → ExtractedFields
   │
   ├─ ConversationState.merge(fields)      ── never overwrite known with None
   │
   ├─ StateMachine.advance(state)          ── may call API, may transition
   │     → BusinessOutcome(code, instruction, data)
   │
   ├─ Responder.render(outcome, state)     ── LLM call #2 (temp=0.3)
   │     → user-visible message
   │
   └─ append assistant message to history (already redacted at write)
```

Two LLM calls per turn is a deliberate tradeoff. We could fold them into one tool-calling round, but separating extraction from generation lets us:

- run the extractor at temperature 0 for stable, JSON-schema-validated output;
- run the responder at a small temperature for natural variation;
- evaluate each independently.

---

## 4. Verification logic

### Rules (per spec)

- Full name must match **exactly** (case-sensitive, no fuzzy).
- Plus **at least one** of: DOB (`YYYY-MM-DD`), Aadhaar last 4, or pincode.
- Strict matching — no normalization beyond `.strip()` of leading/trailing whitespace.

### Retry policy

- `MAX_VERIFICATION_ATTEMPTS = 3`.
- An attempt is counted only when **both** name and a secondary factor have been supplied and the combination doesn't match.
- Repeated submission of the **same** failing data does **not** double-count (snapshot comparison).
- Invalid date formats (e.g. `1989-02-29`) do not consume an attempt — the user is asked to re-enter.
- On exhaustion: state transitions to `FAILED`, session is closed, user is directed to support. Correct values are never disclosed.

### Why these choices

3 attempts is the standard for high-friction identity flows (banks, call-center scripts). Lower would frustrate; higher would weaken security. Snapshot deduplication avoids penalizing users for re-sending the same correction without realizing the agent already evaluated it.

---

## 5. Payment validation

Local, before any API call:

| Check | Rule |
|---|---|
| Amount | `> 0`, `<= balance`, ≤ 2 decimal places |
| Card number | Digits only, length 13–19, passes Luhn |
| CVV | 3 digits (4 for Amex `34/37` BIN) |
| Expiry | Month 1–12, year sane, last day of expiry month ≥ today |

Local validation catches the obvious failures before we burn an API request. The remote API is the source of truth for everything else (and for genuinely invalid card BINs that pass Luhn).

---

## 6. PII and sensitive data handling

| Datum | Storage rule |
|---|---|
| DOB / Aadhaar / Pincode | Held in `account_data` only for comparison. Never echoed to the user. |
| Full card number | Held in `CollectedData` until the payment API call returns; then **immediately wiped**. |
| CVV | Same as card number. |
| Conversation history | Card and CVV are masked **at write time** (`****1234`, `***`) before storage. |
| Logs | All log records pass through a redaction filter; PAN and CVV patterns are masked. |

Critically, the conversation history shipped to the responder LLM contains only redacted text. No raw PAN ever leaves the agent except in the single `PaymentAPIClient.process_payment` call.

---

## 7. Failure taxonomy

```
PaymentAgentError
├── APIError
│   ├── APITimeoutError        retryable (handled by tenacity)
│   ├── APINetworkError        retryable (handled by tenacity)
│   ├── AccountNotFoundError   user-fixable
│   └── PaymentDeclinedError   carries .error_code
│       ├── invalid_card       user-fixable → re-ask card number
│       ├── invalid_cvv        user-fixable → re-ask CVV
│       ├── invalid_expiry     user-fixable → re-ask expiry
│       ├── insufficient_balance user-fixable → re-ask amount
│       ├── invalid_amount     user-fixable → re-ask amount
│       └── unknown            terminal → close, escalate
└── VerificationError          internal signaling
```

Per error code, the FSM clears the relevant collected fields so the user re-enters them.

Idempotency keys on `process-payment` ensure that a transient retry never causes a double charge.

---

## 8. Deliberate tradeoffs

| Choice | Why | Cost |
|---|---|---|
| Two LLM calls per turn | Cleaner separation, easier eval | Extra latency + cost |
| Free-text → JSON extraction (instead of strict tools API) | Simpler, model-agnostic | Slightly more brittle on weird inputs |
| Real API in e2e tests | Catches contract drift | Tests are slower and require network |
| Case-sensitive name match | Spec mandate | UX friction (`nithin jain` rejected) |
| Per-error-code field clearing | User-friendly retries | More code paths to maintain |
| In-memory state (no persistence) | Spec scope | Process restart loses session |

---

## 9. What I'd add with more time

1. **Structured-output JSON schema** via the OpenAI tools API (currently free-form `json_object`).
2. **Single-LLM-call mode** with function calling, gated by a feature flag.
3. **Persistent session store** (Redis) so a process restart can resume.
4. **HTTP idempotency at lookup** as well, with a short TTL cache.
5. **Async I/O** (`httpx` + FastAPI) for concurrent sessions.
6. **Prompt versioning** — append a hash to log records to correlate behavior with prompt version.
7. **Eval harness with golden traces** — a corpus of conversations whose `agent.state` evolution is the ground truth.
8. **OpenTelemetry traces** spanning extraction → FSM → API → responder for production observability.
