from pathlib import Path

import pytest

from report_export.__main__ import main, run


def _prepare_fake_saa_repo(tmp_path: Path) -> tuple[Path, Path]:
    builder = tmp_path / "common" / "report_index" / "build_index.py"
    builder.parent.mkdir(parents=True)
    builder.write_text(
        """from pathlib import Path
import sys

client_dir = Path(sys.argv[1])
(client_dir / "index.html").write_text("<h1>report index</h1>", encoding="utf-8")
""",
        encoding="utf-8",
    )
    report_dir = tmp_path / "outputs" / "sample-client" / "04_traffic"
    report_dir.mkdir(parents=True)
    markdown = report_dir / "basic-analysis-report.md"
    markdown.write_text(
        "# 基本分析\n\n"
        "<!-- pictograms: issue,insight,target -->\n"
        "| 課題 | 発見 | 次の判断 |\n|---|---|---|\n| A | B | C |\n\n"
        "<!-- chart: bar; title: チャネル比較 -->\n"
        "| チャネル | セッション |\n|---|---:|\n| Organic | 10 |\n",
        encoding="utf-8",
    )
    return markdown, report_dir


def test_html_export_refreshes_client_report_index(tmp_path: Path):
    markdown, _ = _prepare_fake_saa_repo(tmp_path)

    generated = run(markdown, ["html"], None)

    assert generated[0].suffix == ".html"
    index_path = tmp_path / "outputs" / "sample-client" / "index.html"
    assert index_path.read_text(encoding="utf-8") == "<h1>report index</h1>"


def test_cli_prints_report_index_as_viewing_entry(tmp_path: Path, capsys):
    markdown, _ = _prepare_fake_saa_repo(tmp_path)

    assert main([str(markdown), "--to", "html"]) == 0

    output = capsys.readouterr().out
    assert "[report_export] 閲覧入口:" in output
    assert str((tmp_path / "outputs" / "sample-client" / "index.html").resolve()) in output


def test_pdf_only_refreshes_report_index(tmp_path: Path, monkeypatch):
    markdown, _ = _prepare_fake_saa_repo(tmp_path)
    monkeypatch.setattr("report_export.__main__.export_pdf_from_html", lambda html, out: out.write_bytes(b"%PDF"))

    run(markdown, ["pdf"], None)

    assert (tmp_path / "outputs" / "sample-client" / "index.html").exists()


def test_html_outside_saa_outputs_does_not_create_report_index(tmp_path: Path):
    markdown = tmp_path / "report.md"
    markdown.write_text("# Report\n", encoding="utf-8")

    run(markdown, ["html"], None)

    assert not (tmp_path / "index.html").exists()


def test_index_refresh_failure_is_not_hidden(tmp_path: Path):
    markdown, _ = _prepare_fake_saa_repo(tmp_path)
    builder = tmp_path / "common" / "report_index" / "build_index.py"
    builder.write_text("raise SystemExit(2)\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="閲覧入口の更新に失敗"):
        run(markdown, ["html"], None)
