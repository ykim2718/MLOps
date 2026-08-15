> ⚠️ **This is an auto-synced copy.** Do not edit here.

# Git CLI (Command Line Interface)

Rev. 106 | Created: 2026-06-17 | Updated: 2026-08-14 21:32 CDT

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

## 2. Repository Lifecycle

저장소도 만들어져 원격에 오르거나, 복제돼 내려오고, 운영되다 지워지는 한살이를 거칩니다. 저장소 단위 명령을 단계로 모았습니다.

```text
Creation → Publish (→ remote) → Track (← remote) → Management → Delete
```

### Creation

빈 폴더를 새 저장소로 만들어 `.git` 을 깔아 둡니다.

```bash
git init                                   # turn the current folder into a new git repo (.git created).
git init -b main                           # start with the default branch named main.
```

### Publish — upload to remote

로컬 저장소를 원격에 이어 처음 올립니다.

```bash
git remote add origin <url>                # link a remote under the name 'origin'.
git push -u origin main                    # first upload — set the tracking link (later just git push).
```

### Track — download from remote

원격 저장소를 통째로 받아 로컬에 복제합니다.

```bash
git clone <url>                            # copy a remote repo down in full.
git clone -b <branch> <url>                # clone a specific branch.
git clone --depth 1 <url>                  # shallow clone, recent history only (fast).
```

### Management

원격 연결과 설정을 살피고 손봅니다.

```bash
git remote -v                              # list linked remotes (fetch/push URLs).
git remote set-url origin <url>            # change origin's URL.
git remote rename <old> <new>              # rename a remote.
git config --list                          # show the active config (user.name, etc.).
```

### Delete

저장소나 원격 연결을 치웁니다.

```bash
git remote remove origin                   # drop only the remote link (local repo stays).
rm -rf .git                                # delete .git to revert to a plain folder (history lost, careful).
```

> 원격 저장소 자체 (GitHub 등) 는 호스팅 사이트 설정에서 지웁니다 — git 명령으로는 지워지지 않습니다.

## 3. Branch Lifecycle

가지는 생겨나 원격에 오르고, 남이 받아 다듬다, 일이 끝나면 지워집니다. 한살이를 단계로 나눠 핵심만 추립니다 (명령 상세는 아래 Commands).

```text
Creation → Publish (→ remote) → Track (← remote) → Management → Delete
```

### Creation

새 가지를 만들고 그 위에서 작업을 시작합니다.

```bash
git switch -c <branch>                     # create a branch and switch to it (recommended).
git branch <branch>                        # create only, do not switch.
git switch -c <branch> <start-point>       # branch off a specific commit/branch.
```

### Publish — upload to remote

로컬 가지를 원격에 올려 공유합니다. 처음 올릴 때 추적 관계를 맺습니다.

```bash
git push -u origin <branch>                # first upload, set the tracking link (later just git push).
git push                                   # push the current branch once tracking is set.
```

### Track — download from remote

원격에만 있는 가지를 내 쪽으로 받아 그 위에서 작업합니다.

```bash
git fetch                                  # fetch remote branch info only (working tree untouched).
git switch <branch>                        # create and track a remote branch of the same name.
git switch -c <local> origin/<branch>      # make a tracking branch from a named remote branch.
```

### Management

가지를 살피고, 이름을 바꾸고, 최신으로 맞춥니다.

```bash
git branch                                 # list local branches (* marks current).
git branch -a                              # include remote-tracking branches.
git branch -m <old> <new>                  # rename a branch.
git pull                                   # bring the current branch up to remote (fetch + merge).
git merge <branch>                         # merge another branch into the current one.
```

### Delete

일이 끝난 가지를 양쪽에서 치웁니다.

```bash
git branch -d <branch>                     # delete a merged local branch (-D to force).
git push origin --delete <branch>          # delete the remote branch.
git fetch --prune                          # clean up tracking refs for branches gone from remote.
```

## 4. Nested Repositories

메인 저장소 안에 다른 저장소를 특정 커밋으로 고정해 하위 폴더로 끼워 넣습니다. 두 방식이 있습니다 — `submodule` 은 포인터만 두고, `subtree` 는 코드를 통째로 합칩니다.

| Aspect | submodule | subtree |
|--------|-----------|---------|
| Storage | 커밋을 가리키는 포인터만 (gitlink) | 파일을 메인 이력에 합쳐 담음 |
| Nested `.git` | 폴더 안에 자체 `.git` 있음 (별도 저장소) | 없음 — 메인 저장소가 곧 전부 |
| Extra file | `.gitmodules` 생성 | 없음 |
| clone | `--recurse-submodules` 등 추가 작업 필요 | 그냥 clone 으로 끝 |
| push | 폴더로 `cd` 해 직접 push | `git subtree push` |
| Best for | 버전 고정·독립 관리 | 의존 코드를 품어 단순화 |

> 실행 위치 — `git submodule` 은 저장소 루트에서 실행을 권장하고, `git subtree` 는 루트 실행이 강제입니다 (아니면 toplevel 에러).

### Creation

다른 저장소를 하위 폴더로 처음 더해 nesting 을 만드는 단계입니다. 두 방식 중 하나를 고릅니다.

#### Submodule — link by pointer

하위 폴더에 다른 저장소를 **특정 커밋 포인터** 로 둡니다. 메인에는 주소와 커밋 해시만 적히고, 실제 파일은 각자의 저장소가 관리합니다.

```bash
git submodule add <url> <path>             # add another repo as a submodule at <path> (.gitmodules created).
git submodule add -b <branch> <url> <path> # add based on a specific branch.
git submodule status                       # show which commit each submodule points to.
```

버전을 올릴 때는 하위 모듈을 원하는 커밋으로 옮긴 뒤, 메인에서 그 포인터 변화를 커밋합니다.

```bash
cd <path> && git checkout <commit>         # set the submodule to the wanted commit.
cd .. && git add <path> && git commit -m "bump submodule"  # record the new pointer in the main repo.
```

> 메인에는 하위 모듈의 **커밋 해시만** 담깁니다. 받는 쪽은 실제 파일을 따로 받아 채워야 합니다 (아래 Track).

#### Subtree — merge code in

다른 저장소의 파일을 **메인 이력 안으로 통째로 합쳐** 하위 폴더에 둡니다. 받는 사람은 별도 명령 없이 보통 폴더처럼 바로 씁니다 (`.gitmodules` 없음).

```bash
git subtree add --prefix=<path> <url> <branch> --squash   # add a repo at <path> (path from repo root); squash history into one commit.
git subtree push --prefix=<path> <url> <branch>           # push <path> (path from repo root) changes back to that remote.
```

> `--squash` 는 끌어온 이력을 한 커밋으로 눌러 메인 이력을 깔끔하게 둡니다. 빼면 원본 커밋이 그대로 섞여 들어옵니다.

### Track — download from remote

메인을 받은 뒤 nested 내용을 내 쪽으로 채웁니다. subtree 는 메인에 이미 들어 있어 `clone` 만으로 따라오고, submodule 은 포인터만 있어 따로 받아 채워야 합니다.

#### Submodule — populate from remote

submodule 은 복제 직후 폴더가 비어 있습니다. 내용을 받아 채우고, 원격 최신으로 맞춥니다.

```bash
git clone --recurse-submodules <url>       # clone the main repo and fetch submodules together.
git submodule update --init --recursive    # if already cloned, populate submodule contents.
git submodule update --remote <path>       # update the submodule to the remote's latest commit.
```

#### Subtree — pull from remote

subtree 는 `clone` 으로 이미 따라옵니다. 원본 저장소의 새 변경만 끌어와 갱신합니다.

```bash
git subtree pull --prefix=<path> <url> <branch> --squash  # pull the remote's new changes into <path> (path from repo root).
```

#### Worktree — pin a version

submodule·subtree 없이, 다른 저장소의 특정 커밋만 하위 폴더로 펼쳐 고정해 씁니다.

```bash
git clone <url> <dep>                       # clone the other repo once into <dep>.
git -C <dep> worktree add <path> <commit>   # unfold <dep>'s commit into <path> (pinned version).
git -C <dep> worktree remove <path>         # remove the unfolded folder when done.
```

> worktree 로 펼친 폴더는 다른 저장소의 사본이라, 메인 저장소에서는 보통 `.gitignore` 로 빼 두어 메인 이력에 담지 않습니다.

## 5. Commands

역할별로 묶은 명령입니다. 대부분 앞의 네 자리 사이에서 무언가를 옮깁니다.

### Stage & Commit — add · commit

변경을 골라 담고 (stage) 이력으로 굳힙니다 (commit).

```bash
git status                                 # see changes and staging at a glance.
git add <file>                             # stage a specific file.
git add .                                  # stage all changes in the current folder.
git restore --staged <file>               # unstage (keep the working-tree changes).

git commit -m "<message>"                  # record staged changes into history.
git commit -am "<message>"                 # add + commit tracked files at once (excludes new files).
git commit --amend -m "<message>"          # rewrite the last commit (before it is pushed).
```

### History — log · rev-list · rev-parse

이력을 훑고, 커밋 수를 세고, ref 를 커밋 해시로 풀어 봅니다.

```bash
git log --oneline                          # browse commits, one line each.
git rev-list --count HEAD                  # count all commits up to HEAD.
git rev-list --count HEAD <file>           # count only commits that touched that file.

git rev-parse main                         # print the full commit hash that main points to.
git rev-parse --short main                 # print the shortened hash.
git rev-parse HEAD                          # print the current commit's hash.
```

### Stash

커밋하기 이른 변경을 잠시 치워 두고, 깨끗한 상태에서 다른 일을 합니다.

```bash
git stash                                  # shelve working changes and clear the working tree.
git stash -u                               # shelve untracked new files too.
git stash list                             # list shelved entries (stash@{0}, stash@{1} ...).
git stash show -p stash@{0}                # show a specific entry's changes.

git stash pop                              # restore the latest entry and drop it from the list.
git stash apply stash@{1}                  # restore a chosen entry but keep it in the list.
git stash drop stash@{0}                   # discard a specific entry.
git stash clear                            # clear all entries (careful).
```

### Branch & Switch — branch · switch · checkout

가지를 만들고 오갑니다. `switch` 는 가지 이동 전용, `checkout` 은 이동·복원을 겸하던 옛 명령입니다.

```bash
git branch                                 # list local branches (* marks current).
git branch -a                              # include remote-tracking branches.
git branch <branch>                        # create a branch (does not switch).
git branch -d <branch>                     # delete a merged branch (-D to force).
git branch -m <old> <new>                  # rename a branch.

git switch <branch>                        # switch to a branch (recommended).
git switch -c <branch>                     # create a branch and switch to it.
git checkout <branch>                      # switch branch (old way, same as switch).
```

### Sync — fetch · pull · push

원격과 주고받습니다. `fetch` 는 받기만, `pull` 은 받아 합치기, `push` 는 올리기입니다.

```bash
git fetch                                  # fetch the latest remote history only (working tree untouched).
git fetch --prune                          # also clean tracking refs for branches gone from remote.

git pull                                   # fetch + merge — bring changes into the current branch.
git pull --rebase                          # fetch, then rebase instead of merge (cleaner history).

git push                                   # push the current branch to the remote.
git push -u origin <branch>                # first upload, set the tracking link (later just git push).
git push --force-with-lease                # push rewritten history (guarded so others' work is not overwritten).
```

방향에 따라 **바뀌는 대상**이 다릅니다.

- 로컬 → 원격: `git push` (원격의 상태가 바뀜).
- 원격 → 로컬: `git fetch` 또는 `git pull` (로컬의 원격 추적 참조 상태가 바뀜).

### Integrate — merge · rebase

두 가지의 이력을 합칩니다. `merge` 는 합친 자국 (merge commit) 을 남기고, `rebase` 는 커밋을 옮겨 붙여 한 줄로 폅니다.

```bash
git merge <branch>                         # merge the given branch into the current one (creates a merge commit).
git merge --abort                          # undo a conflict-stalled merge, back to before merging.

git rebase <branch>                        # replay the current branch's commits onto <branch>'s tip.
git rebase --continue                      # after resolving conflicts, continue the rebase.
git rebase --abort                         # stop the rebase and return to the start.
```

### Undo — restore · checkout · reset · revert

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
# Restore the working tree — return edits to the last commit state.
git restore <file>                         # restore one file (new form of checkout -- <file>).
git restore .                              # discard all working-tree changes (careful).

# Move HEAD — set the whole working tree to another commit.
git checkout <commit>                      # set the working tree to that commit (HEAD goes detached).
git checkout -- <file>                     # discard one file's changes (old form of restore <file>).

# Move the commit position — step HEAD back.
git reset --soft HEAD~1                    # undo the commit only, keep changes staged.
git reset --mixed HEAD~1                   # undo commit and staging, keep changes in the working tree (default).
git reset --hard HEAD~1                    # discard commit, staging, and working tree (hard to undo, careful).

# Offset a commit — safely reverse already-shared history.
git revert <commit>                        # make a new commit that undoes that one (history preserved).
```

> **고르는 법** — 안 올린 작업 정리는 `reset`, 이미 push 한 커밋 뒤집기는 `revert`, 편집만 버리기는 `restore`.

### Extraction — Worktree · Archive

`checkout` 이 local state 와 working tree 를 바꾸는 **undo (되돌리기)** 라면, `worktree` 와 `archive` 는 working tree 만 바꾸는 **extraction (재현)** 입니다.

#### Worktree

  한 저장소에 작업 트리를 여러 개 두어, 가지마다 별도 폴더에서 동시에 작업합니다. 각 폴더가 같은 `.git` 이력을 공유합니다.

  ```bash
  git worktree list                          # list all attached working trees (path, branch, commit).
  git worktree add ../feat <branch>          # unfold <branch> into ../feat as a new working tree.
  git worktree add -b <branch> ../feat       # create a branch and unfold it into ../feat.
  git worktree add --detach ../tmp <commit>  # check out a commit without a branch (detached).

  git worktree remove ../feat                # remove a working tree (blocked if changes remain).
  git worktree prune                         # auto-clean worktree records whose .git pointer is broken.
  git worktree prune --verbose               # also show what was cleaned.
  git worktree prune --dry-run               # preview without deleting.
  ```

  > 같은 가지는 두 작업 트리에 동시에 펼칠 수 없습니다. 한 커밋만 잠깐 볼 때는 `--detach` 가 깔끔합니다.

#### Archive

  가지나 커밋의 한 시점을 `.git` 이력 없이 압축 파일로 내보냅니다. 소스만 묶어 배포할 때 씁니다.

  ```bash
  git archive -o src.zip HEAD                  # bundle the current snapshot as zip (.git excluded).
  git archive --format=tar.gz -o src.tgz HEAD  # bundle as tar.gz.
  git archive -o src.zip <branch>              # bundle a specific branch's snapshot.
  git archive -o sub.zip HEAD:<path>           # bundle only a subfolder.
  git archive --prefix=app/ -o src.zip HEAD    # place bundled files under app/.
  ```

  > `git archive` 는 추적 중인 파일만 담습니다. `.gitignore` 제외 파일과 `.git` 폴더는 빠지므로, 배포용 스냅샷에 알맞습니다.

### Windows

Windows 는 경로를 260자로 제한합니다. 폴더가 깊어 경로가 길면 git 작업이 막히므로, 확장 경로 API 를 켭니다.

```bash
git config --global core.longpaths true    # allow long paths in all repos (once).
git config --get core.longpaths            # check whether it is on (true = enabled).
```

> `--global` 은 현재 사용자 전체에 적용합니다. 한 저장소만 켜려면 그 폴더에서 `--global` 을 뺍니다. Windows 자체 제한도 풀려면 관리자 권한으로 레지스트리의 `LongPathsEnabled` 를 1 로 둡니다.

Git for Windows 배포판 자체를 최신으로 올립니다.

```bash
git update-git-for-windows                 # update Git for Windows to the latest version.
git version                                # check the installed git version.
```

> Git for Windows 전용 명령입니다 (Git Bash·CMD 에서 실행). 새 버전이 있으면 받아서 설치하고, 없으면 최신이라고 알려 줍니다.

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
- **work tree (working tree, working directory)** — 편집 중인 실제 파일이 펼쳐진 작업 폴더. 고친 내용을 `add` 로 stage 에 담고 `commit` 으로 굳힙니다.
