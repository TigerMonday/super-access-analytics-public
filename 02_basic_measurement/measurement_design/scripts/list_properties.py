"""アカウント配下の GA4 プロパティを棚卸しする（読み取りのみ）。

**着手時に「どのプロパティを見るのか」を決めるための道具。** 1クライアントに
プロパティが1本しか無い案件では要らないが、**同じサイトを複数のプロパティで
計測している案件では、これを先に走らせないと診断対象を間違える。**

実際の案件でアカウント内に十数本のプロパティが並ぶことがあり、内訳は
「全エリア1本 ＋ ロールアップ2本 ＋ 県別7本 ＋ 別サイト2本 ＋ 未使用7本」だった。
**プロパティ名だけでは役割が分からない**（「16リニューアル版」が実は0セッション、
主要CVが入っているのは1本だけ）。名前ではなく次の3つで判断する。

  1. **セッションと実績があるか**（直近28日 / 直近7日）
  2. **キーイベントが実際に発火しているか**（登録されているだけの箱が多い）
  3. **どのホスト名から送られているか**（別サイト・検証環境の混入が出る）

あわせて実機での送信先確認（ブラウザの通信を見て測定IDを拾う）も行う。
GTM に載っていない第三者のタグは、この一覧には出てこない。

使い方:

    cd 02_basic_measurement/measurement_design
    uv run python scripts/list_properties.py                          # 見えているアカウント一覧
    uv run python scripts/list_properties.py --account 123456789      # 配下のプロパティを棚卸し
    uv run python scripts/list_properties.py --account 123456789 --json out.json

コンソールは Windows の cp932 で日本語が化けるため、既定で UTF-8 に固定している。
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from google.analytics.admin_v1alpha import AnalyticsAdminServiceClient as AlphaClient
from google.analytics.admin_v1beta import AnalyticsAdminServiceClient as BetaClient
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    OrderBy,
    RunReportRequest,
)
from google.protobuf.json_format import MessageToDict

from auth import get_credentials


# **読み取りしかしないので、読み取り専用のスコープだけを要求する。**
# 既定の SCOPES には `analytics.edit` と `tagmanager.readonly` が入っており、
# 棚卸しのために書き込み権限の同意を求めることになる（読み取りだけ許可された
# 環境では失敗する）。
READONLY_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]


@dataclass
class _AuthOnlyConfig:
    """`auth.get_credentials` が読むのはこの3つだけ。

    `AuditConfig` を使うと `__post_init__` が案件フォルダを解決してしまう。
    棚卸しの時点では案件フォルダがまだ無い（どのプロパティで作るかを決める前）ため、
    認証に必要な項目だけを持つ器を使う。
    """

    auth_method: str = "sa"
    oauth_profile: str = ""
    sa_key_path: str = ""


def _to_dict(proto_msg) -> dict:
    return MessageToDict(type(proto_msg).pb(proto_msg), preserving_proto_field_name=True)


def _metrics(data_client, property_id: str, start: str, end: str) -> dict:
    """期間合計。取得できない場合も落とさず理由を返す（権限が一部だけ無い場合がある）。"""
    try:
        r = data_client.run_report(
            RunReportRequest(
                property=f"properties/{property_id}",
                date_ranges=[DateRange(start_date=start, end_date=end)],
                metrics=[
                    Metric(name="sessions"),
                    Metric(name="totalUsers"),
                    Metric(name="eventCount"),
                    Metric(name="keyEvents"),
                ],
            )
        )
    except Exception as e:  # noqa: BLE001 — API 側の例外は種類が多く、理由を残して続行する
        return {"error": str(e)[:200]}
    if not r.rows:
        return {"sessions": "0", "total_users": "0", "event_count": "0", "key_events": "0"}
    v = [x.value for x in r.rows[0].metric_values]
    return {"sessions": v[0], "total_users": v[1], "event_count": v[2], "key_events": v[3]}


def _hosts(data_client, property_id: str, limit: int = 10) -> dict:
    """ホスト名の内訳（セッション降順）。

    **`limit` を付けるなら並び順も指定する。** 指定しないと API が返す順は保証されず、
    ホスト名が10件を超えるプロパティで**本番のホストが一覧から落ちる**ことがある。
    このスクリプトはホスト名で「どのサイトを計測しているプロパティか」を見分けるので、
    落ちると診断対象を取り違える。
    """
    try:
        r = data_client.run_report(
            RunReportRequest(
                property=f"properties/{property_id}",
                date_ranges=[DateRange(start_date="28daysAgo", end_date="yesterday")],
                dimensions=[Dimension(name="hostName")],
                metrics=[Metric(name="sessions")],
                order_bys=[
                    OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)
                ],
                limit=limit,
            )
        )
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}
    return {
        "rows": [
            (row.dimension_values[0].value, row.metric_values[0].value) for row in r.rows
        ]
    }


def list_accounts(config) -> list[dict]:
    # auth.get_credentials の引数は extra_scopes。READONLY_SCOPES は SCOPES に
    # 含まれるので、追加は要らずそのまま呼ぶ（誤った引数名で常に落ちていた）。
    client = BetaClient(credentials=get_credentials(config))
    return [_to_dict(s) for s in client.list_account_summaries()]


def inventory(config, account_id: str, with_hosts: bool = True) -> dict:
    """アカウント配下の全プロパティに、設定・実績・ホスト名を付けて返す。"""
    creds = get_credentials(config)
    admin = BetaClient(credentials=creds)
    alpha = AlphaClient(credentials=creds)
    data = BetaAnalyticsDataClient(credentials=creds)

    summaries = [_to_dict(s) for s in admin.list_account_summaries()]
    target = next((s for s in summaries if s.get("account") == f"accounts/{account_id}"), None)
    if target is None:
        visible = ", ".join(s.get("account", "") for s in summaries)
        raise SystemExit(
            f"アカウント {account_id} が見えません。権限付与を確認してください。"
            f"（見えているアカウント: {visible or 'なし'}）"
        )

    out = {
        "account": target.get("account"),
        "account_name": target.get("display_name"),
        "properties": [],
    }
    for ps in target.get("property_summaries", []) or []:
        pid = ps["property"].split("/")[-1]
        rec: dict = {
            "property_id": pid,
            "display_name": ps.get("display_name"),
            "property_type": ps.get("property_type"),
        }
        try:
            rec["detail"] = _to_dict(admin.get_property(name=f"properties/{pid}"))
        except Exception as e:  # noqa: BLE001
            rec["detail_error"] = str(e)[:200]
        try:
            rec["streams"] = [
                _to_dict(s) for s in admin.list_data_streams(parent=f"properties/{pid}")
            ]
        except Exception as e:  # noqa: BLE001
            rec["streams_error"] = str(e)[:200]
        try:
            rec["key_events"] = [
                _to_dict(k) for k in alpha.list_key_events(parent=f"properties/{pid}")
            ]
        except Exception as e:  # noqa: BLE001
            rec["key_events_error"] = str(e)[:200]
        rec["d28"] = _metrics(data, pid, "28daysAgo", "yesterday")
        rec["d7"] = _metrics(data, pid, "7daysAgo", "yesterday")
        if with_hosts:
            rec["hosts"] = _hosts(data, pid)
        out["properties"].append(rec)
    return out


def render(result: dict) -> str:
    """セッションの多い順に並べた人間可読の一覧。0セッションのものは末尾にまとまる。"""
    lines = [f"# {result['account_name']}（{result['account']}）"]
    lines.append(f"プロパティ {len(result['properties'])} 本\n")

    def sessions(rec: dict) -> int:
        v = rec.get("d28", {}).get("sessions", "0")
        return int(v) if str(v).isdigit() else 0

    for rec in sorted(result["properties"], key=lambda r: -sessions(r)):
        det = rec.get("detail", {})
        lines.append(f"## {rec['property_id']}  {rec['display_name']}")
        if "detail_error" in rec:
            lines.append(f"- 設定: 取得できず（{rec['detail_error']}）")
        else:
            lines.append(
                f"- 作成: {det.get('create_time', '')[:10]}"
                f" / 業種: {det.get('industry_category') or '—'}"
                f" / TZ: {det.get('time_zone') or '—'} / 通貨: {det.get('currency_code') or '—'}"
            )
        if "streams_error" in rec:
            lines.append(f"- ストリーム: 取得できず（{rec['streams_error']}）")
        else:
            streams = []
            for st in rec.get("streams", []) or []:
                w = st.get("web_stream_data") or {}
                streams.append(f"{w.get('default_uri', '—')}（{w.get('measurement_id', '—')}）")
            lines.append("- ストリーム: " + (", ".join(streams) or "なし"))
        for label, key in (("直近28日", "d28"), ("直近7日", "d7")):
            m = rec.get(key, {})
            if "error" in m:
                lines.append(f"- {label}: 取得できず（{m['error']}）")
            else:
                lines.append(
                    f"- {label}: セッション {m.get('sessions')} / ユーザー {m.get('total_users')}"
                    f" / イベント {m.get('event_count')} / キーイベント {m.get('key_events')}"
                )
        hosts = rec.get("hosts")
        if isinstance(hosts, dict):
            if "error" in hosts:
                lines.append(f"- ホスト名(28日): 取得できず（{hosts['error']}）")
            elif hosts.get("rows"):
                lines.append(
                    "- ホスト名(28日): "
                    + ", ".join(f"{h}={v}" for h, v in hosts["rows"])
                )
        # **取得に失敗したものを「なし」と描かない。** 0件と読めてしまうと、
        # キーイベントが在るプロパティを「空だから対象外」と切ってしまう。
        if "key_events_error" in rec:
            lines.append(f"- キーイベント: 取得できず（{rec['key_events_error']}）")
        else:
            ke = [k.get("event_name") for k in rec.get("key_events", []) or []]
            lines.append(f"- キーイベント({len(ke)}): " + (", ".join(ke) or "なし"))
        lines.append("")
    return "\n".join(lines)


def render_account_summaries(summaries: list[dict]) -> str:
    """追加のデータ取得なしで、見えているアカウントとプロパティ候補を表示する。"""
    lines = ["見えているGA4アカウントとプロパティ:"]
    if not summaries:
        lines.append("  ありません")
        return "\n".join(lines)
    for summary in summaries:
        lines.append(f"- {summary.get('account', '')}  {summary.get('display_name', '')}")
        properties = summary.get("property_summaries", []) or []
        if not properties:
            lines.append("    プロパティなし")
            continue
        for prop in properties:
            lines.append(f"    {prop.get('property', '')}  {prop.get('display_name', '')}")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="GA4 アカウント配下のプロパティを棚卸しする")
    p.add_argument("--account", default="", help="GA4 アカウントID（省略時はアカウント一覧のみ）")
    p.add_argument("--auth", default="sa", choices=["sa", "adc", "oauth"])
    p.add_argument("--oauth-profile", default="")
    p.add_argument("--sa-key-path", default="")
    p.add_argument("--json", default="", help="生の取得結果を JSON で書き出す先")
    p.add_argument("--no-hosts", action="store_true", help="ホスト名の取得を省く（本数が多いとき）")
    args = p.parse_args()

    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    config = _AuthOnlyConfig(
        auth_method=args.auth, oauth_profile=args.oauth_profile, sa_key_path=args.sa_key_path
    )

    if not args.account:
        print(render_account_summaries(list_accounts(config)))
        print("\n棚卸しするには --account <アカウントID> を付ける。")
        return 0

    result = inventory(config, args.account, with_hosts=not args.no_hosts)
    print(render(result))
    if args.json:
        Path(args.json).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"JSON を書き出しました → {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
