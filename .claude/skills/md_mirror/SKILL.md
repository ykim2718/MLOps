---
name: md_mirror
description: 영문판 <file-name>.md 와 한글판 <file-name>-ko.md 가 짝을 이루는 mirror 문서를 만들거나 고치기 전에 반드시 로드할 것. 한쪽만 고치는 것을 막고, 두 판이 같아야 하는 요소와 그 검증 절차를 정한다.
---

# Mirror Document Convention
Rev. 0 | Created: 2026-09-05 | Updated: 2026-09-05 21:36 CDT

## 1. Pair

+ 영문판은 `<stem>.md`, 한글판은 `<stem>-ko.md` 이며 같은 folder 에 둔다.
+ 한글판의 H1 은 영문판 H1 뒤에 ` (Korean)` 을 붙인 것이고, 그 밖의 제목은 두 판이 같다.
+ 번역하는 것은 산문뿐이다. 나머지 요소는 section 3 이 정한다.

## 2. Simultaneous Edit

+ 짝이 있는 `.md` 를 고칠 때는 같은 turn 안에서 두 파일을 모두 고친다. 한쪽만 고치고 끝내지 않는다.
+ 한쪽에만 해당하는 수정은 없다. 오타, 용어 통일, 번역투 손질도 대응하는 자리를 함께 본다.
+ 꼭지를 옮기거나 지우거나 더하면 두 판에서 같은 자리에 같은 일을 한다. 번호 재배열도 같이 한다.
+ Rev 번호는 각 판이 따로 센다. `Updated` 시각은 두 판을 같게 둔다.
+ 짝 가운데 하나만 고쳐 달라는 요청을 받으면, 그렇게 하면 두 판이 어긋난다는 것을 알리고 확인을 받는다.

## 3. What Must Match

산문을 뺀 아래 요소는 두 판이 같아야 한다.

+ 제목. H1 의 ` (Korean)` 표시만 예외이다.
+ `$$...$$` display 수식과 그 번호.
+ Table 과 Fig 의 번호, 그리고 표의 모든 행의 열 수.
+ Fenced code block. 언어 표시를 포함하여 byte 단위로 같아야 하며, code 안의 주석도 번역하지 않는다.
+ 본문 인용 `[[N](#ref-N)]` 의 순서와 `<a id="ref-N"></a>` anchor, 그리고 References 항목의 서지 사항.
+ Appendix A 의 용어 목록과 그 정렬.
+ 꼭지마다의 목록 항목 수.
+ 모든 link 의 목적지와 image 의 경로.
+ Appendix 경계를 표시하는 `---` 의 개수.

## 4. Verification

+ 고친 뒤 저장소의 `tools/check_mirror.py` 를 돌린다. exit 0 이 나오기 전에는 commit 하지 않는다.

```bash
python3 tools/check_mirror.py <folder-or-file>   # 짝 하나 또는 folder
python3 tools/check_mirror.py .                  # 저장소 전체
```

+ 그 script 가 없는 저장소에서는 section 3 의 항목을 손으로 대조하고, 무엇을 대조했는지 보고에 적는다.
+ 검증 없이 "적용했습니다" 라고 말하지 않는다. 돌리지 못했으면 돌리지 못했다고 적는다.

## 5. New Mirror

+ 새 한글판은 영문판을 그대로 옮겨 놓고 산문만 바꾼다. 처음부터 다시 쓰지 않는다.
+ 한글판의 Rev 는 0 에서 시작하고 `Created` 는 만든 날이다. 영문판의 Rev 를 따라가지 않는다.
+ 만든 직후 section 4 의 검증을 돌린다.
+ folder 의 README 나 상위 목록이 그 문서를 가리키고 있으면 한글판 link 를 함께 등록한다.

---

## Appendix A. Terminology

- **mirror**: 같은 내용을 두 언어로 담아 구조가 같은 문서 한 쌍.
- **structural parity**: 산문을 뺀 모든 요소가 두 판에서 같은 상태.
