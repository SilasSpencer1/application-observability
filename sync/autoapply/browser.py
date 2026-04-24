from __future__ import annotations
from contextlib import contextmanager
from typing import Iterator, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext


@contextmanager
def browser_harness(headless: bool = True) -> "Iterator[BrowserContext]":
    """Yield a Playwright browser context with the browser closed on exit.

    The caller is responsible for opening pages from the context and closing
    them when done. The context (and its underlying browser) is cleaned up
    even if the adapter raises, so a crash mid-apply does not leak Chromium.

    headless=True is the default because auto-apply is meant to run
    unattended. Set False when you want to watch the browser drive through
    forms, usually during development.
    """
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            context = browser.new_context(
                accept_downloads=False,
                viewport={"width": 1280, "height": 900},
            )
            try:
                yield context
            finally:
                context.close()
        finally:
            browser.close()
