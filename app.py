"""
y, app.py
2023.8.18, 8.20
2024.7.4 - 10
"""

from flask import Flask
import redis  # https://github.com/microsoftarchive/redis/releases  >> 3.0.504 latest, 2023.1.10
import os
import pymongo
from urllib.parse import urlparse

mongo_uri = os.getenv('MONGO_URI', None)
if mongo_uri:
    print(f"{mongo_uri=}")
else:
    raise AssertionError(f"failed to get environment variable MONGO_URI={mongo_uri}")
mongo_client = pymongo.MongoClient(host=mongo_uri, tz_aware=True)
print(f"{mongo_client.admin.command('ping')=}")
print(f"{mongo_client.list_database_names()=}")

if False:
    redis_host, redis_port = 'redis', 6379
    redis_client = redis.Redis(host=redis_host, port=redis_port)
    # redis_client = redis.StrictRedis(host='localhost', port=redis_port, db=0)
    redis_uri = f"redis://{redis_host}:{redis_port}"
else:
    redis_uri = os.getenv('REDIS_URI', 'redis://localhost:6379')
    redis_client = redis.from_url(redis_uri, db=0, socket_connect_timeout=5)
parsed_url = urlparse(redis_uri)
redis_host = parsed_url.hostname
redis_port = parsed_url.port
try:
    response = redis_client.ping()
    if response:
        print(f"Redis: Server Running !! {response=}")
    else:
        print(f"Redis: Failed to connect to the server {redis_host, redis_port}")
except (redis.ConnectionError, redis.TimeoutError):
    raise ConnectionError(f"Redis: Could not connect to the server {redis_host, redis_port}")


app = Flask(__name__)


@app.route('/')
def hello():
    redis_client.incr('hits')
    counter = str(redis_client.get('hits'), 'utf-8')
    return "Welcome to this webpage!, This webpage has been viewed " + counter + " time(s)"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
