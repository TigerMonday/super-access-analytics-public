"""個人情報らしい値を伏せる。

`_data/` はコミットする前提なので、**取得した実データに含まれる個人情報が
そのままリポジトリに入る**。GA4 のページパスやカスタムパラメータには、
クライアントの実装次第で end user のメールアドレスなどが載ることがある
（実際に `pagePath` に `/channels/<メールアドレス>` が入っていた案件がある）。

保存の一箇所（`dataset.split_and_save`）で通すことで、取得系スクリプトを
個別に直さなくても全データセットが対象になる。

**過剰に伏せない**ことも同じくらい重要。分析に使う値（イベント名・プラン名・
UTM・スクロール率など）を壊すと診断そのものができなくなる。そのため:

- メールアドレスは常に伏せる（誤検知しにくい）
- 電話番号・カード番号は**区切り文字か国番号があるものだけ**。区切りの無い
  数字列は ID との区別が付かないため対象にしない
"""

from __future__ import annotations

import re

MASK = "[redacted:pii]"

# メールアドレス。URL エンコードされた `%40` も拾う。
EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+(?:@|%40)[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
)

# 電話番号。**区切りか国番号があるものに限る。**
# 区切りの無い数字の並びは ID（transaction_id 等）と区別が付かないため対象外。
PHONE_RE = re.compile(
    r"(?:\+\d{1,3}[-.\s]?)?(?:\d{2,4}[-.\s]\d{2,4}[-.\s]\d{3,4})",
)

# カード番号。4桁×4の区切りありに限る。
CARD_RE = re.compile(
    r"(?<![0-9])\d{4}[-.\s]\d{4}[-.\s]\d{4}[-.\s]\d{4}(?![0-9])",
)

PATTERNS = (EMAIL_RE, CARD_RE, PHONE_RE)


def redact_text(text: str) -> tuple[str, int]:
    """文字列から個人情報らしい部分を伏せる。戻り値は (結果, 伏せた件数)。"""
    if not isinstance(text, str) or not text:
        return text, 0
    total = 0
    out = text
    for rx in PATTERNS:
        out, n = rx.subn(MASK, out)
        total += n
    return out, total


def contains_pii(text: str) -> bool:
    return isinstance(text, str) and any(rx.search(text) for rx in PATTERNS)


def redact_obj(obj, _count: list[int] | None = None) -> tuple[object, int]:
    """dict / list / str を再帰的に走査して伏せる。戻り値は (結果, 伏せた件数)。"""
    counter = _count if _count is not None else [0]
    if isinstance(obj, str):
        out, n = redact_text(obj)
        counter[0] += n
        return out, counter[0]
    if isinstance(obj, dict):
        return {k: redact_obj(v, counter)[0] for k, v in obj.items()}, counter[0]
    if isinstance(obj, list):
        return [redact_obj(v, counter)[0] for v in obj], counter[0]
    return obj, counter[0]
