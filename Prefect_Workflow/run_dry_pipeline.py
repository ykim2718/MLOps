# run_dry_pipeline.py — dry run of pipeline.py: build the per-run folders WITHOUT running the payload.
#
# Same setup as pipeline.py (repo/ git db, script/ worktree, data/ MinIO download) but:
#   - plain script, NO @flow / no Prefect run context (run it straight from a shell).
#   - reads the credential block from the CLI (-b/--block) to resolve MinIO creds.
#   - the team payload (python my_flow.py ...) is NOT executed (commented out below).
#   - the folders are KEPT (not cleaned up) so you can inspect them.
#
#     python run_dry_pipeline.py -b yrocket \
#         --git-repo https://github.com/acme/team.git --git-commit-hash <sha> \
#         --minio-key electric_power_consumption/v1/powerconsumption.csv --minio-host localhost
#
# Needs prefect installed and the profile's PREFECT_API_URL pointing at the server that holds the block.
import argparse
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse

import boto3
from prefect.blocks.core import Block
from prefect.blocks.fields import SecretDict

__version__ = "0.0.2"  # Semantic Versioning:  Version = Major.Minor.Patch


class Credentials(Block):              # same shape as pipeline.py's block (one block, nested dicts)
    minio: SecretDict                  # endpoint, access_key, secret_key
    postgresql_catalog: SecretDict     # endpoint, username, password, database
    postgresql_optuna: SecretDict      # endpoint, username, password, database


def _override_url_host(url: str, host: Optional[str]) -> str:
    """Swap only the host of a URL (keep scheme/port). Used to reach a container endpoint from the host."""
    if not host:
        return url
    u = urlparse(url)
    netloc = f"{host}:{u.port}" if u.port else host
    return urlunparse(u._replace(netloc=netloc))


def dry_run(block: str, git_repo: str, git_commit_hash: str, minio_key: Optional[str] = None,
            minio_bucket: str = "datasets", minio_host: Optional[str] = None,
            base: Optional[str] = None) -> Path:
    """Build repo/ + script/ + data/ for one run; download MinIO if a key is given. Payload is NOT run."""
    base = Path(base) if base else Path(tempfile.mkdtemp(prefix="dry-run-", dir=".")).resolve()
    repo = base / "repo"                           # git database (.git + the fetched commit)
    script = base / "script"                       # worktree: team repo snapshot at the commit
    data = base / "data"                           # MinIO download target
    base.mkdir(parents=True, exist_ok=True)
    print(f"[dry-run] base: {base}")

    # 1) git: shallow-fetch just the one commit into repo/, then expand it into a clean worktree at script/.
    subprocess.run(["git", "init", repo], check=True)
    subprocess.run(["git", "-C", repo, "remote", "add", "origin", git_repo], check=True)
    subprocess.run(["git", "-C", repo, "fetch", "--depth", "1", "origin", git_commit_hash], check=True)
    subprocess.run(["git", "-C", repo, "worktree", "add", "--detach", script, git_commit_hash], check=True)
    print(f"[dry-run] repo   (git db):              {repo}")
    print(f"[dry-run] script (worktree @ {git_commit_hash}): {script}")

    # 2) MinIO: read the block's minio section for creds/endpoint, then download the key into data/.
    data.mkdir(parents=True, exist_ok=True)        # git didn't create data/
    minio = Credentials.load(block).minio.get_secret_value()
    endpoint = _override_url_host(minio["endpoint"], minio_host)
    if minio_key:
        s3 = boto3.client("s3", endpoint_url=endpoint,
                          aws_access_key_id=minio["access_key"],
                          aws_secret_access_key=minio["secret_key"])
        local = data / Path(minio_key).name
        s3.download_file(minio_bucket, minio_key, str(local))
        print(f"[dry-run] data   (MinIO {minio_bucket}/{minio_key} @ {endpoint}): {local}")
    else:
        print(f"[dry-run] data   (empty; no --minio-key, MinIO download skipped): {data}")

    # 3) payload — NOT executed in a dry run. pipeline.py would run the team's my_flow.py here:
    # subprocess.run(["python", "my_flow.py", "--member", block,
    #                 "--git_repo", git_repo, "--git_commit_hash", git_commit_hash,
    #                 "--data_folder", data], cwd=script, check=True)

    print(f"[dry-run] done. folders kept (repo/ script/ data/) under {base}. payload NOT run.")
    return base


def parse_args(argv=None) -> argparse.Namespace:
    """Parse CLI args. The block (-b) is read to resolve MinIO creds; git/minio inputs drive the setup."""
    p = argparse.ArgumentParser(
        prog="run_dry_pipeline.py",
        description=f"run_dry_pipeline.py v{__version__} - build a run's repo/script/data folders "
                    "without running the payload.")
    p.add_argument("-V", "--version", action="version", version=f"run_dry_pipeline.py {__version__}")
    p.add_argument("-b", "--block", required=True,
                   help="credential block name; read MinIO creds from that Prefect block")
    p.add_argument("--git-repo", required=True, help="team repo URL (git remote origin)")
    p.add_argument("--git-commit-hash", required=True, help="commit to fetch (shallow) and check out")
    p.add_argument("--minio-key", default=None,
                   help="object key to download into data/ (omit to skip the MinIO download)")
    p.add_argument("--minio-bucket", default="datasets", help="MinIO bucket (default: datasets)")
    p.add_argument("--minio-host", default=None,
                   help="override the minio endpoint host only, e.g. localhost (for host-side runs)")
    p.add_argument("--base", default=None,
                   help="base folder to build under (default: a kept dry-run-* dir in the current folder)")
    return p.parse_args(argv)


if __name__ == "__main__":
    a = parse_args()
    dry_run(a.block, a.git_repo, a.git_commit_hash, minio_key=a.minio_key,
            minio_bucket=a.minio_bucket, minio_host=a.minio_host, base=a.base)
