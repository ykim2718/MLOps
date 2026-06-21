# team_member_1/prefect_run.py
#
# Prefect 오케스트레이터: example/ 폴더의 단계 스크립트를 순서대로 실행하고,
# 각 단계 산출물을 MinIO(실제 데이터)에 업로드 + catalog(메타데이터)에 등록한다.
#   training : pull_data -> train_dp -> train_fe -> train -> train_eval
#   test     :             test_dp  -> test_fe  -> test  -> test_eval
#
# 각 단계는 @task 로 감싸고, @flow 가 순서를 강제한다(앞 단계가 끝나야 다음 단계 실행).
# catalog/MinIO 연결이 없으면(스택 미기동) 경고만 출력하고 로컬 실행은 계속된다.
import json
import os
import sys
from typing import Optional

from prefect import flow, task
from prefect.runtime import flow_run

# 이 파일은 example/ 안에 있다. 단계 모듈은 같은 폴더, catalog.py 는 상위 폴더에 있다.
THIS_DIR = os.path.dirname(os.path.abspath(__file__))          # .../example
sys.path.insert(0, THIS_DIR)                                   # 단계 모듈(train_dp ...)
sys.path.insert(0, os.path.dirname(THIS_DIR))                  # catalog.py (상위 폴더)


def _load_compose_env():
    """docker-compose.env(같은 폴더 또는 상위 폴더)를 읽어 os.environ 에 채운다.

    MinIO 접속(MINIO_ENDPOINT/ACCESS/SECRET 등)을 docker-compose.yml 과 같은
    한 곳(docker-compose.env)에서 가져온다. 이미 설정된 값은 덮어쓰지 않는다(setdefault).
    """
    for d in (THIS_DIR, os.path.dirname(THIS_DIR)):
        path = os.path.join(d, "docker-compose.env")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            break


_load_compose_env()                                           # catalog import 전에 환경변수 로드

import train_dp, train_fe, train as train_mod, train_eval   # noqa: E402
import test_dp, test_fe, test as test_mod, test_eval          # noqa: E402

import catalog   # noqa: E402  (상위 폴더의 카탈로그 헬퍼)

OPTUNA_CFG = os.path.join(THIS_DIR, "optuna.json")


# --------------------------------------------------------------------------- #
# 설정 / 공통 유틸 (MinIO 업로드 + catalog 등록)
# --------------------------------------------------------------------------- #
def load_config():
    """prefect_configuration.json 에서 member/experiment 등 잡 설정을 읽는다.

    -> 네임스페이스 분리에 쓰는 member, experiment 값을 여기서 받는다.
    (config 파일 외에 환경변수나 Prefect flow parameter 로 받아도 된다.)
    """
    with open(os.path.join(THIS_DIR, "prefect_configuration.json"), encoding="utf-8") as f:
        return json.load(f)


def _run_id():
    """현재 flow run 의 고유 id(없으면 'local')."""
    try:
        return flow_run.get_id() or "local"
    except Exception:
        return "local"


def _make_ctx(config):
    """이번 run 의 네임스페이스/버전 컨텍스트. train·test 전 단계가 공유한다."""
    rid = _run_id()
    return {
        "member": config["member"],
        "experiment": config["experiment"],
        "run_id": rid,
        "version": f"run-{rid[:8]}",   # run 마다 새 데이터 버전
    }


def _ensure_schema():
    """catalog 테이블 보장. 스택(catalog DB)이 없으면 경고만."""
    try:
        catalog.ensure_schema()
        print("[catalog] schema ensured")
    except Exception as e:
        print(f"[catalog] ensure_schema skipped: {e}")


def _upload(local_file, bucket, key):
    """로컬 산출물 1개를 MinIO 로 업로드. 스택이 없으면 경고만 출력하고 넘어간다."""
    try:
        import boto3
        # 자격증명/엔드포인트: 환경변수 → Prefect 블록 → 기본값 (catalog.resolve)
        # 서버/워커는 env 로, 팀원 로컬 실행은 Prefect 블록으로 자동 해석된다.
        s3 = boto3.client(
            "s3",
            endpoint_url=catalog.resolve("MINIO_ENDPOINT", "minio_endpoint",
                                         default="http://localhost:9000", secret=False),
            aws_access_key_id=catalog.resolve("MINIO_ACCESS_KEY", "minio-access-key",
                                              default="minioadmin"),
            aws_secret_access_key=catalog.resolve("MINIO_SECRET_KEY", "minio-secret-key",
                                                  default="minioadmin"),
        )
        s3.upload_file(local_file, bucket, key)
        return True
    except Exception as e:
        print(f"[minio] upload skipped ({local_file} -> s3://{bucket}/{key}): {e}")
        return False


def _publish(stage, local_file, bucket, ctx, **extra):
    """단계 산출물 1개를 MinIO 업로드 + catalog 등록.

    - dataset_id = '<member>/<experiment>/<stage>'
    - version    = 이번 run 의 고유 버전(run-<runid8>)
    - minio_path = s3://<bucket>/<member>/<experiment>/<version>/<filename>
    catalog/MinIO 연결이 없으면 경고만 출력(로컬 실행은 계속).
    """
    member, experiment, version = ctx["member"], ctx["experiment"], ctx["version"]
    fname = os.path.basename(local_file.rstrip("/")) or stage
    key = f"{member}/{experiment}/{version}/{fname}"
    minio_path = f"s3://{bucket}/{key}"

    _upload(local_file, bucket, key)

    # 작은 json 산출물은 내용을 metadata 로 함께 보강(검색/계보에 유용)
    meta = {"stage": stage, **extra}
    if local_file.endswith(".json") and os.path.exists(local_file):
        try:
            with open(local_file, encoding="utf-8") as f:
                meta["summary"] = json.load(f)
        except Exception:
            pass

    try:
        catalog.register(
            f"{member}/{experiment}/{stage}", version, minio_path,
            created_by=member,
            prefect_run_id=ctx["run_id"],
            description=f"{stage} output of {experiment}",
            metadata=meta,
        )
        print(f"[catalog] registered {member}/{experiment}/{stage} {version} -> {minio_path}")
    except Exception as e:
        print(f"[catalog] register skipped ({stage} {version}): {e}")
    return minio_path


# --------------------------------------------------------------------------- #
# 단계 task (stage 실행 -> 산출물 publish)
# --------------------------------------------------------------------------- #
@task
def pull_data():
    # DVC 대신: 버전 고정된 raw 데이터를 MinIO 에서 가져온다 (예시)
    print("[pull_data] MinIO 에서 raw 데이터 download  (예시)")


@task
def t_train_dp(ctx: dict):
    out = train_dp.run()
    _publish("train_dp", out, "datasets", ctx)
    return out


@task
def t_train_fe(ctx: dict):
    feature, fe_meta = train_fe.run(optuna_cfg=OPTUNA_CFG)
    _publish("train_fe", feature, "datasets", ctx, fe_meta=fe_meta)
    _publish("train_fe_meta", fe_meta, "datasets", ctx)   # fe_train.json (재현용)
    return feature, fe_meta


@task
def t_train(ctx: dict, out_model: str):
    model_dir, train_meta = train_mod.run(optuna_cfg=OPTUNA_CFG, out_model=out_model)
    _publish("train", os.path.join(model_dir, "model.pt"), "models", ctx)
    _publish("train_meta", train_meta, "datasets", ctx)   # train.json (best params 등)
    return model_dir


@task
def t_train_eval(ctx: dict):
    out = train_eval.run()
    _publish("train_eval", out, "datasets", ctx)
    return out


@task
def t_test_dp(ctx: dict):
    out = test_dp.run()
    _publish("test_dp", out, "datasets", ctx)
    return out


@task
def t_test_fe(ctx: dict):
    feature, fe_meta = test_fe.run()
    _publish("test_fe", feature, "datasets", ctx, fe_meta=fe_meta)
    return feature, fe_meta


@task
def t_test(ctx: dict, model_dir: str):
    out = test_mod.run(model_dir=model_dir)
    _publish("test", out, "datasets", ctx)
    return out


@task
def t_test_eval(ctx: dict):
    out = test_eval.run()
    _publish("test_eval", out, "datasets", ctx)
    return out


# --------------------------------------------------------------------------- #
# flow (순서 강제)
# --------------------------------------------------------------------------- #
@flow(name="ai-training-pipeline")
def training_pipeline(config: dict, ctx: Optional[dict] = None):
    _ensure_schema()
    ctx = ctx or _make_ctx(config)
    # 모델 단계는 로컬(model/)에 쓰고, _publish 가 MinIO(s3://models/...) + catalog 로 올린다
    out_model = f"artifacts/{ctx['member']}/{ctx['experiment']}/model/"
    pull_data()
    t_train_dp(ctx)
    t_train_fe(ctx)
    model_dir = t_train(ctx, out_model)
    t_train_eval(ctx)
    return model_dir


@flow(name="ai-test-pipeline")
def test_pipeline(model_dir: str, ctx: dict):
    t_test_dp(ctx)
    t_test_fe(ctx)
    t_test(ctx, model_dir)
    t_test_eval(ctx)


@flow(name="ai-full-pipeline")
def full_pipeline():
    config = load_config()
    _ensure_schema()
    ctx = _make_ctx(config)               # train·test 가 같은 version 을 공유
    model_dir = training_pipeline(config, ctx)
    test_pipeline(model_dir, ctx)


if __name__ == "__main__":
    # 방법 A) 즉시 1회 실행:
    #     full_pipeline()
    #
    # 방법 B) deployment 로 등록 + 트리거 대기 (현재 기본):
    full_pipeline.serve(name="member1-mnist-resnet50")
