import subprocess
import sys
import threading
from types import SimpleNamespace

from api import launcher, worker
from api.launcher import launch  # the real one: the autouse `launched` fixture patches the module attribute later


def test_launch_pins_blas_to_one_thread_and_keeps_the_llm_setting(monkeypatch):
    calls, reaped = [], []
    proc = SimpleNamespace(wait=lambda: 0)
    monkeypatch.setattr("subprocess.Popen", lambda args, **kw: calls.append((args, kw)) or proc)
    monkeypatch.setattr(launcher, "reap", lambda p, run_id: reaped.append((p, run_id)))
    monkeypatch.setenv("SOMETHING_ELSE", "kept")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")

    launch(7)

    ((args, kw),) = calls
    assert args[-3:] == ["-m", "api.worker", "7"]
    env = kw["env"]
    assert env["OMP_NUM_THREADS"] == env["OPENBLAS_NUM_THREADS"] == env["MKL_NUM_THREADS"] == "1"
    assert env["OPENBLAS_CORETYPE"] == "Haswell"
    assert "X86_V4" in env["NPY_DISABLE_CPU_FEATURES"].split()
    assert env["LLM_PROVIDER"] == "gemini"  # A9: the narratives are grounded, so the worker may call the LLM
    assert env["SOMETHING_ELSE"] == "kept"
    # Windows dev: uvicorn --reload sends Ctrl+C to its process group; the worker must not be in it
    expected = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    assert kw["creationflags"] == expected
    for _ in range(100):
        if reaped:
            break
        threading.Event().wait(0.01)
    assert reaped == [(proc, 7)]


def test_watchdog_exits_the_worker_with_the_timeout_code():
    exited = threading.Event()
    codes = []

    worker.watchdog(0.01, exit=lambda code: (codes.append(code), exited.set()))

    assert exited.wait(2)
    assert codes == [launcher.TIMEOUT_EXIT]
