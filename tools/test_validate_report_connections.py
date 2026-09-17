import copy
from validate_report_connections import digest, validate


def fixture(root):
    files = {}
    for role in ("market", "basic", "plan", "context"):
        path = root / (role + ".md")
        path.write_text(role, encoding="utf-8")
        files[role] = dict(path=path.name, sha256=digest(path))
    return dict(files=files, metrics={r:dict(start="2026-01-01",end="2026-02-01",numerator="CV",denominator="session") for r in ("basic","plan")}, mappings=[dict(market="market",basic="basic",plan="plan")],review_note="単位を確認")


def test_valid(tmp_path):
    assert validate(tmp_path, fixture(tmp_path)) == []


def test_same_day_edit(tmp_path):
    m=fixture(tmp_path)
    (tmp_path/"market.md").write_text("changed", encoding="utf-8")
    assert any("変更" in e for e in validate(tmp_path,m))


def test_missing_file(tmp_path):
    m=fixture(tmp_path)
    m["files"]["basic"]["path"]="missing.md"
    assert any("不在" in e for e in validate(tmp_path,m))


def test_missing_mapping(tmp_path):
    m=fixture(tmp_path)
    m["mappings"][0]["plan"]="invented"
    assert any("対応箇所" in e for e in validate(tmp_path,m))


def test_missing_metric(tmp_path):
    m=fixture(tmp_path)
    del m["metrics"]["plan"]["numerator"]
    assert any("記録不足" in e for e in validate(tmp_path,m))


def test_missing_context(tmp_path):
    m=fixture(tmp_path)
    del m["files"]["context"]
    assert validate(tmp_path,m)
