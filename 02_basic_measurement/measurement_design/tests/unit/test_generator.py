"""generator.py のユニットテスト."""
import pytest
from unittest.mock import patch
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent.parent.parent.parent / "templates" / "design-doc"

CONTEXT = {
    "client_name": "test-client",
    "kpis": [{"kpi_id": "kpi_001", "name": "資料ダウンロード数"}],
    "screen_flow": {"pages": [], "flows": []},
    "standardized_events": [{"event_name": "file_download"}],
    "review_data": {"ga4": {"property": {"name": "テストサイト"}}},
}

HAIKU_CHAPTERS = {1, 2, 3, 5, 9, 10, 14, 15, 16}
SONNET_CHAPTERS = {4, 6, 7, 8, 11, 12, 13}


def test_generate_chapter_returns_string():
    from measurement_design.design.generator import generate_chapter

    with patch("measurement_design.llm_client.complete_text", return_value="# 章1: カバーページ\n\n本文"):
        result = generate_chapter(1, TEMPLATES_DIR / "01-cover.template.md", CONTEXT, "fake-key")

    assert isinstance(result, str)
    assert len(result) > 0


def test_generate_chapter_uses_haiku_for_light_chapters():
    from measurement_design.design.generator import generate_chapter

    with patch("measurement_design.llm_client.complete_text", return_value="content") as mock_complete:
        generate_chapter(1, TEMPLATES_DIR / "01-cover.template.md", CONTEXT, "fake-key")
        assert mock_complete.call_args.kwargs["model"] == "claude-haiku-4-5-20251001"


def test_generate_chapter_uses_sonnet_for_heavy_chapters():
    from measurement_design.design.generator import generate_chapter

    with patch("measurement_design.llm_client.complete_text", return_value="content") as mock_complete:
        generate_chapter(6, TEMPLATES_DIR / "06-event-config.template.md", CONTEXT, "fake-key")
        assert mock_complete.call_args.kwargs["model"] == "claude-sonnet-4-6"


def test_save_chapter_writes_file(tmp_path):
    from measurement_design.design.generator import save_chapter
    content = "# 章1\n本文"
    out = save_chapter(1, content, tmp_path)
    assert out.exists()
    assert "01-" in out.name
    assert out.read_text(encoding="utf-8") == content


# ──────────────────────────────────────
# 回帰テスト: プロンプトへの全件反映（旧実装は kpis[:3] / standardized_events[:5]
# に固定で切り詰めており、GA4イベント設定・GTM変数一覧のほとんどが
# 章生成LLMに渡らないまま出力から欠落していた）
# ──────────────────────────────────────

def _context_with(n_kpis=10, n_events=20, n_observed=30, n_gtm_tags=15):
    return {
        "client_name": "test-client",
        "kpis": [{"kpi_id": f"kpi_{i:03d}", "name": f"KPI{i}"} for i in range(n_kpis)],
        "screen_flow": {"pages": [], "flows": []},
        "standardized_events": [{"event_name": f"event_{i}"} for i in range(n_events)],
        "review_data": {
            "ga4": {
                "property": {"name": "テストサイト"},
                "events_observed": [{"name": f"observed_{i}", "count": i} for i in range(n_observed)],
                "custom_definitions": {"dimensions": [], "metrics": []},
            },
            "gtm": {
                "tags_detail": [{"name": f"tag_{i}", "event_name": f"gtm_event_{i}"} for i in range(n_gtm_tags)],
            },
        },
    }


@pytest.mark.parametrize("chapter,template", [
    (6, "06-event-config.template.md"),
    (7, "07-variables.template.md"),
])
def test_generate_chapter_keeps_all_input_sources(chapter, template):
    from measurement_design.design.generator import generate_chapter

    with patch("measurement_design.llm_client.complete_text", return_value="content") as complete:
        result = generate_chapter(chapter, TEMPLATES_DIR / template, _context_with(), "fake-key")
    assert result == "content"
    prompt = complete.call_args.args[0]
    for sentinel in ("kpi_009", "event_19", "observed_29", "gtm_event_14"):
        assert sentinel in prompt


def test_generate_chapter_handles_missing_gtm_section():
    """GTM未実行（phase3.json無し）でも review_data['gtm'] キー無しで落ちないこと。"""
    from measurement_design.design.generator import generate_chapter

    context = _context_with()
    del context["review_data"]["gtm"]
    with patch("measurement_design.llm_client.complete_text", return_value="content"):
        result = generate_chapter(6, TEMPLATES_DIR / "06-event-config.template.md", context, "fake-key")
    assert isinstance(result, str)


# ──────────────────────────────────────
# 確定所見（context["findings"]）がプロンプトの最優先制約として乗ること
# ──────────────────────────────────────

def test_generate_chapter_includes_findings_when_present():
    from measurement_design.design.generator import generate_chapter

    context = {**CONTEXT, "findings": "signup と sign_up は別イベント。signup が正。"}
    with patch("measurement_design.llm_client.complete_text", return_value="content") as mock_complete:
        generate_chapter(6, TEMPLATES_DIR / "06-event-config.template.md", context, "fake-key")
        prompt = mock_complete.call_args.args[0]
        assert "signup と sign_up は別イベント" in prompt
        assert "確定している事実" in prompt


def test_generate_chapter_does_not_crash_when_findings_missing():
    """findings.md 未整備（context に findings キー無し）でも落ちないこと。"""
    from measurement_design.design.generator import generate_chapter

    context = {k: v for k, v in CONTEXT.items() if k != "findings"}
    with patch("measurement_design.llm_client.complete_text", return_value="content"):
        result = generate_chapter(6, TEMPLATES_DIR / "06-event-config.template.md", context, "fake-key")
    assert isinstance(result, str)


def test_generate_chapter_does_not_crash_when_findings_empty_string():
    from measurement_design.design.generator import generate_chapter

    context = {**CONTEXT, "findings": ""}
    with patch("measurement_design.llm_client.complete_text", return_value="content") as mock_complete:
        generate_chapter(6, TEMPLATES_DIR / "06-event-config.template.md", context, "fake-key")
        prompt = mock_complete.call_args.args[0]
        assert "未整備" in prompt  # 根拠データだけで判断する旨の案内文になる


def test_prompt_list_cap_still_bounds_extreme_input_size():
    """上限を撤廃はしたが、極端な件数（200件超）ではプロンプト膨張を防ぐ安全上限が効くこと。"""
    from measurement_design.design.generator import generate_chapter

    context = _context_with(n_events=500)
    with patch("measurement_design.llm_client.complete_text", return_value="content") as mock_complete:
        generate_chapter(6, TEMPLATES_DIR / "06-event-config.template.md", context, "fake-key")
        prompt = mock_complete.call_args.args[0]
        assert "event_199" in prompt
        assert "event_499" not in prompt
        assert "全 500 件" in prompt  # 総件数は明記される（サイレントな切り詰めにしない）
