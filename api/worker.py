import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from api import engine_run, simulations, storage
from api.db import SessionLocal
from api.models import Run, RunLog

log = logging.getLogger("api.worker")

FINAL_STATUSES = ("succeeded", "inconclusive", "failed")
ENGINE_ERROR = "O motor falhou. Detalhes técnicos ficam no log do servidor (execução {id})."


class JsonFormatter(logging.Formatter):
    # Cloud Logging reads one JSON object per stdout line; the traceback rides inside `message`
    def format(self, record: logging.LogRecord) -> str:
        entry = {"severity": record.levelname, "message": super().format(record)}
        entry.update({k: getattr(record, k) for k in ("run_id", "workspace_id") if hasattr(record, k)})
        return json.dumps(entry, ensure_ascii=False)


def execute(db: Session, run_id: int) -> None:
    run = db.scalar(
        update(Run)
        .where(Run.id == run_id, Run.status == "queued")
        .values(status="running", started_at=func.now())
        .returning(Run)
    )
    if run is None:
        log.info("worker.skipped run_id=%s", run_id)
        return
    rid, wid, sid, config, files = run.id, run.workspace_id, run.simulation_id, run.config, run.inputs
    db.commit()
    ids = {"run_id": rid, "workspace_id": wid}
    log.info("worker.started run_id=%s", rid, extra=ids)

    def on_log(level: str, message: str) -> None:
        db.add(RunLog(run_id=rid, level=level, message=message))
        # ponytail: one insert per line keeps the "running for N s" honest; batch if the engine gets chatty
        db.commit()

    inputs = {
        key: storage.path(simulations.input_key(wid, sid, f["sha256"])) if f else None for key, f in files.items()
    }
    try:
        with tempfile.TemporaryDirectory() as tmp:
            results = engine_run.run(inputs, config, Path(tmp), on_log)
            if results["status"] not in FINAL_STATUSES:
                raise ValueError(f"engine returned status {results['status']!r}")
            out = Path(tmp) / "results.json"
            out.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
            key = f"ws/{wid}/sim/{sid}/runs/{rid}/results.json"
            storage.put(key, out)
        values = {
            "status": results["status"],
            "engine_version": results["engine_version"],
            "results_uri": key,
            "summary": {"status": results["status"]},
        }
        if results["status"] == "failed":
            values["error"] = ENGINE_ERROR.format(id=rid)
            db.add(RunLog(run_id=rid, level="error", message=values["error"]))
    except Exception:  # any engine failure fails the run; the raw message may be English or carry data
        log.exception("worker.engine_failed run_id=%s", rid, extra=ids)
        db.rollback()
        message = ENGINE_ERROR.format(id=rid)
        db.add(RunLog(run_id=rid, level="error", message=message))
        values = {"status": "failed", "error": message}

    # a run the API already failed as stale stays failed
    applied = db.execute(
        update(Run).where(Run.id == rid, Run.status == "running").values(**values, finished_at=func.now())
    ).rowcount
    db.commit()
    log.info("worker.finished run_id=%s status=%s applied=%s", rid, values["status"], bool(applied), extra=ids)


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    # the Cloud Run Job (B11) passes RUN_ID as an env override; locally the launcher passes it as an argument
    run_id = int(args[0] if args else os.environ["RUN_ID"])
    with SessionLocal() as db:
        execute(db, run_id)


if __name__ == "__main__":
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    # a crash before execute (database down, bad RUN_ID) still reaches Cloud Logging as one JSON line;
    # the run stays queued until the API fails it as stale
    try:
        main()
    except Exception:
        log.exception("worker.crashed")
        sys.exit(1)
