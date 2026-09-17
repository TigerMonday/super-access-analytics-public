from pathlib import Path

import pytest

from report_export.markdown_utils import inline_images_as_base64, render_html_body


def test_raw_script_and_event_handlers_are_removed() -> None:
    html = render_html_body(
        '<script>alert(1)</script><img src="x" onerror="alert(2)">'
        '<a href="javascript:alert(3)">link</a>'
    )

    assert "<script" not in html
    assert "onerror" not in html
    assert "javascript:" not in html
    assert "link" in html


def test_data_url_is_allowed_for_images_but_not_links() -> None:
    html = render_html_body(
        '<a href="data:text/html,unsafe">open</a>'
        '<img src="data:image/png;base64,AA==" alt="safe">'
    )

    assert "data:text/html" not in html
    assert "data:image/png;base64,AA==" in html


def test_image_outside_report_directory_is_not_embedded(tmp_path: Path) -> None:
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"not really an image")

    result = inline_images_as_base64("![secret](../secret.png)", report_dir)

    assert "base64" not in result
    assert "not really an image" not in result
    assert "画像を埋め込めません" in result


def test_local_image_is_embedded(tmp_path: Path) -> None:
    image = tmp_path / "chart.png"
    image.write_bytes(b"png bytes")

    result = inline_images_as_base64("![chart](chart.png)", tmp_path)

    assert "data:image/png;base64," in result


@pytest.mark.parametrize("url", [
    "https://example.invalid/pixel?private=synthetic",
    "http://127.0.0.1/private",
    "HTTPS://example.invalid/pixel",
    "//example.invalid/pixel",
])
def test_remote_images_cannot_make_requests(url: str) -> None:
    for md in (f"![remote]({url})", f'<img src="{url}" alt="remote">'):
        html = render_html_body(md)
        assert "src=" not in html
        assert "remote" in html


def test_regular_links_are_preserved() -> None:
    html = render_html_body("[source](https://example.invalid/source)")
    assert 'href="https://example.invalid/source"' in html
