# -*- coding: utf-8 -*-
"""tools/leak_check.py の検査対象絞り込み（Git連携）のテスト。

公開前チェックの検査対象を「実際に公開されるファイル」（Git管理下＋未追跡の
新規ファイル）に絞る変更に対するテスト。狙いは3つ。

  1. Git管理下のファイルと、追跡されていないが .gitignore で無視もされていない
     新規ファイルが検査対象に「入る」こと（絞りすぎて見逃さない）
  2. .gitignore されたファイルが検査対象から「外れる」こと（本来の目的）
  3. Gitが使えない（リポジトリでない等）場合は、辞書欠落と同じ exit 2 にはせず、
     安全側（全件検査）にフォールバックし、その旨を報告すること
"""

from __future__ import annotations

import subprocess
import base64
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import leak_check  # noqa: E402


def test_embedded_image_requires_unchanged_content_approval(tmp_path, denylist_path):
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    payload = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100).decode()
    markup = f'<img src="data:image/png;base64,{payload}">\n'
    doc = root / "sample.html"
    doc.write_text(markup, encoding="utf-8")
    report = leak_check.run(root, denylist_path)
    assert report.embedded_binary
    assert leak_check.print_report(report, root) == 1
    (root / "tools").mkdir()
    manifest = root / "tools" / "public-binary-manifest.sha256"
    manifest.write_text(hashlib.sha256(markup.encode()).hexdigest() + "  sample.html\n", encoding="utf-8")
    report = leak_check.run(root, denylist_path)
    assert report.approved_embedded
    assert not report.embedded_binary
    assert leak_check.print_report(report, root) == 0
    doc.write_text(markup + "changed\n", encoding="utf-8")
    report = leak_check.run(root, denylist_path)
    assert report.embedded_binary
    assert leak_check.print_report(report, root) == 1


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _init_repo(root: Path):
    """user.name/email の設定に依存しない最小限のGitリポジトリを作る。

    git add はコミットと違い identity 設定を要らないため、検査対象の絞り込みは
    add まででテストできる（グローバルなgit configには触れない）。
    """
    _git(["init"], cwd=root)


@pytest.fixture
def denylist_path(tmp_path: Path) -> Path:
    """テスト用の辞書ファイル（リポジトリ外に置く決まりに合わせ、tmp_path配下に作る）。"""
    p = tmp_path / "denylist.txt"
    p.write_text("サンプル株式会社\n", encoding="utf-8")  # leak-ok: 検査ツール自身の動作確認に使う架空社名
    return p


def test_tracked_file_is_scanned(tmp_path, denylist_path):
    """git add したファイルは検査対象に入る。"""
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    (root / "tracked.txt").write_text("hello\n", encoding="utf-8")
    _git(["add", "tracked.txt"], cwd=root)

    report = leak_check.run(root, denylist_path)

    assert report.git_scope_note is None  # 絞り込みが成立している
    assert report.files_scanned == 1


def test_untracked_not_ignored_file_is_scanned(tmp_path, denylist_path):
    """git add していない新規ファイルでも、.gitignoreされていなければ対象に入る。

    コミット前（git add前）に気づきたい、という要件の検証。
    """
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    (root / "tracked.txt").write_text("hello\n", encoding="utf-8")
    _git(["add", "tracked.txt"], cwd=root)
    (root / "new_file.txt").write_text("brand new\n", encoding="utf-8")  # add していない

    report = leak_check.run(root, denylist_path)

    assert report.git_scope_note is None
    assert report.files_scanned == 2  # tracked.txt + new_file.txt


def test_gitignored_file_is_excluded(tmp_path, denylist_path):
    """.gitignoreされた実データファイルは検査対象から外れる（今回の主目的）。"""
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    (root / ".gitignore").write_text("outputs/\n", encoding="utf-8")
    _git(["add", ".gitignore"], cwd=root)
    (root / "outputs").mkdir()
    # 実データを想定した内容。辞書に一致する語を含めておき、
    # 「検査対象から外れているので検出されない」ことまで確認する。
    (root / "outputs" / "real_data.txt").write_text("サンプル株式会社の実データ\n", encoding="utf-8")  # leak-ok: 検査ツール自身の動作確認に使う架空社名

    report = leak_check.run(root, denylist_path)

    assert report.git_scope_note is None
    assert report.candidate_files_total == 2  # .gitignore + outputs/real_data.txt
    assert report.files_scanned == 1  # .gitignore のみ（outputs/配下は対象外）
    assert report.findings == []  # 辞書一致のはずが、検査対象外なので検出されない


def test_gitignore_negation_pattern_is_respected(tmp_path, denylist_path):
    """.gitignoreの否定パターン(!)は自前でパースせずgitに委ねるため、正しく復活する。"""
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    (root / ".gitignore").write_text("outputs/*\n!outputs/keep.txt\n", encoding="utf-8")
    _git(["add", ".gitignore"], cwd=root)
    (root / "outputs").mkdir()
    (root / "outputs" / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    (root / "outputs" / "keep.txt").write_text("kept\n", encoding="utf-8")

    report = leak_check.run(root, denylist_path)

    assert report.files_scanned == 2  # .gitignore + outputs/keep.txt（ignored.txtは対象外）


def test_force_added_file_under_gitignore_is_still_scanned(tmp_path, denylist_path):
    """.gitignoreに書かれていても git add -f で追跡されていれば公開対象＝検査対象。"""
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    (root / ".gitignore").write_text("outputs/\n", encoding="utf-8")
    _git(["add", ".gitignore"], cwd=root)
    (root / "outputs").mkdir()
    (root / "outputs" / "forced.txt").write_text("forced\n", encoding="utf-8")
    _git(["add", "-f", "outputs/forced.txt"], cwd=root)

    report = leak_check.run(root, denylist_path)

    assert report.files_scanned == 2  # .gitignore + outputs/forced.txt（force addされたので対象）


def test_not_a_git_repo_falls_back_to_full_scan(tmp_path, denylist_path):
    """Gitリポジトリでない場合、辞書欠落と違いexit 2にはせず全件検査にフォールバックする。"""
    root = tmp_path / "plain_dir"
    root.mkdir()
    (root / "a.txt").write_text("hello\n", encoding="utf-8")

    report = leak_check.run(root, denylist_path)

    assert report.git_scope_note is not None  # フォールバックした旨が記録されている
    assert report.denylist_error is None  # 辞書は正常なので、検査できていない(exit2)扱いではない
    assert report.files_scanned == 1  # 絞り込めない代わりに全件検査している


def test_git_binary_missing_falls_back_to_full_scan(tmp_path, denylist_path, monkeypatch):
    """gitコマンド自体が無い場合も同様にフォールバックする（exit 2にしない）。"""
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    (root / "a.txt").write_text("hello\n", encoding="utf-8")
    _git(["add", "a.txt"], cwd=root)

    def _raise_not_found(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(leak_check.subprocess, "run", _raise_not_found)

    report = leak_check.run(root, denylist_path)

    assert report.git_scope_note is not None
    assert "git" in report.git_scope_note.lower() or "Git" in report.git_scope_note
    assert report.files_scanned == 1


def test_no_git_scope_flag_disables_filtering(tmp_path, denylist_path):
    """--no-git-scope相当（use_git_scope=False）は絞り込みをせず全件検査する。"""
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    (root / ".gitignore").write_text("outputs/\n", encoding="utf-8")
    _git(["add", ".gitignore"], cwd=root)
    (root / "outputs").mkdir()
    (root / "outputs" / "real_data.txt").write_text("ignored but scanned\n", encoding="utf-8")

    report = leak_check.run(root, denylist_path, use_git_scope=False)

    assert report.git_scope_note is None  # フォールバックではなく明示的に絞り込みをしていない
    assert report.files_scanned == 2  # outputs/配下も検査される


def test_exit_code_is_not_2_when_git_scope_falls_back(tmp_path, denylist_path):
    """print_reportの終了コードが、Git絞り込み不能を理由にexit 2にならないこと。

    exit 2は「（辞書照合など）検査そのものができていない」ことに予約されており、
    絞り込みの可否とは独立した意味であることの確認。
    """
    root = tmp_path / "plain_dir"
    root.mkdir()
    (root / "a.txt").write_text("hello\n", encoding="utf-8")

    report = leak_check.run(root, denylist_path)
    code = leak_check.print_report(report, root)

    assert code != 2


def test_unapproved_binary_fails_check(tmp_path, denylist_path, capsys):
    """公開候補の画像を目視承認していなければ、検出ありとして止める。"""
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    image = root / "report.png"
    image.write_bytes(b"synthetic image bytes")
    _git(["add", "report.png"], cwd=root)

    report = leak_check.run(root, denylist_path)

    assert report.unreadable == [image]
    assert report.approved_binary == []
    assert leak_check.print_report(report, root) == 1
    capsys.readouterr()


def test_binary_with_matching_sha256_manifest_passes(tmp_path, denylist_path, capsys):
    """目視承認済み画像は、内容ハッシュが一致するときだけ通す。"""
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    image = root / "report.png"
    image.write_bytes(b"reviewed synthetic image")
    tools_dir = root / "tools"
    tools_dir.mkdir()
    manifest = tools_dir / "public-binary-manifest.sha256"
    manifest.write_text(
        f"{leak_check.sha256_file(image)}  report.png\n",
        encoding="utf-8",
    )
    _git(["add", "report.png", "tools/public-binary-manifest.sha256"], cwd=root)

    report = leak_check.run(root, denylist_path)

    assert report.unreadable == []
    assert report.approved_binary == [image]
    assert leak_check.print_report(report, root) == 0
    capsys.readouterr()


def test_changed_binary_no_longer_matches_manifest(tmp_path, denylist_path, capsys):
    """承認後に画像が差し替わったら、同じパスでも再確認を要求する。"""
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    image = root / "report.png"
    image.write_bytes(b"reviewed synthetic image")
    tools_dir = root / "tools"
    tools_dir.mkdir()
    manifest = tools_dir / "public-binary-manifest.sha256"
    manifest.write_text(
        f"{leak_check.sha256_file(image)}  report.png\n",
        encoding="utf-8",
    )
    _git(["add", "report.png", "tools/public-binary-manifest.sha256"], cwd=root)
    image.write_bytes(b"changed after review")

    report = leak_check.run(root, denylist_path)

    assert report.unreadable == [image]
    assert report.approved_binary == []
    assert leak_check.print_report(report, root) == 1
    capsys.readouterr()


def test_invalid_binary_manifest_is_incomplete_check(tmp_path, denylist_path, capsys):
    """壊れた承認一覧を無視して成功扱いにしない。"""
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    tools_dir = root / "tools"
    tools_dir.mkdir()
    manifest = tools_dir / "public-binary-manifest.sha256"
    manifest.write_text("not-a-hash  report.png\n", encoding="utf-8")
    _git(["add", "tools/public-binary-manifest.sha256"], cwd=root)

    report = leak_check.run(root, denylist_path)

    assert report.binary_manifest_error is not None
    assert leak_check.print_report(report, root) == 2
    capsys.readouterr()


def test_pattern_only_explicitly_skips_missing_private_denylist(tmp_path, capsys):
    """公開CIは明示指定した場合だけ、秘密辞書なしで1階の検査を実行できる。"""
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    (root / "safe.txt").write_text("public sample\n", encoding="utf-8")
    _git(["add", "safe.txt"], cwd=root)

    report = leak_check.run(
        root,
        tmp_path / "missing-denylist.txt",
        use_denylist=False,
    )

    assert report.denylist_error is None
    assert report.denylist_note is not None
    assert leak_check.print_report(report, root) == 0
    capsys.readouterr()


def _kana_terms(*words):
    """架空のかな語だけを含む辞書エントリ（(term, kind, matcher)のリスト）を組み立てる。

    本物の辞書ファイル(~/.config/saa/denylist.txt)は絶対に読まない。テスト内で
    架空の語（実在しない人名の体裁の語）を使い、_compile_term と scan_line_tier2 の
    境界判定だけを検証する。
    """
    return [(term, *leak_check._compile_term(term)) for term in words]


def test_short_kana_term_embedded_in_longer_kana_run_is_not_detected():
    """短いかな語が、前後をかな文字に挟まれた長いかな列の一部に見えるときは検出しない。

    辞書の短いかな語が、日本語の助詞・活用語尾の音の並びにたまたま一致してしまう
    誤検出のケース（架空の語で再現する）。
    """
    terms = _kana_terms("さくら")  # 架空の3文字のかな語
    # 「ひとさくらものがたり」: 前後とも「さくら」の前後がかな文字（と／も）で、
    # 長いかな列の一部にちょうど埋もれている。
    hits = leak_check.scan_line_tier2("ひとさくらものがたり", terms)
    assert hits == []


def test_short_kana_term_standalone_between_punctuation_is_detected():
    """短いかな語の前後が句読点等（かな文字でない）なら、そのかな列は語とちょうど一致しているとみなし検出する。"""
    terms = _kana_terms("さくら")
    hits = leak_check.scan_line_tier2("・さくら（担当）", terms)
    assert len(hits) == 1
    assert hits[0][1] == "さくら"


def test_short_kana_term_adjacent_to_kanji_only_is_not_detected():
    """短いかな語の前後が漢字だけ（敬称も辞書の別語への隣接も無い）では検出しない。

    「[漢字1文字の動詞語幹]+活用語尾+助詞」という言い回し（誤検出の典型例）は、
    姓の有無に関わらず漢字にそのまま隣接する。漢字隣接だけを検出根拠にすると、
    この種の誤検出を防げないため、漢字隣接単体では検出しない設計にしている。
    """
    terms = _kana_terms("さくら")
    # 「田中さくら教授」: 前=中（漢字）、後=教（漢字）だが、"田中" は辞書に無い
    # （辞書には "さくら" しか無い）ため、姓への隣接とは判定されない。
    hits = leak_check.scan_line_tier2("田中さくら教授にご担当いただいた", terms)
    assert hits == []


def test_short_kana_term_adjacent_to_another_dict_term_is_detected():
    """前後が漢字でも、その漢字列が辞書に載っている別の語（姓など）なら検出する。"""
    terms = _kana_terms("山田", "さくら")  # 架空の姓「山田」と、架空のかな語「さくら」
    # 「山田さくら教授」: "さくら" の直前が、辞書に載っている別の語 "山田" に一致する。
    hits = leak_check.scan_line_tier2("山田さくら教授にご担当いただいた", terms)
    matched = {h[1] for h in hits}
    assert "さくら" in matched


def test_short_kana_term_adjacent_to_kanji_can_miss_unregistered_surname():
    """既知の限界: 姓が辞書に無い場合、漢字隣接だけの人名らしき言及は見逃す。

    このケースは以前の実装（漢字隣接だけで検出する版）では検出できていたが、
    「辞書の別語への隣接」を条件にしたことで、姓が辞書に登録されていない限り
    検出できなくなった。文字種だけでは実在の人名か一般的な言い回しかを区別
    できないため、この見逃しは今回の設計変更に伴うトレードオフとして受け入れる
    （辞書に姓も合わせて登録するか、除外リストと逆の「要注意リスト」的な運用で
    補う必要がある）。
    """
    terms = _kana_terms("さくら")  # 辞書には "さくら" のみで、姓は登録されていない
    # 「未登録の姓+さくら+漢字」の形。前後とも漢字で、敬称も辞書の別語への隣接も無い。
    hits = leak_check.scan_line_tier2("面談担当は山田さくら子です", terms)  # leak-ok: 検査ツール自身の動作確認に使う架空の氏名
    assert hits == []  # 現行設計での既知の見逃し（意図的に固定している）


def test_short_kana_term_followed_by_honorific_is_detected_even_after_kana():
    """直後が「さん」「様」「氏」の場合、直前がかな文字（助詞等）でも検出する。"""
    terms = _kana_terms("さくら")
    # 「は」は助詞（かな文字）だが、直後に「様」が続くため検出する。
    hits = leak_check.scan_line_tier2("本日はさくら様にご来場いただいた", terms)  # leak-ok: 検査ツール自身の動作確認に使う架空の氏名
    assert len(hits) == 1
    assert hits[0][1] == "さくら"


def test_kanji_term_is_not_subject_to_kana_boundary_check():
    """漢字を含む語は、この境界チェックの対象外（これまでと同じ部分一致）のまま。"""
    terms = _kana_terms("架空太郎")  # 架空の氏名（漢字）
    hits = leak_check.scan_line_tier2("採用担当は架空太郎さんです", terms)
    assert len(hits) == 1
    assert hits[0][1] == "架空太郎"


def test_kana_term_longer_than_threshold_is_not_subject_to_kana_boundary_check():
    """4文字以上のかな語は境界チェックの対象外（従来通り、かな列に埋もれていても検出する）。"""
    terms = _kana_terms("さくらんぼ")  # 5文字。_SHORT_KANA_TERM_MAX_LEN(3)を超える
    hits = leak_check.scan_line_tier2("やまさくらんぼうをたべた", terms)
    assert len(hits) == 1
    assert hits[0][1] == "さくらんぼ"


def test_denylist_missing_is_still_exit_2_regardless_of_git_scope(tmp_path):
    """辞書が無いときの exit 2 は、今回のGit絞り込み変更後も維持されていること（既存挙動の回帰確認）。"""
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    (root / "a.txt").write_text("hello\n", encoding="utf-8")
    _git(["add", "a.txt"], cwd=root)

    missing_denylist = root.parent / "no_such_denylist.txt"
    report = leak_check.run(root, missing_denylist)
    code = leak_check.print_report(report, root)

    assert code == 2


# ---------------------------------------------------------------------------
# client_email: キー名だけの言及と、実際の値を伴う形の切り分け
#
# Googleドキュメント/スプレッドシートへの書き込み機能が入り、案内文で
# 「認証ファイルの client_email の値を共有してください」という言い方が
# 増えた。キー名だけの言及で鳴っては誤検出になるが、実際のSAアドレスらしき
# 値が続く形や、認証ファイルの中身がまるごと貼られた形は引き続き検出する
# 必要がある。
# ---------------------------------------------------------------------------

def _has_category(hits, category) -> bool:
    return any(h[0] == category for h in hits)


def test_client_email_key_name_only_mention_is_not_detected():
    """案内文で `client_email` というキー名だけに触れている場合は鳴らない。"""
    line = "共有先には認証ファイルの `client_email` の値を貼ってください（値自体は書かない）。"
    hits = leak_check.scan_line_tier1(line)
    assert not _has_category(hits, "認証情報そのもの")


def test_client_email_json_style_value_is_detected():
    """JSONの `"client_email": "値"` の形で実際のメールアドレスらしき値が続く場合は検出する。"""
    # @example.iam.gserviceaccount.com は架空のドメイン（実在のSAアドレスではない）。
    # 検出されて当然の行なので leak-ok を付ける（このツール自身の動作確認用の架空値）。
    line = '"client_email": "fake-sa@example.iam.gserviceaccount.com",'  # leak-ok: 検査ツール自身の動作確認に使う架空のSAアドレス
    hits = leak_check.scan_line_tier1(line)
    assert _has_category(hits, "認証情報そのもの")


def test_client_email_equals_style_value_is_detected():
    """`client_email=値` のようなJSON以外の形で値が続く場合も検出する。"""
    line = "client_email=fake-sa@example.iam.gserviceaccount.com"  # leak-ok: 検査ツール自身の動作確認に使う架空のSAアドレス
    hits = leak_check.scan_line_tier1(line)
    assert _has_category(hits, "認証情報そのもの")


def test_full_credential_file_pasted_is_still_detected():
    """認証ファイルの中身がまるごと貼られた形は、private_key側の検出で引き続き鳴る。"""
    # 1行にまとめる（複数行に分けるとleak-okが末尾の行にしか効かず、他の行がこの
    # ツール自身の検査で誤って未対処の検出として残ってしまうため）。
    line = '{"type": "service_account", "private_key": "-----BEGIN PRIVATE KEY-----\\nFAKE\\n-----END PRIVATE KEY-----\\n", "client_email": "fake-sa@example.iam.gserviceaccount.com"}'  # leak-ok: 検査ツール自身の動作確認に使う架空の鍵ファイル
    hits = leak_check.scan_line_tier1(line)
    assert _has_category(hits, "認証情報そのもの")


# ---------------------------------------------------------------------------
# docs.google.com のURL: ダミーIDと本物らしい長さのIDの切り分け
#
# 製品側にGoogleドキュメント/スプレッドシートへの書き込み機能が入り、
# URLそのものが正当な設定値・サンプル・テストコードに大量に登場するように
# なった。ダミーID（xxxx, abc123, {doc_id} 等）では鳴らず、本物らしい長さの
# IDが続く場合だけ検出する必要がある。
# ---------------------------------------------------------------------------

# 実在のドキュメントを指さない、架空の長いID（本物のGoogleドキュメントIDと同程度の
# 43文字。現行形式のIDは44文字、旧形式でも28文字あるため、しきい値25文字を
# 安全に上回る）。数字を連続させると別の検査（GA4プロパティIDの9〜10桁検出）に
# 誤ってひっかかるため、英字と数字を交互に混ぜている。
_FAKE_LONG_DOC_ID = "1AbC2dEf3GhI4jKl5MnO6pQr7StU8vWx9YzA0bCd1EfG"


def test_google_doc_url_with_short_dummy_id_is_not_detected():
    """"xxxx" のような短いダミーIDでは鳴らない。"""
    line = 'url = "https://docs.google.com/document/d/xxxx/edit"'
    hits = leak_check.scan_line_tier1(line)
    assert not _has_category(hits, "社内サービスのURL")


def test_google_doc_url_with_placeholder_braces_is_not_detected():
    """"{doc_id}" のようなテンプレートのプレースホルダでは鳴らない。"""
    line = 'url = f"https://docs.google.com/document/d/{doc_id}/edit"'
    hits = leak_check.scan_line_tier1(line)
    assert not _has_category(hits, "社内サービスのURL")


def test_google_doc_url_with_real_looking_long_id_is_detected():
    """本物のGoogleドキュメントIDと同程度に長いIDが続く場合は検出する。"""
    line = f'url = "https://docs.google.com/document/d/{_FAKE_LONG_DOC_ID}/edit"'
    hits = leak_check.scan_line_tier1(line)
    assert _has_category(hits, "社内サービスのURL")


def test_google_sheet_url_with_real_looking_long_id_is_detected():
    """spreadsheets側でも同様に、本物らしい長さのIDは検出する。"""
    line = f'url = "https://docs.google.com/spreadsheets/d/{_FAKE_LONG_DOC_ID}/edit#gid=0"'
    hits = leak_check.scan_line_tier1(line)
    assert _has_category(hits, "社内サービスのURL")
