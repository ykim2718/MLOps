docker --version
docker-compose --version
docker image prune -f
:: docker rmi $(docker images --filter "dangling=true" -q --no-trunc)
:: docker rm -f $(docker ps -aq)
:: docker rmi -f $(docker images -q)        remove all images
docker rmi -f flask redis
:: docker-compose up --build --detach
docker rm -f redis my-server
set Y66='%Y^^%'
docker-compose up --build
:: docker port <my-container>               list the port mappings for a specific container.
docker port debugging-container
:: exit /b 0