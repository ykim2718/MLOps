# 2024.7.4 - 7.10; 2025.1.14; 2026.2.12
# >> docker build -t flask-server .
# >> docker build -t flask-server -f ./docker_flask/dockerfile .     << Working, 2024.7.6
# >> docker rmi $(docker images --filter "dangling=true" -q --no-trunc)
# >> docker system prune
# >> docker rmi $(docker images -q)       << Delete all images
# >> docker ps                             << List your running containers
# >> docker run -it --name my-container image-name    << Create and run container
# >> docker exec -it my-server /bin/bash   << Access the container’s shell


FROM python:3.10.14

ARG RUN_MODE=WET
    # DRY-RUN, WET-RUN
ENV PYTHONPATH=/app

# COPY ./docker_flask/app.py /app
WORKDIR $PYTHONPATH
COPY ["./docker_flask", "/app/docker_flask"]
COPY ./y /app/y
COPY ./finance /app/finance
COPY ./docker_flask/requirements.txt requirements.txt

# RUN apt-get update && apt-get install -y sudo:wget

# Install ping
RUN apt-get update && apt-get install -y iputils-ping
# Install vim
RUN apt-get update && apt-get install -y vim

# Install python modules
RUN if [ "$RUN_MODE" = "DRY" ]; then \
        pip install flask redis pymongo; \
    else \
        pip install --upgrade pip setuptools==78.1.1 wheel; \
        # install numpy first for ucrdtw build dependency \
        pip install numpy; \
        pip install ucrdtw==0.201 --no-build-isolation; \
        pip install --no-cache-dir -r requirements.txt; \
        # python -c "import numpy; print(numpy.__version__)"; \
        # python -c "from _ucrdtw import ucrdtw; print(ucrdtw.__version__)"; \
    fi

# Install ta-lib
RUN pip install TA-Lib-Precompiled
# ARG TA_LIB_TAR=ta-lib-0.4.0-src.tar.gz
# ARG TA_LIB_FOLDER=ta-lib
# RUN if [ "$RUN_MODE" = "WET 2025.1.14" ]; then \
    # apt-get update && \
        # apt-get install -y build-essential wget && \
        # rm -rf /var/lib/apt/lists/*; \
    # wget http://prdownloads.sourceforge.net/ta-lib/$TA_LIB_TAR && \
        # tar -xvzf $TA_LIB_TAR && \
        # cd $TA_LIB_FOLDER && \
        # ./configure --prefix=/usr && \
        # make && \
        # make install && \
        # cd .. && \
        # rm -rf $TA_LIB_FOLDER $TA_LIB_TAR; \
    # pip install TA-Lib; \
    # fi

# Clean up caches
RUN pip cache purge && apt-get clean && rm -rf /var/lib/apt/lists/*

EXPOSE 5000
    # ignored when using network_mode: host in your docker-compose.yml file, 2024.7.9

# CMDs before the last are ignored, 2024.7.10
# CMD ["python", "-V"]
# CMD ["python", "/app/docker_flask/app.py"]
# CMD ["python", "/app/finance/y_rocket_station.py"]
ENV RUN_MODE=$RUN_MODE
    # ARG is build time, ENV is run time, 2024.7.10
CMD if [ "$RUN_MODE" = "DRY" ]; then \
        python /app/docker_flask/app.py; \
    else \
        python /app/finance/y_rocket_station.py; \
    fi
