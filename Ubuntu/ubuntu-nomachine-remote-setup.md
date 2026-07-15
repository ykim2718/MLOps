> ⚠️ **This is an auto-synced copy. Do not edit here.**

# 우분투 원격 접속 서버 구축

rev. 18
<!-- 규칙: 이 파일을 수정할 때마다 위 rev 번호를 1씩 올릴 것 (git commit 여부와 무관). -->

<table width="100%">
<tr>
<td align="left"><a href="https://ubuntu.com"><img src="assets/ubuntu.svg" alt="Ubuntu" height="48"></a></td>
<td align="right"><a href="https://www.nomachine.com"><img src="assets/nomachine.svg" alt="NoMachine" height="48"></a></td>
</tr>
</table>

> 목표: 노트북(Ubuntu 26.04)을 원격 접속 전용 서버로 만들고, Windows 11 데스크톱에서 원격 데스크톱으로 접속
> 최종 방식: **NoMachine + 자동 로그인** (RDP에서 전환)

---

## 1. Final Configuration (Success Path)

```
┌─────────────────────────────────────────────────────┐
│             SERVER: Ubuntu 26.04 laptop             │
│              (<HOSTNAME>, <SERVER_IP>)              │
│                                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │ [1] Ubuntu 26.04 LTS clean install           │   │
│  │     └─ boot USB (Rufus) → Erase disk install │   │
│  └──────────────────────────────────────────────┘   │                           ┌────────────────────────────────────────────────────┐
│                                                     │                           │             CLIENT: Windows 11 desktop             │
│  ┌──────────────────────────────────────────────┐   │                           │                                                    │
│  │ [2] Install NoMachine server                 │   │                           │  ┌──────────────────────────────────────────────┐  │
│  │     └─ nomachine_9.8.2_1_amd64.deb → dpkg -i │   │  LAN (same home network)  │  │ [4] Launch NoMachine Windows client          │  │
│  │     └─ nxserver.service = active (running)   │   ├───────────────────────────┤  │     └─ Host: <SERVER_IP>                     │  │
│  └──────────────────────────────────────────────┘   │  NX protocol / port 4000  │  │     └─ account: <USERNAME> / Ubuntu password │  │
│                                                     │                           │  └──────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────┐   │                           │                                                    │
│  │ [3] Auto-login setup                         │   │                           │  ▶ connected: display scaling OK, keyboard OK      │
│  │     └─ /etc/gdm3/custom.conf                 │   │                           └────────────────────────────────────────────────────┘
│  │        AutomaticLoginEnable=true             │   │
│  │        AutomaticLogin=<USERNAME>             │   │
│  └──────────────────────────────────────────────┘   │
│                                                     │
│  [Boot] ─auto-login─▶ desktop session stays alive   │
│         (physical display = mirrored by NoMachine)  │
└─────────────────────────────────────────────────────┘

  Operating rule:  reboot OK (auto-login)   /   logout NO (login screen issue)
```

---

## 2. Success Path — Steps in Order

### 2.1 Ubuntu 26.04 LTS clean install (server, laptop)
- 부팅 USB 제작: Rufus로 `ubuntu-26.04-desktop-amd64.iso` 기록
  - 파티션 구성 GPT / 대상 시스템 UEFI / ISO 모드
- 설치: "Erase disk and install Ubuntu"로 기존 OS 완전 삭제
- 부팅 USB 제작 및 ISO 관련 문제는 → **Appendix A**, **Appendix B** 참조

### 2.2 Install NoMachine server (server, laptop)
- 패키지: `nomachine_9.8.2_1_amd64.deb` (DEB / amd64)
- 설치:
  ```bash
  cd ~/Downloads
  sudo dpkg -i nomachine_*.deb
  sudo apt install -f
  ```
- 서비스 확인:
  ```bash
  sudo systemctl status nxserver     # active (running)
  ```
- 서비스는 부팅 시 자동 시작되어 서버 용도에 적합
- RDP → NoMachine 전환 배경은 → **Appendix C** 참조
- NoMachine 패키지 다운로드 및 형식(DEB/RPM) 문제는 → **Appendix D** 참조

### 2.3 Auto-login setup (server, laptop)
- 파일 편집:
  ```bash
  sudo vi /etc/gdm3/custom.conf
  ```
- `[daemon]` 섹션에 추가:
  ```
  [daemon]
  AutomaticLoginEnable=true
  AutomaticLogin=<USERNAME>
  ```
- 재부팅 시 비밀번호 입력 없이 바탕화면까지 자동 진입 → 원격 접속 가능한 상태 상시 유지
- 이 설정이 필요했던 이유(헤드리스 접속 실패)는 → **Appendix E** 참조

### 2.4 Windows client connection (client, desktop)
- **NoMachine** 클라이언트 실행 (RDP 클라이언트 `mstsc` 아님)
- 접속 정보:
  - Host: `<SERVER_IP>`
  - 계정: `<USERNAME>` / 우분투 비밀번호
- 결과: 화면 스케일링 정상, 키보드 정상 동작
- RDP(mstsc)와의 혼동 문제는 → **Appendix F** 참조

### 2.5 Operating rules
- **재부팅(O)**: 자동 로그인으로 바탕화면 자동 진입 → 접속 정상
- **로그아웃(X)**: GDM 로그인 화면으로 이동하며, 원격에서 키보드 입력 불가 (→ **Appendix E**)
- 원격에서 노트북을 껐다 켜거나 재부팅해도, 자동 로그인 덕분에 부팅만 되면 재접속 가능

---

# Appendix — 문제 해결 기록

## Appendix A. Rufus "multiple partitions" USB write failure

**Problems**
- Rufus에서 ISO/DD 모드 모두 "실패"
- 장치가 "다중 파티션 (F:) (G:)"로 표시됨 (이전 ISO 기록 흔적)

**Cause**
- USB가 여러 파티션으로 분할되어 Rufus가 볼륨 잠금을 획득하지 못함

**Fix — wipe the USB completely with diskpart**
```
diskpart
list disk                 # identify the USB disk number by size (~57GB)
select disk 2             # must be the USB number (never a system disk)
detail disk               # re-confirm the USB via its F:/G: drive letters
clean                     # wipe the entire partition table
exit
```
- 이후 Rufus에서 단일 빈 디스크로 인식되어 정상 기록

> 주의: `select disk` 번호를 잘못 지정하면 해당 디스크가 삭제됨. 반드시 용량으로 USB 확인.

---

## Appendix B. Bad ISO read — source drive (M:) problem

**Problems**
- Rufus 기록 중 `libcdio: fread(): Permission denied`, `minimal.squashfs`(3.2GB) 읽기 실패
- `Get-FileHash` 실행 시: "파일을 읽을 수 없습니다. 시스템에 부착된 장치가 작동하지 않습니다."

**Cause**
- 쓰기(USB)가 아니라 **읽기(ISO 원본)** 실패
- ISO가 위치한 드라이브(`M:\depot\...`)의 장치 레벨 I/O 오류 — 파일 손상이 아닌 드라이브 접근 불량

**Fix**
- ISO를 안정적인 로컬 디스크(C: 등)로 복사 후 사용, 또는 재다운로드
- SHA256 무결성 대조: `releases.ubuntu.com/26.04/SHA256SUMS`

**Lesson**
- ISO는 네트워크 드라이브/불안정한 보조 디스크가 아닌 로컬 디스크에 두고 기록할 것

---

## Appendix C. RDP (gnome-remote-desktop) limitations — display & keyboard issues

**Problems**
1. 창은 큰데 우분투 화면만 작게 표시 (검은 여백)
2. 코맨드라인에서 키가 밀려 입력됨 (a→s, b→n)
3. 엔터·Ctrl 등 특수키 미동작

**Diagnosis**
- 노트북 물리 키보드 직접 입력은 정상 → RDP 세션에서만 키 전달이 어긋남
- Input Sources는 English(US) 단일로 정상 → 우분투 레이아웃 문제가 아님
- 화면 문제: Desktop Sharing(미러링) 모드가 물리 해상도(1920×1080)에 고정됨
- 근본 원인: **26.04 Wayland 환경에서 gnome-remote-desktop RDP의 키 전달·해상도 처리 한계**

**Decision**
- RDP를 접고 **NoMachine으로 전환** (키 전달·해상도 자동 조정이 안정적)

---

## Appendix D. NoMachine package download problems

**Problem 1 — wrong download URL**
- 명령줄(`wget`/`curl -L`)로 받으면 실제 .deb가 아닌 HTML 페이지가 저장됨
- `dpkg: error: ... is not a Debian format archive`
- 원인: 안내받은 URL 오류 + NoMachine 다운로드 리다이렉트와 CLI 다운로드 불일치
- 해결: 노트북 **Firefox에서 다운로드 페이지의 정확한 항목을 클릭**해 수신

**Problem 2 — wrong package format (RPM)**
- `nomachine_9.8.2_1_x86_64.rpm` 수신 → Ubuntu에서 설치 불가
- 원인: 다운로드 목록에서 RPM 항목 선택
- 해결: **"NoMachine for Linux DEB amd64"** 항목 선택 → `nomachine_9.8.2_1_amd64.deb`

**Install**
```bash
cd ~/Downloads
sudo dpkg -i nomachine_*.deb
sudo apt install -f
```

**Lesson**
- Ubuntu = `.deb` / `amd64` (RPM은 RHEL/Fedora용)
- CLI 다운로드가 계속 실패하면 브라우저로 받는 것이 확실

---

## Appendix E. Logout (headless) connection failure → worked around via auto-login

**Goal**
- 화면 크기 문제의 근본 해결을 위해, 노트북을 로그아웃 상태로 두고 NoMachine 가상 디스플레이로 접속(헤드리스)

**Attempts & failures**
- `/usr/NX/etc/node.cfg`에 `CreateDisplay 1`, `DisplayGeometry 1920x1080` 설정
  → 로그인된 물리 화면에 자동으로 붙어 가상 디스플레이가 무시됨 (해상도 변화 없음)
- 로그아웃 후 재접속 시도 → 접속 실패
  - `nxserver` 로그: `pam_systemd(nx:session): Failed to get user record: No such process`
- GDM을 X11로 전환 시도 (`/etc/gdm3/custom.conf`에 `WaylandEnable=false`)
  → 26.04는 Wayland 전용 방향이라 헤드리스 접속 여전히 실패
- GDM 로그인 화면까지는 원격 표시되나 **키보드 입력 불가** (RDP와 유사한 GDM 키 전달 문제)

**Final fix — worked around via auto-login**
- 헤드리스를 포기하고, 부팅 시 항상 로그인된 세션이 유지되도록 자동 로그인 설정
  ```
  [daemon]
  AutomaticLoginEnable=true
  AutomaticLogin=<USERNAME>
  ```
- `WaylandEnable=false`는 목적을 잃어 제거 (남기면 사용자 세션 강제 X11로 부작용 우려)
- 결과: 재부팅 → 자동 로그인 → 미러링 세션 상시 유지 → NoMachine 접속 안정 (스케일링 정상)

**Operating rules**
- 재부팅은 OK, **로그아웃은 금지** (로그인 화면 키 입력 문제)

> 참고(보안): 자동 로그인은 노트북을 켜면 누구나 바탕화면 접근 가능함을 의미. 집 내부 단독 서버라면 무방.

---

## Appendix F. Client connection error — mstsc (RDP) vs NoMachine confusion

**Problems**
- Windows에서 접속 시 `mstsc error code: 0x904, Extended error code: 0x7`

**Cause**
- Windows **원격 데스크톱 연결(mstsc)** = RDP 클라이언트로 접속 시도
- 서버는 NoMachine으로 전환된 상태 → RDP로 붙을 대상이 없음

**Fix**
- Windows에서 **NoMachine 클라이언트**로 접속 (mstsc 아님)
  - 시작 메뉴에서 "NoMachine" 검색·실행
  - Host `<SERVER_IP>`, 계정 `<USERNAME>` / 우분투 비밀번호

**Lesson**
- 서버가 NoMachine이면 클라이언트도 NoMachine을 사용해야 함 (프로토콜 일치)


---

## Appendix G. File transfer — NoMachine "Connect a disk" & SFTP

**Situation**
- NoMachine으로 접속한 Ubuntu 서버 ↔ Windows 클라이언트 간 파일을 주고받아야 함
- NoMachine 9에는 예전의 "Transfer a file" 버튼이 없고, `Devices` → `Connect a disk`(디스크/폴더 공유) 방식으로 바뀜

**Method 1 — NoMachine `Connect a disk`**
- 세션 메뉴(오른쪽 위 모서리를 끌어내리거나 `Ctrl+Alt+0`) → `Devices` → `Connect a disk`
- 목록 구분:
  - **Local disks (C:, D:, …)** = Windows(클라이언트) 디스크 → Ubuntu로 공유
  - **Remote disks (`/`, `efi`)** = Ubuntu(서버) 디스크 → Windows로 공유
- 예: Windows `D:` 선택 → Ubuntu 세션에 마운트됨
- **마운트 위치**: 루트 `/`가 아니라 **사용자 홈/바탕화면** 아래
  - 예: `~/Desktop/'D on Player (NoMachine)'`
  - 확인 명령: `findmnt -t fuse.nxfs` 또는 `mount | grep -i nx`
- 그 폴더 안에 파일을 복사해 넣으면 Windows·Ubuntu 양쪽에서 보임 → 양방향 전송

**Caution**
- `efi`, `Recovery`, `System Reserved` 등 부팅/시스템 파티션은 **절대 선택 금지** (데이터 없음 + 부팅 손상 위험)
- 마운트 폴더 이름에 공백·괄호가 있어 터미널에서는 따옴표 필요: `cd ~/Desktop/'D on Player (NoMachine)'`
- Ubuntu 26.04 Wayland에서는 FUSE 마운트가 파일 관리자에 안 잡히기도 함 → `sudo apt install fuse3` 후 디스크 재연결

**Method 2 — SFTP (recommended for large / frequent transfers)**
- Ubuntu(서버)에서 한 번만 설정:
  ```bash
  sudo apt install openssh-server
  sudo systemctl enable --now ssh
  ip a | grep inet          # <SERVER_IP> 확인
  ```
- Windows에서 WinSCP/FileZilla로 접속: Host `<SERVER_IP>`, 사용자 `<USERNAME>`, 포트 22 (SFTP)
- 탐색기처럼 드래그로 전송 — 큰 파일·대량 전송에 안정적

**Lesson**
- NoMachine 9의 파일 전송 = `Connect a disk`(폴더 공유). "직접 보내기"가 아니라 공유 폴더를 통해 오감
- 마운트는 `/`가 아니라 **홈/바탕화면** 아래를 확인할 것
- 안정성·속도가 중요하면 SFTP 병행
