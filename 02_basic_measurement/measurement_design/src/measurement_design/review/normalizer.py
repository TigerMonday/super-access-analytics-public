"""レビューデータの正規化モジュール.

phase1.json + phase2.json + phase3.json(optional) から
review_data dict を構築する。
"""

from __future__ import annotations

import json
from pathlib import Path


def build_review_data(data_dir: Path) -> dict:
    """phase JSON ファイルから review_data dict を構築する."""
    phase1_file = data_dir / "phase1.json"
    phase2_file = data_dir / "phase2.json"

    if not phase1_file.exists():
        raise FileNotFoundError(f"phase1.json が見つかりません: {phase1_file}")

    with open(phase1_file, encoding="utf-8") as f:
        phase1 = json.load(f)

    phase2 = {}
    if phase2_file.exists():
        with open(phase2_file, encoding="utf-8") as f:
            phase2 = json.load(f)

    review_data: dict = {"ga4": _build_ga4_section(phase1, phase2)}

    phase3_file = data_dir / "phase3.json"
    if phase3_file.exists():
        with open(phase3_file, encoding="utf-8") as f:
            phase3 = json.load(f)
        review_data["gtm"] = _build_gtm_section(phase3)

    return review_data


def _build_ga4_section(phase1: dict, phase2: dict) -> dict:
    prop = phase1.get("property", {})
    prop_name = prop.get("name", "")
    prop_id = prop_name.split("/")[-1] if "/" in prop_name else prop_name

    events_observed = []
    for row in phase2.get("events_30d", []):
        events_observed.append({
            "name": row.get("eventName", ""),
            "count": int(row.get("eventCount", 0)),
        })

    # events_30d は eventCount 上位100件だけなので、確認済みCVの0件判定には使わない。
    # 新しい取得データでは全イベント名の件数を別に保持する。旧データや取得不足は
    # missing とし、「一覧に無い = 0件」に丸めない。
    all_count_rows = phase2.get("event_name_counts_30d")
    counts_status = phase2.get("event_name_counts_status")
    if isinstance(all_count_rows, list) and counts_status == "complete":
        event_counts_all = [
            {"name": row.get("eventName", ""), "count": int(row.get("eventCount", 0) or 0)}
            for row in all_count_rows if row.get("eventName")
        ]
        event_counts_status = "complete"
    else:
        event_counts_all = []
        event_counts_status = counts_status if counts_status in {"error", "missing"} else "missing"

    key_events = [
        ke.get("event_name", ke.get("eventName", ""))
        for ke in phase1.get("key_events", [])
    ]

    dims = phase1.get("custom_dimensions", [])
    mets = phase1.get("custom_metrics", [])

    return {
        "property": {
            "id": prop_id,
            "name": prop.get("display_name", ""),
            "timezone": prop.get("time_zone", ""),
            "currency": prop.get("currency_code", ""),
            # GTMの送信先が、今回点検しているGA4ストリーム宛かを照合するために保持する。
            # 測定IDが無い状態では「設定はあるが未受信」と断定しない。
            "data_streams": phase1.get("data_streams", []),
        },
        "key_events": key_events,
        "custom_definitions": {
            "dimensions": [
                {
                    "parameter_name": d.get("parameter_name", ""),
                    "scope": d.get("scope", ""),
                    "display_name": d.get("display_name", ""),
                }
                for d in dims
            ],
            "metrics": [
                {
                    "parameter_name": m.get("parameter_name", ""),
                    "scope": m.get("scope", ""),
                    "display_name": m.get("display_name", ""),
                }
                for m in mets
            ],
        },
        "events_observed": events_observed,
        "event_counts_all": event_counts_all,
        "event_counts_status": event_counts_status,
    }


def _scalar_tag_params(tag: dict) -> dict:
    """タグの単純パラメータ（スカラー値）だけを {key: value} で抽出する.

    LIST / MAP の複合パラメータは値の比較が難しいので除外し、
    固定値 / 分岐値の判定や値の使い回し検出に使えるスカラー値だけを残す。
    """
    params: dict = {}
    for p in tag.get("parameter", []):
        if p.get("type") in ("LIST", "MAP"):
            continue
        key = p.get("key", "")
        value = p.get("value", "")
        if key:
            params[key] = value
    return params


def _build_gtm_section(phase3: dict) -> dict:
    tags = phase3.get("tags", [])
    triggers = phase3.get("triggers", [])
    variables = phase3.get("variables", [])
    tag_analysis = phase3.get("tag_analysis", [])

    # tag_analysis から name → type_label を引けるようにする（種別の日本語ラベル用）。
    type_label_by_name = {
        a.get("name", ""): a.get("type_label", "")
        for a in tag_analysis
    }
    trigger_name_by_id = {
        str(t.get("triggerId", "")): t.get("name", "")
        for t in triggers
        if t.get("triggerId") is not None
    }

    firing_trigger_ids: set[str] = set()
    tag_names_with_trigger: set[str] = set()
    for tag in tag_analysis:
        ids = tag.get("firing_trigger_ids", [])
        if ids:
            firing_trigger_ids.update(ids)
            tag_names_with_trigger.add(tag.get("name", ""))

    tags_without_trigger = [
        t.get("name", "") for t in tags
        if t.get("name", "") not in tag_names_with_trigger
    ]
    triggers_without_tag = [
        t.get("name", "") for t in triggers
        if t.get("triggerId", "") not in firing_trigger_ids
    ]

    # 量産・重複発火・残骸・値の使い回し検出に使う、タグ単位の生情報。
    # phase3 の raw tags（paused・parameter・firingTriggerId 等を含む）から構築する。
    tags_detail = []
    for t in tags:
        name = t.get("name", "")
        params = _scalar_tag_params(t)
        event_name = params.get("eventName", "")
        firing_ids = [str(v) for v in t.get("firingTriggerId", [])]
        destination = (
            params.get("measurementIdOverride")
            or params.get("measurementId")
            or params.get("tagId")
            or ""
        )
        tags_detail.append({
            "name": name,
            "type": t.get("type", ""),
            "type_label": type_label_by_name.get(name, ""),
            "paused": bool(t.get("paused", False)),
            "firing_trigger_ids": firing_ids,
            "firing_trigger_names": [
                trigger_name_by_id.get(trigger_id, f"ID {trigger_id}")
                for trigger_id in firing_ids
            ],
            "blocking_trigger_ids": t.get("blockingTriggerId", []),
            "event_name": event_name,
            "destination": destination,
            "params": params,
        })

    detail_by_name = {t.get("name", ""): t for t in tags_detail}
    ga4_event_tags = []
    for analysis in tag_analysis:
        if not analysis.get("ga4_event"):
            continue
        tag_name = analysis.get("name", "")
        detail = detail_by_name.get(tag_name, {})
        ga4_event_tags.append({
            "tag_name": tag_name,
            "event_name": analysis.get("ga4_event", {}).get("event_name", ""),
            "firing_trigger_names": detail.get("firing_trigger_names", []),
            "destination": detail.get("destination", ""),
            "paused": bool(detail.get("paused", False)),
        })

    return {
        "container": {
            "counts": {
                "tags": len(tags),
                "triggers": len(triggers),
                "variables": len(variables),
            }
        },
        "ga4_event_tags": ga4_event_tags,
        "tags_detail": tags_detail,
        "triggers": [
            {
                "id": str(t.get("triggerId", "")),
                "name": t.get("name", ""),
                "type": t.get("type", ""),
            }
            for t in triggers
        ],
        "orphans": {
            "tags_without_trigger": tags_without_trigger,
            "triggers_without_tag": triggers_without_tag,
        },
    }
