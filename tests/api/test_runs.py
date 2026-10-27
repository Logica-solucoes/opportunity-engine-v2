import pytest

from api import engine_run


def test_fake_engine_logs_each_step_and_returns_a_result(tmp_path):
    lines = []

    result = engine_run.run({}, {}, tmp_path, lambda level, message: lines.append((level, message)))

    assert [m for _, m in lines] == engine_run.STEPS + ["Execução concluída"]
    assert {level for level, _ in lines} == {"info"}
    assert result["schema_version"] == 1 and result["engine_version"] == "fake" and result["status"] == "succeeded"


def test_fake_engine_fails_on_request(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ENGINE_FAIL", "1")

    with pytest.raises(RuntimeError, match="did not converge"):
        engine_run.run({}, {}, tmp_path, lambda level, message: None)
