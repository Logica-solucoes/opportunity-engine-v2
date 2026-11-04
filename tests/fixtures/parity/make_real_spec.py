"""Write the --dataset-json spec for the Gol example data: python -m tests.fixtures.parity.make_real_spec OUT.json"""

import json
import sys
from pathlib import Path

from tests.engine.real_data import gol_spec

if __name__ == "__main__":
    Path(sys.argv[1]).write_text(json.dumps(gol_spec(), indent=1), encoding="utf-8")
