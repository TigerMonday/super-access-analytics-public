"""har_ga4.py のユニットテスト.

抽出結果は `_data/` にコミストするため、伏せ漏れは公開事故になる。
実際に「原本 `*.har` は除外したのに派生 JSON に素の識別子が残る」という
抜けを作ったので、伏せる／残すの境界を固定する。
"""

import pytest


# ──────────────────────────────────────
# URL の伏せ字化
# ──────────────────────────────────────

def test_redacts_pii_in_path():
    """クエリではなくパスに個人情報が載るケース（実際に見つかった形）。"""
    from har_ga4 import _redact_url
    out = _redact_url("https://x.app/channels/taro@example.com")
    assert "taro@example.com" not in out
    assert "/channels/" in out


def test_redacts_pii_in_path_with_query():
    from har_ga4 import _redact_url
    out = _redact_url("https://x.app/channels/test@example.com?sort=new")
    assert "test@example.com" not in out
    assert "sort=new" in out


def test_redacts_sensitive_query_keys():
    from har_ga4 import _redact_url
    out = _redact_url("https://x.app/auth?code=SECRET&state=S&plan=pro")
    assert "SECRET" not in out
    assert "plan=pro" in out, "分析に使うパラメータは残す"


def test_redacts_pii_in_generic_query_value():
    """`q` のような汎用キー名の値に個人情報が載る場合。"""
    from har_ga4 import _redact_url
    out = _redact_url("https://x.app/search?q=taro@example.com&sort=new")
    assert "taro@example.com" not in out
    assert "sort=new" in out


def test_keeps_normal_url_intact():
    from har_ga4 import _redact_url
    url = "https://example.com/login/redirect?plan=voice_professional_monthly&provider=google"
    assert _redact_url(url) == url


def test_handles_url_without_query():
    from har_ga4 import _redact_url
    assert _redact_url("https://x.app/blogs/obsidian") == "https://x.app/blogs/obsidian"


# ──────────────────────────────────────
# パラメータ値の伏せ字化
# ──────────────────────────────────────

def test_sentinel_user_id_is_kept():
    """`unknown` は既定値の混入という所見そのもの。伏せると診断できなくなる。"""
    from har_ga4 import _redact_value
    assert _redact_value("uid", "unknown") == "unknown"


def test_real_identifier_is_hashed():
    from har_ga4 import _redact_value
    out = _redact_value("client_id", "1902542194.1785919215")  # leak-ok: GA4 client_id形式の合成値（実在の識別子ではない）
    assert out.startswith("sha256:")


@pytest.mark.parametrize("name", ["user_email", "contact_phone", "member_name", "card_number"])
def test_pii_named_params_hashed(name):
    from har_ga4 import _redact_value
    assert _redact_value(name, "何かの値").startswith("sha256:")


@pytest.mark.parametrize("name,value", [
    ("plan", "voice_professional_monthly"),
    ("method", "google.com"),
    ("button_source", "header_cta_transcription"),
    ("percent_scrolled", "90"),
])
def test_analytical_params_kept(name, value):
    from har_ga4 import _redact_value
    assert _redact_value(name, value) == value


def test_pii_shaped_value_hashed_even_with_generic_name():
    """名前で拾えないケースの保険。"""
    from har_ga4 import _redact_value
    assert _redact_value("note_title", "連絡先 test@example.com").startswith("sha256:")


def test_hit_redaction_covers_identifiers():
    from har_ga4 import _redact_hit
    hit = _redact_hit({
        "page_location": "https://x.app/channels/test@example.com",
        "client_id": "123.456",
        "session_id": "789",
        "user_id": "unknown",
        "event_params": {"plan": "pro", "user_email": "test@example.com"},
        "user_properties": {},
    })
    assert "test@example.com" not in hit["page_location"]
    assert hit["client_id"].startswith("sha256:")
    assert hit["session_id"].startswith("sha256:")
    assert hit["user_id"] == "unknown", "既定値は所見なので残す"
    assert hit["event_params"]["plan"] == "pro"
    assert hit["event_params"]["user_email"].startswith("sha256:")

# ──────────────────────────────────────
# 過剰伏せの回帰テスト
#
# `age` が `page_title` / `engagement_time_msec` / `language` に、
# `name` が `event_name` に部分一致し、分析に使う値をハッシュ化していた。
# `event_name: PageView` はタグ特定の決定的な証拠で、それを黙って壊していた。
# ──────────────────────────────────────

@pytest.mark.parametrize("name,value", [
    ("page_title", "記事タイトル"),
    ("engagement_time_msec", "1234"),
    ("event_name", "PageView"),
    ("page_referrer", "https://g.com"),
    ("page_location", "https://x.app/"),
    ("language", "ja"),
    ("item_name", "商品A"),
    ("campaign_name", "summer_2026"),
    ("search_term", "obsidian"),
])
def test_ga4_standard_params_never_hashed(name, value):
    from har_ga4 import _redact_value
    out = str(_redact_value(name, value))
    assert not out.startswith("sha256:"), f"{name} を過剰に伏せている"


@pytest.mark.parametrize("name", [
    "user_email", "contact_phone", "first_name", "last_name",
    "user_age", "birthday", "postcode", "card_number",
])
def test_pii_params_still_hashed(name):
    from har_ga4 import _redact_value
    assert str(_redact_value(name, "何かの値")).startswith("sha256:")


# ──────────────────────────────────────
# パスのトークンと URL 値のパラメータ
# ──────────────────────────────────────

@pytest.mark.parametrize("url,secret", [
    ("https://x.app/invite/AbC123XyZ", "AbC123XyZ"),
    ("https://x.app/reset/TOK123/confirm", "TOK123"),
    ("https://x.app/verify/SECRET", "SECRET"),
])
def test_path_tokens_redacted(url, secret):
    """クエリではなくパスに秘密が載る形。値の形では判別できないので位置で見る。"""
    from har_ga4 import _redact_url
    assert secret not in _redact_url(url)


def test_normal_path_segments_kept():
    from har_ga4 import _redact_url
    url = "https://x.app/blogs/obsidian"
    assert _redact_url(url) == url


def test_url_valued_param_goes_through_url_sanitizer():
    """`link_url` のような URL 値はハッシュにせず、機微な部分だけ落とす。"""
    from har_ga4 import _redact_value
    out = _redact_value("link_url", "https://x.app/auth?code=SECRET&plan=pro")
    assert "SECRET" not in out
    assert "plan=pro" in out
    assert not out.startswith("sha256:"), "URL はハッシュにせず構造を残す"

# ──────────────────────────────────────
# リストの整合性
#
# 「絶対に伏せない」と「伏せる」の両方に同じ名前を書くと、先に判定される
# 「伏せる」側が勝ち、宣言が嘘になる。実際に `session_id` で起きた。
# ──────────────────────────────────────

def test_never_redact_and_redact_lists_do_not_overlap():
    from har_ga4 import NEVER_REDACT_PARAMS, REDACT_PARAM_NAMES
    overlap = NEVER_REDACT_PARAMS & REDACT_PARAM_NAMES
    assert not overlap, f"両方に入っている名前がある: {sorted(overlap)}"


def test_never_redact_params_are_actually_kept():
    """一覧に入れた名前が本当に伏せられないことを、全件で確かめる。"""
    from har_ga4 import NEVER_REDACT_PARAMS, _redact_value
    for name in sorted(NEVER_REDACT_PARAMS):
        out = str(_redact_value(name, "テスト値"))
        assert not out.startswith("sha256:"), f"{name} が伏せられている"
