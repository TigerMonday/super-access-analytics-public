"""§1 KPI未対応イベント: KPIのソーシングとカバレッジ判定.

KPIは次の優先順で取得する:
  1. local `{client}/inputs/kpis.yaml`（measurement_design native）
  2. 01 コンテキストストア（`load_context(client_id).kpis`）— best-effort

各KPIに `events`（このKPIを計測しているGA4イベント名のリスト。登録時に記録。
01 の schema/context-schema.md 参照）が付いていれば、それをGA4実態と直接突合する。
`events` が無いKPIのみ decomposer で一般的なイベント名を提案し、GA4実態と突合する。
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from measurement_design.review.ga4_defaults import DEFAULT_NOISE_KEY_EVENTS


def load_client_profile(client_id: str, project_root: Path) -> dict:
    """01コンテキストから公開レポート用のクライアント情報を取得する。"""
    ctx_src = project_root.parent.parent / "01_context_management" / "src"
    if not ctx_src.exists():
        return {}
    try:
        if str(ctx_src) not in sys.path:
            sys.path.insert(0, str(ctx_src))
        from context_store.loader import load_context  # type: ignore

        ctx = load_context(client_id)
        return dict((ctx.profile or {}).get("client", {}) or {})
    except Exception as e:
        print(
            f"[kpi_coverage] クライアント情報の読み込みに失敗しました（無視して続行）: {e}",
            file=sys.stderr,
        )
        return {}


def source_kpis(client_dir: Path, project_root: Path) -> tuple[list[dict], dict, str]:
    """KPI と screen_flow を取得する。

    返り値: (kpis, screen_flow, source_label)。取得できなければ ([], 空flow, "none")。
    """
    empty_flow = {"pages": [], "flows": []}

    # 1) local inputs/kpis.yaml
    try:
        from measurement_design.loader import load_kpis, load_screen_flow

        inputs_dir = client_dir / "inputs"
        kpis = load_kpis(inputs_dir)
        try:
            flow = load_screen_flow(inputs_dir)
        except FileNotFoundError:
            flow = empty_flow
        if kpis:
            return kpis, flow, "inputs/kpis.yaml"
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[kpi_coverage] inputs/kpis.yaml の読み込みに失敗しました（無視して続行）: {e}", file=sys.stderr)

    # 2) 01 コンテキストストア（best-effort・relパスで src を sys.path 追加）
    client_id = client_dir.name
    ctx_src = project_root.parent.parent / "01_context_management" / "src"
    if ctx_src.exists():
        try:
            if str(ctx_src) not in sys.path:
                sys.path.insert(0, str(ctx_src))
            from context_store.loader import load_context  # type: ignore

            ctx = load_context(client_id)
            kpis = (ctx.kpis or {}).get("kpis", []) or []
            if kpis:
                return kpis, empty_flow, "01コンテキスト"

            # KPIごとの登録が無くても、01の `key_events`（CV計算用イベント名。全KPI横断の
            # 一覧）は登録されていることがある。旧実装はここを見ておらず、KPIが1件も無い
            # クライアントでは常に §1 が「未連携」になっていた（実データで確認済みのバグ）。
            # 各イベント名をKPI相当のdictに変換し、以後は check_coverage の
            # 「events登録済みKPI」経路にそのまま乗せる。
            key_events = (ctx.kpis or {}).get("key_events", []) or []
            if key_events:
                pseudo_kpis = [
                    {"kpi_id": "", "name": name, "events": [name]}
                    for name in key_events
                ]
                return pseudo_kpis, empty_flow, "01コンテキストのkey_events"
        except Exception as e:
            print(
                f"[kpi_coverage] 01コンテキストストアの読み込みに失敗しました（無視して続行）: {e}",
                file=sys.stderr,
            )

    return [], empty_flow, "none"


def default_key_event_rows(review_data: dict) -> list[dict]:
    """KPIもkey_eventsも登録が無いとき、GA4のキーイベント設定を既定の「成果」として使う。

    §1 KPIと計測イベントの対応 が常に「未連携のため未評価」になっていた問題への対応。
    GA4側でキーイベントとして登録済みのイベントを、発火有無・件数つきでそのまま返す。
    KPIもkey_eventsも登録が無いときは「既定の答え」を使うことになるため、どのプロパティ
    にも既定で入るイベント（`ga4_defaults.DEFAULT_NOISE_KEY_EVENTS`）はここで除外する。
    """
    ga4 = review_data.get("ga4", {})
    key_events = [k for k in (ga4.get("key_events") or []) if k not in DEFAULT_NOISE_KEY_EVENTS]
    counts, counts_complete = _confirmed_event_counts(ga4)

    rows: list[dict] = []
    for name in key_events:
        count = counts.get(name, 0 if counts_complete else None)
        if count:
            status, action = "実装済み", "—"
        elif counts_complete:
            status, action = "未実装", "登録はあるが直近30日で発火していない（要確認）"
        else:
            status, action = "未確認", "全イベント件数を取得できていないため受信状況は未確認"
        rows.append({
            "kpi_id": "—",
            "kpi_name": "(GA4のキーイベント設定)",
            "event": name,
            "status": status,
            "count": count,
            "action": action,
            "source": "ga4_key_event",
        })
    return rows


def _confirmed_event_counts(ga4: dict) -> tuple[dict[str, int], bool]:
    """確認済みイベントの件数正本と、一覧が完全かを返す。

    normalizer経由の実データは ``event_counts_status`` を必ず持つ。古いphase2では
    ``missing`` となるため0件とは判定しない。ユニットテストや従来の直接呼び出しで
    状態キー自体が無い場合だけ、渡された ``events_observed`` を完全な一覧として扱う。
    """
    if "event_counts_status" not in ga4:
        rows = ga4.get("events_observed", [])
        return ({e.get("name", ""): int(e.get("count", 0) or 0) for e in rows}, True)
    complete = ga4.get("event_counts_status") == "complete"
    # 旧データでも上位100件に実在するイベントは受信済みと確認できる。完全一覧が
    # 無いときに未確認なのは「一覧に無いイベント」だけで、観測済みの正数まで捨てない。
    rows = ga4.get("event_counts_all", []) if complete else ga4.get("events_observed", [])
    return ({e.get("name", ""): int(e.get("count", 0) or 0) for e in rows}, complete)


def check_coverage(kpi_breakdowns: list[dict], kpis: list[dict], review_data: dict) -> list[dict]:
    """各KPIの必要イベントがGA4に存在するか判定し、§1表の行データを返す.

    優先順位（登録時にKPIとイベント名の対応を記録し、01の突合が最初にそれを見る運用）:
      1. KPI自体に `events`（このKPIを計測しているGA4イベント名のリスト）が登録されていれば、
         それをGA4実態と直接突合する（01コンテキスト登録時 or `inputs/kpis.yaml` で明記）。
         この場合、LLMによる一般的なイベント名の提案（decomposerの分解結果）は使わない。
      2. `events` が未登録のKPIのみ、従来どおり decomposer の分解結果（`kpi_breakdowns`）で判定する。

    行の "source" は次のいずれか。レンダラー側の表示分岐に使う:
      - "registered": kpis.yaml/01の `kpis` に業務名つきで登録されたKPI↔イベント対応
      - "key_event": 01の `key_events`（業務名を持たないイベント名の一覧）から作った仮KPI
      - "candidate": events未登録のKPIをdecomposerが一般的な命名から推定した候補
      - "unresolved": decomposerでも必要イベントを特定できなかった
    """
    ga4 = review_data.get("ga4", {})
    existing = {e.get("name", "") for e in ga4.get("events_observed", [])}
    existing |= set(ga4.get("key_events", []))
    candidate_counts = {
        e.get("name", ""): int(e.get("count", 0) or 0)
        for e in ga4.get("events_observed", [])
    }
    # 確認済みイベントの件数は、上位100件ではなく全イベント件数を正本にする。
    confirmed_counts, confirmed_counts_complete = _confirmed_event_counts(ga4)

    breakdown_by_id = {bd.get("kpi_id", ""): bd for bd in kpi_breakdowns}

    rows: list[dict] = []
    for kpi in kpis:
        kpi_id = kpi.get("kpi_id", "")
        kpi_name = kpi.get("name", "")
        registered_events = kpi.get("events") or []

        if registered_events:
            # 優先1: 登録済みのKPI↔イベント対応をGA4実態と直接突合する。
            # イベント名が分かっている（人が登録した）ので "source": "registered"。
            #
            # ただし kpi_id が空（= source_kpis が 01の key_events から作った仮KPI。
            # `{"kpi_id": "", "name": イベント名, "events": [イベント名]}`）の場合は
            # kpi_name が事実上イベント名の写しにすぎず、業務名を持たない。
            # source を "key_event" として分け、レンダラー側で「KPI名」列に
            # イベント名と同じ値を重複表示しないようにする（kpi_id は
            # context-schema.md で ✅必須のため、空になるのはこの仮KPI経路だけ）。
            row_source = "registered" if kpi_id else "key_event"
            for ename in registered_events:
                count = confirmed_counts.get(ename, 0 if confirmed_counts_complete else None)
                implemented = bool(count) or ename in ga4.get("key_events", [])
                if count:
                    status, action = "実装済み", "—"
                elif confirmed_counts_complete:
                    status = "実装済み" if implemented else "未実装"
                    action = f"登録済みイベント「{ename}」が直近30日で0件（要確認）"
                else:
                    status, action = "未確認", "全イベント件数を取得できていないため受信状況は未確認"
                rows.append({
                    "kpi_id": kpi_id, "kpi_name": kpi_name, "event": ename,
                    "status": status,
                    "count": count,
                    "action": action,
                    "source": row_source,
                })
            continue

        # 優先2: 未登録のKPIのみ、decomposer の一般的な提案イベントで判定する（従来ロジック）。
        # イベント名は一般的な命名からのLLM提案（＝候補）であり、確定した対応ではないため
        # "source": "candidate" を付け、レンダラー側で「候補」であることが分かる表示に変える。
        bd = breakdown_by_id.get(kpi_id, {})
        req = bd.get("required_events", [])
        if not req:
            rows.append({
                "kpi_id": kpi_id, "kpi_name": kpi_name, "event": "—",
                "status": "要件未分解", "action": "KPIから必要イベントを特定できず（要確認）",
                "source": "unresolved",
            })
            continue
        for ev in req:
            ename = ev.get("event_name", "")
            implemented = ename in existing
            rows.append({
                "kpi_id": kpi_id, "kpi_name": kpi_name, "event": ename,
                "status": "実装済み" if implemented else "未実装",
                "count": candidate_counts.get(ename, 0),
                "action": "—" if implemented else (ev.get("timing", "") or "イベント実装が必要"),
                "source": "candidate",
            })
    return rows


# ──────────────────────────────────────────────────────────
# §1 追加調査: 「発火しました」だけで終わらせないための3つの補助情報。
#
# ユーザーの実データ検証で、イベント名が分かっているKPI（優先1のケース）だけを
# 「実装済み（N件）」と表示すると、当たり前の確認で終わってしまうという指摘があった。
# ここでは、GA4の実測イベントから機械的に分かる次の2点と、事業指標との対比（参考情報）
# を追加する。
#   1. 成果らしいのにGA4のキーイベントに未登録のイベント（候補）
#   2. 「手前のイベント→完了イベント」の完了率が業務上説明のつかない値になっていないか
#   3. KPIの目標値と実績の対比（計測の不備ではなく事業指標。参考情報として明示して出す）
# ──────────────────────────────────────────────────────────

# 「手前のイベント」を示す接尾辞。
_ENTRY_SUFFIXES = ("_form", "_start")
# 「完了イベント」を示す接尾辞。
_COMPLETION_SUFFIXES = ("_thanks", "_complete", "_completed", "_done", "_success", "_sent")


def find_funnel_pairs(events_observed: list[dict]) -> list[dict]:
    """イベント名の接尾辞から「手前→完了」の対応を推定する.

    実データで見つかった対応（`contact_form`→`contact_thanks` 等）は、
    同じ接頭辞に対して手前側の接尾辞（`_form`/`_start`）と完了側の接尾辞
    （`_thanks`/`_complete`/`_completed`/`_done`/`_success`/`_sent`）が
    両方存在する、という形をしている。

    **これは接尾辞パターンに基づく推定であり、対応の唯一の見つけ方ではない。**
    このパターンに当たらない命名のサイトでは対応を見つけられない。呼び出し側
    （kpi_coverage内の各関数）は、この限界を出力の文言に必ず明記すること
    （health_checks.py と同じ「判定できないものを断定しない」方針）。
    """
    by_name = {e.get("name", ""): int(e.get("count", 0) or 0) for e in events_observed if e.get("name")}
    pairs: list[dict] = []
    for name, count in by_name.items():
        for suf in _ENTRY_SUFFIXES:
            if not name.endswith(suf):
                continue
            prefix = name[: -len(suf)]
            if not prefix:
                continue
            for csuf in _COMPLETION_SUFFIXES:
                completion_name = prefix + csuf
                if completion_name != name and completion_name in by_name:
                    pairs.append({
                        "entry_event": name,
                        "entry_count": count,
                        "completion_event": completion_name,
                        "completion_count": by_name[completion_name],
                    })
    return pairs


# ──────────────────────────────────────────────────────────
# 登録名と送信名の食い違い（前方一致・省略表記の疑い）。
#
# 実データで、キーイベントの登録名（例: `generate_lead`）と実際に送信されている
# イベント名（例: `gen_lead_xxx` 系）が食い違っており、§1が「登録済みイベントが
# 0件発火（計測漏れの疑い）」までしか言えていなかった（本当の原因である名前の
# 食い違いが計測設計書にしか出ていなかった）。ここでは0件発火の登録名について、
# 似た名前で実際に発火しているイベントが無いかを照合する。
# ──────────────────────────────────────────────────────────

# トークン（`_`区切りの単語）同士を「対応している」とみなす最短の接頭辞長。
# `gen` と `generate` のような省略表記を拾うが、`cv`（2文字）のような短い略号は
# 対象外にする（2文字以下だと無関係な単語にも高確率で前方一致してしまい、
# 誤検出の主因になる）。
_TOKEN_MATCH_MIN_PREFIX = 3


def _token_match(a: str, b: str) -> bool:
    """2つのトークンが「対応している」とみなせるか（完全一致、または一方が
    他方の `_TOKEN_MATCH_MIN_PREFIX` 文字以上の接頭辞）。"""
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= _TOKEN_MATCH_MIN_PREFIX and longer.startswith(shorter)


def find_similar_firing_events(
    registered_name: str, events_observed: list[dict], exclude: set[str] | None = None,
) -> list[dict]:
    """0件発火の登録名について、似た名前で実際に発火しているイベントが無いかを探す.

    **単純な文字列類似度（difflib等）は使わない。** `click_tel`（電話タップ）と
    `click_email`（メール）は共通の接頭辞 `click_` だけで文字列としては7〜8割
    似てしまい、無関係なのに誤って拾う（実際に試して確認済み）。

    ここでは `_` 区切りの単語（トークン）単位で比較し、**登録名の全トークンが、
    候補側のいずれかのトークンに対応づけられる場合のみ**候補にする（登録名が
    候補の部分集合になっている、という意味。逆方向＝候補側にしか無い単語が
    あるのは許容する——完了ページ等で単語が増えるのは自然なため）。
    トークンの対応は `_token_match`（完全一致、または3文字以上の接頭辞）で判定する。
    `click_tel` vs `click_email` は `click` は一致するが `tel` と `email` が
    どちらの接頭辞にもならず対応しないため、候補にならない。

    候補は実際に発火している（`count > 0`）ものに限り、`exclude`
    （他のKPI/キーイベントとして既に登録済みのイベント名。誤って別の指摘と
    競合させないため）と GA4 拡張計測イベント（有効化するだけで発火し、業務上の
    成果として登録する判断を経ていないためノイズになりやすい。
    `check_unregistered_outcome_events` と同じ理由）は除外する。
    発火件数の多い順に上位3件までに絞る（絞らないと表が埋まる）。
    """
    from measurement_design.review.diagnoser import GA4_ENHANCED_MEASUREMENT

    exclude = exclude or set()
    reg_tokens = [t for t in registered_name.lower().split("_") if t]
    if not reg_tokens:
        return []

    out = []
    for e in events_observed:
        name = e.get("name", "")
        count = int(e.get("count", 0) or 0)
        if not name or name == registered_name or name in exclude or count <= 0:
            continue
        if name in GA4_ENHANCED_MEASUREMENT:
            continue
        cand_tokens = [t for t in name.lower().split("_") if t]
        if not cand_tokens:
            continue
        if all(any(_token_match(rt, ct) for ct in cand_tokens) for rt in reg_tokens):
            out.append({"event": name, "count": count})
    out.sort(key=lambda x: -x["count"])
    return out[:3]


def check_key_event_name_mismatches(kpi_rows: list[dict], review_data: dict) -> list[dict]:
    """0件発火の登録済みキーイベントについて、実際の送信名との食い違いが無いかを照合する.

    対象は `kpi_rows` のうち `source` が registered/ga4_key_event/key_event
    （イベント名が確定している行。`renderer._kpi_row_note` と同じ切り分け）かつ
    `status == "未実装"`（0件発火）の行だけ。`candidate`（LLM推定のイベント名）は
    イベント名自体の確度が低く、ここでさらに「似た名前」を探すと二重に当てずっぽうに
    なるため対象外にする。
    """
    events_observed = review_data.get("ga4", {}).get("events_observed", [])
    registered_names = {r.get("event", "") for r in kpi_rows if r.get("event")}

    out: list[dict] = []
    for r in kpi_rows:
        if r.get("status") != "未実装":
            continue
        if r.get("source") not in ("registered", "ga4_key_event", "key_event"):
            continue
        name = r.get("event", "")
        if not name:
            continue
        candidates = find_similar_firing_events(name, events_observed, registered_names - {name})
        if candidates:
            out.append({
                "kpi_id": r.get("kpi_id", ""),
                "kpi_name": r.get("kpi_name", ""),
                "registered_event": name,
                "candidates": candidates,
            })
    return out


def check_unregistered_outcome_events(review_data: dict, kpis: list[dict]) -> list[dict]:
    """成果らしいのにGA4のキーイベントに未登録のイベントを候補として挙げる.

    キーイベントに登録されていないと、広告の最適化にもレポートの既定指標にも
    使われない。ただし「成果らしい」を名前のパターン（`_thanks` `complete` 等）だけで
    判定すると、当たらない命名のサイトで拾えず、逆に無関係なイベントを拾う。

    ここでは `find_funnel_pairs` が「手前のイベントとの対応が取れている」と判定した
    完了イベントだけを候補にする（名前だけでなく、対になる手前イベントの実績という
    もう1つの手がかりを組み合わせている）。それでも接尾辞パターンに基づく推定である
    ことに変わりはないため、断定はせず「候補」として返す（判断は人に委ねる）。

    すでにKPIに `events` として登録済みのイベント、GA4のキーイベントに登録済みの
    イベントは対象外（この関数が挙げるのは「まだ気づかれていない候補」に限る）。

    **GA4の拡張計測イベント（`video_complete` 等）は候補から外す（試用フィードバックで
    検出）。** `_start`→`_complete`/`_progress` は拡張計測が自動で付ける名前でもあり、
    サイト独自の成果イベントと同じ接尾辞パターンに偶然当たる。拡張計測イベントは
    有効化するだけで発火し、業務上の成果として登録する判断を経ていないため、
    ここで候補として挙げると `purchase`（`ga4_defaults.DEFAULT_NOISE_KEY_EVENTS`）と
    同種のノイズになる。一覧は `diagnoser.GA4_ENHANCED_MEASUREMENT`（GA4が自動収集する
    イベント名の一覧）を1か所から引く。
    """
    from measurement_design.review.diagnoser import GA4_ENHANCED_MEASUREMENT

    ga4 = review_data.get("ga4", {})
    key_events = set(ga4.get("key_events", []))
    registered = {e for k in kpis for e in (k.get("events") or [])}
    pairs = find_funnel_pairs(ga4.get("events_observed", []))

    seen: set[str] = set()
    out: list[dict] = []
    for p in sorted(pairs, key=lambda x: -x["completion_count"]):
        name = p["completion_event"]
        if name in key_events or name in registered or name in seen:
            continue
        if name in GA4_ENHANCED_MEASUREMENT:
            continue
        if p["completion_count"] <= 0:
            continue
        seen.add(name)
        out.append({
            "event": name,
            "count": p["completion_count"],
            "entry_event": p["entry_event"],
            "entry_count": p["entry_count"],
        })
    return out


def check_funnel_completion_rates(review_data: dict) -> list[dict]:
    """「手前→完了」の完了率が、業務上説明のつかない値になっていないか.

    完了率そのものはサイトによって大きく違うため、中間の値を異常扱いしない
    （health_checks.py の `user_engagement` と同じ考え方。しきい値を決め打ちすると
    誤検知の温床になる）。0%（手前に実績があるのに完了が1件も無い）と100%超
    （完了が手前を上回る＝多重計上か対応の取り違え）だけを指摘の対象にする。
    """
    ga4 = review_data.get("ga4", {})
    pairs = find_funnel_pairs(ga4.get("events_observed", []))

    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for p in pairs:
        key = (p["entry_event"], p["completion_event"])
        if key in seen:
            continue
        entry, comp = p["entry_count"], p["completion_count"]
        if entry <= 0:
            continue  # 手前に実績が無ければ比較できない
        rate = comp / entry
        if comp == 0:
            seen.add(key)
            out.append({**p, "rate": 0.0, "issue": "0%（完了が1件も無い）"})
        elif rate > 1.0:
            seen.add(key)
            out.append({**p, "rate": rate, "issue": "100%超（完了が手前を上回る）"})
    return out


def build_target_comparison(kpis: list[dict], kpi_rows: list[dict]) -> list[dict]:
    """KPIの目標値と、GA4で確認できた実績件数を対比する（参考情報）.

    **これは計測の不備の指摘ではない。** 目標未達は事業上の課題であり、計測が正しく
    動いているかどうかとは別の論点のため、判定（○×）は付けず、事実の対比だけを出す
    （呼び出し側でも「計測の不備ではない」と分かる形で表示すること）。

    実績は `kpi_rows`（check_coverage / default_key_event_rows の結果）から
    `kpi_id` 単位で件数を合算する。イベント名の登録有無（優先1/優先2どちらの経路か）を
    問わず同じ集計で扱える。
    """
    counts_by_kpi: dict[str, int] = defaultdict(int)
    has_count: set[str] = set()
    for r in kpi_rows:
        kid = r.get("kpi_id")
        if kid and r.get("count") is not None:
            counts_by_kpi[kid] += int(r.get("count") or 0)
            has_count.add(kid)

    out: list[dict] = []
    for k in kpis:
        target = k.get("target_value") or {}
        goal = target.get("goal")
        if goal is None:
            continue
        kid = k.get("kpi_id", "")
        if kid not in has_count:
            continue
        out.append({
            "kpi_id": kid,
            "kpi_name": k.get("name", ""),
            "actual": counts_by_kpi[kid],
            "goal": goal,
            "unit": target.get("unit") or "",
        })
    return out
