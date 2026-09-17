"""kpis.yaml の kpis[].priority（複数CVがあるとき、どれを主に見るか）のテスト.

観点:
  - KPIが1件だけなら優先度が未設定でも `primary_kpi` がそのKPIを返す（聞く意味が無いため）
  - 複数KPIで優先度が全く未設定（既存クライアントが多い想定）でも `validate()` は止まらず、
    `primary_kpi` は `None`（「未設定」と分かる形）を返す
  - `priority: 1` が一意に決まれば `primary_kpi` がそれを返す
  - 一部だけ設定・値が重複している中途半端な状態は `validate_kpi_priorities` が警告する
  - `writeback.save_kpi_priorities` で既存KPIの他フィールドを壊さずに優先度だけ設定できる
"""
from pathlib import Path

import yaml

from context_store.loader import load_context
from context_store.schema import validate_kpi_priorities
from context_store.writeback import save_kpi_priorities


def _write_kpis(tmp_path: Path, client_id: str, kpis: list, key_events: list | None = None) -> Path:
    client_dir = tmp_path / client_id
    client_dir.mkdir(parents=True)
    (client_dir / "profile.yaml").write_text(
        yaml.safe_dump({"client": {"client_id": client_id, "name": "テスト社"}}, allow_unicode=True),
        encoding="utf-8",
    )
    data = {"kpis": kpis}
    if key_events is not None:
        data["key_events"] = key_events
    (client_dir / "kpis.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return tmp_path


# ---- ClientContext.primary_kpi ---------------------------------------------

def test_primary_kpi_single_kpi_returned_without_priority(tmp_path):
    base = _write_kpis(tmp_path, "c1", [{"kpi_id": "kpi_001", "name": "資料DL"}])
    ctx = load_context("c1", context_dir=base)

    assert ctx.primary_kpi is not None
    assert ctx.primary_kpi["kpi_id"] == "kpi_001"


def test_primary_kpi_none_when_multiple_kpis_unset(tmp_path):
    base = _write_kpis(
        tmp_path,
        "c2",
        [
            {"kpi_id": "kpi_001", "name": "資料DL"},
            {"kpi_id": "kpi_002", "name": "問い合わせ"},
        ],
    )
    ctx = load_context("c2", context_dir=base)

    assert ctx.primary_kpi is None  # 未設定は None。適当に先頭を代用しない
    assert ctx.validate() == []  # 未設定は既存クライアントに多いので止めない（警告も出さない）


def test_primary_kpi_resolves_from_priority_one(tmp_path):
    base = _write_kpis(
        tmp_path,
        "c3",
        [
            {"kpi_id": "kpi_001", "name": "資料DL", "priority": 2},
            {"kpi_id": "kpi_002", "name": "問い合わせ", "priority": 1},
        ],
    )
    ctx = load_context("c3", context_dir=base)

    assert ctx.primary_kpi["kpi_id"] == "kpi_002"


def test_primary_kpi_none_when_priority_one_duplicated(tmp_path):
    base = _write_kpis(
        tmp_path,
        "c4",
        [
            {"kpi_id": "kpi_001", "name": "資料DL", "priority": 1},
            {"kpi_id": "kpi_002", "name": "問い合わせ", "priority": 1},
        ],
    )
    ctx = load_context("c4", context_dir=base)

    assert ctx.primary_kpi is None  # 一意に決まらないので安全側に倒す


# ---- schema.validate_kpi_priorities ----------------------------------------

def test_validate_kpi_priorities_partial_setting_warns():
    kpis = [
        {"kpi_id": "kpi_001", "priority": 1},
        {"kpi_id": "kpi_002"},  # 未設定
    ]
    warnings = validate_kpi_priorities(kpis)
    assert any("一部のKPIにだけ" in w for w in warnings)


def test_validate_kpi_priorities_duplicate_values_warns():
    kpis = [
        {"kpi_id": "kpi_001", "priority": 1},
        {"kpi_id": "kpi_002", "priority": 1},
    ]
    warnings = validate_kpi_priorities(kpis)
    assert any("重複" in w for w in warnings)


def test_validate_kpi_priorities_single_kpi_never_warns():
    assert validate_kpi_priorities([{"kpi_id": "kpi_001"}]) == []
    assert validate_kpi_priorities([{"kpi_id": "kpi_001", "priority": 5}]) == []


def test_validate_kpi_priorities_all_unset_no_warning():
    kpis = [{"kpi_id": "kpi_001"}, {"kpi_id": "kpi_002"}]
    assert validate_kpi_priorities(kpis) == []


def test_validate_kpi_priorities_non_integer_warns():
    kpis = [
        {"kpi_id": "kpi_001", "priority": "高"},
        {"kpi_id": "kpi_002", "priority": 1},
    ]
    warnings = validate_kpi_priorities(kpis)
    assert any("整数ではありません" in w for w in warnings)


# ---- writeback.save_kpi_priorities -----------------------------------------

def test_save_kpi_priorities_sets_priority_without_touching_other_fields(tmp_path):
    base = _write_kpis(
        tmp_path,
        "c5",
        [
            {"kpi_id": "kpi_001", "name": "資料DL", "target_value": {"goal": 200}},
            {"kpi_id": "kpi_002", "name": "問い合わせ", "target_value": {"goal": 50}},
        ],
    )

    save_kpi_priorities("c5", priorities={"kpi_002": 1, "kpi_001": 2}, context_dir=base)

    ctx = load_context("c5", context_dir=base)
    kpis = {k["kpi_id"]: k for k in ctx.kpis["kpis"]}
    assert kpis["kpi_001"]["priority"] == 2
    assert kpis["kpi_001"]["name"] == "資料DL"  # 既存フィールドは維持
    assert kpis["kpi_002"]["priority"] == 1
    assert ctx.primary_kpi["kpi_id"] == "kpi_002"
