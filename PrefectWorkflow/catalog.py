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

3) JSON spec 으로 업로드 + 등록 (MinIO 적재와 catalog 등록을 한 번에):
       python catalog.py upload spec.json
   spec.json 예시:
       {"dataset_id": "sydney_202605", "version": "v2", "path": "./out",
        "bucket": "datasets", "created_by": "zoo", "description": "fab2 CH3",
        "metadata": {"fab": "fab2", "chamber": "CH3"}}
   (boto3 로 올리므로 mc 불필요. 버전은 불변 — 이미 있으면 중단.)

4) 다운로드 / 삭제 / 원본 객체 보기 (모두 boto3, mc 불필요):
       python catalog.py download sydney_202605 v2 ./out  # 없으면 최신, dest 기본 ./<id>
       python catalog.py remove   sydney_202605 v2        # 한 버전 (생략 시 전체) — 영구 삭제
       python catalog.py remove   sydney_202605 --yes     # 확인 프롬프트 건너뛰기
       python catalog.py objects  sydney_202605           # MinIO 에 실제 있는 객체 나열

연결 주소는 환경변수 POSTGRESQL_CATALOG_DSN 으로 덮어쓸 수 있다(로컬/원격 서버 공용).
환경변수가 없으면 Prefect 서버의 블록(`catalog-dsn` Secret 등)에서 가져온다 → resolve() 참고.
즉 팀원은 자격증명을 하드코딩하거나 docker-compose.env 를 보지 않고도(Prefect 서버에 연결만
돼 있으면) 동작한다(관리자가 register_blocks.py 로 블록을 등록해 둔 경우).
"""
import argparse
import json
import os
import re
import sys
import textwrap

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
# 업로드 (MinIO 적재 + catalog 등록) — JSON spec 으로 구동
# --------------------------------------------------------------------------- #
_NAME_RE = re.compile(r"^[a-z0-9_.]+$")


def _check_name(name, field):
    """dataset_id / version 이름 규칙: 소문자·숫자·`_`·`.` 만 (공백·대문자·`-` 불가).

    이 값이 그대로 MinIO 경로와 catalog 키가 되므로 강제한다.
    """
    if not name or not _NAME_RE.match(name):
        raise ValueError(
            f"{field} '{name}' invalid: allowed lowercase a-z, digits 0-9, '_', '.' "
            "(no spaces, uppercase, or '-').")


def upload(spec):
    """JSON spec 한 건으로 MinIO 에 데이터를 올리고 catalog 에 버전 레코드를 등록한다.

    spec keys:
      dataset_id (req) · version (req) · path (req, 파일 또는 폴더)
      bucket (기본 'datasets') · created_by · description · metadata (dict) · prefect_run_id

    버전은 불변 (immutable): 같은 dataset_id/version 이 MinIO 나 catalog 에 이미 있으면
    덮어쓰지 않고 중단한다 (버전을 올려 다시 시도).
    """
    dataset_id = spec["dataset_id"]
    version = spec["version"]
    path = spec["path"]
    bucket = spec.get("bucket", "datasets")

    _check_name(dataset_id, "dataset_id")
    _check_name(version, "version")
    if not os.path.exists(path):
        raise FileNotFoundError(f"path not found: {path}")

    s3 = _s3()
    prefix = f"{dataset_id}/{version}/"
    minio_path = f"s3://{bucket}/{prefix}"
    if get(dataset_id, version) or s3.list_objects_v2(
            Bucket=bucket, Prefix=prefix, MaxKeys=1).get("KeyCount", 0):
        raise FileExistsError(f"version already exists: {minio_path} (bump the version)")

    # upload a file, or a folder (recursive)
    n_files, size_bytes = 0, 0
    if os.path.isdir(path):
        for root, _, files in os.walk(path):
            for fn in files:
                fp = os.path.join(root, fn)
                key = prefix + os.path.relpath(fp, path).replace(os.sep, "/")
                s3.upload_file(fp, bucket, key)
                n_files += 1
                size_bytes += os.path.getsize(fp)
    else:
        s3.upload_file(path, bucket, prefix + os.path.basename(path))
        n_files, size_bytes = 1, os.path.getsize(path)

    ensure_schema()
    register(dataset_id, version, minio_path,
             created_by=spec.get("created_by"),
             n_files=n_files, size_bytes=size_bytes,
             prefect_run_id=spec.get("prefect_run_id"),
             description=spec.get("description"),
             metadata=spec.get("metadata") or {})
    print(f"[catalog] uploaded {n_files} file(s), {size_bytes} B -> {minio_path} and registered")
    return minio_path


# --------------------------------------------------------------------------- #
# 다운로드 / 삭제 (MinIO ± catalog) — boto3 직접 (mc 불필요)
# --------------------------------------------------------------------------- #
def download(dataset_id, version=None, dest=None):
    """catalog 에서 minio_path 를 찾아 (version 생략 시 최신) 그 아래 객체를 dest 로 내려받는다.

    dest 기본값은 `./<dataset_id>`. "search → select → download" 흐름.
    """
    from urllib.parse import urlparse
    _check_name(dataset_id, "dataset_id")
    if version:
        _check_name(version, "version")
    row = get(dataset_id, version)
    if not row:
        raise LookupError(f"not in catalog: '{dataset_id}' (version={version or 'latest'})")

    u = urlparse(row["minio_path"])                # s3://bucket/key/...
    bucket, prefix = u.netloc, u.path.lstrip("/")
    dest = dest or dataset_id
    s3 = _s3()
    n = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            rel = key[len(prefix):] if key.startswith(prefix) else key
            target = os.path.join(dest, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            s3.download_file(bucket, key, target)
            n += 1
    print(f"[catalog] downloaded {n} file(s): {row['minio_path']} -> {dest}")
    return dest


def _delete_prefix(s3, bucket, prefix):
    """prefix 아래 모든 객체 (버전·삭제마커 포함) 를 지운다. 지운 개수를 반환."""
    deleted, batch = 0, []
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Versions", []) + page.get("DeleteMarkers", []):
            batch.append({"Key": item["Key"], "VersionId": item["VersionId"]})
            if len(batch) == 1000:                 # delete_objects caps at 1000 keys per call
                s3.delete_objects(Bucket=bucket, Delete={"Objects": batch})
                deleted += len(batch)
                batch = []
    if batch:
        s3.delete_objects(Bucket=bucket, Delete={"Objects": batch})
        deleted += len(batch)
    return deleted


def remove(dataset_id, version=None, *, yes=False):
    """MinIO 객체와 catalog 행을 영구 삭제한다 (version 생략 시 데이터셋 전체).

    되돌릴 수 없다. yes=False 면 'DELETE' 입력을 요구한다 (CLI 안전장치).
    """
    from urllib.parse import urlparse
    _check_name(dataset_id, "dataset_id")
    if version:
        _check_name(version, "version")

    row = get(dataset_id, version)                 # derive the real bucket from a catalog row if any
    bucket = urlparse(row["minio_path"]).netloc if row else "datasets"
    prefix = f"{dataset_id}/{version}/" if version else f"{dataset_id}/"
    shown = f"s3://{bucket}/{prefix}" + (" (single version)" if version else " (ENTIRE dataset)")

    if not yes:
        print(f"About to PERMANENTLY delete {shown} from MinIO and catalog.")
        if input("Type DELETE to confirm: ") != "DELETE":
            raise SystemExit("cancelled (did not type DELETE).")

    n_obj = _delete_prefix(_s3(), bucket, prefix)
    with _conn() as c, c.cursor() as cur:
        if version:
            cur.execute("DELETE FROM datasets WHERE dataset_id=%s AND version=%s",
                        (dataset_id, version))
        else:
            cur.execute("DELETE FROM datasets WHERE dataset_id=%s", (dataset_id,))
        n_rows = cur.rowcount
    print(f"[catalog] removed {shown}: {n_obj} object(s), {n_rows} catalog row(s)")


def objects(dataset_id=None, *, bucket="datasets"):
    """MinIO 에 실제로 있는 객체를 나열한다 (catalog 등록과 무관한 원본 보기)."""
    prefix = f"{dataset_id}/" if dataset_id else ""
    s3 = _s3()
    rows = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            rows.append({"key": obj["Key"], "size": obj["Size"]})
    return rows


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
def _s3():
    """MinIO(S3 호환) 클라이언트. 자격증명은 resolve() 로 환경변수 → Prefect 블록 순으로 가져온다."""
    import boto3
    ep = resolve("MINIO_ENDPOINT", "minio-endpoint", default="http://localhost:9000")
    ak = resolve("MINIO_ACCESS_KEY", "minio-access-key", default="minioadmin")
    sk = resolve("MINIO_SECRET_KEY", "minio-secret-key", default="minioadmin")
    return boto3.client("s3", endpoint_url=ep,
                        aws_access_key_id=ak, aws_secret_access_key=sk)


def _ext_counts(minio_path):
    """minio_path 아래 객체를 확장자별로 세어 {ext: count} 로 반환."""
    from urllib.parse import urlparse
    s3 = _s3()
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


def _cmd_tree(dataset_id=None, with_files=False):
    """dataset_id > version 트리를 출력. with_files 면 버전 옆에 MinIO 파일 종류별 개수."""
    for ds, vers in tree().items():
        if dataset_id and ds != dataset_id:
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


def _build_parser():
    epilog = textwrap.dedent("""\
        examples:
          python catalog.py list                              # dataset summary (latest version)
          python catalog.py versions sydney_202605            # one dataset's version history
          python catalog.py tree --files                      # dataset > version tree (+ file-type counts)
          python catalog.py find sydney_202605 fab=fab2       # search by metadata key=value
          python catalog.py upload spec.json                  # upload to MinIO + register (JSON spec)
          python catalog.py download sydney_202605 v2 ./out   # version omitted -> latest; dest -> ./<id>
          python catalog.py remove sydney_202605 v2 --yes     # version omitted -> whole dataset
          python catalog.py objects sydney_202605             # raw MinIO objects (not the catalog)

        upload spec.json:
          {"dataset_id": "sydney_202605", "version": "v2", "path": "./out",
           "bucket": "datasets", "created_by": "zoo", "description": "fab2 CH3",
           "metadata": {"fab": "fab2", "chamber": "CH3"}}

        credentials (env, else Prefect Secret blocks via resolve()):
          POSTGRESQL_CATALOG_DSN, MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY
        """)
    p = argparse.ArgumentParser(
        prog="catalog.py",
        description="Data catalog (PostgreSQL ledger) + MinIO object operations.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True,    # exactly one command (mutually exclusive)
                           metavar="<command>")

    sub.add_parser("list", help="list datasets (latest-version summary)")

    sp = sub.add_parser("versions", help="show one dataset's version history")
    sp.add_argument("dataset_id", type=str)

    sp = sub.add_parser("tree", help="print the dataset > version tree")
    sp.add_argument("dataset_id", type=str, nargs="?", default=None,
                    help="limit to one dataset (default: all)")
    sp.add_argument("--files", action="store_true", default=False,
                    help="show MinIO file-type counts per version")

    sp = sub.add_parser("find", help="search by dataset_id + metadata key=value")
    sp.add_argument("dataset_id", type=str)
    sp.add_argument("filters", type=str, nargs="*", default=[], metavar="key=value",
                    help="metadata filters")

    sp = sub.add_parser("upload", help="upload files to MinIO + register, from a JSON spec")
    sp.add_argument("spec", type=str, metavar="spec.json")

    sp = sub.add_parser("download", help="download a version's objects from MinIO")
    sp.add_argument("dataset_id", type=str)
    sp.add_argument("version", type=str, nargs="?", default=None, help="default: latest")
    sp.add_argument("dest", type=str, nargs="?", default=None, help="default: ./<dataset_id>")

    sp = sub.add_parser("remove", help="PERMANENTLY delete from MinIO + catalog")
    sp.add_argument("dataset_id", type=str)
    sp.add_argument("version", type=str, nargs="?", default=None,
                    help="default: entire dataset (all versions)")
    sp.add_argument("--yes", action="store_true", default=False,
                    help="skip the DELETE confirmation")

    sp = sub.add_parser("objects", help="list raw MinIO objects (not the catalog)")
    sp.add_argument("dataset_id", type=str, nargs="?", default=None,
                    help="limit to one dataset (default: all)")

    return p


def _main(argv):
    a = _build_parser().parse_args(argv)
    cmd = a.cmd                                             # exactly one command (required)

    if cmd == "list":
        _print_rows(list_datasets(),
                    ["dataset_id", "versions", "latest_version", "latest_by", "last_updated"])
    elif cmd == "versions":
        _print_rows(versions(a.dataset_id),
                    ["version", "created_by", "created_at", "minio_path"])
    elif cmd == "tree":
        _cmd_tree(a.dataset_id, a.files)
    elif cmd == "find":
        filters = dict(kv.split("=", 1) for kv in a.filters if "=" in kv)
        _print_rows(find(a.dataset_id, **filters),
                    ["dataset_id", "version", "created_by", "minio_path"])
    elif cmd == "upload":
        with open(a.spec, encoding="utf-8") as f:
            upload(json.load(f))
    elif cmd == "download":
        download(a.dataset_id, a.version, a.dest)
    elif cmd == "remove":
        remove(a.dataset_id, a.version, yes=a.yes)
    elif cmd == "objects":
        _print_rows(objects(a.dataset_id), ["key", "size"])


if __name__ == "__main__":
    _main(sys.argv[1:])
