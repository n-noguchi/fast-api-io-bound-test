"""API1c: FastAPI + DuckDB that queries the existing MinIO parquet file.

The blocking DuckDB client is run in a worker thread.  A pool of cursors from
one in-memory DuckDB database lets requests run concurrently while sharing the
httpfs/object metadata cache.
"""
from __future__ import annotations

import asyncio
import os
import re
from contextlib import asynccontextmanager
from typing import Any

import duckdb
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "data")
PARQUET_KEY = os.environ.get("PARQUET_KEY", "events.parquet")
PARQUET_PATH = f"s3://{MINIO_BUCKET}/{PARQUET_KEY}".replace("'", "''")

# A single remote-parquet query already uses DuckDB worker threads.  Keeping
# the default pool at one avoids nested parallelism under high VU load.
DUCKDB_CONNECTIONS = int(os.environ.get("DUCKDB_CONNECTIONS", "1"))
DUCKDB_THREADS = int(os.environ.get("DUCKDB_THREADS", "2"))
DUCKDB_OBJECT_CACHE = os.environ.get("DUCKDB_OBJECT_CACHE", "1") == "1"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DIM_RE = re.compile(r"^[A-Za-z0-9_]+$")


def configure(connection: duckdb.DuckDBPyConnection) -> None:
    """Load httpfs and configure a path-style, HTTP MinIO endpoint."""
    connection.execute("LOAD httpfs")
    connection.execute(f"SET s3_endpoint = {sql_literal(MINIO_ENDPOINT)}")
    connection.execute(f"SET s3_access_key_id = {sql_literal(MINIO_ACCESS_KEY)}")
    connection.execute(f"SET s3_secret_access_key = {sql_literal(MINIO_SECRET_KEY)}")
    connection.execute("SET s3_region = 'us-east-1'")
    connection.execute("SET s3_url_style = 'path'")
    connection.execute("SET s3_use_ssl = false")
    connection.execute(f"SET threads = {DUCKDB_THREADS}")
    connection.execute(f"SET enable_object_cache = {'true' if DUCKDB_OBJECT_CACHE else 'false'}")


def sql_literal(value: str) -> str:
    """Return a SQL string literal for trusted environment configuration."""
    return "'" + value.replace("'", "''") + "'"


class DuckDBPool:
    def __init__(self) -> None:
        if DUCKDB_CONNECTIONS < 1 or DUCKDB_THREADS < 1:
            raise ValueError("DUCKDB_CONNECTIONS and DUCKDB_THREADS must be positive")

        # cursor() creates independent connections to the same DatabaseInstance.
        # This is important: each request may execute concurrently, but httpfs
        # metadata/object cache is still shared by the pool.
        self.anchor = duckdb.connect(database=":memory:")
        configure(self.anchor)
        self.connections: asyncio.Queue[duckdb.DuckDBPyConnection] = asyncio.Queue(
            maxsize=DUCKDB_CONNECTIONS
        )
        for _ in range(DUCKDB_CONNECTIONS):
            connection = self.anchor.cursor()
            configure(connection)
            self.connections.put_nowait(connection)

    def close(self) -> None:
        while not self.connections.empty():
            self.connections.get_nowait().close()
        self.anchor.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = DuckDBPool()
    app.state.pool = pool
    print(
        "[api1c] DuckDB ready "
        f"(connections={DUCKDB_CONNECTIONS}, threads={DUCKDB_THREADS}, "
        f"object_cache={'on' if DUCKDB_OBJECT_CACHE else 'off'}, path=s3://{MINIO_BUCKET}/{PARQUET_KEY})",
        flush=True,
    )
    yield
    pool.close()


app = FastAPI(title="api1c-duckdb", lifespan=lifespan)


def rows_from_query(
    connection: duckdb.DuckDBPyConnection, sql: str, params: list[Any]
) -> list[dict[str, Any]]:
    result = connection.execute(sql, params)
    columns = [column[0] for column in result.description]
    rows: list[dict[str, Any]] = []
    for values in result.fetchall():
        rows.append(
            {
                column: value.isoformat() if hasattr(value, "isoformat") else value
                for column, value in zip(columns, values)
            }
        )
    return rows


async def execute(sql: str, params: list[Any]) -> list[dict[str, Any]]:
    pool: DuckDBPool = app.state.pool
    connection = await pool.connections.get()
    try:
        # DuckDB is synchronous. Offload it so connection-pool waits and other
        # FastAPI requests never block the event loop.
        return await asyncio.to_thread(rows_from_query, connection, sql, params)
    finally:
        pool.connections.put_nowait(connection)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "server": "api1c-duckdb",
        "connections": DUCKDB_CONNECTIONS,
        "threads": DUCKDB_THREADS,
        "object_cache": DUCKDB_OBJECT_CACHE,
    }


@app.get("/query")
async def query(
    tenantid: int = Query(..., ge=1, le=1000),
    date_from: str = Query(...),
    date_to: str = Query(...),
):
    """Same aggregate query as api1b /query, including filter and ordering."""
    if not _DATE_RE.match(date_from) or not _DATE_RE.match(date_to):
        return JSONResponse({"error": "date must be YYYY-MM-DD"}, status_code=400)

    sql = f"""
        SELECT dimension1, SUM(value1) AS sum_value1
        FROM read_parquet('{PARQUET_PATH}')
        WHERE tenantid = ?
          AND date >= CAST(? AS DATE)
          AND date <= CAST(? AS DATE)
        GROUP BY dimension1
        ORDER BY dimension1
    """
    rows = await execute(sql, [tenantid, date_from, date_to])
    return JSONResponse({"count": len(rows), "rows": rows})


@app.get("/scan")
async def scan(
    dimension1: str = Query(...),
    limit: int = Query(100, ge=1, le=10000),
):
    """Same full-scan comparison query as api1b /scan."""
    if not _DIM_RE.match(dimension1):
        return JSONResponse({"error": "dimension1 must be alphanumeric"}, status_code=400)

    sql = f"""
        SELECT tenantid, date, dimension1, dimension2, value1
        FROM read_parquet('{PARQUET_PATH}')
        WHERE dimension1 = ?
        LIMIT ?
    """
    rows = await execute(sql, [dimension1, limit])
    return JSONResponse({"count": len(rows), "rows": rows})
