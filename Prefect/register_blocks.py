# register_blocks.py
# (관리자 1회 실행) 팀원이 자기 PC 에서 Prefect flow 를 직접 돌릴 때 쓰는 자격증명/엔드포인트를
# Prefect 서버에 Secret/Variable 블록으로 등록한다.
# 팀원 코드(catalog.resolve)는 이 블록을 "이름"으로만 불러오므로,
# 하드코딩 없이 / docker-compose.env 를 보지 않고도 동작한다.
#
# 전제:
#   - 이 PC 가 Prefect 서버에 연결돼 있어야 한다:
#       prefect config set PREFECT_API_URL="http://<서버>:4200/api"
#   - 비밀값(access/secret key)은 같은 폴더의 docker-compose.env 에서 자동으로 읽는다.
#
# 사용 (팀원이 접속할 "서버 주소"로 등록 — localhost 아님!):
#   python register_blocks.py http://<서버>:9000 postgresql://reader:pw@<서버>:5432/catalog
#   # 또는 환경변수로:
#   $env:MEMBER_MINIO_ENDPOINT="http://<서버>:9000"
#   $env:MEMBER_CATALOG_DSN="postgresql://reader:pw@<서버>:5432/catalog"
#   python register_blocks.py
#
# 등록 결과:
#   Secret   minio-access-key / minio-secret-key / catalog-dsn
#   Variable minio_endpoint
import os
import sys

from prefect.blocks.system import Secret
from prefect.variables import Variable


def _load_compose_env():
    """같은 폴더의 docker-compose.env 를 읽어 os.environ 에 채운다(이미 있으면 유지)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docker-compose.env")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _member_value(argv_idx, env_name, fallback_env, label):
    """팀원이 접속할 값(엔드포인트/DSN)을 argv → MEMBER_* 환경변수 → 로컬 fallback 순으로 고른다."""
    if len(sys.argv) > argv_idx:
        return sys.argv[argv_idx]
    if os.environ.get(env_name):
        return os.environ[env_name]
    val = os.environ.get(fallback_env, "")
    print(f"[warn] {label}: 서버 주소가 지정되지 않아 로컬값('{val}')으로 등록합니다. "
          f"팀원이 다른 PC 에서 접속하려면 서버 IP/호스트로 바꿔 다시 실행하세요.")
    return val


def main():
    _load_compose_env()

    ak = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
    sk = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
    endpoint = _member_value(1, "MEMBER_MINIO_ENDPOINT", "MINIO_ENDPOINT", "MinIO endpoint")
    dsn = _member_value(2, "MEMBER_CATALOG_DSN", "POSTGRESQL_CATALOG_DSN", "catalog DSN")

    # 시크릿(키/비번 포함 DSN)은 Secret 블록, 시크릿 아닌 엔드포인트는 Variable 로.
    Secret(value=ak).save("minio-access-key", overwrite=True)
    Secret(value=sk).save("minio-secret-key", overwrite=True)
    Secret(value=dsn).save("catalog-dsn", overwrite=True)
    Variable.set("minio_endpoint", endpoint, overwrite=True)

    print("[ok] Secret  : minio-access-key, minio-secret-key, catalog-dsn")
    print(f"[ok] Variable: minio_endpoint = {endpoint}")
    print("팀원은 PREFECT_API_URL 만 설정하면 catalog.resolve() 가 이 블록들을 자동으로 사용합니다.")


if __name__ == "__main__":
    main()
