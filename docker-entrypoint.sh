#!/bin/bash
set -e

# =============================================================================
# docker-entrypoint.sh — Panel de Instructores ADSO
#
# Las variables de entorno llegan directamente desde Coolify UI (o .env local
# en desarrollo). Ya NO se usa DATABASE_URL_B64 ni python3 -c base64 porque
# Docker Compose corrompe los valores que contienen $ al interpolarlos.
#
# Coolify inyecta las variables de forma segura sin pasar por el shell del
# compose, así que DATABASE_URL llega íntegra al contenedor.
# =============================================================================

# --- Construir DATABASE_URL desde partes si no viene completa ---
if [ -z "$DATABASE_URL" ]; then
  DB_HOST="${DB_HOST:-db}"
  DB_PORT="${DB_PORT:-5432}"
  DB_USER="${DB_USER:-adso}"
  DB_NAME="${DB_NAME:-adso_control}"
  if [ -z "$DB_PASSWORD" ]; then
    echo "ERROR: DATABASE_URL y DB_PASSWORD están vacíos. Define al menos uno en Coolify." >&2
    exit 1
  fi
  DATABASE_URL="postgresql+psycopg://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
  export DATABASE_URL
  echo "DATABASE_URL construida desde variables DB_*"
else
  echo "DATABASE_URL recibida directamente desde el entorno."
fi

# --- Esperar PostgreSQL ---
echo "Esperando a PostgreSQL..."
for i in $(seq 1 60); do
  if python3 - <<'PY'
import os, sys
try:
    import psycopg2
    psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=3).close()
except Exception:
    sys.exit(1)
PY
  then
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "PostgreSQL no respondió tras 60 intentos. Abortando." >&2
    exit 1
  fi
  sleep 1
done
echo "PostgreSQL listo."

# --- Migraciones ---
echo "Aplicando migraciones..."
if ! flask db upgrade; then
  echo "No se pudieron aplicar las migraciones. Abortando para proteger los datos." >&2
  exit 1
fi
echo "Migraciones aplicadas."

# --- Seed admin inicial ---
echo "Verificando cuenta admin..."
if ! python3 seed_admin.py; then
  echo "Fallo la creación del admin. Revise ADSO_ADMIN_EMAIL / ADSO_ADMIN_PASSWORD en Coolify." >&2
  exit 1
fi

# --- Arrancar Gunicorn ---
echo "Iniciando servidor Gunicorn en :8009..."
exec gunicorn wsgi:app \
  --bind 0.0.0.0:8009 \
  --workers 4 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile - \
  --log-level info
