"""my_flow.py - PHM 2016 CMP virtual-metrology flow (entrypoint).

Predicts wafer AVG_REMOVAL_RATE (a scalar / regression target) from CMP tool
sensor trajectories with LightGBM - the same Virtual Metrology shape as film
thickness / etch-rate prediction. Run as the team payload that pipeline.py drives:

    python my_flow.py --git_repo <r> --git_commit_hash <c> --member <m> --data_folder ./data

Pipeline (a small DAG): load_config -> train_prepare -> train_featurize -> train ->
(validate || test); parity_plot AND publish_artifacts both fire right after each of
train / validate / test. train_prepare reads CMP-training-*.csv (25 columns x1..x25) + the
CMP-training-removalrate.csv target and sub-samples wafers; train_featurize scales each sensor
to 0-1 (saved as scaler.json), folds each (WAFER_ID, STAGE) trajectory into 155 features, and
carves a validation split. train runs Optuna over LGBMRegressor and reports the CV-RMSE +
train-set RMSE/MAE/R2; validate scores RMSE/MAE/R2 on the held-out validation wafers; the test path
(test_prepare -> test_featurize -> test) builds the official test features with the training
scaler and writes/scores the challenge-format CMP-test-removalrate.csv.

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


__version__ = "0.0.23"

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


def _scale(traj: pd.DataFrame, scaler: dict = None) -> tuple:
    """Per-sensor 0-1 (min-max) scaling core. Fit when `scaler` is None (training) and return
    the {sensor: [min, max]} map; otherwise apply the supplied map (test) so train and test
    share one scale. Only the 19 sensor columns are touched - TIMESTAMP / STAGE stay raw."""
    traj = traj.copy()
    if scaler is None:
        scaler = {v: [float(traj[v].min()), float(traj[v].max())] for v in PROCESS_VARS}
    for v in PROCESS_VARS:
        lo, hi = scaler[v]
        rng = hi - lo
        traj[v] = (traj[v] - lo) / rng if rng else 0.0
    return traj, scaler


def _aggregate(traj: pd.DataFrame) -> pd.DataFrame:
    """Fold each (WAFER_ID, STAGE) trajectory (already 0-1 scaled) into one 155-feature row."""
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


@task(name="train_prepare", task_run_name="train_prepare", tags=["cmp", "dp"],
      retries=2, retry_delay_seconds=2, log_prints=True)
def train_prepare(data_dir: str, work: str, cfg: dict) -> dict:
    """Read training trajectories + target and sub-sample wafers; hand the raw rows downstream."""
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
    rate["y"] = pd.to_numeric(rate["y"], errors="coerce")    # '?' placeholders -> NaN, dropped later

    # optional sub-sample of wafers to keep a dry run fast (sample_wafers: null = all)
    rng = np.random.RandomState(cfg.get("random_state", 42))
    n = cfg.get("sample_wafers")
    wafers = rate["WAFER_ID"].unique()
    if n and n < len(wafers):
        keep = rng.choice(wafers, size=int(n), replace=False)
        rate = rate[rate["WAFER_ID"].isin(keep)]
        traj = traj[traj["WAFER_ID"].isin(keep)]
        print(f"sampled {n} of {len(wafers)} wafers for a quick run")

    # decide the train/val wafer split here, with the same rng sequence as a single-pass run
    # (sample-choice then shuffle), so the by-wafer split is stable across the task boundary
    uniq = np.sort(rate.dropna(subset=["y"])["WAFER_ID"].unique())
    rng.shuffle(uniq)
    cut = int(len(uniq) * (1 - cfg.get("val_fraction", 0.2)))
    split = {"train": uniq[:cut].tolist(), "val": uniq[cut:].tolist()}

    os.makedirs(work, exist_ok=True)
    traj.to_parquet(os.path.join(work, "traj_raw.parquet"))
    rate.to_parquet(os.path.join(work, "rate.parquet"))
    with open(os.path.join(work, "split.json"), "w", encoding="utf-8") as f:
        json.dump(split, f)
    print(f"prepared {len(traj)} raw rows; split {len(split['train'])}/{len(split['val'])} wafers (train/val)")
    return {"work": work}


@task(name="train_featurize", task_run_name="train_featurize", tags=["cmp", "dp", "fe"],
      retries=2, retry_delay_seconds=2, log_prints=True)
def train_featurize(prep: dict, cfg: dict) -> dict:
    """Preprocess + feature engineering: fit per-sensor 0-1 scaling (saved as scaler.json, which
    test reuses), fold each (WAFER_ID, STAGE) trajectory into 155 features, merge the target,
    and split train/val by wafer."""
    work = prep["work"]
    traj = pd.read_parquet(os.path.join(work, "traj_raw.parquet"))
    rate = pd.read_parquet(os.path.join(work, "rate.parquet"))
    with open(os.path.join(work, "split.json"), encoding="utf-8") as f:
        split = json.load(f)                                 # the by-wafer train/val split from train_prepare
    traj, scaler = _scale(traj)                              # preprocessing: per-sensor 0-1 scaling (fit)
    with open(os.path.join(work, "scaler.json"), "w", encoding="utf-8") as f:
        json.dump(scaler, f)                                 # reused at test time by test
    feat = _aggregate(traj)
    data = feat.merge(rate[KEY + ["y"]], on=KEY, how="inner").dropna(subset=["y"])
    print(f"built {data.shape[0]} wafer-stage rows x {data.shape[1] - len(KEY) - 1} features")

    # apply the by-wafer split so a wafer's A/B rows never straddle train and val
    tr = data[data["WAFER_ID"].isin(split["train"])]
    va = data[data["WAFER_ID"].isin(split["val"])]

    feat_cols = [c for c in data.columns if c not in KEY + ["y"]]
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
    # train-set predictions -> train metrics (so train returns the model AND its metrics)
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    train_pred = best.predict(x)
    yt = y.to_numpy()
    train_rmse = float(np.sqrt(mean_squared_error(yt, train_pred)))
    train_mae = float(mean_absolute_error(yt, train_pred))
    train_r2 = float(r2_score(yt, train_pred))
    print(f"train RMSE={train_rmse:.4f} MAE={train_mae:.4f} R2={train_r2:.4f} "
          f"(best CV RMSE={study.best_value:.4f})")
    if mlf:                                                  # final best params/score, then close the run
        mlf.log_params(study.best_params)
        mlf.log_metric("final_cv_rmse", float(study.best_value))
        mlf.log_metric("train_rmse", train_rmse)
        mlf.end_run()
    return {"work": work, "model_path": model_path,
            "best_params": study.best_params, "best_cv_rmse": float(study.best_value),
            "train_rmse": train_rmse, "train_mae": train_mae, "train_r2": train_r2,
            "top_features": [{"feature": f, "gain": float(g)} for f, g in imp[:15]],
            "train_true": y.tolist(), "train_pred": [float(p) for p in train_pred]}


@task(name="validate", task_run_name="validate", tags=["cmp", "eval"],
      retries=2, retry_delay_seconds=2, log_prints=True)
def validate(trained: dict, prep: dict) -> dict:
    """Score the held-out validation wafers (val.parquet): RMSE, MAE, R2."""
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
    return {"val_rmse": rmse, "val_mae": mae, "val_r2": r2,
            "val_true": y.tolist(), "val_pred": [float(p) for p in pred]}


@task(name="test_prepare", task_run_name="test_prepare", tags=["cmp", "dp"],
      retries=2, retry_delay_seconds=2, log_prints=True)
def test_prepare(data_dir: str, work: str) -> dict:
    """Test-side prepare: read the official test trajectories (CMP-test-*.csv) and save them raw.
    The test counterpart of train_prepare (no target, no sampling, no split - test is fixed)."""
    test_files = sorted([os.path.join(data_dir, f) for f in os.listdir(data_dir)
                         if f.startswith("CMP-test-") and f[9:10].isdigit()])
    if not test_files:
        print("no CMP-test-*.csv found - skipping the test path")
        return {"work": work, "has_test": False}
    traj = _read_trajectories(test_files)
    os.makedirs(work, exist_ok=True)
    traj.to_parquet(os.path.join(work, "test_traj_raw.parquet"))
    print(f"prepared {len(traj)} raw test rows from {len(test_files)} files")
    return {"work": work, "has_test": True}


@task(name="test_featurize", task_run_name="test_featurize", tags=["cmp", "dp", "fe"],
      retries=2, retry_delay_seconds=2, log_prints=True)
def test_featurize(tprep: dict) -> dict:
    """Test-side featurize: apply the training scaler.json + features.json schema to the test
    trajectories (no fit, no split) and save test.parquet. Mirrors train_featurize for test."""
    work = tprep["work"]
    if not tprep.get("has_test"):
        return {"work": work, "has_test": False}
    with open(os.path.join(work, "scaler.json"), encoding="utf-8") as f:
        scaler = json.load(f)                                # the training scaler (per-sensor 0-1 min/max)
    with open(os.path.join(work, "features.json"), encoding="utf-8") as f:
        feat_cols = json.load(f)
    traj = pd.read_parquet(os.path.join(work, "test_traj_raw.parquet"))
    traj, _ = _scale(traj, scaler)                           # preprocessing: apply the training scale
    feat = _aggregate(traj)                                  # feature engineering
    for c in feat_cols:                                       # align to the training feature schema
        if c not in feat.columns:
            feat[c] = np.nan
    feat[KEY + feat_cols].to_parquet(os.path.join(work, "test.parquet"))
    print(f"built {len(feat)} test wafer-stage rows x {len(feat_cols)} features")
    return {"work": work, "has_test": True}


@task(name="test", task_run_name="test", tags=["cmp", "infer"],
      retries=1, retry_delay_seconds=2, log_prints=True)
def test(trained: dict, tfz: dict, data_dir: str) -> dict:
    """Predict the prepared test features, write the challenge-format submission, and score
    against CMP-test-answers.csv if present."""
    from lightgbm import Booster

    work = trained["work"]
    if not tfz.get("has_test"):
        print("no test set - skipping test prediction")
        return {"test_predicted": 0, "submission": None,
                "test_rmse": None, "test_mae": None, "test_r2": None}
    with open(os.path.join(work, "features.json"), encoding="utf-8") as f:
        feat_cols = json.load(f)
    feat = pd.read_parquet(os.path.join(work, "test.parquet"))
    booster = Booster(model_file=trained["model_path"])
    feat["AVG_REMOVAL_RATE"] = booster.predict(feat[feat_cols])
    out = feat[KEY + ["AVG_REMOVAL_RATE"]]
    # write to a distinct file so the original '?' submission template is left intact
    sub = os.path.join(work, "CMP-test-removalrate-pred.csv")
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
            result["test_true"] = [float(v) for v in yt]
            result["test_pred"] = [float(v) for v in yp]
    else:
        print("no CMP-test-answers.csv - skipping official test scoring")
    return result


@task(name="parity_plot", task_run_name="parity_plot ({stage})", tags=["cmp", "viz"], log_prints=True)
def parity_plot(y_true: list, y_pred: list, stage: str, work: str) -> dict:
    """Save a y_true vs y_pred 1:1 parity chart for `stage` (train / validation / test); the
    stage is the chart title. Uses the thread-safe Figure API (no pyplot global state) so the
    three per-stage plots run concurrently. Best-effort: also attaches it to the Prefect UI."""
    if not y_true or not y_pred:
        print(f"parity_plot[{stage}]: no data - skipped")
        return {"stage": stage, "path": None}
    from matplotlib.figure import Figure
    from sklearn.metrics import r2_score

    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_pred, dtype=float)
    r2 = float(r2_score(yt, yp))
    lo, hi = float(min(yt.min(), yp.min())), float(max(yt.max(), yp.max()))
    fig = Figure(figsize=(5, 5))
    ax = fig.subplots()
    ax.scatter(yt, yp, s=14, alpha=0.5, edgecolor="none")
    ax.plot([lo, hi], [lo, hi], "r--", lw=1, label="y = x")
    ax.set(xlabel="y_true (AVG_REMOVAL_RATE)", ylabel="y_pred",
           title=f"{stage} - parity  (n={len(yt)}, R2={r2:.3f})")
    ax.set_aspect("equal", "box")
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    out = os.path.join(work, f"parity_{stage}.png")
    fig.savefig(out, dpi=110)
    print(f"parity_plot[{stage}] -> {out}  (R2={r2:.3f})")
    try:                                                     # best-effort: embed in the Prefect UI
        import base64
        b64 = base64.b64encode(open(out, "rb").read()).decode()
        create_markdown_artifact(
            key=f"cmp-vm-parity-{stage}",
            markdown=f"### {stage} - parity (R2={r2:.3f})\n\n![parity](data:image/png;base64,{b64})",
            description=f"y_true vs y_pred parity plot ({stage})")
    except Exception as e:
        print(f"parity artifact skipped: {e}")
    return {"stage": stage, "path": out, "r2": r2}


@flow(name="cmp_vm", flow_run_name="{member}@{git_commit_hash}", log_prints=True,
      task_runner=ThreadPoolTaskRunner(max_workers=4))
def my_flow(data_dir: str, member: str = "local", git_commit_hash: str = "dryrun",
            git_repo: str = ""):
    """PHM 2016 CMP virtual metrology: train_prepare -> train_featurize -> train ->
    (validate || test), parity after each."""
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

    prep = train_prepare.submit(data_dir, work, cfg)
    fz = train_featurize.submit(prep, cfg, wait_for=[prep])   # preprocess (0-1 scaling) + 155 features + split
    tr = train.submit(fz, cfg, storage, mlflow_uri, run_name, wait_for=[fz])

    # test lane: its own test_prepare + test_featurize, mirroring the training lane - concurrent
    tprep = test_prepare.submit(data_dir, work)
    tfz = test_featurize.submit(tprep, wait_for=[tprep, fz])   # reuses scaler.json + features.json

    va = validate.submit(tr, fz, wait_for=[tr])             # held-out validation scoring
    te = test.submit(tr, tfz, data_dir, wait_for=[tr, tfz])

    # right after each stage (mirrors each other): parity_plot draws its chart and
    # publish_artifacts attaches that stage's metrics to the Prefect UI
    prep_meta = fz.result()
    train_meta = tr.result()
    p_train = parity_plot.submit(train_meta["train_true"], train_meta["train_pred"],
                                 "train", work, wait_for=[tr])
    a_train = publish_artifacts.submit(
        "train", {"best_cv_rmse": train_meta["best_cv_rmse"], "train_rmse": train_meta["train_rmse"],
                  "train_mae": train_meta["train_mae"], "train_r2": train_meta["train_r2"]},
        run_name, train_meta["top_features"], wait_for=[tr])
    metrics = va.result()
    p_val = parity_plot.submit(metrics["val_true"], metrics["val_pred"],
                               "validation", work, wait_for=[va])
    a_val = publish_artifacts.submit(
        "validation", {"val_rmse": metrics["val_rmse"], "val_mae": metrics["val_mae"],
                       "val_r2": metrics["val_r2"]}, run_name, wait_for=[va])
    pred_meta = te.result()
    p_test = parity_plot.submit(pred_meta.get("test_true", []), pred_meta.get("test_pred", []),
                                "test", work, wait_for=[te])
    a_test = publish_artifacts.submit(
        "test", {"test_predicted": pred_meta["test_predicted"], "test_rmse": pred_meta["test_rmse"],
                 "test_mae": pred_meta["test_mae"], "test_r2": pred_meta["test_r2"]},
        run_name, wait_for=[te])
    for f in (p_train, p_val, p_test, a_train, a_val, a_test):
        f.result()

    summary = {"member": member, "git_commit_hash": git_commit_hash,
               "n_train": prep_meta["n_train"], "n_val": prep_meta["n_val"],
               "n_features": prep_meta["n_features"],
               "best_cv_rmse": train_meta["best_cv_rmse"],
               "train_rmse": train_meta["train_rmse"], "train_mae": train_meta["train_mae"],
               "train_r2": train_meta["train_r2"],
               "val_rmse": metrics["val_rmse"], "val_mae": metrics["val_mae"],
               "val_r2": metrics["val_r2"],                  # scalars only - not the parity arrays
               "test_predicted": pred_meta["test_predicted"],
               "test_rmse": pred_meta["test_rmse"], "test_mae": pred_meta["test_mae"],
               "test_r2": pred_meta["test_r2"]}
    log.info(f"done: {summary}")
    return summary


@task(name="publish_artifacts", task_run_name="publish_artifacts ({stage})", tags=["cmp"], log_prints=True)
def publish_artifacts(stage: str, metrics: dict, run_label: str, top_features: list = None):
    """Attach this stage's metrics to the Prefect UI right after the stage finishes - one set per
    stage, mirroring parity_plot. For train, also publish the top-feature table. Best-effort: a
    pure-local run with no API backend just skips."""
    try:
        rows = [{"metric": k, "value": round(v, 4) if isinstance(v, float) else v}
                for k, v in metrics.items() if v is not None]
        create_table_artifact(key=f"cmp-vm-metrics-{stage}", table=rows,
                              description=f"PHM 2016 CMP {stage} metrics - {run_label}")
        if top_features:
            create_table_artifact(key="cmp-vm-top-features", table=top_features,
                                  description=f"LightGBM top features by gain - {run_label}")
        md = (f"### CMP VM - {stage}  (`{run_label}`, run `{flow_run.id}`)\n\n"
              + "\n".join(f"- {r['metric']}: **{r['value']}**" for r in rows))
        create_markdown_artifact(key=f"cmp-vm-summary-{stage}", markdown=md,
                                 description=f"CMP VM {stage} summary")
        print(f"published {stage} artifacts: {len(rows)} metrics")
    except Exception as e:                                   # no API backend (pure local) -> skip artifacts
        get_run_logger().warning(f"artifact publish skipped ({stage}): {e}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()                           # pipeline.py passes these as CLI args
    p.add_argument("--data_folder", default=os.path.join(HERE, "data"))
    p.add_argument("--member", default="local")
    p.add_argument("--git_commit_hash", default="dryrun")
    p.add_argument("--git_repo", default="")                # accepted for completeness; unused here
    a = p.parse_args()
    my_flow(a.data_folder, member=a.member, git_commit_hash=a.git_commit_hash, git_repo=a.git_repo)
