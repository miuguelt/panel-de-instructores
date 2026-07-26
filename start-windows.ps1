$ErrorActionPreference = "Stop"

# El reloader de Werkzeug usa watchdog y excluye el entorno virtual,
# uploads, logs y caches desde wsgi.py para evitar reinicios espurios.
Remove-Item Env:WERKZEUG_SERVER_FD -ErrorAction SilentlyContinue
Remove-Item Env:WERKZEUG_RUN_MAIN -ErrorAction SilentlyContinue
# Limpiar vars DevBrain que puedan contaminar la conexion
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:POSTGRES_USER -ErrorAction SilentlyContinue
Remove-Item Env:POSTGRES_PASSWORD -ErrorAction SilentlyContinue
Remove-Item Env:POSTGRES_DB -ErrorAction SilentlyContinue
Remove-Item Env:DEVBRAIN_PG_DSN -ErrorAction SilentlyContinue
Remove-Item Env:PGUSER -ErrorAction SilentlyContinue
Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue

# Inyectar credenciales desde WCM (requiere PowerShell 7+)
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $wcmInjector = "$PSScriptRoot\..\..\_infrastructure\devbraind\scripts\Import-ProjectCredentials.ps1"
    if (Test-Path $wcmInjector) { . $wcmInjector; Import-ProjectCredentials -Project adso }
} else {
    Write-Verbose "[WARN] PowerShell 7+ requerido para importar credenciales WCM. Usando vars .env por defecto."
}

Write-Host "Limpiando procesos fantasma en el puerto 8009..." -ForegroundColor Yellow
$port = 8009
$connections = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
if ($connections) {
    foreach ($conn in $connections) {
        $ownPid = $conn.OwningProcess
        if ($ownPid -gt 0) {
            Write-Host "Matando proceso $ownPid que ocupa el puerto $port..." -ForegroundColor Red
            try {
                Stop-Process -Id $ownPid -Force -ErrorAction Stop
            } catch {
                Write-Warning "No se pudo detener el proceso $ownPid. Puede requerir detener DevBrain o permisos elevados."
            }
        }
    }
    Start-Sleep -Seconds 3
    $remaining = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($remaining) {
        throw "El puerto $port sigue ocupado. Detén el proceso propietario antes de iniciar la aplicación."
    }
}

Write-Host "=== SENA Control Academico - Inicio ===" -ForegroundColor Green

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectDir

if (-not (Test-Path "venv")) {
    Write-Host "Creando entorno virtual..." -ForegroundColor Yellow
    python -m venv venv
}

& ".\venv\Scripts\Activate.ps1"

Write-Host "Instalando dependencias..." -ForegroundColor Yellow
pip install -r requirements.txt -q

Write-Host "Verificando base de datos..." -ForegroundColor Yellow
python -c "
from app import create_app, db
app = create_app()
with app.app_context():
    try:
        db.engine.connect()
        print('Conexion OK')
    except Exception as e:
        print(f'Error BD: {e}')
        print('Creando base de datos...')
"

Write-Host "Aplicando migraciones..." -ForegroundColor Yellow
flask db upgrade
if ($LASTEXITCODE -ne 0) {
    throw "No se pudieron aplicar las migraciones. La aplicación no se iniciará para proteger los datos existentes."
}

Write-Host "Verificando cuenta admin..." -ForegroundColor Yellow
python seed_admin.py
if ($LASTEXITCODE -ne 0) {
    throw "Fallo la verificacion/creacion del admin. Revise ADSO_ADMIN_EMAIL / ADSO_ADMIN_PASSWORD."
}

Write-Host ""
Write-Host "=== Iniciando servidor en http://127.0.0.1:8009 ===" -ForegroundColor Green
python wsgi.py
