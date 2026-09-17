"""初回セットアップのローカル状態を、安全に確認する。

Googleの鍵は存在と形式だけを確認し、秘密鍵の内容は出力しない。
AIエージェントから次のように実行する想定:

    uv run --no-sync --project 01_context_management python tools/setup_status.py --json --run-sample-check
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTEXT_DIR = REPO_ROOT / "01_context_management" / "context"
DEFAULT_KEY_RELATIVE = Path(".saa/credentials/google-analytics/sa-key.json")
PRIVATE_KEY_FIELD = "private" + "_key"
CLIENT_EMAIL_FIELD = "client" + "_email"
REQUIRED_REPO_FILES = (
    "README.md",
    "docs/ai-agent-guide.md",
    "docs/setup-workflow.md",
    "docs/setup-ga4.md",
    "02_basic_measurement/measurement_design/run.py",
)


def _state(state: str, **values: Any) -> dict[str, Any]:
    return {"state": state, **values}


def check_repository(root: Path) -> dict[str, Any]:
    missing = [name for name in REQUIRED_REPO_FILES if not (root / name).is_file()]
    if missing:
        return _state("error", missing=missing)
    return _state("ready", root=str(root))


def check_uv() -> dict[str, Any]:
    executable = shutil.which("uv")
    if not executable:
        return _state("missing")
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _state("error", reason=str(exc))
    version = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        return _state("error", reason=version or f"exit {result.returncode}")
    return _state("ready", version=version)


def check_sample(root: Path, *, run_check: bool, uv_status: Mapping[str, Any]) -> dict[str, Any]:
    project = root / "02_basic_measurement" / "measurement_design"
    required = (
        project / "sample-client" / "inputs" / "kpis.yaml",
        project / "sample-client" / "inputs" / "screen-flow.yaml",
        project / "sample-client" / "inputs" / "ga4.local.yaml",
        project / "sample-client" / "inputs" / "gtm.local.yaml",
    )
    missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
    if missing:
        return _state("error", missing=missing)
    if not run_check:
        return _state("unchecked", files="ready")
    if uv_status.get("state") != "ready":
        return _state("blocked", reason="uv is not ready")

    executable = shutil.which("uv")
    assert executable is not None
    try:
        result = subprocess.run(
            [
                executable,
                "run",
                "--no-sync",
                "--project",
                str(project),
                "python",
                "run.py",
                "validate",
                "--client",
                "sample-client",
            ],
            cwd=project,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _state("error", reason=str(exc))

    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if result.returncode != 0:
        return _state("error", reason=output[-2000:] or f"exit {result.returncode}")
    return _state("ready")


def resolve_key_path(home: Path, env: Mapping[str, str]) -> tuple[Path, str]:
    configured = str(env.get("GA4_SA_KEY_PATH", "")).strip()
    if configured:
        return Path(configured).expanduser(), "GA4_SA_KEY_PATH"
    return home / DEFAULT_KEY_RELATIVE, "default"


def check_google_key(home: Path, env: Mapping[str, str]) -> dict[str, Any]:
    path, source = resolve_key_path(home, env)
    base = {"path": str(path), "source": source}
    if not path.is_file():
        return _state("missing", **base)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _state("invalid", **base, reason=f"JSONとして読めません: {exc}")

    if not isinstance(payload, dict):
        return _state("invalid", **base, reason="JSONの形式がサービスアカウント鍵ではありません")
    required = ("type", "project_id", PRIVATE_KEY_FIELD, CLIENT_EMAIL_FIELD, "token_uri")
    missing = [name for name in required if not payload.get(name)]
    if payload.get("type") != "service_account":
        return _state("invalid", **base, reason="type が service_account ではありません")
    if missing:
        return _state("invalid", **base, reason="必要な項目がありません", missing=missing)

    # 秘密鍵は存在だけを確認する。値は戻り値にも標準出力にも含めない。
    return _state(
        "ready",
        **base,
        service_account_email=str(payload[CLIENT_EMAIL_FIELD]),
        project_id=str(payload["project_id"]),
    )


def check_effective_optional_key(
    home: Path,
    env: Mapping[str, str],
    *,
    variable: str,
    ga4_key: Mapping[str, Any],
) -> dict[str, Any]:
    """任意接続が使う実効鍵を確認する。未指定ならGA4用の鍵を共用する。"""
    configured = str(env.get(variable, "")).strip()
    if not configured:
        if ga4_key.get("state") != "ready":
            return _state("blocked", source="GA4の鍵", reason="GA4の鍵が未設定です")
        return _state(
            "shared",
            source="GA4の鍵",
            path=ga4_key.get("path", ""),
            service_account_email=ga4_key.get("service_account_email", ""),
            project_id=ga4_key.get("project_id", ""),
        )

    result = check_google_key(home, {"GA4_SA_KEY_PATH": configured})
    result["source"] = variable
    return result


def _load_yaml(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.is_file():
        return {}, None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return {}, str(exc)
    if not isinstance(data, dict):
        return {}, "先頭が辞書形式ではありません"
    return data, None


def check_context(context_dir: Path) -> dict[str, Any]:
    if not context_dir.is_dir():
        return _state("missing", clients=[])

    clients: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for directory in sorted(path for path in context_dir.iterdir() if path.is_dir()):
        profile, profile_error = _load_yaml(directory / "profile.yaml")
        measurement, measurement_error = _load_yaml(directory / "measurement.yaml")
        kpis, kpis_error = _load_yaml(directory / "kpis.yaml")
        for filename, reason in (
            ("profile.yaml", profile_error),
            ("measurement.yaml", measurement_error),
            ("kpis.yaml", kpis_error),
        ):
            if reason:
                errors.append({"client_id": directory.name, "file": filename, "reason": reason})

        client = profile.get("client") if isinstance(profile.get("client"), dict) else {}
        ga4 = measurement.get("ga4") if isinstance(measurement.get("ga4"), dict) else {}
        search_console = (
            measurement.get("search_console")
            if isinstance(measurement.get("search_console"), dict)
            else {}
        )
        bigquery = measurement.get("bigquery") if isinstance(measurement.get("bigquery"), dict) else {}
        key_events = kpis.get("key_events") if isinstance(kpis.get("key_events"), list) else []
        clients.append(
            {
                "client_id": directory.name,
                "site_name": str(client.get("name") or ""),
                "site_url": str(client.get("site_url") or ""),
                "ga4_property_id": str(ga4.get("property_id") or ""),
                "search_console_site_url": str(search_console.get("site_url") or ""),
                "bigquery_project_id": str(bigquery.get("project_id") or ""),
                "bigquery_dataset": str(bigquery.get("dataset") or ""),
                "key_event_count": len([value for value in key_events if str(value).strip()]),
            }
        )

    if errors:
        return _state("error", clients=clients, errors=errors)
    if not clients:
        return _state("missing", clients=[])
    needs_input = [
        item["client_id"]
        for item in clients
        if not item["site_name"] or not item["ga4_property_id"]
    ]
    if needs_input:
        return _state("incomplete", clients=clients, needs_input=needs_input)
    return _state("ready", clients=clients)


def choose_next_step(checks: Mapping[str, Mapping[str, Any]]) -> str:
    if checks["repository"].get("state") != "ready":
        return "open_repository_root"
    if checks["uv"].get("state") != "ready":
        return "install_or_fix_uv"
    if checks["sample"].get("state") == "unchecked":
        return "run_sample_check"
    if checks["sample"].get("state") in {"error", "blocked"}:
        return "fix_local_execution"
    key_state = checks["google_key"].get("state")
    if key_state == "missing":
        if checks["google_key"].get("source") == "GA4_SA_KEY_PATH":
            return "fix_google_key_path"
        return "create_google_key"
    if key_state != "ready":
        return "replace_invalid_google_key"
    if checks["context"].get("state") in {"missing", "incomplete"}:
        return "select_and_register_ga4_property"
    if checks["context"].get("state") == "error":
        return "fix_saved_site_settings"
    return "verify_google_connections"


def collect_status(
    *,
    root: Path = REPO_ROOT,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    context_dir: Path | None = None,
    run_sample_check: bool = False,
) -> dict[str, Any]:
    actual_home = home or Path.home()
    actual_env = os.environ if env is None else env
    repository = check_repository(root)
    uv_status = check_uv()
    google_key = check_google_key(actual_home, actual_env)
    checks = {
        "repository": repository,
        "uv": uv_status,
        "sample": check_sample(root, run_check=run_sample_check, uv_status=uv_status),
        "google_key": google_key,
        "search_console_key": check_effective_optional_key(
            actual_home, actual_env, variable="SC_SA_KEY_PATH", ga4_key=google_key
        ),
        "bigquery_key": check_effective_optional_key(
            actual_home, actual_env, variable="BQ_SA_KEY_PATH", ga4_key=google_key
        ),
        "context": check_context(context_dir or root / "01_context_management" / "context"),
    }
    next_step = choose_next_step(checks)
    overall = (
        "needs_online_verification"
        if next_step == "verify_google_connections"
        else "needs_action"
    )
    return {"schema_version": 1, "overall": overall, "checks": checks, "next_step": next_step}


STATE_LABELS = {
    "ready": "OK",
    "shared": "GA4と共用",
    "unchecked": "未確認",
    "missing": "未設定",
    "incomplete": "入力不足",
    "blocked": "保留",
    "invalid": "要修正",
    "error": "エラー",
}

NEXT_STEP_LABELS = {
    "open_repository_root": "README.mdがあるフォルダをAIツールで開く",
    "install_or_fix_uv": "uvをインストールするか、AIツールを開き直す",
    "run_sample_check": "付属サンプルの入力を確認する",
    "fix_local_execution": "サンプルの読み込みエラーを直す",
    "create_google_key": "Google Cloudでサービスアカウントと鍵を作る",
    "fix_google_key_path": "GA4_SA_KEY_PATHと鍵ファイルの場所を合わせる",
    "replace_invalid_google_key": "正しいJSON形式のサービスアカウント鍵を置く",
    "select_and_register_ga4_property": "閲覧できるGA4プロパティを確認し、対象サイトを登録する",
    "fix_saved_site_settings": "保存済みのサイト設定を直す",
    "verify_google_connections": "GA4、Search Console、BigQueryの接続をオンラインで確認する",
}


def render_human(status: Mapping[str, Any]) -> str:
    checks = status["checks"]
    labels = {
        "repository": "作業フォルダ",
        "uv": "実行ツール（uv）",
        "sample": "付属サンプル",
        "google_key": "Googleの鍵",
        "search_console_key": "Search Consoleで使う鍵",
        "bigquery_key": "BigQueryで使う鍵",
        "context": "サイトの登録情報",
    }
    lines = ["セットアップ状況"]
    for key, label in labels.items():
        state = str(checks[key].get("state", "error"))
        lines.append(f"- [{STATE_LABELS.get(state, state)}] {label}")
    next_step = str(status.get("next_step", ""))
    lines.append(f"次にすること: {NEXT_STEP_LABELS.get(next_step, next_step)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="AIが読み取りやすいJSONで表示する")
    parser.add_argument(
        "--run-sample-check",
        action="store_true",
        help="付属サンプルの入力検証まで実行する",
    )
    parser.add_argument("--context-dir", type=Path, default=DEFAULT_CONTEXT_DIR)
    args = parser.parse_args(argv)

    status = collect_status(context_dir=args.context_dir, run_sample_check=args.run_sample_check)
    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
    else:
        print(render_human(status))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
