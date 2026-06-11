"""train_fe.py — feature engineering (train)

input : train transformed parquet, optuna.json (FE 튜닝 설정)
output: train_feature.parquet, fe_train.json (train에 fit된 변환기/통계)

핵심: 변환기를 train 데이터에 "fit"하고, 그 결과(스케일러 평균/분산 등)를
fe_train.json 으로 저장한다. test 단계는 이 fe_train.json 을 "재사용"만 한다.
"""
import json
import os


def run(in_path="data/interim/train_transformed.parquet",
        optuna_cfg="optuna.json",
        out_feature="data/feature/train_feature.parquet",
        out_fe_meta="artifacts/fe_train.json"):
    os.makedirs(os.path.dirname(out_feature), exist_ok=True)
    os.makedirs(os.path.dirname(out_fe_meta), exist_ok=True)

    cfg = {}
    if os.path.exists(optuna_cfg):
        with open(optuna_cfg, encoding="utf-8") as f:
            cfg = json.load(f)

    # TODO: train에 변환기를 fit -> feature 생성. fit 결과를 fe_train.json 에 저장
    fe_params = {
        "scaler_mean": 0.0,
        "scaler_std": 1.0,
        "fe_config": cfg.get("fe", {}),
    }
    with open(out_fe_meta, "w", encoding="utf-8") as f:
        json.dump(fe_params, f, indent=2)
    with open(out_feature, "w", encoding="utf-8") as f:
        f.write(f"features-from:{in_path}\n")

    print(f"[train_fe] {in_path} -> {out_feature}, {out_fe_meta}")
    return out_feature, out_fe_meta


if __name__ == "__main__":
    run()
