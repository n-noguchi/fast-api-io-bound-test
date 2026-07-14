#!/usr/bin/env bash
# bench_df.sh — DataFusion のチューニング軸を変えて k6 ベンチ (git bash 用)
#
# 探索軸:
#   1) target_partitions (1/2/4/8)  ... DF_TARGET_PARTITIONS_LIST で上書き可
#   2) metadata_cache (0/1)         ... 行わないなら DF_NO_MC=1
#   3) predicate pushdown 効果       ... /query vs /scan (DF_PUSHDOWN=1 で追加計測)
#
# 使い方:
#   ./scripts/bench_df.sh
#   VUS=40 DURATION=30s ./scripts/bench_df.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"

COMPOSE="docker compose -f docker-compose.datafusion.yml -p iob-df"
mkdir -p k6/results

VUS="${VUS:-20}"
DURATION="${DURATION:-20s}"
RAMP="${RAMP:-5s}"
TP_LIST="${DF_TARGET_PARTITIONS_LIST:-1 2 4 8}"
DO_MC="${DF_NO_MC:-0}"        # 0=metadata_cache も計測, 1=スキップ
DO_PD="${DF_PUSHDOWN:-1}"     # 1=/query vs /scan も計測

stamp="$(date +%Y%m%d-%H%M%S)"

recreate_api1b() {  # env を渡して api1b を再作成 + ウォームアップ
  local tp="$1" mc="$2"
  DF_TARGET_PARTITIONS="$tp" DF_METADATA_CACHE="$mc" \
    $COMPOSE up -d --force-recreate api1b >/dev/null 2>&1
  local ok=0 i
  for i in $(seq 1 90); do
    curl -sf --max-time 3 http://localhost:18001/health >/dev/null 2>&1 && { ok=$((ok+1)); [ "$ok" -ge 3 ] && break; } || ok=0
    sleep 1
  done
  sleep 3
  # ウォームアップ: 最初のクエリでメタデータ取得を行わせる
  curl -sf --max-time 60 "http://localhost:18001/query?tenantid=1&date_from=2000-01-01&date_to=2026-07-16" >/dev/null 2>&1 || true
  sleep 1
}

run_k6() {
  local ep="$1" out="$2"
  echo "############ $out (VUS=$VUS DURATION=$DURATION) ############"
  $COMPOSE run --rm \
    -e ENDPOINT="$ep" -e VUS="$VUS" -e DURATION="$DURATION" -e RAMP="$RAMP" \
    -e OUT_NAME="$out" \
    k6df run --quiet /scripts/test_datafusion.js || true
  echo
}

# --- 1) target_partitions 探索 (/query, metadata_cache=1) ---
for tp in $TP_LIST; do
  recreate_api1b "$tp" 1
  run_k6 "/query" "${stamp}-tp${tp}-query"
done

# --- 2) metadata_cache 探索 (tp=4, /query) ---
if [ "$DO_MC" = "0" ]; then
  for mc in 0 1; do
    recreate_api1b 4 "$mc"
    run_k6 "/query" "${stamp}-mc${mc}-query"
  done
fi

# --- 3) predicate pushdown 効果 (/query vs /scan), tp=4 ---
if [ "$DO_PD" = "1" ]; then
  recreate_api1b 4 1
  run_k6 "/scan" "${stamp}-pd-scan"
fi

echo "==> done. ./scripts/summarize.sh ${stamp}  で集計"
