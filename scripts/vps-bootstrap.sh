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

# An openssh upgrade restarts ssh.service, and on Ubuntu 24.04 the restart deleted /run/sshd: every
# new login then failed with "chroot(/run/sshd): No such file or directory" until a reboot.
mkdir -p /etc/systemd/system/ssh.service.d
printf '[Service]\nRuntimeDirectoryPreserve=yes\n' > /etc/systemd/system/ssh.service.d/10-keep-privsep-dir.conf
echo 'd /run/sshd 0755 root root -' > /etc/tmpfiles.d/sshd-privsep.conf

# Security updates still install every day, but at 02:00 Vietnam time, not while the demo is watched.
for timer in apt-daily:18:30 apt-daily-upgrade:19:00; do
  mkdir -p "/etc/systemd/system/${timer%%:*}.timer.d"
  printf '[Timer]\nOnCalendar=\nOnCalendar=*-*-* %s\nRandomizedDelaySec=20m\n' "${timer#*:}" \
    > "/etc/systemd/system/${timer%%:*}.timer.d/10-night.conf"
done
systemctl daemon-reload
systemd-tmpfiles --create /etc/tmpfiles.d/sshd-privsep.conf

mkdir -p /opt/firstlight/infra

docker --version
docker compose version
ufw status | head -8
