import numpy as np
import pandas as pd
import pytest

from engine.controls import screen_controls


def _frame(**cols) -> pd.DataFrame:
    n = len(next(iter(cols.values())))
    return pd.DataFrame(cols, index=pd.date_range("2024-01-01", periods=n))


def _spend(n=60, seed=1):
    return np.random.default_rng(seed).normal(1000, 200, n)


def test_control_equal_to_spend_plus_noise_is_rejected():
    spend = _spend()
    frame = _frame(A=spend, ctrl=spend + np.random.default_rng(2).normal(0, 20, 60))
    accepted, rejected = screen_controls(frame, ["ctrl"], ["A"], 0.5)
    assert accepted == [] and rejected[0]["name"] == "ctrl" and abs(rejected[0]["r"]) > 0.9


def test_independent_control_is_accepted():
    frame = _frame(A=_spend(), ctrl=_spend(seed=9))
    accepted, rejected = screen_controls(frame, ["ctrl"], ["A"], 0.5)
    assert accepted == ["ctrl"] and rejected == []


def test_sign_does_not_matter():
    spend = _spend()
    frame = _frame(A=spend, ctrl=-spend + np.random.default_rng(2).normal(0, 20, 60))
    _, rejected = screen_controls(frame, ["ctrl"], ["A"], 0.5)
    assert rejected[0]["r"] < -0.9


def test_threshold_is_strict():
    spend = _spend()
    ctrl = spend + np.random.default_rng(2).normal(0, 300, 60)
    r = abs(float(np.corrcoef(spend, ctrl)[0, 1]))
    accepted, _ = screen_controls(_frame(A=spend, ctrl=ctrl), ["ctrl"], ["A"], r)
    assert accepted == ["ctrl"]


def test_several_treated_channels_use_the_summed_spend():
    a, b = _spend(seed=1), _spend(seed=2)
    frame = _frame(A=a, B=b, ctrl=a + b)
    assert screen_controls(frame, ["ctrl"], ["A", "B"], 0.5)[0] == []
    assert screen_controls(frame, ["ctrl"], ["A"], 0.8)[0] == ["ctrl"]


def test_constant_control_is_not_rejected():
    frame = _frame(A=_spend(), ctrl=np.full(60, 5.0))
    accepted, rejected = screen_controls(frame, ["ctrl"], ["A"], 0.5)
    assert accepted == ["ctrl"] and rejected == []


def test_unknown_candidate_is_ignored_and_unknown_treated_channel_raises():
    frame = _frame(A=_spend(), ctrl=_spend(seed=9))
    assert screen_controls(frame, ["ctrl", "nope"], ["A"], 0.5)[0] == ["ctrl"]
    with pytest.raises(ValueError):
        screen_controls(frame, ["ctrl"], ["Z"], 0.5)


def test_order():
    spend = _spend()
    rng = np.random.default_rng(3)
    frame = _frame(
        A=spend,
        zeta=_spend(seed=11),
        alpha=_spend(seed=12),
        mid=spend + rng.normal(0, 150, 60),
        top=spend + rng.normal(0, 10, 60),
    )
    accepted, rejected = screen_controls(frame, ["zeta", "alpha", "mid", "top"], ["A"], 0.5)
    assert accepted == ["alpha", "zeta"]
    assert [r["name"] for r in rejected] == ["top", "mid"]
