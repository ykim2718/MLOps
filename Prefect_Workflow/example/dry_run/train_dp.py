"""train_dp.py — data preparation (train)

Loads the sample dataset (sklearn breast_cancer — stands in for the MinIO raw
parquet), splits it into train/test, and writes the train "transformed" array.
Also writes raw/test.npz so test_dp reuses the exact same split (consistent,
no leakage).

input : none (sample dataset generated here)
output: raw/train.npz, raw/test.npz, interim/train_transformed.npz
"""
import os

import numpy as np
from sklearn.datasets import load_breast_cancer
from sklearn.model_selection import train_test_split


def run(work_dir, seed=42, test_size=0.2):
    raw = os.path.join(work_dir, "raw")
    interim = os.path.join(work_dir, "interim")
    os.makedirs(raw, exist_ok=True)
    os.makedirs(interim, exist_ok=True)

    X, y = load_breast_cancer(return_X_y=True)                     # sample data (stands in for raw parquet)
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=test_size, random_state=seed, stratify=y)

    np.savez(os.path.join(raw, "train.npz"), X=X_tr, y=y_tr)       # train split (used by train_fe)
    np.savez(os.path.join(raw, "test.npz"), X=X_te, y=y_te)        # test split (reused by test_dp / test_eval)

    # "transform": keep finite rows (a no-op cleaning step on this clean sample data).
    mask = np.isfinite(X_tr).all(axis=1)
    out = os.path.join(interim, "train_transformed.npz")
    np.savez(out, X=X_tr[mask], y=y_tr[mask])
    print(f"[train_dp] sample -> {out} (rows={int(mask.sum())}, cols={X_tr.shape[1]})")
    return out


if __name__ == "__main__":
    run("data")
