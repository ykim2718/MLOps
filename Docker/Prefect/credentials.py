# credentials.py — shared Prefect credential block (Credentials) + JSON register CLI.
#
# Defines the one credential Block used across the stack and registers a team member's block from a
# JSON file (block name = the member's name = the file stem, or the JSON "name" field):
#
#     python credentials.py Jason.json        # save a Credentials block named "Jason"
#
# Separation of concerns: the Prefect folder owns the credential block (this file); PrefectWorkflow's
# catalog.py imports it (`from credentials import Credentials`); pipeline.py keeps its own inline copy
# (baked into the flow image, so it must match this class name + fields). Needs prefect installed and
# the Prefect profile's PREFECT_API_URL pointing at the target server.
import json
import os
import sys

from prefect.blocks.core import Block
from prefect.blocks.fields import SecretDict

__version__ = "0.0.10"  # Semantic Versioning:  Version = Major.Minor.Patch


class Credentials(Block):              # must match pipeline.py exactly (class name + fields)
    minio: SecretDict                  # endpoint, access_key, secret_key
    postgresql_catalog: SecretDict     # endpoint, username, password, database
    postgresql_optuna: SecretDict      # endpoint, username, password, database


def register(spec_path):
    """JSON spec 으로 그 팀원의 Credentials 블록을 server 에 save 한다 (이름 = spec['name'] 또는 파일명)."""
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    name = spec.pop("name", None) or os.path.splitext(os.path.basename(spec_path))[0]
    Credentials(**spec).save(name, overwrite=True)
    print(f"[credentials] saved block '{name}'")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python credentials.py <member>.json", file=sys.stderr)
        sys.exit(2)
    register(sys.argv[1])
