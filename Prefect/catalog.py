"""catalog.py — 데이터 카탈로그(메타데이터 장부) 접근 계층.

PostgreSQL `catalog` DB 의 `datasets` 테이블을 다룬다.
실제 데이터 파일은 MinIO 에 있고, 여기서는 "무엇이 · 어디에 · 어느 버전으로 ·
누가 만들었는지" 같은 **메타데이터만** 기록/조회한다(파일 자체는 boto3/MinIO 담당).

두 가지로 쓴다.

1) 라이브러리로 import (Prefect flow 등에서):
       import catalog
       catalog.ensure_schema()
       catalog.register("sydney_202605", "v1", "s3://datasets/sydney_202605/v1/",
                        created_by="zoo", metadata={"fab": "fab2", "chamber": "CH3"})
       rows = catalog.find("sydney_202605", fab="fab2")

2) CLI 로 카탈로그 둘러보기 (이력을 모르는 팀원이 탐색·선택할 때):
       python catalog.py list                        # 데이터셋 목록(최신 버전 요약)
       python catalog.py versions sydney_202605      # 한 데이터셋의 버전 이력
       python catalog.py tree                         # 데이터셋 > 버전 트리
       python catalog.py find sydney_202605 fab=fab2  # 검색(metadata 키=값)

연결 주소는 환경변수 POSTGRESQL_CATALOG_DSN 으로 덮어쓸 수 있다(로컬/원격 서버 공용).
환경변수가 없으면 Prefect 서버의 블록(`catalog-dsn` Secret 등)에서 가져온다 → resolve() 참고.
즉 팀원은 자격증명을 하드코딩하거나 docker-compose.env 를 보지 않고도(Prefect 서버에 연결만
돼 있으면) 동작한다(관리자가 register_blocks.py 로 블록을 등록해 둔 경우).
"""
import os
import sys

import psycopg2
from psycopg2.extras import Json, RealDictCursor

def _load_compose_env():
    """docker-compose.env(같은 폴더 또는 상위 폴더)를 읽어 os.environ 에 채운다.

    docker-compose.yml 과 같은 한 곳(docker-compose.env)에서 자격증명/엔드포인트를
    가져오기 위한 헬퍼. 이미 설정된 환경변수는 덮어쓰지 않으므로(setdefault),
    셸이나 .ps1 스크립트가 준 값이 항상 우선한다.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (here, os.path.dirname(here)):
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


_load_compose_env()


def resolve(env_name, block_name, *, default=None, secret=True):
    """자격증명/설정 1개를 해석한다: 환경변수 우선 → Prefect 블록 → default.

    - 서버 / 관리자 / .ps1 경로: 환경변수(os.environ)가 이미 있어 그대로 사용(블록 조회 안 함).
    - 팀원 로컬 실행: 환경변수가 없으면 PREFECT_API_URL 로 연결된 Prefect 서버의
      Secret(secret=True) 또는 Variable(secret=False) 블록에서 가져온다
      (관리자가 register_blocks.py 로 등록해 둔 값).
    prefect 미설치 / 서버 미연결 / 블록 없음 등으로 실패하면 조용히 default 로 떨어진다.
    """
    v = os.environ.get(env_name)
    if v:
        return v
    try:
        if secret:
            from prefect.blocks.system import Secret
            return Secret.load(block_name).get()
        from prefect.variables import Variable
        return Variable.get(block_name)
    except Exception:
        return default


def _dsn():
    return resolve("POSTGRESQL_CATALOG_DSN", "catalog-dsn",
                   default="postgresql://postgres:postgres@localhost:5432/catalog")

DDL = """
CREATE TABLE IF NOT EXISTS datasets (
    id             SERIAL PRIMARY KEY,
    dataset_id     TEXT NOT NULL,
    version        TEXT NOT NULL,
    minio_path     TEXT NOT NULL,
    created_by     TEXT,
    created_at     TIMESTAMP DEFAULT now(),
    n_files        INT,
    size_bytes     BIGINT,
    content_hash   TEXT,
    prefect_run_id TEXT,
    description    TEXT,
    metadata       JSONB,
    UNIQUE(dataset_id, version)
);
"""


def _conn():
    return psycopg2.connect(_dsn())


# --------------------------------------------------------------------------- #
# 쓰기 / 스키마
# --------------------------------------------------------------------------- #
def ensure_schema():
    """`datasets` 테이블이 없으면 만든다(있으면 그냥 통과). flow 시작 시 1회 호출."""
    with _conn() as c, c.cursor() as cur:
        cur.execute(DDL)


def register(dataset_id, version, minio_path, *, created_by=None,
             n_files=None, size_bytes=None, content_hash=None,
             prefect_run_id=None, description=None, metadata=None):
    """새 데이터셋 버전을 카탈로그에 등록. metadata 는 dict → JSONB.

    UNIQUE(dataset_id, version) 라 같은 버전 재등록은 무시(DO NOTHING)된다.
    """
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            """INSERT INTO datasets
               (dataset_id, version, minio_path, created_by, n_files, size_bytes,
                content_hash, prefect_run_id, description, metadata)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (dataset_id, version) DO NOTHING""",
            (dataset_id, version, minio_path, created_by, n_files, size_bytes,
             content_hash, prefect_run_id, description, Json(metadata or {})))


# --------------------------------------------------------------------------- #
# 읽기 / 검색
# --------------------------------------------------------------------------- #
def find(dataset_id=None, **filters):
    """이름/메타데이터로 검색. 예: find('sydney_202605', fab='fab2').

    filters 는 metadata JSONB 의 키=값 으로 해석된다(문자열 비교).
    결과는 최신 생성 순(dict 리스트).
    """
    sql = "SELECT * FROM datasets WHERE TRUE"
    args = []
    if dataset_id:
        sql += " AND dataset_id = %s"
        args.append(dataset_id)
    for k, v in filters.items():
        sql += " AND metadata->>%s = %s"
        args += [k, str(v)]
    sql += " ORDER BY created_at DESC"
    with _conn() as c, c.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def get(dataset_id, version=None):
    """한 데이터셋의 특정 버전(없으면 최신) 한 행을 반환. 없으면 None."""
    if version is None:
        sql = ("SELECT * FROM datasets WHERE dataset_id=%s "
               "ORDER BY created_at DESC LIMIT 1")
        args = [dataset_id]
    else:
        sql = "SELECT * FROM datasets WHERE dataset_id=%s AND version=%s"
        args = [dataset_id, version]
    with _conn() as c, c.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, args)
        return cur.fetchone()


# --------------------------------------------------------------------------- #
# 둘러보기(탐색) — 이력을 모르는 팀원이 목록/계층을 보고 고르기 위한 헬퍼
# --------------------------------------------------------------------------- #
def list_datasets():
    """데이터셋별 요약: 버전 수 + 최신 버전 + 최근 갱신 시각/제작자."""
    sql = """
        SELECT DISTINCT ON (dataset_id)
               dataset_id,
               version    AS latest_version,
               created_by AS latest_by,
               created_at AS last_updated,
               (SELECT count(*) FROM datasets x WHERE x.dataset_id = d.dataset_id)
                          AS versions
        FROM datasets d
        ORDER BY dataset_id, created_at DESC
    """
    with _conn() as c, c.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return sorted(rows, key=lambda r: r["last_updated"], reverse=True)


def versions(dataset_id):
    """한 데이터셋의 모든 버전 이력(최신 → 과거)."""
    sql = ("SELECT version, created_by, created_at, minio_path, metadata "
           "FROM datasets WHERE dataset_id=%s ORDER BY created_at DESC")
    with _conn() as c, c.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, [dataset_id])
        return cur.fetchall()


def tree():
    """dataset_id > [versions...] 계층 dict 를 반환."""
    out = {}
    with _conn() as c, c.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT dataset_id, version, created_at FROM datasets "
                    "ORDER BY dataset_id, created_at")
        for row in cur.fetchall():
            out.setdefault(row["dataset_id"], []).append(row["version"])
    return out


# --------------------------------------------------------------------------- #
# 파일 종류(확장자) 집계 — MinIO 객체를 세어 트리에 표시 (boto3 는 필요할 때만 import)
# --------------------------------------------------------------------------- #
def _ext_counts(minio_path):
    """minio_path 아래 객체를 확장자별로 세어 {ext: count} 로 반환."""
    import boto3
    from urllib.parse import urlparse
    ep = resolve("MINIO_ENDPOINT", "minio_endpoint", default="http://localhost:9000", secret=False)
    ak = resolve("MINIO_ACCESS_KEY", "minio-access-key", default="minioadmin")
    sk = resolve("MINIO_SECRET_KEY", "minio-secret-key", default="minioadmin")
    s3 = boto3.client("s3", endpoint_url=ep,
                      aws_access_key_id=ak, aws_secret_access_key=sk)
    u = urlparse(minio_path)                       # s3://bucket/key/...
    bucket, prefix = u.netloc, u.path.lstrip("/")
    counts = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            base = key.rsplit("/", 1)[-1]
            ext = base.rsplit(".", 1)[-1].lower() if "." in base else "(noext)"
            counts[ext] = counts.get(ext, 0) + 1
    return counts


def _fmt_counts(counts):
    """{'parquet':128,'csv':13} -> '(128 parquet, 13 csv)'. 비면 '(empty)'."""
    if not counts:
        return "(empty)"
    parts = ", ".join(f"{n} {e}" for e, n in sorted(counts.items(), key=lambda x: -x[1]))
    return f"({parts})"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_rows(rows, cols):
    """간단 표 출력(외부 의존성 없이)."""
    if not rows:
        print("(없음)")
        return
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    line = "  ".join(c.ljust(widths[c]) for c in cols)
    print(line)
    print("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))


def _main(argv):
    cmd = argv[0] if argv else "list"

    if cmd == "list":
        _print_rows(list_datasets(),
                    ["dataset_id", "versions", "latest_version", "latest_by", "last_updated"])

    elif cmd == "versions":
        if len(argv) < 2:
            sys.exit("usage: python catalog.py versions <dataset_id>")
        _print_rows(versions(argv[1]),
                    ["version", "created_by", "created_at", "minio_path"])

    elif cmd == "tree":
        # tree [--files] [dataset_id]
        #   --files : 각 버전 옆에 MinIO 파일 종류별 개수 표시 (예: (128 parquet, 13 csv))
        with_files = "--files" in argv
        only = next((a for a in argv[1:] if a != "--files"), None)
        for ds, vers in tree().items():
            if only and ds != only:
                continue
            print(ds)
            for v in vers:
                line = f"  └─ {v}"
                if with_files:
                    row = get(ds, v)
                    if row and row.get("minio_path"):
                        try:
                            line += "  " + _fmt_counts(_ext_counts(row["minio_path"]))
                        except Exception as e:
                            line += f"  (count failed: {e})"
                print(line)

    elif cmd == "find":
        if len(argv) < 2:
            sys.exit("usage: python catalog.py find <dataset_id> [key=value ...]")
        dataset_id = argv[1]
        filters = dict(kv.split("=", 1) for kv in argv[2:] if "=" in kv)
        _print_rows(find(dataset_id, **filters),
                    ["dataset_id", "version", "created_by", "minio_path"])

    else:
        sys.exit("commands: list | versions <id> | tree | find <id> [key=value ...]")


if __name__ == "__main__":
    _main(sys.argv[1:])
