"""ブランドカラー（差し色）を1色指定から導出する。

デザインシステムの差し色トークンは `--gold` / `--gold-dark` / `--gold-bright` / `--gold-soft`
の4値セットだが、利用者に4つ入力させるのは酷なので、基準色を1つ（HEX）渡すだけで残りを
自動生成する。

もっとも注意が要るのは `--gold-dark`（`.section-label` や `.highlight-box strong` など、
実際に**文字色として**使われるトークン）で、明るい基準色をそのまま文字色に使うと読めなくなる。
design-system.md に書かれている実例が典型で、`#FFC800` を文字色にすると白背景とのコントラスト比が
1.7:1 しかなく、WCAGの目安（通常サイズの文字で4.5:1以上）を大きく下回る。

このモジュールは色相・彩度を保ったまま明度だけを段階的に下げ、白背景とのコントラスト比が
基準を満たす時点で止める。利用者がどんな明るい色を指定しても、文字として使う `--gold-dark` は
自動的に読める濃さになる。
"""

from __future__ import annotations

import colorsys
import re

# WCAG AA の目安: 通常サイズの文字は4.5:1以上、罫線のような非文字の装飾要素は3:1以上。
# .section-label は11pxなので「大きな文字(18px相当)」の3:1特例は使わず、4.5:1を満たす。
MIN_TEXT_CONTRAST = 4.5
MIN_LINE_CONTRAST = 3.0

_WHITE = (255, 255, 255)
_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


class InvalidColorError(ValueError):
    """指定された色コードが6桁HEXとして不正なときに送出する。"""


def normalize_hex(value: str) -> str:
    """`#D4AF37` / `D4AF37` / `d4af37` を受け付け、`#rrggbb`（小文字）に正規化する。"""
    m = _HEX_RE.match((value or "").strip())
    if not m:
        raise InvalidColorError(
            f"色コードの形式が不正です: {value!r}（6桁HEXで指定してください。例: --accent-color '#1D4ED8'）"
        )
    return "#" + m.group(1).lower()


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = normalize_hex(hex_color)[1:]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = (max(0, min(255, round(c))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _srgb_channel_to_linear(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAGの相対輝度(0〜1)。"""
    r, g, b = rgb
    r_lin, g_lin, b_lin = (
        _srgb_channel_to_linear(r),
        _srgb_channel_to_linear(g),
        _srgb_channel_to_linear(b),
    )
    return 0.2126 * r_lin + 0.7152 * g_lin + 0.0722 * b_lin


def contrast_ratio(rgb_a: tuple[int, int, int], rgb_b: tuple[int, int, int]) -> float:
    """WCAGのコントラスト比(1.0〜21.0)。引数の順序は問わない。"""
    l1 = relative_luminance(rgb_a) + 0.05
    l2 = relative_luminance(rgb_b) + 0.05
    return max(l1, l2) / min(l1, l2)


def _rgb_to_hls(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = (c / 255.0 for c in rgb)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h, l, s


def _hls_to_rgb(h: float, l: float, s: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return round(r * 255), round(g * 255), round(b * 255)


def _darken_until_contrast(
    rgb: tuple[int, int, int], min_contrast: float, *, against: tuple[int, int, int] = _WHITE
) -> tuple[int, int, int]:
    """色相・彩度を保ったまま明度(L)だけを段階的に下げ、対象色とのコントラスト比が
    min_contrast 以上になった時点の色を返す。

    基準色がすでに条件を満たしていれば、そのまま(暗くせず)返す。
    L=0(黒)まで下げても届かない配色は理論上存在しない(黒は白に対してコントラスト比21:1)ため、
    ループは必ず途中で終了する。
    """
    h, l, s = _rgb_to_hls(rgb)
    step = 0.01
    candidate = rgb
    while True:
        candidate = _hls_to_rgb(h, l, s)
        if contrast_ratio(candidate, against) >= min_contrast or l <= 0.0:
            return candidate
        l = max(0.0, l - step)


def derive_palette(base_hex: str) -> dict[str, str]:
    """1色(HEX)から `gold` / `gold-dark` / `gold-bright` / `gold-soft` の4トークンを導出する。

    - `gold`: 基準色そのもの。ただし白地の上で罫線として視認できないほど薄い色
      (白とのコントラスト比が3:1未満)の場合だけ、視認できる濃さまで少し暗くする。
    - `gold-dark`: 文字色用。白背景とのコントラスト比が4.5:1(WCAG AA・通常サイズの文字)を
      満たすまで明度だけを下げる。ここが `#FFC800` のような明るい色を弾く(読める濃さにする)本体。
    - `gold-bright`: 基準色を少し明るくした変種(ホバー等に使う予備トークン)。
    - `gold-soft`: 基準色をごく薄く白へ寄せた、背景用の淡色トークン。
    """
    rgb = hex_to_rgb(base_hex)
    h, l, s = _rgb_to_hls(rgb)

    gold_rgb = rgb
    if contrast_ratio(rgb, _WHITE) < MIN_LINE_CONTRAST:
        gold_rgb = _darken_until_contrast(rgb, MIN_LINE_CONTRAST)

    gold_dark_rgb = _darken_until_contrast(rgb, MIN_TEXT_CONTRAST)

    gold_bright_rgb = _hls_to_rgb(h, min(0.90, l + 0.14), s)
    gold_soft_rgb = _hls_to_rgb(h, 0.96, s * 0.55)

    return {
        "gold": rgb_to_hex(gold_rgb),
        "gold-dark": rgb_to_hex(gold_dark_rgb),
        "gold-bright": rgb_to_hex(gold_bright_rgb),
        "gold-soft": rgb_to_hex(gold_soft_rgb),
    }


def contrast_report(palette: dict[str, str]) -> dict[str, float]:
    """導出済みトークンの、白背景に対するコントラスト比一覧(検証・テスト用)。"""
    return {name: round(contrast_ratio(hex_to_rgb(value), _WHITE), 2) for name, value in palette.items()}
