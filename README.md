# fast-api-io-bound-test

FastAPI(API1) が Go 製 API2（IO バウンドな 0.5s sleep）を呼び出す構成で、
**API1 の呼び出し方をチューニングして最速化を探る** 実験プロジェクト。
すべて Docker 上で動作し、検証は k6、実行スクリプトは **git bash** 向け。

## 構成

```
api2/   Go(net/http)   /slow は 500ms sleep。goroutine ベースで大量同時接続に耐える。
api1/   FastAPI        API2 を呼ぶプロキシ。5 つの実装パターンを比較可能。
k6/     k6 テスト      k6/results/*.json に結果を出力。
scripts/ git bash 用    run / bench / bench-workers / summarize / down
```

## 対応表

| エンドポイント | API1 の実装 | 特徴 |
|---|---|---|
| `/call/sync-requests` | 同期 `requests` | スレッドプール実行（遅い基準） |
| `/call/sync-httpx` | 同期 `httpx` | 同上 |
| `/call/async-naive` | `httpx.AsyncClient` を都度生成 | keep-alive なし |
| `/call/async-pooled` | 起動時生成した `AsyncClient` を使い回し | 推奨基本形 |
| `/call/async-tuned` | 共有 `AsyncClient` + `Limits` 拡張 | **最速** |

## 使い方（git bash）

```bash
# 1) ビルド & 起動 & ヘルスチェック
./scripts/run.sh

# 2) 5 パターンを k6 で一括ベンチ (結果は k6/results/*.json)
./scripts/bench.sh
#   設定を変える例:
#   VUS=200 DURATION=30s ./scripts/bench.sh
#   ENDPOINTS="/call/async-pooled /call/async-tuned" ./scripts/bench.sh

# 3) 最速パターンで uvicorn ワーカー数(1/2/4)を探索
./scripts/bench-workers.sh

# 4) 結果を Markdown 表に集計 (要 jq)
./scripts/summarize.sh

# 5) 停止
./scripts/down.sh
```

> Windows の git bash では、コンテナ内パス(`/scripts/...`)の自動変換を抑止するため、
> 各スクリプト内で `MSYS_NO_PATHCONV=1` を設定済み。

## ポート

| サービス | ホストポート | パス |
|---|---|---|
| api1 (FastAPI) | 18000 | `/health`, `/call/*` |
| api2 (Go) | 18080 | `/health`, `/slow` |

## 結果

チューニングの探索結果と考察は **[RESULTS.md](./RESULTS.md)** を参照。

---

# 追加検証: DataFusion + MinIO (api1b)

FastAPI + Apache DataFusion で MinIO 上の parquet(≈1GB) をクエリする構成。
既存の httpx 検証とは **別 compose**(`docker-compose.datafusion.yml`, project=`iob-df`)で分離済み。

## 構成

```
api1b/   FastAPI + datafusion  MinIO の parquet を SQL クエリ (app_datafusion.py)
datagen/ Spark 3.5.3           1GB parquet を生成して MinIO へ (generate_parquet.py)
k6/      k6 テスト              test_datafusion.js
```

## 使い方（git bash）

```bash
# 1) MinIO + API1b 起動 & ヘルスチェック
./scripts/run_df.sh

# 2) データ生成(1億行 ≈1GB)。行数は NUM_ROWS で調整可
./scripts/gen_data.sh
#   NUM_ROWS=10000000 ./scripts/gen_data.sh        # サイズ調整用

# 3) チューニング探索ベンチ (target_partitions / metadata_cache / pushdown)
./scripts/bench_df.sh
#   VUS=20 DURATION=20s ./scripts/bench_df.sh
#   DF_TARGET_PARTITIONS_LIST='1 4 8' DF_NO_MC=1 DF_PUSHDOWN=0 ./scripts/bench_df.sh

# 4) 結果集計 (python 使用 / jq 不要)
./scripts/summarize.sh          # 最新スタンプ
./scripts/summarize.sh 20260715-030538   # 指定スタンプ

# 5) 停止
./scripts/down_df.sh
```

## ポート

| サービス | ホストポート | パス |
|---|---|---|
| api1b (DataFusion) | 18001 | `/health`, `/query`, `/scan` |
| minio API | 19000 | S3 互換 |
| minio console | 19001 | (minioadmin / minioadmin) |

## 結果

DataFusion のチューニング探索結果は **[RESULTS_DATAFUSION.md](./RESULTS_DATAFUSION.md)** を参照。

