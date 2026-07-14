#!/usr/bin/env bash
# run.sh — ビルド & 起動 & ヘルスチェック (git bash 用)
set -euo pipefail

# スクリプトのあるディレクトリの親(プロジェクトルート)へ移動
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
echo "project root: $ROOT"

echo "==> docker compose build (api1, api2)"
docker compose build api1 api2

echo "==> docker compose up -d api1 api2"
# UVICORN_WORKERS が未設定なら 1。環境変数で上書き可能。
export UVICORN_WORKERS="${UVICORN_WORKERS:-1}"
docker compose up -d api1 api2

wait_for() {
  local name="$1" url="$2"
  echo "==> waiting for $name ($url) ..."
  local i
  for i in $(seq 1 60); do
    if curl -sf --max-time 3 "$url" >/dev/null 2>&1; then
      echo "    $name is up (after ${i}s)"
      return 0
    fi
    sleep 1
  done
  echo "    [ERROR] $name did not become healthy" >&2
  return 1
}

wait_for "api2" "http://localhost:18080/health"
wait_for "api1" "http://localhost:18000/health"

echo "==> services are ready"
echo "    api1: http://localhost:18000  (api2 へのプロキシ)"
echo "    api2: http://localhost:18080  (0.5s sleep)"
echo "    sample: curl http://localhost:18000/call/async-tuned"
