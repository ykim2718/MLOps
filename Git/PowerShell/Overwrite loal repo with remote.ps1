# 1. 원격 저장소의 최신 이력을 일단 다운로드 (내 파일은 아직 안 바뀜)
git fetch --all

# 2. 내 로컬 main 브랜치를 원격 main(origin/main) 상태로 강제 리셋 (덮어쓰기)
git reset --hard origin/main