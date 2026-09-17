"""customer-understanding.yaml（3C・ペルソナ・態度変容ジャーニー）のテスト。

観点:
  - loader: customer-understanding.yaml を読み込み、ClientContext.customer_understanding に
    格納する。summary_markdown() に created_date とペルソナ名・分岐理由が出る
  - schema.validate_customer_understanding: 根拠の無い刺激を「根拠あり」のふりで書いていないか、
    journey が5段階固定順になっているか、created_date・distinguishing_factor の欠落を検出する
  - writeback.save_customer_understanding: 全体を丸ごと置き換える（部分マージしない）
"""
from pathlib import Path

import pytest
import yaml

from context_store.loader import load_context
from context_store.schema import JOURNEY_STAGE_IDS, PERSONA_MAX, validate_customer_understanding
from context_store.writeback import save_customer_understanding


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _minimal_journey(persona_id: str) -> list[dict]:
    """5段階固定順の最小journeyを組み立てるヘルパー。"""
    out = []
    for stage_id in JOURNEY_STAGE_IDS:
        out.append(
            {
                "stage_id": stage_id,
                "stage_name": stage_id,
                "situation": "状況",
                "awareness_state": "認識状態",
                "barriers": [
                    {
                        "barrier_id": f"{persona_id}_{stage_id}_b1",
                        "description": "障壁",
                        "evidence_type": "hypothesis",
                        "evidence": None,
                    }
                ],
                "stimuli": [
                    {
                        "stimulus_id": f"{persona_id}_{stage_id}_s1",
                        "description": "刺激仮説",
                        "evidence_type": "hypothesis",
                        "evidence": None,
                    }
                ],
            }
        )
    return out


# ---- loader -----------------------------------------------------------------

def test_loader_reads_customer_understanding_into_summary(tmp_path):
    client_dir = tmp_path / "c1"
    client_dir.mkdir()
    (client_dir / "profile.yaml").write_text(
        yaml.safe_dump({"client": {"client_id": "c1", "name": "テスト社"}}, allow_unicode=True),
        encoding="utf-8",
    )
    (client_dir / "customer-understanding.yaml").write_text(
        yaml.safe_dump(
            {
                "created_date": "2026-08-30",
                "source_report": "outputs/c1/03_research/x/00_3c_persona_journey_report.md",
                "three_c": {"customer": {"summary": "顧客像"}},
                "personas": [
                    {
                        "persona_id": "persona_001",
                        "name": "現場担当者",
                        "distinguishing_factor": "決裁権が無い",
                        "journey": _minimal_journey("persona_001"),
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    ctx = load_context("c1", context_dir=tmp_path)
    assert ctx.customer_understanding["created_date"] == "2026-08-30"

    md = ctx.summary_markdown()
    assert "作成日: 2026-08-30" in md
    assert "現場担当者" in md
    assert "決裁権が無い" in md


def test_loader_no_customer_understanding_section_when_file_absent(tmp_path):
    client_dir = tmp_path / "c2"
    client_dir.mkdir()
    (client_dir / "profile.yaml").write_text(
        yaml.safe_dump({"client": {"client_id": "c2", "name": "テスト社"}}, allow_unicode=True),
        encoding="utf-8",
    )

    ctx = load_context("c2", context_dir=tmp_path)
    assert ctx.customer_understanding == {}
    assert "3C・ペルソナ" not in ctx.summary_markdown()


# ---- schema.validate_customer_understanding ---------------------------------

def test_validate_warns_missing_created_date():
    warnings = validate_customer_understanding({"personas": []})
    assert any("created_date" in w for w in warnings)


def test_validate_warns_missing_distinguishing_factor_when_multiple_personas():
    cu = {
        "created_date": "2026-08-30",
        "personas": [
            {"persona_id": "persona_001", "journey": _minimal_journey("persona_001")},
            {"persona_id": "persona_002", "journey": _minimal_journey("persona_002")},
        ],
    }
    warnings = validate_customer_understanding(cu)
    assert any("distinguishing_factor" in w and "persona_001" in w for w in warnings)
    assert any("distinguishing_factor" in w and "persona_002" in w for w in warnings)


def test_validate_no_warning_for_single_persona_without_distinguishing_factor():
    """ペルソナが1人なら分ける理由の説明は不要（フローが同じなら1人にまとめてよい）。"""
    cu = {
        "created_date": "2026-08-30",
        "personas": [{"persona_id": "persona_001", "journey": _minimal_journey("persona_001")}],
    }
    warnings = validate_customer_understanding(cu)
    assert not any("distinguishing_factor" in w for w in warnings)


def test_validate_warns_journey_not_five_fixed_stages():
    cu = {
        "created_date": "2026-08-30",
        "personas": [
            {
                "persona_id": "persona_001",
                "journey": [{"stage_id": "research"}],
            }
        ],
    }
    warnings = validate_customer_understanding(cu)
    assert any("5段階固定順" in w for w in warnings)


def test_validate_warns_evidence_type_missing_or_invalid():
    journey = _minimal_journey("persona_001")
    journey[0]["stimuli"][0]["evidence_type"] = "たぶん"
    cu = {
        "created_date": "2026-08-30",
        "personas": [{"persona_id": "persona_001", "persona_basis": "service_derived", "journey": journey}],
    }
    warnings = validate_customer_understanding(cu)
    assert any(
        "evidence_type が ('customer_voice', 'competitor_customer_voice', 'service_derived', "
        "'desk_research', 'hypothesis') のいずれでもありません" in w
        for w in warnings
    )


def test_validate_warns_evidence_claimed_but_empty():
    """根拠が無い刺激を『根拠あり』のふりで書いていないかの検出（今回の指示で厳しくする観点）。"""
    journey = _minimal_journey("persona_001")
    journey[0]["stimuli"][0]["evidence_type"] = "customer_voice"
    journey[0]["stimuli"][0]["evidence"] = ""
    cu = {
        "created_date": "2026-08-30",
        "personas": [{"persona_id": "persona_001", "persona_basis": "service_derived", "journey": journey}],
    }
    warnings = validate_customer_understanding(cu)
    assert any("evidence（根拠）が空です" in w for w in warnings)


def test_validate_accepts_service_derived_evidence_type():
    """evidence_type の3値目（サービスからの逆算）が evidence あり・無しで正しく扱われる。"""
    journey = _minimal_journey("persona_001")
    journey[0]["stimuli"][0]["evidence_type"] = "service_derived"
    journey[0]["stimuli"][0]["evidence"] = "01_desk_research.md 自社サービスページの記載"
    cu = {
        "created_date": "2026-08-30",
        "personas": [{"persona_id": "persona_001", "persona_basis": "service_derived", "journey": journey}],
    }
    assert validate_customer_understanding(cu) == []


def test_validate_warns_barrier_evidence_type_missing_or_empty():
    """barriers も stimuli と同じ evidence_type チェックを受ける（06が『障壁・刺激』双方を前提にしているため）。"""
    journey = _minimal_journey("persona_001")
    journey[0]["barriers"][0]["evidence_type"] = "customer_voice"
    journey[0]["barriers"][0]["evidence"] = ""
    cu = {
        "created_date": "2026-08-30",
        "personas": [{"persona_id": "persona_001", "persona_basis": "service_derived", "journey": journey}],
    }
    warnings = validate_customer_understanding(cu)
    assert any("障壁" in w and "evidence（根拠）が空です" in w for w in warnings)


def test_validate_warns_persona_basis_missing_or_invalid():
    journey = _minimal_journey("persona_001")
    cu = {
        "created_date": "2026-08-30",
        "personas": [{"persona_id": "persona_001", "journey": journey}],
    }
    warnings = validate_customer_understanding(cu)
    assert any("persona_basis" in w and "persona_001" in w for w in warnings)


def test_validate_warns_too_many_personas():
    """personas が上限（5人）を超えたら、切り捨てず統合を促す警告を出す。"""
    personas = [
        {
            "persona_id": f"persona_{i:03d}",
            "persona_basis": "service_derived",
            "distinguishing_factor": "違い",
            "journey": _minimal_journey(f"persona_{i:03d}"),
        }
        for i in range(PERSONA_MAX + 1)
    ]
    cu = {"created_date": "2026-08-30", "personas": personas}
    warnings = validate_customer_understanding(cu)
    assert any(f"{PERSONA_MAX}人を超えています" in w and "統合" in w for w in warnings)


def test_validate_no_warning_at_persona_max():
    """上限（5人）ちょうどなら警告しない。"""
    personas = [
        {
            "persona_id": f"persona_{i:03d}",
            "persona_basis": "service_derived",
            "distinguishing_factor": "違い",
            "journey": _minimal_journey(f"persona_{i:03d}"),
        }
        for i in range(PERSONA_MAX)
    ]
    cu = {"created_date": "2026-08-30", "personas": personas}
    warnings = validate_customer_understanding(cu)
    assert not any("を超えています" in w for w in warnings)


def test_validate_accepts_competitor_customer_voice_evidence_type():
    """competitor_customer_voice（競合事例で顧客層の実在は確認できるが、自社を選ぶかは未確認）が
    evidence あり・無しで正しく扱われる。"""
    journey = _minimal_journey("persona_001")
    journey[0]["barriers"][0]["evidence_type"] = "competitor_customer_voice"
    journey[0]["barriers"][0]["evidence"] = "05_case_study.md 競合A社の導入事例インタビュー"
    cu = {
        "created_date": "2026-08-30",
        "personas": [
            {
                "persona_id": "persona_001",
                "persona_basis": "competitor_customer_voice_confirmed",
                "journey": journey,
            }
        ],
    }
    assert validate_customer_understanding(cu) == []


def test_validate_warns_competitor_customer_voice_evidence_empty():
    journey = _minimal_journey("persona_001")
    journey[0]["barriers"][0]["evidence_type"] = "competitor_customer_voice"
    journey[0]["barriers"][0]["evidence"] = ""
    cu = {
        "created_date": "2026-08-30",
        "personas": [
            {
                "persona_id": "persona_001",
                "persona_basis": "competitor_customer_voice_confirmed",
                "journey": journey,
            }
        ],
    }
    warnings = validate_customer_understanding(cu)
    assert any("障壁" in w and "evidence（根拠）が空です" in w for w in warnings)


def test_validate_accepts_desk_research_evidence_type():
    """desk_research（第三者を調べて確認した客観的事実。不在の確認も含む）が
    evidence あり・無しで正しく扱われる。"""
    journey = _minimal_journey("persona_001")
    journey[0]["barriers"][0]["evidence_type"] = "desk_research"
    journey[0]["barriers"][0]["evidence"] = "02_review_research.md「ITreviewのレビュー0件、Q&Aサイトでの言及0件」"
    cu = {
        "created_date": "2026-08-30",
        "personas": [{"persona_id": "persona_001", "persona_basis": "service_derived", "journey": journey}],
    }
    assert validate_customer_understanding(cu) == []


def test_validate_warns_desk_research_evidence_empty():
    journey = _minimal_journey("persona_001")
    journey[0]["barriers"][0]["evidence_type"] = "desk_research"
    journey[0]["barriers"][0]["evidence"] = ""
    cu = {
        "created_date": "2026-08-30",
        "personas": [{"persona_id": "persona_001", "persona_basis": "service_derived", "journey": journey}],
    }
    warnings = validate_customer_understanding(cu)
    assert any("障壁" in w and "evidence（根拠）が空です" in w for w in warnings)


def test_validate_rejects_desk_research_as_persona_basis():
    """desk_research はペルソナの実在を主張する経路（persona_basis）には無い。
    journey内のevidence_typeとしてのみ有効（あくまで既存ペルソナの障壁・刺激の裏付け）。"""
    journey = _minimal_journey("persona_001")
    cu = {
        "created_date": "2026-08-30",
        "personas": [{"persona_id": "persona_001", "persona_basis": "desk_research", "journey": journey}],
    }
    warnings = validate_customer_understanding(cu)
    assert any("persona_basis" in w and "persona_001" in w for w in warnings)


def test_validate_accepts_competitor_customer_voice_confirmed_persona_basis():
    journey = _minimal_journey("persona_001")
    cu = {
        "created_date": "2026-08-30",
        "personas": [
            {
                "persona_id": "persona_001",
                "persona_basis": "competitor_customer_voice_confirmed",
                "journey": journey,
            }
        ],
    }
    warnings = validate_customer_understanding(cu)
    assert not any("persona_basis" in w for w in warnings)


def test_validate_stage_name_can_be_customized_without_warning():
    """stage_id は固定5値だが、stage_name は自由記述（最終段階を01のCV実態に合わせて改名できる）。"""
    journey = _minimal_journey("persona_001")
    journey[-1]["stage_name"] = "相談"  # purchase の既定「購入」から差し替え
    cu = {
        "created_date": "2026-08-30",
        "personas": [{"persona_id": "persona_001", "persona_basis": "service_derived", "journey": journey}],
    }
    warnings = validate_customer_understanding(cu)
    assert not any("5段階固定順" in w for w in warnings)


def test_validate_no_warning_when_well_formed():
    journey = _minimal_journey("persona_001")
    journey[0]["stimuli"][0]["evidence_type"] = "customer_voice"
    journey[0]["stimuli"][0]["evidence"] = "02_review_research.md の引用"
    cu = {
        "created_date": "2026-08-30",
        "personas": [
            {
                "persona_id": "persona_001",
                "persona_basis": "customer_voice_confirmed",
                "journey": journey,
            }
        ],
    }
    assert validate_customer_understanding(cu) == []


# ---- writeback.save_customer_understanding -----------------------------------

def test_save_customer_understanding_writes_file(tmp_path):
    path = save_customer_understanding(
        "c3",
        three_c={"customer": {"summary": "顧客像", "evidence": "02_review_research.md"}},
        personas=[
            {
                "persona_id": "persona_001",
                "persona_basis": "customer_voice_confirmed",
                "name": "現場担当者",
                "journey": _minimal_journey("persona_001"),
            }
        ],
        source_report="outputs/c3/03_research/x/00_3c_persona_journey_report.md",
        created_date="2026-08-30",
        context_dir=tmp_path,
    )

    assert path == tmp_path / "c3" / "customer-understanding.yaml"
    data = _read_yaml(path)
    assert data["created_date"] == "2026-08-30"
    assert data["three_c"]["customer"]["summary"] == "顧客像"
    assert len(data["personas"]) == 1


def test_save_customer_understanding_defaults_created_date_to_today():
    import datetime

    path_dir_data = {}

    def _run(tmp_path):
        return save_customer_understanding(
            "c4",
            three_c={},
            personas=[],
            context_dir=tmp_path,
        )

    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = _run(Path(d))
        data = _read_yaml(path)
        assert data["created_date"] == datetime.date.today().isoformat()


def test_save_customer_understanding_rejects_incomplete_persona_by_default(tmp_path):
    with pytest.raises(ValueError, match="barrier_id"):
        save_customer_understanding(
            "incomplete",
            three_c={},
            personas=[{"persona_id": "persona_001", "journey": _minimal_journey("persona_001")}],
            context_dir=tmp_path,
        )

    assert not (tmp_path / "incomplete" / "customer-understanding.yaml").exists()


def test_save_customer_understanding_allows_explicit_draft(tmp_path):
    path = save_customer_understanding(
        "draft",
        three_c={},
        personas=[{"persona_id": "persona_001", "journey": _minimal_journey("persona_001")}],
        allow_incomplete=True,
        context_dir=tmp_path,
    )

    assert path.is_file()


def test_save_customer_understanding_overwrites_wholesale_not_merge(tmp_path):
    """他のsave_*と違い、2回目の呼び出しは1回目のpersonasを引き継がない（丸ごと置き換え）。"""
    save_customer_understanding(
        "c5",
        three_c={"customer": {"summary": "旧"}},
        personas=[{
            "persona_id": "persona_old",
            "persona_basis": "service_derived",
            "journey": _minimal_journey("persona_old"),
        }],
        context_dir=tmp_path,
    )
    path = save_customer_understanding(
        "c5",
        three_c={"customer": {"summary": "新"}},
        personas=[{
            "persona_id": "persona_new",
            "persona_basis": "service_derived",
            "journey": _minimal_journey("persona_new"),
        }],
        context_dir=tmp_path,
    )

    data = _read_yaml(path)
    persona_ids = [p["persona_id"] for p in data["personas"]]
    assert persona_ids == ["persona_new"]
    assert data["three_c"]["customer"]["summary"] == "新"
