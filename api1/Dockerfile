FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
# 既定は worker=1 (IOバウンドなので非同期なら1プロセスでも十分)。
# ワーカー数は compose の環境変数 UVICORN_WORKERS で上書きして探索する。
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-1}"]
