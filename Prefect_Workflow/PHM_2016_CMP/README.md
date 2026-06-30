# PHM 2016 CMP - Virtual Metrology (LightGBM)

<sub>rev. 30</sub>

Predicts wafer **AVG_REMOVAL_RATE** (a continuous target - the same Virtual Metrology
shape as film-thickness / etch-rate prediction) from CMP tool sensor trajectories,
using LightGBM. `my_flow.py` is the Prefect entrypoint.

## 1. Layout

| File | Role |
|---|---|
| `download_data.py` | Fetch the PHM 2016 CMP data into `./data` (token-free) |
| `my_flow.py` | Prefect flow entrypoint: train_prepare -> train_featurize -> train -> validate; test lane test_prepare -> test_featurize -> test; parity_plot per stage |
| `optuna.json` | Tuning + run config (trials, CV folds, wafer sample size) |
| `data/` | CSVs land here (created by `download_data.py`; git-ignored) |

## 2. Get the data

```bash
python download_data.py                 # download + unzip into ./data (no account needed)
python download_data.py --url <zip-url>  # use a different mirror if you have one
```

### Data source

The official 2016 PHM Data Challenge sources are gone (the CFP Dropbox link serves a JS
page; phmsociety.org migrated, so its file links 404) and the set is not on Kaggle. The
one reliable, **token-free** source left is the Internet Archive's Wayback Machine.
`download_data.py` pulls two zips from the 2020-07-27 snapshot, each with the `id_`
marker that returns the original bytes (not the Wayback HTML wrapper):

```text
# CMP data set  (approx 9.4 MB)
https://web.archive.org/web/20200727094500id_/https://www.phmsociety.org/sites/phmsociety.org/files/2016%20PHM%20DATA%20CHALLENGE%20CMP%20DATA%20SET.zip

# test answers  (approx 9 KB, released after the competition)
https://web.archive.org/web/20200727104606id_/https://www.phmsociety.org/sites/phmsociety.org/files/PHM16TestValidationAnswers.zip
```

### Metadata

| Field | Value |
|---|---|
| Provenance | 2016 PHM Society Data Challenge - CMP, via Wayback snapshot 2020-07-27 |
| Format | CSV, comma-separated, header row on every file |
| Size | approx 9.4 MB zip, approx 161 MB extracted |
| Trajectory rows | 672,744 timestamp rows across 185 training files (25 columns each) |
| Labeled samples | training 1,981 / test 424, keyed by `(WAFER_ID, STAGE)` |
| Target | `AVG_REMOVAL_RATE` float; the test template withholds it as `?` |

### Data files

**x and y are separate files.** The sensor trajectories (x) never carry the target;
`AVG_REMOVAL_RATE` (y) lives in its own `*-removalrate.csv` / `*-answers.csv` file and
is joined back on `(WAFER_ID, STAGE)`.

| File | Set | Role | Content |
|---|---|---|---|
| `CMP-training-000..184.csv` | training | x (inputs) | 185 files, 25 columns of sensor trajectories, **with a header row** |
| `CMP-training-removalrate.csv` | training | y (target) | `WAFER_ID, STAGE, AVG_REMOVAL_RATE` |
| `CMP-test-000..184.csv` | test | x (inputs) | 185 files, same shape as training |
| `CMP-test-removalrate.csv` | test | y (template) | submission template, `AVG_REMOVAL_RATE` is `?` |
| `CMP-test-answers.csv` | test | y (answers) | official held-out answers, used to score test |

## 3. Data set and splits

The raw data is **time-series sensor trajectories**: every wafer is polished in stage
A and/or B, and each polishing run logs 150–400 timestamped sensor rows. The target
(`AVG_REMOVAL_RATE`) is one scalar per `(WAFER_ID, STAGE)`, so the **modeling unit is a
whole trajectory**, not a single timestamp row.

### Bronze vs silver

Two layers, one transform - `download_data.py` lands **bronze**, `train_featurize` folds it
into **silver** (the model-ready table):

| Layer | Built by | File | Grain (one row =) | Training rows | Columns |
|---|---|---|---|---|---|
| bronze | `download_data.py` | `data/CMP-*.csv` | one timestamp sample | 672,744 | 25 raw (context 6 + sensor 19) |
| silver | `train_featurize` | `work/{train,val}.parquet` | one `(WAFER_ID, STAGE)` trajectory | 1,981 | 155 features + y |

`train_featurize` collapses each trajectory's hundreds of bronze rows into one silver row. The three
non-sensor features are **born in this step** and do not exist in bronze:

```text
bronze column                          silver feature (one per trajectory)
─────────────                          ───────────────────────────────────
TIMESTAMP       ── count rows ──────▶  n_samples   (numeric)
TIMESTAMP       ── max - min ───────▶  duration    (numeric)
STAGE (A/B)     ── == "B" ? 1 : 0 ──▶  stage_is_B  (category, 0/1)
sensor x7..x25  ── mean/std/min/max/median + last/delta/slope ──▶  152 features
```

In bronze, x (trajectories) and y (`AVG_REMOVAL_RATE`) sit in separate files; silver joins
them on `(WAFER_ID, STAGE)` into one table.

### Sizes and splits

| Set | Trajectory files | Raw rows (timestamp-level) | Labeled samples (wafer-stage) |
|---|---|---|---|
| training | 185 | 672,744 x 25 | **1,981** (1,699 wafers; stage A 1,166 / B 815) |
| test | 185 | comparable | **424** (answers in `CMP-test-answers.csv`) |

`AVG_REMOVAL_RATE` over the 1,981 training samples: min 53.4, max 4,326.2, mean 98.6,
std 187.4 - a long right tail (a few extreme wafers), so RMSE is dominated by outliers.

> The official challenge also ships a separate 424-wafer *validation* zip; this project
> does not use it. "validation" below means an internal hold-out carved from training.

How the train/val split works (`train_prepare` fixes it, `train_featurize` applies it; **by
wafer**, so a wafer's A and B rows never straddle train and validation):

| Split | How | Default run (`sample_wafers: 300`) | Full run (`sample_wafers: null`) |
|---|---|---|---|
| train | 80% of training wafers | 278 samples | approx 1,585 samples |
| validation | 20% of training wafers (held out) | 75 samples | approx 396 samples |
| test | official test set, scored vs answers | 424 samples | 424 samples |

## 4. Inputs (x) and target (y)

### Inputs (x)

Each raw row has **25 columns** = 6 context + 19 process sensors:

- **context (6)**: `MACHINE_ID, MACHINE_DATA, TIMESTAMP, WAFER_ID, STAGE, CHAMBER`
- **process sensors (19, `x7..x25`)**: usage measures (backing film, dresser, tables,
  membrane, sheet), pressures (chamber, air bags, retainer ring, edge), slurry flow
  A/B/C, rotations (wafer, stage, head), dressing-water status

`train_featurize` aggregates each trajectory into **155 features**:

| Feature group | Count |
|---|---|
| 19 sensors x {mean, std, min, max, median} | 95 |
| 19 sensors x {last, delta (last-first), slope (delta/duration)} | 57 |
| `n_samples`, `duration`, `stage_is_B` | 3 |
| **total x features** | **155** |

Per-sensor range over all 672,744 training timestamp rows (raw units, before aggregation):

| Sensor | min | max | mean | std |
|---|---|---|---|---|
| x7 USAGE_BACKING_FILM | 19.17 | 10532.50 | 4968.53 | 2888.63 |
| x8 USAGE_DRESSER | 5.19 | 771.85 | 396.44 | 219.52 |
| x9 USAGE_POLISHING_TABLE | 0.00 | 357.04 | 171.98 | 94.62 |
| x10 USAGE_DRESSER_TABLE | 2664.75 | 4305.50 | 3496.35 | 479.74 |
| x11 PRESSURIZED_CHAMBER_PRESSURE | 0.00 | 189.05 | 49.97 | 39.24 |
| x12 MAIN_OUTER_AIR_BAG_PRESSURE | 0.00 | 499.20 | 155.33 | 133.19 |
| x13 CENTER_AIR_BAG_PRESSURE | 0.00 | 139.38 | 40.15 | 34.24 |
| x14 RETAINER_RING_PRESSURE | 0.00 | 10662.60 | 1218.78 | 1499.22 |
| x15 RIPPLE_AIR_BAG_PRESSURE | 0.00 | 22.50 | 5.96 | 5.05 |
| x16 USAGE_MEMBRANE | 0.23 | 124.89 | 58.92 | 34.25 |
| x17 USAGE_PRESSURIZED_SHEET | 5.75 | 3159.75 | 1490.56 | 866.59 |
| x18 SLURRY_FLOW_LINE_A | 0.00 | 42.64 | 4.25 | 6.68 |
| x19 SLURRY_FLOW_LINE_B | 0.00 | 12.50 | 0.73 | 0.42 |
| x20 SLURRY_FLOW_LINE_C | 0.00 | 1083.60 | 249.35 | 214.03 |
| x21 WAFER_ROTATION | 0.00 | 34.88 | 12.80 | 16.33 |
| x22 STAGE_ROTATION | 0.00 | 263.55 | 52.44 | 91.88 |
| x23 HEAD_ROTATION | 0.00 | 192.00 | 159.79 | 8.89 |
| x24 DRESSING_WATER_STATUS | 0.00 | 1.00 | 0.42 | 0.49 |
| x25 EDGE_AIR_BAG_PRESSURE | 0.00 | 141.52 | 28.53 | 24.35 |

**shapes** (full run): X_train `(1981, 155)` before split, y `(1981,)`; test X
`(424, 155)`, y `(424,)`. Default sampled run: train `(278, 155)`, val `(75, 155)`,
test `(424, 155)`.

### Target (y)

`AVG_REMOVAL_RATE` - a continuous float scalar (**regression**, not classification; there
are no class labels). `STAGE` (A/B) is a categorical *input*, encoded as `stage_is_B`.

The train set has a long right tail (a few extreme wafers) that the test set lacks, so the
two differ in scale:

| Set | count | min | max | mean | std |
|---|---|---|---|---|---|
| train | 1,981 | 53.4 | 4,326.2 | 98.6 | 187.4 |
| test | 424 | 54.5 | 163.8 | 89.9 | 29.6 |

The values fall in two clumps - a large one at 50–100 and a smaller 125–200 one - with a
near-empty gap at 100–125 and a few extreme outliers. The split is by `STAGE`, which is exactly
why `stage_is_B` is a useful feature:

```text
AVG_REMOVAL_RATE - training distribution (1,981 samples; each █ ~ 25 wafers)

 [  50,  75)   695  ████████████████████████████
 [  75, 100)   917  █████████████████████████████████████
 [ 100, 125)     1  ·
 [ 125, 150)   142  ██████
 [ 150, 200)   222  █████████
 [ 200,  1k)     0
 [  1k, 4.4k]    4  ·   <- extreme outliers (all stage A; max 4,326)

 stage B (815): all <= 101.5  - tight and low, mean 80
 stage A (1166): spans the 125-200 clump + every outlier, mean 112
```

## 5. Run the flow

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

## 6. Pipeline

```text
training:  load_config -> train_prepare -> train_featurize -> train -> validate
test:      test_prepare  -> test_featurize  -> test     (reuses scaler / features / model)
after each: parity_plot + publish_artifacts fire after each of train / validate / test
```

The training and test sets are **separate official datasets** (`CMP-training-*` vs
`CMP-test-*`), so each lane has its own prepare + featurize (`train_prepare`/`train_featurize`
and `test_prepare`/`test_featurize`); the test lane reuses the training `scaler.json` +
`features.json` (from `train_featurize`) and `model.txt` (from `train`). The only split the
code makes is **train vs validation**, inside `train_featurize` (by wafer, via `split.json`).

Data flows top to bottom; **every box is a `@task`**. The label on every arrow is the data
passed along (`data/` = input CSVs, `work/` = run artifacts):

Left column = **training lane**, right column = **test lane**. The two horizontal arrows are
the hand-off: `train_featurize` passes the fitted `scaler.json` + `features.json` to
`test_featurize`, and **`train` passes the fitted `model.txt` to `test`**.

```text
                          TRAINING LANE                              TEST LANE
                  data/CMP-training-*.csv +                  data/CMP-test-*.csv +
                  CMP-training-removalrate.csv               CMP-test-answers.csv
                                   │                                  │
                                   ▼                                  ▼
 ┌─────────────┐           ┌────────────────┐               ┌────────────────┐
 │ load_config │──cfg─────▶│  train_prepare │               │  test_prepare  │
 └─────────────┘           └───────┬────────┘               └───────┬────────┘
                                   │ rate, split.json                │ test_traj_raw
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
2. Return the `cfg` dict: `n_trials`, `cv_folds`, `val_fraction`, `sample_wafers`, `random_state`,
   `storage`, `mlflow_uri`, `study_name`, `lgbm_fixed`.

### train_prepare

1. Read the 185 `CMP-training-*.csv` trajectory files.
2. Read `CMP-training-removalrate.csv` (the target); rename `AVG_REMOVAL_RATE` -> `y`; coerce `?`
   placeholders -> NaN.
3. Optionally sub-sample wafers (`sample_wafers`, default 300) with `RandomState(random_state)`.
4. Fix the by-wafer train/val split (80/20 via `val_fraction`) by shuffling the sorted unique
   wafers with that same RNG.
5. Write `traj_raw.parquet`, `rate.parquet`, `split.json` - raw rows + the split decision (no
   scaling, no features yet).

### train_featurize

1. Read `traj_raw.parquet`, `rate.parquet`, `split.json`.
2. **Normalization - per-sensor 0-1 min-max scaling, *fit* on training.** For each of the 19
   process sensors `x7..x25`, take `lo = min` and `hi = max` over **all** training rows and
   rescale every value

   ```
   x_scaled = (x - lo) / (hi - lo)        # per sensor; a constant sensor (hi == lo) -> 0
   ```

   so each sensor lands in `[0, 1]`. Only the 19 sensors are scaled - `TIMESTAMP` and `STAGE`
   stay raw.
3. Save the `{sensor: [lo, hi]}` map as **`scaler.json`** (the test lane reuses it).
4. **Feature engineering** - aggregate each (now-scaled) `(WAFER_ID, STAGE)` trajectory into 155
   features (mean/std/min/max/median + last/delta/slope over the 19 sensors, plus
   `n_samples`/`duration`/`stage_is_B`).
5. Merge the target and drop rows with no `y`.
6. Apply `split.json` -> write `train.parquet`, `val.parquet`, `features.json`.

> LightGBM is scale-invariant (it splits on order, not magnitude), so this 0-1 scaling does
> **not** move the score - it is a structural preprocessing stage that keeps train and test on
> one scale.

### train

1. Read `train.parquet` + `features.json`.
2. Run **Optuna** (TPE sampler, `random_state`) over the `LGBMRegressor` hyper-parameters
   (`n_estimators` 200–1200, `learning_rate`, `num_leaves`, `max_depth`, `min_child_samples`,
   `subsample`, `colsample_bytree`, `reg_alpha`, `reg_lambda`), scoring each trial by **5-fold
   CV-RMSE** (plain `KFold` `cross_val_score`).
3. Log every trial to the `optuna DB` and, best-effort, to MLflow.
4. Refit the best params on the full training set; save `model.txt`.
5. Compute the train-set RMSE / MAE / R2 and the top-15 features by gain.
6. Return the model **and** its metrics (best CV-RMSE + train metrics + top features).

### validate

1. Read `val.parquet` + `model.txt`.
2. Predict the held-out validation wafers.
3. Score RMSE / MAE / R2 - a single **by-wafer hold-out** (the 20% carved by `train_prepare`),
   **not k-fold and not temporal** (the 5-fold CV lives inside `train`).

### test_prepare

1. Read the official `CMP-test-*.csv` trajectories.
2. Write `test_traj_raw.parquet` - no target, no sampling, no split (the test set is fixed).

### test_featurize

1. Read `test_traj_raw.parquet`, the training `scaler.json`, and `features.json`.
2. **Normalization - *apply* mode.** Rescale the test sensors with the **same**
   `(x - lo) / (hi - lo)` using the *training* `lo`/`hi` - **no re-fit** - so train and test share
   one scale (a test value outside the training range lands outside `[0, 1]`).
3. Aggregate into the 155 features.
4. Align them to the training `features.json` schema (fill any missing column with NaN).
5. Write `test.parquet` (no split).

### test

1. Read `test.parquet` + `model.txt`.
2. Predict, and write `work/CMP-test-removalrate-pred.csv` (the `?` template is left intact).
3. If `CMP-test-answers.csv` is present, score the test set (RMSE / MAE / R2).

### parity_plot

1. Take a stage's `y_true` / `y_pred`.
2. Draw the 1:1 chart (with the `y = x` line and R2), titled by the stage (thread-safe `Figure`
   API).
3. Save `work/parity_<stage>.png` and embed it in the Prefect UI.

> Fires right after **train**, **validate**, and **test** (3 runs).

### publish_artifacts

1. Take a stage's metrics.
2. Build a metrics table + markdown, keyed `cmp-vm-metrics-<stage>` (the train call also publishes
   the top-feature table).
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
- `sample_wafers` is data size, not iterations: `null` uses all 1,981 samples but still
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
to the same `study_name` (`cmp_vm`).

`optuna.json -> storage` is an **override**: leave it `null` to use the
`postgresql_optuna` block (default), or set a full DSN (e.g. a local
`sqlite:///optuna.db` or a test Postgres) to point elsewhere.

## 9. MLflow metrics

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
| `train_rmse` | the refit model's RMSE on the training set, logged once at the end |

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

## 10. Appendix - Prefect syntax

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
prep  = train_prepare.submit(data_dir, work, cfg)       # training lane (schedule -> future, non-blocking)
fz    = train_featurize.submit(prep, cfg, wait_for=[prep])  # scale + aggregate + split; after train_prepare
tr    = train.submit(fz, cfg, storage, wait_for=[fz])   # start after train_featurize finishes
va    = validate.submit(tr, fz, wait_for=[tr])          # held-out validation scoring
tprep = test_prepare.submit(data_dir, work)             # test lane, concurrent with training
tfz   = test_featurize.submit(tprep, wait_for=[tprep, fz])  # needs scaler.json + features.json
te    = test.submit(tr, tfz, data_dir, wait_for=[tr, tfz])  # needs model.txt from train
metrics, pred = va.result(), te.result()                # block until done; re-raises on failure
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
