# Python 3.11.15 실행 이미지 — 설치 후 앱을 자동 실행하는 컨테이너를 빌드한다.
# 의존성 설치는 빌드 시 1회만 수행되어 레이어 캐시에 남고, 이후 기동은 빠르다.
FROM python:3.11.15

WORKDIR /app

# requirements.txt 만 먼저 복사해 설치한다. 코드만 바뀐 경우 이 레이어가 캐시되어 재설치를 건너뛴다.
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드를 복사한다.
COPY app/ .

# 컨테이너 기동 시 자동 실행할 앱. 실제 앱에 맞춰 파일명을 바꾼다.
CMD ["python", "main.py"]
