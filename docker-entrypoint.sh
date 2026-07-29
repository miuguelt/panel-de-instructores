#!/bin/bash
set -e

# =============================================================================
# docker-entrypoint.sh — Panel de Instructores ADSO
# =============================================================================

PROCESS_ROLE="${PROCESS_TYPE:-web}"
RUN_MIGRATIONS="${RUN_MIGRATIONS:-true}"
echo "Iniciando proceso '${PROCESS_ROLE}' en contenedor ${HOSTNAME:-desconocido}."

# Resume una URL sin imprimir usuario, password ni query string. Además de ser
# más seguro, permite distinguir inmediatamente PostgreSQL de Redis en Coolify.
url_summary() {
  URL_TO_SUMMARIZE="$1" python3 - <<'PY'
import os
from urllib.parse import urlsplit

raw = (os.environ.get('URL_TO_SUMMARIZE') or '').strip().strip('"').strip("'")
if not raw:
    print('NO_DEFINIDA')
    raise SystemExit
try:
    parsed = urlsplit(raw)
    host = parsed.hostname or 'sin-host'
    port = parsed.port
    if parsed.scheme in ('redis', 'rediss') and port is None:
        port = 6379
    elif parsed.scheme.startswith('postgres') and port is None:
        port = 5432
    destino = f'{parsed.scheme or "sin-scheme"}://{host}:{port or "sin-puerto"}'
    if parsed.path:
        destino += parsed.path
    print(destino)
except Exception as exc:
    print(f'INVALIDA ({type(exc).__name__}: {exc})')
PY
}

# --- Verificar DATABASE_URL obligatoria ---
if [ -z "$DATABASE_URL" ]; then
  echo "ERROR: DATABASE_URL no está definida. Configúrala en Coolify como variable de entorno." >&2
  exit 1
fi
export DATABASE_URL
echo "DATABASE_URL recibida desde el entorno. Destino: $(url_summary "$DATABASE_URL")"

# --- Diagnóstico REDIS_URL sin exponer credenciales ---
if [ -z "$REDIS_URL" ]; then
  echo "[ERROR] REDIS_URL no está definida. El worker no puede procesar importaciones."
else
  echo "REDIS_URL recibida. Destino: $(url_summary "$REDIS_URL")"
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

if [ "$RUN_MIGRATIONS" = "true" ]; then
  # --- Migraciones ---
  echo "Aplicando migraciones desde el proceso '${PROCESS_ROLE}'..."
  if ! python3 -m flask db upgrade; then
    echo "[ERROR] No se pudieron aplicar las migraciones. Abortando para proteger los datos." >&2
    exit 1
  fi
  echo "Migraciones aplicadas."
else
  echo "Migraciones omitidas en el proceso '${PROCESS_ROLE}'; las ejecuta el servicio web."
fi

# --- Seed admin inicial ---
if [ "$PROCESS_ROLE" = "worker" ]; then
  echo "Seed de administrador omitido en el proceso worker."
else
  echo "Verificando cuenta admin..."
  echo "[DEBUG] Destino DATABASE_URL en Python: $(url_summary "$DATABASE_URL")"
  echo "[DEBUG] Archivos .env en /app: $(ls /app/.env* 2>/dev/null || echo 'ninguno')"
  if ! python3 seed_admin.py; then
    echo "[ERROR] Falló la creación del admin. Revise ADSO_ADMIN_EMAIL / ADSO_ADMIN_PASSWORD en Coolify." >&2
    exit 1
  fi
fi

# --- Arrancar proceso ---
if [ "$PROCESS_ROLE" = "worker" ]; then
  echo "Iniciando worker de importaciones Excel con diagnóstico Redis habilitado..."
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
