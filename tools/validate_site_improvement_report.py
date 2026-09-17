"""個別施策レポートの表構造・件数・ICEを検査する。内容レビューは別途必要。"""
import re
import sys
from pathlib import Path

from report_quality_check import table_following_narratives


def section_body(text, heading):
    match = re.search(r'^##\s+' + re.escape(heading) + r'\s*$', text, re.M)
    if not match:
        return ''
    next_heading = re.search(r'^##\s+', text[match.end():], re.M)
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end():end]


def has_table_header(body, expected):
    return any(
        [cell.strip() for cell in line.strip().strip('|').split('|')] == expected
        for line in body.splitlines()
        if line.lstrip().startswith('|')
    )


def validate(text):
    errors = []
    for heading in ('このレポートで分かること', 'このレポートでわかること', 'すぐ直す運用・計測', 'Search Consoleの扱い'):
        if re.search(r'^##\s+' + re.escape(heading) + r'\s*$', text, re.M):
            errors.append('不要な章: ' + heading)
    tables = []
    for block in re.findall(r'(?:^\|.*\|[ \t]*\n?)+', text, re.M):
        rows = [[c.strip() for c in line.strip().strip('|').split('|')] for line in block.strip().splitlines()]
        if len(rows) >= 2:
            tables.append(rows)
    plans = next((t for t in tables if t[0] == ['対象ページ', '施策概要', '施策詳細', '改善指標']), None)
    if plans is None or len(plans[2:]) < 5:
        errors.append('4列の施策表に5件以上の候補が必要')
    scores = next((t for t in tables if t[0] == ['施策', 'I', 'C', 'E', 'ICE', '採点理由']), None)
    if scores is None:
        errors.append('ICE採点表が必要')
    else:
        if plans and len(scores) != len(plans):
            errors.append('施策と採点の件数が不一致')
        previous = 1001
        for row in scores[2:]:
            try:
                i, c, e, total = map(int, row[1:5])
                if not all(1 <= n <= 10 for n in (i, c, e)) or i*c*e != total:
                    errors.append('ICE計算または範囲が不正: ' + row[0])
                if total > previous:
                    errors.append('ICE降順ではない')
                previous = total
                if len(row) != 6 or not row[5]:
                    errors.append('採点理由が必要')
            except (ValueError, IndexError):
                errors.append('採点行が不正')
    evidence = section_body(text, '根拠と改善箇所')
    if not has_table_header(evidence, ['判断', '根拠', '留意点']):
        errors.append('「根拠と改善箇所」は「判断 | 根拠 | 留意点」の表にする')
    decision = section_body(text, '実施後の判断')
    if not has_table_header(decision, ['確認結果', '判断', '次の対応']):
        errors.append('「実施後の判断」は「確認結果 | 判断 | 次の対応」の表にする')
    for line_no, paragraph in table_following_narratives(text):
        errors.append(
            f'表の後の説明文を表の前へ移す（{line_no}行目）: {paragraph[:60]}'
        )
    return errors


if __name__ == '__main__':
    errors = validate(Path(sys.argv[1]).read_text(encoding='utf-8'))
    print('\n'.join(errors) if errors else 'OK: 施策表・件数・ICE')
    sys.exit(bool(errors))
