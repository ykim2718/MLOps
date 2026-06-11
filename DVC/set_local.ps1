pip install dvc
pip install dvc-s3

git init
dvc init
git remote add origin REPOSITORY_URL
dvc remote add -d dvc-minio s3://BUKET_NAME
dvc remote modify dvc-minio endpointurl http://localhost:9000
$env:AWS_ACCESS_KEY_ID="admin"
$env:AWS_SECRET_ACCESS_KEY="password123"