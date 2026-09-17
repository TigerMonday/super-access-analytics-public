from pathlib import Path


RUNBOOK = Path(__file__).resolve().parents[1] / "05_campaign_optimization" / "run.md"


def test_site_improvement_asks_in_chat_before_page_level_work():
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "チャットで方針を要約して続行確認を取り" in text
    assert "この方針で、対象ページの選定とページ別の改善案作成まで進めてよいですか？" in text
    assert "利用者が「OK」「進めて」等と了承したら" in text
    assert "レポート本文に確認待ちの章を置くだけでは" in text
