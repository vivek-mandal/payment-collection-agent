"""HTTP client for the upstream payment-verification API.

Single class: PaymentAPIClient.
Handles connection pooling, exponential-backoff retries on transient failures,
idempotency keys on payment writes, and translation of HTTP responses into the
typed exception taxonomy defined in exceptions.py.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import requests
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from payment_agent.config import Settings, get_settings
from payment_agent.exceptions import (
    AccountNotFoundError,
    APIError,
    APINetworkError,
    APITimeoutError,
    PaymentDeclinedError,
)
from payment_agent.models import Account, CardDetails

log = logging.getLogger(__name__)


class PaymentAPIClient:
    """Resilient client for the verification + payment endpoints."""

    def __init__(self, settings: Settings | None = None) -> None:
        cfg = settings or get_settings()
        self._base_url = cfg.payment_api_base_url.rstrip("/")
        self._timeout = cfg.api_timeout_seconds
        self._max_retries = cfg.api_max_retries
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lookup_account(self, account_id: str) -> Account:
        """Raises AccountNotFoundError (404), APITimeoutError, APINetworkError, APIError."""
        log.info("lookup_account: %s", account_id)
        resp = self._post("/api/lookup-account", {"account_id": account_id})

        if resp.status_code == 200:
            return Account.model_validate(resp.json())
        if resp.status_code == 404:
            raise AccountNotFoundError(account_id)
        raise APIError(f"Unexpected status {resp.status_code} from lookup-account")

    def process_payment(
        self,
        account_id: str,
        amount: float,
        card: CardDetails,
        *,
        idempotency_key: str | None = None,
    ) -> str:
        """Returns transaction_id on success. Raises PaymentDeclinedError, APIError."""
        idem_key = idempotency_key or str(uuid.uuid4())
        payload: dict[str, Any] = {
            "account_id": account_id,
            "amount": round(float(amount), 2),
            "payment_method": {
                "type": "card",
                "card": {
                    "cardholder_name": card.cardholder_name,
                    "card_number": card.card_number,
                    "cvv": card.cvv,
                    "expiry_month": card.expiry_month,
                    "expiry_year": card.expiry_year,
                },
            },
        }
        log.info("process_payment: account=%s amount=%.2f idem=%s", account_id, payload["amount"], idem_key)

        resp = self._post("/api/process-payment", payload, headers={"Idempotency-Key": idem_key})

        try:
            data = resp.json()
        except ValueError as exc:
            raise APIError(f"Invalid JSON in payment response: {exc}") from exc

        if resp.status_code == 200 and data.get("success"):
            txn_id: str = data.get("transaction_id", "")
            log.info("process_payment: success txn=%s", txn_id)
            return txn_id

        error_code: str = data.get("error_code", "unknown_error")
        log.warning("process_payment: declined error_code=%s", error_code)
        raise PaymentDeclinedError(error_code)

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _post(
        self,
        path: str,
        json_body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        url = f"{self._base_url}{path}"

        @retry(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
            retry=retry_if_exception_type(
                (requests.exceptions.Timeout, requests.exceptions.ConnectionError)
            ),
            reraise=True,
        )
        def _do() -> requests.Response:
            return self._session.post(url, json=json_body, headers=headers, timeout=self._timeout)

        try:
            return _do()
        except requests.exceptions.Timeout as exc:
            log.error("api timeout: %s", url)
            raise APITimeoutError(f"Timeout calling {url}") from exc
        except requests.exceptions.ConnectionError as exc:
            log.error("api network error: %s — %s", url, exc)
            raise APINetworkError(f"Network error calling {url}: {exc}") from exc
        except RetryError as exc:
            raise APIError(f"Retries exhausted calling {url}") from exc
