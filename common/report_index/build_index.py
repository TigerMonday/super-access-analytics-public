"""outputs/{client_id}/ 配下を走査して index.html を作る。

使い方:
    python common/report_index/build_index.py "outputs/{client_id}"

設計の考え方（docs/standard-run-order.md §4 規約3が正本）:
- 実在するフォルダ・ファイルを走査する。特定テーマの決め打ちパスを組み立てて
  存在を仮定しない。テーマがまだ新しい出力規約（ファイル名に日付を入れない・
  `_past/` に退避する）に追いついていなくても、あるものを拾って動く。
- `_` や `.` で始まるフォルダ（`_data`・`_past`・旧 `_rework_rounds`・
  `_review_rounds` など）は「生成物ではない・内部の作業領域」の合図として
  スキャン対象から除外する。
- どのテーマがどの1ファイルを「本体のレポート」として見せるかは
  _THEME_REGISTRY にまとめている。未登録のテーマフォルダ（NN_なにか、の形式）
  や、登録済みでも該当ファイルが見つからないテーマは、フォルダ内で見つかった
  Markdown/HTMLファイルをそのまま一覧に出すフォールバックで拾う。
- 複数段をまたぐチェーン（05 CVR改善など）は、クライアント向け確定版が1本だけ
  （個別の段ごとの確定版は持たない）でも、_THEME_REGISTRY に "chain" を持たせて
  「進行中」を出せる。確定版の有無に関わらず _past/ 配下の固定名ファイルの実在を見て、
  まだ確定版に反映されていない段の作業を確定版とは別枠（ThemeSection.progress）で出す。
  ある段の完了を示す `-final.md` が最新の到達点になっている場合は、その段の内容は
  同じ実行の中で確定版へ反映されているはずなので「進行中」としては出さない
  （_find_chain_progress のサスペンド規則。詳細は README.md）。
"""

from __future__ import annotations

import argparse
import posixpath
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path

REPORT_EXTENSIONS = (".html", ".md")
# 生成物ではなく人が書き込む途中のファイルを誤って一覧に出さないためのセーフティネット。
# 一次的な防御はテーマごとの許可リスト（_THEME_REGISTRY）で、これは未登録テーマ用の保険。
_HUMAN_AUTHORED_STEM_HINTS = ("-notes", ".draft", "-draft")
_REPORT_NAV_RE = re.compile(
    r'<aside class="report-nav"[^>]*>.*?</aside>',
    re.DOTALL,
)
_CURRENT_REPORT_GROUP_RE = re.compile(
    r'<details class="toc-report-group"(?=[^>]*\bdata-report-current="true")[^>]*>(.*?)</details>',
    re.DOTALL,
)
_TOC_ITEM_RE = re.compile(
    r'<li class="toc-level-(?P<level>[23])">\s*'
    r'<a href="#(?P<href>[^"]+)" data-section="(?P<section>[^"]+)">'
    r'(?P<label>.*?)</a>\s*</li>',
    re.DOTALL,
)
_ACCORDION_STYLE_RE = re.compile(
    r'<style id="report-accordion-nav-style">.*?</style>',
    re.DOTALL,
)
_ACCORDION_STYLE = """<style id="report-accordion-nav-style">
.report-nav .toc-report-group{ margin:0; padding:0; border:0; }
.report-nav .toc-report-group + .toc-report-group{ border-top:1px solid var(--gray-200); }
.report-nav .toc-report-summary{
  display:flex; align-items:center; justify-content:space-between; gap:10px;
  padding:12px 8px; color:var(--gray-900); font-size:12px; font-weight:800;
  line-height:1.45; cursor:pointer; list-style:none;
}
.report-nav .toc-report-summary::-webkit-details-marker{ display:none; }
.report-nav .toc-report-summary::after{
  content:"＋"; flex:none; color:var(--gray-500); font-size:13px; font-weight:700;
}
.report-nav .toc-report-group[open] > .toc-report-summary::after{ content:"−"; }
.report-nav .toc-report-group[open] > .toc-report-summary{ color:var(--gold-dark); }
.report-nav .toc-report-group > ol{ padding:0 0 10px; }
.report-nav .toc-report-empty{ padding:0 8px 12px; font-size:10.5px; color:var(--gray-500); }
</style>"""

# テーマフォルダ名 -> どのファイルを「本体のレポート」として見せるか
# (basename, 表示タイトル, 説明) の並び順で index.html にも並ぶ
_THEME_REGISTRY: dict[str, dict] = {
    "02_measurement": {
        "label": "計測チェック",
        "nav_label": "計測チェック",
        "reports": [
            (
                "check-report",
                "計測チェックレポート",
                "GA4/GTMの計測設定が正しく入っているかを○△×で判定する",
            ),
        ],
    },
    "03_research": {
        "label": "市場顧客分析",
        "nav_label": "市場顧客分析",
        "reports": [
            (
                "00_3c_persona_journey_report",
                "市場顧客分析",
                "市場・顧客・競合の調査結果をまとめる",
            ),
        ],
        "topic_subfolders": True,
    },
    "04_traffic": {
        "label": "基本分析",
        "nav_label": "基本分析",
        "reports": [
            (
                "basic-analysis-report",
                "基本分析レポート",
                "流入チャネル・ページ・CV経路など集客の現状をまとめる",
            ),
        ],
    },
    "05_cvr": {
        "label": "サイト改善",
        "nav_label": "サイト改善",
        # クライアント向け確定版はこの1本だけ（段ごとの個別確定版は作らない。
        # docs/standard-run-order.md §4-5）。
        "reports": [
            (
                "cvr-improvement-plan",
                "サイト改善レポート",
                "確定した段を1本にまとめた、着手すべき改善施策の全体像（段が増えるたびに更新）",
            ),
        ],
        # チェーン（05↔06）の途中経過を表すための設定。①②の連番ファイルを時系列の
        # 1本のリストにまとめ、_past/ 配下のどの固定名ファイルまで進んでいるかで
        # 「進行中」を出す。判定表の正本は 05_campaign_optimization/run.md
        # （ファイル名を変えたらそちらも直す）。
        # 各段の末尾（`-final.md`）は、その段の是正内容が同じ実行の中で確定版へ
        # 反映されるため、最新の到達点がこれらのファイルのときは「進行中」を出さない
        # （_find_chain_progress 参照）。
        # 旧構成では②（対象ページ選定）と③（ABテスト案）が別の段で、連番ファイルも
        # 07-target-pages.md〜10-abtest-plan-final.mdの4本だったが、1段に統合した
        # （docs/standard-run-order.md §4-5・05_campaign_optimization/README.md）。
        # 07-target-page-plan.mdは「対象ページ選定」「改善案」の2セクションを持ち、
        # 08-target-page-plan-final.mdは両セクションとも06で「妥当」判定されたときだけ書かれる。
        "chain": {
            "cvr-improvement-plan": (
                "サイト改善レポート（作業中）",
                [
                    ("01-analysis.md", "①分析まで完了・検算待ち"),
                    ("02-analysis-review.md", "①分析の検算まで完了・方針作成待ち"),
                    ("03-strategy.md", "①方針案まで完了・レビュー待ち"),
                    ("04-strategy-final.md", "①confirmed"),  # 確定版へ反映済みのはず。進行中には出さない
                    ("page-profile.md", "②ページ分類まで完了・ページ分析待ち"),
                    ("05-page-analysis.md", "②ページ分析まで完了・検算待ち"),
                    ("06-page-analysis-review.md", "②ページ分析の検算まで完了・施策作成待ち"),
                    ("07-target-page-plan.md", "②施策案（対象ページ・改善案）まで完了・レビュー待ち"),
                    ("08-target-page-plan-final.md", "②confirmed"),  # 同上
                ],
            ),
        },
    },
    "07_adhoc": {
        "label": "アドホック分析",
        "nav_label": "アドホック分析",
        "reports": [],
    },
}


@dataclass
class ReportEntry:
    title: str
    desc: str
    href: str
    updated_at: datetime | None
    pdf_href: str | None = None


@dataclass
class ProgressEntry:
    """確定版がまだ無いチェーンの途中経過（社内向け）を表す1件。"""

    title: str
    status: str
    href: str
    updated_at: datetime | None


@dataclass
class ThemeSection:
    label: str
    nav_label: str
    reports: list[ReportEntry] = field(default_factory=list)
    # 確定版がまだ無いチェーンの途中経過（「進行中」として確定版とは別枠で表示する）
    progress: list[ProgressEntry] = field(default_factory=list)


def _is_excluded_dir(name: str) -> bool:
    return name.startswith("_") or name.startswith(".")


def _looks_human_authored(stem: str) -> bool:
    low = stem.lower()
    return any(hint in low for hint in _HUMAN_AUTHORED_STEM_HINTS)


def _iter_files(root: Path, max_depth: int = 6):
    """root配下を再帰的に辿ってファイルを返す。`_`/`.`始まりのフォルダはスキップする。"""
    if not root.is_dir():
        return
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                is_dir = entry.is_dir()
            except OSError:
                continue
            if is_dir:
                if depth < max_depth and not _is_excluded_dir(entry.name):
                    stack.append((entry, depth + 1))
            else:
                yield entry


def _find_by_basename(root: Path, basename: str) -> Path | None:
    """root配下から basename の .html を優先、無ければ .md を探す（深さは決め打ちしない）。"""
    candidates: dict[str, Path] = {}
    for f in _iter_files(root):
        if f.stem == basename and f.suffix.lower() in REPORT_EXTENSIONS:
            candidates[f.suffix.lower()] = f
    if ".html" in candidates:
        return candidates[".html"]
    return candidates.get(".md")


def _fallback_reports(root: Path) -> list[Path]:
    """レジストリに無いテーマ、または該当ファイルが見つからないテーマ用のフォールバック。
    見つかったファイルを stem ごとにまとめ、html があれば html を優先して1件にする。"""
    by_stem: dict[str, dict[str, Path]] = {}
    for f in _iter_files(root):
        suffix = f.suffix.lower()
        if suffix not in REPORT_EXTENSIONS:
            continue
        if _looks_human_authored(f.stem):
            continue
        by_stem.setdefault(f.stem, {})[suffix] = f
    picked = []
    for stem in sorted(by_stem):
        exts = by_stem[stem]
        picked.append(exts.get(".html") or exts.get(".md"))
    return picked


def _humanize_stem(stem: str) -> str:
    text = re.sub(r"^[0-9０-９]+[_\-]?", "", stem)
    text = text.replace("-", " ").replace("_", " ").strip()
    return text or stem


def _humanize_topic_name(name: str) -> str:
    text = re.sub(r"^\d{8}_", "", name)
    text = text.replace("_", " ").strip()
    return text or name


def _default_label(dirname: str) -> str:
    m = re.match(r"^(\d\d)_(.+)$", dirname)
    if not m:
        return dirname
    _, rest = m.groups()
    return _humanize_stem(rest)


def _mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def _rel(path: Path, client_dir: Path) -> str:
    try:
        return path.relative_to(client_dir).as_posix()
    except ValueError:
        return path.as_posix()


def _pdf_href_for(path: Path, client_dir: Path) -> str | None:
    """主ファイルと同じフォルダ・同じbasenameのPDFだけを副リンクとして返す。"""
    pdf_path = path.with_suffix(".pdf")
    return _rel(pdf_path, client_dir) if pdf_path.is_file() else None


def discover_theme_dirs(client_dir: Path) -> list[Path]:
    if not client_dir.is_dir():
        return []
    dirs = []
    for d in client_dir.iterdir():
        try:
            if d.is_dir() and re.match(r"^\d\d_", d.name):
                dirs.append(d)
        except OSError:
            continue
    return sorted(dirs, key=lambda d: d.name)


def _find_chain_progress(past_dir: Path, steps: list[tuple[str, str]]) -> tuple[Path, str] | None:
    """_past/ 配下を見て、steps（時系列順・ファイル名固定）のうち実在する最後の工程を返す。
    どれも無ければ None（＝未着手。「何もしていない」と区別しない＝カードを出さない）。
    退避済み（先頭に書き込み時刻が付いた）ファイルは対象外。プレーンな固定名だけを見る。

    最後に見つかった工程のファイル名が `-final.md` で終わる場合は None を返す（＝進行中として
    出さない）。`-final.md` はある段の是正反映が完了した合図で、そのレビュー実行の中で確定内容が
    そのまま確定版（cvr-improvement-plan）へ反映されるため、これが最新の到達点ということは
    確定版側にすでに反映済みのはず。反映済みの内容を「進行中」として重複表示すると、
    確定版のカードと進行中バッジが混ざって見える（06のようにクライアント向け確定版が1本しか
    無いチェーンでは、個別の段の確定を示すファイルが無いためこの判定が必要になる）。"""
    if not past_dir.is_dir():
        return None
    found: tuple[Path, str] | None = None
    for filename, status in steps:
        candidate = past_dir / filename
        if candidate.is_file():
            found = (candidate, status)
    if found is not None and found[0].name == "08-target-page-plan-final.md":
        try:
            review = found[0].read_text(encoding="utf-8")
        except OSError:
            return found
        # レビューは可読性のためラベルを Markdown 太字にすることがある。
        # `**選定の判定**: 妥当` もプレーン表記と同じ確定判定として扱う。
        selection_ok = re.search(
            r"\*{0,2}選定の判定\*{0,2}\s*[:：]\s*\*{0,2}妥当", review
        ) is not None
        proposal_ok = re.search(
            r"\*{0,2}改善案の判定\*{0,2}\s*[:：]\s*\*{0,2}妥当", review
        ) is not None
        if selection_ok and proposal_ok:
            return None
        return found[0], "②レビュー差し戻し・対応待ち"
    if found is not None and found[0].name.endswith("-final.md"):
        return None
    return found


def _add_registered_reports(section: ThemeSection, theme_dir: Path, meta: dict, client_dir: Path) -> None:
    found_any = False
    chain_meta = meta.get("chain") or {}
    for basename, title, desc in meta["reports"]:
        path = _find_by_basename(theme_dir, basename)
        if path is not None:
            found_any = True
            section.reports.append(
                ReportEntry(
                    title=title,
                    desc=desc,
                    href=_rel(path, client_dir),
                    updated_at=_mtime(path),
                    pdf_href=_pdf_href_for(path, client_dir),
                )
            )
        # 確定版（この基準名）の有無に関わらず、進行中の判定は独立して行う。06のように
        # 確定版が複数段を束ねた1本しか無いテーマでは、確定版が既にあっても
        # まだそこに反映されていない次の段の作業が _past/ にありうるため（例:
        # ①が確定して確定版ができた後、②の分析が進行中）、確定版の有無で進行中の
        # 表示を打ち切らない。反映済みの段が「進行中」として重複表示されないための
        # 規則は _find_chain_progress 側（`-final.md` が最新到達点なら None を返す）にある。
        chain = chain_meta.get(basename)
        if not chain:
            continue
        progress_title, steps = chain
        progress = _find_chain_progress(theme_dir / "_past", steps)
        if progress is not None:
            progress_path, status = progress
            section.progress.append(
                ProgressEntry(
                    title=progress_title,
                    status=status,
                    href=_rel(progress_path, client_dir),
                    updated_at=_mtime(progress_path),
                )
            )
    # チェーンを持つテーマ（06等）は、構成を知らないファイルを一覧に混ぜない。
    # 未着手（confirmedもprogressも無い）は「まだレポートがありません」のままにする。
    if not found_any and not chain_meta:
        _add_fallback_reports(section, theme_dir, client_dir)


def _add_topic_subfolder_reports(section: ThemeSection, theme_dir: Path, meta: dict, client_dir: Path) -> None:
    reports_meta = meta.get("reports") or []
    basename = reports_meta[0][0] if reports_meta else None
    base_title = reports_meta[0][1] if reports_meta else None
    generic_desc = reports_meta[0][2] if reports_meta else "調査結果をまとめたレポート"

    subdirs = []
    try:
        subdirs = [d for d in theme_dir.iterdir() if d.is_dir() and not _is_excluded_dir(d.name)]
    except OSError:
        pass
    subdirs.sort(key=lambda d: d.name)

    if not subdirs:
        # サブフォルダに分けていない旧来の置き方にもフォールバックする
        _add_registered_reports(section, theme_dir, meta, client_dir)
        return

    # 03のように対象違いの調査が複数トピック並ぶことがある。タイトルがフォルダ名（英字スラッグ等）
    # だけになると他テーマの日本語タイトルの中で浮くため、レジストリの表示名を基本にし、
    # 複数トピックがあるときだけフォルダ名から推測した対象名を添えて区別する。
    multiple = len(subdirs) > 1
    for sub in subdirs:
        path = _find_by_basename(sub, basename) if basename else None
        matched_registry = path is not None
        if path is None:
            candidates = _fallback_reports(sub)
            path = candidates[0] if candidates else None
        if path is None:
            continue
        topic = _humanize_topic_name(sub.name)
        if matched_registry and base_title:
            title = f"{base_title}（{topic}）" if multiple else base_title
        else:
            # レジストリの基準ファイルが見つからない（旧命名・未対応の内容）場合は
            # 何のレポートか判断できないため、従来どおりフォルダ名をそのまま出す。
            title = topic
        section.reports.append(
            ReportEntry(
                title=title,
                desc=generic_desc,
                href=_rel(path, client_dir),
                updated_at=_mtime(path),
                pdf_href=_pdf_href_for(path, client_dir),
            )
        )


def _add_fallback_reports(section: ThemeSection, theme_dir: Path, client_dir: Path) -> None:
    for path in _fallback_reports(theme_dir):
        title = _humanize_stem(path.stem)
        section.reports.append(
            ReportEntry(
                title=title,
                desc="このフォルダで見つかった成果物",
                href=_rel(path, client_dir),
                updated_at=_mtime(path),
                pdf_href=_pdf_href_for(path, client_dir),
            )
        )


def build_sections(client_dir: Path) -> list[ThemeSection]:
    sections: list[ThemeSection] = []
    for theme_dir in discover_theme_dirs(client_dir):
        meta = _THEME_REGISTRY.get(theme_dir.name)
        label = meta["label"] if meta else _default_label(theme_dir.name)
        nav_label = meta.get("nav_label", label) if meta else re.sub(r"^\d\d\s+", "", label)
        section = ThemeSection(label=label, nav_label=nav_label)
        if meta and meta.get("topic_subfolders"):
            _add_topic_subfolder_reports(section, theme_dir, meta, client_dir)
        elif meta:
            _add_registered_reports(section, theme_dir, meta, client_dir)
        else:
            _add_fallback_reports(section, theme_dir, client_dir)
        sections.append(section)
    return sections


@dataclass(frozen=True)
class TocItem:
    level: str
    section: str
    label_html: str


@dataclass(frozen=True)
class ReportNavigation:
    label: str
    path: Path
    href: str
    items: tuple[TocItem, ...]


def _extract_report_toc(path: Path) -> tuple[TocItem, ...]:
    """単体目次、または再生成済みアコーディオンの現在レポートから見出しを読む。"""
    try:
        html = path.read_text(encoding="utf-8")
    except OSError:
        return ()
    nav_match = _REPORT_NAV_RE.search(html)
    if nav_match is None:
        return ()
    nav_html = nav_match.group(0)
    current_match = _CURRENT_REPORT_GROUP_RE.search(nav_html)
    own_nav = current_match.group(1) if current_match is not None else nav_html
    return tuple(
        TocItem(
            level=match.group("level"),
            section=match.group("section"),
            label_html=match.group("label"),
        )
        for match in _TOC_ITEM_RE.finditer(own_nav)
        if match.group("href") == match.group("section")
    )


def _report_navigation(client_dir: Path, sections: list[ThemeSection]) -> list[ReportNavigation]:
    navigation: list[ReportNavigation] = []
    for section in sections:
        html_reports = [report for report in section.reports if report.href.lower().endswith(".html")]
        for report in html_reports:
            path = client_dir / Path(report.href)
            if not path.is_file():
                continue
            label = section.nav_label if len(html_reports) == 1 else report.title
            navigation.append(
                ReportNavigation(
                    label=label,
                    path=path,
                    href=report.href,
                    items=_extract_report_toc(path),
                )
            )
    return navigation


def _relative_report_href(source: ReportNavigation, target: ReportNavigation) -> str:
    source_dir = posixpath.dirname(source.href) or "."
    return posixpath.relpath(target.href, source_dir)


def _accordion_nav(current: ReportNavigation, navigation: list[ReportNavigation]) -> str:
    groups: list[str] = []
    for target in navigation:
        is_current = target.path.resolve() == current.path.resolve()
        attributes = (
            ' name="report-toc" data-report-current="true" open'
            if is_current
            else ' name="report-toc" data-report-current="false"'
        )
        items: list[str] = []
        report_href = _relative_report_href(current, target)
        for item in target.items:
            href = f"#{item.section}" if is_current else f"{report_href}#{item.section}"
            safe_href = escape(href, quote=True)
            safe_section = escape(item.section, quote=True)
            data_section = f' data-section="{safe_section}"' if is_current else ""
            items.append(
                f'<li class="toc-level-{item.level}"><a href="{safe_href}"{data_section}>{item.label_html}</a></li>'
            )
        if items:
            content = "<ol>" + "".join(items) + "</ol>"
        else:
            content = (
                '<div class="toc-report-empty">'
                f'<a href="{escape(report_href, quote=True)}">レポートを開く</a></div>'
            )
        groups.append(
            f'<details class="toc-report-group"{attributes}>'
            f'<summary class="toc-report-summary">{escape(target.label)}</summary>'
            f"{content}</details>"
        )
    return (
        '<aside class="report-nav" aria-label="全レポートの目次">'
        '<div class="toc-title">目次</div>'
        + "".join(groups)
        + '<a class="back-to-top" href="#report-top">先頭へ戻る</a></aside>'
    )


def _inject_report_navigation(client_dir: Path, sections: list[ThemeSection]) -> None:
    """全レポートの目次を各HTMLへ入れ、現在のレポートだけを開いた状態にする。"""
    navigation = _report_navigation(client_dir, sections)
    if not navigation:
        return
    for current in navigation:
        try:
            html = current.path.read_text(encoding="utf-8")
        except OSError:
            continue
        if _REPORT_NAV_RE.search(html) is None:
            continue
        html = _REPORT_NAV_RE.sub(_accordion_nav(current, navigation), html, count=1)
        if _ACCORDION_STYLE_RE.search(html):
            html = _ACCORDION_STYLE_RE.sub(_ACCORDION_STYLE, html, count=1)
        elif "</head>" in html:
            html = html.replace("</head>", f"{_ACCORDION_STYLE}\n</head>", 1)
        current.path.write_text(html, encoding="utf-8")


# --- HTML生成 -----------------------------------------------------------
# コアCSSは common/report_export/design_system/design-system.md の
# 「コアCSS（全成果物に丸ごと埋め込む）」節をそのまま埋め込む（意図的な二重管理。
# 配布先で1ファイルで開ける必要があるため外部CSSは参照しない）。
_CORE_CSS = """
:root{
  --gold:#D4AF37; --gold-dark:#9A7B1F; --gold-bright:#E3C457; --gold-soft:#FBF6E8;
  --gray-50:#fafafa; --gray-100:#f5f5f5; --gray-200:#e5e5e5; --gray-300:#d4d4d4;
  --gray-400:#a3a3a3; --gray-500:#737373; --gray-700:#404040; --gray-900:#171717; --white:#ffffff;
  --red:#b91c1c; --green:#15803d;
}
*{ margin:0; padding:0; box-sizing:border-box; }
html{ scroll-behavior:smooth; }
body{
  font-family:"Hiragino Kaku Gothic ProN","Noto Sans JP","Yu Gothic","Meiryo",sans-serif;
  color:var(--gray-900); line-height:1.8; -webkit-font-smoothing:antialiased;
  font-feature-settings:"palt" 1;
}
.section-label{ font-size:11px; font-weight:700; letter-spacing:.16em; text-transform:uppercase; color:var(--gold-dark); display:flex; align-items:center; gap:8px; margin-bottom:10px; }
.section-label::before{ content:""; width:16px; height:2px; background:var(--gold); flex:none; }
.section-title{ font-size:23px; font-weight:800; line-height:1.4; letter-spacing:-.01em; color:var(--gray-900); margin-bottom:14px; }
.section-summary{ font-size:14px; color:var(--gray-700); line-height:1.95; margin-bottom:20px; }
.card{ padding:18px 20px; background:var(--gray-50); border:none; }
.card .card-title{ font-size:14px; font-weight:800; color:var(--gray-900); margin-bottom:7px; letter-spacing:-.005em; }
.card .card-body{ font-size:12.5px; color:var(--gray-700); line-height:1.85; }

/* コールアウト（design-system.md §2 と同一定義。01の登録情報の置き場を示す注記に使う） */
.callout{ display:flex; align-items:flex-start; gap:12px; margin-top:16px; padding:15px 18px; background:var(--gray-50); font-size:13px; line-height:1.9; color:var(--gray-700); }
.callout-icon{ flex-shrink:0; width:24px; height:24px; background:var(--gray-900); color:var(--white); display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:700; }
"""

_PAGE_CSS = """
body{ background:var(--white); padding:40px 24px 80px; }
.index-page{ max-width:760px; margin:0 auto; }
.index-header{ margin-bottom:24px; }
.index-header + .callout{ margin-top:0; margin-bottom:32px; }
.callout a{ color:var(--gray-900); font-weight:700; text-decoration:underline; }
.callout a:hover{ color:var(--gold-dark); }
.theme-block{ margin-bottom:32px; }
.theme-block .section-title{ font-size:16px; margin-bottom:12px; }
.report-list{ display:flex; flex-direction:column; gap:10px; }
.report-card{ display:block; color:inherit; }
.report-actions{ display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; }
.report-action{
  display:inline-block; padding:7px 12px; font-size:12px; font-weight:700;
  text-decoration:none; border:1px solid var(--gray-300); color:var(--gray-700); background:var(--white);
}
.report-action:hover{ background:var(--gray-100); color:var(--gray-900); }
.report-action.primary{ border-color:var(--gray-900); color:var(--white); background:var(--gray-900); }
.report-action.primary:hover{ background:var(--gray-700); }
.report-meta{ font-size:11px; color:var(--gray-500); margin-top:8px; font-variant-numeric:tabular-nums; }
.empty-note{ font-size:12.5px; color:var(--gray-500); padding:12px 0; }
.index-footer{ margin-top:48px; font-size:11px; color:var(--gray-400); }

/* 進行中（確定版がまだ無いチェーンの途中経過）。良否の判定ではないため、ゴールドの文字で控えめに示す。 */
.progress-list{ display:flex; flex-direction:column; gap:8px; margin-top:10px; }
.progress-item{ padding:10px 2px; }
.progress-badge{ font-size:10px; font-weight:700; letter-spacing:.06em; color:var(--gold-dark); margin-right:8px; }
.progress-title{ font-size:12.5px; font-weight:700; color:var(--gray-700); }
.progress-status{ font-size:12px; color:var(--gray-500); margin-top:4px; }
.progress-link{ font-size:11.5px; color:var(--gray-500); text-decoration:underline; display:inline-block; margin-top:6px; }
.progress-link:hover{ color:var(--gray-700); }
"""


def _format_dt(dt: datetime | None) -> str:
    if dt is None:
        return "更新日時不明"
    return dt.strftime("%Y-%m-%d %H:%M")


def render_html(client_id: str, sections: list[ThemeSection], generated_at: datetime) -> str:
    safe_client = escape(client_id)
    body_parts = [
        '<div class="index-page">',
        '<header class="index-header">',
        '<div class="section-label">OUTPUTS</div>',
        f'<h1 class="section-title">{safe_client} の成果物</h1>',
        '<p class="section-summary">まずここから。実行済みのエージェントごとに、いま見るべき最新のレポートをまとめている。</p>',
        "</header>",
    ]

    if not sections:
        body_parts.append(
            '<p class="empty-note">まだ成果物がありません。各エージェントを実行すると、ここに一覧が表示されます。</p>'
        )
    else:
        for section in sections:
            body_parts.append('<section class="theme-block">')
            body_parts.append(f'<div class="section-label">{escape(section.label)}</div>')
            if not section.reports and not section.progress:
                body_parts.append('<p class="empty-note">まだレポートがありません。</p>')
            else:
                if section.reports:
                    body_parts.append('<div class="report-list">')
                    for report in section.reports:
                        primary_label = "HTMLで見る" if report.href.lower().endswith(".html") else "Markdownで見る"
                        actions = (
                            '<div class="report-actions">'
                            f'<a class="report-action primary" href="{escape(report.href)}">{primary_label}</a>'
                        )
                        if report.pdf_href:
                            actions += (
                                f'<a class="report-action" href="{escape(report.pdf_href)}">PDFを開く</a>'
                            )
                        actions += "</div>"
                        body_parts.append(
                            '<div class="card report-card">'
                            f'<div class="card-title">{escape(report.title)}</div>'
                            f'<div class="card-body">{escape(report.desc)}</div>'
                            f'<div class="report-meta">更新: {escape(_format_dt(report.updated_at))}</div>'
                            f"{actions}</div>"
                        )
                    body_parts.append("</div>")
                if section.progress:
                    # 確定版と混ざらないよう別枠にし、前面には出さない（控えめな表示。docs/standard-run-order.md §4）
                    body_parts.append('<div class="progress-list">')
                    for p in section.progress:
                        body_parts.append(
                            '<div class="progress-item">'
                            '<span class="progress-badge">進行中</span>'
                            f'<span class="progress-title">{escape(p.title)}</span>'
                            f'<p class="progress-status">{escape(p.status)}</p>'
                            f'<a class="progress-link" href="{escape(p.href)}">途中の成果物を見る（社内確認用）→</a>'
                            f'<div class="report-meta">更新: {escape(_format_dt(p.updated_at))}</div>'
                            "</div>"
                        )
                    body_parts.append("</div>")
            body_parts.append("</section>")

    body_parts.append(
        f'<div class="index-footer">生成: {escape(_format_dt(generated_at))}（common/report_index）</div>'
    )
    body_parts.append("</div>")
    body = "\n".join(body_parts)

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_client} の成果物</title>
<style>{_CORE_CSS}
{_PAGE_CSS}</style>
</head>
<body>
{body}
</body>
</html>
"""


def build_index(client_dir: Path, client_id: str | None = None, generated_at: datetime | None = None) -> str:
    """client_dir（outputs/{client_id}）を走査してindex.htmlの内容を作る。"""
    client_dir = Path(client_dir)
    resolved_client_id = client_id or client_dir.name
    sections = build_sections(client_dir)
    return render_html(resolved_client_id, sections, generated_at or datetime.now())


def write_index(client_dir: Path, client_id: str | None = None) -> Path:
    """index.htmlを client_dir/index.html に書き出し、そのパスを返す。"""
    client_dir = Path(client_dir)
    client_dir.mkdir(parents=True, exist_ok=True)
    sections = build_sections(client_dir)
    resolved_client_id = client_id or client_dir.name
    html = render_html(resolved_client_id, sections, datetime.now())
    out_path = client_dir / "index.html"
    out_path.write_text(html, encoding="utf-8")
    _inject_report_navigation(client_dir, sections)
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="outputs/{client_id}/ を走査して index.html を作る")
    parser.add_argument("client_dir", help="outputs/{client_id} のパス")
    parser.add_argument("--client-id", default=None, help="表示に使うclient_id（省略時はフォルダ名）")
    args = parser.parse_args(argv)

    out_path = write_index(Path(args.client_dir), client_id=args.client_id)
    print(str(out_path.resolve()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
