"""site-segments.yaml（分析対象の定義。役割の違うセクションの切り分け）のテスト。

背景: 試用フィードバックで、オウンドメディア（本体サイトと訪問目的が違う）への流入と本体サイトへの
流入を混ぜて見たため「新規のCVRが低すぎる」と誤読された（数字は正しく解釈が間違っている型）。
このファイルはその再発防止のための器（スキーマ・分類・validate）のテスト。

観点:
  - この機能は利用者が事前に定義するものではなく、01/03が実ページ一覧から気づいて提案し、
    確認が取れた結果だけを保存する。未設定（`site_segments` が無い）クライアントが多数派で、
    その場合は警告0件・`classify_page` は常に `None`
  - `schema.match_site_segment`: host_name / path_prefix / content_group は複数キー指定でAND、
    各キー内（リスト）はOR。条件が空のセグメントは絶対に一致しない
  - **既定セグメント（`default: true`）**: どの match にも一致しないページはここに分類される
    （「その他」という3つ目のバケツを作らない設計）。明示的な match に一致するページは
    既定セグメントより優先される。`default: true` が1件も無い場合に限り `None`（「その他」）が
    返り、黙って消えない
  - `schema.validate_site_segments`: segment_id重複・match条件が空・default過不足
    （0件/2件以上）・default と match の同時設定を警告
  - `writeback.save_site_segments`: segment_idでupsertし、既存の他フィールド・他エントリを消さない
"""
from pathlib import Path

import yaml

from context_store.loader import load_context
from context_store.schema import match_site_segment, validate_site_segments
from context_store.writeback import save_site_segments


def _write_profile(client_dir: Path, client_id: str) -> None:
    client_dir.mkdir(parents=True, exist_ok=True)
    (client_dir / "profile.yaml").write_text(
        yaml.safe_dump({"client": {"client_id": client_id, "name": "テスト社"}}, allow_unicode=True),
        encoding="utf-8",
    )


def _write_segments(tmp_path: Path, client_id: str, segments: list) -> Path:
    client_dir = tmp_path / client_id
    _write_profile(client_dir, client_id)
    (client_dir / "site-segments.yaml").write_text(
        yaml.safe_dump({"site_segments": segments}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return tmp_path


# ---- 未設定（機能未使用）が既定であること -----------------------------------

def test_unset_site_segments_no_warning_and_classify_returns_none(tmp_path):
    client_dir = tmp_path / "c1"
    _write_profile(client_dir, "c1")
    ctx = load_context("c1", context_dir=tmp_path)

    assert ctx.site_segments == {}
    assert ctx.validate() == []  # 未設定は既定。警告0件
    assert ctx.classify_page(host_name="example.com", page_path="/media/foo") is None


# ---- schema.match_site_segment ---------------------------------------------

def test_match_by_path_prefix_only():
    segments = [
        {"segment_id": "seg_media", "name": "オウンドメディア", "match": {"path_prefix": "/media/"}},
    ]
    assert match_site_segment(segments, page_path="/media/article-1") == "seg_media"
    assert match_site_segment(segments, page_path="/contact") is None  # 既定セグメントが無いので「その他」


def test_match_by_host_name_only():
    segments = [
        {"segment_id": "seg_media", "name": "メディア", "match": {"host_name": "media.example.com"}},
    ]
    assert match_site_segment(segments, host_name="media.example.com", page_path="/anything") == "seg_media"
    assert match_site_segment(segments, host_name="example.com", page_path="/anything") is None


def test_match_requires_and_when_both_host_and_path_given():
    """host_name と path_prefix を両方指定した場合はAND（両方満たさないと一致しない）。"""
    segments = [
        {
            "segment_id": "seg_media",
            "name": "メディア",
            "match": {"host_name": "example.com", "path_prefix": "/media/"},
        },
    ]
    # 両方満たす -> 一致
    assert match_site_segment(segments, host_name="example.com", page_path="/media/a") == "seg_media"
    # ホストは合うがパスが違う -> 不一致（ORなら一致してしまう）
    assert match_site_segment(segments, host_name="example.com", page_path="/contact") is None
    # パスは合うがホストが違う -> 不一致
    assert match_site_segment(segments, host_name="other.com", page_path="/media/a") is None


def test_match_list_values_are_or_within_key():
    segments = [
        {
            "segment_id": "seg_media",
            "name": "メディア",
            "match": {"path_prefix": ["/media/", "/blog/"]},
        },
    ]
    assert match_site_segment(segments, page_path="/media/a") == "seg_media"
    assert match_site_segment(segments, page_path="/blog/a") == "seg_media"
    assert match_site_segment(segments, page_path="/other/a") is None


def test_match_by_content_group():
    """GA4側でコンテンツグループ設定済みのサイト向け: content_groupで直接分類できる。"""
    segments = [
        {"segment_id": "seg_media", "name": "メディア", "match": {"content_group": "記事/コラム"}},
    ]
    assert match_site_segment(segments, content_group="記事/コラム") == "seg_media"
    assert match_site_segment(segments, content_group="本サイト") is None


def test_match_empty_condition_never_matches():
    """match条件が host_name/path_prefix/content_group のいずれも無い（かつ default でもない）
    セグメントは一致しない（空条件を『すべてに一致』にすると『その他』が消えてしまう事故に
    つながるため安全側に倒す）。
    """
    segments = [{"segment_id": "seg_empty", "name": "空条件", "match": {}}]
    assert match_site_segment(segments, host_name="example.com", page_path="/anything") is None


# ---- 既定セグメント（default: true） -----------------------------------------

def test_unmatched_page_falls_back_to_default_segment():
    """既定セグメントがあるとき、どの match にも一致しないページは既定セグメントに分類される。"""
    segments = [
        {"segment_id": "seg_media", "name": "オウンドメディア", "match": {"path_prefix": "/media/"}},
        {"segment_id": "seg_main", "name": "本体サイト", "default": True},
    ]
    assert match_site_segment(segments, page_path="/media/article-1") == "seg_media"
    # トップ・about・お問い合わせ等、matchに書いていないページは全部 default に落ちる
    assert match_site_segment(segments, page_path="/") == "seg_main"
    assert match_site_segment(segments, page_path="/about") == "seg_main"
    assert match_site_segment(segments, page_path="/contact") == "seg_main"


def test_explicit_match_wins_over_default():
    """明示的な match に一致するページは、既定セグメントではなくそちらに入る（既定は優先されない）。"""
    segments = [
        {"segment_id": "seg_media", "name": "オウンドメディア", "match": {"path_prefix": "/media/"}},
        {"segment_id": "seg_main", "name": "本体サイト", "default": True},
    ]
    assert match_site_segment(segments, page_path="/media/a") == "seg_media"


def test_unmatched_page_returns_none_without_default_segment():
    """既定セグメントが無いときは、従来どおり None（『その他』）が返り、黙って消えない。"""
    segments = [
        {"segment_id": "seg_main", "name": "本体サイト", "match": {"path_prefix": "/service/"}},
        {"segment_id": "seg_media", "name": "メディア", "match": {"path_prefix": "/media/"}},
    ]
    assert match_site_segment(segments, page_path="/recruit/entry") is None


def test_first_default_segment_wins_when_duplicated():
    """default: true が複数あっても match は落ちず、定義順で最初の default を採用する
    （validate_site_segments が別途これを警告する）。"""
    segments = [
        {"segment_id": "seg_a", "name": "A", "default": True},
        {"segment_id": "seg_b", "name": "B", "default": True},
    ]
    assert match_site_segment(segments, page_path="/anything") == "seg_a"


def test_first_match_wins_on_overlap():
    segments = [
        {"segment_id": "seg_a", "name": "A", "match": {"path_prefix": "/media/"}},
        {"segment_id": "seg_b", "name": "B", "match": {"path_prefix": "/media/special/"}},
    ]
    # 定義順で先に一致した方（seg_a）を返す
    assert match_site_segment(segments, page_path="/media/special/x") == "seg_a"


def test_classify_page_via_context_falls_back_to_default(tmp_path):
    base = _write_segments(
        tmp_path,
        "c2",
        [
            {"segment_id": "seg_media", "name": "メディア", "match": {"path_prefix": "/media/"}},
            {"segment_id": "seg_main", "name": "本体サイト", "default": True},
        ],
    )
    ctx = load_context("c2", context_dir=base)
    assert ctx.classify_page(page_path="/media/a") == "seg_media"
    assert ctx.classify_page(page_path="/recruit") == "seg_main"  # どちらのmatchにも当てはまらない=既定


# ---- schema.validate_site_segments ------------------------------------------

def test_validate_no_warning_when_unset():
    assert validate_site_segments([]) == []


def test_validate_warns_duplicate_segment_id():
    segments = [
        {"segment_id": "seg_a", "name": "A", "match": {"path_prefix": "/a/"}},
        {"segment_id": "seg_a", "name": "A2", "match": {"path_prefix": "/a2/"}},
        {"segment_id": "seg_main", "name": "本体サイト", "default": True},
    ]
    warnings = validate_site_segments(segments)
    assert any("重複" in w for w in warnings)


def test_validate_warns_empty_match_condition():
    segments = [
        {"segment_id": "seg_a", "name": "A", "match": {}},
        {"segment_id": "seg_main", "name": "本体サイト", "default": True},
    ]
    warnings = validate_site_segments(segments)
    assert any("match条件" in w and "空です" in w for w in warnings)


def test_validate_warns_no_default_segment():
    """default: true のセグメントが1件も無いと『その他』が黙って残るリスクがあるため警告する。"""
    segments = [
        {"segment_id": "seg_a", "name": "オウンドメディア", "match": {"path_prefix": "/media/"}},
    ]
    warnings = validate_site_segments(segments)
    assert any("default" in w for w in warnings)


def test_validate_warns_multiple_default_segments():
    segments = [
        {"segment_id": "seg_a", "name": "A", "default": True},
        {"segment_id": "seg_b", "name": "B", "default": True},
    ]
    warnings = validate_site_segments(segments)
    assert any("複数" in w for w in warnings)


def test_validate_warns_default_with_match():
    """default: true のセグメントに match も設定されていると、役割が曖昧になるため警告する。"""
    segments = [
        {
            "segment_id": "seg_main",
            "name": "本体サイト",
            "default": True,
            "match": {"path_prefix": "/service/"},
        },
    ]
    warnings = validate_site_segments(segments)
    assert any("default" in w and "match" in w for w in warnings)


def test_validate_no_warning_for_well_formed_segments():
    segments = [
        {
            "segment_id": "seg_media",
            "name": "オウンドメディア",
            "match": {"path_prefix": "/media/"},
        },
        {
            "segment_id": "seg_main",
            "name": "本体サイト",
            "default": True,
        },
    ]
    assert validate_site_segments(segments) == []


# ---- writeback.save_site_segments -------------------------------------------

def test_save_site_segments_creates_new_file(tmp_path):
    client_dir = tmp_path / "c3"
    _write_profile(client_dir, "c3")

    save_site_segments(
        "c3",
        segments=[
            {
                "segment_id": "seg_media",
                "name": "オウンドメディア",
                "description": "集客記事",
                "match": {"path_prefix": "/media/"},
            }
        ],
        context_dir=tmp_path,
    )

    ctx = load_context("c3", context_dir=tmp_path)
    segs = ctx.site_segments["site_segments"]
    assert len(segs) == 1
    assert segs[0]["segment_id"] == "seg_media"
    assert segs[0]["match"]["path_prefix"] == "/media/"


def test_save_site_segments_upserts_by_segment_id_without_touching_others(tmp_path):
    base = _write_segments(
        tmp_path,
        "c4",
        [
            {
                "segment_id": "seg_main",
                "name": "本体サイト",
                "default": True,
            },
        ],
    )

    # 既存の seg_main は触らず、seg_media だけ追加する
    save_site_segments(
        "c4",
        segments=[
            {
                "segment_id": "seg_media",
                "name": "メディア",
                "match": {"path_prefix": "/media/"},
            }
        ],
        context_dir=base,
    )

    ctx = load_context("c4", context_dir=base)
    segs = {s["segment_id"]: s for s in ctx.site_segments["site_segments"]}
    assert set(segs) == {"seg_main", "seg_media"}
    assert segs["seg_main"]["name"] == "本体サイト"  # 既存は維持

    # 既存segment_idを指定した更新は該当フィールドだけ上書きする
    save_site_segments(
        "c4",
        segments=[{"segment_id": "seg_main", "description": "サービス紹介・問い合わせ"}],
        context_dir=base,
    )
    ctx2 = load_context("c4", context_dir=base)
    segs2 = {s["segment_id"]: s for s in ctx2.site_segments["site_segments"]}
    assert segs2["seg_main"]["name"] == "本体サイト"  # 既存フィールドは維持
    assert segs2["seg_main"]["description"] == "サービス紹介・問い合わせ"  # 新規フィールドが追加
