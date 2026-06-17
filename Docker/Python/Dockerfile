# Python 3.11.15 runtime image — builds a container that installs deps and runs the app automatically.
# Dependency installation runs only once at build time and stays in the layer cache, so later startups are fast.
FROM python:3.11.15

# System packages needed to build native extensions.
#   build-essential : compiles C extensions such as the ucrdtw / dtaidistance / TA-Lib Python wrappers
#   wget            : downloads the TA-Lib C library source
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential wget \
    && rm -rf /var/lib/apt/lists/*

# The TA-Lib Python package requires the C library of the same name, so build and install it from source.
RUN wget -q http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz \
    && tar -xzf ta-lib-0.4.0-src.tar.gz \
    && cd ta-lib \
    && ./configure --prefix=/usr \
    && make \
    && make install \
    && cd .. \
    && rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

WORKDIR /app

# Copy only requirements.txt first and install. When only the code changes, this layer is cached and reinstallation is skipped.
COPY app/requirements.txt .

# ucrdtw needs numpy at build time, but pip's build isolation environment has no numpy, so it fails.
# Therefore install numpy first, install only ucrdtw with build isolation disabled, then install the rest.
RUN pip install --no-cache-dir numpy==1.26.4
# Also set SETUPTOOLS_USE_DISTUTILS=stdlib so the standard distutils is used.
# (setuptools' distutils shim lacks the msvccompiler that numpy.distutils looks for.)
RUN SETUPTOOLS_USE_DISTUTILS=stdlib pip install --no-cache-dir --no-build-isolation ucrdtw==0.201
# TA-Lib 0.4.29's pre-generated C source uses the numpy 1.x C API. With build isolation on, pip pulls
# numpy 2.x and compilation fails on the API mismatch, so disable isolation and compile against the numpy 1.26 headers installed above.
RUN pip install --no-cache-dir --no-build-isolation TA-Lib==0.4.29
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code.
COPY app/ .

# App to run automatically when the container starts. Change the filename to match the real app.
CMD ["python", "start.py"]
