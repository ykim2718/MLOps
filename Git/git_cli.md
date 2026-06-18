# Git CLI (Command Line Interface)

자주 쓰는 git 명령을 **작업 영역**과 **역할**로 분류해 모았습니다. `<branch>` · `<remote>` · `<commit>` · `<file>` 은 실제 이름으로 바꿔 씁니다. 명령 문법은 PowerShell · bash 어느 셸에서나 같습니다.

## 1. The Four Standard Areas

git 은 파일이 아래 네 자리를 오가며 관리됩니다. 대부분의 명령은 **"어느 자리에서 어느 자리로 옮기느냐"** 로 이해하면 쉽습니다.

```text
[ 내 컴퓨터 (Local) ]                                           [ 서버 (Remote) ]
---------------------------------------------------------------+------------------
 1. Working Tree  ───>  2. Stage (Index)  ───>  3. Local Repo  ───>  4. Remote Repo
 (작업 디렉토리)           (스테이징 영역)         (로컬 저장소)            (원격 저장소)
       │                        │                     │                      │
       │     [git add]          │                     │                      │
       ├───────────────────────>│                     │                      │
       │                        │    [git commit]     │                      │
       │                        ├────────────────────>│                      │
       │                        │                     │     [git push]       │
       │                        │                     ├─────────────────────>│
       │                        │                     │                      │
       │<─────────────────────────────────────────────┴──────────────────────┤
       │                             [git clone / git pull]                  │
```

| Area | Meaning | Commands |
|------|---------|----------|
| Working Tree | 지금 편집 중인 실제 파일 | `restore`, `checkout`, `switch` |
| Stage (Index) | 다음 커밋에 담으려고 골라 둔 변경 | `add`, `restore --staged` |
| Local Repository | 커밋되어 이력에 굳은 상태 | `commit`, `reset`, `revert` |
| Remote Repository | 서버의 공유 저장소 | `push`, `fetch`, `pull` |

---

## 2. Repository Setup — init · remote

저장소를 새로 만들거나 원격을 잇는 단계입니다.

```bash
git init                                   # 현재 폴더를 새 git 저장소로 만든다.
git clone <url>                            # 원격 저장소를 통째로 내려받아 복제한다.

git remote -v                              # 연결된 원격 목록을 본다(fetch/push 주소).
git remote add origin <url>                # 'origin' 이라는 이름으로 원격을 잇는다.
git remote set-url origin <url>            # origin 의 주소를 바꾼다.
git remote remove origin                   # 원격 연결을 끊는다.
```

## 3. Stage & Commit — add · commit

작업한 변경을 골라 담고(stage) 이력으로 굳힙니다(commit).

```bash
git status                                 # 변경·스테이징 상태를 한눈에 본다.
git add <file>                             # 특정 파일을 stage 에 담는다.
git add .                                  # 현재 폴더의 모든 변경을 담는다.
git restore --staged <file>               # stage 에서 내린다(작업 내용은 그대로 둔다).

git commit -m "메시지"                     # 담아 둔 변경을 이력으로 굳힌다.
git commit -am "메시지"                    # 추적 중인 파일을 add + commit 한 번에(새 파일 제외).
git commit --amend -m "메시지"             # 직전 커밋을 고쳐 다시 쓴다(아직 push 전일 때).
```

## 4. Stash

커밋하기엔 이르지만 작업 중인 변경을 잠시 치워 두고, 깨끗한 상태에서 다른 일을 할 때 씁니다.

```bash
git stash                                  # 작업 중 변경을 보관함에 치우고 작업 트리를 비운다.
git stash -u                               # 추적 안 되는 새 파일까지 함께 치운다.
git stash list                             # 보관해 둔 목록을 본다(stash@{0}, stash@{1} ...).
git stash show -p stash@{0}                # 특정 보관본의 변경 내용을 본다.

git stash pop                              # 가장 최근 보관본을 꺼내 되살리고 목록에서 지운다.
git stash apply stash@{1}                  # 지정 보관본을 되살리되 목록에는 남겨 둔다.
git stash drop stash@{0}                   # 특정 보관본을 버린다.
git stash clear                            # 보관본을 모두 비운다(주의).
```

## 5. Branch & Switch — branch · switch · checkout

가지를 만들고 오가는 단계입니다. `switch` 는 가지 이동 전용으로 새로 나온 명령이고, `checkout` 은 이동·파일 복원을 겸하던 옛 명령입니다.

```bash
git branch                                 # 로컬 가지 목록을 본다(현재 가지에 *).
git branch -a                              # 원격 추적 가지까지 함께 본다.
git branch <branch>                        # 새 가지를 만든다(이동은 하지 않는다).
git branch -d <branch>                     # 병합 끝난 가지를 지운다(-D 는 강제).
git branch -m <old> <new>                  # 가지 이름을 바꾼다.

git switch <branch>                        # 가지로 이동한다(권장).
git switch -c <branch>                     # 새 가지를 만들면서 바로 이동한다.
git checkout <branch>                      # 가지 이동(옛 방식, switch 와 같은 동작).
```

## 6. Sync — fetch · pull · push

원격과 주고받는 단계입니다. `fetch` 는 받아만 오고, `pull` 은 받아서 합치며, `push` 는 올립니다.

```bash
git fetch                                  # 원격의 최신 이력을 받아만 온다(작업 트리는 건드리지 않는다).
git fetch --prune                          # 원격에서 사라진 가지 추적 정보를 함께 정리한다.

git pull                                   # fetch + merge — 받아서 현재 가지에 합친다.
git pull --rebase                          # fetch 후 merge 대신 rebase 로 합친다(이력이 깔끔).

git push                                   # 현재 가지를 원격에 올린다.
git push -u origin <branch>                # 처음 올리며 추적 관계를 맺는다(이후엔 git push 만).
git push --force-with-lease                # 다시 쓴 이력을 올린다(남의 작업은 덮지 않도록 안전장치).
```

## 7. Integrate — merge · rebase

두 가지의 이력을 하나로 합칩니다. `merge` 는 합친 자국(merge commit)을 남기고, `rebase` 는 커밋을 옮겨 붙여 한 줄로 폅니다.

```bash
git merge <branch>                         # 지정 가지를 현재 가지에 합친다(병합 커밋 생성).
git merge --abort                          # 충돌로 멈춘 병합을 되돌려 합치기 전으로 복귀한다.

git rebase <branch>                        # 현재 가지의 커밋을 <branch> 끝으로 옮겨 붙인다.
git rebase --continue                      # 충돌을 해결한 뒤 rebase 를 이어 간다.
git rebase --abort                         # rebase 를 멈추고 시작 전으로 되돌린다.
```

## 8. Undo — restore · checkout · reset · revert

되돌리기는 **"어느 영역을 되돌리느냐"** 로 갈립니다.

| Command | Target | History | Safety |
|---------|--------|---------|--------|
| `restore <file>` | Working Tree 의 파일 | 없음 | 변경분만 사라짐 |
| `restore --staged <file>` | Stage(언스테이징) | 없음 | 안전 |
| `reset` | 가지가 가리키는 커밋 위치 | **이력 이동** | `--hard` 는 위험 |
| `revert <commit>` | 특정 커밋의 효과 | 새 커밋으로 상쇄 | 안전(공유 가지 권장) |

```bash
# 작업 트리 되돌리기 — 편집한 내용을 마지막 커밋 상태로 돌린다.
git restore <file>                         # 한 파일을 되돌린다(checkout -- <file> 의 새 방식).
git restore .                              # 작업 트리의 모든 변경을 버린다(주의).

# 커밋 위치 옮기기 — HEAD 를 뒤로 물린다.
git reset --soft HEAD~1                    # 커밋만 취소, 변경은 stage 에 남긴다.
git reset --mixed HEAD~1                   # 커밋·stage 취소, 변경은 작업 트리에 남긴다(기본값).
git reset --hard HEAD~1                    # 커밋·stage·작업 트리까지 버린다(되돌리기 어려움, 주의).

# 커밋 상쇄 — 이미 공유한 이력을 안전하게 뒤집는다.
git revert <commit>                        # 그 커밋을 취소하는 새 커밋을 만든다(이력은 보존).
```

> **고르는 법** — 아직 안 올린 내 작업을 정리하면 `reset`, 이미 push 해 남들이 받은 커밋을 뒤집으면 `revert` 가 안전합니다. 단순히 편집만 버리려면 `restore` 면 충분합니다.

## 9. Windows — Long Paths

Windows 는 기본적으로 경로 길이를 260자로 제한합니다. `node_modules` 처럼 폴더가 깊게 겹쳐 경로가 길어지면 git 작업이 막히므로, git 이 확장 경로 API 를 쓰도록 켜 둡니다.

```bash
git config --global core.longpaths true    # 모든 저장소에서 긴 경로를 허용한다(한 번만).
git config --get core.longpaths            # 적용 여부를 확인한다(true 가 나오면 켜짐).
```

> `--global` 은 현재 사용자 전체에 적용합니다. 특정 저장소에만 켜려면 그 폴더에서 `--global` 을 빼고 실행합니다. Windows 자체의 제한도 함께 풀려면 관리자 권한으로 레지스트리의 `LongPathsEnabled` 를 1 로 둡니다.
