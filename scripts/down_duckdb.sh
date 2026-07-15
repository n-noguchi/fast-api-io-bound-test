#!/usr/bin/env bash
# down_duckdb.sh -- DuckDB API/k6 のみを停止。前回 parquet の MinIO volume は残す。
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose -f docker-compose.duckdb.yml -p iob-duck down --remove-orphans
