from engine.config import EngineConfig


def full_config(config: dict | None = None) -> dict:
    """A complete legacy config (every default filled) with `config` laid over it, as `run` hands it to the modules."""
    return {**EngineConfig().to_legacy_dict(), **(config or {})}
