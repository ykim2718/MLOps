"""test.py — inference on the test set

input : test_feature.parquet, fe_test.json, model/ folder (train이 만든 모델)
output: test.json (테스트 추론 결과)
"""
import json
import os


def run(feature="data/feature/test_feature.parquet",
        fe_meta="artifacts/fe_test.json",
        model_dir="model/",
        out="artifacts/test.json"):
    model_file = os.path.join(model_dir, "model.pt")
    # TODO: model_file 로드 후 feature 로 추론
    _ = model_file

    os.makedirs(os.path.dirname(out), exist_ok=True)
    predictions = {"predictions": [0, 1, 1, 0], "model": model_file}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(predictions, f, indent=2)

    print(f"[test] {feature} (+{model_dir}) -> {out}")
    return out


if __name__ == "__main__":
    run()
