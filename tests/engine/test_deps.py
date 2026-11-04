import importlib

import pytest

PINNED = {
    "numpy": "2.5.0",
    "pandas": "3.0.3",
    "scipy": "1.18.0",
    "statsmodels": "0.14.6",
    "sklearn": "1.9.0",
    "holidays": "0.99",
    "matplotlib": "3.11.0",
}


@pytest.mark.parametrize("module,version", PINNED.items())
def test_numeric_libs_are_pinned(module, version):
    assert importlib.import_module(module).__version__ == version


def test_packages_import():
    import engine
    import llm

    assert engine and llm
