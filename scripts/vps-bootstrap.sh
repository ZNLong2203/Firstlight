#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu VPS for Firstlight. Safe to run again.
# Usage on the server, as root:  SSH_PORT=22 bash vps-bootstrap.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
SSH_PORT="${SSH_PORT:-22}"

apt-get update -q
apt-get install -yq ca-certificates curl rsync ufw fail2ban

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

# Swap keeps a PyTorch memory spike from getting the brain killed on a 4 GB machine.
if ! swapon --show | grep -q '^/swapfile'; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Only SSH, HTTP and HTTPS are reachable. Containers other than Caddy bind to 127.0.0.1.
ufw allow "${SSH_PORT}/tcp"
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

systemctl enable --now fail2ban
mkdir -p /opt/firstlight/infra

docker --version
docker compose version
ufw status | head -8
