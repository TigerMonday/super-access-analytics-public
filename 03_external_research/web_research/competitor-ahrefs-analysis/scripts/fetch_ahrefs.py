#!/usr/bin/env python3
"""Ahrefs API v3 を直接叩く CLI（標準ライブラリのみ、依存ゼロ）

このリポの `03_external_research` テーマは依存ゼロ方針のため、`urllib.request` のみで実装している。
`requests` 等は追加しないこと。

**このスクリプトは Ahrefs の契約（API トークン）が無いと動かない。** 契約が無い場合は
`../SKILL.md` の手順ごと使わなくてよい（`external-research-coordinator` 経由の実行では
トークン未設定時にこの子スキルの章を丸ごとスキップする）。

## 認証
- 解決順: ① 環境変数 `AHREFS_API_TOKEN` → ② `~/.saa/credentials/ahrefs/token.txt`
- トークンの値は絶対に stdout/stderr/保存ファイルに出力しない

## サブコマンド
    limits                                                残ユニット確認（--client 不要）
    overview       --client X --targets a.com,b.com,c.com  DR・被リンク・オーガニックKW数の横並び
    organic-keywords --client X --target a.com [--min-volume 100 --max-position 10 --limit 1000]
    refdomains     --client X --target a.com [--min-dr 50 --limit 500]
    serp           --client X --keyword "キーワード"        上位10件のSERP
    kw-overview    --client X --keywords "kw1,kw2,kw3"      volume/KD/CPC
    gap            --client X --own a.com --competitors b.com,c.com
                   キーワードギャップ（UC-2）＋被リンクギャップ（UC-3）を決定論的に計算・保存

## 使用例
    uv run python scripts/fetch_ahrefs.py limits
    uv run python scripts/fetch_ahrefs.py overview --client sample-client --targets example.com,example.org
    uv run python scripts/fetch_ahrefs.py organic-keywords --client sample-client --target example.com --min-volume 100 --max-position 10 --limit 1000
    uv run python scripts/fetch_ahrefs.py refdomains --client sample-client --target example.com --min-dr 50 --limit 500
    uv run python scripts/fetch_ahrefs.py serp --client sample-client --keyword "アクセス解析"
    uv run python scripts/fetch_ahrefs.py kw-overview --client sample-client --keywords "アクセス解析,GA4,ヒートマップ"
    uv run python scripts/fetch_ahrefs.py gap --client sample-client --own example.com --competitors example.org,example.net --exclude "サンプル社,サンプルブランド"

## 保存先
    <リポルート>/outputs/{client_id}/_data/ahrefs/{subcommand}_{slug}_{YYYYMMDD}.json
    エンベロープ: fetched_at / endpoint / params / units_consumed / rows
    gap のみ形式が異なる: fetched_at / params / own_dr / kd_threshold / units_consumed /
    keyword_gap[] / keyword_gap_kd_over[] / backlink_gap[] / excluded_brand_count / source_files[]
    ファイル名: gap_{own}_vs_{競合slug}_{YYYYMMDD}.json

## API 仕様メモ（実装時に実機検証して確定した内容。次の設計変更時の参考に残す）
- ほぼ全ての site-explorer 系エンドポイントは `date=YYYY-MM-DD`（当日でよい）が必須
- `select` を要求するエンドポイントは `where` によるサーバー側フィルタが使えるが、構文は
  `{"field": "<col>", "is": ["<op>", <value>]}`（複数条件は `{"and": [...]}` / `{"or": [...]}`）。
  `gte` / `lte` / `eq` 等の演算子は `is` 配列の1つ目の要素として渡す（ドット記法や `>` 等は 400 エラー）
- `order_by` は `"<col>:asc"` / `"<col>:desc"` 形式
- `domain-rating` / `backlinks-stats` はドメイン全体の値で `country` を無視する。`country` が意味を持つのは
  `metrics`（オーガニック流入・KW数）や `organic-keywords` 系
- ユニット消費はレスポンスヘッダ `x-api-units-cost-total-actual` を見る（`x-api-units-cost-total` は
  リクエスト時点の見積り、`-actual` が実際の課金値。エラーレスポンス時はヘッダ自体が付かない＝消費0）
- `serp-overview` は `top_positions=N` を指定しても SERP 特集枠（AI Overview・強調スニペット・PAA 等）が
  同じ position 番号で複数行返るため、そのまま件数を絞ると「上位10位」にならない。`type` フィールド
  （配列。例: `["organic"]` / `["ai_overview_sitelink","image_th"]`）でオーガニック行だけをクライアント側で
  絞り込む必要がある（`where` で `type` の配列フィルタを試したが、サーバー側では効かず素通りだった）
- `keywords-explorer/overview` `/related-terms` `/matching-terms` `/search-suggestions` は本アカウント
  （Advanced プラン）では **パラメータの組み合わせに関係なく常に `500 internal server error`** になった
  （`keyword_list_id`・`keywords`・`target` 等どの入力でも同じ）。一方 `keywords-explorer/volume-history`
  （`keyword` 単数形、`select` 不要、固定スキーマで `date`/`volume` の月次系列のみ返す）は正常に動作した。
  ヘルプセンターの記載上はプラン間で API v3 のエンドポイント自体に差はない（月間ユニット上限・最大行数のみ差）
  ため、恐らく Ahrefs 側の一時的な不具合。`kw-overview` は overview を優先し、`500` を検知したら
  `volume-history` へ自動フォールバック（KD・CPC は取得不可としてログに明記）する
- エラーレスポンス（400番台）は課金されず、`{"error": "..."}` に原因が明示される（パラメータ調整に使える）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# Windows + Git Bash等では既定の画面エンコーディングがUTF-8にならず、日本語の
# 表示だけが文字化けすることがある（ファイル自体はUTF-8で正しく書かれている）。
# 明示的にUTF-8へ揃えて防ぐ。reconfigure非対応の環境（一部のリダイレクト等）では
# 何もしない（元の表示に戻るだけで、実行そのものは失敗させない）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

BASE_URL = "https://api.ahrefs.com/v3"
REPO_ROOT = Path(__file__).resolve().parents[4]
CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# select 列の定義（課金は「行数 × 選択列数」のため、事前見積りにも使う。2026-07-12 実測で確定）。
#
# 2026-07-14 ユニット削減: `gap` 内部呼び出し（build_keyword_gap / build_backlink_gap / gap のレポート
# 出力）を全行読み、競合側 organic-keywords の sum_traffic・best_position_url と refdomains の
# first_seen が一切参照されていないことを確認した上で、gap 用の select を用途別に分離した。
# - 競合側は「volume/best_position/keyword_difficulty での突合」にしか使わないため4列に削減
# - 自社側は best_position_url をリライト/内部リンク強化の対象ページ特定用に残すため5列
#   （アクション判定自体は best_position の数値で行う。URLはギャップ結果行の
#    own_best_position_url フィールドとレポート表「自社URL」列に伝搬される）
# - refdomains は自社/競合とも domain・DR・dofollow数しか使わないため3列に統一
# 単体の `organic-keywords` サブコマンド（人間が表を見るための独立実行）は従来通りフル6列を既定にし、
# `--select` で上書き可能にしている（主用途は gap 経由のため、そちらの内部呼び出しだけ最適化すれば十分）。
ORGANIC_KW_SELECT = "keyword,best_position,volume,keyword_difficulty,sum_traffic,best_position_url"  # organic-keywords サブコマンド既定（フル6列）
GAP_OWN_KW_SELECT = "keyword,best_position,volume,keyword_difficulty,best_position_url"  # gap: 自社側（5列）
GAP_COMPETITOR_KW_SELECT = "keyword,best_position,volume,keyword_difficulty"  # gap: 競合側（4列）
REFDOMAINS_SELECT = "domain,domain_rating,dofollow_links"  # 自社/競合/単体共通（3列。first_seen は未使用のため削除）

# --cache-days 明示指定が無いときのエンドポイント別既定値（2026-07-14 導入）。
# 根拠: 検索順位は日次で動くが打ち手の優先度判断に日次精度は不要。被リンク・DRは月単位でしか動かない。
CACHE_DAYS_OVERVIEW_DEFAULT = 30  # domain-rating / backlinks-stats / metrics
CACHE_DAYS_ORGANIC_KW_DEFAULT = 14  # organic-keywords
CACHE_DAYS_REFDOMAINS_DEFAULT = 30  # refdomains
CACHE_DAYS_SERP_DEFAULT = 7  # serp-overview（現状維持）
CACHE_DAYS_KW_OVERVIEW_DEFAULT = 7  # kw-overview（今回のスコープ外。現状維持）


def resolve_cache_days(explicit: int | None, endpoint_default: int) -> int:
    """--cache-days の明示指定はエンドポイント別既定値より常に優先する（従来互換）。"""
    return explicit if explicit is not None else endpoint_default


class AhrefsAPIError(RuntimeError):
    def __init__(self, status: int, message: str, path: str):
        super().__init__(f"Ahrefs API error ({status}) at {path}: {message}")
        self.status = status
        self.message = message
        self.path = path


# ---------------------------------------------------------------------------
# 認証
# ---------------------------------------------------------------------------

def resolve_token() -> str:
    token = os.environ.get("AHREFS_API_TOKEN")
    if token:
        return token.strip()

    token_path = Path.home() / ".saa" / "credentials" / "ahrefs" / "token.txt"
    if token_path.exists():
        token = token_path.read_text(encoding="utf-8").strip()
        if token:
            return token

    print(
        "エラー: Ahrefs APIトークンが見つかりません。この機能は Ahrefs の契約が必要です。"
        f" 環境変数 AHREFS_API_TOKEN か {token_path} のいずれかにトークンを設定してください"
        "（Ahrefsを契約していない場合は、この子スキル自体が使えません。他の市場・顧客理解の"
        "子スキルで代替してください）。",
        file=sys.stderr,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def call_api(path: str, params: dict[str, Any] | None, token: str) -> tuple[dict, int]:
    """Ahrefs API を1回叩く。戻り値は (JSONボディ, 消費ユニット数)。失敗時は AhrefsAPIError。"""
    query = urllib.parse.urlencode(params or {})
    url = f"{BASE_URL}{path}"
    if query:
        url += f"?{query}"

    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            headers = dict(resp.getheaders())
            body_text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        headers = dict(e.headers) if e.headers else {}
        body_text = e.read().decode("utf-8") if e.fp else ""
        try:
            body = json.loads(body_text) if body_text else {}
        except json.JSONDecodeError:
            body = {"error": body_text}
        message = body.get("error", body_text or f"HTTP {e.code}")
        raise AhrefsAPIError(e.code, message, path) from None
    except urllib.error.URLError as e:
        raise AhrefsAPIError(0, f"接続エラー: {e.reason}", path) from None

    try:
        body = json.loads(body_text) if body_text else {}
    except json.JSONDecodeError:
        body = {}

    units = int(
        headers.get("x-api-units-cost-total-actual")
        or headers.get("x-api-units-cost-total")
        or 0
    )
    return body, units


# ---------------------------------------------------------------------------
# 保存 / キャッシュ
# ---------------------------------------------------------------------------

def slugify(text: str, max_len: int = 60) -> str:
    """ファイル名に安全な形へ。ASCII以外（日本語キーワード等）はハッシュ化する。"""
    if re.fullmatch(r"[A-Za-z0-9._-]+", text):
        return text[:max_len]
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    return f"hash{digest}"


def multi_slug(items: list[str], max_len: int = 80) -> str:
    joined = "_".join(items)
    return slugify(joined, max_len=max_len)


def data_dir(client_id: str) -> Path:
    if not isinstance(client_id, str) or not CLIENT_ID_RE.fullmatch(client_id):
        raise ValueError(
            "client_id は英数字・ハイフン・アンダースコアだけで指定してください"
        )

    outputs_root = (REPO_ROOT / "outputs").resolve()
    d = (outputs_root / client_id / "_data" / "ahrefs").resolve()
    try:
        d.relative_to(outputs_root)
    except ValueError:
        raise ValueError("出力先が outputs ディレクトリの外です") from None

    d.mkdir(parents=True, exist_ok=True)
    return d


def find_cached(d: Path, subcommand: str, slug: str, cache_days: int) -> Path | None:
    pattern = re.compile(rf"^{re.escape(subcommand)}_{re.escape(slug)}_(\d{{8}})\.json$")
    candidates: list[tuple[date, Path]] = []
    for p in d.glob(f"{subcommand}_{slug}_*.json"):
        m = pattern.match(p.name)
        if not m:
            continue
        try:
            file_date = datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        candidates.append((file_date, p))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    newest_date, newest_path = candidates[0]
    if (date.today() - newest_date).days <= cache_days:
        return newest_path
    return None


def save_envelope(
    d: Path,
    subcommand: str,
    slug: str,
    endpoint: str,
    params: dict[str, Any],
    units_consumed: int,
    rows: Any,
) -> Path:
    envelope = {
        "fetched_at": datetime.now().astimezone().isoformat(),
        "endpoint": endpoint,
        "params": params,
        "units_consumed": units_consumed,
        "rows": rows,
    }
    today_str = date.today().strftime("%Y%m%d")
    path = d / f"{subcommand}_{slug}_{today_str}.json"
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_envelope(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 安全チェック: 残ユニット確認
# ---------------------------------------------------------------------------

def get_remaining_units(token: str) -> int | None:
    """このAPIキーの残ユニット数を返す（取得できなければ None）。"""
    body, _ = call_api("/subscription-info/limits-and-usage", None, token)
    info = body.get("limits_and_usage", {})
    limit = info.get("units_limit_api_key")
    usage = info.get("units_usage_api_key")
    if limit is None or usage is None:
        return None
    return limit - usage


def check_remaining_units(token: str, threshold: int = 10000) -> None:
    body, _ = call_api("/subscription-info/limits-and-usage", None, token)
    info = body.get("limits_and_usage", {})
    limit = info.get("units_limit_api_key")
    usage = info.get("units_usage_api_key")
    if limit is None or usage is None:
        return
    remaining = limit - usage
    if remaining < threshold:
        print(
            f"エラー: APIキーの残ユニットが {remaining:,} で閾値 {threshold:,} を下回っています。"
            " 取得系の実行を中止します（limits サブコマンドで詳細確認可）。",
            file=sys.stderr,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# where 句ビルダー
# ---------------------------------------------------------------------------

def build_where(conditions: list[tuple[str, str, Any]]) -> str | None:
    """conditions: [(field, op, value), ...] -> where JSON文字列。空なら None。"""
    clauses = [{"field": f, "is": [op, v]} for f, op, v in conditions]
    if not clauses:
        return None
    if len(clauses) == 1:
        return json.dumps(clauses[0], ensure_ascii=False)
    return json.dumps({"and": clauses}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# サブコマンド実装
# ---------------------------------------------------------------------------

def cmd_limits(args, token: str) -> None:
    body, units = call_api("/subscription-info/limits-and-usage", None, token)
    info = body.get("limits_and_usage", {})
    print("=== Ahrefs API 残ユニット ===")
    print(f"サブスクリプション: {info.get('subscription')}")
    print(f"リセット日: {info.get('usage_reset_date')}")
    print(
        f"ワークスペース全体: {info.get('units_usage_workspace'):,} / "
        f"{info.get('units_limit_workspace'):,} units使用"
    )
    print(
        f"このAPIキー: {info.get('units_usage_api_key'):,} / "
        f"{info.get('units_limit_api_key'):,} units使用"
    )
    print(f"APIキー有効期限: {info.get('api_key_expiration_date')}")
    print(f"\n消費ユニット: {units}")


def cmd_overview(args, token: str) -> None:
    targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    slug = multi_slug(targets)
    d = data_dir(args.client)

    cache_days = resolve_cache_days(args.cache_days, CACHE_DAYS_OVERVIEW_DEFAULT)
    cached = None if args.refresh else find_cached(d, "overview", slug, cache_days)
    if cached:
        env = load_envelope(cached)
        print(f"キャッシュ使用（取得日: {env['fetched_at'][:10]}） -> {cached}")
        print_overview_table(env["rows"])
        print(f"\n消費ユニット: 0（キャッシュ利用。取得時消費: {env['units_consumed']}）")
        return

    check_remaining_units(token)

    today = date.today().isoformat()
    total_units = 0
    rows = []
    for target in targets:
        row: dict[str, Any] = {"target": target}

        dr_body, u = call_api(
            "/site-explorer/domain-rating", {"target": target, "date": today}, token
        )
        total_units += u
        dr = dr_body.get("domain_rating", {})
        row["domain_rating"] = dr.get("domain_rating")
        row["ahrefs_rank"] = dr.get("ahrefs_rank")

        bl_body, u = call_api(
            "/site-explorer/backlinks-stats", {"target": target, "date": today}, token
        )
        total_units += u
        bl = bl_body.get("metrics", {})
        row["backlinks_live"] = bl.get("live")
        row["refdomains_live"] = bl.get("live_refdomains")

        m_body, u = call_api(
            "/site-explorer/metrics",
            {"target": target, "date": today, "country": args.country},
            token,
        )
        total_units += u
        m = m_body.get("metrics", {})
        row["org_keywords"] = m.get("org_keywords")
        row["org_traffic"] = m.get("org_traffic")

        rows.append(row)

    endpoint = "/site-explorer/domain-rating + backlinks-stats + metrics"
    params = {"targets": targets, "country": args.country, "date": today}
    path = save_envelope(d, "overview", slug, endpoint, params, total_units, rows)
    print(f"保存: {path}")
    print_overview_table(rows)
    print(f"\n消費ユニット: {total_units}")


def print_overview_table(rows: list[dict]) -> None:
    print("\n| サイト | DR | 参照ドメイン数 | 被リンク数 | オーガニックKW数 | 流入推計(月) |")
    print("|---|---:|---:|---:|---:|---:|")
    for r in rows:
        print(
            f"| {r.get('target')} | {fmt(r.get('domain_rating'))} | "
            f"{fmt(r.get('refdomains_live'))} | {fmt(r.get('backlinks_live'))} | "
            f"{fmt(r.get('org_keywords'))} | {fmt(r.get('org_traffic'))} |"
        )


def fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:,.1f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def fetch_organic_keywords(
    d: Path,
    target: str,
    country: str,
    min_volume: int,
    max_position: int,
    limit: int,
    token: str,
    refresh: bool,
    cache_days: int,
    skip_units_check: bool = False,
    select: str = ORGANIC_KW_SELECT,
) -> tuple[list[dict], int, Path, bool]:
    """organic-keywords を（キャッシュ経由で）取得する共通ロジック。

    戻り値: (rows, この呼び出しでの新規消費ユニット, 参照/保存したファイルパス, キャッシュを使ったか)
    `organic-keywords` サブコマンドと `gap` サブコマンド（自社側/競合側で列数が違う）の両方から使う。
    `select` は呼び出し元ごとに変わるため、キャッシュの slug に列数タグ（例 `_c4`）を含めて、
    列構成が異なるキャッシュファイルを取り違えないようにしている。
    """
    col_count = len(select.split(","))
    slug = slugify(f"{target}_minvol{min_volume}_maxpos{max_position}_limit{limit}_c{col_count}")

    cached = None if refresh else find_cached(d, "organic-keywords", slug, cache_days)
    if cached:
        env = load_envelope(cached)
        return env["rows"], 0, cached, True

    if not skip_units_check:
        check_remaining_units(token)

    today = date.today().isoformat()
    where = build_where(
        [
            ("volume", "gte", min_volume),
            ("best_position", "lte", max_position),
        ]
    )
    params = {
        "target": target,
        "date": today,
        "country": country,
        "select": select,
        "order_by": "volume:desc",
        "limit": limit,
        "mode": "domain",
    }
    if where:
        params["where"] = where

    body, units = call_api("/site-explorer/organic-keywords", params, token)
    rows = body.get("keywords", [])

    path = save_envelope(d, "organic-keywords", slug, "/site-explorer/organic-keywords", params, units, rows)
    return rows, units, path, False


def cmd_organic_keywords(args, token: str) -> None:
    d = data_dir(args.client)
    rows, units, path, cached = fetch_organic_keywords(
        d,
        args.target,
        args.country,
        args.min_volume,
        args.max_position,
        args.limit,
        token,
        args.refresh,
        resolve_cache_days(args.cache_days, CACHE_DAYS_ORGANIC_KW_DEFAULT),
        select=args.select,
    )
    if cached:
        env = load_envelope(path)
        print(f"キャッシュ使用（取得日: {env['fetched_at'][:10]}） -> {path}")
        print_keywords_table(rows)
        print(f"\n消費ユニット: 0（キャッシュ利用。取得時消費: {env['units_consumed']}）")
        return

    print(f"保存: {path}")
    print_keywords_table(rows)
    print(f"\n消費ユニット: {units}")


def print_keywords_table(rows: list[dict]) -> None:
    print(f"\n行数: {len(rows)}")
    print("| キーワード | 順位 | Volume | KD | 流入推計 | 上位URL |")
    print("|---|---:|---:|---:|---:|---|")
    for r in rows[:20]:
        print(
            f"| {r.get('keyword')} | {fmt(r.get('best_position'))} | "
            f"{fmt(r.get('volume'))} | {fmt(r.get('keyword_difficulty'))} | "
            f"{fmt(r.get('sum_traffic'))} | {r.get('best_position_url', '-')} |"
        )
    if len(rows) > 20:
        print(f"...他 {len(rows) - 20} 行（保存ファイル参照）")


def fetch_refdomains(
    d: Path,
    target: str,
    min_dr: int,
    limit: int,
    token: str,
    refresh: bool,
    cache_days: int,
    skip_units_check: bool = False,
) -> tuple[list[dict], int, Path, bool]:
    """refdomains を（キャッシュ経由で）取得する共通ロジック。

    戻り値: (rows, この呼び出しでの新規消費ユニット, 参照/保存したファイルパス, キャッシュを使ったか)
    `refdomains` サブコマンドと `gap` サブコマンドの両方から使う。
    """
    slug = slugify(f"{target}_mindr{min_dr}_limit{limit}")

    cached = None if refresh else find_cached(d, "refdomains", slug, cache_days)
    if cached:
        env = load_envelope(cached)
        return env["rows"], 0, cached, True

    if not skip_units_check:
        check_remaining_units(token)

    today = date.today().isoformat()
    select = REFDOMAINS_SELECT
    where = build_where([("domain_rating", "gte", min_dr)])
    params = {
        "target": target,
        "date": today,
        "select": select,
        "order_by": "domain_rating:desc",
        "limit": limit,
        "mode": "domain",
    }
    if where:
        params["where"] = where

    body, units = call_api("/site-explorer/refdomains", params, token)
    rows = body.get("refdomains", [])

    path = save_envelope(d, "refdomains", slug, "/site-explorer/refdomains", params, units, rows)
    return rows, units, path, False


def cmd_refdomains(args, token: str) -> None:
    d = data_dir(args.client)
    rows, units, path, cached = fetch_refdomains(
        d, args.target, args.min_dr, args.limit, token, args.refresh,
        resolve_cache_days(args.cache_days, CACHE_DAYS_REFDOMAINS_DEFAULT),
    )
    if cached:
        env = load_envelope(path)
        print(f"キャッシュ使用（取得日: {env['fetched_at'][:10]}） -> {path}")
        print_refdomains_table(rows)
        print(f"\n消費ユニット: 0（キャッシュ利用。取得時消費: {env['units_consumed']}）")
        return

    print(f"保存: {path}")
    print_refdomains_table(rows)
    print(f"\n消費ユニット: {units}")


def print_refdomains_table(rows: list[dict]) -> None:
    # 2026-07-14 ユニット削減で select から first_seen を外したため表示列からも削除
    print(f"\n行数: {len(rows)}")
    print("| 参照ドメイン | DR | dofollowリンク数 |")
    print("|---|---:|---:|")
    for r in rows[:20]:
        print(
            f"| {r.get('domain')} | {fmt(r.get('domain_rating'))} | "
            f"{fmt(r.get('dofollow_links'))} |"
        )
    if len(rows) > 20:
        print(f"...他 {len(rows) - 20} 行（保存ファイル参照）")


def cmd_serp(args, token: str) -> None:
    keyword = args.keyword
    slug = slugify(keyword)
    d = data_dir(args.client)

    cache_days = resolve_cache_days(args.cache_days, CACHE_DAYS_SERP_DEFAULT)
    cached = None if args.refresh else find_cached(d, "serp", slug, cache_days)
    if cached:
        env = load_envelope(cached)
        print(f"キャッシュ使用（取得日: {env['fetched_at'][:10]}） -> {cached}")
        print_serp_table(env["rows"])
        print(f"\n消費ユニット: 0（キャッシュ利用。取得時消費: {env['units_consumed']}）")
        return

    check_remaining_units(token)

    select = "position,type,url,title,domain_rating,traffic"
    params = {
        "select": select,
        "country": args.country,
        "keyword": keyword,
        "top_positions": 20,
    }
    body, units = call_api("/serp-overview/serp-overview", params, token)
    all_rows = body.get("positions", [])
    # SERP特集枠（AI Overview / PAA 等）を除き、オーガニック行だけ上位10件に絞る
    organic_rows = [r for r in all_rows if isinstance(r.get("type"), list) and "organic" in r["type"]]
    rows = organic_rows[:10]

    endpoint = "/serp-overview/serp-overview"
    path = save_envelope(d, "serp", slug, endpoint, params, units, rows)
    print(f"保存: {path}")
    print_serp_table(rows)
    print(f"\n消費ユニット: {units}")


def print_serp_table(rows: list[dict]) -> None:
    print(f"\n行数: {len(rows)}")
    print("| 順位 | URL | タイトル | DR | 推定トラフィック |")
    print("|---:|---|---|---:|---:|")
    for r in rows:
        print(
            f"| {fmt(r.get('position'))} | {r.get('url', '-')} | {r.get('title', '-')} | "
            f"{fmt(r.get('domain_rating'))} | {fmt(r.get('traffic'))} |"
        )


def cmd_kw_overview(args, token: str) -> None:
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    slug = multi_slug(keywords)
    d = data_dir(args.client)

    cache_days = resolve_cache_days(args.cache_days, CACHE_DAYS_KW_OVERVIEW_DEFAULT)
    cached = None if args.refresh else find_cached(d, "kw-overview", slug, cache_days)
    if cached:
        env = load_envelope(cached)
        print(f"キャッシュ使用（取得日: {env['fetched_at'][:10]}） -> {cached}")
        print_kw_overview_table(env["rows"])
        print(f"\n消費ユニット: 0（キャッシュ利用。取得時消費: {env['units_consumed']}）")
        return

    check_remaining_units(token)

    total_units = 0
    endpoint_used = "/keywords-explorer/overview"
    try:
        select = "keyword,volume,difficulty,cpc"
        params = {"select": select, "country": args.country, "keywords": ",".join(keywords)}
        body, units = call_api("/keywords-explorer/overview", params, token)
        total_units += units
        rows = body.get("keywords", [])
    except AhrefsAPIError as e:
        print(
            f"警告: /keywords-explorer/overview が失敗しました（{e}）。"
            " volume-history へフォールバックします（KD/CPCは取得できません）。",
            file=sys.stderr,
        )
        endpoint_used = "/keywords-explorer/volume-history (fallback)"
        rows = []
        # date_from/date_to を直近2ヶ月に絞ることで行数（=ユニット消費）を最小化する
        # （無指定だと2015年からの全月次履歴が返り、1キーワードあたり250+ units かかる）
        date_to = date.today().isoformat()
        date_from = (date.today() - timedelta(days=60)).isoformat()
        for kw in keywords:
            try:
                vh_body, units = call_api(
                    "/keywords-explorer/volume-history",
                    {
                        "keyword": kw,
                        "country": args.country,
                        "date_from": date_from,
                        "date_to": date_to,
                    },
                    token,
                )
                total_units += units
                metrics = vh_body.get("metrics", [])
                latest = metrics[-1] if metrics else {}
                rows.append(
                    {
                        "keyword": kw,
                        "volume": latest.get("volume"),
                        "volume_as_of": latest.get("date"),
                        "difficulty": None,
                        "cpc": None,
                    }
                )
            except AhrefsAPIError as e2:
                print(f"警告: {kw} の取得にも失敗: {e2}", file=sys.stderr)
                rows.append({"keyword": kw, "volume": None, "difficulty": None, "cpc": None})

    params_saved = {"keywords": keywords, "country": args.country}
    path = save_envelope(d, "kw-overview", slug, endpoint_used, params_saved, total_units, rows)
    print(f"保存: {path}")
    print_kw_overview_table(rows)
    print(f"\n消費ユニット: {total_units}")


def print_kw_overview_table(rows: list[dict]) -> None:
    print("\n| キーワード | Volume | KD | CPC |")
    print("|---|---:|---:|---:|")
    for r in rows:
        print(
            f"| {r.get('keyword')} | {fmt(r.get('volume'))} | "
            f"{fmt(r.get('difficulty'))} | {fmt(r.get('cpc'))} |"
        )


# ---------------------------------------------------------------------------
# gap: キーワードギャップ（UC-2）・被リンクギャップ（UC-3）の決定論的計算
#
# analysis-design.md の UC-2 / UC-3 に定めた抽出条件・KD閾値・推奨アクション判定を
# ここにコードとして固定する（SKILL.md の例示コードをLLMが毎回手で再実装しないため）。
# ---------------------------------------------------------------------------

def _find_cached_dr_row(d: Path, own: str, cache_days: int, subcommand: str, glob_pattern: str) -> Path | None:
    pattern = re.compile(rf"^{re.escape(subcommand)}_.+_(\d{{8}})\.json$")
    candidates: list[tuple[date, Path]] = []
    for p in d.glob(glob_pattern):
        m = pattern.match(p.name)
        if not m:
            continue
        try:
            file_date = datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        if (date.today() - file_date).days > cache_days:
            continue
        candidates.append((file_date, p))
    candidates.sort(key=lambda t: t[0], reverse=True)
    for _, p in candidates:
        try:
            env = load_envelope(p)
        except (json.JSONDecodeError, OSError):
            continue
        for row in env.get("rows", []):
            if row.get("target") == own and row.get("domain_rating") is not None:
                return p
    return None


def find_own_dr_cache(d: Path, own: str, cache_days: int) -> Path | None:
    """cache_days 以内の overview キャッシュ、または過去の gap 実行が作った domain-rating
    単体キャッシュの中から、target==own の domain_rating を含む最新ファイルを探す（無ければ None）。
    2つの名前空間を見るのは、overview サブコマンドの完全なキャッシュファイルを domain-rating
    単体取得の保存で上書きして壊さないため（保存先を別名前空間に分けている）。"""
    overview_hit = _find_cached_dr_row(d, own, cache_days, "overview", "overview_*.json")
    if overview_hit is not None:
        return overview_hit
    return _find_cached_dr_row(d, own, cache_days, "domain-rating", "domain-rating_*.json")


def get_own_domain_rating(
    d: Path,
    own: str,
    token: str,
    refresh: bool,
    cache_days: int,
    skip_units_check: bool = False,
) -> tuple[float | None, int, Path | None]:
    """自社DRを取得する。既存 overview キャッシュがあればそこから、無ければ domain-rating を1回叩く。

    戻り値: (DR, 新規消費ユニット, 参照/生成したファイルパス)
    """
    if not refresh:
        cached_path = find_own_dr_cache(d, own, cache_days)
        if cached_path is not None:
            env = load_envelope(cached_path)
            for row in env.get("rows", []):
                if row.get("target") == own and row.get("domain_rating") is not None:
                    return row["domain_rating"], 0, cached_path

    if not skip_units_check:
        check_remaining_units(token)

    today = date.today().isoformat()
    dr_body, units = call_api("/site-explorer/domain-rating", {"target": own, "date": today}, token)
    dr = dr_body.get("domain_rating", {})
    dr_value = dr.get("domain_rating")

    # 次回以降の gap 実行が使い回せるよう保存する。ただし overview サブコマンドが作る
    # フル項目（backlinks_live 等）入りのキャッシュファイルを上書きしないよう、
    # 別の名前空間（domain-rating_*）に保存する
    slug = slugify(own)
    params = {"target": own, "date": today}
    row = {"target": own, "domain_rating": dr_value, "ahrefs_rank": dr.get("ahrefs_rank")}
    path = save_envelope(
        d, "domain-rating", slug, "/site-explorer/domain-rating (gap補完取得)", params, units, [row]
    )
    return dr_value, units, path


def kd_threshold_for_dr(dr: float | None) -> int:
    """analysis-design.md UC-2 のKD閾値表。自社DR不明時は中間値(45)にフォールバック。"""
    if dr is None:
        return 45
    if dr < 40:
        return 30
    if dr < 60:
        return 45
    return 60


def is_brand_keyword(keyword: str, brand_terms: list[str]) -> bool:
    kw_lower = keyword.lower()
    return any(term.lower() in kw_lower for term in brand_terms if term)


def build_keyword_gap(
    own_rows: list[dict],
    competitor_rows_by_domain: dict[str, list[dict]],
    min_volume: int,
    max_position: int,
    own_min_position: int,
    brand_terms: list[str],
    kd_threshold: int,
) -> tuple[list[dict], list[dict], int]:
    """UC-2 のギャップ抽出条件を固定実装。

    戻り値: (優先キーワード[KD<=閾値], 参考キーワード[KD>閾値], ブランド語除外件数)
    """
    own_kw_map: dict[str, dict] = {}
    for r in own_rows:
        kw = r.get("keyword")
        if kw is None:
            continue
        pos = r.get("best_position")
        existing = own_kw_map.get(kw)
        if existing is None or (
            pos is not None and (existing.get("best_position") is None or pos < existing["best_position"])
        ):
            own_kw_map[kw] = r

    merged: dict[str, dict] = {}
    for competitor, rows in competitor_rows_by_domain.items():
        for r in rows:
            kw = r.get("keyword")
            volume = r.get("volume")
            position = r.get("best_position")
            kd = r.get("keyword_difficulty")
            if kw is None:
                continue
            if volume is None or volume < min_volume:
                continue
            if position is None or position > max_position:
                continue

            entry = merged.setdefault(
                kw,
                {
                    "keyword": kw,
                    "volume": volume,
                    "kd": kd,
                    "best_competitor_position": position,
                    "competitors": set(),
                },
            )
            entry["competitors"].add(competitor)
            if position < entry["best_competitor_position"]:
                entry["best_competitor_position"] = position
            if volume is not None and (entry["volume"] is None or volume > entry["volume"]):
                entry["volume"] = volume
            if kd is not None:
                entry["kd"] = kd

    excluded_brand_count = 0
    priority: list[dict] = []
    kd_over: list[dict] = []

    for kw, entry in merged.items():
        if brand_terms and is_brand_keyword(kw, brand_terms):
            excluded_brand_count += 1
            continue

        own_row = own_kw_map.get(kw)
        own_position = own_row.get("best_position") if own_row else None
        if own_position is not None and own_position <= own_min_position:
            continue  # 自社が既に十分な順位を取っている -> ギャップではない

        # アクション判定は自社順位の数値で行う。best_position_url は判定には使わず、
        # リライト/内部リンク強化の「打ち手の対象ページ特定」用に結果行へ添付する
        # （自社順位が無い=新規記事の行は None）
        if own_position is None or own_position > 50:
            action = "新規記事"
        elif own_position > 20:
            action = "リライト"
        else:
            action = "内部リンク強化"

        own_url = own_row.get("best_position_url") if own_row else None

        row_out = {
            "keyword": kw,
            "volume": entry["volume"],
            "kd": entry["kd"],
            "best_competitor_position": entry["best_competitor_position"],
            "own_position": own_position,
            "own_best_position_url": own_url,
            "competitors": sorted(entry["competitors"]),
            "action": action,
        }

        kd_val = entry["kd"]
        if kd_val is not None and kd_val <= kd_threshold:
            priority.append(row_out)
        else:
            kd_over.append(row_out)

    priority.sort(key=lambda r: (r["volume"] or 0), reverse=True)
    kd_over.sort(key=lambda r: (r["volume"] or 0), reverse=True)
    return priority, kd_over, excluded_brand_count


def build_backlink_gap(
    own_rows: list[dict],
    competitor_rows_by_domain: dict[str, list[dict]],
) -> list[dict]:
    """UC-3: 競合の参照ドメイン集合 - 自社の参照ドメイン集合。
    「何社の競合からリンクされているか」降順 -> DR降順でソート。"""
    own_domains = {r.get("domain") for r in own_rows if r.get("domain")}
    merged: dict[str, dict] = {}
    for competitor, rows in competitor_rows_by_domain.items():
        for r in rows:
            domain = r.get("domain")
            if not domain or domain in own_domains:
                continue
            entry = merged.setdefault(
                domain, {"domain": domain, "domain_rating": r.get("domain_rating"), "competitors": set()}
            )
            entry["competitors"].add(competitor)
            dr = r.get("domain_rating")
            if dr is not None and (entry["domain_rating"] is None or dr > entry["domain_rating"]):
                entry["domain_rating"] = dr

    out = [
        {
            "domain": v["domain"],
            "domain_rating": v["domain_rating"],
            "linking_competitor_count": len(v["competitors"]),
            "competitors": sorted(v["competitors"]),
        }
        for v in merged.values()
    ]
    out.sort(key=lambda r: (r["linking_competitor_count"], r["domain_rating"] or 0), reverse=True)
    return out


def cmd_gap(args, token: str) -> None:
    competitors = [c.strip() for c in args.competitors.split(",") if c.strip()]
    if not competitors:
        print("エラー: --competitors が空です。", file=sys.stderr)
        sys.exit(1)
    brand_terms = [t.strip() for t in (args.exclude or "").split(",") if t.strip()]

    d = data_dir(args.client)

    # 1. 事前見積りガード。課金は「行数 × 選択列数」（2026-07-12 実測で確定）。
    #    gap は自社側(5列)・競合側(4列)・refdomains(3列)で列数が違うため個別に計算する
    #    （2026-07-14 列削減。旧: 自社/競合とも6列・refdomains4列）。
    #    キャッシュ命中や実行結果の行数が少なければ実消費は下がるが、最悪ケースで判断する。
    own_kw_cols = len(GAP_OWN_KW_SELECT.split(","))
    competitor_kw_cols = len(GAP_COMPETITOR_KW_SELECT.split(","))
    rd_cols = len(REFDOMAINS_SELECT.split(","))
    worst_case = (
        50  # 自社DR取得
        + args.own_limit * own_kw_cols
        + len(competitors) * args.limit * competitor_kw_cols
        + (len(competitors) + 1) * args.refdomains_limit * rd_cols
    )
    remaining = get_remaining_units(token)
    print(f"事前見積り（最悪ケース）: {worst_case:,} units / APIキー残り: {fmt(remaining)} units")
    if remaining is not None and worst_case > remaining - 10_000 and not args.force_units:
        print(
            f"エラー: 最悪ケース見積り {worst_case:,} units が安全マージン（残 {remaining:,} − 10,000）を超えます。\n"
            "  対処: --limit / --own-limit / --refdomains-limit を下げる、競合数を減らす、\n"
            "  またはキャッシュ済み・対象サイトの行数が少ないと確信できる場合のみ --force-units で実行してください。",
            file=sys.stderr,
        )
        sys.exit(1)
    if remaining is not None and remaining < 10_000 and not args.force_units:
        print(f"エラー: APIキーの残ユニットが {remaining:,} で閾値 10,000 を下回っています。", file=sys.stderr)
        sys.exit(1)

    total_units = 0
    source_files: list[str] = []

    # 自社DR（overview キャッシュ流用 or domain-rating 単発取得）
    own_dr, u, dr_path = get_own_domain_rating(
        d, args.own, token, args.refresh,
        resolve_cache_days(args.cache_days, CACHE_DAYS_OVERVIEW_DEFAULT),
        skip_units_check=True,
    )
    total_units += u
    if dr_path is not None:
        source_files.append(dr_path.name)

    # KD閾値（auto: 自社DRから自動選定 / 数値指定: そのまま使用）
    if args.kd_max == "auto":
        kd_threshold = kd_threshold_for_dr(own_dr)
    else:
        kd_threshold = int(args.kd_max)

    # 自社 organic-keywords（自社の順位を広く知るため max-position=100・自社側は best_position 条件なし。
    # ただし volume は競合側と同じ --min-volume を適用する。ギャップ判定の照合対象は競合側で
    # volume>=min_volume に絞った候補語だけなので、自社の低ボリューム語を取得しても判定には使われず、
    # 判定品質を落とさずに行数=課金を削減できる。2026-07-14 導入）
    own_kw_rows, u, own_kw_path, _ = fetch_organic_keywords(
        d, args.own, args.country, args.min_volume, 100, args.own_limit, token, args.refresh,
        resolve_cache_days(args.cache_days, CACHE_DAYS_ORGANIC_KW_DEFAULT),
        skip_units_check=True, select=GAP_OWN_KW_SELECT,
    )
    total_units += u
    source_files.append(own_kw_path.name)

    # 競合各社 organic-keywords（min-volume・max-position=10）
    competitor_kw_rows: dict[str, list[dict]] = {}
    for comp in competitors:
        rows, u, path, _ = fetch_organic_keywords(
            d, comp, args.country, args.min_volume, args.max_position, args.limit, token,
            args.refresh, resolve_cache_days(args.cache_days, CACHE_DAYS_ORGANIC_KW_DEFAULT),
            skip_units_check=True, select=GAP_COMPETITOR_KW_SELECT,
        )
        total_units += u
        source_files.append(path.name)
        competitor_kw_rows[comp] = rows

    # 自社 refdomains
    own_rd_rows, u, own_rd_path, _ = fetch_refdomains(
        d, args.own, args.min_dr, args.refdomains_limit, token, args.refresh,
        resolve_cache_days(args.cache_days, CACHE_DAYS_REFDOMAINS_DEFAULT),
        skip_units_check=True,
    )
    total_units += u
    source_files.append(own_rd_path.name)

    # 競合各社 refdomains
    competitor_rd_rows: dict[str, list[dict]] = {}
    for comp in competitors:
        rows, u, path, _ = fetch_refdomains(
            d, comp, args.min_dr, args.refdomains_limit, token, args.refresh,
            resolve_cache_days(args.cache_days, CACHE_DAYS_REFDOMAINS_DEFAULT),
            skip_units_check=True,
        )
        total_units += u
        source_files.append(path.name)
        competitor_rd_rows[comp] = rows

    # ギャップ計算（決定論的。ここが analysis-design.md UC-2/UC-3 の固定実装）
    keyword_gap, keyword_gap_kd_over, excluded_brand_count = build_keyword_gap(
        own_kw_rows,
        competitor_kw_rows,
        args.min_volume,
        args.max_position,
        args.own_min_position,
        brand_terms,
        kd_threshold,
    )
    backlink_gap = build_backlink_gap(own_rd_rows, competitor_rd_rows)

    # 保存
    slug = f"{slugify(args.own)}_vs_{multi_slug(competitors)}"
    params = {
        "client": args.client,
        "own": args.own,
        "competitors": competitors,
        "country": args.country,
        "min_volume": args.min_volume,
        "max_position": args.max_position,
        "own_min_position": args.own_min_position,
        "kd_max": args.kd_max,
        "kd_threshold": kd_threshold,
        "exclude": brand_terms,
        "limit": args.limit,
        "own_limit": args.own_limit,
        "min_dr": args.min_dr,
        "refdomains_limit": args.refdomains_limit,
    }
    envelope = {
        "fetched_at": datetime.now().astimezone().isoformat(),
        "params": params,
        "own_dr": own_dr,
        "kd_threshold": kd_threshold,
        "units_consumed": total_units,
        "keyword_gap": keyword_gap,
        "keyword_gap_kd_over": keyword_gap_kd_over,
        "backlink_gap": backlink_gap,
        "excluded_brand_count": excluded_brand_count,
        "source_files": sorted(set(source_files)),
    }
    today_str = date.today().strftime("%Y%m%d")
    path = d / f"gap_{slug}_{today_str}.json"
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"保存: {path}")
    print("\n=== ギャップ分析サマリ ===")
    print(f"自社DR: {fmt(own_dr)} / KD閾値: {kd_threshold}以下を優先（kd-max={args.kd_max}）")
    print(f"キーワードギャップ: 優先 {len(keyword_gap)} 件 / 参考(KD高) {len(keyword_gap_kd_over)} 件")
    print(f"ブランド語除外: {excluded_brand_count} 件")
    print(f"被リンクギャップ: {len(backlink_gap)} 件")

    print_keyword_gap_table(keyword_gap)
    print_backlink_gap_table(backlink_gap)

    print(f"\n消費ユニット: {total_units}")


def print_keyword_gap_table(rows: list[dict]) -> None:
    print("\n=== 優先キーワード（volume降順、上位20件） ===")
    print(f"行数: {len(rows)}")
    print("| キーワード | Volume | KD | 競合最良順位 | 自社順位 | 自社URL | 取得競合 | 推奨アクション |")
    print("|---|---:|---:|---:|---:|---|---|---|")
    for r in rows[:20]:
        print(
            f"| {r['keyword']} | {fmt(r['volume'])} | {fmt(r['kd'])} | "
            f"{fmt(r['best_competitor_position'])} | {fmt(r['own_position'])} | "
            f"{r.get('own_best_position_url') or ''} | "
            f"{', '.join(r['competitors'])} | {r['action']} |"
        )
    if len(rows) > 20:
        print(f"...他 {len(rows) - 20} 件（保存ファイル参照）")


def print_backlink_gap_table(rows: list[dict]) -> None:
    print("\n=== 被リンクギャップ（上位20件） ===")
    print(f"行数: {len(rows)}")
    print("| ドメイン | DR | リンクしている競合数 | 競合 |")
    print("|---|---:|---:|---|")
    for r in rows[:20]:
        print(
            f"| {r['domain']} | {fmt(r['domain_rating'])} | "
            f"{r['linking_competitor_count']} | {', '.join(r['competitors'])} |"
        )
    if len(rows) > 20:
        print(f"...他 {len(rows) - 20} 件（保存ファイル参照）")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    def add_common(p: argparse.ArgumentParser, client_required: bool = True):
        p.add_argument("--client", required=client_required, help="クライアントID（outputs/{client}/ 配下に保存）")
        p.add_argument("--country", default="jp", help="国コード（既定 jp）")
        p.add_argument("--refresh", action="store_true", help="キャッシュを無視して再取得")
        p.add_argument(
            "--cache-days", type=int, default=None,
            help=(
                "キャッシュ有効日数。未指定ならエンドポイント別既定値を使う"
                "（overview/refdomains=30日, organic-keywords=14日, serp=7日, kw-overview=7日）。"
                "指定した場合はそのサブコマンドが触る全エンドポイントに一律優先適用される"
            ),
        )

    p_limits = sub.add_parser("limits", help="残ユニット確認（--client 不要）")
    p_limits.set_defaults(func=cmd_limits)

    p_overview = sub.add_parser("overview", help="複数ドメインのDR・被リンク・オーガニックKW数を横並び取得")
    add_common(p_overview)
    p_overview.add_argument("--targets", required=True, help="対象ドメイン（カンマ区切り）例: a.com,b.com,c.com")
    p_overview.set_defaults(func=cmd_overview)

    p_kw = sub.add_parser("organic-keywords", help="単一ドメインのオーガニックキーワードを取得")
    add_common(p_kw)
    p_kw.add_argument("--target", required=True, help="対象ドメイン")
    p_kw.add_argument("--min-volume", type=int, default=100, help="最小検索ボリューム（既定 100）")
    p_kw.add_argument("--max-position", type=int, default=10, help="最大順位（既定 10）")
    p_kw.add_argument("--limit", type=int, default=1000, help="最大行数（既定 1000）")
    p_kw.add_argument(
        "--select", default=ORGANIC_KW_SELECT,
        help=(
            "取得列（カンマ区切り）。既定はフル6列。課金は行数×列数のため、"
            "sum_traffic/best_position_url が不要なら絞ると消費を減らせる"
            f"（既定: {ORGANIC_KW_SELECT}）"
        ),
    )
    p_kw.set_defaults(func=cmd_organic_keywords)

    p_rd = sub.add_parser("refdomains", help="単一ドメインの参照ドメインを取得")
    add_common(p_rd)
    p_rd.add_argument("--target", required=True, help="対象ドメイン")
    p_rd.add_argument("--min-dr", type=int, default=50, help="最小DR（既定 50）")
    p_rd.add_argument("--limit", type=int, default=500, help="最大行数（既定 500）")
    p_rd.set_defaults(func=cmd_refdomains)

    p_serp = sub.add_parser("serp", help="キーワードのSERP上位10件を取得")
    add_common(p_serp)
    p_serp.add_argument("--keyword", required=True, help="検索キーワード")
    p_serp.set_defaults(func=cmd_serp)

    p_kwo = sub.add_parser("kw-overview", help="複数キーワードのvolume/KD/CPCを取得")
    add_common(p_kwo)
    p_kwo.add_argument("--keywords", required=True, help="キーワード（カンマ区切り）例: kw1,kw2,kw3")
    p_kwo.set_defaults(func=cmd_kw_overview)

    p_gap = sub.add_parser(
        "gap", help="キーワードギャップ（UC-2）・被リンクギャップ（UC-3）を決定論的に計算"
    )
    add_common(p_gap)
    p_gap.add_argument("--own", required=True, help="自社ドメイン")
    p_gap.add_argument("--competitors", required=True, help="競合ドメイン（カンマ区切り）例: a.com,b.com,c.com")
    p_gap.add_argument(
        "--min-volume", type=int, default=100,
        help=(
            "最小検索ボリューム（既定 100）。競合側の抽出条件であると同時に、"
            "2026-07-14〜 自社側 organic-keywords 取得の絞り込みにも使う"
            "（ギャップ判定は volume>=この値の候補語だけを見るため、自社の低volume語を取得しても"
            "判定には使われず、行数=課金だけ削減できる）"
        ),
    )
    p_gap.add_argument("--max-position", type=int, default=10, help="競合側の最大順位（既定 10）")
    p_gap.add_argument(
        "--own-min-position",
        type=int,
        default=20,
        help="自社がこの順位より下 or 未取得ならギャップ扱い（既定 20）",
    )
    p_gap.add_argument(
        "--kd-max",
        default="auto",
        help="優先/参考を分けるKD閾値。'auto'（既定）で自社DRから自動選定。数値も指定可",
    )
    p_gap.add_argument(
        "--exclude", default="", help="ブランド語（カンマ区切り）。含むキーワードはギャップから除外"
    )
    p_gap.add_argument("--limit", type=int, default=1000, help="競合 organic-keywords の最大行数（既定 1000）")
    p_gap.add_argument(
        "--own-limit", type=int, default=2000,
        help="自社 organic-keywords の最大行数（既定 2000。課金は行×列のため大きくしすぎない）",
    )
    p_gap.add_argument("--min-dr", type=int, default=50, help="refdomains の最小DR（既定 50）")
    p_gap.add_argument(
        "--refdomains-limit", type=int, default=500, help="refdomains の最大行数（既定 500）"
    )
    p_gap.add_argument(
        "--force-units", action="store_true",
        help="事前見積りガードを無視して実行（キャッシュ済み・行数が少ないと確信できる場合のみ）",
    )
    p_gap.set_defaults(func=cmd_gap)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    token = resolve_token()

    try:
        args.func(args, token)
    except AhrefsAPIError as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
