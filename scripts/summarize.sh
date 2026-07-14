#!/usr/bin/env bash
# summarize.sh — k6 結果を Markdown 表に集計 (git bash 用, python 使用 / jq 不要)
# 使い方:
#   ./scripts/summarize.sh                   # 最新スタンプの結果を集計
#   ./scripts/summarize.sh 20260715-002254   # 指定スタンプを集計
#   ./scripts/summarize.sh w                 # "w" で始まる結果(w1/w2/w4)を集計
set -euo pipefail
cd "$(dirname "$0")/.."

PY="$(command -v python || command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "[ERROR] python が必要です (jq は不要)。" >&2
  exit 1
fi

if [ -n "${1:-}" ]; then
  prefix="$1"
else
  prefix="$(ls -1 k6/results/ 2>/dev/null | grep -oE '^[0-9]{8}-[0-9]{6}' | sort -u | tail -n1 || true)"
  if [ -z "$prefix" ]; then
    echo "[ERROR] k6/results に結果がありません。" >&2
    exit 1
  fi
fi

shopt -s nullglob
files=( k6/results/${prefix}*.json )
shopt -u nullglob

if [ ${#files[@]} -eq 0 ]; then
  echo "[ERROR] '${prefix}' に一致する結果が見つかりません。" >&2
  exit 1
fi

"$PY" scripts/summarize.py "${files[@]}"
