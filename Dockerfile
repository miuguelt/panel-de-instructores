# ==========================================
# Dockerfile — Panel de Instructores ADSO
# Multi-stage: builder deps → runner final
# ==========================================

# ── Stage 1: Instalar dependencias ────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 2: Imagen final mínima ──────────────────────────
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev curl && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -r adso && useradd -r -g adso -d /app -s /bin/false adso

# Copiar dependencias del stage builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

WORKDIR /app

COPY --chown=adso:adso . .

RUN chmod +x /app/docker-entrypoint.sh && \
    mkdir -p /app/uploads && chown -R adso:adso /app/uploads

ENV FLASK_APP=wsgi.py \
    FLASK_ENV=production \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8009

# Health check: Coolify lo usa para detectar estado del contenedor
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=5 \
    CMD curl -f http://localhost:8009/health || exit 1

USER adso

ENTRYPOINT ["/app/docker-entrypoint.sh"]
