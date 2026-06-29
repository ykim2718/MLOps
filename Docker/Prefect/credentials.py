# credentials.py — shared Prefect credential block (Credentials) + JSON register CLI.
#
# Defines the one credential Block used across the stack and registers a team member's block from a
# JSON file. Block name precedence: --block-name > JSON "name" field > file stem. Prefect requires the
# block name to be lowercase letters, numbers, and dashes only — use a lowercase member name.
#
#     python credentials.py --json-path Jason.json --block-name jason    # save a block named "jason"
#     python credentials.py --json-path Jason.json --block-name alice    # any lowercase block name
#
# Separation of concerns: the Prefect folder owns the credential block (this file); PrefectWorkflow's
# catalog.py imports it (`from credentials import Credentials`); pipeline.py keeps its own inline copy
# (baked into the flow image, so it must match this class name + fields). Needs prefect installed and
# the Prefect profile's PREFECT_API_URL pointing at the target server.
import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Union

from prefect.blocks.core import Block
from prefect.blocks.fields import SecretDict

__version__ = "0.0.18"  # Semantic Versioning:  Version = Major.Minor.Patch

# Prefect block document names allow lowercase letters, numbers, and dashes only (no upper/underscore/space/dot).
_BLOCK_NAME_RE = re.compile(r"^[a-z0-9-]+$")


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
    if not _BLOCK_NAME_RE.match(name):                     # also guards the JSON-name / file-stem path
        raise ValueError(f"invalid block name '{name}': use lowercase letters, numbers, and dashes only")
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
    """argparse type: Prefect block 이름 규칙(lowercase letters, numbers, dashes)에 맞는 문자열만 통과시킨다."""
    if not _BLOCK_NAME_RE.match(value):
        raise argparse.ArgumentTypeError(
            f"invalid block name '{value}': use lowercase letters, numbers, and dashes only"
        )
    return value


def parse_args(argv: Optional[List[str]] = None) -> Optional[argparse.Namespace]:
    """argparse 로 CLI 인자를 파싱한다. 옵션이 없으면 전체 도움말을 출력하고 None 을 돌려준다."""
    parser = argparse.ArgumentParser(description="Register a team member's Credentials block from a JSON spec.")
    parser.add_argument(
        "--json-path", required=True, type=_json_path,
        help="path to an existing <member>.json credential spec",
    )
    parser.add_argument(
        "--block-name", default=None, type=_block_name,
        help="block name, lowercase letters/numbers/dashes (default: JSON 'name' field, else file stem)",
    )
    if not argv:                                           # no options -> show full help on stdout
        parser.print_help()
        return None
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args(sys.argv[1:])
    if args is not None:                                   # None: no options, help already printed
        try:
            register(args.json_path, args.block_name)
        except Exception as e:                             # show a clean message, not a traceback
            print(f"[credentials] error: {e}", file=sys.stderr)
            sys.exit(1)
