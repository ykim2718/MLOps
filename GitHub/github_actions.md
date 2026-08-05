# Auto-Sync Files from a Private Repo to a Public Repo with GitHub Actions

rev. 17

---

## 1. Purpose

Private repository 의 지정한 file 과 folder 를 public repository 로 자동 동기화한다. 이 문서에서
`<SOURCE_REPO>` 는 원본이 되는 private repository 를 가리키고, `<TARGET_REPO>` 는 복사본을 받는
public repository 를 가리킨다. 문서에서 사용한 용어의 정의는
[Appendix A. Terminology](#appendix-a-terminology) 에 정리한다.

```text
[private] <SOURCE_REPO>                   [public] <TARGET_REPO>
  |- docs/setup-guide.md         ---->      |- docs/setup-guide.md
  +- shared/**                   ---->      +- shared/**
```

Fig 1. One-way synchronization from the source repository to the target repository.

Private repository 에 GitHub Actions workflow 를 두고, workflow 의 `paths:` 에 지정한 file 이나
folder 가 바뀔 때마다 workflow 가 실행되어 public repository 로 push 한다. Trigger 는 markdown
file 에 국한되지 않으며, 지정한 경로이면 어떤 종류의 file 이나 folder 든 대상이 된다.

동기화는 원본에서 복사본으로 향하는 한 방향이다. 복사본은 push 할 때마다 원본 내용으로
덮어써지므로 직접 수정하지 않는다. 대상 repository 에 원래 있던 다른 file 은 복사 대상에
포함되지 않으므로 그대로 유지된다.

---

## 2. Deploy Key Authentication

Actions 가 기본 제공하는 `GITHUB_TOKEN` 은 자기 repository 안에서만 권한이 있으므로, 다른
repository 로 push 하려면 별도 인증이 필요하다. 여기서는 deploy key 를 사용한다.

Table 1. Deploy key versus fine-grained PAT.

| Aspect | Deploy key | Fine-grained PAT |
|---|---|---|
| Expiry | 없으므로 갱신이 필요하지 않다 | 있으므로 주기적으로 갱신한다 |
| Scope | Repository 한 개로 고정된다 | 여러 repository 를 지정할 수 있다 |
| Mechanism | SSH key pair 를 쓴다 | Token 문자열을 쓴다 |

하나의 SSH key 는 deploy key 로 repository 한 개에만 등록할 수 있으므로, secret 이름은 대상
repository 를 드러내는 `TARGET_DEPLOY_KEY` 형태로 짓는다. 대상 repository 가 늘어나면 대상 한
개당 key pair 한 세트를 새로 만든다.

### 2.1. Setup Steps

Deploy key 는 계정 설정이 아니라 대상 repository 의 Settings 탭에서 Security 영역의 Deploy keys
로 들어가 등록한다.

1. 로컬 terminal 에서 key pair 를 생성한다.

   ```bash
   ssh-keygen -t ed25519 -C "sync-to-target-repo" -f sync_key -N ""
   ```

   비공개 key 인 `sync_key` 와 공개 key 인 `sync_key.pub` 두 file 이 생성된다.

2. 공개 key 를 대상 repository 에 등록한다. `<TARGET_REPO>` 의 Settings 에서 Deploy keys 로 들어가
   Add deploy key 를 누르고, Key 항목에 `sync_key.pub` 의 내용을 붙여 넣은 뒤 Allow write access 를
   체크한다. 이 항목을 체크해야 push 가 가능하다.

3. 비공개 key 를 원본 repository 에 secret 으로 등록한다. `<SOURCE_REPO>` 의 Settings 에서 Secrets
   and variables 의 Actions 로 들어가 New repository secret 을 누르고, 이름은 `TARGET_DEPLOY_KEY`
   로 하며 값은 `sync_key` file 의 전체 내용을 넣는다.

비공개 key file 인 `sync_key` 는 secret 으로 등록한 뒤 로컬에서 삭제한다.

---

## 3. Workflow File

원본 repository 의 `.github/workflows/sync-target.yml` 로 저장한다.

Trigger 인 `paths:` 와 실제 복사를 수행하는 `Copy files` 단계는 별개다. `paths:` 는 workflow 를
언제 실행할지만 정하고, 무엇을 복사할지는 복사 단계가 정한다. 대상을 추가하려면 이 두 곳을 함께
고친다.

복사된 file 은 원본과 완전히 동일하며 workflow 가 내용을 덧붙이거나 고치지 않는다. 따라서 대상
repository 의 file 은 원본과 byte 단위로 일치하고, 복사 단계가 매번 원본 내용으로 덮으므로 대상
쪽에서 직접 수정한 내용은 다음 실행에서 사라진다.

```yaml
# .github/workflows/sync-target.yml
name: Sync files to the public target repo

on:
  push:
    branches: [main]                       # source branch
    paths:
      - 'docs/setup-guide.md'
      - 'shared/**'                        # add more files or folders here
  workflow_dispatch:                       # manual run from the Actions tab

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout the source repo
        uses: actions/checkout@v5

      - name: Checkout the target repo via deploy key
        uses: actions/checkout@v5
        with:
          repository: <TARGET_REPO>
          ssh-key: ${{ secrets.TARGET_DEPLOY_KEY }}
          path: target

      - name: Copy files
        run: |
          # single file
          mkdir -p target/docs
          cp docs/setup-guide.md target/docs/

          # whole folder mirrored
          mkdir -p target/shared
          rsync -av --delete shared/ target/shared/

      - name: Commit and push if changed
        run: |
          cd target
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add -A
          if git diff --staged --quiet; then
            echo "No change - skip"
          else
            git commit -m "Sync files from the source repo"
            git push
          fi
```

마지막 step 의 `git diff --staged --quiet` 는 stage 에 올라온 변경이 없으면 성공을 반환하므로,
복사 결과가 기존 내용과 같을 때는 commit 과 push 를 건너뛴다. 이 조건이 없으면 실행할 때마다 빈
commit 이 쌓인다.

### 3.1. Execution Flow

1. Trigger 단계에서는 `main` 의 `paths:` 에 지정한 file 이나 folder 가 바뀌어 push 되면 실행되며,
   수동 실행도 가능하다.
2. 원본 checkout 단계에서는 private repository 를 작업 folder 로 받는다.
3. 대상 checkout 단계에서는 deploy key secret 으로 대상 repository 를 `target/` 으로 받는다.
4. 복사 단계에서는 지정한 file 과 folder 를 대상 위치로 복사한다.
5. Commit 단계에서는 내용이 달라졌을 때만 commit 하고 push 하며, 동일하면 건너뛴다.

---

## 4. Multiple Target Handling

Workflow file 한 개로 여러 대상을 처리한다. Trigger 인 `paths:` 와 복사 명령을 함께 늘리면 되며,
세 가지 방식이 있다.

### 4.1. File List

File 마다 목적지가 다를 때 쓴다.

```yaml
    paths:
      - 'docs/setup-guide.md'
      - 'docs/another-guide.md'
```

복사 단계에서 각 file 을 원하는 위치로 `cp` 한다.

### 4.2. Whole Folder Mirroring

특정 folder 전체를 내보낼 때 쓴다.

```yaml
    paths:
      - 'shared/**'
```

```bash
mkdir -p target/shared
rsync -av --delete shared/ target/shared/
```

`rsync -av --delete` 는 folder 안의 모든 file 과 하위 folder 를 대상에 복사하고 갱신하며, 원본에서
삭제된 file 은 대상에서도 삭제해 양쪽을 완전히 동일하게 맞춘다. `--delete` 를 빼면 추가와 수정만
반영되고 삭제는 반영되지 않는다.

### 4.3. Pattern Matching

특정 folder 의 특정 확장자만 대상으로 삼을 때 쓴다.

```yaml
    paths:
      - 'docs/*.md'
```

---

## 5. Difference from PAT

대상 repository 를 checkout 하는 한 줄만 다르다. Deploy key 는
`ssh-key: ${{ secrets.TARGET_DEPLOY_KEY }}` 를 쓰고, PAT 은 `token: ${{ secrets.TARGET_PAT }}` 를
쓴다.

`ssh-key` 를 쓰면 checkout 이 SSH remote 로 자동 설정되어 이후의 `git push` 가 그 key 로
인증되므로, 별도의 ssh-agent 설정이 필요 없다.

---

## Appendix A. Terminology

+ **CI/CD (Continuous Integration / Continuous Delivery)** — Code 변경을 자동으로 build 하고 test 하며 배포하는 개발 자동화 방식이다.
+ **Deploy key** — 특정 repository 한 개에만 연결되는 SSH 공개 key 다. 쓰기 권한을 부여하면 그 repository 에 push 할 수 있고 만료가 없다. 계정 설정이 아니라 해당 repository 의 Settings 에서 등록하며, 같은 key 를 두 repository 에 deploy key 로 등록할 수 없다.
+ **Ed25519** — SSH key 생성에 쓰는 최신 타원곡선 암호 algorithm 이다. 짧고 안전해 RSA 보다 권장된다.
+ **git diff --staged** — Stage 에 올라온 변경을 보여 주는 명령이다. `--quiet` 를 붙이면 출력 없이 변경 유무만 종료 code 로 알려 주므로 조건 분기에 쓴다.
+ **GitHub Actions** — GitHub 에 내장된 CI/CD 자동화 도구이며 push 같은 event 에 반응해 workflow 를 실행한다.
+ **GITHUB_TOKEN** — Workflow 실행 시 GitHub 이 자동 발급하는 임시 token 이다. 해당 repository 내부 작업에만 권한이 있어 다른 repository 에는 쓸 수 없다.
+ **PAT (Personal Access Token)** — GitHub 계정 비밀번호 대신 사용하는 인증용 token 문자열이다. 권한 범위와 만료일을 지정할 수 있으며, fine-grained PAT 은 특정 repository 와 특정 권한으로 범위를 좁힌 최신 방식이다.
+ **paths** — `on: push:` 아래의 trigger filter 다. 여기에 지정한 file 이나 folder 가 바뀔 때만 workflow 가 실행되며 확장자에 국한되지 않는다.
+ **Repository** — Code 와 file 과 history 를 담는 저장 단위이며 private 과 public 으로 구분된다.
+ **rsync** — Folder 단위로 file 을 동기화하는 명령이다. `-a` 는 하위 구조를 보존하고, `-v` 는 log 를 출력하며, `--delete` 는 원본에서 지운 file 을 대상에서도 지운다.
+ **Secret** — Repository 나 organization 에 저장하는 암호화된 값이다. Workflow 안에서 `${{ secrets.NAME }}` 으로 참조하며 log 에 노출되지 않고 이름은 대소문자를 구분한다.
+ **SSH (Secure Shell)** — Network 로 원격 server 에 안전하게 접속하고 통신하는 암호화 protocol 이다. GitHub 은 SSH key pair 로 push 와 pull 인증을 지원한다.
+ **SSH key pair** — 짝을 이루는 두 개의 key 다. 공개 key 는 server 에 등록하고 비공개 key 는 본인만 보관하며, 공개 key 로 잠근 것은 짝이 되는 비공개 key 로만 열 수 있어 신원이 증명된다.
+ **Workflow** — `.github/workflows/` 안의 YAML file 로 정의하는 자동화 작업 묶음이며 하나 이상의 job 과 step 으로 구성된다.
+ **workflow_dispatch** — Workflow 를 Actions 탭에서 수동으로 실행할 수 있게 해 주는 trigger 다.
+ **YAML (YAML Ain't Markup Language)** — 들여쓰기로 구조를 표현하는 사람이 읽기 쉬운 설정 file 형식이며 workflow 정의에 사용된다.
