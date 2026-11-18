import math

import pytest

from app.services.reorder import compute_d_bar, compute_rop, recommended_order_qty


def test_rop_closed_form():
    d_bar, sigma_d, lead_time, z = 4.0, 2.0, 12, 1.65
    expected = (d_bar * lead_time) + z * sigma_d * math.sqrt(lead_time)
    assert compute_rop(d_bar, sigma_d, lead_time, z) == pytest.approx(expected)


def test_d_bar_mean_when_short_history():
    assert compute_d_bar([1, 2, 3, 4]) == pytest.approx(2.5)


def test_d_bar_regression_blend():
    series = [2, 3, 2, 4, 3, 5, 4, 3, 6, 4, 5, 3, 4, 5]
    d = compute_d_bar(series)
    assert d > 0
    assert d >= min(series)


def test_order_qty_respects_moq():
    rop, qty = recommended_order_qty(
        d_bar=5.0, sigma_d=1.5, lead_time=12, on_hand=3, moq=40
    )
    assert rop > 0
    assert qty >= 40