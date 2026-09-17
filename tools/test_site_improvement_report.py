from validate_site_improvement_report import validate


def fixture():
    return ('## 改善施策\n\n| 対象ページ | 施策概要 | 施策詳細 | 改善指標 |\n|---|---|---|---|\n'
            + '| / | 案 | 変更 | 率 |\n'*5
            + '\n## 優先順位（ICE）\n\n| 施策 | I | C | E | ICE | 採点理由 |\n|---|---|---|---|---|---|\n'
            + '| 案 | 5 | 5 | 5 | 125 | 根拠 |\n'*5
            + '\n## 根拠と改善箇所\n\n| 判断 | 根拠 | 留意点 |\n|---|---|---|\n| 案 | 数値 | 制約 |\n'
            + '\n## 実施後の判断\n\n| 確認結果 | 判断 | 次の対応 |\n|---|---|---|\n| 増加 | 継続 | 展開 |\n')


def test_valid():
    assert validate(fixture()) == []


def test_wrong_score():
    assert validate(fixture().replace('125', '126'))


def test_missing_plan():
    assert validate(fixture().replace('| / | 案 | 変更 | 率 |\n', '', 1))


def test_internal_heading():
    assert validate(fixture() + '\n## Search Consoleの扱い\n')


def test_missing_evidence_table():
    assert validate(fixture().replace('| 判断 | 根拠 | 留意点 |', '| 判断 | 説明 | 注意 |'))


def test_missing_decision_table():
    assert validate(fixture().replace('| 確認結果 | 判断 | 次の対応 |', '| 結果 | 判断 | 対応 |'))


def test_narrative_must_precede_table():
    text = fixture().replace(
        '\n## 優先順位（ICE）',
        '\nこの結論は表の前に置く必要があります。\n\n## 優先順位（ICE）',
    )
    assert any('表の後の説明文を表の前へ移す' in error for error in validate(text))
