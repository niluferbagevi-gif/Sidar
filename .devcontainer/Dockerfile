ARG UV_VERSION=0.11.12
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv
FROM mcr.microsoft.com/devcontainers/python:1-3.11-bookworm

COPY --from=uv /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=.venv-container \
    SIDAR_PYTHON_VERSION=3.11 \
    CODING_MODEL=qwen2.5-coder:7b \
    OLLAMA_REQUIRED_MODELS=qwen2.5-coder:7b \
    OLLAMA_MODEL_SYNC=auto \
    AUTONOMOUS_LOOP_COVERAGE_PROFILE=full \
    AUTONOMOUS_LOOP_OPERATION_PROFILE=coverage-campaign \
    ENABLE_GPU_TESTS=1

# Pin uv in the image so updateContent/postCreate does not spend time
# bootstrapping it on every fresh Dev Container. The setup script still keeps
# a fallback installer for non-standard base images.
#
# Keep the image Python version aligned with Sidar's default local development
# runtime (SIDAR_PYTHON_VERSION=3.11). This avoids an extra managed-Python
# download during postCreate on WSL/Dev Containers hosts and makes the VS Code
# interpreter path deterministic.

# The upstream devcontainer image can include a preconfigured Yarn APT source.
# When that source has a missing/rotated GPG key, Dev Container features that run
# apt-get update (for example common-utils) fail before the workspace is created.
# Sidar does not install Node/Yarn from this repository during container build, so
# remove the stale source early and let features install against healthy Debian repos.
RUN rm -f \
    /etc/apt/sources.list.d/yarn.list \
    /etc/apt/sources.list.d/yarn.sources \
    /usr/share/keyrings/yarnkey.gpg \
    /usr/share/keyrings/yarn-archive-keyring.gpg

# `uv sync --frozen --all-extras` installs the `voice` extra, whose PyAudio
# wheel can fall back to a local build on Linux. Provide PortAudio headers at
# image-build time so updateContent/postCreate dependency syncs do not fail with
# `fatal error: portaudio.h: No such file or directory`. Also install zstd
# before postCreate so the official Ollama installer can extract its current
# Zstandard-compressed release archives reliably.
#
# Install the Docker client as well. Dev Containers still require a host Docker
# daemon to build this image, but once the workspace is running Sidar scripts and
# contributors can execute Docker/Compose commands through the mounted host
# socket without having to bootstrap the CLI manually inside the container.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        portaudio19-dev \
        zstd \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && . /etc/os-release \
    && printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian %s stable\n' "$(dpkg --print-architecture)" "${VERSION_CODENAME}" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        docker-buildx-plugin \
        docker-ce-cli \
        docker-compose-plugin \
    && docker --version \
    && docker compose version \
    && rm -rf /var/lib/apt/lists/*
