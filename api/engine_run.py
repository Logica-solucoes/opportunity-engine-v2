import os
import time
from collections.abc import Callable
from pathlib import Path

STEPS = [
    "Lendo os arquivos de investimento e performance",
    "Detectando eventos de investimento",
    "Estimando o impacto causal dos eventos",
    "Ajustando as curvas de saturação",
    "Calculando os cenários de orçamento",
    "Montando o resultado",
]


def run(inputs: dict[str, Path | None], config: dict, out_dir: Path, on_log: Callable[[str, str], None]) -> dict:
    # ponytail: stand-in for engine.run (A0/A1, docs/m2/README.md contract §3) that only paces log lines;
    # when engine/ exists this module becomes `from engine import run`
    pause = float(os.environ.get("FAKE_ENGINE_STEP_SECONDS", "1"))
    for i, message in enumerate(STEPS):
        if i:
            time.sleep(pause)
        on_log("info", message)
        if i == 2 and os.environ.get("FAKE_ENGINE_FAIL") == "1":
            raise RuntimeError("fake engine failure: model did not converge")
    on_log("info", "Execução concluída")
    return {
        "schema_version": 1,
        "engine_version": "fake",
        "status": "succeeded",
        "validation": None,
        "sufficiency": None,
        "causal": None,
        "elasticity": None,
        "experiment_design": None,
        "reports": None,
    }
