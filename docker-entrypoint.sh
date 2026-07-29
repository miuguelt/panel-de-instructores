#!/bin/bash
set -e

# =============================================================================
# docker-entrypoint.sh — Panel de Instructores ADSO
# =============================================================================

# --- Verificar DATABASE_URL obligatoria ---
if [ -z "$DATABASE_URL" ]; then
  echo "ERROR: DATABASE_URL no está definida. Configúrala en Coolify como variable de entorno." >&2
  exit 1
fi
export DATABASE_URL
echo "DATABASE_URL recibida desde el entorno."

# Muestra una versión sanitizada (ocultando la contraseña) para depurar la URL recibida
URL_SANITIZED=$(echo "$DATABASE_URL" | sed -E 's/(:\/\/[^:]+:)[^@]+(@)/\1****\2/')
echo "Probando conexión a base de datos: $URL_SANITIZED"

# --- Debug REDIS_URL: confirma qué llega realmente al contenedor ---
# docker-compose.yml usa pass-through "${REDIS_URL}"; si el valor puesto en
# Coolify contiene '$' (común en passwords generados), Compose lo reinterpreta
# como otra variable y lo vacía/corrompe antes de que Python lo vea. Este log
# es la unica forma de confirmarlo sin exponer la contraseña.
if [ -z "$REDIS_URL" ]; then
  echo "[DEBUG] REDIS_URL: NO DEFINIDA (rate limiter usara memory://)."
else
  REDIS_SANITIZED=$(echo "$REDIS_URL" | sed -E 's/(:\/\/[^:@]*:)[^@]+(@)/\1****\2/')
  echo "[DEBUG] REDIS_URL recibida: $REDIS_SANITIZED"
fi

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
  else
    echo "[Intento $i/60] Error al conectar a PostgreSQL: $ERR_MSG"
  fi
  
  if [ "$i" -eq 60 ]; then
    echo " PostgreSQL no respondió tras 60 intentos. Último error: $ERR_MSG" >&2
    exit 1
  fi
  sleep 2
done
echo "PostgreSQL listo."

# --- Migraciones ---
echo "Aplicando migraciones..."
if ! python3 -m flask db upgrade; then
  echo "No se pudieron aplicar las migraciones. Abortando para proteger los datos." >&2
  exit 1
fi
echo "Migraciones aplicadas."

# --- Seed admin inicial ---
echo "Verificando cuenta admin..."
# Debug: verifica qué DATABASE_URL recibe Python y si existe .env en el contenedor
echo "[DEBUG] DATABASE_URL en shell: $URL_SANITIZED"
echo "[DEBUG] DATABASE_URL en Python: $(python3 -c 'import os; u=os.getenv("DATABASE_URL","NOT_SET"); import re; print(re.sub(r"(://[^:]+:)[^@]+(@)",r"\1****\2",u))')"
echo "[DEBUG] Archivos .env en /app: $(ls /app/.env* 2>/dev/null || echo 'ninguno')"
if ! python3 seed_admin.py; then
  echo "Fallo la creación del admin. Revise ADSO_ADMIN_EMAIL / ADSO_ADMIN_PASSWORD en Coolify." >&2
  exit 1
fi

# --- Arrancar proceso ---
if [ "${PROCESS_TYPE:-web}" = "worker" ]; then
  echo "Iniciando worker de importaciones Excel..."
  exec python3 worker.py
fi

# --- Arrancar Gunicorn ---
# Worker class `gthread`: la app es I/O-bound (PostgreSQL + Redis) y los workers
# `sync` bloquean el proceso entero durante cada query. psycopg2 libera el GIL
# alrededor de libpq y redis-py usa sockets de Python, asi que los hilos si
# solapan I/O. Se descarta gevent porque psycopg2 es una extension C y sin
# psycogreen el hub queda bloqueado igual, sin ganancia y con mas riesgo.
# Concurrencia total = WEB_CONCURRENCY * GUNICORN_THREADS; debe cuadrar con
# DB_POOL_SIZE (ver config.py) y con max_connections de PostgreSQL.
GUNICORN_WORKERS="${WEB_CONCURRENCY:-3}"
GUNICORN_THREADS="${GUNICORN_THREADS:-8}"
echo "Iniciando servidor Gunicorn en :8009 (${GUNICORN_WORKERS} workers x ${GUNICORN_THREADS} hilos, gthread)..."
exec gunicorn wsgi:app \
  --bind 0.0.0.0:8009 \
  --worker-class gthread \
  --workers "$GUNICORN_WORKERS" \
  --threads "$GUNICORN_THREADS" \
  --worker-tmp-dir /dev/shm \
  --timeout 120 \
  --graceful-timeout 30 \
  --keep-alive 5 \
  --access-logfile - \
  --error-logfile - \
  --log-level info
