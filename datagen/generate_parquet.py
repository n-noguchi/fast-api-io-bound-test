"""
1GB (程度) の snappy parquet を生成し MinIO へアップロードする (Apache Spark 3.5.3)。

設計:
- 列: tenantid, date, dimension1, dimension2, value1
- tenantid: 1..50000
- date    : 2000-01-01 .. 2026-07-16
- dimension1: 100 種 (cat_00..cat_99) / dimension2: 50 種 (sub_00..sub_49) -> 辞書エンコード
- value1 : ランダム long -> 圧縮されにくく、ファイルサイズの大部分を占める(1GB 調整の主軸)

row group 構成:
- tenantid, date でグローバルソートして 1 ファイル化する。
- これにより各 row group(blockSize=128MB) が tenantid/date の連続範囲をカバーし、
  DataFusion の predicate pushdown が row group 単位で効くようになる。

環境変数:
- NUM_ROWS, TENANT_MAX, MINIO_*
"""
import glob
import os
from datetime import date

from minio import Minio
from pyspark.sql import SparkSession
from pyspark.sql import functions as F


def main() -> None:
    num_rows = int(os.environ.get("NUM_ROWS", "100000000"))
    tenant_max = int(os.environ.get("TENANT_MAX", "50000"))

    endpoint = os.environ["MINIO_ENDPOINT"].replace("http://", "").replace("https://", "")
    access_key = os.environ["MINIO_ACCESS_KEY"]
    secret_key = os.environ["MINIO_SECRET_KEY"]
    bucket = os.environ["MINIO_BUCKET"]
    object_key = os.environ.get("PARQUET_KEY", "events.parquet")

    spark = (
        SparkSession.builder.appName("parquet-gen")
        .master("local[*]")
        .config("spark.driver.memory", "4g")
        .config("spark.sql.parquet.blockSize", "134217728")  # 128MB -> row group 単位
        .config("spark.sql.parquet.compression.codec", "snappy")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    # 2000-01-01 .. 2026-07-16 の日数
    num_days = (date(2026, 7, 16) - date(2000, 1, 1)).days

    df = (
        spark.range(num_rows)
        .withColumn("tenantid", (F.col("id") % F.lit(tenant_max) + 1).cast("int"))
        .withColumn("date", F.expr(f"date_add(date '2000-01-01', cast(id % {num_days} as int))"))
        .withColumn("dimension1", F.concat(F.lit("cat_"), F.lpad((F.floor(F.rand() * 100)).cast("string"), 2, "0")))
        .withColumn("dimension2", F.concat(F.lit("sub_"), F.lpad((F.floor(F.rand() * 1000)).cast("string"), 3, "0")))
        .withColumn("value1", (F.rand() * 1e15).cast("long"))
        .drop("id")
    )

    out_dir = "/tmp/output"
    (
        df.orderBy("tenantid", "date")  # グローバルソート -> row group が tenantid/date 範囲をカバー
        .coalesce(1)                    # 1 ファイル化
        .write.mode("overwrite")
        .option("compression", "snappy")
        .parquet(out_dir)
    )

    files = sorted(glob.glob(f"{out_dir}/part-*.parquet"))
    if not files:
        raise RuntimeError("parquet が生成されませんでした")
    local_path = files[0]
    size = os.path.getsize(local_path)
    print(f"[gen] rows={num_rows} file={local_path} size={size/1024/1024:.1f} MiB", flush=True)

    client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=False)
    client.fput_object(bucket, object_key, local_path)
    print(f"[gen] uploaded s3://{bucket}/{object_key}", flush=True)

    spark.stop()


if __name__ == "__main__":
    main()
