"""export_pdf_from_html のエラーハンドリングのテスト。

Playwright の Chromium が未取得のときに出る "Executable doesn't exist" を、
`[report_export] エラー: ...` として素直に表示できる RuntimeError に変換できているかを確認する
（RuntimeError は __main__.main() の except節が拾える型。playwright.sync_api.Error は拾えないため
未対策だと生のトレースバックで落ちる）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from playwright.sync_api import Error as PlaywrightError

from report_export.pdf_export import export_pdf_from_html


class _FakeChromium:
    def __init__(self, error: Exception):
        self._error = error

    def launch(self):
        raise self._error


class _FakeBrowserType:
    def __init__(self, error: Exception):
        self.chromium = _FakeChromium(error)


class _FakePlaywrightContext:
    def __init__(self, error: Exception):
        self._error = error

    def __enter__(self):
        return _FakeBrowserType(self._error)

    def __exit__(self, *exc_info):
        return False


def test_missing_chromium_raises_runtime_error_with_install_command(monkeypatch, tmp_path: Path):
    error = PlaywrightError(
        "Executable doesn't exist at /fake/path/chromium\n"
        "Looks like Playwright Browsers are not installed. Please run:\n"
        "    playwright install"
    )
    monkeypatch.setattr(
        "report_export.pdf_export.sync_playwright",
        lambda: _FakePlaywrightContext(error),
    )

    with pytest.raises(RuntimeError) as exc_info:
        export_pdf_from_html("<html></html>", tmp_path / "out.pdf")

    message = str(exc_info.value)
    assert "uv run playwright install chromium" in message
    assert "common/report_export" in message


def test_other_playwright_launch_error_is_wrapped_too(monkeypatch, tmp_path: Path):
    error = PlaywrightError("何らかの起動エラー")
    monkeypatch.setattr(
        "report_export.pdf_export.sync_playwright",
        lambda: _FakePlaywrightContext(error),
    )

    with pytest.raises(RuntimeError) as exc_info:
        export_pdf_from_html("<html></html>", tmp_path / "out.pdf")

    assert "何らかの起動エラー" in str(exc_info.value)


def test_pdf_blocks_requests_before_loading_html(monkeypatch, tmp_path: Path):
    """画像・CSSを含むHTMLでも、印刷前に全リクエストが遮断される。"""
    page = Mock()
    browser = Mock()
    browser.new_page.return_value = page
    context = Mock()
    context.__enter__ = Mock(return_value=SimpleNamespace(
        chromium=SimpleNamespace(launch=lambda: browser),
    ))
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr("report_export.pdf_export.sync_playwright", lambda: context)

    def load_html(*args, **kwargs):
        pattern, handler = page.route.call_args.args
        assert pattern == "**/*"
        for url in ("https://example.invalid/pixel", "http://127.0.0.1/private"):
            route = Mock()
            route.request.url = url
            handler(route)
            route.abort.assert_called_once_with()
            route.continue_.assert_not_called()

    page.set_content.side_effect = load_html
    page.evaluate.return_value = []
    export_pdf_from_html('<img src="https://example.invalid/pixel">', tmp_path / "out.pdf")
    browser.new_page.assert_called_once_with(service_workers="block")
    page.wait_for_function.assert_called_once_with(
        "document.body.dataset.slidesReady === 'true'", timeout=10_000
    )
    page.pdf.assert_called_once()
    pdf_kwargs = page.pdf.call_args.kwargs
    assert pdf_kwargs["width"] == "13.333333in"
    assert pdf_kwargs["height"] == "7.5in"
    assert pdf_kwargs["prefer_css_page_size"] is True
    assert pdf_kwargs["display_header_footer"] is False
    browser.close.assert_called_once()


def test_pdf_stops_when_a_semantic_block_does_not_fit(monkeypatch, tmp_path: Path):
    page = Mock()
    page.evaluate.return_value = ["巨大な表"]
    browser = Mock()
    browser.new_page.return_value = page
    context = Mock()
    context.__enter__ = Mock(return_value=SimpleNamespace(
        chromium=SimpleNamespace(launch=lambda: browser),
    ))
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr("report_export.pdf_export.sync_playwright", lambda: context)

    with pytest.raises(RuntimeError, match="巨大な表"):
        export_pdf_from_html("<html></html>", tmp_path / "out.pdf")

    page.pdf.assert_not_called()
    browser.close.assert_called_once()
