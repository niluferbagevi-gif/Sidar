FROM mcr.microsoft.com/devcontainers/python:1-3.11-bookworm

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
# `fatal error: portaudio.h: No such file or directory`.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*
