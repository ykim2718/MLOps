@echo off
REM __version__ = "0.0.17"
REM Launch the pool-mode dry-run trigger. cmd.exe can't run a .ps1 directly,
REM so invoke PowerShell explicitly. %~dp0 = this .bat's folder (so the .ps1
REM is found regardless of the current directory).
REM STAMP = locale-safe timestamp (e.g. 20260709-19:11); appended to the submitter label so each run is unique.
for /f %%i in ('powershell -NoProfile -Command "[TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), 'Korea Standard Time').ToString('yyyyMMdd-HHmm') + '_Seoul'"') do set "STAMP=%%i"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0my_flow_trigger.ps1" ^
  -Mode pool -PrefectBlock yrocket -Submitter "yRocket-%STAMP%" ^
  -PrefectApiUrl "http://localhost:4200/api" ^
  -PrefectDeployment pipeline/pipelineflow-low ^
  -GitRepo https://github.com/ykim2718/SandBox4Git.git ^
  -GitCommit 95153312753021be0e4c09d04a387d1864de9569  ^
  -MinioKey electric_power_consumption/v0/powerconsumption.csv
