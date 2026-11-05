from pathlib import Path

import engine


def validate(inputs: dict[str, Path | None], config: dict) -> dict:
    # a data problem is a check in the report; only a config the engine refuses raises EngineError
    return engine.validate(inputs, config).model_dump(mode="json")
