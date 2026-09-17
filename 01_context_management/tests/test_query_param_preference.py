"""profile.yaml の preferences.include_query_params のテスト。

背景: 試用フィードバックで、ランディングページ集計に `/?renew=` のようなクエリパラメータが
そのまま残っていて見づらいという指摘があった。既定はパスのみ（クエリを無視）とし、
EC・ブログのようにクエリ自体が別ページを表すサイトだけ明示的に true を設定できる器を用意する。

観点:
  - 未設定なら `ClientContext.include_query_params` は常に `False`（聞き直しが必要な3値は不要）
  - `writeback.save_query_param_preference` で true/false を保存でき、他の preferences
    （output_formats 等）や client の他フィールドを壊さない
"""
from pathlib import Path

import yaml

from context_store.loader import load_context
from context_store.writeback import save_query_param_preference


def _write_profile(tmp_path: Path, client_id: str, profile: dict) -> Path:
    client_dir = tmp_path / client_id
    client_dir.mkdir(parents=True)
    (client_dir / "profile.yaml").write_text(
        yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return tmp_path


def test_include_query_params_defaults_to_false_when_unset(tmp_path):
    base = _write_profile(tmp_path, "c1", {"client": {"client_id": "c1", "name": "テスト社"}})
    ctx = load_context("c1", context_dir=base)
    assert ctx.include_query_params is False


def test_save_query_param_preference_sets_true(tmp_path):
    base = _write_profile(
        tmp_path,
        "c2",
        {
            "client": {"client_id": "c2", "name": "テスト社"},
            "preferences": {"output_formats": ["html"]},
        },
    )
    save_query_param_preference("c2", include_query_params=True, context_dir=base)

    ctx = load_context("c2", context_dir=base)
    assert ctx.include_query_params is True
    assert ctx.output_formats == ["html"]  # 既存preferencesは維持
    assert ctx.name == "テスト社"  # client情報も維持


def test_save_query_param_preference_can_set_back_to_false(tmp_path):
    base = _write_profile(
        tmp_path,
        "c3",
        {
            "client": {"client_id": "c3", "name": "テスト社"},
            "preferences": {"include_query_params": True},
        },
    )
    save_query_param_preference("c3", include_query_params=False, context_dir=base)

    ctx = load_context("c3", context_dir=base)
    assert ctx.include_query_params is False
