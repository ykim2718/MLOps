"""my_flow.py — git-delivered ML payload (dry run that validates the Prefect workflow).

This is the team payload that pipeline.py (the orchestrator, prefect.md §4.3) runs as:

    python my_flow.py --git_repo <r> --git_commit_hash <c> --member <m> --data <dir>

It wires every example/ stage (train_dp/fe/train/eval + test_dp/fe/test/eval) and
optuna.json into one Prefect flow, running a small but real LightGBM sample so the
whole orchestration path can be validated end to end — no MinIO/GPU needed.

Prefect features exercised: @flow + @task, flow_run_name / task_run_name templating,
tags, retries, log_prints, get_run_logger, a ThreadPoolTaskRunner with .submit()
futures + wait_for for the DAG, result caching (cache_policy), runtime context, and
markdown/table artifacts. Each @task wraps a plain stage function so the stages stay
importable and runnable on their own.
"""
import argparse
import json
import os
from datetime import timedelta

from prefect import flow, get_run_logger, task
from prefect.artifacts import create_markdown_artifact, create_table_artifact
from prefect.cache_policies import INPUTS
from prefect.runtime import flow_run
from prefect.task_runners import ThreadPoolTaskRunner

# example/ stages — every file in this folder is used by the flow below.
import test as test_stage
import test_dp
import test_eval
import test_fe
import train
import train_dp
import train_eval
import train_fe

HERE = os.path.dirname(os.path.abspath(__file__))
OPTUNA_CFG = os.path.join(HERE, "optuna.json")


# ── config: a pure task, cached on its inputs (same path → reuse, skip re-read) ──
@task(name="load_config", cache_policy=INPUTS, cache_expiration=timedelta(hours=1),
      task_run_name="load_config", log_prints=True)
def load_config(optuna_cfg: str) -> dict:
    with open(optuna_cfg, encoding="utf-8") as f:
        cfg = json.load(f)
    print(f"optuna config: {cfg}")
    return cfg


# ── stage tasks: each wraps a plain stage.run(); retries + tags + named runs ──
@task(name="train_dp", task_run_name="train_dp", tags=["train", "dp"],
      retries=2, retry_delay_seconds=2, log_prints=True)
def train_dp_task(work: str):
    return train_dp.run(work)


@task(name="train_fe", task_run_name="train_fe", tags=["train", "fe"],
      retries=2, retry_delay_seconds=2, log_prints=True)
def train_fe_task(work: str, optuna_cfg: str):
    return train_fe.run(work, optuna_cfg)


@task(name="train", task_run_name="train", tags=["train", "model"],
      retries=1, retry_delay_seconds=2, log_prints=True)
def train_task(work: str, optuna_cfg: str):
    return train.run(work, optuna_cfg)


@task(name="train_eval", task_run_name="train_eval", tags=["train", "eval"],
      retries=2, retry_delay_seconds=2, log_prints=True)
def train_eval_task(work: str):
    return train_eval.run(work)


@task(name="test_dp", task_run_name="test_dp", tags=["test", "dp"],
      retries=2, retry_delay_seconds=2, log_prints=True)
def test_dp_task(work: str):
    return test_dp.run(work)


@task(name="test_fe", task_run_name="test_fe", tags=["test", "fe"],
      retries=2, retry_delay_seconds=2, log_prints=True)
def test_fe_task(work: str):
    return test_fe.run(work)


@task(name="test", task_run_name="test", tags=["test", "infer"],
      retries=1, retry_delay_seconds=2, log_prints=True)
def test_task(work: str):
    return test_stage.run(work)


@task(name="test_eval", task_run_name="test_eval", tags=["test", "eval"],
      retries=2, retry_delay_seconds=2, log_prints=True)
def test_eval_task(work: str):
    return test_eval.run(work)


@flow(name="my_flow", flow_run_name="{member}@{git_commit_hash}", log_prints=True,
      task_runner=ThreadPoolTaskRunner(max_workers=4))
def my_flow(data_dir: str, member: str = "local", git_commit_hash: str = "dryrun",
            git_repo: str = ""):
    """Dry-run pipeline: dp → fe → train → eval for train, mirrored for test.

    The eight stages form a DAG; .submit() + wait_for run independent branches
    concurrently (e.g. test_dp alongside train_fe) while preserving dependencies.
    """
    log = get_run_logger()
    work = os.path.join(data_dir, "work")                        # all stage I/O lives under --data (cleaned with the run)
    os.makedirs(work, exist_ok=True)
    log.info(f"dry-run start: member={member} commit={git_commit_hash} repo={git_repo or '-'} work={work}")

    cfg = load_config(OPTUNA_CFG)                                # cached pure task
    log.info(f"tuning {cfg['n_trials']} trials, scaling={cfg['fe']['scaling']}")

    # DAG via futures: edges are expressed with wait_for; independent nodes run in parallel.
    tr_dp = train_dp_task.submit(work)                                          # makes raw/ + interim/train
    te_dp = test_dp_task.submit(work, wait_for=[tr_dp])                         # needs raw/test  ┐ run
    tr_fe = train_fe_task.submit(work, OPTUNA_CFG, wait_for=[tr_dp])            # fits scaler     ┘ in parallel
    tr = train_task.submit(work, OPTUNA_CFG, wait_for=[tr_fe])                  # optuna + lgbm
    tr_eval = train_eval_task.submit(work, wait_for=[tr])
    te_fe = test_fe_task.submit(work, wait_for=[tr_fe, te_dp])                  # reuse fe_train + test interim
    te = test_task.submit(work, wait_for=[tr, te_fe])                           # model + test feature
    te_eval = test_eval_task.submit(work, wait_for=[te])

    train_meta = tr.result()                                     # resolve futures (raises → flow Failed)
    train_metrics = tr_eval.result()
    test_metrics = te_eval.result()

    summary = {"member": member, "git_commit_hash": git_commit_hash,
               "best_params": train_meta["best_params"],
               "best_cv_accuracy": train_meta["best_cv_accuracy"],
               **train_metrics, **test_metrics}
    log.info(f"dry-run done: {summary}")

    _publish_artifacts(summary, train_meta)
    return summary


def _publish_artifacts(summary: dict, train_meta: dict):
    """Surface results in the Prefect UI; best-effort so the dry run never fails on the backend."""
    try:
        rows = [{"metric": k, "value": v} for k, v in summary.items()
                if k in ("best_cv_accuracy", "train_accuracy", "train_f1",
                         "test_accuracy", "test_f1")]
        create_table_artifact(key="dry-run-metrics", table=rows,
                              description="LightGBM dry-run metrics")
        md = (f"# my_flow dry run — `{summary['member']}@{summary['git_commit_hash']}`\n\n"
              f"- flow run: `{flow_run.name}` (`{flow_run.id}`)\n"
              f"- best params: `{train_meta['best_params']}`\n"
              f"- best CV accuracy: **{summary['best_cv_accuracy']}**\n"
              f"- train acc/f1: {summary['train_accuracy']} / {summary['train_f1']}\n"
              f"- test acc/f1: **{summary['test_accuracy']}** / {summary['test_f1']}\n")
        create_markdown_artifact(key="dry-run-summary", markdown=md,
                                 description="my_flow dry-run summary")
    except Exception as e:                                       # no API backend (pure local) → skip artifacts
        get_run_logger().warning(f"artifact publish skipped: {e}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()                               # pipeline.py passes these as CLI args (§4.3)
    p.add_argument("--data", required=True)
    p.add_argument("--member", default="local")
    p.add_argument("--git_commit_hash", default="dryrun")
    p.add_argument("--git_repo", default="")                    # accepted for completeness; unused here
    a = p.parse_args()
    my_flow(a.data, member=a.member, git_commit_hash=a.git_commit_hash, git_repo=a.git_repo)
