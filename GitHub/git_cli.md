# Git CLI (Command Line Interface)

rev. 106

자주 쓰는 git 명령을 작업 영역과 역할로 분류한다. `<BRANCH>`, `<REMOTE>`, `<COMMIT>`, `<FILE>` 과
같은 자리표시자는 실제 이름으로 바꿔 쓴다. 문법은 PowerShell 과 bash 에서 공통이다. 문서에서
사용한 용어의 정의는 [Appendix A. Terminology](#appendix-a-terminology) 에 정리한다.

---

## 1. Four Standard Areas

File 은 아래 네 영역을 오간다. 대부분의 명령은 어느 영역에서 어느 영역으로 옮기는가로 이해하면
쉽다.

```text
[ Local ]                                           [ Remote ]
---------------------------------------------------------------+------------------
 1. Working Tree  --->  2. Stage (Index)  --->  3. Local Repo  --->  4. Remote Repo
       |                        |                     |                      |
       |     [git add]          |                     |                      |
       |----------------------->|                     |                      |
       |                        |    [git commit]     |                      |
       |                        |-------------------->|                      |
       |                        |                     |     [git push]       |
       |                        |                     |--------------------->|
       |                        |                     |                      |
       |<---------------------------------------------+----------------------|
       |                             [git clone / git pull]                  |
```

Fig 1. File movement between the four standard areas.

Table 1. The four standard areas and their commands.

| Area | Meaning | Commands |
|---|---|---|
| Working tree | 편집 중인 실제 file 이 놓인 영역이다 | `restore`, `checkout`, `switch` |
| Stage (index) | 다음 commit 에 담아 둔 변경이다 | `add`, `restore --staged` |
| Local repository | Commit 되어 history 에 굳은 상태다 | `commit`, `reset`, `revert` |
| Remote repository | Server 에 있는 공유 repository 다 | `push`, `fetch`, `pull` |

---

## 2. Repository Lifecycle

Repository 는 만들어져 remote 에 올라가거나, 복제되어 내려오고, 운영되다 삭제되는 lifecycle 을
거친다. Repository 단위 명령을 단계별로 모은다.

```text
Creation -> Publish (-> remote) -> Track (<- remote) -> Management -> Deletion
```

Fig 2. Repository lifecycle stages.

### 2.1. Creation

빈 folder 를 새 repository 로 만들어 `.git` 을 생성한다.

```bash
git init                                   # turn the current folder into a new git repo
git init -b main                           # start with the default branch named main
```

### 2.2. Publish

Local repository 를 remote 에 연결해 처음 올린다.

```bash
git remote add origin <URL>                # link a remote under the name 'origin'
git push -u origin main                    # first upload; set the tracking link
```

### 2.3. Track

Remote repository 를 통째로 받아 local 에 복제한다.

```bash
git clone <URL>                            # copy a remote repo down in full
git clone -b <BRANCH> <URL>                # clone a specific branch
git clone --depth 1 <URL>                  # shallow clone with recent history only
```

### 2.4. Management

Remote 연결과 설정을 확인하고 수정한다.

```bash
git remote -v                              # list linked remotes with fetch and push URLs
git remote set-url origin <URL>            # change origin's URL
git remote rename <OLD> <NEW>              # rename a remote
git config --list                          # show the active config
```

### 2.5. Deletion

Repository 나 remote 연결을 정리한다.

```bash
git remote remove origin                   # drop only the remote link; the local repo stays
rm -rf .git                                # revert to a plain folder; history is lost
```

Remote repository 자체는 hosting service 의 설정 화면에서 삭제하며, git 명령으로는 지워지지 않는다.

---

## 3. Branch Lifecycle

Branch 는 만들어져 remote 에 올라가고, 다른 사람이 받아 다듬다가, 작업이 끝나면 삭제된다.
Lifecycle 을 단계로 나누어 핵심만 정리한다.

```text
Creation -> Publish (-> remote) -> Track (<- remote) -> Management -> Deletion
```

Fig 3. Branch lifecycle stages.

### 3.1. Creation

새 branch 를 만들고 그 위에서 작업을 시작한다.

```bash
git switch -c <BRANCH>                     # create a branch and switch to it
git branch <BRANCH>                        # create only, do not switch
git switch -c <BRANCH> <START_POINT>       # branch off a specific commit or branch
```

### 3.2. Publish

Local branch 를 remote 에 올려 공유한다. 처음 올릴 때 tracking 관계를 맺는다.

```bash
git push -u origin <BRANCH>                # first upload; set the tracking link
git push                                   # push the current branch once tracking is set
```

### 3.3. Track

Remote 에만 있는 branch 를 받아 그 위에서 작업한다.

```bash
git fetch                                  # fetch remote branch info only
git switch <BRANCH>                        # create and track a remote branch of the same name
git switch -c <LOCAL> origin/<BRANCH>      # make a tracking branch from a named remote branch
```

### 3.4. Management

Branch 를 확인하고, 이름을 바꾸고, 최신 상태로 맞춘다.

```bash
git branch                                 # list local branches; * marks the current one
git branch -a                              # include remote-tracking branches
git branch -m <OLD> <NEW>                  # rename a branch
git pull                                   # bring the current branch up to remote
git merge <BRANCH>                         # merge another branch into the current one
```

### 3.5. Deletion

작업이 끝난 branch 를 local 과 remote 양쪽에서 정리한다.

```bash
git branch -d <BRANCH>                     # delete a merged local branch; -D forces it
git push origin --delete <BRANCH>          # delete the remote branch
git fetch --prune                          # clean up refs for branches gone from remote
```

---

## 4. Nested Repositories

Main repository 안에 다른 repository 를 특정 commit 으로 고정해 하위 folder 로 넣는다. 두 가지
방식이 있으며, submodule 은 pointer 만 두고 subtree 는 code 를 통째로 합친다.

Table 2. Submodule versus subtree.

| Aspect | Submodule | Subtree |
|---|---|---|
| Storage | Commit 을 가리키는 pointer 만 담는다 | File 을 main history 에 합쳐 담는다 |
| Nested `.git` | Folder 안에 자체 `.git` 이 있다 | 없으며 main repository 가 전부다 |
| Extra file | `.gitmodules` 가 생성된다 | 없다 |
| Clone | `--recurse-submodules` 같은 추가 작업이 필요하다 | Clone 만으로 끝난다 |
| Push | Folder 로 이동해 직접 push 한다 | `git subtree push` 를 쓴다 |
| Best for | Version 고정과 독립 관리에 적합하다 | 의존 code 를 품어 단순화하는 데 적합하다 |

`git submodule` 은 repository root 에서 실행하기를 권장하고, `git subtree` 는 root 실행이
강제되며 그렇지 않으면 toplevel error 가 발생한다.

### 4.1. Creation

다른 repository 를 하위 folder 로 처음 더해 nesting 을 만드는 단계이며, 두 방식 중 하나를 고른다.

#### Submodule — link by pointer

하위 folder 에 다른 repository 를 특정 commit pointer 로 둔다. Main repository 에는 주소와
commit hash 만 기록되고, 실제 file 은 각자의 repository 가 관리한다.

```bash
git submodule add <URL> <PATH>             # add another repo as a submodule at <PATH>
git submodule add -b <BRANCH> <URL> <PATH> # add based on a specific branch
git submodule status                       # show which commit each submodule points to
```

Version 을 올릴 때는 submodule 을 원하는 commit 으로 옮긴 뒤, main repository 에서 그 pointer
변화를 commit 한다.

```bash
cd <PATH>
git checkout <COMMIT>                      # set the submodule to the wanted commit
cd ..
git add <PATH>
git commit -m "bump submodule"             # record the new pointer in the main repo
```

Main repository 에는 submodule 의 commit hash 만 담기므로, 받는 쪽은 실제 file 을 따로 받아
채워야 한다.

#### Subtree — merge code in

다른 repository 의 file 을 main history 안으로 통째로 합쳐 하위 folder 에 둔다. 받는 사람은 별도
명령 없이 보통 folder 처럼 바로 쓰며 `.gitmodules` 도 생기지 않는다.

```bash
git subtree add --prefix=<PATH> <URL> <BRANCH> --squash   # add a repo at <PATH> from repo root
git subtree push --prefix=<PATH> <URL> <BRANCH>           # push <PATH> changes back to that remote
```

`--squash` 는 가져온 history 를 하나의 commit 으로 눌러 main history 를 깔끔하게 유지한다. 이
option 을 빼면 원본 commit 이 그대로 섞여 들어온다.

### 4.2. Track

Main repository 를 받은 뒤 nested 내용을 채운다. Subtree 는 main history 에 이미 들어 있어
`clone` 만으로 따라오고, submodule 은 pointer 만 있어 따로 받아 채워야 한다.

#### Submodule — populate from remote

Submodule 은 복제 직후 folder 가 비어 있다. 내용을 받아 채우고 remote 최신 상태로 맞춘다.

```bash
git clone --recurse-submodules <URL>       # clone the main repo and fetch submodules together
git submodule update --init --recursive    # if already cloned, populate submodule contents
git submodule update --remote <PATH>       # update the submodule to the remote's latest commit
```

#### Subtree — pull from remote

Subtree 는 `clone` 으로 이미 따라오므로, 원본 repository 의 새 변경만 가져와 갱신한다.

```bash
git subtree pull --prefix=<PATH> <URL> <BRANCH> --squash  # pull new changes into <PATH>
```

#### Worktree — pin a version

Submodule 과 subtree 없이, 다른 repository 의 특정 commit 만 하위 folder 로 펼쳐 고정해 쓴다.

```bash
git clone <URL> <DEP>                      # clone the other repo once into <DEP>
git -C <DEP> worktree add <PATH> <COMMIT>  # unfold <DEP>'s commit into <PATH>
git -C <DEP> worktree remove <PATH>        # remove the unfolded folder when done
```

Worktree 로 펼친 folder 는 다른 repository 의 사본이므로, main repository 에서는 보통
`.gitignore` 로 제외해 main history 에 담지 않는다.

---

## 5. Commands

역할별로 묶은 명령이며, 대부분 앞의 네 영역 사이에서 무언가를 옮긴다.

### 5.1. Stage and Commit

변경을 골라 stage 에 담고 history 로 굳힌다.

```bash
git status                                 # see changes and staging at a glance
git add <FILE>                             # stage a specific file
git add .                                  # stage all changes in the current folder
git restore --staged <FILE>                # unstage but keep the working-tree changes

git commit -m "<MESSAGE>"                  # record staged changes into history
git commit -am "<MESSAGE>"                 # add and commit tracked files at once
git commit --amend -m "<MESSAGE>"          # rewrite the last commit before it is pushed
```

### 5.2. History

History 를 훑고, commit 수를 세고, ref 를 commit hash 로 풀어 본다.

```bash
git log --oneline                          # browse commits, one line each
git rev-list --count HEAD                  # count all commits up to HEAD
git rev-list --count HEAD <FILE>           # count only commits that touched that file

git rev-parse main                         # print the full commit hash that main points to
git rev-parse --short main                 # print the shortened hash
git rev-parse HEAD                         # print the current commit's hash
```

### 5.3. Stash

Commit 하기에 이른 변경을 잠시 치워 두고, 깨끗한 상태에서 다른 작업을 한다.

```bash
git stash                                  # shelve working changes and clear the working tree
git stash -u                               # shelve untracked new files too
git stash list                             # list shelved entries
git stash show -p stash@{0}                # show a specific entry's changes

git stash pop                              # restore the latest entry and drop it from the list
git stash apply stash@{1}                  # restore a chosen entry but keep it in the list
git stash drop stash@{0}                   # discard a specific entry
git stash clear                            # clear all entries
```

### 5.4. Branch and Switch

Branch 를 만들고 오간다. `switch` 는 branch 이동 전용이고, `checkout` 은 이동과 복원을 겸하던
예전 명령이다.

```bash
git branch                                 # list local branches; * marks the current one
git branch -a                              # include remote-tracking branches
git branch <BRANCH>                        # create a branch without switching
git branch -d <BRANCH>                     # delete a merged branch; -D forces it
git branch -m <OLD> <NEW>                  # rename a branch

git switch <BRANCH>                        # switch to a branch
git switch -c <BRANCH>                     # create a branch and switch to it
git checkout <BRANCH>                      # switch branch the old way
```

### 5.5. Sync

Remote 와 주고받는다. `fetch` 는 받기만 하고, `pull` 은 받아 합치며, `push` 는 올린다.

```bash
git fetch                                  # fetch the latest remote history only
git fetch --prune                          # also clean refs for branches gone from remote

git pull                                   # fetch and merge into the current branch
git pull --rebase                          # fetch, then rebase instead of merge

git push                                   # push the current branch to the remote
git push -u origin <BRANCH>                # first upload; set the tracking link
git push --force-with-lease                # push rewritten history without overwriting others' work
```

방향에 따라 바뀌는 대상이 다르다. Local 에서 remote 로 가는 `git push` 는 remote 의 상태를
바꾸고, remote 에서 local 로 오는 `git fetch` 와 `git pull` 은 local 의 remote-tracking branch
상태를 바꾼다.

### 5.6. Integrate

두 branch 의 history 를 합친다. `merge` 는 합친 자국인 merge commit 을 남기고, `rebase` 는
commit 을 옮겨 붙여 한 줄로 편다.

```bash
git merge <BRANCH>                         # merge the given branch into the current one
git merge --abort                          # undo a conflict-stalled merge

git rebase <BRANCH>                        # replay the current branch's commits onto <BRANCH>
git rebase --continue                      # after resolving conflicts, continue the rebase
git rebase --abort                         # stop the rebase and return to the start
```

### 5.7. Undo

되돌리기는 어느 영역을 되돌리는가에 따라 갈린다.

Table 3. Undo commands by target area.

| Command | Target | State | Working tree | Commit history |
|---|---|---|---|---|
| `restore <FILE>` | Working tree 의 file | modified 에서 committed 로 되돌리고 변경을 버린다 | 복원된다 | 바뀌지 않는다 |
| `restore --staged <FILE>` | Stage | staged 에서 modified 로 되돌린다 | 유지된다 | 바뀌지 않는다 |
| `checkout <COMMIT>` | HEAD 위치 | 지정한 commit 기준으로 맞춘다 | 교체된다 | HEAD 만 이동하고 보존된다 |
| `reset --soft` | Commit 위치 | committed 에서 staged 로 되돌린다 | 유지된다 | 이동한다 |
| `reset --mixed` | Commit 과 stage | committed 에서 modified 로 되돌린다 | 유지된다 | 이동한다 |
| `reset --hard` | Commit 과 stage 와 working tree | committed 에서 clean 으로 되돌리고 변경을 버린다 | 삭제된다 | 이동한다 |
| `revert <COMMIT>` | 특정 commit 의 효과 | 새 commit 을 추가한다 | 갱신된다 | 새 commit 으로 상쇄한다 |

```bash
# restore the working tree to the last commit state
git restore <FILE>                         # restore one file
git restore .                              # discard all working-tree changes

# move HEAD and set the whole working tree to another commit
git checkout <COMMIT>                      # HEAD goes detached
git checkout -- <FILE>                     # discard one file's changes, the old form

# move the commit position
git reset --soft HEAD~1                    # undo the commit only, keep changes staged
git reset --mixed HEAD~1                   # undo commit and staging, keep working-tree changes
git reset --hard HEAD~1                    # discard commit, staging, and working tree

# offset a commit and safely reverse already-shared history
git revert <COMMIT>                        # make a new commit that undoes that one
```

아직 올리지 않은 작업을 정리할 때는 `reset` 을 쓰고, 이미 push 한 commit 을 뒤집을 때는 `revert`
를 쓰며, 편집만 버릴 때는 `restore` 를 쓴다.

### 5.8. Extraction

`checkout` 이 local state 와 working tree 를 함께 바꾸는 undo 라면, `worktree` 와 `archive` 는
working tree 만 바꾸는 extraction 이다.

#### Worktree

한 repository 에 working tree 를 여러 개 두어, branch 마다 별도 folder 에서 동시에 작업한다. 각
folder 는 같은 `.git` history 를 공유한다.

```bash
git worktree list                          # list all attached working trees
git worktree add ../feat <BRANCH>          # unfold <BRANCH> into ../feat
git worktree add -b <BRANCH> ../feat       # create a branch and unfold it into ../feat
git worktree add --detach ../tmp <COMMIT>  # check out a commit without a branch

git worktree remove ../feat                # remove a working tree
git worktree prune                         # clean records whose .git pointer is broken
git worktree prune --verbose               # also show what was cleaned
git worktree prune --dry-run               # preview without deleting
```

같은 branch 를 두 working tree 에 동시에 펼칠 수는 없다. 한 commit 만 잠깐 확인할 때는
`--detach` 가 깔끔하다.

#### Archive

Branch 나 commit 의 한 시점을 `.git` history 없이 압축 file 로 내보낸다. 소스만 묶어 배포할 때
쓴다.

```bash
git archive -o src.zip HEAD                  # bundle the current snapshot as zip
git archive --format=tar.gz -o src.tgz HEAD  # bundle as tar.gz
git archive -o src.zip <BRANCH>              # bundle a specific branch's snapshot
git archive -o sub.zip HEAD:<PATH>           # bundle only a subfolder
git archive --prefix=app/ -o src.zip HEAD    # place bundled files under app/
```

`git archive` 는 추적 중인 file 만 담는다. `.gitignore` 로 제외한 file 과 `.git` folder 는 빠지므로
배포용 snapshot 에 적합하다.

### 5.9. Windows

Windows 는 경로를 260자로 제한한다. Folder 가 깊어 경로가 길면 git 작업이 막히므로 확장 경로 API
를 켠다.

```bash
git config --global core.longpaths true    # allow long paths in all repos
git config --get core.longpaths            # check whether it is on
```

`--global` 은 현재 사용자 전체에 적용한다. 하나의 repository 에만 적용하려면 그 folder 에서
`--global` 을 뺀다. Windows 자체 제한까지 풀려면 관리자 권한으로 registry 의 `LongPathsEnabled`
값을 1 로 둔다.

Git for Windows 배포판 자체는 다음 명령으로 최신으로 올린다.

```bash
git update-git-for-windows                 # update Git for Windows to the latest version
git version                                # check the installed git version
```

이 명령은 Git for Windows 전용이며 Git Bash 나 CMD 에서 실행한다. 새 version 이 있으면 받아서
설치하고, 없으면 최신이라고 알려 준다.

---

## Appendix A. Terminology

+ **.git** — Repository 의 모든 것이 담긴 숨김 folder 다. Commit, branch, history, 설정이 여기에 들어 있어 이 folder 가 곧 local repository 다. `git init` 으로 만들어지거나 `git clone` 으로 받아 오며, 지우면 history 가 사라지고 보통 folder 로 돌아간다.
+ **.gitattributes** — 경로별 취급 규칙을 적는 file 이다. 줄바꿈 정규화, diff 와 merge 방식, LFS 지정 등을 경로 pattern 에 걸어 둔다.
+ **.gitignore** — 추적하지 않을 file 을 pattern 으로 적는 file 이다. Build 산출물, cache, 비밀 key 등을 적어 두면 `git status` 와 `git add` 에서 빠지며, 이미 추적 중인 file 에는 적용되지 않는다.
+ **.gitmodules** — Submodule 의 경로와 remote 주소를 적어 두는 file 이다. `git submodule add` 로 채워진다.
+ **Branch** — Commit 을 가리키는 움직이는 이름표다. 본줄을 건드리지 않고 갈라져 작업하다 나중에 합친다.
+ **Detached HEAD** — HEAD 가 branch 가 아닌 특정 commit 을 직접 가리키는 상태다. 여기서 commit 하면 어느 branch 에도 매이지 않아, branch 를 새로 만들지 않으면 잃기 쉽다.
+ **HEAD** — 현재 위치를 가리키는 pointer 다. 보통 현재 branch 의 맨 끝 commit 을 가리키며, branch 가 아닌 특정 commit 을 직접 가리키면 detached 상태가 된다.
+ **Local repository** — 내 machine 에 있는 repository 다. Commit, branch, history 가 `.git` folder 에 담겨 network 없이도 모든 작업이 가능하다.
+ **Main** — 기본 branch 의 현재 표준 이름이며 예전의 master 를 대체한다.
+ **Master** — 기본 branch 의 옛 표준 이름이다. 동작은 main 과 같고 오래된 repository 에 남아 있다.
+ **Origin** — `git clone` 시 자동으로 붙는 remote 의 기본 이름이며 주소 대신 쓰는 별칭이다.
+ **Remote repository** — Server 에 있는 공유 repository 다. 여럿이 push 와 pull 로 history 를 주고받는 중심점이다.
+ **Remote-tracking branch** — Remote branch 를 local 에 비춰 둔 읽기용 이름이며 `fetch` 때 갱신된다.
+ **Repository** — Project 의 모든 file 과 history 를 담는 저장 단위이며 local 과 remote 양쪽에 존재한다.
+ **State** — 변경된 file 이 거치는 단계다. modified 는 working tree 에서 고쳤지만 아직 담지 않은 상태이고, staged 는 `git add` 로 다음 commit 에 담은 상태이며, committed 는 `git commit` 으로 history 에 굳은 상태다.
+ **Working tree** — 편집 중인 실제 file 이 펼쳐진 작업 folder 다. 고친 내용을 `git add` 로 stage 에 담고 `git commit` 으로 굳힌다.
