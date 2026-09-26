---
name: coding_rules
description: 코드를 쓰거나 고칠 때 반드시 지킬 규칙. Edit/Write 하기 전에 로드할 것. 입력 검증, 실패 처리, API 설계, 검증, 버전 표기에 적용된다.
---
# Coding Rules

Rev. 27 | Created: 2026-8-26 | Updated: 2026-8-26 14:30 CDT


## 적용 방법

코드를 작성·수정하기 전에 해당 언어의 규칙 파일을 읽는다.

| 언어     | 파일                     |
| ------ | ---------------------- |
| Python | `references/python.md` |

파일이 없는 언어는 일반 관례를 따른다.



## 1. 원칙

### 1.1. 애매하면 조용히 고르지 말고 에러를 내라

호출자가 모순된 입력을 줬다면 그건 버그다. 한쪽을 골라주는 건 버그를 감추는 것이다.

- 같은 것을 정하는 인자 2개를 동시에 받으면 → 에러. 한쪽 무시 금지.
- 예상 밖 입력을 기본값으로 채우지 마라.
- 침묵의 우선순위(`a or b`)로 모순을 해소하지 마라.
  ```python
  # 나쁨: 둘 다 줬는데 value가 이긴다. 호출자는 method가 먹은 줄 안다
  result = value or compute(method=method)

  # 좋음
  if value and method:
      raise ValueError("value and method are mutually exclusive; pass one or neither.")
  ```

### 1.2. 코드의 실패를 드러내라

로그가 없는 실패는 없었던 일이 된다. 몇 달을 그렇게 지나갈 수 있다.

- `verbose`/`debug` 플래그 안에 에러 로그를 넣지 마라. 실패는 항상 보이게.
- 빈 결과를 정상처럼 반환하지 마라. 0건은 그 자체가 신호다.
- 참/거짓만 보고 통과시키지 마라. 공백 문자열도 truthy다.
- `except: pass` 금지. 삼킬 거면 왜 삼켜도 되는지 주석으로 남겨라.
  ```python
  # 나쁨: verbose=False면 아무도 모른다
  if verbose:
      logger.warning(f"failed: {reason}")
  # 좋음: 실패는 verbose와 무관하게 보인다
  logger.error(f"failed {failed_count}/{total}: {reason}")
  ```

  ```python
  # 나쁨: '\r\n' * 6 도 truthy라 통과한다
  if response.text:
      data = response.json()
  # 좋음
  if not response.text.strip():
      raise ValueError(f"empty body: {response.status_code=}")
  ```

### 1.3. 잘못된 사용이 애초에 불가능하게 만들어라

막는 것보다 없애는 게 낫다. 에러로 막으면 여전히 틀릴 수 있지만, 표현 자체가 불가능하면 틀릴 수 없다.

- 인자 2개가 배타적이면 → **하나로 합쳐라.** 그게 안 될 때만 에러로 막아라.
- "쓰면 안 되는 조합"을 문서에 적지 말고 코드가 막게 하라.
- 위험한 기본값을 주지 마라. 위험한 선택은 명시적으로 opt-in 하게 하라.

### 1.4. 검증 없이 "됐습니다" 하지 마라

- 고쳤으면 실제로 돌려봐라. 못 돌렸으면 **"안 돌려봤다"고 말해라.**
- 테스트가 실패하면 기대값이 틀린 건지 코드가 틀린 건지 **먼저 가려라.**
- 기존 동작을 바꿨으면 기존 사용처가 안 깨졌는지부터 확인하라.


## 2. 공통

### 2.1. Author

- author는 **yRocket**을 사용할 것.
    + python: `__author__ = 'yRocket'` 의 형식으로 파일 위에 둘 것

### 2.2. Changelog

- Major or Minor change시에만 docstring 의 changelog에 변경 내용을 한 줄로 추가한다.
### 2.3. Versioning

- versioning marker는 날짜가 있는 `__version__` `Major.Minor.Patch.Date(YYYY.M.D)` 형식이 default이고, 날짜가 없는 `Major.Minor.Patch` 형식도 있다.
- initial release에는 `0.0.0.<YYYY.M.D>` 를 둔다.
- `py`, `ps1`, `sh`, `yml` 파일 머리에 아래처럼 versioning marker를 기입하고, 없으면 추가할 것:

  ```python
  __version__ = "0.0.0.2026.7.14"  # Semantic Versioning: Major.Minor.Patch.Date(YYYY.M.D)
  ```

- 날짜가 있는 형식이면 change 발생 시:
  - **patch bump** + 날짜를 오늘로
  - 기능 추가면 **minor bump**, patch는 0
  - 날짜가 없는 형식 (예: `__version__ = "0.0.0"`) 이면 change 발생 시 **patch bump**만 할 것  (날짜 없음).

### 2.4. CLI (Command Line Interface)

- `-h`, `--help` 를 추가해서 usage stdout을 보이게 한다.
- `-v`, `--version`을 추가해서 `__version__` 을 보이게 한다.
- usage stdout에는 script name과  `__version__`을 맨 위에서 보이게 한다.

## 3. 반면교사: 실제 사고 기록

+ 전부 실제로 낸 사고에서 나왔다. 원인이 셋 다 같다 — **모순을 만나면 에러 대신 조용히 한쪽을 고름.**

| 사고                            | 결과                   |
| ----------------------------- | -------------------- |
| 빈 응답을 truthy라 통과시킴            | 스케줄러가 죽음             |
| `verbose=False`라 실패를 로그도 안 남김 | 수집이 7개월간 조용히 멈춰 있었음  |
| 배타적 인자 2개를 받고 한쪽을 조용히 무시      | 사용자가 안 먹은 옵션을 먹은 줄 앎 |
