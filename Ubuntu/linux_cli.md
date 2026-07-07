# Linux CLI

<sub>rev. 6</sub>

> 이 문서의 명령은 **Ubuntu** 기준으로 작성되었습니다.

## 1. Users

Ubuntu에서는 대화형 `adduser`/`deluser`가 권장 도구입니다. (`useradd`/`userdel`도 있지만 옵션을 일일이 지정해야 합니다.)

### 1.1 Create a user

```bash
sudo adduser username    # 계정 + 홈 디렉터리 생성, 비번·이름을 프롬프트로 입력받음
```

- 홈 디렉터리(`/home/username`), 기본 그룹, 로그인 셸을 자동 생성한다.
- 실행하면 비밀번호와 이름 등을 대화형으로 물어본다.

### 1.2 Verify a user

```bash
id username              # UID, GID, 소속 그룹 확인
getent passwd username   # /etc/passwd 항목 확인
ls -ld /home/username    # 홈 디렉터리 소유자·권한 확인
```

### 1.3 Delete a user

```bash
sudo deluser username                  # 계정만 삭제 (홈 디렉터리는 남음)
sudo deluser --remove-home username    # 홈 디렉터리까지 함께 삭제
```

- `--remove-home` — 홈 디렉터리(`/home/username`)를 같이 제거한다.
- 삭제하려는 사용자가 실행 중인 프로세스를 갖고 있으면 거부될 수 있다. 프로세스를 먼저 종료한다.

### 1.4 Grant sudo privileges

```bash
sudo usermod -aG sudo username   # sudo 그룹에 추가
```

- Ubuntu의 관리자(sudo) 그룹 이름은 `sudo`이다.
- `-aG` — 기존 그룹을 유지(`-a`)하면서 지정 그룹(`-G`)에 추가. `-a` 없이 `-G`만 쓰면 기존 보조 그룹이 모두 교체되니 주의.
