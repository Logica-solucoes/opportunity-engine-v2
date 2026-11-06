from datetime import date
from typing import get_args

import httpx
import pytest

from api import bcb
from engine.config import BcbControl

ROWS = {
    433: [{"data": "01/01/2024", "valor": "0.42"}, {"data": "01/02/2024", "valor": "0.83"}],
    432: [{"data": "01/01/2024", "valor": "11.75"}, {"data": "02/01/2024", "valor": "11.75"}],
}


@pytest.fixture
def sgs(monkeypatch):
    calls = []

    def get(code, start, end):
        calls.append((code, start, end))
        return ROWS[code]

    monkeypatch.setattr(bcb, "get", get)
    return calls


def test_every_engine_control_has_an_sgs_code():
    assert set(bcb.SERIES) == set(get_args(BcbControl))


def test_fetch_joins_the_series_by_date_in_a_fixed_csv(sgs):
    content = bcb.fetch(["bcb_ipca", "bcb_selic"], today=date(2026, 11, 6))

    assert content.decode().splitlines() == [
        "Date,bcb_ipca,bcb_selic",
        "2024-01-01,0.42,11.75",
        "2024-01-02,,11.75",
        "2024-02-01,0.83,",
    ]
    assert [code for code, *_ in sgs] == [433, 432]
    assert sgs[0][1:] == (date(2016, 11, 8), date(2026, 11, 6))  # 3650 days: under the SGS's 10-year cap


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectTimeout("slow"), httpx.HTTPStatusError("503", request=None, response=None), ValueError("bad json")],
)
def test_a_failing_sgs_is_unavailable(monkeypatch, failure):
    def get(code, start, end):
        raise failure

    monkeypatch.setattr(bcb, "get", get)

    with pytest.raises(bcb.Unavailable):
        bcb.fetch(["bcb_ipca"])


def test_an_empty_series_is_unavailable(monkeypatch):
    monkeypatch.setattr(bcb, "get", lambda code, start, end: [])

    with pytest.raises(bcb.Unavailable):
        bcb.fetch(["bcb_ipca"])
