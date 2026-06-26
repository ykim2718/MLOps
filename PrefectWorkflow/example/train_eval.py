"""train_eval.py — evaluate the trained model on the train set

input : feature/train_feature.npz, model/model.txt
output: artifacts/train_eval.json
"""
import json
import os

import lightgbm as lgb
import numpy as np
from sklearn.metrics import accuracy_score, f1_score


def run(work_dir):
    feat = os.path.join(work_dir, "feature", "train_feature.npz")
    model_path = os.path.join(work_dir, "model", "model.txt")
    out = os.path.join(work_dir, "artifacts", "train_eval.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    d = np.load(feat)
    X, y = d["X"], d["y"]
    booster = lgb.Booster(model_file=model_path)
    pred = (booster.predict(X) >= 0.5).astype(int)               # prob -> label

    metrics = {"train_accuracy": round(accuracy_score(y, pred), 4),
               "train_f1": round(f1_score(y, pred), 4)}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    print(f"[train_eval] -> {out} {metrics}")
    return metrics


if __name__ == "__main__":
    run("data")
