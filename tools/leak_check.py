#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公開してはいけない記述がリポジトリに残っていないかを検査する。

    python tools/leak_check.py [対象ディレクトリ]

対象ディレクトリを省略すると、このファイルの1つ上の階層（リポジトリ直下）を検査する。
自分自身のリポジトリではない場所（例: 元になった社内リポジトリ）を読むだけで検査したい
ときは、対象ディレクトリを引数で渡す（--root でも同じ）。

検査は2階建て。

  1階: 辞書が要らない検査。正規表現のパターンだけで検出する。個人環境のパス、
       社内サービスのURL、認証情報の形、ダミーでない実IDなど。コードごと公開してよい。

  2階: 辞書が要る検査。自社名・親会社名・個人名・実クライアント名の一覧を
       ~/.config/saa/denylist.txt（1行1語、# 以降コメント）から読んで、
       リポジトリ全文に対して照合する。このファイルはリポジトリの外に置く決まりで、
       中身をこのツールに書き込んではいけない。

辞書が見つからないときは「検出0件」にしない。2階の検査ができていないという事実を
exit 2 で表す。exit 2 は「検査できていない」であって「検出0件」とは別物として扱う
（社内版 common/tenant_leak_check.sh と同じ考え方）。
公開CIでは秘密の辞書をrunnerへ渡せないため、`--pattern-only` を明示した場合に限り
1階だけを実行する。公開担当者の最終検査ではこの指定を使わず、2階も必ず実行する。

検査対象は既定で「実際に公開されるファイル」に絞る。具体的には
  - Gitが追跡しているファイル（git ls-files）
  - まだ追跡されていないが .gitignore 等で無視もされていない新規ファイル
    （git ls-files --others --exclude-standard。git add 前でも気づきたいため対象にする）
の合計で、outputs/ や 01_context_management/context/ のような .gitignore 済みの
検証用実データディレクトリはそもそも公開されないため検査から外れる。
.gitignore の否定パターン(!)等の解釈は自前でパースせずgit自身に委ねる。

Gitが使えない（gitコマンドが無い／このディレクトリがGitリポジトリでない等）場合は、
「絞り込みができない」だけであって「検査ができない」わけではないので、辞書欠落と同じ
exit 2 にはしない。安全側（見逃しが最悪という方針）に倒して全件検査にフォールバックし、
その旨を必ず画面に表示する（`--no-git-scope` で明示的に全件検査にすることもできる）。

除外は2種類ある。

  - 行末 `leak-ok: 理由`（リポジトリ内）: ダミー社名・ダミーIDなど、注記自体を公開しても
    辞書の中身が推測できないものに使う。理由が空の leak-ok は除外として認めない。

  - 除外リスト ~/.config/saa/leak-allow.txt（リポジトリの外）: 辞書の語がたまたま
    日本語の一般的な言い回し（「〜まわりの」「〜寄りの」等）の一部に一致してしまう
    誤検出に使う。注記をリポジトリ内に書くと、どの語で誤検出したかの手がかりから
    辞書の中身が推測できてしまうため、除外そのものを辞書と同じ考え方でリポジトリの
    外に置く。書式は denylist.txt と同じ1行1件（相対パス:検出語、# 以降コメント）。
    このファイルが無い場合も「検査できていない」扱いにはしない。除外なしで検査が
    成立する（辞書と違い、除外リストは無くても検査の前提が崩れないため）。

画像などのバイナリは文字列検索できないため、未承認なら検出あり（exit 1）にする。
公開してよいことを人が確認したバイナリだけ、tools/public-binary-manifest.sha256 に
内容のSHA256と相対パスを記録する。内容が変わればハッシュが一致せず、再確認が必要になる。

終了コード: 0=検出なし / 1=検出あり（未承認バイナリを含む） / 2=検査できていない
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --- このツール自身は検査対象から外す ---------------------------------------
SELF_PATH = Path(__file__).resolve()

# 既定の辞書の置き場所。リポジトリの外（ホームディレクトリ配下）。
DEFAULT_DENYLIST = Path.home() / ".config" / "saa" / "denylist.txt"

# 既定の除外リストの置き場所。リポジトリの外（ホームディレクトリ配下）。
# 辞書の誤検出（日本語の言い回しの一部が辞書の語に一致する等）をここで除外する。
DEFAULT_ALLOWLIST = Path.home() / ".config" / "saa" / "leak-allow.txt"

# 検査から常に外すディレクトリ名
EXCLUDE_DIR_NAMES = {".venv", "venv", "node_modules", "__pycache__", ".git"}

# 検査から常に外すファイル名（拡張子ではなくファイル名で判定）。
# uv.lock は uv が自動生成するロックファイルで、中身は PyPI 上の公開パッケージへの
# URL・sha256ハッシュ・アップロード日時のみ（社内の実データは一切含まれない）。
# ハッシュ値やURLパス中の16進文字列にたまたま9〜10桁の数字の並びが出現するため、
# 「ダミー以外の実ID」検査が大量に誤検出する。1行ずつ leak-ok を付ける運用は
# 現実的でなく、再生成のたびに消えてしまうため、ファイル単位で検査対象から外す。
# パッケージごとの直下（例: 05_campaign_optimization/1_overall_strategy/analysis/uv.lock）
# に複数存在するため、名前一致であれば深さを問わず除外してよい。
EXCLUDE_FILE_NAMES = {"uv.lock"}

# LICENSE は発行元（自社名）を名乗ること自体が目的のファイルで、辞書一致は
# 常に「意図した検出」にしかならない。定型フォーマットの法務文書に
# `leak-ok: 理由` のようなコード注記を混ぜるのも体裁として不適切なため、
# 検査対象から外す。ただしファイル名だけで判定すると、リポジトリの深い階層に
# 同名で紛れ込んだファイル（サンプル出力の中の "LICENSE" というダミーファイル名、
# 第三者コードに同梱された本物のLICENSE等）まで一律に見逃す抜け穴になる。
# 発行元を名乗る対象はルート直下の1ファイルだけなので、パスをルート直下に限定する。
ROOT_LICENSE_NAME = "LICENSE"

# 拡張子だけで「文字列検索できないファイル」と判定するもの（画像・PDF・バイナリ等）
BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svgz",
    ".pdf", ".zip", ".gz", ".tgz", ".tar", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".class", ".jar", ".pyc",
    ".mp4", ".mov", ".avi", ".mp3", ".wav", ".m4a", ".webm",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ppt",
    ".db", ".sqlite", ".sqlite3", ".parquet",
    ".psd", ".ai", ".eps",
}

LEAK_OK_RE = re.compile(r"leak-ok:\s*(\S.*)?$")


def is_excluded_by_leak_ok(line: str) -> bool:
    """行末の leak-ok: 理由 で除外されるかどうか。理由が空なら除外しない。"""
    m = LEAK_OK_RE.search(line)
    if not m:
        return False
    reason = m.group(1)
    return bool(reason and reason.strip())


@dataclass
class Finding:
    path: Path
    lineno: int
    category: str
    matched: str
    hint: str


@dataclass
class Report:
    findings: list = field(default_factory=list)
    unreadable: list = field(default_factory=list)  # 検査できなかったファイル
    approved_binary: list = field(default_factory=list)  # 内容ハッシュを人が承認済みのバイナリ
    binary_manifest_error: str = None  # 承認済みバイナリ一覧を読めなかった理由
    embedded_binary: list = field(default_factory=list)  # base64/データURIの画像等（人の確認が必要）
    approved_embedded: list = field(default_factory=list)
    files_scanned: int = 0
    denylist_error: str = None  # 2階（辞書照合）が実行できなかった理由。Noneなら実行できた
    denylist_note: str = None  # --pattern-only により辞書照合を明示的に省略した旨
    allowlist_note: str = None  # 除外リストが読めなかった/無かった旨の案内。検査自体は成立する
    candidate_files_total: int = 0  # os.walkで見つかった全候補ファイル数（Git絞り込み前）
    git_scope_note: str = None  # Gitでの絞り込みができず全件検査にフォールバックした理由。Noneなら絞り込み成立


# ---------------------------------------------------------------------------
# 1階: 辞書が要らない検査（パターンのみ）
# ---------------------------------------------------------------------------

# (カテゴリ名, コンパイル済み正規表現, 修正のヒント)
# 単純な「マッチしたら即アウト」のパターン群。
SIMPLE_PATTERNS = [
    (
        "個人環境のパス",
        re.compile(r"[A-Za-z]:\\{1,2}Users\\{1,2}[^\s\"'<>]*", re.IGNORECASE),
        "個人のマシン名・ユーザー名が写り込んでいる。汎用的なプレースホルダ（例: <ホームディレクトリ>）に置き換える。",
    ),
    (
        "個人環境のパス",
        re.compile(r"(?<![\w/])/Users/[^\s\"'<>]*"),
        "個人のマシン名・ユーザー名が写り込んでいる。汎用的なプレースホルダに置き換える。",
    ),
    (
        "個人環境のパス",
        re.compile(r"(?<![\w/])/home/[^\s\"'<>]*"),
        "個人のマシン名・ユーザー名が写り込んでいる。汎用的なプレースホルダに置き換える。",
    ),
    (
        "個人環境のパス",
        re.compile(r"(?<![\w/])/Volumes/[^\s\"'<>]*"),
        "個人の外付けボリューム名が写り込んでいる。汎用的なプレースホルダに置き換える。",
    ),
    (
        "個人環境のパス",
        re.compile(r"~/Work/[^\s\"'<>]*"),
        "個人・社内の作業フォルダ構成が写り込んでいる。削除するか一般化する。",
    ),
    (
        "個人環境のパス",
        re.compile(r"~/ai/[^\s\"'<>]*"),
        "社内共通の作業ディレクトリ（~/ai/...）のパスが写り込んでいる。認証ファイル置き場に限らず、"
        "内部サービスへの参照（~/ai/services/... 等）も含めて検出する。削除するか一般化する。",
    ),
    (
        "社内サービスのURL",
        re.compile(r"\blinear\.app\S*", re.IGNORECASE),
        "Linear（社内タスク管理）へのリンク。削除するか「内部トラッキング済」等の表記に置き換える。",
    ),
    (
        "社内サービスのURL",
        re.compile(r"\bnotion\.so\S*", re.IGNORECASE),
        "Notion（社内ドキュメント）へのリンク。削除するか一般化する。",
    ),
    (
        "社内サービスのURL",
        re.compile(r"\bforgejo\.\S*", re.IGNORECASE),
        "社内Forgejo（Gitホスティング）へのリンク。削除するか一般化する。",
    ),
    (
        "社内サービスのURL",
        re.compile(r"slack\.com/archives\S*", re.IGNORECASE),
        "Slackの特定チャンネル・スレッドへのリンク。削除する。",
    ),
    (
        "社内サービスのURL",
        re.compile(r"drive\.google\.com\S*", re.IGNORECASE),
        "Google Driveへの直リンク。社内共有ドライブの構成が漏れる。削除するか一般化する。",
    ),
    (
        "認証情報そのもの",
        re.compile(r"BEGIN PRIVATE KEY"),
        "秘密鍵の断片が写り込んでいる。ファイルごと除外し、鍵は無効化（ローテーション）する。",
    ),
    (
        "認証情報そのもの",
        re.compile(r'"private_key"'),
        "サービスアカウント鍵のJSONがそのまま入っている可能性。ファイルごと除外し、鍵は無効化する。",
    ),
    (
        "認証情報そのもの",
        re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
        "Google APIキーの形をした文字列。無効化のうえ削除する。",
    ),
    (
        "認証情報そのもの",
        re.compile(r"\bxox[bp]-[0-9A-Za-z-]{10,}\b"),
        "Slackトークンの形をした文字列。無効化のうえ削除する。",
    ),
    (
        "認証情報そのもの",
        re.compile(r"\bgh[po]_[0-9A-Za-z]{20,}\b"),
        "GitHubトークンの形をした文字列。無効化のうえ削除する。",
    ),
    (
        "メールアドレス",
        re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+\-]*@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
        "example.com / example.org 以外のドメインのメールアドレス。サンプル用ドメインに差し替える。",
    ),
]

# example.com / example.org（およびそのサブドメイン）はメールアドレス検査の対象外
_ALLOWED_EMAIL_DOMAINS = ("example.com", "example.org")

# 「〜様」の誤検知になりやすい一般語（人名+様ではないもの）
_SAMA_FALSE_POSITIVES = {
    "仕様", "同様", "多様", "様々", "様式", "異様", "模様", "王様", "神様",
    "お客様", "皆様", "各位様", "貴社様", "担当者様", "クライアント様",
    "ご担当者様", "一様", "並様",
}

# 「様」は敬称のほかに「様子」「様々」「仕様」「同様」「模様」のような普通の語にも出る。
# 敬称として使われた形だけを拾うため、直後が「子」「々」の場合と、
# 直前が「仕」「同」「模」「多」「異」の場合は対象外にする（いずれも人名の直後には来ない）。
_SAMA_RE = re.compile(r"[一-龥ぁ-んァ-ヶー]{1,6}(?<![仕同模多異])様(?![子々])")
_KABUSHIKI_RE = re.compile(r"株式会社")

_GA4_ID_RE = re.compile(r"(?<!\d)\d{9,10}(?!\d)")
_GA4_ID_DUMMY = "123456789"

_G_TAG_RE = re.compile(r"\bG-([A-Za-z0-9]{6,})\b")
_GTM_RE = re.compile(r"\bGTM-([A-Za-z0-9]{6,8})\b")
_AW_RE = re.compile(r"\bAW-(\d{6,11})\b")

# docs.google.com のURL: プロダクト側にGoogleドキュメント/スプレッドシートへの
# 書き込み機能が入り、URLそのものが正当な設定値として大量に登場するようになった。
# 「docs.google.comを含む」という一律検出では、ダミーID（xxxx, abc123, {doc_id} 等）の
# サンプル・テストコードまで鳴ってしまう。そこで、URLの有無ではなく「本物らしい長さの
# ドキュメントIDを伴っているか」で判定する。
#
# しきい値の根拠: 実際のGoogleドキュメント/スプレッドシートIDは、現行形式で44文字
# （例: Google Sheets API公式サンプルの "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"）、
# 2014年より前に発行された旧形式でも28文字ある。対してこのリポジトリのダミー値は
# "xxxxxxxx"（8文字）「x」「abc123」「AbC123-xyz」（10文字）等、長くても十数文字に収まる。
# 旧形式（28文字）にも安全に届き、かつ現行のダミー値のどれとも重ならないよう、
# 余裕を持って25文字を境目にする。
_GOOGLE_DOC_ID_MIN_LEN = 25
_GOOGLE_DOC_URL_RE = re.compile(
    r"docs\.google\.com/(?:document|spreadsheets|presentation|forms)/(?:u/\d+/)?d/(?:e/)?"
    r"([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

# client_email: キー名そのものの言及（案内文で「認証ファイルのclient_emailの値を
# 共有してください」のように書く）は、実際の値を書いていないので鳴らさない。
# 「client_email」に続けて実際のメールアドレスらしき値が来ている形（JSONの
# "client_email": "xxx@xxx.iam.gserviceaccount.com" や client_email=xxx@xxx 等）
# だけを検出する。BEGIN PRIVATE KEY / "private_key" の検出とあわせて、認証ファイルの
# 中身がまるごと貼られる事故は引き続き検出できる。
_CLIENT_EMAIL_VALUE_RE = re.compile(
    r'client_email["\']?\s*[:=]\s*["\']?'
    r"[A-Za-z0-9][A-Za-z0-9._%+\-]*@[^\s\"'<>]+",
    re.IGNORECASE,
)


def _is_dummy_placeholder(token: str) -> bool:
    """G-XXXXXXXXXX / GTM-XXXXXXX のような「Xで埋めたダミー」かどうか。"""
    return bool(token) and all(c.upper() == "X" for c in token)


def scan_line_tier1(line: str) -> list:
    """1階（辞書不要）のパターンを1行に対して走らせ、(category, matched, hint) を返す。"""
    hits = []

    for category, pattern, hint in SIMPLE_PATTERNS:
        for m in pattern.finditer(line):
            matched = m.group(0)
            if category == "メールアドレス":
                domain = matched.rsplit("@", 1)[-1].lower()
                if domain in _ALLOWED_EMAIL_DOMAINS or domain.endswith(
                    tuple("." + d for d in _ALLOWED_EMAIL_DOMAINS)
                ):
                    continue
            hits.append((category, matched, hint))

    # GA4プロパティID（9〜10桁、ダミーの123456789以外）
    for m in _GA4_ID_RE.finditer(line):
        if m.group(0) == _GA4_ID_DUMMY:
            continue
        hits.append((
            "ダミー以外の実ID",
            m.group(0),
            "9〜10桁の数値がGA4プロパティIDの可能性。ダミー値 123456789 に差し替える。",
        ))

    # G-XXXXXXXXXX / GTM-XXXXXXX / AW-XXXXXXXXX
    for m in _G_TAG_RE.finditer(line):
        if not _is_dummy_placeholder(m.group(1)):
            hits.append((
                "ダミー以外の実ID",
                m.group(0),
                "測定ID(G-...)の実値の可能性。ダミー値 G-XXXXXXXXXX に差し替える。",
            ))
    for m in _GTM_RE.finditer(line):
        if not _is_dummy_placeholder(m.group(1)):
            hits.append((
                "ダミー以外の実ID",
                m.group(0),
                "GTMコンテナIDの実値の可能性。ダミー値 GTM-XXXXXXX に差し替える。",
            ))
    for m in _AW_RE.finditer(line):
        hits.append((
            "ダミー以外の実ID",
            m.group(0),
            "Google広告のコンバージョンID(AW-...)の実値の可能性。ダミー値に差し替える。",
        ))

    # docs.google.com: 本物らしい長さのドキュメントIDを伴う場合のみ検出する
    for m in _GOOGLE_DOC_URL_RE.finditer(line):
        if len(m.group(1)) >= _GOOGLE_DOC_ID_MIN_LEN:
            hits.append((
                "社内サービスのURL",
                m.group(0),
                "Google Docs/Sheetsへの直リンク（本物らしい長さのドキュメントIDを含む）。"
                "削除するか一般化する。",
            ))

    # client_email: キー名だけでなく実際の値が続く形のみ検出する
    for m in _CLIENT_EMAIL_VALUE_RE.finditer(line):
        hits.append((
            "認証情報そのもの",
            m.group(0),
            "サービスアカウント鍵のメールアドレスが値として書かれている可能性。ファイルごと除外し、鍵は無効化する。",
        ))

    # 日本語の実社名の気配
    for m in _KABUSHIKI_RE.finditer(line):
        hits.append((
            "日本語の実社名の気配",
            m.group(0),
            "実在の社名を含む可能性。サンプルとして使うなら行末に leak-ok: 理由 を付ける。",
        ))
    for m in _SAMA_RE.finditer(line):
        token = m.group(0)
        # 直前の文字を最大6文字まで貪欲に取り込むため、"意図的な仕様" のように
        # 本来の一般語より前方の文字列を余分に抱え込むことがある。末尾一致で判定する。
        if any(token.endswith(fp) for fp in _SAMA_FALSE_POSITIVES):
            continue
        hits.append((
            "日本語の実社名の気配",
            token,
            "個人名・社名+「様」の可能性。サンプルとして使うなら行末に leak-ok: 理由 を付ける。",
        ))

    return hits


# ---------------------------------------------------------------------------
# base64 / データURI: デコードして中身も検査する
#
# ロゴのようなベクター画像(SVG)は、パス座標の羅列であって文字列としての社名を
# 含まない。そのため「デコードしてパターン照合する」だけでは実在の意匠(ロゴ)の
# 埋め込みを検出できない。デコードできたテキストにはパターン照合をかけつつ、
# 画像・フォント等(SVGを含む)は種別を問わず「人の目で確認が必要」として
# report.embedded_binary に積む。findings（検出件数）には数えず、
# unreadable と同様に常に一覧表示する。
# ---------------------------------------------------------------------------

# data:MIME;base64,<payload> 形式。テンプレートのプレースホルダ(__LOGO_B64__ 等)は
# base64の文字集合に含まれない文字を含むため、ここではマッチしない。
_DATA_URI_RE = re.compile(
    r"data:(?P<mime>[\w.+-]+/[\w.+-]+)?(?:;charset=[\w-]+)?;base64,"
    r"(?P<payload>[A-Za-z0-9+/]{4,}={0,2})"
)

# data: プレフィックスのない裸のbase64の塊（ロゴ・フォントの直埋め込みを想定）。
# 60文字未満は誤検出が多いため対象外。
_BARE_B64_RE = re.compile(
    r"(?<![A-Za-z0-9+/=_.-])[A-Za-z0-9+/]{60,}={0,2}(?![A-Za-z0-9+/=_.-])"
)

# sha256ハッシュ等の16進文字列は base64 の文字集合の部分集合に収まってしまうが
# base64エンコードされた画像等ではない。32文字以上の16進のみの並びは除外する。
_HEX_ONLY_RE = re.compile(r"^[0-9a-fA-F]+$")

_IMAGE_LIKE_MIME_PREFIXES = (
    "image/", "font/", "application/font", "application/octet-stream",
    "application/pdf", "video/", "audio/",
)


def _try_b64_decode(payload: str):
    """base64文字列をデコードする。不正な場合はNone（=たまたま英数字が続いただけとみなす）。"""
    core = payload.rstrip("=")
    pad = (-len(core)) % 4
    try:
        return base64.b64decode(core + ("=" * pad), validate=True)
    except Exception:
        return None


def _decode_as_text(data: bytes):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _looks_like_image_markup(text: str) -> bool:
    head = text.lstrip()[:200].lower()
    return head.startswith("<svg") or head.startswith("<?xml")


def _classify_b64_candidate(payload: str, mime: str, denylist_terms, findings_hits: list, review_notes: list) -> None:
    core = payload.rstrip("=")
    if len(core) >= 32 and _HEX_ONLY_RE.match(core):
        return  # sha256等の16進ハッシュ。base64の画像埋め込みではない

    raw = _try_b64_decode(payload)
    if raw is None:
        return  # base64として不正な文字列。誤検出として無視する

    text = _decode_as_text(raw)
    mime_lower = (mime or "").lower()
    is_image_mime = mime_lower.startswith(_IMAGE_LIKE_MIME_PREFIXES)
    is_svg_markup = text is not None and _looks_like_image_markup(text)

    if text is None or is_image_mime or is_svg_markup:
        note = (
            f"base64/データURIの埋め込みデータ（mime={mime or '不明'}, "
            f"デコード後{len(raw):,}バイト）。ベクター画像は文字列に実在の社名が現れないため"
            "パターン検査では検出できない。人の目で意匠を確認する。"
        )
        review_notes.append(note)

    if text is not None:
        # base64に包まれたテキスト（JSON等）にも通常のパターン検査をかける
        for subline in text.splitlines() or [text]:
            for category, matched, hint in scan_line_tier1(subline):
                findings_hits.append((f"[Base64復号後] {category}", matched, hint))
            if denylist_terms:
                for category, matched, hint in scan_line_tier2(subline, denylist_terms):
                    findings_hits.append((f"[Base64復号後] {category}", matched, hint))


def scan_line_base64(line: str, denylist_terms) -> tuple:
    """行内のbase64/データURIを検出し、デコードできる範囲で中身も検査する。

    戻り値: (findings用のhitsリスト, 人の確認が必要な候補のメモ文字列リスト)
    """
    findings_hits: list = []
    review_notes: list = []
    covered_spans = []

    for m in _DATA_URI_RE.finditer(line):
        covered_spans.append((m.start(), m.end()))
        _classify_b64_candidate(m.group("payload"), m.group("mime") or "", denylist_terms, findings_hits, review_notes)

    for m in _BARE_B64_RE.finditer(line):
        if any(s <= m.start() and m.end() <= e for s, e in covered_spans):
            continue  # data URIの一部として既に検査済み
        _classify_b64_candidate(m.group(0), "", denylist_terms, findings_hits, review_notes)

    return findings_hits, review_notes


# ---------------------------------------------------------------------------
# 2階: 辞書が要る検査
# ---------------------------------------------------------------------------

_ASCII_ONLY_RE = re.compile(r"^[\x00-\x7f]+$")

# ひらがな・カタカナのみで構成された語かどうかの判定に使う（漢字は含まない）。
_KANA_ONLY_RE = re.compile(r"^[ぁ-んァ-ヶー]+$")
_KANA_CHAR_RE = re.compile(r"[ぁ-んァ-ヶー]")
# 漢字1文字の判定に使う（_SAMA_RE/_KABUSHIKI_REと同じ範囲）。
_KANJI_CHAR_RE = re.compile(r"[一-龥]")

# 「短いかな語」として境界チェックを適用する長さの上限（文字数）。
# 人名の一部に使われるひらがな・カタカナの語（名前の下の名の全体や、その一部）は
# 2〜3文字程度のものが多い。この長さの語は日本語の助詞・活用語尾の音の並びに
# そのまま埋もれて文中に頻出するため、前後関係を見ずに部分一致させると誤検出が
# 大量に出る。
# 4文字以上になると「たまたま同じ音の並びが一般語の一部として頻出する」度合いが
# 下がる（一般名詞の一致として偶然性が薄れ、逆にその長さの一致は無視できなくなる）
# ため、境界チェックの対象を2〜3文字（目安として3文字まで）に絞る。
# 漢字を含む語（例: 2文字の姓）は、そもそも文中でかな列に埋もれて偶然一致する
# ことが少ないため、この境界チェックの対象にしない（漏れを増やすだけになる）。
#
# 注意: 「短いかな語の前後が漢字」というだけでは人名かどうか判定できない。
# 「[漢字1文字の動詞語幹]+活用語尾+助詞」という言い回し（例: 見出しの言い切りの
# 強さ、区切りの無い数字、のような表現）は、漢字にそのまま隣接する短いかな語の
# 典型例であり、実際の調査でも境界チェックの対象になった語の大半がこの形だった。
# そのため「前後が漢字」は検出の根拠にせず（下の_kana_boundary_hit参照）、
# 敬称・辞書の別の語への隣接・句読点等による孤立、のいずれかでのみ検出する。
_SHORT_KANA_TERM_MAX_LEN = 3

# 短いかな語の直後にこれが続く場合は検出する
# （「〜さん」「〜様」「〜氏」に続く形は、その前が一般語の活用でも人名の言及として扱う）。
_HONORIFIC_SUFFIXES = ("さん", "様", "氏")


def _is_kana_char(ch) -> bool:
    return ch is not None and bool(_KANA_CHAR_RE.match(ch))


def _is_kanji_char(ch) -> bool:
    return ch is not None and bool(_KANJI_CHAR_RE.match(ch))


def _compile_term(term: str):
    """辞書の1語を照合用にコンパイルする。

    英数字だけの語（Ito / Hai / shift 等）は、"monitor" に含まれる "ito" のような
    他の単語の部分文字列に化けやすい。英数字の前後が英数字でないことを要求する
    単語境界つき正規表現にして誤検出を抑える。

    ひらがな・カタカナのみで構成された短い語（目安2〜3文字、_SHORT_KANA_TERM_MAX_LEN参照）
    も同様に化けやすい。こちらは英数字のような「単語」の概念が無い代わりに、
    前後がかな文字で連続している（＝長いかな列の一部に埋もれている）かどうかで判定する。

    それ以外（漢字を含む語、4文字以上のかな語）は、これまで通り部分一致で照合する。
    """
    if _ASCII_ONLY_RE.match(term):
        pattern = re.compile(
            r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])",
            re.IGNORECASE,
        )
        return ("regex", pattern)
    if _KANA_ONLY_RE.match(term) and len(term) <= _SHORT_KANA_TERM_MAX_LEN:
        return ("kana_boundary", term)
    return ("substr", term.lower())


def load_denylist(path: Path) -> list:
    """1行1語、# 以降コメントの辞書を読む。空行・コメントのみの行は無視。

    戻り値は (元の語, 照合方式, コンパイル済みマッチャー) のリスト。
    """
    terms = []
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if line:
                terms.append(line)
    # 長い語を先に照合したいので長さ降順に（部分一致の重複報告を減らす）
    terms.sort(key=len, reverse=True)
    return [(term, *(_compile_term(term))) for term in terms]


# ---------------------------------------------------------------------------
# 除外リスト（リポジトリの外）: 辞書の誤検出をパス+検出語の単位で除外する
# ---------------------------------------------------------------------------

def load_allowlist(path: Path) -> set:
    """除外リストを読む。1行1件、書式: 相対パス:検出語（# 以降コメント、空行は無視）。

    検出語は Finding.matched と同じもの（辞書照合ならヒットした辞書の語そのもの）。
    パスの区切りは "/" に正規化して照合する。
    """
    entries = set()
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            relpath, sep, matched = line.partition(":")
            relpath = relpath.strip().replace("\\", "/")
            matched = matched.strip()
            if not sep or not relpath or not matched:
                continue
            entries.add((relpath, matched))
    return entries


def is_excluded_by_allowlist(allowlist: set, relpath: str, matched: str) -> bool:
    return (relpath, matched) in allowlist


_MAX_HONORIFIC_LEN = max(len(suf) for suf in _HONORIFIC_SUFFIXES)


def _kana_boundary_hit(term: str, line: str, other_terms: list) -> bool:
    """短いかな語が、次のいずれかを満たす箇所で出現するかどうか。

      1. 直後が「さん」「様」「氏」などの敬称
      2. 直前または直後が、辞書に載っている別の語（姓など）に隣接している
      3. 前後がかな文字でも漢字でもない（句読点・空白・ASCII・行頭行末に囲まれ、
         単独の語として現れている）

    上記のいずれにも当たらない場合は、日本語の動詞の活用語尾＋助詞のような
    一般的な言い回しにたまたま一致しただけとみなして無視する。

    「前後が漢字」であること自体は検出の根拠にしない。「[漢字1文字の動詞語幹]
    +活用語尾+助詞」という言い回しは、姓の有無に関わらず漢字に直接隣接するため、
    漢字隣接だけでは人名の言及と普通の言い回しを区別できない
    （_SHORT_KANA_TERM_MAX_LEN のコメント参照）。
    """
    lower_line = line.lower()
    other_terms_lower = [t.lower() for t in other_terms if t and t != term]

    for m in re.finditer(re.escape(term), line):
        s, e = m.start(), m.end()

        after_slice = line[e:e + _MAX_HONORIFIC_LEN]
        if any(after_slice.startswith(suf) for suf in _HONORIFIC_SUFFIXES):
            return True

        before_lower = lower_line[:s]
        after_lower = lower_line[e:]
        if any(before_lower.endswith(t) or after_lower.startswith(t) for t in other_terms_lower):
            return True

        before_ch = line[s - 1] if s > 0 else None
        after_ch = line[e] if e < len(line) else None
        before_is_word_char = _is_kana_char(before_ch) or _is_kanji_char(before_ch)
        after_is_word_char = _is_kana_char(after_ch) or _is_kanji_char(after_ch)
        if not before_is_word_char and not after_is_word_char:
            return True

    return False


def scan_line_tier2(line: str, compiled_terms: list) -> list:
    hits = []
    lower_line = line.lower()
    all_terms = [t for t, _kind, _matcher in compiled_terms]
    for term, kind, matcher in compiled_terms:
        if kind == "regex":
            found = matcher.search(line) is not None
        elif kind == "kana_boundary":
            found = _kana_boundary_hit(matcher, line, all_terms)
        else:
            found = matcher in lower_line
        if found:
            hits.append((
                "辞書一致（社名・個人名・クライアント名）",
                term,
                "自社/親会社/個人/実クライアントの名称。削除するか一般化する。サンプルとして必要なら leak-ok: 理由 を付ける。",
            ))
    return hits


# ---------------------------------------------------------------------------
# ファイル走査
# ---------------------------------------------------------------------------

def read_text_or_none(path: Path):
    """テキストとして読めれば文字列を、読めなければ None を返す。"""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:8000]:
        return None
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def load_binary_manifest(path: Path) -> dict[str, str]:
    """承認済みバイナリの ``SHA256  相対パス`` 一覧を読む。

    パスだけの除外では、同じ名前の画像を顧客データへ差し替えても検査を通る。
    内容ハッシュも照合し、差し替え時は再び人の確認を必須にする。
    """
    if not path.exists():
        return {}

    approved: dict[str, str] = {}
    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            raise ValueError(f"{path}:{lineno}: SHA256と相対パスの形式ではありません")
        relpath = parts[1].split(" # ", 1)[0].strip().replace("\\", "/")
        if not relpath or relpath.startswith("/") or ".." in Path(relpath).parts:
            raise ValueError(f"{path}:{lineno}: 安全なリポジトリ相対パスではありません")
        approved[relpath] = parts[0].lower()
    return approved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_candidate_files(root: Path) -> list:
    """os.walkでの走査対象（ディレクトリ名・ファイル名による除外は適用済み）を全て返す。

    Gitでの絞り込みをかける前の候補一覧。絞り込みができない場合はこのリストが
    そのまま検査対象になる（安全側＝広く検査する方向のフォールバック）。
    """
    root_license = (root / ROOT_LICENSE_NAME).resolve()
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIR_NAMES]
        for name in filenames:
            if name in EXCLUDE_FILE_NAMES:
                continue
            p = Path(dirpath) / name
            if p.resolve() == SELF_PATH:
                continue
            # LICENSEはルート直下の1ファイルだけを除外する（深い階層の同名ファイルは検査する）
            if name == ROOT_LICENSE_NAME and p.resolve() == root_license:
                continue
            files.append(p)
    return files


def _run_git(args: list, cwd: Path):
    """git を実行する。成功時は (True, 標準出力バイト列)、失敗時は (False, 理由文字列)。"""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            timeout=30,
        )
    except FileNotFoundError:
        return False, "gitコマンドが見つかりません"
    except OSError as e:
        return False, f"gitの実行に失敗しました: {e}"
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        reason = stderr or f"git {' '.join(args)} が失敗しました（終了コード {result.returncode}）"
        return False, reason
    return True, result.stdout


def list_publishable_relpaths(root: Path):
    """「実際に公開されるファイル」の相対パス（"/" 区切り）集合を返す。

    対象は次の2種類の合計。
      - Gitが追跡しているファイル（git ls-files）: コミット済み・ステージ済み
      - 追跡されていないが .gitignore 等で無視もされていない新規ファイル
        （git ls-files --others --exclude-standard）: git add 前でも気づきたい対象
    .gitignore の否定パターン(!)や除外ルールの解釈は自前でパースせず、gitの
    判定（--exclude-standard）に委ねる。

    戻り値: (パスの集合, None) を返せた場合。gitが使えない／このディレクトリが
    Gitリポジトリでない場合は (None, 理由文字列) を返す。
    """
    ok, reason = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=root)
    if not ok:
        return None, reason

    paths = set()
    for args in (["ls-files", "-z"], ["ls-files", "-z", "--others", "--exclude-standard"]):
        ok, out = _run_git(args, cwd=root)
        if not ok:
            return None, out
        for chunk in out.split(b"\x00"):
            if not chunk:
                continue
            rel = chunk.decode("utf-8", errors="replace").replace("\\", "/")
            paths.add(rel)
    return paths, None


def filter_to_publishable(files: list, root: Path, publishable: set) -> list:
    """候補ファイル一覧を、Gitで公開対象と判定された相対パス集合に絞り込む。"""
    root_resolved = root.resolve()
    kept = []
    for p in files:
        try:
            rel = str(p.resolve().relative_to(root_resolved)).replace(os.sep, "/")
        except ValueError:
            rel = str(p).replace(os.sep, "/")
        if rel in publishable:
            kept.append(p)
    return kept


def run(
    root: Path,
    denylist_path: Path,
    allowlist_path: Path = DEFAULT_ALLOWLIST,
    use_git_scope: bool = True,
    binary_manifest_path: Path | None = None,
    use_denylist: bool = True,
) -> Report:
    report = Report()

    if binary_manifest_path is None:
        binary_manifest_path = root / "tools" / "public-binary-manifest.sha256"
    try:
        approved_binaries = load_binary_manifest(binary_manifest_path)
    except (OSError, UnicodeError, ValueError) as e:
        approved_binaries = {}
        report.binary_manifest_error = f"承認済みバイナリ一覧を読めません: {e}"

    denylist_terms = None
    denylist_error = None
    if not use_denylist:
        denylist_terms = []
        report.denylist_note = "--pattern-only の指定により、秘密辞書を使う2階の照合を省略しました"
    elif not denylist_path.exists():
        denylist_error = f"辞書ファイルが見つかりません: {denylist_path}"
    else:
        try:
            denylist_terms = load_denylist(denylist_path)
            if not denylist_terms:
                denylist_error = f"辞書ファイルは存在しますが中身が空です: {denylist_path}"
        except OSError as e:
            denylist_error = f"辞書ファイルを読めません: {denylist_path} ({e})"

    # 除外リストが無くても検査は成立する（辞書と違い exit 2 にはしない）。
    # 無い/読めない事実だけ案内として残す。
    allowlist = set()
    allowlist_note = None
    if not allowlist_path.exists():
        allowlist_note = f"除外リストが見つかりません（除外なしで検査します）: {allowlist_path}"
    else:
        try:
            allowlist = load_allowlist(allowlist_path)
        except OSError as e:
            allowlist_note = f"除外リストを読めません（除外なしで検査します）: {allowlist_path} ({e})"
    report.allowlist_note = allowlist_note

    # 検査対象を「実際に公開されるファイル」に絞る。既定はGit管理下＋未追跡の新規ファイル。
    candidate_files = collect_candidate_files(root)
    report.candidate_files_total = len(candidate_files)

    target_files = candidate_files
    git_scope_note = None
    if use_git_scope:
        publishable, git_error = list_publishable_relpaths(root)
        if publishable is None:
            # 絞り込みができないだけで検査自体はできるので、辞書欠落と同じexit 2にはしない。
            # 見逃しが最悪という方針に合わせ、安全側（全件検査）にフォールバックする。
            git_scope_note = (
                f"Gitでの絞り込みができないため、全件（Git管理外のファイルを含む）を検査しました。"
                f"理由: {git_error}"
            )
        else:
            target_files = filter_to_publishable(candidate_files, root, publishable)
    report.git_scope_note = git_scope_note

    for path in target_files:
        ext = path.suffix.lower()
        if ext in BINARY_EXTS:
            try:
                rel_str = str(path.resolve().relative_to(root.resolve())).replace(os.sep, "/")
                approved_hash = approved_binaries.get(rel_str)
                if approved_hash and sha256_file(path) == approved_hash:
                    report.approved_binary.append(path)
                else:
                    report.unreadable.append(path)
            except (OSError, ValueError):
                report.unreadable.append(path)
            continue

        text = read_text_or_none(path)
        if text is None:
            report.unreadable.append(path)
            continue

        report.files_scanned += 1
        rel = path
        try:
            rel_str = str(path.resolve().relative_to(root.resolve())).replace(os.sep, "/")
        except ValueError:
            rel_str = str(path).replace(os.sep, "/")

        # テキスト内の画像も承認必須。改行だけを正規化してOS間で同じ承認を使う。
        normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
        embedded_approved = approved_binaries.get(rel_str) == hashlib.sha256(
            normalized_text.encode("utf-8")
        ).hexdigest()
        for lineno, line in enumerate(text.splitlines(), start=1):
            excluded = is_excluded_by_leak_ok(line)

            hits = scan_line_tier1(line)
            if denylist_terms:
                hits += scan_line_tier2(line, denylist_terms)

            b64_hits, b64_review_notes = scan_line_base64(line, denylist_terms)
            hits += b64_hits
            for note in b64_review_notes:
                target = report.approved_embedded if embedded_approved else report.embedded_binary
                target.append((path, lineno, note))

            if excluded:
                continue

            for category, matched, hint in hits:
                if allowlist and is_excluded_by_allowlist(allowlist, rel_str, matched):
                    continue
                report.findings.append(
                    Finding(path=rel, lineno=lineno, category=category, matched=matched, hint=hint)
                )

    report.denylist_error = denylist_error
    return report


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------

def _relpath_str(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _group_findings(findings: list, root: Path):
    """findings を (種別, 検出語) ごとに集約する。

    同じ語・同じ種別が何十件も並ぶと、1件ずつのブロック表示では出力が流れて
    人が読まなくなる。抑制ではなく表示のまとめとして、件数とファイルごとの
    行番号一覧だけを見せる（件数は必ず表示する）。1件ずつ全部見たいときは
    --verbose を使う（print_reportのverbose引数）。

    戻り値: (キーの初出順リスト, {(category, matched): {"hint": ヒント, "by_file": {相対パス: [行番号,...]}}})
    """
    order = []
    groups = {}
    for f in findings:
        key = (f.category, f.matched)
        if key not in groups:
            groups[key] = {"hint": f.hint, "by_file": {}}
            order.append(key)
        relpath = _relpath_str(f.path, root)
        groups[key]["by_file"].setdefault(relpath, []).append(f.lineno)
    return order, groups


def print_report(report: Report, root: Path, verbose: bool = False) -> int:
    findings = report.findings

    print("■ 検査対象の絞り込み")
    if report.git_scope_note:
        print(f"  {report.git_scope_note}")
        print(f"  候補ファイル数: {report.candidate_files_total:,} 件（全件検査）")
    else:
        inspected = report.files_scanned + len(report.unreadable) + len(report.approved_binary)
        excluded = report.candidate_files_total - inspected
        print(
            f"  候補 {report.candidate_files_total:,} ファイル中 "
            f"{inspected:,} 件を検査対象にしました"
            f"（Git管理外のため対象外: {excluded:,} 件）"
        )
    print()

    if findings:
        print("=" * 70)
        print(f"検出: {len(findings)} 件")
        print("=" * 70)

        by_category = {}
        for f in findings:
            by_category.setdefault(f.category, 0)
            by_category[f.category] += 1

        print("\n■ 種別ごとの内訳")
        for cat, n in sorted(by_category.items(), key=lambda kv: -kv[1]):
            print(f"  {cat}: {n:,} 件")

        if verbose:
            print("\n■ 検出箇所（全件）")
            for f in findings:
                try:
                    relpath = f.path.resolve().relative_to(root.resolve())
                except ValueError:
                    relpath = f.path
                print(f"  {relpath}:{f.lineno}")
                print(f"    検出: [{f.category}] {f.matched}")
                print(f"    対処: {f.hint}")
                if f.category == "辞書一致（社名・個人名・クライアント名）":
                    print(
                        "    除外したい場合: 実在の名称でなく日本語の言い回しの一部に "
                        "たまたま一致しただけなら、リポジトリの外にある除外リスト "
                        f"（{Path.home() / '.config' / 'saa' / 'leak-allow.txt'}）に "
                        f"`{relpath}:{f.matched}` を追記する（注記をリポジトリ内に書かない）"
                    )
                else:
                    print("    除外したい場合: この行の末尾に  # leak-ok: 理由  を追記する")
        else:
            order, groups = _group_findings(findings, root)
            print("\n■ 検出箇所（語・種別ごとに集約。全件は --verbose）")
            for category, matched in order:
                info = groups[(category, matched)]
                total = sum(len(linenos) for linenos in info["by_file"].values())
                n_files = len(info["by_file"])
                print(f"  [{category}] {matched}  ―  {total:,} 件 / {n_files:,} ファイル")
                for relpath, linenos in info["by_file"].items():
                    lines_str = ",".join(str(n) for n in linenos)
                    print(f"    {relpath}  ({len(linenos):,} 件: {lines_str})")
                print(f"    対処: {info['hint']}")
                if category == "辞書一致（社名・個人名・クライアント名）":
                    print(
                        "    除外したい場合: 実在の名称でなく日本語の言い回しの一部に "
                        "たまたま一致しただけなら、リポジトリの外にある除外リスト "
                        f"（{Path.home() / '.config' / 'saa' / 'leak-allow.txt'}）に "
                        f"ファイルごとに `<相対パス>:{matched}` の形で追記する（注記をリポジトリ内に書かない）"
                    )
                else:
                    print("    除外したい場合: 該当行の末尾に  # leak-ok: 理由  を追記する")
    else:
        print("パターン一致による検出: 0 件")

    if report.unreadable:
        print("\n" + "=" * 70)
        print(f"■ 検査できないファイル（文字列検索の対象外）: {len(report.unreadable):,} 件")
        print("  画像・PDF・バイナリ等は機械検査できない。人が目で見る必要がある。")
        print("=" * 70)
        for p in report.unreadable:
            try:
                relpath = p.resolve().relative_to(root.resolve())
            except ValueError:
                relpath = p
            print(f"  {relpath}")

    if report.approved_binary:
        print(f"\n承認済みバイナリ（SHA256一致）: {len(report.approved_binary):,} 件")
    if report.approved_embedded:
        print(f"\n承認済み埋め込み画像（テキスト全体のSHA256一致）: {len(report.approved_embedded):,} 件")

    if report.embedded_binary:
        print("\n" + "=" * 70)
        print(f"■ base64/データURIとして埋め込まれた画像等（人の目で確認が必要）: {len(report.embedded_binary):,} 件")
        print("  ベクター画像(SVG等)は文字列に実在の社名が現れないため、パターン検査だけでは検出できない。")
        print("=" * 70)
        for p, lineno, note in report.embedded_binary:
            try:
                relpath = p.resolve().relative_to(root.resolve())
            except ValueError:
                relpath = p
            print(f"  {relpath}:{lineno}")
            print(f"    {note}")

    if report.allowlist_note:
        print("\n" + "=" * 70)
        print("■ 除外リスト（辞書の誤検出を除外する）について")
        print(f"  {report.allowlist_note}")
        print("  無くても検査できていない扱いにはしない（除外なしで検査は成立する）。")
        print("=" * 70)

    if report.denylist_note:
        print("\n" + "=" * 70)
        print(f"■ 辞書照合: {report.denylist_note}")
        print("  公開担当者の最終検査では --pattern-only を外して完全検査してください。")
        print("=" * 70)

    denylist_error = report.denylist_error
    print("\n" + "=" * 70)
    if denylist_error or report.binary_manifest_error:
        print("★ 検査できていません")
        if denylist_error:
            print("  2階の辞書照合が未実行です。")
            print(f"  理由: {denylist_error}")
            print("  保守者は次の場所に辞書ファイルを用意してください（このリポジトリの外）:")
            print(f"    {Path.home() / '.config' / 'saa' / 'denylist.txt'}")
        if report.binary_manifest_error:
            print(f"  理由: {report.binary_manifest_error}")
        print("  このツールはこのプロダクトを開発・公開する側が使う検査ツールです。")
        print("  exit 2 は「検査できていない」であって「検出0件」とは別物です。")
        print("=" * 70)
        return 2

    if findings:
        print(f"検査対象ファイル数: {report.files_scanned:,} / 検出 {len(findings):,} 件")
        print("=" * 70)
        return 1

    if report.unreadable or report.embedded_binary:
        print(
            f"未承認のバイナリ: {len(report.unreadable):,} 件、埋め込み画像: {len(report.embedded_binary):,} 件。"
            "内容を確認し、公開可能なものだけSHA256を承認一覧へ登録してください。"
        )
        print("=" * 70)
        return 1

    print(f"検査対象ファイル数: {report.files_scanned:,} / 検出 0 件")
    print("=" * 70)
    return 0


def main() -> int:
    # Windowsではリダイレクト時に既定エンコーディングがcp932になり日本語出力が
    # 文字化けするため、標準出力/標準エラーをUTF-8に固定する。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    parser = argparse.ArgumentParser(description="公開してはいけない記述の漏れ検査")
    parser.add_argument(
        "root",
        nargs="?",
        default=None,
        help="検査対象ディレクトリ（省略時はこのファイルの1つ上の階層）",
    )
    parser.add_argument(
        "--root",
        dest="root_opt",
        default=None,
        help="検査対象ディレクトリ（位置引数と同じ意味。両方指定時はこちらを優先）",
    )
    parser.add_argument(
        "--denylist",
        default=None,
        help=f"辞書ファイルのパス（省略時は {DEFAULT_DENYLIST}）",
    )
    parser.add_argument(
        "--pattern-only",
        action="store_true",
        help="秘密辞書を使えない公開CI向けに、辞書不要の一般パターンだけを検査する",
    )
    parser.add_argument(
        "--allowlist",
        default=None,
        help=f"除外リストのパス（省略時は {DEFAULT_ALLOWLIST}。無くても検査は成立する）",
    )
    parser.add_argument(
        "--no-git-scope",
        action="store_true",
        help="Gitでの絞り込みをせず、候補ファイルを全件検査する（既定はGit管理下＋未追跡の新規ファイルのみ）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="検出箇所を語・種別ごとに集約せず、1件ずつ全て表示する（既定は集約表示）",
    )
    args = parser.parse_args()

    root_arg = args.root_opt or args.root
    root = Path(root_arg).resolve() if root_arg else SELF_PATH.parent.parent
    denylist_path = Path(args.denylist).expanduser().resolve() if args.denylist else DEFAULT_DENYLIST
    allowlist_path = Path(args.allowlist).expanduser().resolve() if args.allowlist else DEFAULT_ALLOWLIST

    if not root.is_dir():
        print(f"★ 検査対象ディレクトリがありません: {root}", file=sys.stderr)
        return 2

    report = run(
        root,
        denylist_path,
        allowlist_path,
        use_git_scope=not args.no_git_scope,
        use_denylist=not args.pattern_only,
    )
    return print_report(report, root, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
