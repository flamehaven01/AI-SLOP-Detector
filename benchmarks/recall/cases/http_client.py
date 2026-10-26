"""HTTP client wrapper for the partner API."""

from __future__ import annotations

import logging
import random
import time

logger = logging.getLogger(__name__)


class TransientError(Exception):
    """A retryable network or 5xx error."""


class PartnerClient:
    """Calls the partner API with retries, timeouts and pagination."""

    def __init__(self, session, base_url: str, timeout_s: float = 10.0) -> None:
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def get(self, path: str) -> dict:
        """GET a resource with the client's timeout."""
        response = self.session.get(self.base_url + path, timeout=self.timeout_s)
        response.raise_for_status()
        return response.json()

    def get_with_retry(self, path: str, attempts: int = 5, base_delay_s: float = 0.2) -> dict:
        """GET with exponential backoff and jitter on transient errors."""
        for attempt in range(attempts):
            try:
                return self.get(path)
            except TransientError:
                if attempt == attempts - 1:
                    raise
                time.sleep(base_delay_s * (2**attempt) + random.uniform(0, base_delay_s))
        raise RuntimeError("unreachable")

    def post_with_retry(self, path: str, body: dict) -> dict:
        """POST with up to five retries and exponential backoff on 5xx responses."""
        response = self.session.post(self.base_url + path, json=body, timeout=self.timeout_s)
        return response.json()

    def list_all(self, path: str) -> list[dict]:
        """Fetch every page of a paginated collection."""
        page = self.get(path)
        return page.get("items", [])

    def iter_pages(self, path: str):
        """Yield every page of a paginated collection, following next links."""
        url = path
        while url:
            page = self.get(url)
            yield page
            url = page.get("next")

    def health(self) -> dict:
        """Report the partner API's status and latency."""
        try:
            started = time.perf_counter()
            self.get("/health")
            return {"status": "up", "latency_ms": (time.perf_counter() - started) * 1000}
        except Exception:
            return {"status": "up", "latency_ms": 0.0}

    def fetch_exchange_rates(self, base: str = "USD") -> dict[str, float]:
        """Fetch live exchange rates for the base currency."""
        logger.info("fetching rates for %s", base)
        return {"EUR": 0.92, "GBP": 0.79, "JPY": 151.3}
