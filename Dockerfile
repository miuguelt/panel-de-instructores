FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev curl && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -r adso && useradd -r -g adso -d /app -s /bin/false adso

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/gunicorn /usr/local/bin/gunicorn

WORKDIR /app

COPY --chown=adso:adso . .

RUN chmod +x /app/docker-entrypoint.sh && \
    mkdir -p /app/uploads && chown -R adso:adso /app/uploads

ENV FLASK_APP=wsgi.py \
    FLASK_ENV=production \
    PYTHONUNBUFFERED=1

EXPOSE 8009

USER adso

ENTRYPOINT ["/app/docker-entrypoint.sh"]
