# Kaggle Electric Power Consumption - Power Forecasting (LightGBM)

<sub>rev. 9</sub>

Predicts a Tetouan-city power-consumption zone (**PowerConsumption_Zone1** by default - a
continuous regression target) from weather and calendar features, using LightGBM.
`my_flow.py` is the Prefect entrypoint.

## 1. Layout

| File | Role |
|---|---|
| `my_flow.py` | Prefect flow entrypoint: train_prepare -> train_featurize -> train -> validate; test lane test_prepare -> test_featurize -> test; parity_plot per stage |
| `optuna.json` | Tuning + run config (trials, CV folds, split fractions, target zone, sample size) |
| `minio_spec.json` | Dataset metadata spec - the catalog uploads it to MinIO (`dataset_id` / `version` / `metadata`) |
| `data/` | `powerconsumption.csv` lives here (downloaded from Kaggle; git-ignored) |

## 2. Get the data

Download the CSV from Kaggle and drop it in `./data/powerconsumption.csv` (the flow reads it
there). No fetch script is needed - it is a single static file:

```text
https://www.kaggle.com/datasets/fedesoriano/electric-power-consumption
```

### Data source

The set is the Kaggle **Electric Power Consumption** dataset by *fedesoriano*. It originates
from the UCI ML Repository ("Power consumption of Tetouan city", id 849; Salam & El Hibaoui,
2018) - power draw of three distribution zones in Tetouan, Morocco, with local weather, sampled
every 10 minutes through 2017.

### Metadata

These fields live in `minio_spec.json -> metadata` (keyed `electric_power_consumption` / `v1`):

| Field | Value |
|---|---|
| Source | Kaggle (fedesoriano); `kaggle.com/datasets/fedesoriano/electric-power-consumption` |
| Provenance | UCI ML Repository id 849 - Tetouan city (Morocco), 2017 |
| License | CC BY 4.0 |
| Format | single CSV, comma-separated, one header row (approx 4.3 MB) |
| Rows | 52,416 timestamp rows (10-min samples, 2017-01-01 00:00 .. 2017-12-30 23:50) |
| Sampling | uniform 10-min grid; no missing timestamps, no null values |
| Target | one of `PowerConsumption_Zone1..3` (float); `Zone1` by default (`target_zone`) |

### Data files

**x and y live in one file.** Unlike a separate-template challenge, every row already carries
both the weather inputs (x) and all three zone targets (y); the flow selects one zone as `y`
(`target_zone`) and the temporal split decides which rows are train / validation / test.

| File | Set | Role | Content |
|---|---|---|---|
| `powerconsumption.csv` | all | x + y | 9 columns: `Datetime` + 5 weather + 3 zone targets, **with a header row** |

## 3. Data set and splits

The raw data is a **single uniform time series**: one row every 10 minutes for all of 2017, so
the **modeling unit is one timestamp row** (not an aggregated window). Each row pairs the
weather at that minute with the three zones' power draw.

### Bronze vs silver

Two layers, one transform - the Kaggle CSV (registered via `catalog.py`) is **bronze**,
`train_featurize` folds it into **silver** (the model-ready table). The grain does not change
(one row stays one 10-min sample); the transform is **per-row**, not an aggregation:

| Layer | Built by | File | Grain (one row =) | Full rows | Columns |
|---|---|---|---|---|---|
| bronze | Kaggle download (catalog `v1`) | `data/powerconsumption.csv` | one 10-min sample | 52,416 | 9 raw (Datetime + 5 weather + 3 zones) |
| silver | `train_featurize` | `work/{train,val}.parquet` | one 10-min sample | 41,932 (train+val) | 14 features + y |

`train_featurize` turns each bronze row into one silver row. The calendar features are **born
in this step** and do not exist in bronze:

```text
bronze column                          silver feature (per row)
─────────────                          ────────────────────────
Datetime    ── .hour / .dayofweek ──▶  hour, dayofweek, is_weekend   (numeric)
Datetime    ── sin/cos of cycle ────▶  hour_sin/cos, dow_sin/cos, month_sin/cos
Temperature .. DiffuseFlows ── 0-1 ──▶ 5 scaled weather features
PowerConsumption_Zone{1,2,3}        ──▶ y   (the selected target_zone)
```

### Sizes and splits

The split is **temporal** (no shuffle - it is a time series): the most recent slice is the test
set, the slice just before it is held-out validation, the rest is train. `train_prepare` fixes
the cut, `train_featurize` applies it - so train < validation < test in time and no future row
ever leaks into training.

| Split | How | Full run (default, `sample_rows: null`) | Fast smoke test (`--sample_rows 8000`) |
|---|---|---|---|
| train | earliest 64% (`1 - val_fraction` of `1 - test_fraction`) | 33,545 rows | 5,120 rows |
| validation | next 16% (held-out tail, just before test) | 8,387 rows | 1,280 rows |
| test | most recent 20% (`test_fraction`) | 10,484 rows | 1,600 rows |

`sample_rows` is `null` by default, so a run uses the full 52,416 rows; the `--sample_rows N` CLI
flag takes only the most-recent N rows - a fast smoke test that checks the DAG end to end. The
full year is a genuine seasonal-extrapolation problem; a small recent window (e.g. 8,000, approx
55 days) keeps train / validation / test inside one season, which inflates the score (see section 5).

`PowerConsumption_Zone1` over all 52,416 rows: min 13,895.7, max 52,204.4, mean 32,345.0,
std 7,130.6 - a broad daily swing driven by temperature and the work/rest cycle.

## 4. Inputs (x) and target (y)

### Inputs (x)

Each row has **5 weather inputs**; `train_featurize` derives **9 calendar features** from
`Datetime`, for **14 features** total:

| Feature group | Count |
|---|---|
| 5 weather (`Temperature, Humidity, WindSpeed, GeneralDiffuseFlows, DiffuseFlows`), scaled 0-1 | 5 |
| `hour`, `dayofweek`, `is_weekend` | 3 |
| cyclical sin/cos of `hour`, `dayofweek`, `month` | 6 |
| **total x features** | **14** |

> Raw monotonic indices (`day`, `month`, `dayofyear`) are deliberately left out. A tree cannot
> extrapolate past its training range, so a future-only value (e.g. December's `dayofyear`) just
> pins to the edge split and hurts the test score; the cyclical `sin/cos` carry the same
> seasonality while staying bounded and in-range for any date.

Per-feature range over all 52,416 rows (raw units, before 0-1 scaling):

| Feature | min | max | mean | std |
|---|---|---|---|---|
| Temperature (°C) | 3.25 | 40.01 | 18.81 | 5.82 |
| Humidity (%) | 11.34 | 94.80 | 68.26 | 15.55 |
| WindSpeed | 0.05 | 6.48 | 1.96 | 2.35 |
| GeneralDiffuseFlows | 0.004 | 1163.00 | 182.70 | 264.40 |
| DiffuseFlows | 0.011 | 936.00 | 75.03 | 124.21 |

**shapes** (default full run): X_train `(33545, 14)`, val `(8387, 14)`, test `(10484, 14)`.
Fast smoke test (`--sample_rows 8000`): train `(5120, 14)`, val `(1280, 14)`, test `(1600, 14)`.

### Target (y)

`target_zone` selects one column as `y` - a continuous float (**regression**, not
classification). The three zones differ in scale (full data):

| Zone | column | min | max | mean | std |
|---|---|---|---|---|---|
| Zone1 (default) | `PowerConsumption_Zone1` | 13,895.7 | 52,204.4 | 32,345.0 | 7,130.6 |
| Zone2 | `PowerConsumption_Zone2` | 8,560.1 | 37,408.9 | 21,042.5 | 5,201.5 |
| Zone3 | `PowerConsumption_Zone3` | 5,935.2 | 47,598.3 | 17,835.4 | 6,622.2 |

Consumption is strongly seasonal and cyclic - a daily peak (evening) and trough (pre-dawn), a
weekday/weekend shift, and a yearly swing with temperature. That is exactly why the cyclical
`hour` / `dayofweek` / `month` encodings and the weather features carry the signal:

```text
PowerConsumption_Zone1 - daily shape (mean by hour, all of 2017)

 00–05  low      ██████████████████               approx 26k, easing toward dawn
 06–10  rising   ██████████████████               approx 23k trough (hr 6) -> climbing
 11–16  midday   ███████████████████████████      approx 34k plateau
 17–21  peak     ██████████████████████████████   approx 44k evening peak (hr 20)
 22–23  falling  █████████████████████████        approx 37k, dropping off
```

## 5. Run the flow

`--run-on` is **required** (no default - the caller must choose where the run is recorded):

```bash
python my_flow.py --data_folder ./data --run-on local       # ephemeral, no server (full year)
python my_flow.py --data_folder ./data --run-on local --sample_rows 8000  # fast smoke test
python my_flow.py --data_folder ./data --run-on server      # record the run on the Prefect server
# full pipeline.py-style invocation (records on the team server):
python my_flow.py --git_repo <r> --git_commit_hash <c> --member <m> --data_folder ./data --run-on server
```

`optuna.json -> environment -> sample_rows` is `null` by default, so a run uses all 52,416 rows. The
`--sample_rows N` CLI flag overrides it (no config edit) to take only the most-recent N rows -
a fast smoke test that checks the DAG end to end. `target_zone` (`Zone1` / `Zone2` / `Zone3`)
picks the target.

`--run-on` chooses where the run is recorded: **`local`** clears `PREFECT_API_URL` for the run so
Prefect executes it ephemerally (a throwaway in-process server) - nothing reaches the team server;
**`server`** sends the flow run, tasks, and artifacts to the configured Prefect server
(`PREFECT_API_URL`), the way `pipeline.py` runs this payload inside the compose network (so
`pipeline.py` and any team-server run pass `--run-on server`). A `local` run that should also
avoid the team Optuna DB needs `optuna.json -> environment -> storage` set to a local DSN (e.g.
`sqlite:///optuna.db`); otherwise `train` still dials the Postgres in the member's block.

Environment: this repo's deps (prefect, lightgbm, optuna, scikit-learn, pandas,
pyarrow) live in the conda `base` env here, so prefix commands with
`conda run -n base python ...` if `python` is not the base interpreter on PATH.

The default full-year run (all 52,416 rows) is a genuine **seasonal-extrapolation** problem -
the most-recent 20% (late Oct–Dec) is a colder regime under-represented before the cut - so it
reaches **val R2 approx 0.85** and **test R2 approx 0.56**. That gap is the honest cost of
forecasting a season the training span barely covers, not a bug; it is the headline lesson of a
chronological split. A fast smoke test on the most-recent 8,000 rows (`--sample_rows 8000`, approx
55 days) keeps train / validation / test inside one season, so it runs in seconds and reaches
about **val R2 = 0.96** / **test R2 = 0.96** - useful for checking the DAG, not for judging the model.

## 6. Pipeline

```text
training:  load_config -> train_prepare -> train_featurize -> train -> validate
test:      test_prepare  -> test_featurize  -> test     (reuses scaler / features / model)
after each: parity_plot + publish_artifacts fire after each of train / validate / test
```

The data is **one CSV**, so both lanes read the same `powerconsumption.csv` and slice it by time
from the same config: the training lane takes everything before the test cut (`train_prepare` /
`train_featurize`), the test lane takes the most-recent slice (`test_prepare` /
`test_featurize`). The test lane reuses the training `scaler.json` + `features.json` (from
`train_featurize`) and `model.txt` (from `train`). The only split the code makes inside the
training span is **train vs validation**, fixed in `train_prepare` (by time, via `split.json`).

Data flows top to bottom; **every box is a `@task`**. The label on every arrow is the data
passed along (`data/` = input CSV, `work/` = run artifacts):

Left column = **training lane**, right column = **test lane**. The two horizontal arrows are
the hand-off: `train_featurize` passes the fitted `scaler.json` + `features.json` to
`test_featurize`, and **`train` passes the fitted `model.txt` to `test`**.

```text
                          TRAINING LANE                              TEST LANE
                   data/powerconsumption.csv                  data/powerconsumption.csv
                   (rows before the test cut)                 (most-recent test_fraction)
                                   │                                  │
                                   ▼                                  ▼
 ┌─────────────┐           ┌────────────────┐               ┌────────────────┐
 │ load_config │──cfg─────▶│  train_prepare │               │  test_prepare  │
 └─────────────┘           └───────┬────────┘               └───────┬────────┘
                                   │ trainval_raw, split.json        │ test_raw
                                   ▼                                  ▼
                           ┌────────────────┐ scaler.json + ┌────────────────┐
                           │ train_featurize│─features.json▶│ test_featurize │
                           └───────┬────────┘               └───────┬────────┘
                                   │ train/val.parquet               │ test.parquet
                                   ▼                                  ▼
   ┌───────────┐           ┌────────────────┐   model.txt   ┌────────────────┐
   │ optuna DB │◀──trials──│      train     │──────────────▶│      test      │
   └───────────┘           └───────┬────────┘               └───────┬────────┘
       parity_plot (train) ◀───────┤                                ├──▶ parity_plot (test)
   publish_artifacts (train) ◀─────┤ model + metrics       metrics  └──▶ publish_artifacts (test)
                                   ▼                      + pred.csv
                           ┌────────────────┐
                           │    validate    │
                           └───────┬────────┘
        parity_plot (validation) ◀─┤
   publish_artifacts (validation) ◀┤ val metrics
                                   ▼
        each stage emits both: parity_plot -> work/parity_<stage>.png ; publish_artifacts -> Prefect UI
```

The boxes run concurrently where the DAG allows (`.submit()` + `wait_for`): the test lane runs
alongside training, joining only where it needs the training `scaler.json` / `features.json`
(`test_featurize` waits for `train_featurize`) and `model.txt` (`test` waits for `train`). The
flow returns the combined `summary` dict (train + val + test metrics) for `pipeline.py`. Each
diagram function, in pipeline order:

### load_config

1. Re-read `optuna.json` **fresh on every run** (so edits take effect without a restart).
2. Return the `cfg` dict: `n_trials`, `cv_folds`, `val_fraction`, `test_fraction`, `sample_rows`,
   `target_zone`, `random_state`, `storage`, `mlflow_uri`, `study_name`, `lgbm_fixed`.

### train_prepare

1. Read `powerconsumption.csv`, parse `Datetime`, and sort by time (tolerant of the UCI header
   spelling, mapped onto the Kaggle schema).
2. Optionally keep only the most recent `sample_rows` rows (`null` = all 52,416) for a quick run.
3. Compute the test cut (`1 - test_fraction`) and keep everything before it as the train+val span.
4. Fix the by-time train/val split (`1 - val_fraction`) as a contiguous tail of that span - so
   validation sits right before the test slice.
5. Write `trainval_raw.parquet`, `split.json` (the `val_start` timestamp) - raw rows + the split
   decision (no scaling, no features yet).

### train_featurize

1. Read `trainval_raw.parquet`, `split.json`.
2. **Normalization - per-feature 0-1 min-max scaling, *fit* on training rows only.** For each of
   the 5 weather features, take `lo = min` and `hi = max` over the **train** rows (before
   `val_start`) and rescale

   ```
   x_scaled = (x - lo) / (hi - lo)        # per feature; a constant feature (hi == lo) -> 0
   ```

   so each weather feature lands in `[0, 1]`. Only the 5 weather columns are scaled - the
   calendar features stay raw.
3. Save the `{feature: [lo, hi]}` map as **`scaler.json`** (the test lane reuses it).
4. **Feature engineering** - derive the 9 calendar features (`hour`, `dayofweek`, `is_weekend` +
   cyclical sin/cos of `hour` / `dayofweek` / `month`) for every row, and attach the selected
   `target_zone` as `y`.
5. Apply `split.json` -> write `train.parquet`, `val.parquet`, `features.json`.

> LightGBM is scale-invariant (it splits on order, not magnitude), so this 0-1 scaling does
> **not** move the score - it is a structural preprocessing stage that keeps train and test on
> one scale.

### train

1. Read `train.parquet` + `features.json`.
2. Run **Optuna** (TPE sampler, `random_state`) over the `LGBMRegressor` hyper-parameters
   (`n_estimators` 200–1200, `learning_rate`, `num_leaves`, `max_depth`, `min_child_samples`,
   `subsample`, `colsample_bytree`, `reg_alpha`, `reg_lambda`), scoring each trial by **5-fold
   CV-RMSE** (plain `KFold` `cross_val_score`; the temporal evaluation lives in validate / test).
3. Log every trial to the `optuna DB` and, best-effort, to MLflow.
4. Refit the best params on the full training set; save `model.txt`.
5. Compute the train-set RMSE / MAE / R2 and the top-15 features by gain.
6. Return the model **and** its metrics (best CV-RMSE + train metrics + top features).

### validate

1. Read `val.parquet` + `model.txt`.
2. Predict the held-out validation rows (the tail just before the test slice).
3. Score RMSE / MAE / R2 - a single **by-time hold-out**, **not k-fold and not random** (the
   5-fold CV lives inside `train`).

### test_prepare

1. Read the same CSV and slice the most-recent `test_fraction` (the test span is fixed by config).
2. Write `test_raw.parquet` - no target selection, no scaling, no split.

### test_featurize

1. Read `test_raw.parquet`, the training `scaler.json`, and `features.json`.
2. **Normalization - *apply* mode.** Rescale the test weather with the **same**
   `(x - lo) / (hi - lo)` using the *training* `lo`/`hi` - **no re-fit** - so train and test share
   one scale (a test value outside the training range lands outside `[0, 1]`).
3. Derive the same 14 features and attach `y` (the true target, for scoring).
4. Align them to the training `features.json` schema (fill any missing column with NaN).
5. Write `test.parquet` (no split).

### test

1. Read `test.parquet` + `model.txt`.
2. Predict, and write `work/powerconsumption-test-pred.csv` (`Datetime, y_true, y_pred`).
3. Score the test slice (RMSE / MAE / R2) - the single dataset always carries the true target.

### parity_plot

1. Take a stage's `y_true` / `y_pred`.
2. Draw the 1:1 chart (with the `y = x` line and R2), titled by the stage (thread-safe `Figure`
   API).
3. Save `work/parity_<stage>.png` and embed it in the Prefect UI.

> Fires right after **train**, **validate**, and **test** (3 runs).

### publish_artifacts

1. Take a stage's metrics.
2. Build a metrics table + markdown, keyed `epc-power-metrics-<stage>` (the train call also
   publishes the top-feature table).
3. Attach them to the Prefect UI - best-effort, so a pure-local run with no API backend just skips.

> Fires right after each stage too, mirroring `parity_plot`.

Prefect features used: `@flow`/`@task`, `flow_run_name`/`task_run_name`, tags,
retries, `ThreadPoolTaskRunner` + `.submit()`/`wait_for` DAG, `get_run_logger`, and
table/markdown artifacts.

## 7. Iterations

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
- `retries` (train_prepare 2, train 1) only add runs on failure - 0 on a clean run.
- `sample_rows` is data size, not iterations: `null` uses all 52,416 rows but still
  runs the same 20 trials.

## 8. Optuna dashboard

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
to the same `study_name` (`epc_power`).

`optuna.json -> environment -> storage` is an **override**: leave it `null` to use the
`postgresql_optuna` block (default), or set a full DSN (e.g. a local
`sqlite:///optuna.db` or a test Postgres) to point elsewhere.

## 9. MLflow metrics

`train` also logs each Optuna trial to the team **MLflow** server as a metric step, so the
MLflow UI draws a per-trial curve. This is the place for metric curves; the optuna-dashboard
above is for the tuning plots. Logging is **best-effort** - if MLflow is unreachable the run
prints `MLflow disabled ...` and continues, so a local dry run never fails on it.

Logged in one run named `<member>@<commit>` under experiment `epc_power`:

| Metric / field | Meaning |
|---|---|
| `cv_rmse` (step = trial number) | that trial's CV-RMSE - the per-trial curve |
| `best_cv_rmse` (step = trial number) | running best so far (monotonic) |
| `final_cv_rmse` + best params | the chosen result, logged once at the end |
| `train_rmse` | the refit model's RMSE on the training set, logged once at the end |

View it on the stack's MLflow server:

```bash
# host: http://localhost:5000   (inside the compose network: http://mlflow:5000)
# Experiments -> epc_power -> run <member>@<commit> -> Metrics -> cv_rmse  (x = trial, y = RMSE)
```

`optuna.json -> environment -> mlflow_uri` is an **override**: leave it `null` to use `http://mlflow:5000`
(the compose service, how `pipeline.py` runs this payload), or set `http://localhost:5000`
when you run `my_flow.py` directly on the host. The tracking URI is a plain service address,
not a secret, so it stays in config - unlike the DB / MinIO creds, which come from the
member's `Credentials` block.

## 10. Appendix - Prefect syntax

A quick reference for every Prefect construct used in `my_flow.py`.

### Decorators - `@task`, `@flow`

`@task` / `@flow` wrap a plain function so Prefect runs, tracks, and shows it in the UI.

```python
@task(name="train", task_run_name="train", tags=["epc", "model"],
      retries=1, retry_delay_seconds=2, log_prints=True)
def train(prep, cfg, storage, mlflow_uri="", run_name=""): ...

@flow(name="epc_power", flow_run_name="{member}@{git_commit_hash}", log_prints=True,
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
prep  = train_prepare.submit(data_dir, work, cfg)           # training lane (schedule -> future, non-blocking)
fz    = train_featurize.submit(prep, cfg, wait_for=[prep])  # scale + calendar features + split; after train_prepare
tr    = train.submit(fz, cfg, storage, wait_for=[fz])       # start after train_featurize finishes
va    = validate.submit(tr, fz, wait_for=[tr])              # held-out validation scoring
tprep = test_prepare.submit(data_dir, work, cfg)            # test lane, concurrent with training
tfz   = test_featurize.submit(tprep, cfg, wait_for=[tprep, fz])  # needs scaler.json + features.json
te    = test.submit(tr, tfz, data_dir, wait_for=[tr, tfz])  # needs model.txt from train
metrics, pred = va.result(), te.result()                    # block until done; re-raises on failure
parity_plot.submit(metrics["val_true"], metrics["val_pred"], "validation", work, wait_for=[va])
```

| Call | What it does |
|---|---|
| `task.submit(...)` | schedule the task on the task runner; returns a `PrefectFuture` at once (non-blocking) - this is what enables concurrency |
| `wait_for=[...]` | ordering edge: hold the task until those futures finish - used to build the DAG |
| `future.result()` | block until the task finishes and return its value (raises if the task failed) |
| `ThreadPoolTaskRunner(max_workers=4)` | run up to 4 submitted tasks at the same time |

Passing a future as an argument (`train.submit(fz, ...)`) already creates a data
dependency; `wait_for` adds explicit ordering even when no data is passed between them.

### Logging and artifacts

```python
log = get_run_logger()                 # logger bound to this run -> UI logs
log.info("start ...")

create_table_artifact(key="epc-power-metrics", table=rows, description="...")     # list[dict] -> UI table
create_markdown_artifact(key="epc-power-summary", markdown=md, description="...") # markdown -> UI panel
md = f"flow run: {flow_run.name} ({flow_run.id})"                                 # current run's name / id
```

| Call | What it does |
|---|---|
| `get_run_logger()` | logger tied to the current flow / task run; messages show in the UI |
| `create_table_artifact(key, table, description)` | attach a table (`list[dict]`) to the run, rendered in the UI |
| `create_markdown_artifact(key, markdown, description)` | attach a markdown block to the run |
| `flow_run.name` / `flow_run.id` | runtime context (`from prefect.runtime import flow_run`): the current run's name / id |
