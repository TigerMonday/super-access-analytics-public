"""指摘IDを内容から決まる安定した符号にする.

旧実装は `V-001` のような通し番号だった。`events_observed` や GTM の `tags` は
GA4/GTM APIが返す順序を保証しておらず、データを取り直すと並び順が変わることがある。
通し番号は並び順に依存するため、**同じ指摘なのに再生成のたびに別の番号が振られる**
（逆に、別の指摘が同じ番号を引き継ぐ）という不具合があった。改善ロードマップや
`check-report-notes.md`（人が対応を書き込むファイル）はIDで指摘を参照するため、
これは実害が大きい。

対策として、IDを「その指摘が何を指しているか」を表す識別要素（カテゴリ・対象・
場所など）から計算する。入力データの並び順が変わっても、指摘の内容が同じなら
同じIDになる。

識別要素に選んではいけないもの: 件数・比率など実行のたびに変わる数字
（description に入る「16件ある」「0.84倍」等）。これを含めると、指摘の実体は
同じでも再取得のたびにIDが変わってしまい、通し番号と同じ問題を再現する。
"""

from __future__ import annotations

import hashlib
from collections import defaultdict

# 識別要素を連結する区切り文字。対象名には日本語・URL・記号など何でも入り得るため、
# 通常のテキストに出てこない制御文字（Unit Separator）を使う。"-" や "|" のような
# 表示にも使う文字を区切りにすると、要素の境界がずれて別の指摘が同じ基準文字列に
# なりかねない。
_SEP = "\x1f"

# ハッシュの採用桁数。16進6桁 = 24bit ≈ 1677万通り。1サイトの指摘は実際には
# 数十〜数百件程度なので、この桁数なら衝突はまず起きない
# （誕生日問題で500件でも衝突確率は1%未満）。万一取りこぼしで衝突しても、
# `dedupe_ids` が実行順に依存しない方法で最終的に分ける。
_DIGITS = 6


def make_id(prefix: str, *parts: str) -> str:
    """`prefix` と `parts`（対象を一意に決める識別要素）から安定したIDを作る.

    同じ `parts` を渡せば、呼び出し回数・呼び出し順・他の指摘の増減に関わらず
    常に同じ文字列が返る。`parts` には最低でもカテゴリ・種別・対象名・場所を
    渡すこと。1つの対象に複数の指摘が付く可能性がある検査（例: 同じキーイベントに
    複数の要確認トリガーが紐づく）では、呼び出し側が区別できる追加の
    識別子（トリガー名など。件数や比率のような変動する数字は不可）を渡す。

    戻り値はASCIIの16進文字列なので、対象名に日本語やURLを含んでいても
    IDそのものは検索・表示に安全に使える。
    """
    basis = _SEP.join(p or "" for p in parts)
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:_DIGITS]
    return f"{prefix}{digest}"


def dedupe_ids(violations: list[dict]) -> list[dict]:
    """同じIDが複数件に振られてしまった場合の最終防衛.

    `make_id` に渡す識別要素が呼び出し側で足りず、本来別の指摘なのに基準文字列が
    一致してしまった場合（ハッシュそのものの衝突ではなく識別要素の取りこぼし）に、
    実行順に依存しない決定的な方法で連番を振り直す。カテゴリ・対象名・説明文で
    安定ソートしてから振るため、`events_observed` 等の入力順が変わっても
    結果は変わらない。

    渡されたリストを直接書き換えて返す（呼び出し側の使い勝手に合わせるため）。
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for v in violations:
        groups[v.get("id", "")].append(v)
    for base_id, members in groups.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda v: (
            v.get("category", ""), v.get("target_name", ""), v.get("description", ""),
        ))
        for i, v in enumerate(members):
            if i > 0:
                v["id"] = f"{base_id}-{i}"
    return violations
