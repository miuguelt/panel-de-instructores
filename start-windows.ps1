param([switch]$Stop)

$ErrorActionPreference = "Stop"

# Sin este bloque param el script no tenia forma de parar nada: el supervisor
# lo invocaba como `start-windows.ps1 -Stop`, PowerShell ignoraba el argumento
# suelto y el cuerpo arrancaba el servidor en primer plano. `db stop` se quedaba
# colgado para siempre en el paso 1/7 y, de paso, ARRANCABA este proyecto en vez
# de detenerlo (2026-08-16).
function Get-ListeningPidsOnPort($TargetPort) {
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        return @(Get-NetTCPConnection -LocalPort $TargetPort -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique)
    }
    # pwsh 7 no trae el modulo NetTCPIP: sin este respaldo el puerto se lee
    # siempre como libre y la parada seria un falso verde.
    $matchesFound = @(netstat -ano -p tcp 2>$null | Select-String ":$TargetPort\s+\S+\s+LISTENING\s+(\d+)")
    return @($matchesFound | ForEach-Object { [int]$_.Matches.Groups[1].Value } | Select-Object -Unique)
}

if ($Stop) {
    Write-Host "Deteniendo SENA Control Academico (:8009)..." -ForegroundColor Yellow
    $detenidos = 0
    foreach ($ownerPid in (Get-ListeningPidsOnPort 8009)) {
        if ($ownerPid -gt 4) {
            try { Stop-Process -Id $ownerPid -Force -ErrorAction Stop; $detenidos++ } catch {
                Write-Warning "No se pudo detener el proceso $ownerPid."
            }
        }
    }
    Write-Host "Detenido(s): $detenidos proceso(s) en el puerto 8009." -ForegroundColor Green
    return
}

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
    if (Test-Path $wcmInjector) {
        try {
            . $wcmInjector
            Import-ProjectCredentials -Project adso
        } catch {}
    }
} else {
    Write-Verbose "[WARN] PowerShell 7+ requerido para importar credenciales WCM. Usando vars .env por defecto."
}

Write-Host "Limpiando procesos fantasma en el puerto 8009..." -ForegroundColor Yellow
$port = 8009

function Get-PortPids($p) {
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        $conns = Get-NetTCPConnection -LocalPort $p -ErrorAction SilentlyContinue
        if ($conns) { return $conns.OwningProcess | Select-Object -Unique }
    }
    $lines = netstat -ano 2>$null | Select-String ":$p\s+.*LISTENING\s+(\d+)"
    $foundPids = @()
    foreach ($l in $lines) {
        if ($l.Matches.Groups.Count -gt 1) {
            $foundPids += [int]$l.Matches.Groups[1].Value
        }
    }
    return $foundPids | Select-Object -Unique
}

$pidsToKill = Get-PortPids $port
if ($pidsToKill) {
    foreach ($ownPid in $pidsToKill) {
        if ($ownPid -gt 0) {
            Write-Host "Matando proceso $ownPid que ocupa el puerto $port..." -ForegroundColor Red
            try {
                Stop-Process -Id $ownPid -Force -ErrorAction SilentlyContinue
            } catch {
                Write-Warning "No se pudo detener el proceso $ownPid."
            }
        }
    }
    Start-Sleep -Seconds 2
}

Write-Host "=== SENA Control Academico - Inicio ===" -ForegroundColor Green

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectDir

$venvDir = if (Test-Path "venv_win\Scripts\Activate.ps1") { "venv_win" } elseif (Test-Path "venv\Scripts\Activate.ps1") { "venv" } else { "venv" }
if (-not (Test-Path "$venvDir\Scripts\Activate.ps1")) {
    Write-Host "Creando entorno virtual ($venvDir)..." -ForegroundColor Yellow
    python -m venv $venvDir
}

& ".\$venvDir\Scripts\Activate.ps1"

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
