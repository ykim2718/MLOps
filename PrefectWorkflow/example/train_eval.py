"""train_eval.py — evaluate the model on the train set

input : train.json
output: train_eval.json
"""
import json
import os


def run(train_meta="artifacts/train.json",
        out="artifacts/train_eval.json"):
    with open(train_meta, encoding="utf-8") as f:
        meta = json.load(f)

    # TODO: 실제로는 train set 으로 추론해 지표 계산
    metrics = {"train_accuracy": round(meta.get("best_value", 0.9), 4)}

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    print(f"[train_eval] {train_meta} -> {out} {metrics}")
    return out


if __name__ == "__main__":
    run()
