#!/usr/bin/env bash
# run_duckdb.sh -- prior events.parquet を使う DuckDB + MinIO 検証を起動 (git bash 用)
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"

DF_COMPOSE="docker compose -f docker-compose.datafusion.yml -p iob-df"
COMPOSE="docker compose -f docker-compose.duckdb.yml -p iob-duck"

echo "==> ensure prior MinIO and s3://data/events.parquet are available"
$DF_COMPOSE up -d minio
$DF_COMPOSE up -d minio-init

for i in $(seq 1 90); do
  if $DF_COMPOSE exec -T minio mc alias set local http://localhost:9000 minioadmin minioadmin >/dev/null 2>&1 \
    && $DF_COMPOSE exec -T minio mc stat local/data/events.parquet >/dev/null 2>&1; then
    break
  fi
  if [ "$i" = "90" ]; then
    echo "[ERROR] s3://data/events.parquet が見つかりません。先に ./scripts/gen_data.sh を実行してください。" >&2
    exit 1
  fi
  sleep 1
done

echo "==> build and start api1c"
$COMPOSE build api1c
$COMPOSE up -d api1c

for i in $(seq 1 90); do
  if curl -sf --max-time 3 http://localhost:18002/health >/dev/null 2>&1; then
    echo "==> DuckDB stack ready: http://localhost:18002"
    exit 0
  fi
  sleep 1
done

echo "[ERROR] api1c did not become healthy" >&2
exit 1
