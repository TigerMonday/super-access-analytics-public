"""Curated report pictograms derived from Material Symbols Rounded.

The bundled SVG files are licensed under Apache License 2.0.  The license text
is kept beside the assets in ``assets/pictograms/LICENSE``.  Only the small set
used by analytical reports is bundled; this is intentionally not a general
icon library.
"""

from __future__ import annotations

import re
from importlib.resources import files


PICTOGRAM_NAMES = frozenset(
    {"analysis", "issue", "insight", "target", "growth", "verified"}
)


def inline_pictogram(name: str) -> str | None:
    """Return a trusted inline SVG for *name*, or ``None`` for unknown names.

    The surrounding card already contains a visible heading and description,
    so the SVG is decorative for assistive technology.  Removing the bundled
    ``title`` also avoids duplicate IDs when an icon is used more than once.
    """
    if name not in PICTOGRAM_NAMES:
        return None
    svg = (
        files("report_export")
        .joinpath("assets", "pictograms", f"{name}.svg")
        .read_text(encoding="utf-8")
    )
    svg = re.sub(r"\s+aria-labelledby=\"[^\"]+\"", "", svg, count=1)
    svg = re.sub(r"<title\b[^>]*>.*?</title>", "", svg, count=1)
    svg = svg.replace('fill="#1F2328"', 'fill="currentColor"', 1)
    return svg.replace(
        "<svg ",
        '<svg class="pictogram-icon" aria-hidden="true" focusable="false" ',
        1,
    )
