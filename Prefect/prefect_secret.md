# Prefect Secret

Prefect의 **Secret 블록**으로 비밀값(키·비밀번호·자격증명)을 **Prefect 서버에 저장**하고, 코드에서 **이름으로 불러와** 안전하게 쓴다.

---

## 1. Overview

- **Secret 블록**은 민감한 값을 Prefect 서버(backend DB)에 **이름 붙여 저장**하고 코드가 이름으로 꺼내 쓰는 Prefect 내장 기능이며, UI·로그에서는 값이 가려진다.
- 저장 방법은 **① 파이썬 코드**와 **② 웹 UI** 두 가지가 있고, 저장한 값을 불러와 쓰는 코드는 어느 방법이든 동일하다.
- 값으로는 문자열뿐 아니라 **dict(JSON)** 도 넣을 수 있어, 여러 자격증명을 한 블록에 묶을 수 있다.

---

## 2. Store — Python Code

스크립트를 1회 실행해 Secret을 서버(또는 Prefect Cloud)에 저장한다. `overwrite=True` 면 같은 이름이 있을 때 덮어쓴다.

**문자열 하나를 저장한다:**
```python
from prefect.blocks.system import Secret

block: Secret = Secret(value="my-secret-key")   # 비밀 문자열을 담은 Secret 블록
block.save(name="api-key", overwrite=True)      # 서버에 'api-key' 라는 이름으로 저장
```

**dict 로 여러 값을 한 블록에 저장한다:**
```python
from prefect.blocks.system import Secret

creds: dict = {
    "access_key": "AKIA...",
    "secret_key": "wJal...",
    "endpoint":   "http://example:9000",
}
Secret(value=creds).save(name="my-confidentials", overwrite=True)
```

---

## 3. Store — Web UI

코드 없이 대시보드에서 등록할 수도 있다.

1. Prefect 대시보드에 접속한다.
2. 좌측 메뉴에서 **Blocks** 를 누르고, 우측 상단 **[+ Add Block]** 을 클릭한다.
3. 블록 종류에서 **Secret** 을 선택한다.
4. **Block Name** 과 **Value** 를 입력한 뒤 **Save** 를 누른다.

---

## 4. Load & Use

저장 방식과 무관하게, 코드에서는 이름으로 로드한 뒤 `.get()` 으로 실제 값을 꺼낸다.

```python
from prefect import flow, task
from prefect.blocks.system import Secret

@task
def use_credentials(creds: dict) -> dict:
    print(f"endpoint={creds['endpoint']} (key len={len(creds['access_key'])})")
    return {"status": "ok"}

@flow(name="secret-demo")
def my_pipeline() -> dict:
    creds: dict = Secret.load("my-confidentials").get()   # → dict (복호화된 실제 값)
    return use_credentials(creds)

if __name__ == "__main__":
    my_pipeline()
```

---

## 5. Per-User Secrets

user별로 다른 값을 주려면 **블록 이름에 user를 박아** 저장하고, 코드가 실행 중인 user에 맞는 이름을 고른다.

```python
# 등록 (user별 1회)
from prefect.blocks.system import Secret

Secret(value={"access_key": "...A", "secret_key": "...A"}).save("my-confidentials-userA", overwrite=True)
Secret(value={"access_key": "...B", "secret_key": "...B"}).save("my-confidentials-userB", overwrite=True)
```

```python
# 사용 — 실행 중인 user에 맞는 블록을 고른다
import os
from prefect.blocks.system import Secret

user: str = os.environ["USER_ID"]
creds: dict = Secret.load(f"my-confidentials-{user}").get()
```

> ⚠️ **self-hosted Prefect(OSS) 서버는 기본 API 인증이 없어**, API에 접근 가능한 사람은 모든 Secret을 읽을 수 있다. 이 방식은 **이름만 분리될 뿐 접근 차단은 아니므로**, 진짜 격리가 필요하면 각 머신에 **환경변수**로 분리하거나 Prefect Cloud(워크스페이스/RBAC), 또는 Vault 같은 시크릿 매니저를 쓴다.

---

## 6. Notes

- **저장 위치**: Secret 값은 Prefect 서버의 backend DB(Prefect 메타데이터 DB) 안 block 테이블에 저장된다.
- **Variable 과의 차이**: `prefect.variables` 의 Variable도 서버에 이름-값을 저장하지만, 값을 가리지 않고 **평문 그대로** 보관한다. 따라서 비밀번호·키 같은 민감한 값은 Secret에 두고, 엔드포인트·플래그처럼 민감하지 않은 설정값은 Variable에 둔다.
- **Naming Convention**: 블록이 많아지면 팀원들이 헷갈릴 수 있으므로, 이름 규칙이 필요하다. 예: `[프로젝트명]-[Task명]-[용도]` (예: `sydney2026-modeling-rw`).
