# deploy.py — register the deployments on the server (admin, run once from the host shell).
# Run from the folder holding pipeline.py, with PREFECT_API_URL pointing at the server.
from prefect import flow

# Same source + entrypoint for every tier; tiers differ only by deployment name and work pool.
src = flow.from_source(source=".", entrypoint="pipeline.py:pipeline")   # source dir + <file>:<@flow function>

for name, pool in (("high", "high_performance"), ("low", "lower_performance")):
    src.deploy(
        name=name,
        work_pool_name=pool,
        image="pipeline-flow:latest",
        build=False,   # image is built separately (docker build); don't build/push here
        push=False,
    )
