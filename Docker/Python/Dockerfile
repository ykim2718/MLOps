# Python 3.11.15 실행 이미지 — 설치 후 앱을 자동 실행하는 컨테이너를 빌드한다.
# 의존성 설치는 빌드 시 1회만 수행되어 레이어 캐시에 남고, 이후 기동은 빠르다.
FROM python:3.11.15

# 네이티브 확장 빌드에 필요한 시스템 패키지.
#   build-essential : ucrdtw / dtaidistance / TA-Lib 파이썬 래퍼 등 C 확장 컴파일
#   wget            : TA-Lib C 라이브러리 소스 내려받기
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential wget \
    && rm -rf /var/lib/apt/lists/*

# TA-Lib 파이썬 패키지는 동명의 C 라이브러리를 요구하므로 소스에서 빌드해 설치한다.
RUN wget -q http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz \
    && tar -xzf ta-lib-0.4.0-src.tar.gz \
    && cd ta-lib \
    && ./configure --prefix=/usr \
    && make \
    && make install \
    && cd .. \
    && rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

WORKDIR /app

# requirements.txt 만 먼저 복사해 설치한다. 코드만 바뀐 경우 이 레이어가 캐시되어 재설치를 건너뛴다.
COPY app/requirements.txt .

# ucrdtw 는 빌드 시 numpy 가 필요한데 pip 의 빌드 격리 환경에는 numpy 가 없어 실패한다.
# 따라서 numpy 를 먼저 설치하고, ucrdtw 만 빌드 격리를 끈 채로 설치한 뒤 나머지를 설치한다.
RUN pip install --no-cache-dir numpy==1.26.4
# 추가로 SETUPTOOLS_USE_DISTUTILS=stdlib 로 표준 distutils 를 쓰게 한다.
# (setuptools 의 distutils 대체본에는 numpy.distutils 가 찾는 msvccompiler 가 없다.)
RUN SETUPTOOLS_USE_DISTUTILS=stdlib pip install --no-cache-dir --no-build-isolation ucrdtw==0.201
# TA-Lib 0.4.29 의 사전 생성 C 소스는 numpy 1.x C API 를 쓴다. 빌드 격리를 켜면 pip 가 numpy 2.x 를
# 받아 와 API 불일치로 컴파일이 실패하므로, 격리를 끄고 위에서 설치한 numpy 1.26 헤더로 컴파일한다.
RUN pip install --no-cache-dir --no-build-isolation TA-Lib==0.4.29
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드를 복사한다.
COPY app/ .

# 컨테이너 기동 시 자동 실행할 앱. 실제 앱에 맞춰 파일명을 바꾼다.
CMD ["python", "run.py"]
