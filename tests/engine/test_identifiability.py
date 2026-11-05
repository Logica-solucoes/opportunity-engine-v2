import numpy as np

from engine.identifiability import UNIDENTIFIED_KEY, assess, collinear_channels
from engine.results_schema import Collinearity, ValidationReport


def _matrix(**cols) -> tuple[np.ndarray, list[str]]:
    return np.column_stack(list(cols.values())), list(cols)


def _rng():
    return np.random.default_rng(3)


def test_unidentified_key():
    assert UNIDENTIFIED_KEY == "nao_identificavel"


def test_positive_narrow_ci_is_identifiable():
    coefs, cols = _matrix(A=_rng().normal(10, 1, 200))
    out = assess(coefs, cols, 1.0, set())["A"]
    assert out["identifiable"] is True and out["reasons"] == []
    lo, hi = np.percentile(coefs[:, 0], [2.5, 97.5])
    assert out["coef_ci"] == (lo, hi) and out["point"] == coefs[:, 0].mean()


def test_ci_crossing_zero_is_not_identifiable():
    coefs, cols = _matrix(A=_rng().uniform(-5, 15, 200))
    out = assess(coefs, cols, 1.0, set())["A"]
    assert out["identifiable"] is False and out["reasons"] == ["ci_crosses_zero"]


def test_lower_bound_exactly_zero_is_not_identifiable():
    values = np.concatenate([np.zeros(10), _rng().normal(10, 1, 190)])  # 5% of the resamples zero the channel
    coefs, cols = _matrix(A=values)
    assert assess(coefs, cols, 1.0, set())["A"]["reasons"] == ["ci_crosses_zero"]


def test_wide_positive_ci_is_too_wide_unless_the_ratio_allows_it():
    values = _rng().uniform(1, 9, 200)  # lo > 0, width about 7.8 > point about 5
    coefs, cols = _matrix(A=values)
    assert assess(coefs, cols, 1.0, set())["A"]["reasons"] == ["ci_too_wide"]
    assert assess(coefs, cols, 2.0, set())["A"]["identifiable"] is True


def test_zero_point_is_never_identifiable():
    coefs, cols = _matrix(A=np.zeros(200))
    out = assess(coefs, cols, 1.0, set())["A"]
    assert out["identifiable"] is False and out["reasons"] == ["ci_crosses_zero"]


def test_collinear_channel_is_never_identifiable():
    coefs, cols = _matrix(A=_rng().normal(10, 1, 200), B=_rng().uniform(-5, 15, 200))
    out = assess(coefs, cols, 1.0, {"A", "B"})
    assert out["A"]["identifiable"] is False and out["A"]["reasons"] == ["collinearity"]
    assert out["B"]["reasons"] == ["ci_crosses_zero", "collinearity"]


def test_invariant_to_column_order_and_names():
    rng = _rng()
    a, b = rng.normal(10, 1, 200), rng.uniform(-5, 15, 200)
    first = assess(*_matrix(A=a, B=b), 1.0, set())
    other = assess(*_matrix(Z=b, Y=a), 1.0, set())
    assert first["A"] == other["Y"] and first["B"] == other["Z"]


def test_collinear_channels_from_the_report():
    report = ValidationReport(
        ok=False,
        collinearity=Collinearity(
            pairs=[{"a": "A", "b": "B", "r": 0.9}], vif={"C": None, "D": 12.0, "E": 3.0}, suggested_groups=[]
        ),
    )
    assert collinear_channels(report, 10.0) == {"A", "B", "C", "D"}
    assert collinear_channels(None, 10.0) == set()
    assert collinear_channels(ValidationReport(ok=True, collinearity=Collinearity()), 10.0) == set()
