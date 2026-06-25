# Git CLI (Command Line Interface)

자주 쓰는 git 명령을 **작업 영역**과 **역할**로 분류했습니다. `<branch>` · `<remote>` · `<commit>` · `<file>` 은 실제 이름으로 바꿔 씁니다. 문법은 PowerShell · bash 공통입니다.

## 1. The Four Standard Areas

파일은 아래 네 자리를 오갑니다. 대부분의 명령은 **어느 자리에서 어느 자리로 옮기는가**로 이해하면 쉽습니다.

```text
[ Local ]                                           [ Remote ]
---------------------------------------------------------------+------------------
 1. Working Tree  ───>  2. Stage (Index)  ───>  3. Local Repo  ───>  4. Remote Repo
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
| Working Tree | 편집 중인 실제 파일 | `restore`, `checkout`, `switch` |
| Stage (Index) | 다음 커밋에 담아 둔 변경 | `add`, `restore --staged` |
| Local Repository | 커밋되어 이력에 굳은 상태 | `commit`, `reset`, `revert` |
| Remote Repository | 서버의 공유 저장소 | `push`, `fetch`, `pull` |

---

## 2. Repository Setup — init · remote

저장소를 새로 만들고 원격을 잇습니다.

```bash
git init                                   # 현재 폴더를 새 git 저장소로 만든다.
git clone <url>                            # 원격 저장소를 통째로 내려받아 복제한다.

git remote -v                              # 연결된 원격 목록을 본다(fetch/push 주소).
git remote add origin <url>                # 'origin' 이라는 이름으로 원격을 잇는다.
git remote set-url origin <url>            # origin 의 주소를 바꾼다.
git remote remove origin                   # 원격 연결을 끊는다.
```

## 3. Stage & Commit — add · commit

변경을 골라 담고 (stage) 이력으로 굳힙니다 (commit).

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

커밋하기 이른 변경을 잠시 치워 두고, 깨끗한 상태에서 다른 일을 합니다.

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

가지를 만들고 오갑니다. `switch` 는 가지 이동 전용, `checkout` 은 이동·복원을 겸하던 옛 명령입니다.

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

원격과 주고받습니다. `fetch` 는 받기만, `pull` 은 받아 합치기, `push` 는 올리기입니다.

```bash
git fetch                                  # 원격의 최신 이력을 받아만 온다(작업 트리는 건드리지 않는다).
git fetch --prune                          # 원격에서 사라진 가지 추적 정보를 함께 정리한다.

git pull                                   # fetch + merge — 받아서 현재 가지에 합친다.
git pull --rebase                          # fetch 후 merge 대신 rebase 로 합친다(이력이 깔끔).

git push                                   # 현재 가지를 원격에 올린다.
git push -u origin <branch>                # 처음 올리며 추적 관계를 맺는다(이후엔 git push 만).
git push --force-with-lease                # 다시 쓴 이력을 올린다(남의 작업은 덮지 않도록 안전장치).
```

방향에 따라 **바뀌는 대상**이 다릅니다.

- 로컬 → 원격: `git push` (원격의 상태가 바뀜).
- 원격 → 로컬: `git fetch` 또는 `git pull` (로컬의 원격 추적 참조 상태가 바뀜).

## 7. Integrate — merge · rebase

두 가지의 이력을 합칩니다. `merge` 는 합친 자국 (merge commit) 을 남기고, `rebase` 는 커밋을 옮겨 붙여 한 줄로 폅니다.

```bash
git merge <branch>                         # 지정 가지를 현재 가지에 합친다(병합 커밋 생성).
git merge --abort                          # 충돌로 멈춘 병합을 되돌려 합치기 전으로 복귀한다.

git rebase <branch>                        # 현재 가지의 커밋을 <branch> 끝으로 옮겨 붙인다.
git rebase --continue                      # 충돌을 해결한 뒤 rebase 를 이어 간다.
git rebase --abort                         # rebase 를 멈추고 시작 전으로 되돌린다.
```

## 8. Undo — restore · checkout · reset · revert

되돌리기는 **어느 영역을 되돌리느냐**로 갈립니다.

| Command | Target | State | Working<br>Tree | Commit<br>History |
|---------|--------|-------|--------------|---------|
| `restore <file>` | Working Tree 의 파일 | modified → committed (변경 버림) | 복원 | 없음 |
| `restore --staged <file>` | Stage (언스테이징) | staged → modified | 유지 | 없음 |
| `checkout <commit>` | HEAD 위치 (작업 트리째) | committed 기준으로 맞춤 | 교체 | HEAD 이동 (이력 보존) |
| `reset --soft` | 커밋 위치 | committed → staged | 유지 | **이력 이동** |
| `reset --mixed` | 커밋·Stage | committed → modified | 유지 | **이력 이동** |
| `reset --hard` | 커밋·Stage·Working Tree | committed → clean (버림) | 삭제 | **이력 이동** |
| `revert <commit>` | 특정 커밋의 효과 | 새 committed 추가 | 갱신 | 새 커밋으로 상쇄 |

```bash
# 작업 트리 되돌리기 — 편집한 내용을 마지막 커밋 상태로 돌린다.
git restore <file>                         # 한 파일을 되돌린다(checkout -- <file> 의 새 방식).
git restore .                              # 작업 트리의 모든 변경을 버린다(주의).

# HEAD 옮기기 — 작업 트리째 다른 커밋 상태로 맞춘다.
git checkout <commit>                      # 그 커밋으로 작업 트리를 맞춘다(HEAD 가 detached 된다).
git checkout -- <file>                     # 한 파일의 변경만 버린다(restore <file> 의 옛 방식).

# 커밋 위치 옮기기 — HEAD 를 뒤로 물린다.
git reset --soft HEAD~1                    # 커밋만 취소, 변경은 stage 에 남긴다.
git reset --mixed HEAD~1                   # 커밋·stage 취소, 변경은 작업 트리에 남긴다(기본값).
git reset --hard HEAD~1                    # 커밋·stage·작업 트리까지 버린다(되돌리기 어려움, 주의).

# 커밋 상쇄 — 이미 공유한 이력을 안전하게 뒤집는다.
git revert <commit>                        # 그 커밋을 취소하는 새 커밋을 만든다(이력은 보존).
```

> **고르는 법** — 안 올린 작업 정리는 `reset`, 이미 push 한 커밋 뒤집기는 `revert`, 편집만 버리기는 `restore`.

## 9. Extraction — Worktree · Archive

`checkout` 이 local state 와 working tree 를 바꾸는 **undo (되돌리기)** 라면, `worktree` 와 `archive` 는 working tree 만 바꾸는 **extraction (재현)** 입니다.

### Worktree

  한 저장소에 작업 트리를 여러 개 두어, 가지마다 별도 폴더에서 동시에 작업합니다. 각 폴더가 같은 `.git` 이력을 공유합니다.

  ```bash
  git worktree list                          # 딸려 있는 작업 트리를 모두 본다(경로·가지·커밋).
  git worktree add ../feat <branch>          # <branch> 를 ../feat 폴더에 새 작업 트리로 펼친다.
  git worktree add -b <branch> ../feat       # 새 가지를 만들면서 ../feat 에 펼친다.
  git worktree add --detach ../tmp <commit>  # 특정 커밋을 가지 없이(detached) 꺼내 본다.

  git worktree remove ../feat                # 작업 트리를 걷어 낸다(변경이 남아 있으면 막힌다).
  git worktree prune                         # 폴더를 손으로 지운 뒤 남은 등록 정보를 정리한다.
  ```

  > 같은 가지는 두 작업 트리에 동시에 펼칠 수 없습니다. 한 커밋만 잠깐 볼 때는 `--detach` 가 깔끔합니다.

### Archive

  가지나 커밋의 한 시점을 `.git` 이력 없이 압축 파일로 내보냅니다. 소스만 묶어 배포할 때 씁니다.

  ```bash
  git archive -o src.zip HEAD                  # 현재 시점을 zip 으로 묶는다(.git 은 빠진다).
  git archive --format=tar.gz -o src.tgz HEAD  # tar.gz 형식으로 묶는다.
  git archive -o src.zip <branch>              # 특정 가지의 시점을 묶는다.
  git archive -o sub.zip HEAD:<path>           # 하위 폴더만 골라 묶는다.
  git archive --prefix=app/ -o src.zip HEAD    # 압축 안 파일을 app/ 아래로 모아 담는다.
  ```

  > `git archive` 는 추적 중인 파일만 담습니다. `.gitignore` 제외 파일과 `.git` 폴더는 빠지므로, 배포용 스냅샷에 알맞습니다.

## 10. Windows — Long Paths

Windows 는 경로를 260자로 제한합니다. 폴더가 깊어 경로가 길면 git 작업이 막히므로, 확장 경로 API 를 켭니다.

```bash
git config --global core.longpaths true    # 모든 저장소에서 긴 경로를 허용한다(한 번만).
git config --get core.longpaths            # 적용 여부를 확인한다(true 가 나오면 켜짐).
```

> `--global` 은 현재 사용자 전체에 적용합니다. 한 저장소만 켜려면 그 폴더에서 `--global` 을 뺍니다. Windows 자체 제한도 풀려면 관리자 권한으로 레지스트리의 `LongPathsEnabled` 를 1 로 둡니다.

## Appendix A. Terminology

- **.git** — 저장소의 모든 것이 담긴 숨김 폴더. 커밋·가지·이력·설정이 여기에 들어 있어, 이 폴더가 곧 local repository 입니다. `git init` 으로 만들어지며 (또는 `git clone` 이 받아 옴), 지우면 이력이 사라지고 보통 폴더로 돌아갑니다.
- **.gitattributes** — 경로별 취급 규칙을 적는 파일. 줄바꿈 정규화 (`text=auto`), `diff`·`merge` 방식, `linguist`·LFS 지정 등을 경로 패턴에 걸어 둡니다.
- **.gitignore** — 추적하지 않을 파일을 패턴으로 적는 파일. 빌드 산출물·캐시·비밀키 등을 적어 두면 `git status` 와 `add` 에서 빠집니다 (이미 추적 중인 파일에는 적용되지 않음).
- **.gitmodules** — submodule 의 경로와 원격 주소를 적어 두는 파일. `git submodule add` 로 채워지며, 다른 저장소를 하위 폴더로 끌어와 고정된 커밋에 묶어 둡니다.
- **branch** — 커밋을 가리키는 움직이는 이름표. 본줄을 건드리지 않고 갈라져 작업하다 나중에 합칩니다.
- **detached HEAD** — HEAD 가 가지가 아닌 특정 커밋을 직접 가리키는 상태. 여기서 커밋하면 어느 가지에도 매이지 않아, 가지를 새로 만들지 않으면 잃기 쉽습니다.
- **HEAD** — branch and commit history pointer. 보통 현재 가지의 맨 끝 커밋을 가리키며, 가지가 아닌 특정 커밋을 직접 가리키면 detached 상태입니다.
- **local repository** — 내 컴퓨터의 저장소. 커밋·가지·이력이 `.git` 폴더에 담겨, 인터넷 없이도 모든 작업이 됩니다.
- **main** — 기본 가지의 요즘 표준 이름. 예전 `master` 를 대체한 본줄입니다.
- **master** — 기본 가지의 옛 표준 이름. 동작은 `main` 과 같고, 오래된 저장소에 남아 있습니다.
- **origin** — `git clone` 시 자동으로 붙는 원격의 기본 이름. 주소 대신 쓰는 별칭입니다.
- **remote repository** — 서버의 공유 저장소 (GitHub 등). 여럿이 `push`·`pull` 로 이력을 주고받는 중심점입니다.
- **remote-tracking branches** — 원격 가지를 내 쪽에 비춰 둔 읽기용 이름 (`origin/main` 등). `fetch` 때 갱신됩니다.
- **repository** — 프로젝트의 모든 파일과 이력을 담는 저장 단위. 로컬·원격 양쪽에 존재합니다.
- **state** — 변경 파일이 거치는 단계. **modified** 는 working tree 에서 고쳤지만 안 담은 상태, **staged** 는 `add` 로 다음 커밋에 담은 상태, **committed** 는 `commit` 으로 이력에 굳은 상태입니다.
- **working tree** — 편집 중인 실제 파일이 펼쳐진 작업 폴더. 고친 내용을 `add` 로 stage 에 담고 `commit` 으로 굳힙니다.
