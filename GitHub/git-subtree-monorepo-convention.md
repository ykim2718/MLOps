# Git Subtree Monorepo Convention — Distributing Code Locked to an Exact Commit Hash

rev. 5

---

## 1. Purpose

작업 code 를 git commit hash 로 받아 배포하고 실행하는 상황을 전제로, repository 구조와 upload 및
download 규약을 정의한다. 문서에서 사용한 용어의 정의는
[Appendix A. Terminology](#appendix-a-terminology) 에 정리한다. 만족해야 할 요구사항은 다음과 같다.

1. Commit hash 로 version 을 정확히 고정한다. 어떤 code 가 실행되었는지 재현할 수 있도록 불변으로 남긴다.
2. 작업자가 code 를 하위 folder 로 자유롭게 추가한다.
3. Commit hash 하나로 작업 전체를 한 번에 받는다.
4. Upload 와 download 가 단순하고 관리가 쉽다.
5. Hardcoding 을 하지 않는다. Repository URL 과 commit hash 와 경로를 code 에 박지 않는다.

---

## 2. Decision

단일 monorepo 와 `main` branch 하나를 기준으로 한다. `main` 에서 하위 folder 를 만드는 방법과 그
허용 여부는 아래와 같다.

### 2.1. Taxonomy of Subfolder Creation Methods

가르는 기준은 하나다. 내용을 부모 commit 안에 물리적으로 넣는지, 아니면 pointer 나 link 만
넣는지로 나눈다. 물리적으로 넣으면 허용하고, pointer 나 link 만 넣으면 허용하지 않는다.

Table 1. Six ways to create a subfolder on `main` and whether each is allowed.

| No. | Method | How content enters the subfolder | Allowed |
|---|---|---|---|
| 1 | `mkdir` | Folder 와 file 을 직접 만들어 commit 하므로 내용이 monorepo 안에 물리적으로 포함된다 | 허용한다 |
| 2 | `cp` 또는 vendoring | 외부 repository 의 file 을 하위 folder 로 복사해 넣고 그쪽 `.git` 은 버리므로 내용이 plain file 로 포함된다 | 허용한다 |
| 3 | `git read-tree --prefix=<DIR>/` | 다른 tree 나 commit 을 index 의 하위 경로로 직접 읽어 넣으므로 내용이 물리적으로 포함된다 | 허용한다 |
| 4 | `git subtree` | 외부 upstream repository 의 내용을 하위 folder 로 흡수하므로 내용과 history 가 함께 들어온다 | 조건부로 허용한다 |
| 5 | `git submodule` | 외부 repository 를 gitlink pointer 로만 참조하므로 내용이 부모에 들어오지 않는다 | 허용하지 않는다 |
| 6 | Symlink | Repository 밖을 가리키는 symbolic link 만 commit 하므로 git 은 link 경로 문자열만 저장한다 | 허용하지 않는다 |

`mkdir` 은 기본 방식이며 평상시 작업은 전부 여기에 해당한다. 작업자는 code 를 실험 단위 folder 와
file 로 만들어 `main` 에 직접 commit 한다. 여러 팀이 아니라 한 사람이나 소규모가 실험과 code 를
늘려 가는 형태다.

`cp` 와 vendoring 은 외부 code 를 그대로 복사해 넣는 것이므로 결과는 `mkdir` 과 같은 plain file 이다.
출처가 외부 repository 라는 점만 다르고 이후 동기화가 필요 없을 때 쓴다. `.git` 을 함께 넣으면
embedded repository 문제가 되므로 반드시 제거한다.

`git read-tree --prefix` 는 subtree 의 저수준 형태다. History 를 잇지 않고 특정 tree 나 commit 의
snapshot 만 하위 folder 로 한 번 가져오며, 내용이 물리적으로 들어오므로 재현성 문제가 없다.

`git subtree` 는 외부에 독립 upstream repository 가 있어 양방향 동기화가 필요한 경우에만 쓴다.
흡수된 내용은 부모 commit hash 안에 물리적으로 남으므로 요구사항 1 과 요구사항 3 을 만족한다.

`git submodule` 과 symlink 는 pointer 나 link 경로만 저장하므로 허용하지 않으며, 그 이유는 2.2 에서
설명한다.

### 2.2. Exclusion of Submodule and Symlink

1 번부터 4 번까지는 내용을 부모 repository 안에 실제로 넣지만, submodule 과 symlink 는 pointer 나
link 만 넣는다. 그래서 commit hash 하나로 전체를 재현한다는 전제가 깨진다.

Table 2. Whether each method satisfies the requirements.

| Method | One commit hash equals all code | Download | Hardcoding | Reproducibility |
|---|---|---|---|---|
| `mkdir`, `cp`, `read-tree` | Hash 안에 code file 이 물리적으로 포함된다 | `clone` 한 번이면 끝난다 | 없다 | 보장된다 |
| `git subtree` | 내용이 부모 repository 로 흡수된다 | `clone` 한 번이면 끝난다 | 없다 | 보장된다 |
| `git submodule` | Hash 는 pointer 만 저장한다 | `clone --recurse` 와 submodule 별 fetch 및 인증이 필요하다 | `.gitmodules` 에 URL 이 박힌다 | Submodule 의 remote 가 살아 있어야 한다 |
| Symlink | Hash 는 link 경로만 저장한다 | `clone` 은 한 번이지만 대상은 따라오지 않는다 | Link 에 대상 경로가 박힌다 | 대상이 그대로 있어야 한다 |

요구사항 3 을 위반하는 이유는 부모 commit 이 submodule 이 가리키는 commit 의 pointer 만 담기
때문이다. Symlink 는 대상 경로 문자열만 담는다. 실제 code 는 재귀 fetch 나 대상 경로가 추가로
필요하므로 hash 하나로 끝나지 않는다.

요구사항 4 를 위반하는 이유는 submodule 이 pull 에 재귀 option 과 submodule 별 자격증명을
요구하고 push 에 두 단계를 요구하기 때문이다. Symlink 는 대상이 repository 밖에 있으면 download
로 함께 오지 않는다.

요구사항 5 를 위반하는 이유는 submodule 이 `.gitmodules` 에 URL 을 박고 symlink 가 link 에 대상
경로를 박기 때문이다.

`cp` 로 넣을 때 외부 repository 의 `.git` 을 함께 넣으면 등록되지 않은 내부 repository 가 되어
submodule 과 같은 문제가 생기므로, 반드시 `.git` 을 제거하고 plain file 로 넣는다.

---

## 3. Directory Layout

```text
repo/
|-- experiment_1/
|   +-- my_flow.py             # experiment flow locked to an exact commit hash
|-- experiment_2/
|   +-- other_flow.py          # another experiment flow
+-- common/                    # shared scripts and resources for flows
```

Fig 1. Monorepo directory layout.

각 실험은 자기 folder 안에서 자유롭게 구성하며 folder 끼리는 충돌하지 않는다. 여러 실험이
공유하는 script 와 resource 는 `common/` 에 둔다. Code 를 추가하는 작업은 folder 와 file 을 만들고
`main` 에 commit 하는 것으로 끝난다. Branch 를 만들지 않고 `main` 에 직접 commit 하며, 배포와
실행에 쓰는 것은 `main` 의 commit hash 다.

---

## 4. Reproducibility

배포와 실행 대상은 항상 branch 나 tag 가 아니라 40자 commit hash 로 지정한다. Tag 와 branch 는
움직일 수 있어 재현성이 깨지지만 hash 는 불변이다.

Monorepo 이므로 commit 하나를 받으면 그 시점의 작업 전체 tree 가 통째로 온다. 어떤 flow code 가
실행되었는지가 commit hash 하나로 완전히 고정된다.

---

## 5. Hardcoding Prohibition

Repository URL 과 commit hash 와 실행할 code 경로를 code 에 literal 로 박지 않는다. 환경변수와
실행 인자와 설정 file 로 주입한다.

```bash
export SOURCE_REPO_URL="<REPO_URL>"
export SOURCE_COMMIT_SHA="<COMMIT_SHA>"
export FLOW_PATH="<FLOW_PATH>"
```

실행할 flow 경로도 위와 같이 환경변수나 인자로 주입하고 code 에 박지 않는다.

---

## 6. Upload Command

Monorepo 의 `main` 을 기준으로 한다. Subtree 가 없는 평상시 흐름과 subtree 가 있는 동기화 흐름을
나눈다.

### 6.1. Without Subtree

Code 를 추가하거나 수정하는 평상시 흐름이며 거의 모든 작업이 여기에 해당한다.

```bash
git add -A
git commit -m "<MESSAGE>"
git push origin main

# print the commit hash that fixes this exact version
git rev-parse HEAD
```

### 6.2. With Subtree

외부 upstream 을 흡수한 subtree folder 를 거꾸로 밀어 올리거나 갱신할 때만 쓴다. Subtree folder 가
없다면 이 절은 건너뛴다.

```bash
# push local subtree changes back up to the upstream
git subtree push --prefix=common/<SHARED> <REMOTE_URL> main

# pull upstream changes down into the subtree
git subtree pull --prefix=common/<SHARED> <REMOTE_URL> main --squash
```

`<SHARED>` 는 외부 upstream 을 흡수해 둔 subtree folder 의 이름이고, `<REMOTE_URL>` 은 그 upstream
repository 의 주소다.

---

## 7. Download Command

Download 는 원하는 하위 folder 하나만 따로 받는 것이 아니라, 그 folder 를 포함한 repository 를
통째로 받는 명령이다. 받은 뒤 그 안에서 필요한 하위 folder 를 골라 쓴다. 7.1 은 전체 history 와
file 을 받고, 7.2 는 해당 commit 시점의 tree 전부를 받으며, 7.3 은 같은 tree 를 별도의 detached
worktree 로 펼친다.

### 7.1. Full Clone

```bash
# full clone then checkout the hash; the whole code tree comes with it
git clone <REPO_URL> _src
git -C _src checkout <COMMIT_SHA>
```

### 7.2. Shallow Fetch

```bash
mkdir _src
cd _src
git init -q
git remote add origin <REPO_URL>
git fetch --depth 1 origin <COMMIT_SHA>    # shallow fetch
git checkout FETCH_HEAD
```

### 7.3. Worktree

Shallow fetch 로 받은 commit 을 별도의 detached worktree directory 로 펼쳐 실행하고 재현할 때 쓴다.
`git worktree add` 는 같은 repository 에 연결된 또 하나의 작업 directory 를 새로 만든다. 그래서
맨 처음 만들어진 main worktree 에 무엇이 checkout 되어 있든 그대로 두고, 새 worktree directory 에만
대상 commit 을 펼친다. 즉 main worktree 의 branch 와 file 을 건드리지 않는다.

```bash
git init <REPO>
git -C <REPO> remote add origin <REPO_URL>
git -C <REPO> fetch --depth 1 origin <COMMIT_SHA>   # shallow fetch
# expand the fetched commit into a clean detached worktree
git -C <REPO> worktree add --detach <SCRIPT> <COMMIT_SHA>
```

`--detach` 는 새 worktree 의 HEAD 를 branch 에 붙이지 않고 지정한 commit 에 detached HEAD 로
고정한다. 재현에는 특정 commit 의 snapshot 만 있으면 되고 branch 가 필요 없다. 또한 branch 를 쓰면
같은 branch 를 두 worktree 에 동시에 checkout 할 수 없다는 제약에 걸리는데, `--detach` 는 branch 를
만들지 않으므로 이를 피한다.

### 7.4. Trade-offs

Table 3. Comparison of clone, shallow fetch, and worktree.

| Method | Result | Download | Needs arbitrary-SHA fetch | Pros | Cons |
|---|---|---|---|---|---|
| Full clone | 독립된 repository 사본이 남는다 | 전체 history 와 file 을 받는다 | 필요하지 않다 | 가장 단순하고 어떤 server 에서도 동작하며 전체 history 가 남는다 | 전체 history 를 받아 무겁고 느리다 |
| Shallow fetch | 단일 commit tree 만 남는다 | 해당 commit tree 만 받는다 | 필요하다 | Download 가 최소라 가장 빠르다 | Server 가 막으면 실패하고 history 가 없어 이후 git 작업이 제약된다 |
| Worktree | Main worktree 와 detached worktree 가 함께 남는다 | 해당 commit tree 만 받는다 | 필요하다 | 받은 commit 을 main worktree 와 분리된 깨끗한 directory 로 펼친다 | Worktree 를 따로 관리해야 하고 server 가 막으면 실패한다 |

임의 SHA fetch 를 server 가 막으면 shallow fetch 방식과 worktree 방식은 실패하므로 full clone 으로
대체한다. 단발 실행과 재현은 셋 중 하나로 받아 그 자리에서 실행한다. Main worktree 를 건드리지
않고 별도 directory 에서 재현하려면 worktree 방식을 쓴다.

Checkout 되었거나 worktree 로 펼쳐진 tree 에서 하위 folder 의 flow file 을 그대로 실행하면, 그
commit hash 로 고정한 시점의 code 가 그대로 재현된다.

---

## Appendix A. Terminology

+ **Commit hash** — Commit 하나를 가리키는 40자 식별자다. 불변이므로 version 을 고정하는 기준으로 쓴다.
+ **Detached HEAD** — HEAD 가 branch 가 아니라 특정 commit 을 직접 가리키는 상태다.
+ **Embedded repository** — 다른 repository 의 `.git` 이 하위 folder 에 그대로 딸려 들어와 등록되지 않은 내부 repository 가 된 상태다.
+ **Gitlink** — 부모 repository 가 submodule 의 commit 을 가리키기 위해 저장하는 pointer 다.
+ **Monorepo** — 여러 작업과 code 를 하나의 repository 에 모아 두는 구조다.
+ **Shallow fetch** — `--depth` option 으로 history 의 일부만 받아 오는 fetch 다.
+ **Submodule** — 외부 repository 를 pointer 로만 참조해 하위 folder 에 두는 방식이다.
+ **Subtree** — 외부 repository 의 내용을 부모 repository 의 history 로 흡수해 하위 folder 에 두는 방식이다.
+ **Symlink** — 다른 경로를 가리키는 symbolic link 다. git 은 link 의 경로 문자열만 저장한다.
+ **Upstream** — Subtree 나 fork 의 출처가 되는 외부 repository 다.
+ **Vendoring** — 외부 code 를 복사해 자기 repository 안에 plain file 로 포함시키는 방식이다.
+ **Worktree** — 같은 repository 에 연결된 별도의 작업 directory 다. Main worktree 는 맨 처음 만들어진 기본 작업 directory 를 가리킨다.
