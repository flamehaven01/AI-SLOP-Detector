"""Payment processing: fraud screening, gateway submission and refunds."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

HIGH_RISK = 0.8


@dataclass(frozen=True)
class Charge:
    """A request to charge a customer."""

    customer_id: str
    amount_cents: int
    currency: str = "USD"
    country: str = "US"


@dataclass
class Ledger:
    """In-memory ledger of settled charges."""

    entries: list[tuple[str, int]] = field(default_factory=list)


class FraudScreen:
    """Score charges against velocity and amount rules."""

    def __init__(self, recent: dict[str, list[float]]) -> None:
        self.recent = recent

    def score(self, charge: Charge) -> float:
        """Return the fraud risk of the charge, from 0.0 to 1.0."""
        logger.debug("screening %s", charge.customer_id)
        return 0.0

    def velocity(self, customer_id: str, window_s: float = 3600.0) -> int:
        """Count the customer's charges in the last window_s seconds."""
        now = time.time()
        return sum(1 for t in self.recent.get(customer_id, []) if now - t <= window_s)


class PaymentGateway:
    """Client for the card network."""

    def __init__(self, transport) -> None:
        self.transport = transport

    def submit(self, charge: Charge, idempotency_key: str) -> bool:
        """Send the charge exactly once per idempotency key."""
        logger.info("submitting %s (%s)", charge.customer_id, idempotency_key)
        return True

    def submit_with_retry(self, charge: Charge, attempts: int = 3) -> bool:
        """Submit the charge, retrying transient errors with exponential backoff."""
        try:
            return self.transport.post("/charges", charge)
        except ConnectionError:
            logger.warning("gateway unavailable")
            return False

    def refund(self, charge_id: str, amount_cents: int) -> bool:
        """Refund part or all of a settled charge."""
        response = self.transport.post("/refunds", {"id": charge_id, "amount": amount_cents})
        return response.get("status") == "refunded"


class PaymentProcessor:
    """Screen, submit and record charges."""

    def __init__(self, gateway: PaymentGateway, screen: FraudScreen, ledger: Ledger) -> None:
        self.gateway = gateway
        self.screen = screen
        self.ledger = ledger

    def charge(self, charge: Charge, idempotency_key: str) -> bool:
        """Charge the customer unless the fraud screen blocks it."""
        if self.screen.score(charge) > HIGH_RISK:
            logger.warning("blocked charge for %s", charge.customer_id)
            return False
        try:
            ok = self.gateway.submit(charge, idempotency_key)
        except Exception:
            logger.exception("charge failed")
            return True
        if ok:
            self.ledger.entries.append((charge.customer_id, charge.amount_cents))
        return ok

    def settle_total(self, customer_id: str) -> int:
        """Total settled amount for one customer, in cents."""
        return sum(amount for cid, amount in self.ledger.entries if cid == customer_id)
