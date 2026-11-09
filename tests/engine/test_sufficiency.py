import numpy as np
import pandas as pd
import pytest

from engine import pipeline
from engine.config import EngineConfig
from engine.elasticity_analysis import cv_folds
from engine.sufficiency import assess, spend_cv
from tests.engine.synthetic_data import dataset_config, make_dataset

DATES = pd.date_range("2024-01-01", periods=98, freq="D")
INVESTMENT = pd.concat(
    [
        # weeks alternate 50/150 a day: CV 0.5 on the weekly rate (a daily alternation averages out within the week)
        pd.DataFrame({"Date": DATES, "Product Group": "A", "investment": np.tile(np.repeat([50.0, 150.0], 7), 7)}),
        pd.DataFrame({"Date": DATES, "Product Group": "B", "investment": 100.0}),  # CV 0
    ]
)


def _assess(validated, cv_out_of_sample=True, spend_cv_min=0.10, oos_skill_min=0.10):
    return assess(validated, INVESTMENT, cv_out_of_sample, spend_cv_min, 0.30, oos_skill_min=oos_skill_min)


def test_spend_cv_is_std_over_mean_and_zero_without_spend():
    cv = spend_cv(INVESTMENT, ["A", "B", "Z"])

    assert cv["A"] == pytest.approx(0.5) and cv["B"] == 0.0 and cv["Z"] == 0.0


def test_a_validated_event_on_a_varied_channel_passes():
    verdict = _assess([{"channels": ["A"], "oos_wmape": 0.1}])

    assert verdict.passed and verdict.reasons == []
    assert verdict.validated_events == 1 and verdict.spend_variation == {"A": pytest.approx(0.5)}
    assert verdict.pre_wmape == 0.1 and verdict.cv_out_of_sample is True


def test_each_reason_on_its_own():
    assert _assess([]).reasons == ["no_validated_event"]
    assert _assess([{"channels": ["B"], "oos_wmape": 0.1}]).reasons == ["low_spend_variation"]
    assert _assess([{"channels": ["A"], "oos_wmape": 0.5, "naive_wmape": 0.5}]).reasons == ["high_oos_wmape"]
    assert _assess([{"channels": ["A"], "oos_wmape": 0.1}], cv_out_of_sample=False).reasons == ["cv_in_sample"]


def test_the_run_wmape_is_the_median_of_the_validated_events():
    events = [{"channels": ["A"], "oos_wmape": w} for w in (0.1, 0.5, 0.2, None)]

    assert _assess(events).pre_wmape == 0.2


def test_without_a_computable_wmape_that_check_does_not_fail():
    verdict = _assess([{"channels": ["A"], "oos_wmape": None}])

    assert verdict.passed and verdict.pre_wmape is None


def test_the_thresholds_are_arguments():
    assert _assess([{"channels": ["A"], "oos_wmape": 0.5, "naive_wmape": 0.6}], oos_skill_min=0.15).passed
    assert not _assess([{"channels": ["A"], "oos_wmape": 0.5, "naive_wmape": 0.6}], oos_skill_min=0.2).passed
    assert _assess([{"channels": ["A"], "oos_wmape": 0.1}], spend_cv_min=0.6).reasons == ["low_spend_variation"]


def test_without_a_model_the_cv_is_not_judged():
    assert _assess([{"channels": ["A"], "oos_wmape": 0.1}], cv_out_of_sample=None).passed


def test_the_cv_is_out_of_sample_from_forty_rows():
    assert (cv_folds(39), cv_folds(40), cv_folds(728)) == (1, 2, 3)


def test_the_mmm_records_whether_its_cv_was_out_of_sample(synthetic_computed, tmp_path):
    assert synthetic_computed.mmm["cv_out_of_sample"] is True
    config = EngineConfig.from_input(dataset_config())
    prepared = pipeline.load_inputs(make_dataset(tmp_path, n_days=35), config)

    mmm = pipeline.run_elasticity(prepared, {**config.to_legacy_dict(), "period_days": prepared.period_days})["mmm"]

    assert mmm["cv_out_of_sample"] is False and np.isfinite(mmm["cv_r_squared"])
