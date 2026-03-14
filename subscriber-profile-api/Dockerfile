FROM python:3.11-slim

# Non-root user
RUN groupadd -r api && useradd -r -g api api

WORKDIR /app

# Install dependencies first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app/ ./app/

RUN chown -R api:api /app

USER api

# HTTP API port
EXPOSE 8080
# Prometheus metrics port
EXPOSE 9091

CMD ["python", "-m", "app.main"]
