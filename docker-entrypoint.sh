#!/bin/bash
set -e

# --- Resolve DATABASE_URL (priority: B64 > FILE > secret > env > parts) ---
# DATABASE_URL_B64 bypasses Docker Compose $ expansion entirely
if [ -n "$DATABASE_URL_B64" ]; then
  DATABASE_URL=$(echo "$DATABASE_URL_B64" | base64 -d 2>/dev/null || python3 -c "import sys,base64; s=sys.argv[1]; s+='='*((4-len(s)%4)%4); print(base64.b64decode(s).decode())" "$DATABASE_URL_B64")
  export DATABASE_URL
elif [ -n "$DATABASE_URL_FILE" ] && [ -f "$DATABASE_URL_FILE" ]; then
  DATABASE_URL=$(cat "$DATABASE_URL_FILE")
  export DATABASE_URL
elif [ -f /run/secrets/DATABASE_URL ]; then
  DATABASE_URL=$(cat /run/secrets/DATABASE_URL)
  export DATABASE_URL
elif [ -f /run/secrets/db_url ]; then
  DATABASE_URL=$(cat /run/secrets/db_url)
  export DATABASE_URL
fi

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
