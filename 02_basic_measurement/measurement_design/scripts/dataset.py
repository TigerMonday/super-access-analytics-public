"""`_data/` を検証観点ごとのデータセットとして読み書きする。

旧構成は取得の都合（API 呼び出しのまとまり）で `phase1/2/3.json` に分かれていたが、
**調査の単位と一致しないため手を入れにくい**。「イベントだけ取り直す」「GTM だけ
差し替える」ができるよう、`docs/design-doc-*/` と同じ観点番号でファイルを分ける。

    01-property.json           プロパティ・データストリーム・拡張計測・保持・アトリビューション
    02-events.json             イベント発火実績・キーイベントの登録と発火
    03-custom-definitions.json カスタムディメンション/指標・イベント作成ルール・オーディエンス
    05-traffic.json            チャネル別・source/medium 別・campaign 別
    06-pages.json              ページ別
    07-data-quality.json       ホスト名別・国別
    09-gtm.json                GTM コンテナ

旧 `phase1/2/3.json` しかない案件でも読めるよう、フォールバックを持つ。
"""

from __future__ import annotations

import json
from pathlib import Path

# データセット名 → ファイル名
DATASETS: dict[str, str] = {
    "property": "01-property.json",
    "events": "02-events.json",
    "custom_definitions": "03-custom-definitions.json",
    "traffic": "05-traffic.json",
    "pages": "06-pages.json",
    "data_quality": "07-data-quality.json",
    "gtm": "09-gtm.json",
}

# 旧 phase ファイルのどのキーを、どのデータセットへ割り当てるか。
# `prefix:` で始まる指定は前方一致（enhanced_measurement_<streamId> 等）。
LEGACY_KEY_MAP: dict[str, dict[str, list[str]]] = {
    "phase1.json": {
        "property": [
            "property", "data_streams", "data_retention", "google_signals",
            "user_provided_data", "reporting_identity", "attribution", "ads_links",
            "bigquery_links", "prefix:enhanced_measurement_",
        ],
        "events": ["key_events"],
        "custom_definitions": [
            "custom_dimensions", "custom_metrics", "audiences", "prefix:event_create_rules_",
        ],
    },
    "phase2.json": {
        "events": [
            "events_30d", "event_name_counts_30d", "event_name_counts_status",
            "key_event_firing", "totals", "event_name_total",
        ],
        "traffic": ["channel_performance"],
        "custom_definitions": ["dimension_values"],
    },
    "phase3.json": {
        "gtm": ["*"],
    },
    # 観点別に新設した取得単位（旧 phase には対応しない）
    "pages.json": {
        "pages": ["pages", "content_groups"],
    },
    "data-quality.json": {
        "data_quality": ["hosts", "countries", "country_environment"],
    },
    "traffic.json": {
        # phase2 が入れた channel_performance は残る（split_and_save が既存とマージする）
        "traffic": ["source_medium", "campaigns"],
    },
}


def path_for(data_dir: Path, name: str) -> Path:
    if name not in DATASETS:
        raise KeyError(f"未知のデータセット: {name}（有効: {', '.join(DATASETS)}）")
    return data_dir / DATASETS[name]


def save(data_dir: Path, name: str, data: dict) -> Path:
    out = path_for(data_dir, name)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return out


def _read_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _collect_legacy(data_dir: Path, name: str) -> dict:
    """旧 phase*.json から該当データセット分のキーを集める。"""
    out: dict = {}
    for legacy_file, mapping in LEGACY_KEY_MAP.items():
        keys = mapping.get(name)
        if not keys:
            continue
        path = data_dir / legacy_file
        if not path.exists():
            continue
        src = _read_json(path)
        if keys == ["*"]:
            out.update(src)
            continue
        for key in keys:
            if key.startswith("prefix:"):
                pref = key[len("prefix:"):]
                out.update({k: v for k, v in src.items() if k.startswith(pref)})
            elif key in src:
                out[key] = src[key]
    return out


def load(data_dir: Path, name: str, *, required: bool = False) -> dict:
    """データセットを読む。無ければ旧 phase*.json から組み立てる。

    どちらも無い場合、`required=True` なら FileNotFoundError、そうでなければ空 dict。
    """
    path = path_for(data_dir, name)
    if path.exists():
        return _read_json(path)

    legacy = _collect_legacy(data_dir, name)
    if legacy:
        return legacy

    if required:
        raise FileNotFoundError(
            f"{DATASETS[name]} が見つかりません: {path}\n"
            "先に `fetch` を実行してください。"
        )
    return {}


def exists(data_dir: Path, name: str) -> bool:
    return bool(load(data_dir, name))


def migrate(data_dir: Path, *, remove_legacy: bool = False) -> list[Path]:
    """旧 phase*.json を観点別ファイルへ分割して書き出す。

    "traffic" 等は新設フェーズ (`split_and_save` 経由) と旧 phase*.json の両方から
    供給されうる。ここを単純な上書き保存にすると、新設フェーズが先に書いた
    observation ファイル（例: 05-traffic.json の source_medium/campaigns）が、
    旧 phase2.json 由来の channel_performance だけの内容で丸ごと消える
    （実際に流入詳細が消えたバグ）。既存ファイルを優先しつつ legacy 由来の
    キーで補うマージにする。
    """
    written: list[Path] = []
    for name in DATASETS:
        legacy_data = _collect_legacy(data_dir, name)
        if not legacy_data:
            continue
        path = path_for(data_dir, name)
        existing = _read_json(path) if path.exists() else {}
        merged = {**legacy_data, **existing}  # 既存（新設フェーズ由来）を優先
        written.append(save(data_dir, name, merged))
    if remove_legacy and written:
        for legacy_file in LEGACY_KEY_MAP:
            p = data_dir / legacy_file
            if p.exists():
                p.unlink()
    return written


def split_and_save(data_dir: Path, legacy_name: str, data: dict) -> list[Path]:
    """取得直後の dict を、旧 phase 名のキー割り当てに従って観点別に保存する。

    `LEGACY_KEY_MAP` を「取得のまとまり → 観点」の対応表として再利用する。
    どの観点にも割り当てられなかったキーは取りこぼさずに `_unmapped` へ入れる。
    """
    # **保存前に個人情報を伏せる。** `_data/` はコミットする前提なので、
    # 取得した実データに end user のメールアドレス等が載っていると、そのまま
    # リポジトリに入る（実際に GA4 の pagePath に入っていた案件がある）。
    # 取得系スクリプトを個別に直すのではなく、書き出しの一箇所で通す。
    import pii
    data, redacted = pii.redact_obj(data)
    if redacted:
        print(f"  個人情報らしい値を {redacted} 件伏せました（{pii.MASK}）")

    mapping = LEGACY_KEY_MAP.get(legacy_name, {})
    written: list[Path] = []
    assigned: set[str] = set()

    for name, keys in mapping.items():
        if keys == ["*"]:
            chunk = dict(data)
            assigned |= set(data)
        else:
            chunk = {}
            for key in keys:
                if key.startswith("prefix:"):
                    pref = key[len("prefix:"):]
                    hit = {k: v for k, v in data.items() if k.startswith(pref)}
                    chunk.update(hit); assigned |= set(hit)
                elif key in data:
                    chunk[key] = data[key]; assigned.add(key)
        if not chunk:
            continue
        # 既存ファイルがあればマージする（02-events は property 側と data 側の両方から書かれる）
        merged = {**load(data_dir, name), **chunk}
        written.append(save(data_dir, name, merged))

    leftover = {k: v for k, v in data.items() if k not in assigned}
    if leftover:
        out = data_dir / "_unmapped.json"
        existing = _read_json(out) if out.exists() else {}
        with open(out, "w", encoding="utf-8") as f:
            json.dump({**existing, **leftover}, f, indent=2, ensure_ascii=False)
        written.append(out)
    return written
