"""A9: the post-generation check. Fabricated texts against a payload the engine published."""

import pytest

from engine.grounding import check

PAYLOAD = {
    "lift": {"abs": -1234.4, "ci": [-2010.0, -458.7], "rel_pct": -31.08},
    "incremental_investment": 3_412_000.0,
    "fit": {"r2": 0.4567, "wmape": 0.8968},
    "iroas": -0.1712,
    "p_value": 0.0123,
    "ci_level_pct": 95,
    "start": "2025-01-20",
    "end": "2025-02-03",
}
UNIVERSE = {"CANAL_01", "CANAL_02", "CANAL_03"}


def _issues(text, published=frozenset({"CANAL_01"})):
    return check(text, PAYLOAD, set(published), UNIVERSE)


@pytest.mark.parametrize(
    "text",
    [
        "Investimento incremental de R$ 3,4M.",
        "Investimento incremental de R$ 3.412.000,00.",
        "Investimento incremental de 3,41 milhões.",
        "Queda de 1.234 no KPI.",
        "Queda de -1.234 no KPI.",
        "Variação de -31,1%.",
        "Variação de 31%.",
        "WMAPE de 89,7%.",
        "R² de 0,46.",
        "iROAS de -0,17x.",
        "p-valor 0,012.",
        "IC 95% [-2.010; -459].",
        "Entre 20/01/2025 e 2025-02-03, no ano de 2025.",
        "Três canais, 2 semanas e 12 meses.",
        "O CANAL_01 respondeu.",
        "Entre 20 de janeiro de 2025 e 3 de fevereiro.",
    ],
)
def test_legitimate_rounding_passes(text):
    assert _issues(text) == []


@pytest.mark.parametrize(
    "text, value",
    [
        ("Investimento de R$ 5.000.", "R$ 5.000"),
        ("Investimento incremental de R$ 3,5M.", "R$ 3,5M"),
        ("Lift de 1.300 no KPI.", "1.300"),
        ("Alta de 40,2%.", "40,2%"),
        ("Em 21/01/2025 o investimento subiu.", "21/01/2025"),
        ("R² de 0,7.", "0,7"),
        ("Em 21 de janeiro de 2025 o investimento subiu.", "21 de janeiro de 2025"),
        ("Em 25 de março houve alta.", "25 de março"),
    ],
)
def test_an_invented_number_fails(text, value):
    assert _issues(text) == [{"kind": "number", "value": value}]


def test_a_channel_outside_the_published_set_fails_case_insensitively():
    assert _issues("O canal_02 e o CANAL_03 também.") == [
        {"kind": "channel", "value": "CANAL_02"},
        {"kind": "channel", "value": "CANAL_03"},
    ]


def test_a_channel_name_inside_another_word_is_not_a_mention():
    assert _issues("XCANAL_02 e CANAL_02X") == []


def test_numbers_inside_channel_names_are_not_numbers():
    assert check("O CANAL_06 subiu.", {}, {"CANAL_06"}, {"CANAL_06"}) == []
