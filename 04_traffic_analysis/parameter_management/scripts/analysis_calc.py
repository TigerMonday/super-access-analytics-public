"""基本分析レポートの計算ロジック（GA4 API 呼び出しを含まない純粋関数のみ）

fetch_ga4_analytics.py から呼ばれる。GA4 API に依存しないため、
tests/test_analysis_calc.py で実データ無しに単体テストできる。

含む計算:
- delta_pct: 前期比・前週比・前月比の共通計算（セッション・ユーザー・CVなど実数指標専用）
- delta_pt: 率指標の前期比較専用。ポイント（pt）差分で返す
  （実数指標の相対変化率と、率指標のポイント差分は計算方法が違うため関数を分けている。
  率にdelta_pctを使うと「72.3%に対して2.1%増えた」という誤読を招く相対値になってしまい、
  実際のポイント差（+1.5pt）と乖離する）
- compute_funnel: CVファネルの各ステップに「到達率」と「到達後の転換率」を付与
- select_funnels: CVファネルを作る本数を、CV件数が多い順に上限（既定5本）まで絞る
- rank_page_candidates: CVファネルの中間ページ候補を、セッション数（共起）の多い順に並べる。
  event_name を渡すと、キーイベント自身の発火ページ（サンクスページ等）を推定して除外扱いにする
- with_parent_path_guess: 候補が全て除外扱い（サンクスページ型）だった場合に、完了ページの
  親パスを既に取得済みのページ一覧と照合し、実在すれば「推定候補」として先頭に追加する
- unclassified_diff: デバイス別・新規/リピーター別のシェアの分母を「全体セッション」に揃え、
  内訳の合計が全体に届かない場合の差分（GA4が分類できないセッション）を返す
- reconciliation_diff / format_reconciliation_note: 絞り込み条件付きの取得（フィルタ・
  クロス集計）の内訳合計と、参照値（絞り込み無しの全体・別集計の合計など）の差を符号付きで
  返し、注記文に整形する。unclassified_diff は差を0にクランプする（内訳漏れ専用）のに対し、
  この2関数は内訳合計が参照値を上回るケース（取得の切り口が違う値どうしを比べたことによる
  ズレ）も黙って消さずそのまま出す
- rank_with_gap: セッション数ランキングとCV数ランキングを両方作り、量と質のズレを可視化
- format_week_range: GA4のyearWeek（YYYYWW）を「YYYY/MM/DD〜MM/DD」の日付レンジ表記に変換
- mark_incomplete_months: 取得期間の端にあたる不完全な月次行に目印を付与
- parse_event_names_json: 01の kpis.yaml から作った {event_name: KPI名} のJSON文字列をパース。
  未指定・不正な値でも例外を出さず空辞書にする（レポートを止めない）
- format_funnel_title: CVファネル見出し用に「KPI名（event_name）」を組み立てる。名前が無い
  イベントは event_name のみ（フォールバック）
- format_key_events_header: レポートヘッダーの「キーイベント」表示用に、イベントコードと
  KPI名を組み立てる。1つのKPIが複数イベントを持つ場合はまとめて表示する
- kpi_labels_and_events: key_events を業務名（またはイベント名）が同じKPI単位にグループ化し、
  表示ラベルを確定させる。複数CVを合算せず内訳表示する全セクションの下ごしらえ
- kpi_group_rows: 上記のグループごとにCV件数（当期・前期）を集計し、01の優先度1（主KPI）が
  あれば先頭に並べ替えて★印を付ける（「主KPIを主として扱う」の実装）
- kpi_display_label / kpi_column_headers / kpi_column_cells: kpi_group_rows() の結果を
  Markdownの列見出し・セルに整形する小さな組み立て関数
- attach_kpi_breakdown: チャネル別・ランディングページ別などの既存の集計行に、
  kpi_group_rows() 形式のCV内訳を付与する（該当データが無い行は0件で埋め、黙って空けない）
- select_funnels の primary_events 引数: 主KPIに属するイベントをCV件数の順位に関わらず
  先頭に並べ、`--funnel-max` の上限cutoffで黙って落とさないようにする

サイトセグメント（そのセクションが何であるか、の定義。01の site-segments.yaml 由来）関連:
- match_site_segment: 01の `context_store.schema` にある同名関数と完全に同じ
  アルゴリズムの複製（02は01に依存しない設計のため、判定ロジックをここに複製している。
  片方だけ直すと2つが違う結果を返す事故につながるため、両者が同じ入力に同じ結果を
  返すことを tests/test_analysis_calc.py の MatchSiteSegmentParityWithSchemaTest で
  固定している）。`default: true` のセグメント（どの match にも一致しないページの
  既定の受け皿）の扱いも複製している
- landing_page_dimension / page_path_dimension: クエリパラメータを含めるかどうかで
  使うGA4ディメンション名を切り替える（既定はパスのみ。実データで `/?renew=` のような
  クエリ付き別名や、完了ページのクエリ違いで中間ページ候補が埋まる不具合があったため）
- classify_segment_rows: ページ単位の行をセグメントごとに分類・集計する（どのセグメントを
  CVR分母とみなすかは02側では決めない＝「対象」「対象外」の区分けはしない。サマリーに
  セグメント別の内訳を並べるための土台）。実データで「独立した3つの切り口の合計が全体を
  29,361件上回っていた」事故（分類漏れの黙殺）があったため、その他は必ず件数付きで残す
- segment_breakdown_table_lines: 上記の分類結果をサマリーの「セグメント別内訳」の表に
  整形する
- detect_trailing_slash_dupes: 末尾スラッシュ違いで別行になっているパスの組を検出する
  （実データで `/contact/service` と `/contact/service/` が7件対356件に分かれていた事故を
  受けての注記用。自動マージはしない判断の理由は同関数のdocstring参照）
- parse_site_segments_json: 01の site-segments.yaml 由来のJSON文字列をパースする。
  未指定・不正なJSONでも例外を出さず空リストにする（site_segments未設定と同じ扱い）
"""

from __future__ import annotations

import calendar
import json
import re
from collections import defaultdict
from datetime import date, timedelta


def delta_pct(curr: float, prev: float) -> str:
    """前期比（相対変化率）を "+12.3%" 形式の文字列で返す。比較対象が0/無しなら "-"。

    セッション・ユーザー・CVなど「実数」の指標専用。割合のような
    「率」の指標にはこの関数を使わない（率どうしの比較には delta_pt を使う。
    率に相対変化率を使うと、実際のポイント差より過大/過小な数字に見えてしまう）。
    """
    if not prev:
        return "-"
    diff = (curr - prev) / prev * 100
    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff:.1f}%"


def delta_pt(curr: float, prev: float) -> str:
    """率どうしの差分を "+1.5pt" 形式のポイント表記で返す。

    curr・prev は分率（0〜1、例: 0.738）を想定し、100倍したうえでの差分（ポイント）を返す。
    CVRなど「率」の指標の前期比較専用。セッション・ユーザー・CVなど
    「実数」の指標の相対変化率には delta_pct を使う（率と実数で計算方法が異なることを
    関数名で明示し、呼び出し側で取り違えないようにする）。
    """
    diff = (curr - prev) * 100
    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff:.1f}pt"


def compute_funnel(steps: list[dict]) -> list[dict]:
    """CVファネルの各ステップに到達率・到達後の転換率を付与する。

    steps: [{"label": str, "sessions": int}, ...]（先頭 = 流入の基準ステップ）
    戻り値: 各要素に以下を追加したリスト
      - step_rate: 直前のステップに対する到達率（%, float）。先頭要素は None
      - overall_rate: 先頭ステップ（流入全体）に対する到達率（%, float）
      - note: 異常値をクランプした場合の注記（無ければ None）

    GA4 Data API は少量データに丸め処理（しきい値処理）をかけることがあり、
    後段のステップのセッション数が前段を上回る場合がまれにある
    （例: 中間ページ到達セッション数 > 全体セッション数）。
    この場合は到達率を100%にクランプし、note に理由を残す（黙って矛盾した数値を出さない）。
    """
    if not steps:
        return []

    base_sessions = steps[0].get("sessions", 0) or 0
    out: list[dict] = []
    prev_sessions: int | None = None

    for i, step in enumerate(steps):
        sessions = step.get("sessions", 0) or 0
        note = None

        if i == 0:
            step_rate = None
            overall_rate = 100.0 if base_sessions else 0.0
        else:
            if prev_sessions:
                raw_step_rate = sessions / prev_sessions * 100
            else:
                raw_step_rate = 0.0
            if raw_step_rate > 100:
                step_rate = 100.0
                note = (
                    "GA4の集計上の丸め処理により前段のステップを上回る値が出たため"
                    "100%として表示（実際の到達率はこれよりやや低い可能性がある）"
                )
            else:
                step_rate = raw_step_rate

            raw_overall_rate = (sessions / base_sessions * 100) if base_sessions else 0.0
            overall_rate = min(raw_overall_rate, 100.0)
            if raw_overall_rate > 100 and note is None:
                note = (
                    "GA4の集計上の丸め処理により流入全体を上回る値が出たため"
                    "100%として表示（実際の到達率はこれよりやや低い可能性がある）"
                )

        out.append({**step, "step_rate": step_rate, "overall_rate": overall_rate, "note": note})
        prev_sessions = sessions

    return out


def select_funnels(
    key_event_counts: dict[str, int],
    max_funnels: int = 5,
    primary_events: set[str] | None = None,
) -> tuple[list[str], list[tuple[str, int]]]:
    """CVファネルを作る本数を、CV件数が多い順に上限までに絞る。

    キーイベント1件=中間ページ1件の対で1本のファネルを作る設計（分子と分母を対応させるため、
    全キーイベントのORで1本にまとめる旧設計は廃止）。ファネルを無制限に作ると本文が
    肥大化するため、CV件数が多い順に max_funnels 本まで採用し、外した分は黙って消さずに
    件数付きで記録する。

    key_event_counts: {キーイベント名: CV件数}。同数のキーイベントが複数あった場合の
    タイブレークは辞書の並び順（呼び出し側でキーイベントの指定順に辞書を作ること）。

    primary_events: 01の kpis.yaml で優先度1と判定されたKPIに属するイベント名の集合。
    指定された場合、CV件数の順位に関わらずこれらのイベントを先頭に並べる（「主KPIを
    主として扱う」の実装。CV件数が少なくても上限cutoffで黙って外れないようにする）。
    未指定（None）なら従来どおりCV件数の降順のみで決める。
    戻り値: (選ばれたキーイベント名のリスト（先頭は primary_events、以降CV件数降順）,
             外したキーイベントと件数のペアのリスト)
    """
    ordered = sorted(key_event_counts.items(), key=lambda kv: kv[1], reverse=True)
    if primary_events:
        primary = [kv for kv in ordered if kv[0] in primary_events]
        rest = [kv for kv in ordered if kv[0] not in primary_events]
        ordered = primary + rest
    selected = [name for name, _ in ordered[:max_funnels]]
    excluded = ordered[max_funnels:]
    return selected, excluded


def parse_event_names_json(raw: str | None) -> dict[str, str]:
    """`--event-names-json` の値をパースする。

    01の kpis.yaml（kpis[].name / kpis[].events）から作った {event_name: KPI名} の
    JSON文字列を受け取る想定。未指定・空文字・不正なJSON・オブジェクト以外・値が空の
    エントリは、レポート生成を止めずに無視する（未登録なら黙ってイベント名にフォールバック
    させるための設計。ここで例外を出すと、名前対応表が無いだけで基本分析が丸ごと止まる）。
    """
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v}


def format_funnel_title(event: str, event_names: dict[str, str] | None = None) -> str:
    """CVファネル見出し（`### ...`）用の表示名を組み立てる。

    01の kpis.yaml に業務名（kpis[].name）が登録されているイベントは
    「{name}（{event}）」、未登録のイベント（09未登録のクライアント／01に無いイベントを含む）
    は event 名のみを返す（フォールバック。計測の技術名としてのイベント名は必ず残す）。
    """
    name = (event_names or {}).get(event)
    return f"{name}（{event}）" if name else event


def _group_key_events(
    key_events: list[str], event_names: dict[str, str] | None = None
) -> list[tuple[str | None, list[str]]]:
    """key_events を業務名（01の kpis.yaml 由来）が同じイベントごとにグループ化する。

    1つのKPIが複数イベントを持つ場合（kpis.yaml の events が配列）は同じグループにまとめる。
    名前が無いイベントは他のイベントとまとめず、1件ずつ単独グループ（name=None）にする
    （名前が分からないイベント同士を、同じ意味であるかのように見せないため）。
    戻り値の順序は key_events の登場順（グループの代表位置は、そのグループの最初のイベントの位置）。

    format_key_events_header() と kpi_labels_and_events() の共通ロジック
    （表示用の文字列を作るか、KPI別集計の下ごしらえに使うかが違うだけで、グループ分けの
    考え方は同じにする必要があるため、ここに1本化する）。
    """
    entries: list[tuple[str | None, list[str]]] = []
    name_index: dict[str, int] = {}
    for e in key_events:
        name = (event_names or {}).get(e) or None
        if name is not None and name in name_index:
            entries[name_index[name]][1].append(e)
            continue
        if name is not None:
            name_index[name] = len(entries)
        entries.append((name, [e]))
    return entries


def format_key_events_header(key_events: list[str], event_names: dict[str, str] | None = None) -> str:
    """レポートヘッダーの「キーイベント」表示用の文字列を組み立てる。

    イベントコード（バッククォート付き）を主表記にし、01の kpis.yaml に業務名が
    登録されていれば「（名前）」を添える（例: "`form_submit`（お問い合わせ完了数）"）。
    1つのKPIが複数イベントを持つ場合（kpis.yaml の events が配列）は、そのイベントを
    まとめて1つの名前表記にする（例: "`generate_lead`、`form_submit`（お問い合わせ完了数）"）。
    名前が無いイベントは event 名のみ（フォールバック）で、他のイベントとまとめない
    （名前が分からないイベント同士を、同じ意味であるかのように見せないため）。
    key_events が空、event_names が未指定/空でもエラーにしない。
    """
    if not key_events:
        return "(なし)"
    parts = []
    for name, events in _group_key_events(key_events, event_names):
        code = "、".join(f"`{ev}`" for ev in events)
        parts.append(f"{code}（{name}）" if name else code)
    return "、".join(parts)


def kpi_labels_and_events(
    key_events: list[str], event_names: dict[str, str] | None = None
) -> list[tuple[str, list[str]]]:
    """key_events を、CVを分けて表示する際の「KPI単位」にグループ化する。

    _group_key_events() と同じグループ分けを使い、表示ラベルを1本の文字列に確定させる
    （業務名があればその名前、無ければ先頭イベント名をそのまま使う＝フォールバック）。
    複数KPIをテーブルへ内訳表示する全セクション（サマリー・推移・チャネル別等）の
    共通の下ごしらえとして使う。
    """
    return [
        (name if name else events[0], events)
        for name, events in _group_key_events(key_events, event_names)
    ]


def apply_primary_name_fallback(
    key_events: list[str], event_names: dict[str, str], primary_name: str | None,
) -> dict[str, str]:
    """単一CVに業務名が無い場合だけ、主KPI名を表示名として補う。

    複数イベントではどのイベントに対応する名前か断定できないため補完しない。
    """
    result = dict(event_names)
    if primary_name and len(key_events) == 1 and not result.get(key_events[0]):
        result[key_events[0]] = primary_name
    return result


def kpi_group_rows(
    key_events: list[str],
    counts_current: dict[str, int],
    counts_previous: dict[str, int] | None = None,
    event_names: dict[str, str] | None = None,
    primary_name: str | None = None,
    sessions_current: dict[str, int] | None = None,
    sessions_previous: dict[str, int] | None = None,
) -> list[dict]:
    """key_events をKPI単位にグループ化し、グループごとのCV件数（当期・前期）をまとめる。

    複数のCV（キーイベント）を持つクライアントで、合算のCV列だけを出すと「どのCVが
    増減したか」が読めない不具合の修正に使う（相談件数と資料ダウンロード件数を合算すると、
    どちらの施策を打つべきか決められないという実例を踏まえた設計）。

    counts_current/counts_previous: {event_name: 件数}（fetch_key_event_counts() 等、
    eventName別に絞り込んだ取得結果を想定。GA4標準の「conversions」指標をディメンション無しで
    そのまま使うと、--key-events で指定していない他のキーイベントまで合算されてしまうため、
    必ずeventNameで絞り込んだ集計を渡すこと）。

    primary_name: 01の kpis.yaml で優先度1（`ClientContext.primary_kpi`）と判定されたKPIの
    表示名。指定され、いずれかのグループの表示名と一致すれば、そのグループを先頭に並べ替え、
    "is_primary": True を付ける（「主KPIを主として扱う」の実装。読み手がまず見るべき数字を
    先頭に出す）。一致するグループが無い場合（primary_nameが空/None、またはそのKPIの
    イベントがkey_eventsに含まれていない）は並び順・印付けを変えない
    （＝09で優先度が未設定、または1件しかないKPIの場合に相当。「先頭グループで代用してよい」
    という意味にはしないため、一致しない限りマークしない）。

    戻り値の各要素: {"label", "events", "current", "previous", "is_primary"}
    （counts_previous を渡さない場合は "previous" が None のまま。呼び出し側が前期比の
    有無を判定できるようにする）。
    """
    groups = kpi_labels_and_events(key_events, event_names)
    if primary_name:
        primary = [g for g in groups if g[0] == primary_name]
        if primary:
            rest = [g for g in groups if g[0] != primary_name]
            groups = primary + rest
    out = []
    for label, events in groups:
        current = sum(counts_current.get(e, 0) for e in events)
        previous = (
            sum(counts_previous.get(e, 0) for e in events) if counts_previous is not None else None
        )
        converted_sessions = (
            sum((sessions_current or {}).get(e, 0) for e in events)
            if sessions_current is not None else None
        )
        previous_converted_sessions = (
            sum((sessions_previous or {}).get(e, 0) for e in events)
            if sessions_previous is not None else None
        )
        out.append(
            {
                "label": label,
                "events": events,
                "current": current,
                "previous": previous,
                "is_primary": bool(primary_name) and label == primary_name,
                "converted_sessions": converted_sessions,
                "previous_converted_sessions": previous_converted_sessions,
            }
        )
    return out


def kpi_display_label(row: dict) -> str:
    """kpi_group_rows() の1要素から、表示用ラベルを組み立てる（主KPIには★を付ける）。"""
    return f"★{row['label']}" if row.get("is_primary") else row["label"]


def kpi_column_headers(labels: list[str]) -> list[str]:
    """チャネル別・ランディングページ別等の表で、KPIごとに「CV数: X」「CVR: X」の
    列見出しペアを組み立てる（複数CVを合算せず、内訳の列として並べて表示するため）。

    基本分析のCV数は、ユーザー確認済みのCVイベントの発生回数を使う。CVRも同じ
    イベント発生回数をセッション数で割る。1セッションで同じCVイベントが複数回発火する
    場合は100%を超え得るため、「CVしたセッション割合」と混同しない。
    """
    cells: list[str] = []
    for label in labels:
        cells.append(f"CV数: {label}")
        cells.append(f"CVR: {label}")
    return cells


def kpi_column_cells(kpi_breakdown: list[dict], sessions: int) -> list[str]:
    """kpi_group_rows() の戻り値と、その行のセッション数から、KPIごとの
    「CVイベント数」「CVR」セルを組み立てる（kpi_column_headers() と対になる列の並び）。
    セッションが0ならCVRは0.00%にする（ゼロ除算を避ける。分子のCVが無いのでこの値は
    見た目上も問題にならない）。
    """
    cells: list[str] = []
    for kr in kpi_breakdown:
        event_count = kr["current"]
        cvr = event_count / sessions * 100 if sessions else 0.0
        cells.append(f"{event_count:,}")
        cells.append(f"{cvr:.2f}%")
    return cells


def attach_kpi_breakdown(
    rows: list[dict],
    dim_keys: str | tuple[str, ...],
    breakdown_rows: list[dict],
    key_events: list[str],
    event_names: dict[str, str] | None = None,
    primary_name: str | None = None,
) -> list[dict]:
    """チャネル別・ランディングページ別などの既存の集計行に、KPIごとのCV内訳を付与する。

    breakdown_rows: dim_keys（1つ以上のディメンション）× eventName のクロス集計行
    （fetch_ga4_analytics.fetch_conversions_by_event() の戻り値。GA4標準の「conversions」を
    そのまま使わず、必ずeventNameでkey_eventsに絞り込んだ集計にする＝合算に他のキーイベントが
    混入しない）。

    dim_keys が複数（tuple）の場合は、そのディメンションの組み合わせをキーにして突き合わせる
    （例: sessionSource と sessionMedium の組み合わせ）。rows・breakdown_rows の両方に
    同じキー（GA4のディメンション名）でフィールドが入っている前提。

    該当する行が breakdown_rows に無い組み合わせ（＝そのディメンション値でキーイベントが
    1件も発火していない）でも、各KPIグループを0件として付与する（黙って欄を空けない）。
    各行に "kpi_breakdown"（kpi_group_rows() と同じ形のリスト、previousは常にNone）を追加する。
    """
    keys = dim_keys if isinstance(dim_keys, tuple) else (dim_keys,)

    def _row_key(r: dict) -> tuple:
        return tuple(r.get(k) for k in keys)

    count_by_key: dict[tuple, dict[str, int]] = defaultdict(dict)
    for r in breakdown_rows:
        count_by_key[_row_key(r)][r["eventName"]] = r.get("conversions", 0)

    out = []
    for r in rows:
        counts = count_by_key.get(_row_key(r), {})
        r2 = dict(r)
        r2["kpi_breakdown"] = kpi_group_rows(
            key_events, counts, None, event_names, primary_name,
        )
        out.append(r2)
    return out


def _normalize_page_path(page: str) -> str:
    """`?submissionGuid=...` のようなクエリ文字列違いを同一ページとして扱うため、
    パス部分だけを取り出す。"""
    return page.split("?", 1)[0]


def _path_tokens(page: str) -> list[str]:
    """パスを `/`・`_`・`-` で分割したトークン列にする（空トークンは除く）。"""
    path = _normalize_page_path(page).strip("/")
    return [t for t in re.split(r"[/_\-]+", path.lower()) if t]


def is_event_self_page(event_name: str, page: str) -> bool:
    """このページが「そのキーイベント自身が発火したページ（＝サンクスページ等）」らしいかを、
    イベント名とページパスの命名対応から推定する。

    実データで、CVファネルの中間ページ候補にキーイベント自身の完了ページ（サンクスページ）
    が1位で出てくる不具合があった。原因は、このサイトのキーイベントが「サンクスページの
    page_view」として発火する設計になっているため（GA4で最もありふれた計測方式で、他社でも
    同様に起こりうる）。GA4 Data API はイベント名でフィルタした pagePathPlusQueryString を
    「そのイベント自身が発火した時のページ」として返すため、この形の計測では集計が常に
    サンクスページ自身を1位で返してしまう。

    サンクスページ型のキーイベントは、イベント名がそのページのパスに由来する命名になって
    いることが多い（例: contact_service_thanks ↔ /contact/service/thanks/、
    download_thanks ↔ /download/thanks/）。イベント名をアンダースコア/ハイフンで区切った
    トークン列が、ページパスの末尾トークン列とそのまま一致するかで判定する。

    ボタンクリック等でイベントが発火する型（発火ページ＝入力前ページ＝正解）は、イベント名が
    アクション名（例: form_submit, cta_click）であることが多く、発火ページのパスのトークンとは
    一致しないため、この判定には引っかからない＝除外されない。

    既知の限界: イベント名がページパスに由来しない命名のサンクスページ型（例:
    キーイベント名が `conversion_1` のような連番）は、この判定では検出できない。
    その場合は除外されずに残るため、候補一覧を目視で確認する運用は引き続き必要。
    """
    ev_tokens = [t for t in re.split(r"[_\-]+", event_name.lower()) if t]
    if not ev_tokens:
        return False
    p_tokens = _path_tokens(page)
    if len(p_tokens) < len(ev_tokens):
        return False
    return p_tokens[-len(ev_tokens):] == ev_tokens


def rank_page_candidates(
    rows: list[dict],
    sessions_key: str = "sessions",
    page_key: str = "pagePathPlusQueryString",
    limit: int = 10,
    event_name: str | None = None,
) -> list[dict]:
    """CVファネルの中間ページ候補を、セッション数（そのキーイベントとの共起）の多い順に並べる。

    GA4 Data API 側でも order_by を指定して取得するが、並べ替え自体をここに切り出すことで
    GA4クライアントをモックせずに順位付けを検証できるようにする。

    event_name を渡すと、各行に is_event_self_page() の判定結果を "excluded_self" として
    付与する。除外扱いの行は黙って消さず、非除外の行より後ろに回した上でそのまま返す
    （除外行しか無ければ、そのまま表示されて「候補が見つからなかった」と分かる）。
    event_name を渡さない場合は excluded_self を付与せず、従来通りセッション数の
    多い順に並べるだけ（後方互換）。
    """
    if event_name is None:
        return sorted(rows, key=lambda r: r.get(sessions_key, 0), reverse=True)[:limit]

    annotated = []
    for r in rows:
        r2 = dict(r)
        r2["excluded_self"] = is_event_self_page(event_name, r.get(page_key, ""))
        annotated.append(r2)
    annotated.sort(key=lambda r: (r["excluded_self"], -r.get(sessions_key, 0)))
    return annotated[:limit]


def _parent_paths(path: str) -> list[str]:
    """パスを1階層ずつ遡った親パスの列を返す（自分自身は含まない）。

    例: /contact/service/thanks/ -> ['/contact/service/', '/contact/', '/']
    """
    segments = [s for s in _normalize_page_path(path).strip("/").split("/") if s]
    out = []
    for i in range(len(segments) - 1, 0, -1):
        out.append("/" + "/".join(segments[:i]) + "/")
    out.append("/")
    return out


def with_parent_path_guess(
    candidates: list[dict],
    page_rows: list[dict],
    page_key: str = "pagePathPlusQueryString",
    lookup_path_key: str = "landingPagePlusQueryString",
    sessions_key: str = "sessions",
    conversions_key: str = "conversions",
) -> list[dict]:
    """候補が全て「イベント自身の発火ページ」（excluded_self）だった場合に、完了ページの
    親パスを既に取得済みのページ一覧（page_rows。ランディングページ別など）と照合し、
    実在する親パスを「推定候補」として先頭に追加する。

    実データで、contact_service_thanks / download_thanks の候補が全て完了ページ自身の
    クエリ文字列違いだけになり、GA4のイベント別集計（pagePathPlusQueryStringをeventNameで
    フィルタする方式）だけでは入力前ページを検出できないケースがあった。GA4はディメンション
    と指標をイベント行で結合するため、eventNameで絞ると「そのイベントが起きた行のページ」
    しか返らない構造上の限界で、is_event_self_page()の判定を直しても、このデータからは
    入力前ページが浮上しない（詳しくは standards/ga4-event-scoped-dimensions.md）。

    そこで、完了ページのパス（例: /contact/service/thanks/）から親パス（/contact/service/、
    /contact/、/ の順）を1階層ずつ遡り、既に取得済みのページ一覧（例: fetch_landing_pages()。
    GA4への新規クエリを増やさない）に実在する最初の親パスを候補にする。サンクスページの
    URLから入力前ページを推測するのは、人がサイト構造を見て行う推測と同じ発想。

    推測であることが分かるよう "estimated_from_parent": True を付ける（黙って確定させない。
    実際にサイトを見て確認する運用はそのまま引き継ぐ）。ページ一覧に実在する親パスが
    無ければ何も追加せず、元のリストをそのまま返す（中間ページ無し・2段構成へのフォール
    バックは既存の挙動を維持する）。

    candidates が空、またはexcluded_selfでない候補（＝正規の候補データ）が既に1件でも
    あれば何もしない（正規の候補がある場合は推測を出さない。クリック発火型はここで
    素通りする）。
    """
    if not candidates or not all(c.get("excluded_self") for c in candidates):
        return candidates

    self_path = _normalize_page_path(candidates[0].get(page_key, ""))
    lookup: dict[str, dict] = {}
    for r in page_rows:
        p = _normalize_page_path(r.get(lookup_path_key, ""))
        if not p:
            continue
        agg = lookup.setdefault(p, {"sessions": 0, "conversions": 0})
        agg["sessions"] += r.get(sessions_key, 0)
        agg["conversions"] += r.get(conversions_key, 0)

    for ancestor in _parent_paths(self_path):
        hit = lookup.get(ancestor)
        if hit and hit["sessions"] > 0:
            guess = {
                page_key: ancestor,
                sessions_key: hit["sessions"],
                "conversions": hit["conversions"],
                "excluded_self": False,
                "estimated_from_parent": True,
            }
            return [guess] + candidates
    return candidates


def unclassified_diff(overall_sessions: int, rows: list[dict], sessions_key: str = "sessions") -> int:
    """内訳（デバイス別・新規/リピーター別など）の合計が全体セッションに届かない差分を返す。

    実データで、デバイス別（mobile/desktop/tabletの3カテゴリ）の合計がセッション全体と
    4,009件（1.2%）ずれる不具合があった。GA4がこの3カテゴリに分類できないセッションが
    集計から漏れるため。内訳の合計だけを分母にシェアを計算すると、漏れた分だけ
    シェアが実態より高く出てしまう。全体セッションを分母に固定した上で、この関数の
    戻り値を「(不明・分類外)」のような差分行として明示すれば、読み手が分母の違いに気づける。

    合計が全体を超えている場合（サンプリング等による誤差）は0を返す（負の行を作らない）。
    """
    subtotal = sum(r.get(sessions_key, 0) for r in rows)
    diff = overall_sessions - subtotal
    return diff if diff > 0 else 0


def reconciliation_diff(reference_total: int, rows: list[dict], sessions_key: str = "sessions") -> int:
    """絞り込み条件付きの取得（フィルタ・クロス集計）の内訳合計と、参照値との差を符号付きで返す。

    unclassified_diff() は「分類できないセッションが内訳から漏れる」（合計が全体に届かない）
    ケース専用に、負の値を0にクランプしている。絞り込み・クロス集計を伴う取得ではこれと逆方向
    ――内訳合計が参照値を上回る――ことも起きる。07の実測で、着地ページや期間でデバイス別を
    絞り込んだ取得・ホスト名別・月×チャネル/月×国のクロス集計など、複数の「絞り込んだ取得」で
    合計と参照値のズレ（+376〜+6,645件、-1,312件）が確認され、そのズレが出力のどこにも
    現れていなかった（引き算・比率計算に使うと分母が混ざり、増減分に占める割合の合計が
    102.4%になるなど矛盾した数字が生まれた）。

    この関数はズレを黙って消さず、reference_total - subtotal をそのまま返す
    （正なら内訳が参照値に届いていない、負なら内訳が参照値を上回っている）。
    """
    subtotal = sum(r.get(sessions_key, 0) for r in rows)
    return reference_total - subtotal


def format_reconciliation_note(
    reference_total: int,
    rows: list[dict],
    sessions_key: str = "sessions",
    reference_label: str = "参照値（絞り込み無しの全体）",
    subtotal_label: str = "内訳合計",
) -> str | None:
    """reconciliation_diff() の結果を、レポートにそのまま出せる注記文（先頭に「※ 」付き）に
    整形する。差が0ならNoneを返す（注記を出さない）。

    呼び出し側は、絞り込み条件付きの取得の合計を他の値と比較・引き算・比率計算に使う前に
    必ずこの関数（またはreconciliation_diff）で参照値との整合を確認し、diffが0でなければ
    注記として出力に残す（「取得の切り口が違うと合計が合わない」ことを出力から読み取れる
    形にする）。
    """
    subtotal = sum(r.get(sessions_key, 0) for r in rows)
    diff = reference_total - subtotal
    if diff == 0:
        return None
    if diff > 0:
        return (
            f"※ {subtotal_label}（{subtotal:,}）が{reference_label}（{reference_total:,}）に"
            f"{diff:,}件届いていない（取得の切り口が違うため合計が一致しない。この絞り込みでは"
            "捕捉できていないセッションがある可能性がある）。"
        )
    excess = -diff
    return (
        f"※ {subtotal_label}（{subtotal:,}）が{reference_label}（{reference_total:,}）を"
        f"{excess:,}件上回っている（取得の切り口が違うため合計が一致しない。同じセッションが"
        "複数の内訳行に重複して数えられている可能性がある）。"
    )


def rank_with_gap(
    rows: list[dict],
    count_key: str,
    cv_key: str,
    label_key: str,
) -> list[dict]:
    """セッション数ランキングとCV数ランキングを両方作り、順位差（量と質のズレ）を付与する。

    rank_gap = session_rank - cv_rank。
    正の値が大きいほど「セッション順位のわりにCV順位が高い」（質が良い・見落とされがちな流入）。
    負の値が大きいほど「セッションは多いのにCVが伸びていない」（量はあるが転換しない流入）。
    """
    if not rows:
        return []

    by_sessions = sorted(rows, key=lambda r: r.get(count_key, 0), reverse=True)
    by_cv = sorted(rows, key=lambda r: r.get(cv_key, 0), reverse=True)

    session_rank = {r[label_key]: i + 1 for i, r in enumerate(by_sessions)}
    cv_rank = {r[label_key]: i + 1 for i, r in enumerate(by_cv)}

    out = []
    for r in rows:
        label = r[label_key]
        out.append(
            {
                **r,
                "session_rank": session_rank[label],
                "cv_rank": cv_rank[label],
                "rank_gap": session_rank[label] - cv_rank[label],
            }
        )
    return out


def attach_entrance_rate(
    pages: list[dict],
    landing_pages: list[dict],
    page_key: str = "pagePathPlusQueryString",
    views_key: str = "screenPageViews",
    landing_key: str = "landingPagePlusQueryString",
    landing_sessions_key: str = "sessions",
) -> list[dict]:
    """ページ別データに、着地（エントランス相当）セッション数と閲覧開始率を付与する。

    閲覧開始率 = そのページが着地ページだったセッション数 ÷ そのページの総PV数。
    GA4 Data API には UA の「エントランス」「離脱率」に相当する指標が無いため、
    エントランス数は landingPagePlusQueryString 別セッション数（セッション単位で正確に
    取得できる、GA4の正式な session-scoped ディメンション）から算出する。
    離脱率に相当する指標は算出しない（セッション内の最終ページを表すディメンションが
    GA4標準APIに存在しないため。正確な値が必要な場合はBigQueryのGA4エクスポート生データが必要）。
    """
    # GA4の landingPage と pagePath は、同じ実URLでも末尾スラッシュの有無が異なる形で
    # 返ることがある。完全一致を優先し、該当が無い場合だけクエリ文字列と末尾スラッシュを
    # 除いたキーで照合する。完全一致の行があるときまで正規化合算すると、実際に別URLとして
    # 計測されている行を二重に割り当てるため、フォールバックに限定する。
    def join_key(value: str) -> str:
        path = _normalize_page_path(value)
        return path if path == "/" else path.rstrip("/")

    landing_sessions: dict[str, int] = defaultdict(int)
    normalized_sessions: dict[str, int] = defaultdict(int)
    for lp in landing_pages:
        landing_path = lp[landing_key]
        sessions = lp[landing_sessions_key]
        landing_sessions[landing_path] += sessions
        normalized_sessions[join_key(landing_path)] += sessions
    out = []
    for p in pages:
        path = p[page_key]
        entrances = (
            landing_sessions[path]
            if path in landing_sessions
            else normalized_sessions.get(join_key(path), 0)
        )
        views = p.get(views_key, 0)
        entrance_rate = (entrances / views * 100) if views else 0.0
        out.append({**p, "entrances": entrances, "entrance_rate": entrance_rate})
    return out


def _ga4_week_bounds(year: int, week: int) -> tuple[date, date]:
    """GA4のyearWeekディメンションにおける、その週の開始日・終了日を求める。

    GA4の「週」は ISO 8601 とは異なる独自定義（公式ドキュメント準拠）:
    - 週は日曜始まり
    - 1月1日は常に第1週に含まれる（1/1が日曜でなければ、第1週は7日未満の部分週になる）
    - 第1週・最終週以外は必ず7日間
    - 最終週も年末（12/31）で打ち切られるため、7日未満になることがある
    """
    jan1 = date(year, 1, 1)
    # Python の date.weekday() は 月=0…日=6。1/1から直後の日曜日までの日数を求める。
    days_to_first_sunday = (6 - jan1.weekday()) % 7
    first_sunday = jan1 + timedelta(days=days_to_first_sunday)
    if week == 1:
        # 1/1が日曜なら第1週はまるまる7日、そうでなければ次の日曜日の前日までの部分週
        end = jan1 + timedelta(days=6) if days_to_first_sunday == 0 else first_sunday - timedelta(days=1)
        start = jan1
    else:
        start = first_sunday + timedelta(days=(week - 2) * 7)
        end = start + timedelta(days=6)
    dec31 = date(year, 12, 31)
    if end > dec31:
        end = dec31
    return start, end


def format_week_range(year_week: str) -> str:
    """GA4のyearWeek（"YYYYWW"形式、例: "202632"）を「YYYY/MM/DD〜MM/DD」の日付レンジに変換する。

    週の開始・終了は必ず同一年内に収まる（GA4が年末で週を打ち切るため）ので、
    終了日側は月日のみを表示する。
    """
    year = int(year_week[:4])
    week = int(year_week[4:])
    start, end = _ga4_week_bounds(year, week)
    return f"{start.year}/{start.month:02d}/{start.day:02d}〜{end.month:02d}/{end.day:02d}"


def mark_incomplete_months(
    rows: list[dict],
    dim_key: str,
    period_start: date,
    period_end: date,
) -> list[dict]:
    """月次行（yearMonth別）に、取得期間の端で不完全な月かどうかの目印を付与する。

    yearMonth は暦月で集計されるため、取得期間の開始・終了が月の途中にかかっている場合、
    その月は暦月の一部しか含まない。最初の行が period_start の月と一致し、かつ
    period_start が月初(1日)でない場合、最後の行が period_end の月と一致し、かつ
    period_end がその月の末日でない場合に「不完全（incomplete）」とマークする。
    """
    if not rows:
        return []
    first_month = f"{period_start.year:04d}{period_start.month:02d}"
    last_month = f"{period_end.year:04d}{period_end.month:02d}"
    start_incomplete = period_start.day != 1
    last_day_of_end_month = calendar.monthrange(period_end.year, period_end.month)[1]
    end_incomplete = period_end.day != last_day_of_end_month

    out = []
    for r in rows:
        value = r[dim_key]
        incomplete = (value == first_month and start_incomplete) or (
            value == last_month and end_incomplete
        )
        out.append({**r, "incomplete": incomplete})
    return out


# ---------------------------------------------------------------------------
# サイトセグメント（分析対象の定義。01の site-segments.yaml 由来）
# ---------------------------------------------------------------------------

def _as_list(value) -> list:
    """値をリストとして返す（単一値なら1要素リスト、None/空なら空リスト）。

    01_context_management/src/context_store/schema.py の同名関数と同じ挙動。
    02は01に依存しない設計のため、判定ロジックをここに複製している
    （09側の schema.py を変更したら、こちらの match_site_segment() も合わせること）。
    """
    if not value:
        return []
    return value if isinstance(value, list) else [value]


def parse_site_segments_json(raw: str | None) -> list[dict]:
    """`--site-segments-json` の値をパースする。

    01の `site-segments.yaml` の `site_segments` リストをJSON文字列で受け取る想定。
    未指定・空文字・不正なJSON・リスト以外は、レポート生成を止めずに空リストを返す
    （site_segments が未設定のクライアントと同じ挙動＝呼び出し側はサイト全体を分母にする）。
    """
    if not raw or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [s for s in data if isinstance(s, dict)]


def match_site_segment(
    segments: list,
    host_name: str | None = None,
    page_path: str | None = None,
    content_group: str | None = None,
) -> str | None:
    """1ページを site_segments に照らして分類し、一致した segment_id を返す。

    01_context_management/src/context_store/schema.py の match_site_segment() と
    完全に同じアルゴリズム（02は01に依存しない設計のため、ここに複製している。
    片方だけ直すと2つが違う結果を返す事故につながるため、両者が同じ入力に同じ結果を
    返すことを tests/test_analysis_calc.py の MatchSiteSegmentParityWithSchemaTest で
    固定している。09側を直したときはこちらも必ず追随させること）:
    - `match.host_name` / `match.path_prefix` / `match.content_group` は省略可、
      スカラーでもリストでもよい（`_as_list` で正規化）
    - 1セグメント内で複数キーを指定した場合はAND（すべて満たす）、各キー内はOR
      （いずれかに一致すればよい）
    - host_name は大文字小文字を無視して比較する。path_prefix・content_group は
      大文字小文字を区別する
    - 定義順に見て最初に一致したセグメントを返す（先勝ち）
    - どのキーも指定されていない（条件が空の）セグメントは絶対に一致しない
      （空条件を「すべてに一致」として扱うと「その他」に何も残らなくなるため、安全側に倒す）。
      ただし `default: true` を持つセグメント（既定セグメント）はこのチェックの対象外（下記）
    - **`default: true` を持つセグメントは match を評価しない。** 他のどのセグメントにも
      一致しなかったページは、既定セグメントがあればそこに落ちる（定義順で最初に見つかった
      `default: true` を採用）
    - **`default: true` が1件も無い場合に限り、どれにも一致しなければ None を返す。**
      これが「その他」バケツ。呼び出し側は None を無視して合計から除外してはならない
      （除外すると『独立した切り口の合計が全体と合わない』事故が再発する。None の件数を
      集計し「その他」として必ず表示すること）
    """
    host_name = str(host_name or "").strip()
    page_path = str(page_path or "").strip()
    content_group = str(content_group or "").strip()
    default_segment_id: str | None = None
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        if seg.get("default") is True:
            if default_segment_id is None:
                default_segment_id = seg.get("segment_id")
            continue  # 既定セグメントは match を見ない（後段のフォールバックとしてのみ使う）
        match = seg.get("match")
        if not isinstance(match, dict):
            continue
        hosts = [str(h).strip() for h in _as_list(match.get("host_name")) if str(h).strip()]
        prefixes = [str(p).strip() for p in _as_list(match.get("path_prefix")) if str(p).strip()]
        groups = [str(g).strip() for g in _as_list(match.get("content_group")) if str(g).strip()]
        if not hosts and not prefixes and not groups:
            continue  # 条件が空のセグメントは何にも一致しない
        host_ok = (not hosts) or (host_name.lower() in [h.lower() for h in hosts])
        prefix_ok = (not prefixes) or any(page_path.startswith(p) for p in prefixes)
        group_ok = (not groups) or (content_group in groups)
        if host_ok and prefix_ok and group_ok:
            return seg.get("segment_id")
    return default_segment_id


def landing_page_dimension(include_query_params: bool) -> str:
    """ランディングページ集計に使うGA4ディメンション名を返す。

    既定（include_query_params=False）はクエリ文字列を含まない `landingPage`。
    実データで `/?renew=` のようなクエリ付き別名が別ページとして計上されたり、
    CVファネルの中間ページ候補が完了ページのクエリ違い（`?submissionGuid=...`）で
    埋まったりする不具合があったため、既定でクエリを落とす
    （01の `ClientContext.include_query_params` の既定値と揃える）。
    """
    return "landingPagePlusQueryString" if include_query_params else "landingPage"


def page_path_dimension(include_query_params: bool) -> str:
    """ページ別集計に使うGA4ディメンション名を返す（考え方は landing_page_dimension と同じ）。"""
    return "pagePathPlusQueryString" if include_query_params else "pagePath"


def detect_trailing_slash_dupes(rows: list[dict], key: str) -> list[tuple[str, str]]:
    """末尾スラッシュ違いで別行になっているパスの組を検出する（自動マージはしない）。

    実データで `/contact/service` と `/contact/service/` が別集計になり、セッション数が
    7件 対 356件に分かれていた事故があった。クエリ文字列の除去（既定でクエリを落とす）
    と違い、末尾スラッシュの有無はサーバー側のリダイレクト・正規化設定次第で本当に別の
    ページを指すこともあり、02側で安全に同一ページと断定できない。そのためこの関数は
    自動マージせず、該当ペアを検出してレポートに注記するためだけに使う
    （黙って気づかせないままにしない。マージするかどうかはサイト側の設定を確認したうえで
    利用者が判断する）。

    戻り値: [(スラッシュ無し, スラッシュ有り), ...]（両方が rows に存在するペアのみ、
    スラッシュ無し側の文字列順）。
    """
    values = {str(r.get(key, "")) for r in rows}
    pairs = [
        (v, v + "/")
        for v in values
        if v and not v.endswith("/") and (v + "/") in values
    ]
    return sorted(pairs)


def classify_segment_rows(
    rows: list[dict],
    segments: list,
    path_key: str,
    host_key: str | None = None,
    content_group_key: str | None = None,
    sessions_key: str = "sessions",
    conversions_key: str = "conversions",
) -> dict:
    """ページ単位の行を site_segments に照らして、セグメントごとのセッション・CVを
    集計する（サマリーに並べる「セグメント別の内訳」向け）。

    どのセグメントを分母にするか（CVを狙っているとみなすか）は02側では決めない
    ＝「対象」「対象外」の区分けはしない。01の site-segments.yaml は「そのセクションが
    何であるか」だけを持ち、狙っているかどうかの判断はここでは行わない設計に合わせている。

    rows: 例えば landingPage×hostName×sessions,conversions のような、絞り込み無しで
    取得済みの行のリスト。match_site_segment() で1行ずつ分類し、セッション・CVを積み上げる。

    実データで「独立した3つの切り口の合計が全体を29,361件上回っていた」事故（分類から
    漏れたページを黙って除外していた）があったため、どのセグメントにも一致しない行
    （None）を「その他」として必ず残す（page_count で件数も可視化する）。`default: true`
    のセグメントが定義されていれば通常 None は発生しない（未設定クライアントのみ発生しうる）。

    このrows自体がGA4取得上限で取りこぼしている可能性があるため、"total"（rows自体の
    合計）と、別途取得した絞り込み無しの全体値との突き合わせは呼び出し側が行う
    （fetch_ga4_analytics.py 側。calc.format_reconciliation_note が使える）。

    戻り値:
      {
        "segments": [{"segment_id", "name", "sessions", "conversions"}, ...]
            （segments の定義順。一致した行が無いセグメントも0件のまま含める＝
            合計の照合をしやすくするため、件数0でも黙って行を消さない）,
        "other": {"sessions": float, "conversions": float, "page_count": int}
            （どのセグメントにも一致しなかった行。page_count は該当した行数）,
        "total": {"sessions": float, "conversions": float}（rows自体の合計）,
      }
    """
    dict_segments = [s for s in segments if isinstance(s, dict) and s.get("segment_id")]
    totals: dict[str, dict] = {
        s["segment_id"]: {
            "segment_id": s["segment_id"],
            "name": s.get("name", s["segment_id"]),
            "sessions": 0.0,
            "conversions": 0.0,
        }
        for s in dict_segments
    }

    other_sessions = 0.0
    other_conversions = 0.0
    other_count = 0
    total_sessions = 0.0
    total_conversions = 0.0

    for r in rows:
        sessions = r.get(sessions_key, 0) or 0
        conversions = r.get(conversions_key, 0) or 0
        total_sessions += sessions
        total_conversions += conversions

        seg_id = match_site_segment(
            segments,
            host_name=r.get(host_key) if host_key else None,
            page_path=r.get(path_key),
            content_group=r.get(content_group_key) if content_group_key else None,
        )
        if seg_id is not None and seg_id in totals:
            totals[seg_id]["sessions"] += sessions
            totals[seg_id]["conversions"] += conversions
        else:
            other_sessions += sessions
            other_conversions += conversions
            other_count += 1

    return {
        "segments": list(totals.values()),
        "other": {
            "sessions": other_sessions,
            "conversions": other_conversions,
            "page_count": other_count,
        },
        "total": {"sessions": total_sessions, "conversions": total_conversions},
    }


def segment_breakdown_table_lines(classification: dict) -> list[str]:
    """classify_segment_rows() の結果から、サマリーに並べる「セグメント別内訳」の
    テーブル行を組み立てる。

    セグメント別のセッション構成を並べることで、「メディアの流入が多いので
    当たり前なのに『新規に弱い』と解釈してしまう」ような早合点を防ぐ（読み手が内訳を
    見れば、どのセクションの数字が全体を動かしているかが分かる）。

    「その他（分類外）」は該当行（page_count > 0）がある場合のみ出す（`default: true`
    のセグメントがあれば通常発生しない。無いクライアントでは今も発生しうるため、節自体は
    残しつつ、該当が無ければ出さない）。末尾に合計行を必ず出し、内訳合計が全体と
    一致することをその場で確認できるようにする。
    """
    lines = ["| セグメント | セッション |", "|---|---:|"]
    for seg in classification["segments"]:
        sessions = seg["sessions"]
        lines.append(f"| {seg['name']} | {sessions:,.0f} |")
    other = classification["other"]
    if other["page_count"] > 0:
        o_sessions = other["sessions"]
        lines.append(f"| その他（分類外、{other['page_count']:,}ページ） | {o_sessions:,.0f} |")
    total = classification["total"]
    t_sessions = total["sessions"]
    lines.append(f"| 合計 | {t_sessions:,.0f} |")
    return lines
