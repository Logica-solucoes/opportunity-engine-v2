import numpy as np
import pandas as pd

from engine.config import GateThresholds
from engine.sufficiency import CAUSAL_REASONS, assess, spend_cv


def _investment(**channels) -> pd.DataFrame:
    days = pd.date_range("2025-01-01", periods=60)
    rows = [
        {"Date": d, "Product Group": name, "investment": float(v)}
        for name, series in channels.items()
        for d, v in zip(days, series, strict=True)
    ]
    return pd.DataFrame(rows)


VARYING = np.tile([50.0, 150.0], 30)  # mean 100, std 50 -> CV 0.5
FLAT = np.full(60, 100.0)


def _ev(group="A", wmape=0.1):
    return {"product_group": group, "oos_wmape": wmape}


def test_causal_reasons_ids():
    assert CAUSAL_REASONS == ("no_validated_event", "low_spend_variation", "high_oos_wmape")


def test_spend_cv_is_std_over_mean_and_zero_mean_is_zero():
    df = _investment(A=VARYING, B=FLAT, C=np.zeros(60))
    assert spend_cv(df, ["A", "B", "C"]) == {"A": 0.5, "B": 0.0, "C": 0.0}


def test_no_validated_event_fails():
    out = assess([], _investment(A=VARYING), True, GateThresholds())
    assert out.passed is False and out.reasons == ["no_validated_event"] and out.validated_events == 0


def test_a_sound_event_passes():
    out = assess([_ev()], _investment(A=VARYING), True, GateThresholds())
    assert out.passed is True and out.reasons == []
    assert out.validated_events == 1 and out.pre_wmape == 0.1 and out.spend_variation == {"A": 0.5}
    assert out.cv_out_of_sample is True


def test_flat_spend_is_low_variation():
    out = assess([_ev()], _investment(A=FLAT), True, GateThresholds())
    assert out.reasons == ["low_spend_variation"] and out.spend_variation == {"A": 0.0}


def test_median_wmape_above_the_limit_fails():
    out = assess([_ev(wmape=w) for w in (0.1, 0.5, 0.6)], _investment(A=VARYING), True, GateThresholds())
    assert out.pre_wmape == 0.5 and out.reasons == ["high_oos_wmape"]


def test_no_computable_wmape_does_not_fail():
    out = assess([_ev(wmape=None)], _investment(A=VARYING), True, GateThresholds())
    assert out.pre_wmape is None and out.passed is True


def test_in_sample_cv_fails_and_none_does_not():
    inv = _investment(A=VARYING)
    out = assess([_ev()], inv, False, GateThresholds())
    assert out.reasons == ["cv_in_sample"] and out.passed is False and out.cv_out_of_sample is False
    assert assess([_ev()], inv, None, GateThresholds()).passed is True


def test_thresholds_are_configurable():
    inv = _investment(A=VARYING)
    assert assess([_ev()], inv, True, GateThresholds(spend_cv_min=0.9)).reasons == ["low_spend_variation"]
    assert assess([_ev(wmape=0.2)], inv, True, GateThresholds(oos_wmape_max=0.1)).reasons == ["high_oos_wmape"]


def test_a_group_of_channels_checks_each_member():
    inv = _investment(A=VARYING, B=FLAT)
    out = assess([_ev("A, B")], inv, True, GateThresholds())
    assert out.spend_variation == {"A": 0.5, "B": 0.0} and out.reasons == ["low_spend_variation"]
