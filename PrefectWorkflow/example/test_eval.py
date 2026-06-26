"""test_eval.py — evaluate predictions on the test set

Compares test.py predictions against the held-out labels (raw/test.npz).

input : artifacts/test.json, raw/test.npz (ground-truth labels)
output: artifacts/test_eval.json
"""
import json
import os

import numpy as np
from sklearn.metrics import accuracy_score, f1_score


def run(work_dir):
    test_json = os.path.join(work_dir, "artifacts", "test.json")
    raw = os.path.join(work_dir, "raw", "test.npz")
    out = os.path.join(work_dir, "artifacts", "test_eval.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    with open(test_json, encoding="utf-8") as f:
        pred = np.array(json.load(f)["predictions"])
    y = np.load(raw)["y"]                                        # held-out ground truth

    metrics = {"test_accuracy": round(accuracy_score(y, pred), 4),
               "test_f1": round(f1_score(y, pred), 4)}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    print(f"[test_eval] {test_json} -> {out} {metrics}")
    return metrics


if __name__ == "__main__":
    run("data")
