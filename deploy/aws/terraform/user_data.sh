#!/bin/bash
# First boot of the instance (Amazon Linux 2023): Docker + Compose. The application itself is
# installed by deploy.py through SSM (deploy/aws/server/bootstrap.sh).
set -euxo pipefail
dnf install -y docker
systemctl enable --now docker
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
# 2 GB swap: the 4 GB instance briefly needs more while loading meshes and embeddings
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile swap swap defaults 0 0' >> /etc/fstab
mkdir -p /opt/cochleahub
