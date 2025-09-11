# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# 系統套件（憑證等）
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 安裝 Python 相依
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# 複製專案原始碼
COPY . .

EXPOSE 8000

# 啟動 FastAPI (用 uvicorn 啟動 backend.logic:app)
CMD ["uvicorn", "backend.logic:app", "--host", "0.0.0.0", "--port", "8000"]
