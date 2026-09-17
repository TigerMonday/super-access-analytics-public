"""pii.py のユニットテスト.

伏せる／伏せないの境界がそのまま成果物の質に効く。

- 伏せ漏れ → コミット済みファイルに個人情報が残る（実際に起きた）
- 伏せ過剰 → 分析に使う値が壊れて診断そのものができなくなる

どちらも実害があるので、両方向を押さえる。
"""

import pytest


# ──────────────────────────────────────
# 伏せるべきもの
# ──────────────────────────────────────

@pytest.mark.parametrize("text", [
    "taro.yamada@example.com",
    "/channels/taro@example.com",
    "/channels/createdメルアド：a@b.co.jp",  # leak-ok: 合成のダミードメイン（実在のメールアドレスではない）
    "user%40example.com",                      # URLエンコード
    "連絡先は a@b.jp です",  # leak-ok: 合成のダミードメイン（実在のメールアドレスではない）
    "090-1234-5678",
    "+81 90-1234-5678",
    "03.1234.5678",
    "4111-1111-1111-1111",
    "4111 1111 1111 1111",
])
def test_redacts_pii(text):
    from pii import contains_pii, redact_text
    assert contains_pii(text), f"伏せられていない: {text}"
    out, n = redact_text(text)
    assert n >= 1
    assert "@" not in out or "redacted" in out


# ──────────────────────────────────────
# 伏せてはいけないもの（分析に使う値）
# ──────────────────────────────────────

@pytest.mark.parametrize("text", [
    "/blogs/obsidian",
    "/form/request_material?from=transcription",
    "/notes/bMGAbyd4GCjSikH0ZH3u",
    "voice_professional_monthly",
    "utm_campaign=summer_2026&utm_source=google",
    "google.com",                    # signup の method
    "header_cta_transcription",      # button_source
    "90",                            # percent_scrolled
    "G-XXXXXXXXXX",
    "GTM-XXXXXXX",
    "12345678901234567890",          # 区切りの無い数字列は ID と区別が付かない
    "2026-08-05",
    "session_start",
])
def test_keeps_analytical_values(text):
    from pii import contains_pii, redact_text
    assert not contains_pii(text), f"過剰に伏せている: {text}"
    out, n = redact_text(text)
    assert out == text and n == 0


# ──────────────────────────────────────
# 再帰的な走査
# ──────────────────────────────────────

def test_redact_obj_walks_nested_structures():
    from pii import MASK, redact_obj
    data = {
        "pages": [
            {"pagePath": "/channels/a@b.com", "sessions": 10},  # leak-ok: 合成のダミードメイン（実在のメールアドレスではない）
            {"pagePath": "/blogs/obsidian", "sessions": 20},
        ],
        "meta": {"creator_email_address": "staff@example.co.jp"},  # leak-ok: 合成のダミードメイン（実在のメールアドレスではない）
    }
    out, n = redact_obj(data)
    assert n == 2
    assert out["pages"][0]["pagePath"] == f"/channels/{MASK}"
    assert out["pages"][1]["pagePath"] == "/blogs/obsidian"
    assert out["meta"]["creator_email_address"] == MASK
    assert out["pages"][0]["sessions"] == 10, "数値は壊さない"


def test_redact_obj_returns_zero_when_clean():
    from pii import redact_obj
    data = {"pages": [{"pagePath": "/blogs/x", "sessions": 1}]}
    out, n = redact_obj(data)
    assert n == 0 and out == data


def test_redact_obj_handles_non_string_scalars():
    from pii import redact_obj
    data = {"a": 1, "b": None, "c": True, "d": 1.5}
    out, n = redact_obj(data)
    assert n == 0 and out == data


# ──────────────────────────────────────
# 単語境界の指定が壊れていないこと
#
# 以前、自前定義した境界指定が実際には U+0008（バックスペース）文字になっていて
# カード番号の判定が機能していなかった。同じ事故を検出するための回帰テスト。
# ──────────────────────────────────────

def test_patterns_have_no_control_characters():
    from pii import PATTERNS
    for rx in PATTERNS:
        assert "\x08" not in rx.pattern, f"制御文字が混入している: {rx.pattern!r}"
        assert all(ord(c) >= 32 or c in "\t" for c in rx.pattern), \
            f"制御文字が混入している: {rx.pattern!r}"
