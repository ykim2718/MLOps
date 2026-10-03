# Monorepo Subfolder Export Convention — Publishing One Folder as a History-Free Snapshot
Rev. 5 | Created: 2026-10-02 | Updated: 2026-10-03 00:02 UTC

- [1. Purpose](#1-purpose)
- [2. Summary](#2-summary)
- [3. Taxonomy and its Hierarchy](#3-taxonomy-and-its-hierarchy)
  - [3.1 Placement](#31-placement)
- [4. Procedure](#4-procedure)
  - [4.1 Prerequisites](#41-prerequisites)
  - [4.2 Choose the Method](#42-choose-the-method)
  - [4.3 Run](#43-run)
  - [4.4 Verify](#44-verify)
  - [4.5 How the Commands Work](#45-how-the-commands-work)
- [5. Application](#5-application)
- [6. Further Work](#6-further-work)
- [References](#references)
- [Appendix A. Terminology](#appendix-a-terminology)
- [Appendix B. Reference Implementation](#appendix-b-reference-implementation)
  - [B.1 Orphan Snapshot](#b1-orphan-snapshot)
  - [B.2 Chained Snapshot](#b2-chained-snapshot)

## 1. Purpose

- **Problem Statement**: Git 의 push 단위는 branch 이므로 monorepo 의 하위 folder 하나만 골라 다른 remote repository 로 보낼 수 없고, subtree 로 그 folder 를 떼어 내면 folder 의 전 history 가 전송 대상이 되어 큰 binary file 이 쌓인 folder 에서는 전송이 끝나지 않는다.
- **Goal**: 하위 folder 하나의 현재 내용만 다른 remote 의 `main` 으로 올려 받는 쪽이 `clone` 한 번으로 그 folder 를 얻게 하고, 실무자가 이 문서만으로 방식을 골라 실행하고 결과를 확인할 수 있는 user guide 가 된다.
- **Non-Goal**: Remote 의 변경을 monorepo 로 되받는 양방향 동기화는 다루지 않는다.

## 2. Summary

방식은 remote 의 `main` 이 force push 를 받는지로 고른다. 받으면 orphan snapshot 을 쓰고, branch protection 으로 force push 가 막혀 있거나 이전 판을 remote 에 남겨야 하면 chained snapshot 을 쓴다. 두 방식 모두 script 하나를 Windows 의 Git Bash 나 Linux 의 shell 에서 실행하며, GitHub 와 Gitea 에 같은 방법으로 access token 을 써서 올린다.

Orphan snapshot 은 내보낼 folder 의 tree 를 그대로 가리키는 parent 없는 commit 하나를 만들어 remote 의 `main` 에 force push 한다. 전송량은 그 folder 의 현재 file 크기이고 history 는 전송하지 않으므로, folder 에 쌓인 과거 판의 크기가 전송 시간에 들어오지 않는다. 받는 쪽은 remote 를 `clone` 하면 그 folder 의 내용이 repository root 에 그대로 놓인다.

대가는 두 가지다. Remote 의 `main` 이 실행마다 새 commit 하나로 바뀌므로 이전 commit hash 는 닿을 수 없게 되고, remote 에서 monorepo 로 되받는 길이 없다. Chained snapshot 은 같은 tree 를 remote 의 현재 `main` 위에 이어 올리므로 force push 가 필요 없고 이전 commit hash 가 남는다.

## 3. Taxonomy and its Hierarchy

내보내기 방법은 보내는 단위, 보내는 history, 방향의 세 축으로 갈리며, 전송량은 history 축이 정한다.

```text
Unit        repository ----------------------------------- folder
History     full ------ rewritten full ------ snapshot only ------ none
Direction   two-way ------------------------------------- one-way

repository + full           + one-way : git push <REMOTE_URL> main
folder     + rewritten full + two-way : git subtree push, git subtree pull
folder     + rewritten full + one-way : git subtree split, then git push
folder     + snapshot only  + one-way : commit-tree with the previous snapshot as parent
folder     + none           + one-way : commit-tree with no parent   <- this convention
```

Fig 1. Export axes and the place of each method.

Unit 축은 remote 가 받는 범위이고, history 축은 그 범위의 과거 판을 얼마나 함께 보내는지이며, direction 축은 remote 의 변경을 되받는지이다. History 축을 한 단계 내려가면 전송량이 줄고 내려놓는 것이 생긴다. `full` 에서 `rewritten full` 로 내려가면 monorepo 의 다른 folder 를 내려놓고, `rewritten full` 에서 `snapshot only` 로 내려가면 folder 안의 commit 단위 이력을 내려놓으며, `snapshot only` 에서 `none` 으로 내려가면 remote 에 쌓인 이전 판을 내려놓는다. 되받기는 remote 가 받은 commit 이 monorepo 의 commit 과 대응할 때만 가능하므로, 양방향은 `rewritten full` 에서만 성립한다.

### 3.1 Placement

Table 1. Export methods by unit, history, and direction

| Method                                 | Unit            | History sent  | Direction | Transfer size            | When to use                                                   |
| :------------------------------------: | :-------------: | :-----------: | :-------: | :----------------------: | :-----------------------------------------------------------: |
| `git push <REMOTE_URL> main`           | Repository 전체 | 전량          | 단방향    | Repository 의 전 history | Monorepo 를 그 remote 에 그대로 두는 경우                     |
| `git subtree push`, `git subtree pull` | Folder 하나     | 재작성한 전량 | 양방향    | 그 folder 의 전 history  | 외부 upstream 이 있어 되받기가 필요한 경우                    |
| `git subtree split`, 그 뒤 `git push`  | Folder 하나     | 재작성한 전량 | 단방향    | 그 folder 의 전 history  | 내보내기만 하되 folder 의 commit 이력을 remote 에 남기는 경우 |
| Chained snapshot                       | Folder 하나     | Snapshot 만   | 단방향    | 그 folder 의 현재 file   | 내보낸 판을 remote 에 쌓는 경우                               |
| Orphan snapshot                        | Folder 하나     | 없음          | 단방향    | 그 folder 의 현재 file   | 현재 내용만 배포하는 경우                                     |

이 규약은 orphan snapshot 을 기본으로 쓰고, remote 에 이전 판을 남겨야 하거나 remote 의 `main` 이 force push 를 막을 때 chained snapshot 으로 바꾼다. 두 subtree 방법은 folder 의 전 history 를 전송하므로, 과거 판에 큰 binary file 이 쌓인 folder 에서는 전송량이 현재 file 크기의 몇 배가 된다.

## 4. Procedure

실무자는 4.1 의 준비를 한 번 마친 뒤, 실행할 때마다 4.3 과 4.4 를 따른다. 4.5 는 script 가 무엇을 하는지 설명한다.

### 4.1 Prerequisites

- **Git** — Windows 는 Git for Windows 를 설치하고 script 를 함께 설치되는 Git Bash 에서 실행한다. Linux 는 배포판의 `git` package 를 쓴다.
- **Remote repository** — GitHub 나 Gitea 에 받는 repository 를 미리 만든다. 비어 있어도 된다.
- **Access token** — 그 repository 에 쓰기 권한이 있는 access token 을 발급한다. Push 가 username 과 password 를 물으면 password 자리에 token 을 넣는다.
- **`REMOTE_URL`** — HTTPS 주소를 쓴다. GitHub 는 `https://github.com/<OWNER>/<REPO>.git`, Gitea 는 `https://<GITEA_HOST>/<OWNER>/<REPO>.git` 꼴이다.

Token 은 `REMOTE_URL` 에 넣지 않는다. 주소에 넣은 token 은 script file 과 shell history 에 그대로 남는다. Windows 의 Git for Windows 는 credential helper 가 token 을 저장해 다음 실행부터 묻지 않는다. Linux 에서 매번 묻지 않게 하려면 `git config --global credential.helper store` 를 쓰며, 이때 token 은 `~/.git-credentials` 에 평문으로 저장된다.

### 4.2 Choose the Method

Table 2. Method by remote condition

| Remote `main` condition                   | Method           | Script |
| :---------------------------------------: | :--------------: | :----: |
| Force push 허용, 현재 판만 필요           | Orphan snapshot  | B.1    |
| Branch protection 으로 force push 금지    | Chained snapshot | B.2    |
| 이전 판을 remote 에 남겨야 함             | Chained snapshot | B.2    |

Branch protection 이 직접 push 자체를 막으면 두 방식 모두 거부되므로, 그 account 의 push 를 허용하도록 protection 설정을 바꿔야 한다. 방식은 도중에 바꿀 수 있다. Orphan 에서 chained 로 바꾸면 B.2 가 remote 의 orphan commit 을 parent 로 두고 이어 올린다. Chained 에서 orphan 으로 바꾸면 B.1 의 force push 가 쌓인 snapshot 을 모두 닿을 수 없게 만든다.

### 4.3 Run

1. Table 2 로 고른 script 를 Appendix B 에서 복사해 monorepo 안에 file 로 저장한다 (예: `export-snapshot.sh`).
2. Script 머리의 `REMOTE_URL`, `DIR`, `MESSAGE` 세 변수를 고친다.
3. Linux 의 shell 이나 Windows 의 Git Bash 에서 `bash export-snapshot.sh` 로 실행한다. Script 가 monorepo 의 root 로 옮겨 가므로, 실행 위치는 monorepo 안이면 어디든 된다.
4. 첫 실행에서 username 과 password 를 물으면 password 자리에 access token 을 넣는다.

### 4.4 Verify

Script 는 마지막 줄에 올린 commit hash 를 출력한다. Remote 의 `main` 이 그 commit 을 가리키면 성공이다.

```bash
git ls-remote <REMOTE_URL> main    # Hash must match the commit printed by the script
```

받는 쪽에서 `git clone <REMOTE_URL>` 하면 `<DIR>` 의 내용이 repository root 에 놓이고, monorepo 의 다른 folder 는 없다.

### 4.5 How the Commands Work

두 script 의 핵심은 `git commit-tree` 와 `git push` 두 줄이다. `git rev-parse HEAD:<DIR>` 이 monorepo 의 마지막 commit 에서 그 folder 의 tree 를 꺼내고, `git commit-tree` 는 tree 하나와 parent 목록을 받아 commit 을 만든다 [[1](#ref-1)]. Parent 를 주지 않으면 그 commit 은 orphan commit 이 되어 history 가 없다. `git push` 의 refspec 은 source 자리에 임의의 commit 식별자를 받으므로 [[2](#ref-2)], branch 를 만들지 않고 그 commit 을 remote 의 `main` 으로 올린다. B.2 는 `git fetch` 로 받은 remote 의 현재 `main` 을 `-p FETCH_HEAD` 로 parent 에 두므로, push 가 fast-forward 가 되어 force 없이 올라간다.

`http.postBuffer` 는 기본값으로 둔다. 이 설정값보다 큰 전송은 chunked 로 나가고 작은 전송은 한 번의 POST 로 나가므로, 값을 전송량보다 크게 올리면 git 이 전부를 메모리에 모아 단일 POST 로 보내고 그 요청은 server 의 body 한도에 걸린다 [[3](#ref-3)].

## 5. Application

- **가정** — 내보낼 folder 가 monorepo 안의 plain file 로만 되어 있다. Gitlink 가 있으면 그 자리는 pointer 로 전송되어 받는 쪽에 내용이 오지 않는다.
- **설정값** — Push 대상은 `refs/heads/main` 하나이고, orphan snapshot 은 `--force` 를 쓰며, `http.postBuffer` 는 기본값으로 둔다.
- **깨지는 조건** — Remote 의 `main` 을 사람이 직접 commit 하면 그 commit 은 다음 실행의 force push 에서 사라진다. 받는 쪽이 이전에 받은 commit hash 로 재현해야 하는 경우에도 orphan snapshot 을 쓸 수 없다.
- **만나는 자리** — Monorepo 의 한 folder 만 다른 git server 로 배포하는 자리이며, 받는 쪽은 그 folder 를 읽기만 한다.

Remote 를 받는 쪽은 `clone` 한 뒤 필요하면 그 snapshot 의 commit hash 로 checkout 한다. Orphan snapshot 으로 올린 remote 에서 그 hash 는 다음 실행까지만 유효하므로, 받은 판을 오래 가리켜야 하면 chained snapshot 으로 올리거나 remote 에서 그 commit 에 tag 를 붙인다.

실행이 실패하면 Table 3 에서 증상으로 원인과 대처를 찾는다.

Table 3. Failures and fixes

| Symptom                                    | Cause                                               | Fix                                                   |
| :----------------------------------------: | :-------------------------------------------------: | :---------------------------------------------------: |
| Push 가 인증 오류로 끝남                   | Token 이 없거나 만료되었거나 쓰기 권한이 없음       | 쓰기 권한이 있는 token 을 다시 발급해 password 에 넣음 |
| B.1 의 force push 가 거부됨                | Remote 의 `main` 에 branch protection               | B.2 로 바꾸거나 그 branch 에 force push 를 허용       |
| B.2 의 push 가 non-fast-forward 로 거부됨  | Fetch 가 실패했거나 fetch 뒤 remote 의 `main` 이 바뀜 | Script 를 다시 실행                                   |
| Push 가 HTTP 413 으로 끝남                 | `http.postBuffer` 를 전송량보다 크게 올림           | `http.postBuffer` 를 기본값으로 둠                    |

## 6. Further Work

N/A — 이 문서의 두 방식과 절차에 남은 미확정 방향이 없다.

## References

<a id="ref-1"></a>
[1] Git. [git-commit-tree](https://git-scm.com/docs/git-commit-tree). Git Documentation.<br>
<a id="ref-2"></a>
[2] Git. [git-push](https://git-scm.com/docs/git-push). Git Documentation.<br>
<a id="ref-3"></a>
[3] Git. [git-config](https://git-scm.com/docs/git-config). Git Documentation.

---

## Appendix A. Terminology

- **Access token**: Password 대신 git server 에 인증하는 문자열이며, 발급할 때 권한과 만료일을 정한다.
- **Branch protection**: Git server 가 특정 branch 에 대한 push, force push, 삭제를 제한하는 설정이다.
- **Chained snapshot**: Remote 의 현재 commit 을 parent 로 두고 만든 snapshot commit 이다.
- **Commit hash**: Commit 하나를 가리키는 40자 식별자다.
- **Credential helper**: Git 이 인증 정보를 저장했다가 다음 push 에 다시 쓰게 하는 기능이다.
- **Fast-forward**: Remote 의 ref 를 그 ref 에서 이어지는 commit 으로 옮기는 갱신이며, 이어지지 않으면 non-fast-forward 로 거부된다.
- **FETCH_HEAD**: `git fetch` 가 마지막으로 받아 온 commit 을 가리키는 ref 다.
- **Force push**: Remote 의 ref 를 기존 commit 과 이어지지 않는 commit 으로 바꿔 쓰는 push 다.
- **Git Bash**: Git for Windows 와 함께 설치되는 bash shell 이며, Windows 에서 bash script 를 실행한다.
- **Gitlink**: 부모 repository 가 다른 repository 의 commit 을 가리키기 위해 저장하는 pointer 다.
- **Monorepo**: 여러 작업과 code 를 하나의 repository 에 모아 두는 구조다.
- **Orphan commit**: Parent 가 없는 commit 이며 그 commit 에서 닿는 history 가 없다.
- **Orphan snapshot**: Folder 의 tree 를 가리키는 orphan commit 으로 내보내는 방식이다.
- **Refspec**: `<src>:<dst>` 꼴로 적어 push 와 fetch 의 source 와 목적지를 지정하는 인자다.
- **Subtree**: 다른 repository 의 내용을 부모 repository 의 history 로 흡수해 하위 folder 에 두는 방식이다.
- **Tree**: Folder 하나의 내용을 담은 git object 이며, file 이름과 그 내용의 object 이름을 가진다.

## Appendix B. Reference Implementation

Section 4 의 두 방식을 각각 한 번의 실행으로 올리는 script 이며, 값을 바꾸는 자리는 두 script 모두 머리의 세 변수뿐이다.

### B.1 Orphan Snapshot

Remote 의 `main` 을 실행마다 parent 없는 snapshot commit 하나로 바꿔 쓴다.

```bash
#!/usr/bin/env bash
set -euo pipefail

REMOTE_URL='http://alice@192.0.2.10:3000/alice/Widget.git'
DIR='Falcon'
MESSAGE='snapshot'

cd "$(git rev-parse --show-toplevel)"

git add "$DIR"
git diff --cached --quiet || git commit -m "$MESSAGE"

TREE=$(git rev-parse "HEAD:$DIR")
SNAP=$(git commit-tree "$TREE" -m "$MESSAGE")
git -c http.postBuffer=1048576 push --force "$REMOTE_URL" "$SNAP:refs/heads/main"

echo "pushed $DIR to $REMOTE_URL as commit $SNAP on main"
```

`REMOTE_URL` 은 받는 remote repository 의 주소이고, `DIR` 은 내보낼 하위 folder 이며, `MESSAGE` 는 monorepo 의 commit 과 snapshot 에 함께 쓰는 message 다. `cd "$(git rev-parse --show-toplevel)"` 는 script 를 어느 folder 에서 실행하더라도 monorepo 의 root 로 옮긴다. `git diff --cached --quiet || git commit` 은 stage 한 변경이 없을 때 commit 을 건너뛰어, `set -e` 아래에서 실행이 중단되지 않게 한다.

### B.2 Chained Snapshot

B.1 을 고쳐, remote 의 현재 `main` 을 parent 로 두고 새 snapshot 을 그 위에 잇는다. Remote 의 `main` 에는 실행마다 snapshot commit 이 하나씩 쌓인다.

```bash
#!/usr/bin/env bash
set -euo pipefail

REMOTE_URL='http://alice@192.0.2.10:3000/alice/Widget.git'
DIR='Falcon'
MESSAGE='snapshot'

cd "$(git rev-parse --show-toplevel)"

git add "$DIR"
git diff --cached --quiet || git commit -m "$MESSAGE"

# chain onto the remote main; an empty remote has no main, so the first snapshot has no parent
PARENT=()
if git fetch "$REMOTE_URL" main; then PARENT=(-p FETCH_HEAD); fi

TREE=$(git rev-parse "HEAD:$DIR")
SNAP=$(git commit-tree "$TREE" "${PARENT[@]}" -m "$MESSAGE")
git -c http.postBuffer=1048576 push "$REMOTE_URL" "$SNAP:refs/heads/main"

echo "pushed $DIR to $REMOTE_URL as commit $SNAP on main"
```

B.1 에서 바뀐 곳은 세 군데다 (`git diff` 기준).

1. 추가 — `PARENT=()` 와 `if git fetch "$REMOTE_URL" main; then PARENT=(-p FETCH_HEAD); fi`: remote 의 현재 commit 을 `FETCH_HEAD` 로 받아 두고, 받지 못하면 `PARENT` 를 비운다. Remote 가 비어 있는 첫 실행에서는 이 경로로 parent 없는 snapshot 이 만들어진다.
2. 변경 — `git commit-tree "$TREE" -m …` → `git commit-tree "$TREE" "${PARENT[@]}" -m …`: snapshot 이 remote 의 그 commit 을 부모로 갖는다 [[1](#ref-1)].
3. 변경 — `push --force "$REMOTE_URL" …` → `push "$REMOTE_URL" …`: force 를 뺐으므로 fast-forward 가 아니면 push 가 거부된다.

Table 4. Orphan and chained snapshot scripts compared

| Item                           | B.1 Orphan snapshot              | B.2 Chained snapshot                       |
| :----------------------------: | :------------------------------: | :----------------------------------------: |
| Snapshot 의 parent             | 없음                             | Remote 의 현재 `main` (`FETCH_HEAD`)       |
| Commit 전 단계                 | 없음                             | `git fetch "$REMOTE_URL" main`             |
| Push                           | `--force`                        | Force 없음 (fast-forward)                  |
| Remote 의 `main` history       | 실행마다 commit 하나로 바뀜      | 실행마다 commit 이 하나씩 쌓임             |
| 이전 commit hash               | 다음 실행 뒤 닿을 수 없음        | 계속 닿을 수 있음                          |
| Remote 에 직접 한 commit       | 다음 실행에서 사라짐             | Parent 로 남지만 그 file 은 다음 판에 없음 |
| Fetch 실패 뒤 push             | 해당 없음                        | Parent 없는 commit 이 되어 거부됨          |

두 script 모두 tree 는 monorepo 의 `HEAD:$DIR` 에서 가져오므로, 각 snapshot 의 내용은 같고 차이는 parent 와 push 방식뿐이다. Table 4 의 마지막 행은 안전장치이다. 비어 있지 않은 remote 에서 fetch 가 실패하면 parent 없는 commit 은 remote 의 `main` 에서 이어지지 않아, force 없는 push 가 non-fast-forward 로 거부되고 remote 는 바뀌지 않는다. 변경이 없는 실행도 B.2 에서는 내용이 같은 snapshot commit 을 하나 더 쌓는다.
