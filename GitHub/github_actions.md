# Auto-Sync Files from Private to Public Repo with GitHub Actions

Rev. 16 | Created: 2026-07-18 | Updated: 2026-08-14 21:32 CDT

---

## 1. Purpose

Private repo `ykim2718/claude` 의 지정한 파일·폴더를
Public repo `ykim2718/MLOps` 로 자동 동기화한다.

```
[private] ykim2718/claude                         [public] ykim2718/MLOps
  ├ Ubuntu/ubuntu-nomachine-remote-setup.md  ──▶     ├ Ubuntu/ubuntu-nomachine-remote-setup.md
  └ VS-Code/**                               ──▶     └ VS-Code/**
```

Private repo에 GitHub Actions 워크플로를 두고, 워크플로의 `paths:`에 지정한
파일이나 폴더가 바뀔 때마다 워크플로가 실행되어 Public repo(`MLOps`)로 push 한다.
트리거는 마크다운 파일에 국한되지 않으며, 지정한 경로면 어떤 종류의 파일·폴더든 대상이 된다.

동기화는 A(원본) → B(복사본) 한 방향이다. B는 push할 때마다 A 내용으로 덮어써지므로
직접 수정하지 않는다. B가 복사본임을 알리기 위해, 이번 실행이 실제로 바꾼 마크다운 문서에만
안내 배너를 끼워넣는다(3절 참고). MLOps에 원래 있던 다른 문서에는 배너를 붙이지 않는다.

---

## 2. Authentication: Deploy Key

Actions 기본 `GITHUB_TOKEN`은 자기 repo 안에서만 권한이 있으므로,
다른 repo(`MLOps`)에 push 하려면 별도 인증이 필요하다. Deploy Key를 사용한다.

| | Deploy Key | Fine-grained PAT |
|---|---|---|
| 만료 | 없음 (갱신 불필요) | 있음 (주기적 갱신) |
| 범위 | repo 1개로 고정 | 여러 repo 지정 가능 |
| 방식 | SSH 키페어 | 토큰 문자열 |

하나의 SSH 키는 Deploy key로 repo 1개에만 등록할 수 있으므로,
Secret 이름은 대상 repo를 드러내는 `MLOPS_DEPLOY_KEY` 형태로 짓는다.
대상 repo가 늘어나면 대상 repo 1개당 키페어 1세트를 새로 만든다.

### Setup Steps

Deploy Key는 계정(Account) 설정이 아니라 대상 repo(`ykim2718/MLOps`)의 설정에서 등록한다.
(repo 상단 Settings 탭 → 왼쪽 Security 영역의 Deploy keys)

1. 키페어 생성 (로컬 터미널)

   ```bash
   ssh-keygen -t ed25519 -C "sync-claude-to-mlops" -f sync_key -N ""
   ```

   `sync_key`(비공개 키), `sync_key.pub`(공개 키) 두 파일이 생성된다.

2. 공개 키를 대상 repo(MLOps)에 등록

   - `ykim2718/MLOps` repo → Settings → Deploy keys → Add deploy key
   - Key: `sync_key.pub` 내용 붙여넣기
   - "Allow write access" 체크 (push 하려면 필수)

3. 비공개 키를 원본 repo(claude)에 secret으로 등록

   - `ykim2718/claude` repo → Settings → Secrets and variables → Actions → New repository secret
   - 이름: `MLOPS_DEPLOY_KEY`
   - 값: `sync_key`(비공개 키) 파일 전체 내용 (`-----BEGIN...` ~ `...END-----`)

비공개 키 파일(`sync_key`)은 secret 등록 후 로컬에서 삭제한다.

---

## 3. Workflow File

원본 repo(`ykim2718/claude`)의 `.github/workflows/sync-MLOps.yml` 로 저장한다.

트리거(`paths:`)와 실제 복사(`Copy files`의 `cp`/`rsync`)는 별개다.
`paths:`는 워크플로를 언제 실행할지만 정하고, 무엇을 복사할지는 복사 단계가 정한다.
대상을 추가하려면 이 두 곳을 함께 고친다. 배너 단계는 대상을 자동으로 판별하므로 손댈 필요가 없다.

복사가 끝나면 별도 단계에서 배너를 붙인다. 단, **이번 실행이 실제로 바꾼 `.md`에만** 적용한다.
이번 실행이 무엇을 바꿨는지는 `git diff`로 알아내므로(복사 단계가 방금 건드린 파일 = 동기화 대상),
하드코딩한 경로 목록이 필요 없고, MLOps에 원래 있던 다른 문서는 건드리지 않는다.
원본(A)에는 배너가 들어가지 않고 동기화된 대상(B)에만 붙으며,
복사 단계가 매번 원본의 깨끗한 내용으로 덮으므로 배너가 중복 누적되지 않는다.

```yaml
name: Sync files to public MLOps repo

on:
  push:
    branches: [main]                       # source branch (change if master, etc.)
    paths:
      - 'Ubuntu/ubuntu-nomachine-remote-setup.md'
      - 'VS-Code/**'                       # add more files or folders here
  workflow_dispatch:                       # manual run from the Actions tab

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout private repo
        uses: actions/checkout@v5

      - name: Checkout public MLOps repo (via deploy key)
        uses: actions/checkout@v5
        with:
          repository: ykim2718/MLOps
          ssh-key: ${{ secrets.MLOPS_DEPLOY_KEY }}
          path: mlops

      - name: Copy files
        run: |
          # single file
          mkdir -p mlops/Ubuntu
          cp Ubuntu/ubuntu-nomachine-remote-setup.md mlops/Ubuntu/

          # whole folder (mirror)
          mkdir -p mlops/VS-Code
          rsync -av --delete VS-Code/ mlops/VS-Code/

      - name: Add copy-notice banner to files changed by this sync
        run: |
          cd mlops
          banner='> ⚠️ **This is an auto-synced copy.** Do not edit here.'
          # files this run added/modified (markdown only); guard grep for pipefail
          git add -A
          changed=$(git diff --cached --name-only --diff-filter=d | grep -E '\.md$' || true)
          echo "$changed" | while read -r f; do
            [ -n "$f" ] || continue
            [ -f "$f" ] || continue
            tmp=$(mktemp)
            { printf '%s\n\n' "$banner"; cat "$f"; } > "$tmp"
            mv "$tmp" "$f"
          done

      - name: Commit & push if changed
        run: |
          cd mlops
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add -A
          if git diff --staged --quiet; then
            echo "No change - skip"
          else
            git commit -m "Sync files from claude repo"
            git push
          fi
```

`git diff --cached --name-only --diff-filter=d`는 이번 실행이 추가·수정한 파일 목록(삭제 제외)이다.
그중 `.md`만 골라 배너를 붙이므로, 개별 파일이든 폴더로 미러링된 파일이든 이번에 바뀐 것만 표시된다.
`grep ... || true`는 매치가 없을 때 셸(`-eo pipefail`)이 스텝을 실패로 처리하지 않도록 하는 방어다.
배너는 인용구(`>`) 문법이라 GitHub의 렌더링 화면 맨 위에 노란 인용 박스로 표시된다.
마크다운이 아닌 파일(예: 코드·이미지)에는 배너가 붙지 않는다.

### How It Works

1. 트리거 — `main`에서 `paths:`에 지정한 파일·폴더가 바뀌어 push되면 실행 (수동 실행도 가능)
2. 원본 체크아웃 — private repo를 작업 폴더에 받음
3. 대상 체크아웃 — `MLOPS_DEPLOY_KEY`로 `MLOps` repo를 `mlops/`에 받음
4. 복사 — 지정한 파일·폴더를 대상 위치로 복사
5. 배너 — 이번 실행이 바꾼 `.md`에만 복사본 안내 배너를 붙임 (git diff로 자동 판별)
6. 커밋 & push — 내용이 달라졌을 때만 커밋 (동일하면 skip)

---

## 4. Handling Multiple Files

워크플로 파일은 1개로 여러 대상을 처리한다. `paths:`(트리거)와 복사 명령을 함께 늘리면 된다.
세 가지 방식이 있다.

### 1) 파일 나열 — 파일마다 목적지가 다를 때

```yaml
    paths:
      - 'Ubuntu/ubuntu-nomachine-remote-setup.md'
      - 'Ubuntu/another-guide.md'
```

복사 단계에서 각 파일을 원하는 위치로 `cp` 한다.

### 2) 폴더 통째 동기화 — 특정 폴더 전체를 내보낼 때

```yaml
    paths:
      - 'VS-Code/**'
```

```bash
mkdir -p mlops/VS-Code
rsync -av --delete VS-Code/ mlops/VS-Code/
```

`rsync -av --delete`는 폴더 안의 모든 파일·하위 폴더를 대상에 복사·갱신하고,
원본에서 삭제된 파일은 대상에서도 삭제해 양쪽을 완전히 동일하게 맞춘다.
(`--delete`를 빼면 추가·수정만 반영되고 삭제는 반영되지 않는다.)

### 3) 패턴 매칭 — 특정 폴더의 특정 확장자만 (예: Ubuntu 폴더의 모든 `.md`)

```yaml
    paths:
      - 'Ubuntu/*.md'
```

---

## 5. Difference from PAT

대상 repo checkout 한 줄만 다르다.

- Deploy key: `ssh-key: ${{ secrets.MLOPS_DEPLOY_KEY }}`
- PAT: `token: ${{ secrets.MLOPS_PAT }}`

`ssh-key`를 쓰면 checkout이 SSH remote로 자동 설정되어 이후 `git push`가 그 키로 인증된다.
별도 ssh-agent 설정이 필요 없다.

---

## Appendix A. Terminology

- PAT (Personal Access Token) — GitHub 계정 비밀번호 대신 사용하는 인증용 토큰 문자열. 권한 범위와 만료일을 지정할 수 있다. Fine-grained PAT은 특정 repo·특정 권한으로 범위를 좁힌 최신 방식.
- SSH (Secure Shell) — 네트워크로 원격 서버에 안전하게 접속·통신하는 암호화 프로토콜. GitHub는 SSH 키페어로 push/pull 인증을 지원한다.
- SSH Key Pair (SSH 키페어) — 짝을 이루는 두 개의 키. Public key(공개 키)는 서버(GitHub)에 등록하고, Private key(비공개 키)는 본인만 보관한다. 공개 키로 잠근 것은 짝이 되는 비공개 키로만 열 수 있어 신원이 증명된다.
- Deploy Key — 특정 repo 한 개에만 연결되는 SSH 공개 키. 쓰기 권한을 부여하면 그 repo에 push할 수 있다. 만료가 없다. 계정 설정이 아니라 해당 repo의 Settings에서 등록한다. 같은 키를 두 repo에 Deploy key로 등록할 수 없다.
- Ed25519 — SSH 키 생성에 쓰는 최신 타원곡선 암호 알고리즘. 짧고 안전해 RSA보다 권장된다. (`ssh-keygen -t ed25519`)
- Secret — repo/조직에 저장하는 암호화된 값(토큰·키 등). 워크플로 안에서 `${{ secrets.NAME }}` 으로 참조하며 로그에 노출되지 않는다. 이름은 대소문자를 구분한다.
- GITHUB_TOKEN — 워크플로 실행 시 GitHub가 자동 발급하는 임시 토큰. 해당 repo 내부 작업에만 권한이 있어 다른 repo에는 쓸 수 없다.
- GitHub Actions — GitHub에 내장된 CI/CD 자동화 도구. 이벤트(예: push)에 반응해 워크플로를 실행한다.
- CI/CD (Continuous Integration / Continuous Delivery) — 코드 변경을 자동으로 빌드·테스트·배포하는 개발 자동화 방식.
- Workflow (워크플로) — `.github/workflows/` 안의 YAML 파일로 정의하는 자동화 작업 묶음. 하나 이상의 job과 step으로 구성된다.
- paths — `on: push:` 아래의 트리거 필터. 여기에 지정한 파일·폴더가 바뀔 때만 워크플로가 실행된다. 확장자에 국한되지 않는다.
- rsync — 폴더 단위로 파일을 동기화하는 명령. `-a`는 하위 구조 보존, `-v`는 로그 출력, `--delete`는 원본에서 지운 파일을 대상에서도 지운다.
- git diff --cached — staging area(인덱스)에 올라온 변경 목록을 보여주는 명령. `--diff-filter=d`로 삭제를 제외하면 이번 실행이 추가·수정한 파일만 남는다.
- YAML (YAML Ain't Markup Language) — 들여쓰기로 구조를 표현하는 사람이 읽기 쉬운 설정 파일 형식. 워크플로 정의에 사용된다.
- workflow_dispatch — 워크플로를 Actions 탭에서 수동으로 실행할 수 있게 해주는 트리거.
- Repository (Repo) — 코드·파일·이력을 담는 저장소. private(비공개)과 public(공개)으로 구분된다.
