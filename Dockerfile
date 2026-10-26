FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Seed initial database
RUN python3 scripts/seed_database.py

EXPOSE 8000

CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
