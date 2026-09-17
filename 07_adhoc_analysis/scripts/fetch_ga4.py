#!/usr/bin/env python3
"""fetch_ga4.py — 互換シム

実体はリポジトリルートの common/ga4_fetch/fetch_ga4.py（05・06/1・06/2・02 で共通）。
使い方・引数は従来と同一。修正は common 側の1箇所だけ行う。
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def _find_common() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "common" / "ga4_fetch" / "fetch_ga4.py"
        if candidate.exists():
            return candidate
    sys.exit("common/ga4_fetch/fetch_ga4.py が見つかりません（リポジトリ構成を確認してください）")


_real = _find_common()
sys.path.insert(0, str(_real.parent))

if __name__ == "__main__":
    runpy.run_path(str(_real), run_name="__main__")
else:
    import importlib.util as _ilu

    _spec = _ilu.spec_from_file_location("_common_fetch_ga4", _real)
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
