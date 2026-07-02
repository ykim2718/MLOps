"""train_fe.py — feature engineering (train)

Fits a scaler on the TRAIN data (type chosen by optuna.json fe.scaling) and saves
the fitted statistics (center/scale) to artifacts/fe_train.json. test_fe reuses
these — transform only, no fit — so train/test share identical scaling (no skew).

input : interim/train_transformed.npz, optuna.json
output: feature/train_feature.npz, artifacts/fe_train.json
"""
import json
import os

import numpy as np
from sklearn.preprocessing import MinMaxScaler, StandardScaler


def run(work_dir, optuna_cfg="optuna.json"):
    interim = os.path.join(work_dir, "interim", "train_transformed.npz")
    feat_dir = os.path.join(work_dir, "feature")
    art_dir = os.path.join(work_dir, "artifacts")
    os.makedirs(feat_dir, exist_ok=True)
    os.makedirs(art_dir, exist_ok=True)

    cfg = {}
    if os.path.exists(optuna_cfg):
        with open(optuna_cfg, encoding="utf-8") as f:
            cfg = json.load(f)
    scaling = cfg.get("fe", {}).get("scaling", "standard")

    d = np.load(interim)
    X, y = d["X"], d["y"]

    # Both scalers reduce to (X - center) / scale, so test_fe can re-apply with two arrays.
    if scaling == "minmax":
        sc = MinMaxScaler().fit(X)                                 # FIT only on train
        center, scale = sc.data_min_, sc.data_range_
    else:
        sc = StandardScaler().fit(X)                              # FIT only on train
        center, scale = sc.mean_, sc.scale_
    scale = np.where(scale == 0, 1.0, scale)                      # guard constant columns

    X_scaled = (X - center) / scale
    np.savez(os.path.join(feat_dir, "train_feature.npz"), X=X_scaled, y=y)

    fe_meta = os.path.join(art_dir, "fe_train.json")
    with open(fe_meta, "w", encoding="utf-8") as f:
        json.dump({"scaling": scaling, "center": center.tolist(), "scale": scale.tolist()}, f)

    print(f"[train_fe] {interim} -> feature/train_feature.npz, {fe_meta} (scaling={scaling})")
    return fe_meta


if __name__ == "__main__":
    run("data")
