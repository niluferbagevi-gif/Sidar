FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

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
