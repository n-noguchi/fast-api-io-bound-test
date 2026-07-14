#!/usr/bin/env python3
"""k6 結果 JSON を読んで Markdown 表を stdout に出力する。jq 不要。"""
import json
import os
import sys


def extract(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    m = d["metrics"]
    h = m["http_reqs"]["values"]
    t = m["http_req_duration"]["values"]
    fail = m["http_req_failed"]["values"]
    return {
        "name": os.path.basename(path)[: -len(".json")],
        "count": h["count"],
        "rps": h["rate"],
        "p50": t.get("med"),
        "p90": t.get("p(90)"),
        "p95": t.get("p(95)"),
        "max": t["max"],
        "fail": fail["rate"],
    }


def fmt(v, nd=2):
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else "n/a"


def main(argv):
    files = argv[1:]
    if not files:
        sys.stderr.write("usage: summarize.py result.json [result2.json ...]\n")
        return 1
    rows = [extract(p) for p in sorted(files)]
    print("| name | http_reqs | req/s | p50(ms) | p90(ms) | p95(ms) | max(ms) | fail(%) |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        print("| {} | {} | {} | {} | {} | {} | {} | {} |".format(
            r["name"], r["count"], fmt(r["rps"]),
            fmt(r["p50"]), fmt(r["p90"]), fmt(r["p95"]),
            fmt(r["max"]), fmt(r["fail"] * 100),
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
