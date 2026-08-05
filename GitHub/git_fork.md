# Git Fork — collaborating across repository boundaries

rev. 1

---

## 1. Purpose

`fork` 는 **다른 사람의 repo 를 내 계정 아래 복사본으로 만드는 것**이다. 이 문서는 fork 를
**협업(collaboration) 관점**에서 정리한다. 즉 "명령을 어떻게 치는가" 보다 **누가 어디에 쓸
권한을 갖는가, 변경이 어떤 경로로 원본에 합쳐지는가** 를 중심에 둔다.

핵심 한 줄: **fork 는 git 기능이 아니라 GitHub(호스팅) 기능이며, 쓰기 권한이 없는 사람이
기여할 수 있게 해 주는 장치다.**

```text
  [upstream] someone/project          ← 원본. 나는 push 권한 없음
        │  fork (server-side copy, GitHub 이 수행)
        ▼
  [origin]   me/project               ← 내 계정의 복사본. 나는 push 권한 있음
        │  clone
        ▼
  [local]    ~/project                ← 내 PC
```

변경은 `local → origin` 으로 push 되고, `origin → upstream` 으로는 **Pull Request(PR)** 를
통해서만 들어간다. 이 비대칭이 fork 협업의 전부다.

---

## 2. Fork vs Clone vs Branch

셋 다 "복사"처럼 보이지만 **복사가 일어나는 장소**와 **권한 경계**가 다르다.

| | `fork` | `clone` | `branch` |
|---|---|---|---|
| 수행 주체 | GitHub (서버) | git (로컬) | git (로컬/원격) |
| 복사본 위치 | 내 GitHub 계정 | 내 PC | 같은 repo 안 |
| 새 repo 생성 | ✅ 별도 repo | ❌ 원본의 사본 | ❌ 같은 repo |
| 원본에 대한 권한 | 불필요 (읽기만) | 불필요 (읽기만) | **필요** (쓰기) |
| 원본에 반영 | PR (fork → upstream) | push (권한 있을 때) | merge / PR |
| 원본과의 연결 | fork network 로 기록 | remote 로 연결 | 같은 이력 |

- **branch** — 같은 repo 안에서 작업을 나눈다. **팀원(쓰기 권한 보유)** 의 기본 도구.
- **clone** — 어떤 repo든 로컬로 내려받는다. 권한과 무관하며, 그 자체로는 기여 경로가 아니다.
- **fork** — **쓰기 권한이 없는 사람** 이 자기 소유의 push 대상을 확보하는 방법.

> clone 만 해서는 push 할 곳이 없다. 권한 없는 repo 를 clone 하고 push 하면 거절된다.
> fork 는 "push 할 수 있는 내 repo" 를 먼저 만들어 주는 단계다.

---

## 3. Two collaboration models

협업 방식은 크게 두 가지고, **fork 를 쓰느냐 마느냐** 로 갈린다.

### 3.1. Shared Repository Model — branch + PR

repo 하나를 팀원이 공유하고, 각자 branch 를 만들어 PR 을 올린다.

```text
        me/team-repo (모두 쓰기 권한)
   main ──┬── feature/a  ──PR──▶ main
          └── feature/b  ──PR──▶ main
```

- 전제: 참여자 전원이 **신뢰받는 collaborator** 이고 쓰기 권한이 있다.
- 장점: 구조가 단순하다. remote 가 `origin` 하나뿐이고 동기화 개념이 없다.
- 단점: 아무나 참여시킬 수 없다. 권한을 주는 순간 repo 전체에 대한 권한이다.
- 적합: 사내 팀, 소규모 프로젝트, 개인 repo. **대부분의 업무 repo 는 여기에 해당한다.**

### 3.2. Fork & Pull Model — fork + PR

기여자는 fork 를 만들고 자기 fork 에 push 한 뒤, upstream 으로 PR 을 올린다.

```text
   someone/project (upstream)  ◀──PR──  me/project (origin, 내 fork)
          │                                    ▲
          │ (읽기)                              │ push
          └────────────────────────────────────┴── local
```

- 전제: 기여자에게 **권한을 주지 않고도** 기여를 받아야 한다.
- 장점: 권한 없이 누구나 기여할 수 있다. 원본은 maintainer 의 merge 없이는 바뀌지 않는다.
- 단점: remote 가 둘(`origin`, `upstream`)이 되고, **fork 를 최신으로 유지하는 부담**이 생긴다.
- 적합: 오픈소스, 외부 협력사·인턴·계약직 기여, 사고 위험이 큰 중요 repo.

### 3.3. Choosing

| 상황 | 권장 |
|---|---|
| 같은 팀, 서로 신뢰, 쓰기 권한 부여 가능 | **branch + PR** (fork 불필요) |
| 외부 기여자 / 권한을 줄 수 없음 | **fork + PR** |
| 원본을 완전히 다른 방향으로 가져가려 함 | fork (또는 별도 repo, §8) |
| 남의 repo 를 참고·실험만 하려 함 | clone 으로 충분 |

> 흔한 오해 — "협업하려면 fork 해야 한다"는 아니다. **권한을 줄 수 있으면 branch 가 더 낫다.**
> fork 는 권한 경계를 넘기 위한 도구이지, 협업의 기본형이 아니다.

---

## 4. Contributor workflow

기여자 입장에서의 전체 흐름이다. 1~2 는 최초 1회, 3~7 은 기여할 때마다 반복한다.

### 4.1. Fork the upstream

GitHub 웹에서 원본 repo 우상단 **Fork** 버튼을 누른다. CLI 로도 가능하다.

```bash
gh repo fork someone/project --clone           # fork and clone in one step (GitHub CLI).
gh repo fork someone/project --remote          # also set the 'upstream' remote automatically.
```

### 4.2. Clone and wire up two remotes

fork 협업의 규약은 **remote 이름 두 개**다. 이 이름을 지키면 이후 모든 명령이 통한다.

| Remote | 가리키는 곳 | 권한 | 용도 |
|---|---|---|---|
| `origin` | 내 fork (`me/project`) | 읽기 + **쓰기** | 내 branch 를 push |
| `upstream` | 원본 (`someone/project`) | 읽기만 | 최신 변경을 fetch |

```bash
git clone https://github.com/me/project.git            # clone MY fork -> becomes 'origin'.
cd project
git remote add upstream https://github.com/someone/project.git   # link the original repo.
git remote -v                                          # verify: origin=my fork, upstream=original.
```

> `upstream` 은 관례일 뿐 git 이 강제하는 이름은 아니지만, **반드시 이 이름을 쓴다.**
> 문서·스크립트·다른 기여자의 설명이 전부 이 이름을 전제한다.

### 4.3. Sync before you start

작업을 시작하기 전에 항상 upstream 의 최신 상태에서 출발한다. 이걸 건너뛰면 나중에 충돌한다.

```bash
git fetch upstream                             # get upstream's latest history (nothing merged yet).
git switch main
git merge upstream/main                        # fast-forward my main to upstream/main.
git push origin main                           # keep my fork's main in sync too.
```

### 4.4. Work on a topic branch

**`main` 에서 직접 작업하지 않는다.** 반드시 주제 branch 를 판다.

```bash
git switch -c fix/typo-in-readme upstream/main # branch off the freshest upstream state.
# ... edit files ...
git add -A && git commit -m "docs: fix typo in README"
```

이유는 협업 관점에서 셋이다.

1. PR 하나 = branch 하나. `main` 에서 작업하면 PR 을 여러 개 병행할 수 없다.
2. maintainer 가 수정을 요청하면 그 branch 에만 commit 을 더하면 된다.
3. 내 `main` 은 upstream 을 그대로 따라가는 **깨끗한 기준선**으로 남는다.

### 4.5. Push to my fork

```bash
git push -u origin fix/typo-in-readme          # first push sets the tracking link.
git push                                       # afterwards, just this.
```

### 4.6. Open the Pull Request

GitHub 이 fork 를 인식하므로, push 직후 원본 repo 페이지에 PR 생성 배너가 뜬다.

```text
base:  someone/project : main        ← 합쳐질 곳 (upstream)
head:  me/project      : fix/typo…   ← 내 변경 (fork)
```

```bash
gh pr create --repo someone/project --base main --head me:fix/typo-in-readme \
  --title "docs: fix typo in README" --body "..."
```

- **base 를 반드시 확인한다.** 잘못 두면 내 fork 안에서 끝나는 PR 이 된다.
- **"Allow edits by maintainers"** 를 켜 둔다. maintainer 가 내 branch 에 직접 commit 을
  더해 rebase·사소한 수정을 대신해 줄 수 있어 왕복이 줄어든다.

### 4.7. Respond to review

리뷰 코멘트가 달리면 **같은 branch 에 commit 을 더해 push** 한다. PR 은 branch 를 추적하므로
자동으로 갱신된다. PR 을 새로 열지 않는다.

```bash
git add -A && git commit -m "review: address feedback"
git push                                       # the existing PR updates itself.
```

---

## 5. Keeping a fork up to date

fork 는 **자동으로 갱신되지 않는다.** 만든 순간의 snapshot 이고, 그때부터 upstream 과 벌어진다.
오래 방치된 fork(stale fork)는 fork 협업에서 가장 흔한 사고 원인이다.

### 5.1. Merge vs Rebase

```bash
git fetch upstream                             # always start here.

# (a) merge — safe, keeps history as-is. Use when the branch is already pushed/shared.
git switch main && git merge upstream/main

# (b) rebase — replays my commits on top of upstream. Cleaner PR, but rewrites history.
git switch fix/typo-in-readme
git rebase upstream/main
git push --force-with-lease                    # required after rebase; never plain --force.
```

| | merge | rebase |
|---|---|---|
| 이력 | merge commit 이 남는다 | 선형으로 정리된다 |
| 안전성 | 안전 (이력 보존) | 이력 재작성 — force push 필요 |
| PR 가독성 | 관련 없는 merge commit 이 섞임 | 내 변경만 깔끔히 보임 |
| 권장 | 공유된 branch, 잘 모를 때 | **내 fork 의 내 branch** (혼자 쓰는 branch) |

> `--force-with-lease` 를 쓴다. `--force` 는 그 사이 올라온 남의 commit(maintainer 가
> "allow edits" 로 넣은 수정 포함)을 말없이 날린다.

### 5.2. Sync without a local clone

fork 의 `main` 만 맞추면 될 때는 GitHub 이 대신 해 준다.

- 웹: fork repo 상단 **Sync fork → Update branch**
- CLI: `gh repo sync me/project --branch main`

### 5.3. Cadence

| 시점 | 할 일 |
|---|---|
| 새 작업을 시작할 때 | `fetch upstream` 후 최신에서 branch 를 판다 (§4.3) |
| PR 이 오래 열려 있을 때 | 주기적으로 upstream 을 반영해 충돌을 미리 푼다 |
| PR 이 merge 된 뒤 | 내 `main` 을 sync 하고, 끝난 branch 는 지운다 |

```bash
git branch -d fix/typo-in-readme               # delete the merged local branch.
git push origin --delete fix/typo-in-readme    # delete it on my fork too.
git fetch --prune                              # clean up stale tracking refs.
```

---

## 6. Maintainer side

받는 쪽의 관점이다. fork 에서 오는 PR 은 **신뢰할 수 없는 코드**로 다루는 것이 기본이다.

### 6.1. Reviewing a PR from a fork

PR 의 코드를 로컬에서 돌려 보려면, fork 를 remote 로 추가할 필요 없이 PR ref 를 바로 가져온다.

```bash
git fetch origin pull/42/head:pr-42            # fetch PR #42 into a local branch 'pr-42'.
git switch pr-42                               # inspect / run tests locally.
gh pr checkout 42                              # same thing with GitHub CLI.
```

### 6.2. Pushing to a contributor's branch

기여자가 "Allow edits by maintainers" 를 켰다면, maintainer 는 그 fork 의 PR branch 에
직접 push 할 수 있다. 사소한 수정·rebase 를 대신해 왕복을 줄이는 용도다.

```bash
gh pr checkout 42                              # checks out with the fork remote wired up.
# ... small fix ...
git push                                       # goes back to the contributor's fork branch.
```

### 6.3. Merge strategy

| 방식 | 결과 | 언제 |
|---|---|---|
| Merge commit | 기여자의 commit 이 모두 남고 merge commit 추가 | 이력을 그대로 보존하고 싶을 때 |
| **Squash and merge** | commit 여러 개를 하나로 압축 | **fork PR 의 기본 선택.** WIP commit 이 정리된다 |
| Rebase and merge | 선형으로 이어 붙임 | 이력을 선형으로 유지하는 repo |

### 6.4. CI and secrets — the security boundary

fork PR 은 외부인이 보낸 코드다. GitHub Actions 는 이를 전제로 동작을 제한한다.

| Trigger | fork PR 에서 secret 접근 | `GITHUB_TOKEN` | 비고 |
|---|---|---|---|
| `pull_request` | ❌ 노출되지 않음 | 읽기 전용 | **기본이자 안전한 선택** |
| `pull_request_target` | ✅ 노출됨 | 쓰기 가능 | base repo 문맥에서 실행 — **위험** |

- `pull_request` 로 도는 CI 는 fork PR 에서 secret 을 못 받으므로, secret 이 필요한 job
  (배포, 외부 API 호출)은 fork PR 에서 실패하거나 건너뛰도록 설계한다.
- `pull_request_target` 은 **PR 의 코드를 checkout 해서 실행하면 안 된다.** 외부인이 보낸
  스크립트가 secret 을 쥔 채 실행되어 유출된다. 라벨 부착 같은 코드 실행 없는 작업에만 쓴다.
- 첫 기여자의 workflow 실행은 maintainer 승인이 필요하도록 설정할 수 있다
  (Settings → Actions → *Require approval for first-time contributors*).

> 같은 조직의 repo 라면 fork 대신 branch 를 쓰는 편이 CI 설계가 훨씬 단순해진다 (§3.3).

---

## 7. Fork mechanics and caveats

협업 중에 실제로 걸리는 지점들이다.

| 항목 | 내용 |
|---|---|
| Fork network | fork 들은 upstream 과 하나의 network 로 묶여 객체(commit)를 공유한다. |
| Private repo | private repo 의 fork 는 private 로 유지되며, 원본 접근 권한을 잃으면 fork 접근도 잃는다. |
| Visibility | public 원본의 fork 를 private 로 바꿀 수 없다. 그게 필요하면 fork 대신 mirror/복제 repo 를 만든다. |
| Issues / PR / Wiki | fork 에는 issue·PR·설정이 따라오지 않는다. 코드와 이력만 복사된다. |
| Deleting the upstream | upstream 이 지워져도 fork 는 남는다. 다만 PR 이력과 비교 기준은 잃는다. |
| Fork of a fork | 가능하지만 upstream 이 헷갈린다. 항상 **최상위 원본**을 `upstream` 으로 둔다. |
| One fork per account | 한 계정에 같은 repo 의 fork 는 하나다. 작업 분리는 fork 가 아니라 branch 로 한다. |
| Deleted objects | fork network 에 한 번 push 된 commit 은 fork 를 지워도 남을 수 있다. **secret 을 commit 했다면 지우는 것으로 끝나지 않는다** — 즉시 폐기·교체한다. |

---

## 8. Fork as a starting point (not collaboration)

fork 를 "원본에 기여" 가 아니라 "여기서 갈라져 나가 내 것으로 발전" 하려는 용도로 쓰기도 한다.
이때는 협업이 아니라 **분기(divergence)** 이므로 판단 기준이 다르다.

| 목적 | 권장 |
|---|---|
| 원본에 기여할 계획이 있다 | **fork 를 유지**한다. PR 경로와 upstream 추적이 유지된다. |
| 원본과 무관하게 갈 것이다 | fork 대신 **독립 repo** 로 만든다 (bare clone → 새 repo 로 push). |
| 원본 코드를 내 repo 의 일부로 품고 싶다 | fork 가 아니라 **subtree / vendoring** (→ `git-subtree-monorepo-convention.md`) |

```bash
# start an independent repo from someone else's code (no fork relationship)
git clone --bare https://github.com/someone/project.git
cd project.git
git push --mirror https://github.com/me/my-own-project.git
```

> 독립 repo 는 fork 배지·PR 경로가 없어 깨끗하지만, upstream 의 수정을 받아오려면 remote 를
> 직접 추가해 merge 해야 한다. **원본을 계속 따라갈 생각이면 fork 가 낫다.**

---

## 9. Common pitfalls

| 증상 | 원인 | 대처 |
|---|---|---|
| `remote: Permission denied` on push | 원본을 clone 하고 push 시도 | fork 를 만들고 `origin` 을 내 fork 로 (`git remote set-url origin <my-fork>`) |
| PR 에 남의 commit 수십 개가 섞임 | 오래된 fork 에서 branch 를 팠다 | `git rebase upstream/main` 후 force-with-lease |
| PR 을 열었는데 base 가 내 fork | PR 생성 시 base repo 를 확인 안 함 | PR 을 닫고 base 를 upstream 으로 다시 연다 |
| 리뷰 반영이 PR 에 안 보임 | 다른 branch 에 commit 했다 | PR 의 head branch 에 commit 하고 push |
| `main` 이 upstream 과 충돌 | 내 `main` 에서 직접 작업했다 | `git reset --hard upstream/main` 으로 기준선 복구 (작업은 별도 branch 로 옮긴 뒤) |
| fork 의 CI 가 secret 없다고 실패 | `pull_request` 는 fork 에 secret 을 안 준다 | secret 필요한 job 을 fork PR 에서 skip 하도록 조건 추가 (§6.4) |
| force push 로 남의 수정이 사라짐 | `--force` 사용 | 항상 `--force-with-lease` |

---

## 10. Command summary

```bash
# --- setup (once) ---
gh repo fork someone/project --clone --remote      # fork + clone + wire upstream in one go.
git remote add upstream https://github.com/someone/project.git
git remote -v                                      # origin = my fork, upstream = original.

# --- start a change ---
git fetch upstream                                 # refresh upstream history.
git switch -c topic/xyz upstream/main              # branch off the latest upstream.

# --- publish and propose ---
git push -u origin topic/xyz                       # push to MY fork.
gh pr create --repo someone/project --base main --head me:topic/xyz

# --- keep in sync ---
git fetch upstream && git switch main && git merge upstream/main && git push origin main
git switch topic/xyz && git rebase upstream/main && git push --force-with-lease

# --- maintainer ---
gh pr checkout 42                                  # try a fork PR locally.
git fetch origin pull/42/head:pr-42                # same, without GitHub CLI.

# --- cleanup after merge ---
git switch main && git branch -d topic/xyz
git push origin --delete topic/xyz
git fetch --prune
```

---

## 11. Glossary

- **upstream** — 원본 repo. fork 의 출처이며 PR 의 목적지다. remote 이름으로도 그대로 쓴다.
- **origin** — clone 한 repo 를 가리키는 기본 remote 이름. fork 협업에서는 **내 fork** 다.
- **fork network** — 같은 원본에서 갈라진 fork 들의 묶음. 객체를 공유한다.
- **Pull Request (PR)** — 내 branch 를 다른 branch·repo 에 합쳐 달라는 요청. 리뷰 단위다.
- **topic branch** — 하나의 변경 주제를 담는 branch. PR 하나에 대응한다.
- **stale fork** — upstream 과 오래 벌어진 fork. 충돌과 잘못된 PR 의 주원인이다.
- **squash merge** — PR 의 commit 여러 개를 하나로 압축해 합치는 방식.
