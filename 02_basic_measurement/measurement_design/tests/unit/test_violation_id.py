"""violation_id.py のユニットテスト.

指摘IDを安定させる採番ロジックの肝は3つ:
  1. 同じ入力なら同じID
  2. 他の指摘が増減してもIDが変わらない（通し番号の弱点だった点）
  3. 違う指摘なら違うID（衝突しない）
"""


def test_make_id_is_deterministic():
    from measurement_design.review.violation_id import make_id

    id1 = make_id("V-", "命名規則", "event", "click_CTA", "GA4")
    id2 = make_id("V-", "命名規則", "event", "click_CTA", "GA4")
    assert id1 == id2


def test_make_id_differs_by_content():
    from measurement_design.review.violation_id import make_id

    id_a = make_id("V-", "命名規則", "event", "click_CTA", "GA4")
    id_b = make_id("V-", "命名規則", "event", "FormSubmit", "GA4")
    assert id_a != id_b


def test_make_id_uses_prefix():
    from measurement_design.review.violation_id import make_id

    assert make_id("V-", "a", "b").startswith("V-")
    assert make_id("V-H-", "a", "b").startswith("V-H-")


def test_make_id_is_ascii_and_short():
    """検索できる（ASCII）・幅の狭いID列で折り返さない程度に短いことを固定する."""
    from measurement_design.review.violation_id import make_id

    vid = make_id("V-H-", "計測漏れ", "event", "コラムページ到達（日本語のURLやタイトルを含む対象名）", "GA4")
    assert vid.isascii()
    assert len(vid) <= 16


def test_make_id_does_not_confuse_element_boundaries():
    """区切り文字を挟まずに連結すると、要素の境界がずれて別の指摘が同じ基準文字列になる.

    例えば "A" + "BC" と "AB" + "C" は単純連結だと同じ "ABC" になってしまう。
    区切り文字（`\\x1f`）を挟むことで、この2通りが別のIDになることを確認する。
    """
    from measurement_design.review.violation_id import make_id

    id1 = make_id("V-", "A", "BC")
    id2 = make_id("V-", "AB", "C")
    assert id1 != id2


def test_dedupe_ids_keeps_unique_ids_untouched():
    from measurement_design.review.violation_id import dedupe_ids

    violations = [
        {"id": "V-aaa111", "category": "x", "target_name": "a", "description": ""},
        {"id": "V-bbb222", "category": "y", "target_name": "b", "description": ""},
    ]
    dedupe_ids(violations)
    assert [v["id"] for v in violations] == ["V-aaa111", "V-bbb222"]


def test_dedupe_ids_splits_colliding_ids_deterministically():
    """識別要素の取りこぼしでIDが衝突した場合、実行順に依存しない方法で分ける."""
    from measurement_design.review.violation_id import dedupe_ids

    def _make(order):
        violations = [
            {"id": "V-same01", "category": "cat", "target_name": "b", "description": "desc-b"},
            {"id": "V-same01", "category": "cat", "target_name": "a", "description": "desc-a"},
        ]
        if order == "swap":
            violations.reverse()
        dedupe_ids(violations)
        return {v["target_name"]: v["id"] for v in violations}

    result_normal = _make("normal")
    result_swapped = _make("swap")

    # target_name が違う2件が別々のIDになっている
    assert result_normal["a"] != result_normal["b"]
    # 呼び出し前の並び順（リストに現れた順）が変わっても、結果は同じ
    assert result_normal == result_swapped
