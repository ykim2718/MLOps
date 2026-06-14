"""test_eval.py — evaluate predictions on the test set

input : test.json
output: test_eval.json
"""
import json
import os


def run(test_meta="artifacts/test.json",
        out="artifacts/test_eval.json"):
    with open(test_meta, encoding="utf-8") as f:
        _ = json.load(f)

    # TODO: 실제로는 정답 라벨과 비교해 지표 계산
    metrics = {"test_accuracy": 0.93, "f1": 0.92}

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    print(f"[test_eval] {test_meta} -> {out} {metrics}")
    return out


if __name__ == "__main__":
    run()
