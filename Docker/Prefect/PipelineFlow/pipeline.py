# pipeline.py — orchestrator; Prefect runs this as the deployment entrypoint.
import shutil
import subprocess
import tempfile
from pathlib import Path

import boto3
from prefect import flow, get_run_logger
from prefect.blocks.core import Block
from prefect.blocks.fields import SecretDict

__version__ = "0.0.19"  # Semantic Versioning:  Version = Major.Minor.Patch


class Credentials(Block):              # ONE block holds everything as nested dicts; values hidden
    minio: SecretDict                  # endpoint, access_key, secret_key
    postgresql_catalog: SecretDict     # endpoint, username, password, database
    postgresql_optuna: SecretDict      # endpoint, username, password, database


# flow_run_name shows whose run it is (e.g. alice@a1b2c3d).
@flow(name="pipeline", flow_run_name="{member}@{git_commit_hash}")
def pipeline(git_repo: str, git_commit_hash: str, minio_key: str, minio_bucket: str = "datasets",
             member: str = "", payload: str = "my_flow.py") -> None:
    log = get_run_logger()                         # writes to this run's UI logs
    base = Path(tempfile.mkdtemp(prefix="run-"))   # per-run temp dir (removed in finally)
    repo = base / "repo"                           # git database (.git + the fetched commit)
    script = base / "script"                       # worktree: team repo snapshot at the commit
    data = base / "data"                           # MinIO download target
    try:
        # shallow-fetch just the one commit (no history), then expand it into a clean worktree.
        subprocess.run(["git", "init", repo], check=True)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin", git_repo], check=True)
        subprocess.run(["git", "-C", repo, "fetch", "--depth", "1", "origin", git_commit_hash], check=True)
        subprocess.run(["git", "-C", repo, "worktree", "add", "--detach", script, git_commit_hash], check=True)

        data.mkdir(parents=True, exist_ok=True)    # git didn't create data/
        # this run's member -> their block, minio section (§6).
        minio = Credentials.load(member).minio.get_secret_value()
        s3 = boto3.client("s3", endpoint_url=minio["endpoint"],
                          aws_access_key_id=minio["access_key"],
                          aws_secret_access_key=minio["secret_key"])
        # bucket/key -> data/ (latest; pick a version by its key path). e.g. data/Bennelong Point
        local = data / Path(minio_key).name
        s3.download_file(minio_bucket, minio_key, str(local))

        # run the team's payload in script/; run identity passed as CLI args; output streams to this run's logs.
        subprocess.run(["python", payload, "--member", member,
                        "--git_repo", git_repo, "--git_commit_hash", git_commit_hash,
                        "--data_folder", data], cwd=script, check=True)
    except subprocess.CalledProcessError as e:     # payload exited non-zero (crashed)
        # tag the failure with whose run + message; re-raise -> run marked Failed, logs kept in the UI.
        log.error(f"payload {payload} crashed (exit {e.returncode}) for {member}@{git_commit_hash}: {e}")
        raise
    finally:
        shutil.rmtree(base, ignore_errors=True)    # one cleanup removes repo/ + script/ + data/
