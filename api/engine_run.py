import os
import time
from collections.abc import Callable
from pathlib import Path

import engine

STEPS = [
    "Lendo os arquivos de investimento e performance",
    "Detectando eventos de investimento",
    "Estimando o impacto causal dos eventos",
    "Ajustando as curvas de saturação",
    "Calculando os cenários de orçamento",
    "Montando o resultado",
]


def run(inputs: dict[str, Path | None], config: dict, out_dir: Path, on_log: Callable[[str, str], None]) -> dict:
    if os.environ.get("ENGINE_FAKE") == "1":
        return fake_run(on_log)
    return engine.run(inputs, config, out_dir, on_log)


def fake_run(on_log: Callable[[str, str], None]) -> dict:
    # ponytail: only paces log lines, for the E2E and the API tests; never set ENGINE_FAKE in production
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
