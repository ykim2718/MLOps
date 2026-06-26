"""test_fe.py — feature engineering (test)

Reuses the scaler fitted by train_fe (artifacts/fe_train.json) — transform only,
no fit — so train and test use the exact same scaling (no train/test skew).

input : interim/test_transformed.npz, artifacts/fe_train.json
output: feature/test_feature.npz, artifacts/fe_test.json
"""
import json
import os

import numpy as np


def run(work_dir):
    interim = os.path.join(work_dir, "interim", "test_transformed.npz")
    fe_train = os.path.join(work_dir, "artifacts", "fe_train.json")
    out_feat = os.path.join(work_dir, "feature", "test_feature.npz")
    out_meta = os.path.join(work_dir, "artifacts", "fe_test.json")
    os.makedirs(os.path.dirname(out_feat), exist_ok=True)

    with open(fe_train, encoding="utf-8") as f:
        fe = json.load(f)                                        # reuse train-fitted center/scale
    center, scale = np.array(fe["center"]), np.array(fe["scale"])

    d = np.load(interim)
    X, y = d["X"], d["y"]
    X_scaled = (X - center) / scale                             # APPLY only (no fit)
    np.savez(out_feat, X=X_scaled, y=y)
    with open(out_meta, "w", encoding="utf-8") as f:
        json.dump({"applied_from": fe_train, "scaling": fe["scaling"]}, f)

    print(f"[test_fe] {interim} (+{fe_train}) -> {out_feat}")
    return out_feat


if __name__ == "__main__":
    run("data")
