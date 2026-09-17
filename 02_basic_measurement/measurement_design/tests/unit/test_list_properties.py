from __future__ import annotations

from list_properties import render_account_summaries


def test_account_summary_includes_property_names_and_ids():
    text = render_account_summaries(
        [
            {
                "account": "accounts/123",
                "display_name": "自社アカウント",
                "property_summaries": [
                    {"property": "properties/456", "display_name": "自社サイト"}
                ],
            }
        ]
    )

    assert "accounts/123" in text
    assert "自社アカウント" in text
    assert "properties/456" in text
    assert "自社サイト" in text


def test_empty_account_summary_is_clear():
    assert "ありません" in render_account_summaries([])
