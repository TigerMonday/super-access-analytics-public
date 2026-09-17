"""コンテキストストアへの書き戻しヘルパー。

他エージェントが分析・レビュー完了時に呼ぶ最小 API:

    append_finding(client_id, agent, summary, findings, outputs)

`context/<client_id>/analysis-history.yaml` の `entries` 末尾に1エントリ追記する。
ファイルや `entries` キーが無ければ新規作成する（運用初期の未記入を許容する方針は
loader.py と揃える）。client_id は loader の別名解決を通す。

未登録クライアントに「最低限必要な情報だけ」を保存する API（軽量受付フロー用）:

    ensure_client_registered(client_id, name)   # 未登録なら最小の profile.yaml を作る
    save_measurement_ids(client_id, ga4_property_id=..., search_console_site_url=..., bigquery_project_id=..., bigquery_dataset=...)
    save_kpi_info(client_id, key_events=[...], kpis=[...])
    save_kpi_priorities(client_id, priorities={"kpi_002": 1, "kpi_001": 2})   # 複数CVがあるとき、どれを主に見るか（1が最優先）
    save_site_segments(client_id, segments=[...])   # 分析対象の定義（役割別セクションの切り分け。01/03が気づいて提案し、確認後に保存。segment_idでupsert）
    save_query_param_preference(client_id, include_query_params=True)   # ランディングページ集計でクエリを含めるか（既定False=パスのみ）
    save_output_format_preference(client_id, output_formats=[...], google_doc_url=..., google_sheet_url=...)   # 成果物の書き出し先（空リスト=MDのみ。gdoc/gsheetを含める場合はURLも必須）
    save_brand_preferences(client_id, accent_color=..., logo_path=...)   # HTML/PDF成果物のブランドカラー・ロゴ（common/report_exportの--accent-color/--logoに渡す値）
    save_external_ai_approval(client_id, provider)   # 外部AIへの送信承認（クライアント・送信先ごとに初回だけ）
    save_business_profile(client_id, site_url=..., industry=..., business=..., business_model=...)   # サイトURL・役割・業種・toB/toCの前提（分析の解釈精度を上げる。サイトを読んだ推測はユーザー確認後にのみ渡すこと）
    save_customer_understanding(client_id, three_c=..., personas=..., ...)   # 3C・ペルソナ・態度変容ジャーニー（03完了時）。他と異なり全体を丸ごと置き換える（下記docstring参照）

いずれも既存ファイル・既存キーを壊さない（追記・更新であり、全消し上書きはしない）。
**例外は `save_customer_understanding` だけ**：3C・ペルソナ・ジャーニーは03が1回の実行で一式作り直す性質のため、
`customer-understanding.yaml` の中身を丸ごと置き換える（関数のdocstring参照）。
`01_context_management/prompts/context-manager.md` のフル対話登録とは別の、
エージェントごとに最小限だけ聞く受付フロー（docs/standard-run-order.md 参照）から呼ばれる。
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import yaml

from context_store import schema
from context_store.loader import CONTEXT_DIR, _CLIENT_ID_RE, resolve_client_id


def _atomic_write_yaml(path: Path, data: dict) -> None:
    """同じディレクトリへ一時保存してから置換し、途中終了でYAMLを壊さない。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            yaml.safe_dump(data, stream, allow_unicode=True, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


@contextmanager
def _exclusive_lock(path: Path, timeout: float = 10.0):
    """read-modify-write 用の簡易プロセス間ロック。"""
    lock_dir = path.with_name(path.name + ".lock")
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock_dir.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"別プロセスが更新中のため待機時間を超えました: {path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        lock_dir.rmdir()


def _load_yaml_or_backup(path: Path, *, what: str) -> dict:
    """YAML を dict として読む。パース失敗時は元ファイルを `.broken-<日時>` に退避し {} を返す。

    ファイルが無ければ {} を返す。読めた内容が dict でなければ {} を返す（壊れた形式として扱う）。
    書き戻し系の関数（append_finding / save_* / ensure_client_registered）で共通に使う。
    """
    if not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except yaml.YAMLError as e:
        backup_path = path.with_name(
            path.name + ".broken-" + _dt.datetime.now().strftime("%Y%m%d%H%M%S")
        )
        path.rename(backup_path)
        print(
            f"[context_store] {what} のパース失敗。元ファイルを {backup_path.name} に退避し、"
            f"新規として書き直します: {path} ({e})",
            file=sys.stderr,
        )
        return {}


def _resolved_client_root(client_id: str, context_dir: Path | None) -> tuple[str, Path]:
    """client_id を検証・別名解決し、(正規id, context/<正規id>/ のパス) を返す。"""
    base_dir = context_dir or CONTEXT_DIR
    resolved_id = resolve_client_id(client_id, base_dir)
    if not _CLIENT_ID_RE.match(resolved_id):
        raise ValueError(
            f"不正な client_id: {resolved_id!r}（英数字・ハイフン・アンダースコアのみ）"
        )
    return resolved_id, base_dir / resolved_id


def ensure_client_registered(
    client_id: str,
    name: str,
    context_dir: Path | None = None,
) -> Path:
    """未登録クライアントに最小の `profile.yaml` を作る（軽量受付フロー用）。

    - `profile.yaml` が無ければ `client.client_id` / `client.name` だけを埋めて新規作成する。
      業種・ターゲット像・背景などは書かない（フル登録は別途 01 登録フローに委ねる）。
    - 既に `profile.yaml` があれば **上書きしない**。`client.name` が空欄のときだけ埋める。
    - client_id は新規登録の入口のため別名解決はしない（既存クライアントの表記ゆれ更新は
      呼び出し側で正規 client_id を使うこと）。
    - `name` が空、または `client_id` と同一の値のときは、URL・サイト・GA4情報から
      表示名を導出できているか呼び出し側に気づかせるため stderr に警告を出す
      （エラーにはしない。client_id をそのままサイト名として使いたい正当なケースもあるため、
      書き込み自体は止めない）。

    戻り値: `profile.yaml` のパス。
    """
    base_dir = context_dir or CONTEXT_DIR
    if not _CLIENT_ID_RE.match(client_id):
        raise ValueError(
            f"不正な client_id: {client_id!r}（英数字・ハイフン・アンダースコアのみ）"
        )
    if not name:
        print(
            f"[context_store] ensure_client_registered: name（サイト名）が空です。"
            f"client_id={client_id!r} だけでは後から何のサイトか分からなくなります。"
            f"対象URL・サイト・GA4情報から表示名を導出し、必要な場合だけ利用者に確認してください。",
            file=sys.stderr,
        )
    elif name == client_id:
        print(
            f"[context_store] ensure_client_registered: name（サイト名）が client_id と同じ値 "
            f"{name!r} です。表示名を導出せず client_id をそのまま使っていませんか。"
            f"意図的に同じ値にする場合はこの警告は無視してかまいません。",
            file=sys.stderr,
        )
    client_root = base_dir / client_id
    client_root.mkdir(parents=True, exist_ok=True)
    path = client_root / schema.YAML_FILES["profile"]
    data = _load_yaml_or_backup(path, what="profile.yaml")

    client = data.get("client")
    if not isinstance(client, dict):
        client = {}
    if not client.get("client_id"):
        client["client_id"] = client_id
    if not client.get("name") and name:
        client["name"] = name
    data["client"] = client
    data.setdefault("aliases", [])

    _atomic_write_yaml(path, data)
    return path


def save_measurement_ids(
    client_id: str,
    *,
    ga4_property_id: str | None = None,
    gtm_account_id: str | None = None,
    gtm_container_id: str | None = None,
    search_console_site_url: str | None = None,
    bigquery_project_id: str | None = None,
    bigquery_dataset: str | None = None,
    context_dir: Path | None = None,
) -> Path:
    """`measurement.yaml` に GA4/GTM/Search Console/BigQueryの識別情報を保存する。

    渡した項目だけ更新し、`search_console` / `bigquery` / `ad_accounts` など他ブロックや
    未指定の項目（例: `ga4.auth_method`）は保持する。値が空文字/None の引数は無視する。

    戻り値: `measurement.yaml` のパス。
    """
    resolved_id, client_root = _resolved_client_root(client_id, context_dir)
    client_root.mkdir(parents=True, exist_ok=True)
    path = client_root / schema.YAML_FILES["measurement"]
    data = _load_yaml_or_backup(path, what="measurement.yaml")

    if ga4_property_id:
        ga4 = data.get("ga4")
        if not isinstance(ga4, dict):
            ga4 = {}
        ga4["property_id"] = str(ga4_property_id)
        ga4.setdefault("auth_method", "sa")
        data["ga4"] = ga4

    if gtm_account_id or gtm_container_id:
        gtm = data.get("gtm")
        if not isinstance(gtm, dict):
            gtm = {}
        if gtm_account_id:
            gtm["gtm_account_id"] = str(gtm_account_id)
        if gtm_container_id:
            gtm["gtm_container_id"] = str(gtm_container_id)
        data["gtm"] = gtm

    if search_console_site_url:
        search_console = data.get("search_console")
        if not isinstance(search_console, dict):
            search_console = {}
        search_console["site_url"] = str(search_console_site_url)
        data["search_console"] = search_console

    if bigquery_project_id or bigquery_dataset:
        bigquery = data.get("bigquery")
        if not isinstance(bigquery, dict):
            bigquery = {}
        if bigquery_project_id:
            bigquery["project_id"] = str(bigquery_project_id)
        if bigquery_dataset:
            bigquery["dataset"] = str(bigquery_dataset)
        data["bigquery"] = bigquery

    _atomic_write_yaml(path, data)
    return path


def save_kpi_info(
    client_id: str,
    *,
    key_events: list[str] | None = None,
    kpis: list[dict] | None = None,
    replace_key_events: bool = False,
    context_dir: Path | None = None,
) -> Path:
    """`kpis.yaml` に主要イベント（CV）・KPI を保存する（軽量受付フロー用）。

    - `key_events`: 既定では既存リストに追記する（重複はスキップ）。
      `replace_key_events=True` の場合は、渡した一覧で置き換える（空リストならクリア）。
    - `kpis`: `kpi_id` が既存と一致すれば該当エントリを更新（`dict.update`）、
      一致しなければ末尾に追加する。
    - どちらも既存の他エントリを消さない（全消し上書きはしない）。

    戻り値: `kpis.yaml` のパス。
    """
    resolved_id, client_root = _resolved_client_root(client_id, context_dir)
    client_root.mkdir(parents=True, exist_ok=True)
    path = client_root / schema.YAML_FILES["kpis"]
    data = _load_yaml_or_backup(path, what="kpis.yaml")

    if key_events is not None:
        normalized_events = []
        for ev in key_events:
            ev = str(ev).strip()
            if ev and ev not in normalized_events:
                normalized_events.append(ev)
        if replace_key_events:
            data["key_events"] = normalized_events
        elif normalized_events:
            existing_events = data.get("key_events")
            if not isinstance(existing_events, list):
                existing_events = []
            for ev in normalized_events:
                if ev not in existing_events:
                    existing_events.append(ev)
            data["key_events"] = existing_events

    if kpis:
        existing_kpis = data.get("kpis")
        if not isinstance(existing_kpis, list):
            existing_kpis = []
        by_kpi_id = {
            k.get("kpi_id"): i
            for i, k in enumerate(existing_kpis)
            if isinstance(k, dict) and k.get("kpi_id")
        }
        for kpi in kpis:
            if not isinstance(kpi, dict):
                continue
            kpi_id = kpi.get("kpi_id")
            if kpi_id and kpi_id in by_kpi_id:
                existing_kpis[by_kpi_id[kpi_id]].update(kpi)
            else:
                existing_kpis.append(kpi)
        data["kpis"] = existing_kpis

    _atomic_write_yaml(path, data)
    return path


def save_kpi_priorities(
    client_id: str,
    priorities: dict[str, int],
    context_dir: Path | None = None,
) -> Path:
    """既存の `kpis.yaml` の各KPIに `priority`（どれを主に見るか。1が最優先）を設定する。

    複数CVがあるクライアントで「どれが主か」を後から確認できたとき用の薄いラッパー
    （内部では `save_kpi_info(kpis=[...])` と同じ upsert 経路を通るため、他フィールドは
    変更しない）。`priorities` は `{kpi_id: priority}`（例: `{"kpi_002": 1, "kpi_001": 2}`）。

    - KPIが1件しかない場合に呼ぶ意味は無い（`ClientContext.primary_kpi` が優先度に関わらず
      その1件を返すため）が、呼んでも害は無い。
    - `kpi_id` が既存の `kpis.yaml` に無い場合は新規KPIとして追加されてしまう
      （`save_kpi_info` の upsert 仕様どおり）。呼び出し側は既存の `kpi_id` を指定すること。
    - 値の妥当性（重複していないか等）はここでは見ない。読み込み側の
      `schema.validate_kpi_priorities`（`ClientContext.validate()` 経由）が警告する。

    戻り値: `kpis.yaml` のパス。
    """
    kpis = [{"kpi_id": kpi_id, "priority": priority} for kpi_id, priority in priorities.items()]
    return save_kpi_info(client_id, kpis=kpis, context_dir=context_dir)


def save_site_segments(
    client_id: str,
    segments: list[dict],
    context_dir: Path | None = None,
) -> Path:
    """`site-segments.yaml` に分析対象の定義（役割の違うセクションの切り分け）を保存する。

    **利用者が最初に埋める入力欄ではない。** 01/03がGA4の実ページ一覧・パスの構造から
    「役割の違うセクションがありそう」と気づき、利用者に提案して確認が取れた結果だけを
    ここに保存する（例:「/media/ 配下が全体の6割を占めています。分けて集計しますか」→OK）。
    メディア（集客記事）のようにCVを直接狙っていないセクションを本体と混ぜて分析すると
    「新規のCVRが低すぎる」のような誤解釈につながる（数字自体は合っているのに解釈を誤る事故）。

    - `segment_id` が既存と一致すれば該当エントリを更新（`dict.update`）、一致しなければ末尾に追加する
      （`save_kpi_info` と同じ upsert 方式）。既存の他エントリ・他フィールドは消さない。
    - 各要素の形式は `schema/context-schema.md`「site-segments.yaml」節。最低限
      `segment_id` / `name`（役割の自由記述。「本体/メディア」等に固定しない）を持たせ、
      そのうえで次のどちらかを持たせる:
        - 切り出したいセクション（例: オウンドメディア）は `match`
          （`host_name` / `path_prefix` / `content_group` のいずれか1つ以上。複数指定時はAND、
          各キー内はリストでOR）
        - 残り全部を受け取る本体サイトは `default: true`（`match` は持たせない）
      **「その他」という3つ目のバケツは作らない。** 一致条件を書くのは切り出したいセクション
      だけでよく、それ以外（トップ・about・お問い合わせ・LP等）は`default: true`のセグメントに
      自動で落ちる設計にした（判断理由は `schema.py` の `match_site_segment` docstring参照）。
    - 保存前に `schema.validate_site_segments()` を通し、警告（segment_id重複・match条件が空・
      既定セグメントの過不足など）があれば stderr に出す。**警告があっても保存は止めない**
      （運用初期の未記入を許容する他の validate と同じ方針）。

    戻り値: `site-segments.yaml` のパス。
    """
    resolved_id, client_root = _resolved_client_root(client_id, context_dir)
    client_root.mkdir(parents=True, exist_ok=True)
    path = client_root / schema.YAML_FILES["site_segments"]
    data = _load_yaml_or_backup(path, what="site-segments.yaml")

    existing = data.get("site_segments")
    if not isinstance(existing, list):
        existing = []
    by_segment_id = {
        s.get("segment_id"): i
        for i, s in enumerate(existing)
        if isinstance(s, dict) and s.get("segment_id")
    }
    for seg in segments or []:
        if not isinstance(seg, dict):
            continue
        seg_id = seg.get("segment_id")
        if seg_id and seg_id in by_segment_id:
            existing[by_segment_id[seg_id]].update(seg)
        else:
            existing.append(seg)
    data["site_segments"] = existing

    warnings = schema.validate_site_segments(existing)
    for w in warnings:
        print(f"[context_store] save_site_segments: {w}", file=sys.stderr)

    _atomic_write_yaml(path, data)
    return path


_BUSINESS_MODEL_VALUES = {"toB", "toC", "both"}


def save_business_profile(
    client_id: str,
    *,
    site_url: str | None = None,
    industry: str | None = None,
    business: str | None = None,
    business_model: str | None = None,
    context_dir: Path | None = None,
) -> Path:
    """`profile.yaml` の `client.site_url` / `industry` / `business` / `business_model` を保存する（軽量受付フロー用）。

    分析エージェント（02など）が「サイトを読みに行って前提を推測し、利用者に確認する」フローで、
    確認が取れた内容を保存するための API。**推測をそのままここに渡さない**こと。
    ユーザーの確認（または訂正）を経た値だけを渡す（無人実行で確認できない場合はこの関数を呼ばず、
    レポート側に「未確認の推測」として扱う。docs/standard-run-order.md §4-2 の無人実行時の方針に揃える）。

    - 渡した項目だけ更新し、他の `client.*` キー（`name` 等）や `aliases` / `preferences` は保持する。
    - 値が空文字/None の引数は無視する（未確認・未回答の項目は上書きしない）。
    - `business_model` は `toB` / `toC` / `both` を想定するが、事業形態が複合的で一言に収まらない
      自由記述（例: 「toB中心・一部toC」）を止める必要はないため、想定外の値でもエラーにはせず
      stderr に警告を出すだけで保存する（`ensure_client_registered` の名前警告と同じ方針）。

    戻り値: `profile.yaml` のパス。
    """
    if business_model and business_model not in _BUSINESS_MODEL_VALUES:
        print(
            f"[context_store] save_business_profile: business_model が想定値 "
            f"{sorted(_BUSINESS_MODEL_VALUES)} のいずれでもありません: {business_model!r}"
            "（自由記述として保存します。想定外でなければこの警告は無視してかまいません）",
            file=sys.stderr,
        )

    resolved_id, client_root = _resolved_client_root(client_id, context_dir)
    client_root.mkdir(parents=True, exist_ok=True)
    path = client_root / schema.YAML_FILES["profile"]
    data = _load_yaml_or_backup(path, what="profile.yaml")

    client = data.get("client")
    if not isinstance(client, dict):
        client = {}
    if site_url:
        client["site_url"] = str(site_url).strip()
    if industry:
        client["industry"] = str(industry).strip()
    if business:
        client["business"] = str(business).strip()
    if business_model:
        client["business_model"] = str(business_model).strip()
    data["client"] = client

    _atomic_write_yaml(path, data)
    return path


def save_query_param_preference(
    client_id: str,
    include_query_params: bool,
    context_dir: Path | None = None,
) -> Path:
    """`profile.yaml` の `preferences.include_query_params` を保存する。

    ランディングページ等の集計でクエリパラメータ（例: `/?renew=`）を含めるかどうかの設定。
    既定はパスのみ（クエリを無視）——ECサイト・ブログのようにクエリ文字列そのものが別ページを
    表すサイトだけ、必要になった時点でこれを呼んで `True` を設定する。01の通常登録フローで
    毎回聞く項目ではない（ほとんどのクライアントは既定のパスのみで問題無いため。02が実データを
    見て必要性に気づいた時点で確認し保存する運用は `save_site_segments` と同じ考え方）。

    - `output_formats` と異なり「聞いたか未確認か」を区別する3値は持たない。未設定なら
      `ClientContext.include_query_params` は常に `False`（既定どおりパスのみ）を返す単純なbool。
    - `preferences` ブロックの他のキー（`output_formats` 等）や `client` / `aliases` など
      他のトップレベルキーは保持する。

    戻り値: `profile.yaml` のパス。
    """
    resolved_id, client_root = _resolved_client_root(client_id, context_dir)
    client_root.mkdir(parents=True, exist_ok=True)
    path = client_root / schema.YAML_FILES["profile"]
    data = _load_yaml_or_backup(path, what="profile.yaml")

    preferences = data.get("preferences")
    if not isinstance(preferences, dict):
        preferences = {}
    preferences["include_query_params"] = bool(include_query_params)
    data["preferences"] = preferences

    _atomic_write_yaml(path, data)
    return path


def save_output_format_preference(
    client_id: str,
    output_formats: list[str],
    *,
    google_doc_url: str | None = None,
    google_sheet_url: str | None = None,
    context_dir: Path | None = None,
) -> Path:
    """`profile.yaml` の `preferences.output_formats` に成果物の書き出し先を保存する（軽量受付フロー用）。

    - `output_formats` は `schema.OUTPUT_FORMATS`（`html` / `pdf` / `docx` / `xlsx` /
      `gdoc` / `gsheet`）のリスト（例: `["html"]`, `["html", "pdf"]`）。
      `html` / `pdf` / `docx` / `xlsx` は `common/report_export` の `--to` にそのまま渡せる形式名。
      `gdoc` / `gsheet` はGoogleドキュメント/スプレッドシートへの書き込みを表す
      （変換ではなく書き込みだが、利用者からは同じ「どの形式で見たいか」という問いのため、
      別の器を作らずここに含める）。
    - **空リストは「MDのみ（変換しない）」という明示的な選択として保存する**。他の save_* と違い、
      空だからといって無視しない（呼び出す時点でユーザーに確認済みの決定を渡す想定）。
    - 一度保存すれば、次回からは聞き直さない（`ClientContext.output_formats` が None
      （未設定＝一度も聞いていない）と `[]`（MDのみ）を区別する）。
    - `google_doc_url` / `google_sheet_url`: `output_formats` に `gdoc` / `gsheet` を含める場合の
      書き込み先URL。**サービスアカウントは自分でファイルを作れない**
      （Google Drive API公式ドキュメント: "Service accounts don't have storage quota and
      can't own files."。共有ドライブでの回避策はGoogle Workspaceの有償エディションが前提で、
      無料アカウントの利用者では成立しない）ため、利用者が先に空のファイルを作り
      サービスアカウントのメールアドレス（認証ファイルの `client_email`）に編集者で共有した
      その先のURLを渡す運用に固定する（自動作成はしない。この理由を消さないこと）。
      渡さなかった場合（`None`）は既存値を保持する（他の任意項目と同じ、上書きしたいときだけ渡す方式）。
      `gdoc` / `gsheet` を選んだのにURLが空の状態は `schema.validate_output_format_preference()`
      （`ClientContext.validate()` 経由）が警告する。**警告があっても保存は止めない**
      （運用初期の未記入を許容する他の validate と同じ方針）。
    - `preferences` ブロックの他のキー（将来追加分）や `client` / `aliases` など他のトップレベル
      キーは保持する。

    戻り値: `profile.yaml` のパス。
    """
    resolved_id, client_root = _resolved_client_root(client_id, context_dir)
    client_root.mkdir(parents=True, exist_ok=True)
    path = client_root / schema.YAML_FILES["profile"]
    data = _load_yaml_or_backup(path, what="profile.yaml")

    preferences = data.get("preferences")
    if not isinstance(preferences, dict):
        preferences = {}
    preferences["output_formats"] = [
        str(f).strip() for f in (output_formats or []) if str(f).strip()
    ]
    if google_doc_url is not None:
        preferences["google_doc_url"] = str(google_doc_url).strip()
    if google_sheet_url is not None:
        preferences["google_sheet_url"] = str(google_sheet_url).strip()
    data["preferences"] = preferences

    for w in schema.validate_output_format_preference(preferences):
        print(f"[context_store] save_output_format_preference: {w}", file=sys.stderr)

    _atomic_write_yaml(path, data)
    return path


_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def save_brand_preferences(
    client_id: str,
    *,
    accent_color: str | None = None,
    logo_path: str | None = None,
    context_dir: Path | None = None,
) -> Path:
    """`profile.yaml` の `preferences.accent_color` / `preferences.logo_path` を保存する（軽量受付フロー用）。

    HTML/PDF成果物の差し色・ロゴを自社ブランドに差し替えたい利用者向けの設定。値は
    `common/report_export` の `--accent-color` / `--logo`（同名の環境変数でも可）にそのまま渡せる形で保存する。

    - `accent_color`: 基準色1つの6桁HEX（例 `"#1D4ED8"`）。`common/report_export` 側
      （`accent_color.derive_palette()`）が `--gold` 系4トークンを自動導出し、文字色に使う
      `--gold-dark` はコントラスト比を確保するよう自動調整する。ここでは形式（6桁HEX）だけ検証する。
    - `logo_path`: ロゴSVGのファイルパス（文字列のまま保存。存在確認はしない。呼び出し側や
      report_export側の `--logo` 解決時にファイルの有無を確認する）。
    - どちらも渡さなかった項目は既存値を保持する（他の save_* と同じ、追記・更新方式）。
    - `report_export` はこのモジュール（context_store）を一切importしない。汎用ツールとして
      01に依存させない設計（design-system.md「差し色を自社ブランドカラーに変える」参照）。
      値の受け渡しは、呼び出し側のエージェント/コマンドがここで保存した値を読み、
      `--accent-color` / `--logo` の引数として渡す形に閉じる。
    - 未設定（一度も呼ばれていない）なら `preferences` に該当キー自体が無く、
      `common/report_export` 側は既定のゴールド・ロゴのまま変わらない。

    戻り値: `profile.yaml` のパス。
    """
    if accent_color is not None and not _HEX_COLOR_RE.match(accent_color):
        raise ValueError(
            f"accent_color の形式が不正です: {accent_color!r}（6桁HEXで指定してください。例: '#1D4ED8'）"
        )

    resolved_id, client_root = _resolved_client_root(client_id, context_dir)
    client_root.mkdir(parents=True, exist_ok=True)
    path = client_root / schema.YAML_FILES["profile"]
    data = _load_yaml_or_backup(path, what="profile.yaml")

    preferences = data.get("preferences")
    if not isinstance(preferences, dict):
        preferences = {}
    if accent_color is not None:
        preferences["accent_color"] = accent_color
    if logo_path is not None:
        preferences["logo_path"] = str(logo_path)
    data["preferences"] = preferences

    _atomic_write_yaml(path, data)
    return path


def save_external_ai_approval(
    client_id: str,
    provider: str,
    *,
    approved_date: str | None = None,
    context_dir: Path | None = None,
) -> Path:
    """外部AIへのデータ送信承認をクライアント・送信先ごとに1度だけ記録する。"""
    provider = provider.strip()
    if not provider or not re.fullmatch(r"[A-Za-z0-9_-]+", provider):
        raise ValueError(f"不正な外部AI provider: {provider!r}")
    _, client_root = _resolved_client_root(client_id, context_dir)
    client_root.mkdir(parents=True, exist_ok=True)
    path = client_root / schema.YAML_FILES["profile"]
    with _exclusive_lock(path):
        data = _load_yaml_or_backup(path, what="profile.yaml")
        preferences = data.get("preferences")
        if not isinstance(preferences, dict):
            preferences = {}
        approvals = preferences.get("external_ai_approvals")
        if not isinstance(approvals, list):
            approvals = []
        if not any(isinstance(a, dict) and a.get("provider") == provider for a in approvals):
            approvals.append({"provider": provider, "approved_date": approved_date or _dt.date.today().isoformat()})
        preferences["external_ai_approvals"] = approvals
        data["preferences"] = preferences
        _atomic_write_yaml(path, data)
    return path


def save_customer_understanding(
    client_id: str,
    *,
    three_c: dict,
    personas: list[dict],
    source_report: str | None = None,
    source_child_reports: list[str] | None = None,
    unresolved: list[str] | None = None,
    created_date: str | None = None,
    context_dir: Path | None = None,
    allow_incomplete: bool = False,
) -> Path:
    """`customer-understanding.yaml`（3C・ペルソナ・態度変容ジャーニー）を保存する。

    **他の save_* と違い、ファイルの中身を丸ごと置き換える**（追記・部分更新ではない）。
    3C・ペルソナ・態度変容ジャーニーは `03_external_research`（市場・顧客理解エージェント）が
    1回の実行で一式作り直す性質の情報のため、古い personas と新しい personas が
    混在する方が事故になる（例: 前回のペルソナ2人＋今回のペルソナ2人で計4人、のような混在）。

    - `created_date` を省略した場合は当日（`YYYY-MM-DD`）を使う。呼び出し側（03のコーディネーター
      スキル）は基本的に省略してよい。
    - `three_c` / `personas` の形式は `schema/context-schema.md`「customer-understanding.yaml」節。
      personas の各要素は `journey` に5段階
      （`daily_business` / `problem_emergence` / `research` / `consideration` / `purchase`）を
      固定順で持たせる（`stage_id` は固定。`stage_name` は自由記述で、最終段階は01の
      `kpis.yaml` から導いたCVの実態に合わせて改名してよい）。personas の各要素には
      `persona_basis`（`customer_voice_confirmed` / `competitor_customer_voice_confirmed` /
      `service_derived`）も必須。
    - 保存前に `schema.validate_customer_understanding()` を通し、警告（根拠の無い障壁・刺激に
      `evidence_type: customer_voice` / `competitor_customer_voice` / `service_derived` を
      付けて evidence が空、`persona_basis` 未設定、personas が `schema.PERSONA_MAX`（5人）を
      超えているなど）があれば既定では保存を止める。作業途中の下書きを意図的に保存する場合だけ
      `allow_incomplete=True` を明示する。下書きの警告を確定データとして黙って流さないための制約。

    戻り値: `customer-understanding.yaml` のパス。
    """
    resolved_id, client_root = _resolved_client_root(client_id, context_dir)
    client_root.mkdir(parents=True, exist_ok=True)
    path = client_root / schema.YAML_FILES["customer_understanding"]

    data: dict = {
        "created_date": created_date or _dt.date.today().isoformat(),
        "three_c": three_c,
        "personas": personas,
    }
    if source_report:
        data["source_report"] = source_report
    if source_child_reports:
        data["source_child_reports"] = list(source_child_reports)
    if unresolved:
        data["unresolved"] = list(unresolved)

    warnings = schema.validate_customer_understanding(data)
    for w in warnings:
        print(f"[context_store] save_customer_understanding: {w}", file=sys.stderr)
    if warnings and not allow_incomplete:
        raise ValueError(
            "customer-understanding.yaml の必須根拠が不足しています。"
            "barrier_id / stimulus_id と evidence を補完してから保存してください: "
            + " / ".join(warnings)
        )

    _atomic_write_yaml(path, data)
    return path


def append_finding(
    client_id: str,
    agent: str,
    summary: str,
    findings: list[str],
    outputs: list[str],
    date: str | None = None,
    context_dir: Path | None = None,
) -> Path:
    """`analysis-history.yaml` の `entries` に1エントリ追記する。

    - `agent` 名は `{テーマ番号}_{エージェント名}`（例: `04_parameter_management`）で統一する
      （docs/standard-run-order.md §2 の規約）。
    - `client_id` は別名でもよい（loader.resolve_client_id を通す。別名解決時は stderr に警告）。
    - `date` 省略時は当日（`YYYY-MM-DD`）。
    - ファイル・`context/<client_id>/` ディレクトリ・`entries` キーが無ければ作成する。
    - 既存 YAML のパースに失敗した場合は、元ファイルを `.broken-<日時>` に退避してから
      新規 `entries` で書き直す（元データを消さない・失敗時も落ちない方針は loader.py と揃える）。

    戻り値: 追記先ファイルのパス。
    """
    resolved_id, client_root = _resolved_client_root(client_id, context_dir)
    if not (client_root / schema.YAML_FILES["profile"]).exists():
        print(
            f"[context_store] 09未登録の client_id {resolved_id!r} に書き込もうとしています。"
            "表記揺れでないか確認し、未登録なら先に context-manager で登録してください（続行します）",
            file=sys.stderr,
        )
    client_root.mkdir(parents=True, exist_ok=True)
    history_path = client_root / schema.YAML_FILES["analysis_history"]

    with _exclusive_lock(history_path):
        data = _load_yaml_or_backup(history_path, what="analysis-history.yaml")
        entries = data.get("entries")
        if not isinstance(entries, list):
            entries = []
        entries.append(
            {
                "date": date or _dt.date.today().isoformat(),
                "agent": agent,
                "summary": summary,
                "findings": list(findings),
                "outputs": list(outputs),
            }
        )
        data["entries"] = entries
        _atomic_write_yaml(history_path, data)
    return history_path
