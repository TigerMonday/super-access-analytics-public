#!/usr/bin/env python3
"""CVR改善成果物を、内部作業用とクライアント向けに分けて検査する。"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


PREMISE_ROWS = ("計測チェック", "基本分析", "市場・顧客理解")
BARRIER_FALLBACKS = (
    "対応する障壁は見当たらない",
    "障壁は未定義",
    "顧客理解の裏付けなし",
)
STIMULUS_FALLBACKS = (
    "対応する刺激は見当たらない",
    "刺激は未定義",
    "顧客理解の裏付けなし",
)
CLIENT_PROGRESS_PHRASES = (
    "個別ページ改善へ進む前の確認",
    "この全体方針を確認いただいた後",
    "次工程へ進む前に",
)


def validate_text(text: str, *, client_facing: bool = False) -> list[str]:
    errors: list[str] = []
    if client_facing:
        if not re.search(r"<!--\s*pictograms:\s*issue\s*,\s*target\s*,\s*growth\s*-->", text, flags=re.IGNORECASE):
            errors.append("クライアント向け確定版に改善要点のピクトグラム指定がありません")
        if re.search(r"^##\s+使った前提\s*$", text, flags=re.MULTILINE):
            errors.append("クライアント向け確定版に「使った前提」を表示しないでください")
        if re.search(r"(?:barrier|stimulus|persona|stage)_id\s*:", text):
            errors.append("クライアント向け確定版に内部IDを表示しないでください")
        found_progress_phrases = [phrase for phrase in CLIENT_PROGRESS_PHRASES if phrase in text]
        if found_progress_phrases:
            errors.append(
                "クライアント向け確定版に確認待ちの案内を表示しないでください"
                f"（該当: {', '.join(found_progress_phrases)}）。続行確認はチャットで行います"
            )
        first_h2 = re.search(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE)
        if not first_h2 or not re.match(r"(?:結論|要点|改善方針)", first_h2.group(1)):
            errors.append("クライアント向け確定版は結論または改善方針から始めてください")
        return errors

    h2_matches = list(re.finditer(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE))
    if not h2_matches or h2_matches[0].group(1) != "使った前提":
        errors.append("最初のH2見出しが「使った前提」ではありません")

    premise_section = ""
    if h2_matches and h2_matches[0].group(1) == "使った前提":
        end = h2_matches[1].start() if len(h2_matches) > 1 else len(text)
        premise_section = text[h2_matches[0].end() : end]
    for row in PREMISE_ROWS:
        if row not in premise_section:
            errors.append(f"使った前提に「{row}」がありません")

    if "barrier_id:" not in text and not any(x in text for x in BARRIER_FALLBACKS):
        errors.append("barrier_id または『対応する障壁は見当たらない』等の明示がありません")

    if "stimulus_id:" not in text and not any(x in text for x in STIMULUS_FALLBACKS):
        errors.append("stimulus_id または『対応する刺激は見当たらない』等の明示がありません")

    return errors


def validate_file(path: Path, *, client_facing: bool | None = None) -> list[str]:
    if not path.is_file():
        return ["ファイルが見つかりません"]
    if client_facing is None:
        client_facing = path.name == "cvr-improvement-plan.md" and path.parent.name == "05_cvr"
    return validate_text(path.read_text(encoding="utf-8"), client_facing=client_facing)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="検査するMarkdown成果物")
    parser.add_argument(
        "--client-facing", action="store_true",
        help="すべての入力をクライアント向け確定版として検査する",
    )
    args = parser.parse_args()

    failed = False
    for path in args.paths:
        errors = validate_file(path, client_facing=True if args.client_facing else None)
        if errors:
            failed = True
            print(f"NG: {path}")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"OK: {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
