#!/usr/bin/env bash
# bench_duckdb.sh -- DuckDB の並列度・接続数・メタデータキャッシュを k6 で比較 (git bash 用)
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"

COMPOSE="docker compose -f docker-compose.duckdb.yml -p iob-duck"
mkdir -p k6/results

VUS="${VUS:-20}"
DURATION="${DURATION:-20s}"
RAMP="${RAMP:-5s}"
CONNECTIONS_LIST="${DUCKDB_CONNECTIONS_LIST:-1 2 4 8}"
THREADS_LIST="${DUCKDB_THREADS_LIST:-1 2 4}"
# DataFusion results と同じ「キャッシュなし」を既定にする。キャッシュ比較は
# DUCKDB_COMPARE_CACHE=1 を指定した場合だけ追加で行う。
CACHE="${DUCKDB_OBJECT_CACHE:-0}"
COMPARE_CACHE="${DUCKDB_COMPARE_CACHE:-0}"
stamp="$(date +%Y%m%d-%H%M%S)"

recreate_api1c() {
  local connections="$1" threads="$2" cache="$3"
  DUCKDB_CONNECTIONS="$connections" DUCKDB_THREADS="$threads" DUCKDB_OBJECT_CACHE="$cache" \
    $COMPOSE up -d --force-recreate api1c >/dev/null
  for i in $(seq 1 90); do
    curl -sf --max-time 3 http://localhost:18002/health >/dev/null 2>&1 && break
    if [ "$i" = "90" ]; then
      echo "[ERROR] api1c did not become healthy" >&2
      exit 1
    fi
    sleep 1
  done
  # httpfs の初期化および parquet footer 取得を測定から除外する。
  curl -sf --max-time 60 "http://localhost:18002/query?tenantid=1&date_from=2000-01-01&date_to=2026-07-16" >/dev/null
}

run_k6() {
  local endpoint="$1" name="$2"
  echo "############ $name (VUS=$VUS DURATION=$DURATION) ############"
  $COMPOSE run --rm -e ENDPOINT="$endpoint" -e VUS="$VUS" -e DURATION="$DURATION" \
    -e RAMP="$RAMP" -e OUT_NAME="$name" k6duck run --quiet /scripts/test_duckdb.js || true
}

# 1) Query-level parallelism. Connections bound concurrent requests; threads
# bound a single query's parallel scan. Compare them independently first.
for connections in $CONNECTIONS_LIST; do
  recreate_api1c "$connections" 2 "$CACHE"
  run_k6 "/query" "${stamp}-conn${connections}-query"
done

for threads in $THREADS_LIST; do
  recreate_api1c 4 "$threads" "$CACHE"
  run_k6 "/query" "${stamp}-threads${threads}-query"
done

# 2) Object/metadata cache. Keep the other settings at their provisional default.
if [ "$COMPARE_CACHE" = "1" ]; then
  for cache in 0 1; do
    recreate_api1c 4 2 "$cache"
    run_k6 "/query" "${stamp}-cache${cache}-query"
  done
fi

# 3) Same pushdown contrast as the prior DataFusion benchmark.
recreate_api1c 4 2 "$CACHE"
run_k6 "/scan" "${stamp}-scan"

echo "==> done. ./scripts/summarize.sh ${stamp} で集計できます。"
