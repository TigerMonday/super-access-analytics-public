"""report_export CLI — Markdownレポートを HTML/PDF/Word/Excel/Googleドキュメント/
Googleスプレッドシートへ変換・書き出しする。

使い方:
    uv run python -m report_export <input.md> --to html,pdf,docx,xlsx
    uv run python -m report_export <input.md> --to all
    uv run python -m report_export <input.md> --to html --output-dir /path/to/out

    # 既存のGoogleドキュメント/スプレッドシートへ書き出す(新規ファイルの自動作成はしない。
    # gdoc_export.py/gsheet_export.pyのモジュールdocstring参照)
    uv run python -m report_export <input.md> --to gdoc --gdoc "https://docs.google.com/document/d/xxxx/edit"
    uv run python -m report_export <input.md> --to gsheet --gsheet "https://docs.google.com/spreadsheets/d/xxxx/edit"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import accent_color
from .docx_export import export_docx
from .gdoc_export import export_gdoc
from .gsheet_export import export_gsheet
from .html_export import build_html, export_html
from .index_refresh import refresh_report_indexes, report_index_paths
from .markdown_utils import read_markdown
from .pdf_export import export_pdf_from_html
from .visual_contract import validate_visual_contract
from .xlsx_export import export_xlsx

# Windows + Git Bash等では既定の画面エンコーディングがUTF-8にならず、日本語の
# 表示だけが文字化けすることがある（ファイル自体はUTF-8で正しく書かれている）。
# 明示的にUTF-8へ揃えて防ぐ。reconfigure非対応の環境（一部のリダイレクト等）では
# 何もしない（元の表示に戻るだけで、実行そのものは失敗させない）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ALL_FORMATS = ["html", "pdf", "docx", "xlsx"]
# gdoc/gsheetは書き込み先(既存ファイルのURL)を毎回明示させる方針のため、'--to all'には
# 含めない(URLを補完しようがないため。resolve_formatsでは選択肢として受け付ける)。
GOOGLE_FORMATS = ["gdoc", "gsheet"]
VALID_FORMATS = ALL_FORMATS + GOOGLE_FORMATS

# --accent-color / --logo を明示しない場合に見るフォールバック環境変数。
# report_export自体は特定のエージェント専用ではない汎用CLIなので、呼び出し側
# (例: SAAの01コンテキストストアに保存したブランド設定を読む run.md 側)が
# クライアントごとの値をここに詰めて渡す想定。report_export自身はcontext_store等を
# importしない(汎用性を保つため、値の受け渡しはCLI引数/環境変数だけに絞る)。
ENV_ACCENT_COLOR = "REPORT_EXPORT_ACCENT_COLOR"
ENV_LOGO_PATH = "REPORT_EXPORT_LOGO_PATH"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="report_export",
        description="MarkdownレポートをHTML/PDF/Word(docx)/Excel(xlsx)へ変換する汎用CLI。",
    )
    parser.add_argument("input", type=Path, help="変換元のMarkdownファイル")
    parser.add_argument(
        "--to",
        required=True,
        help=(
            "出力形式をカンマ区切りで指定(html,pdf,docx,xlsx,gdoc,gsheet)。"
            "'all'でgdoc/gsheetを除く全形式(書き込み先URLを都度指定するgdoc/gsheetは"
            "'all'に含まれない。個別に指定すること)。"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="出力先ディレクトリ(既定: 入力Markdownと同じディレクトリ)",
    )
    parser.add_argument(
        "--accent-color",
        default=None,
        help=(
            "差し色(ゴールド)を自社ブランドカラーに置き換える。6桁HEXで指定"
            "(例: --accent-color '#1D4ED8')。未指定なら既定のゴールドのまま。"
            f"環境変数 {ENV_ACCENT_COLOR} でも指定できる(この引数の方が優先)。"
        ),
    )
    parser.add_argument(
        "--logo",
        type=Path,
        default=None,
        help=(
            "ロゴSVGを差し替える(design_system/logo-placeholder.svg の代わりに使うファイルパス)。"
            f"環境変数 {ENV_LOGO_PATH} でも指定できる(この引数の方が優先)。"
        ),
    )
    parser.add_argument(
        "--gdoc",
        default=None,
        help=(
            "--to にgdocを含める場合、書き込み先の既存Googleドキュメントの"
            "URL(またはID)を指定する(必須。サービスアカウントは新規ファイルを作れないため"
            "自動作成はしない。事前に対象ドキュメントを用意し、認証ファイルのclient_emailの"
            "値を編集者として共有しておくこと)。"
        ),
    )
    parser.add_argument(
        "--gdoc-heading",
        default=None,
        help=(
            "Googleドキュメント内で、このレポート用の区画を区切る見出し1のテキスト。"
            "未指定ならMarkdown先頭のH1(無ければファイル名)を使う。"
            "「メモ」は利用者が書き込む専用の区画のため指定できない(エラーで止まる)。"
        ),
    )
    parser.add_argument(
        "--gsheet",
        default=None,
        help=(
            "--to にgsheetを含める場合、書き込み先の既存Googleスプレッドシートの"
            "URL(またはID)を指定する(必須。gdocと同じ理由で自動作成はしない)。"
            "既存シートは変更せず、新しいシート(タブ)を追加する。"
        ),
    )
    return parser.parse_args(argv)


def resolve_accent_color(cli_value: str | None) -> str | None:
    """--accent-color と環境変数から、正規化済みHEX(または None)を決める。CLI引数を優先する。"""
    raw = cli_value or os.environ.get(ENV_ACCENT_COLOR)
    if not raw:
        return None
    return accent_color.normalize_hex(raw)  # 不正な形式は InvalidColorError(ValueErrorのサブクラス)


def resolve_logo_path(cli_value: Path | None) -> Path | None:
    """--logo と環境変数から、ロゴファイルのパス(または None)を決める。CLI引数を優先する。"""
    raw = cli_value or os.environ.get(ENV_LOGO_PATH)
    if not raw:
        return None
    path = Path(raw)
    if not path.is_file():
        raise FileNotFoundError(f"ロゴファイルが見つかりません: {path}")
    return path


def resolve_formats(to_arg: str) -> list[str]:
    if to_arg.strip().lower() == "all":
        return list(ALL_FORMATS)
    requested = [f.strip().lower() for f in to_arg.split(",") if f.strip()]
    seen: set[str] = set()
    ordered: list[str] = []
    for fmt in requested:
        if fmt not in VALID_FORMATS:
            raise ValueError(
                f"未対応の形式です: {fmt}（対応形式: {', '.join(VALID_FORMATS)}。PowerPointは対象外）"
            )
        if fmt not in seen:
            seen.add(fmt)
            ordered.append(fmt)
    if not ordered:
        raise ValueError("--to に有効な形式が指定されていません")
    return ordered


def run(
    input_path: Path,
    formats: list[str],
    output_dir: Path | None,
    *,
    accent_hex: str | None = None,
    logo_path: Path | None = None,
    gdoc_target: str | None = None,
    gdoc_heading: str | None = None,
    gsheet_target: str | None = None,
) -> list[Path | str]:
    if not input_path.is_file():
        raise FileNotFoundError(f"入力Markdownが見つかりません: {input_path}")

    md_text = read_markdown(input_path)
    out_dir = output_dir if output_dir is not None else input_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = input_path.stem

    # gdoc/gsheetはローカルファイルを生成しない(既存のGoogleドキュメント/スプレッドシートへの
    # 書き込みのみ)ため、generatedにはPathの代わりに書き込み先URL(文字列)を積む。
    generated: list[Path | str] = []
    generated_html: list[Path] = []

    # HTMLはPDFの元にもなるため、どちらかが要求されたら先に生成しておく。
    # accent_hex/logo_path はHTML/PDFにのみ効く(docx/xlsxはCSSが効かないため対象外。README参照)。
    full_html = None
    if "html" in formats or "pdf" in formats:
        full_html, _ = build_html(md_text, input_path, accent_hex=accent_hex, logo_path=logo_path)
        validate_visual_contract(input_path, full_html)

    if "html" in formats:
        out = out_dir / f"{stem}.html"
        out.write_text(full_html, encoding="utf-8")
        resolved_out = out.resolve()
        generated.append(resolved_out)
        generated_html.append(resolved_out)
        # HTMLが書けた時点で入口も揃える。後続のPDF等が失敗しても、すでに生成済みの
        # HTMLだけが一覧から漏れる状態を残さない。
        refresh_report_indexes(generated_html)

    if "pdf" in formats:
        out = out_dir / f"{stem}.pdf"
        export_pdf_from_html(full_html, out)
        resolved_out = out.resolve()
        generated.append(resolved_out)
        # PDFの副リンクをindex.htmlへ反映する。HTMLとPDFを同時生成した場合は、
        # HTML出力直後の安全側更新に続く2回目の更新になる。
        refresh_report_indexes([resolved_out])

    if "docx" in formats:
        out = out_dir / f"{stem}.docx"
        export_docx(input_path, out, md_text)
        generated.append(out.resolve())

    if "xlsx" in formats:
        out = out_dir / f"{stem}.xlsx"
        export_xlsx(input_path, out, md_text)
        generated.append(out.resolve())

    if "gdoc" in formats:
        url = export_gdoc(input_path, gdoc_target, md_text, heading=gdoc_heading)
        generated.append(url)

    if "gsheet" in formats:
        url = export_gsheet(input_path, gsheet_target, md_text)
        generated.append(url)

    return generated


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        formats = resolve_formats(args.to)
        accent_hex = resolve_accent_color(args.accent_color)
        logo_path = resolve_logo_path(args.logo)
        generated = run(
            args.input,
            formats,
            args.output_dir,
            accent_hex=accent_hex,
            logo_path=logo_path,
            gdoc_target=args.gdoc,
            gdoc_heading=args.gdoc_heading,
            gsheet_target=args.gsheet,
        )
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        print(f"[report_export] エラー: {e}", file=sys.stderr)
        return 1

    print("[report_export] 出力完了:")
    for path in generated:
        print(f"  {path}")
    local_paths = [path for path in generated if isinstance(path, Path)]
    for index_path in report_index_paths(local_paths):
        print(f"[report_export] 閲覧入口: {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
