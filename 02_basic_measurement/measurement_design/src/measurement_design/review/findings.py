"""人が確定させた所見を読み出す。

機械検出と LLM 生成は、原因まで特定した調査結果を知らない。そのため
似たイベント名を取り違えたり、人が出した結論と逆の推奨を書くことがある
（実際の案件で `signup`/`sign_up` の取り違えとリネーム方向の逆転が発生した）。

対策として、確定所見を1箇所に置き、生成プロンプトの最優先制約として渡す。
置き場所は次の順で探す。

1. `docs/findings.md` — 確定所見の専用ファイル（推奨）
2. `docs/check-report.md` の `## 0.` 節 — レポートに直接書いた場合のフォールバック
"""

from __future__ import annotations

import re
from pathlib import Path

FINDINGS_FILE = "findings.md"
CHECK_REPORT_FILE = "check-report.md"

# テンプレートの雛形プレースホルダ。これが残っている＝人がまだ書いていない。
#
# **`{{` を含むかどうかで判定してはいけない。** GA4/GTM のレポートでは
# `{{Event}}` `{{Click URL}}` のような GTM 変数記法を普通に書く
# （実際に「`{{Event}}` をそのままイベント名に使っているタグ」という指摘文を書いた）。
# 一律で弾くと、人が書いた所見が「テンプレートのまま」と誤判定されて消える。
# 「人がまだ書いていない」ことを示すマーカー。
#
# **`{{...}}` の一致で判定してはいけない。** GA4/GTM のレポートでは
# `{{Event}}` `{{event_name}}` のような GTM 変数記法を普通に書くため、
# トークン一覧との照合では人の所見を雛形と誤判定して消してしまう
# （この判定は3回作り直した。1回目は `{{` の有無、2回目はトークン一覧、
# どちらも GTM 変数と衝突した）。
#
# HTML コメントなら Markdown の表示に出ず、GTM 変数とも衝突しない。
# 人が §0 を書くときはこの行ごと消す（消し忘れても「未記入」と分かる）。
SCAFFOLD_MARKER = "<!-- scaffold:unwritten -->"

# §0（確定所見）専用の雛形プレースホルダ。
# **レポート生成の安全網でこれを `—` に置換してはいけない。** 置換すると未記入の §0 が
# 「人が書いた所見」と誤判定され、生成の最優先制約として空の表が渡る。
SECTION0_PLACEHOLDERS = ("{{finding}}", "{{evidence}}", "{{impact}}")

SCAFFOLD_PLACEHOLDERS = (
    "{{finding}}", "{{evidence}}", "{{impact}}", "{{severity}}",
    "{{クライアント名}}", "{{YYYY-MM-DD}}", "{{property_id}}",
    "{{key_event}}", "{{key_event_name}}", "{{event_name}}", "{{status}}", "{{action}}",
    "{{purpose}}", "{{timing}}", "{{fit_note}}",
    "{{name}}", "{{violation}}", "{{suggestion}}",
    "{{event}}", "{{param}}", "{{issue}}", "{{fix}}",
    "{{tag_name}}", "{{gtm_event}}", "{{ga4_event}}", "{{diff}}",
    "{{owner}}", "{{timeline}}", "{{event_count}}",
)


def is_scaffold(text: str) -> bool:
    """人がまだ書いていない雛形か。

    判定はマーカーを主とする。**GTM 変数記法（`{{event_name}}` 等）と衝突しない**
    ことが要件なので、`{{...}}` の一致は §0 専用の3トークンだけに限る
    （これらは GTM 変数として使われる可能性が実質無い）。
    `{{event_name}}` のような一般的な変数名は判定に使わない。
    """
    if SCAFFOLD_MARKER in text:
        return True
    return any(ph in text for ph in SECTION0_PLACEHOLDERS)

# check-report.md の「## 0. …」から次の「## 」までを確定所見とみなす
SECTION0_RE = re.compile(r"^##\s*0\.\s.*?(?=^##\s|\Z)", re.M | re.S)


def load_findings(docs_dir: Path) -> tuple[str, str]:
    """(確定所見の本文, 取得元の説明) を返す。無ければ ("", "")。"""
    path = docs_dir / FINDINGS_FILE
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text, f"docs/{FINDINGS_FILE}"

    report = docs_dir / CHECK_REPORT_FILE
    if report.exists():
        m = SECTION0_RE.search(report.read_text(encoding="utf-8"))
        if m:
            text = m.group(0).strip()
            # 雛形のプレースホルダが残っている＝人がまだ書いていない。
            # これを「確定している事実」として生成に渡すと、架空の所見を最優先の
            # 制約として与えてしまう。書かれていないものは無いものとして扱う。
            if text and not is_scaffold(text):
                return text, f"docs/{CHECK_REPORT_FILE} §0"

    return "", ""
