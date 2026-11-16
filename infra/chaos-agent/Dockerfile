# Chaos agent: the only container that may reach the Docker socket.
# See agent.py and docs/chaos.md. It is the Python standard library plus the
# docker command-line client; nothing is installed with pip.
FROM python:3.12-alpine

RUN apk add --no-cache docker-cli

# The container runs with a read-only root filesystem: no .pyc files, and the
# docker client keeps its (empty) config under the tmpfs at /tmp.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DOCKER_CONFIG=/tmp/docker

COPY agent.py /agent.py

# Informational only: the port is never published to the host.
EXPOSE 8081

CMD ["python", "/agent.py"]
