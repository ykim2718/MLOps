---
name: md_rules
description: markdown document(.md, README, CHANGELOG)를 쓰거나 고치거나 검토하기 전에 반드시 로드할 것. 문서 검증, 서식 통일, 헤딩 구조, 표·코드블록 표기, 버전 표기에 적용된다.
---

# Documentation Conventions
rev. 10

## 1. Terminology
+ 정의되지 않은 용어는 사용하지 않는다.
+ 이미 사용되거나 정의된 용어를 재 사용하고, 새 용어를 만들지 않는다.
+ Occam’s razor을 적용하여 가장 단순한 용어와 표현을 선택한다.
+ 문서 전체에서 용어와 문맥과 맥락을 일관되게 유지한다.

## 2. Language
+ H1, H2, H3 제목, inline comment, text diagram, 표의 열 제목은 영어로 작성한다.
+ 기술 용어는 한글 음역이나 직역 대신 영어로 표기하고, 괄호 안 음역은 제거한다.
    - 나쁨: `도커(Docker) 컨테이너(container)를 빌드(build)한다`
    - 좋음: `docker container를 build한다`
+ 다음 용어는 코드 블록 주석을 포함하여 영어로 표기한다: console, catalog, endpoint, job, slot, architecture, worker, server, trigger, script.

## 3. Headings
+ H2 제목은 명사형으로 작성한다.
+ H2 제목에는 1., 2., ... 순서로 번호를 매긴다.
+ H3 제목에는 1.1, 1.2, ..., 2.1, ... 순서로 번호를 매긴다.
+ H4 제목에는 번호를 매기지 않는다.

## 4. Body Text
+ 본문은 명사형 종결 대신 완전한 문장으로 작성한다.

## 5. Formatting
+ 괄호는 앞뒤에 각각 한 칸을 띄우고 괄호 안은 공백 없이 붙이며, 한글과 영어에 공통으로 적용한다.
+ 가운뎃점 바로 뒤에 괄호가 오면 공백 없이 붙인다.
+ 표의 열 제목은 첫 글자를 대문자로 한다.

## 6. Document Independence
+ 모든 md 파일은 독립 문서로 작성하며, 다른 md 파일에 의존하지 않는다.
+ 특정 환경, 특히 작성자 컴퓨터에 대한 정보를 포함하지 않는다.

## 7. Content Scope
+ 해당 md 파일에 첨부되지 않은 코드는 언급하지 않으며, 다른 md 파일에 첨부된 코드도 언급하지 않는다.
+ 이미 기술한 내용을 부가가치 없이 반복하지 않는다.

## 8. Versioning
+ 문서 머리에 있는 H1 꼭지 다음에 본문 글씨체로 `rev. 0` 형식의 버전 표시를 추가하고, 문서를 수정할 때마다 버전을 올린다.
+ 버전 표시를 제외한 변경 이력 표현은 문서에서 삭제한다.

## 9. Code Block
+ Code block 내부의 inline comment는 모두 영어로 작성한다. 주석 기호는 해당 언어의 문법을 따른다 (예: Python `#`, JavaScript `//`, SQL `--`).
+ Code block의 첫 줄에 파일명, 실행 환경 또는 언어를 주석으로 명기한다. 실제 파일이 있으면 파일명 주석이 우선하고, 출력·로그처럼 실행 대상이 아닌 block만 예외로 한다.  JSON의 경우 실제 파일에서 주석이 있으면 동작하지 않지만, md에서만 예외로 첫 줄 주석을 //를 써서 허용한다.
+ 실제 파일이 있는 코드는 block 첫 줄에 주석으로 파일명을 표시한다. 프로젝트 루트 기준의 상대 경로로 적어 위치를 알 수 있게 한다.

```python
# src/utils/parser.py
def parse(text: str) -> dict:
    ...
```

+ 실제 파일이 없는 예시 코드는 파일명 대신 언어명을 주석으로 표시한다. 단, code fence에 이미 언어가 명시되어 있으면(예: ```python```) 첫 줄 주석은 생략해도 된다.

```python
# Python
result = [x * 2 for x in range(10)]
```

+ JSON 및 dict 형태의 데이터는 pretty print 한다. 들여쓰기는 2칸(space)을 기본으로 하고, key 순서는 원본을 유지한다.

```json
{
  "name": "example",
  "items": [1, 2, 3],
  "nested": {
    "enabled": true
  }
}
```

+ 언어를 특정할 수 없는 터미널 출력·로그·설정값 등은 fence에 언어를 지정하지 않거나 `text`/`bash`를 사용하고, 파일명·언어 주석은 붙이지 않는다.
+ 값을 치환해야 하는 자리표시자는 `<UPPER_CASE>` 형태로 통일하고, 실제 값과 혼동되지 않게 한다 (예: `Authorization: Bearer <API_KEY>`).

## 10. Table
+ 모든 table 에는 Table 1. title의 형식으로 제목을 붙이고, 문서에서 순서대로 번호를 매긴다.
+ Table의 열 제목은 영어로 한다.

## 11. Figure
+ 모든 figure 에는 Fig 1. title의 형식으로 제목을 붙이고, 문서에서 순서대로 번호를 매긴다.

## 12. Appendix
+ Appendix A. Terminology를 두어, 문서에서 사용한 미정의 용어에 대한 정의를 리스트 형식으로 정리한다. 리스트 꼭지에 용어를 두고, 정렬한다.
+ 본문에서 Appendix를 언급한 경우, 본문에 anchor link를 둔다.
