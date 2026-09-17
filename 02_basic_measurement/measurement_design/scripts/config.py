"""計測設計 CLI — 設定モジュール"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
# リポジトリルート（成果物の置き場所は docs/standard-run-order.md §4 の規約:
# `<repo_root>/outputs/{client_id}/` 配下）。
# PROJECT_ROOT = .../02_basic_measurement/measurement_design なので、2階層上がリポジトリルート。
REPO_ROOT = PROJECT_ROOT.parent.parent

DEFAULT_ADC_PATH = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
# サービスアカウント鍵の既定置き場。リポジトリの外、ホームフォルダ配下の ~/.saa/credentials/。
# フォルダごと圧縮・コピーしたときに鍵まで一緒に漏れないよう、リポジトリの中には置かない。
# 準備手順は docs/setup-ga4.md。環境変数 GA4_SA_KEY_PATH で上書き可能（scripts/auth.py 側）。
CREDENTIALS_DIR = Path.home() / ".saa" / "credentials" / "google-analytics"

# client_id の規約は docs/standard-run-order.md §3。`../` 等によるパストラバーサル対策も兼ねる。
CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_client_id(client_id: str) -> str:
    """client_id を検証して返す。不正な場合は ValueError を送出する。

    許可パターンは `^[A-Za-z0-9_-]+$`（docs/standard-run-order.md §3）。
    `/` や `..` を含む値を拒否することで、`--client ../../foo` のようなパストラバーサルを防ぐ。
    """
    if not client_id or not CLIENT_ID_PATTERN.fullmatch(client_id):
        raise ValueError(
            f"client_id が不正です: {client_id!r}"
            "（許可パターン: ^[A-Za-z0-9_-]+$。英数字・アンダースコア・ハイフンのみ使用可）"
        )
    return client_id


@dataclass
class ClientPaths:
    """クライアント1件分のディレクトリ構成。

    - `inputs_dir`: クライアントが用意する入力（KPI・画面遷移・ローカルID設定）。
      従来どおり `{measurement_design}/{client_id}/inputs/` に置く（リポジトリ管理対象）。
    - それ以外（`output_dir`/`data_dir`/`docs_dir`/`report_dir`）は成果物であり、
      リポジトリルートの `outputs/{client_id}/02_measurement/` 配下（docs/standard-run-order.md §4。git管理外）。

    `report_dir` は**納品用に人が手で仕上げた原稿（Markdown・HTML）の置き場所**
    （`verify` の突合対象。README.md 参照）。フォルダ名を `pdf` に戻さないこと
    （PDF以外のHTML等も置くため `pdf` は名前として不正確。過去にレビューで指摘され
    `report` に一本化した）。

    **`report_dir` は他の成果物ディレクトリと違い、ここでは自動作成しない。**
    人が実際に何かを置くまでフォルダが存在しない状態でよく、`data_dir`/`docs_dir` と
    同様に先読みで `mkdir` すると、review を1回実行しただけで「誰も書き込んでいない
    空の report/」がクライアント成果物に混ざる（実際にそうなっていた不具合の修正）。
    """

    inputs_dir: Path
    output_dir: Path
    data_dir: Path
    docs_dir: Path
    report_dir: Path


def resolve_client_paths(client_id: str, *, create: bool = True) -> ClientPaths:
    """client_id からディレクトリ構成を解決する。

    不正な client_id は ValueError を送出する。`create=True`（既定）の場合、
    存在しないディレクトリを作成する。
    """
    validate_client_id(client_id)
    inputs_dir = PROJECT_ROOT / client_id / "inputs"
    output_dir = REPO_ROOT / "outputs" / client_id / "02_measurement"
    paths = ClientPaths(
        inputs_dir=inputs_dir,
        output_dir=output_dir,
        data_dir=output_dir / "_data",
        docs_dir=output_dir / "docs",
        report_dir=output_dir / "report",
    )
    if create:
        # report_dir はここでは作らない（ClientPaths のdocstring参照。人が実際に
        # 納品用の原稿を置くまで存在しない状態でよい。他の3つは各コマンドが
        # 必ず書き込む前提の作業用ディレクトリなので、従来どおり先に作る）。
        for d in (paths.data_dir, paths.docs_dir, paths.inputs_dir):
            d.mkdir(parents=True, exist_ok=True)
    return paths


@dataclass
class AuditConfig:
    """1回の審査・設計実行の設定"""

    property_id: str
    client_name: str

    account_id: str = ""
    gtm_account_id: str = ""
    gtm_container_id: str = ""
    site_url: str = ""
    sc_site_url: str = ""
    industry: str = ""
    auth_method: str = "sa"
    oauth_profile: str = ""
    sa_key_path: str = ""

    output_dir: Path = field(init=False)
    data_dir: Path = field(init=False)
    docs_dir: Path = field(init=False)
    report_dir: Path = field(init=False)
    inputs_dir: Path = field(init=False)

    def __post_init__(self):
        paths = resolve_client_paths(self.client_name)
        self.output_dir = paths.output_dir
        self.data_dir = paths.data_dir
        self.docs_dir = paths.docs_dir
        self.report_dir = paths.report_dir
        self.inputs_dir = paths.inputs_dir

    @property
    def property_resource(self) -> str:
        return f"properties/{self.property_id}"

    @property
    def account_resource(self) -> str:
        return f"accounts/{self.account_id}"
