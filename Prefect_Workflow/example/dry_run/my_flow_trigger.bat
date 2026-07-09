@echo off
REM __version__ = "0.0.17"
REM Launch the pool-mode dry-run trigger. cmd.exe can't run a .ps1 directly,
REM so invoke PowerShell explicitly. %~dp0 = this .bat's folder (so the .ps1
REM is found regardless of the current directory).
REM STAMP = locale-safe timestamp (e.g. 20260709-19:11); appended to the submitter label so each run is unique.
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HH:mm"') do set "STAMP=%%i"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0my_flow_trigger.ps1" ^
  -Mode pool -PrefectBlock yrocket -Submitter "yRocket-%STAMP%" ^
  -PrefectApiUrl "http://localhost:4200/api" ^
  -PrefectDeployment pipeline/pipelineflow-low ^
  -GitRepo https://github.com/ykim2718/SandBox4Git.git ^
  -GitCommit b3f60a0b3ecb8358d344943ac4589be0154697c7 ^
  -MinioKey electric_power_consumption/v0/powerconsumption.csv
