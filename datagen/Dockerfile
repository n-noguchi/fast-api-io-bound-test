FROM apache/spark:3.5.3
USER root

# PySpark 用の python3 は同梱されている。minio SDK だけ追加。
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir minio

COPY generate_parquet.py /opt/generate_parquet.py

# ローカルモードで PySpark を実行。driver に十分なメモリを割り当てる。
ENTRYPOINT ["/opt/spark/bin/spark-submit", \
            "--master", "local[*]", \
            "--driver-memory", "4g", \
            "--conf", "spark.sql.parquet.blockSize=134217728", \
            "/opt/generate_parquet.py"]
