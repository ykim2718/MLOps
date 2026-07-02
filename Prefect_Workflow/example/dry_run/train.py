"""train.py — model training with Optuna tuning (LightGBM)

Optuna calls objective() once per trial: it suggests LightGBM hyperparameters,
scores them with cross-validation, and returns the score; Optuna uses that to pick
the next trial. The best params then train the final model.

input : feature/train_feature.npz, optuna.json (n_trials)
output: model/model.txt (LightGBM booster), artifacts/train.json (best params/score)
"""
import json
import os

import lightgbm as lgb
import numpy as np
import optuna
from sklearn.model_selection import cross_val_score


def run(work_dir, optuna_cfg="optuna.json"):
    feat = os.path.join(work_dir, "feature", "train_feature.npz")
    model_dir = os.path.join(work_dir, "model")
    art_dir = os.path.join(work_dir, "artifacts")
    os.makedirs(model_dir, exist_ok=True)
    os.makedirs(art_dir, exist_ok=True)

    n_trials, direction = 5, "maximize"
    if os.path.exists(optuna_cfg):
        with open(optuna_cfg, encoding="utf-8") as f:
            cfg = json.load(f)
        n_trials = cfg.get("n_trials", n_trials)
        direction = cfg.get("direction", direction)

    d = np.load(feat)
    X, y = d["X"], d["y"]

    def objective(trial):                                          # Optuna calls this each trial
        params = dict(
            num_leaves=trial.suggest_int("num_leaves", 8, 64),
            learning_rate=trial.suggest_float("learning_rate", 1e-3, 0.3, log=True),
            n_estimators=trial.suggest_int("n_estimators", 30, 200),
        )
        clf = lgb.LGBMClassifier(verbose=-1, **params)
        return cross_val_score(clf, X, y, cv=3, scoring="accuracy").mean()   # score -> Optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction=direction)
    study.optimize(objective, n_trials=n_trials)                  # call objective n_trials times

    best = lgb.LGBMClassifier(verbose=-1, **study.best_params)    # final fit on full train
    best.fit(X, y)
    model_path = os.path.join(model_dir, "model.txt")
    best.booster_.save_model(model_path)

    meta = {"best_params": study.best_params, "best_cv_accuracy": round(study.best_value, 4),
            "model_path": model_path, "n_trials": n_trials}
    with open(os.path.join(art_dir, "train.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print(f"[train] best={study.best_params} cv_acc={study.best_value:.4f} -> {model_path}")
    return meta


if __name__ == "__main__":
    run("data")
