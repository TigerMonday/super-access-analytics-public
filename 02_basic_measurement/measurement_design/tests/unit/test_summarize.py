"""summarize.py のユニットテスト.

GTM 構成表示のラベル修正（`live_version` の名称・メモを「取得元」「説明」と
誤表示していたバグ）を固定する。`live_version` は GTM コンテナの公開版に
紐づく任意の版名・リリースノート（運用者が書く社内向けテキスト）であり、
「データをどう取得したか」とは無関係。
"""
import summarize


def test_gtm_source_method_reports_api_when_live_version_present():
    """API 経路（gtm.py）は `source` キーを持たず `live_version` を持つ。"""
    p3 = {"live_version": {"name": "v12", "description": "定期更新"}, "tags": []}

    assert summarize._gtm_source_method(p3) == "api"


def test_gtm_source_method_reports_public_gtm_js():
    """フォールバック経路（gtm_public.py）は `source.method` を明示的に持つ。"""
    p3 = {"source": {"method": "public_gtm_js"}, "tags": []}

    assert summarize._gtm_source_method(p3) == "public_gtm_js"


def test_gtm_source_method_unknown_when_neither_present():
    assert summarize._gtm_source_method({}) == "不明"


def test_section_gtm_labels_live_version_as_release_metadata_not_source():
    """`live_version.name/description` は「取得元」「説明」ではなく、
    コンテナの公開版名・公開時のメモとして表示する。取得方法は別行で示す。
    """
    p3 = {
        "live_version": {"name": "v12", "description": "キャンペーン反映のため更新"},
        "measurement_ids": ["G-ABCDEF1234"],  # leak-ok: 合成テストID（実在の測定IDではない）
        "tags": [],
        "triggers": [],
        "variables": [],
        "built_in_variables": [],
    }

    text = "\n".join(summarize._section_gtm(p3))

    assert "コンテナの公開版名" in text
    assert "公開時のメモ" in text
    assert "取得方法" in text and "api" in text
    # 旧ラベル（取得方法と無関係な運用メモを「取得元」「説明」と誤表示していた）は残っていない
    assert "| 取得元 |" not in text
    assert "| 説明 |" not in text
