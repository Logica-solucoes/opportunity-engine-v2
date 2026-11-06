"""A5 acceptance on more than one draw: the rule must not hold only for the seed it was written against."""

import pytest
from threadpoolctl import threadpool_limits

from engine.config import EngineConfig
from engine.pipeline import compute
from tests.engine.synthetic_data import identifiable_config, make_identifiable_dataset


@pytest.mark.parametrize("seed", [7, 11, 23])
def test_a_strong_channel_is_identifiable_and_a_no_effect_one_is_not(tmp_path, seed):
    inputs = make_identifiable_dataset(tmp_path, seed=seed)

    with threadpool_limits(limits=1):
        verdicts = compute(inputs, EngineConfig.from_input(identifiable_config())).identifiability

    assert verdicts["STRONG"]["identifiable"] is True
    assert verdicts["NOEFFECT"]["identifiable"] is False
