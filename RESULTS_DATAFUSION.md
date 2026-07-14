# DataFusion 検証結果レポート (RESULTS_DATAFUSION.md)

API1b(FastAPI + Apache DataFusion) が **MinIO 上の parquet(≈1GB)** を SQL クエリする構成で、
**api1b のメモリ内キャッシュを完全に無効化(毎回 read_parquet 相当で新規読み込み)** した上で、
DataFusion 側の設定によるスループット最大化を k6 で探索した結果。

> 既存の api1/api2(httpx 検証) とは別 compose(`docker-compose.datafusion.yml`, project=`iob-df`)で分離。

---

## 1. 構成

| サービス | 役割 |
|---|---|
| `minio` | S3 互換ストレージ。バケット `data` に `events.parquet` |
| `datagen` | Apache **Spark 3.5.3** で parquet 生成 → MinIO へ |
| `api1b` | FastAPI + **datafusion 43.1.0**。MinIO を object store として SQL クエリ |
| `k6df` | k6 で api1b に負荷 |

- 検証ツール: k6 (Docker)
- api1b は uvicorn **workers=1**(DataFusion が内部でマルチスレッド)

## 2. データ仕様 (generate_parquet.py)

| 項目 | 値 |
|---|---|
| 行数 | 100,000,000 (1億) |
| ファイルサイズ | **995.9 MiB (snappy, 1ファイル)** |
| テナント数 | 1,000 (tenantid 1..1000) → 100,000行/テナント |
| date | 2000-01-01 .. 2026-07-16 |
| dimension1 | ランダム 100 種 / dimension2 | ランダム 1000 種 |
| value1 | ランダム long |
| **ソート** | `orderBy(tenantid, date)` → row group が tenantid/date の範囲をカバー |

## 3. クエリとキャッシュ方針

| path | 内容 |
|---|---|
| `/query` | 単一 `tenantid` + date 範囲 → `GROUP BY dimension1, SUM(value1)` |
| `/scan` | `dimension1` のみ → `LIMIT 100`(row group skip 不可、比較用) |

### メモリ内キャッシュは完全無効
- parquet の事前登録(`register_parquet`)は起動時に行わない。
- **各クエリごとにランダム名テーブルを `register_parquet` し、即 `deregister`** する。
  これにより listing/schema/footer(行グループ統計) を毎回 MinIO から新規取得し、
  DataFusion の内部メタデータキャッシュ効果を完全に排除。
- ※ `read_parquet('...')` SQL テーブル関数は datafusion 43.1.0 で未サポートのため上記方式。

k6 は VU ごとに異なる tenantid(1..1000) を指定(単一テナント検索)。

---

## 4. ベンチ結果 (VUS=50, 20s, キャッシュなし)

### target_partitions (単一テナント /query)

| target_partitions | req/s | p50 (ms) | p95 (ms) | max (ms) | fail |
|---:|---:|---:|---:|---:|---:|
| 1 | 60.3 | 626 | 1549 | 20953 | **39.2%** |
| 2 | 38.4 | 989 | 2111 | 18710 | 0% |
| **4** | **38.6** | **924** | **2058** | 19181 | **0%** |
| 8 | 38.3 | 966 | 2095 | 17431 | 0% |

### pushdown 比較

| 条件 | req/s | p50 (ms) | p95 (ms) |
|---|---:|---:|---:|
| tp4 /query(tenantid+date) | 38.6 | 924 | 2058 |
| tp4 /scan(dimension1, LIMIT100) | 8.5 | 2333 | 15381 |

### 単発レイテンシ(参考, キャッシュなし)

| | #1 | #2 | #3 |
|---|---:|---:|---:|
| /query(tenantid=1) | 191ms | 43ms | 38ms |

---

## 5. 考察と結論

### 5-1. target_partitions は 2 以上(推奨 4)
- **tp1 は fail 39% で不安定**: 単一パーティションのため 50 並列クエリが直列化し、
  k6 タイムアウト(一部 max 20s 超も)を引き起こす。
- **tp2/4/8 は req/s・p50 ともにほぼ同等(38前後 / 924-989ms)**。これ以上並列度を上げても
  単一 parquet(1-2 row group を読む)では頭打ち。

### 5-2. キャッシュなしのオーバーヘッド
- 単発で 38-43ms(2 回目以降)。**事前 register(キャッシュあり)時は 28-30ms** だったので、
  毎回の listing/schema/footer 取得で **+10ms 程度** の固定オーバーヘッド。
- 高負荷(VUS=50)では p50 924ms。クエリ本体より **DataFusion のクエリ実行直列化(CPU 飽和)** が支配的。

### 5-3. pushdown の効果は継続
- `/query`(tenantid+date, row group skip 有効) は **/scan より 4.5 倍高速**(38.6 vs 8.5 req/s)。
  キャッシュを無効化しても **predicate pushdown 自体の効果は崩れない**(統計は parquet footer に格納済みのため毎回読める)。

### 5-4. スループットの律速要因
- 単一 parquet + リモートオブジェクトストアでは **CPU 飽和(VUS 増で p50 急増)** と
  **毎回のメタデータ取得** が律速。target_partitions のチューニング余地は小さい。

---

## 6. 推奨(スループット最大化)

| 観点 | 推奨 |
|---|---|
| DataFusion 設定 | **target_partitions=4**(tp1 は不安定、tp8 まで差は小さい) |
| キャッシュ | 本要件では無効化。実運用でレイテンシ重視なら事前 register_parquet(メタデータキャッシュ)で +10ms 短縮可 |
| **クエリ設計(最重要)** | **selective な条件**(row group skip が効く tenantid/date)が 4.5 倍高速 |
| スケール | CPU 飽和が律速なら api1b の **横スケール(プロセス/コンテナ増)** |

### 一言結論
> キャッシュなし・単一 parquet・単一テナント検索では、**target_partitions=4 以上で安定**するが
> 設定によるスループット差は小さく、**selective なクエリ(row group skip)** と
> **CPU 横スケール** がスループット向上の実効手段。
