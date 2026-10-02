# Monorepo Subfolder Export Convention — Publishing One Folder as a History-Free Snapshot
Rev. 0 | Created: 2026-10-02 | Updated: 2026-10-02 14:02 CDT

- [1. Purpose](#1-purpose)
- [2. Summary](#2-summary)
- [3. Taxonomy and its Hierarchy](#3-taxonomy-and-its-hierarchy)
  - [3.1 Placement](#31-placement)
- [4. Upload Command](#4-upload-command)
- [5. Application](#5-application)
- [References](#references)
- [Appendix A. Terminology](#appendix-a-terminology)

## 1. Purpose

- **Problem Statement**: Git 의 push 단위는 branch 이므로 monorepo 의 하위 folder 하나만 골라 다른 remote repository 로 보낼 수 없고, subtree 로 그 folder 를 떼어 내면 folder 의 전 history 가 전송 대상이 되어 큰 binary file 이 쌓인 folder 에서는 전송이 끝나지 않는다.
- **Goal**: 하위 folder 하나의 현재 내용만 다른 remote 의 `main` 으로 올려, 받는 쪽이 `clone` 한 번으로 그 folder 를 얻게 한다.
- **Non-Goal**: Remote 의 변경을 monorepo 로 되받는 양방향 동기화는 다루지 않는다.

## 2. Summary

내보낼 folder 의 tree 를 그대로 가리키는 parent 없는 commit 하나를 만들어 remote 의 `main` 에 force push 한다. 전송량은 그 folder 의 현재 file 크기이고 history 는 전송하지 않으므로, folder 에 쌓인 과거 판의 크기가 전송 시간에 들어오지 않는다. 받는 쪽은 remote 를 `clone` 하면 그 folder 의 내용이 repository root 에 그대로 놓인다.

대가는 두 가지다. Remote 의 `main` 이 실행마다 새 commit 하나로 바뀌므로 이전 commit hash 는 닿을 수 없게 되고, remote 에서 monorepo 로 되받는 길이 없다. 이전 판을 remote 에 남겨야 하면 section 4 의 chained snapshot 을 쓴다.

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

이 규약은 orphan snapshot 을 기본으로 쓰고, remote 에 이전 판을 남겨야 할 때만 chained snapshot 으로 바꾼다. 두 subtree 방법은 folder 의 전 history 를 전송하므로, 과거 판에 큰 binary file 이 쌓인 folder 에서는 전송량이 현재 file 크기의 몇 배가 된다.

## 4. Upload Command

Monorepo 의 root folder 에서 실행한다. `<DIR>` 은 내보낼 하위 folder 이고 `<REMOTE_URL>` 은 받는 remote repository 의 주소다.

```bash
# run from the monorepo root
git add <DIR>
git commit -m "<MESSAGE>"

# tree of the folder at HEAD, then an orphan commit that points to it
TREE=$(git rev-parse HEAD:<DIR>)
SNAP=$(git commit-tree "$TREE" -m "<MESSAGE>")

git push --force <REMOTE_URL> "$SNAP":refs/heads/main
```

`git commit-tree` 는 tree 하나와 parent 목록을 받아 commit 을 만든다 [[1](#ref-1)]. Parent 를 주지 않으면 그 commit 은 orphan commit 이 되어 history 가 없다. `git push` 의 refspec 은 source 자리에 임의의 commit 식별자를 받으므로 [[2](#ref-2)], branch 를 만들지 않고 그 commit 을 remote 의 `main` 으로 올린다.

이전 판을 remote 에 남기려면 remote 의 현재 `main` 을 parent 로 주고 force 없이 올린다.

```bash
# run from the monorepo root; keep the previous snapshot as the parent
git fetch <REMOTE_URL> main
TREE=$(git rev-parse HEAD:<DIR>)
SNAP=$(git commit-tree "$TREE" -p FETCH_HEAD -m "<MESSAGE>")

git push <REMOTE_URL> "$SNAP":refs/heads/main
```

`http.postBuffer` 는 기본값으로 둔다. 이 설정값보다 큰 전송은 chunked 로 나가고 작은 전송은 한 번의 POST 로 나가므로, 값을 전송량보다 크게 올리면 git 이 전부를 메모리에 모아 단일 POST 로 보내고 그 요청은 server 의 body 한도에 걸린다 [[3](#ref-3)].

## 5. Application

- **가정** — 내보낼 folder 가 monorepo 안의 plain file 로만 되어 있다. Gitlink 가 있으면 그 자리는 pointer 로 전송되어 받는 쪽에 내용이 오지 않는다.
- **설정값** — Push 대상은 `refs/heads/main` 하나이고, orphan snapshot 은 `--force` 를 쓰며, `http.postBuffer` 는 기본값으로 둔다.
- **깨지는 조건** — Remote 의 `main` 을 사람이 직접 commit 하면 그 commit 은 다음 실행의 force push 에서 사라진다. 받는 쪽이 이전에 받은 commit hash 로 재현해야 하는 경우에도 orphan snapshot 을 쓸 수 없다.
- **만나는 자리** — Monorepo 의 한 folder 만 다른 git server 로 배포하는 자리이며, 받는 쪽은 그 folder 를 읽기만 한다.

Remote 를 받는 쪽은 `clone` 한 뒤 필요하면 그 snapshot 의 commit hash 로 checkout 한다. Orphan snapshot 으로 올린 remote 에서 그 hash 는 다음 실행까지만 유효하므로, 받은 판을 오래 가리켜야 하면 chained snapshot 으로 올리거나 remote 에서 그 commit 에 tag 를 붙인다.

## References

<a id="ref-1"></a>
[1] Git. [git-commit-tree](https://git-scm.com/docs/git-commit-tree). Git Documentation.<br>
<a id="ref-2"></a>
[2] Git. [git-push](https://git-scm.com/docs/git-push). Git Documentation.<br>
<a id="ref-3"></a>
[3] Git. [git-config](https://git-scm.com/docs/git-config). Git Documentation.

---

## Appendix A. Terminology

- **Chained snapshot**: Remote 의 현재 commit 을 parent 로 두고 만든 snapshot commit 이다.
- **Commit hash**: Commit 하나를 가리키는 40자 식별자다.
- **Force push**: Remote 의 ref 를 기존 commit 과 이어지지 않는 commit 으로 바꿔 쓰는 push 다.
- **Gitlink**: 부모 repository 가 다른 repository 의 commit 을 가리키기 위해 저장하는 pointer 다.
- **Monorepo**: 여러 작업과 code 를 하나의 repository 에 모아 두는 구조다.
- **Orphan commit**: Parent 가 없는 commit 이며 그 commit 에서 닿는 history 가 없다.
- **Orphan snapshot**: Folder 의 tree 를 가리키는 orphan commit 으로 내보내는 방식이다.
- **Refspec**: `<src>:<dst>` 꼴로 적어 push 와 fetch 의 source 와 목적지를 지정하는 인자다.
- **Subtree**: 다른 repository 의 내용을 부모 repository 의 history 로 흡수해 하위 folder 에 두는 방식이다.
- **Tree**: Folder 하나의 내용을 담은 git object 이며, file 이름과 그 내용의 object 이름을 가진다.
