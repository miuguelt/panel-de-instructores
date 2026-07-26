#!/bin/bash
set -e

# =============================================================================
# docker-entrypoint.sh — Panel de Instructores ADSO
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
  DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
  export DATABASE_URL
  echo "DATABASE_URL construida desde variables DB_*"
else
  echo "DATABASE_URL recibida directamente desde el entorno."
fi

# Muestra una versión sanitizada (ocultando la contraseña) para depurar la URL recibida
URL_SANITIZED=$(echo "$DATABASE_URL" | sed -E 's/(:\/\/[^:]+:)[^@]+(@)/\1****\2/')
echo "Probando conexión a base de datos: $URL_SANITIZED"

# --- Esperar PostgreSQL ---
echo "Esperando a PostgreSQL..."
for i in $(seq 1 60); do
  ERR_MSG=$(python3 - 2>&1 <<'PY'
import os, sys
try:
    import psycopg2
    url = os.environ.get("DATABASE_URL", "")
    if "+" in url.split("://")[0]:
        driver, rest = url.split("://", 1)
        base_scheme = driver.split("+")[0]
        url = f"{base_scheme}://{rest}"
    conn = psycopg2.connect(url, connect_timeout=3)
    conn.close()
    sys.exit(0)
except Exception as e:
    print(f"Error de conexión ({type(e).__name__}): {e}", file=sys.stderr)
    sys.exit(1)
PY
  )
  STATUS=$?
  if [ $STATUS -eq 0 ]; then
    echo " Conexión exitosa a PostgreSQL en el intento $i."
    break
  fi
  
  echo "[Intento $i/60] Aún esperando a PostgreSQL... Detalle: $ERR_MSG"
  
  if [ "$i" -eq 60 ]; then
    echo " PostgreSQL no respondió tras 60 intentos. Último error: $ERR_MSG" >&2
    exit 1
  fi
  sleep 2
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
