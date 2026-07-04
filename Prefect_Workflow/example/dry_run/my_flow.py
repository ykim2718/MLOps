"""example/dry_run/my_flow.py — git-delivered ML payload, Prefect dry run.

Validates workflow wiring only: each @task and config variable stands in for the
real example/ file (train_prepare.py, train_featurize.py, train.py, validate.py,
test_prepare.py, test_featurize.py, test.py, parity_plot.py, prepare.json,
optuna.json). No real ML — every stage just records that it ran, while
train_prepare also counts the files under --data_folder and logs that to the
Prefect run log + MLflow, so `python my_flow.py --data_folder <dir>` walks the
whole prepare -> featurize -> train -> validate / test path end to end.

Run by pipeline.py (orchestrator, prefect.md §4.3):
    python my_flow.py --git_repo <r> --git_commit_hash <c> --member <m> --data_folder <dir>
"""
__version__ = "0.0.5"

import argparse
from pathlib import Path
from typing import Any, Dict

import mlflow
from prefect import flow, get_run_logger, task

State = Dict[str, str]                            # per-stage status map (stage -> "ok") threaded through the flow

prepare: Dict[str, Any] = {"train": {"split": [0.8, 0.2]}}  # stand-in for prepare.json (free-form / nested)
optuna: Dict[str, Any] = {}  # stand-in for optuna.json

STAGES = ("train_prepare", "train_featurize", "train", "validate",
          "test_prepare", "test_featurize", "test", "parity_plot")


@task(task_run_name="train_prepare")
def train_prepare(state: State, data_folder: str) -> State:
    log = get_run_logger()
    data = Path(data_folder)
    n_files = sum(1 for p in data.rglob("*") if p.is_file()) if data.exists() else 0
    log.info(f"train_prepare: {n_files} files under {data_folder}")   # Prefect run log
    mlflow.log_metric("n_data_files", n_files)                        # MLflow (metric -> tracking store)
    return {**state, "train_prepare": "ok"}


@task(task_run_name="train_featurize")
def train_featurize(state: State) -> State:
    return {**state, "train_featurize": "ok"}


@task(task_run_name="train")
def train(state: State) -> State:
    return {**state, "train": "ok"}


@task(task_run_name="validate")
def validate(state: State) -> State:
    return {**state, "validate": "ok"}


@task(task_run_name="test_prepare")
def test_prepare(state: State) -> State:
    return {**state, "test_prepare": "ok"}


@task(task_run_name="test_featurize")
def test_featurize(state: State) -> State:
    return {**state, "test_featurize": "ok"}


@task(task_run_name="test")
def test(state: State) -> State:
    return {**state, "test": "ok"}


@task(task_run_name="parity_plot")
def parity_plot(state: State) -> State:
    return {**state, "parity_plot": "ok"}


@flow(name="my_flow", flow_run_name="{member}@{git_commit_hash}", log_prints=True)
def my_flow(data_folder: str, member: str = "local", git_commit_hash: str = "dryrun",
            git_repo: str = "") -> State:
    log = get_run_logger()
    log.info(f"dry run: member={member} commit={git_commit_hash} "
             f"data={data_folder} prepare={prepare} optuna={optuna}")

    with mlflow.start_run(run_name=f"{member}@{git_commit_hash}"):  # real run -> MLflow server
        s = validate(train(train_featurize(train_prepare({}, data_folder))))  # train branch
        s = test(test_featurize(test_prepare(s)))  # test branch
        s = parity_plot(s)  # parity over both branches

    ran = sorted(s)
    assert set(ran) == set(STAGES), f"missing stages: {set(STAGES) - set(ran)}"
    log.info(f"dry run ok: {len(ran)}/{len(STAGES)} stages ran {ran}")
    return s


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--data_folder", default=".")
    p.add_argument("--member", default="local")
    p.add_argument("--git_commit_hash", default="dryrun")
    p.add_argument("--git_repo", default="")                   # accepted for completeness; unused here
    a = p.parse_args()
    my_flow(a.data_folder, member=a.member, git_commit_hash=a.git_commit_hash, git_repo=a.git_repo)
