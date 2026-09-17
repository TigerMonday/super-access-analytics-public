"""context_store — スーパーアクセス解析 全エージェント共通のコンテキストストア。

他エージェントからの基本的な使い方:

    from context_store.loader import load_context, list_clients

    ctx = load_context("sample-client")
    print(ctx.summary_markdown())   # プロンプトに差し込める前提情報サマリ
    property_id = ctx.measurement.get("ga4", {}).get("property_id")

分析・レビュー完了時の書き戻し:

    from context_store.writeback import append_finding

    append_finding(
        "sample-client", agent="07_adhoc_analysis", summary="...",
        findings=["..."], outputs=["outputs/sample-client/..."],
    )
"""

from context_store.loader import ClientContext, list_clients, load_context, resolve_client_id
from context_store.writeback import append_finding

__all__ = [
    "ClientContext",
    "load_context",
    "list_clients",
    "resolve_client_id",
    "append_finding",
]
