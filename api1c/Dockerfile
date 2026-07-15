FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "import duckdb; con = duckdb.connect(); con.execute('INSTALL httpfs'); con.execute('LOAD httpfs')"

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app_duckdb:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
