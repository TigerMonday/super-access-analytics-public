"""build_design_doc_html.py のユニットテスト.

docs/design-doc/ の章ファイル（01-16の単一セット）を1枚のHTMLにまとめる。
現状/推奨の2系統に分かれていた旧構成（design-doc-current/recommend）ではなく、
公開版の章ベースの設計書生成（generator.py/selector.py）が書き出す構成に合わせる。
"""
import pytest

import build_design_doc_html
import config as config_module
from config import AuditConfig


@pytest.fixture
def cfg(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)
    return AuditConfig(property_id="123456789", client_name="acme-123456789")


def _write_chapter(cfg, filename: str, content: str):
    design_doc_dir = cfg.docs_dir / "design-doc"
    design_doc_dir.mkdir(parents=True, exist_ok=True)
    (design_doc_dir / filename).write_text(content, encoding="utf-8")


def test_build_raises_when_no_chapters(cfg):
    """章ファイルが1つも無ければ、fetch/design未実行と分かるエラーにする."""
    with pytest.raises(FileNotFoundError):
        build_design_doc_html.build(cfg)


def test_build_collects_chapters_and_strips_prefix(cfg):
    """章番号ごとに集め、見出しの「章 NN:」接頭辞を落とす."""
    _write_chapter(cfg, "01-cover.md", "# 章 01: 表紙\n\n対象プロパティ: テスト\n")
    _write_chapter(
        cfg, "06-event-config.md",
        "# 章 06: イベント設定\n\n| event_name | 意味 |\n|---|---|\n| `login` | ログイン |\n",
    )

    out = build_design_doc_html.build(cfg, client_label="テスト会社")

    assert out == cfg.docs_dir / "design-doc.html"
    html_text = out.read_text(encoding="utf-8")
    assert "テスト会社" in html_text
    assert '<span class="n">01</span>表紙' in html_text
    assert '<span class="n">06</span>イベント設定' in html_text
    # 表は横スクロール可能なラッパーに包む
    assert '<div class="tablewrap"><table>' in html_text


def test_build_skips_readme_and_template_files(cfg):
    """README.md と *.template.md は成果物ではないので含めない."""
    _write_chapter(cfg, "01-cover.md", "# 章 01: 表紙\n\n本文\n")
    _write_chapter(cfg, "README.md", "# 使い方\n")
    _write_chapter(cfg, "02-basic-settings.template.md", "# 章 02: {{未記入}}\n")

    out = build_design_doc_html.build(cfg)
    html_text = out.read_text(encoding="utf-8")

    assert '<span class="n">01</span>' in html_text
    assert "02" not in html_text.split('<nav class="toc">')[1].split("</nav>")[0]


def test_build_warns_on_duplicate_chapter_number(cfg, capsys):
    """同じ章番号のファイルが2つあると警告し、後に来たファイルを採用する."""
    _write_chapter(cfg, "01-cover.md", "# 章 01: 旧版\n\n旧本文\n")
    _write_chapter(cfg, "01-cover2.md", "# 章 01: 新版\n\n新本文\n")

    out = build_design_doc_html.build(cfg)

    err = capsys.readouterr().out
    assert "警告" in err
    assert "新本文" in out.read_text(encoding="utf-8")
    assert "旧本文" not in out.read_text(encoding="utf-8")


def test_build_escapes_raw_html_from_chapters(cfg):
    """章Markdownに混じった生HTMLを実行可能な形で出力しない."""
    _write_chapter(
        cfg,
        "01-cover.md",
        "# 章 01: 表紙\n\n<script>alert('xss')</script>\n"
        '<img src=x onerror="alert(1)">\n',
    )

    out = build_design_doc_html.build(cfg)
    html_text = out.read_text(encoding="utf-8")

    assert "<script>alert('xss')</script>" not in html_text
    assert '<img src=x onerror="alert(1)">' not in html_text
    assert "&lt;script&gt;alert('xss')&lt;/script&gt;" in html_text
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html_text
