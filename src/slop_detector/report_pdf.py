"""PDF output: the HTML report printed to A4 by an installed Chromium-based
browser in headless mode (docs/REPORTS.md 6).

Nothing is downloaded or installed. The browser runs with a throwaway
profile, no extensions and no background networking; the page itself allows
no network request (its Content Security Policy). A PDF is written to the
target path only after the browser produced a complete one.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

# A browser to use instead of the search below (a path to chrome / msedge /
# chromium).
BROWSER_ENV = "SLOP_PDF_BROWSER"
_NAMES = (
    "chrome",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "msedge",
    "microsoft-edge",
)
_WINDOWS = (
    ("PROGRAMFILES", "Google/Chrome/Application/chrome.exe"),
    ("PROGRAMFILES(X86)", "Google/Chrome/Application/chrome.exe"),
    ("LOCALAPPDATA", "Google/Chrome/Application/chrome.exe"),
    ("PROGRAMFILES(X86)", "Microsoft/Edge/Application/msedge.exe"),
    ("PROGRAMFILES", "Microsoft/Edge/Application/msedge.exe"),
)
_MAC = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)
# Measured 2026-11-08 on the development machine: the 62-page report of a
# 215-file project printed in under 10 s; 180 s leaves room for slower machines.
RENDER_TIMEOUT_S = 180


class PdfUnavailableError(RuntimeError):
    """ENV_BLOCKED: no Chromium-based browser to print with."""


class PdfFailedError(RuntimeError):
    """The browser ran and did not produce a complete PDF."""


def find_browser() -> Optional[str]:
    """The browser to print with: $SLOP_PDF_BROWSER, then one on PATH, then
    the usual install locations."""
    chosen = os.environ.get(BROWSER_ENV)
    if chosen:
        return chosen if Path(chosen).is_file() else None
    for name in _NAMES:
        found = shutil.which(name)
        if found:
            return found
    candidates = [str(Path(os.environ[var]) / rel) for var, rel in _WINDOWS if os.environ.get(var)]
    for path in candidates + list(_MAC):
        if Path(path).is_file():
            return path
    return None


def unavailable_message() -> str:
    return (
        "ENV_BLOCKED: PDF output needs an installed Chromium-based browser (Chrome, Edge or "
        f"Chromium) and none was found; set {BROWSER_ENV} to its path. Nothing was written. "
        "Alternative: write the HTML report (-o report.html) and print it to PDF from a browser; "
        "it carries the same A4 layout."
    )


def _command(browser: str, page: Path, out: Path, profile: Path) -> List[str]:
    return [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-sync",
        f"--user-data-dir={profile}",
        "--no-pdf-header-footer",
        "--print-to-pdf-no-header",
        f"--print-to-pdf={out}",
        page.as_uri(),
    ]


def write_pdf(page_html: str, target: str) -> None:
    """Print `page_html` to the PDF file `target`, or raise PdfUnavailableError /
    PdfFailedError leaving `target` untouched."""
    browser = find_browser()
    if browser is None:
        raise PdfUnavailableError(unavailable_message())
    with tempfile.TemporaryDirectory(prefix="slop-pdf-") as tmp:
        work = Path(tmp)
        page, out = work / "report.html", work / "report.pdf"
        page.write_text(page_html, encoding="utf-8")
        try:
            subprocess.run(
                _command(browser, page, out, work / "profile"),
                capture_output=True,
                timeout=RENDER_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PdfFailedError(
                f"the browser did not finish printing the PDF ({type(exc).__name__})"
            ) from exc
        if not out.is_file() or not out.read_bytes()[:5] == b"%PDF-":
            raise PdfFailedError("the browser ran but wrote no PDF")
        shutil.copyfile(out, target)
