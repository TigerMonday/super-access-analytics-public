"""HAR ファイルから GA4 の送信（`/g/collect`）を抜き出して一覧・要約する。

実機でテスト CV を踏んだときの記録を、目視より確実に突合するための道具。
「どのイベントが・何回・どの測定IDに・どんなパラメータで飛んだか」を表にする。
多重発火の実証と、`user_id` の実値確認に使う。

使い方:

    # 一覧（時系列）と要約
    python har_ga4.py report --in sample-signup.har

    # 正規化 JSON に落とす（案件フォルダの _data/ に置く）
    python har_ga4.py dump --in sample-signup.har --out _data/10-har-ga4.json

HAR の取り方（Chrome / Edge）:

    1. 新しいシークレットウィンドウを開く（広告ブロッカーは無効にする）
    2. DevTools → Network タブ → **「Preserve log」にチェック**
       （OAuth リダイレクトでページが遷移するため、これが無いと記録が消える）
    3. テスト CV を実施
    4. Network タブで右クリック → 「Save all as HAR with content」

`v=2` の GA4 送信のみを対象にする。1リクエストに複数イベントが載る
バッチ送信（POST 本文が改行区切り）にも対応する。

**出力する識別子は伏せ字化する。** HAR 原本をコミットしないのと同じ理由で、
抽出結果もクライアントID・セッションID・広告Cookie・URLの機微なクエリ
（OAuth の `code`/`state`、招待・再設定トークン、メールアドレス等）を素のまま残さない
（値の同一性だけ判別できる短いハッシュに置き換える）。
`user_id` の既定値（`"unknown"` 等）は**それ自体が所見**なのでそのまま残す。
生の値が必要なときは gitignore 済みの HAR 原本を直接見る。
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

import pii

# GA4 の収集エンドポイント。サーバーサイド GTM 経由（独自ドメイン）も拾えるよう
# パスで判定する。
GA4_PATHS = ("/g/collect", "/mp/collect")

# 参考として件数だけ数える他ベンダー
OTHER_VENDORS = {
    "Google 広告": ("/pagead/conversion", "/ccm/collect"),
    "Facebook": ("/tr",),
    "Microsoft 広告(UET)": ("/bat.js", "/action/"),
}

# 意味が分かるものだけ名前を付ける（GA4 の内部パラメータ名）
PARAM_LABELS = {
    "en": "イベント名",
    "tid": "測定ID",
    "cid": "クライアントID",
    "uid": "user_id",
    "sid": "セッションID",
    "dl": "ページURL",
    "dr": "リファラ",
    "sct": "セッション回数",
    "seg": "エンゲージ済み",
    "_et": "エンゲージ時間(ms)",
    "gcs": "同意状態",
    "_ss": "セッション開始",
    "_fv": "初回訪問",
}


# ──────────────────────────────────────
# 識別子の伏せ字化
#
# HAR 原本は Cookie・認証トークンを含むためコミットしない（`.gitignore` の `*.har`）。
# 一方、そこから抽出した JSON も **クライアントID・セッションID・広告Cookie** を
# そのまま持つため、同じ理由で伏せる必要がある。原本を除外しておきながら
# 派生物に素の識別子を残しては意味がない。
#
# ただし `user_id` の既定値（`"unknown"` 等）は**それ自体が調査の所見**なので残す。
# 値の同一性だけ判別できればよいものは、短いハッシュに置き換える。
# ──────────────────────────────────────

# それ自体が所見になる値。伏せずに残す。
SENTINEL_VALUES = frozenset({"", "unknown", "undefined", "null", "none", "0", "false", "true"})

# 値を伏せるパラメータ名（完全一致）
REDACT_PARAM_NAMES = frozenset({
    "user_data", "organization_id", "transaction_id", "event_id",
    "_fbp", "_fbc", "em", "ph", "fn", "ln",
    # 識別子そのものがイベントパラメータとして送られている場合も伏せる。
    # 上位フィールドの cid/sid は `_redact_hit` が処理するが、
    # パラメータ名として同じものが来ることがあるため二重に押さえる。
    "client_id", "session_id", "user_id", "cid", "sid", "uid",
})

# 値を伏せるパラメータ名（前方一致）。広告Cookieの引き渡しなど。
REDACT_PARAM_PREFIXES = ("x-fb-ck-", "x-ga-", "_p.", "gclid", "wbraid", "gbraid")

# ── 個人情報らしいパラメータ名の判定 ──────────────────────
#
# **部分一致で見てはいけない。** `age` は `page_title` / `engagement_time_msec` /
# `language` に、`name` は `event_name` / `campaign_name` / `item_name` に含まれる。
# 実際にこれで `event_name: PageView` をハッシュ化し、**タグ特定の決定的な証拠を
# 黙って壊した**（コミット済みの成果物に入っていた）。
#
# 名前は `_` `-` `.` で区切ったトークン単位で照合し、
# 分析に使う既知のパラメータは先に除外する。名前で拾えない分は値の形で拾う。

# GA4 標準・拡張計測のパラメータ。**絶対に伏せない**（伏せると分析ができなくなる）。
# 注: 識別子（`session_id` `client_id` `gclid` 等）はここに入れない。
# `REDACT_PARAM_NAMES` が先に判定されるため、両方に書くとこちらが死んで
# 「絶対に伏せない」という宣言が嘘になる。識別子は伏せる側で一貫させる。
# ハッシュは決定的なので、同一セッションのグルーピングは伏せた後も成立する。
NEVER_REDACT_PARAMS = frozenset({
    "page_title", "page_location", "page_referrer", "page_path", "page_hostname",
    "event_name", "engagement_time_msec", "language",
    "percent_scrolled", "screen_resolution", "content_group",
    "item_name", "item_id", "item_category", "campaign_name", "campaign",
    "source", "medium", "term", "content", "currency", "value", "method",
    "search_term", "link_url", "link_text", "link_domain", "outbound",
    "file_name", "file_extension", "video_title", "video_url", "form_id", "form_name",
})

# 単体で個人情報を指すトークン。区切りで分割して**完全一致**で見る。
PII_NAME_TOKENS = frozenset({
    "email", "mail", "phone", "tel", "mobile", "fax",
    "birthday", "birthdate", "dob", "gender", "age",
    "zipcode", "postcode", "ssn", "passport", "cvv", "iban",
    "lat", "lng", "latitude", "longitude",
})

# 人名・住所・カードを指す組み合わせ。`name` 単体は非個人情報にも多いので使わない。
PII_NAME_EXACT = frozenset({
    "first_name", "last_name", "family_name", "given_name", "full_name",
    "user_name", "member_name", "customer_name", "contact_name", "account_name",
    "address", "address1", "address2", "street_address", "home_address",
    "card_number", "credit_card", "card", "license_number",
})


def _looks_like_pii_name(name: str) -> bool:
    """パラメータ名が個人情報を指していそうか。"""
    low = name.lower()
    if low in NEVER_REDACT_PARAMS:
        return False
    if low in PII_NAME_EXACT:
        return True
    tokens = set(re.split(r"[_\-.]+", low))
    return bool(tokens & PII_NAME_TOKENS)

# 値そのものが個人情報の形をしているかの判定は pii.py に置く。
# ここで独自に正規表現を書くと基準が2箇所に分かれ、片方だけ直る。
# （自前定義した単語境界の指定が実際にはバックスペース文字になっていて機能していなかった）


# URL のクエシリに載りうる機微な値。OAuth の認可コードや招待・再設定トークン、
# メールアドレスなどが `dl`（ページURL）に含まれることがある。
# 派生 JSON はコミット前提なので、値だけ伏せてキー名は残す（あった事実は残す）。
REDACT_QUERY_KEYS = frozenset({
    "code", "state", "token", "access_token", "id_token", "refresh_token",
    "password", "passwd", "pwd", "secret", "api_key", "apikey", "key",
    "email", "mail", "e", "signature", "sig", "auth", "jwt", "otp",
    "invite", "invitation", "reset", "confirmation_token", "ticket", "session",
})
REDACT_QUERY_PREFIXES = ("utm_content_id", "gclid", "wbraid", "gbraid", "_ga")

# パスの「この語の次のセグメント」はトークンとみなして伏せる。
# `/invite/<token>` `/reset/<token>` のように、クエリではなくパスに秘密が載る形。
# メールアドレス等は pii.py が拾うが、任意のトークンは形では判別できないため
# 位置で判断する。
TOKEN_PATH_KEYWORDS = frozenset({
    "invite", "invitation", "reset", "confirm", "confirmation", "verify",
    "activate", "activation", "token", "magic", "unsubscribe", "share",
    "password", "recover", "recovery", "auth", "callback",
})


def _redact_path_tokens(path: str) -> str:
    """`/reset/<token>` のような、キーワードの次のセグメントを伏せる。"""
    segments = path.split("/")
    for i in range(len(segments) - 1):
        if segments[i].lower() in TOKEN_PATH_KEYWORDS and segments[i + 1]:
            segments[i + 1] = "[redacted]"
    return "/".join(segments)


def _redact_url(url: str) -> str:
    """URL のクエリから機微な値だけを伏せる。パスとその他のパラメータは残す。"""
    if not url:
        return url
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    try:
        parts = urlsplit(url)
    except ValueError:
        return "[解析不能なURL]"
    # **パスも伏せる。** メールアドレスや招待トークンがクエリではなくパスに
    # 載ることがある（実際に GA4 の pagePath に `/channels/<メールアドレス>` があった）。
    path, _ = pii.redact_text(_redact_path_tokens(parts.path))

    if not parts.query:
        return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    out = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        low = k.lower()
        if low in REDACT_QUERY_KEYS or low.startswith(REDACT_QUERY_PREFIXES):
            out.append((k, "[redacted]"))
            continue
        # **キー名だけで判断しない。** 汎用的なキー名（`q` `keyword` `input` 等）の
        # 値にメールアドレスや電話番号が載ることがある。値の形でも検査する。
        masked, n = pii.redact_text(v)
        out.append((k, masked if n else v))
    return urlunsplit((parts.scheme, parts.netloc, path,
                       urlencode(out, safe="[]"), ""))


def _hash(value: str) -> str:
    """値の同一性だけ判別できる短いハッシュにする。"""
    import hashlib
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _redact_value(name: str, value: str) -> str:
    """パラメータ1つを、必要なら伏せ字化して返す。"""
    if value is None:
        return value
    if str(value).strip().lower() in SENTINEL_VALUES:
        return value  # 既定値の混入は所見なので残す
    low = name.lower()
    if low in REDACT_PARAM_NAMES or low.startswith(REDACT_PARAM_PREFIXES):
        return _hash(str(value))
    if _looks_like_pii_name(name):
        return _hash(str(value))
    text = str(value)
    # URL を値に持つパラメータ（`link_url` など）は、URL としての伏せ字化を通す。
    # ハッシュにすると分析に使えなくなるので、機微な部分だけ落とす。
    if text.startswith(("http://", "https://")):
        return _redact_url(text)
    if pii.contains_pii(text):
        return _hash(text)
    return value


def _redact_hit(hit: dict) -> dict:
    """1イベント分の識別子を伏せ字化する。"""
    # ページURLのクエリに OAuth コードや招待トークンが載ることがある
    if hit.get("page_location"):
        hit["page_location"] = _redact_url(str(hit["page_location"]))
    for key in ("client_id", "session_id"):
        if hit.get(key):
            hit[key] = _hash(str(hit[key]))
    # user_id は既定値の混入を見たいので、sentinel はそのまま・実IDはハッシュ
    if hit.get("user_id"):
        hit["user_id"] = _redact_value("user_id_value", hit["user_id"]) \
            if str(hit["user_id"]).strip().lower() in SENTINEL_VALUES else _hash(str(hit["user_id"]))
    for bucket in ("event_params", "user_properties"):
        params = hit.get(bucket) or {}
        hit[bucket] = {k: _redact_value(k, v) for k, v in params.items()}
    return hit


def _is_ga4(url: str) -> bool:
    path = urlparse(url).path
    return any(path.endswith(p) or path == p for p in GA4_PATHS)


def _vendor(url: str) -> str | None:
    path = urlparse(url).path
    for name, paths in OTHER_VENDORS.items():
        if any(p in path for p in paths):
            return name
    return None


def _post_text(entry: dict) -> str:
    return (entry.get("request", {}).get("postData", {}) or {}).get("text", "") or ""


def extract_hits(har: dict) -> tuple[list[dict], Counter]:
    """HAR から GA4 イベントを1件ずつに展開する。戻り値は (イベント一覧, 他ベンダー件数)。"""
    entries = har.get("log", {}).get("entries", [])
    hits: list[dict] = []
    others: Counter = Counter()

    for entry in entries:
        url = entry.get("request", {}).get("url", "")
        if not _is_ga4(url):
            vendor = _vendor(url)
            if vendor:
                others[vendor] += 1
            continue

        base = dict(parse_qsl(urlparse(url).query, keep_blank_values=True))
        if base.get("v") not in (None, "2"):
            continue  # v=2 以外（旧 UA など）は対象外

        started = entry.get("startedDateTime", "")
        method = entry.get("request", {}).get("method", "")
        status = entry.get("response", {}).get("status", "")
        host = urlparse(url).netloc

        # POST 本文があればバッチ送信。1行 = 1イベント。
        body = _post_text(entry)
        lines = [ln for ln in body.split("\n") if ln.strip()] if body else []

        if lines:
            for i, line in enumerate(lines):
                params = dict(base)
                params.update(dict(parse_qsl(line, keep_blank_values=True)))
                hits.append(_build(params, started, method, status, host, batch_index=i,
                                   batch_size=len(lines)))
        else:
            hits.append(_build(base, started, method, status, host))

    return hits, others


def _build(params: dict, started: str, method: str, status, host: str,
           batch_index: int = 0, batch_size: int = 1) -> dict:
    event_params = {k[3:]: v for k, v in params.items() if k.startswith("ep.")}
    event_params.update({k[4:]: v for k, v in params.items() if k.startswith("epn.")})
    user_props = {k[3:]: v for k, v in params.items() if k.startswith("up.")}
    user_props.update({k[4:]: v for k, v in params.items() if k.startswith("upn.")})
    # 抽出した時点で伏せ字化する。生の識別子を持ったまま呼び出し側に返さない。
    return _redact_hit({
        "time": started,
        "method": method,
        "status": status,
        "host": host,
        "event_name": params.get("en", ""),
        "measurement_id": params.get("tid", ""),
        "client_id": params.get("cid", ""),
        "user_id": params.get("uid", ""),
        "session_id": params.get("sid", ""),
        "page_location": params.get("dl", ""),
        "consent": params.get("gcs", ""),
        "batch": f"{batch_index + 1}/{batch_size}" if batch_size > 1 else "",
        "event_params": event_params,
        "user_properties": user_props,
    })


def summarize(hits: list[dict]) -> dict:
    by_event = Counter(h["event_name"] for h in hits)
    by_tid = Counter(h["measurement_id"] for h in hits)
    by_host = Counter(h["host"] for h in hits)
    uids = Counter(h["user_id"] for h in hits if h["user_id"])
    # 同一イベントが同一ページで複数回飛んでいる箇所
    dupes: dict[tuple[str, str], int] = defaultdict(int)
    for h in hits:
        dupes[(h["event_name"], h["page_location"])] += 1
    return {
        "total_events": len(hits),
        "by_event": dict(by_event.most_common()),
        "by_measurement_id": dict(by_tid.most_common()),
        "by_host": dict(by_host.most_common()),
        "user_ids": dict(uids.most_common()),
        "repeated": {f"{e} @ {p}": n for (e, p), n in
                     sorted(dupes.items(), key=lambda x: -x[1]) if n > 1},
    }


def build_report(hits: list[dict], others: Counter) -> str:
    s = summarize(hits)
    out = [
        "# GA4 送信ログ（HAR より）",
        "",
        f"- GA4 イベント送信: **{s['total_events']} 件**",
        f"- 送信先ホスト: {', '.join(f'{k}({v})' for k, v in s['by_host'].items()) or 'なし'}",
        f"- 測定ID: {', '.join(f'{k}({v})' for k, v in s['by_measurement_id'].items()) or 'なし'}",
    ]
    if others:
        out.append(f"- 他ベンダーへの送信: {', '.join(f'{k}({v})' for k, v in others.items())}")

    out += ["", "## イベント別の件数", "", "| イベント名 | 件数 |", "|---|---|"]
    for name, n in s["by_event"].items():
        out.append(f"| `{name}` | {n} |")

    out += ["", "## user_id の実値", ""]
    if not s["user_ids"]:
        out.append("`uid` パラメータは送信されていない。")
    else:
        out += ["| user_id | 件数 |", "|---|---|"]
        for uid, n in s["user_ids"].items():
            flag = "  ← **既定値がそのまま送られている**" if uid in ("unknown", "undefined", "null", "") else ""
            out.append(f"| `{uid}` | {n} |{flag}")

    out += ["", "## 同一ページで複数回飛んでいるイベント（多重発火）", ""]
    if not s["repeated"]:
        out.append("該当なし。")
    else:
        out += ["| イベント @ ページ | 回数 |", "|---|---|"]
        for key, n in s["repeated"].items():
            out.append(f"| {key} | **{n}** |")

    out += ["", "## 時系列", "", "| # | 時刻 | イベント名 | 測定ID | user_id | ページ |", "|---|---|---|---|---|---|"]
    for i, h in enumerate(hits, 1):
        t = h["time"][11:23] if len(h["time"]) > 23 else h["time"]
        page = h["page_location"]
        page = page[:70] + "…" if len(page) > 70 else page
        batch = f" ({h['batch']})" if h["batch"] else ""
        out.append(f"| {i} | {t}{batch} | `{h['event_name']}` | {h['measurement_id']} | "
                   f"`{h['user_id']}` | {page} |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_report = sub.add_parser("report", help="一覧と要約を出力")
    p_report.add_argument("--in", dest="infile", required=True)
    p_report.add_argument("--out", default="", help="省略時は標準出力")

    p_dump = sub.add_parser("dump", help="正規化 JSON に落とす")
    p_dump.add_argument("--in", dest="infile", required=True)
    p_dump.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    har = json.loads(Path(args.infile).read_text(encoding="utf-8-sig"))
    hits, others = extract_hits(har)

    if args.command == "report":
        text = build_report(hits, others)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"レポートを書き出しました → {args.out}")
        else:
            print(text)
        return 0

    if args.command == "dump":
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source": {"har": str(args.infile)},
            "summary": summarize(hits),
            "other_vendors": dict(others),
            "hits": hits,
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"GA4 イベント {len(hits)} 件を書き出しました → {out}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
