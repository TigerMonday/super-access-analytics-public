"""HTMLをPDF化する(Playwright chromiumでの印刷)。

HTMLとPDFの見た目を一致させるため、生成済みの単体HTML(house_style.wrap_htmlの
出力)をそのままブラウザ描画してPDF化する。画像はbase64埋め込み済みのため
外向き通信はブラウザでも遮断する。

レポートの1面はHTMLと同じ1280x720（16:9）で固定する。ページ番号と
CONFIDENTIALは各.report-sheetのCSSで描画し、画面とPDFで同じ位置に置く。
PDF化の前にブラウザ上の意味単位ページ分割が完了するまで待ち、1まとまりが
1面へ収まらない場合は切れたPDFを作らずエラーにする。
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

_PDF_WIDTH = "13.333333in"  # 1280 CSS px at 96dpi
_PDF_HEIGHT = "7.5in"       # 720 CSS px at 96dpi


def export_pdf_from_html(html_content: str, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except PlaywrightError as e:
            if "Executable doesn't exist" in str(e):
                raise RuntimeError(
                    "PDF変換に使うChromiumが未取得です。初回のみ次のコマンドで取得してください"
                    "（数百MBのダウンロード）:\n"
                    "  cd common/report_export\n"
                    "  uv run playwright install chromium"
                ) from e
            raise RuntimeError(f"PDF変換の起動に失敗しました: {e}") from e
        try:
            page = browser.new_page(service_workers="block")
            # HTMLの画像・CSS等に外部参照が残っても通信しない。
            # data URI はネットワークリクエストを必要としない。
            page.route("**/*", lambda route: route.abort())
            page.set_content(html_content, wait_until="load")
            page.wait_for_function(
                "document.body.dataset.slidesReady === 'true'",
                timeout=10_000,
            )
            overflow_labels = page.evaluate(
                "() => (window.__reportSlideState || {}).overflowLabels || []"
            )
            if overflow_labels:
                labels = "、".join(dict.fromkeys(str(label) for label in overflow_labels))
                raise RuntimeError(
                    "PDF変換を中止しました。1スライドに収まらない意味単位があります: "
                    f"{labels}。見出し・段落・図表のまとまりを原稿側で分けてください。"
                )
            page.pdf(
                path=str(output_path),
                width=_PDF_WIDTH,
                height=_PDF_HEIGHT,
                print_background=True,
                prefer_css_page_size=True,
                display_header_footer=False,
                margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            )
        finally:
            browser.close()
    return output_path
