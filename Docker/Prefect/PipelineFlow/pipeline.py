# pipeline.py — orchestrator; Prefect runs this as the deployment entrypoint.
import os
import shutil
import subprocess
import tempfile
import boto3
from prefect import flow, get_run_logger
from prefect.blocks.core import Block
from prefect.blocks.fields import SecretDict

__version__ = "0.0.13"  # Semantic Versioning:  Version = Major.Minor.Patch


class Credentials(Block):                          # ONE block holds everything as nested dicts; values hidden
    minio: SecretDict                              # endpoint, access_key, secret_key
    catalog: SecretDict                            # endpoint, username, password, database
    optuna: SecretDict                             # endpoint, username, password, database


@flow(name="pipeline", flow_run_name="{member}@{git_commit_hash}")                                          # run name shows whose run (e.g. alice@a1b2c3d)
def pipeline(git_repo: str, git_commit_hash: str, minio_key: str, minio_bucket: str = "datasets",
             member: str = "", payload: str = "my_flow.py"):
    log    = get_run_logger()                                                                         # writes to this run's UI logs
    base   = tempfile.mkdtemp(prefix="run-")                                                          # per-run temp dir (removed in finally)
    repo   = os.path.join(base, "repo")                                                               # git database (.git + the fetched commit)
    script = os.path.join(base, "script")                                                             # worktree: team repo snapshot at the commit
    data   = os.path.join(base, "data")                                                               # MinIO download target
    try:
        subprocess.run(["git", "init", repo], check=True)                                             # git init creates repo/ (no mkdir needed)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin", git_repo], check=True)
        subprocess.run(["git", "-C", repo, "fetch", "--depth", "1", "origin", git_commit_hash], check=True)  # just that commit (shallow; no history)
        subprocess.run(["git", "-C", repo, "worktree", "add", "--detach", script, git_commit_hash], check=True)  # expand the commit into script/ (clean worktree)

        os.makedirs(data, exist_ok=True)                                                              # git didn't create data/
        minio = Credentials.load("Jason").minio.get_secret_value()                                    # one block -> minio section (§6)
        s3 = boto3.client("s3", endpoint_url=minio["endpoint"],
                          aws_access_key_id=minio["access_key"],
                          aws_secret_access_key=minio["secret_key"])
        local = os.path.join(data, os.path.basename(minio_key))                                        # e.g. data/Bennelong Point
        s3.download_file(minio_bucket, minio_key, local)                                               # bucket/key → data/ (latest; pick a version by its key path)

        subprocess.run(["python", payload,                                                             # run the team's payload in script/
                        "--git_repo", git_repo, "--git_commit_hash", git_commit_hash,                           # run identity, passed as CLI args
                        "--member", member, "--data", data], cwd=script, check=True)                     # stdout/stderr stream to this run's logs
    except subprocess.CalledProcessError as e:                                                         # payload exited non-zero (crashed)
        log.error(f"payload {payload} crashed (exit {e.returncode}) for {member}@{git_commit_hash}: {e}")   # tag the failure with whose run + message
        raise                                                                                          # re-raise → run marked Failed, logs kept in the UI
    finally:
        shutil.rmtree(base, ignore_errors=True)                                                        # one cleanup removes repo/ + script/ + data/
