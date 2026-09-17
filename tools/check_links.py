#!/usr/bin/env python3
"""
リポジトリ内の Markdown ファイルにある相対リンク（[text](path) 形式）が
実在するファイル/ディレクトリを指しているかを検査するスクリプト。

使い方:
    python tools/check_links.py

- 走査対象: リポジトリ直下の全 .md ファイル（生成物・依存フォルダは除外）
- 対象リンク: [text](相対パス) 形式のみ（http(s)://, mailto:, #アンカーのみ は対象外）
- パス末尾の #アンカー は無視して存在確認する
- 0件なら exit code 0、1件以上あれば一覧を表示して exit code 1
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXCLUDE_DIRS = {"_build", ".git", "node_modules", ".venv", "outputs"}

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
FENCE_RE = re.compile(r"^ {0,3}(```|~~~)", re.MULTILINE)


def iter_md_files():
    for path in REPO_ROOT.rglob("*.md"):
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        yield path


def strip_code_fences(text: str) -> str:
    """フェンス付きコードブロック（```...```）の中身を同じ行数の空行に置き換える。
    コード内の正規表現・サンプル記法が [text](path) 風に誤検出されるのを防ぐが、
    行番号はそのまま維持する。"""
    lines = text.split("\n")
    out = []
    in_fence = False
    for line in lines:
        if FENCE_RE.match(line):
            in_fence = not in_fence
            out.append("")  # フェンス行自体もリンク対象外
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def is_checkable(link: str) -> bool:
    link = link.strip()
    if not link:
        return False
    if link.startswith(("http://", "https://", "mailto:", "#")):
        return False
    if link.startswith("<") or link.startswith("data:"):
        return False
    return True


def main():
    # Windowsではリダイレクト時に既定エンコーディングがcp932になり日本語出力が
    # 文字化けするため、標準出力/標準エラーをUTF-8に固定する（leak_check.pyと同じ対応）。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    broken = []
    for md_file in iter_md_files():
        text = md_file.read_text(encoding="utf-8", errors="replace")
        scan_text = strip_code_fences(text)
        for match in LINK_RE.finditer(scan_text):
            raw_link = match.group(1).strip()
            if not is_checkable(raw_link):
                continue
            # タイトル付き記法 [text](path "title") に対応
            link = raw_link.split(" ", 1)[0]
            # アンカーを除去
            link_no_anchor = link.split("#", 1)[0]
            if not link_no_anchor:
                continue
            target = (md_file.parent / link_no_anchor).resolve()
            if not target.exists():
                line_no = scan_text[: match.start()].count("\n") + 1
                broken.append((md_file.relative_to(REPO_ROOT), line_no, raw_link))

    if broken:
        print(f"リンク切れ {len(broken)} 件:\n")
        for file, line, link in sorted(broken):
            print(f"  {file}:{line}  {link}")
        sys.exit(1)
    else:
        print("リンク切れ 0件")
        sys.exit(0)


if __name__ == "__main__":
    main()
