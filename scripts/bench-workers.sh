#!/usr/bin/env bash
# bench-workers.sh — async-tuned(最速パターン) で uvicorn ワーカー数を変えて探索する (git bash 用)
# 使い方: ./scripts/bench-workers.sh
set -euo pipefail

cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

VUS="${VUS:-100}"
DURATION="${DURATION:-20s}"
RAMP="${RAMP:-5s}"
ENDPOINT="${ENDPOINT:-/call/async-tuned}"
WORKERS_LIST="${WORKERS_LIST:-1 2 4}"

run_w() {
  local w="$1"
  echo "===================== workers=$w (endpoint=$ENDPOINT) ====================="
  UVICORN_WORKERS="$w" docker compose up -d --force-recreate api1 >/dev/null 2>&1
  # health が連続で成功するまで待ち、さらに settle する (全ワーカーの起動を保証)
  local ok=0
  for i in $(seq 1 60); do
    if curl -sf --max-time 3 http://localhost:18000/health >/dev/null 2>&1; then
      ok=$((ok + 1))
      [ "$ok" -ge 5 ] && break
    else
      ok=0
    fi
    sleep 1
  done
  sleep 4
  # 探索なので threshold 超過で止めず、結果を記録する
  docker compose run --rm \
    -e ENDPOINT="$ENDPOINT" \
    -e VUS="$VUS" \
    -e DURATION="$DURATION" \
    -e RAMP="$RAMP" \
    -e OUT_NAME="w${w}-${ENDPOINT##*/}" \
    k6 run --quiet /scripts/test.js || true
  echo
}

for w in $WORKERS_LIST; do
  run_w "$w"
done

echo "ALL DONE"
