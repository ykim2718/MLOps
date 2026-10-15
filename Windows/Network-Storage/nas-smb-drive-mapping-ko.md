# NAS SMB Drive Mapping
Rev. 1 | Created: 2026-10-15 | Updated: 2026-10-15 17:33 UTC

- [1. Purpose](#1-purpose)
- [2. Summary](#2-summary)
- [3. Drive Mapping](#3-drive-mapping)
  - [3.1 Share name check](#31-share-name-check)
  - [3.2 Credential and drive connection](#32-credential-and-drive-connection)
- [4. Verification](#4-verification)
- [5. Troubleshooting](#5-troubleshooting)
- [Appendix A. Terminology](#appendix-a-terminology)

## 1. Purpose

- **Problem Statement**: Windows 에서 NAS 를 network drive 로 연결하면 System error 67 이 나거나, 연결은 되었는데 탐색기에 drive 가 보이지 않거나, 재부팅 뒤에 연결이 사라진다.
- **Goal**: NAS 공유 폴더 하나를 drive 문자 하나로 연결하여, 탐색기에서 보이고 재부팅 뒤에도 자동으로 다시 연결되게 한다.
- **Non-Goal**: NAS 쪽의 공유 폴더 생성과 사용자 권한 설정은 다루지 않는다.

## 2. Summary

SMB drive 는 NAS 전체가 아니라 공유 폴더 하나에 연결하며, 관리자가 아닌 일반 PowerShell 에서 `cmdkey` 로 NAS 비밀번호를 저장한 뒤 `net use ... /persistent:yes` 로 연결한다.
공유 폴더가 여럿이면 공유 폴더마다 drive 문자를 하나씩 따로 연결한다.

## 3. Drive Mapping

### 3.1 Share name check
- 탐색기 주소창에 `\\<NAS_IP>` 를 입력하고 NAS 계정으로 로그인하면 공유 폴더 목록이 보인다.
- 연결 경로는 `\\<NAS_IP>\<SHARE_NAME>` 이다. `\\<NAS_IP>\` 까지만 적으면 System error 67 이 난다.

### 3.2 Credential and drive connection
- **관리자가 아닌** 일반 PowerShell 을 연다. 관리자 창에서 연결한 drive 는 일반 권한으로 도는 탐색기에 나타나지 않는다.
- NAS 비밀번호를 Windows 에 저장한다. `/pass` 뒤에 값을 적지 않으면 비밀번호를 묻는다.

```powershell
# PowerShell
cmdkey /add:<NAS_IP> /user:<NAS_USER> /pass
```

- 공유 폴더를 drive 문자에 연결한다. `/persistent:yes` 와 저장된 비밀번호로 재부팅 뒤에도 자동으로 다시 연결된다.

```powershell
# PowerShell
net use <DRIVE>: \\<NAS_IP>\<SHARE_NAME> /persistent:yes
```

- 관리자 창에서 연결한 drive 도 탐색기에 보이게 하려면, 관리자 PowerShell 에서 아래 설정을 한 번 넣고 재부팅한다. 이 설정만으로는 drive 가 생기지 않으며, 위의 연결은 따로 해야 한다.

```powershell
# PowerShell (Administrator)
New-ItemProperty -Path HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System -Name EnableLinkedConnections -Value 1 -PropertyType DWord -Force
```

## 4. Verification

연결한 일반 PowerShell 창에서 `net use` 를 실행하여 `<DRIVE>:` 의 상태가 `OK` 인지 확인한다.

아래 명령은 drive 의 목록 조회 시간과 50MB 이상 파일 하나의 복사 속도를 보여 준다. 1GbE LAN 이면 복사 속도가 100MB/s 안팎이다.

```powershell
# PowerShell
$sw = [Diagnostics.Stopwatch]::StartNew()
(Get-ChildItem <DRIVE>:\ -Recurse -Depth 2 -Force | Measure-Object).Count
"list $($sw.ElapsedMilliseconds) ms"
$f = Get-ChildItem <DRIVE>:\ -Recurse -File -Depth 3 | Where-Object Length -gt 50MB | Select-Object -First 1
$sw.Restart()
Copy-Item $f.FullName $env:TEMP\t.bin
"{0:N0} MB/s" -f ($f.Length / 1MB / $sw.Elapsed.TotalSeconds)
Remove-Item $env:TEMP\t.bin
```

## 5. Troubleshooting

Table 1. Symptoms and fixes

| Symptom                                | Cause                                                  | Fix                                               |
| :------------------------------------: | :----------------------------------------------------: | :-----------------------------------------------: |
| System error 67                        | 경로에 공유 폴더 이름이 빠짐                           | `\\<NAS_IP>\<SHARE_NAME>` 로 연결                 |
| 연결 성공 후 탐색기에 drive 가 안 보임 | 관리자 PowerShell 에서 연결함                          | 일반 PowerShell 에서 다시 연결                    |
| 재부팅 뒤 drive 가 안 보임             | 현재 사용자에 drive 연결 기록과 저장된 비밀번호가 없음 | 일반 PowerShell 에서 `cmdkey` 후 `net use` 재실행 |

- 연결 기록은 `HKCU\Network\<DRIVE>` 에, 저장된 비밀번호는 `cmdkey /list` 에서 확인한다. 둘 중 하나라도 없으면 재부팅 뒤에 다시 연결되지 않는다.

---

## Appendix A. Terminology

- **1GbE**: 초당 1 Gbit 를 전송하는 Ethernet. 실제 file 복사 속도는 100MB/s 안팎.
- **cmdkey**: Windows 자격 증명 관리자에 server 별 사용자 이름과 비밀번호를 저장하는 명령.
- **EnableLinkedConnections**: 관리자 session 과 일반 session 이 network drive 연결을 함께 쓰게 하는 Windows registry 값.
- **LAN**: Local area network. 같은 가정·사무실 내부 network.
- **NAS**: Network-attached storage. Network 로 file 을 공유하는 저장 장비.
- **net use**: Windows 에서 network 공유 폴더를 drive 문자에 연결하는 명령.
- **SMB**: Server Message Block. Windows 의 file 공유 protocol.
