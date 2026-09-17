"""インプットファイルの読み込みモジュール."""

from __future__ import annotations

from pathlib import Path

import yaml


def load_kpis(inputs_dir: Path) -> list[dict]:
    """kpis.yaml を読み込んでリストを返す."""
    kpis_file = inputs_dir / "kpis.yaml"
    if not kpis_file.exists():
        raise FileNotFoundError(f"kpis.yaml が見つかりません: {kpis_file}")
    with open(kpis_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("kpis", [])


def load_screen_flow(inputs_dir: Path) -> dict:
    """screen-flow.yaml を読み込んでdictを返す."""
    flow_file = inputs_dir / "screen-flow.yaml"
    if not flow_file.exists():
        raise FileNotFoundError(f"screen-flow.yaml が見つかりません: {flow_file}")
    with open(flow_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return {
        "pages": data.get("pages", []),
        "flows": data.get("flows", []),
    }


def load_ga4_local(inputs_dir: Path) -> dict:
    """ga4.local.yaml を読み込む。存在しない場合は空dictを返す."""
    ga4_file = inputs_dir / "ga4.local.yaml"
    if not ga4_file.exists():
        return {}
    with open(ga4_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("ga4", {})


def load_gtm_local(inputs_dir: Path) -> dict | None:
    """gtm.local.yaml を読み込む。存在しない場合は None を返す."""
    gtm_file = inputs_dir / "gtm.local.yaml"
    if not gtm_file.exists():
        return None
    with open(gtm_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    gtm = data.get("gtm", {})
    if not gtm:
        return None
    return gtm
