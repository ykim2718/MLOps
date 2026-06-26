"""test_dp.py — data preparation (test)

Reuses the raw test split that train_dp created and applies the same cleaning,
keeping train/test consistent.

input : raw/test.npz (from train_dp)
output: interim/test_transformed.npz
"""
import os

import numpy as np


def run(work_dir):
    raw = os.path.join(work_dir, "raw", "test.npz")
    out = os.path.join(work_dir, "interim", "test_transformed.npz")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    d = np.load(raw)
    X, y = d["X"], d["y"]
    mask = np.isfinite(X).all(axis=1)                            # same no-op cleaning as train_dp
    np.savez(out, X=X[mask], y=y[mask])
    print(f"[test_dp] {raw} -> {out} (rows={int(mask.sum())})")
    return out


if __name__ == "__main__":
    run("data")
