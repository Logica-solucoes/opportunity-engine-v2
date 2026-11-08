import os
import subprocess
import sys

WORKER_ENV = {
    # the models are small: multithreaded BLAS only fights itself (~99 s vs ~40 s) and changes the numbers
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    # the MMM fit is ill-conditioned: the BLAS kernel and numpy's SIMD path move the optimum, so every CPU takes the AVX2 one
    # (same pins in mise.toml and ci.yml; docs/decisoes/engine.md, "Paridade")
    "OPENBLAS_CORETYPE": "Haswell",
    "NPY_DISABLE_CPU_FEATURES": "AVX512F AVX512CD AVX512_SKX AVX512_CLX AVX512_CNL AVX512_ICL AVX512_SPR",
}


def launch(run_id: int) -> None:
    # ponytail: subprocess on the same server, also in production (no GCP); a queue if runs ever contend for CPU
    subprocess.Popen([sys.executable, "-m", "api.worker", str(run_id)], env={**os.environ, **WORKER_ENV})
