#!/bin/bash
set -euxo pipefail

# IST timezone for cron schedules
timedatectl set-timezone Asia/Kolkata

# 2 GB swap (prevents OOM on 1 GB RAM)
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  sysctl vm.swappiness=10
  echo 'vm.swappiness=10' >> /etc/sysctl.conf
fi

apt-get update -y
apt-get install -y python3-venv python3-pip git unzip jq

# SSM agent ships as a snap on Ubuntu 24.04
snap start amazon-ssm-agent || true

# App directory (code deployed later by GitHub Actions via SSM)
mkdir -p /opt/equity-pulse
chown ubuntu:ubuntu /opt/equity-pulse
sudo -u ubuntu python3 -m venv /opt/equity-pulse/.venv
