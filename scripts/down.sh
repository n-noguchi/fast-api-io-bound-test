#!/usr/bin/env bash
# down.sh — コンテナを停止・削除 (git bash 用)
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose down --remove-orphans
