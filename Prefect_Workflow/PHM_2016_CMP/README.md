# PHM 2016 CMP - Virtual Metrology (LightGBM)

Predicts wafer **AVG_REMOVAL_RATE** (a continuous target - the same Virtual Metrology
shape as film-thickness / etch-rate prediction) from CMP tool sensor trajectories,
using LightGBM. `my_flow.py` is the Prefect entrypoint.

## Layout

| File | Role |
|---|---|
| `download_data.py` | Fetch the PHM 2016 CMP data into `./data` (token-free) |
| `my_flow.py` | Prefect flow entrypoint: prepare -> train -> evaluate / predict |
| `optuna.json` | Tuning + run config (trials, CV folds, wafer sample size) |
| `data/` | CSVs land here (created by `download_data.py`; git-ignored) |

## 1. Get the data

All the official 2016 sources are dead (the CFP Dropbox link serves a JS page,
phmsociety.org migrated so its file links 404) and the set is not on Kaggle. The one
reliable, **token-free** source left is the Internet Archive's Wayback Machine, which
captured the full 9.4 MB zip - that is the default.

```bash
python download_data.py                 # download + unzip into ./data (no account needed)
python download_data.py --url <zip-url>  # use a different mirror if you have one
```

Files in `./data` after download: `CMP-training-000..184.csv` (185 files, 25 columns,
**with a header row**), `CMP-training-removalrate.csv` (the `WAFER_ID, STAGE,
AVG_REMOVAL_RATE` target), `CMP-test-000..184.csv`, `CMP-test-removalrate.csv` (a
submission template where `AVG_REMOVAL_RATE` is `?`), and `CMP-test-answers.csv` (the
official held-out test answers, fetched from the same archive - used to score test).

## Data set and splits

The raw data is **time-series sensor trajectories**: every wafer is polished in stage
A and/or B, and each polishing run logs 150–400 timestamped sensor rows. The target
(`AVG_REMOVAL_RATE`) is one scalar per `(WAFER_ID, STAGE)`, so the **modeling unit is a
whole trajectory**, not a single timestamp row.

| Set | Trajectory files | Raw rows (timestamp-level) | Labeled samples (wafer-stage) |
|---|---|---|---|
| training | 185 | 672,744 x 25 | **1,981** (1,699 wafers; stage A 1,166 / B 815) |
| test | 185 | comparable | **424** (answers in `CMP-test-answers.csv`) |

`AVG_REMOVAL_RATE` over the 1,981 training samples: min 53.4, max 4,326.2, mean 98.6,
std 187.4 - a long right tail (a few extreme wafers), so RMSE is dominated by outliers.

> The official challenge also ships a separate 424-wafer *validation* zip; this project
> does not use it. "validation" below means an internal hold-out carved from training.

How `prepare` splits (split is **by wafer**, so a wafer's A and B rows never straddle
train and validation):

| Split | How | Default run (`sample_wafers: 300`) | Full run (`sample_wafers: null`) |
|---|---|---|---|
| train | 80% of training wafers | 278 samples | approx 1,585 samples |
| validation | 20% of training wafers (held out) | 75 samples | approx 396 samples |
| test | official test set, scored vs answers | 424 samples | 424 samples |

## Inputs (x) and target (y)

Each raw row has **25 columns** = 6 context + 19 process sensors:

- **context (6)**: `MACHINE_ID, MACHINE_DATA, TIMESTAMP, WAFER_ID, STAGE, CHAMBER`
- **process sensors (19, `x7..x25`)**: usage measures (backing film, dresser, tables,
  membrane, sheet), pressures (chamber, air bags, retainer ring, edge), slurry flow
  A/B/C, rotations (wafer, stage, head), dressing-water status

`prepare` aggregates each trajectory into **155 features**:

| Feature group | Count |
|---|---|
| 19 sensors x {mean, std, min, max, median} | 95 |
| 19 sensors x {last, delta (last-first), slope (delta/duration)} | 57 |
| `n_samples`, `duration`, `stage_is_B` | 3 |
| **total x features** | **155** |

- **y label**: `AVG_REMOVAL_RATE` - a continuous float scalar (**regression**, not
  classification; there are no class labels). `STAGE` (A/B) is a categorical *input*,
  encoded as `stage_is_B`.
- **shapes** (full run): X_train `(1981, 155)` before split, y `(1981,)`; test X
  `(424, 155)`, y `(424,)`. Default sampled run: train `(278, 155)`, val `(75, 155)`,
  test `(424, 155)`.

## 2. Run the flow

```bash
python my_flow.py --data_folder ./data
# full pipeline.py-style invocation:
python my_flow.py --git_repo <r> --git_commit_hash <c> --member <m> --data_folder ./data
```

`optuna.json` -> `sample_wafers` keeps the dry run fast (default 300 wafers); set it
to `null` to use all 1,981 training wafer-stage samples.

Environment: this repo's deps (prefect, lightgbm, optuna, scikit-learn, pandas,
pyarrow) live in the conda `base` env here, so prefix commands with
`conda run -n base python ...` if `python` is not the base interpreter on PATH.

A 300-wafer run reaches about **val R2 = 0.93** (RMSE 6.7) on held-out wafers and
**test R2 = 0.94** (RMSE 7.1) against the official 424-wafer answers.

## Pipeline

`load_config -> prepare -> train -> (evaluate || predict_test)`

Data flows top to bottom; each box is a `@task`, and the label on every arrow is the
data passed from one function to the next (`data/` = input CSVs, `work/` = run artifacts):

```text
  optuna.json                  data/CMP-training-*.csv
       │                       data/CMP-training-removalrate.csv
       ▼                              │
 ┌─────────────┐    cfg               │
 │ load_config │────────┐             │
 └─────────────┘        ▼             ▼
                  ┌──────────────────────┐
                  │       prepare        │
                  └──────────┬───────────┘
                             │  train.parquet, val.parquet, features.json
                             ▼
                  ┌──────────────────────┐   trials    ┌───────────┐
                  │        train         │───────────▶ │ optuna DB │
                  └──────────┬───────────┘             └───────────┘
                             │  model.txt
                ┌────────────┴────────────┐
                ▼                         ▼
        ┌──────────────┐          ┌──────────────┐ ◀── data/CMP-test-*.csv
        │   evaluate   │          │ predict_test │ ◀── data/CMP-test-answers.csv
        └──────┬───────┘          └──────┬───────┘
               │ metrics                 │ pred, CMP-test-removalrate-pred.csv
               └────────────┬────────────┘
                            ▼
                 ┌──────────────────────┐
                 │  _publish_artifacts  │
                 └──────────┬───────────┘
                            ▼
               Prefect UI (table / markdown)
```

`evaluate` and `predict_test` both read `model.txt` from `train` and run in parallel
(`.submit()` + `wait_for`). `evaluate` also reuses `val.parquet` + `features.json` from
`prepare`; `predict_test` reuses `features.json` and scores against `CMP-test-answers.csv`.

- **prepare** - reads all training trajectories + target, aggregates each
  `(WAFER_ID, STAGE)` trajectory into per-wafer statistics (mean/std/min/max/median +
  last/delta/slope over the 19 process variables `x7..x25`), splits train/val **by
  wafer**.
- **train** - Optuna over `LGBMRegressor` (CV-RMSE), refits the best params.
- **evaluate** - RMSE / MAE / R2 on held-out wafers.
- **predict_test** - predicts the test wafers, writes
  `work/CMP-test-removalrate-pred.csv` (the `?` template is left intact), and - if
  `CMP-test-answers.csv` is present - scores the test set (RMSE / MAE / R2).

Prefect features used: `@flow`/`@task`, `flow_run_name`/`task_run_name`, tags,
retries, `ThreadPoolTaskRunner` + `.submit()`/`wait_for` DAG, `get_run_logger`, and
table/markdown artifacts.

## Iterations

One run, with the defaults in `optuna.json`:

| Layer | Count | Source |
|---|---|---|
| Optuna trials (search) | 20 | `n_trials` |
| CV folds per trial | 5 | `cv_folds` |
| LightGBM fits while tuning | 100 | 20 trials x 5 folds |
| Final refit on best params | 1 | `best.fit` |
| **Total LightGBM fits** | **101** | 100 + 1 |
| Boosting rounds per fit | 200–1200 | tuned `n_estimators` (step 100) |

- "Iteration" usually means the **20 Optuna trials**. Each trial fits 5 CV models, so
  tuning does 100 fits; the best params are then refit once (101 total).
- `retries` (prepare 2, train 1) only add runs on failure - 0 on a clean run.
- `sample_wafers` is data size, not iterations: `null` uses all 1,981 samples but still
  runs the same 20 trials.

## Optuna dashboard

`train` logs every trial to the **team PostgreSQL Optuna DB**. The storage DSN is not
hardcoded - it is built from the `postgresql_optuna` section of the member's
`Credentials` block (`Credentials.load(<member>)`), exactly like `catalog.py`. So the
DB target follows whoever runs the flow (`--member`), and no secret lives in the repo.

That block holds host `postgres` (the compose-network service name), so the study is
written when the flow runs **inside the compose network** (how `pipeline.py` runs this
payload). The same DB is published on the host at `localhost:5432`, so to view it:

```bash
pip install optuna-dashboard                                   # one time
optuna-dashboard postgresql://<user>:<pw>@localhost:5432/optuna  # open http://127.0.0.1:8080/
```

The dashboard shows optimization history, parallel-coordinate and
hyperparameter-importance plots, and every trial's params and CV-RMSE. Re-runs append
to the same `study_name` (`cmp_vm`).

`optuna.json -> storage` is an **override**: leave it `null` to use the
`postgresql_optuna` block (default), or set a full DSN (e.g. a local
`sqlite:///optuna.db` or a test Postgres) to point elsewhere.

## MLflow metrics

`train` also logs each Optuna trial to the team **MLflow** server as a metric step, so the
MLflow UI draws a per-trial curve. This is the place for metric curves; the optuna-dashboard
above is for the tuning plots. Logging is **best-effort** - if MLflow is unreachable the run
prints `MLflow disabled ...` and continues, so a local dry run never fails on it.

Logged in one run named `<member>@<commit>` under experiment `cmp_vm`:

| Metric / field | Meaning |
|---|---|
| `cv_rmse` (step = trial number) | that trial's CV-RMSE - the per-trial curve |
| `best_cv_rmse` (step = trial number) | running best so far (monotonic) |
| `final_cv_rmse` + best params | the chosen result, logged once at the end |

View it on the stack's MLflow server:

```bash
# host: http://localhost:5000   (inside the compose network: http://mlflow:5000)
# Experiments -> cmp_vm -> run <member>@<commit> -> Metrics -> cv_rmse  (x = trial, y = RMSE)
```

`optuna.json -> mlflow_uri` is an **override**: leave it `null` to use `http://mlflow:5000`
(the compose service, how `pipeline.py` runs this payload), or set `http://localhost:5000`
when you run `my_flow.py` directly on the host. The tracking URI is a plain service address,
not a secret, so it stays in config - unlike the DB / MinIO creds, which come from the
member's `Credentials` block.

## Appendix - Prefect syntax

A quick reference for every Prefect construct used in `my_flow.py`.

### Decorators - `@task`, `@flow`

`@task` / `@flow` wrap a plain function so Prefect runs, tracks, and shows it in the UI.

```python
@task(name="train", task_run_name="train", tags=["cmp", "model"],
      retries=1, retry_delay_seconds=2, log_prints=True)
def train(prep, cfg, storage, mlflow_uri="", run_name=""): ...

@flow(name="cmp_vm", flow_run_name="{member}@{git_commit_hash}", log_prints=True,
      task_runner=ThreadPoolTaskRunner(max_workers=4))
def my_flow(data_dir, member="local", git_commit_hash="dryrun", git_repo=""): ...
```

| Argument | Meaning |
|---|---|
| `name` | task / flow name shown in the UI |
| `task_run_name` / `flow_run_name` | per-run label; `"{member}@{git_commit_hash}"` is filled from the call arguments |
| `tags` | labels for UI filtering and concurrency limits |
| `retries`, `retry_delay_seconds` | on failure, re-run the task N times, waiting M seconds between tries |
| `log_prints=True` | capture the function's `print()` into the Prefect run logs |
| `task_runner` | how tasks execute (`@flow` only); here `ThreadPoolTaskRunner` runs them on threads |

### Running tasks - `.submit()`, `wait_for`, `.result()`

```python
prep = prepare.submit(data_dir, work, cfg)             # schedule -> returns a future, non-blocking
tr   = train.submit(prep, cfg, storage, wait_for=[prep])    # start after prep finishes
ev   = evaluate.submit(tr, prep, wait_for=[tr])        # evaluate and predict_test run
pr   = predict_test.submit(tr, data_dir, wait_for=[tr])     # in parallel, both after train
metrics, pred = ev.result(), pr.result()               # block until done; re-raises on failure
```

| Call | What it does |
|---|---|
| `task.submit(...)` | schedule the task on the task runner; returns a `PrefectFuture` at once (non-blocking) - this is what enables concurrency |
| `wait_for=[...]` | ordering edge: hold the task until those futures finish - used to build the DAG |
| `future.result()` | block until the task finishes and return its value (raises if the task failed) |
| `ThreadPoolTaskRunner(max_workers=4)` | run up to 4 submitted tasks at the same time |

Passing a future as an argument (`train.submit(prep, ...)`) already creates a data
dependency; `wait_for` adds explicit ordering even when no data is passed between them.

### Logging and artifacts

```python
log = get_run_logger()                 # logger bound to this run -> UI logs
log.info("start ...")

create_table_artifact(key="cmp-vm-metrics", table=rows, description="...")     # list[dict] -> UI table
create_markdown_artifact(key="cmp-vm-summary", markdown=md, description="...") # markdown -> UI panel
md = f"flow run: {flow_run.name} ({flow_run.id})"                              # current run's name / id
```

| Call | What it does |
|---|---|
| `get_run_logger()` | logger tied to the current flow / task run; messages show in the UI |
| `create_table_artifact(key, table, description)` | attach a table (`list[dict]`) to the run, rendered in the UI |
| `create_markdown_artifact(key, markdown, description)` | attach a markdown block to the run |
| `flow_run.name` / `flow_run.id` | runtime context (`from prefect.runtime import flow_run`): the current run's name / id |
