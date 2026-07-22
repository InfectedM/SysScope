#!/usr/bin/env bash
# Instalador do SysScope: dependências de tracing, venv e serviços systemd.
set -euo pipefail

DEST=/opt/sysscope
USER_NAME=${SUDO_USER:-$(whoami)}

if [[ $(id -u) -eq 0 && -z "${SUDO_USER:-}" ]]; then
  echo "Corre este script com sudo a partir do teu utilizador normal, não como root direto." >&2
  exit 1
fi

echo "==> A instalar dependências de sistema"
sudo apt-get update
sudo apt-get install -y hdparm smartmontools python3-venv rsync

echo "==> A copiar o projeto para $DEST"
sudo mkdir -p "$DEST"
sudo cp -r sysscope pyproject.toml "$DEST/"

echo "==> A criar o virtualenv"
sudo python3 -m venv "$DEST/.venv"
sudo "$DEST/.venv/bin/pip" install -q --upgrade pip
sudo "$DEST/.venv/bin/pip" install -q fastapi "uvicorn[standard]" psutil

echo "==> A criar diretórios de dados"
sudo mkdir -p /var/lib/sysscope /etc/sysscope
sudo chown "$USER_NAME" /var/lib/sysscope

echo "==> A instalar serviços systemd"
sudo sed "s/^User=infectedserver/User=$USER_NAME/" systemd/sysscope-web.service \
  | sudo tee /etc/systemd/system/sysscope-web.service >/dev/null
sudo cp systemd/sysscope-collector.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sysscope-collector.service sysscope-web.service

echo "==> Feito. Dashboard em http://127.0.0.1:8787"
