"""トップレベルのエージェント番号が標準実行順からずれないことを確認する。"""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_AGENT_DIRS = [
    "01_context_management",
    "02_basic_measurement",
    "03_external_research",
    "04_traffic_analysis",
    "05_campaign_optimization",
    "06_effect_verification",
    "07_adhoc_analysis",
]


def test_agent_directories_follow_standard_run_order() -> None:
    actual = sorted(
        path.name
        for path in REPO_ROOT.iterdir()
        if path.is_dir() and re.match(r"^\d{2}_", path.name)
    )

    assert actual == EXPECTED_AGENT_DIRS


def test_legacy_agent_directories_do_not_reappear() -> None:
    legacy = {
        "01_basic_measurement",
        "02_external_research",
        "03_traffic_analysis",
        "05_adhoc_analysis",
        "06_campaign_optimization",
        "07_effect_verification",
        "09_context_management",
    }

    assert not legacy.intersection(path.name for path in REPO_ROOT.iterdir())


def test_product_specific_slash_commands_do_not_reappear() -> None:
    command_dir = REPO_ROOT / ".claude" / "commands"
    assert not command_dir.exists() or not any(command_dir.iterdir())

    forbidden = (".claude" + "/commands", "/" + "saa-")
    roots = [
        REPO_ROOT / "docs",
        REPO_ROOT / "common",
        *(REPO_ROOT / name for name in EXPECTED_AGENT_DIRS),
    ]
    standalone = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "AGENTS.md",
        REPO_ROOT / "CLAUDE.md",
        REPO_ROOT / "GEMINI.md",
    ]
    offenders: list[str] = []
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or ".venv" in path.parts:
                continue
            if path.suffix.lower() not in {".md", ".py", ".yml", ".yaml", ".toml"}:
                continue
            text = path.read_text(encoding="utf-8")
            if any(token in text for token in forbidden):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    for path in standalone:
        if path.exists() and any(
            token in path.read_text(encoding="utf-8") for token in forbidden
        ):
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert offenders == []


def test_every_human_facing_entrypoint_accepts_natural_language() -> None:
    entrypoints = [
        REPO_ROOT / "docs" / "ai-agent-guide.md",
        REPO_ROOT / "01_context_management" / "run.md",
        REPO_ROOT / "02_basic_measurement" / "measurement_design" / "README.md",
        REPO_ROOT
        / "03_external_research"
        / "web_research"
        / "external-research-coordinator"
        / "SKILL.md",
        REPO_ROOT / "04_traffic_analysis" / "parameter_management" / "run.md",
        REPO_ROOT / "05_campaign_optimization" / "run.md",
        REPO_ROOT / "07_adhoc_analysis" / "run.md",
        REPO_ROOT / "common" / "report_export" / "README.md",
    ]

    for path in entrypoints:
        assert "自然文" in path.read_text(encoding="utf-8"), path


def test_campaign_creation_and_review_role_numbers_do_not_regress() -> None:
    campaign_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "05_campaign_optimization").rglob("*.md")
    )
    review_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "06_effect_verification").rglob("*.md")
    )

    assert "agent='06_1_analysis'" not in campaign_text
    assert "agent='06_1_creation'" not in campaign_text
    assert "agent='06_2_analysis'" not in campaign_text
    assert "agent='06_2_creation'" not in campaign_text
    assert "05/analysis_review" not in campaign_text
    assert "agent='07_" not in review_text
    assert "前段（06/analysis）" not in review_text
    assert "前段（06/creation）" not in review_text
    assert "②分析（06）" not in review_text
    assert "②施策作成（06）" not in review_text
