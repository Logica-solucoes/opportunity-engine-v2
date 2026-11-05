import numpy as np
import pandas as pd
import pytest

from engine.collinearity import analyze, flagged

R_MAX, VIF_MAX = 0.85, 10.0


def _rng():
    return np.random.default_rng(1)


def _wide(**cols) -> pd.DataFrame:
    n = len(next(iter(cols.values())))
    return pd.DataFrame(cols, index=pd.date_range("2024-01-01", periods=n))


def test_pair_above_threshold_is_flagged_with_signed_r():
    a = _rng().normal(100, 20, 60)
    b = a * 1.1 + _rng().normal(0, 2, 60)
    result = analyze(_wide(A=a, B=b), R_MAX, VIF_MAX)
    assert len(result.pairs) == 1
    pair = result.pairs[0]
    assert (pair["a"], pair["b"]) == ("A", "B") and pair["r"] > 0.95 and pair["r"] == round(pair["r"], 4)


def test_negative_correlation_counts():
    a = _rng().normal(100, 20, 60)
    result = analyze(_wide(A=a, B=300 - a + _rng().normal(0, 2, 60)), R_MAX, VIF_MAX)
    assert len(result.pairs) == 1 and result.pairs[0]["r"] < -0.9


def test_threshold_is_strict():
    a = _rng().normal(100, 20, 60)
    b = a + _rng().normal(0, 15, 60)
    r = abs(float(np.corrcoef(a, b)[0, 1]))
    assert analyze(_wide(A=a, B=b), r, VIF_MAX).pairs == []
    assert len(analyze(_wide(A=a, B=b), r - 1e-3, VIF_MAX).pairs) == 1


def test_vif_matches_manual_regression():
    rng = _rng()
    a = rng.normal(100, 20, 30)
    b = 0.5 * a + rng.normal(0, 15, 30)
    c = 0.3 * a - 0.4 * b + rng.normal(0, 10, 30)
    frame = _wide(A=a, B=b, C=c)
    result = analyze(frame, R_MAX, VIF_MAX)
    for name in frame.columns:
        others = np.column_stack([np.ones(30), frame.drop(columns=name).to_numpy()])
        y = frame[name].to_numpy()
        beta = np.linalg.lstsq(others, y, rcond=None)[0]
        r2 = 1 - ((y - others @ beta) ** 2).sum() / ((y - y.mean()) ** 2).sum()
        assert result.vif[name] == pytest.approx(1 / (1 - r2), rel=1e-3)


def test_independent_channels_have_low_vif_and_no_groups():
    rng = _rng()
    result = analyze(
        _wide(A=rng.normal(100, 20, 200), B=rng.normal(80, 10, 200), C=rng.normal(50, 5, 200)), R_MAX, VIF_MAX
    )
    assert result.pairs == [] and result.suggested_groups == []
    assert all(v < 1.5 for v in result.vif.values())


def test_perfect_collinearity_gives_null_vif():
    a = _rng().normal(100, 20, 40)
    result = analyze(_wide(A=a, B=2 * a), R_MAX, VIF_MAX)
    assert result.vif == {"A": None, "B": None}
    pairs, vif_channels = flagged(result, VIF_MAX)
    assert len(pairs) == 1 and vif_channels == ["A", "B"]


def test_constant_and_zero_channels_are_ignored():
    rng = _rng()
    result = analyze(
        _wide(A=rng.normal(100, 20, 40), B=np.full(40, 5.0), C=np.zeros(40), D=rng.normal(9, 2, 40)), R_MAX, VIF_MAX
    )
    assert set(result.vif) == {"A", "D"}
    assert all(p["a"] in "AD" and p["b"] in "AD" for p in result.pairs)


def test_fewer_rows_than_channels_has_empty_vif_but_still_pairs():
    a = np.array([1.0, 2.0, 3.0])
    frame = _wide(A=a, B=a * 2 + np.array([0.0, 0.01, 0.0]), C=np.array([3.0, 1.0, 2.0]), D=np.array([1.0, 5.0, 2.0]))
    result = analyze(frame, R_MAX, VIF_MAX)
    assert result.vif == {} and any((p["a"], p["b"]) == ("A", "B") for p in result.pairs)


def test_single_channel():
    result = analyze(_wide(A=_rng().normal(100, 20, 30)), R_MAX, VIF_MAX)
    assert result.pairs == [] and result.vif == {} and result.suggested_groups == []


def test_suggested_groups_are_connected_components():
    rng = _rng()
    a = rng.normal(100, 20, 80)
    b = a + rng.normal(0, 4, 80)
    c = b + rng.normal(0, 4, 80)
    result = analyze(_wide(A=a, B=b, C=c, D=rng.normal(50, 9, 80)), 0.9, VIF_MAX)
    assert result.suggested_groups == [["A", "B", "C"]]


def test_vif_only_channel_joins_its_most_correlated_partner():
    rng = _rng()
    a, b = rng.normal(100, 20, 300), rng.normal(100, 20, 300)
    c = a + b + rng.normal(0, 0.5, 300)
    result = analyze(_wide(A=a, B=b, C=c), 0.95, VIF_MAX)
    assert result.pairs == []
    _, vif_channels = flagged(result, VIF_MAX)
    assert "C" in vif_channels
    assert any("C" in group for group in result.suggested_groups)


def test_invariant_to_column_order_and_names():
    rng = _rng()
    a = rng.normal(100, 20, 60)
    frame = _wide(A=a, B=a + rng.normal(0, 3, 60), C=rng.normal(50, 9, 60))
    base = analyze(frame, R_MAX, VIF_MAX)
    renamed = frame[["C", "B", "A"]].rename(columns={"A": "X_A", "B": "X_B", "C": "X_C"})
    other = analyze(renamed, R_MAX, VIF_MAX)
    assert [p["r"] for p in other.pairs] == [p["r"] for p in base.pairs]
    assert {k.removeprefix("X_"): v for k, v in other.vif.items()} == base.vif
    assert [[m.removeprefix("X_") for m in g] for g in other.suggested_groups] == base.suggested_groups
