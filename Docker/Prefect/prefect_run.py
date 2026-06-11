# team_member_1/prefect_run.py
#
# Prefect 오케스트레이터: example/ 폴더의 단계 스크립트를 순서대로 실행한다.
#   training : pull_data -> train_dp -> train_fe -> train -> train_eval
#   test     :             test_dp  -> test_fe  -> test  -> test_eval
#
# 각 단계는 @task 로 감싸고, @flow 가 순서를 강제한다(앞 단계가 끝나야 다음 단계 실행).
import json
import os
import sys

from prefect import flow, task

# example/ 폴더의 단계 모듈을 import 경로에 추가
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(THIS_DIR, "example"))

import train_dp, train_fe, train as train_mod, train_eval   # noqa: E402
import test_dp, test_fe, test as test_mod, test_eval          # noqa: E402


def load_config():
    """prefect_configuration.json 에서 member/experiment 등 잡 설정을 읽는다.

    -> 네임스페이스 분리에 쓰는 member, experiment 값을 여기서 받는다.
    (config 파일 외에 환경변수나 Prefect flow parameter 로 받아도 된다.)
    """
    with open(os.path.join(THIS_DIR, "prefect_configuration.json"), encoding="utf-8") as f:
        return json.load(f)


@task
def pull_data():
    # DVC: 버전 고정된 raw 데이터를 가져온다 (예시 — 실제로는 `dvc pull`)
    print("[pull_data] dvc pull data/raw  (예시)")


@task
def t_train_dp():
    return train_dp.run()


@task
def t_train_fe():
    return train_fe.run(optuna_cfg=os.path.join(THIS_DIR, "example", "optuna.json"))


@task
def t_train(out_model):
    return train_mod.run(optuna_cfg=os.path.join(THIS_DIR, "example", "optuna.json"),
                         out_model=out_model)


@task
def t_train_eval():
    return train_eval.run()


@task
def t_test_dp():
    return test_dp.run()


@task
def t_test_fe():
    return test_fe.run()


@task
def t_test(model_dir):
    return test_mod.run(model_dir=model_dir)


@task
def t_test_eval():
    return test_eval.run()


@flow(name="ai-training-pipeline")
def training_pipeline(config: dict):
    # 이름 충돌 방지: 공유 루트 아래 member/experiment 로 모델 출력 경로를 분리
    out_model = f"artifacts/{config['member']}/{config['experiment']}/model/"
    pull_data()
    t_train_dp()
    t_train_fe()
    t_train(out_model)
    t_train_eval()
    return out_model


@flow(name="ai-test-pipeline")
def test_pipeline(model_dir: str):
    t_test_dp()
    t_test_fe()
    t_test(model_dir)
    t_test_eval()


@flow(name="ai-full-pipeline")
def full_pipeline():
    config = load_config()
    model_dir = training_pipeline(config)
    test_pipeline(model_dir)


if __name__ == "__main__":
    # 방법 A) 즉시 1회 실행:
    #     full_pipeline()
    #
    # 방법 B) deployment 로 등록 + 트리거 대기 (현재 기본):
    full_pipeline.serve(name="member1-mnist-resnet50")
