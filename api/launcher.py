import subprocess
import sys


def launch(run_id: int) -> None:
    # ponytail: local subprocess only; the Cloud Run Jobs launcher (RUN_ID env override) comes in B11
    subprocess.Popen([sys.executable, "-m", "api.worker", str(run_id)])
