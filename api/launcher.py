import os
import subprocess
import sys

WORKER_ENV = {
    # the models are small: multithreaded BLAS only fights itself (~99 s vs ~40 s) and changes the numbers
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    # until A9 the engine's LLM reports are written to a temp dir and thrown away: no cost, no client data out
    "LLM_PROVIDER": "none",
}


def launch(run_id: int) -> None:
    # ponytail: subprocess on the same server, also in production (no GCP); a queue if runs ever contend for CPU
    subprocess.Popen([sys.executable, "-m", "api.worker", str(run_id)], env={**os.environ, **WORKER_ENV})
