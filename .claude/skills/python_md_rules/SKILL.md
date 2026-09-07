---
name: python_md_rules
description: 사용자가 python code에 대한 markdown document의 생성을 원할 때 로드 할 것. Python 소스(.py 파일, 패키지, 리포지토리)를 읽어 구조·공개 API·사용예시를 정리한 Markdown 문서(README, API 레퍼런스, 모듈 설명서)를 생성한다. 사용자가 Python 코드를 두고 "문서 만들어줘", "README 써줘", "API 정리해줘", "모듈 설명서", "docstring 기반 문서화" 등을 요청하면 반드시 이 스킬을 사용할 것. 'Markdown'이나 '문서'라는 단어를 쓰지 않더라도, 코드에 대한 설명 산출물을 파일로 요구하면 사용한다. 단, 코드 동작을 대화로 설명만 하는 경우, docstring·주석을 코드 안에 추가하는 경우, Python 이외의 언어는 대상이 아니다.
---
# Python Documentation Conventions

Rev. 5 | Created: 2026-8-11 | Updated: 2026-8-18 08:15 CDT


이 컨벤션의 목적은 **독자가 코드를 읽지 않고도 "무엇을 왜, 어떤 데이터로, 어떻게 돌려서, 무엇을 얻었는지"를 순서대로 재구성할 수 있게** 하는 것이다. 각 장은 그 재구성 과정의 한 단계를 담당하며, 순서를 바꾸면 독자가 앞 장의 결과를 모르는 상태에서 뒷 장을 읽게 되므로 순서는 고정한다.

## Markdown File

markdown file 이름은 python script file의 stem을 사용하여 `<stem>.md` 로 한다.

## Document Scope

### Script Correspondence

+ `<script>.md` 는 `<script>.py` 의 실행 결과만 담는다. 문서 이름이 곧 출처 계약이며, 독자는 문서의 모든 표·figure·수치를 그 script 한 번의 실행 산출물로 읽는다.
+ 다른 script 의 결과 (표, figure, CSV) 를 부득이 실을 때는, 산출한 script 이름을 본문과 figure caption 에 명시하여 출처를 숨기지 않는다.
+ 사용자에게 결과를 보고할 때도 어느 script 의 실행 결과인지 함께 밝힌다.

## Document skeleton

문서 제목만 H1이고, 각 장은 **번호를 붙인 H2**다. 아래 골격을 그대로 사용한다. 해당 없는 장이라도 삭제하지 말고 제목을 남긴 뒤 `N/A — <이유>` 한 줄을 적는다. 장이 비어 있다는 사실 자체가 정보이기 때문이다.

```markdown
# <Document title>

Rev. <n> | Created: <YYYY-MM-DD> | Updated: <YYYY-MM-DD HH:MM TZ>

**Goal** — ...
**Non-Goals** — ...
**Background** — ...

## 1. Pipeline
## 2. Method
## 3. Input
## 4. Output
## 5. Result
## 6. Analysis

## Appendix A. Terminology
## Appendix B. CLI (Command Line Options)
```

장 번호는 1–6으로 고정이며, 장을 `N/A`로 비우더라도 번호는 재배열하지 않는다. 번호가 문서 간 참조("4장 Output 참고")의 고정 좌표 역할을 하기 때문이다. 하위 절은 `### 4.1`처럼 장 번호를 상속한다. 부록은 번호 대신 A, B를 쓰고, 추가 부록이 필요하면 C부터 이어 붙인다.

## Front matter

`Rev.` / `Created` / `Updated` 한 줄 뒤에 세 항목을 둔다. 날짜는 ISO 8601(`2026-08-11`, 한 자리 월·일도 0을 채운다), `Updated`에는 시각과 타임존을 붙인다.
세 항목은 blockquote (인용문)를 이용하여 아래의 예시처럼 작성한다.

- **Goal** — 이 코드가 해결하는 문제. 산출물이 아니라 판단 기준으로 쓸 수 있게 쓴다. ("웨이퍼별 두께 예측값을 생성한다"가 아니라 "계측 없이 두께를 ±X nm 내로 추정해 계측 부하를 줄인다")
- **Non-Goals** — 의도적으로 하지 않는 것. 리뷰어가 "이건 왜 없냐"고 묻게 될 항목을 미리 적는다. 범위를 좁히는 진술이므로 최소 1개는 적는다.
- **Background** — 이 코드가 왜 필요 해졌는 지의 맥락. 선행 작업, 실패한 이전 접근, 전제 조건.

## Chapters

각 장은 이름값을 해야 한다. 내용이 옆 장으로 새면 독자가 찾지 못한다.

| 장               | 담는 것                                        | 담지 않는 것           |
| --------------- | ------------------------------------------- | ----------------- |
| **1. Pipeline** | 처리 단계의 전체 흐름(단계별 목록 또는 다이어그램), 각 단계의 입출력 연결 | 알고리즘 내부           |
| **2. Method**   | 각 단계의 알고리즘·수식·하이퍼파라미터와 그 선택 근거              | 실행 결과 수치          |
| **3. Input**    | 소스, 기간/로트 범위, 파일 포맷, 스키마, 전제 조건             | 전처리 로직(→ Method)  |
| **4. Output**   | 생성되는 산출물 파일의 인벤토리 (아래 표기 규칙 필수)             | 산출물의 해석(→ Result) |
| **5. Result**   | 실행 결과 수치·지표·그래프. 사실만.                       | 원인 추정, 의견         |
| **6. Analysis** | Result에 대한 해석, 실패 사례, 한계, 다음 단계             | 새 수치의 최초 등장       |

Pipeline은 다이어그램을 쓰더라도 **텍스트 목록을 함께** 둔다. 다이어그램만 있으면 diff·검색·스크린리더에서 내용이 사라진다.

## Output chapter — file notation

산출물은 개수와 규모를 모르면 검증할 수 없다. 파일마다 아래 형식으로 적는다.

**Tabular (csv, parquet, tsv):** file count와 shape를 `(rows × cols)`로 표기한다. shape는 **파일 1개당** 기준이며 헤더 행은 제외한다.

```markdown
- `vm_features_<lot>.csv` — 49 files, shape (1,024 × 128) each
- `summary_metrics.csv` — 1 file, shape (49 × 12)
- `trace_<chamber>.csv` — 8 files, shape (2,880–3,150 × 64)   # 파일별로 다르면 범위로
```

**Non-tabular (png, json, pkl, log, npy):** file count만 적는다.

```markdown
- `sensor_matrix_<sensor>.png` — 49 files
- `model_<fold>.pkl` — 5 files
```

규칙:
- 파일명은 실제 이름 또는 glob/플레이스홀더 패턴으로 쓰고 백틱으로 감싼다.
- 1개짜리도 `1 file`이라고 명시한다. 개수 생략은 "개수를 모른다"와 구분되지 않는다.
- 네 자리 이상 숫자는 천 단위 구분자를 넣는다 (`12,480`).
- 각 파일 뒤에 한 줄로 "행 1개가 무엇인지"를 덧붙인다 (예: `1 row = 1 wafer × 1 step`). 컬럼 수만으로는 데이터 단위를 알 수 없다.
- 출력 경로와 디렉터리 구조를 장 첫머리에 트리로 한 번 보여준다.

## Appendices

- **Appendix A. Terminology** — 도메인 약어와 사내 용어. 본문에서 처음 쓸 때 풀어쓰고, 여기서 정의한다. 알파벳순.
- **Appendix B. CLI (Command Line Options)** — 옵션명, 타입, 기본값, 설명, 필수 여부. 표로 작성하고 대표 실행 예시 명령을 1–2개 붙인다.

## Embedded Python script

- 파일명을 붙인 block 은 그 파일과 동일해야 한다. 발췌하거나 줄여서 싣지 않는다.
  파일명은 그 block 이 그 파일이라는 뜻이므로, 줄여 실으면 문서와 파일이 어긋나고
  독자는 문서에 없는 것을 파일에서 만난다.
    - module docstring은 제외한다
    - `if __name__ == '__main__':` block 은 제외한다.
       module 이 제공하는 것이 아니라 그것을 실행하는 방법이다.

## Before finishing

- [ ] 문서 제목이 H1, 장 제목이 번호 붙은 H2인가
- [ ] 6개 장 + 부록 2개가 순서대로 모두 존재하는가 (해당 없으면 `N/A — 이유`)
- [ ] Goal / Non-Goals / Background가 모두 채워졌는가
- [ ] Output의 모든 파일에 file count가 있고, tabular에는 shape가 있는가
- [ ] Result에 해석이, Analysis에 새 수치가 섞이지 않았는가
- [ ] `Updated` 타임스탬프와 `Rev.`를 갱신했는가

