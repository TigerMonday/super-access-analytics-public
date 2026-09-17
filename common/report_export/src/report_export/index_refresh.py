"""SAAのローカル成果物を書き出した後に、クライアント別の閲覧入口を更新する。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Iterable


def _index_target(artifact_path: Path) -> tuple[Path, Path] | None:
    """成果物パスから (client_dir, builder_path) を返す。

    ``outputs/{client_id}/`` 配下かつ、同じリポジトリに report_index がある場合だけ
    SAAの成果物と判断する。report_exportを単体で別プロジェクトから使う場合は何もしない。
    """

    resolved = artifact_path.resolve()
    for candidate in resolved.parents:
        outputs_dir = candidate.parent
        if outputs_dir.name.casefold() != "outputs":
            continue
        builder = outputs_dir.parent / "common" / "report_index" / "build_index.py"
        if builder.is_file():
            return candidate, builder
        return None
    return None


def report_index_paths(artifact_paths: Iterable[Path]) -> list[Path]:
    """対象成果物に対応する、実在する閲覧入口のパスを重複なく返す。"""

    paths: list[Path] = []
    seen: set[Path] = set()
    for artifact_path in artifact_paths:
        target = _index_target(Path(artifact_path))
        if target is None:
            continue
        client_dir, _ = target
        index_path = (client_dir / "index.html").resolve()
        if index_path.is_file() and index_path not in seen:
            seen.add(index_path)
            paths.append(index_path)
    return paths


def refresh_report_indexes(artifact_paths: Iterable[Path]) -> list[Path]:
    """SAAの成果物に対応する ``index.html`` をクライアント単位で再生成する。

    閲覧入口の更新失敗を隠すと、変換は成功したのに一覧が古い状態になるため、
    report_indexの異常終了はRuntimeErrorとして呼び出し元へ返す。
    """

    targets: dict[Path, Path] = {}
    for artifact_path in artifact_paths:
        target = _index_target(Path(artifact_path))
        if target is not None:
            client_dir, builder = target
            targets[client_dir] = builder

    refreshed: list[Path] = []
    for client_dir, builder in targets.items():
        try:
            subprocess.run(
                [sys.executable, str(builder), str(client_dir)],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = getattr(exc, "stderr", "") or str(exc)
            raise RuntimeError(f"閲覧入口の更新に失敗しました: {detail.strip()}") from exc

        index_path = (client_dir / "index.html").resolve()
        if not index_path.is_file():
            raise RuntimeError(f"閲覧入口が生成されませんでした: {index_path}")
        refreshed.append(index_path)

    return refreshed
