FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
RUN chmod +x /app/app/management/migrate.sh 2>/dev/null || true
RUN chmod +x /app/app/management/seed.sh 2>/dev/null || true
RUN chmod +x /app/app/management/run.sh 2>/dev/null || true

ENV PYTHONPATH=/app:
