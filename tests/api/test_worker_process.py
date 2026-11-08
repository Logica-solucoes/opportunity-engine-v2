import threading

from api import worker
from api.launcher import launch  # the real one: the autouse `launched` fixture patches the module attribute later


def test_launch_pins_blas_to_one_thread_and_keeps_the_llm_setting(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.Popen", lambda args, **kw: calls.append((args, kw)))
    monkeypatch.setenv("SOMETHING_ELSE", "kept")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")

    launch(7)

    ((args, kw),) = calls
    assert args[-3:] == ["-m", "api.worker", "7"]
    env = kw["env"]
    assert env["OMP_NUM_THREADS"] == env["OPENBLAS_NUM_THREADS"] == env["MKL_NUM_THREADS"] == "1"
    assert env["LLM_PROVIDER"] == "gemini"  # A9: the narratives are grounded, so the worker may call the LLM
    assert env["SOMETHING_ELSE"] == "kept"


def test_watchdog_exits_the_worker_after_the_deadline():
    exited = threading.Event()
    codes = []

    worker.watchdog(0.01, exit=lambda code: (codes.append(code), exited.set()))

    assert exited.wait(2)
    assert codes == [1]
