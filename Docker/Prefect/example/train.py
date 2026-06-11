"""train.py — model training (+ Optuna hyperparameter tuning)

input : train_feature.parquet, fe_train.json, optuna.json
output: model/ folder, train.json (학습 메타: best params/지표/모델 경로)
"""
import json
import os

try:
    import optuna
    HAS_OPTUNA = True
except ImportError:           # 예시가 optuna 없이도 돌도록 fallback
    HAS_OPTUNA = False


def objective(trial):
    """Optuna가 매 trial마다 호출하는 '목적 함수'.

    - trial.suggest_*() 로 하이퍼파라미터를 "제안받아"
    - 그 값으로 학습/검증을 한 뒤
    - 점수(여기선 검증 정확도)를 return 한다.
    Optuna는 반환된 점수를 보고 다음 trial의 하이퍼파라미터를 더 똑똑하게 고른다.
    """
    lr = trial.suggest_float("lr", 1e-4, 1e-1, log=True)
    n_estimators = trial.suggest_int("n_estimators", 50, 300)
    # TODO: 실제로는 위 파라미터로 모델 학습 후 검증셋 점수를 계산
    val_acc = 1.0 - abs(lr - 0.01) - (n_estimators - 150) ** 2 * 1e-6  # 가짜 점수
    return val_acc            # direction="maximize" 대상


def run(feature="data/feature/train_feature.parquet",
        fe_meta="artifacts/fe_train.json",
        optuna_cfg="optuna.json",
        out_model="model/",
        out_meta="artifacts/train.json"):
    os.makedirs(out_model, exist_ok=True)
    os.makedirs(os.path.dirname(out_meta), exist_ok=True)

    n_trials = 20
    if os.path.exists(optuna_cfg):
        with open(optuna_cfg, encoding="utf-8") as f:
            n_trials = json.load(f).get("n_trials", 20)

    if HAS_OPTUNA:
        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=n_trials)   # objective 를 n_trials 번 호출
        best_params, best_value = study.best_params, study.best_value
    else:
        best_params, best_value = {"lr": 0.01, "n_estimators": 150}, 0.95

    # TODO: best_params 로 최종 모델 학습 후 out_model 에 저장
    with open(os.path.join(out_model, "model.pt"), "w", encoding="utf-8") as f:
        f.write("trained-weights\n")

    meta = {"best_params": best_params, "best_value": best_value, "model_path": out_model}
    with open(out_meta, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print(f"[train] best={best_params} value={best_value:.4f} -> {out_model}, {out_meta}")
    return out_model, out_meta


if __name__ == "__main__":
    run()
