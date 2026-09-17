"""01の出力形式設定に応じて、成果物MDを `common/report_export` で変換する橋渡し.

背景: `run.py review` を直接叩くと check-report.html が更新されない不具合があった。
HTMLへの変換指示がAIエージェント向けの案内にしか書かれておらず、Python側（run.py）には
無かったため、AIエージェントを経由しない直接実行では変換されなかった。

置き場所の判断:
- 元々は02（計測設計）の `scripts/` 配下にあったが、client_id を持ちレポートMDを
  クライアントへ渡す他のエージェントからも同じ橋渡しを使えるようにするため、
  共通ツール置き場 `common/` へ移した。`common/ga4_fetch`（GA4取得の共通実装）・
  `common/report_index`（index.html生成の共通実装）と同じ「テーマ横断の共通処理は
  common/ 配下に1箇所だけ置き、各パッケージは自分の `sys.path` にこのフォルダを
  足して参照する」という既存の作法に合わせている。
- ここに置いても増える依存は「呼び出し側が sys.path にこのフォルダを足すこと」だけ
  （import自体は標準ライブラリのみで完結し、report_export本体は subprocess で
  別プロセス起動するため、pip の依存関係は増えない）。01（context_store）も
  実行時に見つかれば読むだけで、無ければ諦めて続行する（import-timeの必須依存にしない）。
- 現時点でこの橋渡しを実際に呼ぶのは02の run.pyだけ（03・04・05・06・07 はAIエージェントが
  run.md/プロンプトに従ってMarkdownを書く形で、Pythonの run.py を持たない。そちらの
  変換導線は各機能の正本と `common/report_export/README.md` 側の話であり、このモジュールの対象外）。
  2つ目の呼び出し元ができたときに、この置き場所がそのまま使える状態にしてある。

設計判断:
- `common/report_export` への依存は、呼び出し元パッケージの仮想環境に追加しない。
  各パッケージが独立した仮想環境を持つ設計（README/docs/standard-run-order.md）を
  保つため、`subprocess` で `uv run python -m report_export` を別プロセスとして呼ぶ。
- 今回の `output_formats` が指定されれば保存済み形式より優先し、空リストなら自動変換を抑制する。
- 01の設定はここでは「読むだけ」。`output_formats` が未設定(None)でも、この場から
  対話で聞くことはしない（対話で1回だけ聞く役割は、各機能の正本に従う現在のAIエージェントにある。
  docs/standard-run-order.md §4-2）。ブランド設定とGoogle書き込み先は保存済み設定から読む。
- `gdoc`/`gsheet` は「変換」ではなく既存のGoogleドキュメント/スプレッドシートへの
  書き込みで、書き込み先URL（`google_doc_url`/`google_sheet_url`）が無いと成立しない
  （サービスアカウントは自分でファイルを作れないため。詳細は
  `context_store.loader.ClientContext.google_doc_url` のdocstring参照）。
  URLが無い場合はその形式だけを静かに諦める（他の形式の変換は続ける）が、
  「無かったことにする」のではなく `ExportOutcome.warnings` に理由を積んで呼び出し元へ返す。
- 変換に失敗しても例外を投げない。レポート本体（MD）の生成が成功している以上、
  変換の失敗でコマンド全体を失敗扱いにしない（理由を標準エラーに出し、`warnings` にも
  積んで続行する）。呼び出し元は「MDは出た、変換は失敗した」を利用者に区別して示せる。
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# common/report_export_bridge/report_export_bridge.py から見て2階層上がリポジトリルート
# （common/report_export_bridge/ -> common/ -> リポジトリルート）。01のconfig.pyが持つ
# REPO_ROOTと同じ値になる想定（このモジュールは特定パッケージのconfigに依存しない）。
REPO_ROOT = Path(__file__).resolve().parents[2]

# report_export が実際に出力しうる拡張子（stdout から生成ファイルのパスを拾うための判定用）。
_KNOWN_EXTS = {"html", "pdf", "docx", "xlsx"}

# output_formats のうち、書き込み先URLが無いと成立しない値 → ClientContext のプロパティ名。
# 01側の `context_store.schema.OUTPUT_FORMAT_URL_KEYS` と同じ対応関係（キー名がそのまま
# `ClientContext` のプロパティ名にもなっている）。01の実装をここでimportして依存を増やす
# ほどではないため、対応関係だけをこちらにも持つ（値は"profile.yamlのキー名"= "プロパティ名"
# で01側と共通なので、ずれたらどちらかを直すときにもう一方に気づける）。
_URL_REQUIRED_FORMATS = {
    "gdoc": "google_doc_url",
    "gsheet": "google_sheet_url",
}


@dataclass
class ExportOutcome:
    """`export_if_configured` の戻り値.

    - `generated`: 実際に書き出せた先の一覧。ローカルファイルは絶対パスの `Path`、
      Googleドキュメント/スプレッドシートは書き込み先の `str`（URL）。
    - `warnings`: 01に出力設定はあったが、書き出しが一部または全部できなかった理由
      （日本語の一言）。空なら「設定通りに全部書き出せた」または「そもそも設定が無い」。
      呼び出し元はこれを見て「MDは出た、○○への書き出しは失敗した」を利用者に示せる。
    """

    generated: list[Path | str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _load_output_prefs(
    client_id: str,
) -> tuple[list[str] | None, str | None, str | None, dict[str, str | None]]:
    """01から (output_formats, accent_color, logo_path, {format: url}) を読む。

    01が無い／読めない場合は (None, None, None, {})。kpi_coverage.load_client_profile と
    同じ「無ければ諦めて続行する」方針に合わせている。
    """
    ctx_src = REPO_ROOT / "01_context_management" / "src"
    if not ctx_src.exists():
        return None, None, None, {}
    try:
        if str(ctx_src) not in sys.path:
            sys.path.insert(0, str(ctx_src))
        from context_store.loader import load_context  # type: ignore

        ctx = load_context(client_id)
        urls = {fmt: getattr(ctx, attr, None) for fmt, attr in _URL_REQUIRED_FORMATS.items()}
        return ctx.output_formats, ctx.accent_color, ctx.logo_path, urls
    except Exception as e:
        print(
            f"[report_export_bridge] サイト設定の読み込みに失敗しました（無視して続行）: {e}",
            file=sys.stderr,
        )
        return None, None, None, {}


def export_if_configured(
    md_paths: list[Path], client_id: str, *, output_formats: list[str] | None = None
) -> ExportOutcome:
    """01に既定の出力形式が設定されていれば、対象MDを report_export で変換する。

    - 引数がNoneなら保存済み形式、空リストなら今回だけMDのみ。明示した形式は既定より優先する。
      引数も保存済み形式も無ければ何もしない。保存済み設定は更新しない。
    - 存在しないMDパスはスキップする。
    - `gdoc`/`gsheet` が指定されていても書き込み先URLが01に無ければ、その形式だけを
      諦めて `warnings` に理由を積む（他の形式の変換は続ける）。
    - 1件でも変換に失敗しても他のファイルの変換は続ける。失敗は標準エラーに理由を出し、
      `warnings` にも積む（例外は投げない。呼び出し元のレポート生成成功は守る）。

    戻り値: `ExportOutcome`（実際に生成できた先の一覧と、途中で諦めた理由の一覧）。
    """
    # Noneは保存済み設定、空リストは今回だけMDのみ。既定設定は更新しない。
    if output_formats == []:
        return ExportOutcome()
    formats, accent_color, logo_path, urls = _load_output_prefs(client_id)
    if output_formats is not None:
        formats = output_formats
    if formats and any(f not in {*_KNOWN_EXTS, 'gdoc', 'gsheet'} for f in formats):
        return ExportOutcome(warnings=['未対応の出力形式があるため変換をスキップしました'])
    if not formats:
        return ExportOutcome()

    report_export_dir = REPO_ROOT / "common" / "report_export"
    if not report_export_dir.exists():
        print(
            "[report_export_bridge] common/report_export が見つからないため変換をスキップしました。",
            file=sys.stderr,
        )
        return ExportOutcome()

    # gdoc/gsheetは書き込み先URLが無いと成立しないため、無ければこの実行では諦める
    # （設定自体は01に残したまま。他の形式の変換は続ける）。
    outcome = ExportOutcome()
    effective_formats: list[str] = []
    gdoc_url: str | None = None
    gsheet_url: str | None = None
    for fmt in formats:
        url_attr = _URL_REQUIRED_FORMATS.get(fmt)
        if url_attr is None:
            effective_formats.append(fmt)
            continue
        url = urls.get(fmt)
        if not url:
            outcome.warnings.append(
                f"{fmt} への書き出しが01に設定されていますが、書き込み先URL（{url_attr}）が"
                "未設定のためスキップしました。"
            )
            continue
        effective_formats.append(fmt)
        if fmt == "gdoc":
            gdoc_url = url
        elif fmt == "gsheet":
            gsheet_url = url

    if not effective_formats:
        return outcome

    to_arg = ",".join(effective_formats)
    for md_path in md_paths:
        if not md_path.is_file():
            continue
        cmd = [
            "uv", "run", "python", "-m", "report_export",
            str(md_path.resolve()),
            "--to", to_arg,
            "--output-dir", str(md_path.resolve().parent),
        ]
        if accent_color:
            cmd += ["--accent-color", accent_color]
        if logo_path:
            cmd += ["--logo", logo_path]
        if gdoc_url:
            cmd += ["--gdoc", gdoc_url]
        if gsheet_url:
            cmd += ["--gsheet", gsheet_url]

        try:
            result = subprocess.run(
                cmd,
                cwd=report_export_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        except OSError as e:
            msg = f"{md_path.name} の変換に失敗しました（無視して続行）: {e}"
            print(f"[report_export_bridge] {msg}", file=sys.stderr)
            outcome.warnings.append(msg)
            continue

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            msg = f"{md_path.name} の変換に失敗しました（無視して続行）: {detail}"
            print(f"[report_export_bridge] {msg}", file=sys.stderr)
            outcome.warnings.append(msg)
            continue

        for line in result.stdout.splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            if candidate.startswith("http://") or candidate.startswith("https://"):
                # gdoc/gsheetの書き込み先URL（ローカルファイルを生成しないため、Pathでなく文字列のまま積む）。
                outcome.generated.append(candidate)
                continue
            ext = Path(candidate).suffix.lstrip(".").lower()
            if ext in _KNOWN_EXTS:
                outcome.generated.append(Path(candidate))

    return outcome
