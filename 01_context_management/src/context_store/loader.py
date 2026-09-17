"""コンテキストストアのローダー。

他エージェントが import して使う最小 API:

    load_context(client_id) -> ClientContext   # 全YAML + 議事録を統合して返す
    list_clients()          -> list[str]       # context/ 配下のクライアントID一覧

context/ や個別ファイルが無い／未記入でも例外で落とさず、欠損は None / 空で返す。
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from context_store import schema

logger = logging.getLogger("context_store")

# このファイル = src/context_store/loader.py → リポジトリ上の 01_context_management/
_AGENT_ROOT = Path(__file__).resolve().parents[2]
CONTEXT_DIR = _AGENT_ROOT / "context"

_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass
class ClientContext:
    """1クライアント分の統合コンテキスト。各属性は対応YAMLのパース結果（dict）。"""

    client_id: str
    profile: dict = field(default_factory=dict)
    measurement: dict = field(default_factory=dict)
    kpis: dict = field(default_factory=dict)
    site_segments: dict = field(default_factory=dict)
    customer_understanding: dict = field(default_factory=dict)
    initiatives: dict = field(default_factory=dict)
    constraints: dict = field(default_factory=dict)
    stakeholders: dict = field(default_factory=dict)
    analysis_history: dict = field(default_factory=dict)
    # 議事録: [{"file": str, "date": str, "type": str, "title": str, "text": str}, ...]
    meetings: list[dict] = field(default_factory=list)

    # ---- 取り回し用のショートカット -------------------------------------
    @property
    def name(self) -> str:
        return (self.profile.get("client", {}) or {}).get("name", self.client_id)

    @property
    def ga4_property_id(self) -> str | None:
        return (self.measurement.get("ga4", {}) or {}).get("property_id")

    @property
    def search_console_site_url(self) -> str | None:
        """Search Console APIへそのまま渡せるプロパティ文字列。"""
        return (self.measurement.get("search_console", {}) or {}).get("site_url")

    @property
    def key_events(self) -> list[str]:
        return self.kpis.get("key_events", []) or []

    @property
    def form_pages_by_event(self) -> dict[str, list[dict]]:
        """利用者確認済みの完了イベントとフォームページの対応。"""
        result: dict[str, list[dict]] = {}
        for kpi in self.kpis.get("kpis", []) or []:
            if not isinstance(kpi, dict):
                continue
            pages = [p for p in (kpi.get("form_pages") or []) if isinstance(p, dict) and p.get("path")]
            for event in kpi.get("events", []) or []:
                if pages:
                    result[str(event)] = pages
        return result

    def external_ai_approved(self, provider: str) -> bool:
        """指定送信先への外部AI利用がこのクライアントで承認済みか。"""
        preferences = self.profile.get("preferences")
        if not isinstance(preferences, dict):
            return False
        approvals = preferences.get("external_ai_approvals")
        return isinstance(approvals, list) and any(
            isinstance(item, dict) and item.get("provider") == provider for item in approvals
        )

    @property
    def primary_kpi(self) -> dict | None:
        """複数CVがあるとき、どれを主に見るか（`kpis.yaml` の `kpis[].priority: 1`）。

        - `priority: 1` を持つKPIが1件だけ見つかればそれを返す。
        - KPIが1件しかない場合はそのKPIを返す（優先度を明示する必要が無いため）。
        - 優先度が未設定（一度も聞いていない）、または `priority: 1` が0件/複数件で一意に
          決まらない場合は `None`。**`None` を「先頭のKPIで代用してよい」という意味には
          しない**（未設定と分かる形で呼び出し側に伝えるための設計。schema.validate_kpi_priorities
          が中途半端な設定を警告する）。
        """
        kpis = [k for k in (self.kpis.get("kpis", []) or []) if isinstance(k, dict)]
        if len(kpis) == 1:
            return kpis[0]

        def _is_top(k: dict) -> bool:
            try:
                return int(k.get("priority")) == 1
            except (TypeError, ValueError):
                return False

        top = [k for k in kpis if _is_top(k)]
        return top[0] if len(top) == 1 else None

    def classify_page(
        self,
        host_name: str | None = None,
        page_path: str | None = None,
        content_group: str | None = None,
    ) -> str | None:
        """1ページを `site-segments.yaml` の定義に照らして分類し、一致した `segment_id` を返す。

        `content_group` はGA4側でコンテンツグループが設定済みのサイトでのみ渡せばよい
        （未設定なら省略し、host_name/page_pathだけで判定する）。
        `default: true` を持つセグメントが定義されていれば、どの `match` にも一致しない
        ページはそこ（既定セグメント。通常は「本体サイト」）に分類されるため、通常は `None`
        にならない。`None` が返るのは `default: true` を1件も設定していない場合だけで、
        この場合に限り**呼び出し側はこれを捨てず「その他」件数として必ず集計に残すこと**
        （合計が全体と合わなくなる事故を防ぐため）。
        `site_segments` が未設定（機能未使用）のクライアントでは常に `None` を返す。
        """
        segments = (self.site_segments or {}).get("site_segments", []) or []
        return schema.match_site_segment(
            segments, host_name=host_name, page_path=page_path, content_group=content_group
        )

    @property
    def include_query_params(self) -> bool:
        """ランディングページ等の集計でクエリパラメータを含めるか（`profile.yaml` の
        `preferences.include_query_params`）。

        既定は `False`（パスのみ。`/?renew=` のようなクエリを無視する）。ECサイト・ブログのように
        クエリ文字列そのものが別ページを表すサイトだけ、必要になった時点で明示的に `True` を設定する
        （保存は `writeback.save_query_param_preference`）。未設定なら常に `False` を返す
        （`output_formats` と違い「聞いたか未確認か」を区別する必要が無い設定のため、
        3値ではなく単純な bool にしている）。
        """
        preferences = self.profile.get("preferences")
        if not isinstance(preferences, dict):
            return False
        return bool(preferences.get("include_query_params", False))

    @property
    def output_formats(self) -> list[str] | None:
        """成果物の既定変換形式（`profile.yaml` の `preferences.output_formats`）。

        3値を区別する:
          - `None`: 未設定（一度も聞いていない） → 実行前チェックでまとめて1回聞く
          - `[]`: MDのみを明示的に選択済み（変換しない） → 聞き直さない
          - `["html", ...]`: 保存済みの既定変換形式 → 聞かずに使う

        許容値は `schema.OUTPUT_FORMATS`（`html` / `pdf` / `docx` / `xlsx` に加え、
        Googleドキュメント/スプレッドシートへの書き込みを表す `gdoc` / `gsheet`）。
        `gdoc` / `gsheet` を含む場合は、書き込み先URLを `google_doc_url` / `google_sheet_url`
        プロパティで別途取得できる（サービスアカウントは自分でファイルを作れないため、
        利用者が用意したURLが必須。詳細は両プロパティのdocstring参照）。
        """
        preferences = self.profile.get("preferences")
        if not isinstance(preferences, dict) or "output_formats" not in preferences:
            return None
        formats = preferences.get("output_formats")
        if not isinstance(formats, list):
            return []
        return [str(f).strip() for f in formats if str(f).strip()]

    @property
    def google_doc_url(self) -> str | None:
        """`output_formats` に `gdoc` を含むときの書き込み先URL（`preferences.google_doc_url`）。

        サービスアカウントは自分でファイルを作れない（Google Drive API公式ドキュメント:
        "Service accounts don't have storage quota and can't own files."。共有ドライブでの
        回避策はGoogle Workspaceの有償エディションが前提で、無料アカウントの利用者では成立しない）。
        そのため運用は「利用者が先に空のドキュメントを作り、サービスアカウントのメールアドレス
        （認証ファイルの `client_email`）に編集者で共有し、そこへ書き込む」形に固定する
        （自動作成はしない）。未設定なら `None`。保存は `writeback.save_output_format_preference()`。
        """
        preferences = self.profile.get("preferences")
        if not isinstance(preferences, dict):
            return None
        value = preferences.get("google_doc_url")
        return str(value).strip() or None if value else None

    @property
    def google_sheet_url(self) -> str | None:
        """`output_formats` に `gsheet` を含むときの書き込み先URL（`preferences.google_sheet_url`）。

        理由・運用は `google_doc_url` と同じ（サービスアカウントは自分でファイルを作れないため、
        利用者が用意し共有したURLが必須）。未設定なら `None`。
        保存は `writeback.save_output_format_preference()`。
        """
        preferences = self.profile.get("preferences")
        if not isinstance(preferences, dict):
            return None
        value = preferences.get("google_sheet_url")
        return str(value).strip() or None if value else None

    @property
    def accent_color(self) -> str | None:
        """HTML/PDF成果物の差し色（`profile.yaml` の `preferences.accent_color`）。

        未設定なら `None`（`common/report_export` の既定ゴールドのまま）。設定されていれば
        `common/report_export` の `--accent-color` にそのまま渡せる6桁HEX文字列。
        保存は `writeback.save_brand_preferences()`。
        """
        preferences = self.profile.get("preferences")
        if not isinstance(preferences, dict):
            return None
        value = preferences.get("accent_color")
        return str(value).strip() or None if value else None

    @property
    def logo_path(self) -> str | None:
        """HTML/PDF成果物のロゴファイルパス（`profile.yaml` の `preferences.logo_path`）。

        未設定なら `None`（`common/report_export` の既定ロゴ `logo-placeholder.svg` のまま）。
        設定されていれば `common/report_export` の `--logo` にそのまま渡せるパス文字列。
        保存は `writeback.save_brand_preferences()`。
        """
        preferences = self.profile.get("preferences")
        if not isinstance(preferences, dict):
            return None
        value = preferences.get("logo_path")
        return str(value).strip() or None if value else None

    def validate(self) -> list[str]:
        """軽量バリデーション。警告メッセージ一覧を返す（空なら正常）。"""
        return schema.validate(self)

    def summary_markdown(self) -> str:
        """プロンプトに差し込める前提情報サマリ（Markdown）。

        他エージェントが起動時にこれを会話へ注入することで、毎回の聞き取りを省く。
        """
        client = self.profile.get("client", {}) or {}
        lines: list[str] = [f"## クライアント前提: {self.name}"]

        # 基本情報
        basics = []
        if client.get("industry"):
            basics.append(f"業種: {client['industry']}")
        if client.get("business_model"):
            basics.append(f"事業形態: {client['business_model']}")
        if client.get("site_url"):
            basics.append(f"URL: {client['site_url']}")
        if basics:
            lines.append("- " + " / ".join(basics))

        # 計測環境
        ga4_id = self.ga4_property_id
        if ga4_id:
            lines.append(f"- GA4 property: {ga4_id}")
        if self.key_events:
            lines.append(f"- key events: {', '.join(self.key_events)}")

        # KPI（複数あるときは優先度が分かるように表示する。未設定なら分かる形でそう出す）
        kpis = self.kpis.get("kpis", []) or []
        if kpis:
            lines.append("### KPI")
            primary = self.primary_kpi
            dict_kpis = [k for k in kpis if isinstance(k, dict)]
            for k in dict_kpis:
                tv = k.get("target_value", {}) or {}
                goal = f" (目標 {tv.get('goal')}{tv.get('unit', '')})" if tv.get("goal") else ""
                mark = ""
                if len(dict_kpis) > 1:
                    if primary is not None and k is primary:
                        mark = " ★最優先"
                    elif k.get("priority") is not None:
                        mark = f" (priority {k.get('priority')})"
                lines.append(f"- {k.get('kpi_id')}: {k.get('name')}{goal}{mark}")
            if len(dict_kpis) > 1 and primary is None:
                lines.append("  - [注意] 複数KPIの優先度が未設定です（どれが主か聞いていない）")

        # サイトセグメント（分析対象の定義。役割の違うセクションの混在による誤解釈を防ぐ）
        segments = (self.site_segments or {}).get("site_segments", []) or []
        dict_segments = [s for s in segments if isinstance(s, dict)]
        if dict_segments:
            lines.append("### サイトセグメント（分析対象の定義）")
            has_default = any(s.get("default") is True for s in dict_segments)
            for s in dict_segments:
                mark = " ★既定（未分類のページはここに入る）" if s.get("default") is True else ""
                lines.append(f"- {s.get('segment_id')}: {s.get('name')}{mark}")
            if has_default:
                lines.append(
                    "  - どの条件にも一致しないページは既定セグメントに分類される（『その他』は作らない）"
                )
            else:
                lines.append(
                    "  - [注意] 既定セグメント（default: true）が未設定です。"
                    "どれにも一致しないページは「その他」として残す（合計から消さない）"
                )

        # 3C・ペルソナ・態度変容ジャーニー（03由来。分析より寿命が長いので created_date を必ず見せる）
        cu = self.customer_understanding or {}
        personas = cu.get("personas", []) or []
        if cu.get("created_date") or personas:
            lines.append("### 3C・ペルソナ・態度変容ジャーニー")
            if cu.get("created_date"):
                lines.append(f"- 作成日: {cu['created_date']}（古い場合は03の再実行を検討）")
            else:
                lines.append("- [注意] created_date が未設定（作成日不明）")
            for p in personas:
                if not isinstance(p, dict):
                    continue
                name = p.get("name", p.get("persona_id", "?"))
                factor = p.get("distinguishing_factor")
                if factor:
                    lines.append(f"- {name}: {str(factor).strip().splitlines()[0]}")
                else:
                    lines.append(f"- {name}")
            if cu.get("source_report"):
                lines.append(f"- 詳細: {cu['source_report']} / customer-understanding.yaml")

        # gotchas（誤分析防止 — 最重要）
        # 形式ズレ（id/note形式・文字列リスト・想定外）でも無言で捨てない（schema.normalize_gotchas）
        gotchas = schema.normalize_gotchas(self.constraints)
        if gotchas:
            lines.append("### [注意] 分析時の注意 (gotchas)")
            for g in gotchas:
                if g["detail"] and g["detail"] != g["title"]:
                    lines.append(f"- {g['title']}: {g['detail']}")
                else:
                    lines.append(f"- {g['title']}")

        # 未解決課題（文字列リスト・想定外形式も表示に回す。resolved のみ除外）
        oqs = schema.normalize_open_questions(self.constraints)
        open_oqs = [q for q in oqs if q["status"] != "resolved"]
        if open_oqs:
            lines.append("### 未解決課題")
            for q in open_oqs:
                status = f" (status: {q['status']})" if q["status"] else ""
                lines.append(f"- {q['question']}{status}")

        # 直近の分析findings（引き継ぎ）
        entries = self.analysis_history.get("entries", []) or []
        if entries:
            latest = sorted(
                (e for e in entries if isinstance(e, dict)),
                key=lambda e: e.get("date", ""),
                reverse=True,
            )[:3]
            lines.append("### 直近の分析findings")
            for e in latest:
                lines.append(f"- [{e.get('date')}] {e.get('agent')}: {e.get('summary')}")
                for f_ in e.get("findings", []) or []:
                    lines.append(f"    - {f_}")

        return "\n".join(lines)


def _read_yaml(path: Path) -> dict:
    """YAML を緩く読み込む。無ければ {} を返し、壊れていれば警告して {}。"""
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError as e:
        logger.warning("YAML パース失敗: %s (%s)", path, e)
        return {}


def _read_meetings(meetings_dir: Path) -> list[dict]:
    """meetings/*.md を読み込み、frontmatter とタイトルを抽出する。"""
    if not meetings_dir.is_dir():
        return []
    out: list[dict] = []
    for md in sorted(meetings_dir.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        meta = {"file": md.name, "date": "", "type": "", "title": "", "text": text}
        # frontmatter (--- ... ---)
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                fm = _safe_yaml_str(parts[1])
                meta["date"] = str(fm.get("date", ""))
                meta["type"] = str(fm.get("type", ""))
                body = parts[2]
            else:
                body = text
        else:
            body = text
        # 最初の見出し行をタイトルに
        for line in body.splitlines():
            if line.startswith("# "):
                meta["title"] = line[2:].strip()
                break
        out.append(meta)
    return out


def _safe_yaml_str(s: str) -> dict:
    try:
        data = yaml.safe_load(s)
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError as e:
        logger.warning("議事録frontmatterのYAMLパース失敗: %s", e)
        return {}


def _build_alias_index(context_dir: Path) -> dict[str, list[str]]:
    """context/ 配下の全クライアントの profile.yaml から alias -> [client_id, ...] の索引を作る。

    複数クライアントが同じ別名を登録している場合に検出できるよう、一致した client_id を
    すべてリストで保持する（黙って片方を選ばないため）。
    """
    index: dict[str, list[str]] = {}
    if not context_dir.is_dir():
        return index
    for client_dir in context_dir.iterdir():
        if not client_dir.is_dir() or client_dir.name.startswith("."):
            continue
        profile = _read_yaml(client_dir / schema.YAML_FILES["profile"])
        aliases = profile.get("aliases", []) or []
        for alias in aliases:
            if not alias:
                continue
            index.setdefault(str(alias), []).append(client_dir.name)
    return index


def resolve_client_id(client_id: str, context_dir: Path | None = None) -> str:
    """別名解決: client_id が正規IDでなければ、全クライアントの profile.yaml の aliases から
    正規IDを探して返す。

    - ディレクトリ名として直接存在する場合はそれを正規IDとして優先する（別名解決はしない）。
    - 別名にも一致しなければ入力をそのまま返す（未登録クライアントとして通常の空コンテキスト
      フローに委ねる）。
    - 別名が複数クライアントに登録されている場合は ValueError を投げる（黙って片方を選ばない）。
    - 別名から正規IDに解決した場合、stderr に1行警告を出す。
    """
    base = context_dir or CONTEXT_DIR
    if (base / client_id).is_dir():
        return client_id

    matches = sorted(set(_build_alias_index(base).get(client_id, [])))
    if not matches:
        return client_id
    if len(matches) > 1:
        raise ValueError(
            f"別名 {client_id!r} が複数クライアントに登録されています: {matches}"
            "（各クライアントの profile.yaml の aliases を見直してください）"
        )
    resolved = matches[0]
    print(
        f"[context_store] 別名 {client_id} を正規ID {resolved} に解決しました",
        file=sys.stderr,
    )
    return resolved


def load_context(client_id: str, context_dir: Path | None = None) -> ClientContext:
    """指定クライアントの全コンテキストを読み込んで ClientContext を返す。

    `client_id` は別名（`profile.yaml` の `aliases`）でもよい。別名で呼ばれた場合は
    正規IDに解決したうえで読み込む（解決時は stderr に警告を1行出す）。
    ファイルが無くても落ちない（欠損は空 dict / 空 list）。
    """
    base_dir = context_dir or CONTEXT_DIR
    resolved_id = resolve_client_id(client_id, base_dir)

    if not _CLIENT_ID_RE.match(resolved_id):
        raise ValueError(
            f"不正な client_id: {resolved_id!r}（英数字・ハイフン・アンダースコアのみ）"
        )

    base = base_dir / resolved_id
    if not base.is_dir():
        logger.warning("コンテキスト未作成: %s （空のコンテキストを返します）", base)

    data = {attr: _read_yaml(base / fname) for attr, fname in schema.YAML_FILES.items()}
    meetings = _read_meetings(base / schema.MEETINGS_DIR)

    return ClientContext(client_id=resolved_id, meetings=meetings, **data)


def list_clients(context_dir: Path | None = None) -> list[str]:
    """context/ 配下のクライアントID一覧を返す（無ければ空リスト）。"""
    base = context_dir or CONTEXT_DIR
    if not base.is_dir():
        return []
    return sorted(
        p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")
    )
