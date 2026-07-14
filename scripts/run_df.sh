#!/usr/bin/env bash
# run_df.sh — MinIO + API1b(DataFusion) を起動しヘルスチェック (git bash 用)
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"

COMPOSE="docker compose -f docker-compose.datafusion.yml -p iob-df"

echo "==> build api1b"
$COMPOSE build api1b

echo "==> up -d minio minio-init api1b"
export DF_TARGET_PARTITIONS="${DF_TARGET_PARTITIONS:-4}"
export DF_METADATA_CACHE="${DF_METADATA_CACHE:-1}"
$COMPOSE up -d minio
$COMPOSE up -d minio-init
$COMPOSE up -d api1b

wait_for() {
  local name="$1" url="$2"
  echo "==> waiting for $name ($url) ..."
  local ok=0 i
  for i in $(seq 1 90); do
    if curl -sf --max-time 3 "$url" >/dev/null 2>&1; then
      ok=$((ok+1)); [ "$ok" -ge 3 ] && { echo "    $name is up"; return 0; }
    else
      ok=0
    fi
    sleep 1
  done
  echo "    [ERROR] $name not healthy" >&2; return 1
}

wait_for "minio" "http://localhost:19000/minio/health/live"
wait_for "api1b" "http://localhost:18001/health"
echo "==> datafusion stack ready"
echo "    minio console : http://localhost:19001 (minioadmin/minioadmin)"
echo "    api1b health  : http://localhost:18001/health"
