# pipeline.py — orchestrator; Prefect runs this as the deployment entrypoint.
import os
import shutil
import subprocess
import tempfile

from prefect import flow


@flow(name="pipeline")
def pipeline(git_repo: str, git_commit: str, minio_version: str, payload: str = "train.py"):
    work = tempfile.mkdtemp(prefix="run-")                                       # private clone dir (per run)
    try:
        subprocess.run(["git", "clone", git_repo, work], check=True)            # fresh clone (small per-member repo)
        subprocess.run(["git", "-C", work, "checkout", git_commit], check=True)  # pin to the requested commit
        env = {**os.environ, "MINIO_VERSION": minio_version}                    # team code reads this version directly from MinIO
        subprocess.run(["python", payload], cwd=work, env=env, check=True)      # run the team's payload script in the private clone
    finally:
        shutil.rmtree(work, ignore_errors=True)                                 # clean up the per-run dir (the container is auto-removed anyway)
