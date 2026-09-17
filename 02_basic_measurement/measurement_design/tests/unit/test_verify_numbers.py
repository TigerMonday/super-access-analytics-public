"""verify_numbers.py のユニットテスト.

「実データと食い違う数値」と「他案件名の混入」を確実に検出し、
正しい記載・無関係な数値では誤検知しないことを検証する。
"""
import json

import pytest

import config as config_module
import verify_numbers
from config import AuditConfig

PHASE1 = {
    "property": {"name": "properties/123456789", "parent": "accounts/999"},
    "key_events": [{"event_name": "cv_reserve"}, {"event_name": "purchase"}],
    "custom_dimensions": [{"parameter_name": f"d{i}"} for i in range(31)],
    "audiences": [],
}
PHASE2 = {
    "events_30d": [
        {"eventName": "cv_reserve", "eventCount": "1162", "totalUsers": "1100"},
        {"eventName": "purchase", "eventCount": "47", "totalUsers": "47"},
        {"eventName": "scroll_page", "eventCount": "214497", "totalUsers": "90000"},
    ],
    "key_event_firing": [
        {"eventName": "cv_reserve", "eventCount": "1162"},
        {"eventName": "purchase", "eventCount": "47"},
    ],
    "channel_performance": [
        {"sessionDefaultChannelGroup": "Organic Search", "sessions": "231148", "conversions": "575"},
        {"sessionDefaultChannelGroup": "Paid Search", "sessions": "40532", "conversions": "242"},
    ],
}
PHASE3 = {
    "tags": [{"name": f"t{i}", "type": "gaawe"} for i in range(210)],
    "triggers": [{"name": f"g{i}"} for i in range(250)],
    "variables": [{"name": f"v{i}"} for i in range(42)],
}


def _seed_case(config: AuditConfig):
    """案件（outputs/{client}/02_measurement/）に突合の真値となる `_data/` を用意する。"""
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.docs_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in (("phase1.json", PHASE1), ("phase2.json", PHASE2), ("phase3.json", PHASE3)):
        (config.data_dir / name).write_text(json.dumps(payload), encoding="utf-8")


def _patch_roots(monkeypatch, tmp_path):
    """config.py / verify_numbers.py の REPO_ROOT・PROJECT_ROOT をテスト用の tmp_path に差し替える."""
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(verify_numbers, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(verify_numbers, "PROJECT_ROOT", tmp_path / "measurement_design")


@pytest.fixture
def case(monkeypatch, tmp_path):
    """outputs/acme-123456789/02_measurement/ に _data と docs を用意した案件を作る。

    他案件名の混入検出テストも兼ねるため、別案件の出力フォルダ（othercorp）も
    無害な形で1つ用意しておく（他のテストの markdown には現れないので影響しない）。
    """
    _patch_roots(monkeypatch, tmp_path)

    config = AuditConfig(property_id="123456789", client_name="acme-123456789")
    _seed_case(config)
    (tmp_path / "outputs" / "othercorp").mkdir(parents=True)

    def run(markdown: str):
        (config.docs_dir / "report.md").write_text(markdown, encoding="utf-8")
        return verify_numbers.verify(config)

    return run


def test_detects_stale_event_count(case):
    """前回実行の古い発火数が残っているケースを検出する."""
    findings = case("| `cv_reserve` | 1,096 | 予約完了 |\n")

    assert len(findings) == 1
    assert "cv_reserve" in findings[0].label
    assert findings[0].expected == "1,162"
    assert findings[0].found == "1,096"


def test_accepts_correct_event_count(case):
    assert case("| `cv_reserve` | 1,162 | 予約完了 |\n") == []


def test_detects_stale_gtm_counts(case):
    findings = case("GTMタグは 205 本ある。\n")

    assert len(findings) == 1
    assert findings[0].label == "GTMタグ"
    assert findings[0].expected == "210"


def test_detects_other_client_name_leak(case):
    """テンプレート由来で他案件のクライアント名が残っているケースを検出する.

    実際の事故はテンプレート冒頭の引用行（`> ... サンプル ... シート相当。`）で
    起きたため、注記行でも検出できることを確認する。
    """
    findings = case("> othercorp サンプル「表紙」シート相当。\n")

    assert len(findings) == 1
    assert "othercorp" in findings[0].label


def test_own_client_name_with_hyphen_is_not_self_flagged(monkeypatch, tmp_path):
    """client_id 自体にハイフンを含む場合、末尾を数字サフィックスと誤認して
    自分自身を除外リストから漏らし、常に「他案件名の混入」として誤検知していたバグ。

    旧実装は `client_name.rsplit("-", 1)[0]` で無条件に末尾を切り落としていたため、
    "my-site" が "my" になり、除外漏れした "my-site" 自身が混入として検出されていた。
    """
    _patch_roots(monkeypatch, tmp_path)
    config = AuditConfig(property_id="123456789", client_name="my-site")
    _seed_case(config)
    (tmp_path / "outputs" / "othercorp").mkdir(parents=True)

    (config.docs_dir / "report.md").write_text("my-site の計測状況をまとめる。\n", encoding="utf-8")

    findings = verify_numbers.verify(config)

    assert findings == []


@pytest.mark.parametrize(
    ("client_name", "expected"),
    [
        ("my-site", "my-site"),               # ハイフン入りIDは数字サフィックスが無ければ切り落とさない
        ("acme-123456789", "acme"),            # 数字サフィックスは切り落とす
        ("north-star-12345", "north-star"),    # ベース名にハイフンがあっても末尾の数字だけ落とす
        ("othercorp", "othercorp"),            # ハイフンが無ければそのまま
    ],
)
def test_own_client_base_name(client_name, expected):
    assert verify_numbers._own_client_base_name(client_name) == expected


def test_ignores_breakdown_lines(case):
    """合計ラベルの行に内訳が並ぶだけなら不一致にしない（和が真値と一致）."""
    total = 575 + 242  # チャネル別 conversions 合計 = 817
    assert total == 817
    assert case("- キーイベント合計（当期）: cv_reserve 1,162 / purchase 47\n") == []


def test_ignores_unrelated_numbers(case):
    """日付・パーセント・IDなど無関係な数値では誤検知しない."""
    md = (
        "取得期間は 2026-06-17 から 2026-07-16。\n"
        "エンゲージ率は 58.7% だった。\n"
        "測定ID は G-NVBCH967V3。\n"  # leak-ok: 合成の測定ID（実在の識別子ではない）
    )
    assert case(md) == []


def test_ignores_quote_and_comment_lines(case):
    """注記（>）とコメント（<!--）は突合対象外."""
    assert case("> `cv_reserve` は 1,096 件（旧実行の値・参考）\n") == []


def test_ignores_distant_numbers_on_same_line(case):
    """1行に複数の指標が並ぶ散文で、対象名から遠い数値を結びつけない.

    実例: 「約11,800セッションが集中し …『hp_reserve_form』が 312→1,214」の行で、
    hp_reserve_form の真値(11,128)に近い 11,800 を誤検知していた。
    """
    md = (
        "- 7/14 19〜20時の2時間に約11,800セッションが集中し、`line_friend_updated` が +10,330。"
        "**`scroll_page`（スクロール）が 312→1,214 と約4倍**\n"
    )
    assert case(md) == []


def test_still_detects_adjacent_stale_number(case):
    """近接判定を入れても、名前の直後にある古い値は検出する."""
    findings = case("| `scroll_page` | 198,000 | スクロール |\n")

    assert len(findings) == 1
    assert findings[0].expected == "214,497"


def test_ignores_page_level_subtotal(case):
    """ページ別の内訳は全体の一部なので不一致にしない."""
    md = "| 自社Webフォーム | `cv_reserve`（`/reserve/thanks.php`） | 1,134 |\n"
    assert case(md) == []


def test_detects_subtotal_exceeding_total(case):
    """部分集合が全体を超えていたら誤りとして検出する."""
    findings = case("| `cv_reserve`（`/reserve/thanks.php`） | 1,400 |\n")

    assert len(findings) == 1
    assert findings[0].expected == "1,162"


def test_ignores_sibling_event_count_on_same_line(case):
    """同じ行の別イベントの実測値と一致する数値は、その別イベントの値なので誤りにしない."""
    md = "| `purchase` | 47件 | `cv_reserve`（1,162）とは別導線 |\n"
    assert case(md) == []


def test_keeps_truth_even_when_sibling_has_same_count(case):
    """別イベントと同数でも、真値そのものは除外しない（正しい記載は通す）."""
    md = "| `scroll_page` | 214,497 | `cv_reserve` 1,162 と併記 |\n"
    assert case(md) == []


def test_ignores_sum_of_named_events(case):
    """行内で名前が挙がっているイベントの合計値は不一致にしない."""
    md = "| `transaction_id` | `purchase`、`cv_reserve` | 1,209 |\n"
    assert case(md) == []


def test_other_client_names_still_detected(monkeypatch, tmp_path):
    """クライアント名（数字でない）の混入はこれまでどおり検出する."""
    _patch_roots(monkeypatch, tmp_path)
    config = AuditConfig(property_id="123456789", client_name="acme-123456789")
    _seed_case(config)
    (tmp_path / "outputs" / "sample-client").mkdir(parents=True)

    (config.docs_dir / "report.md").write_text(
        "sample-client のテンプレートが残っている。\n", encoding="utf-8"
    )
    findings = verify_numbers.verify(config)

    assert len(findings) == 1
    assert "sample-client" in findings[0].label


def test_verifies_html_report_source(monkeypatch, tmp_path):
    """納品レポートの原稿（report/*.src.html）も突合対象にする.

    `*.md` しか見ていないと、HTML化した原稿では「verify は通ったが数値は
    誰も突合していない」状態になる。
    """
    _patch_roots(monkeypatch, tmp_path)
    config = AuditConfig(property_id="123456789", client_name="acme-123456789")
    _seed_case(config)
    config.report_dir.mkdir(parents=True, exist_ok=True)
    (config.report_dir / "configuration_check.src.html").write_text(
        "<tr><td><code>cv_reserve</code></td><td>1,096</td></tr>\n", encoding="utf-8"
    )

    findings = verify_numbers.verify(config)

    assert [f.found for f in findings] == ["1,096"]
    assert findings[0].file.endswith("configuration_check.src.html")


def test_ignores_built_html_report(monkeypatch, tmp_path):
    """ビルド後の HTML（*.src.html 以外）は見ない（埋め込んだ CSS の数値で誤検知する）."""
    _patch_roots(monkeypatch, tmp_path)
    config = AuditConfig(property_id="123456789", client_name="acme-123456789")
    _seed_case(config)
    config.report_dir.mkdir(parents=True, exist_ok=True)
    (config.report_dir / "configuration_check.html").write_text(
        "<tr><td><code>cv_reserve</code></td><td>1,096</td></tr>\n", encoding="utf-8"
    )

    assert verify_numbers.verify(config) == []


def test_verifies_multiline_html_table_row(monkeypatch, tmp_path):
    """セルを改行して書いた表でも突合する.

    近接判定は行単位なので、`<tr>` を畳まないと「名前の行」と「数値の行」が
    別になり、**0件で合格するが何も比べていない**状態になる。
    """
    _patch_roots(monkeypatch, tmp_path)
    config = AuditConfig(property_id="123456789", client_name="acme-123456789")
    _seed_case(config)
    config.report_dir.mkdir(parents=True, exist_ok=True)
    (config.report_dir / "configuration_check.src.html").write_text(
        "<table>\n"
        "  <tr>\n"
        "    <td><code>cv_reserve</code></td>\n"
        "    <td>1,096</td>\n"
        "  </tr>\n"
        "</table>\n",
        encoding="utf-8",
    )

    findings = verify_numbers.verify(config)

    assert [f.found for f in findings] == ["1,096"]
    # 行番号は畳む前のまま（<tr> が始まった行）
    assert findings[0].line_no == 2


def test_collapse_table_rows_keeps_line_count():
    """畳んでも行数は変えない（所見の行番号がずれる）."""
    text = "<tr>\n<td>a</td>\n</tr>\n<p>x</p>\n"
    out = verify_numbers._collapse_table_rows(text)

    assert len(out.split("\n")) == len(text.split("\n"))
    assert out.split("\n")[0] == "<tr> <td>a</td> </tr>"
    assert out.split("\n")[3] == "<p>x</p>"


def test_ignores_multiline_html_comment(monkeypatch, tmp_path):
    """複数行の HTML コメントの中は突合しない（画面に出ないもので落とさない）."""
    _patch_roots(monkeypatch, tmp_path)
    config = AuditConfig(property_id="123456789", client_name="acme-123456789")
    _seed_case(config)
    config.report_dir.mkdir(parents=True, exist_ok=True)
    (config.report_dir / "configuration_check.src.html").write_text(
        "<!--\n"
        "作業メモ: 前回の実行では `cv_reserve` は 1,096 件だった\n"
        "-->\n"
        "<tr><td><code>cv_reserve</code></td><td>1,162</td></tr>\n",
        encoding="utf-8",
    )

    assert verify_numbers.verify(config) == []


def test_blank_html_comments_keeps_line_count():
    text = "<p>a</p>\n<!--\nx\n-->\n<p>b</p>\n"
    out = verify_numbers._blank_html_comments(text)

    assert len(out.split("\n")) == len(text.split("\n"))
    assert out.split("\n")[0] == "<p>a</p>"
    assert out.split("\n")[4] == "<p>b</p>"
    assert "x" not in out


JP_PHASE2 = {
    "events_30d": [
        {"eventName": "資料請求", "eventCount": "172", "totalUsers": "170"},
        {"eventName": "来場予約", "eventCount": "134", "totalUsers": "130"},
        {"eventName": "10%", "eventCount": "197208", "totalUsers": "90000"},
    ],
    "key_event_firing": [
        {"eventName": "資料請求", "eventCount": "172"},
        {"eventName": "来場予約", "eventCount": "134"},
    ],
    "channel_performance": [],
}


@pytest.fixture
def jp_case(monkeypatch, tmp_path):
    """日本語のイベント名を持つ案件（GA4 は日本語名でも通ってしまう）."""
    _patch_roots(monkeypatch, tmp_path)
    config = AuditConfig(property_id="123456789", client_name="acme-123456789")
    _seed_case(config)
    (config.data_dir / "phase2.json").write_text(
        json.dumps(JP_PHASE2, ensure_ascii=False), encoding="utf-8"
    )
    config.report_dir.mkdir(parents=True, exist_ok=True)

    def run(html: str):
        (config.report_dir / "configuration_check.src.html").write_text(
            html, encoding="utf-8"
        )
        return verify_numbers.verify(config)

    return run


def test_detects_stale_japanese_event_count(jp_case):
    """日本語のイベント名でも突合する.

    以前は英数字の名前しか拾っていなかったため、**日本語名のキーイベントは
    1件も比べられていなかった**（0件で合格するが何も見ていない）。
    """
    findings = jp_case("<tr><td><code>資料請求</code></td><td>150</td></tr>\n")

    assert [f.found for f in findings] == ["150"]
    assert "資料請求" in findings[0].label
    assert findings[0].expected == "172"


def test_accepts_correct_japanese_event_count(jp_case):
    assert jp_case("<tr><td><code>資料請求</code></td><td>172</td></tr>\n") == []


def test_ignores_backticked_non_event_strings(jp_case):
    """イベント名でない囲み（URL・ファイル名）は対象にしない."""
    assert jp_case(
        "<p><code>/request/complete</code> への到達は 1,234 回</p>\n"
    ) == []


def test_ignores_reference_numbers(jp_case):
    """`#135` のような参照番号は発火数として数えない（GTM のタグ番号）."""
    assert jp_case(
        "<p><code>来場予約</code> は GA4 イベントタグ（#135）で送信している</p>\n"
    ) == []


def test_still_detects_count_next_to_reference(jp_case):
    """参照番号を無視しても、本物の数値は拾う."""
    findings = jp_case("<p><code>来場予約</code>（#135）は 150 件</p>\n")

    assert [f.found for f in findings] == ["150"]


def test_html_row_with_url_still_detects_stale_count(jp_case):
    """HTML の表で、同じ行にURLがあっても古い数値を見逃さない.

    表の1行には「イベント名・件数・条件のURL」が別のセルとして並ぶ。URLがあるだけで
    「内訳」と見なすと、**真値より小さい古い数値がそのまま通る**。
    """
    findings = jp_case(
        "<tr><td><code>資料請求</code></td><td>150件</td>"
        "<td><code>/request/complete</code> 到達</td></tr>\n"
    )

    assert [f.found for f in findings] == ["150"]


def test_markdown_page_breakdown_still_allowed(case):
    """Markdown のページ別内訳は従来どおり許す（真値を超えたときだけ誤り）."""
    assert case("| `cv_reserve`（`/reserve/thanks.php`）| 1,134 |\n") == []


def test_html_row_word_hint_still_scopes(jp_case):
    """HTML でも「うち」などの語があれば内訳として扱う."""
    assert jp_case(
        "<tr><td><code>資料請求</code></td><td>うち 150件 は特設ページ経由</td></tr>\n"
    ) == []


def test_html_prose_page_breakdown_still_allowed(jp_case):
    """HTML の本文に書いたページ別内訳は、Markdown と同じく内訳として扱う.

    表の行だけ URL を手がかりから外す（表は条件セルが同居するため）。
    """
    assert jp_case(
        "<p><code>資料請求</code>（<code>/request/complete</code>）150件</p>\n"
    ) == []


def test_html_table_row_with_url_is_not_scoped(jp_case):
    """表の行では URL があっても内訳扱いにしない（古い数値を見逃さない）."""
    findings = jp_case(
        "<tr><td><code>資料請求</code></td><td>150件</td>"
        "<td><code>/request/complete</code></td></tr>\n"
    )

    assert [f.found for f in findings] == ["150"]
