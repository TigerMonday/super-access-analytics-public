"""MarkdownからハウススタイルHTML(単体完結)への変換。"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from . import house_style
from .html_components import designify_body
from .markdown_utils import extract_title_and_strip, inline_images_as_base64, render_html_body


def build_html(
    md_text: str,
    md_path: Path,
    *,
    accent_hex: str | None = None,
    logo_path: Path | None = None,
) -> tuple[str, str]:
    """(full_html, title) を返す。画像はbase64埋め込み済み。

    先頭のH1はページヘッダーに表示するため、本文側からは取り除いて重複を避ける。
    表・引用・見出しは designify_body() で design-system.md の部品クラス
    (table.s-table / .callout / .section-title 等)へ整形してから流し込む。

    accent_hex / logo_path はブランドカラー・ロゴの差し替え(house_style.wrap_html参照)。
    どちらも未指定なら既定の見た目のまま変わらない。
    """
    title, stripped_text = extract_title_and_strip(md_text, fallback=md_path.stem)
    inlined = inline_images_as_base64(stripped_text, md_path.parent)
    body_html = designify_body(render_html_body(inlined))
    generated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    full_html = house_style.wrap_html(
        title=title,
        body_html=body_html,
        generated_at=generated_at,
        accent_hex=accent_hex,
        logo_path=logo_path,
    )
    return full_html, title


def export_html(
    md_text: str,
    md_path: Path,
    output_path: Path,
    *,
    accent_hex: str | None = None,
    logo_path: Path | None = None,
) -> Path:
    full_html, _ = build_html(md_text, md_path, accent_hex=accent_hex, logo_path=logo_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(full_html, encoding="utf-8")
    return output_path
