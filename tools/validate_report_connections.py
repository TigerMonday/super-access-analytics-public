"""Validate reviewed report provenance. Does not certify semantic correctness."""
import argparse
import hashlib
import json
from pathlib import Path

ROLES = {"market", "basic", "plan", "context"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(root, manifest):
    errors = []
    files = manifest.get("files", {})
    if set(files) != ROLES:
        errors.append("market/basic/plan/context の4参照が必要")
    texts = {}
    for role, item in files.items():
        path = (root / item.get("path", "")).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            errors.append(f"{role}: 参照ファイル不在または範囲外")
            continue
        texts[role] = path.read_text(encoding="utf-8-sig")
        if digest(path) != item.get("sha256"):
            errors.append(f"{role}: 内容が接続確認時から変更。再レビューが必要")
    metrics = manifest.get("metrics", {})
    for role in ("basic", "plan"):
        m = metrics.get(role, {})
        if not all(m.get(k) for k in ("start", "end", "numerator", "denominator")):
            errors.append(f"{role}: 期間・分子・分母の記録不足")
        elif m["start"] > m["end"]:
            errors.append(f"{role}: 期間の前後が逆")
    if not manifest.get("mappings"):
        errors.append("顧客課題→データ→施策の対応が必要")
    for row in manifest.get("mappings", []):
        for role in ("market", "basic", "plan"):
            quote = row.get(role)
            if not quote or quote not in texts.get(role, ""):
                errors.append(f"{role}: 対応箇所が本文に存在しない")
    if not manifest.get("review_note"):
        errors.append("期間・指標差と仮説の扱いのレビュー記録が必要")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        errors = validate(args.root, json.loads(args.manifest.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        errors = [f"接続記録を読めません: {exc}"]
    print("\n".join(errors) if errors else "接続参照・対応箇所: OK（内容の妥当性は別途レビュー）")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
