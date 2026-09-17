"""questions.py のユニットテスト（確認事項の骨組み生成）.

この骨組みはクライアントに出す `questions.md` の元になる。**誤った指摘を出さないこと**が
いちばん大事なので、データが足りないときの振る舞いを重点的に固定する。
"""
import json

import pytest


def _write(data_dir, filename, data):
    (data_dir / filename).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def case(tmp_path, monkeypatch):
    """`_data/` と `docs/` を tmp に用意し、client_id の解決を差し替える."""
    import config

    data_dir = tmp_path / "_data"
    docs_dir = tmp_path / "docs"
    data_dir.mkdir()
    docs_dir.mkdir()
    paths = config.ClientPaths(
        inputs_dir=tmp_path / "inputs",
        output_dir=tmp_path,
        data_dir=data_dir,
        docs_dir=docs_dir,
        report_dir=tmp_path / "report",
    )
    monkeypatch.setattr(config, "resolve_client_paths", lambda client_id, **kw: paths)
    return paths


def _config():
    from config import AuditConfig
    return AuditConfig(property_id="123456789", client_name="test-client-123456789")


# ── generate のガード ──────────────────────────────────


def test_generate_requires_events_dataset(case):
    import questions

    with pytest.raises(FileNotFoundError, match="02-events.json が見つかりません"):
        questions.generate(_config())


def test_generate_requires_firing_data(case):
    """phase1（設定）だけでも 02-events.json は key_events で埋まる.

    そのまま生成すると「登録済みキーイベントが全部発火0」という誤った指摘になる。
    """
    import questions

    _write(case.data_dir, "01-property.json", {"property": {"display_name": "テスト"}})
    _write(case.data_dir, "02-events.json", {"key_events": [{"event_name": "cv_reserve"}]})

    with pytest.raises(FileNotFoundError, match="events_30d"):
        questions.generate(_config())


def test_generate_writes_draft_without_touching_questions_md(case):
    """人が書いた questions.md を機械が上書きしない（generate() 自体は draft しか書かない）."""
    import questions

    written_by_hand = case.docs_dir / "questions.md"
    written_by_hand.write_text("人が書いた確認事項", encoding="utf-8")
    _write(
        case.data_dir,
        "02-events.json",
        {
            "key_events": [{"event_name": "cv_reserve"}],
            "key_event_firing": [{"eventName": "cv_reserve", "eventCount": "1162"}],
            "events_30d": [{"eventName": "cv_reserve", "eventCount": "1162"}],
        },
    )

    out = questions.generate(_config())

    assert out.name == "questions.draft.md"
    assert out.exists()
    assert written_by_hand.read_text(encoding="utf-8") == "人が書いた確認事項"


# ── ensure_questions_file（本体：questions.md は無ければ作る・あれば上書きしない） ──


def test_ensure_questions_file_creates_from_draft_when_missing(case):
    """questions.md が無ければ draft の骨組みを複製して作る."""
    import questions

    _write(
        case.data_dir,
        "02-events.json",
        {
            "key_events": [{"event_name": "cv_reserve"}],
            "key_event_firing": [{"eventName": "cv_reserve", "eventCount": "0"}],
            "events_30d": [{"eventName": "cv_reserve", "eventCount": "1162"}],
        },
    )
    draft_path = questions.generate(_config())

    out, created = questions.ensure_questions_file(case.docs_dir, draft_path, "test-client")

    assert created is True
    assert out.name == "questions.md"
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    # draft 専用の断り書き（「クライアントに出さない」「骨組み」というタイトル）は
    # questions.md には引き継がない。
    assert "クライアントに出さない" not in text
    assert "確認事項（骨組み）" not in text
    # 上書きされない案内と、骨組み本体（検出済みの表）は引き継ぐ。
    assert "上書きされません" in text
    assert "cv_reserve" in text


def test_ensure_questions_file_never_overwrites_existing(case):
    """questions.md に人が書き込んだ内容は、再実行しても残る（これが本体）."""
    import questions

    _write(
        case.data_dir,
        "02-events.json",
        {
            "key_events": [{"event_name": "cv_reserve"}],
            "key_event_firing": [{"eventName": "cv_reserve", "eventCount": "0"}],
            "events_30d": [{"eventName": "cv_reserve", "eventCount": "1162"}],
        },
    )
    draft_path = questions.generate(_config())

    written_by_hand = case.docs_dir / "questions.md"
    written_by_hand.write_text("人が書き込んだ内容", encoding="utf-8")

    out, created = questions.ensure_questions_file(case.docs_dir, draft_path, "test-client")

    assert created is False
    assert out.read_text(encoding="utf-8") == "人が書き込んだ内容"


# ── A 節の組み立て ────────────────────────────────────


def test_section_a_emits_heading_when_only_a2():
    """A-1 が空でも節見出しを出す（小見出しが宙に浮かないようにする）."""
    from questions import _section_a

    events = {
        "key_events": [{"event_name": "cv_inquiry"}],
        "key_event_firing": [],
        "events_30d": [{"eventName": "page_view", "eventCount": "10000"}],
    }
    out = _section_a(events)

    assert out[0] == "## A. 成果の定義"
    assert any("### A-2." in line for line in out)
    assert not any("### A-1." in line for line in out)


def test_section_a_emits_single_heading_with_both_subsections():
    from questions import _section_a

    events = {
        "key_events": [{"event_name": "cv_inquiry"}],
        "key_event_firing": [],
        "events_30d": [
            {"eventName": "line_cv_reserve_dl", "eventCount": "754"},
            {"eventName": "cv_inquiry", "eventCount": "0"},
        ],
    }
    out = _section_a(events)

    assert out.count("## A. 成果の定義") == 1
    assert any("### A-1." in line for line in out)
    assert any("### A-2." in line for line in out)


def test_section_a_empty_without_findings():
    from questions import _section_a
    assert _section_a({"events_30d": [], "key_events": [], "key_event_firing": []}) == []


# ── A-2（発火0のキーイベント） ────────────────────────


def test_zero_key_events_does_not_fabricate_zeros():
    """発火実績が無いときに「全部0件」と書かない."""
    from questions import _zero_key_events

    out = "\n".join(_zero_key_events({"key_events": [{"event_name": "cv_reserve"}]}))

    assert "判定不能" in out
    assert "key_event_firing" in out
    assert "| `cv_reserve` | 0 |" not in out


def test_zero_key_events_lists_only_zero_fire():
    from questions import _zero_key_events

    events = {
        "key_events": [{"event_name": "cv_reserve"}, {"event_name": "cv_inquiry"}],
        "key_event_firing": [{"eventName": "cv_reserve", "eventCount": "1162"}],
    }
    out = "\n".join(_zero_key_events(events))

    assert "cv_inquiry" in out
    assert "cv_reserve" not in out


def test_zero_key_events_empty_without_registered_key_events():
    from questions import _zero_key_events
    assert _zero_key_events({"key_events": [], "key_event_firing": []}) == []


def test_zero_key_events_excludes_purchase():
    """purchase はどのプロパティにも既定で入るため確認事項にしない（セクションごと出さない）."""
    from questions import _zero_key_events

    events = {
        "key_events": [{"event_name": "purchase"}],
        "key_event_firing": [{"eventName": "purchase", "eventCount": "0"}],
    }
    assert _zero_key_events(events) == []


def test_zero_key_events_excludes_purchase_but_keeps_other_dead_events():
    from questions import _zero_key_events

    events = {
        "key_events": [{"event_name": "purchase"}, {"event_name": "cv_inquiry"}],
        "key_event_firing": [{"eventName": "purchase", "eventCount": "0"}],
    }
    out = "\n".join(_zero_key_events(events))

    assert "cv_inquiry" in out
    assert "purchase" not in out


# ── A-1（成果候補） ──────────────────────────────────


def test_outcome_candidates_excludes_engagement_events():
    """回遊系を除かないと、発火数順で成果候補が下に沈んで論点にならない."""
    from questions import _outcome_candidates

    events = {
        "key_events": [],
        "events_30d": [
            {"eventName": "scroll_page", "eventCount": "50000"},
            {"eventName": "line_cv_reserve_dl", "eventCount": "754"},
        ],
    }
    out = "\n".join(_outcome_candidates(events))

    assert "line_cv_reserve_dl" in out
    assert "scroll_page" not in out


def test_outcome_candidates_excludes_registered_key_events():
    from questions import _outcome_candidates

    events = {
        "key_events": [{"event_name": "cv_reserve"}],
        "events_30d": [{"eventName": "cv_reserve", "eventCount": "1162"}],
    }
    assert _outcome_candidates(events) == []


# ── C 節（UTM） ──────────────────────────────────────


def test_section_c_emits_heading_when_only_c2():
    """Unassigned が無く独自 medium だけの案件でも節見出しを出す."""
    from questions import _section_c

    traffic = {
        "channel_performance": [{"sessionDefaultChannelGroup": "Organic Search", "sessions": "100"}],
        "source_medium": [{"sessionSource": "meta", "sessionMedium": "goldenhour", "sessions": "16154"}],
    }
    out = _section_c(traffic)

    assert out[0] == "## C. 流入パラメータ（UTM）"
    assert any("### C-2." in line for line in out)
    assert not any("### C-1." in line for line in out)


def test_section_c_emits_single_heading_with_both_subsections():
    from questions import _section_c

    traffic = {
        "channel_performance": [
            {"sessionDefaultChannelGroup": "Unassigned", "sessions": "20827"},
            {"sessionDefaultChannelGroup": "Organic Search", "sessions": "231148"},
        ],
        "source_medium": [{"sessionSource": "meta", "sessionMedium": "goldenhour", "sessions": "16154"}],
    }
    out = _section_c(traffic)

    assert out.count("## C. 流入パラメータ（UTM）") == 1
    assert any("### C-1." in line for line in out)
    assert any("### C-2." in line for line in out)


def test_custom_mediums_reports_unfetched_utm_data():
    """UTM 別の実値が未取得なら、黙って空にせず未取得であることを出す.

    黙って何も出さないと「独自 medium は無かった」と読まれる。取得の接続は P-4741。
    """
    from questions import _custom_mediums, _section_c

    out = "\n".join(_custom_mediums({"channel_performance": []}))
    assert "### C-2." in out
    assert "未取得" in out

    # 節見出しも付く（C-1 が無くても宙に浮かない）
    assert _section_c({"channel_performance": []})[0] == "## C. 流入パラメータ（UTM）"


def test_section_c_empty_when_fetched_and_all_standard():
    """取得済みで独自 medium が無い場合は、論点が無いので何も出さない."""
    from questions import _section_c
    traffic = {
        "channel_performance": [{"sessionDefaultChannelGroup": "Organic Search", "sessions": "100"}],
        "source_medium": [{"sessionSource": "google", "sessionMedium": "organic", "sessions": "100"}],
    }
    assert _section_c(traffic) == []


# ── D 節（命名規則） ──────────────────────────────────


def test_naming_excludes_japanese_and_uppercase_only():
    """日本語（対象外）と大文字・ハイフンだけの表記（low）は質問せず、highだけ拾う。"""
    from questions import _naming

    events = {"events_30d": [
        {"eventName": "資料請求", "eventCount": "100"},
        {"eventName": "click_CTA", "eventCount": "50"},
        {"eventName": "contact_curious-about_form", "eventCount": "5"},
        {"eventName": "contact form", "eventCount": "3"},
    ]}
    out = "\n".join(_naming(events))

    assert "contact form" in out
    assert "contact_curious-about_form" not in out
    assert "資料請求" not in out
    assert "click_CTA" not in out


def test_naming_heading_reflects_ga4_spec_violation_not_all_naming_rules():
    """見出しは3分類（仕様外/大文字/日本語）と整合させる。表に載るのは仕様外だけなので、
    「命名規則違反」という広い言い方ではなく、仕様外だと分かる文言にする。
    """
    from questions import _naming

    events = {"events_30d": [{"eventName": "contact form", "eventCount": "5"}]}
    out = "\n".join(_naming(events))

    assert "## D. 命名規則" not in out
    assert "命名規則違反" not in out
    assert "GA4の仕様に合わない" in out or "仕様外" in out


def test_custom_mediums_ignores_standard_values():
    from questions import _custom_mediums

    traffic = {"source_medium": [
        {"sessionSource": "google", "sessionMedium": "cpc", "sessions": "1000"},
        {"sessionSource": "meta", "sessionMedium": "goldenhour", "sessions": "500"},
    ]}
    out = "\n".join(_custom_mediums(traffic))

    assert "goldenhour" in out
    assert "cpc" not in out
