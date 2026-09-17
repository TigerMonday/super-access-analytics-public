"""GTM コンテナ エクスポート JSON を読んで構成レポートとバージョン差分を作る。

GTM の閲覧権限が下りない案件でも、クライアントに管理画面から
「管理 → コンテナをエクスポート → 公開中のバージョン → JSONをダウンロード」
を依頼すれば、API と同じ全量が手に入る。本モジュールはその JSON を入力にする。

3つの取得手段の使い分け（読む前に必ず把握すること）:

| | `gtm.py`（API） | `gtm_export.py`（エクスポート） | `gtm_public.py`（gtm.js） |
|---|---|---|---|
| 必要なもの | GTM 閲覧権限 | クライアントの手作業 | 何も要らない |
| タグ名・トリガー名 | 取得できる | **取得できる** | 取得できない |
| メモ（notes） | 取得できる | **取得できる** | 取得できない |
| 発火オプション | 取得できる | **取得できる** | 一部のみ |
| 一時停止タグ | 取得できる | 取得できる | 個数のみ |
| 対象バージョン | 任意 | エクスポート時に選んだもの | 公開中のみ |

エクスポートは**バージョンを選び間違えやすい**。`containerVersionId` が `0` のものは
ワークスペースのエクスポートで、公開中の内容とは限らない（ワークスペースは公開しても
最新バージョンに自動追従しないため、古いバージョンのまま残っていることがある）。
`report` は先頭でこれを警告する。公開中バージョンの番号は
`gtm_public.py dump` が表示する `version` と突き合わせて確認すること。

使い方:

    # 構成レポート（Markdown）
    python gtm_export.py report --in GTM-XXXXXXX_v121.json --out docs/gtm-report.md

    # バージョン間の差分
    python gtm_export.py diff --old GTM-XXXXXXX_v120.json --new GTM-XXXXXXX_v121.json \
        --out docs/gtm-diff.md

    # コミット前の秘匿情報チェック（カスタムHTMLにトークンが直書きされていないか）
    python gtm_export.py scan --in GTM-XXXXXXX_v121.json

読み取り専用。タグマネージャには一切書き込まない。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# ワイルドカードで全カスタムイベントを拾うトリガーの表示名
ANY_DATALAYER_EVENT = "(すべてのカスタムイベント)"

# GA4 へ送るタグの type。gaawe = GA4 イベント / googtag = Google タグ（設定）
#
# **googtag は GA4 専用ではない。** 同じタグ種別で Google 広告（`AW-`）や
# Floodlight（`DC-`）も設定するため、種別だけで GA4 と判定すると広告タグを
# 「GA4 の送信先」に数えてしまう。GA4 かどうかは測定IDの接頭辞で見る。
GA4_TAG_TYPES = ("gaawe", "googtag")

# GA4 の測定IDの接頭辞。変数参照（`{{...}}`）は解決できないので GA4 側に寄せて扱う
# （GA4 タグの送信先を変数で切り替える構成が一般的なため）。
GA4_ID_PREFIX = "G-"
NON_GA4_ID_PREFIXES = ("AW-", "DC-", "GT-")

# 送信系タグ（一覧表に載せる対象）。cvt_* はカスタムテンプレートなので別扱い。
MEASUREMENT_TAG_TYPES = GA4_TAG_TYPES + ("awct", "baut", "ua", "sp", "awud")

TAG_TYPE_LABELS = {
    "gaawe": "GA4 イベント",
    "googtag": "Google タグ",
    "html": "カスタム HTML",
    "awct": "Google Ads コンバージョン",
    "awud": "Google Ads ユーザーデータ",
    "baut": "Microsoft Ads",
    "ua": "ユニバーサル アナリティクス",
    "sp": "その他",
    "gclidw": "コンバージョン リンカー",
    "cegg": "Crazy Egg",
}

CONDITION_LABELS = {
    "EQUALS": "=",
    "CONTAINS": "含む",
    "STARTS_WITH": "前方一致",
    "ENDS_WITH": "後方一致",
    "MATCH_REGEX": "正規表現一致",
    "CSS_SELECTOR": "CSSセレクタ一致",
    "URL_MATCHES": "URL一致",
    "LESS": "<",
    "LESS_OR_EQUALS": "<=",
    "GREATER": ">",
    "GREATER_OR_EQUALS": ">=",
}

# 組み込みトリガーはエクスポートの `trigger` 配列に含まれない（ID だけが参照される）。
# ID を引けないと発火条件が「?」になり、全ページで動くタグを見落とす。
BUILT_IN_TRIGGERS = {
    "2147479553": "All Pages（全ページ・ページビュー）",  # leak-ok: GTMの組み込みトリガーID（Google共通の固定値・実クライアントの値ではない）
    "2147479573": "Initialization（初期化）",  # leak-ok: GTMの組み込みトリガーID（Google共通の固定値・実クライアントの値ではない）
}

FIRING_OPTION_LABELS = {
    "ONCE_PER_EVENT": "イベントごと",
    "ONCE_PER_LOAD": "1ページに1回",
    "UNLIMITED": "制限なし",
}

# 秘匿情報の疑いがあるパターン。カスタムHTMLにトークンを直書きしている事故を拾う。
# 公開 gtm.js にそのまま載る値（＝ブラウザから誰でも読める）なので「秘密ではない」が、
# リポジトリに入れる前に人が中身を見て判断するための足がかりにする。
SECRET_PATTERNS = [
    ("Bearer トークン", re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}")),
    ("Authorization ヘッダ", re.compile(r"(?i)authorization['\"]?\s*[:=]")),
    ("api_key / apiKey", re.compile(r"(?i)api[_-]?key['\"]?\s*[:=]\s*['\"][^'\"]{12,}")),
    ("secret", re.compile(r"(?i)(client_secret|secret_key|app_secret)['\"]?\s*[:=]")),
    ("password", re.compile(r"(?i)passw(or)?d['\"]?\s*[:=]")),
    ("秘密鍵", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("JWT", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("32桁以上の16進文字列", re.compile(r"\b[0-9a-f]{32,}\b")),
]


# ──────────────────────────────────────
# 読み込み
# ──────────────────────────────────────

def load(path: str | Path) -> dict:
    """エクスポート JSON を読み、`containerVersion` を返す。

    形式が違う場合は何が足りないかを添えて落とす。GTM の「バージョンをエクスポート」
    以外（GA4 の設定コピーなど）を渡す取り違えが起きやすいため。
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if "containerVersion" not in raw:
        raise ValueError(
            f"{path}: GTM のコンテナ エクスポート JSON ではありません"
            "（トップレベルに containerVersion がない）。"
            "GTM 管理画面 → 管理 → コンテナをエクスポート で出力したファイルを指定してください。"
        )
    cv = raw["containerVersion"]
    cv["_exportTime"] = raw.get("exportTime", "")
    cv["_exportFormatVersion"] = raw.get("exportFormatVersion", "")
    return cv


def is_workspace_export(cv: dict) -> bool:
    """ワークスペースのエクスポート（＝公開中の内容とは限らない）か。"""
    return str(cv.get("containerVersionId", "")) in ("", "0")


def container_label(cv: dict) -> str:
    c = cv.get("container", {})
    return f"{c.get('name', '?')}（{c.get('publicId', '?')}）"


# ──────────────────────────────────────
# 参照の解決
# ──────────────────────────────────────

def param_map(obj: dict) -> dict:
    """`parameter` のリストを {key: 値} に畳む。list/map はそのまま値として持つ。"""
    out: dict = {}
    for p in obj.get("parameter", []) or []:
        out[p.get("key")] = p.get("value", p.get("list", p.get("map")))
    return out


def _condition(cond: dict) -> str:
    p = param_map(cond)
    label = CONDITION_LABELS.get(cond.get("type", ""), cond.get("type", "?"))
    text = f"{p.get('arg0', '?')} {label} {p.get('arg1', '')}".strip()
    # negate は `type` ではなく parameter 側に入る。読み落とすと条件が逆になる。
    if str(p.get("negate", "")).lower() == "true":
        text = f"NOT({text})"
    return text


def trigger_conditions(trigger: dict) -> list[str]:
    """トリガーの発火条件を人が読める文字列にする。

    `customEventFilter`（イベント名の条件）と `filter`（その他の条件）は AND で結ばれる。
    片方だけ読むと条件を取り違えるので必ず両方を見る。
    """
    parts = [_condition(c) for c in trigger.get("customEventFilter", []) or []]
    parts += [_condition(c) for c in trigger.get("filter", []) or []]
    if not parts:
        return [trigger.get("type", "?")]
    return [" かつ ".join(parts)]


def datalayer_events_of(trigger: dict) -> list[str]:
    """トリガーが待ち受けている dataLayer イベント名。

    完全一致（`{{_event}} EQUALS xxx`）以外は個別のイベント名に落とせないので、
    ワイルドカード扱いにして `ANY_DATALAYER_EVENT` を返す。
    """
    names: list[str] = []
    wildcard = False
    for c in trigger.get("customEventFilter", []) or []:
        p = param_map(c)
        if p.get("arg0") != "{{_event}}":
            continue
        if c.get("type") == "EQUALS" and str(p.get("negate", "")).lower() != "true":
            names.append(str(p.get("arg1", "")))
        else:
            wildcard = True
    if wildcard and not names:
        names.append(ANY_DATALAYER_EVENT)
    if not names and trigger.get("type") == "CUSTOM_EVENT":
        names.append(ANY_DATALAYER_EVENT)
    return names


def tag_destination(tag: dict) -> str:
    """GA4/広告タグの送信先ID。変数参照ならその名前がそのまま出る。"""
    p = param_map(tag)
    for key in ("measurementIdOverride", "tagId", "conversionId", "tagID"):
        if p.get(key):
            return str(p[key])
    return "—"


def tag_event_name(tag: dict) -> str:
    return str(param_map(tag).get("eventName", ""))


def firing_option(tag: dict) -> str:
    opt = tag.get("tagFiringOption", "ONCE_PER_EVENT")
    return FIRING_OPTION_LABELS.get(opt, opt)


def type_label(tag: dict) -> str:
    t = tag.get("type", "")
    if t.startswith("cvt_"):
        return "カスタム テンプレート"
    return TAG_TYPE_LABELS.get(t, t)


# ──────────────────────────────────────
# 分析
# ──────────────────────────────────────

def index_triggers(cv: dict) -> dict[str, dict]:
    return {t["triggerId"]: t for t in cv.get("trigger", [])}


def tags_by_datalayer_event(cv: dict) -> dict[str, list[dict]]:
    """dataLayer イベント名 → そのイベントで発火する GA4 タグ一覧。"""
    trg = index_triggers(cv)
    by_event: dict[str, list[dict]] = defaultdict(list)
    for tag in cv.get("tag", []):
        if not is_ga4_tag(tag) or tag.get("paused"):
            continue
        for tid in tag.get("firingTriggerId", []) or []:
            for name in datalayer_events_of(trg.get(tid, {})):
                if tag not in by_event[name]:
                    by_event[name].append(tag)
    return dict(sorted(by_event.items()))


def duplicate_sends(cv: dict) -> dict[str, tuple[list[dict], bool]]:
    """同一 dataLayer イベントに複数の GA4 イベントタグがぶら下がっている箇所。

    返すのは {dataLayer イベント名: (タグ一覧, 確実に二重計上か)}。

    **本数が多いだけでは二重計上ではない。** 同じ行動を種別ごとに別のイベント名で
    送り分ける構成（`conversion` → `conversion` と `generate_lead`）は意図的な設計で、
    GA4 上は別イベントになるため重複しない。
    「送信先と GA4 イベント名の両方が同じ」ものだけが確実な二重計上で、そこに True を返す。
    残りは仕分けが要る候補として False を返す。

    ワイルドカードのタグ（全カスタムイベント転送）は個別イベントの一覧に現れないため、
    `wildcard_tags()` で別途扱うこと。
    """
    trg = index_triggers(cv)
    out: dict[str, tuple[list[dict], bool]] = {}
    for ev, tags in tags_by_datalayer_event(cv).items():
        senders = [t for t in tags if t.get("type") == "gaawe"]
        if len(senders) <= 1:
            continue
        # 「送信先 × GA4 イベント名」が同じタグ同士だけが重複しうる。
        # グループ単位で見る。行全体で判定すると、条件付きのタグが1本混ざっただけで
        # 無条件タグ同士の確実な重複まで見逃す。
        groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for t in senders:
            groups[(tag_destination(t), tag_event_name(t))].append(t)
        # 追加条件（URL 等）が付いていれば相互排他で同時に発火しないことがあるので、
        # 無条件のタグが2本以上あるグループだけを「確実」とする。
        certain = any(
            len([t for t in g if not _has_extra_filter(t, trg, ev)]) > 1
            for g in groups.values()
        )
        out[ev] = (senders, certain)
    return out


def _has_extra_filter(tag: dict, triggers: dict[str, dict], event: str) -> bool:
    """`event` を拾うトリガーがすべて、イベント名以外の絞り込み（URL 等）付きか。

    1本のタグが同じ dataLayer イベントを「無条件トリガー」と「条件付きトリガー」の
    両方から拾っていることがある。その場合は無条件で発火するので、条件付き扱いに
    してはいけない（本物の二重計上を取りこぼす）。
    """
    if tag.get("blockingTriggerId"):
        return True
    relevant = [
        triggers[tid] for tid in tag.get("firingTriggerId", []) or []
        if tid in triggers and event in datalayer_events_of(triggers[tid])
    ]
    if not relevant:
        return False
    return all(tr.get("filter") for tr in relevant)


def wildcard_tags(cv: dict) -> list[dict]:
    """あらゆるカスタムイベントに掛かる GA4 タグ（＝全イベントを二重に送る候補）。"""
    return tags_by_datalayer_event(cv).get(ANY_DATALAYER_EVENT, [])


def is_ga4_tag(tag: dict) -> bool:
    """GA4 へ送るタグか。googtag は広告タグとも共用なので測定IDで判別する。

    `gaawe`（GA4 イベント）は種別だけで確定する。`googtag`（Google タグ）は
    GA4・Google 広告・Floodlight で共用なので、測定IDを見て判別する。
    判別できないもの（IDが空／未知の接頭辞）は **GA4 に数えない**。
    誤って数えると「GA4 の送信先」「測定ID直書き」の件数が水増しされ、
    そのままクライアントへの指摘件数になってしまう。
    """
    kind = tag.get("type")
    if kind == "gaawe":
        return True
    if kind != "googtag":
        return False
    dest = tag_destination(tag)
    if dest.startswith("{{"):
        return True  # 変数参照。GA4 タグの送信先切り替えとして扱う
    return dest.startswith(GA4_ID_PREFIX)


def hardcoded_destinations(cv: dict) -> list[dict]:
    """測定IDを変数経由ではなく直書きしている GA4 タグ。

    環境判定（本番/ステージング/ローカルで送信先を振り分ける変数）を通らないため、
    検証環境の操作が本番プロパティに混ざる原因になる。
    広告タグ（`AW-`/`DC-`）は GA4 プロパティ混入の話ではないので含めない。
    """
    return [
        t for t in cv.get("tag", [])
        if is_ga4_tag(t)
        and not t.get("paused")
        and not tag_destination(t).startswith("{{")
        and tag_destination(t) != "—"
    ]


def notes_of(cv: dict) -> list[tuple[str, str, str]]:
    """タグ・トリガー・変数に書かれたメモ。引き継ぎでいちばん情報量が多い。"""
    out: list[tuple[str, str, str]] = []
    for kind, label in (("tag", "タグ"), ("trigger", "トリガー"), ("variable", "変数")):
        for x in cv.get(kind, []):
            if x.get("notes"):
                out.append((label, x.get("name", "?"), x["notes"]))
    return out


def scan_secrets(cv: dict) -> list[tuple[str, str, str]]:
    """秘匿情報らしき文字列を含むタグを列挙する。(タグ名, 種別, 検出パターン)"""
    out: list[tuple[str, str, str]] = []
    for tag in cv.get("tag", []):
        blob = json.dumps(tag, ensure_ascii=False)
        hits = [name for name, pat in SECRET_PATTERNS if pat.search(blob)]
        if hits:
            out.append((tag.get("name", "?"), tag.get("type", "?"), " / ".join(hits)))
    return out


# ──────────────────────────────────────
# レポート
# ──────────────────────────────────────

def _esc(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def build_report(cv: dict) -> str:
    trg = index_triggers(cv)
    tags = cv.get("tag", [])
    lines = [
        f"# GTM コンテナ構成（{container_label(cv)} / エクスポート JSON より）",
        "",
        f"- アカウントID {cv.get('accountId', '?')} / コンテナID {cv.get('containerId', '?')}",
    ]
    if is_workspace_export(cv):
        lines += [
            "- **バージョン: ワークスペースのエクスポート（`containerVersionId` = 0）**",
            "",
            "> ワークスペースは公開しても最新バージョンに自動追従しない。"
            "**公開中の内容とは限らない。** 公開中バージョンの番号を "
            "`gtm_public.py dump` の出力と突き合わせ、食い違う場合は"
            "「バージョン タブ → 公開中のバージョン → エクスポート」で取り直すこと。",
        ]
    else:
        lines.append(
            f"- バージョン {cv.get('containerVersionId')} "
            f"{('「' + cv['name'] + '」') if cv.get('name') else ''}"
        )
        if cv.get("description"):
            lines += ["", "> バージョンの説明:", "> ", f"> {_esc(cv['description'])}"]
    lines += [
        f"- エクスポート日時 {cv.get('_exportTime', '?')}",
        f"- タグ {len(tags)} / トリガー {len(cv.get('trigger', []))} "
        f"/ 変数 {len(cv.get('variable', []))} "
        f"/ カスタムテンプレート {len(cv.get('customTemplate', []))}",
        f"- うち一時停止 {sum(1 for t in tags if t.get('paused'))} 本",
        "",
        "## タグ種別の内訳",
        "",
        "| 種別 | 件数 |",
        "|---|---|",
    ]
    kinds: dict[str, int] = defaultdict(int)
    for t in tags:
        kinds[type_label(t)] += 1
    for label, n in sorted(kinds.items(), key=lambda x: -x[1]):
        lines.append(f"| {label} | {n} |")

    # 送信先の内訳
    lines += ["", "## GA4 の送信先（測定ID）", "", "| 送信先 | タグ数 | 指定方法 |", "|---|---|---|"]
    dests: dict[str, int] = defaultdict(int)
    for t in tags:
        if is_ga4_tag(t) and not t.get("paused"):
            dests[tag_destination(t)] += 1
    for dest, n in sorted(dests.items(), key=lambda x: -x[1]):
        how = "変数経由（環境判定あり）" if dest.startswith("{{") else "**直書き**"
        lines.append(f"| `{dest}` | {n} | {how} |")

    hard = hardcoded_destinations(cv)
    if hard and any(d.startswith("{{") for d in dests):
        lines += [
            "",
            f"**測定IDを直書きしているタグが {len(hard)} 本ある**: "
            + " / ".join(f"`{_esc(t['name'])}`" for t in hard),
            "",
            "> 変数経由のタグは環境判定（ホスト名で本番/検証を振り分ける変数）を通るが、"
            "直書きのタグは通らない。**検証環境の操作が本番プロパティに混ざる。**",
        ]

    # 発火オプション
    lines += ["", "## 発火オプション", "", "| 設定 | GA4 イベントタグ数 |", "|---|---|"]
    opts: dict[str, int] = defaultdict(int)
    for t in tags:
        if t.get("type") == "gaawe" and not t.get("paused"):
            opts[firing_option(t)] += 1
    for label, n in sorted(opts.items(), key=lambda x: -x[1]):
        lines.append(f"| {label} | {n} |")
    lines += [
        "",
        "> 「イベントごと」は dataLayer に同じイベントが複数回 push されると"
        "**その回数だけ送信する**。アプリが1つの行動で複数回 push する実装だと、"
        "そのまま多重計上になる。「1ページに1回」はページロード単位で1回に抑える。",
    ]

    # 多重送信
    lines += ["", "## 同一イベントで複数の GA4 タグが発火する箇所", ""]
    dupes = duplicate_sends(cv)
    if not dupes:
        lines.append("該当なし。")
    else:
        lines += [
            "「二重計上」列が **確実** の行は、送信先と GA4 イベント名が同じタグが複数あるもの。",
            "**要仕分け** は、同じ dataLayer イベントから別々の GA4 イベント名で送り分けている構成で、",
            "意図的な設計のこともある（例: `conversion` を種別ごとに切り出す）。送信先と条件を見て判断する。",
            "",
            "| dataLayer イベント | 二重計上 | 発火する GA4 タグ | 送信されるイベント名 |",
            "|---|---|---|---|",
        ]
        for ev, (ts, certain) in sorted(dupes.items(), key=lambda x: -len(x[1][0])):
            names = " / ".join(f"`{_esc(t['name'])}`" for t in ts)
            sent = " / ".join(f"`{_esc(tag_event_name(t))}`" for t in ts)
            mark = "**確実**" if certain else "要仕分け"
            lines.append(f"| `{ev}` | {mark} | {len(ts)}本: {names} | {sent} |")

    wild = wildcard_tags(cv)
    if wild:
        lines += [
            "",
            f"**あらゆるカスタムイベントに掛かるタグが {len(wild)} 本ある**: "
            + " / ".join(f"`{_esc(t['name'])}`" for t in wild),
            "",
            "> `Event` を完全一致ではなく正規表現・部分一致で見ているタグ。"
            "個別イベントすべてに重ねて発火するため、**送信先が GA4 なら全イベントが二重計上される**。"
            "上の表には現れないので見落としやすい。",
        ]

    # GA4 イベントタグ一覧
    lines += [
        "", "## GA4 イベントタグ一覧", "",
        "| タグ名 | 送信イベント名 | 送信先 | 発火オプション | 発火条件 |", "|---|---|---|---|---|",
    ]
    for t in tags:
        if t.get("type") != "gaawe":
            continue
        conds = []
        for tid in t.get("firingTriggerId", []) or []:
            if tid not in trg:
                conds.append(BUILT_IN_TRIGGERS.get(tid, f"組み込みトリガー（ID {tid}）"))
                continue
            tr = trg[tid]
            conds.append(f"{tr.get('name', '?')}（{'; '.join(trigger_conditions(tr))}）")
        blocked = [
            trg[i].get("name", "?") if i in trg
            else BUILT_IN_TRIGGERS.get(i, f"組み込みトリガー（ID {i}）")
            for i in t.get("blockingTriggerId", []) or []
        ]
        cond = " または ".join(conds) or "(トリガーなし)"
        if blocked:
            cond += " ／ 例外: " + ", ".join(blocked)
        name = f"`{_esc(t['name'])}`" + ("（一時停止）" if t.get("paused") else "")
        lines.append(
            f"| {name} | `{_esc(tag_event_name(t))}` | `{_esc(tag_destination(t))}` "
            f"| {firing_option(t)} | {_esc(cond)} |"
        )

    # メモ
    notes = notes_of(cv)
    if notes:
        lines += [
            "", "## 設定に書かれたメモ", "",
            "クライアント側の担当者が残したメモ。**設計意図と既知の不具合が書かれていることが多い**ので、"
            "診断の前に必ず読む。",
            "",
        ]
        for kind, name, note in notes:
            lines += [f"### {kind}『{name}』", "", "```", note.strip(), "```", ""]

    return "\n".join(lines) + "\n"


def _normalize(obj):
    """比較用に、差分の意味を持たない項目（ID・fingerprint）を落とす。"""
    # ID はコンテナをまたぐ・再採番されると変わるが、設定の中身は同じ。落とさないと
    # 「全件が変更扱い」になって本当の差分が埋もれる。
    drop = {"fingerprint", "path", "tagManagerUrl", "containerVersionId",
            "accountId", "containerId", "parentFolderId", "_exportTime",
            "_exportFormatVersion", "tagId", "triggerId", "variableId",
            "templateId", "folderId"}
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in sorted(obj.items()) if k not in drop}
    if isinstance(obj, list):
        return [_normalize(x) for x in obj]
    return obj


def build_diff(old: dict, new: dict) -> str:
    """2バージョンの差分。名前をキーに突き合わせる（IDは版をまたぐと変わりうるため）。"""
    def ver(cv: dict) -> str:
        if is_workspace_export(cv):
            return "ワークスペース"
        return f"v{cv.get('containerVersionId')}" + (f"「{cv['name']}」" if cv.get("name") else "")

    lines = [
        f"# GTM 差分: {ver(old)} → {ver(new)}",
        "",
        f"対象コンテナ: {container_label(new)}",
        "",
    ]
    if new.get("description"):
        lines += ["新バージョンの説明:", "", "```", new["description"].strip(), "```", ""]

    total = 0
    for kind, label in (("tag", "タグ"), ("trigger", "トリガー"),
                        ("variable", "変数"), ("customTemplate", "カスタムテンプレート")):
        A = {x["name"]: _normalize(x) for x in old.get(kind, [])}
        B = {x["name"]: _normalize(x) for x in new.get(kind, [])}
        added = sorted(set(B) - set(A))
        removed = sorted(set(A) - set(B))
        changed = sorted(k for k in set(A) & set(B) if A[k] != B[k])
        total += len(added) + len(removed) + len(changed)
        lines += [
            f"## {label}（{len(old.get(kind, []))} → {len(new.get(kind, []))}）",
            "",
            f"追加 {len(added)} / 削除 {len(removed)} / 変更 {len(changed)}",
            "",
        ]
        if not (added or removed or changed):
            lines += ["差分なし。", ""]
            continue
        for name in added:
            lines.append(f"- **追加** `{name}`")
        for name in removed:
            lines.append(f"- **削除** `{name}`")
        for name in changed:
            lines.append(f"- **変更** `{name}`")
        lines.append("")

    if total == 0:
        lines += [
            "## 総評", "",
            "**2つのエクスポートは（ID と fingerprint を除いて）完全に一致している。**",
            "ワークスペースのエクスポートを公開中バージョンと取り違えていないか確認すること。",
            "",
        ]
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────
# CLI
# ──────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_report = sub.add_parser("report", help="エクスポート JSON から Markdown レポートを生成")
    p_report.add_argument("--in", dest="infile", required=True)
    p_report.add_argument("--out", required=True)

    p_diff = sub.add_parser("diff", help="2つのエクスポート JSON の差分を出す")
    p_diff.add_argument("--old", required=True)
    p_diff.add_argument("--new", required=True)
    p_diff.add_argument("--out", default="")

    p_scan = sub.add_parser("scan", help="秘匿情報らしき文字列を含むタグを列挙（コミット前チェック）")
    p_scan.add_argument("--in", dest="infile", required=True)

    args = parser.parse_args(argv)

    if args.command == "report":
        cv = load(args.infile)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(build_report(cv), encoding="utf-8")
        print(f"レポートを書き出しました → {out}")
        if is_workspace_export(cv):
            print("警告: ワークスペースのエクスポートです。公開中の内容とは限りません。",
                  file=sys.stderr)
        return 0

    if args.command == "diff":
        old, new = load(args.old), load(args.new)
        text = build_diff(old, new)
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
            print(f"差分を書き出しました → {out}")
        else:
            print(text)
        return 0

    if args.command == "scan":
        cv = load(args.infile)
        hits = scan_secrets(cv)
        if not hits:
            print("秘匿情報らしき文字列は見つかりませんでした。")
            return 0
        print(f"{len(hits)} 本のタグに該当がありました。**中身を人が見て判断すること**。")
        for name, type_, pattern in hits:
            print(f"  - {name}（{type_}）: {pattern}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
