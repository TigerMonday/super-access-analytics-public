"""必要ID（GA4プロパティ・GTMアカウント/コンテナ・認証）の解決と保存.

「一度聞いたら残す」を実現する。解決の優先順:
  CLIフラグ > `{client}/inputs/*.local.yaml` > 01コンテキストストア > なし

解決できた値は `inputs/*.local.yaml` に保存し、次回以降はフラグ無しで再利用する。
どこにも無ければ呼び出し側でユーザーに尋ねる（このモジュールは「見つからない」を返すだけ）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


def _arg(args, name: str) -> str:
    return (getattr(args, name, "") or "").strip()


def _from_01_context(client_id: str, project_root: Path, context_dir: Path | None = None) -> dict:
    """01 コンテキストストアから property/GTM を best-effort 取得.

    `context_dir` はテスト用のオーバーライド（省略時は 01 コンテキストストアの既定パス）。
    """
    ctx_src = project_root.parent.parent / "01_context_management" / "src"
    if not ctx_src.exists():
        return {}
    try:
        if str(ctx_src) not in sys.path:
            sys.path.insert(0, str(ctx_src))
        from context_store.loader import load_context  # type: ignore

        ctx = load_context(client_id, context_dir=context_dir)
        out: dict = {}
        if getattr(ctx, "ga4_property_id", None):
            out["property_id"] = ctx.ga4_property_id
        meas = getattr(ctx, "measurement", {}) or {}
        gtm = (meas.get("gtm") or {}) if isinstance(meas, dict) else {}
        # measurement.yaml のキー名は gtm_account_id / gtm_container_id
        # （01_context_management/templates/measurement.template.yaml・context-schema.md 準拠）。
        if gtm.get("gtm_account_id"):
            out["gtm_account_id"] = str(gtm["gtm_account_id"])
        if gtm.get("gtm_container_id"):
            out["gtm_container_id"] = str(gtm["gtm_container_id"])
        return out
    except Exception as e:
        print(
            f"[id_resolver] 01コンテキストストアの読み込みに失敗しました（無視して続行）: {e}",
            file=sys.stderr,
        )
        return {}


def resolve_ids(args, client_dir: Path, project_root: Path, *, context_dir: Path | None = None) -> dict:
    """ID を解決して dict で返す（property_id 等。見つからない項目は空文字）.

    `context_dir` はテスト用のオーバーライド（省略時は 01 コンテキストストアの既定パス）。
    """
    from measurement_design.loader import load_ga4_local, load_gtm_local

    inputs_dir = client_dir / "inputs"
    ga4 = load_ga4_local(inputs_dir) or {}
    gtm = load_gtm_local(inputs_dir) or {}
    ctx = _from_01_context(client_dir.name, project_root, context_dir=context_dir)

    def pick(*vals: str) -> str:
        for v in vals:
            if v:
                return str(v)
        return ""

    return {
        "property_id": pick(_arg(args, "property_id"), ga4.get("property_id"), ctx.get("property_id")),
        "auth": pick(_arg(args, "auth"), ga4.get("auth_method"), "sa"),
        "sa_key_path": pick(_arg(args, "sa_key_path"), ga4.get("sa_key_path")),
        "gtm_account": pick(_arg(args, "gtm_account"), gtm.get("gtm_account_id"), ctx.get("gtm_account_id")),
        "gtm_container": pick(_arg(args, "gtm_container"), gtm.get("gtm_container_id"), ctx.get("gtm_container_id")),
        # ID は分かっているが API は叩けない案件がある（GTM の閲覧権限が無い／認証が通らない）。
        # その場合でも ID は記録として残したいので、Phase 3 の実行可否は別のフラグで持つ。
        # 既定は true（未指定なら従来どおり API を叩く）。
        "gtm_api_enabled": gtm.get("api_enabled", True) is not False,
    }


def prompt_gtm_ids(ids: dict) -> dict:
    """GTM ID が未解決なら、実行の最初に尋ねる（対話時のみ）.

    GTM は任意のため、見つからない場合に「分析するか」をユーザーに確認する。
    非対話実行（パイプ/バックグラウンド）では尋ねずにそのまま返す（スキップ）。
    """
    if ids.get("gtm_account") and ids.get("gtm_container"):
        return ids
    if not sys.stdin.isatty():
        return ids  # 非対話: 聞かずにスキップ（GA4のみ）
    print("GTM コンテナも分析しますか？（タグ・トリガー・GTM-GA4 不整合まで確認できます）")
    try:
        acc = input(
            "  GTM アカウントID（不要なら空Enterでスキップ・不明ならクライアント担当に確認）: "
        ).strip()
    except EOFError:
        # 実行環境によっては isatty() が True でも標準入力を受け取れないことがある。
        # 任意機能のGTMが未登録なだけでGA4の計測チェック全体を失敗させない。
        print("\n  → 入力を受け取れない実行環境のため GTM はスキップ（GA4 のみ）")
        return ids
    if not acc:
        print("  → GTM はスキップ（GA4 のみ）")
        return ids
    try:
        con = input("  GTM コンテナID（公開ID GTM-XXXXXXX または数値containerId）: ").strip()
    except EOFError:
        print("\n  → 入力を受け取れない実行環境のため GTM はスキップ（GA4 のみ）")
        return ids
    if not con:
        print("  → コンテナID未入力のため GTM はスキップ")
        return ids
    ids["gtm_account"] = acc
    ids["gtm_container"] = con
    return ids


def persist_ids(client_dir: Path, resolved: dict) -> None:
    """解決した値を inputs/*.local.yaml に保存（次回以降フラグ不要にする）.

    sample-client は配布用サンプルで inputs/*.local.yaml がリポジトリ管理対象のため、
    ここには実データを書き込まない（呼び出し元の run.py cmd_fetch でも同様のガードを
    掛けているが、他の呼び出し元が増えても事故らないよう二重に防ぐ）。
    """
    if client_dir.name == "sample-client":
        print(
            "[警告] sample-client の inputs/*.local.yaml は配布用サンプルのため書き込みをスキップしました。"
            "実データを保存するには別のクライアント名を使ってください。"
        )
        return

    inputs_dir = client_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    if resolved.get("property_id"):
        ga4: dict = {"property_id": resolved["property_id"], "auth_method": resolved.get("auth") or "sa"}
        if resolved.get("sa_key_path"):
            ga4["sa_key_path"] = resolved["sa_key_path"]
        (inputs_dir / "ga4.local.yaml").write_text(
            yaml.safe_dump({"ga4": ga4}, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    if resolved.get("gtm_account") and resolved.get("gtm_container"):
        # 既存ファイルには手で書いた項目（api_enabled・エクスポートの版・経緯のコメント）が
        # 入っていることがある。丸ごと上書きすると消えるので、値が変わるときだけ書き換える。
        from measurement_design.loader import load_gtm_local

        current = load_gtm_local(inputs_dir) or {}
        if (str(current.get("gtm_account_id") or "") == resolved["gtm_account"]
                and str(current.get("gtm_container_id") or "") == resolved["gtm_container"]):
            return
        gtm = dict(current)
        gtm["gtm_account_id"] = resolved["gtm_account"]
        gtm["gtm_container_id"] = resolved["gtm_container"]
        (inputs_dir / "gtm.local.yaml").write_text(
            yaml.safe_dump({"gtm": gtm}, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
