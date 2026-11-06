import pytest

from engine.scenario import TCPA_NOTE, TROAS_NOTE, bid_note, ramp

CURVE = [
    {"investment": 0.0, "kpi": 0.0, "kpi_lo": 0.0, "kpi_hi": 0.0},
    {"investment": 200.0, "kpi": 400.0, "kpi_lo": 300.0, "kpi_hi": 500.0},
]


def levels(steps):
    return [s["investment"] for s in steps]


def test_plus_50_percent_in_20_percent_steps_is_three_steps_ending_on_target():
    steps = ramp(100.0, 150.0, 0.2, CURVE)

    assert levels(steps) == pytest.approx([120.0, 144.0, 150.0])
    assert [s["step"] for s in steps] == [1, 2, 3]


def test_minus_50_percent_needs_four_steps_down():
    assert levels(ramp(100.0, 50.0, 0.2, CURVE)) == pytest.approx([80.0, 64.0, 51.2, 50.0])


def test_a_move_within_the_step_needs_no_ramp():
    assert ramp(100.0, 115.0, 0.2, CURVE) is None
    assert ramp(100.0, 120.0, 0.2, CURVE) is None
    assert ramp(100.0, 100.0, 0.2, CURVE) is None


def test_landing_exactly_on_a_step_does_not_add_a_tiny_last_step():
    assert levels(ramp(100.0, 144.0, 0.2, CURVE)) == pytest.approx([120.0, 144.0])


def test_no_ramp_without_a_current_investment():
    assert ramp(0.0, 150.0, 0.2, CURVE) is None
    assert ramp(None, 150.0, 0.2, CURVE) is None


@pytest.mark.parametrize(
    ("current", "target"),
    [(float("nan"), 150.0), (100.0, float("nan")), (float("inf"), 150.0), (100.0, float("inf")), (100.0, -1.0)],
)
def test_a_non_finite_or_negative_investment_gives_no_ramp_instead_of_looping(current, target):
    assert ramp(current, target, 0.2, CURVE) is None


def test_step_kpi_and_band_are_interpolated_on_the_curve():
    first = ramp(100.0, 150.0, 0.2, CURVE)[0]

    assert first["kpi"] == pytest.approx(240.0)
    assert first["kpi_lo"] == pytest.approx(180.0)
    assert first["kpi_hi"] == pytest.approx(300.0)


def test_a_curve_without_band_gives_steps_without_band():
    curve = [{**row, "kpi_lo": None, "kpi_hi": None} for row in CURVE]

    first = ramp(100.0, 150.0, 0.2, curve)[0]

    assert first["kpi"] == pytest.approx(240.0)
    assert first["kpi_lo"] is None and first["kpi_hi"] is None


def test_the_bid_note_follows_the_mode():
    assert bid_note(revenue_mode=False) == TCPA_NOTE
    assert bid_note(revenue_mode=True) == TROAS_NOTE
    assert "tCPA" in TCPA_NOTE and "tROAS" in TROAS_NOTE
