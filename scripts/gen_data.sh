#!/usr/bin/env bash
# gen_data.sh — Spark で parquet を生成し MinIO へアップロード (git bash 用)
# 使い方:
#   ./scripts/gen_data.sh              # NUM_ROWS 既定(1億) -> 約1GB
#   NUM_ROWS=20000000 ./scripts/gen_data.sh   # サイズ調整用
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"

COMPOSE="docker compose -f docker-compose.datafusion.yml -p iob-df"

echo "==> ensure minio is up"
$COMPOSE up -d minio
$COMPOSE up -d minio-init

echo "==> run datagen (NUM_ROWS=${NUM_ROWS:-100000000})"
NUM_ROWS="${NUM_ROWS:-100000000}" $COMPOSE run --rm --build datagen

echo "==> done. MinIO に events.parquet が配置されました"
$COMPOSE exec -T minio mc alias set local http://localhost:9000 minioadmin minioadmin >/dev/null 2>&1 || true
$COMPOSE exec -T minio mc ls local/data/ 2>/dev/null || true
