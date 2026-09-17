"""Markdown読み込み・画像embed・HTML本文生成のユーティリティ。"""

from __future__ import annotations

import base64
import mimetypes
import re
import sys
from pathlib import Path

import markdown as md_lib
import nh3

# 画像参照 ![alt](path "title") を検出する正規表現。
# 既にhttp(s)/dataスキームのものは対象外。
_IMAGE_RE = re.compile(
    r'!\[([^\]]*)\]\(\s*(?!https?://|data:)([^)\s]+)(\s+"[^"]*")?\s*\)'
)

_MD_EXTENSIONS = [
    "extra",       # tables, fenced_code, footnotes, def_list等をまとめて含む
    "sane_lists",  # 番号付きリストの意図しない再開を防ぐ
    "toc",         # 見出しにid付与（PDF内リンク等の将来拡張用）
]

_IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
_MAX_IMAGE_BYTES = 10 * 1024 * 1024

# Markdown が生成する要素と、本リポジトリのレポートで使用する要素だけを許可する。
# イベント属性・script/style・未知のURLスキームは nh3 が除去する。
_SAFE_TAGS = {
    "a", "abbr", "blockquote", "br", "code", "dd", "del", "details", "div",
    "dl", "dt", "em", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "img",
    "kbd", "li", "ol", "p", "pre", "s", "small", "span", "strong", "sub",
    "summary", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}
_SAFE_ATTRIBUTES = {
    "a": {"href", "title"},
    "div": {"class"},
    "img": {"alt", "src", "title"},
    "ol": {"start"},
    "td": {"align", "colspan", "rowspan"},
    "th": {"align", "colspan", "rowspan"},
    "*": {"id", "class"},
}


def _filter_attribute(tag: str, attribute: str, value: str) -> str | None:
    """画像は埋め込みだけに限定し、閲覧・PDF化時の外部通信を防ぐ。"""
    normalized = value.strip().lower()
    if tag == "img" and attribute == "src":
        # Markdown のローカル画像は前段で検証・埋め込み済み。
        # URL の大小文字、//host、raw HTML の画像も同じ制約で扱う。
        return value if normalized.startswith("data:image/") else None
    if normalized.startswith("data:"):
        return None
    return value


def read_markdown(path: Path) -> str:
    """Markdownファイルを読み込む(UTF-8前提。BOM付きも許容)。"""
    return path.read_text(encoding="utf-8-sig")


def inline_images_as_base64(md_text: str, base_dir: Path) -> str:
    """相対パスの画像参照をbase64 data URIへ差し替える。

    ファイルが見つからない場合はそのまま残し、標準エラーに警告を出す
    (レポート生成自体は止めない)。
    """

    def _replace(m: re.Match) -> str:
        alt, rel_path, title = m.group(1), m.group(2), m.group(3) or ""
        root = base_dir.resolve()
        img_path = (root / rel_path).resolve()
        try:
            img_path.relative_to(root)
        except ValueError:
            print(f"[report_export] 警告: 基準フォルダ外の画像は埋め込みません: {rel_path}", file=sys.stderr)
            return f"`[画像を埋め込めません: {alt or rel_path}]`"
        if not img_path.is_file():
            print(f"[report_export] 警告: 画像が見つかりません: {rel_path}", file=sys.stderr)
            return m.group(0)
        if img_path.suffix.lower() not in _IMAGE_SUFFIXES:
            print(f"[report_export] 警告: 許可されていない画像形式です: {rel_path}", file=sys.stderr)
            return f"`[画像を埋め込めません: {alt or rel_path}]`"
        if img_path.stat().st_size > _MAX_IMAGE_BYTES:
            print(f"[report_export] 警告: 画像が10MBを超えています: {rel_path}", file=sys.stderr)
            return f"`[画像を埋め込めません: {alt or rel_path}]`"
        mime, _ = mimetypes.guess_type(str(img_path))
        if not mime or not mime.startswith("image/"):
            print(f"[report_export] 警告: 画像として判定できません: {rel_path}", file=sys.stderr)
            return f"`[画像を埋め込めません: {alt or rel_path}]`"
        data = base64.b64encode(img_path.read_bytes()).decode("ascii")
        return f'![{alt}](data:{mime};base64,{data}{title})'

    return _IMAGE_RE.sub(_replace, md_text)


def render_html_body(md_text: str) -> str:
    """MarkdownをHTML断片(bodyの中身)に変換する。"""
    rendered = md_lib.markdown(md_text, extensions=_MD_EXTENSIONS, output_format="html5")
    return nh3.clean(
        rendered,
        tags=_SAFE_TAGS,
        attributes=_SAFE_ATTRIBUTES,
        attribute_filter=_filter_attribute,
        url_schemes={"data", "http", "https", "mailto"},
        # グラフ指定は Markdown 内の `<!-- chart:... -->` コメントを使う。
        # コメント自体は実行されず、後段の designify_body() が安全な SVG に置換する。
        strip_comments=False,
    )


_H1_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)


def extract_title_and_strip(md_text: str, fallback: str) -> tuple[str, str]:
    """タイトルを抽出し、ヘッダーで表示済みの先頭H1を本文から取り除く。

    見出しを2回表示しない(ページヘッダーと本文冒頭)ための処理。
    先頭H1以外の見出しはそのまま残す。
    """
    m = _H1_RE.search(md_text)
    if not m:
        return fallback, md_text
    title = m.group(1).strip()
    stripped = md_text[: m.start()] + md_text[m.end():]
    return title, stripped
