#!/usr/bin/env bash
# down_df.sh — datafusion スタックを停止 (git bash 用)
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose -f docker-compose.datafusion.yml -p iob-df down --remove-orphans
