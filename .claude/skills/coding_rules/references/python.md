
---
name: python
description: python coding rules
note#1: 규칙마다 괄호안에 이유를 추가 함.

---

Rev. 13 | Created: 2026-8-23 | Updated: 2026-9-5 15:30 CDT


## 1. Grammar & Type Safety

### Annotation

- `from typing import Union` 등을 사용해서 annotation을 표시할 것.
- function annotation에서 `array: list = None`의 형식을 사용할 것.


### `__all__`

- all__을 사용해서 모듈에서 from 모듈 import *로 가져올 수 있는 공개 함수, 클래스, 변수의 목록을 문자열 리스트로 지정한다.


## 2. Module & Dependencies

### Standard Module

- 다음 모듈을 최대한 사용할 것: pathlib, argparse, tqdm, typing, dataclass, abc (Abstract Base Classes)
- 코드를 새로 생성하기 보다는 가능하면 scikit-learn, scipy, numpy 등 파이썬 모듈을 최대한 이용해서 구현 할 것.

### import
+ import는 파일 맨 위에. 함수 안에 넣지 마라
- 의존성은 파일만 열면 보여야 한다.
    + 함수 안에 숨긴 import는, 프로세스가 한참 돌아간 뒤에, 그 함수가 호출되는 순간에야 ModuleNotFoundError로 터진다.
- 무거운 의존성을 피하고 싶으면 import를 숨기지 말고 **모듈을 분리하라.**


### Matplotlib
+ `import matplotlib` 또는 `plt`를 사용하는 모든 코드에 적용.
- matrix chart를 fig.savefig()로 저장할 경우 `dpi=300` 을 지정한다.
- 색상은 `TABLEAU_COLORS`를 사용할 것.
- `figsize` 와 `dpi` 는 그림의 비례와 해상도만 정한다. 문서에서 차지할 크기는 문서 쪽이 정하므로, 그것을 줄이려고 `figsize` 나 `dpi` 를 낮추지 않는다.
- `figsize` 가 문서의 렌더 크기에 영향을 주는 유일한 경우는 종횡비를 바꿀 때이다. 세로를 줄이려면 가로 대비 세로를 납작하게 잡는다.
- Figure 안의 text 크기는 `figsize` 에 비례하도록 잡는다. Point 로 고정하면 `figsize` 를 줄일 때 글자만 커져 배치가 무너진다.

  ```python
  FIGSIZE: tuple = (9.0, 6.0)
  REFERENCE_WIDTH: float = 9.0     # the width BASE_FONT_SIZE was chosen for
  BASE_FONT_SIZE: float = 9.0
  font_size = BASE_FONT_SIZE * FIGSIZE[0] / REFERENCE_WIDTH
  ```
### tqdm

- `from tqdm import tqdm`을 아래처럼 사용할 것.

  ```python
  pbar = tqdm(files, ncols=100, unit='parquet')
  for fpath in pbar:
      pbar.set_description(f"Reading {pathlib.Path(fpath).stem}")
  ```


## 3. Style & Conventions

- hard coding 하지 말 것.
- main() 함수를 만들지 말 것.
- max code + comment line width <= 120
- comment를 모두 영어로 쓸 것.
  
### Doc string

- pandas DataFrame을 리턴하는 함수는 docstring에 리턴하는 pd.DataFrame의 index와 columns의 name을 명기할 것.

### Naming

- dir을 쓰지 말고 folder를 사용할 것.

### Variable Declaration & Constants
- **Key String Groups:** Use `enum.StrEnum` with `auto()` instead of bare strings or plain dictionaries to declare fixed key groups and prevent magic string errors.

### Class

- class는 Constructor Injection 할 것:  arguments를 method마다 받지 말고 생성자로 주입 할 것.

### Function

- 함수 정의할 때 될 수 있으면 keyword arguments를 사용하여 readability를 높일 것.
- 함수 호출할 때 keyword arguments 방식을 사용할 것.

### Command Line Interface (CLI)
+ `import argparse` 와 `import click`를 사용하는 모든 코드에 적용.

- CLI는 Kebab case를 사용한다 (예: --kebab-case)
- CLI option이 하나도 없을 때는 CLI 사용법을 출력한다.
- CLI의 option parsing을 parse_args() 함수를 생성해서 실행한다.
- parse_args()에서만 사용하는 help string은 parse_args()안에 둔다.
   (최대한으로 global variable을 없애서 가독성을 높이기 위함임)
- `parse_args()`는 `if __name__ == '__main__':` 바로 위에 위치시킬 것.
- CLI option value들 사이의 조건 검증은 `parse_args()`에서 진행하고 crash 처리할 것.
- file or folder path의 CLI는 `parse_args()`에서 확인하고 오류가 있으면 help 메세지 출력할 것.
 
- 주로 **`argparse`** 모듈을 사용해서 `def parse_args()  -> argparse.Namespace` 에서 처리한다.
  - Boolean CLI option은 `store_true`나 `BooleanOptionalAction`을 쓰지 말고 값을 받게 하라: 
    * `--<option> {true,false}` 형태로 `choices=['true', 'false']`와 명시적 default를 주고, `parse_args()` 안에서 bool로 변환하라.
    * `--no-<option>` 같은 부정형 쌍둥이 option을 만들지 마라. 상태 하나에 option 하나 —   켜고 끄는 일이 같은 이름으로 읽혀야 CLI 표면이 늘지 않는다.
  - `argparse.ArgumentParser`의 choices 옵션을 필요시 사용할 것.
  - CLI option에서 choices로 검증된 변수를 함수의 argument로 사용할 때는
  `from typing import Literal`을 사용해서 표시할 것.

- `--ouput-folder` option으로 모든 output root 가 되어 다른 산출물들이 이 폴더 밑으로 들어간다.

- **`click`** 사용 시, 복수의 option이 배타적일 때는 `MutuallyExclusiveOption(click.Option)`을 `cls`로 걸어서 parsing 단계에서 막을 것.

### Chart Data

- 분포를 그리는 chart (violin, box, histogram, KDE) 는 그림이 받은 표본을 file 로 남길 것.
  (요약값만으로는 분포의 모양이 복원되지 않아 그림을 다시 그릴 수 없다.)
- 저장 단위는 표본 하나가 한 행이며, mean·median·min·max 같은 요약값은 저장하지 말 것.
  (요약값은 표본에서 언제든 계산되고, 두 벌로 두면 서로 어긋난다.)
- 표시용으로 값을 자른 경우 (clipping), file 에는 자르지 않은 값을 쓸 것.
  (그림은 읽기 편하려고 자르지만, 자료는 사실이어야 한다.)
- 문서가 인용하는 수치는 그 file 에서 계산할 것. 그림에서 눈으로 읽어 옮기지 말 것.
  (그림에서 옮긴 수는 검증할 수 없고, 그림이 바뀌면 조용히 틀린 값이 된다.)

## 4. Error Handling & Robustness

* Include fallback mechanisms or clear error messages for critical failures.


## 5. Risk Mitigation

- **Deterministic Execution & Reproducibility:** Do not use `list(set(...))` as `set` iteration order is non-deterministic across Python processes. Always use `sorted(list(set(...)))` or `dict.fromkeys(...)` (to preserve insertion order) when unique ordered collections are required