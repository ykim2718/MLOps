---
name: md_rules
description: markdown document(.md, README, CHANGELOG)를 쓰거나 고치거나 검토하기 전에 반드시 로드할 것. 문서 검증, 서식 통일, 헤딩 구조, 표·코드블록 표기, 버전 표기에 적용된다.
---

# Documentation Conventions
Rev. 41 | Created: 2026-8-1 | Updated: 2026-09-04 20:15 UTC

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
- 의역한 한글 기술 용어는 문서에서 최초 사용시에만, 괄호안에 영어 기술 용어를 병기한다.
    - 예시: 다중회귀표준화계수 (Standardized Regression Coefficient)
+ 다음 용어는 코드 블록 주석을 포함하여 영어로 표기한다: console, catalog, endpoint, job, slot, architecture, worker, server, trigger, script.

## 3. Headings

+ H2 제목은 명사형으로 작성한다.
+ H2 제목에는 1., 2., ... 순서로 번호를 매긴다.   References 꼭지는 예외로 section 14 를 따른다.
+ H3 제목에는 1.1, 1.2, ..., 2.1, ... 순서로 번호를 매긴다.
+ H4 제목에는 번호를 매기지 않는다.

## 4. Body Text

+ 줄글로 쓰는 문단은 완전한 문장으로 작성한다.
+ 목록 항목과 표의 칸은 명사형 단문으로 줄여 쓸 수 있다. 주어와 계사를 생략하고 한 항목에 한 가지만 담는다.
    - 나쁨: `The server resolves the last L observations of the key as of the cut-off, and it refuses the request when the window is too sparse to be used.`
    - 좋음: `Last L observations of the key, as of the cut-off. A window too sparse to use, refused.`
+ 한 문서 안에서 두 방식을 섞지 않는다. 목록과 표를 명사형으로 쓰기로 했으면 그 문서의 목록과 표는 모두 그렇게 쓴다.

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

+ 문서 머리에 있는 H1 꼭지 다음에 본문 글씨체로 `Rev. <N> | Created: <YYYY-MM-DD> | Updated: <YYYY-MM-DD HH:MM> <TIMEZONE>` 형식의 버전 표시를 추가하고, 문서를 수정할 때마다 버전을 올린다. Created는 최초 문서 제작일 (ISO 8601 형식), Updated는 문서 수정 시간을 기록한다. `<TIMEZONE>`은 실행 환경의 시간대이며 `date +%Z` 로 읽는다.  최초 문서 제작 시 버전은 0 이다.
+ 버전 표시를 제외한 변경 이력 표현은 문서에서 삭제한다.

## 9. Math

+ GitHub web page rendering을 위해서, 표·본문 안의 $...$ 수식에서 <, >를 HTML entity (&lt;, &gt;) 로 바꿔 MathJax에 넘기는 바람에 "Misplaced &" 오류가 나는 알려진 문제가 있기에,  수식 안의 부등호를 MathJax 매크로 \lt, \gt로 바꿀  것.
+ GitHub web page rendering을 위해서, 수식 안에 \text{} 로 code 식별자를 쓰지 않는다. GitHub이 \_ 의 backslash를 떼어내 맨 _ 를 text mode로 넘기는 바람에 "_ allowed only in math mode" 오류가 난다. underscore가 든 식별자는 수식 밖 code span으로 적고, 수식에는 값과 연산자만 남긴다.
    - 나쁨: $\mathrm{corr}(\text{max\_delta},\ \text{sigma\_st})$
    - 좋음: corr(`max_delta`, `sigma_st`)
+ 수식 안의 별표는 MathJax 매크로 \ast 로 쓴다. GitHub 은 markdown 을 먼저 읽으므로, 한 줄에 * 가 두 번 나오면 그 사이를 강조로 보아 두 별표를 지우고 `<em>` 으로 바꾼다. 그러면 수식에 `^{}` 같은 빈 첨자가 남아 "Extra close brace or missing open brace" 오류가 난다.
    - 나쁨: $\mathbf{t}^{*} = \mathbf{Q}^{+}\mathbf{y}^{*}$
    - 좋음: $\mathbf{t}^{\ast} = \mathbf{Q}^{+}\mathbf{y}^{\ast}$
+ 번호를 붙이는 display 수식은 식 끝에 `\hspace{19em}` 을 두고 그 뒤에 `(1)`, `(2)`, ... 를 적는다. 번호는 문서 전체에서 등장 순서대로 하나씩 매긴다.
    - 예시: `$$S_{\mathrm{total}}^2 = \sigma_w^2 + \sigma_b^2 \hspace{19em} (1)$$`
    - `\tag` 는 쓰지 않는다. GitHub 은 tag 를 표로 그리는데, 좁은 폭에서 번호가 왼쪽으로 가고 식이 여러 줄로 접힌다.
    - 번호를 식 폭에 맞춰 한 열로 정렬하려 하지 않는다. 폭을 재어 `\hspace` 를 식마다 다르게 주는 방법뿐인데, 렌더러의 폰트와 배율에 따라 어긋난다.

## 10. Code Block

+ Code block 내부의 inline comment는 모두 영어로 작성한다. 주석 기호는 해당 언어의 문법을 따른다 (예: Python `#`, JavaScript `//`, SQL `--`).
+ Code block의 첫 줄에 파일명, 실행 환경 또는 언어를 주석으로 명기한다. 실제 파일이 있으면 파일명 주석이 우선하고, 출력·로그처럼 실행 대상이 아닌 block만 예외로 한다.  JSON의 경우 실제 파일에서 주석이 있으면 동작하지 않지만, md에서만 예외로 첫 줄 주석을 //를 써서 허용한다.
+ 실제 파일이 있는 코드는 block 첫 줄에 주석으로 파일명을 표시한다. 프로젝트 루트 기준의 상대 경로로 적어 위치를 알 수 있게 한다.
+ 파일명을 붙인 block 은 그 파일과 동일해야 한다. 발췌하거나 줄여서 싣지 않는다. 파일명은 그 block 이 그 파일이라는 뜻이므로, 줄여 실으면 문서와 파일이 어긋나고 독자는 문서에 없는 것을 파일에서 만난다.
    - module docstring 은 제외한다. 여기에는 changelog 가 들어 있는데, section 8 이 변경 이력을 문서에서 빼라고 하므로 그대로 실으면 두 규칙이 충돌한다.
    - `if __name__ == '__main__':` block 은 제외한다. module 이 제공하는 것이 아니라 그것을 실행하는 방법이다.
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
+ Pseudocode block 은 그 규칙의 예외로, fence 는 `text` 로 두되 첫 줄에 `# Pseudocode` 를 적는다. 언어가 없어 fence 만으로는 실행할 수 있는 code 와 구분되지 않으므로, 독자가 그대로 실행해 보려 하는 것을 첫 줄에서 막는다.
+ 값을 치환해야 하는 자리표시자는 `<UPPER_CASE>` 형태로 통일하고, 실제 값과 혼동되지 않게 한다 (예: `Authorization: Bearer <API_KEY>`).

## 11. Table
+ 모든 table 에는 Table 1. title의 형식으로 제목을 붙이고, 문서에서 순서대로 번호를 매긴다.
+ 제목은 표 **위**에 둔다. 표는 첫 행부터 차례로 읽어 내려가므로, 무엇을 읽는 중인지 먼저 알려야 한다.
+ Table의 열 제목은 영어로 한다.
+ 표 아래에는 빈 줄을 한 줄 둔다. 표의 마지막 행 바로 다음 줄에 본문이 붙으면 GitHub 이 그 줄을 표의 행으로 이어 읽는다.

## 12. Figure

+ 모든 figure 에는 Fig 1. title의 형식으로 제목을 붙이고, 문서에서 순서대로 번호를 매긴다.
+ 제목은 그림 **아래**에 둔다. 그림은 한눈에 들어오므로, 제목은 본 것을 확인해 주는 자리에 있어야 한다.
+ 복수 panel figure 에는 전부 panel labels를 (a), (b), (c) ... 처럼 붙일 것. 단 Matrix chart는 예외로 panel labels를 붙이지 말 것.
+ Panel label 은 그 panel 의 chart **아래**, 축 label 보다 더 아래에 둔다. Chart 위의 title 자리에 두지 않는다. Figure 제목을 그림 아래에 두는 것과 같은 이유이며, 위에 두면 그림보다 글이 먼저 읽힌다.
    - Label 은 그 panel 의 가로 중앙에 맞추고, 한 figure 안의 label 은 모두 같은 높이에 둔다. Panel 마다 chart 의 아래 끝이 다르므로 chart 기준으로 두면 높이가 어긋난다.
    - Label 이 들어갈 여백을 그림 아래에 미리 확보하여, 저장할 때 잘려 나가지 않게 한다.
+ Figure image는 CLI로 특정 folder를 지정하지 않는 경우에, md 파일과 같은 위치의 `<md file stem>_fig` folder에 두고, 본문에서는 그 folder 기준 상대 경로로 참조한다.
    - `foo.md` 의 image는 `foo_fig/` 아래에 두고 `![Fig 1](foo_fig/fig1.png)` 로 쓴다.
    - 절대 경로나 외부 URL로 참조하지 않는다. 저장소를 clone하거나 folder를 옮겨도 그림이 그대로 보여야 한다.
+ 문서에서 그림이 차지할 폭을 정해야 하면 `<img>` 로 참조하고 `width` 와 `max-width` 를 함께 준다. Markdown image 문법에는 크기 인자가 없어, image 가 본문 폭보다 넓으면 언제나 본문 폭까지 늘어난다.
    - `<img src="foo_fig/fig1.png" width="800" style="max-width: 100%;" alt="Fig 1">` 로 쓴다.
    - `width` 는 기본 렌더 폭이고, `max-width` 는 화면이 그보다 좁을 때 가로 scroll 대신 그림이 줄어들게 한다. GitHub 은 자체 stylesheet 로 같은 일을 하지만 다른 renderer 를 위해 함께 적는다.
    - 그림을 만든 code 의 figure 크기를 줄여서 렌더 폭을 줄이려 하지 않는다. 종횡비가 같으면 image 가 본문보다 넓은 한 렌더 크기는 그대로이다.

## 13. Lists

- Use `-` as the bullet marker throughout. Do not mix in `*` or `+`.
  The References section is the one exception; see section 14.
- Indent nested items by two spaces per level.
- Do not nest more than two levels deep. If a third level seems necessary,
  split the content into a separate section instead.

## 14. References

+ 출처를 밝히는 꼭지는 `## References` 로 두고, 다른 H2 제목과 달리 번호를 매기지 않는다. 본문의 논지를 잇는 절이 아니라 목록이므로 번호 체계에서 뺀다.
+ 위치는 본문 마지막 꼭지 뒤, Appendix 경계를 표시하는 `---` 앞이다.
+ 항목의 bullet 은 `-` 대신 `[1]`, `[2]`, ... 를 쓴다. 본문에서 인용할 때 쓰는 번호와 목록의 표시가 같아야 서로 찾아진다.
+ 항목 사이에는 빈 줄을 두지 않고, 앞 항목의 끝에 `<br>` 을 둔다. `[N]` 은 markdown list 가 아니라 문단이므로, 빈 줄을 두면 항목마다 `<p>` 가 되어 문단 사이 여백이 생기고 목록이 아니라 따로 떨어진 글 여러 개로 읽힌다. `<br>` 은 한 문단 안에서 줄만 바꾸므로 항목이 한 덩어리로 붙는다.
    - 나쁨: `[1] ...` 다음에 빈 줄, 그다음 `<a id="ref-2"></a>`
    - 좋음: `[1] ...<br>` 다음 줄에 바로 `<a id="ref-2"></a>`
+ 마지막 항목에는 `<br>` 을 붙이지 않는다. 뒤에 이어질 항목이 없으므로 빈 줄만 남는다.
+ 항목 앞에 `<a id="ref-N"></a>` 를 두어, 본문에서 그 항목에 바로 닿게 한다.
+ 본문의 인용은 `[[1](#ref-1)]` 로 적어 화면에 `[1]` 로 보이게 하고, link 는 숫자에만 건다. 대괄호는 항목을 가리키는 표시일 뿐 누를 것이 아니므로 link 밖에 둔다. `[1](#ref-1)` 로 적으면 대괄호가 link 문법에 먹혀 본문에 숫자만 남고, 목록의 `[1]` 과 표시가 달라져 서로 찾아지지 않는다.
+ 서지 사항의 제목은 DOI 로 연결한다. DOI 가 없는 간행물은 발행처의 공식 page 와 ISBN 을 적는다.
+ URL 은 제목에 건 link 의 목적지로만 두고, 주소 자체를 항목에 드러내지 않는다. 주소를 link 의 글자로 삼으면 서지 사항보다 긴 문자열이 항목에 들어가 화면에서 제 줄로 넘어가고, 읽는 이가 얻는 것은 이미 제목이 가리키고 있는 곳뿐이다.
    - 나쁨: `[1] Kane, V. E. (1986). Process Capability Indices. *Journal of Quality Technology*, 18(1), 41–52.` 다음 줄에 `[https://doi.org/10.1080/00224065.1986.11978984](https://doi.org/10.1080/00224065.1986.11978984)`
    - 좋음: `[1] Kane, V. E. (1986). [Process Capability Indices](https://doi.org/10.1080/00224065.1986.11978984). *Journal of Quality Technology*, 18(1), 41–52.`
+ Reference 의 외부 link 는 반드시 access 하여, 웹page 의 존재와 문서와의 연관성을 확인하여 등록한다.

## 15. Appendix

- Appendix A. Terminology를 두어, 문서에서 사용한 미정의 용어에 대한 정의를 리스트 형식으로 정리한다. 리스트 꼭지에 용어를 두고, 정렬한다.
- 용어는 `- **term**: 정의` 처럼 굵은 글씨로 쓴다. 목록을 훑을 때 눈이 용어만 따라가게 하려는 것이며, 정의는 보통 글씨로 둔다.
- 본문에서 Appendix를 언급한 경우, 본문에 anchor link를 둔다.
- 본문과 첫 Appendix 사이에 `---` 을 한 줄 두어 경계를 표시한다. Appendix 사이에는 두지 않는다.
    + `---` 의 위아래에 빈 줄을 둔다. 위에 빈 줄이 없으면 앞 줄이 setext heading으로 해석된다.
    + 빈 줄을 여러 개 넣는 방법은 쓰지 않는다. GitHub이 연속된 빈 줄을 하나로 합치므로 렌더링에서는 여백이 생기지 않는다.


## 16. Git

+ 작업 결과는 최종적으로 **main** branch 에 남는다. 작업용 branch 에 push 한 것으로 끝내지 말고, main 에 반영되는 데까지 책임진다.
- 저장소에 main 이 없으면 (첫 commit 등) main 을 만들어 default branch 로 둔다.
- 실행 환경이 특정 branch 를 지정한 경우 그 지정이 이 규칙보다 우선한다. 지정된 branch 에 push 한 뒤 main 반영 방법 (PR 열기 또는 fast-forward) 을 제시하고 승인을 받는다. 승인 없이 main 으로 직접 push 하지 않는다.
- 작업을 마칠 때 어느 branch 에 무엇이 올라갔는지, main 과 무엇이 다른지 항상 보고한다. push 했다는 말만으로는 main 에 있다는 뜻이 아니다.

## 17. Review (required — do not finish the task before completing this step)

+ 검수 범위는 변경의 성격으로 정한다.
    - 기계적 변경은 검수를 생략하고, 바꾼 줄과 그것을 가리키는 상호참조만 확인한다.
      Rev. 번호와 Updated 시간 갱신, 식별자·파일명·제목의 이름 바꾸기,
      제목 번호와 표 번호 재정렬, 그에 따른 상호참조 갱신이 여기에 속한다.
    - 내용 변경은 아래 절차대로 전량 검수한다. 문장·표·수식·코드를 새로 쓰거나 고친 경우,
      절을 추가·삭제·이동한 경우, 문서를 나누거나 합친 경우가 여기에 속한다.
    - 한 작업에 둘이 섞이면 내용 변경으로 본다.

+ 작성한 .md 파일을 **다시 읽는다** (Read 도구로 실제 파일을 연다).
     기억에 의존한 검토는 하지 않는다.

+ 아래 항목별로 위반 후보를 **먼저 목록으로 출력**한다. 수정은 그 다음이다.
     각 항목은 `[유형] 위치(섹션/줄) — 근거` 형식으로 쓴다.

     - 중복: 동일한 논지·정의·예시가 2회 이상 등장
     - 반복: 같은 문장 구조/접속 표현이 3연속 이상
     - 오류: 앞 섹션과 모순되는 서술, 근거 없이 등장한 수치·고유명사, 정의 없이 처음 등장한 약어, 깨진 링크·잘못된 코드 식별자
     - 어색: 한 문장 안에 주어가 바뀌거나 60자 이상 수식이 겹친 문장
     - 비맥락: 해당 섹션 제목이 예고하지 않은 내용, 문서 목적과 무관한 배경 설명

+ 목록의 각 항목에 대해 수정하거나, 수정하지 않는 이유를 한 줄로 남긴다.
     **위반이 없으면 "위반 없음"으로 끝낸다.** 실적을 만들기 위한 문장 손질은 하지 않는다.

+ 최종 보고: 발견 N건 / 수정 N건 / 보류 N건.