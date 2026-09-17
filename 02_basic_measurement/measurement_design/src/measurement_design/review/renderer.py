"""チェックレポート生成モジュール."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

# §8 ロードマップ用: 重要度 → 並び順 / 優先度ラベル
_SEV_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}

# テンプレートの既知プレースホルダ（未置換で残った場合のみ安全網で除去する対象）。
# GTM変数参照（{{event_name}} 等）の正当な {{}} を巻き込まないよう、ブランケット正規表現は使わない。
_TEMPLATE_PLACEHOLDERS = (
    "{{public_summary}}", "{{fixed_check_table}}", "{{manual_settings_table}}",
    "{{findings_result}}", "{{findings_evidence}}",
    "{{matrix_summary}}", "{{audit_matrix_table}}", "{{manual_check_table}}",
    "{{machine_item_count}}", "{{manual_item_count}}",
    "{{kpi_result}}", "{{kpi_evidence}}",
    "{{naming_result}}", "{{naming_evidence}}",
    "{{param_scope}}", "{{param_result}}", "{{param_evidence}}",
    "{{health_result}}", "{{health_evidence}}",
    "{{gtmcfg_result}}", "{{gtmcfg_evidence}}",
    "{{gtm_result}}", "{{gtm_evidence}}",
    "{{unresolved_evidence}}",
    "{{roadmap_result}}", "{{roadmap_evidence}}",
)

# 「根拠データ」に出す指摘が0件のときの一言。結果文がすでに件数・結論を述べているため、
# 中身の無い表（ヘッダーだけ・ダミー行だけ）は出さない（表が2重に「無い」と言うだけの
# 状態を避ける）。
_NO_EVIDENCE_NOTE = "上記のとおりで、表に出す項目はありません。"


# 内部では従来の全監査項目・全違反を保持する。一方、クライアント向け本文へ出す範囲は
# この projection だけで管理する。監査ロジックや保存データを削って表示範囲を狭めると、
# 後から別の確認が必要になったときに再取得が必要になるため、表示と内部監査を分離する。
_PUBLIC_SETTING_CHECKS = (
    {
        "category": "データストリーム", "name": "拡張計測機能", "aliases": ("拡張計測機能",),
        "missing": "設定を取得できていません",
        "ok_action": "必要な操作が受信できるか実操作でも確認します。標準と独自のスクロール深度は併用でき、同じ到達率を重複送信していないかだけ確認します",
        "issue_action": "必要な項目を有効化し、実操作で受信を確認します。同じ操作・同じ到達率の重複送信だけを整理します",
    },
    {
        "category": "データストリーム", "name": "Google タグの管理：ページ上の設定の重複インスタンスを無視します", "aliases": (), "manual": True,
        "missing": "Admin APIでは取得できないため未確認です",
        "ok_action": "通常は変更不要です。SPA等でページ上の再設定を意図的に受け付ける必要がある場合は、この設定を外します",
        "issue_action": "GA4管理画面で設定値とサイト実装を照合します。SPA等で意図的に再設定を受け付ける場合は、この設定を外します",
    },
    {
        "category": "データストリーム", "name": "計測対象ホスト", "aliases": ("対象外ホスト・内部トラフィック", "内部トラフィックの除外"),
        "missing": "受信ホスト名を取得できていません",
        "ok_action": "対象外の検証環境・別サイトが混入していない状態を維持します",
        "issue_action": "主要な受信ホストを確認し、正規の対象・クロスドメイン対象・除外対象に分類します",
    },
    {
        "category": "データストリーム", "name": "クロスドメイン設定", "aliases": ("クロスドメイン計測",),
        "missing": "受信ホスト名と流入データから判定できていません",
        "ok_action": "対象ドメインを同じGoogleタグIDへ接続し、実ブラウザ遷移でもセッション継続を確認します",
        "issue_action": "予約・決済等の別ドメイン導線がある場合は対象ドメインを登録し、同じGoogleタグIDと実ブラウザ遷移時のセッション継続を確認します",
    },
    {
        "category": "データストリーム", "name": "内部トラフィックの定義", "aliases": (), "manual": True,
        "missing": "Admin APIでは定義内容を取得できないため未確認です",
        "ok_action": "除外したい社内・制作会社・拠点等のIPがあれば、traffic_type のルールとして定義します",
        "issue_action": "除外したい社内・制作会社・拠点等のIPがあれば、traffic_type のルールとして定義します",
    },
    {
        "category": "データストリーム", "name": "除外する参照のリスト", "aliases": ("不要な参照元", "参照元の除外"),
        "missing": "流入データを取得できていません",
        "ok_action": "予約・決済導線を変更した際は、外部サービス経由の自己参照が増えていないか再確認します",
        "issue_action": "自己参照やAmazon Pay・PayPal等の決済サービス経由の参照があれば、導線を確認して必要なドメインだけを除外リストへ追加します",
    },
    {
        "category": "データストリーム", "name": "セッションのタイムアウト", "aliases": (), "manual": True,
        "missing": "Admin APIでは設定値を取得できないため未確認です",
        "ok_action": "GA4管理画面で現在値を確認し、サイトの検討・予約・購入に必要な時間に合わせます",
        "issue_action": "GA4管理画面で現在値を確認し、サイトの検討・予約・購入に必要な時間に合わせます",
    },
    {
        "category": "データの収集", "name": "Google シグナル", "aliases": ("Google シグナル",),
        "missing": "設定を取得できていません",
        "ok_action": "利用目的・同意取得・プライバシーポリシーと整合しているか確認します",
        "issue_action": "広告・ユーザー分析の利用目的と同意条件を確認し、必要な場合だけ有効化します",
    },
    {
        "category": "データの収集", "name": "ユーザー提供データの収集", "aliases": ("ユーザー提供データの収集",),
        "missing": "設定を取得できていません",
        "ok_action": "送信項目・同意取得・ハッシュ化を含む実装が運用方針と一致しているか確認します",
        "issue_action": "利用目的・同意・実装要件を確認し、必要な場合だけ有効化します",
    },
    {
        "category": "データの収集", "name": "地域とデバイスに関する詳細なデータの収集", "aliases": (), "manual": True,
        "missing": "Admin APIでは地域別の設定値を取得できないため未確認です",
        "ok_action": "GA4管理画面で対象地域と利用目的を確認します",
        "issue_action": "GA4管理画面で対象地域と利用目的を確認し、不要な地域は無効化します",
    },
    {
        "category": "データの保持", "name": "イベントデータの保持", "aliases": ("データ保持",),
        "missing": "設定を取得できていません",
        "ok_action": "14か月の設定を維持します",
        "issue_action": "探索レポート等で前年比較できるよう、要件に問題がなければ14か月へ変更します",
    },
    {
        "category": "データフィルタ", "name": "Internal Traffic", "aliases": (), "manual": True,
        "missing": "Admin APIではフィルタの設定・適用状態を取得できないため未確認です",
        "ok_action": "内部トラフィックの定義で設定した traffic_type を除外するフィルタとして設定し、テスト後に有効化します",
        "issue_action": "内部トラフィックの定義で設定した traffic_type を除外するフィルタとして設定し、テスト後に有効化します",
    },
    {
        "category": "レポート用識別子", "name": "現在の設定と定義", "aliases": ("レポート用識別子",),
        "missing": "設定を取得できていません",
        "ok_action": "表示されるユーザー数の定義が分析目的と合っているか確認します",
        "issue_action": "GA4管理画面で現在値を確認し、User-ID・デバイスID・モデリングの利用方針に合わせます",
    },
    {
        "category": "アトリビューション設定", "name": "モデルとルックバック期間", "aliases": ("アトリビューション",),
        "missing": "設定を取得できていません",
        "ok_action": "成果への貢献をどの接点へ配分する設定かを理解し、広告評価の方針と照合します",
        "issue_action": "GA4管理画面でモデルとルックバック期間を確認し、広告評価の方針に合わせます",
    },
    {
        "category": "連携", "name": "Google広告とのリンク", "aliases": ("Google広告とのリンク",),
        "missing": "リンク一覧を取得できていません",
        "ok_action": "対象の広告アカウントとのリンクとデータ共有設定を維持します",
        "issue_action": "広告運用で必要な対象アカウントを確認し、必要な場合だけリンクします",
    },
    {
        "category": "連携", "name": "BigQueryとのリンク", "aliases": ("BigQueryとのリンク", "生データの書き出し（BigQuery）"),
        "missing": "リンク一覧を取得できていません",
        "ok_action": "出力先テーブルの最新日付・欠損も確認します",
        "issue_action": "リンク済みなら出力先テーブルの最新日付・欠損を確認し、未リンクなら長期保存・明細分析の要件に応じて設定します",
    },
    {
        "category": "計測タグ", "name": "UA経由の計測継続性", "aliases": ("UA経由の計測継続性",),
        "missing": "GTMまたは公開サイトの実装を取得できていません",
        "ok_action": "GA4がGoogleタグまたはGA4設定タグから直接送信される状態を維持します",
        "issue_action": "GTMのUA/GA4タグ種別と公開サイトのgtag実装を照合し、UA依存を解消します",
    },
)

def _count_by_severity(violations: list[dict]) -> dict:
    counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    for v in violations:
        sev = v.get("severity", "Low")
        if sev in counts:
            counts[sev] += 1
    return counts


def _table_or_note(headers: list[str], rows: list[str]) -> str:
    """行が1件も無ければ表そのものを出さず、一言に差し替える（空表を残さない）."""
    if not rows:
        return _NO_EVIDENCE_NOTE
    sep = "|" + "|".join("---" for _ in headers) + "|"
    head = "| " + " | ".join(headers) + " |"
    return "\n".join([head, sep, *rows])


def _public_fixed_rows(matrix_rows: list[dict] | None) -> list[dict]:
    """内部監査表と手動確認項目から、公開する設定確認表を組み立てる。"""
    by_name = {str(row.get("name", "")): row for row in matrix_rows or []}
    rows = []
    for spec in _PUBLIC_SETTING_CHECKS:
        if spec.get("manual"):
            continue
        display_name = spec["name"]
        aliases = spec["aliases"]
        source = next((by_name[name] for name in aliases if name in by_name), None)
        if source is None:
            rows.append({
                "category": spec["category"],
                "name": display_name,
                "judgement": "warn",
                "state": spec["missing"],
                "action": spec["issue_action"],
            })
        else:
            judgement = source.get("judgement", "warn")
            rows.append({
                **source,
                "category": spec["category"],
                "name": display_name,
                "action": spec["ok_action"] if judgement == "ok" else spec["issue_action"],
            })
    return rows


def _public_manual_rows() -> list[dict]:
    """APIで取得できない設定を、個別の△行ではなく1つの目視確認ブロックへ集約する。"""
    rows = [
        {"name": spec["name"], "action": spec["issue_action"]}
        for spec in _PUBLIC_SETTING_CHECKS if spec.get("manual")
    ]
    rows.append({
        "name": "Search Console連携",
        "action": "GA4管理画面のSearch Consoleリンクで、対象プロパティとの連携を確認します",
    })
    return rows


def _is_dynamic_event_name(text: str) -> bool:
    return "{{" in (text or "") and "}}" in (text or "")


def _is_style_only_naming(v: dict) -> bool:
    """大文字・ハイフンだけの差を修正必須にしない。"""
    if v.get("category") != "命名規則" or v.get("target_kind") != "event":
        return False
    name = str(v.get("target_name", ""))
    if not name or re.search(r"[^A-Za-z0-9_-]", name):
        return False
    description = str(v.get("description", ""))
    return bool(re.search(r"大文字|ハイフン|小文字", description))


def _has_japanese(text: str) -> bool:
    return bool(re.search(r"[ぁ-んァ-ヶ一-龯々ー]", text or ""))


def _public_violation(v: dict) -> dict | None:
    """内部指摘を本文表示用へ変換する。非表示の判断もここだけで行う。"""
    if v.get("target_kind") == "parameter" or "パラメータ" in str(v.get("category", "")):
        return None

    name = str(v.get("target_name", ""))
    description = str(v.get("description", ""))
    category = str(v.get("category", ""))

    # イベント名をGTM変数で決める設計自体は異常ではない。静的に突合できないというだけで
    # 読者へ修正を迫らない。
    if _is_dynamic_event_name(name) or (
        v.get("location") == "GTM" and "変数" in description and "イベント名" in description
    ):
        return None

    if category in {"必須パラメータ不足", "孤立", "フォーム到達未確認", "レポートの分裂"}:
        return None
    # source / medium の未知語彙一覧は出さず、GA4上で実際に Unassigned / (not set)
    # になっている根拠がある場合だけ公開する。
    if category == "流入分類" and not re.search(r"Unassigned|\(not set\)|未分類", description, re.IGNORECASE):
        return None

    # 本数だけを根拠にした「一本化」や、停止タグの存在だけの一般論は本文へ出さない。
    # GTMは同一イベント名・同一条件など、実際の誤計測につながる根拠がある指摘に絞る。
    if v.get("location") == "GTM" and category in {
        "GTMタグ量産", "タグ量産", "値の使い回し", "残骸候補",
    }:
        return None
    if v.get("location") == "GTM" and category in {"判定不能", "発火範囲の確認"}:
        return None
    if v.get("location") == "GTM" and category == "設定の陳腐化" and v.get("severity") == "Low":
        return None
    if v.get("location") != "GTM" and category == "設定の陳腐化":
        return None

    out = dict(v)
    out["reference_only"] = False
    if _is_style_only_naming(out):
        out["severity"] = "Low"
        out["reference_only"] = True
        out["suggested_fix"] = "対応は不要です。新しく追加するイベントの命名時に参考にしてください"
    elif (
        out.get("target_kind") == "event" and _has_japanese(name)
        and _SEV_ORDER.get(out.get("severity", "Low"), 3) > _SEV_ORDER["Medium"]
    ):
        # GA4で受信できてもデータ連携時の互換性問題になるため、参考扱いにはしない。
        out["severity"] = "Medium"
    return out


def _build_public_projection(
    violations: list[dict], matrix_rows: list[dict] | None,
    kpi_rows: list[dict] | None = None,
    kpi_name_mismatches: list[dict] | None = None,
) -> dict:
    """内部監査結果から、クライアント向け本文へ出すデータだけを一度に決める。"""
    public_findings = [projected for v in violations if (projected := _public_violation(v))]
    confirmed_rows = [
        row for row in (kpi_rows or [])
        if row.get("source") in {"registered", "key_event"} and row.get("event")
    ]
    mismatch_by_event = {
        row.get("registered_event"): row for row in (kpi_name_mismatches or [])
        if row.get("registered_event")
    }
    for row in confirmed_rows:
        count = row.get("count")
        if count is None or int(count or 0) > 0:
            continue
        event = str(row.get("event", ""))
        kpi_name = str(row.get("kpi_name", "") or "")
        target = f"{kpi_name}（{event}）" if kpi_name and kpi_name != event else event
        mismatch = mismatch_by_event.get(event, {})
        candidates = mismatch.get("candidates") or []
        candidate_note = ""
        if candidates:
            examples = "・".join(
                f"`{candidate.get('event', '')}`（{int(candidate.get('count', 0) or 0):,}件）"
                for candidate in candidates
            )
            candidate_note = f" 類似名で受信している候補: {examples}。"
        public_findings.append({
            "id": f"conversion:{event}",
            "severity": "Medium",
            "category": "成果計測",
            "target_kind": "event",
            "target_name": target,
            "location": "GA4",
            "description": (
                f"事前にコンバージョンポイントとして確認したイベント `{event}` が"
                f"直近30日で0件。実際に成果が無かったのか、イベント名の食い違い・計測漏れかは未確定。"
                f"{candidate_note}"
            ),
            "suggested_fix": (
                "対象の完了操作を実施し、GTMプレビューとGA4 DebugViewで送信名・受信回数を確認する。"
                "類似名候補がある場合は、確認済みのコンバージョンイベント名を実装に合わせて修正する"
            ),
            "reference_only": False,
        })
    return {
        "fixed_rows": _public_fixed_rows(matrix_rows),
        "manual_rows": _public_manual_rows(),
        "findings": public_findings,
        "roadmap_findings": [v for v in public_findings if not v.get("reference_only")],
        "conversion_total": len(confirmed_rows),
        "conversion_received": sum(
            1 for row in confirmed_rows
            if row.get("count") is not None and int(row.get("count") or 0) > 0
        ),
        "conversion_unverified": sum(1 for row in confirmed_rows if row.get("count") is None),
    }


def _build_public_summary(projection: dict) -> str:
    marks = {"ok": 0, "warn": 0, "ng": 0}
    for row in projection["fixed_rows"]:
        judgement = row.get("judgement", "warn")
        marks[judgement if judgement in marks else "warn"] += 1
    actionable = sum(1 for v in projection["findings"] if not v.get("reference_only"))
    references = sum(1 for v in projection["findings"] if v.get("reference_only"))
    text = (
        f"計測設定の確認結果は、×{marks['ng']}件・△{marks['warn']}件・○{marks['ok']}件でした。"
        f"取得データから具体的に確認できた要対応・要確認は{actionable}件です。"
    )
    if references:
        text += f"このほか、修正を必須としない命名上の参考情報が{references}件あります。"
    conversion_total = int(projection.get("conversion_total", 0) or 0)
    if conversion_total:
        received = int(projection.get("conversion_received", 0) or 0)
        text += (
            f"事前に確認したコンバージョンイベントは{conversion_total}件中{received}件で"
            "直近30日の受信を確認しました。"
        )
        unverified = int(projection.get("conversion_unverified", 0) or 0)
        if unverified:
            text += (
                f"残りのうち{unverified}件は全イベント件数を取得できていないため未確認で、"
                "0件とは判定していません。"
            )
    else:
        text += "事前に確認したコンバージョンポイントが無いため、成果計測の受信状況は未確認です。"
    return text


def _build_public_fixed_table(rows: list[dict]) -> str:
    marks = {"ok": "○", "warn": "△", "ng": "×"}
    return _table_or_note(
        ["カテゴリ", "確認項目", "判定", "結果", "対応事項"],
        [
            f"| {_clean_cell(row.get('category', ''))} | {_clean_cell(row['name'])} | "
            f"{marks.get(row.get('judgement'), '△')} | {_clean_cell(row.get('state', ''))} | "
            f"{_clean_cell(row.get('action', ''))} |"
            for row in rows
        ],
    )


def _build_manual_settings_table(rows: list[dict]) -> str:
    return _table_or_note(
        ["目視確認項目", "確認すること"],
        [
            f"| {_clean_cell(row['name'])} | {_clean_cell(row.get('action', ''))} |"
            for row in rows
        ],
    )


def _finding_group_key(v: dict) -> tuple:
    name = str(v.get("target_name", ""))
    description = str(v.get("description", ""))
    if name:
        description = description.replace(f"'{name}'", "'{}'").replace(f"`{name}`", "`{}`")
    return (
        v.get("category"), v.get("severity"), bool(v.get("reference_only")),
        description, v.get("suggested_fix"),
    )


def _build_public_findings_section(findings: list[dict]) -> tuple[str, str]:
    if not findings:
        return "取得データから具体的な異常・要確認は見つかりませんでした。", _NO_EVIDENCE_NOTE
    groups: dict[tuple, list[dict]] = {}
    for finding in findings:
        groups.setdefault(_finding_group_key(finding), []).append(finding)
    rows = []
    for members in sorted(
        groups.values(),
        key=lambda ms: (_SEV_ORDER.get(ms[0].get("severity", "Low"), 3), str(ms[0].get("category", ""))),
    ):
        rep = members[0]
        examples = "・".join(f"`{_clean_cell(str(v.get('target_name', '')))}`" for v in members[:3]) or "—"
        if len(members) > 3:
            examples += f" ほか{len(members) - 3}件"
        severity = rep.get("severity", "Low") + ("（参考）" if rep.get("reference_only") else "")
        rows.append(
            f"| {_clean_cell(str(rep.get('category', '')))} | {examples} | "
            f"{_clean_cell(str(rep.get('description', '')))} | "
            f"{_clean_cell(str(rep.get('suggested_fix', '')))} | {severity} |"
        )
    actionable = sum(1 for v in findings if not v.get("reference_only"))
    references = len(findings) - actionable
    result = f"要対応・要確認は{actionable}件です。"
    if references:
        result += f"修正を必須としない参考情報は{references}件です。"
    return result, _table_or_note(["区分", "対象（例）", "内容", "対応", "重要度"], rows)


def render_check_report(
    violations: list[dict],
    review_data: dict,
    template_path: Path,
    client_name: str,
    kpi_rows: list[dict] | None = None,
    site_url: str | None = None,
    client_display_name: str | None = None,
    matrix_rows: list[dict] | None = None,
    kpi_outcome_candidates: list[dict] | None = None,
    kpi_completion_issues: list[dict] | None = None,
    kpi_target_comparison: list[dict] | None = None,
    kpi_name_mismatches: list[dict] | None = None,
) -> str:
    """違反リストとレビューデータからチェックレポートを生成する.

    GA4 計測の指摘と GTM 設定の指摘は location で切り分け、サマリーもこの単位で集計する。

    各章は「調査内容（テンプレート側の固定文）→ 結果（ここで組み立てる要約）→
    根拠データ（表。0件なら表自体を出さず一言に差し替える）」の順に統一している。
    ○△×の固定項目一覧（audit_matrix）は全体サマリーの直後にそのまま埋め込む
    （以前は別ファイル docs/audit-matrix.md に分けて出していたが、「見るレポートを
    1本にしたい」という要望を受けて統合した）。**この判定表に指摘IDは出さない**
    （`_build_audit_matrix_table`。以前は×・△行に指摘IDへの参照を付けていたが、
    レポートの中でも最初に・一番目立つ形で読まれる表にID羅列が残ることになり、
    「IDいらない」という試用フィードバックへの対応が判定表にだけ及んでいなかった）。
    指摘IDはレポートには出さず、内部処理でだけ使う。
    テンプレートへの差し込みは他のプレースホルダと同じ単純な文字列置換で行う。
    過去に正規表現で節を組み立てようとしてCRLF環境（Windows）で空振りし、
    `{{audit_matrix}}` が置換されずに残った失敗があるため
    （standards/audit-items.md の「改行を決め打ちしない」を参照）、改行コードに依存する
    組み立て方はしない。

    各違反（1件=1指摘）は、必ずどれか1つのセクションの表にだけ出す（重複掲載しない）。
    振り分けは次の優先順で決まる（後段ほど「前段のどれにも当たらなかった残り」）。

      §2 健全性検出 … 命名・パラメータ以外の GA4 側の指摘（実測値からの機械検出。計測漏れ等）
      §3 命名規則   … カテゴリが 命名規則/表記ゆれ/重複/予約語衝突 の GA4 側の指摘
      §4 パラメータ … target_kind が parameter の指摘（登録済みカスタム定義）
      §5 GTM設定の指摘 … 上記に当たらない GTM 側の指摘（残骸候補・二重計測・タグ量産等）

    §6「GTMとGA4の不整合」は上記の violations リストとは別の突合（GTMタグの送信イベント名
    と GA4 受信イベントの比較）なので、この振り分けの対象外（独立した根拠データ）。
    §7「確認できなかったこと」は検査項目の一覧（audit_matrix）から権限・上限・判定不能の
    行を集約したもので、これも violations リストの振り分けの対象外。
    §8「改善ロードマップ」は全違反をフェーズ→重要度の順で並べた一覧で、説明文はここでは持たない
    （§2〜§5 のどこかに必ず出ているため、対象名で辿れる）。
    かつては「指摘詳細」という全違反を1指摘=1行で並べる表を別に置いていたが、
    §2〜§5 とロードマップで情報が尽きるため廃止した（同じ指摘が最大3セクションに
    重複していた）。

    **検査項目の一覧（判定表）・§2〜§5・§8の本文には指摘IDを出さない。** 対象名
    （イベント名・パラメータ名・タグ名など）だけで各セクションの行を特定できるため、
    IDはそのための手がかりとして要らない（「指摘IDの羅列が多すぎる」「IDいらない」
    という試用フィードバックへの対応。当初は§2〜§5・§8だけを直したが、レポートの中で
    最初に・一番目立つ形で読まれる「検査項目の一覧」の×・△行にも同じID羅列
    （`add_violation_references` が付けていたもの）が残っており、後で判定表側も揃えた）。
    IDは `check-report-notes.md`（対応メモ）が見出しに使う安定した符号として内部では残すが、
    読者向けレポートには掲載しない。

    `client_display_name`（01コンテキストの `client.name`。受付時にユーザーへ確認して
    保存した正式名称）が渡されればそれをタイトル・「対象サイト」に使う。無ければ従来どおり
    GA4プロパティの表示名、それも無ければ「サイト名未登録」と表示する。client_name
    （client_id）は工程間の受け渡し・保存先識別にだけ使い、レポートには出さない。
    GA4プロパティの表示名はGA4管理画面で当該プロパティを探す手がかりとして情報価値がある
    ため捨てず、「GA4プロパティ」行に property_id と併記する（対象サイト/タイトルには
    出さない。長い正式名称と管理画面上の表示名が並ぶと冒頭が読みにくくなるため）。
    """
    template = template_path.read_text(encoding="utf-8")
    from measurement_design.review.diagnoser import drop_naming_findings_for_unnecessary_events
    violations = drop_naming_findings_for_unnecessary_events(violations)

    prop = review_data.get("ga4", {}).get("property", {})
    property_display_name = (prop.get("name") or "").strip()
    # 対象サイト名: 09で確認済みの正式名称 → GA4プロパティ表示名 → 未登録表示の順で解決する。
    # 受付でユーザーに聞いて01に保存した正式名称があるのに、GA4管理画面上の表示名
    # （通称・略称になっていることが多い）が優先されてしまっていた不具合の修正。
    site_name = (client_display_name or "").strip() or property_display_name or "サイト名未登録"

    content = template
    # client_name（client_id）は工程間の受け渡し・保存先識別にだけ使い、読者向け本文には出さない。
    content = content.replace("{{クライアント名}}", "")
    content = content.replace("{{サイト名}}", site_name)
    content = content.replace("{{サイトURL}}", (site_url or "").strip() or "未登録")
    content = content.replace("{{YYYY-MM-DD}}", date.today().isoformat())
    projection = _build_public_projection(
        violations, matrix_rows, kpi_rows=kpi_rows, kpi_name_mismatches=kpi_name_mismatches,
    )
    content = content.replace("{{public_summary}}", _build_public_summary(projection))
    content = content.replace("{{fixed_check_table}}", _build_public_fixed_table(projection["fixed_rows"]))
    content = content.replace("{{manual_settings_table}}", _build_manual_settings_table(projection["manual_rows"]))

    findings_result, findings_evidence = _build_public_findings_section(projection["findings"])
    content = content.replace("{{findings_result}}", findings_result)
    content = content.replace("{{findings_evidence}}", findings_evidence)

    # ロードマップも同じ projection の表示対象だけを使う。本文で非表示にした内部指摘が
    # 末尾だけに再登場することを防ぐ。
    roadmap_result, roadmap_evidence = _build_roadmap(projection["roadmap_findings"])
    content = content.replace("{{roadmap_result}}", roadmap_result)
    content = content.replace("{{roadmap_evidence}}", roadmap_evidence)

    # 安全網: 万一テンプレの既知プレースホルダが未置換で残っても消す。
    # （GTM変数参照 {{event_name}} 等の正当な {{}} を巻き込まないよう、既知トークンのみ対象）
    for tok in _TEMPLATE_PLACEHOLDERS:
        content = content.replace(tok, "—")

    return content


def _complete_matrix_rows(matrix_rows: list[dict] | None) -> list[dict]:
    """固定項目の欠落を未評価で補い、部分的な監査表を完成扱いしない。"""
    from measurement_design.review.audit_matrix import ITEMS

    supplied = {(r["area"], r["name"]): r for r in matrix_rows or []}
    return [
        supplied.get((area, name), {
            "area": area, "name": name, "judgement": "warn",
            "state": "判定結果が取得されていないため未評価",
        })
        for area, name, _, _ in ITEMS
    ]


def _build_manual_check_table(template_path: Path) -> tuple[str, int]:
    """目視項目は正本から読み、全案件に同じチェック範囲を表示する。"""
    standards = template_path.resolve().parent.parent / "standards" / "audit-items.md"
    if not standards.exists():
        standards = Path(__file__).resolve().parents[3] / "standards" / "audit-items.md"
    text = standards.read_text(encoding="utf-8")
    match = re.search(r"## 目視で判定する\d+項目\s*(.*?)(?:\n## |\Z)", text, re.DOTALL)
    if not match:
        raise ValueError("目視監査項目の節が見つかりません")
    section = match.group(1)
    groups: dict[str, list[str]] = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) == 4 and cells[0] not in ("領域", "---"):
            groups.setdefault(cells[0], []).append(f"| {cells[1]} | 未確認 | {cells[2]} |")
    total = sum(len(rows) for rows in groups.values())
    if total == 0:
        raise ValueError("目視監査項目が0件です")
    table = "\n\n".join(
        f"#### {area}\n\n" + _table_or_note(["項目", "状態", "確認内容"], rows)
        for area, rows in groups.items()
    )
    return table, total


def _build_matrix_summary(matrix_rows: list[dict] | None) -> str:
    """全体サマリーに置く、○△×の機械判定項目（audit_matrix）の件数まとめ.

    詳細な項目一覧は直後の `{{audit_matrix_table}}`（`_build_audit_matrix_table`）に
    そのまま埋め込んでおり、ここでは同じ集計結果（audit_matrix.counts）を1箇所から
    取得して件数だけ載せる。matrix_rows が無ければ（審査結果を渡されなかった呼び出し等）
    何も出さない。
    """
    if not matrix_rows:
        return ""
    from measurement_design.review.audit_matrix import counts as _matrix_counts

    c = _matrix_counts(matrix_rows)
    total = len(matrix_rows)
    return (
        f"**検査項目の全体像:** 機械判定できる{total}項目のうち、"
        f"×{c['ng']}件が根拠のある不備／△{c['warn']}件が要確認・未評価／○{c['ok']}件が記載した確認範囲で問題未検出、"
        "という結果でした。項目ごとの一覧はこの下の表のとおりです。"
        "以下の章では、そのうち対応方針まで説明が必要な論点を掘り下げます。"
    )


def _build_audit_matrix_table(matrix_rows: list[dict] | None) -> str:
    """検査項目の一覧（○△×の固定項目）を表にする.

    以前は同じ内容を別ファイル docs/audit-matrix.md に出し、check-report.md には件数だけを
    載せていたが、「見るレポートを1本にしたい」という要望を受けて本文に統合した。

    **指摘IDはこの表に出さない。** 以前は×・△の行のうち、判定関数が §2〜§5 の指摘を作る
    check_* 関数を直接呼んでいる項目に、対応する指摘IDへの参照を付けていた
    （`audit_matrix.add_violation_references`）。だがレポートの中でも最初に・一番目立つ形で
    読まれるこの表に指摘IDの羅列（`` `V-a1`・`V-b2`・`V-c3` など49件 ``）が残ることになり、
    「指摘IDの羅列が多すぎる」「IDいらない」という試用フィードバックへの対応が判定表にだけ
    及んでいなかった（§2〜§5・改善ロードマップからは先に外していた）。行は各 `_judge_*` が
    state 文に書く対象名・検出内容で引ける設計のままなので、判定表の状態は短い1行のままにし、
    詳しい内容（なぜ・どう直すか）は指摘側のセクションにだけ書く。内部処理ではIDを保持するが、
    読者向けレポートには出さない。

    matrix_rows が無ければ（審査結果を渡されなかった呼び出し等）何も出さない
    （`_build_matrix_summary` と同じ挙動）。
    """
    if not matrix_rows:
        return ""
    from measurement_design.review.audit_matrix import render_matrix

    return render_matrix(matrix_rows)


def _kpi_row_note(row: dict) -> str:
    """KPI表の「備考」列。「実装済み」「対応方針: —」という情報量のない表現はやめ、
    実際に確認が必要なものだけを書く.

    ユーザーの指摘（実データ検証後の差し戻し）: 「イベント名も分かってるんだったら、
    別にこの今の発火確認できましたはいらないかな」。イベント名が確定している行
    （`source` が `registered`/`ga4_key_event`/`key_event`）で発火0件は本物の計測漏れの
    疑いが強いので、そこだけは引き続き明確に指摘する。一方 `candidate`（イベント名が
    LLMの推定）で発火0件は、イベント名自体が外れている可能性があるため「計測漏れ」
    と決め打ちしない。
    """
    source = row.get("source", "")
    status = row.get("status", "")
    if source == "unresolved":
        return "要件未分解（要確認）"
    if status == "未実装":
        if source == "candidate":
            return "候補のイベント名では発火が見つからない（未確定）"
        # source は registered / ga4_key_event / key_event。イベント名が確定しているので、
        # 0件発火は本物の計測漏れの疑い（見落とさない）。
        return "登録済みイベントが0件発火（計測漏れの疑い）"
    return "—"


def _build_kpi_section(
    kpi_rows: list[dict] | None,
    outcome_candidates: list[dict] | None = None,
    completion_issues: list[dict] | None = None,
    target_comparison: list[dict] | None = None,
    name_mismatches: list[dict] | None = None,
) -> tuple[str, str]:
    """§1: (結果の要約文, 根拠データのブロック) を返す.

    kpi_rows は kpi_coverage.check_coverage（KPI/01のkey_events登録あり）または
    default_key_event_rows（登録なし。GA4のキーイベント設定を既定の答えとして使う）
    のいずれかの結果。呼び出し元（run.py）は常にどちらかを渡すため、
    None になるのは算出自体に失敗した場合のみ。

    KPIと受信イベントの対応・受信件数・登録名の不一致候補を表示する。
    completion_issues / target_comparison は既存呼び出しの互換引数として残すが、
    フォーム率や事業目標との対比は計測監査の対象外のため使用しない。

    「対象N件すべてで発火を確認できました」という言い切りも、イベント名が分かって
    いる場合はそもそも要らないという指摘を受けて廃止した。代わりに、このセクションで
    追加で分かったこと（成果らしいのにキーイベント未登録の候補）を結果文に書く。
    KPI×イベントの対応（どのKPIをどのイベントで測っているか）
    自体は前提情報として残す。
    """
    if kpi_rows is None:
        return "判定できませんでした（GA4データの取得状況を確認してください）。", _NO_EVIDENCE_NOTE
    if not kpi_rows:
        return "KPIの登録もGA4のキーイベントの登録も見つからず、評価できる情報がありませんでした。", _NO_EVIDENCE_NOTE

    outcome_candidates = outcome_candidates or []
    # 互換引数は受け取るが、成果率と事業目標の評価は基本分析の責務。
    name_mismatches = name_mismatches or []

    total = len(kpi_rows)
    zero_registered = sum(
        1 for r in kpi_rows
        if r.get("status") == "未実装" and r.get("source") in ("registered", "ga4_key_event", "key_event")
    )
    unresolved = sum(1 for r in kpi_rows if r.get("source") == "unresolved")
    # "ga4_key_event" は default_key_event_rows（KPI・01のkey_eventsどちらの登録も無く、
    # GA4管理画面のキーイベント設定をそのまま使った場合）だけが付ける source。
    # かつては kpi_id の有無で判定していたが、01の key_events から作った仮KPI（source
    # "key_event"）も kpi_id="" になるため誤って一致していた（key_events はユーザーが
    # 01に登録した値であり、「KPIの個別登録が見つからなかった」という以下の文言は誤り）。
    using_default = all(r.get("source") == "ga4_key_event" for r in kpi_rows)
    has_candidate = any(r.get("source") == "candidate" for r in kpi_rows)
    lead = (
        "KPIの個別登録が見つからなかったため、GA4に設定されているキーイベントをそのまま成果として使っています。"
        if using_default else ""
    )

    findings = []
    if zero_registered:
        findings.append(f"登録済みのイベントが1件も発火していないものが{zero_registered}件あります（計測漏れの疑い）")
        # 0件発火のうち、登録名と実際の送信名が食い違っているだけの疑いがあるものを
        # 別途照合する（一番効く指摘が「0件発火」までしか伝わっていなかったため）。
        findings.append(
            f"うち{len(name_mismatches)}件は登録名と送信名が食い違っている可能性があります"
            if name_mismatches else "登録名と送信名の食い違いは見つかりませんでした"
        )
    if unresolved:
        findings.append(f"{unresolved}件はKPIから必要イベントを特定できていません")
    findings.append(
        f"成果らしいのにキーイベントに未登録の候補が{len(outcome_candidates)}件見つかりました"
        if outcome_candidates else "成果らしいイベントの未登録候補は見つかりませんでした"
    )
    result = f"{lead}対象{total}件のKPIとイベントの対応は下表のとおりです。" + "。".join(findings) + "。"
    if has_candidate:
        result += (
            " イベント名の登録が無いKPIについては、一般的な命名から候補を推定しています"
            "（確定した対応ではありません）。"
        )

    rows = []
    for r in kpi_rows:
        event_cell = f"{'（候補）' if r.get('source') == 'candidate' else ''}{r.get('event', '')}"
        count = r.get("count")
        count_cell = f"{count:,}件" if count is not None else "—"
        note = _kpi_row_note(r)
        # source="key_event"（01の key_events から作った仮KPI）は kpi_name が
        # イベント名の写しにすぎない。「KPI名」列に同じ値をもう一度出すと情報量が無く、
        # かつ「業務名として登録されている」かのような誤解を招くため「—」にする
        # （イベント名自体はこの行の「イベント名」列にすでに出ている）。
        kpi_name_cell = "—" if r.get("source") == "key_event" else r.get("kpi_name", "")
        rows.append(f"| {kpi_name_cell} | {event_cell} | {count_cell} | {note} |")

    headers = ["KPI名", "イベント名", "実績（直近30日）", "備考"]
    table_md = _table_or_note(headers, rows)
    blocks = [table_md]

    if name_mismatches:
        mismatch_rows = [
            f"| {m['kpi_name'] or '—'} | `{m['registered_event']}` | "
            + "・".join(f"`{c['event']}`（{c['count']:,}件）" for c in m["candidates"])
            + " |"
            for m in name_mismatches
        ]
        blocks.append(
            "\n**登録名と送信名の食い違いの疑い:**\n\n"
            "0件発火の登録済みイベントについて、似た名前で実際に発火しているイベントが"
            "無いかを`_`区切りの単語単位で照合しました（例: 登録が`generate_lead`、"
            "実際の送信が`gen_lead_form`のような接頭辞違い）。**単語単位の照合のため、"
            "たまたま単語の一部が重なるだけの無関係なイベントを拾っている可能性があります。"
            "実際に同じ成果を指しているかどうかは人の確認が必要です。**\n\n"
            + _table_or_note(
                ["KPI名", "登録名（0件発火）", "似た名前で発火しているイベント"], mismatch_rows
            )
        )

    if outcome_candidates:
        cand_rows = [
            f"| `{c['event']}` | {c['count']:,} | `{c['entry_event']}`（{c['entry_count']:,}件） | "
            "キーイベントに未登録（要確認） |"
            for c in outcome_candidates
        ]
        blocks.append(
            "\n**成果らしいのにキーイベント未登録の候補:**\n\n"
            "手前のイベントとの対応（`_form`→`_thanks`等の接尾辞のパターン）が取れているイベントのうち、"
            "GA4のキーイベントに登録されていないものです。事業上の成果に当たるかを確認してから登録を判断します。"
            "**接尾辞パターンに基づく推定のため、"
            "これに当たらない命名のイベントは拾えていない可能性があります。**登録すべきか、"
            "計測用の補助イベントとして残すかは判断が必要です。\n\n"
            + _table_or_note(
                ["イベント名", "直近30日件数", "手前のイベント", "対応"], cand_rows
            )
        )


    evidence = "\n\n".join(blocks)
    return result, evidence


# 命名規則の表で、同じ理由の行に付く根拠IDを列挙する上限。件数がここを超えると
# audit_matrix の判定表と同じ「IDの壁」になる（試用フィードバックで検出）。
_MAX_NAMING_ID_REFS = 3


def _naming_group_key(v: dict) -> str:
    """対象名をプレースホルダに戻した説明文を、同じ理由でまとめるための鍵にする.

    `naming_high_description` 等のテンプレート文は対象名だけが差し替わる作りなので、
    対象名を除けば「なぜ仕様外か」は同一になる。実データでは仕様外のハイフンを含む
    イベント名が49件同時に出るなど、同じ理由が大量に繰り返されることが多く、旧実装は
    1件=1行でそのまま49行を並べていた（試用フィードバックで検出:「対象イベントが
    全部羅列されるので見づらい」「要因に対して該当のイベント名を並べる見せ方の
    ほうが見やすい」）。

    説明文に対象名が literal に含まれない場合（テストの作り物データ等）はグルーピング
    が効かず、1件=1行のまま今までと同じ見た目になる（安全側のフォールバック）。
    """
    name = str(v.get("target_name", ""))
    desc = v.get("description", "") or ""
    if name and f"'{name}'" in desc:
        desc = desc.replace(f"'{name}'", "'{}'")
    return f"{v.get('category', '')}\x1f{v.get('severity', '')}\x1f{desc}"


def _build_naming_section(ga4_violations: list[dict]) -> tuple[str, str, list[dict]]:
    """§3: (結果の要約文, 根拠データのブロック, 対象になった違反) を返す。

    命名規則違反の表は GA4 計測の指摘のみ。予約語衝突（Google予約のプレフィックスとの
    衝突）は §2 の調査内容で説明している範囲のため、命名規則・表記ゆれ・重複と同じ表に含める。
    3つ目の戻り値（対象になった違反）は、§4健全性検出が「§2・§3のどちらにも
    当たらなかった残り」を計算するときの除外リストとして使う。

    表は1件=1行ではなく、`_naming_group_key` で同じ理由の指摘を1行にまとめる。
    対象イベント名は全件を詰め込まず3件までの例に留め、全体件数を別に示す。

    **指摘IDはこの表に出さない。** 以前は「根拠ID」列に1行あたり最大
    `_MAX_NAMING_ID_REFS` 件まで例示していたが、49件を3件に絞っても「IDの羅列が
    多すぎる」「IDいらない」という試用フィードバックへの対応にはなっていなかった。
    対象イベント名（全件列挙）だけで行を特定できるため、IDは内部処理だけに残す。
    """
    rows_v = [
        v for v in ga4_violations
        if v.get("category") in ("命名規則", "表記ゆれ", "重複", "予約語衝突")
    ]
    reserved = [v for v in rows_v if v.get("category") == "予約語衝突"]
    high = [v for v in rows_v if v.get("category") == "命名規則" and v.get("severity") == "High"]
    low = [v for v in rows_v if v.get("category") == "命名規則" and v.get("severity") == "Low"]
    # 上の3つに数えなかった残り（表記ゆれ・重複や、LLM検出が出す想定外の severity など）。
    # id() で対象を除外し、内容が同じ2件を誤って二重カウント・欠落させない。
    _counted = {id(v) for v in (*reserved, *high, *low)}
    other = [v for v in rows_v if id(v) not in _counted]

    if not rows_v:
        result = "GA4の仕様外の名前・表記のばらつきは見つかりませんでした。"
    else:
        parts = []
        if high:
            parts.append(f"仕様外の名前が{len(high)}件")
        if reserved:
            parts.append(f"予約語との衝突が{len(reserved)}件")
        if low:
            parts.append(f"大文字・ハイフンを含む参考情報が{len(low)}件")
        if other:
            parts.append(f"表記のばらつき・重複が{len(other)}件")
        result = "・".join(parts) + "見つかりました。"

    groups: dict[str, list[dict]] = {}
    for v in rows_v:
        groups.setdefault(_naming_group_key(v), []).append(v)

    rows = []
    for members in groups.values():
        rep = members[0]
        severity = rep.get("severity", "")
        examples = []
        for member in members[:3]:
            name = member.get("target_name", "")
            fix = (member.get("suggested_fix") or "").strip()
            if severity != "Low" and fix:
                examples.append(f"`{name}` → `{fix}`")
            else:
                examples.append(f"`{name}`")
        examples_cell = "・".join(examples)
        if len(members) > 3:
            examples_cell += f" ほか{len(members) - 3}件"
        description = _clean_cell(rep.get("description", ""))
        target_name = str(rep.get("target_name", ""))
        # イベント名自体は右の「例」列へ出すため、説明列からは除く。
        # 単純に「対象イベント」へ置換すると「イベント名 対象イベント に」のような
        # 不自然な文になるため、前後の助詞までまとめて整える。
        description = description.replace(f"イベント名 '{target_name}' に", "イベント名に")
        description = description.replace(f"イベント名 '{target_name}' は", "イベント名は")
        description = description.replace(f"'{target_name}'", "対象イベント")
        rows.append(
            f"| {len(members)}件 | {description} | {examples_cell} | {severity} |"
        )
    evidence = _table_or_note(["件数", "内容", "例（最大3件）", "重要度"], rows)
    return result, evidence, rows_v


def _build_param_section(violations: list[dict], review_data: dict) -> tuple[str, str, str, list[dict]]:
    """§4: (調査内容, 結果の要約文, 根拠データのブロック, 対象になった違反) を返す.

    対象は GA4 のカスタムディメンション／カスタム指標（登録済みパラメータ）の命名・重複。
    「なし」の一言だけでは、検査対象が0件だったのか、対象はあったが問題が無かったのかが
    分からなかったため、登録件数を必ず出す。
    4つ目の戻り値（対象になった違反）は §2 と同様、§4健全性検出の除外リストに使う。
    """
    cd = review_data.get("ga4", {}).get("custom_definitions", {})
    dims = len(cd.get("dimensions") or [])
    mets = len(cd.get("metrics") or [])
    scope = (
        f"GA4に登録されているカスタムディメンション{dims}件・カスタム指標{mets}件を対象に、"
        "命名（使用可能文字・大文字表記）と重複登録を検査しました。"
    )

    param_violations = [v for v in violations if v.get("target_kind") == "parameter"]
    if dims + mets == 0:
        result = "カスタムディメンション・カスタム指標が登録されていません（検査対象が0件でした）。"
    elif not param_violations:
        result = f"登録済みの{dims + mets}件に、命名・重複の問題は見つかりませんでした。"
    else:
        result = f"登録済みの{dims + mets}件のうち、{len(param_violations)}件の指摘が見つかりました。"

    # 1列目はイベント名ではなくスコープ（EVENT/USER）。パラメータはイベントに限らず
    # ユーザースコープでも登録されるため、対象を正しく表す見出しにしている。
    # 指摘IDはこの表に出さない（§2と同じ理由。内部処理だけに残す）。
    rows = [
        f"| {v.get('scope') or '—'} | {_clean_cell(v['target_name'])} | "
        f"{_clean_cell(v['description'])} | {_clean_cell(v.get('suggested_fix', ''))} |"
        for v in param_violations
    ]
    evidence = _table_or_note(["スコープ", "パラメータ名", "問題内容", "修正案"], rows)
    return scope, result, evidence, param_violations


def _build_health_section(violations: list[dict]) -> tuple[str, str]:
    """§2: (結果の要約文, 根拠データのブロック) を返す。

    §3（命名規則）・§4（パラメータ）のどちらにも当たらなかった GA4 側の指摘の受け皿。
    health_checks.py による実測値ベースの健全性検出（計測漏れ・データ品質・発火タイミング
    など）がここに入る。この受け皿が無いと、これらの指摘は改善ロードマップと
    旧「指摘詳細」にしか出ない、という漏れが実データで見つかった。
    """
    if not violations:
        return "実測値からの健全性チェックで、指摘は見つかりませんでした。", _NO_EVIDENCE_NOTE

    result = f"実測値からの健全性チェックで、{len(violations)}件の指摘が見つかりました。"
    # 指摘IDはこの表に出さない（§2と同じ理由。内部処理だけに残す）。
    rows = [
        f"| {_clean_cell(v.get('target_name', ''))} | "
        f"{_clean_cell(v.get('description', ''))} | {_clean_cell(v.get('suggested_fix', ''))} | "
        f"{v.get('severity', '')} |"
        for v in sorted(violations, key=lambda x: _SEV_ORDER.get(x.get("severity", "Low"), 3))
    ]
    evidence = _table_or_note(["対象", "内容", "修正案", "重要度"], rows)
    return result, evidence


def _build_gtm_config_section(violations: list[dict]) -> tuple[str, str]:
    """§5: (結果の要約文, 根拠データのブロック) を返す。

    GTMコンテナの設定そのものの指摘（残骸候補・二重計測・値の使い回し・タグ量産など。
    diagnoser.gtm_mechanical_checks と health_checks.py のGTM側チェック）。
    §6「GTMとGA4の不整合」はGTMが送るイベント名とGA4受信イベントの突合であり、
    ここで扱うタグ構成そのものの健全性とは観点が違うため分けている
    （§6は violations リストを使わない別の突合結果なので、こことは重複しない）。
    """
    if not violations:
        return "GTMコンテナの設定に、指摘は見つかりませんでした。", _NO_EVIDENCE_NOTE

    result = f"GTMコンテナの設定に、{len(violations)}件の指摘が見つかりました。"
    # 指摘IDはこの表に出さない（§2と同じ理由。内部処理だけに残す）。
    rows = [
        f"| {_clean_cell(v.get('target_name', ''))} | "
        f"{_clean_cell(v.get('description', ''))} | {_clean_cell(v.get('suggested_fix', ''))} | "
        f"{v.get('severity', '')} |"
        for v in sorted(violations, key=lambda x: _SEV_ORDER.get(x.get("severity", "Low"), 3))
    ]
    evidence = _table_or_note(["対象", "内容", "修正案", "重要度"], rows)
    return result, evidence


def _build_gtm_mismatch_section(review_data: dict) -> tuple[str, str]:
    """§6: (結果の要約文, 根拠データのブロック) を返す。

    GTMが送信するGA4イベント名と、GA4で実際に受信したイベントを突合する。
    GTMデータ（phase3）が無ければ「未評価」を表示し、ユーザーにID指定を促す。
    """
    gtm = review_data.get("gtm")
    if not gtm:
        note = (
            "GTM未取得のため未評価です。実行時に GTM アカウントID・コンテナID"
            "（--gtm-account / --gtm-container）を指定してください（不明な場合は担当者に確認）。"
        )
        return "GTMを取得していないため未評価です。", note

    received = {e.get("name", "") for e in review_data.get("ga4", {}).get("events_observed", [])}
    if "ga4_event_tags" not in gtm or not received:
        return "GTMとGA4の突合は未評価です。", "送信イベント名またはGA4受信実績が確認できていません。"
    rows = []
    for t in gtm.get("ga4_event_tags", []):
        ev = (t.get("event_name", "") or "").strip()
        tag = t.get("tag_name", "")
        if not ev:
            continue
        if "{{" in ev:
            # イベント名がGTM変数（動的）→ 静的には実イベント名が定まらず突合不可
            rows.append(
                f"| {tag} | （GTM変数・動的） | 判定不可 | "
                "イベント名が変数で送信されるため静的に受信突合できない（実発火イベントを手動確認） |"
            )
        elif ev not in received:
            rows.append(
                f"| {tag} | {ev} | （受信なし） | "
                "GTMに送信設定があるが取得期間のGA4受信記録はない（操作の未発生・未発火・取得範囲を確認） |"
            )
    evidence = _table_or_note(["GTMタグ名", "GTM内イベント名", "GA4受信イベント名", "不整合内容"], rows)
    if not rows:
        return "静的なイベント名の突合で不一致は検出されませんでした。実際の発火条件は別途確認が必要です。", evidence
    return f"{len(rows)}件に受信記録の未確認または動的イベント名による判定保留があります。", evidence


# 「確認できなかったこと」に集める、判定表の state 文の目印。権限が無い／データが
# 取れていない／取得上限に達した／機械では判定できない、のいずれかを指す。
# **単に「上限」を含む、では拾わない。** `_judge_retention` の「14ヶ月（上限）」
# （＝データ保持を上限まで伸ばせている、という良い状態）を誤って「確認できなかった
# こと」に含めてしまう（試して確認済み）。「取得上限」（GA4/GTM APIの取得件数の
# 上限）という複合語に絞ることで、この誤検出を避ける。
_UNRESOLVED_MARKERS = ("取れていない", "取得していない", "権限が無く", "取得上限", "判定できません", "確認できていない", "未評価", "未確認", "未検証")


def _build_unresolved_section(matrix_rows: list[dict] | None, review_data: dict) -> str:
    """§7「確認できなかったこと」の根拠データのブロックを返す.

    権限が無くて見られなかったもの、取得上限に達したもの、機械では判定できなかった
    ものは、検査項目の一覧（○△×）の各行の状態文に散らばっていて1か所にまとまって
    いなかった（試用フィードバックで検出）。ここに集約する。様式は基本分析レポート
    （`parameter_management/templates/checklist.template.md` の「不明・追加確認事項」）
    に合わせ、確認が要る項目を箇条書きで1か所に集める。

    matrix_rows の state 文に `_UNRESOLVED_MARKERS` のいずれかを含む行を拾う
    （文言ベースの簡易な判定のため、判定関数側が別の言い回しを使うと拾えないことが
    ある。完全な網羅は保証しない）。GTM未取得は§6にも出るが、影響範囲が§5・§6の
    両方に及ぶため、ここでも明示する。
    """
    items = []
    if matrix_rows:
        for row in matrix_rows:
            state = row.get("state", "")
            if any(marker in state for marker in _UNRESOLVED_MARKERS):
                items.append(f"- **{row.get('area', '')}: {row.get('name', '')}** — {state}")

    if not review_data.get("gtm"):
        items.append(
            "- **GTM設定** — GTMコンテナを取得していないため、GTM設定の指摘（§5）と"
            "GTMとGA4の不整合（§6）は未評価です。"
        )

    if not items:
        return "権限・取得上限・機械判定の限界による確認漏れは見つかりませんでした。"
    return "\n".join(items)


def _roadmap_action_text(v: dict) -> str:
    """ロードマップの「対応内容」を、対象名と修正案の生の並びではなく1つの文にする.

    旧実装は `f"{target_name}: {suggested_fix}"` の生の形のままで、文になっていない
    という指摘があった。GTM/健全性検出の指摘は suggested_fix が元々「〜する」という
    対応の文になっているので、そのまま使う。命名（event/parameter）の指摘は
    target_name と suggested_fix を組み合わせて「`旧名` を `新名` に変更する」という
    文を組み立てる。
    """
    fix = (v.get("suggested_fix") or "").strip()
    name = v.get("target_name", "")
    kind = v.get("target_kind", "")

    if not fix:
        return f"「{name}」を確認する"
    if fix.startswith(("（", "(")):
        # 修正案が具体的な値ではなく注記（手動命名が必要 等）のケース
        note = fix.strip("（）()")
        return f"「{name}」の表記を見直す（{note}）"
    if kind == "event":
        return f"イベント名 `{name}` を `{fix}` に変更する場合は、既存の集計・広告連携への依存を先に確認する"
    if kind == "parameter":
        return f"パラメータ名 `{name}` を `{fix}` に変更する場合は、参照するタグ・集計への依存を先に確認する"
    # GTMタグ・健全性検出の指摘は suggested_fix が既に対応として読める文になっている。
    # ただし対象名を落とすと、同じ対応文の行が複数並んだときにどれの話か分からなくなる
    # （例: 二重計測の指摘は 2 件とも「重複であればどちらかに一本化する」になる）。
    if name:
        return f"「{name}」について、{fix}"
    return fix


def _roadmap_group_action_text(members: list[dict]) -> str:
    """グループ化した行（同じ理由の指摘が複数件）の「対応内容」.

    個々の対象名・修正案（`旧名 → 新名`）は§2〜§5の表に1件=1行で残っているため、
    ここでは「何を・何件」レベルの要約に留める（49件分の`旧名→新名`をこの1行に
    詰め込むと、まさにロードマップが埋まっていた元の問題を1行の中で再現してしまう）。
    """
    rep = members[0]
    kind = rep.get("target_kind", "")
    n = len(members)
    if kind == "event":
        return f"既存の集計・広告連携への依存を確認してからイベント名の表記統一を判断する（対象{n}件）"
    if kind == "parameter":
        return f"参照するタグ・集計への依存を確認してからパラメータ名の表記統一を判断する（対象{n}件）"
    fix = (rep.get("suggested_fix") or "").strip()
    if fix.startswith(("（", "(")):
        note = fix.strip("（）()")
        return f"表記を見直す（{note}。対象{n}件）"
    return f"{fix}（対象{n}件）" if fix else f"内容を確認する（対象{n}件）"


def _build_roadmap(violations: list[dict]) -> tuple[str, str]:
    """§8: (結果の要約文, 根拠データのブロック) を返す。フェーズ順の改善ロードマップ.

    対応の順序と依存関係を示す一覧にする（フェーズ・優先度・対象・対応内容）。
    説明文（いま何が起きているか）は §2〜§5 のいずれかのセクションに必ず出ているため、
    ここでは繰り返さない（旧実装は「なぜ直すか」列に同じ説明文を複製していたため、
    同じ指摘がセクションをまたいで最大3回出る不具合の一因になっていた）。
    担当・対応期間はサイトの運用体制次第で機械的に決め打ちできる根拠が無いため、
    列として持たない。

    **指摘IDはこの表に出さない。** 以前は「根拠」列にIDを並べていたが、件数が
    多いと`` `V-a1`・`V-b2`・`V-c3` など49件 ``のようなID自体の壁になり、「IDの
    羅列が多すぎる」「IDいらない」という試用フィードバックを受けた（§2〜§5の
    根拠データの表からも同じ理由でID列を外している）。この表の「対象」列（対象名）
    と§2〜§5の表の対象名は同じ文字列で引けるため、IDが無くても対応する行を
    見つけられる。指摘IDは内部処理にだけ残し、レポートには出さない。

    **同じ理由の指摘は1行にまとめる。** 命名規則の表と同じグルーピング
    （`_naming_group_key`）をここにも適用する。旧実装は1件=1行のまま重要度順に
    並べていたため、実データでは54件中49件が同一の命名指摘（ハイフン表記）で
    埋まり、「上から潰せば直る」というロードマップの役目を果たしていなかった
    （試用フィードバックで検出）。対象名が多い行は§2の表と同じ上限
    （`_MAX_NAMING_ID_REFS`）で例示に切り詰める（全件は各セクションの表に必ず残る）。
    """
    actionable = [
        v for v in violations
        if not (v.get("category") == "命名規則" and v.get("severity") == "Low")
    ]
    if not actionable:
        return "改善項目はありませんでした。", _NO_EVIDENCE_NOTE

    def _phase(v: dict) -> str:
        if v.get("category") in {"命名規則", "表記ゆれ", "重複", "予約語衝突", "パラメータ命名規則", "パラメータ重複"}:
            return "2. 命名・定義の修正"
        # 調査・対象確定や、実測値を誤らせる可能性がある指摘は先に扱う。
        # GTMにあるという理由だけでフェーズ3へ送ると、棚卸しが命名変更より後になる。
        if v.get("category") in {
            "判定不能", "発火範囲の確認", "GTMタグ量産", "二重計測", "値の使い回し",
            "計測の停止リスク", "多重計上", "多重発火", "GTM・GA4突合", "設定の陳腐化",
        }:
            return "1. 現状の棚卸し・誤計測の修正"
        if v.get("location") == "GTM":
            return "3. GTM内の整理"
        return "1. 現状の棚卸し・誤計測の修正"

    def _roadmap_group_key(v: dict):
        if v.get("category") in {"命名規則", "表記ゆれ", "パラメータ命名規則"}:
            return ("naming", _naming_group_key(v))
        return (
            "action", _phase(v), v.get("location"), v.get("category"),
            v.get("severity"), v.get("target_name"), v.get("suggested_fix"),
        )

    groups: dict[tuple, list[dict]] = {}
    for v in actionable:
        groups.setdefault(_roadmap_group_key(v), []).append(v)

    def _group_severity(members: list[dict]) -> str:
        # グループ内で最も重要度が高い（`_SEV_ORDER` の値が小さい）ものを代表値にする。
        return min(members, key=lambda m: _SEV_ORDER.get(m.get("severity", "Low"), 3)).get("severity", "Low")

    ordered_groups = sorted(
        groups.values(),
        key=lambda members: (_phase(members[0]), _SEV_ORDER.get(_group_severity(members), 3)),
    )

    rows = []
    for members in ordered_groups:
        sev = _group_severity(members)
        rep = members[0]
        action = _roadmap_action_text(rep) if len(members) == 1 else _roadmap_group_action_text(members)

        names = sorted({m.get("target_name", "") for m in members if m.get("target_name")})
        if len(names) > _MAX_NAMING_ID_REFS:
            shown = "・".join(f"`{n}`" for n in names[:_MAX_NAMING_ID_REFS])
            target = f"{shown} など{len(names)}件"
        else:
            target = "・".join(f"`{n}`" for n in names) if names else "—"

        rows.append(f"| {_phase(rep)} | {sev} | {target} | {action} |")

    result = (
        "フェーズは 1 → 2 → 3 の順です。フェーズ1で現状と誤計測の対象を確定してから"
        "フェーズ2の命名・定義を決め、その内容を前提にフェーズ3のGTM整理へ進みます。"
        f"同一フェーズ内は重要度（Critical > High > Medium > Low）の順に、同じ理由の指摘をまとめて{len(rows)}件"
        f"（対応対象は{len(actionable)}件）を並べました。大文字・ハイフンだけのLowは参考情報のため除外しています。"
        "重要度は検出ルール上の目安です。"
        "実際の影響を確認し、修正順を決めてください。詳しい内容は「要対応・要確認」の"
        "同じ対象名を確認してください。"
    )
    evidence = _table_or_note(["フェーズ", "重要度", "対象", "対応内容"], rows)
    return result, evidence


def _clean_cell(text: str) -> str:
    """表のセルに入れる文字列を整える（改行・パイプの巻き込みだけ処理し、長さは切らない）.

    以前は70字で丸めて表の下に全文をもう一度並べていたが、同じ文章が2回出て
    元より読みにくくなっていた。Markdown表はHTML化すると自動で折り返す
    （`table.s-table td` に `white-space: nowrap` を指定していないことを確認済み）ため、
    長文でも省略せずに1つの表に収める。
    """
    return (text or "").replace("\n", " ").replace("|", "／").strip()


def save_check_report(content: str, docs_dir: Path) -> Path:
    """チェックレポートを docs_dir/check-report.md に保存する.

    上書き前の退避（規約2）は呼び出し元（run.py cmd_review）が
    `archive_check_report_before_overwrite` で行う。この関数自体は
    「与えられた内容で書く」だけの責務にとどめる。
    """
    docs_dir.mkdir(parents=True, exist_ok=True)
    out = docs_dir / "check-report.md"
    out.write_text(content, encoding="utf-8")
    return out


# check-report.md（と report_export_bridge が作る .html/.pdf/.docx/.xlsx）は
# review 実行のたびに機械が作り直す生成物。docs/standard-run-order.md の規約2
# （上書き前に `_past/` へ退避する）の対象であり、02・03・06と同じ形に揃える。
_ARCHIVABLE_REPORT_EXTS = ("md", "html", "pdf", "docx", "xlsx")


def archive_check_report_before_overwrite(docs_dir: Path, stem: str = "check-report") -> list[Path]:
    """`{stem}.{ext}`（ext は _ARCHIVABLE_REPORT_EXTS）の生成物を、上書き前に
    `_past/{YYYY-MM-DD_HHMMSS}_{元のファイル名}` へリネーム退避する（規約2）。

    ファイル名は `check-report.{ext}` の完全一致のみを対象にする。
    `check-report-notes.md`（人が書き込む対応メモ）・`check-report.before-notes-file.md`
    （下の ensure_check_report_notes が過去に作った一度きりの移行用バックアップ）は
    ハイフンで続く別名であり、この一致条件に当たらないため対象に含まれない
    （退避も上書きもしない。「あれば絶対に触らない」を守る）。

    対象が1件も無ければ何もしない（初回実行）。同一実行内で複数ファイル
    （.md と .html 等）を退避する場合は同じタイムスタンプを使う。
    """
    existing = [
        docs_dir / f"{stem}.{ext}"
        for ext in _ARCHIVABLE_REPORT_EXTS
        if (docs_dir / f"{stem}.{ext}").exists()
    ]
    if not existing:
        return []

    past_dir = docs_dir / "_past"
    past_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    archived = []
    for path in existing:
        dest = past_dir / f"{timestamp}_{path.name}"
        suffix = 2
        while dest.exists():
            # 同一秒内に複数回退避される（テスト等）場合の衝突回避。
            dest = past_dir / f"{timestamp}_{suffix}_{path.name}"
            suffix += 1
        path.replace(dest)
        archived.append(dest)
    return archived


# 対策として、人が書き込む場所を check-report.md と分離する。このファイルは
# 「無ければ作る。あれば絶対に触らない」を徹底する（機械はここへは一切書き込まない。
# docs/findings.md と同じ「人専用ファイル」の扱い）。
CHECK_REPORT_NOTES_FILE = "check-report-notes.md"

_NOTES_TEMPLATE = """# 計測チェック 対応メモ — {client}

**このファイルは `review` を再実行しても上書きされません。**
`check-report.md` は毎回まっさらに再生成される成果物です。
指摘への確認・対応の状況、クライアントへの確認内容と回答は、ここに書いてください。

## 書き方

`check-report.md` の章名と対象名ごとに見出しを立てて書きます。レポートを再生成しても
追いかけやすいよう、イベント名・パラメータ名・タグ名などの対象名を省略しないでください。

例:

```
## 3. パラメータ — `sample_parameter`
- 確認日: YYYY-MM-DD
- 状態: 対応済み / 未対応 / 保留
- メモ: 関係者へ確認した内容・回答をここに書く
```

---

"""

# 旧方式（通し番号）のIDパターン。プレフィックス + ちょうど3桁の数字
# （`V-001` `V-P-010` `V-H-001` `V-G-003` `V-LLM-001` 等）。新方式は内容から決まる
# 16進6桁のIDで、桁数が違うためこの正規表現には一致しない
# （\d{3} の直後に単語境界を要求するため、6桁の数字が並んでも3桁目の後は
# まだ数字が続き境界にならず、誤って新IDを「旧IDが残っている」と拾わない）。
_LEGACY_ID_RE = re.compile(r"\bV-(?:P-|H-|G-|LLM-)?\d{3}\b")


def notes_file_has_legacy_ids(notes_path: Path) -> bool:
    """対応メモ（`check-report-notes.md`）に旧方式の通し番号IDへの言及が残っているか.

    指摘IDを内容から決まる安定した方式（`violation_id.make_id`）に変更したため、
    今後 `check-report.md` に旧方式のID（`V-002` のような3桁の通し番号）は
    二度と現れない。既存の対応メモに残っていても書き換えはしない
    （`ensure_check_report_notes` の「あれば絶対に触らない」原則を保つため）が、
    呼び出し側（`run.py`）が案内を出すかどうかの判定に使う。旧IDの記述が
    メモから無くなれば（書き換えれば）この判定も自然に False になり、
    案内は出なくなる。
    """
    if not notes_path.exists():
        return False
    return bool(_LEGACY_ID_RE.search(notes_path.read_text(encoding="utf-8")))


def ensure_check_report_notes(docs_dir: Path, client: str) -> tuple[Path, bool]:
    """人が書き込む対応メモファイルを用意する。**既にあれば何もしない。**

    戻り値: (notes_path, 今回新規作成したか)

    このファイル導入前から運用していたクライアントは check-report.md 本体に
    書き足していた可能性がある。かつてはこの関数が、notes ファイルを初めて作る
    タイミングで既存の check-report.md を `check-report.before-notes-file.md` へ
    一度だけ退避していた。いまは `archive_check_report_before_overwrite`（規約2の
    `_past/` 退避）が review 実行のたびに check-report.md の旧版を退避するため、
    このファイル固有の一度きりの移行措置は不要になった（notes ファイルを初めて
    作る回の check-report.md も、他の回と同じように `_past/` へ回る）。
    """
    docs_dir.mkdir(parents=True, exist_ok=True)
    notes_path = docs_dir / CHECK_REPORT_NOTES_FILE
    if notes_path.exists():
        return notes_path, False

    notes_path.write_text(_NOTES_TEMPLATE.format(client=client), encoding="utf-8")
    return notes_path, True
