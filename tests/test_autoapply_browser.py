import pytest

pytest.importorskip("playwright")
from sync.autoapply.browser import browser_harness


def test_browser_harness_yields_working_context():
    with browser_harness(headless=True) as ctx:
        page = ctx.new_page()
        page.set_content("<h1 id='hello'>hi</h1>")
        assert page.locator("#hello").inner_text() == "hi"


def test_browser_harness_closes_on_exception():
    # If the block raises, the context manager must still close the browser
    # (no leaked chromium process). We verify by entering again afterwards,
    # which would fail if the previous browser was still holding something.
    with pytest.raises(RuntimeError):
        with browser_harness(headless=True) as ctx:
            ctx.new_page().set_content("<div>ok</div>")
            raise RuntimeError("boom")

    # Second context after the first exited via exception should still work.
    with browser_harness(headless=True) as ctx:
        page = ctx.new_page()
        page.set_content("<div id='x'>after</div>")
        assert page.locator("#x").inner_text() == "after"
