"""my_flow.py - PHM 2016 CMP virtual-metrology flow (entrypoint).

Predicts wafer AVG_REMOVAL_RATE (a scalar / regression target) from CMP tool
sensor trajectories with LightGBM - the same Virtual Metrology shape as film
thickness / etch-rate prediction. Run as the team payload that pipeline.py drives:

    python my_flow.py --git_repo <r> --git_commit_hash <c> --member <m> --data_folder ./data

Pipeline (a small DAG): load_config -> prepare -> train -> (evaluate || predict).
prepare reads CMP-training-*.csv (25 columns x1..x25, no header) and the
CMP-training-removalrate.csv target, aggregates each (WAFER_ID, STAGE) trajectory
into per-wafer statistics, and carves a validation split. train runs Optuna over
LGBMRegressor; evaluate scores RMSE/MAE/R2 on the held-out wafers; predict (if a
test set is present) writes the challenge-format CMP-test-removalrate.csv.

Prefect features exercised: @flow + @task, flow_run_name / task_run_name templating,
tags, retries, log_prints, get_run_logger, ThreadPoolTaskRunner with .submit()
futures + wait_for for the DAG, runtime context, and markdown/table artifacts.
Optuna trials are logged to a SQLite study so they can be viewed in optuna-dashboard.
"""
import argparse
import json
import os
import re

import numpy as np
import pandas as pd
from prefect import flow, get_run_logger, task
from prefect.artifacts import create_markdown_artifact, create_table_artifact
from prefect.runtime import flow_run
from prefect.task_runners import ThreadPoolTaskRunner

# Credentials block class (defined in Prefect/credentials.py). Optional import so the flow
# still parses without it; in production pipeline.py provides it on the path, same as catalog.py.
try:
    from credentials import Credentials
except Exception:
    Credentials = None

HERE = os.path.dirname(os.path.abspath(__file__))
OPTUNA_CFG = os.path.join(HERE, "optuna.json")

# Dev-only fallback; the real DSN comes from the member's postgresql_optuna block.
_OPTUNA_DEFAULT = {"endpoint": "localhost:5432", "username": "postgres",
                   "password": "postgres", "database": "optuna"}

# 25 positional columns (CSVs are header-less) - PHM 2016 CFP, Table 1.
COLS = [
    "MACHINE_ID", "MACHINE_DATA", "TIMESTAMP", "WAFER_ID", "STAGE", "CHAMBER",
    "USAGE_OF_BACKING_FILM", "USAGE_OF_DRESSER", "USAGE_OF_POLISHING_TABLE",
    "USAGE_OF_DRESSER_TABLE", "PRESSURIZED_CHAMBER_PRESSURE",
    "MAIN_OUTER_AIR_BAG_PRESSURE", "CENTER_AIR_BAG_PRESSURE",
    "RETAINER_RING_PRESSURE", "RIPPLE_AIR_BAG_PRESSURE", "USAGE_OF_MEMBRANE",
    "USAGE_OF_PRESSURIZED_SHEET", "SLURRY_FLOW_LINE_A", "SLURRY_FLOW_LINE_B",
    "SLURRY_FLOW_LINE_C", "WAFER_ROTATION", "STAGE_ROTATION", "HEAD_ROTATION",
    "DRESSING_WATER_STATUS", "EDGE_AIR_BAG_PRESSURE",
]
KEY = ["WAFER_ID", "STAGE"]                                   # a wafer is processed in stage A and/or B
# x7..x25: the 19 process variables aggregated per trajectory into features.
PROCESS_VARS = COLS[6:]


# ── config: read fresh each run so edits to optuna.json always take effect ──
@task(name="load_config", task_run_name="load_config", log_prints=True)
def load_config(optuna_cfg: str) -> dict:
    with open(optuna_cfg, encoding="utf-8") as f:
        cfg = json.load(f)
    print(f"optuna config: {cfg}")
    return cfg


def _mask(dsn: str) -> str:
    """Hide the password in a DSN before logging it."""
    return re.sub(r"(://[^:/@]+:)[^@]*(@)", r"\1***\2", dsn)


def _optuna_storage(cfg: dict, member: str) -> tuple:
    """Optuna storage URL = the member's postgresql_optuna Credentials block (the team DB).

    `cfg['storage']` overrides (e.g. a test DSN); otherwise the DSN is built from the
    `postgresql_optuna` section of `Credentials.load(member)`, exactly like catalog.py.
    Falls back to a localhost optuna DB if the block / prefect is unavailable. The block
    holds host `postgres` (the compose-network name), so a live connect needs the flow to
    run inside that network - which is how pipeline.py runs this payload in production.
    """
    override = cfg.get("storage")
    if override:
        return override, "config"
    sect, src = _OPTUNA_DEFAULT, "default (localhost optuna)"
    if Credentials is not None and member:
        try:
            sect = Credentials.load(member).postgresql_optuna.get_secret_value()
            src = f"prefect-block (member={member})"
        except Exception:                                        # block missing / server down
            pass
    host, _, port = sect["endpoint"].partition(":")
    dsn = f"postgresql://{sect['username']}:{sect['password']}@{host}:{port or '5432'}/{sect['database']}"
    return dsn, src


def _mlflow_start(uri: str, experiment: str, run_name: str):
    """Best-effort MLflow run: set tracking URI + experiment, start a run, and return the
    mlflow module - or None if the server is unreachable (so a local dry run never fails on it).
    The caller logs per-trial metrics through the returned module, then calls end_run()."""
    if not uri:
        return None
    try:
        import mlflow
        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment(experiment)
        mlflow.start_run(run_name=run_name or None)
        print(f"MLflow logging to {uri} (experiment={experiment})")
        return mlflow
    except Exception as e:                                    # server down / mlflow missing -> skip
        print(f"MLflow disabled (cannot use {uri}): {e}")
        return None


def _read_trajectories(paths: list) -> pd.DataFrame:
    """Concatenate CMP CSVs (the real files carry a header; tolerate header-less too)."""
    frames = []
    for p in paths:
        df = pd.read_csv(p)
        if "WAFER_ID" not in df.columns or "STAGE" not in df.columns:   # header-less variant
            df = pd.read_csv(p, header=None).iloc[:, -len(COLS):]
            df.columns = COLS
        else:
            df = df[[c for c in COLS if c in df.columns]]
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    for c in out.columns:
        if c != "STAGE":
            out[c] = pd.to_numeric(out[c], errors="coerce")
    out["STAGE"] = out["STAGE"].astype(str).str.strip()
    return out


def _featurize(traj: pd.DataFrame) -> pd.DataFrame:
    """Aggregate each (WAFER_ID, STAGE) trajectory into one feature row."""
    traj = traj.sort_values(KEY + ["TIMESTAMP"])
    aggs = ["mean", "std", "min", "max", "median"]
    feat = traj.groupby(KEY)[PROCESS_VARS].agg(aggs)
    feat.columns = [f"{c}_{a}" for c, a in feat.columns]

    # shape features: trajectory length, polish duration, last/first/slope per var
    g = traj.groupby(KEY)
    feat["n_samples"] = g["TIMESTAMP"].size()
    feat["duration"] = g["TIMESTAMP"].max() - g["TIMESTAMP"].min()
    first = g[PROCESS_VARS].first()
    last = g[PROCESS_VARS].last()
    dur = feat["duration"].replace(0, np.nan)
    for v in PROCESS_VARS:
        feat[f"{v}_last"] = last[v]
        feat[f"{v}_delta"] = last[v] - first[v]
        feat[f"{v}_slope"] = (last[v] - first[v]) / dur
    feat["stage_is_B"] = (feat.index.get_level_values("STAGE") == "B").astype(int)
    return feat.reset_index()


@task(name="prepare", task_run_name="prepare", tags=["cmp", "dp", "fe"],
      retries=2, retry_delay_seconds=2, log_prints=True)
def prepare(data_dir: str, work: str, cfg: dict) -> dict:
    """Read training trajectories + target, build per-wafer features, split train/val."""
    train_files = sorted([os.path.join(data_dir, f) for f in os.listdir(data_dir)
                          if f.startswith("CMP-training-") and f[13:14].isdigit()])
    rate_path = os.path.join(data_dir, "CMP-training-removalrate.csv")
    if not train_files or not os.path.exists(rate_path):
        raise FileNotFoundError(
            f"missing CMP-training-*.csv / CMP-training-removalrate.csv in {data_dir}. "
            "Run  python download_data.py  first.")
    print(f"reading {len(train_files)} trajectory files + target")

    traj = _read_trajectories(train_files)
    rate = pd.read_csv(rate_path)
    rate.columns = [c.strip().upper() for c in rate.columns]
    rate = rate.rename(columns={"AVG_REMOVAL_RATE": "y"})
    rate["STAGE"] = rate["STAGE"].astype(str).str.strip()
    rate["y"] = pd.to_numeric(rate["y"], errors="coerce")    # '?' placeholders -> NaN, dropped below

    # optional sub-sample of wafers to keep a dry run fast (sample_wafers: null = all)
    n = cfg.get("sample_wafers")
    rng = np.random.RandomState(cfg.get("random_state", 42))
    wafers = rate["WAFER_ID"].unique()
    if n and n < len(wafers):
        keep = rng.choice(wafers, size=int(n), replace=False)
        rate = rate[rate["WAFER_ID"].isin(keep)]
        traj = traj[traj["WAFER_ID"].isin(keep)]
        print(f"sampled {n} of {len(wafers)} wafers for a quick run")

    feat = _featurize(traj)
    data = feat.merge(rate[KEY + ["y"]], on=KEY, how="inner").dropna(subset=["y"])
    print(f"built {data.shape[0]} wafer-stage rows x {data.shape[1] - len(KEY) - 1} features")

    # split by wafer so a wafer's A/B rows never straddle train and val
    uniq = data["WAFER_ID"].unique()
    rng.shuffle(uniq)
    cut = int(len(uniq) * (1 - cfg.get("val_fraction", 0.2)))
    train_w, val_w = set(uniq[:cut]), set(uniq[cut:])
    tr = data[data["WAFER_ID"].isin(train_w)]
    va = data[data["WAFER_ID"].isin(val_w)]

    feat_cols = [c for c in data.columns if c not in KEY + ["y"]]
    os.makedirs(work, exist_ok=True)
    tr.to_parquet(os.path.join(work, "train.parquet"))
    va.to_parquet(os.path.join(work, "val.parquet"))
    with open(os.path.join(work, "features.json"), "w", encoding="utf-8") as f:
        json.dump(feat_cols, f)
    print(f"train={len(tr)} val={len(va)} rows")
    return {"work": work, "n_features": len(feat_cols),
            "n_train": int(len(tr)), "n_val": int(len(va)),
            "target_mean": float(data["y"].mean()), "target_std": float(data["y"].std())}


@task(name="train", task_run_name="train", tags=["cmp", "model"],
      retries=1, retry_delay_seconds=2, log_prints=True)
def train(prep: dict, cfg: dict, storage: str,
          mlflow_uri: str = "", run_name: str = "") -> dict:
    """Optuna search over LGBMRegressor, CV-RMSE on the training wafers; refit best.

    `storage` is the postgresql_optuna DSN (trials are logged there for optuna-dashboard).
    If `mlflow_uri` is reachable, each trial's CV-RMSE is also logged to MLflow as a step,
    so the MLflow UI shows a per-trial metric curve (best-effort; skipped if MLflow is down).
    """
    import optuna
    from lightgbm import LGBMRegressor
    from sklearn.model_selection import cross_val_score

    work = prep["work"]
    tr = pd.read_parquet(os.path.join(work, "train.parquet"))
    with open(os.path.join(work, "features.json"), encoding="utf-8") as f:
        feat_cols = json.load(f)
    x, y = tr[feat_cols], tr["y"]
    fixed = cfg.get("lgbm_fixed", {})
    seed = cfg.get("random_state", 42)
    folds = cfg.get("cv_folds", 5)
    study_name = cfg.get("study_name", "cmp_vm")

    def objective(trial):
        params = dict(
            n_estimators=trial.suggest_int("n_estimators", 200, 1200, step=100),
            learning_rate=trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            num_leaves=trial.suggest_int("num_leaves", 15, 255),
            max_depth=trial.suggest_int("max_depth", 3, 12),
            min_child_samples=trial.suggest_int("min_child_samples", 5, 80),
            subsample=trial.suggest_float("subsample", 0.6, 1.0),
            colsample_bytree=trial.suggest_float("colsample_bytree", 0.6, 1.0),
            reg_alpha=trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
            reg_lambda=trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
            random_state=seed, **fixed)
        model = LGBMRegressor(**params)
        score = cross_val_score(model, x, y, cv=folds,
                                scoring="neg_root_mean_squared_error")
        return -score.mean()

    mlf = _mlflow_start(mlflow_uri, study_name, run_name)     # None if MLflow is unreachable

    def log_trial(study, trial):                             # Optuna runs this after each trial
        print(f"trial {trial.number}: cv_rmse={trial.value:.4f} best={study.best_value:.4f}")
        if mlf:                                              # step=trial number -> a metric curve
            mlf.log_metric("cv_rmse", float(trial.value), step=trial.number)
            mlf.log_metric("best_cv_rmse", float(study.best_value), step=trial.number)

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction=cfg.get("direction", "minimize"),
                                sampler=optuna.samplers.TPESampler(seed=seed),
                                storage=storage, study_name=study_name,
                                load_if_exists=True)
    study.optimize(objective, n_trials=cfg.get("n_trials", 20), callbacks=[log_trial])
    print(f"best CV RMSE={study.best_value:.4f} params={study.best_params}")
    print(f"optuna study '{study_name}' -> {_mask(storage)}  (view: optuna-dashboard <dsn>)")

    best = LGBMRegressor(random_state=seed, **fixed, **study.best_params)
    best.fit(x, y)
    model_path = os.path.join(work, "model.txt")
    best.booster_.save_model(model_path)
    imp = sorted(zip(feat_cols, best.booster_.feature_importance(importance_type="gain")),
                 key=lambda t: t[1], reverse=True)
    if mlf:                                                  # final best params/score, then close the run
        mlf.log_params(study.best_params)
        mlf.log_metric("final_cv_rmse", float(study.best_value))
        mlf.end_run()
    return {"work": work, "model_path": model_path,
            "best_params": study.best_params, "best_cv_rmse": float(study.best_value),
            "top_features": [{"feature": f, "gain": float(g)} for f, g in imp[:15]]}


@task(name="evaluate", task_run_name="evaluate", tags=["cmp", "eval"],
      retries=2, retry_delay_seconds=2, log_prints=True)
def evaluate(trained: dict, prep: dict) -> dict:
    """Score the held-out validation wafers: RMSE, MAE, R2."""
    from lightgbm import Booster
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

    work = trained["work"]
    va = pd.read_parquet(os.path.join(work, "val.parquet"))
    with open(os.path.join(work, "features.json"), encoding="utf-8") as f:
        feat_cols = json.load(f)
    booster = Booster(model_file=trained["model_path"])
    pred = booster.predict(va[feat_cols])
    y = va["y"].to_numpy()
    rmse = float(np.sqrt(mean_squared_error(y, pred)))
    mae = float(mean_absolute_error(y, pred))
    r2 = float(r2_score(y, pred))
    print(f"val RMSE={rmse:.4f} MAE={mae:.4f} R2={r2:.4f}")
    return {"val_rmse": rmse, "val_mae": mae, "val_r2": r2}


@task(name="predict_test", task_run_name="predict_test", tags=["cmp", "infer"],
      retries=1, retry_delay_seconds=2, log_prints=True)
def predict_test(trained: dict, data_dir: str) -> dict:
    """If a test set is present, write challenge-format CMP-test-removalrate.csv."""
    from lightgbm import Booster

    test_files = sorted([os.path.join(data_dir, f) for f in os.listdir(data_dir)
                         if f.startswith("CMP-test-") and f[9:10].isdigit()])
    if not test_files:
        print("no CMP-test-*.csv found - skipping test prediction")
        return {"test_predicted": 0, "submission": None}

    work = trained["work"]
    with open(os.path.join(work, "features.json"), encoding="utf-8") as f:
        feat_cols = json.load(f)
    traj = _read_trajectories(test_files)
    feat = _featurize(traj)
    for c in feat_cols:                                       # align columns to training schema
        if c not in feat.columns:
            feat[c] = np.nan
    booster = Booster(model_file=trained["model_path"])
    feat["AVG_REMOVAL_RATE"] = booster.predict(feat[feat_cols])
    out = feat[KEY + ["AVG_REMOVAL_RATE"]]
    # write to a distinct file so the original '?' submission template is left intact
    sub = os.path.join(trained["work"], "CMP-test-removalrate-pred.csv")
    out.to_csv(sub, index=False)
    print(f"wrote {len(out)} predictions -> {sub}")

    # score against the official test answers if they were downloaded (CMP-test-answers.csv)
    result = {"test_predicted": int(len(out)), "submission": sub,
              "test_rmse": None, "test_mae": None, "test_r2": None}
    ans_path = os.path.join(data_dir, "CMP-test-answers.csv")
    if os.path.exists(ans_path):
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
        ans = pd.read_csv(ans_path)
        ans.columns = [c.strip().upper() for c in ans.columns]
        ans["STAGE"] = ans["STAGE"].astype(str).str.strip()
        ans["AVG_REMOVAL_RATE"] = pd.to_numeric(ans["AVG_REMOVAL_RATE"], errors="coerce")
        m = out.merge(ans, on=KEY, suffixes=("_pred", "_true")).dropna()
        if len(m):
            yt, yp = m["AVG_REMOVAL_RATE_true"], m["AVG_REMOVAL_RATE_pred"]
            result["test_rmse"] = float(np.sqrt(mean_squared_error(yt, yp)))
            result["test_mae"] = float(mean_absolute_error(yt, yp))
            result["test_r2"] = float(r2_score(yt, yp))
            print(f"test (n={len(m)}) RMSE={result['test_rmse']:.4f} "
                  f"MAE={result['test_mae']:.4f} R2={result['test_r2']:.4f}")
    else:
        print("no CMP-test-answers.csv - skipping official test scoring")
    return result


@flow(name="cmp_vm", flow_run_name="{member}@{git_commit_hash}", log_prints=True,
      task_runner=ThreadPoolTaskRunner(max_workers=4))
def my_flow(data_dir: str, member: str = "local", git_commit_hash: str = "dryrun",
            git_repo: str = ""):
    """PHM 2016 CMP virtual metrology: prepare -> train -> (evaluate || predict_test)."""
    log = get_run_logger()
    work = os.path.join(HERE, "work")
    os.makedirs(work, exist_ok=True)
    log.info(f"start: member={member} commit={git_commit_hash} repo={git_repo or '-'} data={data_dir}")

    cfg = load_config(OPTUNA_CFG)                            # read fresh each run
    log.info(f"tuning {cfg['n_trials']} trials, metric={cfg['metric']}")

    storage, src = _optuna_storage(cfg, member)             # postgresql_optuna block (by member)
    log.info(f"optuna storage [{src}]: {_mask(storage)}")

    mlflow_uri = cfg.get("mlflow_uri") or "http://mlflow:5000"   # compose service; localhost:5000 on host
    run_name = f"{member}@{git_commit_hash}"
    log.info(f"mlflow uri: {mlflow_uri}")

    prep = prepare.submit(data_dir, work, cfg)
    tr = train.submit(prep, cfg, storage, mlflow_uri, run_name, wait_for=[prep])
    ev = evaluate.submit(tr, prep, wait_for=[tr])           # eval and test-predict run
    pr = predict_test.submit(tr, data_dir, wait_for=[tr])   # in parallel after train

    prep_meta, train_meta = prep.result(), tr.result()
    metrics, pred_meta = ev.result(), pr.result()

    summary = {"member": member, "git_commit_hash": git_commit_hash,
               "n_train": prep_meta["n_train"], "n_val": prep_meta["n_val"],
               "n_features": prep_meta["n_features"],
               "best_cv_rmse": train_meta["best_cv_rmse"], **metrics,
               "test_predicted": pred_meta["test_predicted"],
               "test_rmse": pred_meta["test_rmse"], "test_mae": pred_meta["test_mae"],
               "test_r2": pred_meta["test_r2"]}
    log.info(f"done: {summary}")

    _publish_artifacts(summary, train_meta)
    return summary


def _publish_artifacts(summary: dict, train_meta: dict):
    """Surface results in the Prefect UI; best-effort so a pure-local run never fails on it."""
    try:
        metric_rows = [{"metric": k, "value": round(v, 4) if isinstance(v, float) else v}
                       for k, v in summary.items()
                       if k in ("best_cv_rmse", "val_rmse", "val_mae", "val_r2",
                                "test_rmse", "test_mae", "test_r2",
                                "n_train", "n_val", "n_features", "test_predicted")
                       and v is not None]
        create_table_artifact(key="cmp-vm-metrics", table=metric_rows,
                              description="PHM 2016 CMP virtual-metrology metrics")
        create_table_artifact(key="cmp-vm-top-features", table=train_meta["top_features"],
                              description="LightGBM top features by gain")
        md = (f"# CMP VM run - `{summary['member']}@{summary['git_commit_hash']}`\n\n"
              f"- flow run: `{flow_run.name}` (`{flow_run.id}`)\n"
              f"- rows: train **{summary['n_train']}** / val **{summary['n_val']}**, "
              f"features **{summary['n_features']}**\n"
              f"- best CV RMSE: **{summary['best_cv_rmse']:.4f}**\n"
              f"- val RMSE / MAE / R2: **{summary['val_rmse']:.4f}** / "
              f"{summary['val_mae']:.4f} / **{summary['val_r2']:.4f}**\n"
              + (f"- test RMSE / MAE / R2: **{summary['test_rmse']:.4f}** / "
                 f"{summary['test_mae']:.4f} / **{summary['test_r2']:.4f}** "
                 f"(official answers)\n" if summary.get("test_rmse") is not None else "")
              + f"- best params: `{train_meta['best_params']}`\n"
              f"- test wafers predicted: {summary['test_predicted']}\n")
        create_markdown_artifact(key="cmp-vm-summary", markdown=md,
                                 description="CMP VM run summary")
    except Exception as e:                                   # no API backend (pure local) -> skip artifacts
        get_run_logger().warning(f"artifact publish skipped: {e}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()                           # pipeline.py passes these as CLI args
    p.add_argument("--data_folder", default=os.path.join(HERE, "data"))
    p.add_argument("--member", default="local")
    p.add_argument("--git_commit_hash", default="dryrun")
    p.add_argument("--git_repo", default="")                # accepted for completeness; unused here
    a = p.parse_args()
    my_flow(a.data_folder, member=a.member, git_commit_hash=a.git_commit_hash, git_repo=a.git_repo)
