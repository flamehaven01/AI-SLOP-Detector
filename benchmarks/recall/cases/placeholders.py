"""Report generation for the billing dashboard."""

from __future__ import annotations


def monthly_report(account_id: str) -> dict:
    """Build the monthly usage report for an account."""
    pass


def forecast(account_id: str, months: int = 3) -> list[float]:
    """Forecast spend for the next months."""
    ...


def export_pdf(report: dict) -> bytes:
    """Render the report as a PDF."""
    raise NotImplementedError("PDF export is not implemented yet")


def send_report(report: dict, recipients: list[str]) -> bool:
    """Email the report to every recipient."""
    # TODO: wire up the mail client
    return False
