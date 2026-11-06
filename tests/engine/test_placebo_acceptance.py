"""A6 acceptance (docs/m2/trilha-a-motor.md): white noise publishes nothing; a placebo with an effect fails."""

import numpy as np
import pandas as pd
import pytest
from threadpoolctl import threadpool_limits

import engine
from tests.engine.synthetic_data import DAYS, START, dataset_config, make_dataset

NOISE_SEEDS = (1, 2, 3)
YOUTUBE_EVENT = "synthetic_YOUTUBE_2024-10-28"  # pre-period of 300 days: its placebo reads days 150-163


def _run(work, config, inputs):
    with threadpool_limits(limits=1):
        return engine.run(inputs, config, work / "out", lambda level, message: None)


def _module_run(tmp_path_factory, name, config, build):
    mp = pytest.MonkeyPatch()
    mp.setenv("LLM_PROVIDER", "none")
    work = tmp_path_factory.mktemp(name)
    try:
        return _run(work, config, build(work / "data"))
    finally:
        mp.undo()


def make_noise_dataset(out_dir, seed):
    """The default dataset's spend (spikes included) with a KPI of pure noise: no channel moves it."""
    paths = make_dataset(out_dir)
    kpi = 5000.0 * np.random.default_rng(seed).lognormal(0.0, 0.03, DAYS)
    frame = pd.DataFrame({"date": pd.date_range(START, periods=DAYS, freq="D"), "Sessions": kpi})
    frame.to_csv(paths["performance_file"], index=False, date_format="%Y-%m-%d")
    return paths


def with_a_pulse_in_the_pre_period(out_dir):
    paths = make_dataset(out_dir)
    kpi = pd.read_csv(paths["performance_file"])
    kpi.loc[150:163, "Sessions"] *= 1.5
    kpi.to_csv(paths["performance_file"], index=False)
    return paths


@pytest.fixture(scope="module", params=NOISE_SEEDS)
def noise_run(request, tmp_path_factory):
    config = {**dataset_config(), "p_value_threshold": 0.05}  # the engine's default threshold
    return _module_run(
        tmp_path_factory, f"noise{request.param}", config, lambda d: make_noise_dataset(d, request.param)
    )


@pytest.fixture(scope="module")
def injected_run(tmp_path_factory):
    return _module_run(tmp_path_factory, "injected", dataset_config(), with_a_pulse_in_the_pre_period)


@pytest.fixture(scope="module")
def clean_run(tmp_path_factory):
    return _module_run(tmp_path_factory, "clean", dataset_config(), make_dataset)


def test_white_noise_publishes_no_event_and_the_run_is_inconclusive(noise_run):
    assert [e["id"] for e in noise_run["causal"]["events"] if e["status"] == "published"] == []
    assert noise_run["status"] == "inconclusive" and noise_run["causal"]["status"] == "inconclusive"
    assert noise_run["sufficiency"]["passed"] is False


def test_an_effect_injected_in_the_pre_period_fails_the_placebo(injected_run):
    event = next(e for e in injected_run["causal"]["events"] if e["id"] == YOUTUBE_EVENT)

    assert event["status"] == "rejected" and "placebo_failed" in event["reasons"]
    assert event["placebo"]["passed"] is False and event["placebo"]["p_value"] < 0.1


def test_a_real_effect_with_a_clean_pre_period_is_still_published(clean_run):
    published = [e for e in clean_run["causal"]["events"] if e["status"] == "published"]

    assert published and clean_run["sufficiency"]["passed"] is True
    for event in published:
        assert event["placebo"]["passed"] is True and event["fit"]["wmape"] is not None
