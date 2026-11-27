#!/usr/bin/env bash
# One-time setup for Ubuntu 24.04 on EC2
set -euo pipefail

curl -fsSL https://get.docker.com | sudo sh        # Docker engine + compose plugin
sudo usermod -aG docker "$USER"
sudo apt-get install -y git

# 2 GB swap as a safety net against memory spikes
if [ ! -f /swapfile ]; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

echo "Done. Log out and back in so the 'docker' group takes effect."