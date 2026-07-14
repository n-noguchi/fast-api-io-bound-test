"""
API1b — FastAPI + Apache DataFusion。

MinIO(S3互換) 上の parquet(1ファイル) を DataFusion で SQL クエリし、
tenantid / date 範囲 / dimension1 でフィルタした行を返す。

既存の api1(app.py) とは別ファイルで、httpx 経由の API2 呼び出しを行わない。
スループット最大化のチューニング探索は DataFusion 側の設定で行う:
  - DF_TARGET_PARTITIONS : クエリの並列度
  - DF_METADATA_CACHE    : object store のメタデータキャッシュ(on=1/off=0)
"""
from __future__ import annotations

import os
import re
import uuid
from contextlib import asynccontextmanager
from typing import Any

import datafusion
from datafusion import SessionConfig, SessionContext
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

MINIO_ENDPOINT_URL = os.environ.get("MINIO_ENDPOINT", "http://minio:9000")  # http://minio:9000
MINIO_HOST = MINIO_ENDPOINT_URL.replace("http://", "").replace("https://", "")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "data")
PARQUET_KEY = os.environ.get("PARQUET_KEY", "events.parquet")
# テーブル名: "events" は datafusion 43.1.0 で URL 内のファイル名(events.parquet)と衝突し
# "already exists" になるため、明示的に別名をつける。
TABLE_NAME = "evt"
TABLE_PATH = f"s3://{MINIO_BUCKET}/{PARQUET_KEY}"
DF_TARGET_PARTITIONS = int(os.environ.get("DF_TARGET_PARTITIONS", "4"))
DF_METADATA_CACHE = os.environ.get("DF_METADATA_CACHE", "1") == "1"

# object store の登録名(URL 中の host)。DataFusion は <host>://<path> で参照する。
STORE_HOST = "minio"


def build_context() -> SessionContext:
    config = SessionConfig()
    # 並列度のチューニング軸
    config.set("datafusion.execution.target_partitions", str(DF_TARGET_PARTITIONS))
    # parquet の非同期プリフェッチ(高同時で効果的)
    config.set("datafusion.execution.parquet.pushdown_filters", "true")
    config.set("datafusion.execution.parquet.reorder_filters", "true")
    config.set("datafusion.execution.meta_fetch_concurrency", "4")

    ctx = SessionContext(config=config)

    # MinIO を S3 互換 object store として明示登録。
    # 注意: datafusion 43.1.0 の register_object_store は url = format!("{}{}", scheme, host)
    # と "://" を挟まず単純結合する。したがって scheme="s3://" + host=バケット名 で
    # "s3://data" を作る必要がある(BUG 的挙動の回避策)。
    from datafusion.object_store import AmazonS3

    s3 = AmazonS3(
        bucket_name=MINIO_BUCKET,
        region="us-east-1",
        access_key_id=MINIO_ACCESS_KEY,
        secret_access_key=MINIO_SECRET_KEY,
        endpoint=MINIO_ENDPOINT_URL,
        allow_http=True,
    )
    ctx.register_object_store("s3://", s3, host=MINIO_BUCKET)
    print(f"[api1b] registered S3 object store -> s3://{MINIO_BUCKET}", flush=True)

    # メモリ内キャッシュを設けないため、parquet の事前登録(register_parquet)は行わず、
    # 各クエリで read_parquet で都度 MinIO から新規に読み込む(listing/schema/footer も毎回取得)。
    print(
        f"[api1b] object store ready (target_partitions={DF_TARGET_PARTITIONS}, "
        f"metadata_cache=OFF, per-query read_parquet)",
        flush=True,
    )
    return ctx


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ctx = build_context()
    yield
    # SessionContext に明示的な close は不要(GC)


app = FastAPI(title="api1b-datafusion", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "server": "api1b-datafusion"}


_INT_RE = re.compile(r"^-?\d+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DIM_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _to_jsonable(v: Any) -> Any:
    # pyarrow の date32/date64, date オブジェクト等を JSON 可能に
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


@app.get("/query")
async def query(
    tenantid: int = Query(..., ge=1, le=1000),
    date_from: str = Query(...),
    date_to: str = Query(...),
):
    if not _DATE_RE.match(date_from) or not _DATE_RE.match(date_to):
        return JSONResponse({"error": "date must be YYYY-MM-DD"}, status_code=400)

    ctx: SessionContext = app.state.ctx
    # メモリ内キャッシュなし: クエリごとに新規テーブルを都度 register して即 deregister
    # (listing/schema/footer を毎回 MinIO から取得する)。
    tbl = "q" + uuid.uuid4().hex[:8]
    ctx.register_parquet(tbl, TABLE_PATH)
    try:
        sql = (
            "SELECT dimension1, SUM(value1) AS sum_value1 "
            f"FROM {tbl} "
            f"WHERE tenantid = {int(tenantid)} "
            f"  AND date >= DATE '{date_from}' "
            f"  AND date <= DATE '{date_to}' "
            f"GROUP BY dimension1 "
            f"ORDER BY dimension1"
        )
        batches = ctx.sql(sql).collect()
    finally:
        try:
            ctx.deregister_table(tbl)
        except Exception:
            pass

    rows: list[dict[str, Any]] = []
    for batch in batches:
        d = batch.to_pydict()
        n = len(next(iter(d.values())))
        for i in range(n):
            rows.append({k: _to_jsonable(v[i]) for k, v in d.items()})

    return JSONResponse({"count": len(rows), "rows": rows})


# pushdown 効果の比較用: tenantid/date を使わない(全 row group スキャンになる)クエリ
@app.get("/scan")
async def scan(
    dimension1: str = Query(...),
    limit: int = Query(100, ge=1, le=10000),
):
    if not _DIM_RE.match(dimension1):
        return JSONResponse({"error": "dimension1 must be alphanumeric"}, status_code=400)
    ctx: SessionContext = app.state.ctx
    tbl = "q" + uuid.uuid4().hex[:8]
    ctx.register_parquet(tbl, TABLE_PATH)
    try:
        sql = (
            "SELECT tenantid, date, dimension1, dimension2, value1 "
            f"FROM {tbl} "
            f"WHERE dimension1 = '{dimension1}' "
            f"LIMIT {int(limit)}"
        )
        batches = ctx.sql(sql).collect()
    finally:
        try:
            ctx.deregister_table(tbl)
        except Exception:
            pass
    rows: list[dict[str, Any]] = []
    for batch in batches:
        d = batch.to_pydict()
        n = len(next(iter(d.values())))
        for i in range(n):
            rows.append({k: _to_jsonable(v[i]) for k, v in d.items()})
    return JSONResponse({"count": len(rows), "rows": rows})
