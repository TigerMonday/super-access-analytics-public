"""run.py の終了コードのユニットテスト.

外部LLMを使わない設定（既定 `--llm-backend none`）は失敗ではなく正常な分岐であり、
「計測設計書の文章生成はいまのAIエージェントに任せる」という状態を表す。
`design` を直接呼んだ場合と `run`（fetch+review+design一括）経由で同じ分岐に
入った場合とで終了コードが揃うことを固定する（design側だけ2を返していた
不整合の再発防止）。
"""
import argparse
import pytest

import config as config_module
import run as run_module
from config import resolve_client_paths


def _design_args(client="sample-client", llm_backend="none"):
    return argparse.Namespace(client=client, llm_backend=llm_backend)


def _run_args(client="sample-client", llm_backend="none"):
    return argparse.Namespace(
        client=client,
        llm_backend=llm_backend,
        no_llm=False,
        property_id="",
        auth="sa",
        oauth_profile="",
        sa_key_path="",
        gtm_account="",
        gtm_container="",
    )


def test_cmd_design_returns_zero_when_backend_none(monkeypatch, tmp_path, capsys):
    """design を直接呼んでも、noneのとき終了コードは0（失敗扱いにしない）."""
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)

    rc = run_module.cmd_design(_design_args())

    assert rc == 0
    out = capsys.readouterr().out
    assert "[NG]" not in out  # 失敗ではないので[NG]表記は出ない
    assert "[案内]" in out  # 次に何をすればいいかが分かる案内表記に変わっている


def test_cmd_run_returns_zero_when_backend_none_and_skips_design(monkeypatch):
    """run経由でも同じ分岐に入り、design段には進まず0を返す."""
    monkeypatch.setattr(run_module, "cmd_fetch", lambda args: 0)
    monkeypatch.setattr(run_module, "cmd_review", lambda args: 0)

    def _fail_if_called(args):
        raise AssertionError("backend=none のとき cmd_design は呼ばれないはず")

    monkeypatch.setattr(run_module, "cmd_design", _fail_if_called)

    rc = run_module.cmd_run(_run_args())

    assert rc == 0


def test_cmd_design_and_cmd_run_exit_codes_match_when_backend_none(monkeypatch, tmp_path):
    """design単体呼び出しとrun経由の終了コードが一致する（呼び方で結果が割れない）."""
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(run_module, "cmd_fetch", lambda args: 0)
    monkeypatch.setattr(run_module, "cmd_review", lambda args: 0)

    rc_design = run_module.cmd_design(_design_args())
    rc_run = run_module.cmd_run(_run_args())

    assert rc_design == rc_run == 0


# ──────────────────────────────────────
# 確定所見（docs/findings.md）が cmd_design から章生成の context に渡ること
#
# 生成器はデータセットしか見ないため、docs/findings.md に書いた「原因まで
# 特定した事実」を知らない。context["findings"] 経由で最優先の制約として
# 渡す配線を、run.py 側で固定する（生成プロンプトへの反映は generator.py 側
# の test_generator.py で検証済み）。
# ──────────────────────────────────────

def _write_minimal_inputs(inputs_dir):
    inputs_dir.mkdir(parents=True, exist_ok=True)
    (inputs_dir / "kpis.yaml").write_text(
        "kpis:\n  - kpi_id: kpi_001\n    name: テストKPI\n", encoding="utf-8",
    )
    (inputs_dir / "screen-flow.yaml").write_text(
        "pages: []\nflows: []\n", encoding="utf-8",
    )


def test_cmd_design_passes_findings_md_into_generation_context(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)

    paths = resolve_client_paths("sample-client")
    _write_minimal_inputs(paths.inputs_dir)
    paths.docs_dir.mkdir(parents=True, exist_ok=True)
    (paths.docs_dir / "findings.md").write_text(
        "signup と sign_up は別イベント。signup が正。", encoding="utf-8",
    )

    monkeypatch.setattr(
        "measurement_design.design.decomposer.decompose_all_kpis",
        lambda kpis, screen_flow, naming_md, api_key: [],
    )
    monkeypatch.setattr(
        "measurement_design.design.standardizer.standardize_events",
        lambda breakdowns, review_data, naming_md, reserved_md, api_key: [],
    )
    monkeypatch.setattr(
        "measurement_design.design.selector.select_chapters",
        lambda breakdowns, review_data: [1],
    )

    captured_context = {}

    def _fake_generate_all_chapters(chapters, templates_dir, context, api_key, design_doc_dir):
        captured_context.update(context)
        return []

    monkeypatch.setattr(
        "measurement_design.design.generator.generate_all_chapters",
        _fake_generate_all_chapters,
    )

    rc = run_module.cmd_design(_design_args(llm_backend="claude_cli"))

    assert rc == 0
    assert "signup と sign_up は別イベント" in captured_context["findings"]


def test_cmd_design_leaves_findings_empty_when_findings_md_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)

    paths = resolve_client_paths("sample-client")
    _write_minimal_inputs(paths.inputs_dir)
    # docs/findings.md も docs/check-report.md も置かない

    monkeypatch.setattr(
        "measurement_design.design.decomposer.decompose_all_kpis",
        lambda kpis, screen_flow, naming_md, api_key: [],
    )
    monkeypatch.setattr(
        "measurement_design.design.standardizer.standardize_events",
        lambda breakdowns, review_data, naming_md, reserved_md, api_key: [],
    )
    monkeypatch.setattr(
        "measurement_design.design.selector.select_chapters",
        lambda breakdowns, review_data: [1],
    )

    captured_context = {}

    def _fake_generate_all_chapters(chapters, templates_dir, context, api_key, design_doc_dir):
        captured_context.update(context)
        return []

    monkeypatch.setattr(
        "measurement_design.design.generator.generate_all_chapters",
        _fake_generate_all_chapters,
    )

    rc = run_module.cmd_design(_design_args(llm_backend="claude_cli"))

    assert rc == 0
    assert captured_context["findings"] == ""
    assert "確定所見が見つかりません" in capsys.readouterr().out


# ──────────────────────────────────────
# ○△×の網羅チェック（audit_matrix）が review 実行時に計算され、render_check_report に
# 渡されること。
#
# 以前は同じ計算結果を別ファイル docs/audit-matrix.md にも書き出していたが、
# 「見るレポートは check-report 一本にしたい」という要望で統合し、別ファイルの
# 生成はやめた（render_check_report 内で check-report.md 本文に埋め込む。
# tests/unit/test_renderer.py で埋め込み自体は検証済み）。ここでは cmd_review が
# render_check_report へ matrix_rows を正しく渡していること、そして
# 別ファイルがもう作られないことを固定する。
# ──────────────────────────────────────

def _review_args(client="sample-client"):
    return argparse.Namespace(client=client, llm_backend="none", no_llm=True)


@pytest.mark.parametrize("formats, expected", [(None, {}), (["md"], {"output_formats": []}), (["html"], {"output_formats": ["html"]})])
def test_cmd_review_passes_audit_matrix_to_render_check_report_and_stops_writing_separate_file(monkeypatch, tmp_path, formats, expected):
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)

    paths = resolve_client_paths("sample-client")
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    (paths.data_dir / "phase1.json").write_text(
        '{"property": {"name": "properties/1"}}', encoding="utf-8",
    )

    monkeypatch.setattr(
        "measurement_design.review.diagnoser.diagnose",
        lambda review_data, standards_dir, api_key, data_dir=None: [],
    )

    captured: dict = {}

    def fake_render(*a, **k):
        captured["matrix_rows"] = k.get("matrix_rows")
        return "# check report\n"

    monkeypatch.setattr(
        "measurement_design.review.renderer.render_check_report",
        fake_render,
    )

    import report_export_bridge
    export_calls = []
    def fake_export(paths, client, **kwargs):
        export_calls.append(kwargs)
        return report_export_bridge.ExportOutcome()
    monkeypatch.setattr(report_export_bridge, "export_if_configured", fake_export)
    args = _review_args()
    args.output_formats = formats
    rc = run_module.cmd_review(args)
    assert export_calls == [expected]

    assert rc == 0
    # render_check_report が固定項目の判定表をそのまま受け取っている
    from measurement_design.review.audit_matrix import ITEMS as AUDIT_ITEMS

    assert captured["matrix_rows"] is not None
    assert len(captured["matrix_rows"]) == len(AUDIT_ITEMS)
    # 別ファイル docs/audit-matrix.md はもう作られない（check-report.md に統合済み）
    assert not (paths.docs_dir / "audit-matrix.md").exists()


# ──────────────────────────────────────
# cmd_review が diagnose() へ data_dir を渡すこと。
#
# `diagnose(review_data, standards_dir, api_key)` と3引数で呼んでいたため、
# 第4引数 data_dir（省略時 None）が渡らず、health_checks（実測ベースの健全性
# 検出18項目）が一度も実行されずに常に検出0件を返していた（配線漏れバグ）。
# diagnose() 自体は実装をそのまま使い、health_checks だけ差し替えて、
# cmd_review 経由で正しい data_dir が渡り発火することを検証する。
# ──────────────────────────────────────

def test_cmd_review_wires_data_dir_so_health_checks_actually_run(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)

    paths = resolve_client_paths("sample-client")
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    (paths.data_dir / "phase1.json").write_text(
        '{"property": {"name": "properties/1"}}', encoding="utf-8",
    )

    sentinel = [{
        "id": "V-H-001", "severity": "High", "category": "健全性検出",
        "target_kind": "check", "target_name": "sentinel",
        "location": "GA4", "description": "sentinel", "suggested_fix": "",
    }]
    received: dict = {}

    def fake_health_checks(data_dir):
        received["data_dir"] = data_dir
        return sentinel

    monkeypatch.setattr(
        "measurement_design.review.health_checks.health_checks",
        fake_health_checks,
    )

    captured: dict = {}

    def fake_render(violations, *a, **k):
        captured["violations"] = violations
        return "# check report\n"

    monkeypatch.setattr(
        "measurement_design.review.renderer.render_check_report",
        fake_render,
    )

    rc = run_module.cmd_review(_review_args())

    assert rc == 0
    # health_checks が呼ばれ、正しい data_dir を受け取っている
    assert received.get("data_dir") == paths.data_dir
    # health_checks の結果がレポートに実際に反映されている（呼ばれただけで消える配線も検出する）
    assert sentinel[0] in captured["violations"]


# ──────────────────────────────────────
# クロスドメイン計測（audit_matrix の新規項目）が review 実行のCLI経路で
# 正しく「対象外」を出すこと。実測（前提として与えられている実データの形）は
# 単一ドメイン（実ホスト1件＋`(not set)`＋空文字）で、複数ドメインの誤検知が
# 出ないことをここで固定する。
# ──────────────────────────────────────

def test_cmd_review_cross_domain_is_out_of_scope_for_single_domain_hosts(monkeypatch, tmp_path):
    import json

    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)

    paths = resolve_client_paths("sample-client")
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    (paths.data_dir / "phase1.json").write_text(
        '{"property": {"name": "properties/1"}}', encoding="utf-8",
    )
    # 実データの形（単一の実ホスト＋`(not set)`＋空文字の3件のみ）を再現する
    (paths.data_dir / "07-data-quality.json").write_text(
        json.dumps({"hosts": [
            {"hostName": "www.example.jp", "sessions": 9990},
            {"hostName": "(not set)", "sessions": 8},
            {"hostName": "", "sessions": 2},
        ]}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "measurement_design.review.diagnoser.diagnose",
        lambda review_data, standards_dir, api_key, data_dir=None: [],
    )

    captured: dict = {}

    def fake_render(*a, **k):
        captured["matrix_rows"] = k.get("matrix_rows")
        return "# check report\n"

    monkeypatch.setattr(
        "measurement_design.review.renderer.render_check_report",
        fake_render,
    )

    rc = run_module.cmd_review(_review_args())

    assert rc == 0
    cross_domain_row = next(
        r for r in captured["matrix_rows"] if r["name"] == "クロスドメイン計測"
    )
    assert cross_domain_row["judgement"] == "warn"
    assert "主要ホストは1つ（www.example.jp）" in cross_domain_row["state"]
    assert "予約・決済等の別ホストはGA4受信データに現れていない" in cross_domain_row["state"]
    # 複数ドメインの誤検知（×または「自己参照」の指摘）が出ていないこと
    assert "自己参照" not in cross_domain_row["state"]


# ──────────────────────────────────────
# 対応メモ（docs/check-report-notes.md）が cmd_review 経由で保護されること。
#
# review は check-report.md を毎回まっさらに再生成する。
# これまでは指摘への確認・対応を check-report.md 本文に直接書き足すしかなく、
# 再実行のたびに消えていた。対応メモを分離したことで、review を何度実行しても
# check-report.md は更新され続け、対応メモは一切変わらないことをここで固定する。
# ──────────────────────────────────────

def _write_review_fixtures(paths):
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    (paths.data_dir / "phase1.json").write_text(
        '{"property": {"name": "properties/1"}}', encoding="utf-8",
    )


def test_cmd_review_creates_notes_file_on_first_run(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)

    paths = resolve_client_paths("sample-client")
    _write_review_fixtures(paths)

    monkeypatch.setattr(
        "measurement_design.review.diagnoser.diagnose",
        lambda review_data, standards_dir, api_key, data_dir=None: [],
    )
    monkeypatch.setattr(
        "measurement_design.review.renderer.render_check_report",
        lambda *a, **k: "# check report v1\n",
    )

    rc = run_module.cmd_review(_review_args())

    assert rc == 0
    notes_path = paths.docs_dir / "check-report-notes.md"
    assert notes_path.exists()
    assert "再実行しても上書きされません" in notes_path.read_text(encoding="utf-8")


def test_cmd_review_preserves_hand_written_notes_across_reruns(monkeypatch, tmp_path):
    """1回目で対応メモができたあと、人が書き足してから2回目を実行しても書き足しが残る."""
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)

    paths = resolve_client_paths("sample-client")
    _write_review_fixtures(paths)

    monkeypatch.setattr(
        "measurement_design.review.diagnoser.diagnose",
        lambda review_data, standards_dir, api_key, data_dir=None: [],
    )
    monkeypatch.setattr(
        "measurement_design.review.renderer.render_check_report",
        lambda *a, **k: "# check report v1\n",
    )

    rc1 = run_module.cmd_review(_review_args())
    assert rc1 == 0

    notes_path = paths.docs_dir / "check-report-notes.md"
    report_path = paths.docs_dir / "check-report.md"
    assert report_path.read_text(encoding="utf-8") == "# check report v1\n"

    # 人が対応メモに書き足す
    hand_written = notes_path.read_text(encoding="utf-8") + "\n## V-002 について\n- 確認済み\n"
    notes_path.write_text(hand_written, encoding="utf-8")

    # データを取り直して2回目の review（check-report.md の内容が変わる想定）
    monkeypatch.setattr(
        "measurement_design.review.renderer.render_check_report",
        lambda *a, **k: "# check report v2（再取得後）\n",
    )
    rc2 = run_module.cmd_review(_review_args())
    assert rc2 == 0

    # check-report.md はちゃんと新しい内容に更新される
    assert report_path.read_text(encoding="utf-8") == "# check report v2（再取得後）\n"
    # 対応メモの書き足しは消えていない（今回の肝）
    assert notes_path.read_text(encoding="utf-8") == hand_written


def test_cmd_review_archives_previous_check_report_to_past_dir(monkeypatch, tmp_path):
    """規約2: 2回目の review 実行で、1回目の check-report.md が docs/_past/ へ退避されること。

    02・03・06と同じ「上書き前に _past/ へ退避する」を01（Pythonコード生成）にも揃える。
    check-report-notes.md は退避・上書きの対象外（そのまま残る）ことも併せて固定する。
    """
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)

    paths = resolve_client_paths("sample-client")
    _write_review_fixtures(paths)

    monkeypatch.setattr(
        "measurement_design.review.diagnoser.diagnose",
        lambda review_data, standards_dir, api_key, data_dir=None: [],
    )
    monkeypatch.setattr(
        "measurement_design.review.renderer.render_check_report",
        lambda *a, **k: "# check report v1\n",
    )

    rc1 = run_module.cmd_review(_review_args())
    assert rc1 == 0

    report_path = paths.docs_dir / "check-report.md"
    notes_path = paths.docs_dir / "check-report-notes.md"
    past_dir = paths.docs_dir / "_past"

    # 1回目は退避対象が無いので _past/ はまだ作られない
    assert not past_dir.exists()

    # 人がメモに書き足す
    hand_written = notes_path.read_text(encoding="utf-8") + "\n## V-002 について\n- 確認済み\n"
    notes_path.write_text(hand_written, encoding="utf-8")

    monkeypatch.setattr(
        "measurement_design.review.renderer.render_check_report",
        lambda *a, **k: "# check report v2（再取得後）\n",
    )
    rc2 = run_module.cmd_review(_review_args())
    assert rc2 == 0

    # check-report.md は新しい内容
    assert report_path.read_text(encoding="utf-8") == "# check report v2（再取得後）\n"
    # 1回目の内容が _past/ に残っている
    archived = list(past_dir.glob("*_check-report.md"))
    assert len(archived) == 1
    assert archived[0].read_text(encoding="utf-8") == "# check report v1\n"
    # 対応メモは退避も上書きもされていない
    assert notes_path.read_text(encoding="utf-8") == hand_written
    assert not (past_dir / notes_path.name).exists()
    assert not any(p.name.endswith("_check-report-notes.md") for p in past_dir.glob("*"))
