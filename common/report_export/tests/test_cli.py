from pathlib import Path

import pytest

from report_export.accent_color import InvalidColorError
from report_export.__main__ import (
    ENV_ACCENT_COLOR,
    ENV_LOGO_PATH,
    resolve_accent_color,
    resolve_formats,
    resolve_logo_path,
    run,
)


def test_resolve_formats_all():
    assert resolve_formats("all") == ["html", "pdf", "docx", "xlsx"]


def test_resolve_formats_accepts_gdoc_and_gsheet():
    assert resolve_formats("gdoc,gsheet") == ["gdoc", "gsheet"]


def test_run_raises_when_gdoc_requested_without_target(tmp_path: Path):
    md_path = tmp_path / "report.md"
    md_path.write_text("# タイトル\n本文\n", encoding="utf-8")
    with pytest.raises(ValueError):
        run(md_path, ["gdoc"], tmp_path)


def test_run_raises_when_gsheet_requested_without_target(tmp_path: Path):
    md_path = tmp_path / "report.md"
    md_path.write_text("# タイトル\n本文\n", encoding="utf-8")
    with pytest.raises(ValueError):
        run(md_path, ["gsheet"], tmp_path)


def test_resolve_formats_comma_list_preserves_order():
    assert resolve_formats("xlsx,html") == ["xlsx", "html"]


def test_resolve_formats_dedupes():
    assert resolve_formats("html,html,pdf") == ["html", "pdf"]


def test_resolve_formats_rejects_pptx():
    with pytest.raises(ValueError):
        resolve_formats("pptx")


def test_resolve_formats_rejects_empty():
    with pytest.raises(ValueError):
        resolve_formats("  ,  ")


def test_resolve_accent_color_none_when_unset(monkeypatch):
    monkeypatch.delenv(ENV_ACCENT_COLOR, raising=False)
    assert resolve_accent_color(None) is None


def test_resolve_accent_color_cli_arg_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv(ENV_ACCENT_COLOR, "#000000")
    assert resolve_accent_color("#1D4ED8") == "#1d4ed8"


def test_resolve_accent_color_falls_back_to_env(monkeypatch):
    monkeypatch.setenv(ENV_ACCENT_COLOR, "#1D4ED8")
    assert resolve_accent_color(None) == "#1d4ed8"


def test_resolve_accent_color_rejects_invalid_hex(monkeypatch):
    monkeypatch.delenv(ENV_ACCENT_COLOR, raising=False)
    with pytest.raises(InvalidColorError):
        resolve_accent_color("not-a-color")


def test_resolve_logo_path_none_when_unset(monkeypatch):
    monkeypatch.delenv(ENV_LOGO_PATH, raising=False)
    assert resolve_logo_path(None) is None


def test_resolve_logo_path_cli_arg_takes_precedence_over_env(monkeypatch, tmp_path):
    cli_logo = tmp_path / "cli.svg"
    cli_logo.write_text("<svg></svg>", encoding="utf-8")
    env_logo = tmp_path / "env.svg"
    env_logo.write_text("<svg></svg>", encoding="utf-8")
    monkeypatch.setenv(ENV_LOGO_PATH, str(env_logo))
    assert resolve_logo_path(cli_logo) == cli_logo


def test_resolve_logo_path_falls_back_to_env(monkeypatch, tmp_path):
    env_logo = tmp_path / "env.svg"
    env_logo.write_text("<svg></svg>", encoding="utf-8")
    monkeypatch.setenv(ENV_LOGO_PATH, str(env_logo))
    assert resolve_logo_path(None) == env_logo


def test_resolve_logo_path_raises_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.delenv(ENV_LOGO_PATH, raising=False)
    missing = tmp_path / "missing.svg"
    with pytest.raises(FileNotFoundError):
        resolve_logo_path(missing)
