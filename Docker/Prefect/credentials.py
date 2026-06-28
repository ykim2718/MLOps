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
import re
from pathlib import Path
from typing import List, Optional, Union

from prefect.blocks.core import Block
from prefect.blocks.fields import SecretDict

__version__ = "0.0.16"  # Semantic Versioning:  Version = Major.Minor.Patch

# Prefect block document names allow alphanumeric characters and dashes only (no underscores/spaces/dots).
_BLOCK_NAME_RE = re.compile(r"^[a-zA-Z0-9-]+$")


class Credentials(Block):              # must match pipeline.py exactly (class name + fields)
    minio: SecretDict                  # endpoint, access_key, secret_key
    postgresql_catalog: SecretDict     # endpoint, username, password, database
    postgresql_optuna: SecretDict      # endpoint, username, password, database


def register(spec_path: Union[str, Path], name: Optional[str] = None) -> None:
    """JSON spec 으로 그 팀원의 Credentials 블록을 server 에 save 한다 (이름 우선순위: 인자 > spec['name'] > 파일명)."""
    spec_path = Path(spec_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    name = name or spec.pop("name", None) or spec_path.stem
    spec.pop("name", None)             # drop "name" if present so it is not passed as a block field
    Credentials(**spec).save(name, overwrite=True)
    print(f"[credentials] saved block '{name}'")


def _json_path(value: str) -> Path:
    """argparse type: 존재하는 .json 파일 경로만 통과시킨다."""
    path = Path(value)
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"file not found: {value}")
    if path.suffix.lower() != ".json":
        raise argparse.ArgumentTypeError(f"not a .json file: {value}")
    return path


def _block_name(value: str) -> str:
    """argparse type: Prefect block 이름 규칙(alphanumeric + dashes)에 맞는 문자열만 통과시킨다."""
    if not _BLOCK_NAME_RE.match(value):
        raise argparse.ArgumentTypeError(
            f"invalid block name '{value}': use alphanumeric characters and dashes only"
        )
    return value


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """CLI 인자를 파싱한다 (--block-name -> args.block_name, --json-path -> args.json_path)."""
    parser = argparse.ArgumentParser(description="Register a team member's Credentials block from a JSON spec.")
    parser.add_argument(
        "--json-path", required=True, type=_json_path,
        help="path to an existing <member>.json credential spec",
    )
    parser.add_argument(
        "--block-name", default=None, type=_block_name,
        help="block name, alphanumeric + dashes (default: JSON 'name' field, else file stem)",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    register(args.json_path, args.block_name)
