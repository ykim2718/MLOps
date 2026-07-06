.\my_flow_trigger.ps1 -Mode pool -Member yrocket ^
  -PrefectApiUrl "http://localhost:4200/api" ^
  -PrefectDeployment pipeline/pipelineflow-low  ^
  -GitRepo https://github.com/ykim2718/SandBox4Git.git ^
  -GitCommit 8fd9c6a2eaf04dcae5f99c087ff6aeeb83dd64a1 ^
  -MinioKey electric_power_consumption/v0/powerconsumption.csv