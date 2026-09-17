"""accent_color.py: 1色(HEX)からデザイントークン一式(gold系4値)を導出する処理のテスト。"""

import pytest

from report_export.accent_color import (
    MIN_LINE_CONTRAST,
    MIN_TEXT_CONTRAST,
    InvalidColorError,
    contrast_ratio,
    derive_palette,
    hex_to_rgb,
    normalize_hex,
)

_WHITE = (255, 255, 255)


def test_normalize_hex_accepts_with_and_without_hash():
    assert normalize_hex("#D4AF37") == "#d4af37"
    assert normalize_hex("D4AF37") == "#d4af37"


def test_normalize_hex_rejects_invalid_format():
    with pytest.raises(InvalidColorError):
        normalize_hex("gold")
    with pytest.raises(InvalidColorError):
        normalize_hex("#12345")  # 5桁
    with pytest.raises(InvalidColorError):
        normalize_hex("")


def test_derive_palette_returns_four_tokens():
    palette = derive_palette("#1D4ED8")
    assert set(palette.keys()) == {"gold", "gold-dark", "gold-bright", "gold-soft"}
    for value in palette.values():
        normalize_hex(value)  # 全部有効なHEXであること


def test_derive_palette_gold_dark_meets_text_contrast_even_for_bright_input():
    """design-system.mdに書かれている実例(#FFC800は白背景で1.7:1しか出ず読めない)と同じ罠を、
    利用者が指定した色でも再現しないことを確認する。"""
    palette = derive_palette("#FFC800")
    ratio = contrast_ratio(hex_to_rgb(palette["gold-dark"]), _WHITE)
    assert ratio >= MIN_TEXT_CONTRAST


@pytest.mark.parametrize(
    "base_hex",
    ["#D4AF37", "#FFC800", "#1D4ED8", "#DC2626", "#059669", "#000000", "#FFFFFF", "#7C3AED"],
)
def test_derive_palette_gold_dark_always_readable_on_white(base_hex):
    palette = derive_palette(base_hex)
    ratio = contrast_ratio(hex_to_rgb(palette["gold-dark"]), _WHITE)
    assert ratio >= MIN_TEXT_CONTRAST, f"{base_hex} -> gold-dark={palette['gold-dark']} ratio={ratio}"


@pytest.mark.parametrize(
    "base_hex",
    ["#D4AF37", "#FFC800", "#1D4ED8", "#DC2626", "#059669", "#FFFFFF", "#7C3AED"],
)
def test_derive_palette_gold_stays_visible_as_a_thin_line_on_white(base_hex):
    palette = derive_palette(base_hex)
    ratio = contrast_ratio(hex_to_rgb(palette["gold"]), _WHITE)
    assert ratio >= MIN_LINE_CONTRAST, f"{base_hex} -> gold={palette['gold']} ratio={ratio}"


def test_derive_palette_black_input_stays_black_family():
    # 既にコントラストが十分な入力(黒)は、暗くしすぎたりしない
    palette = derive_palette("#000000")
    assert palette["gold"] == "#000000"
    assert palette["gold-dark"] == "#000000"


def test_derive_palette_soft_is_a_light_tint_near_white():
    palette = derive_palette("#1D4ED8")
    r, g, b = hex_to_rgb(palette["gold-soft"])
    # gold-softは背景用の淡色トークンなので、白にかなり近いはず
    assert min(r, g, b) > 220


def test_derive_palette_raises_on_invalid_hex():
    with pytest.raises(InvalidColorError):
        derive_palette("not-a-color")


def test_contrast_ratio_is_symmetric():
    a = hex_to_rgb("#1D4ED8")
    b = _WHITE
    assert contrast_ratio(a, b) == contrast_ratio(b, a)


def test_contrast_ratio_of_identical_colors_is_one():
    a = hex_to_rgb("#D4AF37")
    assert contrast_ratio(a, a) == pytest.approx(1.0)
