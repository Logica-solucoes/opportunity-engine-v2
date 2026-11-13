import logging
import os
import subprocess
import sys
import threading

from sqlalchemy import func, update

from api.db import SessionLocal
from api.models import ACTIVE_RUN_STATUSES, Run, RunLog

log = logging.getLogger(__name__)

WORKER_ENV = {
    # the models are small: multithreaded BLAS only fights itself (~99 s vs ~40 s) and changes the numbers
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    # the MMM fit is ill-conditioned: the BLAS kernel and numpy's SIMD path move the optimum, so every CPU takes the AVX2 one
    # (same pins in mise.toml and ci.yml; docs/decisoes/engine.md, "Paridade")
    "OPENBLAS_CORETYPE": "Haswell",
    "NPY_DISABLE_CPU_FEATURES": "X86_V4 AVX512_ICL AVX512_SPR",
}


TIMEOUT_EXIT = 124  # the worker's watchdog (api/worker.py); timeout(1)'s code, and not abort()'s 3 on Windows
TIMEOUT_ERROR = (
    "A execução passou do limite de 20 minutos e foi interrompida. Agrupe canais ou encurte o período e rode de novo."
)
CRASH_ERROR = "A execução foi interrompida antes de terminar."


def launch(run_id: int) -> None:
    # ponytail: subprocess on the same server, also in production (no GCP); a queue if runs ever contend for CPU
    # Windows dev: uvicorn --reload sends Ctrl+C to its process group, which killed the worker silently
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        [sys.executable, "-m", "api.worker", str(run_id)], env={**os.environ, **WORKER_ENV}, creationflags=flags
    )
    threading.Thread(target=reap, args=(proc, run_id), daemon=True).start()


def reap(proc, run_id: int) -> None:
    """Waits for the worker (also reaping the zombie) and fails its run at once when it died: OOM, crash, watchdog.
    Exit 0 means the worker wrote the final status itself, or skipped a run that was not queued. If the API restarts
    first, this thread dies with it and the 20-min fail_stale is the net."""
    code = proc.wait()
    if code == 0:
        return
    error = TIMEOUT_ERROR if code == TIMEOUT_EXIT else CRASH_ERROR
    try:
        with SessionLocal() as db:
            failed = db.execute(
                update(Run)
                .where(Run.id == run_id, Run.status.in_(ACTIVE_RUN_STATUSES))
                .values(status="failed", error=error, finished_at=func.now())
            ).rowcount
            if failed:
                db.add(RunLog(run_id=run_id, level="error", message=error))
            db.commit()
    except Exception:  # database down: fail_stale catches the run later; keep the trace in the JSON log
        log.exception("run.reap_failed run_id=%s exit=%s", run_id, code)
        return
    log.warning("run.worker_died run_id=%s exit=%s failed=%s", run_id, code, bool(failed))
