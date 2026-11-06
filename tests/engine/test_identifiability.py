from types import SimpleNamespace

import numpy as np
import pytest

from engine import identifiability
from engine.identifiability import UNIDENTIFIED, assess, fold_mix, unidentified


def _mmm(samples: dict[str, list[float]], totals: dict[str, float]) -> dict:
    names = list(samples)
    matrix = np.column_stack([samples[n] for n in names])
    return {
        "spend_cols": names,
        "coef_samples": matrix,
        "channel_totals": np.array([totals[n] for n in names]),
        "model": SimpleNamespace(coef_=matrix.mean(axis=0)),
    }


def test_a_tight_positive_channel_is_identifiable():
    verdict = assess(_mmm({"A": list(np.linspace(0.9, 1.1, 200))}, {"A": 100.0}))["A"]

    assert verdict["identifiable"] is True and verdict["reasons"] == []
    lo, hi = verdict["ci"]
    assert lo == pytest.approx(np.percentile(np.linspace(90, 110, 200), 2.5))
    assert hi == pytest.approx(np.percentile(np.linspace(90, 110, 200), 97.5))


def test_a_channel_zeroed_in_some_resamples_includes_zero():
    samples = [0.0] * 20 + [1.0] * 180  # 10% of resamples zero the channel

    verdict = assess(_mmm({"A": samples}, {"A": 50.0}))["A"]

    assert verdict["identifiable"] is False and "coef_ci_includes_zero" in verdict["reasons"]


def test_a_wide_interval_is_too_wide():
    samples = list(np.linspace(0.2, 3.0, 200))  # all positive, width ≈ 2.7 > mean 1.6

    verdict = assess(_mmm({"A": samples}, {"A": 1.0}))["A"]

    assert verdict["reasons"] == ["coef_ci_too_wide"] and verdict["identifiable"] is False


def test_unidentified_lists_the_failing_channels():
    verdicts = {"A": {"identifiable": True}, "B": {"identifiable": False}}

    assert unidentified(verdicts) == {"B"}
    assert unidentified({}) == set()


def test_fold_mix_sums_the_hidden_channels_and_keeps_the_total():
    mix = {"A": 10.0, "B": 5.0, "C": 2.0}

    folded = fold_mix(mix, {"B", "C"})

    assert folded == {"A": 10.0, UNIDENTIFIED: 7.0}
    assert sum(folded.values()) == sum(mix.values())


def test_fold_mix_without_hidden_channels_is_the_same_mix():
    mix = {"A": 10.0, "B": None}

    assert fold_mix(mix, set()) == mix
    assert fold_mix(mix, {"Z"}) == mix


def test_fold_mix_treats_a_missing_value_as_zero():
    assert fold_mix({"A": 1.0, "B": None}, {"B"}) == {"A": 1.0, UNIDENTIFIED: 0.0}


def test_the_bucket_name_is_shown_as_is():
    assert identifiability.UNIDENTIFIED == "Não identificados"


def test_compute_keeps_the_bootstrap_matrix_and_the_verdicts(synthetic_computed):
    mmm = synthetic_computed.mmm
    assert mmm["coef_samples"].shape == (200, len(mmm["spend_cols"]))
    np.testing.assert_allclose(mmm["coef_samples"].mean(axis=0), mmm["model"].coef_)
    assert set(synthetic_computed.identifiability) == set(mmm["spend_cols"])


def test_the_flat_spend_synthetic_has_no_identifiable_channel(synthetic_computed):
    # spend varies ~3% outside two spikes: the split between channels is not separable (measured 05/nov/2026)
    assert unidentified(synthetic_computed.identifiability) == set(synthetic_computed.mmm["spend_cols"])


def test_a_strong_channel_is_identifiable_and_a_no_effect_one_is_not(identifiable_computed):
    verdicts = identifiable_computed.identifiability
    assert verdicts["STRONG"]["identifiable"] is True
    assert verdicts["NOEFFECT"]["identifiable"] is False
    assert "coef_ci_includes_zero" in verdicts["NOEFFECT"]["reasons"]


def test_the_contribution_log_leaves_out_channels_that_are_not_identifiable(caplog):
    from engine.pipeline import _log_contribution_split

    mmm = {"contribution_pct": {"STRONG": 80.0, "NOEFFECT": 20.0}}
    verdicts = {"STRONG": {"identifiable": True}, "NOEFFECT": {"identifiable": False}}
    with caplog.at_level("INFO", logger="engine.pipeline"):
        _log_contribution_split(mmm, verdicts)

    text = caplog.text
    assert "STRONG: 80.00%" in text
    assert "NOEFFECT" not in text and "20.00" not in text
    assert "1 channel(s) not identifiable" in text
