# set_environment.ps1
# 같은 폴더의 docker-compose.env 에 있는 KEY=VALUE 들을 "환경변수"로 올린다.
# 한 번 실행해 두면, 이후 호스트 파이썬(catalog.py / register_blocks.py / data_*.ps1)이
# os.environ(=$env:) 에서 값을 읽어 쓴다. (파일을 직접 읽지 않아도 됨)
#
# 사용:
#   .\set_environment.ps1            # 현재 세션 + 사용자(User) 영구 환경변수에 설정(기본)
#   .\set_environment.ps1 -Session   # 현재 세션에만 설정(영구 저장 안 함)
#
param(
    [switch]$Session,                                      # 현재 세션에만 설정
    [string]$EnvFile = (Join-Path $PSScriptRoot 'docker-compose.env')
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $EnvFile)) {
    throw "Not found: $EnvFile  (docker-compose.env_example 를 복사해 만드세요)"
}

$count = 0
foreach ($line in Get-Content -LiteralPath $EnvFile) {
    $t = $line.Trim()
    if (-not $t -or $t.StartsWith('#') -or ($t -notmatch '=')) { continue }   # 주석/빈 줄 건너뜀
    $idx = $t.IndexOf('=')
    $k = $t.Substring(0, $idx).Trim()
    $v = $t.Substring($idx + 1).Trim()
    if (-not $k) { continue }

    Set-Item -Path "Env:$k" -Value $v                     # 현재 세션
    if (-not $Session) {
        [Environment]::SetEnvironmentVariable($k, $v, 'User')   # 사용자(User) 영구 저장
    }
    $count++
    Write-Host ("set {0}" -f $k)                          # 값은 출력하지 않음(시크릿 보호)
}

$scope = if ($Session) { "현재 세션" } else { "현재 세션 + 사용자(User) 영구" }
Write-Host ("[ok] {0} 개 환경변수 설정 완료 ({1})." -f $count, $scope) -ForegroundColor Green
if (-not $Session) {
    Write-Host "영구 설정은 '새로 여는' 터미널부터 적용됩니다(현재 세션엔 이미 적용됨)." -ForegroundColor Yellow
}
