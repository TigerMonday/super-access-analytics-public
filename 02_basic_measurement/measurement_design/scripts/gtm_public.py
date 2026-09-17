"""公開 gtm.js から GTM コンテナ構成を復元する（GTM 権限が無い案件向け）。

GTM API（`gtm.py`）はコンテナへの閲覧権限が前提。権限が下りない案件では、
サイトが公開配信している `https://www.googletagmanager.com/gtm.js?id=GTM-XXXXXXX`
をそのまま読んで、タグ・発火条件・送信先測定IDを復元する。

`gtm.py` との違い（読む前に必ず把握すること）:

| | `gtm.py`（API） | `gtm_public.py`（gtm.js） |
|---|---|---|
| 権限 | GTM 閲覧者が必要 | 不要（公開ファイル） |
| タグ名・トリガー名 | 取得できる | **取得できない**（配信時に削除される） |
| 対象 | 公開バージョン or ワークスペース | **公開中バージョンのみ** |
| 一時停止タグ | 内容も取得できる | `__paused` として個数のみ |
| カスタムHTML本文 | 取得できる | 取得できる |

そのため本モジュールは「名前」ではなく **「何のイベントが・どの条件で・どの測定IDへ送られるか」**
を軸に一覧化する。名前が要る場合はクライアントに管理画面のエクスポート JSON を依頼し、
`gtm_export.py` で解析する。

使い方:

    # サイトから GTM / GA4 / Google Ads の各IDを検出
    python gtm_public.py discover --url https://example.com --out _data/09-site-implementation.json

    # コンテナを取得して正規化 JSON に落とす
    python gtm_public.py dump --container GTM-XXXXXXX --out _data/09-gtm-public.json

    # 正規化 JSON から人間可読レポート（Markdown）を作る
    python gtm_public.py report --in _data/09-gtm-public.json --out docs/gtm-public-report.md

読み取り専用。サイトにもタグマネージャにも一切書き込まない。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

UA = "Mozilla/5.0 (compatible; SAAConfigCheck/1.0)"
GTM_JS = "https://www.googletagmanager.com/gtm.js?id={container_id}"

ID_PATTERNS = {
    "gtm_containers": r"GTM-[A-Z0-9]{6,}",
    "ga4_measurement_ids": r"G-[A-Z0-9]{8,}",
    "google_ads_ids": r"AW-\d{9,}",
    "floodlight_ids": r"DC-\d{6,}",
    "universal_analytics_ids": r"UA-\d{4,}-\d+",
}

# 完全一致以外（正規表現・部分一致）で Event を見ているトリガーを表す擬似的な名前。
# 「あらゆるカスタムイベントに掛かるタグ」を集計対象に載せるために使う。
ANY_DATALAYER_EVENT = "(すべてのカスタムイベント)"

# gtm.js の関数名 → 人間向けラベル
TAG_FUNCTIONS = {
    "__googtag": "Google タグ（基盤設定）",
    "__gaawe": "GA4 イベント",
    "__html": "カスタム HTML",
    "__paused": "一時停止中",
    "__awct": "Google 広告 コンバージョン",
    "__awud": "Google 広告 ユーザー提供データ",
    "__gclidw": "コンバージョンリンカー",
    "__baut": "Microsoft 広告（UET）",
    "__tg": "Google Ads リマーケティング",
    "__ua": "Universal Analytics（2024/7 に計測停止済み）",
    "__sp": "Google Ads リマーケティング（旧）",
    "__lcl": "リンククリック リスナー",
}

MACRO_FUNCTIONS = {
    "__e": "イベント名",
    "__v": "dataLayer 変数",
    "__u": "URL",
    "__c": "定数",
    "__jsm": "カスタム JavaScript",
    "__d": "DOM 要素",
    "__k": "Cookie",
    "__aev": "自動イベント変数",
    "__r": "乱数",
    "__smm": "ルックアップテーブル",
    "__remm": "ルックアップテーブル（正規表現）",
    "__f": "リファラ",
    "__cid": "コンテナID",
}

PREDICATE_OPS = {
    "_eq": "=",
    "_neq": "≠",
    "_cn": "含む",
    "_nc": "含まない",
    "_sw": "前方一致",
    "_ew": "後方一致",
    "_re": "正規表現一致",
    "_nr": "正規表現不一致",
    "_lt": "<",
    "_le": "≦",
    "_gt": ">",
    "_ge": "≧",
    "_css": "CSS セレクタ一致",
}


# ──────────────────────────────────────
# 取得
# ──────────────────────────────────────

def http_get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        charset = res.headers.get_content_charset() or "utf-8"
        return res.read().decode(charset, errors="replace")


def discover_ids(html: str) -> dict[str, list[str]]:
    """HTML から各種計測IDを検出する。"""
    return {key: sorted(set(re.findall(pat, html))) for key, pat in ID_PATTERNS.items()}


def inspect_site(url: str) -> dict:
    """公開サイトのHTMLと、HTMLから見つかった公開GTMコンテナを読む。

    GTM API 権限が無い案件でも、次の客観的な証拠を計測チェックに
    残すための読み取り専用スキャン。

    - HTMLに直接出ている GTM / GA4 / UA / Google Ads のID
    - 公開中の gtm.js に含まれるタグ種別とGA4送信先

    公開ページの応答と公開コンテナを読むだけで、サイトやGTMへの
    書き込みは行わない。コンテナ単位の取得失敗は全体を落とさず、
    ``container_errors`` に残す。
    """
    html = http_get(url)
    found = discover_ids(html)
    containers: list[dict] = []
    container_errors: list[dict[str, str]] = []
    tags: list[dict] = []

    for container_id in found["gtm_containers"]:
        try:
            normalized = normalize(parse_resource(fetch_container(container_id)), container_id, url)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            container_errors.append({"container_id": container_id, "error": type(exc).__name__})
            continue
        containers.append(normalized)
        for tag in normalized.get("tags") or []:
            copied = dict(tag)
            copied["container_id"] = container_id
            tags.append(copied)

    return {
        "source": {"method": "public_site_scan", "url": url},
        **found,
        "counts": {"tags": len(tags), "containers": len(containers)},
        "containers": containers,
        "container_errors": container_errors,
        "tags": tags,
    }


def fetch_container(container_id: str) -> str:
    if not re.fullmatch(r"GTM-[A-Z0-9]{6,}", container_id):
        raise ValueError(f"GTM コンテナIDの形式ではありません: {container_id}")
    return http_get(GTM_JS.format(container_id=container_id))


# ──────────────────────────────────────
# パース
# ──────────────────────────────────────

def _extract_balanced(text: str, start: int) -> str:
    """text[start] の '{' に対応する '}' までを、文字列リテラルを考慮して切り出す。"""
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise ValueError("gtm.js の resource が閉じていません（形式が想定外）")


def parse_resource(gtm_js: str) -> dict:
    """gtm.js 本文から resource（macros / tags / predicates / rules）を取り出す。"""
    match = re.search(r'"resource"\s*:\s*\{', gtm_js)
    if not match:
        raise ValueError(
            "resource が見つかりません。コンテナIDが誤っているか、"
            "gtm.js の形式が変わった可能性があります。"
        )
    brace = gtm_js.index("{", match.end() - 1)
    return json.loads(_extract_balanced(gtm_js, brace))


# ──────────────────────────────────────
# 参照解決
# ──────────────────────────────────────

class Resolver:
    """macro / predicate 参照を人間が読める文字列に解決する。"""

    def __init__(self, resource: dict):
        self.macros = resource.get("macros", [])
        self.predicates = resource.get("predicates", [])

    def macro(self, index: int, depth: int = 0) -> str:
        if index >= len(self.macros):
            return f"macro[{index}]"
        if depth > 4:  # ルックアップの入れ子を辿りすぎない
            return f"macro[{index}]"
        m = self.macros[index]
        fn = m.get("function", "?")
        if fn == "__e":
            return "Event"
        if fn == "__v":
            return f"DLV:{m.get('vtp_name', '')}"
        if fn == "__u":
            return f"URL:{m.get('vtp_component', 'URL')}"
        if fn == "__c":
            return self.value(m.get("vtp_value"), depth + 1)
        if fn == "__k":
            return f"Cookie:{m.get('vtp_name', '')}"
        if fn == "__aev":
            return f"自動イベント変数:{m.get('vtp_varType', '')}"
        if fn == "__d":
            return f"DOM:{m.get('vtp_elementId') or m.get('vtp_selectorType', '')}"
        if fn == "__jsm":
            return "カスタムJS"
        if fn in ("__smm", "__remm"):
            return self.lookup(m, depth + 1)
        return MACRO_FUNCTIONS.get(fn, fn)

    def lookup(self, m: dict, depth: int) -> str:
        """ルックアップテーブルを「入力 ? key→value / 既定値」形式に展開する。"""
        entries = []
        raw = m.get("vtp_map", [])
        if isinstance(raw, list) and raw and raw[0] == "list":
            for item in raw[1:]:
                if isinstance(item, list) and item and item[0] == "map":
                    kv = dict(zip(item[1::2], item[2::2]))
                    entries.append(
                        f"{self.value(kv.get('key'), depth)}→{self.value(kv.get('value'), depth)}"
                    )
        default = (
            self.value(m.get("vtp_defaultValue"), depth)
            if m.get("vtp_setDefaultValue")
            else "なし"
        )
        src = self.value(m.get("vtp_input"), depth)
        return f"ルックアップ({src}: {', '.join(entries)} / 既定={default})"

    def value(self, v, depth: int = 0) -> str:
        """['macro', n] / ['template', ...] / リテラルを文字列にする。"""
        if isinstance(v, list) and v:
            if v[0] == "macro" and len(v) >= 2:
                return self.macro(v[1], depth)
            if v[0] == "template":
                return "".join(self.value(part, depth + 1) for part in v[1:])
            return json.dumps(v, ensure_ascii=False)[:120]
        return "" if v is None else str(v)

    def predicate(self, index: int) -> str:
        if index >= len(self.predicates):
            return f"predicate[{index}]"
        p = self.predicates[index]
        op = PREDICATE_OPS.get(p.get("function", "?"), p.get("function", "?"))
        return f"{self.value(p.get('arg0'))} {op} {self.value(p.get('arg1'))}"

    def datalayer_events_of(self, index: int) -> list[str]:
        """述語が Event を対象にしていれば、対応する dataLayer イベント名を**列**で返す。

        `^(login|sign_up)$` のような列挙は**1件ずつに展開する**。
        `"login|sign_up"` のような合成名を1つ返すと、
        個別の `login` タグと関連づけられず**実在する多重発火を見落とす**うえ、
        レポートに存在しないイベント名が出る。
        """
        p = self.predicates[index] if index < len(self.predicates) else None
        if not p or p.get("arg0") != ["macro", 0]:
            return []
        fn = p.get("function", "")
        arg1 = p.get("arg1")
        if fn == "_eq":
            return [arg1] if isinstance(arg1, str) and arg1 else []
        # 否定形（`gtm.` を含まない等）は絞り込みであって対象の指定ではないので数えない
        if fn in ("_neq", "_nc", "_nr"):
            return []
        if fn in ("_re", "_cn", "_sw", "_ew", "_css"):
            label = self._broad_or_literals(fn, arg1)
            if not label:
                return []
            # リテラル列挙は `|` で連結して返ってくるので、ここで1件ずつに割る
            if label != ANY_DATALAYER_EVENT and not label.startswith("(条件:"):
                return [x for x in label.split("|") if x]
            return [label]
        return []

    def datalayer_event(self, index: int) -> str | None:
        """後方互換。1件目だけ返す（新しい呼び出しは `datalayer_events_of` を使う）。"""
        got = self.datalayer_events_of(index)
        return got[0] if got else None

    @staticmethod
    def _broad_or_literals(fn: str, pattern) -> str | None:
        """完全一致以外のトリガーを、扱える形に落とす。

        **すべてを「全イベント」にしてはいけない。** `^(login|sign_up)$` のように
        限られた集合を指す正規表現まで全イベント扱いにすると、
        「全イベントに掛かるタグ」として Critical の誤検知になる。

        - `.+` `.*` のような何にでも当たるものだけ全イベント扱いにする
        - リテラルの列挙（`^(a|b)$`）は、その名前を返す（`|` 区切りで連結）
        - それ以外は条件式をそのまま名前にして、独立した枠として数える
        """
        if not isinstance(pattern, str):
            return None
        pat = pattern.strip()
        broad = {".+", ".*", ".", "^.*$", "^.+$", "^.*", "^.+", ".*$", ".+$", ""}
        if pat in broad:
            return ANY_DATALAYER_EVENT
        if fn == "_re":
            # `^(a|b|c)$` / `(a|b)` / `^a$` のようにイベント名を列挙しているものだけ
            # 名前として扱う。`^checkout_` のような前方一致は列挙ではないので、
            # 名前に見せると実在しないイベント名を作ってしまう。
            m = re.fullmatch(r"\^?\(?([A-Za-z0-9_.\-|]+)\)?\$?", pat)
            if m:
                anchored_both = pat.startswith("^") and pat.endswith("$")
                grouped = "(" in pat and ")" in pat
                parts = [x for x in m.group(1).split("|") if x]
                if parts and (anchored_both or grouped):
                    return "|".join(parts)
        # 判断できない条件は、それ自体を1つの枠として持つ（全イベント扱いにはしない）
        return f"(条件: Event {PREDICATE_OPS.get(fn, fn)} {pat})"


# ──────────────────────────────────────
# 正規化
# ──────────────────────────────────────

def normalize(resource: dict, container_id: str, source_url: str = "") -> dict:
    r = Resolver(resource)
    tags = resource.get("tags", [])
    rules = resource.get("rules", [])

    fire: dict[int, list[str]] = defaultdict(list)
    block: dict[int, list[str]] = defaultdict(list)
    events: dict[int, list[str]] = defaultdict(list)

    for rule in rules:
        conditions, added, blocked, ev_names = [], [], [], []
        for clause in rule:
            head = clause[0]
            if head == "if":
                for i in clause[1:]:
                    conditions.append(r.predicate(i))
                    ev_names += r.datalayer_events_of(i)
            elif head == "unless":
                conditions += [f"NOT({r.predicate(i)})" for i in clause[1:]]
            elif head == "add":
                added += clause[1:]
            elif head in ("block", "blockOnce"):
                blocked += clause[1:]
        cond_text = " かつ ".join(conditions) if conditions else "(条件なし)"
        for ti in added:
            fire[ti].append(cond_text)
            events[ti] += ev_names
        for ti in blocked:
            block[ti].append(cond_text)

    normalized = []
    for i, t in enumerate(tags):
        fn = t.get("function", "?")
        if "vtp_measurementIdOverride" in t:
            dest = r.value(t["vtp_measurementIdOverride"])
        elif "vtp_tagId" in t:
            dest = r.value(t["vtp_tagId"])
        elif "vtp_conversionId" in t:
            dest = f"AW-{r.value(t['vtp_conversionId'])}"
        else:
            dest = ""
        normalized.append(
            {
                "index": i,
                "function": fn,
                "type_label": TAG_FUNCTIONS.get(fn, fn),
                "event_name": r.value(t["vtp_eventName"]) if "vtp_eventName" in t else "",
                "destination": dest,
                "datalayer_events": sorted(set(events.get(i, []))),
                "fire_on": fire.get(i, []),
                "blocked_by": block.get(i, []),
                "once_per_event": bool(t.get("once_per_event")),
                "once_per_load": bool(t.get("once_per_load")),
                "parameters": _parameters(r, t),
            }
        )

    return {
        "source": {
            "method": "public_gtm_js",
            "container_id": container_id,
            "url": GTM_JS.format(container_id=container_id),
            "found_on": source_url,
        },
        "version": resource.get("version", ""),
        "counts": {
            "tags": len(tags),
            "macros": len(resource.get("macros", [])),
            "predicates": len(resource.get("predicates", [])),
            "rules": len(rules),
        },
        "tags": normalized,
    }


def _parameters(r: Resolver, tag: dict) -> dict[str, str]:
    """イベント設定テーブル（送信パラメータ）を {名前: 値} に展開する。"""
    params: dict[str, str] = {}
    for key in ("vtp_eventSettingsTable", "vtp_configSettingsTable", "vtp_userProperties"):
        raw = tag.get(key)
        if not (isinstance(raw, list) and raw and raw[0] == "list"):
            continue
        for item in raw[1:]:
            if isinstance(item, list) and item and item[0] == "map":
                kv = dict(zip(item[1::2], item[2::2]))
                name = kv.get("parameter") or kv.get("name")
                val = kv.get("parameterValue") or kv.get("value")
                if name is not None:
                    params[r.value(name)] = r.value(val)
    return params


# ──────────────────────────────────────
# レポート
# ──────────────────────────────────────

def find_duplicate_fires(data: dict) -> dict[str, list[dict]]:
    """同一 dataLayer イベントで複数の計測タグが発火する組み合わせを洗い出す。"""
    by_event: dict[str, list[dict]] = defaultdict(list)
    for t in data["tags"]:
        if t["function"] not in ("__gaawe", "__googtag"):
            continue
        for ev in t["datalayer_events"]:
            by_event[ev].append(t)
    return {ev: ts for ev, ts in by_event.items() if len(ts) > 1}


def datalayer_events(data: dict) -> dict[str, list[dict]]:
    """GTM が待ち受けている dataLayer イベント名 → 発火するタグ一覧。

    「アプリが何を push しているか」はコンテナのトリガー条件から逆算するしかない
    （GTM の権限が無いと発火条件の一覧も見られないため）。
    """
    by_event: dict[str, list[dict]] = defaultdict(list)
    for t in data["tags"]:
        # `fire_on` の表示文字列を再解析すると、完全一致（`Event = xxx`）以外の
        # トリガーを取りこぼす。正規化時に解決済みの `datalayer_events` を使う。
        for name in t.get("datalayer_events", []):
            by_event[name].append(t)
    return dict(sorted(by_event.items()))


def build_report(data: dict) -> str:
    counts = data["counts"]
    lines = [
        f"# GTM コンテナ構成（{data['source']['container_id']} / 公開 gtm.js より復元）",
        "",
        f"- 取得元: {data['source']['url']}",
        f"- コンテナ バージョン: {data['version']}",
        f"- タグ {counts['tags']} / 変数 {counts['macros']} / 条件 {counts['predicates']} / ルール {counts['rules']}",
        "",
        "> gtm.js にはタグ名・トリガー名が含まれないため、本レポートは名前ではなく",
        "> 「イベント名・発火条件・送信先」で構成を示す。一時停止タグは内容を取得できない。",
        "",
        "## タグ種別の内訳",
        "",
        "| 種別 | 件数 |",
        "|---|---|",
    ]
    kinds: dict[str, int] = defaultdict(int)
    for t in data["tags"]:
        kinds[t["type_label"]] += 1
    for label, n in sorted(kinds.items(), key=lambda x: -x[1]):
        lines.append(f"| {label} | {n} |")

    lines += ["", "## 同一イベントで複数タグが発火する箇所（多重計上の候補）", ""]
    dupes = find_duplicate_fires(data)
    if not dupes:
        lines.append("該当なし。")
    else:
        lines += ["| dataLayer イベント | 発火する計測タグ |", "|---|---|"]
        for ev, ts in sorted(dupes.items(), key=lambda x: -len(x[1])):
            names = " / ".join(f"`{t['event_name'] or t['type_label']}`(#{t['index']})" for t in ts)
            lines.append(f"| `{ev}` | {len(ts)}本: {names} |")

    events = datalayer_events(data)
    internal = [k for k in events if k.startswith("gtm.")]
    custom = [k for k in events if not k.startswith("gtm.")]
    lines += [
        "", "## GTM が待ち受けている dataLayer イベント", "",
        f"全 {len(events)} 種（アプリ由来 {len(custom)} / GTM内部 {len(internal)}）。",
        "コンテナのトリガー条件から逆算したもので、**アプリが実際に push しているイベントの一覧に相当する**。",
        "", "| dataLayer イベント | タグ数 | GA4 に送られる名前 | その他のタグ |", "|---|---|---|---|",
    ]
    for name in custom:
        if name == ANY_DATALAYER_EVENT:
            continue  # 個別イベントではないので下で別扱いにする
        tags = events[name]
        ga4 = list(dict.fromkeys(
            t["event_name"] for t in tags
            if t["function"] in ("__gaawe", "__googtag") and t["event_name"]))
        other = list(dict.fromkeys(
            t["type_label"] for t in tags if t["function"] not in ("__gaawe", "__googtag")))
        lines.append(
            f"| `{name}` | {len(tags)} | {', '.join(f'`{g}`' for g in ga4) or '—'} "
            f"| {', '.join(other) or '—'} |"
        )
    if ANY_DATALAYER_EVENT in events:
        tags = events[ANY_DATALAYER_EVENT]
        names = " / ".join(
            f"`{t.get('event_name') or t.get('type_label')}`(#{t['index']})" for t in tags)
        lines += [
            "",
            f"**あらゆるカスタムイベントに掛かるタグが {len(tags)} 本ある**: {names}",
            "",
            "> 完全一致ではなく正規表現・部分一致で `Event` を見ているタグ。"
            "上の一覧に出てくる個別のイベントすべてに重ねて発火するため、"
            "**送信先が GA4 なら全イベントが二重計上される**。発火条件と送信先を最初に確認する。",
        ]
    if internal:
        lines += ["", f"GTM内部イベント: {', '.join(f'`{k}`' for k in internal)}"]

    lines += ["", "## 計測タグ一覧", "", "| # | 種別 | イベント名 | 送信先 | 発火条件 |", "|---|---|---|---|---|"]
    for t in data["tags"]:
        if t["function"] not in ("__gaawe", "__googtag", "__awct", "__baut", "__ua"):
            continue
        cond = " または ".join(t["fire_on"]) or "(トリガーなし)"
        cond = cond.replace("|", "\\|")
        lines.append(
            f"| {t['index']} | {t['type_label']} | `{t['event_name']}` | {t['destination']} | {cond} |"
        )
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────
# CLI
# ──────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_discover = sub.add_parser("discover", help="サイトHTMLから GTM/GA4/広告の各IDを検出")
    p_discover.add_argument("--url", required=True)
    p_discover.add_argument("--out", default="", help="検出結果と公開GTMの解析結果をJSON保存")

    p_dump = sub.add_parser("dump", help="公開 gtm.js を取得して正規化 JSON に落とす")
    p_dump.add_argument("--container", required=True, help="GTM-XXXXXXX")
    p_dump.add_argument("--out", required=True)
    p_dump.add_argument("--found-on", default="", help="検出元ページURL（記録用）")
    p_dump.add_argument("--raw-out", default="", help="gtm.js の原本も保存する場合のパス")

    p_report = sub.add_parser("report", help="正規化 JSON から Markdown レポートを生成")
    p_report.add_argument("--in", dest="infile", required=True)
    p_report.add_argument("--out", required=True)

    args = parser.parse_args(argv)

    if args.command == "discover":
        data = inspect_site(args.url)
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(
                f"GA4 ID {len(data['ga4_measurement_ids'])}件 / "
                f"UA ID {len(data['universal_analytics_ids'])}件 / "
                f"GTM {len(data['gtm_containers'])}件 / "
                f"公開タグ {len(data['tags'])}本 → {out}"
            )
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        if not data["gtm_containers"]:
            print("\nGTM コンテナが見つかりません。JS 描画後にのみ挿入される可能性があります。",
                  file=sys.stderr)
        return 0

    if args.command == "dump":
        gtm_js = fetch_container(args.container)
        if args.raw_out:
            Path(args.raw_out).write_text(gtm_js, encoding="utf-8")
        data = normalize(parse_resource(gtm_js), args.container, args.found_on)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        c = data["counts"]
        print(f"{args.container} v{data['version']}: タグ {c['tags']} / 変数 {c['macros']} "
              f"/ 条件 {c['predicates']} / ルール {c['rules']} → {out}")
        return 0

    if args.command == "report":
        data = json.loads(Path(args.infile).read_text(encoding="utf-8"))
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(build_report(data), encoding="utf-8")
        print(f"レポートを書き出しました → {out}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
