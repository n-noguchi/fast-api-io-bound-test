"""
API1 (FastAPI) — API2(Go) を呼び出すプロキシ。

IOバウンドな上流呼び出し(API2 の 0.5s sleep)を、複数の実装パターンで比較できるよう
エンドポイントを分けている。各パターンは同じ仕事(= API2 を1回呼ぶ)を行い、
クライアントの生成方法 / 同期・非同期 / 接続プールの扱いだけを変える。
"""
from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from typing import Any

import httpx
import requests
from fastapi import FastAPI
from fastapi.responses import JSONResponse

API2_BASE_URL = os.environ.get("API2_BASE_URL", "http://api2:8080")
API2_URL = f"{API2_BASE_URL}/slow"
TIMEOUT = 10.0

# 起動時に1度だけ生成し、全リクエストで使い回す共有クライアント(keep-alive)。
# httpx は接続プールを内蔵しているため、これが最も効率的。
_pooled_client: httpx.AsyncClient | None = None
_tuned_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pooled_client, _tuned_client
    _pooled_client = httpx.AsyncClient(timeout=TIMEOUT)
    # 接続プール上限を拡張したクライアント。高同時接続で keep-alive を維持しやすくする。
    _tuned_client = httpx.AsyncClient(
        timeout=TIMEOUT,
        limits=httpx.Limits(
            max_connections=1000,
            max_keepalive_connections=500,
            keepalive_expiry=30.0,
        ),
    )
    try:
        yield
    finally:
        await _pooled_client.aclose()
        await _tuned_client.aclose()


app = FastAPI(title="api1-fastapi", lifespan=lifespan)


def _resp(elapsed_ms: float, upstream: dict[str, Any]) -> dict[str, Any]:
    return {"server": "api1-fastapi", "elapsed_ms": round(elapsed_ms, 2), "upstream": upstream}


@app.get("/health")
async def health():
    return {"status": "ok", "server": "api1-fastapi"}


# --- パターン1: 同期 requests (Starlette のスレッドプールで実行) -----------------
# IO 待ちの間スレッドを占有する。スレッドプール(既定40)が上限なので同時実行数が頭打ち。
@app.get("/call/sync-requests")
def call_sync_requests():
    t0 = time.perf_counter()
    r = requests.get(API2_URL, timeout=TIMEOUT)
    return JSONResponse(_resp((time.perf_counter() - t0) * 1000, r.json()))


# --- パターン2: 同期 httpx (同じくスレッドプール) -------------------------------
@app.get("/call/sync-httpx")
def call_sync_httpx():
    t0 = time.perf_counter()
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.get(API2_URL)
    return JSONResponse(_resp((time.perf_counter() - t0) * 1000, r.json()))


# --- パターン3: 非同期だがリクエスト毎にクライアント新規作成 ---------------------
# 接続確立(TCP+HTTP)が毎回発生するため keep-alive の恩恵が得られず遅い。
@app.get("/call/async-naive")
async def call_async_naive():
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(API2_URL)
    return JSONResponse(_resp((time.perf_counter() - t0) * 1000, r.json()))


# --- パターン4: 共有 AsyncClient(keep-alive) — 推奨基本形 -----------------------
# 1つのイベントループ上で多数の待機を並行できるうえ、接続も再利用される。
@app.get("/call/async-pooled")
async def call_async_pooled():
    t0 = time.perf_counter()
    r = await _pooled_client.get(API2_URL)
    return JSONResponse(_resp((time.perf_counter() - t0) * 1000, r.json()))


# --- パターン5: 共有 AsyncClient + 接続プール上限拡張 ---------------------------
@app.get("/call/async-tuned")
async def call_async_tuned():
    t0 = time.perf_counter()
    r = await _tuned_client.get(API2_URL)
    return JSONResponse(_resp((time.perf_counter() - t0) * 1000, r.json()))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
