import pytest
from threadpoolctl import threadpool_limits

from engine.config import EngineConfig
from engine.pipeline import compute, load_inputs
from tests.engine.synthetic_data import dataset_config, identifiable_config, make_dataset, make_identifiable_dataset

SHORT = 364  # one year: fast, and still holds the YOUTUBE spike


@pytest.fixture(scope="session")
def synthetic_inputs(tmp_path_factory):
    return make_dataset(tmp_path_factory.mktemp("synthetic_results"), n_days=SHORT)


@pytest.fixture(scope="session")
def synthetic_prepared(synthetic_inputs):
    return load_inputs(synthetic_inputs, EngineConfig.from_input(dataset_config()))


@pytest.fixture(scope="session")
def synthetic_computed(synthetic_inputs):
    with threadpool_limits(limits=1):
        return compute(synthetic_inputs, EngineConfig.from_input(dataset_config()))


@pytest.fixture(scope="session")
def identifiable_computed(tmp_path_factory):
    inputs = make_identifiable_dataset(tmp_path_factory.mktemp("identifiable"))
    with threadpool_limits(limits=1):
        return compute(inputs, EngineConfig.from_input(identifiable_config()))
