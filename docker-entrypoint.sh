#!/bin/bash
set -e

echo "Esperando a PostgreSQL..."
for i in $(seq 1 60); do
  if python - <<'PY'
import os, sys
import psycopg2

url = os.environ.get('DATABASE_URL')
if not url:
    host = os.environ.get('DB_HOST', 'db')
    port = os.environ.get('DB_PORT', '5432')
    user = os.environ.get('DB_USER', 'adso')
    password = os.environ.get('DB_PASSWORD', '')
    name = os.environ.get('DB_NAME', 'adso_control')
    url = f'postgresql://{user}:{password}@{host}:{port}/{name}'
try:
    psycopg2.connect(url, connect_timeout=3).close()
except Exception:
    sys.exit(1)
PY
  then
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "PostgreSQL no respondio tras 60 intentos. Abortando." >&2
    exit 1
  fi
  sleep 1
done
echo "PostgreSQL listo."

echo "Aplicando migraciones..."
if ! flask db upgrade; then
  echo "No se pudieron aplicar las migraciones. Se detiene el contenedor para proteger los datos existentes." >&2
  exit 1
fi
echo "Migraciones aplicadas."

echo "Verificando cuenta admin..."
if ! python seed_admin.py; then
  echo "Fallo la creacion del admin. Revise ADSO_ADMIN_EMAIL / ADSO_ADMIN_PASSWORD." >&2
  exit 1
fi

echo "Iniciando servidor..."
exec gunicorn wsgi:app \
  --bind 0.0.0.0:8009 \
  --workers 4 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile - \
  --log-level info
