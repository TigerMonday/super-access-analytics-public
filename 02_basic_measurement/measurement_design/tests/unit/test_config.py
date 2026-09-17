"""config.py のユニットテスト.

成果物ルートがリポジトリルート `outputs/{client_id}/02_measurement/` になること
（docs/standard-run-order.md §4）と、client_id のパストラバーサル対策を検証する。
"""
import pytest

import config as config_module
from config import AuditConfig, resolve_client_paths, validate_client_id


@pytest.mark.parametrize(
    "client_id",
    ["sample-client", "sample_client", "SampleClient123", "a", "another-client"],
)
def test_validate_client_id_accepts_valid(client_id):
    assert validate_client_id(client_id) == client_id


@pytest.mark.parametrize(
    "client_id",
    [
        "",
        "../../etc/passwd",
        "../foo",
        "foo/bar",
        "foo bar",
        "foo.bar",
        "/etc/passwd",
        "foo/../../bar",
        "foo\n",
    ],
)
def test_validate_client_id_rejects_path_traversal_and_invalid_chars(client_id):
    """`--client ../../foo` のようなパストラバーサルを弾く（コードレビュー既知の指摘）."""
    with pytest.raises(ValueError):
        validate_client_id(client_id)


def test_resolve_client_paths_uses_repo_root_outputs(monkeypatch, tmp_path):
    project_root = tmp_path / "measurement_design"
    repo_root = tmp_path
    monkeypatch.setattr(config_module, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(config_module, "REPO_ROOT", repo_root)

    paths = resolve_client_paths("sample-client", create=False)

    # 成果物（_data/docs/pdf）はリポジトリルートの outputs/{client_id}/02_measurement/ 配下
    assert paths.output_dir == repo_root / "outputs" / "sample-client" / "02_measurement"
    assert paths.data_dir == paths.output_dir / "_data"
    assert paths.docs_dir == paths.output_dir / "docs"
    assert paths.report_dir == paths.output_dir / "report"
    # inputs/ は従来どおり measurement_design 配下（クライアント提供の入力・git管理対象）
    assert paths.inputs_dir == project_root / "sample-client" / "inputs"


def test_resolve_client_paths_create_true_makes_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)

    paths = resolve_client_paths("sample-client", create=True)

    assert paths.data_dir.is_dir()
    assert paths.docs_dir.is_dir()
    assert paths.inputs_dir.is_dir()


def test_resolve_client_paths_does_not_create_report_dir(monkeypatch, tmp_path):
    """`report_dir` は人が納品用の原稿を置くまで存在しない状態でよい。

    review を1回実行しただけで「誰も書き込んでいない空の report/」が
    クライアント成果物に混ざっていた不具合の修正（この関数だけが自動作成を担っている
    ため、他の3ディレクトリと違いここでは作らないことを固定する）。
    """
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)

    paths = resolve_client_paths("sample-client", create=True)

    assert not paths.report_dir.exists()


def test_resolve_client_paths_create_false_does_not_make_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)

    paths = resolve_client_paths("sample-client", create=False)

    assert not paths.data_dir.exists()
    assert not paths.inputs_dir.exists()


def test_resolve_client_paths_rejects_invalid_client_id(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)

    with pytest.raises(ValueError):
        resolve_client_paths("../evil", create=False)


def test_audit_config_uses_new_output_layout(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)

    cfg = AuditConfig(property_id="123", client_name="sample-client")

    assert cfg.output_dir == tmp_path / "outputs" / "sample-client" / "02_measurement"
    assert cfg.data_dir == cfg.output_dir / "_data"
    assert cfg.docs_dir == cfg.output_dir / "docs"
    assert cfg.report_dir == cfg.output_dir / "report"
    assert cfg.inputs_dir == (tmp_path / "measurement_design") / "sample-client" / "inputs"


def test_audit_config_rejects_invalid_client_id(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)

    with pytest.raises(ValueError):
        AuditConfig(property_id="123", client_name="../../evil")
