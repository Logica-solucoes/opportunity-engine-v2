import pandas as pd

from engine.grouping import apply_groups, group_name, thresholds


def _long(rows: list[tuple]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["Date", "Product Group", "investment"])
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def _two_days() -> pd.DataFrame:
    return _long(
        [
            ("2024-01-01", "A", 1.0),
            ("2024-01-01", "B", 2.0),
            ("2024-01-01", "C", 4.0),
            ("2024-01-02", "A", 10.0),
            ("2024-01-02", "B", 20.0),
            ("2024-01-02", "C", 40.0),
        ]
    )


def test_group_name_normalizes_and_keeps_config_order():
    assert group_name([" search", "pmax "]) == "SEARCH + PMAX"


def test_apply_groups_sums_members_per_date():
    out, checks = apply_groups(_two_days(), [["a", "b"]])
    assert checks == []
    assert set(out["Product Group"]) == {"A + B", "C"}
    grouped = out[out["Product Group"] == "A + B"].sort_values("Date")["investment"].tolist()
    assert grouped == [3.0, 30.0]
    assert out[out["Product Group"] == "C"].sort_values("Date")["investment"].tolist() == [4.0, 40.0]
    assert list(out.columns) == ["Date", "Product Group", "investment"]


def test_missing_member_row_sums_what_exists():
    df = _long([("2024-01-01", "A", 5.0), ("2024-01-02", "A", 6.0), ("2024-01-02", "B", 7.0)])
    out, checks = apply_groups(df, [["A", "B"]])
    assert checks == []
    assert out.sort_values("Date")["investment"].tolist() == [5.0, 13.0]


def test_unknown_channel():
    df = _two_days()
    out, checks = apply_groups(df, [["A", "X"]])
    assert [c.id for c in checks] == ["group_unknown_channel"]
    assert checks[0].level == "error" and checks[0].details["channels"] == ["X"]
    pd.testing.assert_frame_equal(out, df)


def test_overlap():
    out, checks = apply_groups(_two_days(), [["A", "B"], ["B", "C"]])
    assert [c.id for c in checks] == ["group_overlap"]
    assert checks[0].details["channels"] == ["B"]


def test_too_small():
    for groups in ([["A"]], [["A", "a"]]):
        _, checks = apply_groups(_two_days(), groups)
        assert [c.id for c in checks] == ["group_too_small"], groups


def test_all_channels_in_one_group_leaves_one_channel():
    out, checks = apply_groups(_two_days(), [["A", "B", "C"]])
    assert checks == [] and set(out["Product Group"]) == {"A + B + C"}


def test_no_groups_returns_input_unchanged():
    df = _two_days()
    out, checks = apply_groups(df, [])
    assert checks == []
    pd.testing.assert_frame_equal(out, df)


def test_thresholds_default_and_override():
    assert thresholds({}) == (0.85, 10.0)
    assert thresholds({"gate_thresholds": None}) == (0.85, 10.0)
    assert thresholds({"gate_thresholds": {"collinearity_r": 0.9, "vif_max": 5}}) == (0.9, 5.0)


def test_group_name_equal_to_an_existing_channel_is_an_error():
    df = _long([("2024-01-01", "A", 1.0), ("2024-01-01", "B", 2.0), ("2024-01-01", "A + B", 4.0)])
    out, checks = apply_groups(df, [["A", "B"]])
    assert [c.id for c in checks] == ["group_name_taken"] and checks[0].details["channels"] == ["A + B"]
    pd.testing.assert_frame_equal(out, df)
