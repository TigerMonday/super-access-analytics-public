"""gRPC証明書エラーを、現在のプロセス状態に即して案内する。"""

from __future__ import annotations

import os
from pathlib import Path


ENV_NAME = "GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"
CERT_ERROR_MARKERS = (
    "certificate_verify_failed",
    "unable to get local issuer certificate",
    "ssl_error_ssl",
    "certificate verify failed",
)


def validate_configured_roots() -> None:
    """環境変数が設定済みなら、参照先の実在を接続前に確認する。"""
    configured = os.environ.get(ENV_NAME)
    if configured and not Path(configured).is_file():
        raise RuntimeError(
            f"{ENV_NAME} が現在のプロセスに設定されていますが、"
            f"証明書ファイルが見つかりません: {configured}"
        )


def ssl_error_hint(exc: BaseException) -> str | None:
    """証明書系エラーだけに、再起動・一時設定を含む案内を返す。"""
    message = str(exc).lower()
    if not any(marker in message for marker in CERT_ERROR_MARKERS):
        return None

    configured = os.environ.get(ENV_NAME)
    if not configured:
        return (
            f"現在のプロセスでは {ENV_NAME} が未設定です。"
            "setx で永続化した直後は、実行中のターミナルやCodexには反映されません。"
            "アプリ／ターミナルを開き直すか、このプロセスへ一時設定してから再実行してください。"
            "詳細は docs/setup-ga4.md の『証明書のエラーが出るとき』を参照してください。"
        )

    path = Path(configured)
    if not path.is_file():
        return (
            f"{ENV_NAME} は設定されていますが、証明書ファイルが見つかりません: "
            f"{configured}"
        )

    return (
        f"{ENV_NAME} は現在のプロセスに設定され、ファイルも存在します。"
        "証明書ファイルの内容・通信検査ソフトの設定を確認してください。"
    )
