"""計測設計書 章選定モジュール."""

from __future__ import annotations

EC_EVENTS = frozenset([
    "purchase", "refund", "view_item", "view_item_list",
    "add_to_cart", "remove_from_cart", "view_cart",
    "begin_checkout", "add_shipping_info", "add_payment_info",
])


def select_chapters(kpi_breakdowns: list[dict], review_data: dict) -> list[int]:
    """案件特性から含めるべき章番号リストを返す."""
    chapters: set[int] = {1, 2, 3}

    all_event_names: set[str] = set()
    for breakdown in kpi_breakdowns:
        for event in breakdown.get("required_events", []):
            all_event_names.add(event.get("event_name", ""))

    if kpi_breakdowns:
        chapters.add(4)

    if all_event_names:
        chapters.add(6)

    custom_defs = review_data.get("ga4", {}).get("custom_definitions", {})
    if custom_defs.get("dimensions") or custom_defs.get("metrics"):
        chapters.add(7)

    if all_event_names & EC_EVENTS:
        chapters.add(8)

    chapters.update([11, 12, 13])

    return sorted(chapters)
