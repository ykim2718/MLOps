"""test_fe.py — feature engineering (test)

input : test transformed parquet, fe_train.json (train에서 fit된 변환기 재사용)
output: test_feature.parquet, fe_test.json

핵심: test는 변환기를 새로 fit 하지 않는다. train 단계가 만든 fe_train.json 을
그대로 "적용(transform)"해야 train/test skew 가 생기지 않는다.
"""
import json
import os


def run(in_path="data/interim/test_transformed.parquet",
        fe_train_meta="artifacts/fe_train.json",
        out_feature="data/feature/test_feature.parquet",
        out_fe_meta="artifacts/fe_test.json"):
    os.makedirs(os.path.dirname(out_feature), exist_ok=True)
    os.makedirs(os.path.dirname(out_fe_meta), exist_ok=True)

    with open(fe_train_meta, encoding="utf-8") as f:
        fe_train = json.load(f)        # train에서 fit된 변환기/통계 재사용

    # TODO: fe_train 통계를 test에 transform(적용)만 한다 (fit 금지)
    with open(out_feature, "w", encoding="utf-8") as f:
        f.write(f"features-from:{in_path}\n")
    with open(out_fe_meta, "w", encoding="utf-8") as f:
        json.dump({"applied_from": fe_train_meta, "reused": fe_train}, f, indent=2)

    print(f"[test_fe] {in_path} (+{fe_train_meta}) -> {out_feature}, {out_fe_meta}")
    return out_feature, out_fe_meta


if __name__ == "__main__":
    run()
