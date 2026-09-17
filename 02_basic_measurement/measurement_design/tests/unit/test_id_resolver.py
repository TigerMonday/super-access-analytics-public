"""id_resolver.py のユニットテスト（ID解決の優先順と『一度聞いたら残す』保存）."""
from pathlib import Path
from types import SimpleNamespace

import yaml

# tests/unit/test_id_resolver.py -> tests -> measurement_design（実プロジェクトルート）。
# `_from_01_context` は `project_root.parent.parent / "01_context_management" / "src"` の
# 実在チェックをするため、09連携のテストだけは架空パスでなく実プロジェクトルートを渡す。
_REAL_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _args(**kw):
    base = {"property_id": "", "auth": "sa", "sa_key_path": "", "gtm_account": "", "gtm_container": ""}
    base.update(kw)
    return SimpleNamespace(**base)


def test_resolve_none_when_nowhere(tmp_path):
    from measurement_design.id_resolver import resolve_ids
    client_dir = tmp_path / "c"
    (client_dir / "inputs").mkdir(parents=True)
    ids = resolve_ids(_args(), client_dir, tmp_path)  # flag空・local無し・09無し
    assert ids["property_id"] == ""


def test_resolve_from_local_yaml(tmp_path):
    from measurement_design.id_resolver import resolve_ids
    client_dir = tmp_path / "c"
    inputs = client_dir / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "ga4.local.yaml").write_text(
        yaml.safe_dump({"ga4": {"property_id": "111", "auth_method": "sa"}}), encoding="utf-8"
    )
    (inputs / "gtm.local.yaml").write_text(
        yaml.safe_dump({"gtm": {"gtm_account_id": "A1", "gtm_container_id": "GTM-C1"}}), encoding="utf-8"
    )
    ids = resolve_ids(_args(), client_dir, tmp_path)
    assert ids["property_id"] == "111"
    assert ids["gtm_account"] == "A1"
    assert ids["gtm_container"] == "GTM-C1"


def test_flag_overrides_local(tmp_path):
    from measurement_design.id_resolver import resolve_ids
    client_dir = tmp_path / "c"
    inputs = client_dir / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "ga4.local.yaml").write_text(
        yaml.safe_dump({"ga4": {"property_id": "111"}}), encoding="utf-8"
    )
    ids = resolve_ids(_args(property_id="999"), client_dir, tmp_path)
    assert ids["property_id"] == "999"  # フラグが優先


def test_persist_then_resolve_roundtrip(tmp_path):
    """『一度聞いたら残す』: フラグで来た値を保存→次回フラグ無しで解決できる."""
    from measurement_design.id_resolver import resolve_ids, persist_ids
    client_dir = tmp_path / "c"
    (client_dir / "inputs").mkdir(parents=True)

    first = resolve_ids(_args(property_id="123456789", gtm_account="A9", gtm_container="GTM-X9"), client_dir, tmp_path)
    persist_ids(client_dir, first)

    # 次回: フラグ無しでも保存済みから解決できる
    again = resolve_ids(_args(), client_dir, tmp_path)
    assert again["property_id"] == "123456789"
    assert again["gtm_account"] == "A9"
    assert again["gtm_container"] == "GTM-X9"


def test_resolve_from_01_context(tmp_path):
    """01コンテキストストアの measurement.yaml から GA4/GTM ID を解決できる.

    measurement.yaml の GTM キーは `gtm_account_id` / `gtm_container_id`
    （01_context_management/templates/measurement.template.yaml・context-schema.md 準拠）。
    かつて id_resolver 側が `account_id` / `container_id` を参照しており、
    01に保存済みでも GTM だけ毎回聞き直しになっていた回帰を防ぐ。
    """
    from measurement_design.id_resolver import resolve_ids

    project_root = _REAL_PROJECT_ROOT
    client_dir = tmp_path / "c"
    (client_dir / "inputs").mkdir(parents=True)

    context_dir = tmp_path / "context"
    client_ctx_dir = context_dir / "c"
    client_ctx_dir.mkdir(parents=True)
    (client_ctx_dir / "profile.yaml").write_text(
        yaml.safe_dump({"client": {"client_id": "c", "name": "テスト社"}}, allow_unicode=True),
        encoding="utf-8",
    )
    (client_ctx_dir / "measurement.yaml").write_text(
        yaml.safe_dump(
            {
                "ga4": {"property_id": "123456789"},
                "gtm": {"gtm_account_id": "A5", "gtm_container_id": "GTM-C5"},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    ids = resolve_ids(_args(), client_dir, project_root, context_dir=context_dir)
    assert ids["property_id"] == "123456789"
    assert ids["gtm_account"] == "A5"
    assert ids["gtm_container"] == "GTM-C5"


def test_persist_ids_skips_sample_client(tmp_path):
    """sample-client/inputs/*.local.yaml はリポジトリ管理対象のサンプルのため、
    実データで上書きしない（気づかず git にコミットしてしまう事故を防ぐ）。"""
    from measurement_design.id_resolver import resolve_ids, persist_ids

    client_dir = tmp_path / "sample-client"
    inputs = client_dir / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "ga4.local.yaml").write_text(
        yaml.safe_dump({"ga4": {"property_id": "123456789", "auth_method": "sa"}}), encoding="utf-8"
    )

    resolved = resolve_ids(
        _args(property_id="987654321", gtm_account="REAL-A", gtm_container="GTM-REAL"),  # leak-ok: テスト用の架空ID（sample-clientが上書きされないことの確認用）
        client_dir,
        tmp_path,
    )
    persist_ids(client_dir, resolved)

    # 実データでファイルが上書きされていないことを確認
    saved = yaml.safe_load((inputs / "ga4.local.yaml").read_text(encoding="utf-8"))
    assert saved["ga4"]["property_id"] == "123456789"
    assert not (inputs / "gtm.local.yaml").exists()


def test_prompt_gtm_ids_skips_when_tty_has_no_readable_input(monkeypatch, capsys):
    """TTY判定でも input() がEOFになる無人実行では、GA4のみで安全に続行する。"""
    import builtins
    import sys

    from measurement_design.id_resolver import prompt_gtm_ids

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda _prompt: (_ for _ in ()).throw(EOFError()))
    ids = {"property_id": "123456789", "gtm_account": "", "gtm_container": ""}

    assert prompt_gtm_ids(ids) == ids
    assert "GTM はスキップ" in capsys.readouterr().out
