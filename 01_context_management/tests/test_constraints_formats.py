"""constraints.yaml の形式ズレで注意事項が無言のまま消えないことのテスト.

対象（ドライラン2026-07-14 指摘①）:
  - gotchas: 正典の `title`/`detail` 形式と、実運用で出た `id`/`note` 形式の両方を受容する
  - open_questions: 文字列のリストで書かれても丸ごと消えない
  - 想定外の形式（キー不一致の dict 等）も文字列化して表示に回す
  - validate(): constraints.yaml に中身があるのに1件も読めない場合は警告を出す
"""
from pathlib import Path

import yaml

from context_store.loader import ClientContext, load_context
from context_store.schema import normalize_gotchas, normalize_open_questions


def _write_constraints(tmp_path: Path, client_id: str, data: dict) -> Path:
    client_dir = tmp_path / client_id
    client_dir.mkdir(parents=True)
    (client_dir / "profile.yaml").write_text(
        yaml.safe_dump({"client": {"client_id": client_id, "name": "テスト社"}}, allow_unicode=True),
        encoding="utf-8",
    )
    (client_dir / "constraints.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return tmp_path


# ---- ケース1: 正典形式（title/detail） --------------------------------------

def test_canonical_title_detail_format(tmp_path):
    base = _write_constraints(tmp_path, "c1", {
        "gotchas": [{"id": "gotcha_001", "title": "CVR分母はB2B入口に絞る", "detail": "全体分母だと誤結論"}],
        "open_questions": [{"id": "q_001", "question": "リード化率が低い要因は？", "status": "open"}],
    })
    md = load_context("c1", context_dir=base).summary_markdown()

    assert "CVR分母はB2B入口に絞る: 全体分母だと誤結論" in md
    assert "リード化率が低い要因は？ (status: open)" in md


# ---- ケース2: id/note 形式（形式ズレ。従来は「None:」や空欄になった） -----------

def test_id_note_format_not_silently_dropped(tmp_path):
    base = _write_constraints(tmp_path, "c2", {
        "gotchas": [{"id": "gotcha_001", "note": "計測タグはGTM経由のみ。直書きタグは残骸"}],
    })
    md = load_context("c2", context_dir=base).summary_markdown()

    assert "None" not in md
    assert "計測タグはGTM経由のみ。直書きタグは残骸" in md
    # title が無い場合は id を見出しに使う
    assert "gotcha_001" in md


def test_note_without_id_uses_first_line_as_title():
    rows = normalize_gotchas({"gotchas": [{"note": "1行目が見出し\n2行目は詳細"}]})
    assert rows[0]["title"] == "1行目が見出し"
    assert "2行目は詳細" in rows[0]["detail"]


# ---- ケース3: 文字列リスト（従来は dict 前提フィルタで丸ごと消えた） -------------

def test_string_list_not_silently_dropped(tmp_path):
    base = _write_constraints(tmp_path, "c3", {
        "gotchas": ["toC/toB混在サイト。分母に注意"],
        "open_questions": ["資料DL後のリード化率が低い要因は？"],
    })
    md = load_context("c3", context_dir=base).summary_markdown()

    assert "toC/toB混在サイト。分母に注意" in md
    assert "資料DL後のリード化率が低い要因は？" in md


# ---- ケース4: 想定外の形式（それでも消えず文字列化して表示） ---------------------

def test_unexpected_format_stringified_not_dropped(tmp_path):
    base = _write_constraints(tmp_path, "c4", {
        "gotchas": [{"memo": "想定外キーのみのdict"}, 12345],
        "open_questions": [{"hypothesis": "questionキー無し"}],
    })
    ctx = load_context("c4", context_dir=base)
    md = ctx.summary_markdown()

    assert "想定外キーのみのdict" in md
    assert "12345" in md
    assert "questionキー無し" in md


# ---- validate(): 1件も読めない場合の警告 -------------------------------------

def test_validate_warns_when_constraints_present_but_unreadable():
    ctx = ClientContext(
        client_id="c5",
        profile={"client": {"name": "テスト社"}},
        # 中身はあるが gotchas / open_questions が読める形式で1件も無い
        constraints={"gotchas": [], "open_questions": None, "naming_conventions": {"utm_source": "小文字"}},
    )
    warnings = ctx.validate()
    assert any("constraints.yaml" in w and "読み取れませんでした" in w for w in warnings)


def test_validate_no_warning_when_gotchas_readable():
    ctx = ClientContext(
        client_id="c6",
        profile={"client": {"name": "テスト社"}},
        constraints={"gotchas": [{"id": "g1", "note": "id/note形式でも読める"}]},
    )
    warnings = ctx.validate()
    assert not any("constraints.yaml" in w for w in warnings)


def test_validate_no_warning_when_constraints_absent():
    """constraints.yaml 自体が無い（空dict）場合は警告しない（運用初期の未記入を許容）."""
    ctx = ClientContext(client_id="c7", profile={"client": {"name": "テスト社"}})
    warnings = ctx.validate()
    assert not any("constraints.yaml" in w for w in warnings)


# ---- resolved の除外は維持 ----------------------------------------------------

def test_resolved_open_questions_still_excluded():
    rows = normalize_open_questions({
        "open_questions": [
            {"question": "解決済みの課題", "status": "resolved"},
            {"question": "未解決の課題", "status": "open"},
        ]
    })
    open_rows = [r for r in rows if r["status"] != "resolved"]
    assert [r["question"] for r in open_rows] == ["未解決の課題"]
