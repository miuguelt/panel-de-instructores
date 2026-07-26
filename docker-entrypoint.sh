#!/bin/bash
# =============================================================================
# docker-entrypoint.sh — Panel de Instructores ADSO
#
# Politica: NUNCA abortar el arranque. Un `exit 1` aqui produce un contenedor
# en bucle de reinicios ("Stopped after reaching restart limit") donde los logs
# se pierden y no hay forma de diagnosticar. En su lugar cada paso reporta el
# error completo y el proceso continua hasta levantar Gunicorn, de modo que
# /health quede accesible y `docker logs` conserve el diagnostico.
#
# Las variables llegan desde Coolify UI -> Environment Variables. El compose usa
# pass-through (sin ${}) para que un "$" dentro de un secreto no sea expandido.
# =============================================================================

DEGRADED=0

fail() {
  DEGRADED=1
  echo "" >&2
  echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
  echo "ERROR DE ARRANQUE: $*" >&2
  echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
  echo "" >&2
}

echo "=============================================================="
echo " Panel de Instructores ADSO — arranque del contenedor"
echo "=============================================================="

# --- Construir DATABASE_URL desde partes si no viene completa ---
if [ -z "$DATABASE_URL" ]; then
  DB_HOST="${DB_HOST:-db}"
  DB_PORT="${DB_PORT:-5432}"
  DB_USER="${DB_USER:-adso}"
  DB_NAME="${DB_NAME:-adso_control}"
  if [ -z "$DB_PASSWORD" ]; then
    fail "DATABASE_URL y DB_PASSWORD estan vacios. Defina al menos uno en Coolify."
  else
    DATABASE_URL="postgresql+psycopg2://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
    export DATABASE_URL
    echo "DATABASE_URL construida desde variables DB_* (host=${DB_HOST}:${DB_PORT} db=${DB_NAME})"
  fi
else
  echo "DATABASE_URL recibida directamente desde el entorno."
fi

# --- Normalizar driver: la imagen solo trae psycopg2-binary ---
case "$DATABASE_URL" in
  postgresql+psycopg://*)
    DATABASE_URL="postgresql+psycopg2://${DATABASE_URL#postgresql+psycopg://}"
    export DATABASE_URL
    echo "Driver normalizado: postgresql+psycopg -> postgresql+psycopg2"
    ;;
esac

# URL sanitizada (sin contrasena) para depurar que llego integra
URL_SANITIZED=$(echo "$DATABASE_URL" | sed -E 's/(:\/\/[^:]+:)[^@]+(@)/\1****\2/')
echo "Cadena de conexion: ${URL_SANITIZED:-<vacia>}"

# --- Verificar secretos corrompidos por la interpolacion de Docker Compose ---
if [ -z "$SECRET_KEY" ]; then
  fail "SECRET_KEY llego vacia. Si el valor contiene el caracter '\$', Docker Compose lo expandio como variable de shell. Genere una clave hexadecimal: python -c \"import secrets; print(secrets.token_hex(64))\""
fi
case "$DATABASE_URL" in
  *:@*|*://:*)
    fail "La contrasena de DATABASE_URL llego vacia: probable expansion de '\$' por Docker Compose. Use una contrasena alfanumerica."
    ;;
esac

# --- Esperar PostgreSQL (sin abortar si no responde) ---
DB_OK=0
echo "Esperando a PostgreSQL..."
for i in $(seq 1 30); do
  ERR_MSG=$(python3 - 2>&1 <<'PY'
import os, sys
try:
    import psycopg2
    url = os.environ.get("DATABASE_URL", "")
    if "+" in url.split("://")[0]:
        driver, rest = url.split("://", 1)
        url = f"{driver.split('+')[0]}://{rest}"
    psycopg2.connect(url, connect_timeout=3).close()
    sys.exit(0)
except Exception as e:
    print(f"{type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(1)
PY
  )
  if [ $? -eq 0 ]; then
    DB_OK=1
    echo "Conexion exitosa a PostgreSQL en el intento $i."
    break
  fi
  echo "[Intento $i/30] Aun esperando a PostgreSQL... Detalle: $ERR_MSG"
  sleep 2
done

if [ "$DB_OK" -ne 1 ]; then
  fail "PostgreSQL no respondio tras 30 intentos. Ultimo error: $ERR_MSG
  Revise en Coolify: DATABASE_URL (o DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME),
  que el contenedor de Postgres este en la misma red 'coolify' y que el host sea
  el nombre del servicio de Postgres, no 'db' ni 'localhost'."
fi

# --- Migraciones (solo si hay BD) ---
if [ "$DB_OK" -eq 1 ]; then
  echo "Aplicando migraciones..."
  if MIG_OUT=$(python3 -m flask db upgrade 2>&1); then
    echo "$MIG_OUT"
    echo "Migraciones aplicadas."
  else
    echo "$MIG_OUT" >&2
    fail "Fallo 'flask db upgrade'. La app arranca igual, pero el esquema puede estar desactualizado."
  fi

  # --- Seed admin inicial ---
  echo "Verificando cuenta admin..."
  if SEED_OUT=$(python3 seed_admin.py 2>&1); then
    echo "$SEED_OUT"
  else
    echo "$SEED_OUT" >&2
    fail "Fallo la creacion del admin. Revise ADSO_ADMIN_EMAIL / ADSO_ADMIN_PASSWORD en Coolify."
  fi
else
  echo "Se omiten migraciones y seed: no hay conexion a la base de datos."
fi

if [ "$DEGRADED" -eq 1 ]; then
  echo ""
  echo "**************************************************************"
  echo "* ARRANQUE EN MODO DEGRADADO                                 *"
  echo "* El servidor se levanta para exponer el diagnostico.        *"
  echo "* Consulte http://<app>/health para ver el detalle en JSON.  *"
  echo "**************************************************************"
  echo ""
fi

# --- Arrancar Gunicorn (siempre) ---
echo "Iniciando servidor Gunicorn en :8009..."
exec gunicorn wsgi:app \
  --bind 0.0.0.0:8009 \
  --workers 4 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile - \
  --log-level info
