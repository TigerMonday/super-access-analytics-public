"""`_data/` の観点別データセットを人間可読のサマリーに変換する。

**作業用の一時ビュー。** fetch 直後に生データを読むためのもので、
`_data/summary.md` に出力するが git 管理しない（.gitignore 済み・いつでも再生成できる）。

成果物としての人間可読な現状記述は `docs/design-doc/` が担う。
summary.md をそのまま成果物にしない。

Usage:
    python run.py summarize --client <client_id>
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from config import AuditConfig


def _load(data_dir: Path, name: str) -> dict | None:
    """観点別データセットを読む（旧 phase*.json にもフォールバックする）。"""
    import dataset

    data = dataset.load(data_dir, name)
    return data or None


def _gtm_source_method(p3: dict) -> str:
    """GTM データをどう取得したかを返す（`api` / `public_gtm_js` / 不明）。

    フォールバック経路（`gtm_public.py`）は `source.method` を明示的に持つが、
    API 経路（`gtm.py`）はこのキーを持たず `live_version` を持つ。
    `live_version.description` は運用者が書いた社内向けの版名・リリースノートで、
    「どう取得したか」とは無関係（取得方法として表示していたのは誤り）。
    """
    method = (p3.get("source") or {}).get("method")
    if method:
        return method
    if "live_version" in p3:
        return "api"
    return "不明"


def _num(value) -> int:
    """GA4 Data API は数値を文字列で返すため int に寄せる。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _table(headers: list[str], rows: list[list[str]], align_right: set[int] | None = None) -> list[str]:
    align_right = align_right or set()
    sep = ["---:" if i in align_right else "---" for i in range(len(headers))]
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(sep) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out


def _section_property(p1: dict) -> list[str]:
    lines = ["## 1. プロパティ設定（01-property）", ""]
    prop = p1.get("property", {})
    streams = p1.get("data_streams", [])
    retention = p1.get("data_retention", {})

    rows = [
        ["プロパティ名", str(prop.get("display_name", "—"))],
        ["プロパティID", str(prop.get("name", "—")).replace("properties/", "")],
        ["アカウントID", str(prop.get("parent", "—")).replace("accounts/", "")],
        ["業種", str(prop.get("industry_category", "—"))],
        ["タイムゾーン / 通貨", f"{prop.get('time_zone', '—')} / {prop.get('currency_code', '—')}"],
        ["サービスレベル", str(prop.get("service_level", "—"))],
        ["作成日", str(prop.get("create_time", "—"))[:10]],
        ["イベントデータ保持", str(retention.get("event_data_retention", "—"))],
        ["ユーザーデータ保持", str(retention.get("user_data_retention", "—"))],
    ]
    lines += _table(["項目", "値"], rows)
    lines.append("")

    if streams:
        lines += ["### データストリーム", ""]
        srows = []
        for s in streams:
            web = s.get("web_stream_data", {}) or {}
            srows.append([
                str(s.get("display_name", "—")),
                str(s.get("type_", "—")),
                str(web.get("measurement_id", "—")),
                str(web.get("default_uri", "—")),
            ])
        lines += _table(["名称", "種別", "測定ID", "既定URI"], srows)
        lines.append("")

    em_key = next((k for k in p1 if k.startswith("enhanced_measurement_")), None)
    if em_key:
        em = p1[em_key]
        flags = [(k, v) for k, v in em.items() if k.endswith("_enabled")]
        # 可否は ○ × に統一し、表の前に凡例を置く。
        # ここは **Markdown の表を組み立てている**ので、コンソール出力ではなく文書。
        lines += ["### 拡張計測", "", "有効：`○`＝オン／`×`＝オフ", ""]
        lines += _table(
            ["項目", "有効"],
            [[k.removesuffix("_enabled"), "○" if v else "×"] for k, v in flags],
        )
        lines.append("")

    counts = [
        ("キーイベント", len(p1.get("key_events", []))),
        ("カスタムディメンション", len(p1.get("custom_dimensions", []))),
        ("カスタム指標", len(p1.get("custom_metrics", []))),
        ("オーディエンス", len(p1.get("audiences", []))),
        ("イベント作成ルール", len(next((v for k, v in p1.items() if k.startswith("event_create_rules_")), []))),
        ("広告リンク", len(p1.get("ads_links", []))),
    ]
    lines += ["### 定義済みリソースの件数", ""]
    lines += _table(["種別", "件数"], [[n, f"{c:,}"] for n, c in counts], align_right={1})
    lines.append("")
    return lines


def _section_key_events(p1: dict, p2: dict) -> list[str]:
    """キーイベントの登録状況と直近30日の発火数を突き合わせる。"""
    lines = ["## 2. キーイベントと発火実績（02-events）", ""]
    fired = {e["eventName"]: _num(e.get("eventCount")) for e in p2.get("events_30d", [])}
    key_fired = {e["eventName"]: _num(e.get("eventCount")) for e in p2.get("key_event_firing", [])}

    rows = []
    for ke in p1.get("key_events", []):
        name = ke.get("event_name", "—")
        count = key_fired.get(name, fired.get(name, 0))
        rows.append([
            f"`{name}`",
            str(ke.get("counting_method", "—")),
            f"{count:,}",
            "稼働中" if count else "**発火なし**",
        ])
    rows.sort(key=lambda r: -int(r[2].replace(",", "")))
    lines += _table(["キーイベント", "カウント方法", "直近30日", "状態"], rows, align_right={2})
    lines.append("")

    live = sum(1 for r in rows if r[3] == "稼働中")
    lines.append(
        f"登録 {len(rows)} 件のうち発火しているのは **{live} 件**。"
        f"発火のないキーイベントは成果の一覧として使えないため、実装状況の確認か登録解除を検討する。"
    )
    lines.append("")
    return lines


def _section_events(p2: dict) -> list[str]:
    lines = ["## 3. イベント発火実績 直近30日（02-events）", ""]
    events = sorted(p2.get("events_30d", []), key=lambda e: -_num(e.get("eventCount")))
    total = sum(_num(e.get("eventCount")) for e in events)
    lines.append(f"計測されているイベント **{len(events)} 種**、発火合計 **{total:,} 件**。")
    lines.append("")
    rows = [
        [f"`{e['eventName']}`", f"{_num(e.get('eventCount')):,}", f"{_num(e.get('totalUsers')):,}"]
        for e in events
    ]
    lines += _table(["イベント名", "発火数", "ユーザー数"], rows, align_right={1, 2})
    lines.append("")
    return lines


def _section_channels(p2: dict) -> list[str]:
    rows_raw = p2.get("channel_performance", [])
    if not rows_raw:
        return []
    lines = ["## 4. チャネル別パフォーマンス 直近30日（05-traffic）", ""]
    total_s = sum(_num(r.get("sessions")) for r in rows_raw)
    rows = []
    for r in sorted(rows_raw, key=lambda r: -_num(r.get("sessions"))):
        s = _num(r.get("sessions"))
        rows.append([
            str(r.get("sessionDefaultChannelGroup", "—")),
            f"{s:,}",
            f"{s / total_s * 100:.1f}%" if total_s else "—",
        ])
    rows.append(["**合計**", f"**{total_s:,}**", "100.0%"])
    lines += _table(
        ["チャネル", "セッション", "構成比"], rows,
        align_right={1, 2},
    )
    lines += [
        "",
        "> 合計セッションはディメンション別集計の総和であり、ディメンションを付けない"
        "プロパティ総計とは一致しない（GA4 の仕様）。",
        "",
    ]
    return lines


def _section_gtm(p3: dict) -> list[str]:
    lines = ["## 5. GTM 構成（09-gtm）", ""]
    live = p3.get("live_version", {}) or {}
    lines += _table(
        ["項目", "値"],
        [
            ["取得方法", _gtm_source_method(p3)],
            ["コンテナの公開版名", str(live.get("name", "—"))],
            ["公開時のメモ", str(live.get("description", "—"))],
            ["測定ID", ", ".join(p3.get("measurement_ids", [])) or "—"],
            ["タグ", f"{len(p3.get('tags', [])):,}"],
            ["トリガー", f"{len(p3.get('triggers', [])):,}"],
            ["ユーザー定義変数", f"{len(p3.get('variables', [])):,}"],
            ["組み込み変数", f"{len(p3.get('built_in_variables', [])):,}"],
        ],
    )
    lines.append("")

    analysis = p3.get("tag_analysis", []) or p3.get("tags", [])
    by_type: dict[str, int] = {}
    for t in analysis:
        label = t.get("type_label") or t.get("type") or "不明"
        by_type[label] = by_type.get(label, 0) + 1
    if by_type:
        lines += ["### タグ種別の内訳", ""]
        lines += _table(
            ["種別", "件数"],
            [[k, f"{v:,}"] for k, v in sorted(by_type.items(), key=lambda x: -x[1])],
            align_right={1},
        )
        lines.append("")

    # 同名・枝番タグの検出（重複疑い）
    names: dict[str, list[str]] = {}
    for t in analysis:
        n = str(t.get("name", ""))
        base = n.rstrip("0123456789 　_-")  # leak-ok: 末尾の数字を削る文字集合（IDではない）
        names.setdefault(base, []).append(n)
    dupes = {k: v for k, v in names.items() if len(v) > 1 and k}
    lines += ["### 同名・枝番タグ（重複の疑い）", ""]
    if dupes:
        lines.append(f"共通の名前を持つタグが **{len(dupes)} 組**（{sum(len(v) for v in dupes.values())} 本）。")
        lines.append("")
        rows = [[f"`{k}`", f"{len(v)}", "、".join(f"`{x}`" for x in sorted(v)[:4])]
                for k, v in sorted(dupes.items(), key=lambda x: -len(x[1]))[:20]]
        lines += _table(["共通部分", "本数", "タグ名（最大4件）"], rows, align_right={1})
        lines.append("")
        lines.append("> 名前による機械的な検出。意図的に分けているものも含まれるため、停止・削除の判断は個別に行う。")
    else:
        lines.append("検出なし。")
    lines.append("")
    return lines


def _section_gtm_ga4_gap(p2: dict, p3: dict) -> list[str]:
    """GTM が送っている GA4 イベント名のうち、GA4 側で受信が確認できないものを出す。"""
    received = {e["eventName"] for e in p2.get("events_30d", [])}
    sent: dict[str, str] = {}
    for t in p3.get("tags", []):
        if "gaawe" not in str(t.get("type", "")):
            continue
        for param in t.get("parameter", []) or []:
            if param.get("key") == "eventName":
                value = str(param.get("value", "")).strip()
                if value and not value.startswith("{{"):
                    sent.setdefault(value, str(t.get("name", "")))

    missing = {k: v for k, v in sent.items() if k not in received}
    lines = ["## 6. GTM 送信 × GA4 受信の差分（09-gtm × 02-events）", ""]
    if not sent:
        lines += ["GTM のエクスポートから固定値のイベント名を抽出できなかった（変数参照のみ）。", ""]
        return lines
    lines.append(
        f"GTM の GA4 イベントタグから固定値のイベント名を **{len(sent)} 種**抽出し、"
        f"直近30日の GA4 受信イベントと突き合わせた。"
    )
    lines.append("")
    if missing:
        rows = [[f"`{k}`", f"`{v}`"] for k, v in sorted(missing.items())]
        lines += _table(["GA4 で未受信のイベント名", "GTM タグ名"], rows)
        lines += [
            "",
            "> トリガーが動いていないか、設定が途中で止まっている可能性がある。"
            "不要なら削除、必要なら実装を確認する。",
            "",
        ]
    else:
        lines += ["未受信のイベントなし。", ""]
    return lines


def generate(config: AuditConfig, run_date: str | None = None) -> Path:
    """phase1〜3 からサマリーレポートを生成して docs/ に書き出す。"""
    data_dir = config.data_dir
    prop = _load(data_dir, "property")
    defs = _load(data_dir, "custom_definitions")
    ev = _load(data_dir, "events")
    tr = _load(data_dir, "traffic")
    p3 = _load(data_dir, "gtm")
    # 旧 phase1/2 相当の束ね直し（既存のセクション関数がこの形を前提にしている）
    p1 = {**(prop or {}), **(defs or {}),
          **({"key_events": ev["key_events"]} if ev and "key_events" in ev else {})} or None
    p2 = {**{k: v for k, v in (ev or {}).items() if k != "key_events"}, **(tr or {})} or None
    if p1 is None and p2 is None:
        raise FileNotFoundError(
            f"phase1.json / phase2.json が見つかりません: {data_dir}\n"
            "先に fetch を実行してください。"
        )

    run_date = run_date or date.today().isoformat()
    lines = [
        f"# 取得データ サマリー — {config.client_name}",
        "",
        "`fetch` で取得した観点別データセットを人間可読にしたもの。"
        "**作業用の一時ビューで git 管理しない**（`run.py summarize` でいつでも再生成できる）。"
        "成果物としての現状記述は `docs/design-doc/` を参照。",
        "",
        "## 実行メタデータ",
        "",
    ]
    # property_id が渡されていなくても phase1 から確実に引ける
    property_id = config.property_id or str((p1 or {}).get("property", {}).get("name", "")).replace(
        "properties/", ""
    )
    meta = [
        ["生成日", run_date],
        ["GA4 プロパティ", property_id or "—"],
        ["client_id", config.client_name],
        ["データ元", ", ".join(n for n, d in (("01-property", p1), ("02-events", p2), ("09-gtm", p3)) if d)],
    ]
    if p3:
        meta.append(["GTM 取得方法", _gtm_source_method(p3)])
    lines += _table(["項目", "値"], meta)
    lines += ["", "---", ""]

    if p1:
        lines += _section_property(p1)
    if p1 and p2:
        lines += _section_key_events(p1, p2)
    if p2:
        lines += _section_events(p2)
        lines += _section_channels(p2)
    if p3:
        lines += _section_gtm(p3)
    if p2 and p3:
        lines += _section_gtm_ga4_gap(p2, p3)

    out = config.data_dir / "summary.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out
