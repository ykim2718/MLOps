# Git Fork — Collaboration Across Repository Boundaries

rev. 5

---

## 1. Purpose

Fork 는 다른 사람의 repository 를 자기 계정 아래 복사본으로 만드는 기능이다. 이 문서는 fork 를
collaboration 관점에서 정리한다. 명령을 어떻게 입력하는가보다, 누가 어디에 쓸 권한을 가지며
변경이 어떤 경로로 원본에 합쳐지는가를 중심에 둔다.

등장하는 역할은 둘이며 문서 전체에서 이 두 낱말만 쓴다. Contributor 는 변경을 만들어 합쳐 달라고
요청하는 의뢰자이고, Maintainer 는 그 요청을 검토해 원본에 합치는 승인자다. Fork 는 git 자체의
기능이 아니라 GitHub 이 제공하는 기능이며, 원본에 쓰기 권한이 없는 Contributor 가 기여할 수 있게
해 주는 장치다. 문서에서 사용한 용어의 정의는
[Appendix A. Terminology](#appendix-a-terminology) 에 정리한다.

```text
  Contributor (requester)                        Maintainer (approver)
  ==============================                 ==============================
  owns the fork and the local clone              owns the original repository

  [local] Contributor's machine
       |   push: allowed
       v
  [origin] <CONTRIBUTOR>/project  -------------> [upstream] <OWNER>/project
       ^        pull request: ask to merge            |   review and merge:
       |                                              |   Maintainer only
       +--------- fork: server-side copy -------------+
                  performed once by GitHub

  permissions, not a sequence of steps
  ---------------------------------------------------------------
  action                            Contributor   Maintainer
  push into [origin], the fork      yes           no
  push directly into [upstream]     no            yes
  merge a pull request              no            yes
```

Fig 1. Roles, repositories, and the permission each role holds.

Contributor 의 변경은 local 에서 origin 으로 push 되고, origin 에서 upstream 으로는 pull request 를
통해서만 들어가며, 그 pull request 를 실제로 합치는 역할은 Maintainer 다. 이 비대칭이 fork
collaboration 의 핵심이다.

---

## 2. Fork, Clone, and Branch

세 가지 모두 복사처럼 보이지만, 복사가 일어나는 장소와 권한 경계가 서로 다르다.

Table 1. Comparison of fork, clone, and branch.

| Aspect | Fork | Clone | Branch |
|---|---|---|---|
| Performed by | GitHub server | git on the local machine | git in the same repo |
| Copy location | Contributor 의 GitHub 계정 | Contributor 의 local machine | 같은 repository 안 |
| Creates a new repo | 생성한다 | 생성하지 않는다 | 생성하지 않는다 |
| Access to the original | 읽기 권한만 필요하다 | 읽기 권한만 필요하다 | 쓰기 권한이 필요하다 |
| Path back to the original | pull request | push (권한이 있을 때) | merge 또는 pull request |
| Link to the original | fork network 로 기록된다 | remote 로 연결된다 | 같은 history 를 공유한다 |

Branch 는 같은 repository 안에서 작업을 나누는 방법이며, 쓰기 권한을 가진 Contributor 의 기본
도구다. Clone 은 어떤 repository 든 로컬로 내려받는 동작이고, 권한과 무관하며 그 자체로는 기여
경로가 아니다. Fork 는 쓰기 권한이 없는 Contributor 가 자기 소유의 push 대상을 확보하는 방법이다.

Clone 만으로는 push 할 곳이 없다. 권한이 없는 repository 를 clone 한 뒤 push 하면 거절된다.
Fork 는 Contributor 가 push 할 수 있는 repository 를 먼저 만들어 두는 단계다.

---

## 3. Collaboration Models

Collaboration 방식은 크게 두 가지이며, fork 를 쓰는지 여부로 갈린다.

### 3.1. Shared Repository Model

Repository 하나를 여러 사람이 공유하고, 각자 branch 를 만들어 pull request 를 올린다. Fork 가
없으므로 Contributor 와 Maintainer 가 같은 repository 안에서 움직인다.

```text
     [shared repo] <OWNER>/project — both roles have write access here

  Contributor (requester)                    Maintainer (approver)
  pushes a topic branch                      reviews and merges into main

  main --+-- feature/a --pull request-->  review  -->  merged into main
         +-- feature/b --pull request-->  review  -->  merged into main
              ^                                             ^
              | Contributor pushes here                     | Maintainer merges here
              | (no fork involved)                          |
```

Fig 2. Shared repository model, where both roles work in one repository.

이 방식은 Contributor 전원이 신뢰받고 쓰기 권한을 가진다는 것을 전제한다. 구조가 단순해서 remote
가 origin 하나뿐이고 별도의 동기화 개념이 없다. 대신 아무나 참여시킬 수 없으며, 권한을 주는 순간
repository 전체에 대한 권한이 된다. 사내 팀, 소규모 project, 개인 repository 가 여기에 해당하고,
실제 업무 repository 는 대부분 이 모델을 쓴다.

### 3.2. Fork and Pull Model

Contributor 는 fork 를 만들어 자기 fork 에 push 한 뒤, upstream 으로 pull request 를 올린다.

```text
   [upstream] <OWNER>/project   <--pull request--  [origin] <CONTRIBUTOR>/project
   Maintainer merges here                          Contributor pushes here
          |                                             ^
          |  Contributor has read access only           |  push
          +---------------------------------------------+--- [local] Contributor
```

Fig 3. Fork and pull model with the two roles.

이 방식은 Contributor 에게 권한을 주지 않고도 기여를 받아야 하는 상황을 전제한다. 권한 없이
누구나 기여할 수 있고, 원본은 Maintainer 가 merge 하기 전에는 바뀌지 않는다. 대신 remote 가 origin 과
upstream 둘이 되고, fork 를 최신 상태로 유지하는 부담이 생긴다. Open source, 외부 협력사나 단기
Contributor 의 기여, 사고 위험이 큰 중요 repository 가 여기에 해당한다.

### 3.3. Model Selection

Table 2. Model selection by situation.

| Situation | Recommended model |
|---|---|
| 같은 팀이고 서로 신뢰하며 쓰기 권한을 줄 수 있다 | Branch 와 pull request 를 쓰고 fork 는 쓰지 않는다 |
| 외부 Contributor 이거나 권한을 줄 수 없다 | Fork 와 pull request 를 쓴다 |
| 원본을 다른 방향으로 발전시키려 한다 | Fork 를 쓰거나 독립 repository 를 만든다 |
| 남의 repository 를 참고하거나 실험만 한다 | Clone 으로 충분하다 |

Collaboration 을 하려면 fork 를 해야 한다는 것은 오해다. 권한을 줄 수 있는 상대라면 branch 가
더 낫다. Fork 는 권한 경계를 넘기 위한 도구이지 collaboration 의 기본형이 아니다.

---

## 4. Contributor Workflow

Contributor 입장에서의 전체 흐름이다. 4.1 과 4.2 는 최초 한 번만 수행하고, 4.3 부터 4.7 까지는
기여할 때마다 반복한다.

### 4.1. Fork Creation

GitHub 웹 화면에서 원본 repository 우상단의 Fork 를 누른다. GitHub CLI 로도 같은 일을 한다.

```bash
gh repo fork <OWNER>/project --clone       # fork and clone in one step
gh repo fork <OWNER>/project --remote      # also set the upstream remote automatically
```

### 4.2. Remote Configuration

Fork collaboration 의 규약은 remote 이름 두 개다. 이 이름을 지키면 이후의 모든 명령이 그대로
통한다.

Table 3. Remote roles in a fork workflow.

| Remote | Points to | Access | Used for |
|---|---|---|---|
| `origin` | Contributor 의 fork | 읽기와 쓰기가 가능하다 | Contributor 가 자기 branch 를 push 한다 |
| `upstream` | Maintainer 가 소유한 원본 repository | 읽기만 가능하다 | 최신 변경을 fetch 한다 |

```bash
git clone https://github.com/<CONTRIBUTOR>/project.git   # clone the fork; it becomes 'origin'
cd project
git remote add upstream https://github.com/<OWNER>/project.git   # link the original repo
git remote -v                              # verify: origin is the fork, upstream is the original
```

`upstream` 은 git 이 강제하는 이름이 아니라 관례다. 그러나 다른 Contributor 의 설명과 대부분의
안내가 이 이름을 전제하므로 그대로 따르는 것이 좋다.

### 4.3. Pre-work Synchronization

작업을 시작하기 전에 항상 upstream 의 최신 상태에서 출발한다. 이 단계를 건너뛰면 나중에 충돌이
생긴다.

```bash
git fetch upstream                         # get upstream history; nothing is merged yet
git switch main
git merge upstream/main                    # fast-forward the fork's main to upstream/main
git push origin main                       # keep the fork's main in sync as well
```

### 4.4. Topic Branch

`main` 에서 직접 작업하지 않고 반드시 topic branch 를 만든다.

```bash
git switch -c fix/typo-in-readme upstream/main   # branch off the freshest upstream state
git add -A
git commit -m "docs: fix typo in README"
```

Collaboration 관점에서 이유는 세 가지다. 첫째, pull request 하나가 branch 하나에 대응하므로
`main` 에서 작업하면 pull request 를 여러 개 병행할 수 없다. 둘째, Maintainer 가 수정을 요청하면
해당 branch 에 commit 을 더하는 것만으로 반영된다. 셋째, Contributor 의 `main` 이 upstream 을
그대로 따라가는 깨끗한 기준선으로 남는다.

### 4.5. Push to the Fork

```bash
git push -u origin fix/typo-in-readme      # the first push sets the tracking link
git push                                   # afterwards this is enough
```

### 4.6. Pull Request Creation

GitHub 이 fork 관계를 알고 있으므로, push 직후 원본 repository 화면에 pull request 생성 안내가
나타난다.

```text
  base:  <OWNER>/project       : main       <- upstream; the Maintainer merges here
  head:  <CONTRIBUTOR>/project : fix/typo   <- the fork; the Contributor pushed here
```

Fig 4. Pull request direction from the Contributor's fork to the Maintainer's upstream.

```bash
gh pr create --repo <OWNER>/project --base main --head <CONTRIBUTOR>:fix/typo-in-readme \
  --title "docs: fix typo in README" --body "..."
```

Base 를 반드시 확인한다. Base 를 잘못 지정하면 Contributor 의 fork 안에서 끝나는 pull request 가 된다. 또한
Allow edits by maintainers 를 켜 두면 Maintainer 가 Contributor 의 branch 에 직접 commit 을 더해
사소한 수정이나 rebase 를 대신할 수 있어 왕복이 줄어든다.

### 4.7. Review Response

Review comment 가 달리면 같은 branch 에 commit 을 더해 push 한다. Pull request 는 branch 를
추적하므로 자동으로 갱신되며, pull request 를 새로 열지 않는다.

```bash
git add -A
git commit -m "review: address feedback"
git push                                   # the existing pull request updates itself
```

---

## 5. Fork Synchronization

Fork 는 자동으로 갱신되지 않는다. 만들어진 시점의 snapshot 이며, 그때부터 upstream 과 벌어진다.
오래 방치된 fork 는 fork collaboration 에서 가장 흔한 사고 원인이다.

### 5.1. Merge and Rebase

```bash
git fetch upstream                         # always start here

git switch main                            # merge keeps history as it is
git merge upstream/main

git switch fix/typo-in-readme              # rebase replays the Contributor's commits onto upstream
git rebase upstream/main
git push --force-with-lease                # required after a rebase; never use plain --force
```

Table 4. Merge versus rebase when updating a fork.

| Aspect | Merge | Rebase |
|---|---|---|
| History | Merge commit 이 남는다 | 선형으로 정리된다 |
| Safety | History 를 보존하므로 안전하다 | History 를 재작성하므로 force push 가 필요하다 |
| Pull request readability | 관련 없는 merge commit 이 섞인다 | Contributor 의 변경만 깔끔하게 보인다 |
| Recommended for | 이미 공유된 branch 이거나 판단이 서지 않을 때 | Contributor 혼자 쓰는 fork 의 topic branch |

`--force-with-lease` 를 쓴다. `--force` 는 그 사이에 올라온 다른 사람의 commit 을 말없이 지우며,
Maintainer 가 Allow edits by maintainers 로 넣은 수정도 함께 사라진다.

### 5.2. Synchronization without a Local Clone

Fork 의 `main` 만 맞추면 되는 경우에는 GitHub 이 대신 처리한다. 웹 화면에서는 fork repository
상단의 Sync fork 를 누르고, CLI 에서는 다음을 실행한다.

```bash
gh repo sync <CONTRIBUTOR>/project --branch main   # update the fork's main from upstream
```

### 5.3. Synchronization Cadence

Table 5. When to synchronize a fork.

| Timing | Action |
|---|---|
| 새 작업을 시작할 때 | Upstream 을 fetch 한 뒤 최신 상태에서 branch 를 만든다 |
| Pull request 가 오래 열려 있을 때 | 주기적으로 upstream 을 반영해 충돌을 미리 해소한다 |
| Pull request 가 merge 된 뒤 | Fork 의 `main` 을 동기화하고 끝난 branch 를 정리한다 |

### 5.4. Cleanup after Merge

```bash
git switch main
git branch -d fix/typo-in-readme           # delete the merged local branch
git push origin --delete fix/typo-in-readme   # delete it on the fork as well
git fetch --prune                          # clean up stale tracking refs
```

---

## 6. Maintainer Workflow

기여를 받는 쪽의 관점이다. Fork 에서 오는 pull request 는 신뢰할 수 없는 code 로 다루는 것이
기본이다.

### 6.1. Pull Request Review

Pull request 의 code 를 로컬에서 실행해 보려면, Contributor 의 fork 를 remote 로 추가할 필요 없이
pull request ref 를 바로 가져온다.

```bash
git fetch origin pull/42/head:pr-42        # fetch pull request 42 into a local branch
git switch pr-42                           # inspect and run tests locally
gh pr checkout 42                          # the same thing with GitHub CLI
```

### 6.2. Push to a Contributor Branch

Contributor 가 Allow edits by maintainers 를 켜 두었다면, Maintainer 는 그 fork 의 pull request
branch 에 직접 push 할 수 있다. 사소한 수정이나 rebase 를 대신해 왕복을 줄이는 용도로 쓴다.

```bash
gh pr checkout 42                          # checks out with the fork remote wired up
git push                                   # goes back to the Contributor's fork branch
```

### 6.3. Merge Strategy

Table 6. Merge strategies for a pull request from a fork.

| Strategy | Result | Use when |
|---|---|---|
| Merge commit | Contributor 의 commit 이 모두 남고 merge commit 이 추가된다 | History 를 그대로 보존하려 할 때 쓴다 |
| Squash and merge | 여러 commit 이 하나로 압축된다 | Fork pull request 의 기본 선택이며 작업 중 commit 이 정리된다 |
| Rebase and merge | 선형으로 이어 붙는다 | History 를 선형으로 유지하는 repository 에서 쓴다 |

### 6.4. CI Secret Boundary

Fork pull request 는 외부인이 보낸 code 다. GitHub Actions 는 이를 전제로 동작을 제한한다.

Table 7. Workflow trigger behavior on a pull request from a fork.

| Trigger | Secret access | Token permission | Note |
|---|---|---|---|
| `pull_request` | 노출되지 않는다 | 읽기 전용이다 | 기본이자 안전한 선택이다 |
| `pull_request_target` | 노출된다 | 쓰기가 가능하다 | Base repository 문맥에서 실행되므로 위험하다 |

`pull_request` 로 도는 CI 는 fork pull request 에서 secret 을 받지 못하므로, secret 이 필요한 job 은
fork pull request 에서 실패하거나 건너뛰도록 설계한다. `pull_request_target` 은 pull request 의
code 를 checkout 해서 실행하면 안 된다. 외부인이 보낸 script 가 secret 을 쥔 채 실행되어 유출될 수
있으며, label 부착처럼 code 실행이 없는 작업에만 쓴다. 저장소 설정에서 첫 Contributor 의 workflow 실행에
Maintainer 승인을 요구하도록 지정할 수도 있다.

같은 조직의 repository 라면 fork 대신 branch 를 쓰는 편이 CI 설계가 훨씬 단순해진다.

---

## 7. Fork Mechanics

Collaboration 중에 실제로 문제가 되는 fork 의 성질이다.

Table 8. Fork mechanics and constraints.

| Item | Behavior |
|---|---|
| Fork network | Fork 들은 upstream 과 하나의 network 로 묶여 commit object 를 공유한다 |
| Private repository | Private repository 의 fork 는 private 로 유지되며, 원본 접근 권한을 잃으면 fork 접근도 잃는다 |
| Visibility | Public 원본의 fork 를 private 로 바꿀 수 없으며, 그것이 필요하면 별도의 복제 repository 를 만든다 |
| Issue and pull request | Fork 에는 issue, pull request, 설정이 따라오지 않고 code 와 history 만 복사된다 |
| Deleted upstream | Upstream 이 삭제되어도 fork 는 남지만 pull request 이력과 비교 기준을 잃는다 |
| Fork of a fork | 가능하지만 upstream 이 모호해지므로 항상 최상위 원본을 `upstream` 으로 둔다 |
| One fork per account | 한 계정에 같은 repository 의 fork 는 하나이며, 작업 분리는 fork 가 아니라 branch 로 한다 |
| Deleted object | Fork network 에 한 번 push 된 commit 은 fork 를 지워도 남을 수 있으므로, secret 을 commit 했다면 삭제로 끝내지 말고 즉시 폐기하고 교체한다 |

누가 fork 를 만들 수 있는지는 원본의 공개 범위와 설정에 따라 달라진다. 조건은
[Appendix B. Fork Permission Conditions](#appendix-b-fork-permission-conditions) 에 정리한다.

---

## 8. Fork as a Divergence Point

Fork 를 원본에 기여하기 위해서가 아니라, 원본에서 갈라져 나와 독자적으로 발전시키기 위해 쓰기도
한다. 이 경우는 collaboration 이 아니라 divergence 이므로 판단 기준이 다르다.

Table 9. Choice by intent.

| Intent | Recommended approach |
|---|---|
| 원본에 기여할 계획이 있다 | Fork 를 유지하며 pull request 경로와 upstream 추적을 살린다 |
| 원본과 무관하게 발전시킨다 | Fork 대신 독립 repository 를 만든다 |
| 원본 code 를 자기 repository 의 일부로 품는다 | Fork 가 아니라 subtree 나 vendoring 을 쓴다 |

```bash
git clone --bare https://github.com/<OWNER>/project.git   # start an independent repo
cd project.git
git push --mirror https://github.com/<CONTRIBUTOR>/my-own-project.git
```

독립 repository 는 fork badge 와 pull request 경로가 없어 깔끔하지만, upstream 의 수정을
받아오려면 remote 를 직접 추가해 merge 해야 한다. 원본을 계속 따라갈 생각이라면 fork 가 낫다.

---

## 9. Pitfalls

Table 10. Common pitfalls and remedies.

| Symptom | Cause | Remedy |
|---|---|---|
| Push 가 permission denied 로 거절된다 | 원본을 clone 하고 push 를 시도했다 | Fork 를 만들고 `git remote set-url origin <FORK_URL>` 로 origin 을 자기 fork 로 바꾼다 |
| Pull request 에 다른 Contributor 의 commit 이 대량으로 섞인다 | 오래된 fork 에서 branch 를 만들었다 | `git rebase upstream/main` 을 실행한 뒤 `--force-with-lease` 로 push 한다 |
| Pull request 의 base 가 Contributor 의 fork 로 잡힌다 | Pull request 를 만들 때 base repository 를 확인하지 않았다 | Pull request 를 닫고 base 를 upstream 으로 지정해 다시 연다 |
| Review 반영이 pull request 에 보이지 않는다 | 다른 branch 에 commit 했다 | Pull request 의 head branch 에 commit 하고 push 한다 |
| Fork 의 `main` 이 upstream 과 충돌한다 | Fork 의 `main` 에서 직접 작업했다 | 작업을 별도 branch 로 옮긴 뒤 `git reset --hard upstream/main` 으로 기준선을 복구한다 |
| Fork 의 CI 가 secret 이 없다며 실패한다 | `pull_request` 는 fork 에 secret 을 주지 않는다 | Secret 이 필요한 job 을 fork pull request 에서 건너뛰도록 조건을 추가한다 |
| Force push 로 Maintainer 나 다른 Contributor 의 수정이 사라진다 | `--force` 를 사용했다 | 항상 `--force-with-lease` 를 사용한다 |

---

## 10. Command Summary

```bash
# setup, performed once
gh repo fork <OWNER>/project --clone --remote
git remote add upstream https://github.com/<OWNER>/project.git
git remote -v

# start a change
git fetch upstream
git switch -c topic/xyz upstream/main

# publish and propose
git push -u origin topic/xyz
gh pr create --repo <OWNER>/project --base main --head <CONTRIBUTOR>:topic/xyz

# keep the fork in sync
git fetch upstream
git switch main
git merge upstream/main
git push origin main
git switch topic/xyz
git rebase upstream/main
git push --force-with-lease

# maintainer side
gh pr checkout 42
git fetch origin pull/42/head:pr-42

# cleanup after merge
git switch main
git branch -d topic/xyz
git push origin --delete topic/xyz
git fetch --prune
```

---

## Appendix A. Terminology

+ **Contributor** — 변경을 만들어 pull request 로 합쳐 달라고 요청하는 의뢰자다. 원본 repository 에 쓰기 권한이 없고 자기 fork 에만 push 한다.
+ **Fork network** — 같은 원본에서 갈라져 나온 fork 들의 묶음이며 commit object 를 공유한다.
+ **Maintainer** — 원본 repository 에 대한 쓰기 권한을 가지고 pull request 를 검토하고 merge 하는 사람이다.
+ **Origin** — Clone 한 repository 를 가리키는 기본 remote 이름이며, fork collaboration 에서는 Contributor 의 fork 를 가리킨다.
+ **Pull request** — 자기 branch 를 다른 branch 나 repository 에 합쳐 달라고 요청하는 단위이며 review 의 단위이기도 하다.
+ **Squash merge** — Pull request 의 여러 commit 을 하나로 압축해 합치는 방식이다.
+ **Stale fork** — Upstream 과 오래 벌어진 fork 이며 충돌과 잘못된 pull request 의 주된 원인이다.
+ **Topic branch** — 하나의 변경 주제를 담는 branch 이며 pull request 하나에 대응한다.
+ **Upstream** — Fork 의 출처가 되는 원본 repository 이며 pull request 의 목적지다. Remote 이름으로도 같은 낱말을 쓴다.

---

## Appendix B. Fork Permission Conditions

Fork 는 요청과 승인을 주고받는 절차가 아니다. Maintainer 가 개별 fork 를 승인하는 화면은 없으며,
Maintainer 가 정하는 것은 fork 를 허용할지 말지라는 스위치 하나다. 따라서 fork 가 만들어졌다는
사실 자체는 어떤 권한도 뜻하지 않으며, Maintainer 의 실질적인 통제는 pull request 를 merge 하는
단계에서 이루어진다.

Table 11. Who can create a fork, by repository visibility.

| Original repository | Who can fork | Maintainer's control |
|---|---|---|
| Public repository | 로그인한 사용자면 누구나 할 수 있다 | Fork 자체는 막을 수 없고 merge 단계에서 통제한다 |
| Organization 소유 private repository | 읽기 권한을 가진 Contributor 만 할 수 있으며 forking 허용 설정이 켜져 있어야 한다 | 초대 여부와 forking 설정 두 가지로 통제한다 |
| 개인 계정 소유 private repository | 읽기 권한을 부여받은 Contributor 만 할 수 있다 | 초대 여부로 통제한다 |

Public repository 에서 forking 을 끌 수 없는 이유는 공개 자체가 열람과 fork 를 허용한다는 전제
위에 서 있기 때문이다. 그래서 public repository 의 Maintainer 는 fork 단계에서 아무것도 막지
못하고, 원본이 바뀌는 지점인 merge 에서만 통제한다.

Private repository 에서는 조건이 두 겹이다. 첫째, Contributor 를 초대해 읽기 권한을 주어야 한다.
초대되지 않으면 repository 의 존재조차 보이지 않으므로 fork 대상이 되지 않으며, 이 초대가 사실상
승인 행위다. 둘째, organization 소유라면 조직 정책과 repository 설정에서 private repository 의
forking 을 허용해야 한다. 이 설정은 기본이 꺼짐이므로, 읽기 권한이 있어도 설정이 꺼져 있으면
fork 가 만들어지지 않는다.

Private repository 의 fork 에는 추가 제약이 따른다. Fork 는 private 로 만들어지고 같은 fork
network 안에 머무르며 public 으로 바꿀 수 없다. 원본에 대한 접근 권한이 회수되면 그 사람의 fork
도 함께 제거되어, private code 가 fork 형태로 남지 않는다.

읽기 권한을 이미 준 상대라면 fork 보다 branch 가 낫다. 쓰기 권한을 주고 3.1 의 shared repository
model 로 가면 remote 가 하나로 끝나고 CI 설계도 단순해진다. Fork 는 권한을 줄 수 없는 상대를 위한
도구이므로, 권한을 줄 수 있는 상황에서 fork 를 고르면 관리 비용만 늘어난다.

Self-hosted git service 는 정책이 다를 수 있다. 관리자가 forking 을 인스턴스 단위로 막을 수 있어
public repository 라도 fork 버튼이 보이지 않을 수 있으므로, 해당 인스턴스의 설정을 확인한다.
