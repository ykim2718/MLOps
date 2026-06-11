git log -n 10 --format="%h %cd : %s" --date=format:"%Y-%m-%d %H:%M" -- ':(top)**/*.dvc'
dvc dag
dvc dag --mermaid
dvc dag --dot > pipeline.dot