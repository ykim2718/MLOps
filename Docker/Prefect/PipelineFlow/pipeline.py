# pipeline.py — orchestrator; Prefect runs this as the deployment entrypoint.
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import boto3
from prefect import flow, get_run_logger
from prefect.blocks.core import Block
from prefect.blocks.fields import SecretDict

__version__ = "0.0.25"  # Semantic Versioning:  Version = Major.Minor.Patch


class Credentials(Block):              # ONE block holds everything as nested dicts; values hidden
    minio: SecretDict                  # endpoint, access_key, secret_key
    postgresql_catalog: SecretDict     # endpoint, username, password, database
    postgresql_optuna: SecretDict      # endpoint, username, password, database
    mlflow: Optional[SecretDict] = None  # endpoint (MLflow tracking URI); optional so old blocks still load


# flow_run_name shows who submitted the run (e.g. alice@a1b2c3d).
@flow(name="pipeline", flow_run_name="{submitter}@{git_commit_hash}")
def pipeline(*, submitter: str = "", payload: str = "my_flow.py", prefect_block: str = "",
             git_repo: str, git_commit_hash: str, minio_key: str, minio_bucket: str = "datasets") -> None:
    log = get_run_logger()                         # writes to this run's UI logs
    base = Path(tempfile.mkdtemp(prefix="run-"))   # per-run temp dir (removed in finally)
    repo = base / "repo"                           # git database (.git + the fetched commit)
    script = base / "script"                       # worktree: team repo snapshot at the commit
    data = base / "data"                           # MinIO download target
    try:
        # repo/: git database - init, add remote, shallow-fetch the one commit
        subprocess.run(["git", "init", repo], check=True)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin", git_repo], check=True)
        subprocess.run(["git", "-C", repo, "fetch", "--depth", "1", "origin", git_commit_hash], check=True)

        # script/: expand the fetched commit into a clean detached worktree
        subprocess.run(["git", "-C", repo, "worktree", "add", "--detach", script, git_commit_hash], check=True)

        # data/: MinIO download target (git didn't create it)
        data.mkdir(parents=True, exist_ok=True)
        # this run's prefect_block -> its credentials (§6): minio for data, mlflow URI for the payload.
        creds = Credentials.load(prefect_block)
        minio = creds.minio.get_secret_value()
        s3 = boto3.client("s3", endpoint_url=minio["endpoint"],
                          aws_access_key_id=minio["access_key"],
                          aws_secret_access_key=minio["secret_key"])
        # minio_key -> data/: download every object under the key (works for a single file or a whole prefix).
        paginator = s3.get_paginator("list_objects_v2")
        n = 0
        for page in paginator.paginate(Bucket=minio_bucket, Prefix=minio_key):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                rel = key[len(minio_key):].lstrip("/") or Path(key).name  # path under the prefix
                dest = data / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                s3.download_file(minio_bucket, key, str(dest))
                n += 1
        if n == 0:
            raise FileNotFoundError(f"no objects under s3://{minio_bucket}/{minio_key}")
        log.info(f"downloaded {n} object(s) from s3://{minio_bucket}/{minio_key} to {data}")

        # bridge the block's MLflow tracking URI to the payload via env, so my_flow.py logs to the
        # MLflow server instead of a local ./mlruns. set only when the block carries an mlflow endpoint.
        env = os.environ.copy()
        if creds.mlflow is not None:
            mlflow_endpoint = creds.mlflow.get_secret_value().get("endpoint")
            if mlflow_endpoint:
                env["MLFLOW_TRACKING_URI"] = mlflow_endpoint
        # run the team's payload in script/; run identity passed as CLI args; output streams to this run's logs.
        subprocess.run(["python", payload, "--submitter", submitter,
                        "--data_folder", data], cwd=script, env=env, check=True)
    except subprocess.CalledProcessError as e:     # payload exited non-zero (crashed)
        # tag the failure with whose run + message; re-raise -> run marked Failed, logs kept in the UI.
        log.error(f"payload {payload} crashed (exit {e.returncode}) for {submitter}@{git_commit_hash}: {e}")
        raise
    finally:
        shutil.rmtree(base, ignore_errors=True)    # one cleanup removes repo/ + script/ + data/
