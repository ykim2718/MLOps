# Git Subtree Monorepo Convention — distributing code locked to an exact commit hash

Rev. 5 | Created: 2026-07-18 | Updated: 2026-08-14 21:32 CDT

---

## 1. Purpose

작업 **code (예: experiment flow)** 를 **git commit hash 로 받아 배포·실행**하는 상황을
전제로, 저장소 구조와 upload/download 규약을 정의한다. 만족해야 할 요구사항은 다음과 같다.

1. commit hash 로 version을 정확히 고정한다. 어떤 code가 돌았는지 재현 가능하도록 불변으로 남긴다.
2. 작업자가 code를 하위 folder (`experiment_1/`, `experiment_2/` …) 로 자유롭게 추가한다.
3. commit hash 하나로 **작업 전체** 를 한 번에 받는다.
4. upload/download 가 단순하고 관리가 쉽다.
5. **hardcoding을 하지 않는다** (repo URL·commit·경로를 code에 박지 않는다).

---

## 2. Decision

**단일 monorepo + `main` branch 하나** 를 기준으로 한다. `main` 에서 하위 folder를 만드는 방법은
세 가지가 있고, 그 taxonomy 와 허용 여부는 다음과 같다.

### 2.1. Taxonomy — six ways to create a subfolder on `main`

가르는 기준은 하나다. **내용을 부모 commit 안에 물리적으로 넣는가, 아니면 pointer·link만 넣는가.**
물리적으로 넣으면 허용, pointer·link만 넣으면 불허다.

| # | Method | How content enters the subfolder | Allowed |
|---|--------|----------------------------------|---------|
| 1 | **`mkdir` (plain directory)** | folder·file을 직접 만들어 commit한다. 내용이 monorepo 안에 **물리적으로** 포함된다. | ✅ 허용 |
| 2 | **`cp` / vendoring (copy-in)** | 외부 repo file을 하위 folder로 **복사**해 넣고 그쪽 `.git` 은 버린다. 내용이 plain file로 물리적 포함된다. | ✅ 허용 |
| 3 | **`git read-tree --prefix=<dir>/`** | 다른 tree/commit 을 index의 하위 경로로 **직접 읽어** 넣는다 (subtree 의 저수준·일회성 import). 내용 물리적 포함. | ✅ 허용 |
| 4 | **`git subtree`** | 외부 upstream repo 의 내용을 하위 folder로 **흡수(merge)** 한다. 내용이 부모 repo 로 들어오고 이력도 이어진다. | ✅ 허용 (조건부) |
| 5 | **`git submodule`** | 외부 repo 를 **pointer(gitlink)** 로만 참조한다. 내용은 부모에 들어오지 않는다. | ❌ 불허 |
| 6 | **symlink (`ln -s`)** | repo 밖(또는 다른 위치)을 가리키는 **symbolic link**만 commit한다. git 은 link 경로 문자열만 저장한다. | ❌ 불허 |

- **1 `mkdir` — 허용 (기본).** 평상시 작업은 전부 이 방식이다. 작업자는 code를 `experiment_N/<flow>.py`
  단위로 (예: `experiment_1/my_flow.py`, `experiment_2/other_flow.py`) folder·file을 만들어 `main` 에
  직접 commit한다 (요구사항 2). 여러 팀이 아니라 한 사람이나 소규모가 실험·code를 늘려가는 형태다.
- **2 `cp` / vendoring — 허용.** 외부 code를 그대로 복사해 넣는 것이므로 결과는 `mkdir` 과 같은 plain
  file이다. 출처가 외부 repo 라는 점만 다르고, 이후 동기화가 필요 없을 때 쓴다. `.git` 을 함께 넣지
  않도록 주의한다 (넣으면 6번 embedded repo 문제가 된다).
- **3 `git read-tree --prefix` — 허용.** subtree 의 저수준 형태다. 이력을 잇지 않고 특정 tree/commit
  snapshot만 하위 folder로 한 번 끌어온다. 내용이 물리적으로 들어오므로 재현성 문제는 없다.
- **4 `git subtree` — 조건부 허용.** 외부에 독립 upstream repo 가 있어 **양방향 동기화가 필요한
  경우에 한해서만** 쓴다 (예: 공용 code·module을 별도 repo 로 배포하는 경우). 흡수된 내용은 부모
  commit hash 안에 물리적으로 남으므로 req1·req3 를 만족한다.
- **5 `git submodule` — 불허.** pointer만 저장한다. 아래 §2.2 참고.
- **6 symlink — 불허.** link 경로만 저장하고 대상 내용은 저장하지 않는다. submodule 과 같은 실패 mode다.

### 2.2. Why submodule / symlink are excluded

1~4 는 내용을 부모 repo 안에 실제로 넣지만, `submodule` 과 symlink 는 **pointer·link만** 넣는다.
그래서 commit hash 하나로 전체를 재현한다는 전제가 깨진다.

| Method | One commit hash = all code? | Download | Hardcoding (req5) | Reproducibility (req1) |
|--------|-----------------------------|----------|-------------------|------------------------|
| **`mkdir` / `cp` / `read-tree`** | ✅ hash 안에 code file이 물리적으로 포함된다 | `clone` 1번 | 없음 | ✅ |
| **`git subtree`** | ✅ 내용이 부모 repo 로 흡수된다 | `clone` 1번 | 없음 | ✅ |
| **`git submodule`** | ❌ hash는 **pointer만** 저장한다 | `clone --recurse` + submodule N개 fetch + 각각 인증 | `.gitmodules` 에 URL 이 박힌다 | △ submodule 원격이 살아있어야 한다 |
| **symlink** | ❌ hash는 **link 경로만** 저장한다 | `clone` 1번이지만 대상은 안 옴 | link에 대상 경로가 박힌다 | ❌ 대상이 그대로 있어야 한다 |

- **req3 위반**: 부모 commit 은 submodule이 가리키는 commit의 pointer(symlink 는 대상 경로 문자열)만 담는다. 실제 code 소스는 재귀 fetch 또는 대상 경로가 추가로 필요하므로 hash 하나로 끝나지 않는다.
- **req4 위반**: submodule 은 pull 에 재귀 option·submodule별 자격증명이, push 에 2단계가 필요하다. symlink 는 대상이 repo 밖에 있으면 download 로 함께 오지 않는다.
- **req5 위반**: submodule 은 `.gitmodules` 에 URL 이, symlink 는 link에 대상 경로가 hardcoding된다.
- **embedded git repo 주의**: 2번(`cp`) 에서 외부 repo 의 `.git` 을 함께 넣으면 등록 안 된 내부 repo(gitlink)가 되어 5번 submodule 과 같은 문제가 된다. 반드시 `.git` 을 제거하고 plain file로 넣는다.

---

## 3. Directory layout

```
repo/
├── experiment_1/
│   └── my_flow.py             # experiment flow (code locked to an exact commit hash)
├── experiment_2/
│   └── other_flow.py          # another experiment flow
└── common/                    # shared scripts and resources for flows
```

- 각 실험은 자기 folder (`experiment_1`, `experiment_2` …) 안에서 자유롭게 구성한다. folder끼리는 충돌하지 않는다.
- 여러 실험이 공유하는 script·resource는 `common/` 에 둔다.
- code를 추가하는 작업은 folder와 file 하나를 만들고 `main` 에 commit하는 것뿐이다.
- **branch 를 만들지 않고 `main` 에 직접 commit한다.** 배포·실행에 쓰는 것은 `main` 의 commit hash 다.

---

## 4. Reproducibility (req1)

배포·실행 대상은 항상 **branch/tag 가 아니라 40자 commit hash** 로 지정한다.
tag/branch 는 움직일 수 있어 재현성이 깨지지만 hash 는 불변이다.

monorepo 이므로 commit 하나를 받으면 그 시점의 **작업 전체 tree가 통째로** 온다 (req3).
어떤 experiment flow code가 돌았는지가 commit hash 하나로 완전히 고정된다.

---

## 5. No hardcoding (req5)

repo URL 과 commit hash, 실행할 code 경로를 code에 literal로 박지 않는다.
**환경변수·실행 인자·설정 file**로 주입한다.

```bash
export SOURCE_REPO_URL="https://github.com/<org>/<repo>.git"
export SOURCE_COMMIT_SHA="<40-char sha>"
export FLOW_PATH="experiment_1/my_flow.py"
```

실행할 flow 경로도 위처럼 환경변수·인자로 주입하고 code에 박지 않는다.

---

## 6. Upload command (req4)

monorepo `main` 기준이다. subtree 가 없는 평상시 흐름과, subtree 가 있는 동기화 흐름을 나눈다.

### 6.1. Without subtree (plain `main`)

code를 추가하거나 수정한 평상시 흐름이다. 거의 모든 작업은 여기에 해당한다 (§2 taxonomy 1 `mkdir`).

```bash
git add -A
git commit -m "<message>"
git push origin main

# print the commit hash that fixes this exact version
git rev-parse HEAD
```

### 6.2. With subtree (external upstream sync)

외부 upstream (공용 code repo) 을 흡수한 subtree folder를 **거꾸로 밀어 올리거나 갱신할 때만** 쓴다
(§2 taxonomy 4). subtree folder가 없다면 이 절은 건너뛴다.

```bash
# push local subtree changes back up to the upstream
git subtree push --prefix=common/<shared> <remote-url> main

# pull upstream changes down into the subtree
git subtree pull  --prefix=common/<shared> <remote-url> main --squash
```

`<shared>` 는 외부 upstream 을 흡수해 둔 subtree folder 의 이름이다. 예를 들어 공용 module 을
`common/libfoo` 로 받아 뒀다면 `<shared>` 자리에 `libfoo` 를 넣어 `--prefix=common/libfoo` 로 쓴다.
`<remote-url>` 은 그 upstream repo 의 주소다.

---

## 7. Download command (req4)

download 는 원하는 하위 folder 하나만 따로 받는 게 아니라, **그 folder를 포함한 git repo 를 통째로 받는**
명령이다. 받은 뒤 그 안에서 필요한 하위 folder (`experiment_1/` 등) 를 골라 쓴다.
(7.1 은 전체 이력·file을, 7.2 는 해당 commit 시점의 tree 전부를, 7.3 은 같은 tree를 별도 detached worktree 로 펼친다.)

### 7.1. CLI (simplest)

```bash
# full clone then checkout the hash — the whole code tree comes with it
git clone <repo-url> _src && git -C _src checkout <commit-sha>
```

### 7.2. CLI (shallow fetch)

```bash
mkdir _src && cd _src
git init -q
git remote add origin <repo-url>
git fetch --depth 1 origin <commit-sha>   # shallow fetch
git checkout FETCH_HEAD
```

### 7.3. CLI (git worktree)

shallow fetch (7.2) 로 받은 commit 을 **별도의 detached worktree directory** 로 펼쳐 실행·재현할 때 쓴다.
`git worktree add` 는 같은 repo 에 연결된 **또 하나의 worktree**(별도의 작업 directory) 를 새로 만든다.
그래서 repo 의 **main worktree**(맨 처음 만들어진 기본 작업 directory, 평소 checkout 이 이뤄지는 곳) 에
무엇이 checkout 되어 있든 그대로 두고, 새 worktree directory 에만 대상 commit 을 펼친다. 즉 main worktree 의
branch·file 을 건드리지 않는다.

```bash
git init <repo>
git -C <repo> remote add origin <repo-url>
git -C <repo> fetch --depth 1 origin <commit-sha>   # shallow fetch
# expand the fetched commit into a clean detached worktree under <script>/
git -C <repo> worktree add --detach <script> <commit-sha>
```

`--detach` 는 새 worktree 의 HEAD 를 branch 에 붙이지 않고 **지정한 commit 에 detached HEAD 로 고정**한다.
재현에는 특정 commit 스냅샷만 있으면 되고 branch 가 필요 없다. 또 branch 를 쓰면 "같은 branch 는 두
worktree 에 동시에 checkout 할 수 없다" 는 제약에 걸리는데, `--detach` 는 branch 를 만들지 않으므로
이를 피한다.

### 7.4. Trade-offs — clone vs checkout vs worktree

| Method | Result | Download | Needs arbitrary-SHA fetch | Pros | Cons |
|--------|--------|----------|---------------------------|------|------|
| **clone + checkout** (7.1) | standalone repo copy | 전체 이력·file | 불필요 (clone 뒤 로컬 checkout) | 가장 단순하고 어떤 server에서도 동작한다. 전체 이력이 남는다. | 전체 이력을 받아 무겁고 느리다. |
| **shallow fetch + checkout** (7.2) | single commit tree | 해당 commit tree만 (`--depth 1`) | 필요 (server가 SHA fetch 를 허용해야 한다) | download가 최소라 가장 빠르다. | server가 막으면 실패한다. 이력이 없어 이후 git 작업이 제약된다. |
| **shallow fetch + worktree** (7.3) | main worktree + detached worktree | 해당 commit tree 만 (`--depth 1`) | 필요 (server 가 SHA fetch 를 허용해야 한다) | 받은 commit 을 main worktree 와 분리된 **깨끗한 별도 directory** 로 펼친다. download 는 7.2 처럼 최소다. | worktree 를 따로 관리해야 하고, server 가 SHA fetch 를 막으면 실패한다. |

- 임의 SHA fetch 를 server가 막으면 7.2·7.3 은 실패한다. 그 경우 7.1 의 full clone 으로 fallback한다.
- 단발 실행·재현은 7.1~7.3 중 하나로 받아 그 자리에서 돌린다. main worktree 를 건드리지 않고 별도 directory 에서 재현하려면 7.3 을 쓴다.

checkout (또는 worktree 로 펼쳐진) tree에서 `experiment_1/my_flow.py`, `experiment_2/other_flow.py` … 를
그대로 실행하면 그 commit hash 로 고정한 그 시점의 code가 그대로 재현된다.

---

## 8. Example files

- `experiment_1/my_flow.py` — commit hash 로 고정·배포하는 실험 flow code다.
- `experiment_2/other_flow.py` — 같은 방식으로 하위 folder에 추가하는 또 다른 실험 flow 다.
