"""Google Docs / Google Sheets 書き出し用の認証モジュール。

サービスアカウント認証のみ対応。読み取り専用のGA4サービスアカウントへ編集権限を
追加しないよう、Google出力専用の鍵を使う。環境変数
`SAA_GOOGLE_EXPORT_SA_KEY_PATH`、または既定の
`~/.saa/credentials/google-export/sa-key.json` から読む。

書き込み先のGoogleドキュメント/スプレッドシートには、この鍵ファイルの `client_email` の
値を編集者として共有しておく必要がある（ドメイン全体の委任は不要。Google公式ドキュメントで
確認済み。委任が要るのは人になりすます場合のみ）。

google-auth / google-api-python-client は gdoc/gsheet 出力を使わない利用者に強制しない
任意依存（pyproject.tomlの optional-dependencies "google"）にしているため、実際に使う
関数の中でのみ遅延importする。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Docs/Sheetsへの書き込みに必要なスコープ（README/CLAUDE.mdの調査結果どおり）。
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]

_DEFAULT_SA_KEY_PATH_FALLBACK = (
    Path.home() / ".saa" / "credentials" / "google-export" / "sa-key.json"
)

INSTALL_HINT = (
    "Google出力(gdoc/gsheet)には追加の依存が必要です。次のコマンドで導入してください:\n"
    "  cd common/report_export\n"
    "  uv sync --extra google"
)

_DOC_ID_RE = re.compile(r"/document/d/([a-zA-Z0-9_-]+)")
_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")


def _default_sa_key_path() -> Path:
    """呼び出し時点の環境変数を反映する(import時固定にしない)"""
    return Path(os.environ.get("SAA_GOOGLE_EXPORT_SA_KEY_PATH", str(_DEFAULT_SA_KEY_PATH_FALLBACK)))


def get_credentials(sa_key_path: Path | None = None):
    """サービスアカウント認証情報を返す(Docs/Sheets書き込みスコープ)。"""
    try:
        from google.oauth2 import service_account  # type: ignore
    except ImportError as e:
        raise RuntimeError(INSTALL_HINT) from e

    path = sa_key_path or _default_sa_key_path()
    if not path.exists():
        raise FileNotFoundError(
            f"サービスアカウント鍵が見つかりません: {path}\n"
            f"環境変数 SAA_GOOGLE_EXPORT_SA_KEY_PATH でGoogle出力専用鍵のパスを指定するか、"
            f"{_DEFAULT_SA_KEY_PATH_FALLBACK} に配置してください"
            f"(準備手順は docs/service-account-operations.md)。\n"
            f"また、この鍵ファイルの client_email の値を、書き込み先のGoogleドキュメント/"
            f"スプレッドシートに編集者として共有しておく必要があります"
            f"(サービスアカウントは新規ファイルを自分で作れないため、既存ファイルへの共有が前提)。"
        )
    return service_account.Credentials.from_service_account_file(str(path), scopes=SCOPES)


def build_docs_service(credentials):
    """Google Docs APIクライアントを作る。"""
    try:
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as e:
        raise RuntimeError(INSTALL_HINT) from e
    return build("docs", "v1", credentials=credentials, cache_discovery=False)


def build_sheets_service(credentials):
    """Google Sheets APIクライアントを作る。"""
    try:
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as e:
        raise RuntimeError(INSTALL_HINT) from e
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def extract_doc_id(url_or_id: str) -> str:
    """GoogleドキュメントのURL(またはID)からドキュメントIDを取り出す。

    `https://docs.google.com/document/d/xxxx/edit` のようなURLならIDだけを抜き出す。
    URLの形になっていなければ、そのまま素のIDとして扱う。
    """
    m = _DOC_ID_RE.search(url_or_id)
    return m.group(1) if m else url_or_id


def extract_sheet_id(url_or_id: str) -> str:
    """GoogleスプレッドシートのURL(またはID)からスプレッドシートIDを取り出す。"""
    m = _SHEET_ID_RE.search(url_or_id)
    return m.group(1) if m else url_or_id
