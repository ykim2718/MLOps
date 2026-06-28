# credentials.py — shared Prefect credential block (Credentials) + JSON register CLI.
#
# Defines the one credential Block used across the stack and registers a team member's block from a
# JSON file. Block name precedence: --block-name > JSON "name" field > file stem.
#
#     python credentials.py --json-path Jason.json                       # block name = file stem "Jason"
#     python credentials.py --json-path Jason.json --block-name alice    # explicit block name "alice"
#
# Separation of concerns: the Prefect folder owns the credential block (this file); PrefectWorkflow's
# catalog.py imports it (`from credentials import Credentials`); pipeline.py keeps its own inline copy
# (baked into the flow image, so it must match this class name + fields). Needs prefect installed and
# the Prefect profile's PREFECT_API_URL pointing at the target server.
import argparse
import json
import os

from prefect.blocks.core import Block
from prefect.blocks.fields import SecretDict

__version__ = "0.0.12"  # Semantic Versioning:  Version = Major.Minor.Patch


class Credentials(Block):              # must match pipeline.py exactly (class name + fields)
    minio: SecretDict                  # endpoint, access_key, secret_key
    postgresql_catalog: SecretDict     # endpoint, username, password, database
    postgresql_optuna: SecretDict      # endpoint, username, password, database


def register(spec_path, name=None):
    """JSON spec 으로 그 팀원의 Credentials 블록을 server 에 save 한다 (이름 우선순위: 인자 > spec['name'] > 파일명)."""
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    name = name or spec.pop("name", None) or os.path.splitext(os.path.basename(spec_path))[0]
    spec.pop("name", None)             # drop "name" if present so it is not passed as a block field
    Credentials(**spec).save(name, overwrite=True)
    print(f"[credentials] saved block '{name}'")


def parse_args(argv=None):
    """CLI 인자를 파싱한다 (--block-name -> args.block_name, --json-path -> args.json_path)."""
    parser = argparse.ArgumentParser(description="Register a team member's Credentials block from a JSON spec.")
    parser.add_argument("--json-path", required=True, help="path to the <member>.json credential spec")
    parser.add_argument("--block-name", default=None, help="block name (default: JSON 'name' field, else file stem)")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    register(args.json_path, args.block_name)
