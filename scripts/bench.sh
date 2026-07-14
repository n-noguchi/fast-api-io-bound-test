#!/usr/bin/env bash
# bench.sh — 全エンドポイントを k6 でベンチし、JSON/テキストを k6/results に保存する (git bash 用)
# 使い方:
#   ./scripts/bench.sh                 # 既定のエンドポイントを既定条件でベンチ
#   VUS=200 DURATION=30s ./scripts/bench.sh
#   ENDPOINTS="/call/async-pooled /call/async-tuned" ./scripts/bench.sh
set -euo pipefail

cd "$(dirname "$0")/.."

# git bash(MSYS) がコンテナ内パス "/scripts/..." を Windows パスに変換するのを抑止。
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

mkdir -p k6/results

VUS="${VUS:-100}"
DURATION="${DURATION:-20s}"
RAMP="${RAMP:-5s}"

# 既定は 5 パターンをすべて計測。環境変数 ENDPOINTS で絞り込み可能。
if [[ -n "${ENDPOINTS:-}" ]]; then
  read -r -a EPS <<<"$ENDPOINTS"
else
  EPS=(
    "/call/sync-requests"
    "/call/sync-httpx"
    "/call/async-naive"
    "/call/async-pooled"
    "/call/async-tuned"
  )
fi

echo "==> bench config: VUS=$VUS DURATION=$DURATION RAMP=$RAMP"
echo "==> endpoints: ${EPS[*]}"

stamp="$(date +%Y%m%d-%H%M%S)"
for ep in "${EPS[@]}"; do
  # /call/async-tuned -> async-tuned
  name="${ep##*/}"
  out_name="${stamp}-${name}"
  echo
  echo "############ ENDPOINT: $ep  (out=${out_name}) ############"
  docker compose run --rm \
    -e ENDPOINT="$ep" \
    -e VUS="$VUS" \
    -e DURATION="$DURATION" \
    -e RAMP="$RAMP" \
    -e OUT_NAME="$out_name" \
    k6 run /scripts/test.js
done

echo
echo "==> done. raw summaries:"
ls -1 k6/results/${stamp}-*.json 2>/dev/null || true
echo "==> ./scripts/summarize.sh ${stamp}  で集計できます"
