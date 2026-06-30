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
       python catalog.py spec   spec.json     # 빈 spec 뼈대 생성 → dataset_id/version/path 채움
       python catalog.py upload spec.json
   spec.json 예시:
       {"dataset_id": "sydney_202605", "version": "v2", "path": "./out",
        "bucket": "datasets", "created_by": "zoo", "description": "fab2 CH3",
        "metadata": {"fab": "fab2", "chamber": "CH3"}}
   (path 는 파일·폴더·와일드카드(`dir/*.csv`, 재귀 `dir/**/*.csv`). boto3 로 올리므로 mc 불필요.
    버전은 불변 — 이미 있으면 중단.)

4) 다운로드 / 삭제 / 원본 객체 보기 (모두 boto3, mc 불필요):
       python catalog.py download sydney_202605 v2 ./out  # 없으면 최신, dest 기본 ./<id>
       python catalog.py remove   sydney_202605 v2        # 한 버전 (생략 시 전체) — 영구 삭제
       python catalog.py remove   sydney_202605 --yes     # 확인 프롬프트 건너뛰기
       python catalog.py objects  sydney_202605           # MinIO 에 실제 있는 객체 나열

자격증명·연결 주소는 Prefect 프로필(`prefect config set PREFECT_API_URL=...`)로 연결된 Prefect
서버의 **팀원 블록**(블록 이름 = 팀원 이름, 예 `Jason`)에서 가져온다 → _section() 참고. 각 팀원 블록은
minio(자기 키) + postgresql_catalog·postgresql_optuna(공용 DB, 모든 팀원 블록에 같은 값) 세 섹션
(nested dict)을 담고, 비밀 값은 SecretDict 로 가려진다. catalog.py 는 컨테이너 밖에서 도는 도구라
docker-compose.env(Docker/Prefect/ 에 있어 찾을 수 없음)도, 프로세스 환경변수도 쓰지 않는다. member 가
없거나 서버 미연결/블록 없음이면 default(localhost)로 떨어진다(관리자가 팀원마다
`python credentials.py <member>.json` 으로 등록해 둔 경우 인증되어 동작). Credentials 클래스는 credentials.py 에 있다.

**DB·MinIO 모두 팀원 블록에서 온다**: `-m <member>`(라이브러리에선 set_member())로 어느 팀원 블록을
읽을지 정한다 — 모든 명령에 -m 가 있다. catalog·optuna 는 공용 DB 라 어느 팀원 블록이든 같은 값 → _section().
"""
import argparse
import glob
import json
import re
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import Json, RealDictCursor

__version__ = "0.0.32"  # Semantic Versioning:  Version = Major.Minor.Patch

_MEMBER = None       # block name = team member's name; set by CLI -m or set_member(), used to read creds
_PG_HOST = None      # CLI --pg-host: override the postgresql endpoint host only (creds unchanged)
_MINIO_HOST = None   # CLI --minio-host: override the minio endpoint host only (creds unchanged)

# The Credentials block class lives in credentials.py (Prefect/ folder). Import is optional so catalog.py
# still runs (on _DEFAULTS) without prefect/credentials available.
try:
    from credentials import Credentials    # shared block class (defined in Prefect/credentials.py)
except Exception:                          # prefect/credentials missing -> _section() falls back to _DEFAULTS
    Credentials = None

_DEFAULTS = {
    "minio": {"endpoint": "http://localhost:9000", "access_key": "minioadmin", "secret_key": "minioadmin"},
    "postgresql_catalog": {
        "endpoint": "localhost:5432", "username": "postgres", "password": "postgres", "database": "catalog",
    },
    "postgresql_optuna": {
        "endpoint": "localhost:5432", "username": "postgres", "password": "postgres", "database": "optuna",
    },
}


def set_member(member: Optional[str]) -> None:
    """라이브러리 사용 시 자격증명을 읽을 팀원 블록 이름을 지정한다 (CLI 는 -m 가 설정)."""
    global _MEMBER
    _MEMBER = member


def set_host_overrides(pg_host: Optional[str] = None, minio_host: Optional[str] = None) -> None:
    """엔드포인트의 host 만 덮어쓴다 (creds·port·scheme 불변). 컨테이너용 블록을 호스트에서 재사용할 때."""
    global _PG_HOST, _MINIO_HOST
    _PG_HOST = pg_host
    _MINIO_HOST = minio_host


def _override_url_host(url: str, host: Optional[str]) -> str:
    """URL 의 host 만 새 host 로 바꾼다 (scheme·port·path 유지). host 가 None 이면 원본 그대로."""
    if not host:
        return url
    from urllib.parse import urlparse, urlunparse
    u = urlparse(url)
    netloc = f"{host}:{u.port}" if u.port else host
    return urlunparse(u._replace(netloc=netloc))


def _section(section: str, member: Optional[str] = None) -> Tuple[dict, str]:
    """한 섹션(dict)을 (값, 출처) 로 해석한다 — 블록 이름 = 팀원 이름.

    member(없으면 전역 _MEMBER)의 블록 `Credentials.load(member)` 에서 그 섹션을 돌려준다. 각 팀원 블록은
    minio(자기 키) + postgresql_catalog·postgresql_optuna(공용 DB, 모든 팀원 블록에 같은 값) 세 섹션을 담는다.
    catalog.py 는 컨테이너 밖에서 도는 도구라 docker-compose.env 도, 프로세스 환경변수도 쓰지 않는다 (블록만).
    member 가 없거나 prefect 미설치/서버 미연결/블록 없음이면 _DEFAULTS(localhost) 로 떨어진다. 출처는
    'prefect-block (member=...)' | 'default'.
    """
    member = member or _MEMBER
    if Credentials is not None and member:
        try:
            d = getattr(Credentials.load(member), section).get_secret_value()      # SecretDict -> plain dict
            return d, f"prefect-block (member={member})"
        except Exception:                                                          # block missing / server down
            pass
    return _DEFAULTS[section], "default"


def _dsn() -> str:
    """팀원 블록의 'postgresql_catalog' 섹션 필드로 DSN 을 조립한다 (DSN 문자열을 통째로 저장하지 않음)."""
    cfg, _ = _section("postgresql_catalog")
    host, _, port = cfg["endpoint"].partition(":")           # "postgres:5432"
    if _PG_HOST:                                             # CLI --pg-host overrides host only
        host = _PG_HOST
    return f"postgresql://{cfg['username']}:{cfg['password']}@{host}:{port or '5432'}/{cfg['database']}"

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


def _conn() -> "psycopg2.extensions.connection":
    return psycopg2.connect(_dsn())


# --------------------------------------------------------------------------- #
# 쓰기 / 스키마
# --------------------------------------------------------------------------- #
def ensure_schema() -> None:
    """`datasets` 테이블이 없으면 만든다(있으면 그냥 통과). flow 시작 시 1회 호출."""
    with _conn() as c, c.cursor() as cur:
        cur.execute(DDL)


def register(dataset_id: str, version: str, minio_path: str, *, created_by: Optional[str] = None,
             n_files: Optional[int] = None, size_bytes: Optional[int] = None,
             content_hash: Optional[str] = None, prefect_run_id: Optional[str] = None,
             description: Optional[str] = None, metadata: Optional[dict] = None) -> None:
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
_REQUIRED_SPEC_KEYS = ("dataset_id", "version", "path")   # upload() rejects a spec missing any of these
_SPEC_TEMPLATE = {                                        # `spec` command writes this skeleton to fill in
    "dataset_id": "", "version": "", "path": "",
    "bucket": "datasets", "created_by": "", "description": "", "metadata": {},
}


def _check_name(name: str, field: str) -> None:
    """dataset_id / version 이름 규칙: 소문자·숫자·`_`·`.` 만 (공백·대문자·`-` 불가).

    이 값이 그대로 MinIO 경로와 catalog 키가 되므로 강제한다.
    """
    if not name or not _NAME_RE.match(name):
        raise ValueError(
            f"{field} '{name}' invalid: allowed lowercase a-z, digits 0-9, '_', '.' "
            "(no spaces, uppercase, or '-').")


def _has_match(cand: str) -> bool:
    """후보 경로/패턴이 실제 파일·폴더를 가리키면 True (glob 패턴이면 매치 파일 존재로 판단)."""
    if glob.has_magic(cand):
        return any(Path(p).is_file() for p in glob.glob(cand, recursive=True))
    return Path(cand).exists()


def _locate(path: str, spec_dir: Optional[Path] = None) -> str:
    """상대 path 를 spec.json 위치와 catalog.py 위치 두 기준으로 찾는다 (절대경로는 그대로 반환).

    양쪽 기준 모두에서 발견되면 (중복) 모호하므로 메시지와 함께 ValueError. 어디서도 못 찾으면
    FileNotFoundError. 정확히 한 곳에서만 찾으면 그 절대 경로 (글로브면 절대 패턴) 를 돌려준다.
    spec_dir 가 없으면 (라이브러리 호출) 현재 작업 폴더를 spec 위치 대신 쓴다.
    """
    if Path(path).is_absolute():
        if not _has_match(path):                           # absolute but missing -> stop with a message
            raise FileNotFoundError(f"path '{path}' not found (absolute path)")
        return path
    bases, seen = [], set()
    for b in (spec_dir or Path.cwd(), Path(__file__).resolve().parent):
        rb = Path(b).resolve()
        if rb not in seen:                                 # dedupe (spec.json next to catalog.py 인 경우)
            seen.add(rb)
            bases.append(rb)
    hits = [str(rb / path) for rb in bases if _has_match(str(rb / path))]
    if not hits:
        raise FileNotFoundError(
            f"path '{path}' not found under " + " or ".join(str(b) for b in bases))
    if len(hits) > 1:
        raise ValueError(
            f"path '{path}' is ambiguous - matches under both locations:\n  "
            + "\n  ".join(hits)
            + "\nuse an absolute path in spec, or keep it under only one location.")
    return hits[0]


def _glob_base(pattern: str) -> Path:
    """매직 문자가 처음 나오기 전까지의 선행 경로 (glob 키의 기준 폴더). 없으면 Path()(= cwd)."""
    parts = []
    for part in Path(pattern).parts:
        if glob.has_magic(part):
            break
        parts.append(part)
    return Path(*parts) if parts else Path()


def _resolve_sources(path: str) -> List[Tuple[Path, str]]:
    """spec 'path' 를 (로컬 파일, MinIO 키 꼬리) 쌍 목록으로 푼다.

    - 파일       -> 그 파일 하나 (키 = 파일명)
    - 폴더       -> 폴더 아래 모든 파일 (재귀), 키 = 폴더 기준 상대경로
    - 와일드카드 -> glob 매치 (`*` `?` `[]`, 재귀는 `**`), 키 = 매직 없는 선행 폴더 기준 상대경로
    매치가 없거나 경로가 없으면 FileNotFoundError.
    """
    if glob.has_magic(path):
        files = sorted(p for p in map(Path, glob.glob(path, recursive=True)) if p.is_file())
        if not files:
            raise FileNotFoundError(f"no files match pattern: {path}")
        base = _glob_base(path)
        return [(p, p.relative_to(base).as_posix() if base.parts else p.as_posix()) for p in files]
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(f"path not found: {path}")
    if src.is_dir():
        files = sorted(p for p in src.rglob("*") if p.is_file())
        return [(p, p.relative_to(src).as_posix()) for p in files]
    return [(src, src.name)]


def upload(spec: dict, member: Optional[str] = None, spec_dir: Optional[Path] = None) -> str:
    """JSON spec 한 건으로 MinIO 에 데이터를 올리고 catalog 에 버전 레코드를 등록한다.

    spec keys:
      dataset_id (req) · version (req) · path (req, 파일·폴더·와일드카드 `dir/*.csv`)
      bucket (기본 'datasets') · created_by · description · metadata (dict) · prefect_run_id · member

    상대 path 는 spec_dir(spec.json 위치) 와 catalog.py 위치 두 기준으로 찾는다 — 양쪽 다 있으면
    모호하다고 중단, 한 곳에만 있으면 그걸 쓴다 (절대경로는 그대로). _locate() 참고.
    member (인자 또는 spec['member']) 가 있으면 그 사용자의 MinIO 키로 올린다.
    버전은 불변 (immutable): 같은 dataset_id/version 이 MinIO 나 catalog 에 이미 있으면
    덮어쓰지 않고 중단한다 (버전을 올려 다시 시도).
    """
    missing = [k for k in _REQUIRED_SPEC_KEYS if not spec.get(k)]
    if missing:
        raise ValueError(
            f"spec missing required key(s): {', '.join(missing)}"
            f" (required: {', '.join(_REQUIRED_SPEC_KEYS)})."
            " run 'python catalog.py spec <out.json>' to scaffold one.")
    dataset_id = spec["dataset_id"]
    version = spec["version"]
    path = spec["path"]
    bucket = spec.get("bucket", "datasets")
    member = member or spec.get("member")

    _check_name(dataset_id, "dataset_id")
    _check_name(version, "version")
    located = _locate(path, spec_dir)              # resolve relative path vs spec dir + catalog dir
    files = _resolve_sources(located)              # file | folder (recursive) | glob (dir/*.csv, **)

    s3 = _s3(member)
    prefix = f"{dataset_id}/{version}/"
    minio_path = f"s3://{bucket}/{prefix}"
    ensure_schema()                                # create the catalog table if missing, before the dup check
    if get(dataset_id, version) or s3.list_objects_v2(
            Bucket=bucket, Prefix=prefix, MaxKeys=1).get("KeyCount", 0):
        raise FileExistsError(f"version already exists: {minio_path} (bump the version)")

    # upload each resolved file (key suffix already computed relative to the path's base)
    n_files, size_bytes = 0, 0
    for fp, rel in files:
        s3.upload_file(str(fp), bucket, prefix + rel)
        n_files += 1
        size_bytes += fp.stat().st_size

    register(dataset_id, version, minio_path,
             created_by=spec.get("created_by"),
             n_files=n_files, size_bytes=size_bytes,
             prefect_run_id=spec.get("prefect_run_id"),
             description=spec.get("description"),
             metadata=spec.get("metadata") or {})
    print(f"[catalog] uploaded {n_files} file(s), {size_bytes} B -> {minio_path} and registered")
    return minio_path


def write_spec_template(out: str = "spec.json") -> str:
    """빈 upload spec.json 뼈대를 파일로 쓴다 (이미 있으면 덮지 않음). 채워서 `upload` 에 넘긴다."""
    p = Path(out)
    if p.exists():
        raise FileExistsError(f"{out} already exists (not overwriting)")
    p.write_text(json.dumps(_SPEC_TEMPLATE, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[catalog] wrote empty spec -> {out} (fill in required: {', '.join(_REQUIRED_SPEC_KEYS)})")
    return out


# --------------------------------------------------------------------------- #
# 다운로드 / 삭제 (MinIO ± catalog) — boto3 직접 (mc 불필요)
# --------------------------------------------------------------------------- #
def download(dataset_id: str, version: Optional[str] = None, dest: Optional[str] = None,
             member: Optional[str] = None) -> str:
    """catalog 에서 minio_path 를 찾아 (version 생략 시 최신) 그 아래 객체를 dest 로 내려받는다.

    dest 기본값은 `./<dataset_id>`. member 를 주면 그 사용자의 MinIO 키로 받는다.
    "search → select → download" 흐름.
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
    s3 = _s3(member)
    n = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            rel = key[len(prefix):] if key.startswith(prefix) else key
            target = Path(dest) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(target))
            n += 1
    print(f"[catalog] downloaded {n} file(s): {row['minio_path']} -> {dest}")
    return dest


def _delete_prefix(s3: Any, bucket: str, prefix: str) -> int:
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


def remove(dataset_id: str, version: Optional[str] = None, *, yes: bool = False, member: Optional[str] = None) -> None:
    """MinIO 객체와 catalog 행을 영구 삭제한다 (version 생략 시 데이터셋 전체).

    member 를 주면 그 사용자의 MinIO 키로 지운다 (그 사용자 권한으로만 삭제 가능).
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

    n_obj = _delete_prefix(_s3(member), bucket, prefix)
    with _conn() as c, c.cursor() as cur:
        if version:
            cur.execute("DELETE FROM datasets WHERE dataset_id=%s AND version=%s",
                        (dataset_id, version))
        else:
            cur.execute("DELETE FROM datasets WHERE dataset_id=%s", (dataset_id,))
        n_rows = cur.rowcount
    print(f"[catalog] removed {shown}: {n_obj} object(s), {n_rows} catalog row(s)")


def objects(dataset_id: Optional[str] = None, *, bucket: str = "datasets",
            member: Optional[str] = None) -> List[dict]:
    """MinIO 에 실제로 있는 객체를 나열한다 (catalog 등록과 무관한 원본 보기). member 키 우선."""
    prefix = f"{dataset_id}/" if dataset_id else ""
    s3 = _s3(member)
    rows = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            rows.append({"key": obj["Key"], "size": obj["Size"]})
    return rows


# --------------------------------------------------------------------------- #
# 읽기 / 검색
# --------------------------------------------------------------------------- #
def find(dataset_id: Optional[str] = None, **filters: Any) -> List[dict]:
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


def get(dataset_id: str, version: Optional[str] = None) -> Optional[dict]:
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
def list_datasets() -> List[dict]:
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


def versions(dataset_id: str) -> List[dict]:
    """한 데이터셋의 모든 버전 이력(최신 → 과거)."""
    sql = ("SELECT version, created_by, created_at, minio_path, metadata "
           "FROM datasets WHERE dataset_id=%s ORDER BY created_at DESC")
    with _conn() as c, c.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, [dataset_id])
        return cur.fetchall()


def tree() -> Dict[str, List[str]]:
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
def _s3(member: Optional[str] = None) -> Any:
    """MinIO(S3 호환) 클라이언트. 블록의 'minio' 섹션(endpoint·access·secret)을 그대로 쓴다.

    member(없으면 전역 _MEMBER)의 블록 minio 키로 접속해 버킷 권한이 팀원별로 적용된다. member 가
    없거나 블록이 없으면 _DEFAULTS 로 떨어진다.
    """
    import boto3
    m, _ = _section("minio", member)                  # endpoint/access_key/secret_key (per-user, fallback shared)
    return boto3.client("s3", endpoint_url=_override_url_host(m["endpoint"], _MINIO_HOST),
                        aws_access_key_id=m["access_key"], aws_secret_access_key=m["secret_key"])


def _ext_counts(minio_path: str, member: Optional[str] = None) -> Dict[str, int]:
    """minio_path 아래 객체를 확장자별로 세어 {ext: count} 로 반환."""
    from urllib.parse import urlparse
    s3 = _s3(member)
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


def _fmt_counts(counts: Dict[str, int]) -> str:
    """{'parquet':128,'csv':13} -> '(128 parquet, 13 csv)'. 비면 '(empty)'."""
    if not counts:
        return "(empty)"
    parts = ", ".join(f"{n} {e}" for e, n in sorted(counts.items(), key=lambda x: -x[1]))
    return f"({parts})"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_rows(rows: List[dict], cols: List[str]) -> None:
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


def _print_tree(dataset_id: Optional[str] = None, with_files: bool = False,
                member: Optional[str] = None) -> None:
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
                        line += "  " + _fmt_counts(_ext_counts(row["minio_path"], member))
                    except Exception as e:
                        line += f"  (count failed: {e})"
            print(line)


# Command handlers: one per subcommand, bound via set_defaults(func=...); each takes the parsed args.
def _cmd_list(args: argparse.Namespace) -> None:
    _print_rows(list_datasets(),
                ["dataset_id", "versions", "latest_version", "latest_by", "last_updated"])


def _cmd_versions(args: argparse.Namespace) -> None:
    _print_rows(versions(args.dataset_id),
                ["version", "created_by", "created_at", "minio_path"])


def _cmd_tree(args: argparse.Namespace) -> None:
    _print_tree(args.dataset_id, args.files, args.member)


def _cmd_find(args: argparse.Namespace) -> None:
    _print_rows(find(args.dataset_id, **args.filters),
                ["dataset_id", "version", "created_by", "minio_path"])


def _cmd_spec(args: argparse.Namespace) -> None:
    write_spec_template(args.out)


def _cmd_upload(args: argparse.Namespace) -> None:
    spec_path = Path(args.spec)
    upload(json.loads(spec_path.read_text(encoding="utf-8")), member=args.member,
           spec_dir=spec_path.parent)


def _cmd_download(args: argparse.Namespace) -> None:
    download(args.dataset_id, args.version, args.dest, member=args.member)


def _cmd_remove(args: argparse.Namespace) -> None:
    remove(args.dataset_id, args.version, yes=args.yes, member=args.member)


def _cmd_objects(args: argparse.Namespace) -> None:
    _print_rows(objects(args.dataset_id, member=args.member), ["key", "size"])


def _add_member(sp: argparse.ArgumentParser) -> None:
    """연결 옵션을 붙인다: -m/--member (블록 = 팀원 이름; DB·MinIO creds) + 엔드포인트 host 덮어쓰기.

    --pg-host/--minio-host 는 엔드포인트의 host 만 바꾼다 (creds 불변) — 컨테이너용 블록을
    호스트에서 재사용할 때 `--pg-host localhost --minio-host localhost` 처럼 쓴다.
    """
    sp.add_argument("-m", "--member", type=str, default=None,
                    help="team member name = credential block name; read DB/MinIO creds from that block")
    sp.add_argument("--pg-host", type=str, default=None,
                    help="override the postgresql endpoint host only, e.g. localhost (creds unchanged)")
    sp.add_argument("--minio-host", type=str, default=None,
                    help="override the minio endpoint host only, e.g. localhost (creds unchanged)")


def _build_parser() -> argparse.ArgumentParser:
    epilog = textwrap.dedent("""\
        examples:
          python catalog.py list                              # dataset summary (latest version)
          python catalog.py versions sydney_202605            # one dataset's version history
          python catalog.py tree --files                      # dataset > version tree (+ file-type counts)
          python catalog.py find sydney_202605 fab=fab2       # search by metadata key=value
          python catalog.py spec spec.json                    # write an empty upload spec template
          python catalog.py upload spec.json                  # upload to MinIO + register (JSON spec)
          python catalog.py download sydney_202605 v2 ./out   # version omitted -> latest; dest -> ./<id>
          python catalog.py remove sydney_202605 v2 --yes     # version omitted -> whole dataset
          python catalog.py objects sydney_202605             # raw MinIO objects (not the catalog)
          python catalog.py list -m alice                     # read alice's block for DB/MinIO creds (-m, any command)

        upload spec.json:
          {"dataset_id": "sydney_202605", "version": "v2", "path": "./out",
           "bucket": "datasets", "created_by": "zoo", "description": "fab2 CH3",
           "metadata": {"fab": "fab2", "chamber": "CH3"}}

        targets (each command prints where it connects + creds source at start):
          [PostgreSQL] = catalog DB ledger,  [MinIO] = object storage
          creds source: prefect-block | default
          list/versions/find = PostgreSQL    objects = MinIO
          upload/download/remove = both      tree = PostgreSQL (+MinIO with --files)

        credentials - from the team member's Prefect block (block name = member; via the
        profile's PREFECT_API_URL), else default. no env vars, no docker-compose.env.
          block "<member>" sections (nested dict, hidden via SecretDict):
            minio = {endpoint, access_key, secret_key}
            postgresql_catalog/postgresql_optuna = {endpoint, username, password, database}
          -m <member> picks the block (DB + MinIO). catalog/optuna are the shared DB,
                          duplicated identically in every member block (any member's works).
          --pg-host/--minio-host override only the endpoint host (creds unchanged) - reuse a
                          container block from the host: --pg-host localhost --minio-host localhost.
        """)
    p = argparse.ArgumentParser(
        prog="catalog.py",
        description=f"catalog.py v{__version__} - Data catalog (PostgreSQL ledger) + MinIO object operations.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-V", "--version", action="version", version=f"catalog.py {__version__}")
    sub = p.add_subparsers(required=True, metavar="<command>")   # exactly one command; handler via set_defaults

    sp = sub.add_parser("list", help="[PostgreSQL] list datasets (latest-version summary)")
    sp.set_defaults(func=_cmd_list, uses_pg=True, uses_minio=False)
    _add_member(sp)

    sp = sub.add_parser("versions", help="[PostgreSQL] show one dataset's version history")
    sp.set_defaults(func=_cmd_versions, uses_pg=True, uses_minio=False)
    sp.add_argument("dataset_id", type=str)
    _add_member(sp)

    sp = sub.add_parser("tree", help="[PostgreSQL; --files also MinIO] dataset > version tree")
    sp.set_defaults(func=_cmd_tree, uses_pg=True, uses_minio=False)   # --files adds MinIO at run time
    sp.add_argument("dataset_id", type=str, nargs="?", default=None,
                    help="limit to one dataset (default: all)")
    sp.add_argument("--files", action="store_true", default=False,
                    help="show MinIO file-type counts per version")
    _add_member(sp)

    sp = sub.add_parser("find", help="[PostgreSQL] search by dataset_id + metadata key=value")
    sp.set_defaults(func=_cmd_find, uses_pg=True, uses_minio=False)
    sp.add_argument("dataset_id", type=str)
    sp.add_argument("filters", type=str, nargs="*", default=[], metavar="key=value",
                    help="metadata filters")
    _add_member(sp)

    sp = sub.add_parser("spec", help="write an empty upload spec.json template to fill in")
    sp.set_defaults(func=_cmd_spec, uses_pg=False, uses_minio=False)
    sp.add_argument("out", type=str, nargs="?", default="spec.json", metavar="out.json",
                    help="output path (default: spec.json)")

    sp = sub.add_parser("upload", help="[MinIO + PostgreSQL] upload files + register, from a JSON spec")
    sp.set_defaults(func=_cmd_upload, uses_pg=True, uses_minio=True)
    sp.add_argument("spec", type=str, metavar="spec.json")
    _add_member(sp)

    sp = sub.add_parser("download", help="[PostgreSQL + MinIO] look up in catalog, download objects")
    sp.set_defaults(func=_cmd_download, uses_pg=True, uses_minio=True)
    sp.add_argument("dataset_id", type=str)
    sp.add_argument("version", type=str, nargs="?", default=None, help="default: latest")
    sp.add_argument("dest", type=str, nargs="?", default=None, help="default: ./<dataset_id>")
    _add_member(sp)

    sp = sub.add_parser("remove", help="[MinIO + PostgreSQL] PERMANENTLY delete objects + rows")
    sp.set_defaults(func=_cmd_remove, uses_pg=True, uses_minio=True)
    sp.add_argument("dataset_id", type=str)
    sp.add_argument("version", type=str, nargs="?", default=None,
                    help="default: entire dataset (all versions)")
    sp.add_argument("--yes", action="store_true", default=False,
                    help="skip the DELETE confirmation")
    _add_member(sp)

    sp = sub.add_parser("objects", help="[MinIO] list raw MinIO objects (not the catalog)")
    sp.set_defaults(func=_cmd_objects, uses_pg=False, uses_minio=True)
    sp.add_argument("dataset_id", type=str, nargs="?", default=None,
                    help="limit to one dataset (default: all)")
    _add_member(sp)

    return p


def _mask_dsn(dsn: str) -> str:
    """DSN 의 비밀번호를 *** 로 가린다 (배너 노출용)."""
    return re.sub(r"(://[^:/@]+:)[^@]*(@)", r"\1***\2", dsn)


def _print_targets(args: argparse.Namespace) -> None:
    """실행 전, 이 명령이 접속하는 대상 + 자격증명 출처를 stderr 로 알린다 (set_defaults 의 uses_pg/uses_minio 기반)."""
    label = args.func.__name__.replace("_cmd_", "")
    print(f"[catalog.py v{__version__}] command: {label}", file=sys.stderr)
    if args.uses_pg:
        _, src = _section("postgresql_catalog")
        print(f"  PostgreSQL (catalog DB): {_mask_dsn(_dsn())}  [creds: {src}]", file=sys.stderr)
    if args.uses_minio or getattr(args, "files", False):   # tree --files also reaches MinIO
        m, src = _section("minio", getattr(args, "member", None))
        ep = _override_url_host(m["endpoint"], _MINIO_HOST)
        print(f"  MinIO (object storage):  {ep}  [creds: {src}]", file=sys.stderr)


def _main(args: argparse.Namespace) -> None:
    """Dispatch one already-parsed command (parsing/validation done in parse_args())."""
    set_member(getattr(args, "member", None))              # DB ops (_dsn) read creds from this member's block
    set_host_overrides(getattr(args, "pg_host", None), getattr(args, "minio_host", None))
    _print_targets(args)
    args.func(args)                                        # handler bound via set_defaults(func=...)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Build the parser, parse argv, cross-validate option values, return the Namespace.

    인자가 하나도 없으면 전체 사용법을 출력하고 종료한다 (SystemExit 0). 잘못된 값/조합은
    parser.error() 로 usage 와 함께 비정상 종료시킨다 (exit code 2) — 호출부가 따로 검사하지 않게.
    """
    argv = sys.argv[1:] if argv is None else argv
    parser = _build_parser()
    if not argv:                                           # no CLI option -> print usage and exit
        parser.print_help()
        raise SystemExit(0)
    args = parser.parse_args(argv)
    if hasattr(args, "filters"):                           # only `find` has filters; require key=value
        bad = [kv for kv in args.filters if "=" not in kv]
        if bad:
            parser.error("find filters must be key=value (offending: %s)" % ", ".join(bad))
        args.filters = dict(kv.split("=", 1) for kv in args.filters)
    return args


if __name__ == "__main__":
    try:
        _main(parse_args())
    except (ValueError, FileNotFoundError, FileExistsError, LookupError) as exc:
        print(f"[catalog.py] error: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except psycopg2.Error as exc:                          # DB connection/query failure -> one clean line
        lines = str(exc).strip().splitlines()
        print(f"[catalog.py] database error: {lines[0] if lines else 'connection/query failed'}",
              file=sys.stderr)
        raise SystemExit(2)
