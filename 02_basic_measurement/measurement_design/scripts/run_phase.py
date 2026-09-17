"""GA4 設定確認パック — Phase 実行エントリーポイント

各 Phase を個別に実行し、結果を JSON ファイルに保存する。
Claude Code から呼び出して使う想定。

Usage:
    cd 02_basic_measurement/measurement_design/scripts
    python run_phase.py --property-id 123456789 --client サンプル株式会社 phase1  # leak-ok: ダミー会社名の統一表記（実在の社名ではない）
    python run_phase.py --property-id 123456789 --client サンプル株式会社 phase2  # leak-ok: ダミー会社名の統一表記（実在の社名ではない）
    python run_phase.py --property-id 123456789 --client サンプル株式会社 --gtm-account 123 --gtm-container 456 phase3  # leak-ok: ダミー会社名の統一表記（実在の社名ではない）
    python run_phase.py --property-id 123456789 --client サンプル株式会社 phase5  # leak-ok: ダミー会社名の統一表記（実在の社名ではない）
    python run_phase.py --property-id 123456789 --client サンプル株式会社 phase8  # leak-ok: ダミー会社名の統一表記（実在の社名ではない）
    python run_phase.py --property-id 123456789 --client サンプル株式会社 preflight  # leak-ok: ダミー会社名の統一表記（実在の社名ではない）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from config import AuditConfig


def save_result(config: AuditConfig, phase: str, data: dict):
    """結果を JSON ファイルに _data/ に保存"""
    # **保存前に個人情報を伏せる。** `_data/` はコミットする前提なので、
    # 取得した実データ（特に phase2 のカスタムディメンション実測値）に
    # end user のメールアドレス等が載っていると、そのままリポジトリや
    # 手元に残る。dataset.split_and_save と同じく、書き出しの一箇所で通す。
    import pii
    data, redacted = pii.redact_obj(data)
    if redacted:
        print(f"  個人情報らしい値を {redacted} 件伏せました（{pii.MASK}）")

    out_file = config.data_dir / f"{phase}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved: {out_file}")


def run_preflight(config: AuditConfig):
    """プリフライトチェック — Admin APIとData APIの接続確認"""
    from auth import test_connection, test_data_connection

    result = test_connection(config)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # 対象プロパティが見えるか確認
    found = False
    for account in result["accounts"]:
        for prop in account["properties"]:
            if prop["property"] == f"properties/{config.property_id}":
                print(f"\n[OK] 対象プロパティ発見: {prop['display_name']} ({prop['property']})")
                found = True
    if not found:
        print(f"\n[NG] プロパティ {config.property_id} が見つかりません。権限を確認してください。")
        return 1

    try:
        test_data_connection(config)
    except Exception as exc:  # Google APIの例外型が複数あるため、理由を表示して失敗にする
        print(f"\n[NG] Google Analytics Data APIへ接続できません: {exc}")
        print("Data APIが有効か、対象プロパティの閲覧権限があるか確認してください。")
        return 1
    print("[OK] Google Analytics Data APIへ接続できました（実データは取得していません）")
    return 0


def run_phase1(config: AuditConfig):
    """Phase 1: プロパティ設定の取得"""
    import ga4_admin as admin

    data = {}

    print("Getting property details...")
    data["property"] = admin.get_property_details(config)

    print("Listing data streams...")
    data["data_streams"] = admin.list_data_streams(config)

    # ストリームIDを取得して拡張計測・イベント作成ルールを取得
    for stream in data["data_streams"]:
        stream_name = stream.get("name", "")
        stream_id = stream_name.split("/")[-1] if "/" in stream_name else ""
        if stream_id and stream.get("web_stream_data"):
            print(f"Getting enhanced measurement for stream {stream_id}...")
            try:
                data[f"enhanced_measurement_{stream_id}"] = admin.get_enhanced_measurement_settings(config, stream_id)
            except Exception as e:
                data[f"enhanced_measurement_{stream_id}"] = {"error": str(e)}

            # GA4「イベントの作成」ルール（page_view起点でview_*/complete_*やCV用イベントを生成する定義）。
            # GTMにもサイトgtagにも出てこないため、ここを取得しないとカスタムイベントの定義元やCV水増しを見落とす。
            print(f"Listing event create rules for stream {stream_id}...")
            try:
                data[f"event_create_rules_{stream_id}"] = admin.list_event_create_rules(config, stream_id)
            except Exception as e:
                data[f"event_create_rules_{stream_id}"] = {"error": str(e)}

    print("Getting data retention settings...")
    data["data_retention"] = admin.get_data_retention_settings(config)

    print("Getting Google Signals settings...")
    try:
        data["google_signals"] = admin.get_google_signals_settings(config)
    except Exception as e:
        data["google_signals"] = {"error": str(e)}

    print("Getting user-provided data settings...")
    try:
        data["user_provided_data"] = admin.get_user_provided_data_settings(config)
    except Exception as e:
        data["user_provided_data"] = {"error": str(e)}

    print("Getting reporting identity settings...")
    try:
        data["reporting_identity"] = admin.get_reporting_identity_settings(config)
    except Exception as e:
        data["reporting_identity"] = {"error": str(e)}

    print("Getting attribution settings...")
    try:
        data["attribution"] = admin.get_attribution_settings(config)
    except Exception as e:
        data["attribution"] = {"error": str(e)}

    print("Listing Google Ads links...")
    data["ads_links"] = admin.list_google_ads_links(config)

    # BigQuery 連携。BQ の閲覧権限が無くてもこの設定は GA4 の権限だけで読める。
    # excluded_events は「クライアントが使えないと判断済みのイベント」の一覧として読める。
    print("Listing BigQuery links...")
    try:
        data["bigquery_links"] = admin.list_big_query_links(config)
    except Exception as e:
        data["bigquery_links"] = {"error": str(e)}

    print("Listing custom dimensions...")
    data["custom_dimensions"] = admin.list_custom_dimensions(config)

    print("Listing custom metrics...")
    data["custom_metrics"] = admin.list_custom_metrics(config)

    print("Listing key events...")
    data["key_events"] = admin.list_key_events(config)

    print("Listing audiences...")
    try:
        data["audiences"] = admin.list_audiences(config)
    except Exception as e:
        data["audiences"] = {"error": str(e)}

    save_result(config, "phase1", data)
    print(f"\nPhase 1 完了: {len(data)} セクション取得")


def run_phase2(config: AuditConfig):
    """Phase 2: イベント・ディメンション分析"""
    import ga4_data as data_api

    data = {}

    print("Getting event list (30 days)...")
    data["events_30d"] = data_api.get_event_list(config, days=30)

    # ディメンション無しの総計。イベント数との比を見るために使う。
    # 例: session_start ÷ セッション数 が 1 を大きく下回るなら、基盤タグが
    # 初期化時に発火していない（health_checks.check_session_health）。
    # ディメンションで分割した値の合計は総計と一致しないため、必ず別途取得する。
    print("Getting period totals (no dimensions)...")
    totals_rows = data_api.run_report(
        config,
        dimensions=[],
        metrics=["sessions", "totalUsers", "screenPageViews", "eventCount"],
        start_date="30daysAgo",
    )
    data["totals"] = totals_rows[0] if totals_rows else {}

    # イベント名の異なり数。`events_30d` は上位100件に絞っているため、
    # その行数からは上限（500）への接近を判定できない。名前だけを上限なしで数える。
    print("Counting distinct event names...")
    name_rows = data_api.run_report(
        config,
        dimensions=["eventName"],
        metrics=["eventCount"],
        start_date="30daysAgo",
        limit=0,  # 0 = 上限なし
    )
    # 確認済みCVの受信件数は上位100件の events_30d だけでは判定しない。
    # 低頻度の成果イベントが101位以下にあると「0件」と誤判定するため、
    # 全イベント名と件数を保存し、レビュー側ではこの一覧を正本にする。
    data["event_name_counts_30d"] = name_rows
    data["event_name_counts_status"] = "complete"
    data["event_name_total"] = {
        "distinct_event_names": len({r.get("eventName", "") for r in name_rows if r.get("eventName")}),
        "limit": 500,
    }

    print("Getting custom dimension values...")
    # Phase 1 の結果からカスタムディメンションを読み込む
    phase1_file = config.data_dir / "phase1.json"
    if phase1_file.exists():
        with open(phase1_file, encoding="utf-8") as f:
            phase1 = json.load(f)

        custom_dims = phase1.get("custom_dimensions", [])
        dim_values = {}

        for dim in custom_dims:
            param_name = dim.get("parameter_name", "")
            scope = dim.get("scope", "EVENT")
            api_name = f"customEvent:{param_name}" if scope == "EVENT" else f"customUser:{param_name}"

            print(f"  Checking dimension: {param_name} ({scope})...")
            try:
                values = data_api.run_report(
                    config,
                    dimensions=["eventName", api_name],
                    metrics=["eventCount"],
                    start_date="90daysAgo",
                    dimension_filter=data_api.filter_not(
                        data_api.filter_exact(api_name, "(not set)")
                    ),
                    order_by_metric="eventCount",
                    limit=20,
                )
                dim_values[param_name] = {
                    "scope": scope,
                    "has_data": len(values) > 0,
                    "sample_values": values[:10],
                }
            except Exception as e:
                dim_values[param_name] = {"scope": scope, "error": str(e)}

        data["dimension_values"] = dim_values
    else:
        print("  Warning: Phase 1 data not found. Run phase1 first.")

    print("Getting key event firing status...")
    data["key_event_firing"] = data_api.run_report(
        config,
        dimensions=["eventName"],
        metrics=["eventCount"],
        start_date="30daysAgo",
        dimension_filter=data_api.filter_exact("isKeyEvent", "true"),
        order_by_metric="eventCount",
    )

    print("Getting channel performance...")
    data["channel_performance"] = data_api.run_report(
        config,
        dimensions=["sessionDefaultChannelGroup"],
        metrics=["sessions", "totalUsers", "keyEvents", "bounceRate", "averageSessionDuration"],
        start_date="30daysAgo",
        order_by_metric="sessions",
    )

    save_result(config, "phase2", data)
    print(f"\nPhase 2 完了")


def run_pages(config: AuditConfig):
    """ページ別の実績を取得する（コンテンツグルーピング用）。

    コンテンツグループ設計には「どの URL 群にどれだけ PV があるか」が要る。
    URL が増殖している場合（予約システム等）の把握にも使う。

    `pageTitle` は SPA 計測ギャップ検出（health_checks.check_spa_tracking_gap）用に
    追加した。既存のページレポート（`pagePath` 1本）にディメンションを1つ足すだけで、
    APIリクエストの本数は増えない（1回のレポート呼び出しのまま）。
    """
    import ga4_data as data_api
    import dataset

    print("Getting page report (30 days)...")
    rows = data_api.run_report(
        config,
        dimensions=["pagePath", "pageTitle"],
        metrics=["screenPageViews", "sessions", "keyEvents"],
        order_by_metric="screenPageViews",
        limit=100000,
    )
    print("Getting content group report...")
    groups = data_api.run_report(
        config, dimensions=["contentGroup"], metrics=["screenPageViews"], limit=1000
    )
    data = {"pages": rows, "content_groups": groups}
    for out in dataset.split_and_save(config.data_dir, "pages.json", data):
        print(f"Saved: {out}")
    print(f"\nページ取得完了: {len(rows)} URL")


def run_traffic_detail(config: AuditConfig):
    """流入パラメータ（UTM）用: source × medium 別・campaign 別を取得する。

    phase2 が取るチャネル別（`channel_performance`）だけでは、Unassigned の中身・
    medium の実値・campaign の付与状況が分からない。独自 medium（代理店名など）が
    入っていると GA4 の既定チャネルに分類されず、広告の成果が自然流入として計上される。

    source/medium にチャネルグループを併せて取るのは、どの組み合わせが Unassigned に
    落ちているかを内訳として出せるようにするため。
    """
    import ga4_data as data_api
    import dataset

    print("Getting source x medium report (30 days)...")
    source_medium = data_api.run_report(
        config,
        dimensions=["sessionSource", "sessionMedium", "sessionDefaultChannelGroup"],
        metrics=["sessions", "keyEvents"],
        order_by_metric="sessions",
        limit=5000,
    )
    print("Getting campaign report (30 days)...")
    campaigns = data_api.run_report(
        config,
        dimensions=["sessionCampaignName", "sessionSource", "sessionMedium"],
        metrics=["sessions", "keyEvents"],
        order_by_metric="sessions",
        limit=1000,
    )
    data = {"source_medium": source_medium, "campaigns": campaigns}
    for out in dataset.split_and_save(config.data_dir, "traffic.json", data):
        print(f"Saved: {out}")
    print(
        f"\n流入パラメータ取得完了: "
        f"source/medium {len(source_medium)} 組 / campaign {len(campaigns)} 件"
    )


def run_data_quality(config: AuditConfig):
    """データ品質用: ホスト名別・国別の実績を取得する。

    本番以外のドメインが計測されていないか、ボットと見られる流入がないかを
    定点で見るための素材。PV・滞在などの品質確認用データを併せて取る。
    """
    import ga4_data as data_api
    import dataset

    print("Getting hostname report (30 days)...")
    hosts = data_api.run_report(
        config,
        dimensions=["hostName"],
        metrics=["sessions", "screenPageViews", "keyEvents"],
        order_by_metric="sessions",
        limit=1000,
    )
    print("Getting country report (30 days)...")
    countries = data_api.run_report(
        config,
        dimensions=["country"],
        metrics=["sessions", "screenPageViews", "userEngagementDuration", "bounceRate", "keyEvents"],
        order_by_metric="sessions",
        limit=1000,
    )
    print("Getting browser x OS report (30 days)...")
    env = data_api.run_report(
        config,
        dimensions=["country", "browser", "operatingSystem"],
        metrics=["sessions"],
        order_by_metric="sessions",
        limit=5000,
    )
    data = {"hosts": hosts, "countries": countries, "country_environment": env}
    for out in dataset.split_and_save(config.data_dir, "data-quality.json", data):
        print(f"Saved: {out}")
    print(f"\nデータ品質取得完了: ホスト {len(hosts)} / 国 {len(countries)}")


def run_phase3(config: AuditConfig):
    """Phase 3: GTM コンテナ監査"""
    import gtm as gtm_api

    if not config.gtm_account_id or not config.gtm_container_id:
        print("GTM account/container ID が指定されていません。--gtm-account と --gtm-container を指定してください。")
        sys.exit(1)

    data = {}

    try:
        resolved_container_id = gtm_api.resolve_container_id(config)
    except ValueError as exc:
        print(str(exc))
        sys.exit(1)
    if resolved_container_id != config.gtm_container_id:
        print(f"GTM公開ID {config.gtm_container_id} をAPI用コンテナIDへ解決しました。")
        config.gtm_container_id = resolved_container_id

    print("Getting all from live version...")
    version_data = gtm_api.get_all_from_version(config)
    data["live_version"] = {
        "version_id": version_data["version_id"],
        "name": version_data["name"],
        "description": version_data["description"],
    }
    data["tags"] = version_data["tags"]
    data["triggers"] = version_data["triggers"]
    data["variables"] = version_data["variables"]
    data["built_in_variables"] = version_data["builtInVariables"]

    # 分析
    print("\nAnalyzing tags...")
    data["tag_analysis"] = []
    for tag in data["tags"]:
        analysis = {
            "name": tag.get("name", ""),
            "type": tag.get("type", ""),
            "type_label": gtm_api.classify_tag_type(tag),
            "firing_trigger_ids": tag.get("firingTriggerId", []),
        }
        ga4_info = gtm_api.extract_ga4_event_info(tag)
        if ga4_info:
            analysis["ga4_event"] = ga4_info
        dl_events = gtm_api.extract_datalayer_events(tag)
        if dl_events:
            analysis["datalayer_events"] = dl_events
        data["tag_analysis"].append(analysis)

    print("Extracting measurement IDs...")
    data["measurement_ids"] = gtm_api.get_measurement_ids(data["tags"], data["variables"])

    save_result(config, "phase3", data)
    print(f"\nPhase 3 完了: tags={len(data['tags'])}, triggers={len(data['triggers'])}, variables={len(data['variables'])}")


def run_phase5(config: AuditConfig):
    """Phase 5: UTM パラメータ監査"""
    import ga4_data as data_api

    data = {}

    print("Getting UTM sources...")
    data["sources"] = data_api.get_utm_sources(config)

    print("Getting UTM campaigns...")
    data["campaigns"] = data_api.get_utm_campaigns(config)

    print("Getting AI traffic...")
    data["ai_traffic"] = data_api.get_ai_traffic(config)

    print("Getting utm_content...")
    data["utm_content"] = data_api.run_report(
        config,
        dimensions=["sessionManualAdContent", "sessionCampaignName"],
        metrics=["sessions"],
        start_date="90daysAgo",
        order_by_metric="sessions",
        limit=50,
    )

    save_result(config, "phase5", data)
    print(f"\nPhase 5 完了")


def run_phase6(config: AuditConfig):
    """Phase 6: ホスト名・クロスドメイン監査"""
    import ga4_data as data_api

    data = {}

    print("Getting hostnames...")
    data["hostnames"] = data_api.get_hostnames(config)

    print("Getting Unassigned by hostname...")
    data["unassigned"] = data_api.run_report(
        config,
        dimensions=["hostName", "sessionSource"],
        metrics=["sessions"],
        start_date="90daysAgo",
        dimension_filter=data_api.filter_exact("sessionSource", "(not set)"),
        order_by_metric="sessions",
    )

    save_result(config, "phase6", data)
    print(f"\nPhase 6 完了")


def run_phase7(config: AuditConfig):
    """Phase 7: イベント推移の異常検知"""
    import ga4_data as data_api

    # Phase 2 のイベント一覧から主要イベントを取得
    phase2_file = config.data_dir / "phase2.json"
    if not phase2_file.exists():
        print("Phase 2 data not found. Run phase2 first.")
        sys.exit(1)

    with open(phase2_file, encoding="utf-8") as f:
        phase2 = json.load(f)

    events = phase2.get("events_30d", [])
    top_events = [e["eventName"] for e in events[:20]]

    data = {}

    print(f"Getting monthly trend for {len(top_events)} events...")
    data["monthly_trend"] = data_api.get_event_monthly_trend(config, top_events)

    # 異常検知
    print("Detecting anomalies...")
    anomalies = detect_anomalies(data["monthly_trend"])
    data["anomalies"] = anomalies

    # 異常があれば日次データを取得
    for anomaly in anomalies:
        if anomaly["severity"] in ("High", "Medium"):
            event = anomaly["event_name"]
            month = anomaly["month"]
            print(f"  Daily drill-down: {event} @ {month}...")
            year = int(month[:4])
            m = int(month[4:])
            start = f"{year}-{m:02d}-01"
            if m == 12:
                end = f"{year + 1}-01-31"
            else:
                end = f"{year}-{m + 1:02d}-01"
            try:
                data[f"daily_{event}_{month}"] = data_api.get_event_daily(config, event, start, end)
            except Exception as e:
                data[f"daily_{event}_{month}"] = {"error": str(e)}

    save_result(config, "phase7", data)
    print(f"\nPhase 7 完了: {len(anomalies)} 件の異常検出")


def detect_anomalies(monthly_data: list[dict]) -> list[dict]:
    """月次データから異常を検出"""
    # イベントごとに月次データを整理
    by_event: dict[str, dict[str, int]] = {}
    for row in monthly_data:
        event = row["eventName"]
        month = row["yearMonth"]
        count = int(row["eventCount"])
        if event not in by_event:
            by_event[event] = {}
        by_event[event][month] = count

    anomalies = []
    for event, months in by_event.items():
        sorted_months = sorted(months.keys())
        for i in range(1, len(sorted_months)):
            prev_month = sorted_months[i - 1]
            curr_month = sorted_months[i]
            prev_count = months[prev_month]
            curr_count = months[curr_month]

            if prev_count == 0:
                continue

            ratio = curr_count / prev_count

            if ratio < 0.2:
                anomalies.append({
                    "event_name": event,
                    "month": curr_month,
                    "prev_month": prev_month,
                    "prev_count": prev_count,
                    "curr_count": curr_count,
                    "change_ratio": ratio,
                    "severity": "High",
                    "description": f"80%以上の急減（{prev_count:,} → {curr_count:,}）",
                })
            elif ratio < 0.5:
                anomalies.append({
                    "event_name": event,
                    "month": curr_month,
                    "prev_month": prev_month,
                    "prev_count": prev_count,
                    "curr_count": curr_count,
                    "change_ratio": ratio,
                    "severity": "Medium",
                    "description": f"50%以上の減少（{prev_count:,} → {curr_count:,}）",
                })
            elif ratio > 5.0:
                anomalies.append({
                    "event_name": event,
                    "month": curr_month,
                    "prev_month": prev_month,
                    "prev_count": prev_count,
                    "curr_count": curr_count,
                    "change_ratio": ratio,
                    "severity": "Info",
                    "description": f"500%以上の急増（{prev_count:,} → {curr_count:,}）",
                })

        # 2ヶ月以上連続ゼロチェック
        if len(sorted_months) >= 3:
            last_two = [months[m] for m in sorted_months[-2:]]
            earlier = [months[m] for m in sorted_months[:-2]]
            if all(c == 0 for c in last_two) and any(c > 0 for c in earlier):
                anomalies.append({
                    "event_name": event,
                    "month": sorted_months[-1],
                    "severity": "High",
                    "description": "2ヶ月以上連続でゼロ — タグ停止の可能性",
                })

    return anomalies


def run_phase8(config: AuditConfig):
    """Phase 8: 基礎パフォーマンス分析"""
    import ga4_data as data_api

    data = {}

    print("Getting monthly overview (13 months)...")
    data["monthly_overview"] = data_api.get_monthly_overview(config)

    print("Getting channel monthly...")
    data["channel_monthly"] = data_api.get_channel_monthly(config)

    print("Getting source/medium top 20...")
    data["source_medium_top"] = data_api.get_source_medium_top(config)

    print("Getting source/medium YoY...")
    try:
        current_range, prev_range = data_api.get_yoy_ranges()
        data["source_medium_yoy"] = data_api.run_report_dual_date(
            config,
            dimensions=["sessionSourceMedium"],
            metrics=["sessions", "keyEvents"],
            date_range_1=current_range,
            date_range_2=prev_range,
            order_by_metric="sessions",
            limit=20,
        )
    except Exception as e:
        data["source_medium_yoy"] = {"error": str(e)}

    print("Getting device monthly...")
    data["device_monthly"] = data_api.get_device_monthly(config)

    print("Getting key events breakdown...")
    data["key_events_breakdown"] = data_api.get_key_events_breakdown(config)

    save_result(config, "phase8", data)
    print(f"\nPhase 8 完了")


def run_phase9(config: AuditConfig):
    """Phase 9: Search Console 監査"""
    import site_audit

    if not config.sc_site_url:
        print("Search Console サイト URL が指定されていません。--sc-site-url を指定してください。")
        sys.exit(1)

    data = {}

    # パフォーマンス（過去16ヶ月）
    from datetime import date, timedelta
    end = date.today()
    start_16m = end - timedelta(days=480)
    start_30d = end - timedelta(days=30)

    print("Getting SC performance (16 months)...")
    data["performance_daily"] = site_audit.get_sc_performance_monthly(
        config, start_16m.isoformat(), end.isoformat()
    )

    print("Getting SC performance by page (16 months)...")
    data["performance_by_page"] = site_audit.get_sc_performance_by_page(
        config, start_16m.isoformat(), end.isoformat()
    )

    print("Getting top queries (30 days)...")
    data["top_queries"] = site_audit.get_sc_top_queries(config, start_30d.isoformat(), end.isoformat())

    print("Getting top pages (30 days)...")
    data["top_pages"] = site_audit.get_sc_top_pages(config, start_30d.isoformat(), end.isoformat())

    print("Getting device breakdown (30 days)...")
    data["by_device"] = site_audit.get_sc_by_device(config, start_30d.isoformat(), end.isoformat())

    print("Getting sitemaps...")
    data["sitemaps"] = site_audit.get_sc_sitemaps(config)

    # URL 検査（主要ページ）
    print("Inspecting key URLs...")
    base = config.site_url or config.sc_site_url.rstrip("/")
    key_urls = [base + "/", base + "/jobs", base + "/search"]
    # 上位ページから数件
    for row in data["top_pages"][:5]:
        url = row["keys"][0]
        if url not in key_urls:
            key_urls.append(url)

    data["url_inspections"] = []
    for url in key_urls[:10]:
        print(f"  Inspecting {url}...")
        data["url_inspections"].append({"url": url, "result": site_audit.inspect_url(config, url)})

    # robots.txt
    print("Checking robots.txt...")
    data["robots_txt"] = site_audit.check_robots_txt(base)

    # BQ 連携
    print("Checking BigQuery links...")
    data["bq_links"] = site_audit.get_bq_links(config)

    save_result(config, "phase9", data)
    print(f"\nPhase 9 完了: SC パフォーマンス + サイトマップ + URL検査 + robots.txt")


def run_phase10(config: AuditConfig):
    """Phase 10: SSR / 構造化データ / PageSpeed 監査"""
    import site_audit

    if not config.site_url and not config.sc_site_url:
        print("サイト URL が指定されていません。--site-url を指定してください。")
        sys.exit(1)

    base = config.site_url or config.sc_site_url.rstrip("/")
    data = {}

    # SSR 検証（主要ページ）
    print("Checking SSR output...")
    ssr_urls = [base + "/"]
    # トップページ以外のパスを推定
    for path in ["/jobs", "/search", "/column"]:
        ssr_urls.append(base + path)

    data["ssr_checks"] = []
    for url in ssr_urls:
        print(f"  SSR check: {url}")
        data["ssr_checks"].append(site_audit.check_ssr_output(url))

    # 構造化データ検証
    print("Checking structured data...")
    data["structured_data"] = []
    for url in ssr_urls:
        print(f"  Schema check: {url}")
        data["structured_data"].append(
            site_audit.check_structured_data(url, config.industry)
        )

    # PageSpeed Insights (Lighthouse)
    print("Running Lighthouse...")
    data["lighthouse"] = []
    for url in ssr_urls[:3]:  # 上位3ページ
        slug = url.replace(base, "").strip("/").replace("/", "_") or "top"
        out_path = str(config.data_dir / f"lighthouse_{slug}.json")
        print(f"  Lighthouse: {url}")
        result = site_audit.run_lighthouse(url, out_path)
        if result:
            data["lighthouse"].append(result)

    # 業種情報
    if config.industry and config.industry in site_audit.INDUSTRY_SCHEMA_MAP:
        data["industry_spec"] = site_audit.INDUSTRY_SCHEMA_MAP[config.industry]

    save_result(config, "phase10", data)
    print(f"\nPhase 10 完了: SSR {len(data['ssr_checks'])}ページ + 構造化データ + Lighthouse {len(data['lighthouse'])}ページ")


def main():
    parser = argparse.ArgumentParser(description="GA4 設定確認パック - Phase 実行")
    parser.add_argument("phase", choices=["preflight", "phase1", "phase2", "phase3", "phase5", "phase6", "phase7", "phase8", "phase9", "phase10"])
    parser.add_argument("--property-id", required=True, help="GA4 プロパティ ID")
    parser.add_argument("--client", required=True, help="クライアント名")
    parser.add_argument("--account-id", default="", help="GA アカウント ID")
    parser.add_argument("--gtm-account", default="", help="GTM アカウント ID")
    parser.add_argument("--gtm-container", default="", help="GTM コンテナ ID")
    parser.add_argument("--site-url", default="", help="対象サイト URL（例: https://example.com）")
    parser.add_argument("--sc-site-url", default="", help="Search Console サイト URL（例: https://example.com/）")
    parser.add_argument("--industry", default="", help="業種（hr, travel, media, ec, realestate, restaurant, saas）")
    parser.add_argument("--auth", default="sa", choices=["adc", "oauth", "sa"], help="認証方法")
    parser.add_argument("--oauth-profile", default="", help="OAuth プロファイル名")

    args = parser.parse_args()

    config = AuditConfig(
        property_id=args.property_id,
        client_name=args.client,
        account_id=args.account_id,
        gtm_account_id=args.gtm_account,
        gtm_container_id=args.gtm_container,
        site_url=args.site_url,
        sc_site_url=args.sc_site_url,
        industry=args.industry,
        auth_method=args.auth,
        oauth_profile=args.oauth_profile,
    )

    phases = {
        "preflight": run_preflight,
        "phase1": run_phase1,
        "phase2": run_phase2,
        "phase3": run_phase3,
        "phase5": run_phase5,
        "phase6": run_phase6,
        "phase7": run_phase7,
        "phase8": run_phase8,
        "phase9": run_phase9,
        "phase10": run_phase10,
    }

    result = phases[args.phase](config)
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())
