@echo off
REM Launch the pool-mode dry-run trigger. cmd.exe can't run a .ps1 directly,
REM so invoke PowerShell explicitly. %~dp0 = this .bat's folder (so the .ps1
REM is found regardless of the current directory).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0my_flow_trigger.ps1" ^
  -Mode pool -PrefectBlock yrocket ^
  -PrefectApiUrl "http://localhost:4200/api" ^
  -PrefectDeployment pipeline/pipelineflow-low ^
  -GitRepo https://github.com/ykim2718/SandBox4Git.git ^
  -GitCommit 690661f67e54c5ed55820947a54f665937277dd4 ^
  -MinioKey electric_power_consumption/v0/powerconsumption.csv
