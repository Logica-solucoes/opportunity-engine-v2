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
