# DuckDB 追加検証結果 (RESULTS_DUCKDB.md)

API1c (FastAPI + DuckDB) が、前回の DataFusion 検証と同じ MinIO 上の
`s3://data/events.parquet` を `httpfs` 経由でクエリする追加検証の結果です。

> DataFusion 検証とは API 実装を分離し、`docker-compose.duckdb.yml` の api1c
> だけを `iob-df-net` に参加させて同じ MinIO・同じ parquet を利用した。

---

## 1. 構成

| サービス | 役割 |
|---|---|
| `minio` | S3 互換ストレージ。バケット `data` に `events.parquet` |
| `api1c` | FastAPI + DuckDB 1.1.3。DuckDB `httpfs` で MinIO を直接読む |
| `k6duck` | k6 0.54.0 で api1c に負荷をかける |

- API サーバー: uvicorn workers=1
- DuckDB の同期クエリは `asyncio.to_thread` にオフロードする。
- カーソルプールで同時クエリ数を制限する。各カーソルは同一 DuckDB
  DatabaseInstance を共有するため、設定した object/metadata cache も共有する。

## 2. データ仕様

前回の DataFusion 検証と同じ生成条件で `events.parquet` を再生成した。

| 項目 | 値 |
|---|---|
| 行数 | 100,000,000 |
| ファイルサイズ | **995.9 MiB** (snappy、1ファイル) |
| tenantid | 1..1,000 |
| date | 2000-01-01 .. 2026-07-16 |
| dimension1 / dimension2 | ランダム 100 種 / ランダム 1,000 種 |
| ソート | `orderBy(tenantid, date)`。row group の tenant/date 範囲を絞り込める |

## 3. クエリと測定条件

| path | 内容 |
|---|---|
| `/query` | 単一 `tenantid` と date 範囲で絞り込み、`GROUP BY dimension1` と `SUM(value1)`、ソート |
| `/scan` | `dimension1` のみで絞り込み、`LIMIT 100`。前回と同じ比較用クエリ |

- k6: ramp-up 5秒 → **VUS=50、20秒** → ramp-down 5秒。
- VU ごとに異なる tenantid (1..1000) を `/query` に指定した。
- **`DUCKDB_OBJECT_CACHE=0`**。DuckDB の object/Parquet metadata cache を無効化した。
- 各ケースで api1c を再作成し、初回の httpfs 拡張読み込み・接続初期化・footer
  取得だけを 1 回ウォームアップしてから計測した。OS/MinIO のページキャッシュまでは
  消去していないため、ここでの「キャッシュなし」は DuckDB の object cache を指す。
- 計測日時: 2026-07-15 20:47 JST（結果 JSON 接頭辞: `20260715-204726`）。

---

## 4. ベンチ結果 (VUS=50, 20s, キャッシュなし)

### 接続プール数 (`threads=2`, `/query`)

| connections | req/s | p50 (ms) | p95 (ms) | max (ms) | fail |
|---:|---:|---:|---:|---:|---:|
| **1** | **15.71** | **3066** | **3306** | **3435** | **0%** |
| 2 | 14.92 | 3319 | 3508 | 6439 | 0% |
| 4 | 14.86 | 3289 | 3497 | 4384 | 0% |
| 8 | 15.06 | 3218 | 3545 | 3671 | 0% |

### DuckDB 実行スレッド数 (`connections=4`, `/query`)

| threads | req/s | p50 (ms) | p95 (ms) | max (ms) | fail |
|---:|---:|---:|---:|---:|---:|
| 1 | 15.92 | 3286 | 3512 | 6497 | 6.64% |
| **2** | **14.98** | **3179** | **3575** | **3754** | **0%** |
| 4 | 17.57 | 3212 | 3519 | 3783 | **15.62%** |
| 8 | 17.82 | 3163 | 3465 | 3646 | **15.66%** |

### `/query` と `/scan` の比較

| 条件 | req/s | p50 (ms) | p95 (ms) | fail |
|---|---:|---:|---:|---:|
| `connections=4, threads=2` /query | 14.98 | 3179 | 3575 | 0% |
| `connections=4, threads=2` /scan | **23.06** | **2111** | **2269** | 0% |

### 単発レイテンシ（`connections=4, threads=2`, object cache なし）

api1c を再作成後、同じ `/query?tenantid=1&date_from=2000-01-01&date_to=2026-07-16`
を連続で 3 回呼び出した。

| #1 | #2 | #3 |
|---:|---:|---:|
| 240ms | 156ms | 155ms |

---

## 5. 結果と考察

### 5-1. 最速かつ安定した設定は `connections=1, threads=2`

リモートの単一 parquet を読むクエリは、1 クエリ内でも DuckDB の実行スレッドを使う。
そのため VUS=50 で接続プールを増やしても MinIO 読み込みと CPU が競合し、req/s は
伸びなかった。`connections=1` は待ち行列を API 内に集約し、最良の 15.71 req/s、
p50 3066ms、失敗 0% となった。

この結果に合わせ、アプリケーションと Compose の既定値を
`DUCKDB_CONNECTIONS=1`、`DUCKDB_THREADS=2` にした。CPU コア数・ファイル分割数・
ネットワーク帯域が異なる環境では、`bench_duckdb.sh` で再測定する。

### 5-2. スレッドを 4 以上に増やすのは不適切

`threads=4/8` は成功応答だけを見ると 17.6–17.8 req/s まで増えたが、HTTP 失敗が
15%超となり k6 の 5% 閾値を満たさない。単一ファイル・高 VU でのネストした並列性が
過剰であり、採用対象ではない。`threads=1` も 6.64% 失敗のため、安定設定は
`threads=2` のみだった。

### 5-3. `/scan` が速い理由と pushdown の解釈

この `/scan` は `LIMIT 100` を持つため、ランダムな `dimension1` を十分な数見つけた
時点で DuckDB が早期に読取りを止められる。その結果、`/query` より 1.54 倍の req/s
となった。これは tenant/date predicate pushdown が無効という意味ではなく、
**LIMIT による早期終了を含む別の実行特性**である。

row group skip の純粋な効果を DuckDB で比較するには、`LIMIT` を外して全 row group を
読む比較専用クエリを追加する必要がある。ただし本検証では前回との同等性を優先し、
前回と同じ `/scan` を使った。

### 5-4. キャッシュなしでも単発は 155ms 程度まで低下

初回は 240ms、2 回目以降は 155ms 前後だった。DuckDB object cache は無効でも、
接続確立後の httpfs/HTTP keep-alive、MinIO、OS のキャッシュ効果は残る。これは
キャッシュ有効時の性能値として扱わず、測定条件の限界として明記する。

---

## 6. 推奨設定

| 項目 | 推奨 |
|---|---|
| DuckDB 接続数 | **1**。単一 parquet・VUS=50 では最速かつ失敗 0% |
| DuckDB スレッド数 | **2**。4 以上は失敗率が高い |
| object cache | 比較要件では `0`。実運用でメタデータ再利用が許される場合は `1` も別途測定する |
| データレイアウト | tenant/date でソート済みのまま維持し、row group 統計による絞り込みを使う |
| スケール | 単一ファイルでの同一プロセス内並列化には限界がある。性能が不足する場合は parquet の分割・API の水平スケールを優先する |

### 結論

> 同じ 996MiB の MinIO parquet を DuckDB から直接読む VUS=50 検証では、
> **`connections=1, threads=2, object_cache=0` が最速かつ失敗 0%**だった。
> 単一ファイルに対する接続数・スレッド数の増加はスループットを安定して改善せず、
> 過剰なスレッド並列化は失敗率を悪化させた。
