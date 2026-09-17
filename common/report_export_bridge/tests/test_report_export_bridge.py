"""report_export_bridge.py のユニットテスト.

`run.py review` を直接実行してもチェックレポートのHTML等が更新されない不具合の
再発防止用。01の `preferences.output_formats` の3状態（未設定/空/設定済み）に応じて
変換するかどうかが正しく分岐し、変換の失敗が例外にならず後続処理を止めないことを検証する。
gdoc/gsheet（書き込み先URLが必須の形式）の分岐と、warnings への理由の積み方も検証する。
"""
from __future__ import annotations

import subprocess
import sys
import types

import pytest

import report_export_bridge as bridge


class _FakeContext:
    def __init__(
        self,
        output_formats,
        accent_color=None,
        logo_path=None,
        google_doc_url=None,
        google_sheet_url=None,
    ):
        self.output_formats = output_formats
        self.accent_color = accent_color
        self.logo_path = logo_path
        self.google_doc_url = google_doc_url
        self.google_sheet_url = google_sheet_url


def _install_fake_context_store(monkeypatch, ctx_or_error):
    """`context_store.loader.load_context` を差し替える（実ファイルは読まない）。

    `ctx_or_error` が Exception のサブクラスならそれを raise する load_context にする。
    """
    context_store_pkg = types.ModuleType("context_store")
    loader_mod = types.ModuleType("context_store.loader")

    def _load_context(client_id):
        if isinstance(ctx_or_error, type) and issubclass(ctx_or_error, Exception):
            raise ctx_or_error("boom")
        return ctx_or_error

    loader_mod.load_context = _load_context
    context_store_pkg.loader = loader_mod
    monkeypatch.setitem(sys.modules, "context_store", context_store_pkg)
    monkeypatch.setitem(sys.modules, "context_store.loader", loader_mod)


def _forbid_subprocess_run(monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("subprocess.run が呼ばれてはいけない場面で呼ばれた")

    monkeypatch.setattr(bridge.subprocess, "run", _fail)


def test_md_only_override_never_exports_saved_google_target(monkeypatch, tmp_path):
    _install_fake_context_store(monkeypatch, _FakeContext(["gdoc"], google_doc_url="https://docs.google.com/document/d/example/edit"))
    _forbid_subprocess_run(monkeypatch)
    result = bridge.export_if_configured([tmp_path / "report.md"], "sample", output_formats=[])
    assert result.generated == []


def test_explicit_format_replaces_saved_format_without_saving(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "_load_output_prefs", lambda _: (["gdoc"], None, None, {"gdoc": "https://docs.google.com/document/d/example/edit"}))
    report = tmp_path / "report.md"
    report.write_text("# Report", encoding="utf-8")
    calls = []
    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    monkeypatch.setattr(bridge.subprocess, "run", run)
    bridge.export_if_configured([report], "sample", output_formats=["html"])
    assert calls[0][calls[0].index("--to") + 1] == "html"
    assert "--gdoc" not in calls[0]


def test_no_conversion_when_context_store_missing(monkeypatch, tmp_path):
    """01_context_management自体が存在しないクローンでは何もしない."""
    monkeypatch.setattr(bridge, "REPO_ROOT", tmp_path)  # 01_context_management/src が無い
    _forbid_subprocess_run(monkeypatch)

    result = bridge.export_if_configured([tmp_path / "check-report.md"], "client-a")

    assert result.generated == []
    assert result.warnings == []


def test_no_conversion_when_output_formats_unset(monkeypatch, tmp_path):
    """output_formats が None（一度も聞いていない）なら変換しない."""
    _install_fake_context_store(monkeypatch, _FakeContext(output_formats=None))
    _forbid_subprocess_run(monkeypatch)

    result = bridge.export_if_configured([tmp_path / "check-report.md"], "client-a")

    assert result.generated == []
    assert result.warnings == []


def test_no_conversion_when_output_formats_empty(monkeypatch, tmp_path):
    """output_formats が空リスト（MDのみを明示済み）なら変換しない."""
    _install_fake_context_store(monkeypatch, _FakeContext(output_formats=[]))
    _forbid_subprocess_run(monkeypatch)

    result = bridge.export_if_configured([tmp_path / "check-report.md"], "client-a")

    assert result.generated == []
    assert result.warnings == []


def test_no_conversion_when_01_read_fails(monkeypatch, tmp_path):
    """01の読み込みで例外が起きても落とさず、変換しないだけにする."""
    _install_fake_context_store(monkeypatch, RuntimeError)
    _forbid_subprocess_run(monkeypatch)

    result = bridge.export_if_configured([tmp_path / "check-report.md"], "client-a")

    assert result.generated == []
    assert result.warnings == []


def test_skips_missing_md_paths_without_calling_subprocess(monkeypatch, tmp_path):
    """存在しないMDパスは subprocess を呼ばずにスキップする."""
    _install_fake_context_store(monkeypatch, _FakeContext(output_formats=["html"]))
    _forbid_subprocess_run(monkeypatch)

    result = bridge.export_if_configured([tmp_path / "does-not-exist.md"], "client-a")

    assert result.generated == []


def test_converts_when_formats_configured(monkeypatch, tmp_path):
    """output_formats が設定されていれば report_export を subprocess で呼び、生成物を返す."""
    _install_fake_context_store(monkeypatch, _FakeContext(output_formats=["html", "pdf"]))

    md_path = tmp_path / "check-report.md"
    md_path.write_text("# dummy", encoding="utf-8")
    html_out = md_path.with_suffix(".html")
    pdf_out = md_path.with_suffix(".pdf")

    calls = []

    def _fake_run(cmd, cwd, capture_output, text, encoding):
        calls.append(cmd)
        stdout = f"[report_export] 出力完了:\n  {html_out}\n  {pdf_out}\n"
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(bridge.subprocess, "run", _fake_run)

    result = bridge.export_if_configured([md_path], "client-a")

    assert result.generated == [html_out, pdf_out]
    assert result.warnings == []
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[:5] == ["uv", "run", "python", "-m", "report_export"]
    assert str(md_path.resolve()) in cmd
    assert "--to" in cmd and cmd[cmd.index("--to") + 1] == "html,pdf"
    assert "--output-dir" in cmd
    # ブランドカラー・ロゴが未設定なら付けない
    assert "--accent-color" not in cmd
    assert "--logo" not in cmd
    assert "--gdoc" not in cmd
    assert "--gsheet" not in cmd


def test_passes_accent_color_and_logo_when_set(monkeypatch, tmp_path):
    """01にブランドカラー・ロゴが設定されていれば --accent-color/--logo として渡す."""
    _install_fake_context_store(
        monkeypatch,
        _FakeContext(output_formats=["html"], accent_color="#1D4ED8", logo_path="/path/to/logo.svg"),
    )

    md_path = tmp_path / "check-report.md"
    md_path.write_text("# dummy", encoding="utf-8")

    calls = []

    def _fake_run(cmd, cwd, capture_output, text, encoding):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(bridge.subprocess, "run", _fake_run)

    bridge.export_if_configured([md_path], "client-a")

    cmd = calls[0]
    assert "--accent-color" in cmd and cmd[cmd.index("--accent-color") + 1] == "#1D4ED8"
    assert "--logo" in cmd and cmd[cmd.index("--logo") + 1] == "/path/to/logo.svg"


def test_conversion_failure_does_not_raise_and_continues_other_files(monkeypatch, tmp_path):
    """1件の変換が失敗しても例外を投げず、他のファイルの変換は続ける."""
    _install_fake_context_store(monkeypatch, _FakeContext(output_formats=["html"]))

    ok_md = tmp_path / "check-report.md"
    ok_md.write_text("# ok", encoding="utf-8")
    fail_md = tmp_path / "audit-matrix.md"
    fail_md.write_text("# fail", encoding="utf-8")
    ok_html = ok_md.with_suffix(".html")

    def _fake_run(cmd, cwd, capture_output, text, encoding):
        target = cmd[5]
        if target == str(fail_md.resolve()):
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="変換エラー")
        stdout = f"[report_export] 出力完了:\n  {ok_html}\n"
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(bridge.subprocess, "run", _fake_run)

    result = bridge.export_if_configured([fail_md, ok_md], "client-a")

    # 失敗したファイル分は含まれないが、例外は起きず成功したファイル分は返る
    assert result.generated == [ok_html]
    # 失敗の理由がwarningsに積まれ、呼び出し元が「MDは出た、変換は失敗した」を示せる
    assert len(result.warnings) == 1
    assert "audit-matrix.md" in result.warnings[0]
    assert "変換エラー" in result.warnings[0]


def test_conversion_oserror_does_not_raise(monkeypatch, tmp_path):
    """uv 自体が見つからない等の OSError でも例外を外へ漏らさない."""
    _install_fake_context_store(monkeypatch, _FakeContext(output_formats=["html"]))

    md_path = tmp_path / "check-report.md"
    md_path.write_text("# dummy", encoding="utf-8")

    def _fake_run(cmd, cwd, capture_output, text, encoding):
        raise OSError("uv not found")

    monkeypatch.setattr(bridge.subprocess, "run", _fake_run)

    result = bridge.export_if_configured([md_path], "client-a")

    assert result.generated == []
    assert len(result.warnings) == 1
    assert "uv not found" in result.warnings[0]


def test_no_conversion_when_report_export_dir_missing(monkeypatch, tmp_path):
    """common/report_export フォルダ自体が無いクローンでは変換をスキップする."""
    _install_fake_context_store(monkeypatch, _FakeContext(output_formats=["html"]))
    # ctx_src 判定は 01_context_management/src の存在で行われるため、実リポジトリの
    # REPO_ROOT を使いつつ common/report_export だけ無い体で検証したいが、簡単には
    # 差し替えられないため、REPO_ROOT を「09もreport_exportも無いtmp_path」に変えた上で
    # 09側を直接ロードできる体にするのは複雑になる。ここでは実装の分岐（common/report_export
    # が無ければスキップ）を、REPO_ROOT配下に01_context_management/srcだけ用意して検証する。
    (tmp_path / "01_context_management" / "src").mkdir(parents=True)
    monkeypatch.setattr(bridge, "REPO_ROOT", tmp_path)
    _forbid_subprocess_run(monkeypatch)

    md_path = tmp_path / "check-report.md"
    md_path.write_text("# dummy", encoding="utf-8")

    result = bridge.export_if_configured([md_path], "client-a")

    assert result.generated == []


def test_gdoc_selected_without_url_is_skipped_with_warning(monkeypatch, tmp_path):
    """gdocが選ばれているのにgoogle_doc_urlが無ければ、gdocだけ諦めてwarningsに積む."""
    _install_fake_context_store(
        monkeypatch, _FakeContext(output_formats=["gdoc"], google_doc_url=None)
    )
    _forbid_subprocess_run(monkeypatch)

    md_path = tmp_path / "check-report.md"
    md_path.write_text("# dummy", encoding="utf-8")

    result = bridge.export_if_configured([md_path], "client-a")

    assert result.generated == []
    assert len(result.warnings) == 1
    assert "google_doc_url" in result.warnings[0]


def test_gdoc_and_html_mixed_when_url_missing_only_html_runs(monkeypatch, tmp_path):
    """gdoc+htmlが選ばれ、google_doc_urlだけ無い場合はhtmlだけ渡してgdocは諦める."""
    _install_fake_context_store(
        monkeypatch, _FakeContext(output_formats=["html", "gdoc"], google_doc_url=None)
    )

    md_path = tmp_path / "check-report.md"
    md_path.write_text("# dummy", encoding="utf-8")
    html_out = md_path.with_suffix(".html")

    calls = []

    def _fake_run(cmd, cwd, capture_output, text, encoding):
        calls.append(cmd)
        stdout = f"[report_export] 出力完了:\n  {html_out}\n"
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(bridge.subprocess, "run", _fake_run)

    result = bridge.export_if_configured([md_path], "client-a")

    assert result.generated == [html_out]
    assert len(result.warnings) == 1
    assert "gdoc" in result.warnings[0]
    cmd = calls[0]
    assert cmd[cmd.index("--to") + 1] == "html"
    assert "--gdoc" not in cmd


def test_gdoc_and_gsheet_urls_passed_when_configured(monkeypatch, tmp_path):
    """gdoc/gsheetの書き込み先URLが01にあれば --gdoc/--gsheet として渡し、
    戻ってきたURL行（http始まり）をPathではなく文字列のままgeneratedに積む。"""
    _install_fake_context_store(
        monkeypatch,
        _FakeContext(
            output_formats=["gdoc", "gsheet"],
            google_doc_url="https://docs.google.com/document/d/doc-id/edit",
            google_sheet_url="https://docs.google.com/spreadsheets/d/sheet-id/edit",
        ),
    )

    md_path = tmp_path / "check-report.md"
    md_path.write_text("# dummy", encoding="utf-8")

    calls = []
    gdoc_result_url = "https://docs.google.com/document/d/doc-id/edit#heading=h.abc"
    gsheet_result_url = "https://docs.google.com/spreadsheets/d/sheet-id/edit#gid=0"

    def _fake_run(cmd, cwd, capture_output, text, encoding):
        calls.append(cmd)
        stdout = f"[report_export] 出力完了:\n  {gdoc_result_url}\n  {gsheet_result_url}\n"
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(bridge.subprocess, "run", _fake_run)

    result = bridge.export_if_configured([md_path], "client-a")

    assert result.generated == [gdoc_result_url, gsheet_result_url]
    assert all(isinstance(item, str) for item in result.generated)
    assert result.warnings == []
    cmd = calls[0]
    assert cmd[cmd.index("--to") + 1] == "gdoc,gsheet"
    assert cmd[cmd.index("--gdoc") + 1] == "https://docs.google.com/document/d/doc-id/edit"
    assert cmd[cmd.index("--gsheet") + 1] == "https://docs.google.com/spreadsheets/d/sheet-id/edit"


def test_gdoc_and_gsheet_both_missing_urls_skips_all_with_two_warnings(monkeypatch, tmp_path):
    """gdoc・gsheetの両方が選ばれ、両方ともURLが無ければ何も実行せず理由を2件積む."""
    _install_fake_context_store(
        monkeypatch,
        _FakeContext(output_formats=["gdoc", "gsheet"], google_doc_url=None, google_sheet_url=None),
    )
    _forbid_subprocess_run(monkeypatch)

    md_path = tmp_path / "check-report.md"
    md_path.write_text("# dummy", encoding="utf-8")

    result = bridge.export_if_configured([md_path], "client-a")

    assert result.generated == []
    assert len(result.warnings) == 2
