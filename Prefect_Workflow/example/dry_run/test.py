"""test.py — inference on the test set

Loads the model train.py produced and predicts on the test features.

input : feature/test_feature.npz, model/model.txt (from train)
output: artifacts/test.json (predictions + probabilities)
"""
import json
import os

import lightgbm as lgb
import numpy as np


def run(work_dir):
    feat = os.path.join(work_dir, "feature", "test_feature.npz")
    model_path = os.path.join(work_dir, "model", "model.txt")
    out = os.path.join(work_dir, "artifacts", "test.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    d = np.load(feat)
    X = d["X"]
    booster = lgb.Booster(model_file=model_path)                 # load the trained model
    proba = booster.predict(X)
    pred = (proba >= 0.5).astype(int)

    with open(out, "w", encoding="utf-8") as f:
        json.dump({"n": int(len(pred)), "predictions": pred.tolist(),
                   "proba": [round(float(p), 4) for p in proba]}, f)
    print(f"[test] {feat} (+{model_path}) -> {out} (n={int(len(pred))})")
    return out


if __name__ == "__main__":
    run("data")
