# pipeline.py — orchestrator; Prefect runs this as the deployment entrypoint.
import os
import shutil
import subprocess
import tempfile
import boto3
from prefect import flow, get_run_logger
from prefect.blocks.system import Secret


@flow(name="pipeline", flow_run_name="{member}@{git_commit}")                                          # run name shows whose run (e.g. alice@a1b2c3d)
def pipeline(git_repo: str, git_commit: str, minio_key: str, minio_bucket: str = "datasets",
             minio_version: str = "", member: str = "", payload: str = "my_flow.py"):
    log  = get_run_logger()                                                                            # writes to this run's UI logs
    base = tempfile.mkdtemp(prefix="run-")                                                             # per-run temp dir (removed in finally)
    repo = os.path.join(base, "repo")                                                                 # git metadata + full history (.git)
    src  = os.path.join(base, "src")                                                                  # worktree dir: the repo tree at the commit
    data = os.path.join(base, "data")                                                                 # MinIO download target
    try:
        subprocess.run(["git", "init", repo], check=True)                                             # git init creates repo/ (no mkdir needed)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin", git_repo], check=True)
        subprocess.run(["git", "-C", repo, "fetch", "origin"], check=True)                            # full history (past + present commits)
        subprocess.run(["git", "-C", repo, "worktree", "add", "--detach", src, git_commit], check=True)  # expand the commit's tree into src/

        os.makedirs(data, exist_ok=True)                                                              # worktree didn't create data/
        s3 = boto3.client("s3", endpoint_url=Secret.load("minio-endpoint").get(),                     # credentials loaded from Prefect Secret (§5)
                          aws_access_key_id=Secret.load("minio-access-key").get(),
                          aws_secret_access_key=Secret.load("minio-secret-key").get())
        extra = {"VersionId": minio_version} if minio_version else {}                                  # empty → latest version
        local = os.path.join(data, os.path.basename(minio_key))                                        # e.g. data/001.parquet
        s3.download_file(minio_bucket, minio_key, local, ExtraArgs=extra)                              # bucket/key[@version] → data/

        subprocess.run(["python", payload,                                                             # run the team's payload in the worktree
                        "--git_repo", git_repo, "--git_commit", git_commit,                           # run identity, passed as CLI args
                        "--member", member, "--data", data], cwd=src, check=True)                     # stdout/stderr stream to this run's logs
    except subprocess.CalledProcessError as e:                                                         # payload exited non-zero (crashed)
        log.error(f"payload {payload} crashed (exit {e.returncode}) for {member}@{git_commit}: {e}")   # tag the failure with whose run + message
        raise                                                                                          # re-raise → run marked Failed, logs kept in the UI
    finally:
        shutil.rmtree(base, ignore_errors=True)                                                        # one cleanup removes repo/ + src/ + data/
