"""計測設計 CLI — エントリーポイント.

Usage:
    uv run python run.py validate --client {name}
    uv run python run.py fetch --client {name} --property-id {id} [--auth sa|adc|oauth] [--gtm-account X --gtm-container Y]
    uv run python run.py review --client {name} [--no-llm]
    uv run python run.py design --client {name}
    uv run python run.py summarize --client {name}
    uv run python run.py questions --client {name}
    uv run python run.py verify --client {name}
    uv run python run.py doc --client {name}
    uv run python run.py run --client {name} --property-id {id} [options]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Windows + Git Bash等では既定の画面エンコーディングがUTF-8にならず、[OK]等の
# 日本語表示が文字化けすることがある（ファイル自体はUTF-8で正しく書かれている）。
# 明示的にUTF-8へ揃えて防ぐ。reconfigure非対応の環境（一部のリダイレクト等）では
# 何もしない（元の表示に戻るだけで、実行そのものは失敗させない）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# scripts/ を sys.path に追加
sys.path.insert(0, str(Path(__file__).parent / "scripts"))
# src/ を sys.path に追加
sys.path.insert(0, str(Path(__file__).parent / "src"))
# common/report_export_bridge/ を sys.path に追加（01の出力形式設定を読んで成果物MDを
# 変換する橋渡し。01専用ではなく、他のエージェントとも共有する common/ 配下の実装を参照する。
# 詳細は common/report_export_bridge/report_export_bridge.py のモジュールdocstring）。
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "common" / "report_export_bridge"))
# クライアント単位の外部AI承認を01へ保存・確認する。
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "01_context_management" / "src"))

PROJECT_ROOT = Path(__file__).parent


def _check_external_ai_approval(args) -> bool:
    """外部AIは送信先ごとに初回だけ明示承認を要求し、01へ記録する。"""
    backend = getattr(args, "llm_backend", "none") or "none"
    if backend == "none" or getattr(args, "no_llm", False):
        return True
    provider = "anthropic" if backend in {"claude_cli", "anthropic_api", "api"} else backend
    from context_store.loader import load_context
    from context_store.writeback import save_external_ai_approval

    context = load_context(args.client)
    if context.external_ai_approved(provider):
        return True
    if getattr(args, "approve_external_ai", False):
        save_external_ai_approval(args.client, provider)
        print(f"[OK] {provider} への外部AI送信承認をこのクライアントに記録しました。")
        return True
    print(f"[NG] {provider} へのデータ送信が未承認です。")
    print("  送信されるデータと契約条件を説明して利用者の承認を得た後、")
    print("  初回だけ --approve-external-ai を付けて再実行してください。")
    return False


def cmd_validate(args) -> int:
    """入力ファイルの検証."""
    from config import resolve_client_paths
    from measurement_design.loader import load_kpis, load_screen_flow

    try:
        paths = resolve_client_paths(args.client, create=False)
    except ValueError as e:
        print(f"[NG] {e}")
        return 1
    inputs_dir = paths.inputs_dir

    errors: list[str] = []

    if not inputs_dir.exists():
        print(f"[NG] inputs/ ディレクトリが存在しません: {inputs_dir}")
        return 1

    try:
        kpis = load_kpis(inputs_dir)
        print(f"[OK] kpis.yaml: {len(kpis)} 件")
    except FileNotFoundError as e:
        errors.append(str(e))

    try:
        flow = load_screen_flow(inputs_dir)
        print(f"[OK] screen-flow.yaml: pages={len(flow['pages'])}, flows={len(flow['flows'])}")
    except FileNotFoundError as e:
        errors.append(str(e))

    if errors:
        for e in errors:
            print(f"[NG] {e}")
        return 1

    print("\n[OK] 検証完了。問題ありません。")
    return 0


def cmd_fetch(args) -> int:
    """GA4/GTM データ取得 (run_phase.py の phase1, phase2, [phase3] を実行)."""
    from config import AuditConfig, validate_client_id
    import run_phase
    from measurement_design.id_resolver import resolve_ids, persist_ids, prompt_gtm_ids

    try:
        validate_client_id(args.client)
    except ValueError as e:
        print(f"[NG] {e}")
        return 1

    # sample-client は配布用のサンプル（inputs/*.local.yaml がリポジトリ管理対象）。
    # ここで実データを取得すると、実際のプロパティID/GTM IDが persist_ids() で
    # tracked ファイルに書き込まれ、気づかずコミット・公開してしまう恐れがある。
    # 実データで試すときは自分用のクライアント名にコピーしてから実行する。
    if args.client == "sample-client":
        print("[NG] sample-client は配布用のサンプルのため、実データの取得には使えません。")
        print("  inputs/*.local.yaml はこのリポジトリの管理対象で、実際のIDで上書きすると")
        print("  気づかずコミットしてしまう恐れがあるためです。")
        print("  自分用のクライアントフォルダを作ってから実行してください:")
        print("    mkdir -p my-site/inputs && cp sample-client/inputs/*.yaml my-site/inputs/")
        print("    uv run python run.py fetch --client my-site --property-id {GA4プロパティID}")
        return 1

    client_dir = PROJECT_ROOT / args.client
    # ID解決: フラグ → inputs/*.local.yaml → 01コンテキスト の順（一度指定すれば保存し再利用）
    ids = resolve_ids(args, client_dir, PROJECT_ROOT)
    if not ids["property_id"]:
        print("[NG] GA4プロパティIDが見つかりません。")
        print("  --property-id で指定するか、{client}/inputs/ga4.local.yaml に記載してください。")
        print("  （一度指定すれば保存され、次回以降は省略できます。不明な場合はクライアント担当に確認）")
        return 1
    # GTMが未解決なら最初に聞く（対話時のみ。非対話ではスキップ）
    ids = prompt_gtm_ids(ids)
    persist_ids(client_dir, ids)  # 一度聞いたら残す（次回フラグ不要）

    config = AuditConfig(
        property_id=ids["property_id"],
        client_name=args.client,
        gtm_account_id=ids["gtm_account"],
        gtm_container_id=ids["gtm_container"],
        auth_method=ids["auth"],
        oauth_profile=args.oauth_profile or "",
        sa_key_path=ids["sa_key_path"],
    )
    print(f"GA4プロパティID: {ids['property_id']}（解決元: フラグ/ローカル設定/サイトの前提情報）")

    # GTM APIの権限有無とは別に、公開サイト上の実装も証拠として残す。
    # これが無いと、API未設定時に直接設置の gtag.js / UA ID まで
    # 「データが無い」としてしまい、判定できる範囲を捨ててしまう。
    from measurement_design.review.kpi_coverage import load_client_profile

    site_url = (load_client_profile(args.client, PROJECT_ROOT).get("site_url") or "").strip()
    if site_url:
        print("\n=== 公開サイトの計測実装（HTML / 公開GTM） ===")
        try:
            import json
            import gtm_public

            public_impl = gtm_public.inspect_site(site_url)
            public_impl_path = config.data_dir / "09-site-implementation.json"
            public_impl_path.parent.mkdir(parents=True, exist_ok=True)
            public_impl_path.write_text(
                json.dumps(public_impl, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            print(
                f"[OK] GA4 ID {len(public_impl['ga4_measurement_ids'])}件 / "
                f"UA ID {len(public_impl['universal_analytics_ids'])}件 / "
                f"GTM {len(public_impl['gtm_containers'])}件 → {public_impl_path}"
            )
            if public_impl.get("container_errors"):
                print("注意: 一部の公開GTMコンテナは詳細を取得できませんでした。")
        except (OSError, ValueError) as exc:
            # GA4 APIの取得まで失敗扱いにしない。レポートでは「公開実装未取得」
            # として残り、後から再取得できる。
            print(f"注意: 公開サイトの計測実装を取得できませんでした（{type(exc).__name__}）。")
    else:
        print("\nサイトURLが未登録のため、公開サイトの計測実装は未取得です。")

    print("=== Phase 1: GA4 Admin API 取得 ===")
    run_phase.run_phase1(config)

    print("\n=== Phase 2: GA4 Data API 取得 ===")
    run_phase.run_phase2(config)

    print("\n=== 流入パラメータ（source/medium・campaign）===")
    run_phase.run_traffic_detail(config)

    print("\n=== ページ別（コンテンツグルーピング）===")
    run_phase.run_pages(config)

    print("\n=== データ品質（ホスト名・国別）===")
    run_phase.run_data_quality(config)

    if ids["gtm_account"] and ids["gtm_container"] and not ids["gtm_api_enabled"]:
        print("\ninputs/gtm.local.yaml で api_enabled: false が指定されているため Phase 3 をスキップします。")
        print("  GTM の構成は受領したコンテナ エクスポート JSON を scripts/gtm_export.py で解析してください。")
    elif ids["gtm_account"] and ids["gtm_container"]:
        print("\n=== Phase 3: GTM API 取得 ===")
        run_phase.run_phase3(config)
    else:
        print("\nGTM account/container が未指定のため Phase 3 をスキップします。")
        print("  GTM分析するには --gtm-account/--gtm-container を指定（or inputs/gtm.local.yaml に記載）。不明ならクライアント担当に確認。")

    # 旧形式（phase1/2/3.json）に加え、観点別ファイル（01-property.json 等）も
    # 作っておく（dataset.py 経由の health_checks / audit_matrix / questions /
    # summarize / verify が動くようにするため。remove_legacy=False で旧形式も残す）。
    import dataset
    dataset.migrate(config.data_dir)

    print(f"\n[OK] データ取得完了: {config.data_dir}")
    return 0


def cmd_review(args) -> int:
    """チェックレポート生成."""
    from config import resolve_client_paths
    from measurement_design.review.normalizer import build_review_data
    from measurement_design.review.diagnoser import diagnose
    from measurement_design.review.renderer import (
        render_check_report,
        save_check_report,
        archive_check_report_before_overwrite,
        ensure_check_report_notes,
        notes_file_has_legacy_ids,
    )

    try:
        paths = resolve_client_paths(args.client)
    except ValueError as e:
        print(f"[NG] {e}")
        return 1
    # client_dir: inputs/ の置き場所（従来どおり `{measurement_design}/{client}/`）。
    # KPIソーシング（source_kpis）と01コンテキストの client_id 解決に使う。
    client_dir = PROJECT_ROOT / args.client
    data_dir = paths.data_dir
    docs_dir = paths.docs_dir
    standards_dir = PROJECT_ROOT / "standards"
    template_path = PROJECT_ROOT / "templates" / "check-report.template.md"

    backend = getattr(args, "llm_backend", None) or os.environ.get("LLM_BACKEND") or "none"
    if args.no_llm or backend == "none":
        api_key = None
    elif backend == "claude_cli":
        # claude -p 方式はキー不要。下流の `if api_key:` ゲートを通すためダミー値を渡す
        api_key = os.environ.get("ANTHROPIC_API_KEY") or "__claude_cli__"
        print("LLM検出: claude -p（MAXプラン/Teamプラン流用・キー不要）")
    else:  # anthropic_api / api（後方互換）
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("警告: ANTHROPIC_API_KEY が未設定です。機械検出のみ実行します。")

    print("レビューデータを構築中...")
    try:
        review_data = build_review_data(data_dir)
    except FileNotFoundError as e:
        print(f"[NG] {e}")
        print("先に `fetch` コマンドを実行してください。")
        return 1

    print("違反を検出中...")
    # data_dir を渡さないと診断関数内の健全性検出(health_checks)が一度も呼ばれない
    # （実測ベースの18項目チェックが常に0件になる配線漏れがあった）。
    violations = diagnose(review_data, standards_dir, api_key, data_dir)
    print(f"  検出: {len(violations)} 件")

    # §1 KPIと計測イベントの対応: KPIをソース（local→09）し、必要イベントのGA4カバレッジを判定。
    # LLMが無くても埋まるようにする（KPI/01のkey_events自体はGA4実態と直接突合できるため、
    # LLMが要るのは events 未登録のKPIをイベント名に分解する場合だけ）。
    from measurement_design.review.kpi_coverage import (
        source_kpis, check_coverage, default_key_event_rows,
        check_unregistered_outcome_events, check_funnel_completion_rates,
        build_target_comparison, check_key_event_name_mismatches,
    )

    kpis, screen_flow, kpi_source = source_kpis(client_dir, PROJECT_ROOT)
    if kpis:
        print(f"  KPIカバレッジ判定中（{kpi_source}・{len(kpis)}件）...")
        # events（登録済みGA4イベント名）が無いKPIだけLLMで一般的なイベント名を提案する。
        # 登録済みのKPIはそのイベント名で直接突合するため分解不要（check_coverageで優先処理）。
        kpis_needing_breakdown = [k for k in kpis if not k.get("events")]
        breakdowns = []
        if kpis_needing_breakdown and api_key:  # LLM利用可（claude_cliのダミー含む）
            from measurement_design.design.decomposer import decompose_all_kpis

            naming_file = standards_dir / "naming-conventions.md"
            naming_md = naming_file.read_text(encoding="utf-8") if naming_file.exists() else ""
            breakdowns = decompose_all_kpis(kpis_needing_breakdown, screen_flow, naming_md, api_key)
        kpi_rows = check_coverage(breakdowns, kpis, review_data)
    else:
        print("  KPI・キーイベントがサイトの前提情報に登録されていないため、GA4のキーイベント設定を既定の成果として使います")
        kpi_rows = default_key_event_rows(review_data)

    # §1 追加調査: イベント名が分かっているKPI（優先1の登録済みイベント）だけを
    # 「発火しました」で終わらせず、実測から追加で分かることを出す（kpi_id単位の
    # target_value対比は kpi_rows のソースを問わず使えるため常に計算する）。
    kpi_outcome_candidates = check_unregistered_outcome_events(review_data, kpis)
    kpi_completion_issues = check_funnel_completion_rates(review_data)
    kpi_target_comparison = build_target_comparison(kpis, kpi_rows)
    # 0件発火の登録済みキーイベントについて、登録名と実際の送信名が食い違っている
    # だけの疑いが無いかを照合する（「0件発火」までしか伝わっていなかった一番効く
    # 指摘。詳細は kpi_coverage.check_key_event_name_mismatches のdocstring）。
    kpi_name_mismatches = check_key_event_name_mismatches(kpi_rows, review_data)

    # ○△×の網羅チェック（audit_matrix）。判定表は check-report.md 本文に埋め込むため、
    # ここでは計算だけ行い render_check_report に渡す（render_check_report内で violations
    # と突き合わせて、可能な行には指摘IDへの参照も付ける）。
    from measurement_design.review.audit_matrix import audit_matrix

    matrix_rows = audit_matrix(data_dir)

    print("チェックレポートを生成中...")
    from measurement_design.review.kpi_coverage import load_client_profile

    client_profile = load_client_profile(args.client, PROJECT_ROOT)
    content = render_check_report(
        violations,
        review_data,
        template_path,
        args.client,
        kpi_rows=kpi_rows,
        site_url=client_profile.get("site_url"),
        client_display_name=client_profile.get("name"),
        matrix_rows=matrix_rows,
        kpi_outcome_candidates=kpi_outcome_candidates,
        kpi_completion_issues=kpi_completion_issues,
        kpi_target_comparison=kpi_target_comparison,
        kpi_name_mismatches=kpi_name_mismatches,
    )
    # 指摘への確認・対応の書き足しは check-report.md 本体ではなく専用ファイルに書く
    # （check-report.md は毎回まっさらに再生成されるため、本文に書き足すと次回の実行で
    # 消える。無ければ作り、あれば絶対に上書きしない）。
    notes_path, notes_created = ensure_check_report_notes(docs_dir, args.client)
    if notes_created:
        print(f"[OK] 対応メモ（指摘への確認・対応を書く場所。再生成で消えません）: {notes_path}")
    elif notes_file_has_legacy_ids(notes_path):
        # 指摘IDを通し番号から内容ベースの安定した方式に変更した（同じ指摘なら
        # 再実行しても同じIDになる）。既存の対応メモが旧方式のID（3桁の通し番号）を
        # 参照している場合、今回のレポートのIDとは一致しないため対象名で照合する
        # 必要がある。メモの書き換えは行わず、案内だけ出す。
        print(f"[注意] {notes_path} に旧方式の指摘ID（`V-002` 等の3桁の通し番号）への"
              "言及が残っています。今回のレポートのIDとは一致しないため、対象名・"
              "指摘内容で該当箇所を照合してください。")

    # check-report.md（と report_export_bridge が作った .html 等）を上書きする前に、
    # 既存分を docs/_past/ へ退避する（docs/standard-run-order.md 規約2。03・04・05と同じ形）。
    archived = archive_check_report_before_overwrite(docs_dir)
    if archived:
        names = "、".join(p.name for p in archived)
        print(f"[OK] 前回の check-report 一式を退避しました（{docs_dir / '_past'}）: {names}")

    out = save_check_report(content, docs_dir)

    # 01に既定の出力形式（preferences.output_formats）が設定されていれば、check-report を
    # common/report_export で自動変換する（未設定・MDのみなら何もしない）。
    # 変換に失敗してもレポート生成自体は成功扱いにする（report_export_bridge側で例外は握る）。
    from report_export_bridge import export_if_configured

    requested_formats = getattr(args, "output_formats", None)
    if requested_formats is None:
        outcome = export_if_configured([out], args.client)
    else:
        outcome = export_if_configured(
            [out], args.client,
            output_formats=[fmt for fmt in requested_formats if fmt != "md"],
        )
    converted = outcome.generated

    # 「保存完了」「変換済み」を並べて出すだけでは、クライアントに渡すべきはどちらか
    # 伝わらないという指摘を受けた。変換先（HTML等）があればそれを、無ければ
    # check-report.md 自体を「最終成果物」として明示する。対応メモの案内も、
    # 何が起きたかにかかわらず毎回添える（数行に収め、長い説明にはしない）。
    if converted:
        for path in converted:
            print(f"[OK] 閲覧用の最終成果物: {path}")
        print(f"     元データ（Markdown・reviewのたびに上書き）: {out}")
    else:
        print(f"[OK] 閲覧用の最終成果物: {out}")
    # 01に出力形式の設定はあったのに一部/全部書き出せなかった場合、上の分岐と同じ見た目に
    # なって「設定していないのと区別が付かない」ことを避ける。分析（MD）自体は成功している
    # ため失敗扱いにはしないが、何が書き出せなかったかは必ず伝える。
    for warning in outcome.warnings:
        print(f"[注意] {warning}")
    print(f"     社内用の対応メモ（reviewを再実行しても消えません）: {notes_path}")
    return 0


def cmd_design(args) -> int:
    """計測設計書生成."""
    from measurement_design.loader import load_kpis, load_screen_flow
    from measurement_design.review.normalizer import build_review_data
    from measurement_design.design.decomposer import decompose_all_kpis
    from measurement_design.design.standardizer import standardize_events
    from measurement_design.design.selector import select_chapters
    from measurement_design.design.generator import generate_all_chapters
    from config import resolve_client_paths

    try:
        paths = resolve_client_paths(args.client)
    except ValueError as e:
        print(f"[NG] {e}")
        return 1
    inputs_dir = paths.inputs_dir
    data_dir = paths.data_dir
    docs_dir = paths.docs_dir
    design_doc_dir = docs_dir / "design-doc"
    standards_dir = PROJECT_ROOT / "standards"
    templates_dir = PROJECT_ROOT / "templates" / "design-doc"

    backend = getattr(args, "llm_backend", None) or os.environ.get("LLM_BACKEND") or "none"
    if backend == "none":
        # 外部LLMを使わない設定（既定）。これは失敗ではなく正常な分岐で、文章生成の
        # 役割がリポジトリを開いているAIエージェント側に移っただけなので終了コードは0。
        # ただし「AIエージェントに依頼してください」だけでは、依頼された側が
        # 何をどこに書けばいいか分からず堂々巡りになる（design→doc→designの無限ループ）。
        # 章ファイルの置き場所・命名・材料・次の一手までここで明示する。
        print("[案内] 計測設計書はいまお使いのAIエージェントが作成します。")
        print(f"  書き方: 章ファイルを {design_doc_dir} に置く")
        print("    ファイル名・章立ては templates/design-doc/*.template.md と同じにする")
        print("    （例: 01-cover.template.md → 01-cover.md。{{...}}を埋め、先頭の`# 章 NN: ...`見出しは残す）")
        print("    材料: docs/check-report.md、_data/（fetch済みGA4/GTM実測）、")
        print("    inputs/kpis.yaml・screen-flow.yaml、docs/findings.md（あれば最優先の確定所見）")
        print("    どの章を書くかの目安は docs/guide/work-procedure.md ステップ6を参照")
        print(f"  書けたら `run.py doc --client {args.client}` で1枚のHTMLにまとめられます")
        print("  任意: --llm-backend claude_cli または anthropic_api を指定すると、外部LLMで自動生成できます。")
        return 0
    if backend == "claude_cli":
        # claude -p 方式はキー不要。下流の関数へはダミー値を渡す
        api_key = os.environ.get("ANTHROPIC_API_KEY") or "__claude_cli__"
        print("LLM生成: claude -p（MAXプラン/Teamプラン流用・キー不要）")
    else:  # anthropic_api / api（後方互換）
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("[NG] ANTHROPIC_API_KEY が設定されていません。")
            return 1

    print("インプットを読み込み中...")
    try:
        kpis = load_kpis(inputs_dir)
        screen_flow = load_screen_flow(inputs_dir)
    except FileNotFoundError as e:
        print(f"[NG] {e}")
        return 1

    naming_md = ""
    naming_file = standards_dir / "naming-conventions.md"
    if naming_file.exists():
        naming_md = naming_file.read_text(encoding="utf-8")

    reserved_md = ""
    reserved_file = standards_dir / "reserved-words.md"
    if reserved_file.exists():
        reserved_md = reserved_file.read_text(encoding="utf-8")

    print("レビューデータを読み込み中...")
    review_data: dict = {}
    try:
        review_data = build_review_data(data_dir)
    except FileNotFoundError:
        print("警告: _data/ が見つかりません。fetch を先に実行することを推奨します。")
        review_data = {"ga4": {"property": {}, "events_observed": [], "key_events": [], "custom_definitions": {"dimensions": [], "metrics": []}}}

    print("KPI を分解中 (LLM)...")
    kpi_breakdowns = decompose_all_kpis(kpis, screen_flow, naming_md, api_key)

    print("イベント名を標準化中 (LLM)...")
    standardized_events = standardize_events(kpi_breakdowns, review_data, naming_md, reserved_md, api_key)

    # 人が確定させた所見を生成プロンプトの最優先制約として渡す。
    # これが無いと、章生成はデータセットしか見ないため、調査で判明した因果関係を知らず
    # 実測と矛盾する推奨を書く（似たイベント名の取り違え・リネーム方向の逆転など。
    # 実際の案件で `signup`/`sign_up` の取り違えが発生した）。
    from measurement_design.review.findings import load_findings
    findings, findings_source = load_findings(docs_dir)
    if findings:
        print(f"確定所見を読み込みました（{findings_source}・{len(findings)}文字）")
    else:
        print("確定所見が見つかりません（docs/findings.md か check-report.md §0 に置くと精度が上がります）")

    print("章を選定中...")
    chapters = select_chapters(kpi_breakdowns, review_data)
    print(f"  選定章: {chapters}")

    context = {
        "client_name": args.client,
        "kpis": kpis,
        "screen_flow": screen_flow,
        "standardized_events": standardized_events,
        "review_data": review_data,
        "findings": findings,
    }

    print(f"計測設計書を生成中 ({len(chapters)} 章)...")
    saved = generate_all_chapters(chapters, templates_dir, context, api_key, design_doc_dir)
    print(f"\n[OK] 章ファイル生成完了: {len(saved)} 章 → {design_doc_dir}")
    # 章ファイルはまだ1本のレポートになっていない。クライアントへ渡す最終成果物は
    # `doc` コマンドがまとめるHTML（backend==none の案内と同じ次の一手を、LLM生成後にも出す）。
    print(f"     次: run.py doc --client {args.client} で1枚のHTMLにまとめられます（クライアントへ渡す最終成果物はそちら）")
    return 0


def cmd_summarize(args) -> int:
    """phase1〜3 の取得データを人間可読のサマリーレポートにする."""
    from config import AuditConfig
    import summarize as summarize_module

    config = AuditConfig(property_id=getattr(args, "property_id", ""), client_name=args.client)
    try:
        out = summarize_module.generate(config)
    except FileNotFoundError as exc:
        print(f"[NG] {exc}")
        return 1
    # summary.md は fetch した生データを人が読める形にした作業用の一時ビュー
    # （成果物としての現状記述は design-doc が担う）。クライアントへは出さないため、
    # 「[OK] 完了」だけの表示だと最終成果物に見えてしまう指摘を受け、社内用と明示する。
    print(f"[OK] 社内用の取得データサマリー（クライアントには出さない・作業用の一時ビュー）: {out}")
    return 0


def cmd_questions(args) -> int:
    """確認事項の骨組みを _data/ から生成し、人が書き込む questions.md を用意する."""
    from config import AuditConfig
    import questions as questions_module

    config = AuditConfig(property_id=getattr(args, "property_id", ""), client_name=args.client)
    try:
        draft_out = questions_module.generate(config)
    except FileNotFoundError as exc:
        print(f"[NG] {exc}")
        return 1
    # questions.draft.md は検出できた事実と数値だけの骨組みで、questions を再実行する
    # たびに毎回まるごと作り直される（社内用・クライアントには出さない）。
    # 書き込む先は questions.md（review の check-report.md に対する
    # check-report-notes.md と同じ作法。無ければ今回作る。あれば絶対に上書きしない）。
    print(f"[OK] 社内用の確認事項の骨組み（毎回作り直される・クライアントには出さない）: {draft_out}")
    questions_out, created = questions_module.ensure_questions_file(draft_out.parent, draft_out, args.client)
    if created:
        print(f"[OK] 確認事項（ここに書き込む。再実行しても上書きされません）: {questions_out}")
    else:
        print(f"[OK] 確認事項（既存。上書きしていません）: {questions_out}")
    print("  「なぜ確認が必要か」を書いて仕上げ、クライアントへの確認事項としてください")
    return 0


def cmd_doc(args) -> int:
    """計測設計書（章 01〜16）を1枚のHTMLにする。"""
    from config import AuditConfig
    import build_design_doc_html

    config = AuditConfig(property_id=getattr(args, "property_id", ""), client_name=args.client)
    try:
        out = build_design_doc_html.build(config, client_label=getattr(args, "label", "") or "")
    except FileNotFoundError as exc:
        print(f"[NG] {exc}")
        return 1
    print(f"[OK] 閲覧用の最終成果物（計測設計書HTML）: {out}")
    return 0


def cmd_verify(args) -> int:
    """成果物 Markdown/HTML 中の数値を _data/ の実データと突合する."""
    from config import AuditConfig
    import verify_numbers

    config = AuditConfig(property_id=getattr(args, "property_id", ""), client_name=args.client)
    try:
        findings = verify_numbers.verify(config)
    except FileNotFoundError as exc:
        print(f"[NG] {exc}")
        return 1
    verify_numbers.report(findings)
    return 1 if any(f.severity == "mismatch" for f in findings) else 0


def cmd_run(args) -> int:
    """fetch + review + design + summarize を一括実行."""
    rc = cmd_fetch(args)
    if rc != 0:
        return rc
    rc = cmd_review(args)
    if rc != 0:
        return rc
    backend = getattr(args, "llm_backend", None) or os.environ.get("LLM_BACKEND") or "none"
    if backend == "none":
        print("[OK] 外部LLMを呼ばず、データ取得と機械診断まで完了しました。")
        print("     計測設計書は現在利用中のAIエージェントへ依頼してください。")
        return 0
    rc = cmd_design(args)
    if rc != 0:
        return rc
    # 取得データのレポート化は成果物の根拠になるため一括実行に含める
    return cmd_summarize(args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="計測設計 CLI")
    sub = parser.add_subparsers(dest="command")

    # validate
    p_val = sub.add_parser("validate", help="インプットファイルの検証")
    p_val.add_argument("--client", required=True, help="クライアント名")

    # fetch
    p_fetch = sub.add_parser("fetch", help="GA4/GTMデータ取得")
    p_fetch.add_argument("--client", required=True)
    p_fetch.add_argument("--property-id", default="", help="GA4プロパティID（省略時は inputs/ga4.local.yaml / 01コンテキストから解決）")
    p_fetch.add_argument("--auth", default="sa", choices=["sa", "adc", "oauth"])
    p_fetch.add_argument("--oauth-profile", default="")
    p_fetch.add_argument("--sa-key-path", default="")
    p_fetch.add_argument("--gtm-account", default="")
    p_fetch.add_argument("--gtm-container", default="")

    _LLM_BACKEND_HELP = "外部LLM（任意）: none=呼ばない（既定） / claude_cli / anthropic_api"

    # review
    p_review = sub.add_parser("review", help="チェックレポート生成")
    p_review.add_argument("--client", required=True)
    p_review.add_argument("--output-formats", nargs="+", choices=["md", "html", "pdf", "docx", "xlsx", "gdoc", "gsheet"], help="今回のチェックレポート出力形式。md単独で自動変換なし。省略時は保存済み設定")
    p_review.add_argument("--no-llm", action="store_true", help="LLM診断をスキップ (機械検出のみ)")
    p_review.add_argument("--llm-backend", default="none", choices=["none", "claude_cli", "anthropic_api", "api"], help=_LLM_BACKEND_HELP)
    p_review.add_argument("--approve-external-ai", action="store_true", help="このクライアントの外部AI送信を初回承認として記録")

    # design
    p_design = sub.add_parser("design", help="計測設計書生成")
    p_design.add_argument("--client", required=True)
    p_design.add_argument("--llm-backend", default="none", choices=["none", "claude_cli", "anthropic_api", "api"], help=_LLM_BACKEND_HELP)
    p_design.add_argument("--approve-external-ai", action="store_true", help="このクライアントの外部AI送信を初回承認として記録")

    # summarize
    p_sum = sub.add_parser("summarize", help="取得データ(phase1〜3)のサマリーレポート生成")
    p_sum.add_argument("--client", required=True)

    # questions
    p_q = sub.add_parser("questions", help="確認事項の骨組みを生成（docs/questions.draft.md）")
    p_q.add_argument("--client", required=True)

    # verify
    p_verify = sub.add_parser("verify", help="成果物中の数値を _data/ の実データと突合")
    p_verify.add_argument("--client", required=True)

    # doc
    p_doc = sub.add_parser("doc", help="計測設計書（章01〜16）を1枚のHTMLにする")
    p_doc.add_argument("--client", required=True)
    p_doc.add_argument("--label", default="", help="見出しに出すクライアント表記（既定は client_id）")

    # run (all)
    p_run = sub.add_parser("run", help="fetch + review + design + summarize を一括実行")
    p_run.add_argument("--client", required=True)
    p_run.add_argument("--output-formats", nargs="+", choices=["md", "html", "pdf", "docx", "xlsx", "gdoc", "gsheet"], help="今回のチェックレポート出力形式。md単独で自動変換なし。省略時は保存済み設定")
    p_run.add_argument("--property-id", default="", help="GA4プロパティID（省略時は inputs/ga4.local.yaml / 01コンテキストから解決）")
    p_run.add_argument("--auth", default="sa", choices=["sa", "adc", "oauth"])
    p_run.add_argument("--oauth-profile", default="")
    p_run.add_argument("--sa-key-path", default="")
    p_run.add_argument("--gtm-account", default="")
    p_run.add_argument("--gtm-container", default="")
    p_run.add_argument("--no-llm", action="store_true")
    p_run.add_argument("--llm-backend", default="none", choices=["none", "claude_cli", "anthropic_api", "api"], help=_LLM_BACKEND_HELP)
    p_run.add_argument("--approve-external-ai", action="store_true", help="このクライアントの外部AI送信を初回承認として記録")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    # LLMバックエンドを環境変数に反映（llm_client が参照）
    if getattr(args, "llm_backend", None):
        os.environ["LLM_BACKEND"] = args.llm_backend
    if not _check_external_ai_approval(args):
        return 1

    commands = {
        "validate": cmd_validate,
        "fetch": cmd_fetch,
        "review": cmd_review,
        "design": cmd_design,
        "summarize": cmd_summarize,
        "questions": cmd_questions,
        "verify": cmd_verify,
        "doc": cmd_doc,
        "run": cmd_run,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
