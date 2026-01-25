#!/usr/bin/env bash
set -e
cd /opt/GooseGooseDuck
git pull --ff-only
/opt/ggd-venv/bin/pip install -r requirements.txt
sudo systemctl restart ggd
journalctl -u ggd -n 50 --no-pager
